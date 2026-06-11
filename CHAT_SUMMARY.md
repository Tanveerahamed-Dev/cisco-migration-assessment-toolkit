# Chat Summary

Markdown-first session log for the hardening effort on
`COLLECT_PARSE_V3_23_0.py`. Newest entry first.

---

## 2026-06-11 — V3.23.174: the register reaches runbook / deck / AssessHub (arc complete)

On branch `feat/register-docs-webapp` (after #255 merged). One compute → all seven surfaces.

- Runbook §10.1 ranked asset table + compound bullets; deck slide 3b "The assets that worry an
  engineer most" (data-gated; 7/6/8-slide pins all hold); AssessHub Risk-Register panel + section
  tab (shared RegisterTable, SevChip gains optional label).
- Sample fleet regenerated through the real pipeline (23 devices → 7 Severe / 9 Elevated, 22 CRs).
- Visual QA: LibreOffice renders of the deck slide + §10.1 eyeballed; AssessHub verified live.
- 384 engine + 26 webapp tests; ruff clean; frontend build green.

---

## 2026-06-11 — V3.23.173: the register reaches the explorer (visual flagship)

On branch `feat/explorer-risk-register` (after #254 merged). Pure-JS; no engine/golden change.

- Health view: `riskRegisterCard()` leaderboard above the punch-list — ranked rows with band pills,
  risk-index bars, impact × exposure stats, CR-xx chips (hover = basis), inline verdicts for the top 3.
- Switch drawer: `deviceIntelSection` leads with the engine's "Engineer's verdict" card from
  `SNAP.device_dossiers` — rendered, never re-derived.
- Demo seeds a 6-asset register (incl. the CR-05 band-floor case and a not-assessed device).
- Verified live in the preview: both surfaces render, click-to-jump works, 0 console errors; 382 tests.

---

## 2026-06-11 — V3.23.172: the Device Risk Register (per-asset compound-risk synthesis)

On branch `feat/asset-risk-register`. The "automated senior engineer" centerpiece: every existing axis
slices the fleet by topic; this adds the per-ASSET slice — one dossier per box, ranked by stacked risk.

- `analyze.compute_device_dossiers(...)`: joins the 11 per-device axes per asset; `risk_index =
  topology impact (1–10) × stacked exposure (0–10)` (the Cyber Vision / CX-Cloud likelihood×impact
  model); compound patterns CR-01..CR-06 with a Critical-compound band floor; deterministic
  one-sentence engineer's verdict; `na` axes never count (absence of evidence ≠ health).
- Surfaces: snapshot `device_dossiers` + 'Device Risk Register' sheet (ranked + compound detail) +
  punch-list fold (category `Compound risk`) + brief axis 'Asset risk register'.
- Golden: dossiers stripped like `lifecycle_risk` (date-relative bands); punch-list fold frozen-stable
  (band-agnostic CR wording, audited against the fixture's future band transitions).
- 382 engine tests (+8) green; ruff clean; gated-mypy modules clean.

---

## 2026-06-05 — Redaction feature: opt-in `--redact` (sanitized shareable deliverable)

On branch `redact-snapshot`. Opt-in Python feature; default OFF so the golden + normal runs are byte-unchanged.

- New `cisco_toolkit.html.redact_snapshot(snap)` — recursive walk of the snapshot dict; regex-replaces every
  IPv4 (subnet-preserving: remap the /24, keep the host octet) + every MAC (consistent fake `02:..`) in all
  string values, and maps the serial fields (serial_number / chassis_serial / current|neighbor_switch_serial)
  to `SN####`. CONSISTENT (same input → same output) so ARP / dual-homing / subnet+flow-trace survive; hostnames
  kept. Pure (stdlib `re`), input not mutated. Lives in the html/reporting layer.
- `main()`: new `--redact` argparse flag; when set, `snap_dict = redact_snapshot(snap_dict)` AFTER all the
  augmentations (health_scores etc.) and BEFORE write_json_file + write_html_explorer, so BOTH the `.json` and
  the embedded HTML are redacted. Imported back via the existing `from cisco_toolkit.html import …` line.
- **Why regex-over-everything + field-based serials:** IPs/MACs appear both in dedicated fields AND embedded in
  free text (e.g. `hsrp_behavior` "… vIP 10.0.10.1"), so a recursive regex pass is more robust than
  field-by-field; serials have no regex, so they're mapped by key. The 4-octet IP regex won't false-match
  3-part version strings.
- **Verified end-to-end** (golden harness + `--redact`): rc 0; real `10.0.10.x` → `10.0.0.x` (subnet remapped,
  host kept); **no golden IP leaked**; device serials → SN0001/0002/0003; `[redact]` logged. Unit test covers
  consistency + subnet-preservation + embedded-IP + no-mutation. `ruff` clean, mypy 101, **68 tests**. `.md` V3.23.41.

This was the last optional item the user picked after PHASE 2.7 (package split) + PHASE 3 (explorer
a11y / robustness / Health) were complete.

---

## 2026-06-05 — PHASE 2.7 step 30: snapshot_state + write_html_explorer -> html.py (HTML LAYER COMPLETE)

On branch `phase2-split-html2`. Byte-identical. Monolith **~1,290 lines**; `cisco_toolkit/html.py` **~191 = the whole html layer**.

- Moved `snapshot_state` (the JSON snapshot contract — embedded in the HTML, written beside every workbook, and the
  golden's compared artifact) + `write_html_explorer` (bakes the snapshot into a copy of the Blast-Radius Explorer
  template) → html.py (verbatim move script). Both imported back for main(). html.py gained
  `json`/`logging`/`os`/`datetime`/`typing` + `__version__`/model imports + a module logger.
- **Coupling (a) — `__version__`:** snapshot_state embeds `f"V{__version__}"`, and `test_version` checks BOTH
  `cp.snapshot_state({},[])` AND `cp.__version__`. Hoisted `__version__="3.23.0"` from the monolith into
  `cisco_toolkit/__init__.py` (package root, no submodule imports → no cycle), imported it back into the monolith
  (`from cisco_toolkit import __version__`, placed in the top import block to avoid E402) so LOG_FILE / argparse /
  `cp.__version__` survive; html.py imports it too. `cp.__version__` stays "3.23.0".
- **Coupling (b) — template `__file__`:** write_html_explorer found `blast_radius_explorer.html` via
  `dirname(abspath(__file__))` = the monolith's dir = repo root. In html.py `__file__` is `cisco_toolkit/html.py`,
  so the move script rewrote it to `dirname(dirname(abspath(__file__)))` (html.py's grandparent = repo root) + fixed
  the docstring. Same template, byte-identical. (Golden doesn't compare the .html, but the regression was real.)
- **No monolith F401** — `datetime` / `json` / `os` are all used by collect / build_run_manifest / main /
  load_devices, so they stay; the only import change was the `__version__` relocation.
- Extended `test_html_reexported_and_functional` (added snapshot_state / write_html_explorer re-exports +
  `cp.__version__ == cisco_toolkit.__version__ == "3.23.0"` + a snapshot_state smoke). **67 tests.** test_version
  unchanged + green.
- **GOTCHA:** snapshot_state's signature uses `Dict`/`List` (typing) — easy to miss when moving (the lowercase
  `dict` hints on the other html fns don't need it). `py_compile` does NOT catch a missing annotation import (it
  compiles, doesn't execute the `def`); `import cisco_toolkit.html` does (NameError). Always
  `python -c "import <moved-module>"` after a move, not just py_compile.
- Golden **byte-identical**, ruff clean, mypy 101. `.md` V3.23.40.

**Remaining PHASE 2.7 (~1 PR): `__main__`** = what's left in the monolith (setup_logging / debug_scan_headers /
autodetect_platform / detect_platform_from_files / _is_auth_error / connect_device / send_cmd / collect /
load_devices / write_json_file / file_sha256 / build_run_manifest / main / argparse / `_run_phase` /
`_empty_dep_map` + the COMMANDS_* lists + CONFIG constants). Decide: keep `COLLECT_PARSE_V3_23_0.py` AS the thin
entrypoint (it already imports the whole package back), OR thin it into `cisco_toolkit/__main__.py` + a tiny shim.
The monolith is now ~1,290 lines = essentially just the collection/SSH/orchestration entrypoint + import-backs.
PHASE 3 explorer redesign — not started.

---

## 2026-06-05 — PHASE 2.7 step 29: stand up html.py with the diff workbook

On branch `phase2-split-html1`. Byte-identical. Monolith **~1,344 lines**; new `cisco_toolkit/html.py` **~122 lines**.

- New layer `cisco_toolkit/html.py` (the "snapshot-reporting" layer — renders outputs from the pre/post-cutover
  snapshots). Step 29 seeds it with the PURE slice: `write_diff_workbook` (the `--compare OLD NEW` diff workbook
  — Summary / Interface / Endpoint / SVI changes) + `_macset` + `_DIFF_FIELDS`. Depends only on openpyxl + stdlib
  `re`; no cisco_toolkit imports (leaf-ish). Moved via the verbatim CRLF-preserving script. `write_diff_workbook`
  imported back for main()'s --compare path; `_macset` / `_DIFF_FIELDS` package-internal.
- F401: dropped `Font` / `PatternFill` / `Alignment` (openpyxl.styles) + `get_column_letter` (openpyxl.utils) from
  the monolith's hoisted openpyxl import — write_diff_workbook was their last user. `load_workbook` STAYS (main()
  opens the template workbook). No other cascade; `re` still used widely.
- Added `test_html_reexported_and_functional` (identity + a real smoke: write a 2-snapshot diff xlsx to tmp_path,
  reopen, assert the 4 sheets + a "status: connected -> notconnect" Modified row). **67 tests.**
- **DELIBERATELY DEFERRED `snapshot_state` + `write_html_explorer` to step 30** — they carry two entrypoint
  couplings that deserve a focused byte-identical PR: (a) `snapshot_state` embeds `f"V{__version__}"` (a monolith
  global, tested by `test_version` via `cp.snapshot_state` + `cp.__version__`) → plan: move `__version__` into
  `cisco_toolkit/__init__.py`, import it back (keeps `cp.__version__` == "3.23.0"); (b) `write_html_explorer` finds
  `blast_radius_explorer.html` via `os.path.dirname(os.path.abspath(__file__))` (the monolith's dir = repo root) →
  once in html.py, `__file__` is `cisco_toolkit/html.py`, so use `dirname(dirname(__file__))` (html.py's grandparent
  = repo root) for the same template. Golden does NOT check the .html, but the regression is real.
- Golden **byte-identical**, ruff clean, mypy 101. `.md` V3.23.39.

**Remaining PHASE 2.7 (~2 PRs): (1) next = step 30 = `snapshot_state` + `write_html_explorer` → html.py** (the
`__version__` package-ization + the `__file__`→`dirname(dirname())` template fix; `test_version` calls
`cp.snapshot_state` so re-export it + keep `cp.__version__`). **(2) then `__main__`** = what's left (setup_logging /
debug_scan_headers / autodetect_platform / detect_platform_from_files / connect_device / send_cmd / collect /
load_devices / write_json_file / file_sha256 / build_run_manifest / main / argparse / `_run_phase` /
`_empty_dep_map` + the COMMANDS_* lists) — keep as the thin entrypoint or thin into the package. Sequential.

---

## 2026-06-05 — PHASE 2.7 step 28: build_interfaces -> build.py (BUILD LAYER COMPLETE)

On branch `phase2-split-build2`. Byte-identical. Monolith **~1,451 lines**; `cisco_toolkit/build.py` **~444 = the whole build layer**.

- Moved the ~300-line per-device `InterfaceData` builder `build_interfaces` (deferred from step 27) → build.py
  via a verbatim move script (CRLF-preserving, boundary-asserted — too big to hand-transcribe safely). build.py
  gained `import re` + `_safe_parse` (cmdio) + ~22 parsers (parse) + `detect_link_type` (textutils). Imported
  back for main() (calls it @ ~1740) + conftest's `built` fixture (`cp.build_interfaces`).
- **MILESTONE: the monolith no longer imports cisco_toolkit.parse at ALL** — build_interfaces was the last
  parser consumer. Removed the whole `from cisco_toolkit.parse import (…)` (23 parsers). The F401 cascade also
  emptied cmdio down to `_CISCO_ERRORS` (dropped `_load_cmd_output` / `_safe_parse`), textutils down to
  `safe_fs_name` (dropped `normalize_ifname` / `detect_link_type` — build_interfaces was their last monolith
  user too), and `Optional` (typing). ruff caught all of it across two passes.
- **Biggest test cascade of the split:**
  - `test_parsers` (already imported `parse`): `cp.parse_*` → `parse.parse_*` (replace_all).
  - `test_platform_variants`: added `from cisco_toolkit import parse`, same repoint.
  - `test_parser_robustness`: the robustness tests monkeypatch a *failing* parser then call build_interfaces.
    Since build_interfaces now resolves parser names in **build.py's** namespace (and `cp` no longer has them),
    the patch target moved `cp` → `cisco_toolkit.build` (else `monkeypatch.setattr` raises AttributeError);
    `_safe_parse` now from cmdio. **LESSON: `from X import name` binds into the importer's namespace — to patch
    a function a moved consumer calls, patch it on the CONSUMER's module (build), not the monolith and not parse.**
  - `test_package`: updated 5 stale identity assertions (normalize_ifname / detect_link_type /
    parse_show_interface_status / _load_cmd_output+_safe_parse / parse_run_config_interfaces → all
    package-internal) and flipped step-27's `not hasattr(build, "build_interfaces")` guard to
    `cp.build_interfaces is build.build_interfaces`.
- **66 tests**, golden **byte-identical**, ruff clean, mypy 101. `.md` V3.23.38.

**Remaining PHASE 2.7 (~2 PRs): (1) next = html** (`snapshot_state` [the golden's JSON contract — care],
`write_html_explorer`, `write_diff_workbook`, `write_topology_diagram`, `_mermaid_id`, `_macset`, maybe
`write_json_file` / `file_sha256` / `build_run_manifest`) → `cisco_toolkit/html.py`. **(2) then `__main__`** =
what's left (setup_logging / debug_scan_headers / autodetect_platform / detect_platform_from_files /
connect_device / send_cmd / collect / load_devices / main / argparse / `_run_phase` / `_empty_dep_map` + the
COMMANDS_* lists) — keep as the thin entrypoint or thin into the package. Sequential — `/batch` does NOT fit.

---

## 2026-06-05 — PHASE 2.7 step 27: model-construction layer -> build.py

On branch `phase2-split-build1`. Byte-identical. Monolith **~1,745 lines**; new `cisco_toolkit/build.py` **~155 lines**.

- New layer `cisco_toolkit/build.py` (depends on cmdio + parse + model + textutils; sits above those,
  independent of analyze/excel). Moved the 5 model-construction / enrichment functions:
  `build_device_physical`, `build_switch_identity` (build `DevicePhysical` / switch-identity records from
  collected `show` output) + `collect_global_arp`, `apply_global_arp`, `detect_cross_device_dual_connections`
  (network-wide ARP enrichment + dual-homing pass). All 5 imported back for `main()`.
- **Deferred `build_interfaces`** (the ~300-line per-device `InterfaceData` builder — the monolith's biggest
  function, pulls MANY parsers) to its OWN next step. Keeps this PR reviewable + golden byte-exact, same
  discipline as the parser/analyze layers split across many PRs. It stays in the monolith; `test_package`
  asserts `not hasattr(build, "build_interfaces")` as a guard (flips next step).
- F401 cascade (smaller than a full step-27 would be, because build_interfaces stayed): dropped 8 parsers only
  the moved builders used (`parse_show_version` / `_inventory` / `_environment_power` / `_environment` /
  `_module_count` / `parse_vtp_status` / `parse_switch_mgmt_ip` / `parse_show_ip_arp`) + `Tuple` (typing) +
  `PHYSICAL_IFACE_RE` (textutils) from the monolith re-imports. `parse_run_config_interfaces` STAYS
  (build_interfaces uses it @926).
- Two-part cascade as usual: ruff caught the unused imports → fixed; the `PHYSICAL_IFACE_RE` drop made the
  step-17 identity assertion stale → repointed to `not hasattr(cp, "PHYSICAL_IFACE_RE")`. **No other-file test
  repoints** — grepped `tests/` for all 13 symbols, none referenced via `cp.` (the 5 funcs are orchestration,
  covered by the golden pipeline only).
- **66 tests** (added `test_build_reexported_and_functional`), golden **byte-identical**, ruff clean, mypy 101. `.md` V3.23.37.

**Remaining PHASE 2.7 (~3 PRs): (1) next = `build_interfaces` -> build.py** (the big one; pulls a large parser
set → bigger F401 cascade + `test_parsers` / `test_parser_robustness` / `test_platform_variants` repoints).
**(2) then html** (`snapshot_state` [the golden's JSON contract — care], `write_html_explorer`,
`write_diff_workbook`, `_macset`...) → `cisco_toolkit/html.py`. **(3) then `__main__`** = what's left
(autodetect_platform / connect_device / send_cmd / collect / load_devices / main / argparse / `_run_phase` /
`_empty_dep_map` / debug_scan_headers) — keep as the thin entrypoint or thin into the package. Sequential —
`/batch` does NOT fit.

---

## 2026-06-05 — PHASE 2.7 step 26: append_interface_rows -> excel (EXCEL LAYER COMPLETE)

On branch `phase2-split-excel7`. Byte-identical. Monolith **~1,865 lines**; excel.py **~1,203 = the whole excel layer**.

- Moved `append_interface_rows` (the main 'Migration Assessment' interface-sheet filler — the
  LAST sheet writer) → excel.py. excel.py gained `MergedCell` (openpyxl.cell.cell) +
  `PHYSICAL_IFACE_RE`/`_TRUNK_STATUS_WORDS` (textutils). Imported back for main() (it calls it per device).
- This is the GOLDEN's interface sheet, so byte-exactness mattered most — golden stayed byte-identical.
- F401: dropped the monolith's `MergedCell` import + `_TRUNK_STATUS_WORDS` (textutils) + `sortkey` (excel)
  re-imports (append_interface_rows was their last monolith user; `PHYSICAL_IFACE_RE` survives — still used
  at ~800/global_arp). Updated the step-20 sortkey identity assertion + added append_interface_rows identity.
  **65 tests**, golden byte-identical, ruff clean, mypy 101. `.md` V3.23.36.

**WORKFLOW NOTE:** this turn the user said "continue" while PR #34 (step 25) was still OPEN — I caught that
main was at #33 (step-24) and PAUSED rather than branch step 26 off stale main (would conflict with #34 on
merge). Asked them to merge #34; they did, then said continue, and I proceeded off the now-merged step-25 main.
**Always verify `gh pr view <prev> --json state` == MERGED + `git log origin/main` before branching the next step.**

**Remaining PHASE 2.7 (~3 PRs): (1) step 27 = the build_* model layer** (`build_device_physical`/
`build_interfaces`[~300 lines]/`build_switch_identity` + `collect_global_arp`/`apply_global_arp`/
`detect_cross_device_dual_connections`) — construct InterfaceData/DevicePhysical from parsed output; pull MANY
parsers → **big F401 cascade + test_parsers/test_parser_robustness/test_platform_variants repoints**. These
aren't excel → **new `cisco_toolkit/build.py`**. **(2) step 28 = html** (`snapshot_state` [the golden's JSON
contract — care], `write_html_explorer`, `write_diff_workbook`, `_macset`, `write_json_file`/`file_sha256`/
`build_run_manifest`?) → `cisco_toolkit/html.py`. **(3) Then `__main__`** = what's left (autodetect_platform/
connect_device/send_cmd/collect/load_devices/main/argparse/_run_phase/_empty_dep_map/debug_scan_headers) —
keep as the thin entrypoint or thin into the package. Sequential — `/batch` does NOT fit.

