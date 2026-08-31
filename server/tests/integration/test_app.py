import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from yantra_server.app import create_app
from yantra_server.config import load_config


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("YANTRA_PATHS__DATA_DIR", str(tmp_path / "data"))
    app = create_app(load_config())
    with TestClient(app) as test_client:
        yield test_client


def rpc(ws: Any, method: str, params: dict[str, Any], rid: int = 1) -> dict[str, Any]:
    ws.send_text(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}))
    while True:
        frame = json.loads(ws.receive_text())
        if frame.get("id") == rid:
            return frame


@pytest.mark.integration
def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["db"] == "sqlite"


@pytest.mark.integration
def test_ws_ping_and_session_flow(client: TestClient) -> None:
    with client.websocket_connect("/rpc") as ws:
        pong = rpc(ws, "ping", {})
        assert pong["result"]["pong"] is True

        created = rpc(ws, "session.create", {"workspace": "/tmp/w", "mode": "ask"}, rid=2)
        session_id = created["result"]["session_id"]
        assert session_id

        listed = rpc(ws, "session.list", {}, rid=3)
        assert any(s["session_id"] == session_id for s in listed["result"]["sessions"])

        resumed = rpc(ws, "session.resume", {"session_id": session_id}, rid=4)
        assert resumed["result"]["session"]["workspace"] == "/tmp/w"


@pytest.mark.integration
def test_ws_unknown_method_and_bad_params(client: TestClient) -> None:
    with client.websocket_connect("/rpc") as ws:
        err = rpc(ws, "does.not.exist", {})
        assert err["error"]["code"] == -32601
        bad = rpc(ws, "session.create", {"workspace": 42}, rid=2)
        assert bad["error"]["code"] == -32602


@pytest.mark.integration
def test_api_evals_lists_recorded_runs(client: TestClient) -> None:
    assert client.get("/api/evals").json() == {"eval_runs": []}

    state = client.app.state.yantra  # type: ignore[attr-defined]
    from yantra_server.db.models import EvalResultRow, EvalRunRow

    with state.db.session() as s:
        run = EvalRunRow(suite="pid", profile="mock", status="done", meta={"pass_rate": 1.0})
        s.add(run)
        s.flush()
        s.add(
            EvalResultRow(
                eval_run_id=run.id,
                case_id="pid_3-1201_revC",
                passed=True,
                score=1.0,
                metrics={"planted": 3},
                detail={"detail": "3/3 found"},
            )
        )
    body = client.get("/api/evals").json()
    assert len(body["eval_runs"]) == 1
    row = body["eval_runs"][0]
    assert row["suite"] == "pid" and row["pass_rate"] == 1.0
    assert row["cases"][0]["case_id"] == "pid_3-1201_revC" and row["cases"][0]["passed"]


@pytest.mark.integration
def test_seal_status_and_audit_started(client: TestClient) -> None:
    body = client.get("/api/seal").json()
    assert body["blocked_attempts_total"] == 0
    assert body["allowlist"]

    state = client.app.state.yantra  # type: ignore[attr-defined]
    head = state.audit.head()
    assert head is not None and head.event == "server.start"
    assert state.audit.verify().ok
