from sqlalchemy import select

from yantra_server.artifacts import ArtifactStore
from yantra_server.db.base import Database
from yantra_server.db.models import SpanRow
from yantra_server.observe.tracing import force_flush, run_context, span


def _spans(db: Database) -> list[SpanRow]:
    with db.session() as s:
        return list(s.execute(select(SpanRow)).scalars())


def test_span_written_with_attrs(db: Database, tracing: None) -> None:
    with span("llm.call", model="test-model", tokens=42) as handle:
        handle.set("router", {"chosen": "m1", "rejected": []})
    force_flush()
    rows = _spans(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "llm.call"
    assert row.kind == "llm.call"
    assert row.attrs["model"] == "test-model"
    assert row.attrs["router"] == {"chosen": "m1", "rejected": []}
    assert row.end_ns >= row.start_ns


def test_run_context_stamped_and_nested(db: Database, tracing: None) -> None:
    with (
        run_context(run_id="r1", task_id="t1"),
        span("tool.call", tool="read_file"),
        span("retrieval"),
    ):
        pass
    force_flush()
    rows = {r.name: r for r in _spans(db)}
    assert rows["tool.call"].run_id == "r1"
    assert rows["retrieval"].run_id == "r1"
    assert rows["retrieval"].parent_id == rows["tool.call"].id
    assert rows["retrieval"].trace_id == rows["tool.call"].trace_id


def test_large_attr_offloaded_to_artifact(
    db: Database, artifacts: ArtifactStore, tracing: None
) -> None:
    big = "x" * 10_000
    with span("llm.call") as handle:
        handle.set("prompt", big)
    force_flush()
    row = _spans(db)[0]
    stored = row.attrs["prompt"]
    assert isinstance(stored, dict) and stored["size"] == 10_000
    assert artifacts.read_text(stored["artifact_id"]) == big


def test_exception_marks_error(db: Database, tracing: None) -> None:
    try:
        with span("tool.call"):
            raise ValueError("boom")
    except ValueError:
        pass
    force_flush()
    row = _spans(db)[0]
    assert row.status == "error"
    assert "boom" in row.attrs["error"]
