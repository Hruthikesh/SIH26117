# YANTRA operations runbook

Audience: the plant IT/OT engineer who owns the box. Everything here is offline.

## Install (air-gapped)

On a connected machine: `python scripts/fetch_models.py --profile <p>` then
`bash scripts/bundle.sh <p>`. Move the tar by disk to the plant host, then:

```bash
tar -xf yantra-<version>-<profile>.tar -C /opt/yantra-bundle
cd /opt/yantra-bundle && sudo bash install.sh --with-nftables
```

`install.sh` verifies MANIFEST.sha256 and model checksums, loads images, writes
`/opt/yantra/app/.env` + `yantra.yaml`, brings the compose stack up, runs `yantra doctor`
and **fails hard if `yantra seal verify` fails**. Re-running upgrades in place (the server
migrates its database at startup).

## Start / stop / status

```bash
cd /opt/yantra/app
docker compose --profile standard up -d      # start (profile from .env)
docker compose down                          # stop
docker compose ps                            # container health
curl -s http://127.0.0.1:7331/api/health     # server health JSON
```

Bare-metal (no docker, dev or lite hosts): `yantra serve` runs everything in one process
and spawns vLLM/llama.cpp itself from `models/profiles/<profile>.yaml`.

## Daily checks

- Dashboard `http://127.0.0.1:7331` → **Seal Monitor**: must show SEALED, 0 unexplained
  blocked attempts. Every blocked attempt lists the process and destination — investigate
  any you did not cause with `yantra seal demo`.
- `yantra audit verify` — the hash chain must verify; export segments for records with
  `yantra audit export --from N --to M --out audit.jsonl`.
- **Evaluations** page after model or config changes: run `yantra eval run` and compare
  pass rates with history.

## Logs and traces

- Engine logs: `/data/logs/engine-<id>-<replica>.log` inside the server container
  (volume `yantra-data`); `docker compose logs vllm-brain` for container stdout.
- Every model/tool/retrieval call is a span in the local trace store; open a run in the
  dashboard → Runs → trace, or query `spans` in the SQLite/Postgres DB directly.

## Backup / restore

State lives in exactly two places: the `yantra-data` volume (DB, artifacts, indexes,
audit chain) and `/opt/yantra/models` (weights, immutable). Cold-copy the volume while the
stack is down; restore = copy back + `docker compose up -d`. Postgres (refinery): use
`pg_dump yantra` on the postgres service instead of copying its volume live.

## Benchmarks and profiles

```bash
yantra doctor          # GPUs, binaries, TODO-by-operator markers, profile recommendation
yantra bench llm       # TTFT + tok/s through the live gateway -> profile measured: block
yantra bench ingest    # pages/s + chunks/s on this hardware  -> profile measured: block
```

Switch profile by editing `.env` (compose) or `yantra.yaml` (`profile:`), then restart.

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| server unhealthy | `docker compose logs server` | most often a missing model dir — `python3 app/fetch_models.py --verify --dest /opt/yantra/models` |
| engine `unavailable: weights missing` | `yantra models list` shows the expected path | fetch on a connected machine, copy into `/opt/yantra/models` |
| engine `unhealthy` after start | vLLM can take minutes to load; healthcheck `start_period` is 300 s | `docker compose restart vllm-brain`; check VRAM with `nvidia-smi` |
| retrieval degraded, "lexical only" warning | qdrant container health | `docker compose restart qdrant`; the workbench keeps answering from the lexical index meanwhile |
| `seal verify` fails `env_locked` | `YANTRA_SEALED` in the server env | never run the plant host unsealed; fix the env, restart, re-verify |
| run stuck / server killed mid-run | `yantra resume <run_id>` | crash-only design: the run continues from its checkpoint without duplicating files |
| dashboard empty after upgrade | browser cache of old assets | hard-reload; assets are content-hashed so this is rare |

## Security notes

- The compose network is `internal: true`; only 127.0.0.1:7331 is published. Remote access,
  if required, is the operator's reverse-proxy/VPN decision — never expose 7331 directly.
- `install.sh --with-nftables` installs the host-level egress deny table
  (`scripts/seal_nftables.sh`); `yantra seal verify` proves all layers and signs a
  certificate you can archive with audit exports.
- Model weights are read-only mounts. Adding a model is an explicit operator action
  (`yantra models add`), refused for ≥120B without `--allow-large` and always audited.
