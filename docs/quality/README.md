# Quality scorecard — the feedback nerve (substrate)

This directory is the **persisted quality trend** for the "provably improves over time" half of the
Deliverable Excellence Standard — the **feedback nerve** of
[`docs/autonomous-brain-plan-v4-final-2026-07-06.md`](../autonomous-brain-plan-v4-final-2026-07-06.md).
As of Phase 0 the schema below is **wired**: a `SubagentStop` hook appends each `/qa` verdict, and a
deterministic golden-snapshot eval harness scores a known-good deliverable in `pytest`.

## `scorecard.jsonl` — one JSON object per line, append-only

Every consequential QA / eval cycle appends one row. **Verifiable facts only — never a self-assessment**
(the coasting trap: an agent that records "great progress" reads it back and stops trying).

| field | type | meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | when the verdict was produced |
| `deliverable` | string | which artifact (e.g. `design`, `mop`, `crd`, `hld`, or a snapshot id) |
| `score` | number \| null | eval-suite score (0–100) from the golden-snapshot harness; `null` on a `/qa`-verdict row (a QA transcript yields a verdict, not a number) |
| `verdict` | string | `APPROVE` / `BLOCK` (from deliverable-qa-reviewer) |
| `judge_tnr` | number \| null | the measured true-negative rate of the JUDGE that produced this verdict (`cisco_toolkit.defect_panel`), or `null` when unmeasured. An `APPROVE` is only trustworthy to the extent the judge is *shown* to REJECT known-bad work (Jain et al. `2510.11822`: LLM judges default to TNR < 25%). **A QA-verdict row with `judge_tnr` null/absent is PROVISIONAL** — trust unquantified until the defect-panel baseline runs. A deterministic `eval_harness` row is bias-free and carries `null` here (no judge involved). |
| `counterexamples` | int | number of grounded defects the verifier found this cycle (should trend ↓) |
| `laws_tripped` | array | which of the 10 Deliverable-Excellence Laws failed, if any |
| `commit` | string | git SHA the verdict was produced against |
| `notes` | string | short, factual — the counterexample, not an opinion |

Example (illustrative — do not hand-edit real data in):

```json
{"date":"2026-07-06","deliverable":"design","score":null,"verdict":"BLOCK","counterexamples":2,"laws_tripped":["L3"],"commit":"4bedd9f","notes":"ops Security axis rendered 'complete' with no not-assessable branch"}
```

## How rows get here (Phase 0 — wired)

- **The `/qa` appender.** [`.claude/hooks/scorecard-append.sh`](../../.claude/hooks/scorecard-append.sh)
  runs on `SubagentStop`; when the stopped subagent's final message parses as a QA verdict, it appends
  one row via [`cisco_toolkit/scorecard.py`](../../cisco_toolkit/scorecard.py). It records the
  **independent verifier's** verdict (proposer ≠ verifier) — a verifiable fact, never a self-assessment.
  Conservative + fail-open: no confident verdict → **no row** (never a fabricated one); any error → nothing
  appended, the turn never blocks. The parser is unit-tested in `tests/test_scorecard.py`.
- **The message arm — `python -m cisco_toolkit.scorecard --record <file>`.** Under the Claude **Agent
  SDK** harness (the desktop app), `SubagentStop` never fires and Agent-tool subagent transcripts are
  empty — the hook above never sees a verdict there (measured: 3 rows in the nerve's first 3 days, all
  recorded by hand). The `/qa` command therefore ends by saving the reviewer's **verbatim** final message
  to a UTF-8 file and invoking `--record` on it — same conservative parser as the hook (no per-artifact
  signature → no row), and a file rather than stdin because a cp1252 Windows console mangles em-dashes.
  `--record-from <transcript>` remains the arm for the interactive CLI, where the transcript exists.
- **The golden-snapshot eval harness.** [`cisco_toolkit/eval_harness.py`](../../cisco_toolkit/eval_harness.py)
  scores a *fixed known-good deliverable* against deterministic, offline checks — SSOT `reconcile` clean,
  citations byte-match, and the machine-checkable Deliverable-Excellence Laws present (the repo-grounded
  subset **L1/L2/L3/L6/L8/L9/L10**; the full ten-Law Standard is owned by the external Deliverable Excellence
  Kit, so Laws with no in-repo signal are reported UNVERIFIED, never a blanket 10/10). **Tiered** in
  `tests/test_eval_harness.py`: the snapshot-only **smoke** set runs on every change (the `verify-green`
  gate); `EVAL_FULL=1` adds the **full** set on release — render the DOCX family + the rendered-citation
  checks, and score the real on-disk snapshot. The harness's `ScoreResult.to_scorecard_row()` emits the
  same schema, so a release run can append a *scored* row.
