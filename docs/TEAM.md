# Team charter — six seats, six owned systems

One member owns each vertical: they can explain every file in it, they finish its
hardware-blocked items, and they take its judge questions. Ownership means *accountable*,
not *alone* — integration pairs are listed at the end.

## 1 · Conductor & Agents (harness lead / team lead)

- **Owns:** `server/yantra_server/conductor/` (intake → planner+critic → scheduler →
  executor → verifier → escalation ladder), `server/yantra_server/memory/`, `agents/`,
  `tools/fewshot/plans/`.
- **Knows cold:** the 10-stage loop, one-tool-per-step constrained THINK, loop guard,
  progress ledger, crash-resume (write-ahead tasks + idempotent tools), delegate fan-out,
  budgets, 99.4% prefix stability, exemplar relevance selection.
- **Week 1:** run `YANTRA_TINY_MODELS_DIR=<dir> uv run pytest -m e2e
  server/tests/e2e/test_tiny_coding_goal.py`; tune planner exemplars against the real
  models; author `agents/hse_auditor.yaml` + persona (scenario 6); rehearse kill-9 →
  `yantra resume` live.
- **Judge questions:** "How does it not hallucinate?" "What happens when the model fails
  mid-task?" "Why no agent framework?" (ADR 0002).

## 2 · Models & Inference (gateway)

- **Owns:** `server/yantra_server/gateway/` (engines vLLM/llama.cpp/pooling/mock,
  supervisor spawn+attach, router + escalation rungs, structured decoding, caches,
  registry + <120B gate, probes, bench), one-click integration (ADR 0012).
- **Knows cold:** OpenAI-compat serving, grammar-constrained JSON (xgrammar/GBNF and the
  llama.cpp maxLength pitfall), routing policy + local overlays, probe-gated capabilities.
- **Week 1:** bring up the GPU host (vLLM, `python scripts/fetch_models.py --profile
  standard`); `yantra models probe` every serving model; `yantra bench llm` + `bench
  ingest` into the profile `measured:` blocks; exercise the heavy-tier escalation.
- **Judge questions:** "Which models and why under 120B?" "What hardware exactly?" "Can we
  plug in our own model?" (live: one click.)

## 3 · Knowledge & Corpus (librarian)

- **Owns:** `server/yantra_server/knowledge/` (parse→chunk→enrich→embed ingestion,
  Tantivy tag-preserving lexical, Qdrant dense/visual, weighted-RRF + rerank, citations),
  `corpus/` generators + truth sets, retrieval evals.
- **Knows cold:** hybrid fusion and why weights are eval-chosen (ADR 0009), page-level
  citation resolution, latest-revision filtering, degrade-to-lexical resilience.
- **Week 1:** real-embedding retrieval numbers (`yantra eval run retrieval`,
  `yantra eval tune-retrieval --adr`, update ADR 0009); `yantra corpus generate --size
  medium` + ingest benchmark; OCR ingestion pass over scanned PDFs.
- **Judge questions:** "Ten million documents, really?" "Why should we trust a citation?"
  "What about scanned drawings from 1988?"

## 4 · Vision & Deliverables (engineer's eye)

- **Owns:** `server/yantra_server/vision/pid/` (ISA-5.1 tag grammar, detector + truth
  sidecars, PIDGraph, YAML rule engine, overlay annotator), `server/yantra_server/render/`
  (13 schemas, DOCX/XLSX/PPTX/PDF/MD, provenance sidecars), `templates/`,
  `knowledge/pid/` rulepacks + checklists.
- **Knows cold:** tag classification precedence, rule predicates, "the model never
  formats" rendering, the engineering-review banner and domain-safety hard gate.
- **Week 1:** train the detector on GPU (`python scripts/train_pid_detector.py`) and
  measure mAP vs the synthetic truth; extend `knowledge/pid/rules.yaml` and fill
  `TODO-by-operator` clauses with the site engineer; run a real (non-synthetic) P&ID
  through the pipeline.
- **Judge questions:** "Can it actually read a P&ID?" (live: 3/3 planted deviations.)
  "Who signs off on a deliverable?"

## 5 · Seal, Sandbox & Operations (seal-keeper)

- **Owns:** `server/yantra_server/seal/` (env lock, socket guards Py+Node, verify +
  Ed25519 certificate, egress demo), sandboxes (`tools/` bwrap/docker/local), permission
  engine + audit chain, `Dockerfile`, `docker-compose.yml`, `scripts/bundle.sh`,
  `install.sh`, `seal_nftables.sh`, `docs/RUNBOOK.md`, `docs/SEAL.md`.
- **Knows cold:** the five layers and what each defeats, why mock is barred when sealed,
  hash-chain verification, compose `internal:` topology (ADR 0011).
- **Week 1 (Linux VM + connected box):** `uv run pytest -m seal
  server/tests/seal/test_sandbox_net.py` (bwrap); `bash scripts/seal_nftables.sh install`;
  `bash scripts/bundle.sh lite` then air-gapped `install.sh` rehearsal — it must end with
  a green sealed `yantra seal verify` (env_locked passing).
- **Judge questions:** "Prove zero egress." (live: `yantra seal demo`.) "What if someone
  tampers with the logs?" "How do updates reach an air-gapped plant?"

## 6 · Experience, Evals & Demo (the face)

- **Owns:** `tui/` (Ink terminal UI), `web/` console + protocol types, `server/
  yantra_server/evals/` (runner, six suites, scripted scenarios), `scripts/demo.sh`,
  `docs/PITCH.md`, `docs/EVALS.md`, the deck and the pre-recorded fallback.
- **Knows cold:** the 3-minute pitch by heart, every slash command, the Runs trace view,
  eval pass-rate history, what is measured vs mock-scripted (honesty of EVALS.md).
- **Week 1:** full `bash scripts/demo.sh` rehearsal on the GPU host with timings written
  into PITCH.md; record the scenario-2 fallback video; `yantra eval run --write-doc` on
  `standard` for real numbers; build the deck from `docs/img/` screenshots.
- **Judge questions:** drives the live demo; fields "show me…" requests; hands deep-dives
  to the owning member.

## Integration pairs (the seams that need two owners)

- **1 ↔ 2** escalation ladder × router rungs; real-model prompt tuning.
- **3 ↔ 4** visual retrieval (drawing embeddings) × P&ID pipeline.
- **2 ↔ 5** sealed GPU serving: engine env lock, compose profiles, model checksums.
- **6 ↔ all** the demo exercises every system; owners are on call during rehearsals.

## Working agreements

- The ledger (`docs/BUILD_LEDGER.md`) is the single source of "what works"; update it in
  the same commit as the change.
- Any non-obvious decision gets a one-page ADR (`docs/adr/`); numbers come from
  `yantra eval`, not opinion.
- Nothing merges red: `ruff` + `mypy --strict` + full pytest + TUI tests green.
- Conventional commits; never leave the tree non-building.
- Demo freeze 48 h before judging: only P0 fixes, everything re-verified with
  `bash scripts/demo.sh` after each.
- Every member can run the whole demo solo — cross-training in the last week.
