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

## Integration of the W51 absorb (2026-10-09)

`claude/w51-absorb` (`fdf91385`: W48 `a78d85ed`, W50 `add4b377`, W47 `db93b265`, plus the fix commit for the
review's findings (a)-(e); record `docs/w51-absorb-validation-2026-10-09.md`) is merged into this train as `2b082c32`,
on top of the round-1 answers above (`3296626d`).

**Conflicts.** Only `docs/NOW.md` conflicted. The W45 and W46 rows keep #629's newer status. The W28, W29 and W30
rows take the absorb's "carried by W45" status. `docs/w45-engine-sample-train-2026-10-09.md` auto-merged. Finding (e)
is then applied to both now that #629's head is on this train: webapp-ci run `37897012004` concluded `cancelled`
after all six jobs passed, and the succeeded run is `37897790220` on `40ca4d96` (artifact `11600639221`). Both runs,
their jobs and their artifacts were re-read from the GitHub API.

**Semantic overlap.** `webapp/tests/test_impact_surfaces.py` merged cleanly. This round's `_snapshot` fixtures carry
the producer's `collection_completeness` record. The absorb's new tests read the stored sample, not `_snapshot`. The
absorb's wave rule (`engine.wave_blast` with both fleet counts, `zero_bound`, hostless rows observed) was probed as
pure calls (`cutover.build_plan`, `summary.summarize`, `summary.impact_view`, `impact_assessability.wave_blast`). The
fixtures were rebuilt from helper source copied out of the test file. No test function was called. Results:
- every `_snapshot`-based wave keeps the outcome its test asserts;
- none has a largest count of 0 beside an unranked switch, so `zero_bound` never fires there;
- the record-less case still words the unread record through `summary._R_IMPACT_BLIND_UNREAD`, which is now the
  owner's `R_WAVE_FLEET_BLIND_UNREAD` with byte-identical text.

**One defect found and fixed (`webapp/backend/engine.py`, comment only).** W50 added a comment that names
`tests/test_protocol_assessability.py`. That file's receipt-reader census matches the receipt name anywhere in a
scanned file, comments included. It therefore counted `engine.py` as an unclassified 19th reader, which would fail
`test_every_module_that_reads_the_receipt_is_classified_with_a_mechanical_proof`. The comment is reworded on the same
line; `engine.py` does not read the receipt. With the copied helpers, the census is back to 18 readers, all
classified, every class proof holds and there are no hand-list sites.

**Static checks on the integrated tree:**
- every changed `.py` compiles (in memory, `SyntaxWarning` as an error);
- `ruff check` with the repository's `ruff.toml` is clean;
- an AST shadow scan finds no nested def rebound in its scope and no name read before its local binding (63 files; a
  planted control is flagged twice);
- the AST collection scan of all 36 changed test and conftest files finds 0 problems (a planted control is flagged
  seven times);
- a module-attribute scan finds every `alias.attr` the changed files read defined in its module (2,122 reads; only
  `__file__` reported);
- the changed frontend files' relative imports all resolve to exported names (65 imports);
- native pins recomputed with `_native_schema_hash`: view `55bc576f…`, list `ce6e9c45…`, unchanged. As a method
  check, extracts of `6ad57ed9`, `3296626d` and `fdf91385` reproduce that pair, and `f6323759` reproduces #629's
  `0553957c…` / `3ee0af7f…`;
- the offline OpenAPI export is byte-identical to `6ad57ed9`'s (sha256 `0ba06259…`, 331 components, 40 paths), and
  `openapi.ts` is unchanged since that head, whose hosted `api:check` passed (frontend job `113729028501`);
- vocab bijection (v1 mirror): 59 string enums in 50 token sets, 19 ranked and 31 unranked, none doubled,
  unclassified or invented;
- LF receipts, from the byte-custody helper logic: 183 / 38 / 145 / 1, all equal to the fixture. The effective HEAD
  and worktree sets are equal, and the full byte-custody helper passes. W50's new `eol=lf` rule for
  `tests/fixtures/operator_evidence_v1/*.json` lies outside the policy domains;
- the i12 prefix-slice walk visits 170 functions and finds 60 slices, all reviewed, none stale.

Golden, sample, `atlas-scope/` and `webapp/frontend/dist` are byte-identical to `6ad57ed9`. The frontend source
changes (W47, W50, the G21 facets), so the tracked dist is stale until the hosted handoff of the pushed head is
verified and imported.

## Hosted Vitest failure on `8f47dbfa`, and the dist import (2026-10-09)

**Vitest (fixed in `57e64f02`).** Webapp-ci run `37916648764` on `8f47dbfa` failed 1 of 500 Vitest tests in frontend
job `113774440827`; Distribution contract job `113774360599` showed the same single failure. The test is W47's
`Snapshot.test.tsx` case "at most one tab stop per row", written and never run. It expects the per-row disclosure to be
named "Reasons for core2: 6 value(s) not measured", but the computed name was "Reasonsfor core2: …".

The cause is in dom-accessibility-api (0.5.16 and 0.6.3, both in the lock). It trims an inline child element's
accumulated text and adds no separator for an inline element, so the leading space inside the `sr-only` span was lost.
The space is now its own text node between the label and the span. The test is unchanged.

The same run's `ui-projection-contract-7b8ae69b…` observation (artifact `11609549567`) observed the declared native pins
(view `55bc576f…`, list `ce6e9c45…`). Its `openapi.json` equals the offline export above, and its `openapi.ts` equals the
tracked file.

**Dist import.** The verification follows the W29/W46 precedent (`docs/w13-coverage-validation-2026-10-05.md`).
- **Expected record, selected from Git before the archive was read.** GitHub's tested merge for pushed head `57e64f02`
  is `e808ec12` (parents main `f797444e` + `57e64f02`). Its tree `aa87586e` equals the head tree. The record covers 149
  committed inputs, as `frontend_build_handoff.py` defines them: `webapp/frontend/**` without `dist/`, plus its five
  processing inputs. Against the W51 head `6ad57ed9`, 20 frontend source inputs changed: W47, W50, the G21 facets and
  the fix above.
- **Run and job.** Webapp-ci run `37917351322` (pull_request, attempt 1); frontend job `113779670890` succeeded: api:check
  ("Generated API types match the actual app schema"), Vitest 34 files and 500 tests, and the build.
- **Archive.** Artifact `11610072540`, `frontend-dist-handoff-57e64f0217d20337d55c7fad244ee89e6a23b295-37917351322-1`,
  568,793 bytes, sha256 `e226c06eb947fff2a79e58248e0f937e0fc05cfd93d3fd89e974e3901cf99d5b`. This equals the API digest
  and the job log's upload digest and final size. The identity was unchanged on a closing API re-read.
- **Closed seven-file inventory:** `source-before.json`, `handoff.json` and 5 dist members. There are no directory,
  duplicate, absolute, backslash, parent or special entries.
- **Source records.** Both equal the expected record, and `source-before.json` is byte-canonical. `handoff.json` has a
  closed key set, `github_head` `57e64f02`, run `37917351322` and attempt 1.
- **Non-promoting fields hold:** `GENERATED_INPUT_FOR_REVIEW_ONLY`, `release_authority` false,
  `final_source_rebuild_required` true.
- **Toolchain.** Node v24.19.0 and npm 11.17.0 equal the job log's environment details, and the member census equals
  the vite 8.2.4 build log.
- **Members.** The 5 member hashes and sizes pass, and so does the canonical path-aware marker policy (0 hits). The
  index asset links resolve, and every asset is reachable from `index.html`.
- **Negative controls are refused:** one altered input hash, a wrong npm version, the `8f47dbfa` tested-merge record
  (`7b8ae69b`) and W45's (`7eb1868a`). The same verifier passes W45's known handoff (artifact `11601230589`) against its
  own record and refuses it against another.

Only the 5 verified generated members are imported: `index.html`, `assets/index-BWGrS9k2.js`,
`assets/index-DGaCRfa4.css`, `assets/Topology3D-B-untAXO.js` and `assets/react-force-graph-3d-BlVMPyfx.js`. The four
superseded files inside the owned dist directory are removed, and each indexed blob equals its member. No source,
test, package or lock changes. This is review input: the new head must reproduce these bytes in fresh hosted gates.

## Fix round 4: the two hosted failures on `ad9aba07` and the three-lens review (2026-10-09)

**Hosted evidence.** Every Python test leg on `ad9aba07` failed the same two tests and nothing else. The legs are
py3.10, py3.11, py3.12, py3.13 and py3.14 on ubuntu-latest, and py3.12 on windows-latest. The py3.11 job
`113782171837` reports 2 failed and 12,369 passed. The six job logs were read one at a time, never aggregated. An
independent three-lens review had predicted both failures, and it found the further items below. They are fixed
here.

| Item | Where | Fix |
| --- | --- | --- |
| P1-1 | `cisco_toolkit/impact_assessability.py` | The owner no longer imports `re`. A `/collection_completeness/devices/<n>` witness is parsed by `_fleet_blind_row`: `str.startswith` on the prefix plus `str.isdecimal()` on the whole tail, then `int()`. This is the same set of tails that `(\d+)` `fullmatch` accepted. The import guard is unchanged. |
| P1-2 | `tests/test_design_sync_no_client_data.py` | W47's `ImpactValue` and `ImpactLowerBoundTag` are recorded as deliberate source-only components, with the reason (below). They were the only missing exports. |
| P2-1 | `ui_projection._collection_join` (called by `_joins`) | Some devices-map devices have no blind-spot row. For them, the absence is read as "not a blind spot" (`_ABSENT_CC`) only while `ctx.scope_doubt(host)` raises no doubt. Otherwise the collection row is unverified, with the doubt's own reason and witnesses. A row that names the device is joined as before. |
| P2-2 | `tests/test_ui_projection_inventory.py` | Open gaps move from `CAP_SITES` to `OPEN_CAP_SITES`. i12 unions the two, holds them disjoint, and refuses any `exempt:` value that calls itself open. A ratchet holds the open set exactly. |
| P3-1 | `impact_assessability.fleet_blind` | Only `witness` refs are counted. A `failure_record` ref is the reason a record is unread, not a second unread record, so the sentinel case now reads `(0, 1)`, not `(0, 2)`. |
| P3-2 | owner phrases; `summary`; `KEYSTONE_CONTRACT_VERSION` 8 | `fleet_blind` returns a `FleetBlind`, which is still exactly the pair `(blind, unread)` and carries an `unread_kind` of absent, failed or unreadable. `fleet_unread_phrase` words each kind as what it is: `R_WAVE_FLEET_ABSENT`, `R_WAVE_FLEET_FAILED`, or `R_WAVE_FLEET_BLIND_UNREAD`, which no longer lists "absent" or "failed". The MOP (`mop._blast_for`), the cutover plan and `summary.impact_blind_note` all read it. The summary text changed, so `KEYSTONE_CONTRACT_VERSION` is now 8. |
| P3-3 | `tests/test_dossier_input_state.py` | `assert pending == {}` is now a ratchet. |
| P3-4 | `CAP_SITES` justifications | These details were wrongly marked "never read": the punch-list fold (`_fold_axis`) copies each kind's first `detail` into the published `punchlist[].detail`. The detail states the full count before the cut for `flapping[:5]`, `naked_voice[:6]` (with " …"), `policy_maps[:5]`, `with_qos[:5]` and `without_qos[:5]`, so these stay exempt with corrected wording. `dangling[:5]` (undefined-policy-ref) states neither the count nor the cut, so it is **OPEN**. `example[:220]`, `top_messages` and the summary host previews are not folded, so they stay "never read". |
| P3-5 | `ImpactValue.tsx` `Explained`; `styles.css` | Escape now sets `data-dismissed`. The `:focus-visible` reveal yields to it, so the reason hides while keyboard focus stays on the button. Activating the button again, or leaving it, clears the flag. The comments now match this behaviour. |
| P3-6 | `ComparisonDecision.tsx` | An absent or non-integer `n_impacts_total` is now `null`, not 0. The live line says the count is unavailable, and `CapDisclosure` reads "Total: unavailable · Omitted: unavailable". |
| P3-7 | `CoreSnapshot.tsx` `FindingFacets` | A published severity or category count can carry `fleet_lists_exclude_blind_devices`, `findings_without_running_config` or `finding_facet_source_incomplete`. These are the owner's lower-bound caveats in `_finding_facets`. Such a count renders through FactView's `lowerBound`, as "≥ N" with a visible reason. `one_hop_failure_attribution` and the device facet's `device_findings_scope` do not make a count a lower bound. |
| P3-8 | `engine._impacts_view_empty_disclosure`; `ComparisonDecision.tsx` | The impacts view gains `empty_disclosure`. For an empty stored list, this is the projection's own `{state, reason}`, equal to what `summary.failure_impact_table` shows. The SPA words a withheld empty list as "not a finding of no impact (not collected): reason". A view without the field (an older server) is qualified, never clean. |

**Why the two W47 primitives are internal, not cards.** Each one renders a single failure-impact value in a state the
engine owner has already decided, with the owner's own reason. A standalone card would need a second, fictional copy of
that vocabulary outside the server-owned contract. That is the rule already applied to `ComparisonDecision`. The
primitives do reach the Design library inside a public card fed by provider data: CutoverPlanner's `GatedRunOfShow`
renders every worst-case blast radius through them. The reviewed visual contract pins exactly 21 cards and 42 hosted
windows-2025 baselines (`design-cards.visual.spec.ts`), so it covers them there. Making either primitive a card would
need its own hosted-captured baselines, which this round cannot produce. Registering them only partly would break the
pinned visual contract.

**Open cap follow-ups (ratcheted, not fixed here; each fix changes persisted engine output):**
- `analyze.compute_application_intelligence` `vlans_sorted[:40]`. This entry predates W51.
- `analyze.compute_qos_audit` `dangling[:5]`, found by the P3-4 re-review.

The P2-2 instruction named only the first entry for the ratchet. The P3-4 re-review then added the second, under that
item's own rule ("file it as OPEN rather than exempt").

**Not changed: the projection's own absent-record reason.** `ui_projection._R_CC_UNREAD` still reads "collection_completeness cannot be read (not collected: …)"
for a record the snapshot does not carry. It is the projection's coverage-state text, which the owner phrases now cite
in spirit but do not import. Rewording it would move projection reason texts that other tests pin, so it is left for a
follow-up.

**Static checks (no test function called, no npm or build).**
- Compile and lint: `py_compile` and ruff pass on every changed Python file, and the AST shadow scan finds 0.
- Collection-sanity scan of the 7 changed test files: no duplicate names, parametrize names or unknown fixtures. Its
  only flags are three stdlib `datetime` names that it cannot resolve through the C module.
- Copied helpers and pure calls reproduced every new test's assertions. They covered the P2-1 contradiction cases and
  the clean control, `fleet_blind` kinds and wording, copy and pickle of `FleetBlind`, `empty_disclosure` equal to the
  tab, the i12 walk (0 unreviewed, 0 stale, `registered == ENGINE_LIST_CAPS`), the barrel coverage (0 missing, 0 stale)
  and F8's owner and SPA caveat equality.
- Golden and stored sample: `project`, `project_device` for every device, `cutover.build_plan` and `mop._fleet_blind`
  have the same digests as before. `summary.summarize` also matches once its `keystone_contract` is set back to 7.
- Native pins: view `55bc576f…` and list `ce6e9c45…` recompute equal to the pins on an archive of `ad9aba07` (the method
  check) and on this tree. The schema is unchanged, so `openapi.ts` and the vocab bijection are untouched.
- No tracked path was added or removed, so the LF path-set receipts are unchanged.

**Not verified here.** No Python test, Vitest, tsc or build ran. The new TypeScript and Vitest cases rely on the hosted
frontend job, and the Python cases on the hosted test legs.

### Round 4 dist import (2026-10-09)

The round-4 head `aa9be934` changed frontend source, so the tracked dist was rebuilt from a fresh hosted handoff. The
verification followed the W29/W46/W51 precedent (`docs/w13-coverage-validation-2026-10-05.md`).

- **Expected record, selected from Git before the archive was read.** GitHub's tested merge for the pushed head
  `aa9be934` is `77cd79c5`. Its parents are main `6390b66c` (#629 merged) and `aa9be934`, and its tree `bb0e4110`
  equals the head tree. The record covers 149 committed inputs and is input-for-input equal to the head's.
- **Run and job.** Webapp-ci run `37927532324` (pull_request, attempt 1). Frontend job `113810038431` succeeded on
  checkout `77cd79c5`. It ran api:check ("Generated API types match the actual app schema"), Vitest (34 files, 504
  tests, including round 4's 4 new cases) and the build. The type-check passed, so round 4's TypeScript compiles.
- **Archive.** Artifact `11614811855`, `frontend-dist-handoff-aa9be93453cf494410b08987d8fc20386486d046-37927532324-1`,
  569,315 bytes, sha256 `9721cef342dc02028ed1440335943066605fb04237ac58c5ef944ae35746f21d`. The digest equals the API
  digest and the job log's upload digest, and the size equals the job log's final size. The identity was unchanged on
  a closing API re-read.
- **Inventory.** The inventory is closed at seven files: `source-before.json`, `handoff.json` and 5 dist members.
  There are no directory, duplicate, absolute, backslash, parent or special entries.
- **Source records.** Both records equal the expected record, and `source-before.json` is byte-canonical.
  `handoff.json` has a closed key set, `github_head` `aa9be934`, run `37927532324` and attempt 1.
- **Non-promoting fields hold:** `GENERATED_INPUT_FOR_REVIEW_ONLY`, `release_authority` false and
  `final_source_rebuild_required` true.
- **Toolchain.** Node v24.19.0 and npm 11.17.0 match the job log. The member census matches the vite build log.
- **Members.** The 5 member hashes and sizes pass, and the canonical path-aware marker policy finds 0 hits. The index
  asset links resolve, and every asset is reachable from `index.html`.
- **Negative controls are refused:** one altered input hash, a wrong npm version, and the earlier tested-merge records
  `e808ec12` and `7b8ae69b`.

The members are not byte-identical to the tracked dist: all five differ. So only the 5 verified members are imported:
`index.html`, `assets/index-C26NudFB.js`, `assets/index-UkC34GZ_.css`, `assets/Topology3D-B_L0iChV.js` and
`assets/react-force-graph-3d-DZzd_Nay.js`. The 4 superseded files in the owned dist directory are removed, and each
indexed blob equals its member. The commit changes no source, test, package or lock file. This is review input: the
new head must reproduce these bytes in fresh hosted gates.
