# D10 Phase-2 retrieval eval — 2026-07-11 (PARTIAL)

Owner protocol: docs/d10-retrieval-eval-design-2026-07-08.md (§3/§4/§6/§7 + DEC-006 amendment). Thresholds: docs/quality/d10-eval-thresholds.json (pre-registered — read, never adjusted). Fixtures: the frozen P2-1 set (SHA-pinned).

## Environment (recorded per DEC-006 A2)
- corpus: 393 tracked docs (git-tracked *.py + *.md) ⊕ digest PRESENT (10 entries: digest-2026-07-07.jsonl sha256=c5651658f919… verify_feed OK)
- Ollama: ollama version is 0.31.2 (read live); judge model: qwen3:4b (in-code default)

## Judge screening gate (§6 — run FIRST)
- status: **failed**
- self-consistency κ: 0.8661 · anchor accuracy: 0.4667 (floors: κ ≥ 0.7, acc ≥ 0.8) · model: qwen3:4b

## Results (2 configs × 4 strata + overall)

| stratum | n | config | MRR@5 | P@1 | nDCG@5 | Recall@10 | Δ MRR@5 (B−A) | p (paired t) | Cohen's dz |
|---|---|---|---|---|---|---|---|---|---|
| identifier | 20 | graph | 0.1392 | 0.0000 | 0.3922 | 0.8000 |  | |  |
| identifier | 20 | graph+bm25 | 0.2758 | 0.0500 | 0.7170 | 1.0000 | 0.1367 | 0.1069 | 0.3784 |
| semantic | — | — | INVALID — judged stratum, judge gate failed (below floor) | | | | | | |
| multi_hop | — | — | INVALID — judged stratum, judge gate failed (below floor) | | | | | | |
| negative (diagnostic) | 10 | graph | over-retrieval: mean 4.7000 docs@5, any-returned 1.0000 | | | | | | |
| negative (diagnostic) | 10 | graph+bm25 | over-retrieval: mean 5.0000 docs@5, any-returned 1.0000 | | | | | | |

**Hole@10 validity:** graph: 0.5714, graph+bm25: 0.3700 (bar ≤ 0.15) → INVALID — re-pool per §7

## Pre-registered verdicts (§7 — bars read from the thresholds file)

- **BM25 earns its place:** **UNDECIDED** — run PARTIAL — the pre-registered criterion needs a valid full run
- **Dense column:** **DEFERRED** — 0/30 real queries logged; the traffic mix is measured, not assumed (owner §5); no dense config runs until the log clears the floor and classifies ≥ the semantic share

- Pooled qrels appended this run: 0
- owner §7 (corrected): ≈97% overall at dz=0.5 (n=60 frame), but only ≈55%/≈33% per-stratum at n=20/10 — per-stratum deltas are reported, never over-claimed
