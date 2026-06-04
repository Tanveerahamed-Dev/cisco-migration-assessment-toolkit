# Chat Summary

Markdown-first session log for the hardening effort on
`COLLECT_PARSE_V3_23_0.py`. Newest entry first.

---

## 2026-06-04 — PHASE 2.7 step 2: parse primitives + neighbor parsers

On branch `phase2-split-parse`. Behaviour byte-identical.

- Created `cisco_toolkit/parse.py`; moved the column primitives
  (`extract_fixed_cols`, `slice_col`) and the pure routing-neighbor parsers
  (`parse_ospf_neighbors`, `parse_eigrp_neighbors`, `parse_bgp_summary`) into it.
  Depends only on `re` + `cisco_toolkit.textutils`; monolith imports them back.
- Verified: golden byte-identical, `ruff` clean, mypy unchanged (101); +1
  boundary/identity test in `tests/test_package.py`. **61 tests pass.**

Split progress: step 1 textutils (leaf), step 2 parse primitives + neighbor
parsers. **Remaining `parse_*` are entangled** with `build_interfaces` helpers
(`_load_cmd_output`, `_compress_vlans`, `_STP_STS_NAME`, `infer_endpoint_type`,
`_DESC_EP_PATTERNS`, …) so the next slices need care; then analyze / excel /
html / `__main__`. `.md` Change Log V3.23.12.

---

## 2026-06-04 — PHASE 2.7 step 1: begin the package split

On branch `phase2-split-textutils`. Behaviour byte-identical.

- Created the `cisco_toolkit/` package; extracted the pure leaf-level text /
  interface-name helpers + interface regex constants into
  `cisco_toolkit/textutils.py` (depends only on `re`). The monolith imports them
  back, so all references + the `import COLLECT_PARSE_V3_23_0` entrypoint/tests
  keep working unchanged.
- Dropped the unused `_JUNK_IFACE_TOKENS` import-back (F401); placed the import
  in the import block (E402). `ruff` stays clean.

Verified: golden **byte-identical**, mypy baseline unchanged (101), **60 tests
pass** (+2 in `tests/test_package.py`, incl. an `is`-identity check that the
monolith uses the package objects — guards against a future re-definition).
`.md` Change Log V3.23.11.

**Split strategy (safe, incremental):** one self-contained layer per PR, lowest
dependency first, golden verifying each step, monolith stays the entrypoint via
import-back. Done: textutils (leaf). Next layers: parse (the ~40 `parse_*` — but
they depend on more constants/helpers), then analyze / excel / html. Each is its
own PR; the bulk is best continued in a dedicated session.

---

## 2026-06-04 — PHASE 2.6: mypy baseline (report-only)

On branch `phase2-mypy`. Code-health hygiene; behaviour byte-identical.

- Added `mypy.ini` (lenient: `ignore_missing_imports`, py3.10 target, not gated)
  + `mypy` to `requirements-dev.txt`.
- `python -m mypy COLLECT_PARSE_V3_23_0.py` → **101 findings**. Inspected the
  categories (operator/var-annotated/attr-defined): they're dynamic-typing
  strictness — e.g. `float|str` values guarded at runtime by `!= ""` that mypy
  can't narrow, `dict[str, object]` access, untyped openpyxl — **not bugs**.
  Tracked as a report-only baseline for incremental typing, not rewritten
  wholesale (per "don't rewrite working code for style").
- Fixed the 2 clean `var-annotated` easy wins (`proto_high`, `nofhrp_vlans`).
  `compute_*` already have hints + docstrings, so nothing to add there.

`ruff check .` stays clean; **58 tests pass**, golden byte-identical. `.md`
Change Log V3.23.10. This effectively completes 2.6 (full strict typing of a
5.9k-line dynamic monolith is deliberately out of scope).

---

## 2026-06-04 — Lint easy-wins (ruff now clean)

On branch `lint-easy-wins`. Fixed the 5 pyflakes findings from the V3.23.8 ruff
baseline (behaviour byte-identical):

- **4× F402** (`field` import shadowed by loop vars in the sheet writers): aliased
  the import to `field as _dcfield` and updated ScoringConfig's 8 `field(...)`
  calls — the readable `field` loop variables stay as-is.
- **1× F841**: removed the write-only `ios_top` in `parse_show_interface_trunk_table`
  (IOS is the implicit `else`; NX-OS/IOS trunk tests + golden confirm unchanged).
- **1× E401** (multi-import line): intentional compact style → ignored in `ruff.toml`.

`python -m ruff check .` → **All checks passed**. **58 tests pass**, golden
byte-identical. `.md` Change Log V3.23.9.

---

## 2026-06-04 — Loose ends: P4 + M2 + ruff baseline

On branch `loose-ends`. Behaviour byte-identical (golden unchanged).

