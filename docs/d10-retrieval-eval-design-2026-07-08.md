# D10 Retrieval Eval Design — verified, air-gapped, precision-first

*Authored 2026-07-08. Distilled from a Perplexity "Pass 4" whose every load-bearing citation was checked against
primary source (proposer≠verifier). This is the eval that GATES whether D10's hybrid retriever — and its optional
dense lane — earn their place, before a line of it is built (measure-first). Companion to
`docs/remaining-work-plan-2026-07-08.md` (Workstream B / Phase 3 = v4 D10) and
`docs/agent-brain-selfmem-upgrade-plan-2026-07-08.md` §Phase 3. Design/plan only — no retriever built here.*

---

## 0. Verdict

Build the **eval first**. The design below answers our two open D10 questions with committed, falsifiable
thresholds: (a) does hybrid **graph⊕BM25** beat graph-only, and (b) does the **dense/vector lane** earn its
embedding-model dependency (which cuts against the zero-embedding preference)? Do **not** build the retriever
until this eval is stood up. It is prep, not a build — and it is **not the critical path** (that stays the live
cutover); D10 itself remains gated on the Ollama install + a first sanitized vault digest (ADR-0001 Am.1).

## 1. Citation verification (what survived)

| Source | Load-bearing claim | Verdict |
|---|---|---|
| Cormack/Clarke/Büttcher, **SIGIR 2009** | RRF, k=60 near-optimal + insensitive | ✅ foundational, real |
| Thakur et al., **BEIR, NeurIPS 2021** | dense frequently fails to beat BM25 zero-shot | ✅ real |
| GPL (Wang et al.) + **InPars-v2** (2301.01820) | query-inversion pseudo-labels | ✅ real |
| Yuksel/Rau/Kamps, **R-GPL** `2501.14434` | hard-neg remine boosts 13/14 BEIR, 9/12 LoTTE | ✅ verified (fetched) |
| Trappolini et al., **UDCG**, EACL 2026 `2026.eacl-long.391` | +36% correlation w/ RAG accuracy vs nDCG | ✅ verified (fetched) |
| Fröbe et al., **SIGIR 2025** (webis) | LLM assessors agree w/ each other > humans; **system-level τ reliable** | ✅ paper + direction verified; **exact κ/τ/% not independently confirmed** (PDF object-embedded) — treat as reported |
| Fiedler, `2605.06939` | naive judge estimator biased; **sign-reversal** at low J/ΔJ | ✅ verified (fetched) |
| van Gysel/de Rijke, **pytrec_eval** `1805.01597` | Python binding to reference `trec_eval` | ✅ real |
| Acceleratech blog (`[^18]`) | BM25 +0.25 Recall@5 on identifier queries | ⚠️ **vendor blog, not primary** — *direction* backed by BEIR; specific numbers = illustrative |
| `[^16]` dev.to agent-memory · `[^17]` IETF audit-trail | (mis-cited for "RRF k=60 sensitivity") | ❌ **DROPPED** — unrelated; leaked from the earlier Brain research |

The source doc's Python is footnote-corrupted (`shape[^1]`, `x[^1]`) — **reference only, re-implement clean**.

## 2. The eval set — 60 queries + 15 anchors

| Category | Count | Label source | Tests |
|---|---|---|---|
| Identifier / exact-match | 20 | **AST symbol extraction — no LLM, 100% correct by construction** | BM25 IDF, graph traversal |
| Conceptual / semantic | 20 | local-LLM query inversion, **synonym-stripped** (reject any query reusing a node token) | dense lane |
| Multi-hop | 10 | manual/LLM, require ≥2 graph edges | graph-edge logic |
| Negative / unanswerable | 10 | manual (~10 min) | over-retrieval / precision |
| **Anchor calibration set** | 15 (separate) | manual (5 clear-rel / 5 clear-irrel / 5 borderline) | judge calibration, run first every session |

**Our fit:** graphify's AST graph makes the 20 identifier labels **free and exactly correct** — extract the
top-in-degree symbols, query "what does `<symbol>` do?", mark the node grade-3 and near-neighbours grade-1. Hard
negatives come free from this + from mining the current retriever's top-10 that the judge scores 0.

## 3. Metrics — precision-first

- **Primary: MRR@5 + Precision@1.** P@1 directly operationalises "a wrong entry is worse than nothing." Lock
  cutoffs at k ≤ 10.
- **Secondary: nDCG@5, Recall@10** (regression detectors).
- **Diagnostic (report every run): `Hole@k`** (fraction of top-k unseen by annotators — pool-bias), judge κ,
  anchor accuracy.
- **NOT Recall@k as primary** — high recall at large k is irrelevant when a rank-1 error is the failure mode.
- **UDCG** (Trappolini) is a genuine RAG-aware upgrade but needs logprobs from the *consuming* LLM — defer to a
  Phase-2+ nicety, not core.

