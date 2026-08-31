"""Tool registry: schemas for constrained decoding, prompt manifests, few-shots."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from yantra_server.gateway.engines.base import ToolSpec
from yantra_server.gateway.structured import inline_refs

from .base import Tool

log = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, fewshots_dir: Path | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self.fewshots_dir = fewshots_dir

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def subset(self, names: list[str]) -> list[Tool]:
        return [self._tools[n] for n in names if n in self._tools]

    def spec_for(self, tool: Tool) -> ToolSpec:
        override = getattr(tool, "override_schema", None)  # MCP tools carry the server's schema
        if override is not None:
            return ToolSpec(name=tool.name, description=tool.description, parameters=dict(override))
        schema = inline_refs(tool.Args.model_json_schema())
        schema["additionalProperties"] = False
        return ToolSpec(name=tool.name, description=tool.description, parameters=schema)

    def specs_for(self, names: list[str]) -> list[ToolSpec]:
        return [self.spec_for(t) for t in self.subset(names)]

    def manifest_text(self, names: list[str]) -> str:
        """The tool manifest injected into prompts: name, one-line contract, key args."""
        lines: list[str] = []
        for tool in self.subset(names):
            fields = tool.Args.model_fields
            arg_bits: list[str] = []
            for field_name, field_info in fields.items():
                required = field_info.is_required()
                arg_bits.append(field_name if required else f"{field_name}?")
            lines.append(f"- {tool.name}({', '.join(arg_bits)}): {tool.description}")
        return "\n".join(lines)

    def fewshots_text(self, names: list[str], max_per_tool: int = 3) -> str:
        """Few-shot exemplars for exactly the tools in play (SPEC §5.1 point 6)."""
        if self.fewshots_dir is None:
            return ""
        blocks: list[str] = []
        for tool in self.subset(names):
            rel = tool.fewshots_path or f"{tool.name}.jsonl"
            path = self.fewshots_dir / rel
            if not path.is_file():
                continue
            examples: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    shot = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("bad few-shot line in %s", path)
                    continue
                examples.append(
                    f"  situation: {shot.get('situation', '')}\n"
                    f"  call: {json.dumps(shot.get('call', {}), ensure_ascii=False)}\n"
                    f"  why: {shot.get('why', '')}"
                    + (f"\n  avoid: {shot['anti_pattern']}" if shot.get("anti_pattern") else "")
                )
                if len(examples) >= max_per_tool:
                    break
            if examples:
                blocks.append(f"{tool.name} examples:\n" + "\n".join(examples))
        return "\n\n".join(blocks)

    def permission_metadata(self, name: str) -> dict[str, Any]:
        tool = self._tools[name]
        return {
            "side_effects": tool.side_effects,
            "risk": tool.risk,
            "needs_sandbox": tool.needs_sandbox,
            "idempotent": tool.idempotent,
        }
