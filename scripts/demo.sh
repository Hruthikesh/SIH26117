#!/usr/bin/env bash
# YANTRA demo — the seven scenarios of SPEC §20.2, run end-to-end on the available profile.
#
# On a GPU host set YANTRA_PROFILE=standard (or refinery) and the scenarios run on the real
# brain model straight from the goal text. With no GPU the default below (mock, unsealed) runs
# the same pipeline with scripted model reasoning but REAL tools, corpus, vision and rendering.
#
# Each step prints an elapsed time. Deliverables land under $YANTRA_DATA/evals/<run>/<scenario>/.
set -uo pipefail

PROFILE="${YANTRA_PROFILE:-mock}"
export YANTRA_PROFILE="$PROFILE"
# The mock profile is a dev/CI profile; it runs unsealed on a box with no GPU.
if [ "$PROFILE" = "mock" ]; then export YANTRA_SEALED="${YANTRA_SEALED:-0}"; fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${YANTRA_PYTHON:-$ROOT/.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="$(command -v yantra >/dev/null 2>&1 && echo yantra || echo "python -m yantra_server.cli")"
run() { echo; echo "=== $1 ==="; shift; local t0=$SECONDS; "$@"; echo "  (elapsed $((SECONDS - t0))s)"; }
yantra() { ( cd "$ROOT" && "$PY" -m yantra_server.cli "$@" ); }

echo "YANTRA demo — profile: $PROFILE"
run "prep: generate corpus + P&ID (idempotent)" yantra corpus generate --size small

# 1. Seal proof (§14.5) — target 45s. Verification + a live egress attempt that must be blocked.
run "1. Seal proof" yantra seal verify
run "1b. Seal egress demo (attempt must be blocked)" yantra seal demo

# 2-5. The agentic scenarios, each also an eval case, producing real deliverables.
run "2-5. Scenarios (pump reliability, P&ID review, code modernisation, consolidation)" \
    yantra eval run tasks

# 6. Extensibility — a dropped-in model is registered and probed; agents are discovered.
run "6. Extensibility: models + agents" bash -c "
    cd '$ROOT'
    '$PY' -m yantra_server.cli models list || true
    '$PY' -m yantra_server.cli agents list
"

# 7. Crash and resume — kill -9 mid-run, then 'yantra resume' completes it with no duplicate files.
#    The behaviour is verified deterministically by the resilience test suite (kill at each
#    scheduler transition, property-based). On a live host, run scenario 2 headless, kill the
#    server, then: yantra resume <run_id>.
run "7. Crash & resume (see resilience suite)" yantra eval run resilience

echo
echo "Demo complete. Retrieval/P&ID/latency numbers: yantra eval run retrieval pid latency"
echo "Full report + docs/EVALS.md:                   yantra eval run --write-doc"
