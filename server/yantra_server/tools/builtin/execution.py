"""Sandboxed execution tools: bash, python, run_tests, sql_query (SPEC §9.2)."""

from __future__ import annotations

import sys
import uuid

from pydantic import BaseModel, Field

from yantra_server.sandbox.local import shell_argv
from yantra_server.tools.base import Tool, ToolContext, ToolResult


def _sandbox_summary(result_data: dict[str, object]) -> dict[str, object]:
    return result_data


class BashArgs(BaseModel):
    cmd: str = Field(description="Shell command to run inside the no-network sandbox")
    cwd: str = Field(default=".", description="Working directory relative to the workspace")
    timeout_s: float = Field(default=120, ge=1, le=600)


class BashTool(Tool):
    name = "bash"
    description = (
        "Run one shell command in the sandbox (no network). Output is streamed and truncated."
    )
    Args = BashArgs
    side_effects = "exec"
    risk = "medium"
    needs_sandbox = True
    idempotent = False

    async def run(self, args: BashArgs, ctx: ToolContext) -> ToolResult:
        cwd = ctx.resolve_path(args.cwd)
        result = await ctx.sandbox.run(
            shell_argv(args.cmd),
            cwd=cwd,
            timeout_s=min(args.timeout_s, ctx.sandbox.limits.timeout_s),
            on_output=ctx.emit_output,
        )
        if ctx.budget is not None and result.cpu_s:
            ctx.budget.add_sandbox_cpu(result.cpu_s)
        sandbox_record = result.model_dump(mode="json", exclude={"stdout", "stderr"})
        ok = result.exit_code == 0 and not result.timed_out
        summary = (
            f"exit {result.exit_code} in {result.wall_s:.1f}s"
            + (" (TIMED OUT)" if result.timed_out else "")
            + (f", {len(result.files_changed)} file(s) changed" if result.files_changed else "")
        )
        return ToolResult(
            ok=ok,
            summary=summary,
            content=result.combined_output(),
            error=None if ok else f"command failed: {summary}",
            data={"sandbox": sandbox_record, "exit_code": result.exit_code},
        )


class PythonArgs(BaseModel):
    code: str = Field(description="Python source to execute; print() what you need to see")
    cwd: str = Field(default=".", description="Working directory relative to the workspace")
    timeout_s: float = Field(default=120, ge=1, le=600)


class PythonTool(Tool):
    name = "python"
    description = (
        "Run Python in the sandbox with the analysis stack (pandas, numpy, matplotlib, openpyxl). "
        "Compute numbers here, never in your head; save outputs as files."
    )
    Args = PythonArgs
    side_effects = "exec"
    risk = "medium"
    needs_sandbox = True
    idempotent = False

    async def run(self, args: PythonArgs, ctx: ToolContext) -> ToolResult:
        scratch = ctx.workspace / ".yantra" / "py"
        scratch.mkdir(parents=True, exist_ok=True)
        script = scratch / f"cell_{uuid.uuid4().hex[:8]}.py"
        script.write_text(args.code, encoding="utf-8")
        cwd = ctx.resolve_path(args.cwd)
        result = await ctx.sandbox.run(
            [sys.executable, str(script)],
            cwd=cwd,
            timeout_s=min(args.timeout_s, ctx.sandbox.limits.timeout_s),
            on_output=ctx.emit_output,
            env={"MPLBACKEND": "Agg"},
        )
        if ctx.budget is not None and result.cpu_s:
            ctx.budget.add_sandbox_cpu(result.cpu_s)
        ok = result.exit_code == 0 and not result.timed_out
        changed = [f for f in result.files_changed if not f.startswith(".yantra")]
        summary = (
            f"exit {result.exit_code} in {result.wall_s:.1f}s"
            + (" (TIMED OUT)" if result.timed_out else "")
            + (f", wrote {', '.join(changed[:3])}" if changed else "")
        )
        return ToolResult(
            ok=ok,
            summary=summary,
            content=result.combined_output(),
            error=None if ok else "python execution failed",
            data={
                "sandbox": result.model_dump(mode="json", exclude={"stdout", "stderr"}),
                "files_changed": changed,
            },
        )


