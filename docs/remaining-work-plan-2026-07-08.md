# The Remaining-Work Plan — everything left after Act 0, sequenced and gated

*Authored 2026-07-08. Successor to `docs/best-possible-plan-2026-07-08.md` — that plan's Act 0 (the four §2
items) is now DONE, so this plan covers **everything still remaining** across all three workstreams
(validation/quality, agent-brain, autonomy) plus the strategic frame, with the real gating decisions made.
Plan-only — no engine code changed by authoring it. Guardrails intact: read-only, no-egress, no device writes.*

---

## 0. Verdict in one line

The critical path is **one perishable operational event** — a real cutover → **REAL calibration row #1** — and
it unlocks nearly everything downstream. The machinery is built and proven; the gap is *real signal*, not more
code. Best decision: **hold the discipline** (don't pull later Acts forward, don't arm autonomy on a weak judge,
never fabricate an outcome), land the two cheap grounding wins, and make the live cutover the priority.

## 1. Where Act 0 left us (the baseline this plan builds on)

Five commits on `chore/scorecard-first-real-rows`, all pushed: `c5c1f1d` (ADR 0003 + SelfMem plan),
`b2b2951` (best-possible-plan), `748fba3` (baseline judge-TNR), `bad152d` (phantom-health audit), `313b4a5`
(precert readiness-freeze). Measured, load-bearing state:

- **Judge TNR recorded:** deterministic arm **1.0** (12/12, the load-bearing instrument) · cross-family LLM
  (qwen3:4b) **0.2** (weak — a supplement). Every LLM `APPROVE` is PROVISIONAL by construction.
- **Calibration: 0 REAL** (7 fault-injected surrogates; D11 tuning floor legitimately unmet — pre-cutover).
- **Freeze mechanism built:** `precert.compute_readiness_freeze` (schema `precert-readiness/1`), shadow-validated
  → [HISTORY-REDACTED] fleet predicts NOT READY, coverage-honest, `prediction_hash sha256:ea6f2048…`.
- **Deliverables phantom-health-clean** (text + binary), fleet 303/253/50 scoped honestly throughout.

## 2. The full remaining map (three workstreams + strategy)

| Thread | Gate / dependency | Owner | Best-decision disposition |
|---|---|---|---|
| **A. Validation & quality** — *primary axis (~60%)* | | | |
| Act 1 — REAL calibration row #1 (`--mode real` freeze → commit → post-cutover actual) | a real cutover window | **you (live)** | **the unlock** — do the moment a window exists |
| Act 2 — feed corpus to N≥20 *descriptive* (Batfish/Kathará/compare-pairs) | none (surrogate) | mine | **available, DON'T pull forward** — can't tune (D11); low marginal value |
| Act 3 — blind, source-masked head-to-head harness | after Act 1's discipline | mine | build after real signal exists; the credibility proof |
| Act 4 — freeze the 278-item breadth register + recall/RRF behind a flag | none | mine | **later**; relabel self-scored matrix ●→measured/unverified |
| Act 5 — clock arm-or-not decision | REAL calibration **separation** | gated | far off — see §3; shadow-first, ROI-killed |
| **B. Agent-brain** — *ADR 0003 / SelfMem plan* | | | |
| Phase 0a — 2 remaining citations (`2607.03726` at the N-floor; `2601.15778` in `calibration.py`) | none | mine | **DO now** — cheap grounding |
| Phase 0b — SelfMem write-operator lint in `learnings.py` | memory store grows | mine | **DEFER** (store ~13 entries; not yet needed) |
| Phase 2 — hybrid SQLite enforcement/query index | memory volume + real-row need | gated | **don't build speculatively** — hardening, not a gap |
| Phase 3 — RRF retrieval (= v4 **D10**) | Ollama install + first sanitized vault digest | gated | **eval now specified + citation-verified** (`docs/d10-retrieval-eval-design-2026-07-08.md`); ships with that eval, not as SOTA |
| **C. Autonomy nerves** — *v4 final* | | | |
| Clock (D13) — scheduler + `claude -p` nightly | TNR-gate ∧ calibration separation ∧ ROI | gated | rails built (`clock.py`); **do not arm** (see §3) |
| Remediation / self-healing (`/remediate`) | a baseline⋈current drift to act on | mine | propose-only; exercise when drift is real |
| Recall / vault-digest (D10) | Ollama + a signed sanitized digest | gated | degrade-gracefully; not installed |
| **Strategy** — *best-possible-plan §4* | | | |
| Keep axis allocation (validation 60 / career 25 / autonomy 10 / commercial 5) | — | you | keep; autonomy/commercial are downstream of proof |
| Publish the negative result (open the TNR + coverage-honesty harness) | after Act 3 | you | the durable moat incumbents can't copy |

