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

## Phase 1 — ready now, pending your go (infra/spend, not research)

Both are fully built and tested; both stayed unactivated because they cost real money or need a standing
service, never because anything is missing:

1. **Arm nightly autonomy** (`cisco_toolkit/clock.py`, `.claude/hooks/nightly-run.sh` — dry-run tested, D13
   spend-capped). To go live: set `ANTHROPIC_API_KEY` in the run environment, then
   `ASNE_NIGHTLY_ARMED=yes bash .claude/hooks/nightly-run.sh --live` manually for about a week (per D5) before
   registering a Windows Task Scheduler job. Real metered spend starts the moment you do this.
2. **Stand up Batfish twin-verify** (`docs/decisions/0002-batfish-twin-verify-spike.md` — conditional GO,
   CLI-half only, never ACI/vManage). Needs Docker installed and the pybatfish service running; once it's up,
   wiring `differentialReachability` into the existing NRFU pre/post diff is the remaining code work.

Say the word on either and I'll execute the ready steps; the account/Docker provisioning itself is yours.

## Phase 2 — needs your design input before I touch anything

**D10's retrieval gate still fails** — three models across two families (qwen3:4b/8b, llama3.1:8b) all
collapse on the clear-relevant stratum (7-8 of 15, κ up to 1.00), and excerpt-coverage was measured-refuted as
the cause (`memory/feedback-loops-data-gated.md`, rung 5/PR #335). The rule that's non-negotiable here: a new
instrument must be pre-registered *before* any run, never tuned after seeing results — so this genuinely needs
your call, not mine, before I do anything.

Two candidate directions, ranked:
- **(recommended) change the ensemble protocol, not the model** — the harshness traced to *framing*
  (take-the-MIN dual-prompt ensemble), not model choice or excerpt size; e.g. majority-of-3 instead of
  take-the-MIN, or whole-document context instead of windowed excerpts. Three models have already failed under
  the current protocol, so the model axis is close to exhausted as a lever.
- pull a fourth model family — lowest expected payoff; flagging only for completeness, not recommending it.

If you pick a direction, I'll draft the full v3 instrument spec for your sign-off, then it gets pre-registered
and run — in that order.

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
- **Do not** fabricate PIR outcome rows to move Phase 3 — the gate is honest-absence by design, not broken.
- Phase 1's two items are the only "just say go" items in this plan; everything else needs either your design
  input (Phase 2) or a real external event (Phase 3) before it moves.
