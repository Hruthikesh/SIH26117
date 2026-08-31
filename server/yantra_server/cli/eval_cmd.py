"""`yantra eval run|report|tune-retrieval` (SPEC §20.3).

Builds a full app state (like a headless run), drives the eval runner over one or more
suites, prints a table, and optionally writes docs/EVALS.md and a JSON report. On the mock
profile the scripted scenarios and deterministic subsystems run; the report states plainly
what is real versus scripted so the numbers are never overclaimed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from yantra_server.config import LoadedConfig

eval_app = typer.Typer(help="Evaluation harness: suites, reports, tuning.")

ALL_SUITES = ["tasks", "retrieval", "pid", "seal_smoke", "resilience", "latency"]


def _ensure_corpus(loaded: LoadedConfig) -> None:
    """Generate the small corpus + demo P&ID if they are not present yet."""
    base = loaded.assets_dir / "corpus" / "generated" / "small"
    sys.path.insert(0, str(loaded.assets_dir))
    if not (base / "docs").is_dir() or not (base / "truth.json").is_file():
        from corpus.generate import generate_corpus

        generate_corpus(base, size="small")
    if not (base / "drawings").is_dir() or not list((base / "drawings").glob("*.png")):
        from corpus.pid_gen import generate_pids

        generate_pids(base / "drawings")


async def _headless_pump(state: Any, conn: Any) -> asyncio.Task[None]:
    """Auto-approve plan gates and deny interactive permission asks (no human in the loop)."""

    async def pump() -> None:
        while True:
            frame = await conn.outbound.get()
            method = frame.get("method", "")
            params = frame.get("params", {})
            if method == "permission.request":
                request_id = str(params.get("request_id", ""))
                if request_id.startswith("plan:"):
                    state.conductor.resolve_plan_approval(request_id.removeprefix("plan:"), "once")
                else:
                    state.tools.broker.resolve(request_id, "deny", "eval run")

    return asyncio.create_task(pump())


async def _run(loaded: LoadedConfig, suites: list[str], write_doc: bool, out: Path | None) -> int:
    from yantra_server.app import build_state
    from yantra_server.evals.runner import EvalRunner, write_evals_doc
    from yantra_server.rpc import Connection

    _ensure_corpus(loaded)
    state = build_state(loaded)
    state.bus.bind_loop(asyncio.get_running_loop())
    await state.supervisor.start_all()
    for tool in await state.tools.mcp.start_all():
        state.tools.registry.register(tool)
    conn = Connection(id="eval")
    state.bus.attach(conn)
    pump_task = await _headless_pump(state, conn)

    runner = EvalRunner(state)
    reports = []
    try:
        for suite in suites:
            typer.secho(f"▶ {suite}", fg=typer.colors.CYAN)
            report = await runner.run(suite)
            reports.append(report)
            _print_report(report)
    finally:
        pump_task.cancel()
        await state.tools.mcp.stop_all()
        await state.supervisor.stop_all()
        from yantra_server.observe.tracing import force_flush

        force_flush()

    if out is not None:
        out.write_text(  # noqa: ASYNC240 - one-shot write at exit
            json.dumps([r.to_dict() for r in reports], indent=2), encoding="utf-8"
        )
        typer.echo(f"wrote {out}")
    if write_doc:
        doc = loaded.assets_dir / "docs" / "EVALS.md"
        write_evals_doc(reports, doc)
        typer.echo(f"wrote {doc}")
    return 0 if all(r.pass_rate() >= 0.999 for r in reports) else 1


def _print_report(report: Any) -> None:
    for case in report.cases:
        mark = (
            typer.style("PASS", fg=typer.colors.GREEN)
            if case.passed
            else typer.style("FAIL", fg=typer.colors.RED)
        )
        typer.echo(f"  {mark}  {case.case_id:<28} {case.detail}")
    typer.echo(f"  → {report.pass_rate():.0%} pass, {report.wall_s:.1f}s")


@eval_app.command("run")
def eval_run(
    suites: Annotated[list[str] | None, typer.Argument(help="Suites to run (default: all)")] = None,
    write_doc: Annotated[bool, typer.Option("--write-doc", help="Write docs/EVALS.md")] = False,
    out: Annotated[Path | None, typer.Option(help="Write a JSON report here")] = None,
) -> None:
    """Run one or more eval suites and print results."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    chosen = suites or ALL_SUITES
    unknown = [s for s in chosen if s not in ALL_SUITES]
    if unknown:
        typer.secho(
            f"unknown suite(s): {', '.join(unknown)} (have {', '.join(ALL_SUITES)})",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    code = asyncio.run(_run(loaded, chosen, write_doc, out))
    raise typer.Exit(code)


@eval_app.command("report")
def eval_report(
    limit: Annotated[int, typer.Option(help="How many recent runs to show")] = 10,
) -> None:
    """Show recent eval runs recorded in the database."""
    from sqlalchemy import select

    from yantra_server.cli.main import _open_db, cli_config
    from yantra_server.db.models import EvalResultRow, EvalRunRow

    loaded = cli_config()
    db = _open_db(loaded)
    with db.session() as s:
        runs = list(
            s.execute(
                select(EvalRunRow).order_by(EvalRunRow.started_at.desc()).limit(limit)
            ).scalars()
        )
        if not runs:
            typer.echo("no eval runs recorded yet — run `yantra eval run`")
            return
        for run in runs:
            results = list(
                s.execute(
                    select(EvalResultRow).where(EvalResultRow.eval_run_id == run.id)
                ).scalars()
            )
            passed = sum(1 for r in results if r.passed)
            rate = passed / len(results) if results else 0.0
            typer.echo(
                f"{str(run.started_at)[:19]}  {run.suite:<12} {run.profile:<9} "
                f"{rate:.0%} ({passed}/{len(results)})  [{run.status}]"
            )


@eval_app.command("tune-retrieval")
def eval_tune_retrieval(
    out_adr: Annotated[bool, typer.Option("--adr", help="Print an ADR-ready summary")] = False,
) -> None:
    """Sweep fusion weights on the retrieval suite and recommend the best (feeds ADR 0009)."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    code = asyncio.run(_tune_retrieval(loaded, out_adr))
    raise typer.Exit(code)


async def _tune_retrieval(loaded: LoadedConfig, out_adr: bool) -> int:
    import json as _json

    from yantra_server.app import build_state
    from yantra_server.knowledge.retrieve.evaluate import cases_from_truth, evaluate_retrieval

    _ensure_corpus(loaded)
    state = build_state(loaded)
    state.bus.bind_loop(asyncio.get_running_loop())
    await state.supervisor.start_all()
    if state.knowledge is None:
        typer.secho(
            "knowledge plane unavailable (install the 'knowledge' extra)", fg=typer.colors.RED
        )
        return 2
    collection = "tune_retrieval"
    base = loaded.assets_dir / "corpus" / "generated" / "small"
    try:
        await state.knowledge.ingest_path(base / "docs", collection)
        truth = _json.loads((base / "truth.json").read_text(encoding="utf-8"))
        cases = cases_from_truth(truth)
        grid = [
            {"lexical": 1.0, "dense": 0.0},
            {"lexical": 0.8, "dense": 0.2},
            {"lexical": 0.6, "dense": 0.4},
            {"lexical": 0.5, "dense": 0.5},
            {"lexical": 0.4, "dense": 0.6},
        ]
        rows: list[tuple[dict[str, float], float, float]] = []
        for weights in grid:
            state.knowledge.config.knowledge.fusion_weights = weights
            metrics = await evaluate_retrieval(
                state.knowledge, cases, collections=[collection], mode="hybrid"
            )
            rows.append((weights, metrics.recall_at_10, metrics.mrr))
            typer.echo(
                f"  lexical={weights['lexical']:.1f} dense={weights['dense']:.1f}  "
                f"recall@10={metrics.recall_at_10:.2f} mrr={metrics.mrr:.2f}"
            )
        best = max(rows, key=lambda r: (r[1], r[2]))
        typer.secho(
            f"best: lexical={best[0]['lexical']:.1f} dense={best[0]['dense']:.1f} "
            f"(recall@10={best[1]:.2f}, mrr={best[2]:.2f})",
            fg=typer.colors.GREEN,
        )
        if out_adr:
            typer.echo(
                "\nADR note: chosen fusion weights "
                f"{best[0]} by recall@10 on the generated truth set "
                f"({len(cases)} cases). Re-run on a real embedding model before production."
            )
    finally:
        await state.supervisor.stop_all()
    return 0
