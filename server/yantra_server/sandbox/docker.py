"""Docker backend: `--network none --read-only --cap-drop ALL` (hosts without bwrap)."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from .base import OutputCallback, Sandbox, SandboxLimits, SandboxResult, drain_process, now

DEFAULT_IMAGE = os.environ.get("YANTRA_SANDBOX_IMAGE", "yantra-sandbox:latest")


def docker_command(
    argv: list[str],
    *,
    workspace: Path,
    cwd: Path,
    limits: SandboxLimits,
    image: str = DEFAULT_IMAGE,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Pure construction of the docker run argument list."""
    rel_cwd = "/work"
    try:
        rel = cwd.resolve().relative_to(workspace.resolve())
        if str(rel) != ".":
            rel_cwd = f"/work/{rel.as_posix()}"
    except ValueError:
        pass
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(limits.max_pids),
        "--memory",
        f"{limits.max_rss_mb}m",
        "--cpus",
        "2",
        "--tmpfs",
        "/tmp:size=512m",
        "-v",
        f"{workspace.resolve()}:/work",
        "-w",
        rel_cwd,
        "-e",
        "YANTRA_SEALED=1",
        "-e",
        "HOME=/work",
    ]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [image, *argv]
    return cmd


class DockerSandbox(Sandbox):
    name = "docker"
    provides_isolation = True

    @classmethod
    def available(cls) -> bool:
        return shutil.which("docker") is not None

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
        cmd = docker_command(
            argv, workspace=self.workspace, cwd=cwd or self.workspace, limits=self.limits, env=env
        )
        started = now()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
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
            blocked_net_attempts=0,  # --network none: no interface exists
            backend=self.name,
            truncated=truncated,
        )
