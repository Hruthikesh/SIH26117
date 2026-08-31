"""Dev-only backend: plain subprocess, NO isolation. Selectable only when YANTRA_SEALED=0
(select_sandbox enforces this); the TUI shows UNSEALED and `yantra doctor` flags it."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .base import OutputCallback, Sandbox, SandboxResult, drain_process, now


class LocalSandbox(Sandbox):
    name = "local"
    provides_isolation = False

    @classmethod
    def available(cls) -> bool:
        return True

    async def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        timeout_s: float | None = None,
        on_output: OutputCallback | None = None,
    ) -> SandboxResult:
        before = self.snapshot_mtimes()
        import os

        merged_env = dict(os.environ)
        merged_env.update(env or {})
        merged_env["YANTRA_SEALED"] = "0"
        started = now()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd or self.workspace),
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            return SandboxResult(
                exit_code=127, stderr=f"command not found: {exc}", backend=self.name
            )
        if stdin is not None and proc.stdin is not None:
            proc.stdin.write(stdin.encode())
            proc.stdin.close()
        stdout, stderr, timed_out, truncated = await drain_process(
            proc,
            limits=self.limits,
            timeout_s=timeout_s or self.limits.timeout_s,
            on_output=on_output,
        )
        return SandboxResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            wall_s=round(now() - started, 3),
            timed_out=timed_out,
            files_changed=self.diff_files(before),
            blocked_net_attempts=0,  # unenforced here; the process socket guard still logs
            backend=self.name,
            truncated=truncated,
        )


def shell_argv(command: str) -> list[str]:
    """Portable shell invocation: bash where present (Git Bash on Windows), else cmd/sh."""
    import shutil

    bash = shutil.which("bash")
    if bash:
        return [bash, "-c", command]
    import os

    if os.name == "nt":
        return ["cmd", "/c", command]
    return ["/bin/sh", "-c", command]
