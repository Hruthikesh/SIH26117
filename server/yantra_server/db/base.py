"""Engine/session factory. Sync core, thread-offloaded from async code (ADR 0006)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

# JSON that becomes JSONB on Postgres.
JsonDict = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy declarative config, not instance state
        dict[str, Any]: JsonDict,
        list[Any]: JsonDict,
    }


def new_id() -> str:
    """Hex UUID primary key, portable across dialects."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """Create an engine with the right pragmas/pooling for the dialect."""
    if url.startswith("sqlite"):
        is_memory = ":memory:" in url
        if not is_memory:
            db_path = url.removeprefix("sqlite:///")
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url,
            echo=echo,
            connect_args={"check_same_thread": False, "timeout": 15},
            poolclass=StaticPool if is_memory else None,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        return engine
    return create_engine(url, echo=echo, pool_pre_ping=True, pool_size=10, max_overflow=20)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


class Database:
    """Owns one engine + session factory; the unit shared across subsystems."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self.engine = make_engine(url, echo=echo)
        self.session_factory = make_session_factory(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def dispose(self) -> None:
        self.engine.dispose()
