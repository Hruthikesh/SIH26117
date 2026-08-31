"""Eval harness end-to-end on the mock profile (M9 DoD: scenarios 2-5 pass here)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import select

from tests.helpers import make_state
from yantra_server.db.models import EvalResultRow, EvalRunRow
from yantra_server.evals.runner import SUITES_DIR, EvalRunner

pytestmark = pytest.mark.integration

ALL_SUITES = ["tasks", "retrieval", "pid", "seal_smoke", "resilience", "latency"]


def test_all_suites_load() -> None:
    import yaml

    for name in ALL_SUITES:
        data = yaml.safe_load((SUITES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
        assert data.get("kind") in ("tasks", "retrieval", "pid", "seal", "resilience", "latency")


@pytest.fixture
async def runner(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("YANTRA_SEALED", "0")  # local sandbox on the GPU-less dev box
    state = make_state()
    state.bus.bind_loop(asyncio.get_running_loop())
    await state.supervisor.start_all()
    yield EvalRunner(state)
    await state.supervisor.stop_all()


async def test_pid_suite_full_deviation_recall(runner: EvalRunner) -> None:
    report = await runner.run("pid")
    assert report.pass_rate() == 1.0
    assert report.cases[0].metrics["planted"] == 3


async def test_scenarios_2_to_5_pass(runner: EvalRunner) -> None:
    """SPEC §22 M9 DoD. Scripted model reasoning, real tools/corpus/vision/render."""
    report = await runner.run("tasks")
    failures = [f"{c.case_id}: {c.detail}" for c in report.cases if not c.passed]
    assert not failures, failures
    assert {c.case_id for c in report.cases} == {
        "s2_pump_reliability",
        "s3_pid_review",
        "s4_code_modernisation",
        "s5_consolidation",
    }


async def test_latency_suite_reports_metrics(runner: EvalRunner) -> None:
    report = await runner.run("latency")
    assert report.pass_rate() == 1.0
    metrics = report.cases[0].metrics
    assert metrics["samples"] == 20
    assert metrics["p95_ms"] >= metrics["p50_ms"] >= 0


async def test_results_recorded_in_db(runner: EvalRunner) -> None:
    await runner.run("resilience")
    with runner.state.db.session() as s:
        run = s.execute(
            select(EvalRunRow).where(EvalRunRow.suite == "resilience")
        ).scalars().first()
        assert run is not None and run.status == "done" and run.finished_at is not None
        results = list(
            s.execute(select(EvalResultRow).where(EvalResultRow.eval_run_id == run.id)).scalars()
        )
        assert results and all(r.passed for r in results)
