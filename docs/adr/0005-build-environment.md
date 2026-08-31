# 0005 — Build environment: Windows 11, no GPU, no Docker

**Status:** accepted (M0).

**Context.** SPEC §0 requires building/testing with `MockEngine` and tiny models when no GPU
is present; this build machine is Windows 11 with uv, Node 24 (spec says Node 22 LTS; Node 24
is the current LTS here and Ink/Vite are unaffected — using it), pnpm, git, and no make/
Docker/NVIDIA driver.

**Decision.** All code paths are written for the production Linux targets (bwrap, nftables,
vLLM, compose) and unit-tested with mocks on Windows. Tests that require Linux facilities
(`unshare -rn`, bwrap, nftables) run in CI (ubuntu runner) and are marked/skipped locally
with the exact command recorded in `docs/BUILD_LEDGER.md`. Dev startup uses `uv run` / `pnpm`
commands directly instead of make (Makefile targets exist for POSIX hosts).

**Consequences.** The ledger distinguishes "built + mock-tested" from "verified on capable
hardware"; nothing is stubbed, but some verification is deferred to Linux CI or the demo
machine.
