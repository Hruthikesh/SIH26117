"""bubblewrap backend (Linux default): user+net namespaces, RO system, RW workspace only."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

from .base import OutputCallback, Sandbox, SandboxLimits, SandboxResult, drain_process, now


def bwrap_command(
    argv: list[str],
    *,
    workspace: Path,
    cwd: Path,
    limits: SandboxLimits,
    gpu: bool = False,
    extra_ro_binds: list[Path] | None = None,
) -> list[str]:
    """Pure construction of the bwrap argument list (unit-tested without Linux)."""
    cmd: list[str] = [
        "bwrap",
        "--unshare-all",
        "--unshare-net",
        "--die-with-parent",
        "--clearenv",
        "--setenv",
        "HOME",
        "/work",
        "--setenv",
        "PATH",
        "/usr/local/bin:/usr/bin:/bin",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "YANTRA_SEALED",
        "1",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind-try",
        "/lib",
        "/lib",
        "--ro-bind-try",
        "/lib64",
        "/lib64",
        "--ro-bind-try",
        "/bin",
        "/bin",
        "--ro-bind-try",
        "/sbin",
        "/sbin",
        "--ro-bind-try",
        "/etc/alternatives",
        "/etc/alternatives",
        "--ro-bind-try",
        "/etc/ssl",
        "/etc/ssl",
    ]
    venv = Path(sys.prefix)
    cmd += ["--ro-bind", str(venv), str(venv)]
    for extra in extra_ro_binds or []:
        cmd += ["--ro-bind-try", str(extra), str(extra)]
    cmd += ["--bind", str(workspace), "/work"]
    if gpu:
        cmd += ["--dev-bind-try", "/dev/nvidia0", "/dev/nvidia0"]
        cmd += ["--dev-bind-try", "/dev/nvidiactl", "/dev/nvidiactl"]
        cmd += ["--dev-bind-try", "/dev/nvidia-uvm", "/dev/nvidia-uvm"]
    rel_cwd = "/work"
    try:
        rel = cwd.resolve().relative_to(workspace.resolve())
        if str(rel) != ".":
            rel_cwd = f"/work/{rel.as_posix()}"
    except ValueError:
        pass
    cmd += ["--chdir", rel_cwd]
    cmd += ["--", *argv]
    return cmd


class BwrapSandbox(Sandbox):
    name = "bwrap"
    provides_isolation = True

    @classmethod
    def available(cls) -> bool:
        return sys.platform.startswith("linux") and shutil.which("bwrap") is not None

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
        cmd = bwrap_command(
            argv, workspace=self.workspace, cwd=cwd or self.workspace, limits=self.limits
        )
        if env:
            # injected after --clearenv via --setenv pairs, before the terminating "--"
            terminator = cmd.index("--")
            pairs: list[str] = []
            for key, value in env.items():
                pairs += ["--setenv", key, value]
            cmd = cmd[:terminator] + pairs + cmd[terminator:]
        started = now()
        from .limits import children_rusage, make_preexec

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            preexec_fn=make_preexec(self.limits),
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
        wall = now() - started
        cpu_s, peak_rss = children_rusage()
        return SandboxResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            wall_s=round(wall, 3),
            cpu_s=cpu_s,
            peak_rss_mb=peak_rss,
            timed_out=timed_out,
            files_changed=self.diff_files(before),
            blocked_net_attempts=0,  # --unshare-net: there is no network namespace at all
            backend=self.name,
            truncated=truncated,
        )
