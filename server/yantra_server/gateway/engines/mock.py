"""Deterministic, scriptable engine for tests and GPU-less development (SPEC §7.1).

Three resolution layers per call, first hit wins:
1. the active scenario script (ordered responses, optional per-entry match guards),
2. canned responses registered by (role, substring-of-last-user-message),
3. deterministic synthesis: a schema-valid instance for constrained calls, an echo otherwise.

Scripted JSON responses are validated against the request's schema so a harness test cannot
accidentally pass on output a real constrained engine could never produce.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from typing import Any, Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field

from .base import (
    Capabilities,
    ChatEvent,
    ChatResult,
    ContentDelta,
    Engine,
    EngineChatRequest,
    EngineError,
    EngineHealth,
    EngineTimeout,
    FinalEvent,
    ToolCallOut,
    Usage,
)


class MockScriptError(AssertionError):
    """A test script is inconsistent (e.g. scripted output violates the schema)."""


class MockResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    match: dict[str, str] | None = None  # {"role": ..., "contains": ..., "regex": ...}
    text: str | None = None
    json_obj: Any | None = Field(default=None, alias="json")
    tool_call: dict[str, Any] | None = None
    fail: Literal["timeout", "malformed", "error"] | None = None
    delay_ms: int = 0
    skip_validation: bool = False  # for tests that deliberately script invalid output


class MockScript(BaseModel):
    responses: list[MockResponse] = Field(default_factory=list)


def synthesize_from_schema(schema: dict[str, Any], depth: int = 0) -> Any:
    """Produce a deterministic instance satisfying a JSON schema (required fields only)."""
    if depth > 12:
        return None
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    for combinator in ("oneOf", "anyOf", "allOf"):
        if schema.get(combinator):
            if combinator == "allOf":
                merged: dict[str, Any] = {}
                for sub in schema[combinator]:
                    merged.update(sub)
                return synthesize_from_schema(merged, depth + 1)
            return synthesize_from_schema(schema[combinator][0], depth + 1)
    if "$ref" in schema:
        return None  # refs are resolved by callers passing dereferenced schemas
    stype = schema.get("type")
    if isinstance(stype, list):
        stype = stype[0]
    if stype == "object" or (stype is None and "properties" in schema):
        props = schema.get("properties", {})
        required = schema.get("required", list(props.keys()))
        return {k: synthesize_from_schema(props.get(k, {}), depth + 1) for k in required}
    if stype == "array":
        min_items = schema.get("minItems", 0)
        if min_items <= 0:
            return []
        item = synthesize_from_schema(schema.get("items", {}), depth + 1)
        return [item] * min_items
    if stype == "string":
        value = "mock"
        if pattern := schema.get("pattern"):
            literal = _literal_from_pattern(str(pattern))
            if literal is not None:
                return literal
        max_len = schema.get("maxLength")
        min_len = schema.get("minLength", 0)
        if min_len > len(value):
            value = value.ljust(min_len, "x")
        if max_len is not None:
            value = value[:max_len]
        return value
    if stype == "integer":
        return int(schema.get("minimum", 0))
    if stype == "number":
        return float(schema.get("minimum", 0.0))
    if stype == "boolean":
        return True
    if stype == "null":
        return None
    return "mock"


def _literal_from_pattern(pattern: str) -> str | None:
    """Derive a matching string from a simple pattern (alternations, \\d/\\w quantifiers)."""
    inner = pattern.strip("^$")
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    first = inner.split("|")[0]
    if first and re.fullmatch(r"[A-Za-z0-9_. -]+", first) and re.fullmatch(pattern, first):
        return first
    # Naive derivation: collapse common quantified classes to one representative char.
    candidate = first
    for cls_pattern, repl in (
        (r"\\d(\{\d+(,\d+)?\}|[+*]?)", "1"),
        (r"\\w(\{\d+(,\d+)?\}|[+*]?)", "a"),
    ):
        candidate = re.sub(cls_pattern, repl, candidate)
    candidate = re.sub(r"\[([A-Za-z0-9])[^\]]*\](\{\d+(,\d+)?\}|[+*]?)", r"\1", candidate)
    try:
        if candidate and re.fullmatch(pattern, candidate):
            return candidate
    except re.error:
        return None
    return None


class MockEngine(Engine):
    name = "mock"

    def __init__(self, scripts: dict[str, MockScript] | None = None) -> None:
        self.scripts: dict[str, MockScript] = scripts or {}
        self._scenario: str | None = None
        self._cursor = 0
        self._canned: list[tuple[str | None, str, MockResponse]] = []
        self._sequences: list[tuple[str | None, str, list[MockResponse]]] = []
        self.calls: list[EngineChatRequest] = []  # inspection hook for tests

    # ---------------------------------------------------------------- scripting API

    def load_script(self, name: str, script: MockScript | dict[str, Any]) -> None:
        self.scripts[name] = (
            script if isinstance(script, MockScript) else MockScript.model_validate(script)
        )

    def use_scenario(self, name: str | None) -> None:
        if name is not None and name not in self.scripts:
            raise MockScriptError(f"unknown scenario {name!r}")
        self._scenario = name
        self._cursor = 0

    def reset(self) -> None:
        """Clear all scripted, canned and sequenced responses (fresh scenario setup)."""
        self._scenario = None
        self._cursor = 0
        self._canned.clear()
        self._sequences.clear()
        self.calls.clear()

    def add_canned(
        self,
        response: MockResponse | dict[str, Any],
        *,
        role: str | None = None,
        contains: str = "",
    ) -> None:
        resp = (
            response
            if isinstance(response, MockResponse)
            else MockResponse.model_validate(response)
        )
        self._canned.append((role, contains, resp))

    def add_canned_sequence(
        self,
        responses: list[MockResponse | dict[str, Any]],
        *,
        role: str | None = None,
        contains: str = "",
    ) -> None:
        """Ordered responses consumed one per matching call; falls through when exhausted."""
        parsed = [
            r if isinstance(r, MockResponse) else MockResponse.model_validate(r) for r in responses
        ]
        self._sequences.append((role, contains, parsed))

    def scenario_exhausted(self) -> bool:
        if self._scenario is None:
            return True
        return self._cursor >= len(self.scripts[self._scenario].responses)

    # ---------------------------------------------------------------- resolution

    def _last_user_text(self, request: EngineChatRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.text()
        return ""

    def _matches(self, guard: dict[str, str] | None, request: EngineChatRequest) -> bool:
        if not guard:
            return True
        role = str(request.meta.get("role", ""))
        text = self._last_user_text(request)
        if "role" in guard and guard["role"] != role:
            return False
        if "contains" in guard and guard["contains"] not in text:
            return False
        return not ("regex" in guard and not re.search(guard["regex"], text, re.DOTALL))

    def _next_response(self, request: EngineChatRequest) -> MockResponse | None:
        if self._scenario is not None:
            script = self.scripts[self._scenario]
            if self._cursor < len(script.responses):
                candidate = script.responses[self._cursor]
                if not self._matches(candidate.match, request):
                    raise MockScriptError(
                        f"scenario {self._scenario!r} step {self._cursor}: match guard "
                        f"{candidate.match} does not match request "
                        f"(role={request.meta.get('role')!r}, "
                        f"last_user={self._last_user_text(request)[:120]!r})"
                    )
                self._cursor += 1
                return candidate
        role = str(request.meta.get("role", ""))
        text = self._last_user_text(request)
        for want_role, contains, queue in self._sequences:
            if want_role is not None and want_role != role:
                continue
            if contains and contains not in text:
                continue
            if queue:
                return queue.pop(0)
        for want_role, contains, resp in self._canned:
            if want_role is not None and want_role != role:
                continue
            if contains and contains not in text:
                continue
            return resp
        return None

    def _synthesize(self, request: EngineChatRequest) -> MockResponse:
        constraint = request.constraint
        if constraint is None:
            digest = hashlib.sha256(self._last_user_text(request).encode()).hexdigest()[:8]
            return MockResponse(text=f"mock response {digest}")
        if constraint.kind == "choice":
            choices = constraint.choices or ["mock"]
            return MockResponse(text=choices[0])
        if constraint.kind == "json_schema" and constraint.json_schema is not None:
            return MockResponse(json=synthesize_from_schema(constraint.json_schema))
        if constraint.kind == "regex":
            return MockResponse(text="mock", skip_validation=True)
        return MockResponse(text="mock", skip_validation=True)

    def _render(self, request: EngineChatRequest, resp: MockResponse) -> ChatResult:
        if resp.fail == "timeout":
            raise EngineTimeout("mock: scripted timeout")
        if resp.fail == "error":
            raise EngineError("mock: scripted engine error")
        if resp.fail == "malformed":
            return self._result(request, '{"broken": ')
        if resp.tool_call is not None:
            call = ToolCallOut.model_validate(resp.tool_call)
            return self._result(request, "", tool_calls=[call])
        if resp.json_obj is not None:
            constraint = request.constraint
            if (
                constraint is not None
                and constraint.kind == "json_schema"
                and constraint.json_schema is not None
                and not resp.skip_validation
            ):
                try:
                    jsonschema.validate(resp.json_obj, constraint.json_schema)
                except jsonschema.ValidationError as exc:
                    raise MockScriptError(
                        f"scripted JSON violates the request schema: {exc.message}"
                    ) from exc
            return self._result(request, json.dumps(resp.json_obj, ensure_ascii=False))
        text = resp.text if resp.text is not None else "mock"
        constraint = request.constraint
        if (
            constraint is not None
            and constraint.kind == "choice"
            and constraint.choices
            and not resp.skip_validation
            and text not in constraint.choices
        ):
            raise MockScriptError(f"scripted choice {text!r} not in {constraint.choices}")
        return self._result(request, text)

    def _result(
        self, request: EngineChatRequest, content: str, tool_calls: list[ToolCallOut] | None = None
    ) -> ChatResult:
        prompt_tokens = sum(len(m.text()) // 4 + 1 for m in request.messages)
        return ChatResult(
            content=content,
            tool_calls=tool_calls or [],
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=len(content) // 4 + 1),
            model=request.model,
            finish_reason="tool_call" if tool_calls else "stop",
            ttft_ms=1.0,
            latency_ms=2.0,
        )

    # ---------------------------------------------------------------- Engine API

    async def chat_stream(self, request: EngineChatRequest) -> AsyncIterator[ChatEvent]:
        self.calls.append(request)
        resp = self._next_response(request) or self._synthesize(request)
        if resp.delay_ms:
            await asyncio.sleep(resp.delay_ms / 1000)
        result = self._render(request, resp)
        if result.content:
            midpoint = max(1, len(result.content) // 2)
            yield ContentDelta(text=result.content[:midpoint])
            yield ContentDelta(text=result.content[midpoint:])
        yield FinalEvent(result=result)

    async def embed(
        self, model: str, texts: list[str], instruction: str | None = None
    ) -> list[list[float]]:
        """Deterministic 32-d pseudo-embeddings: stable across runs, similar for equal text."""
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vectors.append([b / 255.0 - 0.5 for b in digest])
        return vectors

    async def rerank(self, model: str, query: str, documents: list[str]) -> list[float]:
        query_terms = set(query.lower().split())
        scores: list[float] = []
        for doc in documents:
            doc_terms = set(doc.lower().split())
            overlap = len(query_terms & doc_terms)
            scores.append(overlap / (len(query_terms) or 1))
        return scores

    async def health(self) -> EngineHealth:
        return EngineHealth(ok=True, models=["mock"])

    def capabilities(self) -> Capabilities:
        return Capabilities(
            chat=True, embeddings=True, rerank=True, vision=True, tools=True, structured=True
        )