- `/briefing` (live) reads the tail of this file and renders the trend in the morning digest.

**Coverage-honest note:** while this file is empty, the briefing says so plainly ("no entries yet"). Absence
is reported as absence — it is never rendered as "healthy" (Law 3). The score is a percentage of *applicable*
checks; a partial deliverable's unassessable Laws are disclosed as UNVERIFIED, never counted as passed, and an
empty deliverable scores `null`, never a false 100.

## Judge trust — the defect panel + cross-family judge (Move 1)

The `judge_tnr` field above is only meaningful if something *measures* it. A QA verdict is a Claude judge on
Claude's work, and the literature is blunt: LLM judges default to **TNR < 25%** — they approve almost anything
(Jain et al. `2510.11822`; self-preference / "great models think alike" `2502.04313`), and agents are
systematically **over-confident** about their own success — some that succeed only 22% of the time predict 77%
(`2602.06948`, verified 2026-07-08). So an all-`APPROVE`
scorecard is the *predicted output of a broken instrument*, not evidence of good work. Two instruments
**measure** the judge instead of trusting it:

- **[`cisco_toolkit/defect_panel.py`](../../cisco_toolkit/defect_panel.py) — the deterministic floor.** 12
  doctrine-mapped defects, each an atomic script-injected violation of a named assessment law (oracle sound,
  verified non-vacuous). `deterministic_findings()` is the bias-free arm: it mechanically catches and localizes
  **all 12** (localized TNR = 1.0) — the floor any LLM judge must clear. `python -m cisco_toolkit.defect_panel`.
  **Small-N honesty (computed 2026-07-10):** 12/12 is a point estimate; the exact one-sided 95% lower
  bound (Clopper–Pearson) is **0.779**, so the 0.75 arm-gate is cleared by 0.029 — and a single future
  panel miss would un-clear it (11/12 → lower bound 0.661). Registered hardening targets (gated, not
  scheduled): **18** defects → the gate survives one miss; **29/29** → licenses "TNR ≥ 0.90"; **59/59**
  → "≥ 0.95". New defect classes must come from an *independent* source (real PIR incidents once they
  exist; blind proposals from another model family or person) — the current 12 were selected by the
  detectors' own authors, so same-hand panel growth has diminishing evidential value.
- **[`ollama_judge.py`](../../ollama_judge.py) — the cross-family minority-veto arm.** A *different model
  family* via a local Ollama (127.0.0.1, air-gapped, $0) so it does not share Claude's failure modes. It lives
  at repo root, outside `cisco_toolkit/`, so its `urllib` use never trips the no-egress attestation. Uses
  Ollama Structured Outputs + a neutral per-condition checklist — the *only* framing measured to discriminate
  ("try to disprove" rejects even clean work; "most are fine" approves even defects).

**Honest characterization (qwen3:4b on a 16GB CPU host):** the local judge genuinely *discriminates*
(`approves_clean` = True, so it is specific) but is a **weak detector** (rejection ≈ 0.2 — catches only the
blatant defect). It is a *supplement*, not a replacement; the deterministic arm (12/12) is the reliable
instrument on this hardware. `run_baseline` judges a known-GOOD deliverable **first** and reports
`approves_clean` (specificity): a "rejects everything" judge scores rejection 1.0 yet is worthless, so
`rejection_rate` is only meaningful when `approves_clean` is True. Hermetic tests inject the model I/O, so the
harness never needs a running model (`tests/test_defect_panel.py`, `tests/test_ollama_judge.py`); both are in
the self-check `GUARD_FILES` so a gutted TNR floor reads **RED**.

## `scorecard trend` — the line you watch go up (Phase 1)

```
python -m cisco_toolkit.scorecard trend
```

