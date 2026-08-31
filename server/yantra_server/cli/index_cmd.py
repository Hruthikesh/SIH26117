"""`yantra index add|status|reindex|snapshot` (SPEC §19.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import typer

index_app = typer.Typer(help="Build and manage knowledge collections.")


def _build_state() -> Any:
    from yantra_server.app import build_state
    from yantra_server.cli.main import cli_config

    return build_state(cli_config())


@index_app.command("add")
def index_add(
    path: Annotated[Path, typer.Argument(help="File or folder to ingest")],
    collection: Annotated[str, typer.Option("--collection", "-c", help="Target collection")],
    priority: Annotated[str, typer.Option(help="high|normal (advisory)")] = "normal",
) -> None:
    """Ingest a path into a collection (parse → chunk → enrich → embed → index)."""
    from yantra_server.seal.socket_guard import install as install_guard

    state = _build_state()
    install_guard(allowlist=state.config.seal.allowlist)

    async def run() -> None:
        await state.supervisor.start_all()
        try:
            printed = {"n": 0}

            def progress(stats: object) -> None:
                total = getattr(stats, "documents", 0) + getattr(stats, "skipped", 0)
                if total // 10 > printed["n"]:
                    printed["n"] = total // 10
                    typer.echo(f"  … {total} files processed")

            stats = await state.knowledge.ingest_path(path, collection, on_progress=progress)
            typer.secho(
                f"indexed {stats.documents} document(s), {stats.chunks} chunks "
                f"({stats.skipped} unchanged, {stats.errors} errors) into '{collection}'",
                fg=typer.colors.GREEN,
            )
        finally:
            await state.supervisor.stop_all()
            state.knowledge.close()

    if not path.exists():
        typer.secho(f"path not found: {path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    asyncio.run(run())


@index_app.command("status")
def index_status() -> None:
    """Show collections with document/chunk counts and error totals."""
    state = _build_state()
    cols = state.knowledge.list_collections()
    if not cols:
        typer.echo("no collections yet — `yantra index add <path> -c <name>`")
        return
    for c in cols:
        typer.echo(
            f"{c['name']:<20} {c['documents']:>6} docs {c['chunks']:>8} chunks"
            + (f"  {c['errors']} errors" if c["errors"] else "")
        )


@index_app.command("reindex")
def index_reindex(
    collection: Annotated[str, typer.Option("--collection", "-c")],
    changed_only: Annotated[bool, typer.Option("--changed-only")] = True,
) -> None:
    """Re-ingest a collection's source roots (changed files only by default)."""
    from sqlalchemy import select

    from yantra_server.db.models import CollectionRow

    state = _build_state()
    with state.db.session() as s:
        row = s.execute(
            select(CollectionRow).where(CollectionRow.name == collection)
        ).scalar_one_or_none()
        roots = list(row.source_roots) if row else []
    if not roots:
        typer.secho(f"collection '{collection}' has no source roots", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    async def run() -> None:
        await state.supervisor.start_all()
        try:
            for root in roots:
                stats = await state.knowledge.ingest_path(Path(root), collection)
                typer.echo(f"{root}: {stats.documents} reindexed, {stats.skipped} unchanged")
        finally:
            await state.supervisor.stop_all()
            state.knowledge.close()

    asyncio.run(run())


@index_app.command("snapshot")
def index_snapshot(
    collection: Annotated[str, typer.Option("--collection", "-c")],
) -> None:
    """Snapshot a collection's vector index (Qdrant snapshot + on-disk lexical copy)."""
    state = _build_state()
    name = state.knowledge.vector().snapshot(f"chunks_{collection}")
    typer.echo(f"vector snapshot: {name or '(collection not found)'}")
