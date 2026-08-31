import json
import sys
from pathlib import Path

import pytest

from tests.helpers import make_ctx, make_state
from yantra_server.tools.mcp import MCPManager, load_manifests
from yantra_server.tools.mcp.client import MCPError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "echo_mcp_server.py"


def write_manifest(tmp_path: Path, allowlist: list[str] | None = None) -> Path:
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    manifest = {
        "name": "echo",
        "command": sys.executable,
        "args": [str(FIXTURE)],
    }
    if allowlist is not None:
        manifest["tools_allowlist"] = allowlist
    (mcp_dir / "echo.json").write_text(json.dumps(manifest))
    return mcp_dir


def test_http_transport_rejected(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "remote.json").write_text(json.dumps({"name": "r", "url": "https://x.example"}))
    with pytest.raises(MCPError, match="stdio"):
        load_manifests(mcp_dir)


async def test_discover_and_call_tools(tmp_path: Path) -> None:
    manager = MCPManager(write_manifest(tmp_path, allowlist=["echo", "add"]))
    tools = await manager.start_all()
    try:
        names = sorted(t.name for t in tools)
        assert names == ["mcp_echo_add", "mcp_echo_echo"]  # `secret` filtered by allowlist
        state = make_state()
        for tool in tools:
            state.tools.registry.register(tool)
        ctx = make_ctx(state, tmp_path / "ws")
        echoed = await state.tools.runtime.execute("mcp_echo_echo", {"text": "namaste"}, ctx)
        assert echoed.ok and "echo: namaste" in echoed.content
        added = await state.tools.runtime.execute("mcp_echo_add", {"a": 20, "b": 22}, ctx)
        assert added.ok and added.content.strip() == "42"
        bad = await state.tools.runtime.execute("mcp_echo_add", {"a": "x", "b": 1}, ctx)
        assert not bad.ok and "invalid arguments" in (bad.error or "")
    finally:
        await manager.stop_all()


async def test_missing_server_binary_is_nonfatal(tmp_path: Path) -> None:
    mcp_dir = tmp_path / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "ghost.json").write_text(
        json.dumps({"name": "ghost", "command": "definitely-not-a-binary-xyz"})
    )
    manager = MCPManager(mcp_dir)
    tools = await manager.start_all()
    assert tools == []