class RunTestsArgs(BaseModel):
    cmd: str = Field(
        default="auto",
        description='Test command, or "auto" to detect pytest / npm test from the workspace',
    )
    cwd: str = "."
    timeout_s: float = Field(default=300, ge=1, le=600)


class RunTestsTool(Tool):
    name = "run_tests"
    description = (
        "Run the project's tests in the sandbox and report pass/fail with the output tail."
    )
    Args = RunTestsArgs
    side_effects = "exec"
    risk = "medium"
    needs_sandbox = True
    idempotent = False

    async def run(self, args: RunTestsArgs, ctx: ToolContext) -> ToolResult:
        cwd = ctx.resolve_path(args.cwd)
        cmd = args.cmd
        if cmd == "auto":
            detected = self._detect(cwd)
            if detected is None:
                return ToolResult.fail(
                    "no test setup detected (no pytest tests/, pyproject, or package.json); "
                    "pass cmd explicitly"
                )
            cmd = detected
        argv = (
            shell_argv(cmd) if not cmd.startswith("pytest-argv:") else cmd.split(":", 1)[1].split()
        )
        result = await ctx.sandbox.run(
            argv, cwd=cwd, timeout_s=args.timeout_s, on_output=ctx.emit_output
        )
        if ctx.budget is not None and result.cpu_s:
            ctx.budget.add_sandbox_cpu(result.cpu_s)
        ok = result.exit_code == 0
        return ToolResult(
            ok=ok,
            summary=f"tests {'passed' if ok else 'FAILED'} (exit {result.exit_code}, {result.wall_s:.1f}s)",
            content=result.combined_output(),
            error=None if ok else "tests failed",
            data={
                "exit_code": result.exit_code,
                "cmd": cmd,
                "sandbox": result.model_dump(mode="json", exclude={"stdout", "stderr"}),
            },
        )

    def _detect(self, cwd: object) -> str | None:
        from pathlib import Path

        root = Path(str(cwd))
        if (
            (root / "pyproject.toml").is_file()
            or list(root.glob("test_*.py"))
            or (root / "tests").is_dir()
        ):
            return f'"{sys.executable}" -m pytest -q'
        if (root / "package.json").is_file():
            return "npm test --silent"
        return None


class SqlQueryArgs(BaseModel):
    db_path: str = Field(description="SQLite/DuckDB file in the workspace, or a configured alias")
    query: str = Field(description="Read-only SQL (SELECT/CTE). Writes are refused.")
    limit: int = Field(default=100, ge=1, le=10000)


class SqlQueryTool(Tool):
    name = "sql_query"
    description = "Run a read-only SQL query against a workspace SQLite/DuckDB file."
    Args = SqlQueryArgs
    side_effects = "read"

    async def run(self, args: SqlQueryArgs, ctx: ToolContext) -> ToolResult:
        import re
        import sqlite3

        query = args.query.strip().rstrip(";")
        if not re.match(r"(?is)^\s*(with|select|explain)\b", query):
            return ToolResult.fail("only read-only queries (SELECT/WITH/EXPLAIN) are allowed")
        path = ctx.resolve_path(args.db_path)
        if not path.is_file():
            return ToolResult.fail(f"no such database file: {args.db_path}")
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                cursor = conn.execute(query)
                columns = [d[0] for d in cursor.description or []]
                rows = cursor.fetchmany(args.limit)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return ToolResult.fail(f"SQL error: {exc}")
        header = " | ".join(columns)
        body = "\n".join(" | ".join(str(v) for v in row) for row in rows)
        return ToolResult(
            summary=f"{len(rows)} row(s), {len(columns)} column(s)",
            content=f"{header}\n{'-' * min(len(header), 120)}\n{body}",
            data={"columns": columns, "row_count": len(rows)},
        )
