"""Image handling policy (SPEC §11.1): overview + tiling + coverage map + DPI-aware render."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Tile:
    row: int
    col: int
    x: int
    y: int
    w: int
    h: int


@dataclass
class CoverageMap:
    """Tracks which tiles the model has actually looked at (SPEC §11.1 point 3)."""

    total_tiles: int
    seen: set[tuple[int, int]] = field(default_factory=set)

    def mark(self, row: int, col: int) -> None:
        self.seen.add((row, col))

    def fraction(self) -> float:
        return len(self.seen) / self.total_tiles if self.total_tiles else 1.0


def image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as img:
        return img.width, img.height


def plan_tiles(width: int, height: int, tile_size: int = 1280, overlap: float = 0.15) -> list[Tile]:
    step = int(tile_size * (1 - overlap))
    tiles: list[Tile] = []
    row = 0
    y = 0
    while y < height:
        col = 0
        x = 0
        while x < width:
            tiles.append(
                Tile(
                    row=row,
                    col=col,
                    x=x,
                    y=y,
                    w=min(tile_size, width - x),
                    h=min(tile_size, height - y),
                )
            )
            if x + tile_size >= width:
                break
            x += step
            col += 1
        if y + tile_size >= height:
            break
        y += step
        row += 1
    return tiles


def overview(path: Path, out_path: Path, max_side: int = 1024) -> Path:
    from PIL import Image

    with Image.open(path) as opened:
        img = opened.convert("RGB")
        scale = min(1.0, max_side / max(img.width, img.height))
        if scale < 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
    return out_path


def crop_tile(path: Path, tile: Tile, out_path: Path) -> Path:
    from PIL import Image

    with Image.open(path) as img:
        cropped = img.convert("RGB").crop((tile.x, tile.y, tile.x + tile.w, tile.y + tile.h))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(out_path)
    return out_path


def zoom_grid(path: Path, rows: int, cols: int, out_dir: Path) -> list[dict[str, Any]]:
    """Numbered tiles for systematic inspection (SPEC §9.2 zoom_grid)."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as opened:
        img = opened.convert("RGB")
        tile_w = img.width // cols
        tile_h = img.height // rows
        tiles: list[dict[str, Any]] = []
        index = 1
        for r in range(rows):
            for c in range(cols):
                box = (c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h)
                tile_path = out_dir / f"tile_{index}.png"
                img.crop(box).save(tile_path)
                tiles.append(
                    {"index": index, "row": r, "col": c, "path": str(tile_path), "box": list(box)}
                )
                index += 1
    return tiles


def render_pdf_page(pdf_path: Path, page_no: int, out_path: Path, dpi: int = 200) -> Path:
    """Rasterise one PDF page at a chosen DPI (drawings 200, text pages 110; SPEC §11.1)."""
    import pymupdf

    with pymupdf.open(pdf_path) as pdf:  # type: ignore[no-untyped-call]
        page = pdf.load_page(page_no - 1)
        matrix = pymupdf.Matrix(dpi / 72, dpi / 72)  # type: ignore[no-untyped-call]
        pix = page.get_pixmap(matrix=matrix)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(out_path)
    return out_path
