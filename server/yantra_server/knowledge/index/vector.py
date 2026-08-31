"""Qdrant vector index (SPEC §10.2, §10.3 step 7): chunk / document / visual tiers with
quantization. Embedded (local path) for lite/standard, server mode for refinery."""

from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    VectorParams,
)


def _point_id(chunk_id: str) -> str:
    # Qdrant needs UUID or int ids; derive a stable UUID from the chunk id.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


class VectorIndex:
    """One Qdrant client managing the docs/chunks/visual collections."""

    def __init__(self, location: str, *, quantize: bool = True) -> None:
        # location: "server:host:port" / "http://…" for a Qdrant server, otherwise a
        # filesystem path for embedded mode (the default on lite/standard).
        self.embedded = not (location.startswith(("http://", "https://", "server:")))
        if location.startswith(("http://", "https://")):
            self.client = QdrantClient(url=location)
        elif location.startswith("server:"):
            _, _, hostport = location.partition(":")
            host, _, port = hostport.partition(":")
            self.client = QdrantClient(host=host or "127.0.0.1", port=int(port or 6333))
        else:
            self.client = QdrantClient(path=location)
        self.quantize = quantize

    def ensure_collection(self, name: str, dim: int, *, quantize: bool | None = None) -> None:
        if self.client.collection_exists(name):
            return
        quant_cfg = None
        if quantize if quantize is not None else self.quantize:
            quant_cfg = ScalarQuantization(
                scalar=ScalarQuantizationConfig(type=ScalarType.INT8, always_ram=True)
            )
        self.client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE, on_disk=True),
            quantization_config=quant_cfg,
        )

    def upsert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        points = [
            PointStruct(id=_point_id(cid), vector=vec, payload={**payload, "chunk_id": cid})
            for cid, vec, payload in zip(ids, vectors, payloads, strict=True)
        ]
        self.client.upsert(collection_name=collection, points=points, wait=False)

    def search(
        self,
        collection: str,
        vector: list[float],
        *,
        limit: int = 100,
        oversample: float = 3.0,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        if not self.client.collection_exists(collection):
            return []
        query_filter = self._build_filter(filters)
        # Binary/scalar quantization: oversample then rescore from full vectors (SPEC §10.4).
        # Server mode only — embedded Qdrant does exact brute-force search (no rescore).
        params = None
        if not self.embedded:
            from qdrant_client.models import QuantizationSearchParams, SearchParams

            params = SearchParams(
                quantization=QuantizationSearchParams(rescore=True, oversampling=oversample)
            )
        result = self.client.query_points(
            collection_name=collection,
            query=vector,
            limit=limit,
            query_filter=query_filter,
            search_params=params,
            with_payload=True,
        )
        out: list[tuple[str, float, dict[str, Any]]] = []
        for point in result.points:
            payload = dict(point.payload or {})
            out.append((str(payload.get("chunk_id", point.id)), float(point.score), payload))
        return out

    def _build_filter(self, filters: dict[str, Any] | None) -> Filter | None:
        if not filters:
            return None
        must: list[FieldCondition] = []
        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, list):
                must.append(FieldCondition(key=key, match=MatchAny(any=value)))
            else:
                must.append(FieldCondition(key=key, match=MatchValue(value=value)))
        return Filter(must=must) if must else None

    def delete_document(self, collection: str, document_id: str) -> None:
        if not self.client.collection_exists(collection):
            return
        self.client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )

    def count(self, collection: str) -> int:
        if not self.client.collection_exists(collection):
            return 0
        return int(self.client.count(collection).count)

    def snapshot(self, collection: str) -> str | None:
        if not self.client.collection_exists(collection):
            return None
        info = self.client.create_snapshot(collection_name=collection)
        return info.name if info else None

    def close(self) -> None:
        self.client.close()
