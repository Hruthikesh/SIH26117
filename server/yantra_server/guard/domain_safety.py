"""Domain safety (SPEC §16.3): never recommend defeating safety functions; banner outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Phrases that indicate an unsafe recommendation to bypass/defeat protective functions.
UNSAFE_ACTION = re.compile(
    r"\b(bypass|defeat|disable|override|jumper|force|inhibit|block(?:\s+out)?|remove|car[\s-]?seal\s+closed)\b",
    re.IGNORECASE,
)
SAFETY_TARGET = re.compile(
    r"\b(psv|relief\s+valve|safety\s+valve|interlock|sif|sis|trip|esd|car[\s-]?seal|"
    r"safety\s+instrumented|shutdown\s+system|pressure\s+safety)\b",
    re.IGNORECASE,
)

REVIEW_BANNER = "Engineering review required before use."


@dataclass
class SafetyViolation:
    sentence: str
    reason: str


def check_domain_safety(text: str) -> list[SafetyViolation]:
    """Flag sentences recommending the defeat of a safety function (SPEC §16.3)."""
    violations: list[SafetyViolation] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if UNSAFE_ACTION.search(sentence) and SAFETY_TARGET.search(sentence):
            # "review required" phrasing is acceptable
            if re.search(
                r"review\s+required|confirm|recommend\s+(?:confirming|reviewing)",
                sentence,
                re.IGNORECASE,
            ):
                continue
            violations.append(
                SafetyViolation(
                    sentence=sentence.strip()[:200],
                    reason="recommends bypassing/defeating a safety function",
                )
            )
    return violations


def needs_review_banner(text: str) -> bool:
    """Operational-instruction content gets the review-required banner."""
    return bool(
        re.search(
            r"\b(step \d|procedure|isolate|start|stop|open|close|torque)\b", text, re.IGNORECASE
        )
    )


def apply_banner(text: str) -> str:
    if REVIEW_BANNER in text:
        return text
    return f"{REVIEW_BANNER}\n\n{text}"
