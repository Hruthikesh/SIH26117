#!/usr/bin/env bash
# YANTRA air-gapped installer (SPEC §21). Runs INSIDE the extracted bundle directory on the
# plant host. Idempotent: re-running upgrades in place (server migrates its DB at startup).
#
#   tar -xf yantra-<version>-<profile>.tar -C /opt/yantra-bundle
#   cd /opt/yantra-bundle && sudo bash install.sh [--profile lite|standard|refinery]
#                                                 [--home /opt/yantra] [--with-nftables]
set -euo pipefail

PROFILE=""
YHOME="/opt/yantra"
WITH_NFT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --home) YHOME="$2"; shift 2 ;;
    --with-nftables) WITH_NFT=1; shift ;;
    *) echo "unknown flag $1"; exit 2 ;;
  esac
done
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

step() { echo; echo "== $* =="; }

# 1. Verify the bundle manifest before touching anything.
step "verify bundle manifest"
sha256sum -c MANIFEST.sha256 --quiet && echo "manifest OK" || {
  echo "MANIFEST MISMATCH - the bundle is corrupt or tampered; aborting." >&2; exit 1; }

# 2. Pick the profile: flag > detected GPUs.
if [ -z "$PROFILE" ]; then
  GPUS=$(command -v nvidia-smi >/dev/null && nvidia-smi -L 2>/dev/null | wc -l || echo 0)
  if   [ "$GPUS" -ge 4 ]; then PROFILE=refinery
  elif [ "$GPUS" -ge 1 ]; then PROFILE=standard
  else PROFILE=lite; fi
  echo "detected $GPUS GPU(s) -> profile $PROFILE (override with --profile)"
fi

# 3. Load images (skipped when the bundle was built with YANTRA_SKIP_IMAGES=1).
if [ -f images.tar ]; then
  step "docker load"
  docker load -i images.tar
fi

# 4. Place models + app assets under $YHOME.
step "install files to $YHOME"
mkdir -p "$YHOME"
rsync -a --delete app/ "$YHOME/app/" 2>/dev/null || cp -r app/. "$YHOME/app/"
mkdir -p "$YHOME/models"
cp -an models-weights/. "$YHOME/models/" 2>/dev/null || true

# 5. Verify model checksums offline.
if [ -f "$YHOME/models/MODELS.sha256" ]; then
  step "verify model weights"
  python3 "$YHOME/app/fetch_models.py" --verify --dest "$YHOME/models" \
    || { echo "model weights failed verification; aborting." >&2; exit 1; }
fi

# 6. Write the compose environment + a starter yantra.yaml (kept if already present).
step "configure"
cat > "$YHOME/app/.env" <<EOF
YANTRA_PROFILE=$PROFILE
YANTRA_MODELS_DIR=$YHOME/models
EOF
if [ ! -f "$YHOME/app/yantra.yaml" ]; then
  cat > "$YHOME/app/yantra.yaml" <<EOF
# Written by install.sh - operator-owned from here on.
profile: $PROFILE
seal: {enabled: true}
EOF
fi
echo "profile $PROFILE; models at $YHOME/models"

# 7. Optional host firewall layer (nftables egress deny for the yantra services).
if [ "$WITH_NFT" = "1" ]; then
  step "nftables egress table"
  bash "$YHOME/app/seal_nftables.sh" install
fi

# 8. Bring the stack up and prove the seal.
step "docker compose up"
cd "$YHOME/app"
docker compose --profile "$PROFILE" up -d
echo "waiting for the server to become healthy..."
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:7331/api/health >/dev/null 2>&1; then break; fi
  sleep 5
done

step "doctor + seal verify"
docker compose exec -T server yantra doctor || true
docker compose exec -T server yantra seal verify || {
  echo "SEAL VERIFICATION FAILED - do not use until resolved." >&2; exit 1; }

step "done"
cat <<EOF
YANTRA is up.
  dashboard:  http://127.0.0.1:7331        (from this host only)
  terminal:   yantra tui                    (Node TUI; see docs/RUNBOOK.md)
  demo:       docker compose exec -T server bash scripts/demo.sh
  upgrade:    extract the new bundle over this one and re-run install.sh
EOF
