"""MCP over stdio only (SPEC §9.5). HTTP/SSE transports are rejected by design."""

from .client import MCPManager, MCPServerManifest, load_manifests

__all__ = ["MCPManager", "MCPServerManifest", "load_manifests"]
