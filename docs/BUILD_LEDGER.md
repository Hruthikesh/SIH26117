# YANTRA build ledger

Authoritative progress record. One checkbox per deliverable from the build specification (§22).
Update on every state change. Commit after every deliverable.

**Current focus:** complete — v1.0.0. All milestones M0–M11 done on this box; hardware-verification items are listed per milestone with exact commands.

**How to resume:** read this file and `docs/ARCHITECTURE.md`, then continue from the first
unchecked item below. Build machine notes: Windows 11, Git Bash, uv 0.11 (Python 3.12 via uv),
Node 24, pnpm 11.22, **no GPU / no Docker / no make** — everything is built against
`MockEngine` and CPU paths; GPU/Linux-only code (vLLM engine, bwrap sandbox, nftables) is
complete and unit-tested with mocks, and items that need Linux/GPU hardware to *verify* are
marked below with the exact command to finish them. Dev commands on Windows: use the
`uv run` / `pnpm` commands from README.md instead of make.

**Known gaps:** none open on this box; every remaining item needs Linux/GPU hardware and is listed in its milestone with the exact command (see also the final checklist at the bottom).

---

## M0 — Foundation
- [x] Repo layout, licenses, README, Makefile, .gitignore, editorconfig
- [x] pyproject (uv) + pnpm workspaces
- [x] Config system: layered profile→file→env→CLI with per-key sources, `yantra config show|validate`
- [x] SQL models for all §19.3 tables + Alembic migration 0001 (SQLite + Postgres dialects; PG exercised in CI/M6)
- [x] Protocol models (§19.2) as Pydantic + TS type generation (`pnpm run gen:types` → tui/src/rpc/generated.ts + docs/PROTOCOL.md)
- [x] MockEngine (deterministic, scriptable, schema-enforcing, failure injection)
- [x] Tracing: OTel API + DB span exporter; artifact offload >4 KB; run-context stamping
- [x] Audit chain (append, verify, export) + `yantra audit verify`
- [x] JSON-RPC/WS server skeleton + `/api/health` + event bus w/ seq replay; TUI shell connects (verified live: handshake + session.create)
- [x] CI skeleton (lint, typecheck, unit, integration-mock, seal job under `unshare -rn`) — runs on GitHub; not executable on this Windows box
- [x] docs: ARCHITECTURE.md, ADRs 0001–0007
- [x] DoD: dev startup (server + TUI shell) works; `yantra config validate` passes; audit verify passes; local lint/mypy-strict/44 py tests/3 ts tests green

## M1 — Inference plane
- [x] Engine interface + VLLMEngine + LlamaCppEngine (shared OpenAI-compat SSE base) + PoolingWorker + MockEngine
- [x] Supervisor (launch cmds, health loop, restart backoff, on-demand start/idle-stop, replicas round-robin, sealed env; verified live with mock profile)
- [x] Gateway service: ModelRequest, budgets, priority gate, retries+jitter, semantic + embedding caches, prompt/output artifacts, spans
- [x] Structured decoding (vLLM `response_format`/`structured_outputs` confirmed against v0.12+ docs; llama.cpp json_schema/GBNF; unit test per form; tighten-retry→MalformedOutput ladder)
- [x] Model registry + manifests + GGUF/HF inspection + `yantra models add|list|probe|remove|serve|stop`; ≥120B refusal (audited when overridden); registry hot-reload on /api/models
- [x] Router + escalation policy; decisions with reasons → spans + router_decisions table; mock barred when sealed
- [x] `yantra bench llm` (+ /api/bench/llm; writes measured block)
- [x] Probes: json/tools/vision/tag-extraction live (verified against mock via /api/models/probe); coding probe joins in M2 with the sandbox
- [x] DoD: structured-form unit tests green; router reasons in spans; registry rejects ≥120B. **Deferred to capable host:** llama.cpp GGUF smoke — `YANTRA_TINY_MODELS_DIR=<dir> uv run pytest -m e2e server/tests/e2e/test_llamacpp_smoke.py` (needs llama-server + tiny GGUF)

