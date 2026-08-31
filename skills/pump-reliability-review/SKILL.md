---
name: pump-reliability-review
description: Investigate recurring pump failures from maintenance logs and produce a root-cause report
triggers: [pump, failure, seal, reliability, mtbf, maintenance, log]
tools: [analyst, data_engineer, writer]
success_count: 0
---

# Pump reliability review from maintenance logs

## Plan outline
1. Locate maintenance logs and vendor manuals for the pumps in scope (analyst).
2. Extract failure events per pump into a table with dates and causes, each cited (analyst).
3. Compute MTBF per pump and plot the trend (data_engineer).
4. Cross-check the failing pump's seal type and flush plan against the manual and SOP (analyst).
5. Write the root-cause report with citations and a work-order draft (writer).

## Pitfalls
- Do the arithmetic in code (MTBF = operating hours / failures), never in prose.
- One row per event with a citation; reason over the table, not scattered chunks.
- Distinguish correlation from cause; recommend confirmation, don't assert.
