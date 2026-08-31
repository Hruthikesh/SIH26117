"""Shared knowledge-plane types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Block:
    """A parsed unit of content with its location."""

    text: str
    kind: str = "prose"  # prose|table|code|figure|heading
    page: int = 1
    bbox: tuple[float, float, float, float] | None = None
    section_path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedPage:
    page_no: int
    blocks: list[Block] = field(default_factory=list)
    kind: str = "text"  # text|table|drawing|photo|form
    has_text_layer: bool = True
    text_quality: float = 1.0


@dataclass
class ParsedDocument:
    title: str
    doc_type: str = "unknown"
    language: str = "en"
    pages: list[ParsedPage] = field(default_factory=list)
    revision: str | None = None
    doc_number: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def all_blocks(self) -> list[Block]:
        return [block for page in self.pages for block in page.blocks]

    def full_text(self, limit: int | None = None) -> str:
        text = "\n\n".join(b.text for b in self.all_blocks() if b.text.strip())
        return text[:limit] if limit else text


@dataclass
class Chunk:
    text: str
    page_start: int
    page_end: int
    section_path: str
    kind: str = "prose"
    token_count: int = 0
    context_prefix: str = ""
    parent_index: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    title: str
    path: str
    page: int | None
    section: str
    text: str
    score: float
    revision: str | None = None
    doc_type: str | None = None
    source: str = "hybrid"  # lexical|dense|visual|hybrid
    snippet: str = ""

    def citation(self) -> str:
        rev = f" Rev {self.revision}" if self.revision else ""
        page = f" p.{self.page}" if self.page is not None else ""
        return f"{self.title}{rev}{page}"