---

## 2026-06-05 — PHASE 2.7 step 25: fused compute-in-writer sheets -> excel

On branch `phase2-split-excel6`. Byte-identical. Monolith **~1,945 lines (under 2k!)**; excel.py ~1,107.

- Moved the 3 "fused" writers → excel.py: `write_physical_health_sheet` (big) + `write_l3_forwarding_sheet`
  (each computes L1/L3 records inline + RETURNS them; main() captures via `_run_phase`) +
  `write_flow_trace_sheet` (renders a trace_full_flow dict). `_parse_track`/`_track_summary` moved with
  the L3 writer (package-internal). excel.py now imports build_network_model/_physical_uplink_index/
  _poe_device_util (analyze) + the physical/FHRP parsers (parse) + normalize_speed (textutils).
- **11-symbol F401 cascade** (the biggest): normalize_speed, 6 parse parsers (parse_show_interface_counters/
  _parse_fhrp/_is_physical_port/_classify_media/parse_interface_phy/_parse_poe_watts), 3 analyze
  (build_network_model/_poe_device_util/_physical_uplink_index), and **`_SEV_FILL`** (its last monolith
  writers — physical/l3 — moved) all dropped from the monolith re-imports. Repointed test_parsers
  (parse_show_interface_counters) + 5 test_package identity assertions to not-hasattr.
