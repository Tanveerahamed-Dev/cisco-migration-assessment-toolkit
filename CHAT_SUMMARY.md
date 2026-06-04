# Chat Summary

Markdown-first session log for the hardening effort on
`COLLECT_PARSE_V3_23_0.py`. Newest entry first.

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
