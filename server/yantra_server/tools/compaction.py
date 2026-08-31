"""Observation compaction (SPEC §8.5.4): keep head+tail, describe the middle, point to
the full artifact so the model can page with read_artifact."""

from __future__ import annotations

from .base import ToolResult

DEFAULT_HEAD_LINES = 60
DEFAULT_TAIL_LINES = 40
MAX_LINE_CHARS = 400


def compact_text(
    text: str, head: int = DEFAULT_HEAD_LINES, tail: int = DEFAULT_TAIL_LINES
) -> tuple[str, bool]:
    """(compacted, was_truncated). Long lines are clipped; the elision names the gap size."""
    lines = [
        line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + " …[line clipped]"
        for line in text.splitlines()
    ]
    if len(lines) <= head + tail + 5:
        return "\n".join(lines), False
    omitted = len(lines) - head - tail
    compacted = [*lines[:head], f"… [{omitted} lines omitted] …", *lines[-tail:]]
    return "\n".join(compacted), True


def compact_observation(
    result: ToolResult, head: int = DEFAULT_HEAD_LINES, tail: int = DEFAULT_TAIL_LINES
) -> str:
    """The observation string the executor feeds back to the model."""
    parts: list[str] = []
    if not result.ok:
        parts.append(f"ERROR: {result.error}")
    if result.summary and result.summary != result.error:
        parts.append(result.summary)
    if result.content:
        body, truncated = compact_text(result.content, head, tail)
        parts.append(body)
        if truncated and result.artifact_id:
            parts.append(
                f"[full output: artifact {result.artifact_id}, "
                f"use read_artifact(artifact_id, offset) to page]"
            )
    elif result.artifact_id:
        parts.append(f"[result stored as artifact {result.artifact_id}]")
    if result.data:
        summary_data = {k: v for k, v in result.data.items() if k != "sandbox" and _is_small(v)}
        if summary_data:
            import json

            parts.append(json.dumps(summary_data, ensure_ascii=False, default=str)[:1500])
    return "\n".join(p for p in parts if p).strip() or "(empty result)"


def _is_small(value: object) -> bool:
    return len(str(value)) < 600
