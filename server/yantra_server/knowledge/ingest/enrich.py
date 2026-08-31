"""Enrichment (SPEC §10.3 step 5): document/section summaries + per-chunk contextual prefix.

Summaries cost O(sections) model calls, not O(chunks): the contextual prefix for each chunk
is composed from the document + section summaries, keeping enrichment affordable at scale.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..types import Chunk, ParsedDocument


@dataclass
class Enrichment:
    document_summary: str
    section_summaries: dict[str, str]


async def summarize(gateway: object, doc: ParsedDocument) -> Enrichment:
    """Document + section summaries via the utility role; degrades to extractive on failure."""
    from yantra_server.gateway.engines.base import ChatMessage, Decoding
    from yantra_server.gateway.service import Gateway, ModelRequest

    gw = gateway if isinstance(gateway, Gateway) else None
    doc_text = doc.full_text(6000)
    document_summary = _extractive(doc_text, 400)
    if gw is not None:
        try:
            result = await gw.chat(
                ModelRequest(
                    role="utility",
                    messages=[
                        ChatMessage(
                            role="system",
                            content="Summarise this industrial document in <=120 words. "
                            "State what it is, the equipment/area it covers, and its purpose.",
                        ),
                        ChatMessage(role="user", content=doc_text),
                    ],
                    decoding=Decoding(temperature=0.0, max_tokens=200),
                    priority=1,
                )
            )
            document_summary = str(result.parsed)[:800]
        except Exception:
            pass

    section_summaries: dict[str, str] = {}
    sections = _sections(doc)
    for name, text in list(sections.items())[:30]:
        section_summaries[name] = _extractive(text, 200)
    return Enrichment(document_summary=document_summary, section_summaries=section_summaries)


def contextual_prefix(chunk: Chunk, doc: ParsedDocument, enrichment: Enrichment) -> str:
    """1-2 sentences placing the chunk in the document (SPEC §10.3 step 5b)."""
    parts = [f"From {doc.title}"]
    if doc.doc_type and doc.doc_type != "document":
        parts.append(f"({doc.doc_type.replace('_', ' ')})")
    if chunk.section_path:
        parts.append(f"section '{chunk.section_path}'")
    prefix = " ".join(parts) + "."
    section_summary = enrichment.section_summaries.get(chunk.section_path)
    if section_summary:
        prefix += f" {section_summary[:160]}"
    elif enrichment.document_summary:
        prefix += f" {enrichment.document_summary[:160]}"
    return prefix


def _sections(doc: ParsedDocument) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    for block in doc.all_blocks():
        sections.setdefault(block.section_path, []).append(block.text)
    return {name: "\n".join(texts) for name, texts in sections.items() if any(texts)}


def _extractive(text: str, limit: int) -> str:
    """First sentences up to `limit` chars - a cheap, deterministic fallback summary."""
    import re

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out = ""
    for sentence in sentences:
        if len(out) + len(sentence) > limit:
            break
        out += sentence + " "
    return out.strip() or text[:limit]
