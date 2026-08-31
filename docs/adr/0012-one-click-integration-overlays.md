# 0012 — One-click model integration; machine state lives in data-dir overlays

**Decision.** `POST /api/models/integrate` (Models page: auto-discovered candidates from the
weights folder and Ollama's blob store, each with one Integrate button) performs
inspect → register → route-first → serve in one step. Everything it changes is
**machine-local state under the data dir**, never the shipped config: models append to
`registry.local.yaml` (overlays the shipped registry, local wins by id), routing goes to
`routing.local.yaml` (applied at the front of each role at startup), and the spawned engine
is recorded in `integrated_engines.yaml` (auto-started by the supervisor on boot). The
checked-in `models/*.yaml` stay pristine; `yantra models add` (operator CLI) still edits the
shipped registry per SPEC §7.4.

**Found by the first real model** (Qwen2.5-1.5B GGUF via llama-server on the dev box), three
bugs this feature's e2e run flushed out, each now fixed with a test:
1. Planner exemplars were the first two alphabetically; small models parrot them, so a
   file-write goal got a document-analysis plan. Exemplars are now picked by goal-word
   overlap (planner.py), and a trivial write-a-file exemplar ships.
2. The mock engine claims every model id, so requests for the real model were round-robined
   to the mock. Real engines now shadow the mock (supervisor.engine_for_model).
3. llama.cpp's grammar compiler rejects `maxLength` on strings in the executor's action
   schema ("repetition exceeds sane defaults") and 500s every call. String length bounds are
   stripped from schemas sent to llama.cpp; pydantic still enforces them on parse, and the
   executor clamps over-long thought/notes instead of failing the step.
