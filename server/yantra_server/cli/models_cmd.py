"""`yantra models …` and `yantra bench` (SPEC §7.4, §7.7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
import yaml

from yantra_server.config import LoadedConfig
from yantra_server.gateway.registry import (
    LargeModelRefused,
    ModelRegistry,
    RegistryError,
    inspect_model_path,
)

models_app = typer.Typer(help="Register, inspect, probe and serve models.")
bench_app = typer.Typer(help="Measure inference/ingestion throughput on this hardware.")


def _registry(loaded: LoadedConfig) -> ModelRegistry:
    registry_file = loaded.config.gateway.registry_file
    if not registry_file.is_absolute():
        registry_file = loaded.assets_dir / registry_file
    return ModelRegistry(registry_file, loaded.config.paths.models_dir)


def _server_url(loaded: LoadedConfig) -> str:
    return f"http://{loaded.config.server.host}:{loaded.config.server.port}"


def _server_get(loaded: LoadedConfig, path: str) -> dict[str, Any] | None:
    try:
        resp = httpx.get(_server_url(loaded) + path, timeout=10)
        if resp.status_code == 200:
            return dict(resp.json())
    except httpx.HTTPError:
        return None
    return None


def _server_post(
    loaded: LoadedConfig, path: str, body: dict[str, Any], timeout: float = 600
) -> dict[str, Any] | None:
    try:
        resp = httpx.post(_server_url(loaded) + path, json=body, timeout=timeout)
        if resp.status_code == 200:
            return dict(resp.json())
    except httpx.HTTPError:
        return None
    return None


@models_app.command("list")
def models_list() -> None:
    """Registered models, with live availability when the server is running."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    live = _server_get(loaded, "/api/models")
    if live:
        rows = live["models"]
        typer.echo(f"{'ID':<28} {'ENGINE':<9} {'PARAMS':>7} {'QUANT':<10} {'ROLES':<28} AVAILABLE")
        for m in rows:
            typer.echo(
                f"{m['id']:<28} {m['engine']:<9} {m['params_b']:>6.1f}B {m.get('quant') or '-':<10} "
                f"{','.join(m.get('roles', []))[:28]:<28} {'yes' if m.get('available') else 'no'}"
            )
        typer.echo("\nengines:")
        for e in live.get("engines", []):
            typer.echo(
                f"  {e['engine_id']}[{e['replica']}] {e['kind']:<9} {e['status']:<11} "
                f"port={e.get('port') or '-'} {e.get('error') or ''}"
            )
        return
    registry = _registry(loaded)
    typer.echo("(server not running — registry view only)")
    for manifest in registry.all():
        typer.echo(
            f"{manifest.id:<28} {manifest.engine:<9} {manifest.params_b:>6.1f}B "
            f"{manifest.quant or '-':<10} {','.join(manifest.roles)}"
        )


@models_app.command("add")
def models_add(
    path: Annotated[Path, typer.Argument(help="Model directory (HF layout) or .gguf file")],
    model_id: Annotated[str | None, typer.Option("--id")] = None,
    roles: Annotated[str | None, typer.Option(help="Comma-separated roles for the router")] = None,
    allow_large: Annotated[bool, typer.Option("--allow-large")] = False,
    probe: Annotated[
        bool, typer.Option(help="Run the capability probe (needs the server up)")
    ] = True,
) -> None:
    """Inspect a local model, register it, and probe its capabilities."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    registry = _registry(loaded)
    try:
        manifest = inspect_model_path(path)
    except RegistryError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    if model_id:
        manifest.id = model_id
    if roles:
        manifest.roles = [r.strip() for r in roles.split(",") if r.strip()]
    try:
        registry.register(manifest, allow_large=allow_large)
    except LargeModelRefused as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    registry.save()
    if allow_large and manifest.params_b >= 120:
        _audit(
            loaded, "models.add.allow_large", {"model": manifest.id, "params_b": manifest.params_b}
        )
    typer.secho(
        f"registered {manifest.id} ({manifest.params_b:.1f}B, {manifest.engine}, "
        f"caps: {','.join(manifest.capabilities)})",
        fg=typer.colors.GREEN,
    )
    if probe:
        result = _server_post(loaded, "/api/models/probe", {"model_id": manifest.id})
        if result is None:
            typer.secho(
                "probe skipped: server not running (start `yantra serve`, then "
                f"`yantra models probe {manifest.id}`)",
                fg=typer.colors.YELLOW,
            )
        else:
            _print_probe(result)


def _audit(loaded: LoadedConfig, event: str, payload: dict[str, Any]) -> None:
    from yantra_server.db.base import Database
    from yantra_server.db.migrate import upgrade_to_head
    from yantra_server.observe.audit_chain import AuditChain

    upgrade_to_head(loaded.config.db_url())
    AuditChain(Database(loaded.config.db_url())).append("user", event, payload)


def _print_probe(result: dict[str, Any]) -> None:
    if "error" in result:
        typer.secho(result["error"], fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    for outcome in result.get("outcomes", []):
        mark = "✓" if outcome["passed"] else "✗"
        score = f" score={outcome['score']}" if outcome.get("score") is not None else ""
        typer.echo(f" {mark} {outcome['probe']:<16}{score} {outcome.get('detail', '')[:80]}")


@models_app.command("probe")
def models_probe(model_id: str) -> None:
    """Run the capability probe suite against a registered model (server must be running)."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    result = _server_post(loaded, "/api/models/probe", {"model_id": model_id})
    if result is None:
        typer.secho(
            "server not reachable — start `yantra serve` first", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)
    _print_probe(result)


