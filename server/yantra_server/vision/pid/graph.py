"""PIDGraph: the structured representation the model reasons over (SPEC §11.2 step 6)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

BBox = tuple[float, float, float, float]


class PIDNode(BaseModel):
    id: str
    kind: str  # symbol class: centrifugal_pump, vessel, control_valve, relief_valve, instrument_*
    tag: str = ""
    label: str = ""
    bbox: BBox | None = None
    page: int = 1
    attributes: dict[str, Any] = Field(default_factory=dict)


class PIDEdge(BaseModel):
    id: str
    source: str
    target: str
    style: str = "process"  # process|instrument_signal|pneumatic|electrical
    line_tag: str = ""
    size_inch: float | None = None
    spec: str = ""
    flow_direction: Literal["forward", "reverse", "unknown"] = "unknown"


class ControlLoop(BaseModel):
    loop_number: str
    elements: list[str] = Field(default_factory=list)  # node ids
    narrative: str = ""


class PIDGraph(BaseModel):
    drawing_number: str = ""
    revision: str = ""
    title: str = ""
    sheet: str = ""
    nodes: list[PIDNode] = Field(default_factory=list)
    edges: list[PIDEdge] = Field(default_factory=list)
    control_loops: list[ControlLoop] = Field(default_factory=list)
    coverage: float = 1.0  # fraction of the sheet inspected (SPEC §11.1)

    # ------------------------------------------------------------- accessors

    def node(self, node_id: str) -> PIDNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def nodes_of(self, *kinds: str) -> list[PIDNode]:
        wanted = set(kinds)
        return [n for n in self.nodes if n.kind in wanted]

    def neighbors(self, node_id: str) -> list[tuple[PIDEdge, PIDNode]]:
        out: list[tuple[PIDEdge, PIDNode]] = []
        for edge in self.edges:
            if edge.source == node_id and (target := self.node(edge.target)):
                out.append((edge, target))
            elif edge.target == node_id and (source := self.node(edge.source)):
                out.append((edge, source))
        return out

    def downstream(self, node_id: str) -> list[PIDNode]:
        out = [self.node(e.target) for e in self.edges if e.source == node_id]
        return [n for n in out if n is not None]

    def upstream(self, node_id: str) -> list[PIDNode]:
        out = [self.node(e.source) for e in self.edges if e.target == node_id]
        return [n for n in out if n is not None]

    def to_networkx(self) -> Any:
        import networkx as nx

        g = nx.DiGraph()
        for node in self.nodes:
            g.add_node(node.id, kind=node.kind, tag=node.tag)
        for edge in self.edges:
            g.add_edge(edge.source, edge.target, style=edge.style, tag=edge.line_tag)
        return g

    def equipment_list(self) -> list[dict[str, Any]]:
        rows = []
        for node in self.nodes:
            if node.kind in (
                "centrifugal_pump",
                "positive_displacement_pump",
                "vessel",
                "column",
                "heat_exchanger",
                "fired_heater",
                "compressor",
                "reactor",
            ):
                rows.append({"tag": node.tag, "type": node.kind, "label": node.label})
        return rows

    def instrument_index(self) -> list[dict[str, Any]]:
        return [
            {"tag": n.tag, "type": n.kind, "loop": n.attributes.get("loop", "")}
            for n in self.nodes
            if n.kind.startswith("instrument_")
        ]

    def line_list(self) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for edge in self.edges:
            if edge.line_tag and edge.line_tag not in seen:
                seen[edge.line_tag] = {
                    "tag": edge.line_tag,
                    "size_inch": edge.size_inch,
                    "spec": edge.spec,
                    "style": edge.style,
                }
        return list(seen.values())
