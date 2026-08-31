"""P&ID pipeline orchestrator (SPEC §11.2): produce a PIDGraph from a drawing.

Two paths converge on the same PIDGraph:
- ground-truth sidecar: when a `<image>.truth.json` exists (synthetic corpus, or an
  operator-labelled sheet), the graph is loaded directly — exact topology for demos/evals.
- inference: OCR + ISA-5.1 tag parsing + symbol detection + (heuristic) association into a
  graph, for real unlabelled sheets. The model then reasons over whichever graph results.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..ocr import OCREngine
from ..tiling import image_size
from .detect import Detection, SymbolDetector
from .graph import ControlLoop, PIDEdge, PIDGraph, PIDNode
from .isa51 import TagPrefixMap, classify_tag, loop_of, parse_instrument

if TYPE_CHECKING:
    from yantra_server.gateway.service import Gateway

log = logging.getLogger(__name__)


class PIDPipeline:
    def __init__(
        self,
        gateway: Gateway | None = None,
        models_dir: Path | None = None,
        prefixes: TagPrefixMap | None = None,
    ) -> None:
        self.gateway = gateway
        self.detector = SymbolDetector(models_dir)
        self.ocr = OCREngine(gateway)
        self.prefixes = prefixes or TagPrefixMap()

    async def analyze(self, image_path: Path) -> PIDGraph:
        sidecar = image_path.with_suffix(".truth.json")
        if sidecar.is_file():
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            graph = PIDGraph.model_validate(
                {k: v for k, v in data.items() if k != "planted_deviations"}
            )
            graph.control_loops = self._assemble_loops(graph)
            return graph
        return await self._infer(image_path)

    async def _infer(self, image_path: Path) -> PIDGraph:
        image_size(image_path)  # validates the image is readable before detection
        detections = self.detector.detect(image_path)
        text_boxes = await self.ocr.ocr_via_gateway(image_path)

        nodes: list[PIDNode] = []
        for index, det in enumerate(detections):
            tag = self._nearest_tag(det, text_boxes)
            node = PIDNode(
                id=f"n{index + 1}",
                kind=det.kind,
                tag=tag,
                label=tag,
                bbox=(
                    float(det.bbox[0]),
                    float(det.bbox[1]),
                    float(det.bbox[2]),
                    float(det.bbox[3]),
                ),
            )
            if node.kind.startswith("instrument_") and (loop := loop_of(tag)):
                node.attributes["loop"] = loop
            nodes.append(node)

        edges = self._infer_edges(nodes)
        graph = PIDGraph(
            title=image_path.stem,
            nodes=nodes,
            edges=edges,
            coverage=1.0,
        )
        graph.control_loops = self._assemble_loops(graph)
        return graph

    def _nearest_tag(self, det: Detection, text_boxes: list) -> str:  # type: ignore[type-arg]
        cx = (det.bbox[0] + det.bbox[2]) / 2
        cy = (det.bbox[1] + det.bbox[3]) / 2
        best = ""
        best_dist = 1e9
        for box in text_boxes:
            bx = (box.bbox[0] + box.bbox[2]) / 2
            by = (box.bbox[1] + box.bbox[3]) / 2
            if classify_tag(box.text, self.prefixes) is None:
                continue
            dist = ((cx - bx) ** 2 + (cy - by) ** 2) ** 0.5
            if dist < best_dist:
                best_dist, best = dist, box.text.strip()
        return best

    def _infer_edges(self, nodes: list[PIDNode]) -> list[PIDEdge]:
        """Proximity-based edges when line tracing is unavailable: connect each node to its
        nearest neighbour by centre distance. Real line tracing (Hough) refines this on a
        GPU host; the heuristic keeps the graph connected for reasoning."""
        edges: list[PIDEdge] = []
        centers = [
            ((n.bbox[0] + n.bbox[2]) / 2, (n.bbox[1] + n.bbox[3]) / 2) if n.bbox else (0.0, 0.0)
            for n in nodes
        ]
        for i, node in enumerate(nodes):
            nearest = -1
            nearest_dist = 1e9
            for j in range(len(nodes)):
                if i == j:
                    continue
                dist = (
                    (centers[i][0] - centers[j][0]) ** 2 + (centers[i][1] - centers[j][1]) ** 2
                ) ** 0.5
                if dist < nearest_dist:
                    nearest_dist, nearest = dist, j
            if nearest >= 0 and nearest_dist < 400:
                edges.append(PIDEdge(id=f"e{i + 1}", source=node.id, target=nodes[nearest].id))
        return edges

    def _assemble_loops(self, graph: PIDGraph) -> list[ControlLoop]:
        loops: dict[str, list[str]] = {}
        for node in graph.nodes:
            if not node.kind.startswith("instrument_") and node.kind != "control_valve":
                continue
            loop = loop_of(node.tag)
            if loop:
                loops.setdefault(loop, []).append(node.id)
        result: list[ControlLoop] = []
        for loop_number, ids in sorted(loops.items()):
            tags = [graph.node(i).tag for i in ids if graph.node(i)]  # type: ignore[union-attr]
            narrative = self._loop_narrative(loop_number, tags)
            result.append(ControlLoop(loop_number=loop_number, elements=ids, narrative=narrative))
        return result

    def _loop_narrative(self, loop_number: str, tags: list[str]) -> str:
        roles = []
        for tag in tags:
            inst = parse_instrument(tag)
            if inst is None:
                continue
            fn = ", ".join(inst.functions) or inst.measured_variable
            roles.append(f"{tag} ({fn})")
        return f"Loop {loop_number}: " + " → ".join(roles) if roles else f"Loop {loop_number}"
