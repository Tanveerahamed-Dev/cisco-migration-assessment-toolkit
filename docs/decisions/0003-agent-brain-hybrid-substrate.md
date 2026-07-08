# 0003 — Agent-brain substrate: hybrid markdown+SQLite, and the honest delta over what's built

**Date:** 2026-07-08 · **Status:** accepted · **related:**
`cisco_toolkit/learnings.py`, `cisco_toolkit/scorecard.py`, `cisco_toolkit/calibration.py`,
`cisco_toolkit/defect_panel.py`, `cisco_toolkit/memory_guard.py`, `cisco_toolkit/ssot.py`, `ollama_judge.py`,
`docs/quality/README.md`, `docs/autonomous-brain-plan-v4-final-2026-07-06.md` (D10/D11/D12),
`docs/best-possible-plan-2026-07-08.md`, `docs/agent-brain-selfmem-upgrade-plan-2026-07-08.md`,
arXiv 2607.03726 (SelfMem), 2602.06948 (agentic overconfidence), 2601.15778 (HTC calibration)

## Context

A "Perplexity Brain vs us" benchmark (session 2026-07-08) turned into a 3-pass Perplexity research thread that
produced a detailed engineering spec — *"Agent Brain: True Ceiling Design"* (SelfMem work-memory, an adversarial
verifier + red-team panel, a production SQLite schema with trigger-enforced invariants, RRF hybrid retrieval,
per-dimension ECE calibration). Its three load-bearing citations were **independently verified as real papers**
(arXiv `2607.03726` "SelfMem: Self-Optimizing Memory for AI Agents", 4 Jul 2026; `2602.06948` "Agentic
Uncertainty Reveals Agentic Overconfidence", 6 Feb 2026 — *agents that succeed 22% predict 77%*; `2601.15778`
"Agentic Confidence Calibration / HTC", 22 Jan 2026). It is a grounded document, not a confabulation.

**But on review against the code, ~80% of it re-derives instruments this repo already ships** — the identical
failure mode `docs/best-possible-plan-2026-07-08.md` §1 documented for the two Fable plans: *a planner blind to
the code recommends building the trust instrument you have already built.* The proposed "independent verifier" is
`ollama_judge.py`; the "10 red-team cases" are `defect_panel.py` `D-01…D-12`; the "per-dimension calibration
loop" is `calibration.py` (D11-gated, propose-only); "verified_by/approved_by" is `scorecard.py` `judge_tnr` +
PROVISIONAL semantics; "safety_tier + dual approval" is `memory_guard.py` (D12); "RRF graph+vector retrieval" is
D10 of the v4 brain plan, already planned and Ollama-gated. The Perplexity Python is also **not runnable as
pasted** (markdown footnote refs `[^1]` bled into the code).

The user's substrate choice (from this session): **hybrid** — markdown stays the human-readable source of truth;
SQLite becomes an enforcement + query index. This ADR records that choice and, more importantly, the honest
sequencing that keeps it from violating the repo's data-first thesis.

## Decision

1. **Memory substrate = HYBRID, with markdown as owner.** The markdown + append-only JSONL stores
   (`memory/*.md`, `docs/quality/learnings.md`, `scorecard.jsonl`, `pir_outcomes.jsonl`) remain the
   **git-diffable, human-readable, vault-compatible SOURCE OF TRUTH.** A SQLite layer is adopted **only as a
   derived enforcement + query index — rebuildable from the markdown/JSONL, never authoritative.** On any
   disagreement, markdown wins and SQLite is rebuilt. (This mirrors ADR-0001's "one owner per fact" and keeps
   the vault-bridge and no-egress invariants unchanged.)

2. **Sequencing = gated behind the data-first frontier.** The SQLite index and any per-dimension calibration
   extension are **deferred** behind the frontier `docs/best-possible-plan-2026-07-08.md` §2 already set — REAL
   calibration row #1 (perishable), the recorded baseline TNR, corpus → N≥20. **We do not pull brain-substrate
   build ahead of the perishable measurement work.** Rationale: don't re-build instruments that exist; the next
   unit of insight is a *measurement, not a token*.

3. **Adopt now — cheap, doctrine-aligned, not a new instrument:**
   (a) the three verified papers as **citations** grounding existing rationale (`docs/quality/README.md`,
   `calibration.py`, `learnings.py`) — the overconfidence result (22%→77%) is direct evidence for why
   `judge_tnr` and proposer≠verifier exist;
   (b) the **SelfMem write-operator vocabulary** (`ADD`/`REPLACE`/`MERGE`/`REFINE`/`ARCHIVE`/`RECORD_EXACT`) as a
   *discipline refinement* to the learnings/memory update rules — formalizing the "replace stale, don't
   accumulate" guidance that today lives only as prose.

4. **No change to D10 (RRF retrieval).** Perplexity Part 4 is D10 of the v4 plan — already gated on the Ollama
   install + a first sanitized vault digest. It ships as an experiment with its own eval, not as adopted SOTA.

## Consequences

- The SQLite index, **when built**, is registered in `docs/ssot.md` as a *gated, derived* store (like the
  vault-digest) with the markdown store named as owner — not before.
- The verifier / red-team / calibration proposals require **no new build**; their delta is *measurement* (feed
  `judge_tnr` from `defect_panel`, feed REAL rows into `pir_outcomes.jsonl`), which is already the frontier.
- SelfMem's finding — *a well-constructed small corpus beats a large one; the peak is at intermediate
  refinement* — independently validates the D11 N-floor (`calibration.DEFAULT_N_FLOOR = 5`, descriptive-only
  below it). It is corroboration to cite, not a reason to change the gate.
- The Perplexity spec is retained as a **design reference** (`docs/agent-brain-selfmem-upgrade-plan-2026-07-08.md`
  carries the full mapping + phases), never a drop-in — its Python is footnote-corrupted (`r[^1]`) and its
  "strategy-refinement prompt" is a network-domain *adaptation* of SelfMem's Appendix C "Prompt 1", not verbatim.
  Its **benchmark figures were verified** against the paper HTML (2026-07-08 — all confirmed, incl. affiliations
  KAUST/Univ. Macau); they may be quoted **with citation to arXiv 2607.03726**.
- This is a plan-only decision. No engine code changed by recording it; guardrails intact (read-only, no-egress).
