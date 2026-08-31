import pytest

from yantra_server.protocol import NOTIFICATIONS, REQUESTS
from yantra_server.protocol.export import protocol_schemas
from yantra_server.protocol.jsonrpc import (
    INVALID_REQUEST,
    PARSE_ERROR,
    RpcError,
    error_frame,
    notification_frame,
    parse_request,
    result_frame,
)
from yantra_server.protocol.messages import AssistantDelta, SessionCreateParams


def test_parse_valid_request() -> None:
    rid, method, params = parse_request(
        '{"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}}'
    )
    assert rid == 7 and method == "ping" and params == {}


def test_parse_errors() -> None:
    with pytest.raises(RpcError) as exc:
        parse_request("{nope")
    assert exc.value.code == PARSE_ERROR
    with pytest.raises(RpcError) as exc:
        parse_request('{"jsonrpc": "1.0", "method": "x"}')
    assert exc.value.code == INVALID_REQUEST


def test_frames() -> None:
    assert result_frame(1, {"ok": True})["result"] == {"ok": True}
    err = error_frame(2, -32601, "nope")
    assert err["error"]["code"] == -32601
    note = notification_frame("assistant.delta", {"text": "hi", "seq": 1})
    assert note["method"] == "assistant.delta" and "id" not in note


def test_all_spec_methods_registered() -> None:
    for method in [
        "session.create",
        "session.prompt",
        "run.cancel",
        "run.approve",
        "run.plan.update",
        "session.list",
        "session.resume",
        "session.fork",
        "models.list",
        "rag.search",
        "seal.status",
        "trace.get",
        "config.get",
        "memory.list",
        "skills.list",
    ]:
        assert method in REQUESTS, method
    for method in [
        "assistant.delta",
        "thinking.delta",
        "plan.updated",
        "task.updated",
        "tool.started",
        "tool.output.delta",
        "tool.finished",
        "verify.result",
        "escalation",
        "permission.request",
        "question",
        "image",
        "seal.event",
        "budget.warning",
        "run.finished",
        "error",
    ]:
        assert method in NOTIFICATIONS, method


def test_notifications_carry_run_id_and_seq() -> None:
    note = AssistantDelta(run_id="r1", text="hello")
    dumped = note.model_dump()
    assert dumped["run_id"] == "r1" and "seq" in dumped


def test_params_validate() -> None:
    params = SessionCreateParams.model_validate({"workspace": "/tmp/w"})
    assert params.mode == "ask" and params.collections == []


def test_protocol_schemas_complete() -> None:
    schemas = protocol_schemas()
    assert set(schemas["requests"]) == set(REQUESTS)
    assert set(schemas["notifications"]) == set(NOTIFICATIONS)
    for entry in schemas["requests"].values():
        assert entry["params"]["$ref"].startswith("#/$defs/")
