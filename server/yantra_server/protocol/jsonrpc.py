"""JSON-RPC 2.0 envelope helpers for the WebSocket transport."""

from __future__ import annotations

import json
from typing import Any

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def parse_request(raw: str) -> tuple[Any, str, dict[str, Any]]:
    """Return (id, method, params); raises RpcError on malformed input."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RpcError(PARSE_ERROR, f"parse error: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise RpcError(INVALID_REQUEST, "not a JSON-RPC 2.0 request")
    method = payload.get("method")
    if not isinstance(method, str):
        raise RpcError(INVALID_REQUEST, "missing method")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, "params must be an object")
    return payload.get("id"), method, params


def result_frame(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_frame(
    request_id: Any, code: int, message: str, data: Any | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def notification_frame(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}
