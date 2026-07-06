# Quality scorecard — the feedback nerve (substrate)

This directory is the **persisted quality trend** for the "provably improves over time" half of the
Deliverable Excellence Standard. It is the substrate for Phase 1 of
[`docs/autonomous-brain-plan-2026-07-06.md`](../autonomous-brain-plan-2026-07-06.md): today it is a
schema + an empty log; the appender is wired next.

## `scorecard.jsonl` — one JSON object per line, append-only

Every consequential QA / eval cycle appends one row. **Verifiable facts only — never a self-assessment**
(the coasting trap: an agent that records "great progress" reads it back and stops trying).

| field | type | meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | when the verdict was produced |
| `deliverable` | string | which artifact (e.g. `design`, `mop`, `crd`, `hld`, or a snapshot id) |
| `score` | number \| null | eval-suite score (0–100) once the golden-snapshot harness exists; `null` until then |
| `verdict` | string | `APPROVE` / `BLOCK` (from deliverable-qa-reviewer) |
| `counterexamples` | int | number of grounded defects the verifier found this cycle (should trend ↓) |
| `laws_tripped` | array | which of the 10 Deliverable-Excellence Laws failed, if any |
| `commit` | string | git SHA the verdict was produced against |
| `notes` | string | short, factual — the counterexample, not an opinion |

Example (illustrative — do not hand-edit real data in):

```json
{"date":"2026-07-06","deliverable":"design","score":null,"verdict":"BLOCK","counterexamples":2,"laws_tripped":["L3"],"commit":"4bedd9f","notes":"ops Security axis rendered 'complete' with no not-assessable branch"}
```

## How rows get here (Phase 1, not yet wired)

- A `SubagentStop` / `SessionEnd` hook captures each `/qa` verdict and appends a row (removes the manual step).
- The **golden-snapshot eval suite** (pytest tier) appends a scored row on each merge/release.
- `/briefing` (Phase 0, live now) reads the tail of this file and renders the trend in the morning digest.

**Coverage-honest note:** while this file is empty, the briefing says so plainly ("no entries yet"). Absence
is reported as absence — it is never rendered as "healthy" (Law 3).
