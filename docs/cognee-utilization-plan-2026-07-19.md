# Utilizing the Cognee research — phased plan (2026-07-19)

*Companion to `docs/decisions/0005-cognee-evaluation.md`. Answers "now that we've done the research, how do we
actually use it to improve our setup" — not a Cognee mapping doc (that's the ADR + `memory/cognee-evaluation-2026-07-19.md`),
this is the action plan across every lever currently open in the memory/autonomy-brain system, using the
Cognee research as the immediate trigger. Four phases: one done today, two ready pending a one-word go, one
needs your design input first, one is self-activating.*

## 0. Verdict in one line

The research itself changed nothing structural — it confirmed the existing bet. What's actually left to
*improve the setup* was already known before Cognee (`docs/autonomous-brain-plan-v4-final-2026-07-06.md`,
`memory/feedback-loops-data-gated.md`): the six-nerve brain is built, the frontier is feeding it real data and
closing two specific open gates, not building more machinery.

## Phase 0 — done today, no action needed

- Two citations landed in code (not just docs): `cisco_toolkit/recall.py` (arXiv 2601.07978 v4, the "don't chase
  LLM-cognify graphs" evidence) and `cisco_toolkit/learnings.py` (Cognee's `remember/recall/forget/improve` API
  corroborating the SelfMem operator vocabulary). Targeted tests green (`test_recall`, `test_learnings`,
  `test_readonly_and_no_egress`, `test_attestation`).
- `docs/decisions/0005-cognee-evaluation.md` records the verdict formally; `memory/cognee-evaluation-2026-07-19.md`
  + `memory/external-plans-map-to-code.md` + `memory/second-brain-plan-v2.md` carry the working-memory trail.

## Phase 1 — owner-gated, and the recommendation on both is WAIT (not "pick one")

Both are fully built and tested; both stayed unactivated because they cost real money or need a standing
service, never because anything is missing. Asked for a decision rather than a menu, the recommendation on
both is **not yet — and for a reason tied to this engagement's phase, not to timidity**:

1. **Arm nightly autonomy** (`cisco_toolkit/clock.py`, `.claude/hooks/nightly-run.sh` — dry-run tested, D13
   spend-capped). Mechanically ready: set `ANTHROPIC_API_KEY` in the run environment, then
   `ASNE_NIGHTLY_ARMED=yes bash .claude/hooks/nightly-run.sh --live` manually for ~a week (per D5) before
   registering a Task Scheduler job. **Recommendation: don't arm yet.** A nightly propose-only run bills real
   money every night to re-read local state that, right now, is quiet and — per Phase 3 below — has no fresh
   outcome signal to reason over. The clock nerve's own `--report` ships a zero-value kill flag precisely for
   this failure mode. The moment the value flips is a *cutover approaching*: that's when drift, self-healing,
   and the intel feed have something to say each night.
2. **Stand up Batfish twin-verify** (`docs/decisions/0002-batfish-twin-verify-spike.md` — conditional GO,
   CLI-half only, never ACI/vManage). Needs Docker installed plus a running pybatfish service; then wiring
   `differentialReachability` into the existing NRFU pre/post diff is the remaining code work.
   **Recommendation: defer until a cutover MOP actually needs it.** ADR-0002 already bounds it as *never the
   sole verifier* (NRFU still certifies), so pre-cutover it buys a heavyweight standing dependency for a
   capability nothing is currently asking for.

Neither recommendation is a refusal — say go on either and the ready steps run; the credential and the Docker
install remain yours by nature (an API key is never something the agent should enter).

## Phase 2 — CLOSED, not open: D10 stays PARTIAL (correction, 2026-07-24)

**This section previously framed D10 as an open question awaiting the owner's design pick. That was wrong, and
the error is corrected here rather than silently edited away.** The decision was already taken on 2026-07-11 and
is recorded in `docs/quality/README.md` ("Screening-gate instrument ladder"): **accept the PARTIAL protocol as
the honest Phase-2 verdict; do NOT loosen the gate to manufacture an unlock.** Three specific defects in the
original text, each verifiable against that section:

