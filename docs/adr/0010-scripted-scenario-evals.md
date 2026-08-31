# 0010 — Demo scenarios eval as scripted mock reasoning over real tools

**Decision.** Scenarios 2–5 run as eval cases where the MockEngine replays scripted
plans/steps (`evals/scenarios.py`) while every tool call is real — corpus search, sandbox
execution, chart/DOCX/XLSX rendering, P&ID pipeline, delegate fan-out. On a GPU host the
same cases run unscripted from the goal text.

**Why.** This box has no GPU (ADR 0005); a canned-everything eval would prove nothing, and
skipping the scenarios would leave the pipeline unproven. Scripting only the model isolates
exactly the one component we cannot run, and the file-existence/deviation-recall checks stay
honest.

**Consequence.** The exact-match response cache desyncs stateful mock scripts (a cache hit
skips the engine), so the mock profile sets `gateway.cache_ttl_s: 0` and the gateway treats
`cache_ttl_s <= 0` as cache-off. Found when scenario tasks silently replayed another task's
cached step.
