"""Resource-limit helpers (POSIX rlimits), typed to be analyzable on any platform."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from .base import SandboxLimits

try:
    import resource as _resource_mod
except ImportError:  # Windows: rlimits are unavailable; backends degrade gracefully
    _resource_mod = None  # type: ignore[assignment]

res: Any = cast(Any, _resource_mod)


def make_preexec(limits: SandboxLimits) -> Callable[[], None] | None:
    """A preexec_fn applying CPU/RSS/FD/process rlimits, or None where unsupported."""
    if res is None:
        return None

    def _apply() -> None:  # pragma: no cover - runs in the forked child (Linux only)
        cpu = int(limits.cpu_s)
        res.setrlimit(res.RLIMIT_CPU, (cpu, cpu + 5))
        rss = limits.max_rss_mb * 1024 * 1024
        res.setrlimit(res.RLIMIT_AS, (rss, rss))
        res.setrlimit(res.RLIMIT_NOFILE, (512, 512))
        res.setrlimit(res.RLIMIT_NPROC, (limits.max_pids, limits.max_pids))

    return _apply


def children_rusage() -> tuple[float | None, float | None]:
    """(cpu_seconds, peak_rss_mb) of reaped children, where the platform reports it."""
    if res is None:
        return None, None
    usage = res.getrusage(res.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime, usage.ru_maxrss / 1024
