"""Structure-aware chunking (SPEC §10.3 step 4): ~400-token children, ~1200-token parents,
never splitting a table row or code function, tables carry their header row."""

from __future__ import annotations

from ..types import Block, Chunk, ParsedDocument


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_document(
    doc: ParsedDocument,
    child_tokens: int = 400,
    parent_tokens: int = 1200,
    overlap_ratio: float = 0.15,
) -> list[Chunk]:
    """Produce child chunks with parent groupings. Parents are appended after children and
    referenced by index so the store can link them."""
    children: list[Chunk] = []
    for block in doc.all_blocks():
        if not block.text.strip():
            continue
        if block.kind == "table":
            children.extend(_chunk_table(block, child_tokens))
        elif block.kind == "code":
            children.extend(_chunk_code(block, child_tokens))
        else:
            children.extend(_chunk_prose(block, child_tokens, overlap_ratio))

    # Parent chunks group consecutive children up to parent_tokens (SPEC §10.4 expansion).
    parents: list[Chunk] = []
    current: list[Chunk] = []
    current_tokens = 0
    for child in children:
        if current and current_tokens + child.token_count > parent_tokens:
            parents.append(_merge_parent(current))
            current, current_tokens = [], 0
        current.append(child)
        current_tokens += child.token_count
    if current:
        parents.append(_merge_parent(current))

    parent_base = len(children)
    for parent_index, parent in enumerate(parents):
        parent.meta["is_parent"] = True
        for child in parent.meta.pop("_children", []):
            child.parent_index = parent_base + parent_index
    return children + parents


def _chunk_prose(block: Block, child_tokens: int, overlap_ratio: float) -> list[Chunk]:
    words = block.text.split()
    if not words:
        return []
    words_per_chunk = max(20, child_tokens * 4 // 5)  # ~0.8 words/token heuristic
    overlap = int(words_per_chunk * overlap_ratio)
    chunks: list[Chunk] = []
    start = 0
    while start < len(words):
        window = words[start : start + words_per_chunk]
        text = " ".join(window)
        chunks.append(
            Chunk(
                text=text,
                page_start=block.page,
                page_end=block.page,
                section_path=block.section_path,
                kind="prose",
                token_count=estimate_tokens(text),
            )
        )
        if start + words_per_chunk >= len(words):
            break
        start += words_per_chunk - overlap
    return chunks


def _chunk_table(block: Block, child_tokens: int) -> list[Chunk]:
    rows = block.text.splitlines()
    if not rows:
        return []
    header = rows[0]
    body = rows[1:] or rows
    chunks: list[Chunk] = []
    current = [header]
    current_tokens = estimate_tokens(header)
    for row in body:
        row_tokens = estimate_tokens(row)
        if current_tokens + row_tokens > child_tokens and len(current) > 1:
            chunks.append(_table_chunk(current, block))
            current = [header, row]  # repeat the header (SPEC §12 header repeat)
            current_tokens = estimate_tokens(header) + row_tokens
        else:
            current.append(row)
            current_tokens += row_tokens
    if len(current) > 1 or not chunks:
        chunks.append(_table_chunk(current, block))
    return chunks


def _table_chunk(rows: list[str], block: Block) -> Chunk:
    text = "\n".join(rows)
    return Chunk(
        text=text,
        page_start=block.page,
        page_end=block.page,
        section_path=block.section_path,
        kind="table",
        token_count=estimate_tokens(text),
        meta=dict(block.meta),
    )


def _chunk_code(block: Block, child_tokens: int) -> list[Chunk]:
    """Split code on top-level def/class boundaries, keeping each unit whole."""
    lines = block.text.splitlines()
    units: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if current and (line.startswith(("def ", "class ", "async def ")) or _is_top_symbol(line)):
            units.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        units.append(current)
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_tokens = 0
    for unit in units:
        text = "\n".join(unit)
        unit_tokens = estimate_tokens(text)
        if buffer and buffer_tokens + unit_tokens > child_tokens:
            chunks.append(_code_chunk(buffer, block))
            buffer, buffer_tokens = [], 0
        buffer.extend(unit)
        buffer_tokens += unit_tokens
    if buffer:
        chunks.append(_code_chunk(buffer, block))
    return chunks


def _is_top_symbol(line: str) -> bool:
    return bool(line) and not line[0].isspace() and line.rstrip().endswith((":", "{"))


def _code_chunk(lines: list[str], block: Block) -> Chunk:
    text = "\n".join(lines)
    return Chunk(
        text=text,
        page_start=block.page,
        page_end=block.page,
        section_path=block.section_path,
        kind="code",
        token_count=estimate_tokens(text),
    )


def _merge_parent(children: list[Chunk]) -> Chunk:
    text = "\n\n".join(c.text for c in children)
    parent = Chunk(
        text=text,
        page_start=children[0].page_start,
        page_end=children[-1].page_end,
        section_path=children[0].section_path,
        kind="parent",
        token_count=sum(c.token_count for c in children),
    )
    parent.meta["_children"] = children
    return parent
