"""`yantra` CLI (SPEC §19.1). Subcommand groups are added by their milestones."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from yantra_server import __version__
from yantra_server.config import ConfigError, LoadedConfig, effective_report, load_config

app = typer.Typer(
    name="yantra",
    help="YANTRA — sovereign on-premise agentic workbench.",
    no_args_is_help=False,
    pretty_exceptions_show_locals=False,
)
config_app = typer.Typer(help="Show and validate configuration.")
audit_app = typer.Typer(help="Verify and export the hash-chained audit log.")
app.add_typer(config_app, name="config")
app.add_typer(audit_app, name="audit")

from yantra_server.cli.eval_cmd import eval_app  # noqa: E402
from yantra_server.cli.index_cmd import index_app  # noqa: E402
from yantra_server.cli.models_cmd import bench_app, models_app  # noqa: E402
from yantra_server.cli.run_cmd import resume_run, run_goal  # noqa: E402
from yantra_server.cli.seal_cmd import seal_app  # noqa: E402

app.add_typer(models_app, name="models")
app.add_typer(bench_app, name="bench")
app.add_typer(seal_app, name="seal")
app.add_typer(index_app, name="index")
app.add_typer(eval_app, name="eval")
app.command("run")(run_goal)
app.command("resume")(resume_run)


agents_app = typer.Typer(help="Inspect and validate agent definitions.")
app.add_typer(agents_app, name="agents")


@agents_app.command("list")
def agents_list() -> None:
    from yantra_server.agents import AgentRoster

    loaded = cli_config()
    roster = AgentRoster(loaded.assets_dir / "agents")
    for agent in roster.all():
        typer.echo(
            f"{agent.name:<18} role={agent.model_role:<9} tools={len(agent.tools):<3} {agent.description}"
        )


@agents_app.command("validate")
def agents_validate() -> None:
    from yantra_server.agents import AgentRoster

    loaded = cli_config()
    roster = AgentRoster(loaded.assets_dir / "agents")
    problems = roster.validate_all()
    if problems:
        for problem in problems:
            typer.secho(f"✗ {problem}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"OK — {len(roster.all())} agents valid", fg=typer.colors.GREEN)


_cli_overrides: dict[str, Any] = {}
_config_path: Path | None = None


def cli_config() -> LoadedConfig:
    try:
        return load_config(cli_overrides=_cli_overrides, config_path=_config_path)
    except ConfigError as exc:
        typer.secho(f"config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    profile: Annotated[
        str | None, typer.Option(help="Hardware profile: lite|standard|refinery")
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help="Path to yantra.yaml")] = None,
) -> None:
    global _config_path
    if profile:
        _cli_overrides["profile"] = profile
    if config:
        _config_path = config
    if ctx.invoked_subcommand is None:
        raise typer.Exit(launch_tui())


def launch_tui() -> int:
    """No subcommand → run the terminal UI (Node), pointing it at this environment."""
    loaded = cli_config()
    entry = os.environ.get("YANTRA_TUI_PATH")
    candidates = [Path(entry)] if entry else []
    candidates += [
        loaded.assets_dir / "tui" / "dist" / "index.js",
        Path(__file__).resolve().parents[3] / "tui" / "dist" / "index.js",
    ]
    tui = next((c for c in candidates if c.is_file()), None)
    if tui is None:
        typer.secho(
            "TUI not built. Run `pnpm install && pnpm --filter yantra-tui build`, or use "
            "`yantra serve` + `yantra run` for headless operation.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return 3
    node = shutil.which("node")
    if node is None:
        typer.secho(
            "node not found on PATH (Node 22+ required for the TUI)", fg=typer.colors.RED, err=True
        )
        return 3
    env = dict(os.environ)
    env.setdefault(
        "YANTRA_SERVER_URL",
        f"ws://{loaded.config.server.host}:{loaded.config.server.port}/rpc",
    )
    # Load the Node socket guard via a direct --require (handles paths with spaces, unlike
    # NODE_OPTIONS); the guard is a no-op under YANTRA_SEALED=0.
    argv = [node]
    preload = loaded.assets_dir / "tui" / "preload" / "seal.cjs"
    if preload.is_file():
        argv += ["--require", str(preload)]
    argv.append(str(tui))
    return subprocess.call(argv, env=env)


@app.command()
def version() -> None:
    """Print the YANTRA version."""
    typer.echo(f"yantra {__version__}")


corpus_app = typer.Typer(help="Synthetic refinery corpus for demos and evals.")
app.add_typer(corpus_app, name="corpus")


@corpus_app.command("generate")
def corpus_generate(
    size: Annotated[str, typer.Option(help="small|medium|large")] = "small",
    out: Annotated[Path | None, typer.Option(help="Output dir (default corpus/generated)")] = None,
) -> None:
    """Generate the synthetic MRPL-style corpus and truth.json."""
    import sys as _sys

    loaded = cli_config()
    _sys.path.insert(0, str(loaded.assets_dir))
    from corpus.generate import generate_corpus

    out_dir = out or (loaded.assets_dir / "corpus" / "generated" / size)
    truth = generate_corpus(out_dir, size=size)
    from corpus.pid_gen import generate_pids

    pid = generate_pids(out_dir / "drawings")
    typer.secho(
        f"generated {truth['document_count']} documents + {len(truth['facts'])} truth facts "
        f"+ P&ID {Path(pid['png']).name} → {out_dir}",
        fg=typer.colors.GREEN,
    )


@app.command()
def serve(
    bind: Annotated[str | None, typer.Option(help="Host to bind (default from config)")] = None,
    port: Annotated[int | None, typer.Option(help="Port (default 7331)")] = None,
) -> None:
    """Run the YANTRA server (API + RPC + dashboard)."""
    if bind:
        _cli_overrides.setdefault("server", {})["host"] = bind
    if port:
        _cli_overrides.setdefault("server", {})["port"] = port
    loaded = cli_config()
    _print_banner(loaded)

    # Layer 2 applied before ML libraries import; the guard is installed in the app lifespan.
    from yantra_server.seal.env import apply_seal_env_to_current_process

    if loaded.config.sealed():
        apply_seal_env_to_current_process()

    import uvicorn

    from yantra_server.app import create_app

    uvicorn.run(
        create_app(loaded),
        host=loaded.config.server.host,
        port=loaded.config.server.port,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


@app.command()
def dev() -> None:
    """Run the server in development mode (unsealed warning shown when YANTRA_SEALED=0)."""
    serve(bind=None, port=None)


def _print_banner(loaded: LoadedConfig) -> None:
    sealed = loaded.config.sealed()
    seal_text = "SEALED" if sealed else "UNSEALED (dev)"
    color = typer.colors.GREEN if sealed else typer.colors.RED
    typer.echo(f"yantra-server v{__version__} · profile {loaded.config.profile}")
    typer.secho(f"  seal: {seal_text}", fg=color)
    typer.echo(f"  bind: {loaded.config.server.host}:{loaded.config.server.port}")
    typer.echo(f"  data: {loaded.config.paths.data_dir}")


@config_app.command("show")
def config_show() -> None:
    """Print the effective configuration with the source of each value."""
    loaded = cli_config()
    typer.echo(f"profile: {loaded.config.profile}")
    typer.echo(f"config file: {loaded.config_file or '(none found)'}")
    typer.echo(f"assets dir: {loaded.assets_dir}")
    width = max((len(k) for k, _, _ in effective_report(loaded)), default=20)
    for key, value, source in effective_report(loaded):
        typer.echo(f"  {key.ljust(width)}  {value:<28} [{source}]")


@config_app.command("validate")
def config_validate() -> None:
    """Validate the configuration; exit non-zero on errors."""
    loaded = cli_config()
    typer.secho(
        f"OK — profile {loaded.config.profile}, "
        f"{len(loaded.config.permissions)} permission rules, "
        f"db {loaded.config.db_url().split('://')[0]}",
        fg=typer.colors.GREEN,
    )


def _open_db(loaded: LoadedConfig) -> Any:
    from yantra_server.db.base import Database
    from yantra_server.db.migrate import upgrade_to_head

    upgrade_to_head(loaded.config.db_url())
    return Database(loaded.config.db_url())


@audit_app.command("verify")
def audit_verify() -> None:
    """Recompute the whole audit chain; report the head hash."""
    from yantra_server.observe.audit_chain import AuditChain

    loaded = cli_config()
    db = _open_db(loaded)
    chain = AuditChain(db)
    result = chain.verify()
    head = chain.head()
    if result.ok:
        typer.secho(f"OK — {result.entries} entries verified", fg=typer.colors.GREEN)
        typer.echo(f"head: {head.hash if head else '(empty chain)'}")
    else:
        typer.secho(
            f"FAIL at seq {result.first_bad_seq}: {result.detail} "
            f"({result.entries} entries verified before failure)",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)


@audit_app.command("export")
def audit_export(
    from_seq: Annotated[int, typer.Option("--from", help="First seq to export")] = 1,
    to_seq: Annotated[int | None, typer.Option("--to", help="Last seq to export")] = None,
    out: Annotated[Path | None, typer.Option(help="Output file (default stdout)")] = None,
) -> None:
    """Export a chain segment as JSONL."""
    from yantra_server.observe.audit_chain import AuditChain

    loaded = cli_config()
    chain = AuditChain(_open_db(loaded))
    lines = chain.export(from_seq, to_seq)
    if out:
        with out.open("w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        typer.echo(f"wrote {out}")
    else:
        for line in lines:
            typer.echo(line)


@app.command()
def doctor() -> None:
    """Environment report: interpreter, GPUs, sandbox availability, config, gaps."""
    loaded = cli_config()
    report: list[tuple[str, str, bool]] = []
    report.append(("python", sys.version.split()[0], sys.version_info[:2] == (3, 12)))
    report.append(("platform", sys.platform, True))

    gpus = _detect_gpus()
    report.append(("gpus", ", ".join(gpus) if gpus else "none detected", True))

    for binary, why in [
        ("bwrap", "Linux sandbox"),
        ("docker", "sandbox fallback / compose"),
        ("node", "terminal UI"),
        ("soffice", "PDF export (optional)"),
    ]:
        found = shutil.which(binary)
        report.append(
            (binary, found or f"missing ({why})", found is not None or binary == "soffice")
        )

    sealed = loaded.config.sealed()
    report.append(("seal", "SEALED" if sealed else "UNSEALED (dev)", sealed))
    report.append(("config", str(loaded.config_file or "defaults"), True))
    report.append(("data dir", str(loaded.config.paths.data_dir), True))

    todos = _operator_todos(loaded.assets_dir)
    report.append(("TODO-by-operator", f"{len(todos)} clause markers" if todos else "none", True))

    for name, value, ok in report:
        mark = (
            typer.style("✓", fg=typer.colors.GREEN) if ok else typer.style("✗", fg=typer.colors.RED)
        )
        typer.echo(f" {mark} {name:<18} {value}")
    for path, line_no, text in todos:
        typer.echo(f"    operator input needed: {path}:{line_no}: {text.strip()}")

    profile = "refinery" if len(gpus) >= 4 else ("standard" if _big_gpu(gpus) else "lite")
    typer.echo(f"recommended profile: {profile}")


def _detect_gpus() -> list[str]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    try:
        out = subprocess.run(
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode != 0:
            return []
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def _big_gpu(gpus: list[str]) -> bool:
    for gpu in gpus:
        for token in gpu.replace(",", " ").split():
            if token.isdigit() and int(token) >= 70_000:  # MiB
                return True
    return False


def _operator_todos(assets_dir: Path) -> list[tuple[str, int, str]]:
    """List `TODO-by-operator` clause markers in knowledge packs (the only permitted TODOs)."""
    found: list[tuple[str, int, str]] = []
    knowledge = assets_dir / "knowledge"
    if not knowledge.is_dir():
        return found
    for path in knowledge.rglob("*.yaml"):
        try:
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "TODO-by-operator" in line:
                    found.append((str(path.relative_to(assets_dir)), line_no, line))
        except OSError:
            continue
    return found


@app.command(hidden=True)
def dump_protocol(out: Annotated[Path, typer.Argument()] = Path("-")) -> None:
    """Dump the RPC protocol JSON Schemas (consumed by scripts/gen_types.py)."""
    from yantra_server.protocol.export import protocol_schemas

    payload = json.dumps(protocol_schemas(), indent=2)
    if str(out) == "-":
        typer.echo(payload)
    else:
        out.write_text(payload, encoding="utf-8")


def main() -> None:
    # Windows consoles/pipes often default to a legacy codepage; the UI uses UTF-8 glyphs.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
