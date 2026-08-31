---
name: psv-adequacy-review
description: Review PSV/relief adequacy on a P&ID against the plant rules
triggers: [psv, relief, valve, p&id, pressure, vessel, adequacy]
tools: [drawing_engineer, writer]
success_count: 0
---

# PSV adequacy review from a P&ID

## Plan outline
1. Run pid_analyze on the sheet; get the equipment/instrument lists and graph.
2. Run pid_rules_check with the PSV rules (psv_on_vessel, psv_isolation_car_seal).
3. Confirm each finding against the vessel datasheet where available.
4. Produce a pid_review report with the annotated overlay and findings.

## Pitfalls
- Trust the graph for topology; use zoom/crop only to resolve specific doubts.
- Phrase findings as "review required", never as instructions to change the plant.
- Cite drawing regions (page + bbox) and rule ids for every finding.
