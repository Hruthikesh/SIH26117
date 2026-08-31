# 0001 — Serving engines: vLLM (GPU) + llama.cpp (CPU/GGUF) + in-process pooling worker

**Status:** accepted (M0).

**Context.** We need OpenAI-compatible loopback serving for chat (streaming, tools, images,
structured outputs), embeddings and reranking, on hardware from one 24 GB consumer GPU to
8×H100, fully offline.

**Decision.** vLLM for all GPU serving (structured outputs via xgrammar, prefix caching,
speculative decoding, multimodal); llama.cpp `llama-server` for CPU/Metal/GGUF (`lite` utility
models, dev machines, tests); a `sentence-transformers` in-process worker as the embedding/
rerank fallback when neither engine serves the pooling model; a deterministic `MockEngine`
for tests. All behind one `Engine` interface so the gateway is engine-agnostic.

**Consequences.** Two external engine processes to supervise (health, restart, VRAM budgets)
— owned by `gateway/supervisor.py`. Exact request-field forms for structured outputs are
confirmed against the pinned engine versions in `gateway/structured.py` unit tests.
