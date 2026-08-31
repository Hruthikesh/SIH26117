"""Document classification (SPEC §10.3 step 2): type, revision, page-class heuristics.

Cheap heuristics run first; the utility model refines doc_type when a gateway is available.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import ParsedDocument

DOC_TYPE_KEYWORDS: dict[str, list[str]] = {
    "sop": ["standard operating procedure", "sop-", "operating procedure"],
    "pid": ["p&id", "piping and instrumentation", "piping & instrumentation"],
    "datasheet": ["data sheet", "datasheet", "specification sheet"],
    "inspection_report": ["inspection report", "thickness survey", "ndt report", "corrosion"],
    "maintenance_log": ["maintenance log", "work order", "breakdown", "repair record"],
    "manual": ["operation manual", "instruction manual", "vendor manual", "o&m manual"],
    "hazop": ["hazop", "hazard and operability"],
    "moc": ["management of change", "moc-", "change request"],
    "procurement": ["purchase order", "procurement", "requisition"],
    "incident": ["incident report", "near miss", "root cause"],
    "email": ["from:", "subject:", "to:"],
    "datasheet_dcs": ["tag list", "dcs", "io list"],
}

REVISION_RE = re.compile(r"\b(?:Rev|Revision|Issue)\.?\s?([A-Z0-9]{1,3})\b", re.IGNORECASE)
DOC_NUMBER_RE = re.compile(
    r"\b(?:DWG|DOC|DRG|DRAWING)\.?\s?(?:NO\.?)?\s?([A-Z0-9][A-Z0-9\-/]{3,})\b", re.IGNORECASE
)


def classify_document(doc: ParsedDocument, path: Path) -> ParsedDocument:
    sample = (path.name + "\n" + doc.full_text(4000)).lower()
    if doc.doc_type in ("email", "code"):
        pass  # parser already knows
    else:
        doc.doc_type = _guess_type(sample, path)
    text = doc.full_text(6000)
    if match := REVISION_RE.search(text):
        doc.revision = match.group(1).upper()
    if match := DOC_NUMBER_RE.search(text):
        doc.doc_number = match.group(1).upper()
    doc.language = "en"
    return doc


def _guess_type(sample: str, path: Path) -> str:
    scores: dict[str, int] = {}
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in sample)
        if score:
            scores[doc_type] = score
    if scores:
        return max(scores, key=lambda k: scores[k])
    # fall back to extension-based hints
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return "drawing"
    if suffix == ".csv":
        return "data"
    return "document"


DOC_TYPE_CHOICES = [
    "sop",
    "pid",
    "datasheet",
    "inspection_report",
    "maintenance_log",
    "manual",
    "hazop",
    "moc",
    "procurement",
    "incident",
    "email",
    "drawing",
    "data",
    "document",
]