## 4. Tuning — freeze, don't grid-search

Lock **RRF k=60** (Cormack — near-optimal, insensitive). BM25 priors for a code+docs corpus: **k1=0.9, b=0.4**
(Pyserini/InPars defaults; identifiers have near-zero within-doc repetition, so low k1 is right). **Do NOT
grid-search on 60 queries** — ~4–5 degrees of freedom; any 0.01 nDCG delta is noise. Revisit only at 500+
labelled queries.

## 5. Does the dense lane earn its dependency? (the D10 decision)

**Classify 30 real queries by type FIRST.** Evidence (BEIR + corroborating production write-ups) is consistent:
BM25 wins identifier / exact-match / code (controlled vocabulary; embedding models assign weak high-variance
vectors to rare identifiers), dense wins genuinely *conceptual* cross-file queries. So:

- **If conceptual/semantic < 30% of the real query mix → graph+BM25 is sufficient**; skip the dense lane and its
  embedding dependency (honours the zero-embedding preference).
- **If ≥ 30% → add dense at a low RRF weight**, and only if the eval below confirms it (§7).

This is the coverage-honest answer to "should D10 have a vector lane": **measure the query mix, don't assume.**

## 6. Judge honesty — maps onto instruments we already have

- **Different-family local judge = `ollama_judge`** (already built, air-gapped, cross-family — proposer≠verifier).
- **Graded 0–3 rubric + chain-of-thought before the grade** (curbs the LLM optimism Fröbe documents).
- **Dual-prompt, take-the-MIN:** one adversarial ("find why it does NOT answer") + one neutral framing — the
  conservative ensemble against rubber-stamping (the same framing-sensitivity we measured in `ollama_judge`).
- **Pre-run gate:** run the 15 anchors first; require self-consistency **κ ≥ 0.70** and **anchor accuracy ≥ 0.80**
  — *do not run the eval if the judge fails the gate.* (A new judge-trust instrument, sibling to `defect_panel`.)
- **Reliable use:** individual grades are noisy, but **system-level A-vs-B comparisons are reliable** (Fröbe) —
  which is exactly our use (graph-only vs +BM25 vs +dense). Report Fiedler's **J / ΔJ** caution when the judge is
  weak (our cross-family judge is TNR≈0.2 — so lean on the anchor set + significance test, not raw grades).

## 7. Falsification criteria — commit BEFORE running (coverage-honest)

Write these thresholds to a file first; do not adjust after seeing results. Require **p < 0.05 (paired t-test)
∧ Cohen's d > 0.4** before calling any delta real. Power honesty (corrected 2026-07-10 — the earlier
"~40–50%" figure here was the UNPAIRED two-sample result): for this doc's own pre-registered PAIRED
test, power at dz=0.5 is **≈97% overall** (n=60 pairs; ≈78% even at zero pairing correlation) but only
**≈55% / ≈33% per-stratum** at n=20 / n=10 — the caution belongs to the per-stratum decisions
(the semantic-stratum dense criterion above all), not the overall test.

- **BM25 earns its place:** `MRR@5(graph+BM25) > MRR@5(graph) + 0.05`, significant. FALSIFIED otherwise.
- **Dense earns its dependency:** `MRR@5(+dense, semantic) > MRR@5(BM25, semantic) + 0.05` AND
  `Hole@10` not inflated. **Dense anti-pattern (auto-reject):** `MRR@5(+dense, identifier) < MRR@5(BM25,
  identifier)` — it's hurting the majority category.
- **Eval trustworthy:** judge gate pass (κ≥0.70, anchor acc≥0.80) AND `Hole@10 ≤ 0.15`; else INVALID, re-pool.

## 8. Offline stack (all air-gap-safe)

`rank-bm25` / `bm25s`; `sentence-transformers` + `faiss-cpu` (CPU, `IndexFlatIP` exact — fine at this
graph's ~7.0k nodes; count owner: `graphify-out/GRAPH_REPORT.md` header);
`pytrec_eval` (the reference `trec_eval` binding, offline); `scipy`/`scikit-learn` for the paired t-test + κ.
Everything runs with no egress. Re-implement the source doc's snippets clean (its `[^N]` markers are corruption).

## 9. Where this sits

**Prep, gated, off the critical path.** D10 remains gated on Ollama + a first sanitized digest; this eval is what
gets stood up *when* D10 is built, and it is the thing that decides whether the dense lane ships at all. The one
autonomous slice available now with zero new dependencies: the **20 AST-identifier queries + the graph-only
baseline** (no LLM, no embeddings) — a real first data point whenever we choose to spend it. Not pulled forward.
