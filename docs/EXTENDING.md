# Extending YANTRA

Every extension point is a file drop + a CLI command — no code changes for models, agents,
skills, knowledge packs, templates or MCP tools. New built-in tools and deliverable schemas
are small, typed Python additions.

## Add a model (demo scenario 6)

```bash
cp -r /path/to/Gemma-4-26B-A4B /opt/yantra/models/
yantra models add /opt/yantra/models/Gemma-4-26B-A4B --roles utility
yantra models probe gemma-4-26b-a4b       # health, JSON-mode, tool-call conformance
```

`models add` inspects the weights, writes a manifest into `models/registry.yaml`, and
**refuses ≥120B-parameter models** unless `--allow-large` (both paths audited). The router
uses probe results — a model that fails the JSON probe never gets `json`-needing calls.
To make it resident, add an `engines:` entry in `models/profiles/<profile>.yaml` (or a
compose service + `url:` attach entry in `<profile>-compose.yaml`).

## Add an agent role

Drop `agents/hse_auditor.yaml` plus its persona file `agents/prompts/hse_auditor.md`:

```yaml
name: hse_auditor
description: Permit-to-work and HSE compliance audits against site checklists.
model_role: executor          # which router role serves it
tools: [search_knowledge, get_chunk, cite, read_file, render_document, write_file]
system_prompt: prompts/hse_auditor.md
verification: {rubric: rubrics/analyst.md, threshold: 80}
decoding: {temperature: 0.2}
```

The persona states the stance (findings cite the permit line and the rule; anything touching
interlocks or relief devices is "review required", never a bypass instruction).
`yantra agents validate` checks the pair; the planner can staff it immediately
(scenario 6's permit-to-work audit).

## Add a skill

`skills/<name>/SKILL.md` with YAML frontmatter (name, description, inputs) + markdown
procedure. Skills are injected when the planner matches the goal; agents can also propose
one from a successful run (`propose_skill`), which lands in the approval queue —
operator-approved skills only.

## Add knowledge packs and rules

- Corpus: `yantra index add <dir> --collection <name>` (any mix of PDF/DOCX/XLSX/PPTX/
  images/CSV/code); re-run to pick up changed files only.
- P&ID rules: append to `knowledge/pid/rules.yaml` (predicate + severity + standard name;
  clause numbers are `TODO-by-operator`, listed by `yantra doctor`). Checklists under
  `knowledge/pid/checklists/`.
- Tag grammar: site-specific prefixes in `knowledge/pid/tag_prefixes.yaml`.
- House style for deliverables: `knowledge/house_style.yaml`.

## Add an MCP tool server

Drop `tools/mcp/<name>.json`:

```json
{"name": "lims", "command": "/opt/lims-mcp/bin/lims-mcp", "args": ["--db", "/data/lims.db"],
 "tools_allowlist": ["lims_query"]}
```

stdio transport only — manifests with `url`/`transport` keys are **rejected by design**
(the seal admits no remote tools). Tools appear in agent manifests as `mcp_<name>_<tool>`
and go through the same permission engine and audit as built-ins.

## Add a built-in tool

Subclass `Tool` in `server/yantra_server/tools/builtin/` (typed `Args` model, `side_effects`,
`run()`), register it in the module's `register_*` function, and add 2–3 few-shot lines in
`tools/fewshot/<tool>.jsonl`. Permission defaults come from `side_effects`/`risk`; tests in
`server/tests/unit/` follow the existing per-tool pattern.

## Add a deliverable schema/template

Add the Pydantic model to `server/yantra_server/render/schemas.py` (`SCHEMA_MODELS`), a
template under `templates/docx|pptx/` (or rely on the built-in house renderer), and the
schema is immediately renderable via `render_document` with full validation + provenance
sidecars.

## Add an eval suite

Drop `server/yantra_server/evals/suites/<name>.yaml` (`kind: tasks|retrieval|pid|...`),
run `yantra eval run <name>`. Task cases score against `corpus/truth.json`-style ground
truth; scripted scenario cases (mock profile) register in `evals/scenarios.py`.
