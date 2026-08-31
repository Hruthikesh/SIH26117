"""Custom OTel span exporter writing to the local spans table (SQLite or Postgres)."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from yantra_server.db.base import Database
from yantra_server.db.models import SpanRow

log = logging.getLogger(__name__)

ATTRS_KEY = "yantra.attrs"  # single JSON attribute carrying the rich attrs dict


class DbSpanExporter(SpanExporter):
    def __init__(self, db: Database) -> None:
        self.db = db

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        rows: list[SpanRow] = []
        for span in spans:
            ctx = span.get_span_context()
            if ctx is None:
                continue
            raw = dict(span.attributes or {})
            attrs: dict[str, Any] = {}
            if encoded := raw.get(ATTRS_KEY):
                try:
                    attrs = json.loads(str(encoded))
                except (TypeError, json.JSONDecodeError):
                    attrs = {"_undecodable": str(encoded)[:512]}
            for key, value in raw.items():
                if key != ATTRS_KEY and key not in attrs:
                    attrs[key] = value
            status = "ok"
            if span.status is not None and not span.status.is_ok:
                status = "error"
            rows.append(
                SpanRow(
                    id=format(ctx.span_id, "016x"),
                    trace_id=format(ctx.trace_id, "032x"),
                    parent_id=format(span.parent.span_id, "016x") if span.parent else None,
                    name=span.name[:96],
                    kind=str(attrs.get("yantra.kind") or span.name.split(":")[0])[:32],
                    start_ns=span.start_time or 0,
                    end_ns=span.end_time or 0,
                    status=status,
                    attrs=attrs,
                    run_id=_opt_str(attrs.get("run_id")),
                    task_id=_opt_str(attrs.get("task_id")),
                    step_id=_opt_str(attrs.get("step_id")),
                )
            )
        if not rows:
            return SpanExportResult.SUCCESS
        try:
            with self.db.session() as s:
                for row in rows:
                    s.merge(row)
            return SpanExportResult.SUCCESS
        except Exception:
            log.exception("span export failed (%d spans)", len(rows))
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:  # pragma: no cover - nothing to release
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)
