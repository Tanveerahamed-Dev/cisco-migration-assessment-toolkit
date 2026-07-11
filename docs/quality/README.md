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
| `judge_tnr` | number \| null | the measured true-negative rate of the JUDGE that produced this verdict, **stamped by the QA-verdict writers from the latest `judge-baseline` row** on this scorecard (`scorecard.latest_judge_baseline`; measured by `python ollama_judge.py <model> --append-baseline` over the `cisco_toolkit.defect_panel` panel) — or `null` when no baseline was ever measured (honest absence, never a guess) **or when the latest baseline itself recorded null trust** (the specificity fail-safe; latest row wins, so a refuting re-baseline demotes — P1-3). An `APPROVE` is only trustworthy to the extent the judge is *shown* to REJECT known-bad work (Jain et al. `2510.11822`: LLM judges default to TNR < 25%). A deterministic `eval_harness` row is bias-free and carries `null` here (no judge involved). |
| `provisional` | bool \| null | **the machine-readable PROVISIONAL mark (P0-6 / DEC-004) — enforced in code, not by this table**: `true` on any APPROVE whose `judge_tnr` is `null` or below the broken-instrument floor owned by `cisco_toolkit.scorecard.JUDGE_TNR_FLOOR` (0.25 — that constant is the owner; this cell is a cited cache). A provisional APPROVE is **ADVISORY — nothing may gate on it**. `scorecard.is_provisional` is the one predicate; `append_row` enforces the mark at the write choke point (a fabricated `provisional: false` cannot persist), and `selfcheck.check_judge_trust` is the consumer check that reads **RED** on any persisted row contradicting the predicate in the trusting direction. `false` on deterministic scored rows and floor-clearing judge APPROVEs; `null` on non-verdict rows (`judge-baseline` measurements) and pre-P0-6 history — **unmarked is still treated advisory by the predicate**, never trusted by default. |
| `counterexamples` | int | number of grounded defects the verifier found this cycle (should trend ↓) |
| `laws_tripped` | array | which of the 10 Deliverable-Excellence Laws failed, if any |
| `commit` | string | git SHA the verdict was produced against |
| `notes` | string | short, factual — the counterexample, not an opinion |
| `authored_by` | string \| null | which agent authored the reviewed deliverable(s) — the **proposer** (P0-2/G-002). Optional: `null` = provenance undeclared; pre-P0-2 rows carry no key at all — both stay valid. |
| `reviewed_by` | string \| null | which agent produced this verdict — the **verifier**. The recorder **refuses** any row where `authored_by` == `reviewed_by` (non-empty, case/space-insensitive): a self-review can never mint a quality row (`scorecard.check_independence`, exit 2 on the record arms, backstopped in `append_row`). Residual, declared: these are *declared* identity strings, not proof — full enforcement tops out at the OS/permission layer (CLAUDE.md trust-boundary note). |

Example (illustrative — do not hand-edit real data in):

