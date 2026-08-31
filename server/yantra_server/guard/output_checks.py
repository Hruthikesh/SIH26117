"""Output checks (SPEC §16.3): numbers cited, units consistent, no dangling citations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION_MARKER = re.compile(r"\[\[c:([^\]]+)\]\]")
NUMBER_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s?(bar|barg|mm|mm/year|MW|kW|°C|C|%|Nm|mm/s|h|hours|mA|kPa|MPa)?"
)
UNIT_ALIASES = {"c": "°C", "hours": "h"}


@dataclass
class OutputReport:
    unresolved_citations: list[str] = field(default_factory=list)
    uncited_numbers: list[str] = field(default_factory=list)
    unit_issues: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not (self.unresolved_citations or self.unit_issues)


def check_output(text: str, known_chunk_ids: set[str] | None = None) -> OutputReport:
    report = OutputReport()
    for marker in CITATION_MARKER.findall(text):
        cid = marker.split(":")[-1] if ":" in marker else marker
        if known_chunk_ids is not None and cid not in known_chunk_ids:
            report.unresolved_citations.append(marker)
    # numbers with a unit but no nearby citation are flagged (advisory)
    for match in NUMBER_RE.finditer(text):
        if not match.group(2):
            continue
        window = text[max(0, match.start() - 80) : match.end() + 80]
        if not CITATION_MARKER.search(window):
            report.uncited_numbers.append(match.group(0).strip())
    report.unit_issues = _unit_consistency(text)
    return report


def _unit_consistency(text: str) -> list[str]:
    """Catch an obvious unit contradiction: the same quantity in two incompatible units.

    Deliberately conservative — only flags a level/length quantity given as both cm and m in
    close proximity (the tank_gauging-style bug), to avoid false positives on legitimate
    mixed-unit reports."""
    issues: list[str] = []
    if re.search(r"\bcm\b", text) and re.search(r"\blevel\b.{0,40}\bm\b", text, re.IGNORECASE):
        issues.append("level reported in both cm and m — check unit conversion")
    return issues


def strip_unresolved_markers(text: str, known_chunk_ids: set[str]) -> str:
    """Remove citation markers whose chunk id is not known (SPEC §16.3 no dangling markers)."""

    def repl(match: re.Match[str]) -> str:
        marker = match.group(1)
        cid = marker.split(":")[-1] if ":" in marker else marker
        return match.group(0) if cid in known_chunk_ids else ""

    return CITATION_MARKER.sub(repl, text)