Renders the append-only log as a **time series** — the [feedback nerve's](../autonomous-brain-plan-v4-final-2026-07-06.md)
whole point is that improvement is *watchable*, not asserted. Rows are bucketed by ISO week; per week you see
cycles, block-rate, mean counterexamples, and mean eval-score, then the two watch-lines with a sparkline and a
direction:

- **counterexamples / cycle** — should trend **↓** (fewer grounded defects per QA cycle);
- **eval score** — should trend **↑** (the golden-snapshot harness's number, on release rows).

Coverage-honest by construction (`cisco_toolkit.scorecard.summarize_trend` is the pure core; `render_trend`
prints it): an empty log says "no entries yet" (never a fabricated trend); a log with no *scored* rows says the
score line has none yet rather than drawing a zero; and a span **under two weeks** is labelled *not-yet-meaningful*
instead of dressed up as a trend. The Phase-1 acceptance is exactly this — *≥ 2 weeks of rows render a trend* —
pinned in `tests/test_scorecard.py`. The morning `/briefing` shows a one-line digest of the same data; `trend` is
the full view.

## `pir_outcomes.jsonl` — PIR-outcome calibration (Phase 1, D11-gated)

The *retrospective* half of the feedback nerve. The engine makes a **prediction** before a cutover (a per-unit
readiness verdict) and the **PIR** records what actually happened; joining them tells us whether the scoring was
*calibrated*. One JSON object per line, append-only — **verifiable outcomes only, never a guess**:

| field | type | meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | when the PIR / war-room recorded the outcome |
| `engagement` | string | engagement or snapshot id |
| `unit` | string | the device / wave / site the prediction was about |
| `source_class` | string | provenance — `REAL` (a genuine post-cutover PIR / war-room outcome) or a surrogate class (`fault-injected` / `retro-public` / `compare-pair` / `shadow-PIR` / `synthetic`). **Only `REAL` counts toward the D11 tuning floor**; surrogate rows validate detectors and appear in the descriptive gap but never tune the scorer. Absent / unrecognized ⇒ treated as non-`REAL` (fail-safe) |
| `predicted` | string | the pre-cutover readiness verdict: `READY` / `CAUTION` / `NOT_READY` (aliases accepted) |
| `actual` | string | the real outcome: `clean` (no incident) / `incident` (fault / rollback) (aliases accepted) |
| `commit` | string | git SHA the prediction was produced against |
| `notes` | string | short, factual — what actually happened |

[`cisco_toolkit/calibration.py`](../../cisco_toolkit/calibration.py) derives the **calibration gap** — the
*false-confidence rate* `P(incident | READY)` (we said go, it broke) and the *false-alarm rate* `P(clean |
NOT_READY)` (we blocked a fine unit) — and, from the gap's direction, whether the scorer is **too lenient** or
**too strict**.

```
python -m cisco_toolkit.calibration --report
```

**The D11 gate is load-bearing.** Calibration is **descriptive-only until N ≥ 5 REAL labeled outcomes** — measured
against `source_class == REAL` only, because surrogate / public / synthetic rows validate detectors but must NEVER
unlock a tuning move (otherwise feeding public or multi-customer production data would silently re-tune the engine,
the no-fabrication law turned on the calibration nerve itself). Below the floor `propose_adjustment` **refuses to
move any `ScoringConfig` parameter and says exactly why** (two PIRs must never re-tune the engine). At/above the floor it proposes **one small, reversible, human-gated** delta on a single
conservative lever (`caps.XL` by default) and **applies nothing** (`applied` is always `False`; every unattended
action is propose-only). A full per-finding weight refit is out of reach from per-unit pass/fail labels — stated as
a limitation, not overclaimed. This is **distinct from** `analyze.compute_calibration_report`, which is a
*prospective, within-snapshot* band-discrimination diagnostic (do this fleet's bands separate?) rather than a
*retrospective, cross-engagement* predicted-vs-actual check. Discipline pinned by `tests/test_calibration.py`.

**Prior art grounds these choices** (verified 2026-07-08): **SelfMem** (arXiv `2607.03726`) finds a well-constructed
*small* corpus beats a large one and that calibration peaks at an *intermediate* refinement stage — corroborating the
N-floor over a big-N chase; **Holistic Trajectory Calibration** (arXiv `2601.15778`) is trajectory-level prior art for
calibrating an agent's own success estimate; and the agentic-overconfidence result (`2602.06948`, cited under Judge
trust above) is the empirical *why* — self-scored confidence is not trustworthy, so the outcome join is what calibrates.

## `fault_corpus` — the fault-injected calibration corpus (Move 2)

The strongest *honest* calibration source while N≈0 REAL: **ground truth by construction.**
[`cisco_toolkit/fault_corpus.py`](../../cisco_toolkit/fault_corpus.py) starts from a minimal all-pass scenario
that scores `READY`, then injects **one real fault at a time** (SPOF gateway, single-homed uplink, Critical
device health, cross-layer Critical, err-disabled port, half-duplex uplink). Each fault's actual outcome
(`incident`) is known without fabricating anything, and the row records what the engine *predicts*.

```
python -m cisco_toolkit.fault_corpus --report   # does the scorer flag every fault + pass the clean baseline?
python -m cisco_toolkit.fault_corpus --emit      # the rows as JSONL, for appending to pir_outcomes.jsonl
```

**Measured:** the deterministic readiness scorer discriminates cleanly — clean → `READY`, and **6/6** injected
faults → non-`READY`. Every row is tagged `source_class=fault-injected`, so it populates the **descriptive**
calibration gap (proving the scorer separates good from bad) but **never** unlocks a tuning move — the D11
floor counts `REAL` only. This is why, once the 7 rows are emitted into `pir_outcomes.jsonl`, `calibration
--report` shows `N=7, accuracy=1.0` yet still reads `[GATED] … 0 REAL`: the surrogate rows validate the
detector without ever re-tuning the engine. Pinned by `tests/test_fault_corpus.py` (in the self-check
`GUARD_FILES`).

## `nightly_runs.jsonl` — the clock's safety rails (Phase 2, rails only)

Phase 2 wires a nightly, propose-only headless `claude -p` run. That run spends **real metered money**
(D13) and can misfire, so [`cisco_toolkit/clock.py`](../../cisco_toolkit/clock.py) provides the two rails a
wrapper must check **before** it ever fires, plus the ledger they read/append:

- **3-fail circuit breaker + 30-min cooldown (D5)** — three consecutive failed runs trip it; it holds
  **open** for the cooldown, then allows one **half-open** probe (a fresh failure re-opens it). Fail-safe:
  a tripped breaker with no readable timestamp stays *open* (better to skip a nightly than hammer a failing
  system).
- **Daily-spend ceiling (D13)** — headless runs bill outside the interactive subscription; once today's
  spend reaches the ceiling (`ASNE_NIGHTLY_CEILING_USD`, default \$2), no further run.
- **Weekly spend-vs-action report** — `--report` flags a **zero-value week** (cost but no action) as the
  *kill-the-briefing* signal; value has to be falsifiable too.

```
python -m cisco_toolkit.clock --preflight   # go/no-go; exit 0 = GO, 3 = NO-GO (a wrapper bails on 3)
python -m cisco_toolkit.clock --report      # trailing-7-day spend vs. actions
```

**Rails only — this module starts nothing and spends nothing.** Scheduler registration and the `claude -p`
invocation are **not** wired: like auto-wiring `/briefing` into SessionStart, they are deferred to explicit
approval (a system-config + real-spend change). The decision core takes an injected clock, so it is fully
deterministic; pinned by `tests/test_clock.py` (the breaker trips on exactly three induced failures — the
Phase-2 acceptance).

The manual-trigger wrapper [`nightly-run.sh`](../../.claude/hooks/nightly-run.sh) shows what a
nightly pass *would* do — **dry-run by default** (`bash .claude/hooks/nightly-run.sh` prints the preflight,
the propose-only prompt, and the caps, then stands down; **spends \$0, writes no ledger row**). It is
preflight-gated (NO-GO → stand down) and the live path is **double-guarded** (`--live` **and**
`ASNE_NIGHTLY_ARMED=yes`) so it cannot spend by accident; it is **not** registered as a hook and **not**
scheduled. Its safety properties are pinned by `tests/test_nightly_wrapper.py`. To arm/schedule it later,
see the header of the script — that step is yours (spend + system change).

## Agent-system self-check (Phase 4 — the immune system)

[`cisco_toolkit/selfcheck.py`](../../cisco_toolkit/selfcheck.py) re-derives, from the repo, whether the
guards are **non-vacuous** and the substrate is healthy — a *deleted or gutted* guard reads **RED**, not
silently gone (a skipped test is red). It runs in the nightly wrapper (local, free, no egress) and RED items
lead the briefing. Checks: scorecard / PIR / nightly-ledger substrate present; the learnings lint passes;
all guard suites exist **and assert**; the graph is fresh (absent → UNKNOWN, never GREEN). Coverage-honest —
an un-evaluable check is UNKNOWN, disclosed, never counted healthy.

```
python -m cisco_toolkit.selfcheck    # exit 0 unless a check is RED (then 4)
```

Pinned by `tests/test_selfcheck.py` (a gutted guard, a missing substrate, and a stale graph each read
correctly; a healthy repo reads GREEN).

## `learnings.md` — the distilled, verifiable engine facts (sibling substrate)

The other half of the feedback nerve: [`learnings.md`](learnings.md) is the distilled store of durable,
**verifiable** facts about the codebase/engine, surfaced at SessionStart (via `.claude/hooks/session-brief.sh`)
so the lessons shape every session. Discipline — **under 100 lines · every entry cited · verifiable facts only,
never a self-assessment** — is enforced by [`cisco_toolkit/learnings.py`](../../cisco_toolkit/learnings.py) +
`tests/test_learnings.py` (the coasting trap: a store that records "great progress" and reads it back stops
trying). It is distinct from `docs/log.md` (the raw `/retro` source) and the career/domain vault.
