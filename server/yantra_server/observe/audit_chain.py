"""Hash-chained audit log (SPEC §15.2).

hash = sha256(seq ‖ ts ‖ actor ‖ event ‖ payload_hash ‖ prev_hash), fields joined with '|'.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from yantra_server.db.base import Database
from yantra_server.db.models import AuditRow

GENESIS_HASH = "0" * 64


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _entry_hash(
    seq: int, ts: str, actor: str, event: str, payload_hash: str, prev_hash: str
) -> str:
    material = f"{seq}|{ts}|{actor}|{event}|{payload_hash}|{prev_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class VerifyResult:
    ok: bool
    entries: int
    first_bad_seq: int | None = None
    detail: str | None = None


class AuditChain:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._lock = threading.Lock()

    def append(self, actor: str, event: str, payload: dict[str, Any]) -> AuditRow:
        payload_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        for _attempt in range(5):
            with self._lock:
                try:
                    with self.db.session() as s:
                        last = s.execute(
                            select(AuditRow).order_by(AuditRow.seq.desc()).limit(1)
                        ).scalar_one_or_none()
                        seq = (last.seq + 1) if last else 1
                        prev_hash = last.hash if last else GENESIS_HASH
                        ts = datetime.now(UTC).isoformat()
                        row = AuditRow(
                            seq=seq,
                            ts=ts,
                            actor=actor,
                            event=event,
                            payload=payload,
                            payload_hash=payload_hash,
                            prev_hash=prev_hash,
                            hash=_entry_hash(seq, ts, actor, event, payload_hash, prev_hash),
                        )
                        s.add(row)
                    return row
                except IntegrityError:
                    continue  # concurrent writer won the seq; recompute
        raise RuntimeError("audit chain: could not append after 5 attempts")

    def head(self) -> AuditRow | None:
        with self.db.session() as s:
            return s.execute(
                select(AuditRow).order_by(AuditRow.seq.desc()).limit(1)
            ).scalar_one_or_none()

    def count(self) -> int:
        with self.db.session() as s:
            return int(s.execute(select(func.count()).select_from(AuditRow)).scalar_one())

    def verify(self) -> VerifyResult:
        """Recompute every hash and link; an empty chain verifies trivially."""
        prev_hash = GENESIS_HASH
        expected_seq = 1
        checked = 0
        with self.db.session() as s:
            for row in s.execute(select(AuditRow).order_by(AuditRow.seq.asc())).scalars():
                if row.seq != expected_seq:
                    return VerifyResult(False, checked, row.seq, "sequence gap")
                if row.prev_hash != prev_hash:
                    return VerifyResult(False, checked, row.seq, "broken prev_hash link")
                payload_hash = hashlib.sha256(
                    canonical_json(row.payload).encode("utf-8")
                ).hexdigest()
                if payload_hash != row.payload_hash:
                    return VerifyResult(False, checked, row.seq, "payload tampered")
                recomputed = _entry_hash(
                    row.seq, row.ts, row.actor, row.event, row.payload_hash, row.prev_hash
                )
                if recomputed != row.hash:
                    return VerifyResult(False, checked, row.seq, "entry hash mismatch")
                prev_hash = row.hash
                expected_seq += 1
                checked += 1
        return VerifyResult(True, checked)

    def export(self, from_seq: int = 1, to_seq: int | None = None) -> Iterator[str]:
        """JSONL lines carrying the chain segment, verifiable standalone."""
        with self.db.session() as s:
            query = select(AuditRow).where(AuditRow.seq >= from_seq).order_by(AuditRow.seq.asc())
            if to_seq is not None:
                query = query.where(AuditRow.seq <= to_seq)
            for row in s.execute(query).scalars():
                yield json.dumps(
                    {
                        "seq": row.seq,
                        "ts": row.ts,
                        "actor": row.actor,
                        "event": row.event,
                        "payload": row.payload,
                        "payload_hash": row.payload_hash,
                        "prev_hash": row.prev_hash,
                        "hash": row.hash,
                    },
                    ensure_ascii=False,
                    default=str,
                )
