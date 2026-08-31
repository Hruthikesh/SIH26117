---
name: datasheet-crosscheck
description: Cross-check equipment against its datasheet and flag deviations
triggers: [datasheet, cross-check, equipment, specification, deviation]
tools: [analyst, writer]
success_count: 0
---

# datasheet crosscheck

## Plan outline
1. Gather the source material (drawing / MoC package / datasheet / incident report + evidence).
2. Extract the structured facts with citations before reasoning.
3. Apply the relevant checklist (knowledge/pid/checklists) or rules.
4. Produce the deliverable with numbered, cited findings and recommendations.

## Pitfalls
- Every claim cites its source; safety items are "review required".
- Reason over an extracted table/graph, not raw chunks.