@models_app.command("remove")
def models_remove(model_id: str) -> None:
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    registry = _registry(loaded)
    if not registry.remove(model_id):
        typer.secho(f"unknown model {model_id}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    registry.save()
    _audit(loaded, "models.remove", {"model": model_id})
    typer.echo(f"removed {model_id}")


@models_app.command("serve")
def models_serve(engine_id: str) -> None:
    """Start an engine defined in the active profile (by engine id)."""
    _engine_action(engine_id, "start")


@models_app.command("stop")
def models_stop(engine_id: str) -> None:
    _engine_action(engine_id, "stop")


def _engine_action(engine_id: str, action: str) -> None:
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    result = _server_post(loaded, f"/api/engines/{engine_id}/{action}", {})
    if result is None:
        typer.secho(
            "server not reachable — start `yantra serve` first", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)
    if "error" in result:
        typer.secho(result["error"], fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    for e in result.get("engines", []):
        typer.echo(f"  {e['engine_id']}[{e['replica']}] {e['status']}")


@bench_app.command("llm")
def bench_llm_cmd(
    role: Annotated[str, typer.Option(help="Router role to benchmark")] = "executor",
) -> None:
    """Measure TTFT and tokens/s through the live gateway; record into the profile file."""
    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    result = _server_post(loaded, "/api/bench/llm", {"role": role})
    if result is None:
        typer.secho(
            "server not reachable — start `yantra serve` first", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)
    typer.echo(json.dumps(result, indent=2))
    _record_measured(
        loaded,
        "llm",
        {
            "model": result.get("model"),
            "ttft_ms_p50": result.get("ttft_ms_p50"),
            "tokens_per_s_p50": result.get("tokens_per_s_p50"),
        },
    )


def _record_measured(loaded: LoadedConfig, key: str, value: dict[str, Any]) -> None:
    profile_file = loaded.assets_dir / "models" / "profiles" / f"{loaded.config.profile}.yaml"
    if not profile_file.is_file():
        return
    data = yaml.safe_load(profile_file.read_text(encoding="utf-8")) or {}
    measured = data.setdefault("measured", {}) or {}
    measured[key] = value
    data["measured"] = measured
    profile_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    typer.echo(f"recorded into {profile_file}")


@bench_app.command("ingest")
def bench_ingest_cmd(
    docs: Annotated[
        Path | None, typer.Option(help="Directory to ingest (default: generated corpus)")
    ] = None,
) -> None:
    """Measure ingestion pages/s and chunks/s on this hardware; record into the profile file."""
    import asyncio
    import shutil
    import sys
    import time

    from yantra_server.cli.main import cli_config

    loaded = cli_config()
    source = docs
    if source is None:
        base = loaded.assets_dir / "corpus" / "generated" / "small"
        if not (base / "docs").is_dir():
            sys.path.insert(0, str(loaded.assets_dir))
            from corpus.generate import generate_corpus

            generate_corpus(base, size="small")
        source = base / "docs"

    async def run() -> dict[str, Any]:
        from sqlalchemy import func, select

        from yantra_server.app import build_state
        from yantra_server.db.models import CollectionRow, DocumentRow

        state = build_state(loaded)
        state.bus.bind_loop(asyncio.get_running_loop())
        await state.supervisor.start_all()
        collection = "bench_ingest"
        try:
            if state.knowledge is None:
                raise RuntimeError("knowledge plane unavailable (install the 'knowledge' extra)")
            started = time.monotonic()
            stats = await state.knowledge.ingest_path(Path(source), collection)
            wall = max(time.monotonic() - started, 1e-9)
            with state.db.session() as s:
                collection_id = s.execute(
                    select(CollectionRow.id).where(CollectionRow.name == collection)
                ).scalar_one()
                pages = (
                    s.execute(
                        select(func.sum(DocumentRow.page_count)).where(
                            DocumentRow.collection_id == collection_id
                        )
                    ).scalar()
                    or 0
                )
            return {
                "documents": stats.documents,
                "pages": int(pages),
                "chunks": stats.chunks,
                "errors": stats.errors,
                "wall_s": round(wall, 2),
                "pages_per_s": round(pages / wall, 2),
                "chunks_per_s": round(stats.chunks / wall, 2),
            }
        finally:
            await state.supervisor.stop_all()
            # a throwaway benchmark collection; drop its lexical index dir too
            shutil.rmtree(
                loaded.config.paths.data_dir / "knowledge" / "lexical" / collection,
                ignore_errors=True,
            )

    result = asyncio.run(run())
    typer.echo(json.dumps(result, indent=2))
    _record_measured(
        loaded,
        "ingest",
        {"pages_per_s": result["pages_per_s"], "chunks_per_s": result["chunks_per_s"]},
    )
