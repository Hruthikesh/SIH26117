"""Content-addressed artifact storage: small payloads in the DB, large ones on disk."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from yantra_server.db.base import Database, new_id
from yantra_server.db.models import ArtifactRow

BLOB_THRESHOLD = 64 * 1024  # bytes; larger payloads go to disk


class ArtifactNotFound(Exception):
    pass


class ArtifactStore:
    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _disk_path(self, artifact_id: str) -> Path:
        d = self.root / artifact_id[:2]
        d.mkdir(parents=True, exist_ok=True)
        return d / artifact_id

    def put_bytes(
        self,
        data: bytes,
        *,
        kind: str,
        mime: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        artifact_id = new_id()
        sha = hashlib.sha256(data).hexdigest()
        path: str | None = None
        blob: bytes | None = data
        if len(data) > BLOB_THRESHOLD:
            disk = self._disk_path(artifact_id)
            disk.write_bytes(data)
            path, blob = str(disk), None
        with self.db.session() as s:
            s.add(
                ArtifactRow(
                    id=artifact_id,
                    run_id=run_id,
                    task_id=task_id,
                    kind=kind,
                    path=path,
                    blob=blob,
                    mime=mime,
                    sha256=sha,
                    size=len(data),
                    meta=meta or {},
                )
            )
        return artifact_id

    def put_text(self, text: str, *, kind: str = "text", **kw: Any) -> str:
        return self.put_bytes(text.encode("utf-8"), kind=kind, mime="text/plain", **kw)

    def put_json(self, obj: Any, *, kind: str = "json", **kw: Any) -> str:
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        return self.put_bytes(data, kind=kind, mime="application/json", **kw)

    def put_file(
        self,
        source: Path,
        *,
        kind: str = "file",
        mime: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        meta: dict[str, Any] | None = None,
        copy: bool = False,
    ) -> str:
        """Register an existing file; with copy=True it is duplicated into the store."""
        artifact_id = new_id()
        data_size = source.stat().st_size
        sha = hashlib.sha256()
        with source.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                sha.update(chunk)
        target = source
        if copy:
            target = self._disk_path(artifact_id)
            shutil.copy2(source, target)
        with self.db.session() as s:
            s.add(
                ArtifactRow(
                    id=artifact_id,
                    run_id=run_id,
                    task_id=task_id,
                    kind=kind,
                    path=str(target),
                    mime=mime,
                    sha256=sha.hexdigest(),
                    size=data_size,
                    meta=meta or {},
                )
            )
        return artifact_id

    def get(self, artifact_id: str) -> ArtifactRow:
        with self.db.session() as s:
            row = s.get(ArtifactRow, artifact_id)
            if row is None:
                raise ArtifactNotFound(artifact_id)
            return row

    def read_bytes(self, artifact_id: str) -> bytes:
        row = self.get(artifact_id)
        if row.blob is not None:
            return row.blob
        if row.path:
            return Path(row.path).read_bytes()
        return b""

    def read_text(self, artifact_id: str, offset: int = 0, limit: int | None = None) -> str:
        """Page through a text artifact by line offset/limit (read_artifact tool contract)."""
        text = self.read_bytes(artifact_id).decode("utf-8", errors="replace")
        if offset == 0 and limit is None:
            return text
        lines = text.splitlines()
        window = lines[offset : offset + limit if limit is not None else None]
        return "\n".join(window)
