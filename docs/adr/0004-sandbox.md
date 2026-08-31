# 0004 — Sandbox: bubblewrap first, Docker fallback, explicit dev-only local backend

**Status:** accepted (M0), extended (M2).

**Context.** All model-initiated code/shell must run with no network, a bounded filesystem
view, and resource limits, on Linux servers primarily, with a documented Windows/macOS dev
path.

**Decision.** `bwrap --unshare-all --unshare-net` + seccomp + prlimit is the Linux default;
`docker run --network none …` is the fallback contract for hosts without bwrap. For native
Windows/macOS development *without Docker* (this build machine), a third `local` backend runs
tools as plain subprocesses — it is only selectable when `YANTRA_SEALED=0`, the TUI shows
`UNSEALED (dev)` in red, and `yantra doctor` flags it. Production profiles refuse it.

**Consequences.** One `Sandbox` contract with three backends; seal tests assert the bwrap and
docker backends have no network; the local backend exists so the demo and tests can run on a
plain Windows laptop, with loud, honest signalling that it provides no isolation.