```json
{"date":"2026-07-06","deliverable":"design","score":null,"verdict":"BLOCK","counterexamples":2,"laws_tripped":["L3"],"commit":"4bedd9f","notes":"ops Security axis rendered 'complete' with no not-assessable branch","authored_by":"design-author","reviewed_by":"deliverable-qa-reviewer"}
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
  Both arms take `--authored-by <agent> --reviewed-by <agent>` (the provenance pair above) and refuse a
  non-empty match up front — the P0-2 proposer≠verifier wedge, proven in
  `tests/test_proposer_verifier_guard.py` alongside the read-only analyst-roster pin.
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

**Honest characterization (measured through the P1-3 ladder, 2026-07-10/11, 15.4 GB CPU-only host):** the
local arm is **not yet a trustworthy detector**. qwen3:4b discriminates only *unstably* — two same-config
temperature-0 runs flipped between localized TNR 0.4-with-specificity and 0.2-without (it rejected the clean
control), so a single run must never be trusted: re-baseline with `--runs 2` (worst-run protocol, below).
qwen3:8b detects far more (localized 0.6–0.8, the only judge to catch `D-03` phantom-health) but rejected the
clean control in **both** runs (it insists `n/a - verification step` is a missing rollback), so it has **no
specificity** and records null trust; qwen3 think-mode is compute-infeasible on this host (≈360 s/call, empty
content once the think block exhausts the token budget). The LLM arm stays a *supplement*; the deterministic
arm (12/12) is the reliable instrument on this hardware. `run_baseline` judges a known-GOOD deliverable
**first** and reports `approves_clean` (specificity): a "rejects everything" judge scores rejection 1.0 yet is
worthless, so `rejection_rate` is only meaningful when `approves_clean` is True. Hermetic tests inject the
model I/O, so the harness never needs a running model (`tests/test_defect_panel.py`,
`tests/test_ollama_judge.py`); both are in the self-check `GUARD_FILES` so a gutted TNR floor reads **RED**.

**Advisory-until-measured policy (P0-6 / DEC-004; gap G-006).** A `/qa` APPROVE is **demoted to advisory**
unless the judge that produced it has a measured baseline clearing `judge_tnr ≥ JUDGE_TNR_FLOOR`
(`cisco_toolkit/scorecard.py` owns the 0.25 figure — the Jain et al. broken-instrument threshold). The
mechanics are code, not this paragraph: the QA-verdict writers **stamp** each row's `judge_tnr` from the
latest `judge-baseline` row (`latest_judge_baseline`); `is_provisional` + `append_row` **persist**
`provisional: true` on every unmeasured / below-floor APPROVE (a fabricated `false` cannot be written);
and `selfcheck.check_judge_trust` is the **consumer** — anything gating on verdicts must treat a
provisional APPROVE as non-gating, and the self-check reads RED if a row is ever persisted trusting in
contradiction. Gate consequence: a PROVISIONAL APPROVE never advances a PPDIOO gate by itself — it is the
reviewer's recorded opinion, pending an instrument that has *earned* trust. Re-baseline with
`python ollama_judge.py qwen3:4b --runs 2 --append-baseline` after any judge/prompt/model change; the
appended row is what promotes (**or demotes**) every subsequent verdict — `latest_judge_baseline` is
latest-row-wins (P1-3), so a null-trust re-baseline (the specificity fail-safe) revokes an older numeric
one, and `--runs N` records the WORST of N runs (an unstable judge is never promoted by its best run).
Ollama unreachable → the arm prints `signal_absent` and appends **nothing** (a measurement row is never
fabricated; a multi-run protocol that cannot complete also records nothing).

**Re-baseline record (2026-07-10, P0-6d):** re-run over the 5-defect text-visible panel via the new arm —
localized TNR **0.2** (`D-12` caught; `D-01/03/06/11` approved), `approves_clean=True`, reproducing the
2026-07-08 measurement exactly. **Still below the 0.25 floor ⇒ judge APPROVEs remain PROVISIONAL/advisory**
until a stronger judge (bigger model, better prompt, or a Claude-arm panel run) clears it.

**P1-3 re-baseline ladder (2026-07-10 → 07-11, DEC-004) — outcome: floor NOT durably cleared; the judge
stays ADVISORY.** One variable per rung over the fair subset (the 5 text-visible defects D-01/03/06/11/12);
every completed panel measurement recorded via `python ollama_judge.py <model> [--runs N] --append-baseline`
(append-only — failures included, nothing cherry-picked; per-rung commits on the P1-3 branch make each row's
exact prompt/config reproducible):

| rung | variable changed | measured | row |
|---|---|---|---|
| 0 | none — reproduce the recorded state at HEAD | clean=True, localized **0.2** (only `D-12`) — identical to the two rows on record | not re-appended (already ×2) |
| 1 | prompt: deliverable-first, numbered conditions, forced per-condition HOLDS/DOES-NOT-HOLD walk | clean=True, rejection ↑0.4 but localized **0.0** — both rejects bound `defect_class` to the *first* enum value | `@fddada1` |
| 2 | prompt: reasoning must end `` `HELD: <name|NONE>` ``, `defect_class` copies it | run A: clean=True, localized **0.4** (`D-06`,`D-12`) — *point estimate clears 0.25*; same-config rerun B: clean=**False**, localized 0.2 → **run A refuted; unstable** | `@8d208bf` ×2 (0.4, then null trust) |
| 3 | decoding: qwen3 `think=true` | probe-refuted on this host: ≈360 s/call, content empty (think exhausts `num_predict`) — a full run would mechanically score 0 | none (feasibility probe, not a panel run) |
| 4 | model: qwen3:8b (installed locally; nothing pulled), worst-of-2 | localized **0.8/0.6** (catches `D-03`) but clean control rejected in **both** runs (`n/a - verification step` read as missing-rollback) → **null trust** | `@ee01898` (worst run + spread in notes) |

Small-N honesty (stated per the P1-3 mandate): the fair subset is **n=5**, so even a passing point estimate
carries a wide interval — 2/5 = 0.4 has a one-sided 95% Clopper–Pearson lower bound of **0.076**, far below
the 0.25 floor (4/5, LB 0.343, is the smallest outcome whose *bound* clears it). The DEC-004 promotion gate
is a point-estimate **screening floor, never calibration proof** — the same convention as the deterministic
arm's 12/12 → 0.779 above. What the ladder hardened into code: `--runs N` (worst-run recording) and
**demotion semantics** — `latest_judge_baseline` is latest-row-wins, so the rung-2 stale 0.4 can never keep
stamping APPROVEs gating after a newer refuting run
(`tests/test_scorecard.py::test_latest_judge_baseline_null_trust_demotes`). Highest-value next steps, in
order: (1) one more prompt iteration targeting the 8b's single specificity failure (its detection already
doubles the floor; condition 1's wording vs `n/a`-style rollbacks is the one blocker); (2) a mid-size
instruct model — **needs a human-approved pull: model download = egress**, outside the ADR-0001 local-
inference carve-out; (3) a GPU / higher-RAM host, which unlocks both think-mode and swap-free 8b.

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

## The sealed holdout — `holdout-contract.md` (DEC-007, P1-2; dormant until N ≥ 50 REAL)

[`holdout-contract.md`](holdout-contract.md) is the **policy owner** (registered in
[`docs/ssot.md`](../ssot.md)) for the DEC-007 hybrid data policy: today the existing floors above
are the only gates; when the REAL rows in `pir_outcomes.jsonl` reach the activation floor
(`cisco_toolkit/holdout.py :: ACTIVATION_FLOOR` owns the figure), a **sealed 70/30
optimisation/holdout split activates** — a one-time human-run
`python -m cisco_toolkit.holdout seal`, which **refuses** below the floor and counts REAL rows
only (same `source_class` discriminator as the D11 gate; a surrogate flood never activates it).
The contract was committed **before any REAL data exists** — pre-registration, so the split rule
cannot be fitted to the data.

The seal is a committed `holdout_manifest.json` on the `cisco_toolkit/manifest.py` hash chain: it
freezes the sealed policy terms + each holdout row's content **digest** (never a second copy of
the rows — the store stays the one owner). Holdout rows are read **only** via the logging
accessor, `python -m cisco_toolkit.holdout read --who <name> [--purpose "…"]`, which verifies the
seal against the store and appends one line per access attempt — success or integrity failure —
to the append-only, committed `holdout_access.jsonl`:

| field | meaning |
|---|---|
| `ts` | UTC ISO timestamp of the access attempt |
| `who` | declared identity (required — an unattributed read is refused) |
| `os_user` | best-effort OS account (declared ≠ proven, same residual as the scorecard's provenance pair) |
| `purpose` | free-text why, recorded verbatim (`null` if not given) |
| `manifest` / `chain_root` | which seal the read was against |
| `ok` | whether the seal verified against the store |
| `n_rows` | holdout rows returned (0 on an integrity failure) |

**Audit trail, not proof:** the rows are plaintext in a repo anyone with a checkout can read;
*mathematical proof of non-use does not exist and is not claimed* (the contract says so plainly).
What the mechanism gives is tamper-evidence (hash chain), attributable access (this log, reviewed
weekly alongside the gate-override log), and pre-registration. Discipline — refusal below the
floor, seal→tamper→verify-fails, access-logged, contract figures reconciled to their code owners —
is pinned by `tests/test_holdout.py`.

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

## `query_log.jsonl` — the real-query mix (P2-0a)

The raw material for D10's dense-lane decision ("classify 30 real queries by type FIRST" —
[`docs/d10-retrieval-eval-design-2026-07-08.md`](../d10-retrieval-eval-design-2026-07-08.md) §5): until
P2-0a no log of real queries existed anywhere, so that precondition was permanently unrunnable. One JSON
object per line, append-only, **gitignored / owner-machine only** (like the vault digest: a real query
may name client tokens from another engagement — the two-store rule — so the rows never enter the
pushable repo, and clean clones / CI checkouts carry none); exactly three fields, nothing else:

| field | type | meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | when the query was asked |
| `query` | string | the query text, verbatim |
| `surface` | string | which REAL surface asked it: `recall` (the `python -m cisco_toolkit.recall` CLI) or `ask` (the `/ask` command's mandatory `--log-only --surface=ask` first step) |

Written only by `cisco_toolkit.recall.log_query` at the real surfaces; the synthetic paths (`--eval`,
the labeled experiment, unit tests) deliberately never log, so the recorded mix stays real. **Fail-open:**
a logging failure degrades silently to nothing recorded — it must never break retrieval or an `/ask` turn.
Per-command opt-out: `CISCO_RECALL_NO_LOG=1` (records nothing, returns `False`). While the log is short,
the D10 classification simply stays unrunnable and says so — queries are never invented to fill it.
Never hand-edit. Owner row in [`docs/ssot.md`](../ssot.md); discipline pinned by `tests/test_query_log.py`.

## `d10-eval-set.jsonl` (+ anchors) — the frozen Phase-2 retrieval eval set (P2-1)

The committed, **frozen** eval set the D10 falsification run consumes
([`docs/d10-retrieval-eval-design-2026-07-08.md`](../d10-retrieval-eval-design-2026-07-08.md) §2–§4;
strata counts owned by [`d10-eval-thresholds.json`](d10-eval-thresholds.json) `query_set`). Three
files, each headed by a `{"_meta": …}` line; loaders/validators in
[`cisco_toolkit/d10_eval_set.py`](../../cisco_toolkit/d10_eval_set.py):

- **`d10-eval-set.jsonl`** — 60 query rows: `qid` / `stratum` / `query` / graded `qrels`
  (`{doc, grade 0–3, why}`; doc-ids are repo-relative paths, digest entries as `digest:<id>`) /
  `grounding`. The 20 **identifier** rows are *extracted, not authored* —
  `extract_identifier_queries` derives them from the owner-machine `graphify-out/graph.json`
  (unique code-node labels, cross-file reference in-degree, label tie-break; deterministic, so the
  committed rows reproduce from the recorded graph bytes). **Semantic** rows are synonym-stripped
  (no target-name tokens — owner doc §2) and include digest-lane rows (`requires_digest: true`,
  reported per corpus-config per DEC-006 A2, never pooled). **Multi-hop** rows declare the ≥ 2
  graph edges they require, verified against the live graph. **Negative** rows have empty qrels
  with the absence evidence cited.
- **`d10-anchors.jsonl`** — the judge-visible half of the 15-anchor screening set (5 clear-relevant
  / 5 clear-irrelevant / 5 borderline): `aid`/`query`/`doc` ONLY. Run FIRST every eval session; the
  P2-2 gate (κ ≥ 0.70 ∧ anchor accuracy ≥ 0.80, `validity_gate`) decides whether the judge may
  grade at all.
- **`d10-anchor-key.jsonl`** — the **SEALED** expected-grade bands + rationales. Sealed by
  *separation* (the [`defect_panel`](../../cisco_toolkit/defect_panel.py) pattern: scorer-only,
  never in a judge prompt) and by *tamper-evidence* (exact SHA-256 pins in
  `tests/test_d10_eval_set.py` — an edit must move file + pin together in a reviewed diff).
  Declared residual: the key is plaintext in the repo; the seal is separation + tamper-evidence +
  pre-registration, not secrecy (the holdout contract's honesty).

**Freeze discipline (owner doc §7):** all three fixtures are frozen at registration (2026-07-10).
P2-2 pool judging appends to a *separate* pooled-qrels file; a post-hoc edit to these files is a
protocol violation and the pins make it loud. Validate offline with
`python -m cisco_toolkit.d10_eval_set --verify` (graph-dependent checks skip off the owner machine,
saying so).

## `retrieval_eval` — the Phase-2 falsification harness (P2-2) + `d10-pooled-qrels.jsonl`

[`cisco_toolkit/retrieval_eval.py`](../../cisco_toolkit/retrieval_eval.py) runs the pre-registered
protocol over the frozen fixtures above: judge screening gate **first** (the 15 anchors through the
local-Ollama judge — dual-prompt neutral+adversarial, take-the-MIN, two passes; κ and anchor
accuracy scored against the **sealed** key, floors from `validity_gate`), then the two §7 configs —
**graph-only** vs **graph ⊕ BM25** (RRF k and the BM25 `k1`/`b` priors read from the frozen
`tuning_frozen` block, never hardcoded) — over the corpus of every git-tracked `*.py`/`*.md` ⊕ the
provenance-verified vault digest when present (recorded per DEC-006 A2; a digest-absent run
certifies the degraded graph+docs mode and says so). Scored with `pytrec_eval` (MRR@5 / P@1 on the
grade≥2 binarization, nDCG@5 graded) + direct Recall@10; decided by the pre-registered scipy
paired t + paired Cohen's dz from [`d10-eval-thresholds.json`](d10-eval-thresholds.json). Negative
rows are an over-retrieval diagnostic, never in the rank aggregates. `Hole@10` over its bar ⇒
INVALID, re-pool. Ollama unreachable / gate failed ⇒ the judged strata (semantic, multi-hop) are
INVALID, the identifier stratum still scores, and the run is **PARTIAL** — grades are never
fabricated. All Ollama I/O lives in the root-level subprocess helper
[`ollama_retrieval_judge.py`](../../ollama_retrieval_judge.py) (outside the no-egress fence).

- **`d10-pooled-qrels.jsonl`** — the *separate*, append-only pool-judgment file (§7 "re-pool"):
  one line per screened-judge grade (`qid`/`doc`/`grade`/`judge`/`date`/`source`). Authored fixture
  grades always take precedence on overlap; the frozen fixtures are never edited.
- **`d10-eval-results-<date>.md` (+ `.json`)** — the run record: environment per DEC-006 A2
  (digest lane, live `ollama --version`, judge model), gate outcome, the 2-config × 4-strata
  table, Hole@10 validity, and the §7 verdicts read from the thresholds file. The dense column
  stays **DEFERRED** until the real-query log clears the pre-registered 30-row floor.

CLI: `python -m cisco_toolkit.retrieval_eval --check | --gate | --run`. `--run` REFUSES when the
P2-1 fixtures are absent or fail validation — the harness never builds its own set. Hermetic guard:
`tests/test_retrieval_eval.py` (injected judge + graph lane; `[eval]`-extra tests importorskip).

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
