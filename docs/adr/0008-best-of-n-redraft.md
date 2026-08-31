# 0008 — Best-of-N escalation re-drafts the finish over frozen artifacts

**Status:** accepted (M3).

**Context.** SPEC §8.6 rung 2: "best-of-N with the reviewer selecting". Re-running a whole
tool-using task N times would execute side-effecting tools N times against the same
workspace: later attempts overwrite earlier ones, and the reviewer's chosen finish could
describe artifacts a different attempt last wrote — an unsound mix.

**Decision.** Rung 2 samples N re-drafts of the *finish* (summary, claims, self-check) at
temperature 0.7 over the failed attempt's artifacts, which are frozen; the reviewer scores
the candidates and the best is re-verified. Artifact-level defects escalate past this rung
to the heavy-model full re-attempt (rung 3) and replan (rung 4), which do re-execute.

**Consequences.** Best-of-N is cheap (no tool calls) and safe; it repairs weak summaries,
missing citations and mis-framed findings — its primary value on prose/analysis tasks —
while structural failures ride the later rungs.
