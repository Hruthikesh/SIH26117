"""Real llama.cpp smoke test (M1 DoD): grammar-constrained JSON from a tiny GGUF model.

Runs only when a `llama-server` binary and a tiny model are available:
    export YANTRA_TINY_MODELS_DIR=~/.yantra/models   # containing Qwen3.5-0.8B-Q4_K_M.gguf
    pytest -m e2e server/tests/e2e/test_llamacpp_smoke.py
"""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
from pydantic import BaseModel

from yantra_server.gateway.engines.base import ChatMessage, Decoding, EngineChatRequest
from yantra_server.gateway.engines.llamacpp import LlamaCppEngine
from yantra_server.gateway.structured import constraint_for, validate_output

pytestmark = pytest.mark.e2e

BINARY = shutil.which("llama-server")
MODELS_DIR = os.environ.get("YANTRA_TINY_MODELS_DIR", "")


def _find_tiny_model() -> Path | None:
    if not MODELS_DIR:
        return None
    root = Path(MODELS_DIR).expanduser()
    if not root.is_dir():
        return None
    candidates = sorted(root.glob("*.gguf"), key=lambda p: p.stat().st_size)
    return candidates[0] if candidates else None


TINY = _find_tiny_model()
requires_llama = pytest.mark.skipif(
    BINARY is None or TINY is None,
    reason="needs llama-server on PATH and a tiny GGUF in $YANTRA_TINY_MODELS_DIR",
)


class PumpReport(BaseModel):
    tag: str
    status: str


@requires_llama
async def test_grammar_constrained_json_from_real_model() -> None:
    assert BINARY is not None and TINY is not None
    port = _free_port()
    proc = subprocess.Popen(
        [BINARY, "-m", str(TINY), "--host", "127.0.0.1", "--port", str(port), "-c", "2048"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        engine = LlamaCppEngine(f"http://127.0.0.1:{port}", timeout_s=120)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if (await engine.health()).ok:
                break
            time.sleep(2)
        else:
            pytest.fail("llama-server did not become healthy in 120s")

        constraint = constraint_for(PumpReport)
        result = await engine.chat(
            EngineChatRequest(
                model="tiny",
                messages=[
                    ChatMessage(
                        role="user",
                        content="Pump P-101A is running normally. Report as JSON with keys tag and status.",
                    )
                ],
                constraint=constraint,
                decoding=Decoding(temperature=0.0, max_tokens=128),
            )
        )
        parsed = validate_output(result.content, constraint, PumpReport)
        assert isinstance(parsed, PumpReport)
        assert parsed.tag  # any non-empty tag: the grammar did its job
    finally:
        with contextlib.suppress(OSError):
            proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(10)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
