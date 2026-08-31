"""Equipment/instrument/standard tag extraction (SPEC §10.3 step 5).

Patterns are operator-configurable via knowledge/tag_patterns.yaml; sensible ISA/plant
defaults are baked in so extraction works out of the box.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATTERNS: dict[str, str] = {
    # Instruments: ISA-5.1 loop tags, e.g. FIC-3201A, PSV-101, LT-3104
    "instrument": r"\b[A-Z]{2,4}-?\d{2,5}[A-Z]?\b",
    # Equipment: P-101A (pump), E-201 (exchanger), V-301 (vessel), T-401, C-501, K-601
    "equipment": r"\b[A-Z]{1,2}-\d{2,4}[A-Z]?(?:/[A-Z])?\b",
    # Line numbers: 6"-P-1201-A1A-IH
    "line": r'\b\d{1,2}"-[A-Z]+-\d{3,5}-[A-Z0-9]+(?:-[A-Z]{1,3})?\b',
    # Standards: API 610, ASME B31.3, ASTM A106, IS 2062, OISD-STD-118
    "standard": r"\b(?:API|ASME|ASTM|IS|IEC|ISO|OISD|ANSI|NACE)[\s-]?[A-Z0-9.\-]{2,12}\b",
    # Revisions: Rev C, Rev 2, Issue 3
    "revision": r"\b(?:Rev|Issue|Revision)\.?\s?[A-Z0-9]{1,3}\b",
}


@lru_cache(maxsize=8)
def _compiled(patterns_key: str) -> dict[str, re.Pattern[str]]:
    # patterns_key is a json-ish string used only as a cache key; ignore its value here.
    return {name: re.compile(pat) for name, pat in DEFAULT_PATTERNS.items()}


def load_patterns(patterns_file: Path | None) -> dict[str, re.Pattern[str]]:
    patterns = dict(DEFAULT_PATTERNS)
    if patterns_file and patterns_file.is_file():
        try:
            data = yaml.safe_load(patterns_file.read_text(encoding="utf-8")) or {}
            for name, pat in (data.get("patterns", {}) or {}).items():
                patterns[str(name)] = str(pat)
        except (yaml.YAMLError, re.error):
            pass
    compiled: dict[str, re.Pattern[str]] = {}
    for name, pat in patterns.items():
        try:
            compiled[name] = re.compile(pat)
        except re.error:
            continue
    return compiled


def extract_tags(
    text: str, patterns: dict[str, re.Pattern[str]] | None = None
) -> dict[str, list[str]]:
    """Return {kind: [unique tags]} found in the text."""
    patterns = patterns or _compiled("default")
    found: dict[str, list[str]] = {}
    for name, pattern in patterns.items():
        matches = list(dict.fromkeys(pattern.findall(text)))
        if matches:
            found[name] = matches[:200]
    return found


def all_tags(text: str, patterns: dict[str, re.Pattern[str]] | None = None) -> list[str]:
    tags: list[str] = []
    for values in extract_tags(text, patterns).values():
        tags.extend(values)
    return list(dict.fromkeys(tags))
