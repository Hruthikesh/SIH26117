"""Tiny MCP stdio server used by tests: tools `echo` and `add`."""

import json
import sys


def reply(frame_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": frame_id, "result": result}) + "\n")
    sys.stdout.flush()


TOOLS = [
    {
        "name": "echo",
        "description": "Echo the text back.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add",
        "description": "Add two integers.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "secret",
        "description": "Should be hidden by the allowlist.",
        "inputSchema": {"type": "object"},
    },
]


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        frame_id = msg.get("id")
        if method == "initialize":
            reply(
                frame_id,
                {
                    "protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "echo-test", "version": "1.0"},
                },
            )
        elif method == "tools/list":
            reply(frame_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = msg["params"]["name"]
            args = msg["params"].get("arguments", {})
            if name == "echo":
                reply(frame_id, {"content": [{"type": "text", "text": f"echo: {args['text']}"}]})
            elif name == "add":
                reply(
                    frame_id,
                    {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]},
                )
            else:
                reply(frame_id, {"content": [{"type": "text", "text": "boom"}], "isError": True})
        # notifications (no id) are ignored


if __name__ == "__main__":
    main()
