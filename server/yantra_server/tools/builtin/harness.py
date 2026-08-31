"""Harness tools: delegate (child tasks) and ask_user (SPEC §8.9, §9.2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from yantra_server.tools.base import Tool, ToolContext, ToolResult


class DelegateArgs(BaseModel):
    title: str = Field(max_length=120)
    intent: str = Field(max_length=600, description="What the child task must produce")
    role: str = Field(description="Agent name to run the child (analyst, coder, …)")
    acceptance: list[dict[str, Any]] = Field(
        default_factory=list, description="Optional Check objects; defaults to a rubric check"
    )


class DelegateTool(Tool):
    name = "delegate"
    description = (
        "Spawn a child task with its own agent, budget and verification; blocks until it "
        "finishes and returns its summary. Depth ≤ 2, ≤ 6 children per task."
    )
    Args = DelegateArgs
    side_effects = "exec"
    risk = "medium"
    idempotent = False

    async def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        conductor = ctx.state.conductor
        if conductor is None or ctx.run_id is None or ctx.task_id is None:
            return ToolResult.fail("delegation unavailable outside a run")
        ok, summary = await conductor.delegate(
            ctx.run_id,
            ctx.task_id,
            title=args.title,
            intent=args.intent,
            role=args.role,
            acceptance=args.acceptance or None,
        )
        if ok:
            return ToolResult(summary=f"child task done: {args.title}", content=summary)
        return ToolResult.fail(
            f"child task failed: {summary}", summary=f"delegate: {args.title} failed"
        )


class AskUserArgs(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=5)


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Ask the user numbered questions (ask mode only). In auto mode it returns "
        "'unavailable' — make a reasonable assumption and record it in your finish."
    )
    Args = AskUserArgs
    side_effects = "none"

    async def run(self, args: AskUserArgs, ctx: ToolContext) -> ToolResult:
        if ctx.mode != "ask":
            return ToolResult(
                ok=True,
                summary="ask_user unavailable in auto mode",
                content="unavailable; make an assumption and record it",
            )
        conductor = ctx.state.conductor
        if conductor is None or ctx.run_id is None:
            return ToolResult.fail("no interactive session attached")
        answers = await conductor.ask_questions(ctx.run_id, args.questions)
        if answers is None:
            return ToolResult(
                ok=True,
                summary="user did not answer",
                content="no answer received; proceed on your best assumption and record it",
            )
        paired = "\n".join(
            f"Q{i + 1}: {q}\nA{i + 1}: {a}"
            for i, (q, a) in enumerate(zip(args.questions, answers, strict=False))
        )
        return ToolResult(summary=f"user answered {len(answers)} question(s)", content=paired)
