"""Sandboxed execution for model-initiated code/shell (SPEC §9.3)."""

from .base import Sandbox, SandboxError, SandboxLimits, SandboxResult, select_sandbox

__all__ = ["Sandbox", "SandboxError", "SandboxLimits", "SandboxResult", "select_sandbox"]
