"""Weighted Reciprocal Rank Fusion + per-document capping (SPEC §10.4 step 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RRF_K = 60


@dataclass
class Candidate:
    chunk_id: str
    payload: dict[str, Any]
    scores: dict[str, float]  # source -> raw score
    fused: float = 0.0


def weighted_rrf(
    ranked_lists: dict[str, list[tuple[str, float, dict[str, Any]]]],
    weights: dict[str, float],
    *,
    doc_cap_ratio: float = 0.4,
    limit: int = 60,
) -> list[Candidate]:
    """Fuse per-source ranked lists; cap any single document at doc_cap_ratio of the pool."""
    candidates: dict[str, Candidate] = {}
    for source, results in ranked_lists.items():
        weight = weights.get(source, 1.0)
        for rank, (chunk_id, raw, payload) in enumerate(results):
            cand = candidates.get(chunk_id)
            if cand is None:
                cand = Candidate(chunk_id=chunk_id, payload=payload, scores={})
                candidates[chunk_id] = cand
            cand.scores[source] = raw
            cand.fused += weight / (RRF_K + rank + 1)
            # keep the richest payload (prefer one with text)
            if not cand.payload.get("text") and payload.get("text"):
                cand.payload = payload

    ordered = sorted(candidates.values(), key=lambda c: -c.fused)
    if doc_cap_ratio < 1.0:
        ordered = _cap_by_document(ordered, doc_cap_ratio, limit)
    return ordered[:limit]


def _cap_by_document(candidates: list[Candidate], ratio: float, limit: int) -> list[Candidate]:
    max_per_doc = max(1, int(limit * ratio))
    per_doc: dict[str, int] = {}
    kept: list[Candidate] = []
    overflow: list[Candidate] = []
    for cand in candidates:
        doc_id = str(cand.payload.get("document_id", cand.chunk_id))
        if per_doc.get(doc_id, 0) < max_per_doc:
            per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
            kept.append(cand)
        else:
            overflow.append(cand)
    return kept + overflow  # overflow appended so limit still fills if few documents match
