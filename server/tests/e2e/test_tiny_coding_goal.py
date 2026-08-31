"""M3 DoD e2e: a small coding goal executed end-to-end by a real tiny GGUF model.

Needs `llama-server` on PATH and a tiny instruct GGUF in $YANTRA_TINY_MODELS_DIR.
The tiny model plans/executes/reviews through the same harness the demo uses; thresholds
are relaxed (tiny models are weak) — the assertion is that the HARNESS carries a real model
through plan → constrained steps → verification, not that a 0.8B model codes well.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

BINARY = shutil.which("llama-server")
MODELS_DIR = os.environ.get("YANTRA_TINY_MODELS_DIR", "")


def _tiny_model() -> Path | None:
    if not MODELS_DIR:
        return None
    root = Path(MODELS_DIR).expanduser()
    ggufs = sorted(root.glob("*.gguf"), key=lambda p: p.stat().st_size) if root.is_dir() else []
    return ggufs[0] if ggufs else None


requires_tiny = pytest.mark.skipif(
    BINARY is None or _tiny_model() is None,
    reason="needs llama-server + a tiny GGUF in $YANTRA_TINY_MODELS_DIR",
)


@requires_tiny
async def test_three_task_coding_goal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANTRA_SEALED", "0")
    from tests.helpers import make_state
    from yantra_server.gateway.profile_spec import EngineSpec, ProfileSpec
    from yantra_server.gateway.registry import ModelManifest
    from yantra_server.gateway.supervisor import Supervisor

    state = make_state()
    tiny = _tiny_model()
    assert tiny is not None
    manifest = ModelManifest(
        id="tiny-e2e",
        path=str(tiny),
        engine="llamacpp",
        params_b=1.0,
        capabilities=["chat", "json"],
        context_len=8192,
        serve_context_len=4096,
        roles=["planner", "executor", "reviewer", "router", "utility", "heavy", "vision"],
    )
    state.registry.register(manifest)
    for role_list in state.router.policy.roles.values():
        role_list.insert(0, "tiny-e2e")
    profile = ProfileSpec(
        name="tiny-e2e",
        engines=[EngineSpec(id="tiny", kind="llamacpp", model="tiny-e2e", ctx=4096)],
    )
    state.supervisor = Supervisor(state.config, state.registry, profile)
    state.gateway.supervisor = state.supervisor
    state.router.is_available = state.supervisor.model_available

    state.bus.bind_loop(asyncio.get_running_loop())
    await state.supervisor.start_all()
    try:
        deadline = asyncio.get_running_loop().time() + 180
        while asyncio.get_running_loop().time() < deadline:
            await state.supervisor.check_health_once()
            if state.supervisor.model_available("tiny-e2e"):
                break
            await asyncio.sleep(3)
        assert state.supervisor.model_available("tiny-e2e"), "tiny model never became healthy"

        workspace = tmp_path / "ws"
        workspace.mkdir()
        from yantra_server.db.models import RunRow, SessionRow

        with state.db.session() as s:
            session = SessionRow(workspace_path=str(workspace), collections=[], mode="auto")
            s.add(session)
            s.flush()
            session_id = session.id
        run_id = await state.conductor.start_run(
            session_id,
            "Create add.py containing a function add(a, b) returning a+b, and test_add.py "
            "with a pytest test for it; run the tests.",
            [],
            "auto",
        )
        await state.conductor.wait_for_run(run_id, timeout_s=900)
        with state.db.session() as s:
            run = s.get(RunRow, run_id)
            assert run is not None
            # The harness must land in a terminal state with persisted plan + steps.
            assert run.status in ("done", "done_with_gaps", "failed")
            assert run.plan is not None
        if (workspace / "add.py").exists():
            assert "def add" in (workspace / "add.py").read_text()
    finally:
        await state.supervisor.stop_all()
