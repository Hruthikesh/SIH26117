# 0009 — Retrieval fusion weights: keep 1.0/1.0 default; boost lexical only when tags dominate

**Decision.** Default `knowledge.fusion_weights` stays `{lexical: 1.0, dense: 1.0, visual: 0.8}`.

**Numbers** (`yantra eval run retrieval` + `yantra eval tune-retrieval`, small corpus, 11
truth-set cases, mock profile, 2026-08-31): lexical-only recall@10 = **1.00** / MRR 0.78;
hybrid 0.91 / 0.59; dense-only 0.91 / 0.58. Sweeping lexical weight 0.4→1.0 never beat
lexical-only.

**Why not ship lexical-heavy weights?** The dense side of these numbers is the MockEngine's
hash pseudo-embeddings — they measure the fusion plumbing, not semantic retrieval. The truth
set is also tag-heavy (exact-tag queries), which structurally favours the tag-preserving
lexical index. Tuning real weights on fake embeddings would be overfitting to the mock.

**Standing instruction** (blocks: GPU host): on the standard profile run
`yantra eval tune-retrieval --adr` with the real embedding model and update this ADR with
those numbers; expect dense to earn its weight on paraphrase-style queries the generator
also plants.
