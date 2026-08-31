# 0003 — Search stack: Tantivy (lexical) + Qdrant (dense/visual), two tiers

**Status:** accepted (M0).

**Context.** Corpus target is 10⁷ documents / 4·10⁸ chunks; queries mix semantics with exact
tokens (`P-101A`, `ASTM A106`) that dense vectors miss; everything must run offline.

**Decision.** Tantivy (via tantivy-py) for BM25 with a tag-preserving tokenizer; Qdrant for
dense vectors with scalar/binary quantization; a 256-d document tier (10⁷ vectors, RAM-cheap)
that pre-filters the 1024-d chunk tier; a 512-d visual page tier for drawings. Weighted RRF
fusion + cross-encoder rerank. Qdrant runs embedded (local mode) on `lite`/dev and as a
server/cluster on `standard`/`refinery`.

**Consequences.** Storage arithmetic in SPEC §10.2 holds on commodity NVMe; the fusion
weights and rerank depth are tuned by the retrieval eval suite, not by hand.
