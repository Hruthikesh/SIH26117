"""Model capability probes (SPEC §7.4): a ~2-minute check that a registered model actually
delivers JSON-under-grammar, tool-call adherence, vision, tag extraction, and sandboxed
coding (candidate code never runs outside the sandbox)."""

from __future__ import annotations

import base64
import struct
import zlib
from typing import Any

from pydantic import BaseModel, Field

from .engines.base import ChatMessage, Constraint, Decoding, ImagePart, TextPart, ToolSpec
from .service import Gateway, ModelRequest
from .structured import action_schema


class ProbeOutcome(BaseModel):
    probe: str
    passed: bool
    score: float | None = None
    detail: str = ""


def tiny_png(rgb: tuple[int, int, int], size: int = 48) -> bytes:
    """A solid-colour PNG without any imaging dependency."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * size
    body = zlib.compress(row * size)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", body) + chunk(b"IEND", b"")
    )


class _JsonProbeSchema(BaseModel):
    equipment: str
    reading_bar: float
    status: str = Field(pattern="^(ok|alarm)$")


TAG_PROBE_TEXT = """Shift log, Unit 3.
06:10 P-3101A tripped on low suction; standby P-3101B started.
07:45 FIC-3201 output erratic, instrument tech checked FT-3201 impulse lines.
09:20 PSV-3105 weep observed at flange; E-3102 outlet temperature normal.
11:05 V-3104 level transmitter LT-3104 recalibrated. C-501 loading steady.
"""
TAG_PROBE_TRUTH = {
    "P-3101A",
    "P-3101B",
    "FIC-3201",
    "FT-3201",
    "PSV-3105",
    "E-3102",
    "V-3104",
    "LT-3104",
    "C-501",
}


class _TagProbeSchema(BaseModel):
    tags: list[str]


async def probe_json(gateway: Gateway, model_id: str, role: str) -> ProbeOutcome:
    try:
        result = await gateway.chat(
            ModelRequest(
                role=role,
                messages=[
                    ChatMessage(
                        role="user",
                        content="Pump P-101A discharge pressure reads 12.4 bar and is normal. "
                        "Report as JSON.",
                    )
                ],
                schema_model=_JsonProbeSchema,
                decoding=Decoding(temperature=0.0, max_tokens=256),
                meta={"probe": "json"},
                force_model=model_id,
            )
        )
        parsed = result.parsed
        ok = isinstance(parsed, _JsonProbeSchema)
        return ProbeOutcome(probe="json", passed=ok, detail=f"model={result.result.model}")
    except Exception as exc:
        return ProbeOutcome(probe="json", passed=False, detail=f"{type(exc).__name__}: {exc}")


async def probe_tools(gateway: Gateway, model_id: str, role: str) -> ProbeOutcome:
    tool = ToolSpec(
        name="read_file",
        description="Read a text file from the workspace.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )
    schema = action_schema([tool])
    try:
        result = await gateway.chat(
            ModelRequest(
                role=role,
                messages=[
                    ChatMessage(
                        role="user",
                        content="Decide the next single action to read the file logs/pump.txt.",
                    )
                ],
                constraint=Constraint(kind="json_schema", json_schema=schema),
                decoding=Decoding(temperature=0.0, max_tokens=256),
                meta={"probe": "tools"},
                force_model=model_id,
            )
        )
        obj: Any = result.parsed
        action = obj.get("action", {}) if isinstance(obj, dict) else {}
        ok = action.get("tool") == "read_file" and "path" in action.get("args", {})
        return ProbeOutcome(probe="tools", passed=ok, detail=str(action)[:200])
    except Exception as exc:
        return ProbeOutcome(probe="tools", passed=False, detail=f"{type(exc).__name__}: {exc}")


async def probe_vision(gateway: Gateway, model_id: str, role: str) -> ProbeOutcome:
    png = tiny_png((200, 30, 30))
    try:
        result = await gateway.chat(
            ModelRequest(
                role=role,
                messages=[
                    ChatMessage(
                        role="user",
                        content=[
                            TextPart(text="What colour is this image? Answer with one word."),
                            ImagePart(data_b64=base64.b64encode(png).decode()),
                        ],
                    )
                ],
                constraint=Constraint(kind="choice", choices=["red", "green", "blue"]),
                decoding=Decoding(temperature=0.0, max_tokens=8),
                meta={"probe": "vision"},
                force_model=model_id,
            )
        )
        return ProbeOutcome(
            probe="vision", passed=result.parsed == "red", detail=str(result.parsed)
        )
    except Exception as exc:
        return ProbeOutcome(probe="vision", passed=False, detail=f"{type(exc).__name__}: {exc}")


async def probe_tag_extraction(gateway: Gateway, model_id: str, role: str) -> ProbeOutcome:
    try:
        result = await gateway.chat(
            ModelRequest(
                role=role,
                messages=[
                    ChatMessage(
                        role="user",
                        content="Extract every equipment/instrument tag from this log as JSON "
                        '{"tags": [...]}:\n' + TAG_PROBE_TEXT,
                    )
                ],
                schema_model=_TagProbeSchema,
                decoding=Decoding(temperature=0.0, max_tokens=512),
                meta={"probe": "tags"},
                force_model=model_id,
            )
        )
        parsed = result.parsed
        found = (
            {t.strip().upper() for t in parsed.tags}
            if isinstance(parsed, _TagProbeSchema)
            else set()
        )
        truth = TAG_PROBE_TRUTH
        tp = len(found & truth)
        precision = tp / len(found) if found else 0.0
        recall = tp / len(truth)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return ProbeOutcome(
            probe="tag_extraction",
            passed=f1 >= 0.8,
            score=round(f1, 3),
            detail=f"P={precision:.2f} R={recall:.2f}",
        )
    except Exception as exc:
        return ProbeOutcome(
            probe="tag_extraction", passed=False, detail=f"{type(exc).__name__}: {exc}"
        )


CODING_PROBLEMS = [
    ("Return the sum of a list of ints.", "def solve(xs):", "assert solve([1,2,3]) == 6"),
    ("Return the string reversed.", "def solve(s):", "assert solve('pump') == 'pmup'"),
    (
        "Return True when n is even.",
        "def solve(n):",
        "assert solve(4) is True and solve(3) is False",
    ),
    ("Return the largest value.", "def solve(xs):", "assert solve([3,9,2]) == 9"),
    ("Return n squared.", "def solve(n):", "assert solve(7) == 49"),
]


class _CodeProbeSchema(BaseModel):
    code: str


async def probe_coding(gateway: Gateway, model_id: str, role: str) -> ProbeOutcome:
    """5-item coding smoke test executed in the sandbox (SPEC §7.4)."""
    import sys
    import tempfile
    from pathlib import Path

    from yantra_server.sandbox import SandboxError, select_sandbox

    try:
        with tempfile.TemporaryDirectory(prefix="yantra-probe-") as tmp:
            workspace = Path(tmp)
            try:
                sandbox = select_sandbox(
                    gateway.config.sandbox, workspace, sealed=gateway.config.sealed()
                )
            except SandboxError as exc:
                return ProbeOutcome(probe="coding", passed=False, detail=f"no sandbox: {exc}")
            passed = 0
            for index, (spec, signature, check) in enumerate(CODING_PROBLEMS):
                result = await gateway.chat(
                    ModelRequest(
                        role=role,
                        messages=[
                            ChatMessage(
                                role="user",
                                content=f"Write a Python function.\nSpec: {spec}\n"
                                f'Signature: {signature}\nReturn JSON {{"code": "..."}} '
                                "containing only the complete function definition.",
                            )
                        ],
                        schema_model=_CodeProbeSchema,
                        decoding=Decoding(temperature=0.0, max_tokens=512),
                        force_model=model_id,
                        meta={"probe": "coding"},
                    )
                )
                parsed = result.parsed
                code = parsed.code if isinstance(parsed, _CodeProbeSchema) else ""
                script = workspace / f"case_{index}.py"
                script.write_text(f"{code}\n\n{check}\nprint('OK')\n", encoding="utf-8")
                run = await sandbox.run([sys.executable, str(script)], timeout_s=20)
                if run.exit_code == 0 and "OK" in run.stdout:
                    passed += 1
            score = passed / len(CODING_PROBLEMS)
            return ProbeOutcome(
                probe="coding",
                passed=score >= 0.8,
                score=score,
                detail=f"{passed}/{len(CODING_PROBLEMS)} in {sandbox.name} sandbox",
            )
    except Exception as exc:
        return ProbeOutcome(probe="coding", passed=False, detail=f"{type(exc).__name__}: {exc}")


async def run_probes(
    gateway: Gateway, model_id: str, capabilities: list[str]
) -> list[ProbeOutcome]:
    """Run the applicable probe set for a model through its own serving path."""
    role = _role_for_probe(capabilities)
    outcomes = [
        await probe_json(gateway, model_id, role),
        await probe_tools(gateway, model_id, role),
        await probe_tag_extraction(gateway, model_id, role),
    ]
    if "vision" in capabilities:
        outcomes.append(await probe_vision(gateway, model_id, role))
    if {"code", "chat"} & set(capabilities):
        outcomes.append(await probe_coding(gateway, model_id, role))
    return outcomes


def _role_for_probe(capabilities: list[str]) -> str:
    if "ocr" in capabilities:
        return "ocr"
    return "executor"
