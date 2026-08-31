"""The Engine contract every serving backend implements (SPEC §7.1)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal[
    "planner",
    "executor",
    "reviewer",
    "router",
    "utility",
    "vision",
    "ocr",
    "embed",
    "embed_visual",
    "rerank",
    "rerank_visual",
    "heavy",
]


class EngineError(Exception):
    """Transient or permanent engine failure; the gateway decides on retry."""


class EngineTimeout(EngineError):
    pass


class MalformedOutput(EngineError):
    """The engine produced output violating the requested constraint."""


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    kind: Literal["image"] = "image"
    media_type: str = "image/png"
    data_b64: str | None = None
    path: str | None = None  # resolved to bytes by the gateway before the engine call
    detail: str | None = None


Part = TextPart | ImagePart


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[Part]
    name: str | None = None
    tool_call_id: str | None = None

    def text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return "\n".join(p.text for p in self.content if isinstance(p, TextPart))


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class Constraint(BaseModel):
    """Structured-output constraint; exactly one payload field is used per kind."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["json_schema", "regex", "choice", "grammar"]
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    regex: str | None = None
    choices: list[str] | None = None
    grammar: str | None = None


class Decoding(BaseModel):
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 2048
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    seed: int | None = None
    stop: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prefix_tokens: int = 0
    reasoning_tokens: int = 0


class ToolCallOut(BaseModel):
    id: str = ""
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatResult(BaseModel):
    content: str = ""
    reasoning: str | None = None
    tool_calls: list[ToolCallOut] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    finish_reason: str = "stop"
    ttft_ms: float | None = None
    latency_ms: float = 0.0


class ContentDelta(BaseModel):
    kind: Literal["content"] = "content"
    text: str


class ReasoningDelta(BaseModel):
    kind: Literal["reasoning"] = "reasoning"
    text: str


class FinalEvent(BaseModel):
    kind: Literal["final"] = "final"
    result: ChatResult


ChatEvent = ContentDelta | ReasoningDelta | FinalEvent


class EngineChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    tools: list[ToolSpec] = Field(default_factory=list)
    constraint: Constraint | None = None
    decoding: Decoding = Field(default_factory=Decoding)
    meta: dict[str, Any] = Field(default_factory=dict)  # role, run ids, cache hints


class EngineHealth(BaseModel):
    ok: bool
    detail: str | None = None
    models: list[str] = Field(default_factory=list)


class Capabilities(BaseModel):
    chat: bool = True
    embeddings: bool = False
    rerank: bool = False
    vision: bool = False
    tools: bool = False
    structured: bool = False


class Engine(ABC):
    """Async serving backend. `chat` drains `chat_stream` unless overridden."""

    name: str = "engine"

    @abstractmethod
    def chat_stream(self, request: EngineChatRequest) -> AsyncIterator[ChatEvent]: ...

    async def chat(self, request: EngineChatRequest) -> ChatResult:
        result: ChatResult | None = None
        async for event in self.chat_stream(request):
            if isinstance(event, FinalEvent):
                result = event.result
        if result is None:
            raise EngineError(f"{self.name}: stream ended without a final result")
        return result

    async def embed(
        self, model: str, texts: list[str], instruction: str | None = None
    ) -> list[list[float]]:
        raise EngineError(f"{self.name}: embeddings not supported")

    async def rerank(self, model: str, query: str, documents: list[str]) -> list[float]:
        raise EngineError(f"{self.name}: reranking not supported")

    @abstractmethod
    async def health(self) -> EngineHealth: ...

    @abstractmethod
    def capabilities(self) -> Capabilities: ...
