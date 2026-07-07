# Learnings — the distilled, verifiable engine facts (read at SessionStart)

The feedback nerve's distilled store: durable, **verifiable** facts about this codebase/engine that
should shape every session. Discipline (enforced by `cisco_toolkit/learnings.py` +
`tests/test_learnings.py`): **under 100 lines · every entry cited · verifiable facts only, never a
self-assessment** (a store that records "great progress" and reads it back is the coasting trap).

This is NOT the raw session log (`docs/log.md`, the `/retro` source) nor the career/domain vault
(promoted via `/ingest`). It is the repo/engine facts worth remembering. To add one: state a
falsifiable fact and cite where it is checkable (a file, a test, or a commit).

## Engine / SSOT

- `ssot.reconcile(snap)` returns `[]` both when facts are clean AND when none are published — a
  non-vacuous "clean" gate must also require `ssot.summary(snap)["n_facts"] > 0`. Evidence:
  `cisco_toolkit/eval_harness.py::_check_reconcile`.
- `analyze.vlan_inventory` unions three evidence sources (access-port `.vlan`, `l3_forwarding[].vlan`,
  IGMP queriers), so a fixture publishing `n_vlans=N` must supply N distinct VLANs to reconcile.
  Evidence: `cisco_toolkit/analyze.py:1573`.
- Older-but-good snapshots predate `attestation`/`schema_census`; a coverage-honest check treats an
  absent signal as UNVERIFIED, never a fail. Evidence: `cisco_toolkit/eval_harness.py::_check_provenance`.

## Fixtures / goldens

- The frozen `tests/golden/snapshot.json` is stripped of `executive_brief`/`lifecycle_risk`/
  `design_blueprint` (date-relative) → it has 0 canonical facts, so it is NOT a Law-scoring fixture;
  build a synthetic fully-published one. Evidence: `tests/test_eval_harness.py` (`known_good_snapshot`).
- Adding any `cisco_toolkit/*.py` module changes the attestation's re-derived module count, so the
  pipeline golden must be re-blessed (`UPDATE_GOLDEN=1`); it is additive and the no-egress claim still
  HOLDS. Evidence: `tests/test_pipeline_golden.py`.
- The real assessment snapshot (`Migration_Assessment_*.snapshot.json`) is untracked / absent from git
  → not a reliable committed fixture; score it opportunistically and SKIP when absent (coverage-honest).
  Evidence: `tests/test_eval_harness.py::test_real_on_disk_snapshot_scores_clean_if_present`.

## Tooling / workflow

- Piping pytest through `| tail` masks its exit code (the pipe returns tail's 0), hiding real failures;
  run `python -m pytest` unpiped or capture `$?` before any pipe. Evidence: `.claude/hooks/verify-green.sh`
  (the Stop gate runs pytest unpiped for exactly this reason).
- Memory consolidation deletes "superseded" facts on a schedule, so a rarely-referenced safety
  constraint survives only via the protected tier marker `protected: true`. Evidence:
  `cisco_toolkit/memory_guard.py` (D12) + `.claude/scheduled-tasks/monthly-memory-consolidation/SKILL.md`.
- A transcript-scraping hook keyed on keywords fires on the MAIN agent's own prose that *describes* a
  verdict (a summary with "verdict"/"BLOCK" + a markdown table once fabricated a scorecard row); gate
  on the reviewer's structural signature — a per-artifact `X — BLOCK` line — not keyword co-occurrence.
  Evidence: `cisco_toolkit/scorecard.py` (`_ARTIFACT_VERDICT_RE`) + `tests/test_scorecard.py`.
