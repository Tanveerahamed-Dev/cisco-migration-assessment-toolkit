# W51 contract train: hosted CI round 1 and the #629 carry (2026-10-09)

Row W51, branch `claude/train-contract`, draft PR #630. This record covers the first hosted test run of the train
and what changed in response. The per-slice records stay where they are (W28, W34, W37 to W44 validation docs); this
one owns only the train-level findings.

## Hosted evidence read

Hosted CI on #630 head `6ad57ed9` (Tests, Python 3.12, ubuntu; job `113728958008`) failed 14 tests and passed the
rest. The full log was read once; every traceback below comes from it. No test, build or engine run happened locally
(owner rule): every verdict below rests on the hosted traceback, the test's own intent, and pure library calls on the
test's own fixture, rebuilt in a scratch script (never by importing a test module or calling a test function).

## #629 carried: `origin/claude/train-engine-sample` `f6323759` merged with a merge commit

W51 already carried #629 up to `01720e5b` and #628 at `30e425bb`. The merge brings the three W45 commits W51 did not
have: two board/record commits (`31d9b5b9`, `40ca4d96`) and `f6323759`, which fixes the two trust-input failures (see
below). #629's own merges of main `f797444e` and #628 were already in W51, so they bring no new content.

Five files conflicted:

| File | Resolution |
|---|---|
| `docs/NOW.md` | W51's rows kept; the W45 and W46 rows take #629's newer text; #629's W45 carry handoff block is kept beside the W51 entries; the Codex and W46 lines #629 placed lower are already present verbatim, so nothing is dropped or duplicated. |
| `docs/ssot.md` | W51's side: its failure-impact row is #629's text plus the W43 clause, and it carries the G41 row. |
| `tests/test_ui_projection.py` | W51's admission comment, a superset of #629's. |
| `webapp/backend/ui_projection_api.py` | W51's combined pins (view `55bc576f…`, list `ce6e9c45…`). Recomputed statically with `_native_schema_hash` on the merged tree: unchanged. #629's own extract reproduces its pins (`0553957c…`, `3ee0af7f…`); the pin comment now names them. |
| `webapp/tests/test_ui_projection_api.py` | W51's prospective pins, equal to the production pins above. |

No engine, golden, sample, `atlas-scope/` or distribution byte changes.

## Verdicts, one per hosted failure

### Fixed by the #629 carry (2)

