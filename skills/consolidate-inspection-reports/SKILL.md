---
name: consolidate-inspection-reports
description: Consolidate inspection reports into a register and flag overdue items
triggers: [inspection, report, register, consolidate, overdue, thickness]
tools: [analyst, data_engineer, writer]
success_count: 0
---

# Consolidate inspection reports into a register

## Plan outline
1. Discover all inspection reports in scope (analyst; delegate per-report extraction for many).
2. Extract one row per report: equipment, date, finding, thickness, next-due (cited).
3. Flag overdue items by date arithmetic in code (data_engineer).
4. Produce the register (XLSX) and draft follow-up emails for overdue items (writer).

## Pitfalls
- Compute "overdue" from the data's dates, not a remembered "today".
- Fan out with delegate when there are many reports; merge in a final step.