1. **It re-opened a closed decision.** The owner-doc already decided accept-PARTIAL; presenting it as "needs
   your design input" invites re-litigating a settled call as a quick win — exactly what the recorded decision
   says a future session must not do.
2. **One "recommended" lever was already measured-REFUTED.** The original text suggested "whole-document context
   instead of windowed excerpts." Excerpt coverage *is* the refuted hypothesis: tripling the window
   (v1 single 1800-char → v2 head + top-2, 3×1800, on qwen3:8b) raised only self-consistency (κ 0.87→1.00)
   while anchor accuracy did not improve at all — 8/15 → 7/15, with the clear-relevant stratum going 2/5 → 0/5.
   Recommending it would have spent hours re-testing a dead lever.
3. **The second option is explicitly ruled out.** "Pull a fourth model family" — the owner-doc states plainly
   "NOT trying more models — three have failed identically." Listing it, even as not-recommended, keeps a dead
   path alive.

**Why accept-PARTIAL is the right call and not a resignation:** the §6 gate exists to certify the judge is
trustworthy enough to grade the semantic/multi-hop strata. Changing the ensemble so the judge *passes* — after
we have seen precisely which anchors it under-graded — does not make it trustworthy; it lowers the bar, and the
verdicts a gate-loosened judge then produces are *less* trustworthy, not more. The honest state stands: the
identifier stratum is already answered judge-free (BM25 raises MRR@5 0.139 → 0.276, Δ +0.137, clearing the
+0.05 margin, but p=0.107 / dz=0.38 miss the pre-registered significance bars at n=20 — directionally positive,
underpowered); semantic and multi-hop stay honestly UNDECIDED.

**The one thing that would legitimately change it is human-owned and deliberately not mine to draft:** a §6
protocol *correction* ratified by the protocol owner as a mis-specification fix — the leading candidate being an
**asymmetric or neutral-only relevance ensemble** (take-the-MIN looks right for the *reject* direction, where
clear-irrelevant scores 4–5/5, and wrong for the *accept* direction). Per the owner-doc it should ideally be
re-gated "by a hand that did not fit it to these anchor outcomes" — this session has now read the per-anchor
bands, so an instrument spec drafted here would be pre-registration-contaminated. That is the reason this is
not an offer to draft one.

## Phase 3 — self-activating, nothing to do

Calibration's real-data floor (`cisco_toolkit/calibration.py`, D11-gated at N≥5 REAL) stays at N=0 REAL by
design — this is a pre-cutover engagement. It unlocks itself the first time this engagement reaches an actual
post-cutover PIR; don't force it, don't backfill it with surrogate rows to "improve" the number
(`memory/feedback-loops-data-gated.md` is explicit about this).

## Do-not / caveats

- **Do not** re-research Cognee, Graphiti, claude-mem, or Obsidian-MCP again — all four are recorded as
  rejected-with-reasons in `memory/second-brain-plan-v2.md`; the delta of re-running any of them is expected
  to be near zero absent a new version claim worth verifying.
- **Do not** tune the D10 instrument after seeing a result — pre-registration order matters more than speed.
  And do not re-open Phase 2 as a quick win: it is CLOSED (accept-PARTIAL, 2026-07-11), not pending.
- **Do not** fabricate PIR outcome rows to move Phase 3 — the gate is honest-absence by design, not broken.
- Phase 1's two items are the only "just say go" items in this plan, and the standing recommendation on both is
  WAIT-for-cutover; Phase 2 is closed; Phase 3 moves on a real external event. **The honest net: there is no
  agent-ownable build left in the autonomy-brain system right now.** That is the system working as designed
  (`memory/feedback-loops-data-gated.md`: the frontier is feeding it data, not building more) — a future session
  reading this should resist the urge to invent work here to look busy.
