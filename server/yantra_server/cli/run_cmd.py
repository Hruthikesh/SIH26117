"""`yantra run` / `yantra resume`: headless execution without the TUI (SPEC §17.4)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from yantra_server.config import LoadedConfig

run_app = typer.Typer(help="Headless runs.")


async def _headless(
    loaded: LoadedConfig,
    *,
    goal: str | None,
    resume_id: str | None,
    workspace: Path,
    collections: list[str],
    mode: str,
    json_events: bool,
    out: Path | None,
) -> int:
    from yantra_server.app import build_state
    from yantra_server.db.models import RunRow, SessionRow
    from yantra_server.rpc import Connection

    state = build_state(loaded)
    state.bus.bind_loop(asyncio.get_running_loop())
    await state.supervisor.start_all()
    for tool in await state.tools.mcp.start_all():
        state.tools.registry.register(tool)

    conn = Connection(id="headless")
    state.bus.attach(conn)
    finished = asyncio.Event()
    final_payload: dict[str, Any] = {}

    async def pump() -> None:
        while True:
            frame = await conn.outbound.get()
            method = frame.get("method", "")
            params = frame.get("params", {})
            if json_events:
                typer.echo(json.dumps(frame, default=str))
            else:
                line = _progress_line(str(method), params)
                if line:
                    typer.echo(line)
            if method == "run.finished":
                final_payload.update(params)
                finished.set()
            if method == "permission.request" and not json_events:
                # Headless has no interactive approver; auto mode policy already allows
                # routine actions — anything that still asks is denied explicitly.
                request_id = str(params.get("request_id", ""))
                if request_id.startswith("plan:"):
                    state.conductor.resolve_plan_approval(request_id.removeprefix("plan:"), "once")
                else:
                    state.tools.broker.resolve(request_id, "deny", "headless run")

    pump_task = asyncio.create_task(pump())
    try:
        if resume_id is not None:
            run_id = await state.conductor.resume_run(resume_id)
        else:
            assert goal is not None
            with state.db.session() as s:
                session = SessionRow(
                    workspace_path=str(workspace),
                    collections=list(collections),
                    mode=mode,
                    title="headless",
                )
                s.add(session)
                s.flush()
                session_id = session.id
            run_id = await state.conductor.start_run(session_id, goal, [], mode)
        typer.echo(f"run: {run_id}", err=True)
        await state.conductor.wait_for_run(run_id)
        await asyncio.wait_for(finished.wait(), timeout=30)
    except TimeoutError:
        pass
    finally:
        pump_task.cancel()
        await state.tools.mcp.stop_all()
        await state.supervisor.stop_all()
        from yantra_server.observe.tracing import force_flush

        force_flush()

    with state.db.session() as s:
        run = s.get(RunRow, run_id)
        status = run.status if run else "unknown"
        final = dict(run.final or {}) if run else {}
    final.setdefault("run_id", run_id)
    final.setdefault("status", status)
    if out is not None:
        out.write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")  # noqa: ASYNC240 - one-shot write at exit
        typer.echo(f"wrote {out}", err=True)
    elif not json_events:
        typer.echo(json.dumps(final, indent=2, default=str))
    return 0 if status in ("done", "done_with_gaps", "planned") else 1


def _progress_line(method: str, params: dict[str, Any]) -> str | None:
    if method == "task.updated":
        return f"[task] {params.get('task_id')} {params.get('status')} ({params.get('title', '')[:60]})"
    if method == "tool.started":
        return f"  ● {params.get('tool')}"
    if method == "tool.finished":
        mark = "✔" if params.get("ok") else "✘"
        return f"  ⎿ {mark} {params.get('summary', '')[:100]}"
    if method == "verify.result":
        report = params.get("report", {})
        return f"[verify] {params.get('task_id')}: {report.get('verdict')} (reviewer {report.get('reviewer', {}).get('score')})"
    if method == "escalation":
        return f"[escalate] {params.get('task_id')} → {params.get('rung')}"
    if method == "plan.updated":
        tasks = params.get("plan", {}).get("tasks", [])
        return "[plan] " + "; ".join(f"{t.get('id')} {t.get('title', '')[:40]}" for t in tasks[:8])
    if method == "run.finished":
        return f"[finished] {params.get('status')}"
    if method == "error":
        return f"[error] {params.get('code')}: {params.get('message')}"
    return None


@run_app.command("run")
def run_goal(
    goal: Annotated[str, typer.Argument(help="The goal to execute")],
    mode: Annotated[str, typer.Option(help="ask|auto|plan")] = "auto",
    workspace: Annotated[Path, typer.Option(help="Workspace directory")] = Path.cwd(),
    collections: Annotated[str, typer.Option(help="Comma-separated collection names")] = "",
    out: Annotated[Path | None, typer.Option(help="Write the final answer JSON here")] = None,
    json_events: Annotated[
        bool, typer.Option("--json-events", help="Stream TUI events as JSONL")
    ] = False,
) -> None:
    """Execute one goal headlessly and print the final answer."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    code = asyncio.run(
        _headless(
            loaded,
            goal=goal,
            resume_id=None,
            workspace=workspace.resolve(),
            collections=[c.strip() for c in collections.split(",") if c.strip()],
            mode=mode,
            json_events=json_events,
            out=out,
        )
    )
    raise typer.Exit(code)


@run_app.command("resume")
def resume_run(
    run_id: Annotated[str, typer.Argument(help="Run id to resume")],
    json_events: Annotated[bool, typer.Option("--json-events")] = False,
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Resume an interrupted run from its last checkpoint (crash-only design)."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    code = asyncio.run(
        _headless(
            loaded,
            goal=None,
            resume_id=run_id,
            workspace=Path.cwd(),
            collections=[],
            mode="auto",
            json_events=json_events,
            out=out,
        )
    )
    raise typer.Exit(code)


if sys.platform == "win32":  # Proactor loop handles subprocess creation used by sandboxes
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
