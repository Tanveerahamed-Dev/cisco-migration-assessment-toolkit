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

## `learnings.md` — the distilled, verifiable engine facts (sibling substrate)

The other half of the feedback nerve: [`learnings.md`](learnings.md) is the distilled store of durable,
**verifiable** facts about the codebase/engine, surfaced at SessionStart (via `.claude/hooks/session-brief.sh`)
so the lessons shape every session. Discipline — **under 100 lines · every entry cited · verifiable facts only,
never a self-assessment** — is enforced by [`cisco_toolkit/learnings.py`](../../cisco_toolkit/learnings.py) +
`tests/test_learnings.py` (the coasting trap: a store that records "great progress" and reads it back stops
trying). It is distinct from `docs/log.md` (the raw `/retro` source) and the career/domain vault.