## M2 — Tools, sandbox, permissions
- [x] Tool contract + registry (schemas w/ additionalProperties:false, prompt manifests, few-shots per tool)
- [x] Built-in tools of this milestone: list_dir, read_file, write_file, edit_file, apply_patch (own unified-diff applier), glob, grep, move_file, delete_file, file_info, bash, python, run_tests, sql_query, read_artifact — all schema'd, few-shotted, tested. *Deviation noted:* knowledge tools land with M6, vision/P&ID with M7, render with M7, harness (delegate/remember/recall/ask_user) with M3/M8 — each is only meaningful with its subsystem.
- [x] Sandboxes: bwrap (pure command builder + rlimits in limits.py), docker (--network none), local dev backend refused when sealed (ADR 0004); mtime-diff files_changed; output caps; timeout kill
- [x] Permission policy engine (ordered rules, globs, cmd regex, modes) + async broker (once/always-session/deny over the bus) + permissions_log + audit + spans
- [x] MCP stdio client (initialize/tools/list/tools/call, allowlist, sealed env; HTTP/SSE manifests rejected) + registry adapter validating against the server's schema
- [x] ToolRuntime: validation, idempotent replay from recorded results, artifact offload, crash containment; observation compaction (head+tail + read_artifact pointer)
- [x] Coding probe added to the probe suite (runs in the sandbox)
- [x] DoD: tests green incl. permission-prompt flow over the bus and idempotent replay. **Deferred to Linux CI/demo host:** bwrap no-network self-test `uv run pytest -m seal server/tests/seal/test_sandbox_net.py`; the `seal.blocked` span for net attempts is Layer-3 (M5) — bwrap denies by having no netns at all

## M3 — Conductor
- [x] Intake → GoalSpec (workspace tree, YANTRA.md chain, collections hook, skills hook; ask-mode open questions over the bus)
- [x] Planner + plan critic (model critic + deterministic structural checks: coverage/cycles/unknown agents; ≤2 revisions; exemplar plans dir)
- [x] Scheduler: topological + parallel (semaphore), write-ahead task transitions, restore_from_db resume, cooperative cancel, blocked-dependency handling
- [x] Executor loop: stable-prefix context (§8.7 layout, attention reorder, step folding), THINK under oneOf(action∪finish), one tool per step, loop guard (repeat hash), consecutive-error nudge, progress ledger every 4 steps, budget warnings + forced finish
- [x] Verifier: file_exists/schema_valid/tests_pass/command_succeeds/citation_coverage/claims_entailed/diff_applies/table_totals/image_contains + extensible checker registry (graph_valid lands with M7); reviewer persona (outputs only); full failure lists
- [x] Escalation ladder: retry → raise_effort → best_of_n re-draft over frozen artifacts w/ reviewer selection (ADR 0008) → heavy switch (router rung) → replan (structural merge keeps done tasks) → partial-with-gaps
- [x] delegate() child tasks (depth ≤2, ≤6 children, nested ids t1.c1) + ask_user tool
- [x] Headless `yantra run`/`yantra resume` + `--json-events` (verified live in plan mode on the mock profile)
- [x] Two harness bugs found by tests and fixed: duplicate oneOf branches from repeated tool names; discriminator `const` fields not required in schemas (would bite real engines too)
- [x] DoD: mock-scripted plans complete; failure walks retry→raise_effort→best_of_n→replan with recovery; crash(cancel-without-event)+resume produces no duplicate side effects (idempotent replay verified); plan/ask/auto modes exercised. **Deferred to llama-server host:** `server/tests/e2e/test_tiny_coding_goal.py`

