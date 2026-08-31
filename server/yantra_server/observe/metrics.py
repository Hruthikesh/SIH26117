"""Prometheus text metrics (SPEC §15.3) for the plant's own scraper."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from yantra_server.db.models import RunRow, SealEventRow, SpanRow

if TYPE_CHECKING:
    from yantra_server.state import AppState


def render_metrics(state: AppState) -> str:
    lines: list[str] = []

    def metric(name: str, value: float, help_text: str, labels: str = "") -> None:
        lines.append(f"# HELP yantra_{name} {help_text}")
        lines.append(f"# TYPE yantra_{name} gauge")
        lines.append(f"yantra_{name}{labels} {value}")

    with state.db.session() as s:
        spans_by_kind: dict[str, int] = {
            str(kind): int(count)
            for kind, count in s.execute(
                select(SpanRow.kind, func.count()).group_by(SpanRow.kind)
            ).all()
        }
        runs_by_status: dict[str, int] = {
            str(status): int(count)
            for status, count in s.execute(
                select(RunRow.status, func.count()).group_by(RunRow.status)
            ).all()
        }
        seal_events = int(s.execute(select(func.count()).select_from(SealEventRow)).scalar_one())

    for kind, count in sorted(spans_by_kind.items()):
        lines.append(f'yantra_spans_total{{kind="{kind}"}} {count}')
    lines.insert(0, "# TYPE yantra_spans_total counter")
    lines.insert(0, "# HELP yantra_spans_total Spans recorded by kind")

    for status, count in sorted(runs_by_status.items()):
        lines.append(f'yantra_runs_total{{status="{status}"}} {count}')

    metric("seal_blocked_total", seal_events, "Blocked egress attempts (all layers)")
    metric("sealed", 1 if state.config.sealed() else 0, "1 when YANTRA_SEALED=1")

    for engine_state in state.supervisor.status():
        healthy = 1 if engine_state["status"] == "healthy" else 0
        lines.append(
            f'yantra_engine_up{{engine="{engine_state["engine_id"]}",replica="{engine_state["replica"]}"}} {healthy}'
        )

    from yantra_server.gateway.supervisor import detect_gpus

    for gpu in detect_gpus():
        lines.append(f'yantra_gpu_vram_mb{{index="{gpu["index"]}"}} {gpu["vram_mb"]}')

    return "\n".join(lines) + "\n"
