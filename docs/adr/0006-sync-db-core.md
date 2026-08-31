# 0006 — Synchronous SQLAlchemy core, thread-offloaded from async code

**Status:** accepted (M0).

**Context.** The server is asyncio (FastAPI, streaming); the DB is SQLite (WAL) on
`lite`/`standard` and Postgres on `refinery`. SQLite drivers are fundamentally synchronous
(aiosqlite is a thread wrapper), Alembic is sync, and the tracer/audit writers are called
from sync contexts (CLI, exporters) too.

**Decision.** One sync SQLAlchemy 2 engine + sessionmaker. Async code calls repositories via
`anyio.to_thread` (FastAPI's threadpool); the span exporter batches writes on its own thread.
No aiosqlite/asyncpg dual stack.

**Consequences.** Simpler code and tests, one Alembic path; DB throughput is bounded by the
threadpool, which is far above the write rates involved (spans are batched). Revisit only if
`refinery`-scale tracing shows contention.