## 3. The critical path (what gates what)

```
        [Act 1: real cutover -> REAL row #1]   <-- the single unlock (perishable, yours)
                     |
        REAL rows accumulate (N grows)
                     |
        calibration SEPARATION emerges  ------> [Act 2 tuning unlocks]  (D11: REAL-only)
                     |                    \
                     |                     ---> [Act 5: clock arm-decision]
                     v
   NB: deterministic TNR 1.0 already clears the 0.75 gate — so the missing gate
   EVERYWHERE downstream is REAL calibration data, not the judge. Act 1 is the lever.

Parallel, NOT gated on Act 1 (can run anytime):
   - Phase 0a citations (10 min)           <- do now
   - Act 3 harness build / Act 4 breadth freeze  <- later, but not blocked
```

The single insight: **almost everything of value is gated on Act 1**, and Act 1 is an operational event no code
can manufacture. So the honest plan is *narrow now, wide after the cutover*.

## 4. Decisions (the best-possible calls, with rationale)

1. **Phase 0a citations — DO now.** Verified, apt, ~1 edit each; grounds the doctrine in current literature.
2. **Operator-vocab lint — DEFER.** The store is ~13 entries; formal update-operators solve a problem it
   doesn't have yet. Revisit when it grows.
3. **Hybrid SQLite (Phase 2) — GATED, not speculative.** The markdown+JSONL + `memory_guard` tests already
   enforce the invariants; triggers are *hardening*. Build only when memory volume + real-row history justify a
   queryable index. (Registers in `docs/ssot.md` as derived/gated when built.)
4. **RRF retrieval / D10 — GATED on Ollama + a first digest.** The eval that decides it — including whether the
   dense/vector lane ships at all — is now specified + citation-verified in
   `docs/d10-retrieval-eval-design-2026-07-08.md` (measure the query mix first; different-family judge = the
   existing `ollama_judge`; AST graph gives free identifier labels). Experiment-with-eval, not adopted SOTA.
5. **Act 2 surrogate corpus — AVAILABLE, DON'T pull forward.** It cannot move the tuning floor (D11 = REAL only)
   and the 7 rows already show discrimination=1.0. Do it *only* if Act 1 slips for many weeks and a richer
   descriptive picture is genuinely wanted.
6. **Act 3 blind head-to-head — after Act 1.** The credibility proof (cheaper than a node-priced incumbent,
   coverage-honest) lands best once real signal backs it; needs a small new harness.
7. **Act 5 clock-arm — the gate is REAL calibration SEPARATION, not TNR.** Deterministic TNR 1.0 clears 0.75; the
   LLM judge (0.2) is a supplement, not the gate. Separation needs REAL rows (0 today). So the clock is far off —
   and even when it fires it is shadow-first and ROI-killed (a zero-value week kills the nightly).
8. **Strategy — keep §4.** Validation primary; autonomy/commercial are downstream of proof, no budget now. Stage
   the "publish the negative result" moat *after* Act 3.

## 5. Anti-goals (the counterexamples — do NOT)

