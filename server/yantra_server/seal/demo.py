"""`yantra seal demo` (SPEC §14.5): live proof for the judges.

Fires two egress attempts from sealed child processes — `pip install requests` and a raw
urllib fetch — both must be blocked and appear in the Seal Monitor with stack traces,
while a document task keeps running in the background.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yantra_server.state import AppState

URLLIB_PROBE = (
    "import urllib.request\n"
    "try:\n"
    "    urllib.request.urlopen('https://example.com', timeout=5)\n"
    "    print('LEAK')\n"
    "except Exception as exc:\n"
    "    print(f'BLOCKED: {type(exc).__name__}')\n"
)


async def run_seal_demo(state: AppState) -> dict[str, Any]:
    from yantra_server.evals.seal_smoke import run_seal_smoke
    from yantra_server.seal.verify import _sealed_child_env

    env = _sealed_child_env(state)
    before = state.seal_monitor.blocked_total() if state.seal_monitor else 0

    # The document task keeps running while the attacks are blocked.
    smoke_task = asyncio.create_task(run_seal_smoke(state))

    async def child(cmd: list[str]) -> tuple[int, str]:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=90, env=env
        )
        return result.returncode, (result.stdout + result.stderr).strip()[-500:]

    pip_code, pip_out = await child(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "requests"]
    )
    url_code, url_out = await child([sys.executable, "-c", URLLIB_PROBE])

    smoke = await smoke_task
    if state.seal_monitor is not None:
        state.seal_monitor.ingest_events_file()
        blocked_now = state.seal_monitor.blocked_total()
        attempts = state.seal_monitor.last_attempts(5)
    else:
        blocked_now, attempts = before, []

    state.audit.append(
        "user",
        "seal.demo",
        {"pip_blocked": pip_code != 0, "urllib_blocked": "LEAK" not in url_out},
    )
    return {
        "probes": [
            {
                "name": "pip install requests",
                "blocked": pip_code != 0,
                "output": pip_out,
            },
            {
                "name": "urllib https://example.com",
                "blocked": "LEAK" not in url_out and url_code == 0,
                "output": url_out,
            },
        ],
        "new_blocked_events": max(0, blocked_now - before),
        "last_attempts": attempts,
        "document_task": {"passed": smoke.passed, "detail": smoke.detail, "skipped": smoke.skipped},
        "sealed": state.config.sealed(),
    }
