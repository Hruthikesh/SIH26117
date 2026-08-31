from pathlib import Path

import pytest

from yantra_server.artifacts import ArtifactStore
from yantra_server.artifacts.store import ArtifactNotFound


def test_small_payload_stored_inline(artifacts: ArtifactStore) -> None:
    aid = artifacts.put_text("hello", run_id="r1")
    row = artifacts.get(aid)
    assert row.blob is not None and row.path is None
    assert artifacts.read_text(aid) == "hello"
    assert row.sha256 and row.size == 5


def test_large_payload_goes_to_disk(artifacts: ArtifactStore) -> None:
    data = b"x" * (100 * 1024)
    aid = artifacts.put_bytes(data, kind="tool_output")
    row = artifacts.get(aid)
    assert row.blob is None and row.path is not None
    assert Path(row.path).stat().st_size == len(data)
    assert artifacts.read_bytes(aid) == data


def test_json_roundtrip_and_paging(artifacts: ArtifactStore) -> None:
    aid = artifacts.put_text("\n".join(f"line{i}" for i in range(100)))
    assert artifacts.read_text(aid, offset=10, limit=2) == "line10\nline11"


def test_register_external_file(artifacts: ArtifactStore, tmp_path: Path) -> None:
    source = tmp_path / "report.txt"
    source.write_text("content")
    aid = artifacts.put_file(source, kind="render")
    row = artifacts.get(aid)
    assert row.path == str(source) and row.size == 7


def test_missing_artifact_raises(artifacts: ArtifactStore) -> None:
    with pytest.raises(ArtifactNotFound):
        artifacts.get("nope")
