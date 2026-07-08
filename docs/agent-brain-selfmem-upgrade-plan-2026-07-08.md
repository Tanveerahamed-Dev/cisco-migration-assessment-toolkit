# Agent-brain SelfMem upgrade — phased plan (ground-truthed against the code)

*Authored 2026-07-08. Companion to `docs/decisions/0003-agent-brain-hybrid-substrate.md`. Takes the Perplexity
"Agent Brain: True Ceiling Design" spec (a 3-pass research thread, produced blind to this repo) and maps every
proposal onto the shipped code, so the genuinely-new work is separated from the ~80% that re-derives instruments
already built. Plan-only — no engine code changed by authoring it. Guardrails intact: read-only, no-egress.*

---

## 0. Verdict in one line

The Perplexity spec is **research-grounded and worth keeping as a design reference** (its three citations verify
as real papers), but it is **build-what-exists** — the same trap `best-possible-plan-2026-07-08.md` caught the
Fable plans in. The genuine delta is small: **the SelfMem write-operator vocabulary**, **three citations**, and a
**deferred hybrid SQLite index**. The frontier is unchanged — **MEASURE / FEED, not BUILD.**

## 1. The mapping — Perplexity's spec vs the shipped instruments

| Perplexity "True Ceiling" component | Shipped equivalent | Status | New?  |
|---|---|---|---|
| Independent adversarial verifier (Part 3) | `ollama_judge.py` (cross-family, air-gapped, running) | Built | No |
| 10 red-team test cases (Part 3.2) | `defect_panel.py` `D-01…D-12` (12 seeded defects) | Built | No |
| Per-dimension calibration / ECE (Part 5) | `calibration.py` (readiness→outcome, D11-gated, propose-only) | Built | Refinement only |
| `verified_by`/`approved_by` gating (Part 2) | `scorecard.py` `judge_tnr` + PROVISIONAL semantics | Built | No |
| `safety_tier` + dual-approval (Part 2) | `memory_guard.py` + `memory/protected-constraints.md` (D12) | Built | No |
| Coverage-honesty trigger ("healthy needs tools_run") | Doctrine L3 + `learnings.py`/`scorecard.py` conservatism | Built (prose+tests) | Enforcement upgrade |
| Provenance / cite-the-source (Part 2) | `ssot.py` + `docs/ssot.md` (SSOT Law 1) | Built | No |
| Graph retrieval lane (Part 4) | graphify (AST graph, ~5k nodes) | Built | No |
| RRF hybrid retrieval (Part 4) | **D10** v4 plan — RRF over graph⊕docs⊕vault-digest | Planned, Ollama-gated | No |
| SelfMem work-memory + write operators (Part 1) | — (`learnings.py` lints; no update-operator vocabulary) | **Absent** | **Yes** |
| SQLite substrate w/ trigger enforcement (Part 2) | markdown + JSONL + `memory_guard` tests | Different substrate | **Yes (gated)** |

**Two rows are the whole delta:** the SelfMem operator vocabulary, and the SQLite enforcement/query index.
Everything else is built, planned, or a measurement task already on the frontier.

## 2. The genuine delta (what survives ground-truth)

1. **SelfMem write-operator vocabulary** — `learnings.py` today is a *linter* (lean / cited / no-coasting); it
   governs what a learning may *say*, not how it *updates* the store. SelfMem's best-discovered strategy
   "favored compact canonical memory objects over accumulated lists … preferentially replaced or merged rather
   than appended." Porting the operator set formalizes the update semantics that currently live only as memory
   system-prompt prose ("update the existing file rather than duplicate; delete memories that turn out wrong"):

   | Condition | Operator | Why |
   |---|---|---|
   | Device/role fact changed | `REPLACE` | Accumulating stale roles misleads recall |
   | Two partial fragments of one fact | `MERGE` | Split entries cause conflicting retrieval |
   | Exact value (VLAN/IP/version/AS/ACL-line/timestamp) | `RECORD_EXACT` → transcript, cite owner | Precision facts belong in the SSOT owner, retrieved at answer time — never summarized into a learning |
   | Ticket/engagement closed | `ARCHIVE` | Active-store pollution degrades the SessionStart signal |
   | Known-failure pattern gains a sub-case | `REFINE` | Extends, doesn't overwrite, the original |
   | Genuinely new recurring entity | `ADD` | The only case where append is correct |

