---
name: modernise-legacy-script
description: Convert a legacy script into a tested, typed module with a CLI
triggers: [legacy, script, convert, modernise, refactor, tested, module]
tools: [coder]
success_count: 0
---

# Modernise a legacy script

## Plan outline
1. Read the script fully; identify behaviour, inputs, outputs and any bugs.
2. Write tests that encode the expected behaviour (including the bug's correct form).
3. Refactor to a typed module with a CLI; make the smallest change that passes.
4. Run tests + lint; produce a code_change_summary.

## Pitfalls
- Read before writing; never edit a file unread this task.
- Fix the bug, not the test. No new dependencies (the sandbox has no network).
