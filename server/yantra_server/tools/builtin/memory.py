"""Memory tools (SPEC §9.2): remember, recall."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from yantra_server.tools.base import Tool, ToolContext, ToolResult


class RememberArgs(BaseModel):
    kind: Literal["fact", "preference", "skill_note"]
    text: str
    provenance: list[str] = Field(
        default_factory=list, description="Required for facts: chunk ids or artifact locators"
    )


class RememberTool(Tool):
    name = "remember"
    description = (
        "Persist a fact (with provenance), a preference, or a skill note to memory. "
        "Facts without provenance are refused."
    )
    Args = RememberArgs
    side_effects = "write"
    risk = "medium"
    idempotent = False

    async def run(self, args: RememberArgs, ctx: ToolContext) -> ToolResult:
        memory = ctx.state.memory
        if memory is None:
            return ToolResult.fail("memory not available")
        try:
            if args.kind == "fact":
                mem_id = await memory.remember_fact(args.text, args.provenance)
            elif args.kind == "preference":
                mem_id = await memory.remember_preference(args.text)
            else:
                mem_id = await memory.remember_preference(f"[skill_note] {args.text}")
        except Exception as exc:
            return ToolResult.fail(str(exc))
        ctx.state.audit.append("agent", "memory.write", {"kind": args.kind, "id": mem_id})
        return ToolResult(summary=f"remembered {args.kind}", data={"id": mem_id})


class RecallArgs(BaseModel):
    query: str
    kind: str | None = None


class RecallTool(Tool):
    name = "recall"
    description = "Recall stored facts/preferences relevant to a query, with their provenance."
    Args = RecallArgs
    side_effects = "read"

    async def run(self, args: RecallArgs, ctx: ToolContext) -> ToolResult:
        memory = ctx.state.memory
        if memory is None:
            return ToolResult.fail("memory not available")
        hits = await memory.recall(args.query, kind=args.kind, top=5)
        if not hits:
            return ToolResult(summary="no matching memories", content="")
        lines = [
            f"[{h['kind']}] {h['text']} (provenance: {', '.join(h['provenance']) or 'none'})"
            for h in hits
        ]
        return ToolResult(
            summary=f"{len(hits)} memories", content="\n".join(lines), data={"memories": hits}
        )


def register_memory_tools(registry: Any) -> None:
    for tool in (RememberTool(), RecallTool()):
        if registry.get(tool.name) is None:
            registry.register(tool)
