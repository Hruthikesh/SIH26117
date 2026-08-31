"""Sandbox self-test (SPEC §14.5): code inside the sandbox must have no network at all.

Linux-only (bwrap). CI runs this inside `unshare -rn` as well — belt and braces.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from yantra_server.sandbox.base import SandboxLimits
from yantra_server.sandbox.bwrap import BwrapSandbox

pytestmark = [
    pytest.mark.seal,
    pytest.mark.skipif(not BwrapSandbox.available(), reason="needs Linux + bwrap"),
]

PROBE = """
import socket, sys
try:
    s = socket.create_connection(("1.1.1.1", 443), timeout=3)
    print("CONNECTED")  # must never happen
    sys.exit(1)
except OSError as exc:
    print(f"BLOCKED: {type(exc).__name__}")
    sys.exit(0)
"""

DNS_PROBE = """
import socket, sys
try:
    socket.getaddrinfo("example.com", 443)
    print("RESOLVED")
    sys.exit(1)
except OSError:
    print("DNS-BLOCKED")
    sys.exit(0)
"""


async def test_tcp_connect_blocked(tmp_path: Path) -> None:
    sandbox = BwrapSandbox(tmp_path, SandboxLimits(timeout_s=30))
    result = await sandbox.run([sys.executable, "-c", PROBE])
    assert result.exit_code == 0, result.combined_output()
    assert "BLOCKED" in result.stdout


async def test_dns_blocked(tmp_path: Path) -> None:
    sandbox = BwrapSandbox(tmp_path, SandboxLimits(timeout_s=30))
    result = await sandbox.run([sys.executable, "-c", DNS_PROBE])
    assert result.exit_code == 0, result.combined_output()


async def test_workspace_is_only_writable_location(tmp_path: Path) -> None:
    sandbox = BwrapSandbox(tmp_path, SandboxLimits(timeout_s=30))
    result = await sandbox.run(
        [
            sys.executable,
            "-c",
            "open('/work/ok.txt','w').write('y')\n"
            "import sys\n"
            "try:\n"
            "    open('/usr/evil','w')\n"
            "    sys.exit(1)\n"
            "except OSError:\n"
            "    sys.exit(0)\n",
        ]
    )
    assert result.exit_code == 0
    assert (tmp_path / "ok.txt").read_text() == "y"
