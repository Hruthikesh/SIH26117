# The Seal — zero egress, proven

YANTRA guarantees that **no byte leaves the network**: not a prompt, not a document, not a
telemetry ping, not a `pip install`. The guarantee rests on five independent layers. Any one
alone is a claim; together they are a proof, and `yantra seal verify` checks all of them and
prints a signed certificate.

## The five layers

### Layer 1 — build-time hermeticity
`make bundle` vendors every runtime dependency (Python wheels, pnpm store, container images,
model weights, OCR/layout artifacts, fonts). `install.sh` installs with `--no-index` /
`--offline` / `docker load` and verifies every file against `bundle/MANIFEST.sha256`. The
product never resolves a package or a model from the internet because there is nothing to
resolve — everything is already on disk. `yantra seal verify` re-checks the manifest.

### Layer 2 — runtime environment lock (`seal/env.py`)
Every process the supervisor starts inherits an environment that forces offline, no-telemetry
behaviour and scrubs credentials/proxies. The server asserts the lock at startup and refuses
to run sealed if any variable is wrong. Each variable and the library it silences:

| Variable | Silences |
|---|---|
| `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `HF_DATASETS_OFFLINE` | huggingface_hub / transformers / datasets hub access |
| `HF_HUB_DISABLE_TELEMETRY`, `DISABLE_TELEMETRY`, `DO_NOT_TRACK` | library telemetry |
| `VLLM_NO_USAGE_STATS`, `VLLM_DO_NOT_TRACK` | vLLM usage stats |
| `QDRANT__TELEMETRY_DISABLED` | Qdrant server telemetry |
| `PIP_NO_INDEX`, `UV_OFFLINE`, `PIP_DISABLE_PIP_VERSION_CHECK` | pip/uv index access + version pings |
| `npm_config_update_notifier` | npm update pings |
| `NO_PROXY=*` and unset `*_PROXY` | proxy routing |
| unset `HF_TOKEN`, `OPENAI_*`/cloud-SDK prefixes, any `*_API_KEY`/`*_API_TOKEN`/`*_ACCESS_TOKEN`/`*_SECRET_KEY`, `SENTRY_DSN`, `OTEL_EXPORTER_OTLP_ENDPOINT` | credentials & external exporters (vendor-generic) |

`TOKENIZERS_PARALLELISM=false` quiets the tokenizers fork warning. `PYTHONPATH` gains
`server/` so `sitecustomize.py` loads the socket guard; `NODE_OPTIONS` gains
`--require tui/preload/seal.cjs` so Node children load the Node guard.

### Layer 3 — process socket guard (`seal/socket_guard.py`, `tui/preload/seal.cjs`)
Both runtimes monkey-patch their socket layer. In Python, `socket.connect`/`connect_ex`/
`sendto`/`getaddrinfo` are wrapped: a destination outside the allowlist raises
`SealViolation` (an `OSError`) and emits a `seal.blocked` event with the offending stack;
DNS for a non-allowlisted name returns `EAI_NONAME`. `sitecustomize.py` installs it before
any library imports, so it covers engines, sandboxed `python`, and MCP servers. The Node
preload does the same for `net.Socket.connect`, `dns.lookup`, and `dns.promises.lookup`.
Neither guard can be disabled without `YANTRA_SEALED=0`, which the TUI shows in red as
`UNSEALED (dev)`.

### Layer 4 — network isolation
`docker-compose.yml` puts every service on a network declared `internal: true` (no gateway);
only the server publishes `127.0.0.1:7331`. Sandboxed tool runs use `--unshare-net` (bwrap)
or `--network none` (docker) — there is no network interface inside the sandbox at all.
`scripts/seal_nftables.sh` optionally installs a host nftables table dropping all outbound
from the `yantra` user except the allowlist, with a drop counter the Seal Monitor reads.
This layer is recommended, not required: the compose isolation plus the process guard already
seal the workbench, and `yantra seal verify` reports whether nftables is present.

### Layer 5 — verification and proof
`yantra seal verify` runs: the env-lock assertion; the Python and Node guard self-tests
(attempt `1.1.1.1:443` and `example.com` DNS — both must fail); compose-network inspection;
a sandbox self-test (a `socket` connect inside the sandbox must fail); a scripted agent smoke
run that must complete with all guards active; and the bundle manifest check. It then prints
a **Seal Certificate** (git SHA, SBOM hash, model hashes, audit-chain head, per-check
results) signed with an operator Ed25519 key (`yantra seal keygen`).

`yantra seal demo` is the judge-facing proof: it fires `pip install requests` and a
`urllib.urlopen('https://example.com')` from sealed child processes; both are blocked and
appear in the Seal Monitor with their stack traces, while a document task keeps running.

## Continuous monitoring
`observe/seal_monitor.py` aggregates guard events (in-process callback + a JSONL side-channel
for child processes), reads nftables counters when present, and serves `GET /api/seal`
`{sealed, allowlist, blocked_attempts_total, last_attempts, layers}`. The TUI status line
shows `🔒 SEALED · 0 egress` and turns red with the count if anything is ever blocked — a
blocked attempt means the seal worked; the colour is a prompt to investigate which component
tried.

## Threat model — what is and is not covered
**Covered:** accidental or library-initiated egress (telemetry, update checks, hub fetches);
model-initiated egress via tools or sandboxed code; DNS exfiltration to public resolvers;
credential leakage through inherited environment.

**Not covered:** a root user who deliberately reconfigures the host (removes the guard,
rewrites nftables, sets `YANTRA_SEALED=0`); physical exfiltration; covert channels via
removable media; timing/side channels. The seal defends against software reaching out, not
against an administrator who has decided to defeat it — that is a personnel and physical
control, not a software one.
