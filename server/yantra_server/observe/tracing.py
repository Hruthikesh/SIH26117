"""Tracing facade (SPEC §15.1): rich-attribute spans over the OTel API.

Attributes of any JSON shape are supported; values over 4 KB are offloaded to the artifact
store and replaced with {artifact_id, preview, size}. run_id/task_id/step_id from the ambient
RunContext are stamped on every span so the trace viewer can filter without joins.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from yantra_server.artifacts import ArtifactStore
from yantra_server.db.base import Database

from .exporter_sqlite import ATTRS_KEY, DbSpanExporter

LARGE_ATTR_BYTES = 4096


@dataclass(frozen=True)
class RunContext:
    run_id: str | None = None
    task_id: str | None = None
    step_id: str | None = None


_EMPTY_RUN_CONTEXT = RunContext()
_run_context: ContextVar[RunContext] = ContextVar("yantra_run_context", default=_EMPTY_RUN_CONTEXT)


@dataclass
class _TracingState:
    provider: TracerProvider | None = None
    artifact_store: ArtifactStore | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_state = _TracingState()


def configure_tracing(
    db: Database, artifact_store: ArtifactStore | None = None, *, batch: bool = True
) -> None:
    """Install the DB exporter as the global tracer provider (idempotent per process)."""
    if _state.provider is not None:
        _state.provider.shutdown()
    provider = TracerProvider()
    exporter = DbSpanExporter(db)
    processor = BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    _state.provider = provider
    _state.artifact_store = artifact_store


def force_flush() -> None:
    if _state.provider is not None:
        _state.provider.force_flush()


def shutdown_tracing() -> None:
    if _state.provider is not None:
        _state.provider.shutdown()
        _state.provider = None


@contextmanager
def run_context(
    run_id: str | None = None, task_id: str | None = None, step_id: str | None = None
) -> Iterator[RunContext]:
    """Bind ids to the ambient context; children spans inherit them automatically."""
    current = _run_context.get()
    updates: dict[str, str] = {}
    if run_id is not None:
        updates["run_id"] = run_id
    if task_id is not None:
        updates["task_id"] = task_id
    if step_id is not None:
        updates["step_id"] = step_id
    token = _run_context.set(replace(current, **updates))
    try:
        yield _run_context.get()
    finally:
        _run_context.reset(token)


def current_run_context() -> RunContext:
    return _run_context.get()


class SpanHandle:
    """Mutable attribute bag flushed into the OTel span at exit."""

    def __init__(self, otel_span: Span) -> None:
        self._span = otel_span
        self.attrs: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self.attrs[key] = _offload_if_large(key, value)

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value)

    def error(self, message: str) -> None:
        self._span.set_status(Status(StatusCode.ERROR, message))
        self.attrs.setdefault("error", message)

    @property
    def span_id(self) -> str:
        return format(self._span.get_span_context().span_id, "016x")

    @property
    def trace_id(self) -> str:
        return format(self._span.get_span_context().trace_id, "032x")


def _offload_if_large(key: str, value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    serialized = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(serialized) <= LARGE_ATTR_BYTES or _state.artifact_store is None:
        return value
    ctx = _run_context.get()
    artifact_id = _state.artifact_store.put_text(
        serialized, kind="span_attr", run_id=ctx.run_id, task_id=ctx.task_id, meta={"attr": key}
    )
    return {"artifact_id": artifact_id, "preview": serialized[:512], "size": len(serialized)}


@contextmanager
def span(name: str, kind: str | None = None, **attrs: Any) -> Iterator[SpanHandle]:
    """Start a span; usable from sync and async code (context is task-local)."""
    tracer = (
        _state.provider.get_tracer("yantra")
        if _state.provider is not None
        else otel_trace.get_tracer("yantra")
    )
    with tracer.start_as_current_span(name, record_exception=True) as otel_span:
        handle = SpanHandle(otel_span)
        ctx = _run_context.get()
        handle.attrs["yantra.kind"] = kind or name.split(":")[0]
        if ctx.run_id:
            handle.attrs["run_id"] = ctx.run_id
        if ctx.task_id:
            handle.attrs["task_id"] = ctx.task_id
        if ctx.step_id:
            handle.attrs["step_id"] = ctx.step_id
        handle.update(attrs)
        try:
            yield handle
        except Exception as exc:
            handle.error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            otel_span.set_attribute(ATTRS_KEY, json.dumps(handle.attrs, default=str))
