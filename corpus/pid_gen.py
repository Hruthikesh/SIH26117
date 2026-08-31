"""Synthetic P&ID generator (SPEC §20.1): draws ISA-style sheets as SVG, rasterises to PNG,
and writes the ground-truth PIDGraph JSON alongside — training/eval data for the detector
and the rules engine. Deterministic (seeded); no external services.

Deviation (recorded here): rasterisation uses Pillow drawing from the known geometry rather
than an SVG rasteriser, so the bundle needs no cairo/librsvg. The SVG is still emitted for
human viewing; the PNG and the ground-truth graph are generated from the same coordinates,
so detector labels stay exact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Placed:
    id: str
    kind: str
    tag: str
    x: float
    y: float
    w: float
    h: float
    attributes: dict[str, Any] = field(default_factory=dict)

    def bbox(self) -> list[float]:
        return [self.x, self.y, self.x + self.w, self.y + self.h]

    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)


@dataclass
class PlacedEdge:
    id: str
    source: str
    target: str
    line_tag: str = ""
    size_inch: float | None = None
    spec: str = ""
    style: str = "process"


class PIDSheet:
    """One P&ID sheet with a deliberate set of (optionally omitted) design features."""

    def __init__(self, drawing_number: str, title: str, revision: str = "C", seed: int = 0) -> None:
        self.drawing_number = drawing_number
        self.title = title
        self.revision = revision
        self.nodes: list[Placed] = []
        self.edges: list[PlacedEdge] = []
        self._n = 0
        self.width = 1600
        self.height = 1100

    def add(
        self, kind: str, tag: str, x: float, y: float, w: float = 60, h: float = 60, **attrs: Any
    ) -> Placed:
        self._n += 1
        node = Placed(id=f"n{self._n}", kind=kind, tag=tag, x=x, y=y, w=w, h=h, attributes=attrs)
        self.nodes.append(node)
        return node

    def connect(
        self,
        a: Placed,
        b: Placed,
        line_tag: str = "",
        size: float | None = None,
        spec: str = "",
        style: str = "process",
    ) -> None:
        self.edges.append(
            PlacedEdge(
                id=f"e{len(self.edges) + 1}",
                source=a.id,
                target=b.id,
                line_tag=line_tag,
                size_inch=size,
                spec=spec,
                style=style,
            )
        )

    # ------------------------------------------------------------- ground truth

    def truth_graph(self) -> dict[str, Any]:
        return {
            "drawing_number": self.drawing_number,
            "revision": self.revision,
            "title": self.title,
            "nodes": [
                {
                    "id": n.id,
                    "kind": n.kind,
                    "tag": n.tag,
                    "label": n.tag,
                    "bbox": n.bbox(),
                    "page": 1,
                    "attributes": n.attributes,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "id": e.id,
                    "source": e.source,
                    "target": e.target,
                    "line_tag": e.line_tag,
                    "size_inch": e.size_inch,
                    "spec": e.spec,
                    "style": e.style,
                    "flow_direction": "forward",
                }
                for e in self.edges
            ],
            "coverage": 1.0,
        }

    # ------------------------------------------------------------- SVG

    def to_svg(self) -> str:
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}">',
            f'<rect width="{self.width}" height="{self.height}" fill="white"/>',
        ]
        for edge in self.edges:
            a = self._node(edge.source)
            b = self._node(edge.target)
            if a and b:
                ax, ay = a.center()
                bx, by = b.center()
                dash = ' stroke-dasharray="6,4"' if edge.style != "process" else ""
                parts.append(
                    f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="black" stroke-width="2"{dash}/>'
                )
                if edge.line_tag:
                    parts.append(
                        f'<text x="{(ax + bx) / 2}" y="{(ay + by) / 2 - 4}" font-size="11">{edge.line_tag}</text>'
                    )
        for node in self.nodes:
            parts.append(self._svg_symbol(node))
        parts.append(self._svg_title_block())
        parts.append("</svg>")
        return "\n".join(parts)

    def _node(self, node_id: str) -> Placed | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def _svg_symbol(self, n: Placed) -> str:
        cx, cy = n.center()
        tag = f'<text x="{n.x}" y="{n.y - 4}" font-size="12" font-weight="bold">{n.tag}</text>'
        if n.kind in ("centrifugal_pump", "positive_displacement_pump"):
            shape = f'<circle cx="{cx}" cy="{cy}" r="{n.w / 2}" fill="none" stroke="black" stroke-width="2"/>'
        elif n.kind == "vessel":
            shape = f'<rect x="{n.x}" y="{n.y}" width="{n.w}" height="{n.h}" rx="18" fill="none" stroke="black" stroke-width="2"/>'
        elif n.kind == "heat_exchanger":
            shape = f'<circle cx="{cx}" cy="{cy}" r="{n.w / 2}" fill="none" stroke="black" stroke-width="2"/><line x1="{n.x}" y1="{cy}" x2="{n.x + n.w}" y2="{cy}" stroke="black"/>'
        elif n.kind in ("control_valve", "gate_valve", "globe_valve", "ball_valve", "check_valve"):
            shape = f'<polygon points="{n.x},{n.y} {n.x + n.w},{n.y + n.h} {n.x},{n.y + n.h} {n.x + n.w},{n.y}" fill="none" stroke="black" stroke-width="2"/>'
        elif n.kind == "relief_valve":
            shape = f'<polygon points="{n.x},{n.y + n.h} {cx},{n.y} {n.x + n.w},{n.y + n.h}" fill="none" stroke="black" stroke-width="2"/>'
        elif n.kind.startswith("instrument_"):
            shape = f'<circle cx="{cx}" cy="{cy}" r="{n.w / 2}" fill="none" stroke="black" stroke-width="1.5"/>'
        elif n.kind == "off_page_connector":
            shape = f'<polygon points="{n.x},{cy} {cx},{n.y} {n.x + n.w},{cy} {cx},{n.y + n.h}" fill="none" stroke="black" stroke-width="2"/>'
        else:
            shape = f'<rect x="{n.x}" y="{n.y}" width="{n.w}" height="{n.h}" fill="none" stroke="black" stroke-width="2"/>'
        return shape + tag

    def _svg_title_block(self) -> str:
        x, y = self.width - 340, self.height - 90
        return (
            f'<rect x="{x}" y="{y}" width="330" height="80" fill="none" stroke="black" stroke-width="2"/>'
            f'<text x="{x + 8}" y="{y + 22}" font-size="13">TITLE: {self.title}</text>'
            f'<text x="{x + 8}" y="{y + 44}" font-size="13">DRAWING NO: {self.drawing_number}</text>'
            f'<text x="{x + 8}" y="{y + 66}" font-size="13">REV: {self.revision}</text>'
        )

    # ------------------------------------------------------------- PNG (Pillow)

    def to_png(self, path: Path, scale: float = 2.0) -> None:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (int(self.width * scale), int(self.height * scale)), "white")
        draw = ImageDraw.Draw(img)
        for edge in self.edges:
            a, b = self._node(edge.source), self._node(edge.target)
            if a and b:
                ax, ay = a.center()
                bx, by = b.center()
                draw.line([ax * scale, ay * scale, bx * scale, by * scale], fill="black", width=2)
                if edge.line_tag:
                    draw.text(
                        (((ax + bx) / 2) * scale, ((ay + by) / 2 - 12) * scale),
                        edge.line_tag,
                        fill="black",
                    )
        for n in self.nodes:
            self._png_symbol(draw, n, scale)
        # title block
        tx, ty = (self.width - 340) * scale, (self.height - 90) * scale
        draw.rectangle([tx, ty, tx + 330 * scale, ty + 80 * scale], outline="black", width=2)
        draw.text((tx + 8, ty + 8), f"TITLE: {self.title}", fill="black")
        draw.text((tx + 8, ty + 28), f"DRAWING NO: {self.drawing_number}", fill="black")
        draw.text((tx + 8, ty + 48), f"REV: {self.revision}", fill="black")
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)

    def _png_symbol(self, draw: Any, n: Placed, scale: float) -> None:
        x0, y0, x1, y1 = n.x * scale, n.y * scale, (n.x + n.w) * scale, (n.y + n.h) * scale
        cx, cy = (n.x + n.w / 2) * scale, (n.y + n.h / 2) * scale
        r = (n.w / 2) * scale
        if n.kind in (
            "centrifugal_pump",
            "positive_displacement_pump",
            "heat_exchanger",
        ) or n.kind.startswith("instrument_"):
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="black", width=2)
        elif n.kind == "vessel":
            draw.rounded_rectangle([x0, y0, x1, y1], radius=18 * scale, outline="black", width=2)
        elif n.kind == "relief_valve":
            draw.polygon([(x0, y1), (cx, y0), (x1, y1)], outline="black", width=2)
        elif n.kind == "off_page_connector":
            draw.polygon([(x0, cy), (cx, y0), (x1, cy), (cx, y1)], outline="black", width=2)
        elif "valve" in n.kind:
            draw.polygon([(x0, y0), (x1, y1), (x0, y1), (x1, y0)], outline="black", width=2)
        else:
            draw.rectangle([x0, y0, x1, y1], outline="black", width=2)
        draw.text((x0, y0 - 14 * scale), n.tag, fill="black")


def build_unit3_lpg_sheet(*, seed_deviations: bool = True) -> PIDSheet:
    """The Unit-3 LPG loading sheet from the demo (P-3101A/B, V-3104, PSV-3105).

    With seed_deviations=True it plants three findable defects:
      1. P-3101B discharge missing a check valve
      2. control valve FCV-3201 without a bypass
      3. vessel V-3110 with no PSV
    """
    sheet = PIDSheet("3-1201", "Unit 3 LPG Recovery - Product Pumps", revision="C")

    v3104 = sheet.add("vessel", "V-3104", 700, 120, 140, 90)
    psv = sheet.add("relief_valve", "PSV-3105", 760, 40, 40, 50)
    sheet.connect(v3104, psv, style="process")

    pa = sheet.add("centrifugal_pump", "P-3101A", 200, 400)
    pb = sheet.add("centrifugal_pump", "P-3101B", 200, 560)
    ca = sheet.add("check_valve", "", 320, 410, 40, 40)
    # P-3101B: (deviation 1) NO check valve when seeding defects
    cb = None if seed_deviations else sheet.add("check_valve", "", 320, 570, 40, 40)

    fcv = sheet.add("control_valve", "FCV-3201", 480, 300, 50, 50, has_bypass=not seed_deviations)
    block_up = sheet.add("gate_valve", "", 420, 305, 40, 40)
    block_dn = sheet.add("gate_valve", "", 560, 305, 40, 40)

    ft = sheet.add("instrument_field", "FT-3201", 480, 200, 44, 44, loop="3201")
    fic = sheet.add("instrument_dcs", "FIC-3201", 480, 120, 44, 44, loop="3201")
    lt = sheet.add("instrument_field", "LT-3104", 860, 150, 44, 44, loop="3104")

    v3110 = sheet.add("vessel", "V-3110", 1000, 400, 140, 90)  # (deviation 3) no PSV

    opc = sheet.add(
        "off_page_connector", "OPC-1", 1300, 300, 40, 40, reference="3-1202-A", cross_sheet=True
    )

    sheet.connect(pa, ca, line_tag='6"-P-1201-A1A', size=6, spec="A1A")
    sheet.connect(ca, block_up, line_tag='6"-P-1201-A1A', size=6, spec="A1A")
    sheet.connect(block_up, fcv, line_tag='6"-P-1201-A1A', size=6, spec="A1A")
    sheet.connect(fcv, block_dn, line_tag='6"-P-1201-A1A', size=6, spec="A1A")
    sheet.connect(block_dn, v3104, line_tag='6"-P-1201-A1A', size=6, spec="A1A")
    if cb is not None:
        sheet.connect(pb, cb, line_tag='6"-P-1202-A1A', size=6, spec="A1A")
        sheet.connect(cb, v3104, line_tag='6"-P-1202-A1A', size=6, spec="A1A")
    else:
        sheet.connect(pb, v3104, line_tag='6"-P-1202-A1A', size=6, spec="A1A")
    sheet.connect(ft, fic, style="instrument_signal")
    sheet.connect(ft, fcv, style="instrument_signal")
    sheet.connect(lt, v3104, style="instrument_signal")
    sheet.connect(v3104, v3110, line_tag='4"-P-1203-A1A', size=4, spec="A1A")
    sheet.connect(v3110, opc, line_tag='4"-P-1204-A1A', size=4, spec="A1A")

    # control loop 3201
    return sheet


def generate_pids(out_dir: Path) -> dict[str, Any]:
    """Write the demo P&ID (PNG + SVG + ground truth) and return a manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = build_unit3_lpg_sheet(seed_deviations=True)
    png_path = out_dir / "PID_3-1201_RevC.png"
    svg_path = out_dir / "PID_3-1201_RevC.svg"
    truth_path = out_dir / "PID_3-1201_RevC.truth.json"
    sheet.to_png(png_path)
    svg_path.write_text(sheet.to_svg(), encoding="utf-8")
    truth = sheet.truth_graph()
    truth["planted_deviations"] = [
        {"rule_id": "pump_discharge_check_valve", "element": "P-3101B"},
        {"rule_id": "control_valve_bypass", "element": "FCV-3201"},
        {"rule_id": "psv_on_vessel", "element": "V-3110"},
    ]
    truth_path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return {"png": str(png_path), "svg": str(svg_path), "truth": str(truth_path), "graph": truth}
