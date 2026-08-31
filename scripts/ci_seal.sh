#!/usr/bin/env bash
# Run the test suite inside a no-network namespace (SPEC §14.5: any test that needs
# the network is a bug). Requires Linux with unprivileged user namespaces.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v unshare >/dev/null; then
  echo "unshare not available; seal CI requires Linux" >&2
  exit 2
fi

# Ubuntu 24.04 runners restrict unprivileged userns via AppArmor; relax for this job.
if [ -w /proc/sys/kernel/apparmor_restrict_unprivileged_userns ] 2>/dev/null; then
  sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 || true
fi

exec unshare -rn bash -c '
  ip link set lo up 2>/dev/null || true
  export YANTRA_SEALED=1
  exec uv run pytest -q -m "not e2e" --no-header
'
