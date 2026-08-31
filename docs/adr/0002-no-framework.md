# 0002 — No agent/RAG frameworks; the harness is written directly

**Status:** accepted (M0).

**Context.** The product's value is a strict, observable harness; several popular frameworks
hide control flow and/or phone home by default.

**Decision.** No LangChain, LlamaIndex, CrewAI, AutoGen, Haystack, Ollama, or Ultralytics.
Reasons: hidden control flow defeats the observability requirement; LangSmith/PostHog/Sentry
style telemetry defaults violate the seal; Ollama pulls models from the internet; Ultralytics
is AGPL with telemetry. We use `transformers`, `sentence-transformers`, `vllm`,
`qdrant-client`, `tantivy`, `docling`, `pymupdf`, `opencv-python-headless`, `networkx`,
`shapely`, `rfdetr` directly.

**Consequences.** More first-party code (executor loop, retrieval pipeline, tool runtime),
each piece typed, tested, and emitting spans — which is exactly the point.
