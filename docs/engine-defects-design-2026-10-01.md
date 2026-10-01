# Engine contract defects G13 / G15 / G49 -- designs (2026-10-01)

> **Dated record.** These are the read-only designs for the three top engine defects in
> `docs/one-app-contract-gaps-2026-09-30.md`:
> - G13: move groups carry no label.
> - G15: spanning-tree root uniqueness is never disclosed.
> - G49: device-dossier absence semantics contradict each other.
>
> An implementation run that followed them was interrupted part-way. Its uncommitted, UNVERIFIED
> edits were committed as a WIP checkpoint on branch `fix/engine-contract-defects`; see `docs/NOW.md`
> for who holds the branch and what comes next. The file:line citations refer to that branch's base,
> the Atlas Scope branch head `9a2a677c`.


---

## G13

G13 design (move-group identity). Read-only analysis: no files were edited. The work tree is `.claude/worktrees/engine-defects` at 9a2a677c and is clean.

## 1. Root cause

- **The producer never labels its rows.** `cisco_toolkit/analyze.py:158 compute_move_groups` builds rows at :223-232 and sorts them at :234-235. No row gets a `group` key, and the docstring at :159-167 doesn't list one.
- **Four producers make up their own label from list position** (`f"Group {i}"`) and happen to agree:
  - `compute_wave_sequencing` (:1452, :1475)
  - `compute_vlan_cutover_matrix` (:1586-1589)
  - `compute_migration_readiness` (:3062, :3646)
  - `compute_validation_plan` (:9713-9720)
- **Seven consumers read `g.get("group")`, which doesn't exist, so they always get `""`:**
  - `compute_endpoint_dependencies` (:7329-7332). As a result `dual_homed[].move_groups` is `[]` and `split_across_groups` is always False (:7362), and `clusters[].spans_groups` is always False (:7379).
  - `compute_subnet_intelligence` (:7501-7508): `move_groups[].group` is `""`.
  - `compute_migration_punchlist` (:8251-8254, :8271-8273): every `wave` is `""`.
  - `compute_application_intelligence` (:9010-9013, :9106-9107, :9165, :9205-9207): `waves` is `[]` and `spans_waves` is False. So the criticality weight at :9350-9351, the `n_spanning_waves` count at :9392, the querier-wave cross-domain risk and the on-air "split across waves" risk can never fire.
  - `compute_remediation_plan` (:9441-9444, :9455): `wave` is `""`.
  - `compute_device_dossiers` (:12391-12395, :12703): `wave` is `""`.
  - `webapp/backend/app.py:2839-2848` recomputes dossiers from a stored snapshot's `move_groups`, with the same result.
- **Why the tests stayed green:** existing tests hand-write labels the real producer never emits, so they only prove the consumers work on a fake input:
  - `tests/test_compute.py:262` (`"Wave 1"`)
  - `tests/test_decision_layer.py:74`
  - `tests/test_device_dossiers.py:20`
  - `tests/test_endpoint_intel.py:81` (`G1`/`G2`)
  - `tests/test_application_intelligence.py:81-82` (`Wave-1`/`Wave-2`)
  - `tests/test_subnet_intel.py:40`
- **A second, hidden sort defect:** where labels are joined they are sorted as plain strings (:7362, :7379, :8271, :9106, :9205-9207). Once labels exist, a fleet with 10 or more groups will print "Group 10, Group 2". Two places already sort numerically, but in different ways: `vlan_cutover` parses the label at :1660-1661, and validation uses `_validation_wave_key` at :9593.

## 2. Decision: one owner, one format

- **Owner:** `analyze.compute_move_groups`. After its final sort, it writes `"group": move_group_label(i)` on each row, with `i` counting from 1. Put the key first in the row.
- **Format:** `"Group N"`, where N is the 1-based position in compute_move_groups' own order: size descending, then spanning-VLAN count descending, then first switch name. Switch sets never overlap, so `switches[0]` breaks every tie and the order is total. It does not depend on the order the input dict was built in.
- **Why keep `"Group N"` rather than inventing a new format:** it is already the join key everywhere else, and changing it would orphan data. Places that depend on it today:
  - `wave_sequencing`, `migration_readiness`, `migration_scenarios.per_group`
  - `validation_plan.by_wave` keys and `items[].wave`
  - `vlan_cutover.wave` and `nrfu_commands.waves[].wave_id`
  - the MOP, MCP, workbook and explorer
  - AssessHub's saved gate and execution state, keyed on the `migration_readiness` group (`webapp/backend/gates.py:31-98`, `execution.py:111-195`, `app.py:2599-2621`)
