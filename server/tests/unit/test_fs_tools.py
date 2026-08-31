from pathlib import Path

import pytest

from tests.helpers import make_ctx, make_state
from yantra_server.state import AppState
from yantra_server.tools.base import ToolContext


@pytest.fixture
def state() -> AppState:
    return make_state()


@pytest.fixture
def ctx(state: AppState, tmp_path: Path) -> ToolContext:
    return make_ctx(state, tmp_path / "ws")


async def run_tool(state: AppState, ctx: ToolContext, name: str, **args: object) -> object:
    return await state.tools.runtime.execute(name, dict(args), ctx)


async def test_write_read_roundtrip(state: AppState, ctx: ToolContext) -> None:
    write = await run_tool(state, ctx, "write_file", path="notes/a.txt", content="alpha\nbeta\n")
    assert write.ok, write.error  # type: ignore[union-attr]
    read = await run_tool(state, ctx, "read_file", path="notes/a.txt")
    assert read.ok and "1\talpha" in read.content  # type: ignore[union-attr]


async def test_overwrite_guard(state: AppState, ctx: ToolContext) -> None:
    await run_tool(state, ctx, "write_file", path="a.txt", content="v1")
    denied = await run_tool(state, ctx, "write_file", path="a.txt", content="v2")
    assert not denied.ok and "overwrite" in (denied.error or "")  # type: ignore[union-attr]
    forced = await run_tool(state, ctx, "write_file", path="a.txt", content="v2", overwrite=True)
    assert forced.ok  # type: ignore[union-attr]


async def test_path_escape_blocked(state: AppState, ctx: ToolContext) -> None:
    outside = await run_tool(state, ctx, "read_file", path="../../etc/hosts")
    assert not outside.ok and "escapes the workspace" in (outside.error or "")  # type: ignore[union-attr]
    write_out = await run_tool(state, ctx, "write_file", path="..\\evil.txt", content="x")
    assert not write_out.ok  # type: ignore[union-attr]


async def test_edit_file_exact_and_ambiguous(state: AppState, ctx: ToolContext) -> None:
    await run_tool(state, ctx, "write_file", path="c.py", content="x = 1\ny = 1\n")
    ambiguous = await run_tool(state, ctx, "edit_file", path="c.py", old="= 1", new="= 2")
    assert not ambiguous.ok and "2 times" in (ambiguous.error or "")  # type: ignore[union-attr]
    second = await run_tool(
        state, ctx, "edit_file", path="c.py", old="= 1", new="= 2", occurrence=2
    )
    assert second.ok  # type: ignore[union-attr]
    read = await run_tool(state, ctx, "read_file", path="c.py")
    assert "x = 1" in read.content and "y = 2" in read.content  # type: ignore[union-attr]
    missing = await run_tool(state, ctx, "edit_file", path="c.py", old="nope", new="never")
    assert not missing.ok and "not found" in (missing.error or "")  # type: ignore[union-attr]


async def test_apply_patch_and_context_drift(state: AppState, ctx: ToolContext) -> None:
    original = "def add(a, b):\n    return a + b\n\nprint(add(1, 2))\n"
    await run_tool(state, ctx, "write_file", path="m.py", content=original)
    diff = (
        "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,3 @@\n def add(a, b):\n"
        '+    """Add two numbers."""\n     return a + b\n'
    )
    patched = await run_tool(state, ctx, "apply_patch", unified_diff=diff)
    assert patched.ok, patched.error  # type: ignore[union-attr]
    read = await run_tool(state, ctx, "read_file", path="m.py")
    assert "Add two numbers" in read.content  # type: ignore[union-attr]
    bad = await run_tool(
        state,
        ctx,
        "apply_patch",
        unified_diff="--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n does not exist\n-nope\n+never\n",
    )
    assert not bad.ok and "does not apply" in (bad.error or "")  # type: ignore[union-attr]


async def test_glob_and_grep(state: AppState, ctx: ToolContext) -> None:
    await run_tool(
        state, ctx, "write_file", path="logs/p1.log", content="P-3101A tripped\nnormal\n"
    )
    await run_tool(state, ctx, "write_file", path="logs/p2.log", content="all fine\n")
    globbed = await run_tool(state, ctx, "glob", pattern="logs/*.log")
    assert globbed.data["files"] and len(globbed.data["files"]) == 2  # type: ignore[union-attr]
    grepped = await run_tool(state, ctx, "grep", pattern="P-3101A", regex=False)
    assert grepped.data["matches"] == 1  # type: ignore[union-attr]
    assert "p1.log" in grepped.content  # type: ignore[union-attr]


async def test_binary_detection(state: AppState, ctx: ToolContext) -> None:
    (ctx.workspace / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    result = await run_tool(state, ctx, "read_file", path="blob.bin")
    assert not result.ok and "binary" in (result.error or "")  # type: ignore[union-attr]
    info = await run_tool(state, ctx, "file_info", path="blob.bin")
    assert info.ok and info.data["type"] == "binary"  # type: ignore[union-attr]


async def test_move_and_delete(state: AppState, ctx: ToolContext) -> None:
    await run_tool(state, ctx, "write_file", path="old.txt", content="x")
    moved = await run_tool(state, ctx, "move_file", source="old.txt", dest="new/loc.txt")
    assert moved.ok  # type: ignore[union-attr]
    # delete_file is denied by the default policy in every mode
    deleted = await run_tool(state, ctx, "delete_file", path="new/loc.txt")
    assert not deleted.ok and "denied" in (deleted.error or "")  # type: ignore[union-attr]
    assert (ctx.workspace / "new" / "loc.txt").exists()
