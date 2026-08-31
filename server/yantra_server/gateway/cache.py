"""Semantic response cache + embedding cache (SPEC §7.2). Exact-match, temperature-0 only."""

from __future__ import annotations

import hashlib
import json
import struct
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, update

from yantra_server.db.base import Database, utcnow
from yantra_server.db.models import EmbeddingCacheRow, GatewayCacheRow

from .engines.base import ChatResult, Constraint, EngineChatRequest


def _normalize_messages(request: EngineChatRequest) -> str:
    parts: list[str] = []
    for message in request.messages:
        parts.append(f"{message.role}\x1f{message.text().strip()}")
        if isinstance(message.content, list):
            for part in message.content:
                if getattr(part, "kind", "") == "image":
                    parts.append(
                        f"img\x1f{getattr(part, 'path', '') or getattr(part, 'data_b64', '')[:64]}"
                    )
    return "\x1e".join(parts)


def response_cache_key(request: EngineChatRequest) -> str | None:
    """None when the call is not cacheable (sampling, or streaming side effects don't matter)."""
    if request.decoding.temperature != 0.0:
        return None
    constraint = request.constraint
    constraint_repr = (
        json.dumps(constraint.model_dump(mode="json"), sort_keys=True) if constraint else ""
    )
    tools_repr = json.dumps([t.model_dump(mode="json") for t in request.tools], sort_keys=True)
    material = "\x1d".join(
        [
            request.model,
            _normalize_messages(request),
            constraint_repr,
            tools_repr,
            str(request.decoding.max_tokens),
            str(request.decoding.reasoning_effort),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, db: Database, ttl_s: int = 86400) -> None:
        self.db = db
        self.ttl_s = ttl_s

    def get(self, key: str) -> ChatResult | None:
        with self.db.session() as s:
            row = s.get(GatewayCacheRow, key)
            if row is None:
                return None
            if row.expires_at is not None and _aware(row.expires_at) < utcnow():
                s.delete(row)
                return None
            s.execute(
                update(GatewayCacheRow)
                .where(GatewayCacheRow.key == key)
                .values(hits=GatewayCacheRow.hits + 1)
            )
            return ChatResult.model_validate(row.response)

    def put(self, key: str, model: str, result: ChatResult) -> None:
        with self.db.session() as s:
            s.merge(
                GatewayCacheRow(
                    key=key,
                    model=model,
                    response=result.model_dump(mode="json"),
                    expires_at=utcnow() + timedelta(seconds=self.ttl_s),
                )
            )

    def purge_expired(self) -> int:
        with self.db.session() as s:
            result = s.execute(
                delete(GatewayCacheRow).where(
                    GatewayCacheRow.expires_at.is_not(None), GatewayCacheRow.expires_at < utcnow()
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)


def _aware(dt: Any) -> Any:
    """SQLite returns naive datetimes; treat them as UTC (they were written as UTC)."""
    from datetime import UTC

    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"<{dim}f", blob))


class EmbeddingCache:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def key_for(model: str, text: str) -> str:
        return f"{model}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def get_many(self, model: str, texts: list[str]) -> dict[int, list[float]]:
        found: dict[int, list[float]] = {}
        with self.db.session() as s:
            for index, text in enumerate(texts):
                row = s.get(EmbeddingCacheRow, self.key_for(model, text))
                if row is not None:
                    found[index] = _unpack(row.vector, row.dim)
        return found

    def put_many(self, model: str, pairs: list[tuple[str, list[float]]]) -> list[list[float]]:
        """Store vectors; returns them float32-normalised so fresh and cached reads agree."""
        normalized: list[list[float]] = []
        with self.db.session() as s:
            for text, vector in pairs:
                packed = _pack(vector)
                normalized.append(_unpack(packed, len(vector)))
                s.merge(
                    EmbeddingCacheRow(
                        key=self.key_for(model, text),
                        model=model,
                        dim=len(vector),
                        vector=packed,
                    )
                )
        return normalized


def content_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def cacheable_constraint(constraint: Constraint | None) -> Any:
    return constraint.model_dump(mode="json") if constraint else None