- **Limit to state in the docstring:** the label identifies a group within one snapshot only. Matching groups across two snapshots must use switch membership. No such cross-snapshot consumer exists today (compare and trend don't read `move_groups`).
- **Helpers:** put them in `analyze.py` next to the owner. Do not create a new `cisco_toolkit` module: that would also change the two module-count strings in the golden's attestation section. Snapshot readers can import lazily, as `mop.py:239` already does.
  - `MOVE_GROUP_UNSCHEDULED = "(unscheduled)"` — one owner for this sentinel. Today it is duplicated at `analyze.py:9733/10008/10046`, `nrfu_export.py:71` and `mop.py:427`.
  - `move_group_label(ordinal) -> str` — the only place the format string lives.
  - `move_group_labels(move_groups) -> List[str]` — index-aligned with the raw, unfiltered list. It uses the written labels only if every dict row has a distinct, non-empty string label. Otherwise it applies the owner formula to every row's position. That fallback covers old snapshots written before this fix, hand-written fixtures and malformed values. It never raises and never produces duplicate labels. For an old snapshot the fallback is exact, not a guess, because a snapshot stores the owner's list in owner order.
  - `move_group_host_index(move_groups) -> (host→label, label→ordinal)` — "first group wins" semantics, and hosts are converted to strings.
  - Every multi-label join sorts by the ordinal, not by string order.

## 3. Consumers to update (the whole class)

**A. Consumers that read the missing key.** They become correct as soon as the owner writes the label. Also switch each one to `move_group_host_index` and to owner-order sorting:
- `analyze.py:7329-7332`, :7362, :7379 (endpoint dependencies)
- :7501-7508 (subnet intelligence)
- :8251-8254, :8271 (punch list)
- :9010-9013, :9106, :9205-9207 (application intelligence)
- :9441-9444 (remediation)
- :12391-12395 (dossiers)

**B. Producers that re-derive the label from position.** Switch each to read the owner's label:
- `analyze.py:1452`/:1475 (wave sequencing)
- :1586-1589, plus the sort at :1660-1661 (VLAN cutover)
- :3062/:3646 (readiness)
- :9716-9720 (validation plan; also use `MOVE_GROUP_UNSCHEDULED`)
- `excel.py:687,699` (`write_move_group_sheet`: `g["group"]`)
- `mcp_server.py:331-333`: also delete the now-false comment "move_groups rows are anonymous"
- `mop.py:49-59` (`_waves` fallback)
- `nrfu_export.py:655-665`: build the `ordered` list from the helper; import the sentinel
- `blast_radius_explorer.html`:
  - :7775-7787 (joins by list index)
  - :7804 (the baseline scope label)
  - :7920-7921 (the card label)
  - :7928 (the validation block)
  - In each place use `g.group || "Group "+(i+1)`. Adding labels to the demo snapshot at :2013 is optional.
- `webapp/backend/cutover.py:143-151 _match_move_group`: join on the exact label first, and fall back to switch overlap only for old snapshots. Today, a wave whose switches are all "homing unknown" and has no readiness row matches no group, so it reports 0 endpoints.

**C. Group referenced by a 0-based index into a filtered list.**
- `design_advisor.py:4624-4651 _wave_plan` emits `source_groups` this way. `mop.py:62-66` warns about the off-by-one.
- Recommended: add a `source_move_groups` field holding labels, and keep `source_groups` so the `webapp/frontend/src/api.ts:1232` type doesn't break.

**D. Renderers.** No code change needed; they will now show real values. Check them:
- `excel.py:3576-3587` (Punch-List Wave column)
- `excel.py:4847-4864` (Risk Register wave, shows "—" today)
- `excel.py:923-930` and :1044 onward (endpoint-dependency and application-intelligence sheets)
- `runbook.py:699-705` (currently prints the "(group)" placeholder) and :2201-2207
- `blast_radius_explorer.html:11416-11420` (subnet card, blank names today) and :11442-11443
- `causal.py:262,269`
- atlas-scope `tools/lib/compile-model.mjs:1074` (`finding.wave`)

**E. Count-only readers.** No change:
- `deck.py:547,564`
- `design.py:1113`
- `design_advisor.py:1402-1403,1754,3420-3448`
- `runbook.py:297,388`
- `ssot.py:337`
- `engagement.py:103-106`
- `webapp` `summary.py:446`, `gates.py`, `execution.py`
- `precert.py:579`

**F. Hosts in no group (secondary; moves neither snapshot).** Punch list, remediation and dossier emit `""` for a device that is in no group, which reads the same as "no device at all". Validation and NRFU emit `"(unscheduled)"` for the same case. For device-level fields, recommend `MOVE_GROUP_UNSCHEDULED`, and keep `""` only for punch rows that name no device. Every device in both the sample (23/23) and the golden (3/3) is grouped, so this changes neither snapshot.

**G. SSOT.** Add a row "Move-group identity" to `docs/ssot.md`: owner `analyze.compute_move_groups` → `move_groups[].group`, with the derivatives listed in A and B. `tests/test_ssot_registry.py` then checks that registry row's pointers.

## 4. Failing tests to write first

All of these must use real `compute_move_groups` output, never hand-written labels. Shared fixture, using `InterfaceData(port=, switchport_mode="Access", vlan=, end_host_mac=)`:
- `acc1`, `acc2`, `acc3` on VLAN 10 (each with a MAC)
- `dist1`, `dist2` on VLAN 20
- `solo` on VLAN 30

**T1 – the owner writes labels.**
- `[g["group"] for g in mg]` → `["Group 1","Group 2","Group 3"]`
- The groups' switches → `[acc1,acc2,acc3]`, `[dist1,dist2]`, `[solo]`
- Today: `KeyError 'group'`.

**T2 – determinism.** Building the fixture dict in reverse order gives the same label→switches mapping.

**T3 – the written label wins over position.** Pass `mg_rev = list(reversed(mg))`, labels kept:
- `compute_wave_sequencing` → row groups `["Group 3","Group 2","Group 1"]`
- `compute_validation_plan` → the `solo` items have `wave == "Group 3"`
- `compute_vlan_cutover_matrix(..., move_groups=mg_rev)` → VLAN 30 has `wave == "Group 3"`
- `compute_migration_readiness` (harness from `tests/test_analyze_absence_is_not_health.py:37-43`) → the `solo` row has `group == "Group 3"`
- Today all of these give positional labels.

**T4 – the G13 defect itself.**
- `compute_endpoint_dependencies`:
  - one MAC on `acc1` and `dist1` → `move_groups == ["Group 1","Group 2"]`, `split_across_groups is True`
  - one MAC on `acc1` and `acc2` → `["Group 1"]`, `False`
  - Today: `[]`, `False`.
- `compute_subnet_intelligence(IFACES, {}, mg)` → `move_groups[].group == ["Group 1","Group 2","Group 3"]` (today `["","",""]`).
- `compute_migration_punchlist(..., move_groups=mg, physical_health=[{"switch":"dist1","risk":"err-disabled"}])` → that row has `wave == "Group 2"`.
- `compute_remediation_plan(stp_findings={"accidental":[{"host":"acc1","vlan":"10"}]}, move_groups=mg)` → `wave == "Group 1"`.
- `compute_device_dossiers(health_scores=[{"switch":"solo",...}], move_groups=mg)` → `wave == "Group 3"`.
- `compute_application_intelligence` with `SW01-BC-DANTE-A` on VLAN 10 and `SW02-BC-DANTE-B` on VLAN 11 (separate groups), using the `mg` produced for those two switches:
  - audio domain → `waves == ["Group 1","Group 2"]`, `spans_waves is True`
  - the risk "On-air-critical domain split across migration waves" is present
  - This mirrors `tests/test_application_intelligence.py:79-88`, but through the real producer.

**T5 – ordering with 10+ groups.** Eleven single-switch groups `sw01`..`sw11`, each on its own VLAN (labels follow name order).
- Punch list with `l2={"addressing":{"dup_ip":[{"ip":"10.0.0.1","where":[("sw02","Vlan10",10),("sw10","Vlan20",20)]}],"dup_subnet":[]}}` → the Addressing row has `wave == "Group 2, Group 10"`.
- The same order holds for endpoint-dependency `move_groups` and application-intelligence `waves`.
- A stamp-only fix still fails this test.

**T6 – old snapshots and malformed input.**
- `move_group_labels([{"switches":["a"]},{"switches":["b"]}])` → `["Group 1","Group 2"]`
- A mixed, duplicated or non-string label anywhere → positional labels for all rows, no exception
- `mcp_server.get_move_groups` and `mop._waves` (no readiness) on rows labelled `[Group 2, Group 1]` in that order → names follow the labels (today they follow position)
- `nrfu_export` on the same input → wave order follows the owner ordinal

**T7 – webapp label join.**
- Input: `move_groups=[{"group":"Group 1","switches":["a"],"endpoints":5},{"group":"Group 2","switches":["x"],"endpoints":7}]`, `wave_sequencing=[{"group":"Group 2","make_before_break":[],"hard_cutover":[],"homing_unknown":["x"],"hard_cutover_endpoints":0}]`, no `migration_readiness`.
- `cutover.build_plan` → wave `endpoints == 7` (today 0).

**T8 – SSOT reconcile guard,** run on the fresh `golden_run` pipeline output rather than the committed file, until the goldens are regenerated. Checks:
- Every derived label is in the set of owner labels, plus `""` and `"(unscheduled)"`.
- Every punch row with devices has `wave` equal to the owner-ordered, de-duplicated labels of its devices.
- The owner's labels are unique.

## 5. Golden and sample sections the fix will move (regenerate once after #579 merges)

**`tests/golden/snapshot.json`** (one group: `access1`, `core1`, `core2`):

| Section | Change |
|---|---|
| `move_groups` | rows gain `"group": "Group 1"` |
| `punchlist` | 40 of 41 rows `wave` `""` → `"Group 1"`; the one row with no devices stays `""` |
| `remediation_plan` | `items[16].wave` and `by_device.access1[7]` / `by_device.core1[9]` `.wave` → `"Group 1"` |
| `device_dossiers` | `per_device[3].wave` → `"Group 1"` |
| `subnet_intelligence` | `move_groups[0].group` → `"Group 1"` |
| `application_intelligence` | domains `general`/`compute` `waves` `[]` → `["Group 1"]`; `spans_waves`, scores and `cutover_order` unchanged |

Unchanged: `wave_sequencing`, `migration_readiness`, `migration_scenarios`, `validation_plan`, `vlan_cutover`, `nrfu_commands`, `endpoint_dependencies` (no rows of either kind), `schema_census` (counts only), `sheet_schema.json` (headers only). `design_blueprint` is excluded from the golden comparison anyway.

**`webapp/sample_data/sample_fleet.snapshot.json`** (what the sample will show):

| Section | Change |
|---|---|
| `move_groups` | "Group 1" = 19 switches (`access1`–`17`, `core1`, `core2`); "Group 2" = `dist1`, `dist2`, `podacc1`, `podacc2` |
| `punchlist` | 138 rows "Group 1", 6 rows "Group 2", 1 row "Group 1, Group 2" (index 140, native VLAN 1 on 26 trunk ports), 1 row `""` (index 141, "No QoS configured anywhere", no devices) |
| `remediation_plan` | all 122 items, and the `by_device` copy → "Group 1" |
| `device_dossiers` | 19 "Group 1", 4 "Group 2" |
| `endpoint_dependencies` | the 3 `dual_homed` rows get `move_groups` `["Group 1"]`; `split_across_groups` stays False, now based on real labels |
| `subnet_intelligence` | groups become "Group 1" (19 switches, 4 local / 4 remote) and "Group 2" (4, 3/3) |
| `application_intelligence` | `general`: `waves` `["Group 1","Group 2"]`, `spans_waves` True, `criticality_score` 62 → 67 (+5, possibly ±1 from round-half-even). `cutover_order[1].score` 62 → 67; order and bands unchanged (compute = Pilot, general = Last). `compute`: `waves` `["Group 1"]`. `summary.n_spanning_waves` 0 → 1. No new risks: both domains are Support tier, with no on-air domain and no dual-path split. |
| `design_blueprint` | only if the optional C change lands: `wave_plan.waves[0].source_move_groups == ["Group 1","Group 2"]` |

Unchanged in the sample: `vlan_cutover` ("Group 1"×3, "Group 2"×2), `validation_plan` (142 / 22), `wave_sequencing`, `migration_readiness`, `migration_scenarios`, `nrfu_commands`.

**Things #579 owns that will need attention after the sample is regenerated:**
- `atlas-scope/src/data/fabric.json` has to be recompiled.
- `atlas-scope/src/panels/Inspector.test.tsx:213-222` asserts that F001's wave is null. F001 is the `core1` finding, which becomes "Group 1", so this test will fail.
- `atlas-scope/src/core/query.test.ts:172` and :270-275 are gated on "no finding with a wave". They will be skipped from then on, so that behaviour will need a synthetic fixture.
- The prototype limitation `move_group_label_absent` becomes obsolete.

---

## G15

# G15 design: STP root uniqueness (read-only, no repo edits)

The sample's 17 claimants for VLAN 30 are not separate L2 domains. The data contradicts itself, and the engine hides that by choosing the first host name in sort order. I checked the proposed rule with a scratch prototype against the real `stp_roots` data in both the golden and sample snapshots (results in section 6).

## 1. Verdict: a selection defect, not several L2 domains

**What the sample shows.** All 18 rows for VLAN 30 in the sample's `stp_roots` agree on one root identity: priority 32798, address `cccc.0003.0003`.
- 17 access switches (access1 to access17) each claim `is_root: true` with `bridge_priority` 32798.
- core1 does not claim root. It reports that same root identity.
- A bridge's ID is its priority plus its own MAC address, so it is unique per switch. A claimant's `root_address` is its own address (`parse.py:3100`: `is_root = explicit "This bridge is the root" line or root address == bridge address`).
- So 17 host names are presenting one bridge ID. Separate L2 domains would each show a different root identity with one claimant. This is a duplicate bridge identity instead.

**By topology it is also one domain.**
- 11 claimants carry VLAN 30 on their uplink trunk (allowed `10,20,30`) toward core1/core2, so there can be only one root among them.
- The other 6 (access7 to access12) do not carry VLAN 30 on their trunk (allowed `10,20`) and have no access port in it. Their captured `show spanning-tree` still says they are root for VLAN0030.

**Where the bad data comes from.**
- `webapp/sample_data/build_sample.py:99` deep-copies the `show spanning-tree` output of `fx._ACCESS1` verbatim into every clone: `tests/synthetic_fixtures.py:1255-1260` has the Bridge ID address `cccc.0003.0003` and "This bridge is the root".
- The `carry_vlan30=False` branch (`build_sample.py:116-128`) edits the trunk, switchport, status, VLAN and MAC outputs, but never the STP output.

**The engine defect.**
- `analyze.py:1551-1561` says "First sorted host claiming root wins". Plain string sorting puts `access1` first, which silently discards the 16 contradicting claims.
- `analyze.py:1603` then marks `stp_root_default_election=True` with no disclosure.
- In the same function, a VLAN with no observed root gets `default_election=False`. That is a negative verdict over no evidence: absence reported as a finding.

**The rest of the class.** The same "first claimant wins" or "every claim counts" logic is copied in:
- `analyze.stp_root_findings` (`analyze.py:7135-7138`)
- `excel.write_stp_roots_sheet` (`excel.py:3477-3481`)
- `archreview` L2-1 and L3-4 (`archreview.py:473-500`, `796-805`)
- `design.py:480-492`
- `design_advisor._signals` (`design_advisor.py:1595-1614`)
- `compute_device_dossiers` (`analyze.py:12590-12593`)
- `compute_validation_plan` (`analyze.py:10293-10301`)
- `compute_nrfu_commands` (`nrfu_export.py:854-872`)
- the explorer's `stpRootFor` / `stpRootCard` (`blast_radius_explorer.html:5697`, `7351-7370`).

**The honest rule already exists in two places.** `failover._current_root` (`failover.py:98-108`) names a root only when exactly one host claims it. `l2_rehearsal.py:2338-2343` requires exactly one root and one root address. But `compute_failover_readiness` (`failover.py:420-425`) quietly drops ambiguous VLANs from its counts. With the fixture output, `n_stp_roots` is 1 and VLAN 30 disappears.

## 2. The new owner (one per fact)

**Where it lives.** Put it in the existing `cisco_toolkit/stp_topology.py`, which is already the registered owner for STP topology in `docs/ssot.md` row 31 and only imports `parse` and `textutils`.
- A new module would also change the golden `attestation/claims/3/detail` text, which counts modules.
- `build_stp_roots` and the per-host `stp_roots` data stay byte-identical. `_legacy_roots_reconcile` (`stp_topology.py:913`) depends on that.

**API.**
```python
STP_ROOT_ELECTION_STATES = ("published", "ambiguous", "not_observed")
def classify_stp_root_election(stp_roots) -> {"pvst_vlan": {vid_str: rec}, "mst_instance": {inst_str: rec}}
  rec = {state, reason, root: str|None, claimants: [sorted hosts],
         identities: [{root_address, root_priority: int|None, root_priorities: [ints], claimants, observers}],
         root_priority: int|None, default_election: True|False|None}
def stp_default_priority(vid, prio) -> bool|None   # the one {32768, 32768+vid} test, PVST only
```

**Row handling.**
- A row whose `is_root` is not a real bool, or whose `root_address` is not a string, counts as malformed.
- A priority is accepted only as an integer (not a bool) or a plain digit string. Anything else, including inf and nan, becomes `None`. This one rule replaces today's integer-only check (`analyze.py:7159`) and the `int()` coercion in `design_advisor.py:1605`, which disagree.
- A root identity is keyed by address. A claimant with no address becomes its own identity (`<unaddressed:host>`). A row with no address that does not claim root contributes nothing (like core2's rows).

**States, checked in this order.**
- Any malformed row: `ambiguous` / `malformed_root_rows`.
- Two or more identities: `ambiguous` / `multiple_root_identities`. This covers separate domains and a split domain alike; the engine cannot tell them apart without proof of L2 adjacency.
- Two or more claimants of one identity: `ambiguous` / `duplicate_bridge_identity`.
- Exactly one claimant: `published` / `single_claimant`.
- No claimant but one identity seen by other switches: `not_observed` / `root_not_collected`.
- Nothing at all: `not_observed` / `no_root_evidence`.

**Default election.** It is True or False only when the state is `published` and the root has a single integer priority. Otherwise it is `None` (undetermined), including for `not_observed`.

**MST.** MST instances are keyed separately. The PVST-only verdicts still skip them. This also fixes two cases where an instance number collides with a VLAN number: failover's `_vlan_bridges` (`failover.py:80-96`) and the explorer's `stpRootFor(1)`.

**Rows published in `vlan_cutover`.**
- `stp_root`: the host, or a new `VLAN_CUTOVER_AMBIGUOUS="[AMBIGUOUS]"`, or `[NOT OBSERVED]`.
- New fields: `stp_root_state`, `stp_root_reason`, `stp_root_claimants`, `stp_root_identities`.
- `stp_root_default_election` becomes True, False or `None`.

**SSOT.** Register a new row in `docs/ssot.md` ("Per-VLAN cross-switch STP root election") naming the owner and every consumer below.

## 3. Consumer changes

Existing function signatures stay the same; each consumer calls the owner internally.

- **`analyze.compute_vlan_cutover_matrix`** (1548-1561, 1599-1603, 1678-1681): take the root and default election from the owner. The loop that records which VLANs each host appears in stays.
- **`analyze.stp_root_findings`** (7124-7165):
  - `accidental` and `misaligned` come only from `published` VLANs.
  - New key `ambiguous: [{vlan, reason, claimants, root_priority, identities}]`.
  - Never name one claimant as root.
- **`compute_migration_punchlist`** (8563-8590):
  - Add one item per ambiguous VLAN: Medium, category STP, title `STP root ambiguous (VLAN v)`.
  - Its devices are the claimants, and its references point at each claimant's `stp_roots.<h>.<v>` row, so the pointer-resolution test still passes.
  - If the one identity is at default priority, say so in the detail text.
- **`compute_remediation_plan`** (9457-9475): no configuration snippet for an ambiguous VLAN. Today it produces "the root for VLAN 30 is access1" and "on access1: raise its priority".
- **`compute_validation_plan`** (10293-10301):
  - Published VLANs: unchanged.
  - Each claimant of an ambiguous VLAN: check `Spanning-tree root for VLAN v ambiguous — reconcile before cutover`, command `show spanning-tree vlan v bridge`, severity High, `evidence_state="review"`.
- **`compute_nrfu_commands`** (854-872):
  - A claimant in an ambiguous VLAN gets the expected text `AMBIGUOUS — this bridge and N-1 other collected bridge(s) report being root for VLAN v (<reason>); reconcile before accepting`, with `evidence_family="STP"` and `evidence_state="review"`.
  - Rows for switches that observe the root but do not claim it: unchanged.
- **`compute_device_dossiers`** (12590-12593, 12626-12630, 12708):
  - `stp_root_vlans` counts only VLANs where the host is the published root.
  - New key `stp_root_ambiguous_vlans`.
  - The +1 impact and the CR-03 "root bridge on degraded hardware" pattern apply to published roots only.
  - Coordinate with G49, which edits the same function.
- **`excel.write_stp_roots_sheet`** (3445-3520):
  - Rows are published plus ambiguous VLANs.
  - For an ambiguous VLAN: Root switch `[AMBIGUOUS] N claim root: …`, priority shown only if there is one identity with one priority, Accidental and Aligned both `HEALTH_NOT_OBSERVED`, warning fill.
  - Headers unchanged.
- **`excel.write_vlan_cutover_sheet`** (6116-6130):
  - Driven by state: published gives yes/no; ambiguous gives `undetermined (root ambiguous)` plus the claimant list in STP Root; `not_observed` stays blank.
  - An old row without a state and with `None` must never render "no".
  - Headers unchanged.
- **`archreview`**:
  - L2-1 (473-500): counts published roots only. Ambiguous VLANs are disclosed. If there are only ambiguous VLANs, the verdict is `not-assessable`, not "no explicit root observed".
  - L3-4 (799-802): published roots only.
  - Sentences stay byte-identical when nothing is ambiguous.
- **`design.py` §2.2** (480-492): published counts, plus an ambiguity sentence when there is any.
- **`design_advisor`**:
  - `_signals` (1595-1614): count VLANs, not claims per host. Add `stp_ambiguous_root_vlans`, `_vids` and `_claimants`.
  - `_d_stp_root_determinism` (3699-3712): fires if accidental or ambiguous. The existing sentence stays byte-identical when the ambiguous count is 0, and an ambiguity clause is appended otherwise.
- **`detector_schema.py:179-205`**: extend `abstains_when` on both STP detectors with "root ownership ambiguous …". `design_kb.py:3705` wording is optional.
- **`failover`**:
  - `_current_root` delegates to the owner. A single claimant whose observers disagree now abstains.
  - `compute_failover_readiness` counts each ambiguous VLAN in `n_stp_roots` and `n_stp_indeterminate`, with an `at_risk` row `{kind:"stp", vlan, host: None, claimants, reason}`. This keeps the `l2_rehearsal.py:352` invariant.
- **Explorer**:
  - One shared helper `stpRootElection(vid)`. It reads `SNAP.vlan_cutover[].stp_root_state`, `claimants` and `default_election` when present. For older snapshots it falls back to the same counting rule over `SNAP.stp_roots`, skipping `is_mst` rows.
  - `stpRootFor` returns only the unique root, or "".
  - `stpRootCard` lists ambiguous VLANs and uses both the 32768 and 32768+VLAN priority tests; today it only checks 32768+VLAN.
- **No change needed:** `build.py:167-171`, `stp_topology` per-host baseline, `protocol_deltas`, `cutover_sim`, `l2_rehearsal`, `analyze.py:4859` (subject presence).

## 4. Failing tests to write first

Fixture **F**, built from real parser output:
```python
F = {"access1": parse_spanning_tree_root(fx._ACCESS1["show spanning-tree"]),
     "access2": <the same>,
     "core1": parse_spanning_tree_root(fx._CORE1["show spanning-tree"])}
```
Today this yields `accidental=[{vlan:'30', host:'access1'}]`, `vlan_cutover` 30 = `('access1', True)`, and readiness `n_stp_roots=1`.

**`tests/test_stp_root_election.py` (new)**

1. **F:**
   - VLAN 10 is `published` / `single_claimant`, root core1, observers `[access1, access2]`, default election False.
   - VLAN 30 is `ambiguous` / `duplicate_bridge_identity`, root None, claimants `[access1, access2]`, identities `[{root_address:'cccc.0003.0003', root_priority:32798, claimants:[access1, access2], observers:[core1]}]`, default election None.
2. **Two identities:** `{a:{30:(32798,'aaaa.0000.0001',True)}, b:{30:(32798,'bbbb.0000.0002',True)}}` gives `ambiguous` / `multiple_root_identities` with 2 identities.
3. **One claimant, disagreeing observer:** `{a:(24606,'aaaa…',True), b:(24606,'cccc…',False)}` gives `ambiguous` / `multiple_root_identities`.
4. **Observers only:** one agreed identity, no claimant, gives `not_observed` / `root_not_collected` with default election None. Rows with no root lines (core2 style) give `no_root_evidence`.
5. **Malformed:** `is_root:"true"` next to a real claimant gives `ambiguous` / `malformed_root_rows`, never `published`.
6. **Priority conflict:** priorities 24586 and 24606 on the same address give `published`, `root_priority=None`, `root_priorities=[24586, 24606]`, default election None.
7. **Priority rules:** a bare 32768 gives default election True (legacy with extended system ID off); the string `"24576"` gives an integer; inf, a bool or a dict gives None with no crash.
8. **MST:** MST rows appear only under `mst_instance`. MST instance `"1"` next to PVST VLAN `"1"` on different hosts do not merge.
9. **Whole-class guard over F plus a VLAN 30 SVI on core1.** Every consumer abstains for VLAN 30:
   - `vlan_cutover` 30 has `stp_root == "[AMBIGUOUS]"`.
   - `stp_root_findings` has no VLAN 30 in `accidental` or `misaligned`, and one `ambiguous` entry.
   - The punch list has only `STP root ambiguous (VLAN 30)`.
   - The remediation plan has no `stp-*` item for VLAN 30.
   - The validation plan has no `…VLAN 30 unchanged` check.
   - NRFU has no expected text `This bridge is the root for VLAN 30`.
   - Dossier `stp_root_vlans` is 0 and `stp_root_ambiguous_vlans` is 1 for access1 and access2.
   - Architecture review L2-1 does not say "access1 roots".
   - Readiness counts VLAN 30 as indeterminate.
   - Neither STP sheet has a cell that is exactly `access1`.
10. **Sample regression:** feed the sample's `stp_roots` into `compute_vlan_cutover_matrix({}, stp)`. Row 30 is ambiguous with 17 claimants and observers `[core1]`. Rows 20, 40 and 41 have default election None.
11. **Optional source ratchet:** every `is_root` read in `cisco_toolkit/*.py` and in the explorer is either the owner or on a declared per-host allowlist (parse, stp_topology, protocol_deltas, cutover_sim, l2_rehearsal, `analyze` subject presence).

**Additions to existing test files**

- **`tests/test_vlan_cutover.py`:**
  - VLAN 20 `stp_root_default_election is None` (fails today, which gives False).
  - Published rows carry `stp_root_state="published"` and `claimants=[host]`.
  - The sheet renders an ambiguous row as `[AMBIGUOUS]…` / `undetermined`.
  - A row with `None` and no state does not render "no".
- **`tests/test_explorer_render_safety.py`** (node harness): for F, `stpRootFor(30) === ""` and `stpRootCard()` contains "ambiguous" and not "rooted at … access1". Add a JS-vs-Python parity check over the sample's `stp_roots`.
- **`tests/test_failover.py`:** single claimant plus a disagreeing observer gives `compute_stp_failover(snap, ["a"])` indeterminate. Readiness counts ambiguous VLANs as indeterminate.

**Existing fixtures that encode the defect** (fix them to use one VLAN per host, keeping their intent):
- `tests/test_r6_excel_html_caps.py:239-251`: 14 hosts all claim VLAN 10.
- The next test in that file: 5 hosts claim VLAN 10.
- `tests/test_vlan_cutover.py:139-141` is still valid, because it is a single claimant.

## 5. Coordination and open decisions

- **Same functions as G13 and G49.** `compute_vlan_cutover_matrix` is also edited for G13 (the `wave` label) and `compute_device_dossiers` for G49. Land them together or rebase carefully.
- **Recommendation for the lead:** keep the default election undetermined for `root_not_collected`, even though observers do see the remote root's priority. The alternative is to publish it from the observers' agreed priority. This also keeps the matrix, the findings and the design decision consistent.
- **The sample fixture itself** (distinct bridge MAC per clone, drop VLAN0030 when VLAN 30 is not carried) belongs to #579's `build_sample.py`. Leave it for after the merge; the contradictory data is also a useful demo of the ambiguity detection.

## 6. Snapshot sections the fix will move

These were checked with the prototype for the owner and the `vlan_cutover` rows. Sections that need the full pipeline are marked as expected rather than measured.

**Golden `tests/golden/snapshot.json`** (VLAN 10 and 30 each have one claimant):
- `vlan_cutover`: every row gains `stp_root_state`, `stp_root_reason`, `stp_root_claimants` and `stp_root_identities`. VLAN 20's `stp_root_default_election` goes from `false` to `null`.
- `device_dossiers.per_device[*]`: gains `stp_root_ambiguous_vlans: 0`. G49 moves this section too.
- `detector_schema.detectors[stp-accidental-root, stp-root-gateway-misaligned].abstains_when`.
- Expected to stay byte-identical: `sheet_schema.json` (headers unchanged) and `schema_census` (count and kind unchanged). `punchlist`, `remediation_plan`, `validation_plan`, `nrfu_commands`, `architecture_review` and `design_blueprint` should also stay identical, provided the sentence templates are unchanged when nothing is ambiguous.

**Sample `webapp/sample_data/sample_fleet.snapshot.json`** (to regenerate after #579):
- `vlan_cutover`:
  - Row 30 becomes `[AMBIGUOUS]` with 17 claimants and default `null`.
  - Rows 20, 40 and 41 go from `false` to `null`.
  - All rows gain the new keys.
- `punchlist`:
  - Removed: `STP root != gateway (VLAN 30)`, `Accidental root (VLAN 30)`, and CR-03 for access13 to access17 (CR-03 for core1 stays).
  - Added: `STP root ambiguous (VLAN 30)`.
  - Priorities renumber.
- `remediation_plan`: loses the two VLAN 30 STP items, their per-device entries and the counts.
- `validation_plan`: the 17 VLAN 30 root checks change from Medium "unchanged" to High ambiguity reviews; summary and per-wave counts change.
- `nrfu_commands`: the 17 cases for `show spanning-tree vlan 30` change.
- `device_dossiers`: 17 access hosts go from 1 to 0 on `stp_root_vlans`, gain the new key, lose CR-03 (five of them), and their risk ranking changes.
- `architecture_review`: L2-1 verdict and text.
- `design_blueprint`: the `dc-stp-root-determinism` evidence text, magnitude and devices, plus the linked `design_nrfu` item.
- `detector_schema`: the two `abstains_when` texts.
- Check on regeneration: anything that totals punch-list items, such as the executive brief.
- `atlas-scope/src/data/fabric.json`: its 9 `stp_root_vlans: 1` entries were probably compiled from the sample's dossiers (not verified), so they would move too. That file is owned by #579.

Prototype script: (a session scratch path, not retained)

---

## G49

# G49 design: separate "input absent" from "input present, no findings" in the device risk dossier

The dossier decides most "not assessed" (`na`) and "ok" verdicts from whether a host is missing from an input, not from a record of whether the evidence was collected. The fix is one rule applied to all 11 axes: each exposure carries a new `input_state`, taken from a per-host record of collection whose producer covers every collected host. Most of the change is in `compute_device_dossiers` and its three call sites; follow-on 5 below is a separate change in `excel.py`.

I built a prototype of the rule in the scratchpad and ran it against the golden and sample snapshots and the dossier-related test files. The work tree is unchanged (`git status` clean, HEAD 9a2a677c). The prototype was also checked against the unchanged producer: recomputing today's dossiers from the golden (with the test's pinned lifecycle) and from the sample reproduces the stored `device_dossiers` exactly.

## 1. What each axis does today

All references are `cisco_toolkit/analyze.py` unless stated. The docstring at 12345-12347 promises "absence of evidence is state 'na'".

| Axis | Lines | How absent vs. no-findings is decided today | Defect |
|---|---|---|---|
| Health | 12408-12419 | No row → na; `Insufficient Data` → na; anything else → ok | An unrecognized band reads ok ("health Great" is ok, confirmed) |
| Hardware EoL | 12421-12436 | No row → na; `Unknown` → na; unrecognized → na | None; this is the model the others should follow |
| Software risk | 12438-12462 | Uses `config_assessable` from software_risk's own row | Correct |
| Control plane | 12464-12481 | `collected` False → na; otherwise Hot/Elevated, else ok | Collected output with no CPU/memory figure recognized (`band` Unknown, 11535-11536) reads "ok — control-plane capacity OK" (confirmed) |
| Operational logs | 12483-12492 | `collected` False → na; otherwise ok | A captured log with 0 parsed events reads "ok — no flagged operational events" (confirmed) |
| Security posture | 12494-12504 | No row → "no captured running-config"; no failures → ok | A row with no pass/fail check reads "CIS checks pass" (confirmed) |
| Config hygiene (G49) | 12506-12509 | Not in `config_hygiene` → "no captured running-config" | Wrong reason; details after the table |
| Golden drift | 12517-12529 | No row → "not in the drift baseline" | The absence actually means "no running-config" (the producer emits one row per captured config, 10687-10688 and 10770-10777). The ok label hides that the sample's baseline is only 2 directives |
| QoS posture | 12531-12541 | No row, or not assessable → "full running-config not captured" | If the QoS phase fails (`_default={}`, COLLECT_PARSE:4827-4828) every host gets that same wrong reason |
| Physical | 12543-12562 | Rows present, or host health-scored, → ok; otherwise na | Acceptable |
| Protocol | 12564-12573 | Host health-scored and no High/Medium row → ok | Reads absence from the sparse `protocol_health` list as clean. `docs/ssot.md:26` says to read `protocol_assessability` instead. In the sample, podacc1 and podacc2 have 7 of 7 families `not_collected` yet read "ok — protocol health clean" (confirmed) |

Why Config hygiene is wrong: `parse_config_hygiene` returns `{}` when a config defines or references no ACL, route-map, prefix-list or object-group (parse.py:4985-4986). The axis registry then drops the empty result (COLLECT_PARSE:3347 and 3422-3425), so the section only holds hosts that have such structures. In the sample, 20 hosts carry "no captured running-config", but 17 of them have a captured config. The parse ledger proves it: each has a `parse_config_hygiene` receipt with `zero_yield=1, errors=0`.

## 2. The rule

- **R0, vocabulary.** Each exposure gains `input_state`, one of the existing `ssot.ABSTENTION_STATES` (ssot.py:256): `published`, `collected_but_empty`, `not_collected`, `analysis_unavailable`. The field is additive.
- **R1, records not membership.** Add a closed registry `analyze.DOSSIER_AXIS_INPUTS` (axis → the sections it reads; this is the class denominator) and `DOSSIER_EMPTY_IS_CLEAN = {"Config hygiene", "Physical"}`. An axis takes `input_state` from a per-host record whose producer covers the whole collected fleet, never from whether the host is a key in a sparse section.
- **R2, state follows input.** risk, watch or ok are allowed only when `input_state` is `published` or `collected_but_empty`. ok with `collected_but_empty` is allowed only for the axes in `DOSSIER_EMPTY_IS_CLEAN`. Everything else is na. An unrecognized band or value is na with `analysis_unavailable`.
- **R3, one running-config capture record.**
  - The record is `software_risk.per_device[h].config_assessable` (11310, 11366-11397; `bool(text.strip())` over all hosts, the config text and the device roster). Fall back to `qos_audit.per_device[h].assessable` (11059-11065). If neither has a row, the state is unknown.
  - If the record says False, Security, Config hygiene, Golden drift and QoS are na with `not_collected` for that host, even if a row exists. That covers whitespace-only captures. Software risk keeps its software-version layer.
  - If the record says True but the axis's own row is missing:
    - **Config hygiene:** `collected_but_empty` (so ok, "screened — no named structure to dangle") only if the `parse_yield` receipt for (`parse_config_hygiene`, host, `show running-config`) has `zero_yield ≥ 1` and `errors == 0`. Otherwise it is `analysis_unavailable`.
      - Receipt structure: cmdio.py:378-414.
      - The receipt's device name is `safe_fs_name(hostname)` (COLLECT_PARSE:4166-4167). Match exact name first, then that mapping, as in coverage_matrix.py:128-135.
      - The traffic-assurance code already uses parse receipts as positive proof (traffic_assurance.py:450-451).
    - **Security, Golden drift, QoS:** `analysis_unavailable`. These producers always publish a row for a captured config (parse.py:4667-4668, 10770-10777, 11059-11105), so a missing row means something failed.
- **R4, failed phases.** Add a keyword-only argument `input_failures`: the `(direct, unattributed)` tuple returned by `ssot.failed_sections` (ssot.py:389-421).
  - A section in `direct`, or unattributed and deep-empty (the same rule as ssot.py:479-485), makes every axis that reads it `analysis_unavailable`.
  - Those axes must never be labelled "not captured".
  - This also partly closes the known limitation at ui_projection.py:188-194.
- **R5, Protocol reads the receipt.**
  - A High or Medium `protocol_health` row still wins.
  - Otherwise, if at least one family is in `PROTOCOL_ASSESSABILITY_AUTHORIZING_STATES` (4312-4314), the axis is ok and the label names "k of 7 families".
  - If none is: `collected_but_empty` when a family is `captured_empty`, `captured_no_record` or `not_running`; otherwise `not_collected`; either way na.
  - If no receipt is supplied: na with `analysis_unavailable` (decision D1 below).
- **R6, captured but nothing to judge is not clean.** Control plane (collected, band Unknown), Operational logs (collected, 0 events), Security (no pass/fail check) and Golden drift (no baseline) become na with `collected_but_empty`.
- **R7, ok labels say what was checked.**
  - Golden drift: "matches the 2-directive majority baseline".
  - Protocol: "clean where observed — 1 of 7 protocol family assessed (STP)".
  - The prototype's pluralisation needs a fix ("1 of 7 protocol family" should read "families").

**New keyword-only arguments** (default None): `protocol_assessability`, `parse_yield`, `input_failures`. Every call site must pass them:
- `COLLECT_PARSE_V3_23_0.py:6240-6250` (the adapter) and the `_actx` context at 4858-4869. `protocol_assessability` is already in the context. Add `parse_yield` from `parse_yield_report()`, which is already called before this phase with identical content (4724-4729). Add `input_failures` from `ssot.failed_sections({"assessment_integrity": {"failed_phases": [labels of failed _PHASE_TIMINGS entries]}})`.
- `cisco_toolkit/context.py:43-77`: add the two new fields.
- `webapp/backend/app.py:2839-2848`: pass `snap.get("protocol_assessability")`, `snap.get("parse_yield")` and `ssot.failed_sections(snap)`.
- `tests/test_pipeline_golden.py:370-404`: `_DOSSIER_SECTIONS` must include the new inputs. Derive it from the registry so a new input cannot be forgotten; otherwise the wall-clock test fails.
- `tests/test_context_adapters.py:36-44`.

**Consumers of the exposure states.** None needs a change for correctness, because they all key on `state` and `n_na`:
- analyze.py:12575-12578, 12601-12644 (compound patterns) and 12676-12677.
- excel.py:4751-4791 (the canonical coverage rule and its cases) and 4794-4860.
- deck.py:63-95; runbook.py:55-89; mcp_server.py:73-114, 154-155, 575.
- blast_radius_explorer.html:4755, 6986-6991, 12566-12567, 12624 (demo data at 2469-2522).
- webapp/frontend/src/pages/Snapshot.tsx:535-545, 551-596, 624-688.
- The punch-list fold (analyze.py:8854-8870) and executive brief (12209) read only `compound` and `summary`, which do not change.

Rendering `input_state` in these views is optional.

## 3. Failing tests to write first

Proposed file: `tests/test_dossier_input_state.py`. For every case below I ran the real producer and confirmed today's output.

1. **Config hygiene screened empty (the headline), from real producers.**
   - Setup: a temporary `acc/show_running-config.txt` with about 15 lines and no named structures. Call `cmdio.reset_parse_ledger()`. `security={"acc": build.build_security(c2f)}`. `build.build_config_hygiene(c2f)` returns `{}`, so `config_hygiene={}`. Build `compute_software_risk`, `compute_golden_drift` and `compute_qos_audit` over the same text, and `parse_yield=cmdio.parse_yield_report()`.
   - Expected: Config hygiene is ok, `collected_but_empty`, and its label does not say "no captured running-config". No running-config axis is `not_collected`.
   - Today: na, "no captured running-config".
   - Variants:
     - `parse_yield=None` → na, `analysis_unavailable`.
     - A parser error receipt (make `parse_config_hygiene` raise inside `_safe_parse`) → na, `analysis_unavailable`.
     - No config text and `config_assessable` False → all four config axes na, `not_collected`, "no captured running-config".
2. **Sample consistency.** Compute dossiers from the committed sample's input sections, which this fix does not change. access13's Config hygiene must be ok. For every host, the set of config axes that are `not_collected` must be either empty or all four.
3. **Registry ratchet.** Across dossiers built from empty input, the golden inputs, the sample inputs and case 1:
   - every `input_state` is in `ssot.ABSTENTION_STATES`;
   - a state other than na implies `published` or `collected_but_empty`;
   - ok with `collected_but_empty` implies the axis is in `DOSSIER_EMPTY_IS_CLEAN`;
   - the emitted axes equal `tuple(DOSSIER_AXIS_INPUTS)`.
4. **Failed phase**, parametrised over every registry section that has a label in `ssot.PHASE_SECTIONS`.
   - Setup: the section set to `{}` or `[]`, plus `failed_sections({"assessment_integrity": {"failed_phases": [label]}})`.
   - Expected: that axis is na with `analysis_unavailable`, and its label never says "not captured".
   - Today: with `qos_audit={}` and `config_assessable` True, QoS reads "not assessable — full running-config not captured".
5. **Control plane with no figures.**
   - Setup: `compute_platform_health({"h": {"cpu": {}, "memory": {}, "system": {"uptime": "1d"}}})`, health Good.
   - Expected: na, `collected_but_empty`.
   - Today: ok.
6. **Log captured, zero events.**
   - Setup: `compute_syslog_intelligence({"h": "Syslog logging: enabled ...\nLog Buffer (8192 bytes):\n"})`, which gives `collected` True and 0 events.
   - Expected: na, `collected_but_empty`.
   - Today: ok.
7. **Protocol with an all-missing receipt.**
   - Setup: `compute_protocol_assessability(["h"], {"h": {}}, {"h": {}}, [])` (7 of 7 `not_collected`), health Excellent.
   - Expected: na, `not_collected`.
   - Today: ok.
   - Control cases: a receipt with STP assessed or partial plus an Info row → ok with a "1 of 7" label. No receipt → na, `analysis_unavailable`.
8. **Unrecognized health band.** Band `"Great"` → na, `analysis_unavailable`. Today: ok.
9. **Security with nothing evaluated.**
   - Setup: `{"h": {"findings": [], "summary": {"pass": 0, "fail": 0, "na": 3}}}`.
   - Expected: na, `collected_but_empty`.
   - Today: "CIS checks pass".
10. **Golden drift.**
    - Setup: three configs, plus a fourth host whose `config_assessable` is False.
    - Expected: the fourth host reads na, `not_collected`, "no captured running-config" (today it reads "not in the drift baseline"). The ok label names the baseline size and mode.
11. **Call-site closure.** The adapter, the `app.py` recompute and the golden recompute each pass every keyword argument in the signature.

## 4. Existing tests that will need changes

With the prototype swapped in, exactly 10 existing tests fail. Assertions should not be weakened; the fixtures should be fixed.

- `tests/test_analyze_absence_is_not_health.py::test_dossier_insufficient_data_host_renders_na_not_clean` (193-197). It asserts Protocol ok "by silence", which is the defect itself. It should supply a receipt with one assessed family.
- `test_deck.py` (3 tests, lines 640/649/668/677/683), `test_runbook.py` (2 tests, 745-770) and `test_mcp_server.py` (4 tests, 591-605 and on). All three files copy the same hand-built fixture: `security={"h": {"checks": ...}}` and `software_risk` rows with a `band` key. That shape is not what the real producers emit.
  - Unassessed fixture: n_na goes 8→9 (Protocol correctly abstains).
  - "Assessed" fixture: n_na goes 5→7 and becomes thin (half or more of the axes not assessed).
  - Fix: one shared fixture module built from real producers (`parse_security`-shaped findings and a `compute_protocol_assessability` receipt). That restores 5 of 11 for the assessed case; the unassessed constants move 8→9.

All other dossier-related tests pass under the prototype, including the explorer tests that run in Node and the webapp backend tests.

## 5. What regeneration will move

Only `device_dossiers` moves; no other section changes. `summary`, `note`, ordering, `risk_index`, `risk_band`, `compound` and `verdict` are identical, so the punch-list references into `/device_dossiers/per_device/i/compound/j` stay valid.

**`tests/golden/snapshot.json`** (measured with the pinned lifecycle):
- Every `per_device[*].exposures[*]` gains `input_state` (3 devices × 11 axes).
- `per_device[1]` (access1): `n_na` 3→2; `exposures[6]` Config hygiene na→ok; `exposures[10]` Protocol label changes.
- `per_device[2]` (core2): `exposures[7]` Golden drift label becomes "no captured running-config"; `exposures[10]` Protocol label changes.
- core1 gains only the new field.

**`webapp/sample_data/sample_fleet.snapshot.json`**:
- All 23×11 exposures gain `input_state`.
- access1 to access17: `n_na` down by 1; Config hygiene na→ok; the Golden drift ok label names the 2-directive baseline; Protocol label changes.
- dist1, dist2, core2: Protocol label changes; core2's Golden drift label changes.
- podacc1 and podacc2: `n_na` 8→9; Protocol ok→na; Golden drift label changes.

The state and `n_na` changes are exact. The label strings depend on the final wording.

## Decisions for you

- **D1, Protocol with no receipt.** I recommend failing closed (na), which is what causes the 10 fixture changes in section 4. The softer option keeps today's "health-scored means clean" behaviour when no receipt is supplied. That avoids the fixture edits, but leaves direct callers and older snapshots reading absence as clean.
- **D2, how Config hygiene proves "screened, nothing found".** I recommend requiring a `parse_yield` receipt. The alternative is to make `config_hygiene` publish an empty record for every captured config. That fixes it at the producer, but it also moves the `config_hygiene` section, the architecture review's OPS-2 row, the Excel sheet and the explorer card, so I would not do it in this slice.

## Related defects of the same kind, outside G49's exposure scope

1. `excel.py:3431-3435` counts the sparse `config_hygiene` records and calls them "device(s) with a collected running-config". It is pinned by `tests/test_audit5_false_health.py:208-218`.
2. `parse_security` checks `if not output` without stripping whitespace (parse.py:4667), and the capture store keeps whitespace-only text. A blank capture therefore produces made-up CIS failures. R3 contains this in the dossier only.
3. The dossier verdict still says "No stacked risk — routine migration handling" for podacc1 and podacc2 at 9 of 11 na (12696-12697). The producer does not apply the thin-coverage rule that its 5 consumer copies apply.
4. On the impact side, a missing or failed `failure_impact` falls back to impact 1, "no modeled reachability impact" (12581-12609).
5. G44 (the health verdict inheriting the "scored without security" caveat) is not addressed here.

Files are in (a session scratch path, not retained):
- `g49_proto.py`: the prototype of the rule
- `g49_plugin.py`: the pytest plugin that swaps the prototype in
- `run2.txt`: output of the test run under the prototype