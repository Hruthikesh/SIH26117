import pytest

from yantra_server.gateway.engines.base import (
    ChatMessage,
    Constraint,
    EngineChatRequest,
    EngineTimeout,
)
from yantra_server.gateway.engines.mock import (
    MockEngine,
    MockResponse,
    MockScript,
    MockScriptError,
    synthesize_from_schema,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"enum": ["pass", "fail"]},
        "score": {"type": "integer", "minimum": 0},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "score"],
    "additionalProperties": False,
}


def req(
    text: str, constraint: Constraint | None = None, role: str = "executor"
) -> EngineChatRequest:
    return EngineChatRequest(
        model="mock",
        messages=[ChatMessage(role="user", content=text)],
        constraint=constraint,
        meta={"role": role},
    )


async def test_scenario_plays_in_order() -> None:
    engine = MockEngine()
    engine.load_script(
        "s1",
        MockScript(
            responses=[
                MockResponse(text="first"),
                MockResponse(match={"role": "executor"}, text="second"),
            ]
        ),
    )
    engine.use_scenario("s1")
    assert (await engine.chat(req("a"))).content == "first"
    assert (await engine.chat(req("b"))).content == "second"
    assert engine.scenario_exhausted()


async def test_match_guard_mismatch_is_script_error() -> None:
    engine = MockEngine()
    engine.load_script(
        "s1", MockScript(responses=[MockResponse(match={"role": "planner"}, text="x")])
    )
    engine.use_scenario("s1")
    with pytest.raises(MockScriptError):
        await engine.chat(req("hello", role="executor"))


async def test_scripted_json_validated_against_schema() -> None:
    engine = MockEngine()
    constraint = Constraint(kind="json_schema", json_schema=SCHEMA)
    engine.load_script("bad", MockScript(responses=[MockResponse(json={"verdict": "maybe"})]))
    engine.use_scenario("bad")
    with pytest.raises(MockScriptError):
        await engine.chat(req("grade", constraint))

    engine.load_script(
        "good", MockScript(responses=[MockResponse(json={"verdict": "pass", "score": 91})])
    )
    engine.use_scenario("good")
    result = await engine.chat(req("grade", constraint))
    assert '"verdict": "pass"' in result.content


async def test_synthesis_satisfies_schema() -> None:
    import json

    import jsonschema

    engine = MockEngine()
    result = await engine.chat(req("anything", Constraint(kind="json_schema", json_schema=SCHEMA)))
    obj = json.loads(result.content)
    jsonschema.validate(obj, SCHEMA)


async def test_choice_constraint() -> None:
    engine = MockEngine()
    result = await engine.chat(req("pick", Constraint(kind="choice", choices=["yes", "no"])))
    assert result.content == "yes"


async def test_failure_injection_timeout_then_recovery() -> None:
    engine = MockEngine()
    engine.load_script(
        "flaky", MockScript(responses=[MockResponse(fail="timeout"), MockResponse(text="ok")])
    )
    engine.use_scenario("flaky")
    with pytest.raises(EngineTimeout):
        await engine.chat(req("x"))
    assert (await engine.chat(req("x"))).content == "ok"


async def test_malformed_injection_returns_broken_json() -> None:
    engine = MockEngine()
    engine.load_script("m", MockScript(responses=[MockResponse(fail="malformed")]))
    engine.use_scenario("m")
    result = await engine.chat(req("x", Constraint(kind="json_schema", json_schema=SCHEMA)))
    import json

    with pytest.raises(json.JSONDecodeError):
        json.loads(result.content)


async def test_canned_responses_by_role_and_substring() -> None:
    engine = MockEngine()
    engine.add_canned({"text": "canned!"}, role="reviewer", contains="grade this")
    miss = await engine.chat(req("grade this", role="executor"))
    assert miss.content != "canned!"
    hit = await engine.chat(req("please grade this work", role="reviewer"))
    assert hit.content == "canned!"


async def test_deterministic_embeddings_and_rerank() -> None:
    engine = MockEngine()
    v1 = await engine.embed("mock", ["pump seal failure"])
    v2 = await engine.embed("mock", ["pump seal failure"])
    assert v1 == v2 and len(v1[0]) == 32
    scores = await engine.rerank("mock", "pump seal", ["pump seal report", "unrelated text"])
    assert scores[0] > scores[1]


def test_synthesize_nested() -> None:
    schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "n": {"type": "integer"}},
                    "required": ["id", "n"],
                },
            }
        },
        "required": ["tasks"],
    }
    import jsonschema

    jsonschema.validate(synthesize_from_schema(schema), schema)


async def test_streaming_yields_deltas_then_final() -> None:
    from yantra_server.gateway.engines.base import ContentDelta, FinalEvent

    engine = MockEngine()
    events = [e async for e in engine.chat_stream(req("stream me"))]
    assert isinstance(events[-1], FinalEvent)
    text = "".join(e.text for e in events if isinstance(e, ContentDelta))
    assert text == events[-1].result.content


def test_synthesize_honors_simple_patterns() -> None:
    import jsonschema

    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "pattern": "^(ok|alarm)$"}},
        "required": ["status"],
    }
    value = synthesize_from_schema(schema)
    jsonschema.validate(value, schema)
    assert value["status"] == "ok"
