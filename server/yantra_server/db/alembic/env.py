"""Alembic environment. URL comes from -x db_url, $YANTRA_DB_URL, or the resolved config."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from yantra_server.db import models  # noqa: F401  (registers all tables on Base.metadata)
from yantra_server.db.base import Base

config = context.config
target_metadata = Base.metadata


def _resolve_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    if url := x_args.get("db_url"):
        return url
    if url := os.environ.get("YANTRA_DB_URL"):
        return url
    if url := config.get_main_option("sqlalchemy.url"):
        return url
    from yantra_server.config import load_config

    return load_config().config.db_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-safe ALTERs
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
