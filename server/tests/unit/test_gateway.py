from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel

from yantra_server.artifacts import ArtifactStore
from yantra_server.conductor.budgets import BudgetTracker
from yantra_server.config import load_config
from yantra_server.db.base import Database
from yantra_server.gateway.engines.base import (
    ChatMessage,
    Constraint,
    Decoding,
    EngineError,
    MalformedOutput,
)
from yantra_server.gateway.engines.mock import MockEngine, MockResponse, MockScript
from yantra_server.gateway.registry import ModelManifest, ModelRegistry
from yantra_server.gateway.router import Router, RoutingPolicy
from yantra_server.gateway.service import Gateway, ModelRequest
from yantra_server.gateway.supervisor import Supervisor


class FakeSupervisor:
    """Serves one MockEngine for every model id."""

    def __init__(self) -> None:
        self.engine = MockEngine()

    def model_available(self, model_id: str) -> bool:
        return True

    async def engine_for_model(self, model_id: str) -> MockEngine:
        return self.engine


class Verdict(BaseModel):
    verdict: str
    score: int


POLICY = RoutingPolicy.model_validate(
    {"roles": {"executor": ["mock"], "utility": ["mock"], "embed": ["mock"], "rerank": ["mock"]}}
)


@pytest.fixture
def gateway(db: Database, artifacts: ArtifactStore, tmp_path: Path, tracing: None) -> Gateway:
    registry = ModelRegistry(tmp_path / "reg.yaml", tmp_path)
    registry.register(
        ModelManifest(
            id="mock",
            path="-",
            engine="mock",
            params_b=0,
            capabilities=["chat", "json", "vision", "embed", "rerank"],
            serve_context_len=10**6,
        )
    )
    fake = FakeSupervisor()
    router = Router(POLICY, registry, fake.model_available, allow_mock=True)
    loaded = load_config()
    gw = Gateway(loaded.config, db, artifacts, router, cast(Supervisor, fake), max_concurrent=4)
    gw.mock = fake.engine  # type: ignore[attr-defined]
    return gw


def mock_of(gateway: Gateway) -> MockEngine:
    return gateway.mock  # type: ignore[attr-defined]


def req(text: str = "hello", **kw: object) -> ModelRequest:
    return ModelRequest(
        role="executor",
        messages=[ChatMessage(role="user", content=text)],
        **kw,  # type: ignore[arg-type]
    )


async def test_chat_span_and_router_decision(gateway: Gateway, db: Database) -> None:
    from sqlalchemy import select

    from yantra_server.db.models import RouterDecisionRow, SpanRow
    from yantra_server.observe.tracing import force_flush

    result = await gateway.chat(req("what is a pump?"))
    assert result.result.content
    force_flush()
    with db.session() as s:
        spans = [r for r in s.execute(select(SpanRow)).scalars() if r.kind == "llm.call"]
        assert spans and spans[0].attrs["model"] == "mock"
        assert "prompt_artifact" in spans[0].attrs
        decisions = list(s.execute(select(RouterDecisionRow)).scalars())
        assert decisions and decisions[0].chosen == "mock"


async def test_response_cache_hit_on_identical_call(gateway: Gateway) -> None:
    first = await gateway.chat(req("cache me"))
    assert first.cached is False
    second = await gateway.chat(req("cache me"))
    assert second.cached is True
    assert second.result.content == first.result.content
    assert len(mock_of(gateway).calls) == 1  # engine hit exactly once


async def test_sampling_not_cached(gateway: Gateway) -> None:
    dec = Decoding(temperature=0.8)
    await gateway.chat(req("sample", decoding=dec))
    await gateway.chat(req("sample", decoding=dec))
    assert len(mock_of(gateway).calls) == 2


async def test_transient_engine_error_retried(gateway: Gateway) -> None:
    engine = mock_of(gateway)
    engine.load_script(
        "flaky", MockScript(responses=[MockResponse(fail="error"), MockResponse(text="recovered")])
    )
    engine.use_scenario("flaky")
    result = await gateway.chat(req("try me"))
    assert result.result.content == "recovered"
    assert result.attempts == 2


async def test_malformed_then_tightened_retry_succeeds(gateway: Gateway) -> None:
    engine = mock_of(gateway)
    schema_constraint = Constraint(
        kind="json_schema",
        json_schema={
            "type": "object",
            "properties": {"verdict": {"type": "string"}, "score": {"type": "integer"}},
            "required": ["verdict", "score"],
        },
    )
    engine.load_script(
        "m",
        MockScript(
            responses=[
                MockResponse(fail="malformed"),
                MockResponse(json={"verdict": "pass", "score": 9}),
            ]
        ),
    )
    engine.use_scenario("m")
    result = await gateway.chat(req("grade", constraint=schema_constraint))
    assert result.parsed == {"verdict": "pass", "score": 9}
    # The retry carried a tightened schema:
    second_call = engine.calls[-1]
    assert second_call.constraint is not None
    assert second_call.constraint.json_schema is not None
    assert second_call.constraint.json_schema.get("additionalProperties") is False


async def test_double_malformed_raises(gateway: Gateway) -> None:
    engine = mock_of(gateway)
    constraint = Constraint(
        kind="json_schema",
        json_schema={"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]},
    )
    engine.load_script(
        "mm", MockScript(responses=[MockResponse(fail="malformed"), MockResponse(fail="malformed")])
    )
    engine.use_scenario("mm")
    with pytest.raises(MalformedOutput):
        await gateway.chat(req("grade", constraint=constraint))


async def test_exhausted_retries_raise(gateway: Gateway) -> None:
    engine = mock_of(gateway)
    engine.load_script(
        "dead",
        MockScript(responses=[MockResponse(fail="error")] * 8),
    )
    engine.use_scenario("dead")
    with pytest.raises(EngineError):
        await gateway.chat(req("doomed"))


async def test_budget_accounting(gateway: Gateway) -> None:
    budget = BudgetTracker(max_tokens=100_000)
    await gateway.chat(req("count my tokens", budget=budget))
    assert budget.tokens_used > 0


async def test_schema_model_parsing(gateway: Gateway) -> None:
    engine = mock_of(gateway)
    engine.load_script(
        "v", MockScript(responses=[MockResponse(json={"verdict": "pass", "score": 88})])
    )
    engine.use_scenario("v")
    result = await gateway.chat(req("grade this", schema_model=Verdict))
    assert isinstance(result.parsed, Verdict)
    assert result.parsed.score == 88


async def test_embed_cache(gateway: Gateway) -> None:
    v1 = await gateway.embed(["alpha", "beta"])
    v2 = await gateway.embed(["alpha", "beta"])
    assert v1 == v2
    assert len(v1) == 2 and len(v1[0]) == 32


async def test_rerank(gateway: Gateway) -> None:
    scores = await gateway.rerank("pump seal", ["pump seal doc", "cats"])
    assert scores[0] > scores[1]


async def test_classify_choice(gateway: Gateway) -> None:
    label = await gateway.classify(
        "extract pump data",
        ["trivial", "easy", "normal", "hard", "extreme"],
        instruction="Classify difficulty.",
    )
    assert label in {"trivial", "easy", "normal", "hard", "extreme"}


async def test_force_model_bypasses_router(gateway: Gateway) -> None:
    result = await gateway.chat(req("probe", force_model="mock"))
    assert result.decision.reason == "forced (probe/bench)"
