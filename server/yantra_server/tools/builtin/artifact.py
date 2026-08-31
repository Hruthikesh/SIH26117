"""read_artifact: page through stored full tool outputs and other artifacts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from yantra_server.artifacts.store import ArtifactNotFound
from yantra_server.tools.base import Tool, ToolContext, ToolResult


class ReadArtifactArgs(BaseModel):
    artifact_id: str
    offset: int = Field(default=0, ge=0, description="First line (0-based)")
    limit: int = Field(default=200, ge=1, le=2000)


class ReadArtifactTool(Tool):
    name = "read_artifact"
    description = "Page through a stored artifact (full tool outputs, tables, prompts) by line."
    Args = ReadArtifactArgs
    side_effects = "read"

    async def run(self, args: ReadArtifactArgs, ctx: ToolContext) -> ToolResult:
        try:
            row = ctx.state.artifacts.get(args.artifact_id)
        except ArtifactNotFound:
            return ToolResult.fail(f"no such artifact: {args.artifact_id}")
        if row.mime and not row.mime.startswith(("text/", "application/json")):
            return ToolResult.fail(
                f"artifact {args.artifact_id} is {row.mime}; use view_image for images"
            )
        text = ctx.state.artifacts.read_text(args.artifact_id, args.offset, args.limit)
        total = ctx.state.artifacts.read_text(args.artifact_id).count("\n") + 1
        summary = f"artifact {args.artifact_id[:8]}… lines {args.offset + 1}+ of ~{total}"
        return ToolResult(summary=summary, content=text, data={"total_lines": total})
