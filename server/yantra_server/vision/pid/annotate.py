"""Annotated overlay (SPEC §11.2 step 8): boxes, tags, findings highlighted on the drawing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SEVERITY_COLOR = {"high": (220, 40, 40), "medium": (230, 150, 30), "low": (60, 130, 220)}


def annotate_pid(
    image_path: Path,
    graph: Any,
    findings: list[Any],
    out_path: Path,
) -> Path:
    """Draw node boxes + tags, and outline elements named in findings by severity."""
    from PIL import Image, ImageDraw

    finding_elements: dict[str, str] = {}
    for finding in findings:
        for element in getattr(finding, "elements", []) or finding.get("elements", []):
            finding_elements[element] = getattr(finding, "severity", None) or finding.get(
                "severity", "medium"
            )

    with Image.open(image_path) as base:
        img = base.convert("RGB")
        draw = ImageDraw.Draw(img)
        for node in graph.nodes:
            if not node.bbox:
                continue
            x0, y0, x1, y1 = node.bbox
            severity = finding_elements.get(node.tag) or finding_elements.get(node.id)
            if severity:
                color = SEVERITY_COLOR.get(severity, (230, 150, 30))
                draw.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], outline=color, width=4)
                draw.text((x0, y1 + 2), f"⚠ {severity}", fill=color)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=(30, 160, 90), width=1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
    return out_path
