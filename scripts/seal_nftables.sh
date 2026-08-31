#!/usr/bin/env bash
# Layer 4 (host) — nftables table dropping all outbound from the yantra user/cgroup except
# the allowlist, with a drop counter the Seal Monitor reads (SPEC §14.4).
#
#   sudo scripts/seal_nftables.sh install [yantra_uid]
#   sudo scripts/seal_nftables.sh uninstall
#
# Recommended, not required: docker `internal` networks + the per-process socket guard
# already isolate the workbench. This adds a kernel-level backstop and a visible counter.
set -euo pipefail

TABLE="yantra_seal"
ACTION="${1:-status}"
YANTRA_UID="${2:-$(id -u yantra 2>/dev/null || echo 0)}"
ALLOW_V4="${YANTRA_SEAL_ALLOW_V4:-127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16}"

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "must run as root (nftables changes)" >&2
    exit 1
  fi
}

case "$ACTION" in
  install)
    require_root
    if [ "$YANTRA_UID" -eq 0 ]; then
      echo "refusing to seal uid 0; create a 'yantra' user or pass a uid" >&2
      exit 1
    fi
    nft list table inet "$TABLE" >/dev/null 2>&1 && nft delete table inet "$TABLE"
    nft -f - <<NFT
table inet ${TABLE} {
    counter blocked { }
    chain output {
        type filter hook output priority 0; policy accept;
        meta skuid ${YANTRA_UID} ip daddr { ${ALLOW_V4} } accept
        meta skuid ${YANTRA_UID} ip6 daddr ::1 accept
        meta skuid ${YANTRA_UID} meta l4proto { tcp, udp } counter name blocked drop
    }
}
NFT
    echo "installed nftables table ${TABLE} for uid ${YANTRA_UID}"
    ;;
  uninstall)
    require_root
    nft delete table inet "$TABLE" 2>/dev/null && echo "removed ${TABLE}" || echo "${TABLE} not present"
    ;;
  status)
    nft list table inet "$TABLE" 2>/dev/null || echo "${TABLE} not installed"
    ;;
  *)
    echo "usage: $0 install|uninstall|status [uid]" >&2
    exit 2
    ;;
esac