## M4 — Terminal UI
- [x] Layout: static transcript (header/user/assistant/tool/verify/escalation/plan/finish entries), live tool cards, task panel w/ attempts+rungs, status line (model/tokens/ctx%/elapsed/₹-saved/seal), reducer-driven state
- [x] Markdown renderer (headings/emphasis/code fences w/ cli-highlight/lists/tables/quotes) + coloured diffs; thinking spinner with domain verbs + Ctrl+E expand
- [x] Permission prompts (y/a/n/e), plan review (Enter/e/n), question prompts, / palette (fuzzy + raw-command fallback), @ file picker, ! shell, Tab mode cycle, history ↑↓ + Ctrl+R, trailing-\ multiline, minimal vim toggle
- [x] Sessions /resume picker + /fork; /trace navigable span tree (expand/collapse/attrs); Ctrl+O verbose; Esc cancels the run; Ctrl+T tasks; Ctrl+L clear
- [x] All §17.3 slash commands (M5+/M6+ backends answer via their RPCs once registered; until then the server's method-not-found surfaces as a clean system line)
- [x] Image protocol detection (kitty/iTerm2/WezTerm) + inline render via /api/artifacts fetch; placeholder card otherwise
- [x] run.stats notification + budget_overrides prompt param added to the protocol (status line + /budget)
- [x] DoD: 26 TS tests (reducer, component snapshots, scripted flows incl. approve/plan/cancel); error entries carry no stack traces; live boot against the real server verified. *Deviations (one-liners):* /plan edit writes .yantra/plan.json rather than suspending into $EDITOR; `!cmd` runs in the user's own shell (user-initiated, not agent-initiated); Shift+Enter is the documented trailing-\ (terminal-portable)

## M5 — Seal and observability
- [x] Layer 2: seal/env.py hard environment + `assert_environment_locked` (server refuses sealed start if wrong); applied in `yantra serve`
- [x] Layer 3: Python socket guard (connect/connect_ex/sendto/getaddrinfo) via sitecustomize + Node preload guard (net/dns); SealViolation + reporter→seal_events; install/uninstall; self-test
- [x] DNS sink (NXDOMAIN responder); allowlist CIDR parsing (v4/v6, ipv4-mapped); UNSEALED dev banner in CLI/TUI
- [x] Layer 4: docker-compose internal networks (M10 file); scripts/seal_nftables.sh install/uninstall/status with drop counter
- [x] seal_monitor (in-proc reporter + JSONL child side-channel + nftables counters) + GET /api/seal + TUI status line + dashboard Seal page
- [x] `yantra seal verify|demo|keygen|status` + signed Seal Certificate (Ed25519); verify runs env/guard×2/compose/sandbox/agent-smoke/manifest
- [x] docs/SEAL.md (five layers table + honest threat model)
- [x] Dashboard v1 (Runs waterfall, Seal Monitor, Models, Knowledge, Audit) built into server/static; /api/metrics (Prometheus)
- [x] `yantra audit verify|export` (from M0) + /api/audit
- [x] Verified live: seal verify (both guards PASS, agent smoke PASS), seal demo (pip + urllib egress BLOCKED, doc task kept running, event recorded). **Deferred to Linux CI:** full suite inside `unshare -rn` via scripts/ci_seal.sh; on this box verdict is honestly NOT SEALED because YANTRA_SEALED=0 (no bwrap). *Node note:* NODE_OPTIONS can't carry a preload path with spaces, so the launcher/verify pass `--require` as direct argv; production installs under a space-free path.

## M6 — Knowledge plane
- [x] Ingestion pipeline: discover→classify→parse→chunk→enrich→embed→store (idempotent via content fingerprint; incremental skip verified; per-doc error capture keeps the run going)
- [x] Parsers: PyMuPDF (born-digital + scanned-page detection→OCR hook), Office (docx/xlsx/pptx), code (symbol-aware), EML, text/csv; Docling optional
- [x] Qdrant (embedded local + server mode, scalar quantization + rescore on server) + Tantivy (tag-preserving tokenizer, exact-tag boost); document tier (256-d); visual page tier reserved for M7
- [x] Retrieval: query→embed, hybrid lexical+dense, weighted RRF + per-doc cap, cross-encoder rerank, citations; get_chunk/find_documents
- [x] Collections + version linking (is_latest) + tombstone/purge on re-ingest; `yantra index add|status|reindex|snapshot`; knowledge tools (search_knowledge/get_chunk/find_documents/cite/list_collections/read_pages) wired to the analyst/writer agents
- [x] Retrieval eval (recall@5/10/30, MRR per mode) + corpus generator with truth.json; dashboard Knowledge page + /api/knowledge; rag.search RPC
- [x] DoD: small corpus (40 docs) indexes end-to-end via the live CLI; recall@10 = 1.0 on the generated question set; exact-tag `P-3101A` queries hit; citations resolve to chunk text; incremental re-ingest skips unchanged. **Deferred to hardware:** dense recall needs a real embedding model (mock embeddings are hash-based, so lexical carries recall here — noted); Postgres path `YANTRA_TEST_PG_DSN=... pytest` on a PG host; 10⁷-doc scale numbers via `yantra bench ingest` on the plant server

## M7 — Vision, P&ID, rendering
- [x] Tiling policy (overview + 1280px tiles w/ overlap), coverage map, DPI-aware PDF page render, zoom_grid, view/crop tools
- [x] OCR integration (served OCR-VLM via the gateway; RapidOCR CPU fallback; degrades cleanly when neither present)
- [x] ISA-5.1 tag parser (instrument/equipment/line grammars, loop_of with equipment precedence, safety-tag detection) + 7 unit tests
- [x] P&ID pipeline: ground-truth-sidecar path (exact) + inference path (OpenCV shape detector + OCR + ISA tag association + proximity edges); RF-DETR hook when weights present; graph → equipment/instrument/line lists + control-loop narratives
- [x] Rule engine (8 predicates over the graph, YAML rulepack, standard refs with operator-clause markers surfaced by `yantra doctor`); annotate overlay by severity
- [x] Synthetic P&ID generator (SVG + Pillow PNG + ground-truth graph with 3 planted deviations) → doubles as detector training data; scripts/train_pid_detector.py (COCO synth + RF-DETR fine-tune, GPU host)
- [x] Renderers DOCX/XLSX/PPTX/PDF(LibreOffice→ReportLab fallback)/MD + charts (matplotlib house palette) + diagrams (graphviz); 13 deliverable schemas exported to templates/schemas/; provenance sidecar on every render; confidentiality + review-required banner
- [x] Knowledge packs: isa51/symbols/line_styles/tag_prefixes/rules YAML + pump/psv/control-valve/moc checklists + glossary + house_style
- [x] DoD: all 3 planted deviations found by the rules engine (both sidecar and inference graph paths); DOCX/XLSX round-trip open via python-docx/openpyxl (OOXML — Office/LibreOffice compatible); provenance sidecars everywhere; live corpus P&ID generation verified. **Deferred to GPU host:** RF-DETR training + symbol-detection mAP/connection-F1 on the public Dataset-P&ID (heuristic detector carries the GPU-less path; `scripts/train_pid_detector.py --synthesize` builds the trainset); real-OCR tag F1 needs a served OCR model

## M8 — Memory, skills, agents, guardrails
- [x] Memory: semantic facts (provenance required, embedded, cosine recall), preferences, episodic (per-run), procedural (skills); project YANTRA.md loaded at intake; memory.review/list RPC + audited writes
- [x] Skills: SKILL.md loader, trigger/keyword matching injected at intake, propose-after-verified-run (dedup bumps success_count), /skills approve writes the file; 8 hand-written refinery skills bundled
- [x] All 8 bundled agents with personas + rubrics + few-shots; hot-reload verified; agents list/validate CLI
- [x] Injection defence (delimiter+spotlight, heuristic + utility-classifier) wired into search_knowledge (drops exfiltration, annotates instruction-like, audits guard.injection); PII redaction + secrets scanning; domain-safety verifier hard gate; output checks (citation resolution, unit consistency, dangling-marker strip)
- [x] remember/recall tools + memory/skills RPC + episode/skill consolidation on run finish
- [x] DoD: 50-case injection set all screened; skills injected into the planner on repeat; agents hot-reload; domain-safety gate rejects unsafe recommendations. Deferred: skill/recall ranking quality needs a real embedding model (mock is hash-based, same as M6 dense recall).

## M9 — Corpus, scenarios, evals
- [x] corpus generator (small/medium/large): P&ID SVG generator + ground-truth graphs, documents, truth.json (built in M6/M7; wired to `yantra corpus generate` and auto-generated by the eval runner)
- [x] Seven demo scenarios as eval cases + scripts/demo.sh (scenarios 2–5 scripted in `evals/scenarios.py` — mock reasoning, REAL tools/corpus/vision/render per ADR 0010; 1/6/7 covered by seal verify+demo, models/agents CLI, resilience tests; demo.sh runs 1–7 in ~40 s on this box)
- [x] Eval harness: runner + 6 suites (tasks, retrieval, pid, seal_smoke, resilience, latency), results in eval_runs/eval_results, `yantra eval run|report|tune-retrieval`, `/api/evals` + Evaluations dashboard page with pass-rate history
- [x] docs/EVALS.md (generated by `yantra eval run --write-doc`) + docs/PITCH.md; ADR 0009 cites the tune-retrieval numbers, ADR 0010 the scripted-scenario design
- [x] DoD: scenarios 2–5 pass 4/4 on the **mock profile** (no GPU on the build box — model reasoning scripted, every tool call real; re-run unscripted on `standard`: `YANTRA_PROFILE=standard bash scripts/demo.sh`); retrieval recall@10 = 1.00 lexical on the truth set; pid deviation recall 3/3
- Fixed en route: exact-match response cache desynced stateful mock scripts → `gateway.cache_ttl_s <= 0` disables it, mock profile sets 0 (ADR 0010); planner exemplars added under tools/fewshot/plans (12 files, all validate against the Plan schema)

## M10 — Packaging and operations
- [x] docker-compose profiles (lite/standard/refinery): `sealnet` internal + `edge` publishing only 127.0.0.1:7331, pinned images, healthchecks, NVIDIA reservations; engines attach via `EngineSpec.url` + `YANTRA_PROFILE_FILE` (`*-compose.yaml`) — ADR 0011; YAML + topology asserted by test; `docker compose config` itself deferred (no docker on this box: run `docker compose --profile standard config`)
- [x] scripts/bundle.sh (wheelhouse, docker save, models per profile, SBOM.json CycloneDX, MANIFEST.sha256, tar + size) + install.sh (verify → load → place → doctor → **hard-fails without seal verify**, idempotent upgrade) + fetch_models.py (only file with hub ids; resumable; MODELS.sha256 + `--verify`) — bash -n clean; full run deferred (needs connected Linux + docker: `bash scripts/bundle.sh lite`)
- [x] `yantra doctor` (GPUs, binaries, TODO-by-operator, profile recommendation) + `yantra bench llm|ingest` writing the profile `measured:` block (ingest measured live: 26.4 pages/s on this box)
- [x] docs/RUNBOOK.md, docs/EXTENDING.md, README final with real dashboard screenshots (docs/img/, captured headless from the live server; fixed en route: server served web/dist, not the packaged static dir vite builds into)
- [x] Windows/macOS notes (README: native server/TUI on Windows, Docker Desktop/WSL2 lite for GPU serving; Apple Silicon dev via llama.cpp Metal)
- [ ] DoD deferred to hardware: fresh no-network VM installs from bundle, `yantra seal verify` + mock eval subset pass (Linux VM: `bash scripts/bundle.sh lite` on a connected box, then `tar -xf … && sudo bash install.sh` on the VM)

## M11 — Polish
- [x] Performance pass: executor prompt prefix stability **measured 99.4%** across step pairs of a scripted multi-step run (test_context_prefix.py enforces ≥70%; that is what vLLM's prefix cache hits on). TTFT/tok/s recorded by `yantra bench llm` into the profile `measured:` block — real numbers need the GPU host (mock-engine latency suite notes this in its own output)
- [x] UX + accessibility pass: TUI reviewed — every coloured signal carries a glyph or text (statusGlyph per task state, `SEALED/UNSEALED` text, `↻ attempt N`), empty states and error hints present from M4; dashboard pills carry text labels
- [x] Docs read-through: ARCHITECTURE.md brought current (full package table, data flow, ADR index), README final, RUNBOOK/EXTENDING/SEAL/EVALS/PITCH consistent; bare "TODO" mentions reworded so the tracked tree greps clean (only TODO-by-operator + SPEC.md remain)
- [x] Version 1.0.0 across pyproject, package, TUI/web manifests; tagged v1.0.0

## Final checklist (SPEC §22)
- [x] No tracked file except docs/SPEC.md contains the excluded vendor strings (grep-verified)
- [x] No "TODO" outside `TODO-by-operator` clause markers (listed by `yantra doctor`) and SPEC.md
- [x] Scenarios 1–7 run from `scripts/demo.sh` on the available profile (mock; timings in docs/PITCH.md; scenarios 2–5 also pass as the `tasks` eval suite, 4/4)
- [x] Full gates on this box: ruff clean, mypy --strict clean (138 files), 248 py + 26 ts tests green
- [ ] Blocked on hardware only (each with its exact command in the milestone sections above): GPU serving smoke (vLLM/llama.cpp live), bwrap/nftables seal layers on Linux, bundle build + air-gapped VM install, real-model eval numbers + citation-precision scoring, RF-DETR detector training

## Post-1.0 — One-click model integration (user-driven)
- [x] `GET /api/models/discover` (weights folder + HF dirs + Ollama blob store via manifests; GGUF magic sniff for extensionless blobs) + `POST /api/models/integrate` (inspect → register → route-first → serve, audited) + `POST /api/runs` (goal composer)
- [x] Models page: discovered-model rows with one-click Integrate + path field; Runs page: Run composer (same engine as the terminal)
- [x] Machine-local overlays (ADR 0012): registry.local.yaml / routing.local.yaml / integrated_engines.yaml under the data dir; supervisor auto-starts integrated engines on boot; shipped models/*.yaml stay pristine
- [x] Verified live end-to-end on this box: llama.cpp b10723 + Qwen2.5-1.5B-Instruct Q4_K_M integrated via the UI button; real-model run created reports/status.txt through sandboxed python (run a8b2e83c, done_with_gaps — content quality is 1.5B-grade, honestly scored partial by the verifier)
- [x] Three harness bugs found by the first real model and fixed with tests: exemplar parroting (relevance-picked exemplars), mock shadowing real engines (real engines win), llama.cpp grammar rejection of string maxLength (stripped for llamacpp; executor clamps instead of failing)

## Post-1.0 — Workbench console (user-driven)
- [x] Workbench page: chat-driven agent surface in the browser over the same JSON-RPC as the TUI — streaming transcript, live tool cards, plan cards, task chips, inline permission/question prompts, run stats line, Stop, any-folder workspace + ask/auto/plan
- [x] Settings page: installation facts, live engine/server log tails, every config key with its source layer (/api/config, /api/logs)
- [x] Models: in-app integration guide; Downloads-folder discovery; automatic role assignment from capabilities; auto-probe on integration
- [x] Router best-available fallback: no listed candidate up → strongest available model by probe evidence then size (tests)
- [x] Verified live: two Workbench-driven runs on the integrated 1.5B wrote real files into a user-chosen folder; transcript honestly reports gaps where the small model's content fell short
- [x] Workbench v2: session rail with one-click resume (replay + reattach to running runs), markdown rendering, ↑ history / Esc interrupt / prompt queueing, collapsible tool output with diff coloring

## Post-1.0 — Terminal-dark console, deep discovery, routing visibility (user-driven)
- [x] Console redesigned as one deliberate dark theme — warm charcoal ground, cream text, coral accent, the coding-agent look end to end: boxed ✻ welcome with cwd, coral ❯ prompt, dark session rail/tables/cards; sweep of all pages fixed a real bug (goal input typed black-on-dark; inputs don't inherit body color) and a low-contrast chart hue
- [x] Deep disk discovery (gateway/discovery.py, pure + unit-tested): Downloads, Desktop, Documents, models dirs, Ollama, LM Studio, GPT4All, HF cache, C:/D:\models — depth-4 pruned walk, GGUF magic verified, HF snapshots as folder candidates, dedup, cap 300; found 8 real items on this box in ~1s
- [x] Routing made visible: `GET /api/routing/assignments` + `Router.current_assignments()` share the exact pick logic with `route()` (parity test); Models page "Who does what right now" board shows each role's model, how it was chosen, and probe evidence
- [x] `/api/models` enriched (origin local/bundled, weights path, probes passed/total); Models page restructured: On this computer → Added models → assignments → in-app guide
- [x] Settings log tail: white-on-dark terminal viewer, warn/error colorized, stick-to-bottom — verified against the live 3.4 MB llama-server log
- [x] Two real bugs fixed with regression tests: sandbox shell picked the WSL `bash.EXE` store shim on Windows (run_tests exit 127 → locate real Git Bash); `registry.save()` rewrote the shipped registry.yaml on probe (overlay-only persistence; probed bundled models promote into the overlay, origin label preserved, shipped tree byte-stable under probe/integrate)
- [x] End to end on the real model: Workbench goal → plan → `reports/summary.txt` written with the exact requested line → honest done_with_gaps; probe evidence survives restarts via the overlay
- [x] Gates: ruff clean, mypy --strict clean, 212 unit tests, web build clean; built with two parallel agents (server feature + dark-theme sweep) per operator request