- **ALL sheet writers now live in cisco_toolkit/excel.py except `append_interface_rows`.** 65 tests,
  golden byte-identical, ruff clean, mypy 101. `.md` V3.23.35.

**Remaining: (e) step 26 = `append_interface_rows` + the build_* layer + collection glue.** In the
monolith now: `append_interface_rows` (fills the main interface template sheet — uses find_header_row/
ensure_headers/sortkey [excel] + InterfaceData; the GOLDEN's interface sheet comes from this — extra care),
`build_device_physical`/`build_interfaces`/`build_switch_identity` (construct the model from parsed
output — pull MANY parsers → expect another big F401 cascade + test_parsers repoint; build_interfaces is
huge ~300 lines), `collect_global_arp`/`apply_global_arp`/`detect_cross_device_dual_connections`,
`debug_scan_headers`, `_empty_dep_map`/`_run_phase`, `load_devices`/`write_json_file`/`file_sha256`/
`build_run_manifest`. PLUS html (snapshot_state/write_html_explorer/write_diff_workbook/`_macset`) and
`__main__` (autodetect_platform/connect_device/send_cmd/collect/main/argparse). **Decide next: does
append_interface_rows + build_* go to excel.py, or a new `build`/`collect` module?** build_* construct the
model (not excel) — maybe a `cisco_toolkit/build.py`. append_interface_rows is excel (writes the sheet).
Likely: step 26 = append_interface_rows → excel; step 27 = build_* → new build.py; then html → html.py;
then __main__ stays as the thin entrypoint. Sequential — `/batch` does NOT fit.

---

## 2026-06-05 — PHASE 2.7 step 24: Tier-2 + intelligence writers -> excel

On branch `phase2-split-excel5`. Byte-identical. Monolith **~2,197 lines**; excel.py ~915.

- Moved 5 contiguous writers (monolith 1697-1921) → excel.py: file-reading trio
  `write_interface_health_sheet`/`write_security_posture_sheet`/`write_routing_adjacency_sheet`
  (read `_load_cmd_output` + call parse parsers) + `write_causality_chains_sheet`/
  `write_failure_impact_sheet` (call compute_causality_chains/compute_failure_impact). excel.py
  now imports `from cisco_toolkit.cmdio import _load_cmd_output`, 7 parsers from parse, and
  +compute_causality_chains/compute_failure_impact from analyze.
- **Largest F401 cascade yet (10 drops):** routing/security parsers (parse_ospf/eigrp/bgp/
  port_security/auth/dhcp) + compute_causality_chains/compute_failure_impact + **`_census_header`/
  `_census_autofit`** (no remaining monolith writer uses the census header helpers — the rest use
  inline headers) all became unused in the monolith → dropped. `parse_show_interface_counters`
  SURVIVED (still used elsewhere). Fixed: test_parsers (`cp.parse_ospf/bgp`→`parse.parse_ospf/bgp`,
  added `from cisco_toolkit import parse`), test_package identity assertions (parse ospf/bgp,
  analyze causality/failure, excel _census_*) → not-hasattr. **65 tests**, golden byte-identical,
  ruff clean, mypy 101.
- **Lesson reinforced:** big writer batches that pull cmdio/parse/analyze imports into excel
  trigger proportionally big F401 cascades + multi-file test repoints. Grep tests/ for EVERY
  dropped symbol (test_parsers is the one that bites — it tests parsers via `cp.`). Consider
  splitting future batches that touch many parsers.

**Excel writers remaining:** (d-cont) **step 25 = the FUSED compute-in-writer ones:**
`write_physical_health_sheet` (@~1944 in monolith now — computes physical_health records inline,
returns to main(); uses `_SEV_FILL`/`build_network_model`/`_physical_uplink_index`/`_poe_device_util`/
`parse_interface_phy`/`_classify_media`/`_is_physical_port`/`parse_show_interface_counters`),
`write_l3_forwarding_sheet` (computes l3_forwarding records inline + `_parse_track`/`_track_summary`/
`_parse_fhrp`/`build_network_model`), `write_flow_trace_sheet` (+ `_RISK_FILL`/`_RISK_RANK`, renders a
trace_full_flow dict). main() does `physical_health = _run_phase(..., write_physical_health_sheet, ...)`
— the writer RETURNS records, so import-back keeps it identical. (e) **step 26 = `append_interface_rows`
+ build_* (build_device_physical/build_interfaces/build_switch_identity — these pull MANY parsers →
huge F401 + test_parsers repoint) + global_arp/dual-connection + `debug_scan_headers`.** Then html
(snapshot_state/write_html_explorer/write_diff_workbook/`_macset`), then `__main__`. Sequential.

---

## 2026-06-05 — PHASE 2.7 step 23: health/analysis writers -> excel

On branch `phase2-split-excel4`. Byte-identical. Monolith **~2,395 lines**; excel.py ~728.

- Moved Region C (5 records-rendering writers) → excel.py: `write_cross_layer_sheet`/
  `write_protocol_health_sheet`/`write_health_scores_sheet`/`write_score_sensitivity_sheet`/
  `write_migration_readiness_sheet` (+ `_CL_FILL`/`_READY_FILL`/`_STATUS_FILL` + their `*_SHEET_NAME`).
  They render already-computed records (main() computes via analyze, passes in), so the only
  analyze dep is `_health_band` (added to excel.py's analyze import).
- **`_SEV_FILL` relocation:** it's a severity fill-map shared by ~6 writers across regions
  (causality/failure [B], the fused physical/l3 writers @2036/2227 [D], protocol_health [C]).
  Since protocol_health moved, `_SEV_FILL` had to move to excel.py (excel can't import back from
  monolith). Imported it back for the ~4 monolith writers that still use it.
- F401: `_health_band` was write_health_scores_sheet's last monolith user → dropped from monolith
  analyze import + updated the step-15 `cp._health_band` assertion to not-hasattr. The compute_*
  (cross_layer/protocol_health/health_scores/score_sensitivity/migration_readiness) STAY re-exported —
  main() calls them to produce the records. **65 tests**, golden byte-identical, ruff clean, mypy 101.

**Excel remaining:** (d) **step 24 = fused compute-in-writer + file-reading writers:** causality/
failure (compute_causality_chains/compute_failure_impact — region B, use `_SEV_FILL`), the physical-
health writer (@~2030, computes inline, returns physical_health records to main()), the l3-forwarding
writer (computes l3_forwarding records inline + uses `_parse_track`/`_track_summary`/`_parse_fhrp`),
write_flow_trace_sheet, and the file-reading writers interface_health/security_posture/routing_adjacency
(read `_load_cmd_output` + call parse_port_security/auth/dhcp/ospf/bgp/eigrp/counters → excel.py imports
cmdio + those parsers). (e) **step 25 = `append_interface_rows` + build_* (build_device_physical/
build_interfaces/build_switch_identity) + global_arp/dual-connection + `debug_scan_headers`.** Then
**html** (snapshot_state/write_html_explorer/write_diff_workbook/`_macset`), then **`__main__`**. Sequential.

---

## 2026-06-05 — PHASE 2.7 step 22: analysis writers -> excel (first to call analyze)

On branch `phase2-split-excel3`. Byte-identical. Monolith **~2,544 lines**; excel.py ~576.

- Moved 5 writers (in 2 monolith regions) → excel.py: `write_move_group_sheet`/`write_topology_sheet`/
  `write_findings_sheet`/`write_capacity_sheet`(+`_to_float`)/`write_topology_diagram`(+`_mermaid_id`,
  writes .mmd/.dot via `os`). These are the **first excel writers that call analyze computes**, so
  excel.py now `from cisco_toolkit.analyze import compute_findings, compute_move_groups,
  compute_topology_links` (excel→analyze is one-way, correct direction) + `import os` + `Optional`.
- Import-backs: the 5 writers (main()). Constants + `_to_float`/`_mermaid_id` package-internal.
- **F401 cascade:** `compute_topology_links`/`compute_findings` were their last monolith users →
  dropped from the monolith's analyze import. **`compute_move_groups` STAYS re-exported** (main()
  calls it directly to build move_groups for compute_migration_readiness — ruff confirmed). Updated
  step-12 identity assertions to not-hasattr. **Caught an external test:** `test_cry_wolf.py` used
  `cp.compute_findings` → repointed to `analyze.compute_findings` (it already imports analyze). The
  tests/-grep-for-`cp.<symbol>` discipline caught it.
- Extended excel test (5 writer identities + `_to_float` smoke + `_to_float`/`_mermaid_id` package-
  internal). **65 tests**, golden byte-identical, ruff clean, mypy 101. `.md` V3.23.32.

**Excel writers remaining:** (c) **step 23 = health/analysis writers** — `write_health_scores_sheet`/
`write_score_sensitivity_sheet`/`write_migration_readiness_sheet`/`write_cross_layer_sheet`/
`write_causality_chains_sheet`/`write_failure_impact_sheet`/`write_protocol_health_sheet`/
`write_interface_health_sheet`/`write_security_posture_sheet`/`write_routing_adjacency_sheet`
(+ their `_SEV_FILL`/`_READY_FILL`/`_STATUS_FILL`/`_CL_FILL` fill maps + `*_SHEET_NAME`). Several of
these take already-computed `records` (main() computes, passes in) so they don't import analyze; a few
call computes. Watch for parse-using ones (interface_health/security_posture/routing_adjacency read
files via `_load_cmd_output` + call parsers). (d) FUSED compute-in-writer (physical-health/
l3-forwarding+`_parse_track`/`_track_summary`/flow-trace). (e) `append_interface_rows` + build_* +
global_arp + `debug_scan_headers`. Then html, then `__main__`. Sequential.

---

## 2026-06-05 — PHASE 2.7 step 21: census/inventory writers -> excel

On branch `phase2-split-excel2`. Byte-identical. **First writer batch into excel.py.**
Monolith **~2,719 lines**; `cisco_toolkit/excel.py` ~381.

- Moved 5 pure-render writers + their constants/helper into excel.py:
  `write_device_inventory_sheet`(+`INVENTORY_SHEET_NAME`/`INVENTORY_COLUMNS`),
  `write_svi_gateway_sheet`(+`SVI_SHEET_NAME`/`SVI_COLUMNS`/`_is_svi`),
  `write_stp_detail_sheet`(+`STP_SHEET_NAME`/`STP_COLUMNS`),
  `write_vlan_census_sheet`/`write_endpoint_census_sheet`(+`VLAN_CENSUS_SHEET_NAME`/
  `ENDPOINT_CENSUS_SHEET_NAME`). No analyze compute calls — they just iterate the model.
- excel.py gained: a module `logger = logging.getLogger(__name__)`, `from cisco_toolkit.model
  import DevicePhysical, InterfaceData`, `_split_macs` (textutils), `List` (typing). The census
  writers use excel.py's own `_census_header`/`_census_autofit` (same module now).
- Import-backs: the 5 writers (main() calls them). Constants + `_is_svi` package-internal.
- **F401 cascade:** `_split_macs` was `write_vlan_census_sheet`'s last monolith user → dropped its
  textutils re-import + updated the step-11 identity assertion to `not hasattr(cp, ...)`
  (analyze.py + excel.py import `_split_macs` from textutils directly). `_census_header`/
  `_census_autofit` STAY re-exported — the *remaining* monolith writers (move-group/topology/
  health/etc.) still use them.
- Mechanics: big contiguous block (monolith 816-1122). Did the removal in 2 monolith edits
  (inventory; then SVI+STP+census as one) + the excel.py append as one. mypy now "4 files" (census
  dynamic-dict findings relocated with the writers; net 101). **65 tests** (extended the excel test:
  5 writer identities + `_is_svi` smoke + constants-package-internal). Golden byte-identical, ruff
  clean, mypy 101. `.md` V3.23.31.

**Excel writers remaining (next batches):** (b) **step 22 = move-group/topology/findings/capacity**
(`write_move_group_sheet`/`write_topology_sheet`/`write_findings_sheet`/`write_capacity_sheet`/
`write_topology_diagram`+`_mermaid_id`+`_canon_host`-callers — these DO call analyze computes
[compute_move_groups/topology_links/findings], so excel.py will import analyze → fine, excel is
above analyze); (c) health/analysis writers; (d) FUSED compute-in-writer (physical-health/
l3-forwarding+`_parse_track`/`_track_summary`/flow-trace); (e) `append_interface_rows` + build_*
(build_device_physical/build_interfaces/build_switch_identity) + global_arp + `debug_scan_headers`.
Then html (snapshot/explorer/diff/topology_diagram), then `__main__`. Sequential.

---

## 2026-06-05 — PHASE 2.7 step 20: stand up the Excel layer (shared helpers)

On branch `phase2-split-excel1`. Byte-identical. **First excel slice — establishes
`cisco_toolkit/excel.py`** (the foundation; writers follow). Monolith **~2,973 lines** (<3k).

- New `cisco_toolkit/excel.py` (imports `openpyxl.styles`/`utils` + textutils.normalize_ifname;
  a clean layer ABOVE analyze — excel→textutils only for now, no cycle). Holds: `_CENSUS_HDR_FILL`/
  `_census_header`/`_census_autofit` (openpyxl sheet formatting), `norm_header`/`HEADER_TO_FIELD`/
  `find_header_row`/`ensure_headers` (template header matching), `sortkey` (port-row order).
- Import-backs: `_census_header`/`_census_autofit` (~12 sheet writers), `find_header_row`/
  `ensure_headers` (main() template-fill at ~3102), `sortkey` (append_interface_rows). Package-
  internal: `norm_header`/`HEADER_TO_FIELD`/`_CENSUS_HDR_FILL`. NO F401 cascade this time (the
  openpyxl Font/Alignment/etc. imports stay — many other monolith writers still use them).
- Mind the cmdio test (test_cmdio) which now has the excel test after it; grepped tests/ first
  (no `cp.norm_header`/`cp.HEADER_TO_FIELD` refs; golden exercises find_header_row via the real
  pipeline subprocess, not cp.). New `test_excel_reexported_and_functional` (identity + norm_header/
  sortkey/HEADER_TO_FIELD smokes). **65 tests** (was 64), golden byte-identical, ruff clean, mypy 101.
  `.md` V3.23.30.

**Excel layer plan (this is the BIG remaining layer, several PRs):** now that the helper
foundation is in excel.py, move the `write_*` sheet writers in sheet-group batches, each importing
the analyze/parse computes back (mostly mechanical). Groups: (a) census/inventory
(write_vlan_census/endpoint_census/device_inventory/svi_gateway/stp_detail + `_is_svi`);
(b) move-group/topology/findings/capacity (+ `write_topology_diagram`/`_mermaid_id`);
(c) health/analysis writers (health_scores/score_sensitivity/migration_readiness/cross_layer/
causality/failure_impact/protocol_health/interface_health/security_posture/routing_adjacency);
(d) the FUSED compute-in-writer ones (write_physical_health_sheet, write_l3_forwarding_sheet +
`_parse_track`/`_track_summary`, write_flow_trace_sheet) — these return records to main();
(e) `append_interface_rows` + the build_* helpers (build_device_physical/build_interfaces/
build_switch_identity) + global_arp/dual-connection + `debug_scan_headers`. **Next = step 21:
census/inventory writer group.** Then html (snapshot/explorer/diff/topology_diagram), then `__main__`.
Sequential — `/batch` does NOT fit.

**NOTE (harness):** after `git checkout -b`, Read a file (any slice) before Editing it — the
checkout resets the Edit tool's read-tracking (hit this on analyze.py in step 19).

---

## 2026-06-05 — PHASE 2.7 step 19: flow-trace -> analyze (ANALYZE LAYER COMPLETE)

On branch `phase2-split-analyze9`. Byte-identical. **Last analyze cluster.** Monolith
**~3,064 lines**; `cisco_toolkit/analyze.py` now **~1,344 lines** = the whole analyze layer.

- Moved `trace_full_flow` + helpers `_ip_in_prefix`/`_find_endpoint_by_ip`/`_find_gateways_for`/
  `_bfs_forwarding_path` → analyze.py. Pure (no `_load_cmd_output`); all deps already in the
  package (`_is_physical_port`, `_link_carries`, `build_network_model`, `_physical_uplink_index`),
  so NO new analyze imports. `trace_full_flow` imports back (main() under `--flow-src`/`--flow-dst`,
  line 3558); the 4 helpers are package-internal. `_RISK_FILL`/`_RISK_RANK`/`FLOW_TRACE_SHEET_NAME`
  + `write_flow_trace_sheet` stay (excel).
- **L3-forwarding stayed:** `write_l3_forwarding_sheet` is compute+write FUSED (main() gets the
  `l3_forwarding` records *from* it — `l3_forwarding = _run_phase("L3 Forwarding Map", write_l3_forwarding_sheet, ...)`),
  like physical-health's writer. It + `_parse_track`/`_track_summary` move with the excel layer.
- F401 cascade (routine now): `_link_carries` was `_bfs_forwarding_path`'s last monolith user →
  dropped the import-back + updated the step-13 identity assertion. `build_network_model` /
  `_physical_uplink_index` survive (write_l3_forwarding_sheet / write_physical_health_sheet use them).
- **Harness gotcha:** a fresh `git checkout -b` from main reset the Edit tool's read-tracking for
  `analyze.py` → first Edit failed "File has not been read." Fix: `Read` the file (even a slice)
  after branching before Editing. Monolith was fine (I'd Read a region this turn).
- Extended test_package (trace_full_flow identity + 4 helpers package-internal + `_ip_in_prefix`
  + a same-subnet L2 flow smoke). **64 tests**, golden byte-identical, ruff clean, mypy 101. `.md` V3.23.29.

**ANALYZE LAYER DONE (steps 10-19).** Remaining PHASE 2.7: **excel** (`write_*` — the biggest
layer, ~20 sheet writers + their fused-compute like write_l3_forwarding_sheet/write_physical_health_sheet,
+ the openpyxl header helpers `norm_header`/`find_header_row`/`append_interface_rows` etc.; these
import the analyze/parse computes back, so mostly mechanical but bulky — likely several PRs by sheet
group), then **html** (snapshot_state/write_html_explorer/write_diff_workbook), then **`__main__`**
(collect/connect/main + arg parsing — what's left IS the entrypoint). **Next = step 20: start excel**
(pick a sheet-group: census/topology/move-group writers first, or the build_* helpers
build_device_physical/build_interfaces/build_switch_identity). Sequential — `/batch` does NOT fit.

---

## 2026-06-05 — PHASE 2.7 step 18: dependency-map + cross-layer -> analyze

On branch `phase2-split-analyze8`. Byte-identical. Monolith **~3,270 lines**.

- Moved `build_dependency_map` + `compute_cross_layer_correlations` (CL-01..CL-10) +
  `all_hosts` + the `_CL_RANK` constant into analyze.py. Unblocked by step 17:
  build_dependency_map's deps (`build_network_model`/`_vlan_components`/`_physical_uplink_index`
  [analyze] + `_is_physical_port` [parse]) are all in the package now. Added `_is_physical_port`
  to analyze.py's parse import. build_dependency_map reads NO files — pure on its
  (all_interfaces, physical_health, l3_forwarding) inputs + the package helpers.
- Import-backs: `build_dependency_map` + `compute_cross_layer_correlations` (main() via
  _run_phase). `all_hosts` + `_CL_RANK` package-internal. `_CL_FILL` + `CROSS_LAYER_SHEET_NAME`
  stay (excel).
- **F401 cascade (the now-expected pattern, both gates fired):** build_dependency_map was the
  monolith's LAST `_vlan_components` user → ruff flagged the stale step-13 import-back (dropped
  it) → proactively fixed the step-13 identity assertion `cp._vlan_components is …` to
  `not hasattr(cp, ...)` (build_network_model/_link_carries stay re-exported, still used by the
  L3/flow/physical writers). Grepped tests/ first: only `cp.compute_cross_layer_correlations`
  (test_compute/test_resilience) refs externally, still re-exported → no breakage.
- Extended test_package (identity for build_dependency_map/compute_cross_layer_correlations +
  all_hosts/_CL_RANK package-internal + a sole-gateway-no-FHRP → CL-03 smoke). **64 tests**,
  golden byte-identical, ruff clean, mypy 101. `.md` V3.23.28.

**Analyze: ONE cluster left — L3-forwarding + flow-trace.** In the monolith: `_parse_track`/
`_track_summary` (L3 helpers, → parse.py if shared else analyze), `write_l3_forwarding_sheet`
(excel — computes inline, has the L3-forwarding records logic), and the flow-trace functions
`trace_full_flow`/`_bfs_forwarding_path`/`_ip_in_prefix`/`_find_endpoint_by_ip`/`_find_gateways_for`
+ `write_flow_trace_sheet` (excel). **Next = step 19:** map this cluster (flow-trace is the
compute part; the l3_forwarding *records* may be computed inside write_l3_forwarding_sheet — check
whether there's a clean compute_* or if it's writer-inline like physical-health). Then **excel**
(`write_*`, the biggest layer — ~20 sheet writers), html (snapshot/explorer), `__main__`. Sequential.

---

## 2026-06-05 — PHASE 2.7 step 17: physical-health helpers -> package

On branch `phase2-split-analyze7`. Byte-identical. **Prereq for the dependency-map cluster**
(which uses `_is_physical_port`/`_physical_uplink_index`). Monolith **~3,437 lines**.

- Started toward step 17 = `build_dependency_map`+`compute_cross_layer_correlations`, but
  found `build_dependency_map` uses `_physical_uplink_index` + `_is_physical_port` (physical-
  health helpers still in the monolith) → would be a circular import. So **did the physical
  helpers first** (this PR), dependency-map next.
- Split by kind: pure parsers `_NON_PHYSICAL_RE`(internal)/`_is_physical_port`/`_classify_media`/
  `parse_interface_phy`/`_parse_poe_watts` → **parse.py**; compute helpers `_poe_device_util`
  (needs `DevicePhysical` — analyze.py now imports it)/`_physical_uplink_index` → **analyze.py**.
- Import-backs: parse → `_is_physical_port`/`_classify_media`/`parse_interface_phy`/`_parse_poe_watts`;
  analyze → `_poe_device_util`/`_physical_uplink_index` (all used by write_physical_health_sheet +
  build_dependency_map, both still monolith).
- **Two F401 cascades (both caught + fixed):** (1) `IFACE_TOKEN_RE`/`VALID_IFACE_RE` were the
  phy parsers' last monolith users → dropped from the monolith's textutils import; (2) that
  drop then broke the step-1 identity assertion `cp.VALID_IFACE_RE is textutils.VALID_IFACE_RE`
  → updated to `not hasattr(cp, ...)` (PHYSICAL_IFACE_RE stays re-exported, used at monolith
  800/1744). **Lesson refinement: an F401 drop of a re-export ALSO needs its test_package.py
  identity assertion updated — ruff catches the import, pytest catches the assertion.**
- Extended test_package (parse: 4 phy-parser identities + is_physical/classify_media/
  parse_interface_phy smokes; analyze: `_poe_device_util` 25% + `_physical_uplink_index`
  single-fiber smokes). **64 tests**, golden byte-identical, ruff clean, mypy 101. `.md` V3.23.27.

**Next = step 18: `build_dependency_map` + `compute_cross_layer_correlations` + `all_hosts`**
(now unblocked — its phy-helper deps are in the package; it also uses `build_network_model`/
`_vlan_components` already in analyze, and `_CL_RANK` moves with cross-layer; `_CL_FILL` +
`CROSS_LAYER_SHEET_NAME` stay excel). Then the L3-forwarding + flow-trace cluster finishes
analyze. Then excel (`write_*`, the big layer), html, `__main__`. Sequential — `/batch` does NOT fit.

---

## 2026-06-05 — PHASE 2.7 step 16: protocol-health -> analyze

On branch `phase2-split-analyze6`. Byte-identical. **First parser-entangled analyze
slice.** Monolith **~3,536 lines**.

- Moved `compute_protocol_health` + its analyze-internal sub-parsers `_parse_stp_mode`/
  `_parse_stp_tcn`/`_parse_etherchannel_member_states`/`_parse_vtp_full` into analyze.py.
  analyze.py now imports parser deps from parse.py (`parse_spanning_tree_blockedports`,
  `parse_etherchannel_summary_members`, `parse_ospf_neighbors`/`_bgp_summary`/`_eigrp_neighbors`,
  + `_parse_fhrp`) — analyze→parse is a clean one-way dep (parse imports only textutils).
- **`_parse_fhrp` went to parse.py, not analyze.py:** it's a pure `re`-only FHRP
  behaviour-string parser used by BOTH `compute_protocol_health` (analyze) and the monolith's
  `write_l3_forwarding_sheet` (3104). Leaving it in the monolith would make analyze import
  back from the monolith = circular; parse.py is its proper leaf home. Imported back for
  the L3-fwd sheet. (`_parse_track`/`_track_summary` stay — they're L3-only, next cluster.)
- Import-backs: `compute_protocol_health` (analyze, for main()), `_parse_fhrp` (parse, for
  write_l3_forwarding_sheet). The 4 STP/EC/VTP sub-parsers are package-internal. The 5 parse
  parsers compute_protocol_health used are all still used elsewhere in the monolith
  (build_interfaces / write_routing_adjacency_sheet), so no F401.
- Per the step-15 lesson, grepped tests/ for `cp.<symbol>` first: only `cp.compute_protocol_health`
  (test_compute.py:164) refs externally and it's still re-exported, so no breakage. Extended
  test_package (parse `_parse_fhrp` identity+smoke; analyze compute_protocol_health identity +
  the 4 internals-not-reexported + an FHRP-only smoke). **64 tests**, golden byte-identical,
  ruff clean, mypy 101. `.md` V3.23.26.

**Remaining analyze (each reads files + drags parsers, one cluster/PR):** physical-health
(the writer computes inline; helpers `parse_interface_phy`/`_classify_media`/`_is_physical_port`/
`_parse_poe_watts`/`_poe_device_util`/`_physical_uplink_index` feed `write_physical_health_sheet`
— NOTE: parse_interface_phy/_classify_media/_is_physical_port are pure PARSERS → parse.py;
_poe_device_util/_physical_uplink_index are compute helpers → analyze.py; no clean compute_* to
anchor, so this one is fuzzier); `build_dependency_map`+`compute_cross_layer_correlations`+`all_hosts`;
L3-forwarding (`write_l3_forwarding_sheet`+`_parse_track`/`_track_summary`) + flow-trace
(`trace_full_flow`/`_bfs_forwarding_path`/`_ip_in_prefix`/`_find_*`). **Next = step 17:**
build_dependency_map + cross_layer (cleanest — has clear compute_* anchors). Then excel
(`write_*`, the big layer), html, `__main__`. Sequential — `/batch` does NOT fit.

---

## 2026-06-04 — PHASE 2.7 step 15: scoring + readiness synthesis -> analyze

On branch `phase2-split-analyze5`. Byte-identical. **First I/O-fed analyze slice** (now
that cmdio is homed). Monolith **~3,650 lines**.

- Moved the contiguous scoring/readiness cluster into `cisco_toolkit/analyze.py`:
  `_ESSENTIAL_CMD_VARIANTS` + `compute_data_quality` (the only one that reads files - via
  `cmdio._load_cmd_output`, which analyze.py now imports), `compute_health_scores`,
  `compute_score_sensitivity`, `compute_migration_readiness`. The four `compute_*` import
  back for `main()` (it runs them via `_run_phase`).
- **`ScoringConfig` / `SCORING` / `_host_role` no longer re-exported by the monolith** -
  their last in-monolith users (these compute_*) moved out. `_health_band` STAYS
  re-exported (write_health_scores_sheet still calls it). Excel sheet-name + `_READY_FILL`/
  `_STATUS_FILL` constants stay.
- **Wider blast radius than usual:** dropping the `ScoringConfig`/`SCORING`/`_host_role`
  re-exports broke 8 PRE-EXISTING behavioral unit tests (test_scoring_config / test_cry_wolf
  / test_data_quality from PHASE 2.1/2.2/2.4) that referenced them via `cp.` (the monolith).
  Fixed by pointing those tests at `cisco_toolkit.analyze` (added `from cisco_toolkit import
  analyze`, `cp.ScoringConfig`->`analyze.ScoringConfig`, etc.). Their `cp.compute_*` /
  `cp._empty_dep_map` refs are unchanged (still monolith-side). **Lesson for future drops:
  grep ALL of tests/ for `cp.<symbol>` before dropping a re-export, not just test_package.py.**
- Extended the test_package analyze test (identity for the 4 + a clean compute_health_scores
  smoke + a compute_data_quality fraction smoke). **64 tests** (unchanged count - extended,
  not added). Golden byte-identical, `ruff` clean, mypy 101. `.md` V3.23.25.

**Analyze nearly done.** Still in the monolith (the genuinely I/O-heavy + parser-entangled
analyze functions): physical-health (`compute_*` + `parse_interface_phy`/`_classify_media`/
`_is_physical_port`/`_NON_PHYSICAL_RE`), protocol-health (`compute_protocol_health` +
`_parse_fhrp`/`_parse_track`/`_track_summary`/`_parse_stp_mode`/`_parse_stp_tcn`/
`_parse_etherchannel_member_states`/`_parse_vtp_full`), `build_dependency_map` +
`compute_cross_layer_correlations` + `all_hosts`, and the L3-forwarding / flow-trace
functions (`trace_full_flow`, `_bfs_forwarding_path`, `_ip_in_prefix`, etc.). These read
files AND drag their parsers, so each is a chunkier slice. **Next = step 16:** likely the
physical-health cluster OR protocol-health cluster (pick one, move it + its parsers). Then
build the rest, then excel (`write_*`), html, `__main__`. Sequential — `/batch` does NOT fit.

---

## 2026-06-04 — PHASE 2.7 step 14: home the command-output I/O glue

On branch `phase2-split-cmdio`. Byte-identical. **The gate step** for the I/O-fed
analyze functions — no `compute_*` moved here, just the helper they all need.

- New leaf `cisco_toolkit/cmdio.py` (stdlib only: os/logging/typing; own module
  `logger`) holds `_CISCO_ERRORS`, `_load_cmd_output` (fail-soft loader: tries each
  command variant, skips empty / Cisco-error captures), and `_safe_parse` (runs a
  section parser fail-soft, returns `{}`/`_default` on exception).
- All three imported back into the monolith: `_load_cmd_output`/`_safe_parse` have
  ~50 call sites across build_*/compute_*/write_*; `_CISCO_ERRORS` is also reused by
  the platform-detection-from-files function (line ~529, stays).
- **Byte-identical note:** the two diagnostic breadcrumbs (`_load_cmd_output: failed
  reading…` debug, `[parse] … failed` warning) now log under the `cisco_toolkit.cmdio`
  logger instead of the monolith logger — log *name* only, on failure paths; doesn't
  touch the snapshot.json / Excel contract. Same pattern as parse.py's step-7 logger.
  Golden confirms byte-identical.
- New test `test_cmdio_reexported_and_functional` (identity + `_safe_parse` happy/raise
  paths + `_load_cmd_output` content / error-skip / absent / variant-fallthrough), so
  **64 tests** now (was 63). `ruff` clean, mypy 101. Monolith **~3,842 lines**. `.md` V3.23.24.

**Now unblocked: the I/O-fed `compute_*` batch (step 15+).** With `_load_cmd_output`/
`_safe_parse` in the package, analyze.py can import them (cmdio is a lower leaf, no
cycle). Candidate next slice: `compute_data_quality` (small, uses only `_load_cmd_output`
+ `_ESSENTIAL_CMD_VARIANTS`) as the first I/O-fed move, then the bigger ones —
`compute_health_scores`/`_score_sensitivity`/`_migration_readiness` (note these take
already-computed lists, so they're nearly pure; the real I/O is in physical-health /
protocol-health / build_dependency_map / L3 / flow, which read files and drag the
entangled `parse_interface_phy`/`_classify_media`/`_is_physical_port` +
`_parse_fhrp`/`_parse_track`/`_parse_stp_*`/`_parse_etherchannel_member_states`/
`_parse_vtp_full` parsers). Then excel (`write_*`), html, `__main__`. Sequential — `/batch`
does NOT fit (confirmed with user).

---

## 2026-06-04 — PHASE 2.7 step 13: network-model / blast-radius -> analyze

On branch `phase2-split-analyze4`. Byte-identical. **Fourth analyze slice** — the
blast-radius cluster. Monolith now **under 4,000 lines** (3,866, from ~5,769).

- Moved the **contiguous** pure cluster (monolith lines 2469-2791) into
  `cisco_toolkit/analyze.py`: `_vlan_in_ranges`, `build_network_model`, `_link_carries`,
  `_vlan_components`, `compute_causality_chains`, `compute_failure_impact`. Added
  `Optional` to analyze.py's typing import (`_vlan_components`/causality use it). All pure
  on the model — no `_load_cmd_output`.
- These are still used by monolith functions *outside* the cluster (physical/L3/flow at
  lines ~2976/3138/3171/3510/3567), so import back `build_network_model`, `_link_carries`,
  `_vlan_components` + the two compute fns (for their write_* sheets). The Causality/Failure
  `*_SHEET_NAME` + `_SEV_FILL` constants stay (excel).
- **`build_network_model` was the last monolith user of `_canon_host`/`_canon_host_map`**
  (moved step 12), so dropped those import-backs (ruff F401-confirmed). The step-12
  identity assertions went stale → updated them to package-internal asserts (same pattern
  as step 12 did for `MOVEGROUP_EXCLUDED_VLANS`; this is now a recurring move — the
  identity test reliably catches it).
- Extended the analyze test (still **63 tests**): identity for the 5 moved symbols + a
  build_network_model structure smoke and a sole-gateway-removed → "Hard partition" /
  High `compute_failure_impact` smoke. Golden byte-identical, `ruff` clean, mypy 101.
  `.md` V3.23.23.

**Analyze layer status:** the pure, model-only `compute_*` are now all in the package
(move-groups, topology-links, findings, network-model, causality, failure-impact). **What
remains in the monolith for analyze:** the **I/O-fed** functions — they need
`_load_cmd_output` (+`_safe_parse`), the ~50-call-site helper at line ~687, homed in the
package first. **Next slice (step 14): home `_load_cmd_output` + `_safe_parse`** (probably
a tiny `cisco_toolkit/cmdio.py` leaf, or fold into parse.py — but it does file I/O so a
dedicated module is cleaner). Then the I/O-fed `compute_*` batch: `compute_data_quality`,
`compute_health_scores`/`_score_sensitivity`/`_migration_readiness`, physical-health
(`compute_*` + `parse_interface_phy`/`_classify_media`/`_is_physical_port`), protocol-health
(+ `_parse_fhrp`/`_parse_track`/`_parse_stp_*`/`_parse_etherchannel_member_states`/
`_parse_vtp_full`), `build_dependency_map`/`compute_cross_layer_correlations`, the L3/flow
functions. Then excel (`write_*`), html, `__main__`. Sequential — `/batch` does NOT fit.

---

## 2026-06-04 — PHASE 2.7 step 12: topology-links + findings -> analyze

On branch `phase2-split-analyze3`. Byte-identical. **Third analyze slice** — finishes
the pure model-derived "structure & risk" cluster.

- Moved `compute_topology_links` + `compute_findings` and their analyze-internal
  helpers `_canon_host`, `_is_infra_neighbor`, `_canon_host_map` + the `_SEV_RANK`
  constant into `cisco_toolkit/analyze.py`. `_canon_host` was verified analyze-internal
  in step 11 (no excel writer calls it), so it went *into* analyze.py, not textutils.
- Monolith import-backs now: `compute_topology_links` (write_topology_sheet /
  write_topology_diagram), `compute_findings` (write_findings_sheet), `_canon_host` +
  `_canon_host_map` (build_network_model, still in monolith). `TOPOLOGY_SHEET_NAME` /
  `FINDINGS_SHEET_NAME` stay (excel).
- **Dropped the temporary `MOVEGROUP_EXCLUDED_VLANS` import-back** (from step 11): its
  last monolith user, `compute_findings`, moved out, so it's now package-internal.
  ruff confirmed no F401. The step-11 identity test asserted the monolith re-exported
  it — that assertion went stale and **the package-identity test caught it** (good);
  updated it to assert `analyze.MOVEGROUP_EXCLUDED_VLANS == {1}` + `not hasattr(cp, ...)`,
  mirroring the step-4 convention.
- Extended the analyze test (no new fn, still **63 tests**): identity for the 4 moved
  symbols + `_canon_host` normalization, a both-ends CDP link smoke, and a
  no-FHRP-on-2-SVIs → High "Gateway redundancy" finding smoke. Golden byte-identical,
  `ruff` clean, mypy 101. Monolith **~4,149 lines**. `.md` V3.23.22.

**Structural/findings cluster done.** Next slice (step 13): the **network-model /
blast-radius cluster** — `build_network_model` (+ `_vlan_in_ranges`, `_link_carries`,
`_vlan_components`), `compute_causality_chains`, `compute_failure_impact`. Moving
`build_network_model` drops the `_canon_host`/`_canon_host_map`/`_split_macs` monolith
uses (it's their main remaining caller — re-check after). Then **home `_load_cmd_output`
(+`_safe_parse`)** → the I/O-fed `compute_*` (health/readiness/physical/protocol +
entangled phy/media & `_parse_*` parsers). Then excel (`write_*`), html, `__main__`.
Sequential — `/batch` does NOT fit (confirmed with user).

---

## 2026-06-04 — PHASE 2.7 step 11: move-group computation -> analyze

On branch `phase2-split-analyze2`. Byte-identical. **Second analyze slice** — the
first `compute_*` function to move into the package.

- Moved `compute_move_groups` + its private union-find helpers `_uf_find`/`_uf_union`
  + the `MOVEGROUP_EXCLUDED_VLANS` constant into `cisco_toolkit/analyze.py`.
- **Key untangle:** `compute_move_groups` calls `_split_macs`, a pure one-line MAC
  splitter that the monolith *also* uses in `write_vlan_census_sheet` (excel) and
  `build_network_model` (analyze, still in monolith). Leaving it in the monolith would
  force `analyze.py` to import *back* from the monolith = circular. Fix: relocate
  `_split_macs` down to `cisco_toolkit/textutils.py` (the leaf everyone imports). Both
  layers now get it from textutils.
- Monolith import-backs: `compute_move_groups` (for `write_move_group_sheet`),
  `MOVEGROUP_EXCLUDED_VLANS` (for `compute_findings`, still here — temporary until
  findings moves), `_split_macs` (from textutils). `MOVEGROUP_SHEET_NAME` stays (excel).
- mypy still 101 but now spread over 3 files — `compute_move_groups`'s dynamic-dict
  findings simply moved *with* it into analyze.py (net count unchanged = baseline intact).
- Extended `test_package.py` (no new test fn, so still **63 tests**): `_split_macs`
  identity+smoke, `compute_move_groups`/`MOVEGROUP_EXCLUDED_VLANS` identity + a
  two-switches-share-VLAN-20 → one-group functional smoke. Golden byte-identical,
  `ruff` clean. Monolith **~4,259 lines**. `.md` V3.23.21.

**Dependency map for the rest of the structural/findings cluster (next slice, step 12):**
`compute_topology_links` (uses `_canon_host`, `_is_infra_neighbor`) + `compute_findings`
(uses `_canon_host_map`, `_canon_host`, `_SEV_RANK`, `compute_topology_links`,
`normalize_ifname`, `MOVEGROUP_EXCLUDED_VLANS`). **`_canon_host` is analyze-internal**
(only compute_*/build_network_model/`_is_infra_neighbor`/`_canon_host_map` call it — no
excel writer does), so it moves *into* analyze.py, not textutils. Moving topology+findings
together drops the temporary `MOVEGROUP_EXCLUDED_VLANS` import-back; `_canon_host` +
`_canon_host_map` then get imported back only for `build_network_model` until the
network-model/blast-radius cluster (`build_network_model`, `_vlan_in_ranges`,
`compute_causality_chains`, `compute_failure_impact`) moves after that. Then the I/O-fed
`compute_*` (needs `_load_cmd_output` homed first), excel, html, `__main__`. Sequential —
`/batch` does NOT fit (confirmed with user).

---

## 2026-06-04 — PHASE 2.7 step 10: the analyze layer's scoring foundation

On branch `phase2-split-analyze1`. Byte-identical. **First slice of the analyze
layer** (it's too big + entangled for one PR, like the parser layer was steps 2-8).

- Moved the *leaf* of the analyze layer into a new `cisco_toolkit/analyze.py`:
  `_HEALTH_BANDS`, the `ScoringConfig` frozen dataclass (+ module-default `SCORING`),
  and the two pure helpers `_health_band` / `_host_role`. Depends only on
  `dataclasses` + stdlib + `cisco_toolkit.model`. The `compute_*` functions still in
  the monolith import the four public symbols back.
- **Last dataclass user**: with `ScoringConfig` gone, the monolith's top-level
  `from dataclasses import dataclass, field as _dcfield` was now unused → moved it
  into `analyze.py` (ruff F401-fix, mirrors step-4/7 drops). The local
  `import dataclasses` inside `compute_score_sensitivity` is separate and stayed.
- **Deliberately left behind** (not part of this leaf): the Excel fill maps
  `_READY_FILL`/`_STATUS_FILL` + the `*_SHEET_NAME` constants (excel layer), and all
  `compute_*` (incl. `compute_data_quality`, which needs `_load_cmd_output` — the
  ~50-call-site I/O helper at monolith line ~687 that the whole analyze layer leans
  on; that helper has to find a package home before the bulk of `compute_*` can move).
- `_host_role`'s annotation went from the string `"InterfaceData"` to the real
  imported type (so ruff sees the import used and mypy resolves it) — annotations
  don't affect runtime, so still byte-identical.
- Added `test_analyze_reexported_and_functional` (identity + caps/weights/band/role
  smoke). Golden byte-identical, `ruff` clean, mypy unchanged (101). **63 tests pass**
  (was 62). Monolith **~4,328 lines**. `.md` V3.23.20.

**Next analyze slices (in dependency order):** find a package home for `_load_cmd_output`
(+ `_safe_parse`) — probably a small `cisco_toolkit/io.py` or fold into `parse.py` — then
the `compute_*` graph can move in batches: the model-only ones first (`compute_move_groups`,
`compute_topology_links`, `compute_findings`, `build_network_model`, causality/failure-impact),
then the I/O-fed ones (`compute_data_quality`, `compute_health_scores`, `compute_score_sensitivity`,
`compute_migration_readiness`, physical/protocol-health + their entangled phy/media &
`_parse_fhrp`/`_parse_track`/`_parse_stp_*`/`_parse_vtp_full` parsers). Then excel (`write_*`),
html, `__main__`. **Note:** `/batch` parallel orchestration does NOT fit this work — it's
sequential (shared monolith file + import-back dependency chain + per-step golden); confirmed
with the user, who chose the sequential path.

---

## 2026-06-04 — PHASE 2.7 step 9: the data model

On branch `phase2-split-model`. Byte-identical.

- Moved the two passed-around record dataclasses `InterfaceData` and
  `DevicePhysical` into a new `cisco_toolkit/model.py` leaf (depends only on
  `dataclasses`; no project imports, no I/O). The monolith imports both back, so
  every `Dict[str, Dict[str, InterfaceData]]` hint and every constructor call is
  unchanged. `parse.py` never referenced them (parsers return plain dicts), so the
  model is a clean independent leaf — it sits beside `textutils`, not under `parse`.
- **`ScoringConfig` deliberately stays in the monolith.** It is `@dataclass(frozen=True)`
  + `_dcfield` but it is *scoring tunables*, not a record the layers pass around —
  it belongs with the analyze layer (next step). Because it still uses `dataclass`/
  `_dcfield`, the `from dataclasses import ...` import stays put (no ruff F401).
- Added `test_model_reexported_and_functional` (identity `cp.X is model.X` + a
  field/defaults smoke). Golden byte-identical, `ruff` clean, mypy unchanged (101).
  **62 tests pass** (was 61). Monolith **~4,375 lines**. `.md` V3.23.19.

**Model layer done.** Remaining, in dependency order: analyze (`compute_*` +
`ScoringConfig` + the entangled phy/media + protocol-health parsers `parse_interface_phy`
/`_classify_media`/`_is_physical_port`/`_parse_fhrp`/`_parse_track`/`_parse_stp_*`/
`_parse_etherchannel_member_states`/`_parse_vtp_full`), then excel (`write_*`, the
openpyxl-coupled layer), html (snapshot/explorer), `__main__`. analyze is the next
PR and the meatiest — many `compute_*` functions, all keyed on the model that now lives
in the package.

---

## 2026-06-04 — PHASE 2.7 step 8: counters + security parsers

On branch `phase2-split-parse7`. Byte-identical.

- Moved `parse_show_interface_counters`, `parse_port_security`,
  `parse_auth_sessions`, `parse_dhcp_snooping_binding` to `cisco_toolkit/parse.py`
  (added `VALID_IFACE_RE`/`PHYSICAL_IFACE_RE` to parse.py's import). All 4 back.
- Golden byte-identical, `ruff` clean, mypy unchanged (101). **61 tests pass.**
  Monolith ~4,450 lines. `.md` V3.23.18.

`parse.py` now holds the whole parser layer **except** the physical/media group
(`parse_interface_phy`/`_classify_media`/`_is_physical_port`+`_NON_PHYSICAL_RE`)
and the protocol-health helpers (`_parse_fhrp`/`_parse_track`/`_parse_stp_*`/
`_parse_etherchannel_member_states`/`_parse_vtp_full`) — those are entangled with
the analyze layer, so they come with it. **Next, the hard part:** model
(InterfaceData/DevicePhysical), then analyze (`compute_*`), excel (`write_*`),
html, `__main__`. These are coupled (model is referenced everywhere; write_* tie
to openpyxl) — the clean import-back pattern won't lift them as smoothly.

---

## 2026-06-04 — PHASE 2.7 step 7: version/inventory/environment parsers

On branch `phase2-split-parse6`. Byte-identical.

- Moved `parse_show_version`, `_inv_commit`+`parse_show_inventory`,
  `parse_show_environment_power`, `parse_show_environment`,
  `parse_show_module_count` to `cisco_toolkit/parse.py`. Added a module `logger`
  to parse.py (power-calc debug breadcrumb). `_inv_commit` package-internal;
  5 parsers import back. `normalize_mac` now package-internal (monolith import
  dropped, ruff F401).
- Golden byte-identical, `ruff` clean, mypy unchanged (101). **61 tests pass.**
  Monolith ~4,540 lines (from ~5,769). `.md` V3.23.17.

Parsers still in monolith: counters, port-security/auth/dhcp, interface-phy
(+`_classify_media`/`_is_physical_port`), and the protocol-health helpers
`_parse_fhrp`/`_parse_track`/`_parse_stp_mode`/`_parse_stp_tcn`/
`_parse_etherchannel_member_states`/`_parse_vtp_full`. Then model (InterfaceData/
DevicePhysical), analyze (`compute_*`), excel (`write_*`), html, `__main__`.

---

## 2026-06-04 — PHASE 2.7 step 6: run-config / etherchannel / arp / vtp / mgmt / multicast

On branch `phase2-split-parse5`. Byte-identical.

- Moved 10 pure functions to `cisco_toolkit/parse.py`: run-config, `_proto_from_token`
  + 3 etherchannel parsers, ip-arp, vtp, `_parse_ip_int_brief` + mgmt-ip, multicast.
  `_proto_from_token`/`_parse_ip_int_brief` package-internal; other 8 imported back.
- `is_valid_iface` now package-internal (monolith import dropped, ruff F401-fix);
  updated the identity test accordingly.
- Golden byte-identical, `ruff` clean, mypy unchanged (101). **61 tests pass.**
  Monolith ~4,740 lines (from ~5,769). `.md` V3.23.16.

**Parser layer is essentially done.** Still in monolith (physical/security section):
parse_show_version, parse_show_inventory(+`_inv_commit`), parse_show_environment(+power),
parse_show_module_count, parse_show_interface_counters, parse_port_security,
parse_auth_sessions, parse_dhcp_snooping_binding, parse_interface_phy(+`_classify_media`
/`_is_physical_port`), `_parse_fhrp`/`_parse_track`/`_parse_stp_*`/`_parse_vtp_full`.
Then the big layers: model (InterfaceData/DevicePhysical), analyze (`compute_*`), excel
(`write_*`), html, `__main__`.

---

## 2026-06-04 — PHASE 2.7 step 5: bulk interface-command parsers (bigger batch)

On branch `phase2-split-parse4`. Byte-identical.

- Moved 11 pure parsers + 2 constants into `cisco_toolkit/parse.py`: mac table,
  STP (blockedports/detail/states + `_STP_STS_NAME`), vlan_brief, `_compress_vlans`,
  vrf, power-inline, cdp/lldp, infer_endpoint_type (+`_DESC_EP_PATTERNS`).
  Added `normalize_mac` + `IFACE_TOKEN_RE` to parse.py's textutils import.
- `_STP_STS_NAME`/`_DESC_EP_PATTERNS` are package-internal (sole users moved), so
  not re-imported. `normalize_mac`/`IFACE_TOKEN_RE` are still used elsewhere in
  the monolith → kept (ruff clean, no F401).
- Golden byte-identical, `ruff` clean, mypy unchanged (101). **61 tests pass.**
  Monolith ~4,950 lines (from ~5,769); `parse.py` ~510. `.md` V3.23.15.

Parser layer still in the monolith: run-config, etherchannel proto/members
(+`_proto_from_token`), ip-arp, vtp, ip-int-brief/mgmt-ip, multicast, version,
inventory (+`_inv_commit`), environment(+power/module), counters, security
(port-sec/auth/dhcp), phy/media. Then analyze / excel / html / `__main__`.

---

## 2026-06-04 — PHASE 2.7 step 4: interface-table parsers

On branch `phase2-split-parse3`. Byte-identical.

- Moved `parse_show_interface_status`, `parse_show_interface_switchport`,
  `parse_show_interface_trunk_table` into `cisco_toolkit/parse.py` (added
  normalize_status/duplex/speed to parse.py's textutils import).
- The monolith stopped needing `extract_fixed_cols`/`slice_col`/`normalize_status`/
  `normalize_duplex` (now package-internal) → dropped those import-backs (ruff F401
  auto-fix). The package-identity test caught the stale re-export assertion; updated
  it to assert the package has the primitives + the monolith re-exports what it uses.
- Golden byte-identical, `ruff` clean, mypy unchanged (101). **61 tests pass.**
  `.md` V3.23.14.

Parser layer still remaining in the monolith: mac, STP (+`_STP_STS_NAME`),
vlan_brief, vrf, power_inline, counters, cdp/lldp, run-config, vtp, version,
inventory, environment, security (port-sec/auth/dhcp), phy/media, multicast,
ip-arp, ip-int-brief. Then analyze / excel / html / `__main__`.

---

## 2026-06-04 — PHASE 2.7 step 3: routing/FHRP parsers

On branch `phase2-split-parse2`. Byte-identical.

- Moved the pure parsers `parse_ip_routes`, `parse_hsrp_summary`,
  `parse_vrrp_summary`, `parse_glbp_summary` into `cisco_toolkit/parse.py`
  (`re` + `textutils`; added `is_valid_iface` to parse.py's import). Monolith
  imports them back.
- Golden byte-identical, `ruff` clean, mypy unchanged (101). **61 tests pass.**
  `.md` Change Log V3.23.13.

Split so far: textutils (leaf) · parse primitives+neighbors · routing/FHRP
parsers. Still remaining in parse: interface status/switchport/trunk, mac, STP
(+`_STP_STS_NAME`), vlan_brief, vrf, power_inline, counters, cdp/lldp,
multicast, inventory/version/env; then analyze / excel / html / `__main__`.
A long mechanical tail — see the session note about doing the bulk in a
dedicated session.

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
