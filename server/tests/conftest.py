"""Shared fixtures: isolated env, migrated temp DB, artifact store, audit chain."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from yantra_server.artifacts import ArtifactStore
from yantra_server.db.base import Database
from yantra_server.db.migrate import upgrade_to_head
from yantra_server.observe.audit_chain import AuditChain
from yantra_server.observe.tracing import configure_tracing, shutdown_tracing

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests never read the developer's config, env overrides, or home data dir."""
    for name in list(os.environ):
        if name.startswith("YANTRA_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("YANTRA_PATHS__DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("YANTRA_ASSETS_DIR", str(REPO_ROOT))


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    upgrade_to_head(url)
    database = Database(url)
    yield database
    database.dispose()


@pytest.fixture
def artifacts(db: Database, tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(db, tmp_path / "artifacts")


@pytest.fixture
def audit(db: Database) -> AuditChain:
    return AuditChain(db)


@pytest.fixture
def tracing(db: Database, artifacts: ArtifactStore) -> Iterator[None]:
    configure_tracing(db, artifacts, batch=False)
    yield
    shutdown_tracing()
