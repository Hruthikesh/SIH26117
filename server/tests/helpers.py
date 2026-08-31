"""Test helpers: a fully wired AppState + ToolContext on the mock profile."""

from __future__ import annotations

from pathlib import Path

from yantra_server.app import build_state
from yantra_server.config import load_config
from yantra_server.sandbox.base import SandboxLimits
from yantra_server.sandbox.local import LocalSandbox
from yantra_server.state import AppState
from yantra_server.tools.base import ToolContext


def make_state(profile: str = "mock") -> AppState:
    """Wired AppState; relies on the autouse env fixture for an isolated data dir."""
    return build_state(load_config(cli_overrides={"profile": profile}))


def make_ctx(
    state: AppState,
    workspace: Path,
    *,
    mode: str = "auto",
    run_id: str = "run-test",
    idempotency_key: str = "",
) -> ToolContext:
    workspace.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        workspace=workspace,
        state=state,
        sandbox=LocalSandbox(workspace, SandboxLimits(timeout_s=30)),
        mode=mode,
        run_id=run_id,
        task_id="task-test",
        step_id="step-test",
        idempotency_key=idempotency_key,
    )
