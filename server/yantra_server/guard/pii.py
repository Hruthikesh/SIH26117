"""Data protection (SPEC §16.2): configurable PII redaction + secrets scanning."""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9,12}\b")
EMPLOYEE_RE = re.compile(r"\b(?:EMP|EID|BADGE)[\s-]?\d{3,8}\b", re.IGNORECASE)
# India-relevant IDs plus generic government IDs
AADHAAR_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

SECRET_PATTERNS = {
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "generic_api_key": re.compile(
        r"\b(?:api[_-]?key|token|secret)[\"':=\s]{1,3}[A-Za-z0-9_\-]{16,}\b", re.IGNORECASE
    ),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "password_assignment": re.compile(r"\bpassword[\"':=\s]{1,3}\S{6,}", re.IGNORECASE),
}


@dataclass
class RedactionResult:
    text: str
    redactions: dict[str, int]


def redact_pii(text: str, mode: str = "mask") -> RedactionResult:
    """Mask personal data. mode: off|mask|hash. Off by default (SPEC §16.2)."""
    if mode == "off":
        return RedactionResult(text, {})
    counts: dict[str, int] = {}

    def sub(pattern: re.Pattern[str], label: str, s: str) -> str:
        def repl(m: re.Match[str]) -> str:
            counts[label] = counts.get(label, 0) + 1
            if mode == "hash":
                import hashlib

                return f"[{label}:{hashlib.sha256(m.group(0).encode()).hexdigest()[:8]}]"
            return f"[{label} redacted]"

        return pattern.sub(repl, s)

    text = sub(EMAIL_RE, "email", text)
    text = sub(AADHAAR_RE, "aadhaar", text)
    text = sub(PAN_RE, "pan", text)
    text = sub(EMPLOYEE_RE, "employee_id", text)
    text = sub(PHONE_RE, "phone", text)
    return RedactionResult(text, counts)


@dataclass
class SecretScan:
    found: dict[str, int]
    masked: str


def scan_secrets(text: str) -> SecretScan:
    """Mask credentials in content the agent reads and flag the file (SPEC §16.2)."""
    found: dict[str, int] = {}
    masked = text
    for label, pattern in SECRET_PATTERNS.items():
        matches = pattern.findall(masked)
        if matches:
            found[label] = len(matches)
            masked = pattern.sub(f"[{label} redacted]", masked)
    return SecretScan(found=found, masked=masked)
