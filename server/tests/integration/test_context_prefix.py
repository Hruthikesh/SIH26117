"""M11 performance DoD: executor prompts keep a ≥70% stable prefix across steps.

vLLM's prefix cache hits on the longest common token prefix of consecutive prompts; the
context builder (SPEC §8.7/§8.10) puts persona/rules/tools/task-card first so only the
step tail changes. Measured here on real assembled prompts from a scripted multi-step run.
"""

from __future__ import annotations

import asyncio
import itertools

import pytest

from tests.helpers import make_state
from yantra_server.db.models import SessionRow
from yantra_server.evals.scenarios import ScenarioContext, setup_scenario
from yantra_server.gateway.engines.base import EngineChatRequest

pytestmark = pytest.mark.integration


def _prompt_text(request: EngineChatRequest) -> str:
    return "\x1e".join(f"{m.role}\x1f{m.text()}" for m in request.messages)


def _task_of(request: EngineChatRequest) -> str | None:
    text = _prompt_text(request)
    marker = text.find("Task t")
    if marker == -1:
        return None
    return text[marker : marker + 12]


def _common_prefix_ratio(prev: str, cur: str) -> float:
    limit = min(len(prev), len(cur))
    i = 0
    while i < limit and prev[i] == cur[i]:
        i += 1
    return i / max(len(prev), 1)


async def test_executor_prefix_stability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANTRA_SEALED", "0")
    state = make_state()
    state.bus.bind_loop(asyncio.get_running_loop())
    await state.supervisor.start_all()
    try:
        mock = state.supervisor.processes[0].engine
        base = state.loaded.assets_dir / "corpus" / "generated" / "small"
        if not (base / "docs").is_dir():
            import sys

            sys.path.insert(0, str(state.loaded.assets_dir))
            from corpus.generate import generate_corpus

            generate_corpus(base, size="small")
        setup_scenario(mock, "s4_code_modernisation", ScenarioContext())
        workspace = state.config.paths.data_dir / "prefix-ws"
        workspace.mkdir(parents=True, exist_ok=True)
        legacy = base / "docs" / "tank_gauging.py"
        if legacy.is_file():
            (workspace / "tank_gauging.py").write_text(
                legacy.read_text(encoding="utf-8"), encoding="utf-8"
            )
        with state.db.session() as s:
            session = SessionRow(workspace_path=str(workspace), collections=[], mode="auto")
            s.add(session)
            s.flush()
            session_id = session.id
        run_id = await state.conductor.start_run(session_id, "modernise tank gauging", [], "auto")
        await state.conductor.wait_for_run(run_id, timeout_s=120)

        by_task: dict[str, list[str]] = {}
        for request in mock.calls:
            if request.meta.get("role") != "executor":
                continue
            task = _task_of(request)
            if task:
                by_task.setdefault(task, []).append(_prompt_text(request))

        ratios: list[float] = []
        for prompts in by_task.values():
            for prev, cur in itertools.pairwise(prompts):
                ratios.append(_common_prefix_ratio(prev, cur))
        assert ratios, "no multi-step executor task captured"
        mean = sum(ratios) / len(ratios)
        print(f"measured prefix stability: {mean:.1%} over {len(ratios)} step pairs")
        assert mean >= 0.70, f"prefix stability {mean:.0%} < 70% ({[f'{r:.2f}' for r in ratios]})"
    finally:
        await state.supervisor.stop_all()