- **Never fabricate a REAL PIR row** to unlock tuning — it corrupts the exact nerve it feeds.
- **Don't pull Acts 2–5 forward** as motion-for-motion's-sake; the plan is narrow-now by design.
- **Don't arm the clock on the 0.2 LLM judge** — separation still needs REAL rows; the deterministic arm carries.
- **Don't build the SQLite substrate** before data justifies it (re-deriving a built enforcement layer).
- **Don't self-approve / self-merge** off vague authorization ([[self-merge-blocked-by-automode]]); outward
  actions (push/merge) need an explicit instruction.

## 6. The single next action

**A real cutover (Act 1).** It is perishable, unsubstitutable, and unlocks the rest. Absent a scheduled window,
the *only* autonomous value that isn't pull-forward is **Phase 0a (the two citations, ~10 min)** — everything
else legitimately waits on real signal. Do not manufacture more.

## 7. Verification basis

Repo-grounded: the 5 Act-0 commits + measured TNR (deterministic 1.0 / LLM 0.2, reproduced 2026-07-08), 0 REAL
in `docs/quality/pir_outcomes.jsonl`, `precert.compute_readiness_freeze` (`313b4a5`). Roadmap threads:
`docs/best-possible-plan-2026-07-08.md` §4–§5, `docs/decisions/0003-agent-brain-hybrid-substrate.md` +
`docs/agent-brain-selfmem-upgrade-plan-2026-07-08.md`, `docs/autonomous-brain-plan-v4-final-2026-07-06.md`
(D10/D11/D12/D13), `docs/decisions/0001-two-store-knowledge-architecture.md` Amendment 1. Air-gapped session —
no engine code changed by authoring this plan.

## 8. Addendum — 2026-07-10 (adversarial re-verification: repairs landed, one decision surfaced)

*A refute-first pass over this plan's load-bearing numbers against their in-code owners found substrate
defects — repaired same-day — and one strategic gap only you can close. No Act was pulled forward.*

- **Repaired — doc-rot on the coverage headline.** CLAUDE.md + `docs/universal-architecture-coverage.md`
  said 40 detectors / 23 classes; the owner (`design_advisor._ARCH_COVERAGE_REGISTRY`) holds **46 / 27**,
  including the multi-vendor classes (Arista/Juniper/FortiGate/ISE/FMC/cloud) the docs never absorbed.
  Reconciled, and a count reconcile-guard added to `tests/test_ssot_registry.py` so the next drift fails
  the suite. (Graph size in CLAUDE.md and the stale pyproject release-train comment fixed in the same pass.)
- **Repaired — the feedback nerve's dead trigger.** Under the Agent-SDK harness `SubagentStop` never fires
  and subagent transcripts are empty, so `/qa` verdicts were recorded only by operator memory (3 rows ever).
  `scorecard --record <message-file>` (the message arm) now exists, tested, and `/qa` ends by invoking it.
- **Recorded — §3's judge-gate margin is thin.** "Deterministic TNR 1.0 clears 0.75" holds with a 95%
  Clopper–Pearson lower bound of 0.779 (margin 0.029); one panel miss un-clears it (11/12 → 0.661).
  Hardening targets (18 / 29 / 59, independently sourced classes only) are registered in
  `docs/quality/README.md` — gated hardening, not scheduled work.
- **DECISION NEEDED (yours) — Act 1 has no diverse path.** The critical path is single-homed on a real
  cutover window with no dated fallback; the schema already defines `shadow-PIR`, [HISTORY-REDACTED]'s MOP/NRFU
  execution will produce real outcomes harvestable at zero fabrication cost, and a lab-gear window is a
  real (non-fabricated) outcome too. **Trigger: if no REAL row exists by 2026-08-05, explicitly decide**
  (a) whether [HISTORY-REDACTED] execution outcomes are harvested as `shadow-PIR` rows, and (b) whether a lab cutover
  counts as `REAL` for the D11 floor or joins the surrogate classes. Until then the answer stays "wait" —
  this addendum adds a date to the waiting, not work.
