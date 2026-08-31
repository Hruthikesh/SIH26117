"""Minimal MCP client (stdio transport, newline-delimited JSON-RPC 2.0).

Servers are declared in tools/mcp/*.json and launched inside the sandbox contract (no
network). Their tools appear in the registry as `mcp_<server>_<tool>`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yantra_server.seal.env import sealed_environment
from yantra_server.tools.base import Tool, ToolContext, ToolResult

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
REQUEST_TIMEOUT_S = 60.0


class MCPServerManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown keys (url, transport…) are rejected

    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    tools_allowlist: list[str] | None = None


class MCPError(Exception):
    pass


def load_manifests(mcp_dir: Path) -> list[MCPServerManifest]:
    manifests: list[MCPServerManifest] = []
    if not mcp_dir.is_dir():
        return manifests
    for path in sorted(mcp_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if any(key in raw for key in ("url", "transport", "sse", "http")):
            raise MCPError(
                f"{path.name}: only the stdio transport is supported — remote/HTTP/SSE MCP "
                "servers are rejected by design (SPEC §9.5). Install the server locally and "
                "declare its command."
            )
        try:
            manifests.append(MCPServerManifest.model_validate(raw))
        except ValidationError as exc:
            raise MCPError(f"{path.name}: invalid manifest: {exc}") from exc
    return manifests


class MCPConnection:
    """One running MCP server process."""

    def __init__(self, manifest: MCPServerManifest) -> None:
        self.manifest = manifest
        self.proc: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self.tools: list[dict[str, Any]] = []

    async def start(self) -> None:
        env = sealed_environment(extra=self.manifest.env)
        self.proc = await asyncio.create_subprocess_exec(
            self.manifest.command,
            *self.manifest.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop(), name=f"mcp-{self.manifest.name}")
        init = await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "yantra", "version": "1.0"},
            },
        )
        log.info("mcp %s initialized: %s", self.manifest.name, init.get("serverInfo", {}))
        await self.notify("notifications/initialized", {})
        listed = await self.request("tools/list", {})
        tools = listed.get("tools", [])
        allow = self.manifest.tools_allowlist
        self.tools = [t for t in tools if allow is None or t.get("name") in allow]

    async def _read_loop(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            frame_id = frame.get("id")
            if isinstance(frame_id, int) and frame_id in self._pending:
                self._pending.pop(frame_id).set_result(frame)

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.proc is None or self.proc.stdin is None:
            raise MCPError(f"mcp {self.manifest.name}: not started")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        frame = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self.proc.stdin.write((json.dumps(frame) + "\n").encode())
        await self.proc.stdin.drain()
        try:
            reply = await asyncio.wait_for(future, timeout=REQUEST_TIMEOUT_S)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise MCPError(f"mcp {self.manifest.name}: {method} timed out") from exc
        if "error" in reply:
            raise MCPError(
                f"mcp {self.manifest.name}: {reply['error'].get('message', reply['error'])}"
            )
        result = reply.get("result", {})
        return result if isinstance(result, dict) else {"value": result}

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            return
        frame = {"jsonrpc": "2.0", "method": method, "params": params}
        self.proc.stdin.write((json.dumps(frame) + "\n").encode())
        await self.proc.stdin.drain()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        result = await self.request("tools/call", {"name": name, "arguments": arguments})
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        content = "\n".join(t for t in texts if t)
        is_error = bool(result.get("isError"))
        return ToolResult(
            ok=not is_error,
            summary=content.splitlines()[0][:120] if content else ("error" if is_error else "ok"),
            content=content,
            error=content[:400] if is_error else None,
        )

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self.proc is not None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=10)
            except (ProcessLookupError, TimeoutError):
                if self.proc.returncode is None:
                    self.proc.kill()


class _FreeArgs(BaseModel):
    model_config = ConfigDict(extra="allow")


class MCPTool(Tool):
    """Registry adapter for one remote tool; schema comes from the server verbatim."""

    Args = _FreeArgs
    side_effects = "exec"
    risk = "medium"
    needs_sandbox = False  # the server process itself runs sealed; calls are in-process RPC
    idempotent = False

    def __init__(self, connection: MCPConnection, tool_def: dict[str, Any]) -> None:
        server = connection.manifest.name
        remote = str(tool_def.get("name", ""))
        self.name = f"mcp_{server}_{remote}"
        self.description = str(tool_def.get("description", ""))[:300] or f"{server}:{remote}"
        self.override_schema: dict[str, Any] = tool_def.get("inputSchema") or {"type": "object"}
        self._connection = connection
        self._remote_name = remote

    async def run(self, args: Any, ctx: ToolContext) -> ToolResult:
        arguments = args.model_dump(mode="json") if isinstance(args, BaseModel) else dict(args)
        try:
            jsonschema.validate(arguments, self.override_schema)
        except jsonschema.ValidationError as exc:
            return ToolResult.fail(f"invalid arguments: {exc.message}")
        try:
            return await self._connection.call_tool(self._remote_name, arguments)
        except MCPError as exc:
            return ToolResult.fail(str(exc))


class MCPManager:
    def __init__(self, mcp_dir: Path) -> None:
        self.mcp_dir = mcp_dir
        self.connections: dict[str, MCPConnection] = {}

    async def start_all(self) -> list[MCPTool]:
        tools: list[MCPTool] = []
        for manifest in load_manifests(self.mcp_dir):
            connection = MCPConnection(manifest)
            try:
                await connection.start()
            except (OSError, MCPError) as exc:
                log.warning("mcp server %s failed to start: %s", manifest.name, exc)
                continue
            self.connections[manifest.name] = connection
            tools.extend(MCPTool(connection, t) for t in connection.tools)
        return tools

    async def stop_all(self) -> None:
        for connection in self.connections.values():
            await connection.stop()
        self.connections.clear()
