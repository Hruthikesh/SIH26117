"""`yantra seal verify|demo|keygen|status` (SPEC §14.5, §19.1)."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

import httpx
import typer

seal_app = typer.Typer(help="Zero-egress seal: status, verification, live demo.")


def _build_state() -> Any:  # AppState
    from yantra_server.app import build_state
    from yantra_server.cli.main import cli_config

    return build_state(cli_config())


async def _wire_and_run(coro_name: str) -> Any:
    from yantra_server.seal import verify as verify_mod

    state = _build_state()
    from yantra_server.observe.seal_monitor import SealMonitor
    from yantra_server.seal.socket_guard import install as install_guard

    monitor = SealMonitor(state.config, state.db, state.bus, state.loaded.assets_dir)
    state.seal_monitor = monitor
    install_guard(allowlist=state.config.seal.allowlist, reporter=monitor.record_event)
    await state.supervisor.start_all()
    from yantra_server.agents import AgentRoster
    from yantra_server.conductor.service import Conductor

    if state.conductor is None:
        state.conductor = Conductor(
            state=state, roster=AgentRoster(state.loaded.assets_dir / "agents")
        )
    try:
        if coro_name == "verify":
            return await verify_mod.run_verification(state)
        from yantra_server.seal.demo import run_seal_demo

        return await run_seal_demo(state)
    finally:
        await state.supervisor.stop_all()
        from yantra_server.observe.tracing import force_flush

        force_flush()


@seal_app.command("status")
def seal_status(
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show seal status from a running server, or the local layer report if none is up."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    url = f"http://{loaded.config.server.host}:{loaded.config.server.port}/api/seal"
    try:
        resp = httpx.get(url, timeout=5)
        data = resp.json() if resp.status_code == 200 else None
    except httpx.HTTPError:
        data = None
    if data is None:
        from yantra_server.observe.seal_monitor import SealMonitor

        state = _build_state()
        monitor = SealMonitor(state.config, state.db, state.bus, state.loaded.assets_dir)
        data = monitor.status()
    if json_out:
        typer.echo(json.dumps(data, indent=2))
        return
    color = typer.colors.GREEN if data["sealed"] else typer.colors.RED
    typer.secho(f"sealed: {data['sealed']}", fg=color)
    typer.echo(f"blocked attempts: {data['blocked_attempts_total']}")
    typer.echo(f"allowlist: {', '.join(data['allowlist'])}")
    for layer, ok in data.get("layers", {}).items():
        mark = (
            typer.style("✓", fg=typer.colors.GREEN)
            if ok
            else typer.style("·", fg=typer.colors.YELLOW)
        )
        typer.echo(f"  {mark} {layer}")


@seal_app.command("verify")
def seal_verify() -> None:
    """Run the five-layer verification and print a signed Seal Certificate."""
    from yantra_server.seal.verify import format_report

    report = asyncio.run(_wire_and_run("verify"))
    typer.echo(format_report(report))
    raise typer.Exit(0 if report.ok() else 1)


@seal_app.command("demo")
def seal_demo(json_out: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Fire two egress attempts from sealed children; both must be blocked."""
    result = asyncio.run(_wire_and_run("demo"))
    if json_out:
        typer.echo(json.dumps(result, indent=2))
        return
    for probe in result["probes"]:
        mark = (
            typer.style("BLOCKED", fg=typer.colors.GREEN)
            if probe["blocked"]
            else typer.style("LEAK", fg=typer.colors.RED)
        )
        typer.echo(f"[{mark}] {probe['name']}")
        typer.echo(f"        {probe['output'][:120]}")
    typer.echo(f"new blocked events: {result['new_blocked_events']}")
    doc = result["document_task"]
    typer.echo(
        f"document task kept running: {'ok' if doc['passed'] or doc['skipped'] else 'FAILED'} — {doc['detail']}"
    )
    all_blocked = all(p["blocked"] for p in result["probes"])
    raise typer.Exit(0 if all_blocked else 1)


@seal_app.command("keygen")
def seal_keygen() -> None:
    """Generate the Ed25519 key that signs Seal Certificates."""
    from yantra_server.cli.main import cli_config
    from yantra_server.seal.verify import keygen

    loaded = cli_config()
    private_path, public_path = keygen(loaded.config.paths.data_dir)
    typer.secho(f"wrote {private_path}", fg=typer.colors.GREEN)
    typer.echo(f"public key: {public_path}")