`tests/test_ui_projection_trust_inputs.py::test_a_failed_register_phase_withholds_every_input_with_its_failure_record`
and `::test_every_case_validates_against_the_closed_schema`. W33 attributes a second phase ("Failure Impact
assessability") to `device_dossiers`, so the helper that asserted exactly one label was stale. `f6323759`
parametrizes over every label the SSOT owner attributes to the section. Probed on the merged tree: under either label
all 11 inputs are withheld as analysis unavailable with the failure record, the denominator stays published with the
one-hop caveat, and the full payload validates against the closed schema.

### Gateway risk: stale test precondition (1)

`tests/test_ui_projection_gateways.py::test_stored_evidence_of_another_gateway_withholds_the_sole_flag[secondary_address_on_another_vlans_svi]`
raised `KeyError: 'vrf'`. The case builder asserted `svi["vrf"] is None` on the sample's core2 `Vlan20`. The stored
sample has never carried that key: `html.sparsify_interfaces` drops InterfaceData's `''` default, so the key is
absent (checked on main, on `01720e5b`, on W39's own head `0f39e719` and on this head). The test's intent ("its VRF
was never read") holds: with the key absent and `run_config_observed` cleared, `_port_vrf` reads the VRF as
unreadable. **Test updated**: the precondition is `svi.get("vrf", "") == ""`. Probed: the sole flag is unverified
with the "hold an address in this VLAN's gateway subnet" reason and the `Vlan20` witness on the risk, the fhrp text
and the gateway list; the other VLAN's gateways stay published false; the inventory validates.

### Prefix-slice guard: a widened producer set exposed unreviewed slices (1)

`tests/test_ui_projection_inventory.py::test_i12_every_engine_cap_is_registered_or_reviewed` found 25 unreviewed
slices. **Why they became visible:** the guard walks every `analyze.<function>` this projection's source names. G05
(W40) added `AXIS_UNASSESSED`, naming `compute_syslog_intelligence`, `compute_qos_audit`, `compute_software_risk` and
`compute_platform_health`, and `AXIS_UNASSESSED_ABSENT`, whose prose names `compute_application_intelligence`,
`compute_segmentation` and `compute_multicast_intelligence`. W40's tests were written and never run, so the guard
first ran here. A replication of the walk (library code only, `CAP_SITES` read from the test file by AST) reproduces
the hosted set exactly.

**Test updated** (a reviewed `CAP_SITES` entry per slice; the guard itself is unchanged and still fails on any new
slice). From the AXIS_UNASSESSED producers the projection reads one summary count, `n_devices` and one per-device
field, each the full list's `len()`. From the prose-only producers it reads nothing. So 24 slices cut values no
projected value carries: host previews (`hosts_not_collected`, `hosts_not_assessable`, `hosts_config_not_assessable`),
per-device `top_messages`, finding and risk prose, and `cross_domain_risks` with its `len()`. None of these is read by
the projection or by `compute_executive_brief`, whose headlines the projection publishes. Their only readers are the
workbook and runbook deliverables.

**One is not clean, and is recorded as an open follow-up, not hidden.** `compute_application_intelligence` cuts each
domain's `vlans` list at 40 (`vlans_sorted[:40]`, with the full `vlan_count` beside it).
`compute_vlan_cutover_matrix` maps each VLAN's application domain from that cut list (`doms_of`), and the projection
publishes `vlan_cutover[].app_domain` and `criticality`. A domain with more than 40 VLANs would leave VLAN 41 onward
with an empty `app_domain`, which the projection reads as "no application domain maps this VLAN". That is a clean
absence that is not one. The defect is pre-existing on main; G05 only made it visible. Neither the sample nor the
golden reaches the cap (the largest domain has 5 VLANs). The entry says "OPEN FOLLOW-UP, not a clean exemption".
Closing it needs either a projection disclosure (a cut domain makes an empty `app_domain` not collected, and a
published one `engine_list_capped`) or an engine change. That is product scope beyond this fix round.

### Peer host: fixtures that contradict the producer's inventory count (2)

`tests/test_ui_projection_peer_host.py::test_two_owning_devices_are_unverified_with_every_observation_a_witness` and
`::test_an_owner_whose_rival_capture_did_not_parse_is_not_published`. Both add `r3` to the devices map without
counting it in `collection_completeness.summary.inventory` (still 2). The W51 second round reconciles that count with
the roster (`_inventory_reconcile`), and a record that does not reconcile is a coverage gap of the address index. The
second round already taught `test_a_sole_owner_over_an_incomplete_index_is_never_published` this, through
`_counted`, but missed these two. The new behaviour is correct and stricter: the producer counts every inventory
device, so a roster of three under a count of two may hide a device.

**Tests updated**: each fixture now counts `r3`, as the producer would (`_counted(snap, complete=1)`), so the
original properties are tested again. Each test also pins the new one:

- with two owners, the ambiguity still wins whatever the coverage, but the address no device carries is not
  collected, citing `/collection_completeness/summary/inventory`;
- the complete control left uncounted withholds `r2`, citing the same count.

Probed: every assertion of both tests, old and new, holds on this head.

### Failure-impact surfaces: fixtures without the blind-spot record (8)

`webapp/tests/test_impact_surfaces.py`:

- `test_keystones_never_rank_a_clean_bill_an_uncollected_neighbour_bounds`
- `test_an_unreadable_cable_row_is_a_bound_worded_as_unreadable_never_as_an_uncollected_neighbour`
- `test_a_wave_behind_an_uncollected_neighbour_is_not_assessed_and_its_control_renders_as_before`
- `test_a_lower_bound_worst_case_is_never_complete_and_an_exact_one_stays_complete`
- `test_a_row_with_an_empty_host_is_disclosed_like_one_with_no_host[]` and `[None]`
- `test_the_cutover_document_prints_a_lower_bound_as_at_least`
- `test_a_valid_empty_failure_impact_list_stays_an_empty_table`

One cause covers all eight. The `_snapshot` fixture, and the empty-list upload, carry no `collection_completeness`
record. The W51 second round deliberately reads a record the snapshot does not carry as a gap of the record's
coverage verdict (`_cc_coverage`: `absent`, not collected). So:

- the fleet qualifier marks every failure-impact list;
- each "exact control" picked up a "lower bound" note, a worst case that is not `complete`, or a "LOWER BOUND" in the
  cutover document;
- the empty list went from `collected_but_empty` to `not_collected`.

**Verdict: the new behaviour is correct and stricter, and the tests are updated. The code is not changed.**

The task brief offered the opposite reading as an example: an absent record "may add a qualification but must not
turn a collected section into not_collected". That reading was weighed and rejected, for three reasons:

1. **It would split one rule in two.** `_listing` has a single rule, older than W51: a qualified empty list is not
   collected ("an empty list is not a clean result"). That rule already turns a collected, empty fleet list into
   `not_collected` whenever the record lists a blind spot. An absent record rules out no blind spot, so it falls under
   the same rule. Exempting it would leave a `collected_but_empty` list that also carries the
   `fleet_lists_exclude_blind_devices` caveat, which says both "nothing of this kind" and "may exclude devices".
2. **The reviewed W51 design pins it.**
   `tests/test_ui_projection_unjoinable_rows.py::test_a_blind_spot_list_the_snapshot_does_not_carry_is_never_read_as_no_blind_spot`
   requires every fleet list to be qualified and an empty `failure_impact` and `structural_links` to be
   `not_collected` when the record is absent. That test is not among this run's 14 failures, and its file has no
   skip marker. Changing the code would break it.
3. **It is the doctrine.** "Not observed" never silently becomes "healthy". Without the record, nothing says every
   inventory device was collected.

What the fixtures got wrong is that they modelled no engine run: every pipeline run stores the record. So:

- `_snapshot` now stores the record the real producer writes for a fully collected fleet (`_complete_record`).
- A new test binds that record to `analyze.compute_collection_completeness`, run over real captured files with every
  essential capture present.
- The empty-list upload carries the record.

Every original property is then tested again: the clean controls are exact and `complete`, and the empty list stays
an empty table. The new W51 property is pinned on each surface:

- a new test, `test_a_snapshot_without_a_collection_completeness_record_bounds_every_ranking`, covers the keystones
  and the wave worst case: the measured ranking is unchanged, the note says it is a lower bound, and the worst case is
  not `complete`;
- the cutover-document test adds the absent-record control: the counts stay exact, never "at least", and the line
  adds "LOWER BOUND, the worst case may be larger";
- the empty-list test adds the absent-record upload: `not_collected` with the record's reason, and the tab shows the
  disclosure.

Probed with the real producers on the rebuilt fixtures:

- every assertion of the eight failing tests holds with the record;
- `test_keystones_never_rank_a_row_the_engine_could_not_simulate` and
  `test_the_worst_case_never_ranks_a_row_the_engine_withholds` still hold;
- every new assertion holds, including the producer binding and the cutover document text (python-docx read of
  `write_cutover_docx` output in scratch).

A wording note, not changed here (P3 follow-up). For an absent record, AssessHub's note reads "collection_completeness
carries 1 record(s) the engine cannot read …". The parenthesis then lists "a record that is absent", so the sentence
is accurate only by that parenthesis. A dedicated wording would need the projection to say which gap qualified the
list, since a published list carries no reason. The W51 second round pinned the current wording
(`test_the_blind_spot_note_never_calls_a_record_the_engine_cannot_read_a_blind_device`).

## Static checks run

- `py_compile` and `ruff check` on every changed Python file: clean.
- An AST collection scan of every changed test file: parametrize argnames accepted, fixtures resolvable (module,
  `conftest.py`, built-ins), no duplicate test names, imports resolve. 0 problems. A negative control with a bad
  argname, an unknown fixture, a duplicate and two bad imports reports all five.
- Native pins: recomputed statically, unchanged.
- Golden (`tests/golden/*`) and sample (`webapp/sample_data/sample_fleet.snapshot.json`): byte-identical. No engine
  file changed in this round.
- Rule 7: the repository privacy verifier passes, and a marker scan of `git log -p -m origin/main..HEAD` plus the
  staged diff finds 0 hits.

## Not verified here

- Every test above is written and has not been run. The hosted gates on the next pushed head are the acceptance
  evidence.
- Hosted legs other than py3.12 ubuntu were not part of this round's input.
