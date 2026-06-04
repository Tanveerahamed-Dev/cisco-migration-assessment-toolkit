# Chat Summary

Markdown-first session log for the hardening effort on
`COLLECT_PARSE_V3_23_0.py`. Newest entry first.

---

## 2026-06-04 — PHASE 2.1: externalize scoring tunables

On branch `phase2-externalize-scoring` (PR #2 already merged to main).

- Added a frozen **`ScoringConfig`** dataclass + module default `SCORING`: the
  health-score weights (L1/L3/cross-layer/protocol), per-category caps, the
  score bands, and the 10 readiness pass/warn/fail rules — all formerly
  function-local dicts. `compute_health_scores` and `compute_migration_readiness`
  gained an optional `config=SCORING` param; existing call sites unchanged.
- Defaults reproduce prior behaviour **byte-for-byte** (golden green). 5 new
  tests in `tests/test_scoring_config.py` prove the wiring (a custom config
  changes the output) and that defaults match the baseline.
- The new tests caught a real gap: the band was derived from the module-default
  `_HEALTH_BANDS`, not the passed `config.bands` — fixed.
- **39 tests pass.** In-code version stays `3.23.0`; `.md` Change Log V3.23.4.

This is the prerequisite for **PHASE 2.2** (cry-wolf dedup + asset-criticality
weighting + a one-at-a-time sensitivity sweep) — the tunables are now
addressable in one place.

---

## 2026-06-04 — Protective fixes C1 + C2 (first production-code changes)

On branch `harden-phase1-tests`, now under the golden net.

- **C1 (High, resilience):** added `_run_phase()` + `_empty_dep_map()` and routed
  every pre-save phase (interface rows + the ~20 analysis/sheet writers, Phases
  6–29) through the guard. A single writer/compute failure now logs and the run
  continues to `wb.save()` instead of losing the entire run's output. A failed
  dependency map falls back to an empty skeleton so Phases 28–29 still produce.
- **C2 (High, collection):** `send_cmd` prefers pattern-based `send_command`
  (waits for the prompt) over `send_command_timing` (silent-truncation risk),
  with timing-based fallback then `""`.
- Added runtime `requirements.txt`; 7 new tests in `tests/test_resilience.py`.

Verified: **34 tests pass**; the golden snapshot + Excel schema are byte-identical
(C1 is happy-path-neutral; C2 is exercised by fake-device unit tests since the
offline pipeline doesn't hit the SSH path).

Deferred (next): **P1** folded into PHASE 2.3 (per-section parser guards land
with the parser-robustness work + IOS/NX-OS fixture variants — C1 already
prevents total run loss, and `parse_one` already isolates a bad device).
**P4** (scope the global `warnings` filter) deferred until I can observe what
netmiko/paramiko actually emit. **M2** (single `__version__`) is cosmetic, later.

---

## 2026-06-04 — PHASE 0 audit + PHASE 1 test safety net

**PHASE 0 (audit, no code changes).** Produced a prioritized findings report
across correctness, parser fragility, risk-score calibration, performance,
partial-failure resilience, and maintainability. Highest-signal items:

- **C1/Res2 (High):** the 24 pre-save sheet writers (`main` Phases 6–29) are
  unguarded — one writer throwing aborts the run *before* `wb.save()`.
- **P1 (High):** `build_interfaces` calls ~12 parsers with no per-section guard;
  one parser exception drops the entire device's interfaces.
- **C2 (High):** `send_cmd` uses `send_command_timing` for every command
  (truncation risk on slow/large output).
- **R1/R2/R3 (Med):** scoring tunables are function-local dicts (not config),
  no asset-criticality weighting, and `compute_findings` emits one row per port
  (the "sea of red"). Per-category caps already exist (good).
- **P3 (High):** zero tests — addressed by PHASE 1 below.

Agreed plan: PHASE 1 → cheap protective fixes (C1/P1/P4/C2/M2/M3) → PHASE 2 in
order. Fixtures: synthetic (no real collection dir exists in the repo).

**PHASE 1 (test safety net — this commit).** No change to
`COLLECT_PARSE_V3_23_0.py` (behavior-preserving by construction).

- Added `tests/synthetic_fixtures.py`: hand-authored IOS + NX-OS `show` output
  for 3 switches (core1/core2/access1) exercising trunks, a healthy 2-member
  port-channel, HSRP-redundant SVIs, a sole-gateway VLAN with no FHRP, a single
  fiber uplink, an err-disabled port, and a down OSPF neighbor.
- Added a **golden end-to-end regression** (`tests/test_pipeline_golden.py`):
  runs the real `--no-collect` pipeline (`--workers 1` for determinism) and
  asserts the normalized `snapshot.json` (the HTML contract) and the Excel
  sheet-name/header schema against frozen goldens in `tests/golden/`. Volatile
  `generated_at` is stripped. Regenerate intentionally with
  `UPDATE_GOLDEN=1 python -m pytest tests/test_pipeline_golden.py`.
- Added focused **unit tests**: parsers (`tests/test_parsers.py`, 12) and the
  intelligence layer (`tests/test_compute.py`, 13) — `compute_move_groups`,
  `compute_cross_layer_correlations`, `compute_health_scores`,
  `compute_migration_readiness`, `compute_protocol_health`. Includes a cap test
  and an explicit band-spread (anti-"cry-wolf") assertion.
- Tooling: `conftest.py`, `pytest.ini`, `requirements-dev.txt`.

Result: **27 passing**, deterministic across runs. The synthetic fleet shows a
real band spread — core1 **27/Critical**, access1 **72/Fair**, core2
**100/Excellent** — confirming the scorer discriminates rather than flagging
everything Critical.

Versioning note: following the repo's V3.23.1 precedent, the in-code version
strings (`snapshot_state`, argparse) stay at `3.23.0`; the moving record is the
`.md` Change Log (new **V3.23.2** row). The script itself is untouched this
phase.
