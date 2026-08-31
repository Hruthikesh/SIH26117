# 0011 — Compose topology: attach-mode engines, in-process pooling/ingest

**Decision.** In docker-compose, model engines run as sibling containers and the server's
supervisor **attaches** to them (`EngineSpec.url`, selected via `YANTRA_PROFILE_FILE` →
`models/profiles/<profile>-compose.yaml`) instead of spawning; health/restart stays with
compose. Embedding pooling and ingestion workers stay **in-process** in the server (the
spec's service list names them; a separate container adds a network hop and a second copy
of the model cache for no isolation gain — revisit only if ingest CPU starves the server).
`web-build` is a Dockerfile stage, not a runtime service. Lite runs utility/embed/rerank as
llama.cpp CPU containers and has no resident OCR model (the 24 GB card is full with the
Int4 brain) — ingestion uses the CPU OCR fallback.

**Network.** All services on `sealnet` (`internal: true`); only `server` also joins `edge`
to publish `127.0.0.1:7331` (ports on a purely internal network are silently non-functional
in docker). Engine DNS names resolve via docker's embedded resolver at 127.0.0.11 —
loopback, inside the seal allowlist.