- **P4:** narrowed the global `warnings.filterwarnings("ignore")` to
  `category=DeprecationWarning` — real UserWarning/RuntimeWarning signals now
  surface. (Confirmed netmiko imports clean here, so low risk.)
- **M2:** single `__version__ = "3.23.0"` feeds the argparse description, snapshot
  `script_version` (still `"V3.23.0"` → golden-safe), and the log filename (fixed
  the stale `v3_14_6`).
- **ruff (report-only):** added `ruff.toml` (keep F + E4/E7/E9; ignore the
  intentional E701/E702/E741 one-liner/semicolon/ambiguous-name style). Baseline
  dropped **310 → 6** real findings: 4× F402 (import `field` shadowed by a loop
  var — a side-effect of the 2.1 `field` import; benign), 1× F841 (unused var),
  1× E401. Catalogued for a future targeted lint-fix PR; not fixed here. `ruff`
  added to `requirements-dev.txt`.

**58 tests pass** (+1 `tests/test_version.py`). This ties off the deferred audit
items. Remaining big-ticket (own sessions): 2.5 perf, 2.6 type-hints/mypy,
2.7 (gated) package split, PHASE 3 explorer redesign.

---

## 2026-06-04 — PHASE 2.4: "missing data != healthy" (audit C3)

On branch `phase2-data-quality`.

- Added `compute_data_quality(all_cmd_to_files)` — per-switch fraction of an
  essential command set (status / switchport / version / neighbors) that
  returned usable output (via `_load_cmd_output`).
- `compute_health_scores` gained an optional `data_quality=` arg + a
  `ScoringConfig.data_quality_threshold` (default 0.5): below it, the band is
  overridden to **`Insufficient Data`** and a `data_quality` % is recorded +
  shown in a new Health Scores column. So a partial/failed collection can't
  score a misleading Excellent.
- **Opt-in by construction:** the field/override appear only when `data_quality`
  is passed (main always does; direct callers without it stay byte-identical).

Verified: golden diff **additive-only** (data_quality key per record + sheet
column; fully-collected fixtures stay 1.0, bands unchanged). **57 tests pass**
(+5 in `tests/test_data_quality.py`). `.md` Change Log V3.23.7; in-code version
stays 3.23.0.

Remaining: 2.5 perf · 2.6 mypy/ruff + type hints · 2.7 (gated) package split ·
PHASE 3 explorer redesign.

---

## 2026-06-04 — PHASE 2.3: parser robustness (P1)

On branch `phase2-parser-robustness`.

- Added `_safe_parse(fn, *args)` and routed **every** section parser call in
  `build_interfaces` through it. A parser that *raises* on a malformed block now
  logs a breadcrumb and that section is skipped — the rest of the device still
  parses. Extends FIX-V14-1 from device-level to section-level; resolves the
  deferred audit item **P1**.
- Happy path unchanged (parsers return `{}` on empty input) → **golden
  byte-identical**.
- New tests: `tests/test_parser_robustness.py` (a raising parser, and several at
  once, no longer drop the device) and `tests/test_platform_variants.py` (NX-OS
  interface-status / port-channel / MAC / trunk forms). **52 tests pass.**

Documented a known gap: the NX-OS `show interface trunk` native-VLAN column under
its 2-line header still parses via the IOS branch (status + mode correct). That's
a cross-platform *correctness* gap (not a crash) — next parser target.

Remaining PHASE 2: 2.4 partial-collection / "missing≠healthy", 2.5 perf,
2.6 mypy/ruff + type hints, 2.7 (gated) package split; PHASE 3 explorer redesign.

---

## 2026-06-04 — PHASE 2.2: cry-wolf calibration & transparency

On branch `phase2-cry-wolf`. Three pieces, all under the golden net:

- **Findings dedup:** `compute_findings` now emits one weighted row per switch
  (count + port list) for err-disabled / STP-inconsistent, not one row per port.
  Findings-sheet rows only — snapshot + headers unchanged.
- **Asset-criticality weighting:** new `ScoringConfig.criticality_factors` +
  `_host_role` (SVI-hosting switch -> distribution, else access). Deductions are
  scaled via `round()`. Ships at **factor 1.0 for every role** (opt-in), so
  health scores are byte-identical until tuned — the sign-off choice.
- **Sensitivity sweep:** new `compute_score_sensitivity` + **Score Sensitivity**
  sheet + `snap_dict["score_sensitivity"]`. OAT ±25/±50% over each weight group,
  reporting how many switches change band (on the fixtures, "XL -50%" flips 2).

Verified: golden diff is **additive-only** (142 insertions, 0 deletions — new
sheet + key; existing `health_scores`/`migration_readiness` byte-identical).
**45 tests pass** (+6 in `tests/test_cry_wolf.py`). In-code version stays
`3.23.0`; `.md` Change Log V3.23.5. Next: PHASE 2.3 (parser robustness + the
deferred P1 + IOS/NX-OS fixture variants).

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
