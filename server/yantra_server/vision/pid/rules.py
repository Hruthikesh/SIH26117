"""P&ID rule engine (SPEC §11.2 step 7): predicates over the PIDGraph → findings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .graph import PIDGraph, PIDNode
from .isa51 import is_safety_instrument, loop_of

RELIEF_KINDS = {"relief_valve"}
CHECK_KINDS = {"check_valve"}
BLOCK_KINDS = {"gate_valve", "ball_valve", "globe_valve", "butterfly_valve"}


@dataclass
class Finding:
    rule_id: str
    severity: str
    elements: list[str]
    explanation: str
    standard: str
    confidence: float = 0.9

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "elements": self.elements,
            "explanation": self.explanation,
            "standard": self.standard,
            "confidence": self.confidence,
        }


@dataclass
class RuleSpec:
    id: str
    severity: str
    applies_to: str
    predicate: str
    explanation: str
    standard: str


def load_rulepack(path: Path) -> list[RuleSpec]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs: list[RuleSpec] = []
    for entry in data.get("rules", []):
        specs.append(
            RuleSpec(
                id=entry["id"],
                severity=entry.get("severity", "medium"),
                applies_to=entry.get("applies_to", ""),
                predicate=entry.get("predicate", ""),
                explanation=entry.get("explanation", ""),
                standard=entry.get("standard", ""),
            )
        )
    return specs


class RuleEngine:
    def __init__(self, rulepack: list[RuleSpec], equipment_list: set[str] | None = None) -> None:
        self.rulepack = rulepack
        self.equipment_list = equipment_list or set()

    def check(self, graph: PIDGraph) -> list[Finding]:
        findings: list[Finding] = []
        for spec in self.rulepack:
            predicate = getattr(self, f"_p_{spec.predicate}", None)
            if predicate is None:
                continue
            for node in self._applicable_nodes(graph, spec.applies_to):
                ok, elements = predicate(graph, node)
                if not ok:
                    findings.append(
                        Finding(
                            rule_id=spec.id,
                            severity=spec.severity,
                            elements=elements or [node.tag or node.id],
                            explanation=f"{node.tag or node.id}: {spec.explanation}",
                            standard=spec.standard,
                        )
                    )
        return findings

    def _applicable_nodes(self, graph: PIDGraph, applies_to: str) -> list[PIDNode]:
        if applies_to == "pump":
            return graph.nodes_of("centrifugal_pump", "positive_displacement_pump")
        if applies_to == "instrument":
            return [n for n in graph.nodes if n.kind.startswith("instrument_")]
        return graph.nodes_of(applies_to)

    # ------------------------------------------------------------- predicates
    # Each returns (satisfied, involved_element_ids).

    def _p_discharge_has_check_valve(
        self, graph: PIDGraph, node: PIDNode
    ) -> tuple[bool, list[str]]:
        return self._downstream_within(graph, node, CHECK_KINDS, depth=3)

    def _p_discharge_has_relief(self, graph: PIDGraph, node: PIDNode) -> tuple[bool, list[str]]:
        return self._downstream_within(graph, node, RELIEF_KINDS, depth=3)

    def _p_has_block_and_bypass(self, graph: PIDGraph, node: PIDNode) -> tuple[bool, list[str]]:
        if node.attributes.get("no_bypass_by_service"):
            return True, []
        upstream_block = any(n.kind in BLOCK_KINDS for n in graph.upstream(node.id))
        downstream_block = any(n.kind in BLOCK_KINDS for n in graph.downstream(node.id))
        has_bypass = bool(node.attributes.get("has_bypass"))
        return (upstream_block and downstream_block and has_bypass), [node.tag or node.id]

    def _p_vessel_has_relief(self, graph: PIDGraph, node: PIDNode) -> tuple[bool, list[str]]:
        # A relief valve connected to the vessel (either direction) satisfies the rule.
        for _edge, neighbor in graph.neighbors(node.id):
            if neighbor.kind in RELIEF_KINDS or is_safety_instrument(neighbor.tag):
                return True, [node.tag, neighbor.tag]
        return False, [node.tag or node.id]

    def _p_psv_isolation_car_sealed(self, graph: PIDGraph, node: PIDNode) -> tuple[bool, list[str]]:
        isolation = [n for _e, n in graph.neighbors(node.id) if n.kind in BLOCK_KINDS]
        if not isolation:
            return True, []  # no isolation valves → rule not applicable
        all_cso = all(n.attributes.get("car_sealed") == "open" for n in isolation)
        return all_cso, [node.tag] + [n.tag or n.id for n in isolation]

    def _p_connector_paired(self, graph: PIDGraph, node: PIDNode) -> tuple[bool, list[str]]:
        ref = node.attributes.get("reference")
        if not ref:
            return False, [node.tag or node.id]
        paired = any(
            other.id != node.id and other.attributes.get("reference") == ref
            for other in graph.nodes_of("off_page_connector")
        )
        # A connector may pair with a continuation on another sheet; accept a declared ref.
        return bool(ref) and (paired or node.attributes.get("cross_sheet", False)), [
            node.tag or node.id
        ]

    def _p_equipment_in_reference_list(
        self, graph: PIDGraph, node: PIDNode
    ) -> tuple[bool, list[str]]:
        if not self.equipment_list:
            return True, []  # no reference list provided → rule not applicable
        return (node.tag in self.equipment_list), [node.tag or node.id]

    def _p_loop_numbering_consistent(
        self, graph: PIDGraph, node: PIDNode
    ) -> tuple[bool, list[str]]:
        loop = loop_of(node.tag)
        if not loop:
            return True, []
        declared = node.attributes.get("loop")
        return (declared is None or str(declared) == loop), [node.tag or node.id]

    def _downstream_within(
        self, graph: PIDGraph, node: PIDNode, kinds: set[str], depth: int
    ) -> tuple[bool, list[str]]:
        frontier = [node.id]
        seen = {node.id}
        for _ in range(depth):
            nxt: list[str] = []
            for nid in frontier:
                for down in graph.downstream(nid):
                    if down.kind in kinds:
                        return True, [node.tag or node.id, down.tag or down.id]
                    if down.id not in seen:
                        seen.add(down.id)
                        nxt.append(down.id)
            frontier = nxt
        return False, [node.tag or node.id]
