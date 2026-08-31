"""Retrieval evaluation (SPEC §10.6): recall@k and MRR per mode + fusion-weight tuning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yantra_server.knowledge.service import KnowledgeService


@dataclass
class EvalCase:
    query: str
    answer_document: str  # the doc (basename) that should be retrieved
    tags: list[str] = field(default_factory=list)


@dataclass
class RetrievalMetrics:
    mode: str
    recall_at_5: float
    recall_at_10: float
    recall_at_30: float
    mrr: float
    cases: int


async def evaluate_retrieval(
    knowledge: KnowledgeService,
    cases: list[EvalCase],
    *,
    collections: list[str],
    mode: str = "hybrid",
) -> RetrievalMetrics:
    from yantra_server.db.base import Database  # noqa: F401  (keeps import graph explicit)

    hits5 = hits10 = hits30 = 0
    reciprocal = 0.0
    for case in cases:
        results = await knowledge.search(case.query, collections=collections, k=30, mode=mode)
        rank = _rank_of(results, case.answer_document, knowledge)
        if rank is not None:
            if rank < 5:
                hits5 += 1
            if rank < 10:
                hits10 += 1
            if rank < 30:
                hits30 += 1
            reciprocal += 1.0 / (rank + 1)
    n = max(1, len(cases))
    return RetrievalMetrics(
        mode=mode,
        recall_at_5=hits5 / n,
        recall_at_10=hits10 / n,
        recall_at_30=hits30 / n,
        mrr=reciprocal / n,
        cases=len(cases),
    )


def _rank_of(results: list[Any], answer_document: str, knowledge: KnowledgeService) -> int | None:
    want = answer_document.lower()
    for index, hit in enumerate(results):
        title = hit.title.lower()
        if want in title or title in want or _doc_matches(hit, want, knowledge):
            return index
    return None


def _doc_matches(hit: Any, want: str, knowledge: KnowledgeService) -> bool:
    doc = knowledge.get_chunk(hit.chunk_id)
    if not doc:
        return False
    path = str(doc.get("path", "")).lower()
    return want in path


def cases_from_truth(truth: dict[str, Any]) -> list[EvalCase]:
    """Build eval cases from a corpus truth.json (each planted fact is a case)."""
    cases: list[EvalCase] = []
    for fact in truth.get("facts", []):
        cases.append(
            EvalCase(
                query=fact["statement"],
                answer_document=fact["doc"],
                tags=list(fact.get("tags", [])),
            )
        )
    return cases