2. **Three citations** (near-zero cost, real grounding):
   - `2602.06948` (22%→77% overconfidence) → cite in `docs/quality/README.md` as the empirical basis for
     `judge_tnr` + proposer≠verifier (an agent's self-scored confidence is not trustworthy).
   - `2601.15778` (HTC) → cite in `calibration.py` as prior art for trajectory-level calibration.
   - `2607.03726` (SelfMem: small well-constructed corpus > big; peak at *intermediate* refinement) → cite at
     the D11 N-floor as independent corroboration of "don't re-tune on a handful of engagements."

3. **Hybrid SQLite enforcement/query index** (ADR-0003 decision) — a *derived* index over the markdown/JSONL,
   giving DB-layer triggers that catch raw-SQL/bypass paths the Pydantic/test layer can miss, plus queryable
   history. **Genuinely new, and correctly deferred** (Phase 2) — it is hardening, not a missing capability.

## 3. The phased plan (data-first gated)

**Phase 0 — cheap now, no new instrument (this can land immediately):**
- Land the three citations into `README`/`calibration`/`learnings` rationale.
- Add the SelfMem operator vocabulary to the learnings/memory update discipline (doc + a `learnings.py` lint
  that flags an append where a `REPLACE`/`MERGE` of an existing entry was warranted). Small, testable, offline.
- This mapping doc + ADR-0003 as the durable record.

**Phase 1 — the actual frontier (already owned by `best-possible-plan-2026-07-08.md`, not new work here):**
- REAL calibration row #1 via the `precert` pre-window freeze (perishable, before the maintenance window).
- Record the baseline TNR from `defect_panel` onto the scorecard (`judge_tnr`).
- Feed the corpus toward N≥20 descriptive rows. **The brain-substrate work waits behind this.**

**Phase 2 — hybrid SQLite index (GATED: only once memory volume + real rows justify it):**
- Build SQLite as a *derived* index: `build_index()` reads the markdown/JSONL and populates tables; triggers
  enforce append-only + coverage-honesty + `verified_by`/`approved_by` + safety-tier dual-approval **at the DB
  layer**. Markdown remains owner; index is `rm`-able and rebuilt. Register in `docs/ssot.md` as gated/derived.
- Adapt (do **not** paste) the Perplexity DDL — its triggers are sound; its Python is footnote-corrupted.

**Phase 3 — retrieval (already D10, unchanged):**
- No new decision. RRF over graph⊕docs⊕(vault-digest) ships behind the Ollama gate with its own eval. Skip the
  Perplexity vector lane unless a retrieval eval shows graphify+BM25 is insufficient (it adds an embedding-model
  dependency that cuts against SelfMem's own "zero embedding requests" win).

## 4. Do-not / caveats (the counterexamples)

- **Do not** pull Phase 2/3 ahead of Phase 1. The perishable, unsubstitutable action is REAL row #1, not a schema.
- **Do not** paste the Perplexity code — `r[^1]`/`vecs.shape[^1]` are corrupted; the verifier JSON is truncated
  (`"blocking_findings": unt of …`).
- SelfMem's figures **are now verified** (100K/1M BEAM table, the 0.165/0.141/0.134 margins, the 0.472→0.510
  refinement curve, affiliations — all confirmed vs the paper HTML, 2026-07-08). Quote them **only with the
  arXiv 2607.03726 citation**. But the doc's "Appendix C prompt" is a network-domain *adaptation* of the paper's
  "Prompt 1: Memory-construction instruction" — use it as a template, do **not** attribute it verbatim.
- **Do not** treat this as adopting Perplexity Brain — Brain itself is cloud-only, non-adoptable (ADR/benchmark
  session 2026-07-08). This plan ports *research patterns*, not a product.

## 5. Verification basis

Real-paper checks via `arxiv.org/abs/{2607.03726, 2602.06948, 2601.15778}` (title/date/topic confirmed);
SelfMem figures + affiliations + Appendix B/C existence confirmed against `arxiv.org/html/2607.03726v1`
(2026-07-08). Code-state checks: `learnings.py`, `scorecard.py`,
`calibration.py` (read this session) and the file:line inventory in `best-possible-plan-2026-07-08.md` §1
(`defect_panel.py` `D-01…D-12`, `ollama_judge.py`, `precert.py`, `pir_outcomes.jsonl`). v4 D-decisions from
`docs/autonomous-brain-plan-v4-final-2026-07-06.md`. Air-gapped session — no engine code changed.
