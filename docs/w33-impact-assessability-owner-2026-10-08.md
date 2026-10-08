# W33 engine-owned failure-impact assessability (follow-up F5)

Started from main `d0e10888` (W23, #616, merged). Branch `claude/impact-assessability-owner`.

W23 taught the projection to withhold the failure-impact cells that are not measurements. The ENGINE's own
offline deliverables still read the raw stored rows, so the same row could be withheld on a screen and
printed as "Info / no impact / 0 stranded" in a document, or ranked as a keystone. W33 moves the row-level
rules into one engine owner and makes the projection and the deliverables read it. Nothing is re-simulated.

No local test, build, browser, pipeline or projection run took place; the owner's rule is GitHub-hosted only.
The checks run locally were syntax compilation, the static helpers of `tests/test_protocol_assessability.py`,
a static comparison of reason constants, and `json.load` of tracked snapshots.

## The owner

`cisco_toolkit/impact_assessability.py` is a new module, not a function in `analyze.py`:

- `analyze.py` is the producer. The projection's guard
  (`tests/test_ui_projection_device_impact.py::test_the_projection_source_never_names_a_topology_producer`)
  forbids any module object through which the projection could reach a producer. An owner inside
  `analyze.py` would put the projection one attribute away from `compute_failure_impact`.
- The owner imports only `ssot`, so ui_projection, the deliverables, the pipeline and the dossier (inside
  `analyze.py`, through a local import) can all read it without an import cycle.
- `tests/test_impact_assessability.py` pins both properties: the module names no topology producer, and
  its only project import is `ssot`.

Per stored row the owner returns a verdict:

| Verdict | Meaning | Values a deliverable may print |
|---|---|---|
| `published` | The producer's measurement. | Every value. |
| `lower_bound` | A bound applies: off-scan VLANs, an uncollected neighbour that can carry endpoints, or a cable map that cannot be read. | The worst band and each positive count, as lower bounds. A band below `High`, a zero and a detail naming no simulated VLAN are withheld. |
| `not_assessed` | A hold applies, or the section failed, or the row is not an object. | Nothing but the producer's own INDETERMINATE disclosure. |
| `ambiguous` | Two or more rows carry this exact host text. | Nothing; neither row is picked. |

The rules are the W23 rules, unchanged, now in one place:

1. **Hold, first match wins** (`row_hold`): the producer's `Blast radius INDETERMINATE` detail; no
   `off_scan_gw_vlans` (a legacy row); an unreadable off-scan count; no readable host; no interface of the
   device carrying `run_config_observed: true`; a positive off-scan count with nothing simulated.
2. **Bounds** (`off_scan_bound`, `neighbour_bound`): a positive off-scan count; a stored cable to a
   `cable_map.nodes` peer not shown as collected unless it is `collected: false` with kind `ap`, `phone` or
   `endpoint` (`IMPACT_EDGE_KINDS`). The join fails closed: an unreadable cable row, a far end joining no
   single node, and a cable list that cannot be read.
3. **Doubt** (`duplicate_doubt`): two rows naming one exact host.
4. **Per value** (`measure_withheld`, `detail_withheld`): a hold withholds every measure and every detail
   except the INDETERMINATE disclosure. A bound withholds a band below `High`, a zero, and (neighbour bound
   only) a detail that names no simulated VLAN.

Each verdict also carries reason codes, the owner's full reasons, RFC 6901 pointers that resolve in the
snapshot, and reader-facing phrases (`CODE_PHRASES`) that name no engine internals. `assessment_document`
is the JSON form (`failure_impact_assessability/1`); it is never stored in the snapshot.

A cable row the join cannot read bounds every row. A hostile upload can therefore make the witness lists
grow as rows times cables. The deliverable routes now run the owner too: the AssessHub explorer, the design
document, the deck and the architecture review. So `assess_failure_impact` keeps at most
`DELIVERABLE_WITNESS_CAP` (32) witnesses per neighbour bound and duplicate doubt. Its verdicts, codes,
reasons and withheld cells stay exact.

The projection reads uncapped, exactly as before. Its own rows-times-cables witness growth predates W33 and
is unchanged.

The join itself was restructured: readable rows are walked per host, and the unreadable rows once per list.
`test_the_neighbour_join_equals_the_pre_refactor_loop` holds it equal to the W23 loop.

## The projection consumes the owner, byte for byte

`ui_projection._topology_impact` now asks `ctx.impact.row(i, raw)` for the doubt, the hold and the bounds,
then applies them in the module's state precedence, as before. What moved:

- `_impact_hold`, `_impact_off_scan`, `_impact_peers`, `_impact_bound`, `_impact_bound_state` and
  `_impact_dup` are gone.
- `_impact_pre` and `_impact_detail_pre` call `measure_withheld` and `detail_withheld`.
- The reason templates live in the owner. A static AST comparison against origin/main showed every one equal.
- `IMPACT_INDETERMINATE_PREFIX` and `IMPACT_SEVERITIES` are re-exports of the owner's constants.

What stayed in the projection:

- **The list-state reading of `cable_map.cables` and `cable_map.nodes`.** `_impact_cable_source` reads it
  through the projection's own envelope (`_topology_source`, its reason texts, its failure records). It
  hands the owner that reading, and the context's own exact-key indexes, through `CableSource`.
- **The exact-key host index.** It is `ctx.index`, passed in as a callable and read on first use only, as before.
- **The duplicate precedence** (`_ambiguous_pre`) and the cell envelopes.

The owner has its own default cable reading (`read_cable_source`) for the deliverables. A parity test holds
its state equal to the projection's over 36 shapes. The test file pins the projection against the
pre-refactor reasons copied verbatim from `d0e10888`, and requires each measure and detail cell to be
withheld exactly when the owner's verdict withholds it.

The import allowlist in `tests/test_ui_projection.py` admits `cisco_toolkit:impact_assessability` by exact
name, with the reason stated beside it.

## The deliverables, site by site

| Site | Before | After |
|---|---|---|
| `excel.write_failure_impact_sheet` | Raw `severity`, counts, `detail`. | Each cell is the owner's `table_value`: `not assessed`, `High (lower bound)`, `≥ N`, or the stored value. The detail leads with the verdict and keeps the producer's detail only where the owner publishes it. `main()` still writes the sheet at Phase 20, where it reads fail-closed, then rewrites it in place once the cable map exists. |
| `excel.write_executive_summary_sheet` | Top 10 raw rows; "top keystone" = first row. | Ranks published rows only. One "Not ranked" line names the rest with why. "Where to start" never names a withheld row. New keyword `impact_evidence`. |
| `design.write_design_doc_docx` §2.1 / §2.4 | Keystones = raw rows with `stranded > 0`. | Published rows only. A "Blast radius not a measurement" paragraph and a §2.4 row disclose the rest. |
| `deck.write_executive_deck_pptx` keystone slide | Raw ranking. The INDETERMINATE count read only `off_scan_gw_vlans`. | Published rows only. Every non-published row counts as INDETERMINATE and is named, so the slide never reads "well distributed". |
| `archreview` RES-4 | A raw zero conformed; raw rows ranked. | Only a published row's `stranded` is graded. Withheld rows are disclosed ("not graded"). A lower bound keeps "strands at least N". The check never conforms while a row is withheld. |
| `analyze.compute_device_dossiers` impact term | Raw row; "no modeled reachability impact". | New keyword `failure_impact_assessability`, which `main()` passes. A lower-bound row's values are floors ("at least"). A not-assessed or ambiguous row, or a device with no row, takes the absent-row floor. Its phrase says why, and a Low/Guarded verdict says so instead of "routine migration handling". Each dossier carries `impact_assessability` `{assessable, why, pointer}`. Without the keyword the term is unchanged. |
| `html._slim_for_embed` + explorer `cockpitKeystones` / `keystoneCard` | Ranked `SNAP.failure_impact[].stranded`; a missing row read as 0. | The embed carries `failure_impact_assessability`, index-aligned. The card ranks published rows only and names every other switch, including a scanned switch with no row and a row with no verdict. The page holds no rule of its own. |

`main()` moves the Cable map phase before the Device risk register. No sheet is written between the two
points, so the tab order is unchanged. The phase builds the evidence view (`interfaces` marks, `cable_map`,
failures so far) once and passes it to the dossier, both sheets and the architecture review view.

**The new dossier argument and the AssessHub recompute.** `tests/test_dossier_input_state.py` requires every
`compute_device_dossiers` call site to pass every argument. The pipeline passes `failure_impact_assessability`.
The AssessHub section recompute (`webapp/backend/app.py`) belongs to W27 (#620), which this row may not edit,
so its recompute still reads the pre-W33 term.

The test now records that one missing argument as a ratchet, not as an open exemption. Its equality fails as
soon as `app.py` passes the argument, and the entry must then be deleted. The one-line change for W27 is:

```
failure_impact_assessability=impact_assessability.assessment_document(snap)
```

The golden harness's in-process dossier recompute (`tests/test_pipeline_golden.py`) passes the same argument
over the golden's own evidence, so it matches the pipeline once W31 regenerates.

**Sites deliberately left for a follow-up (F6), with reasons.** Each has its own fixture population, and
changing it unverified risks a wide hosted red:

- `runbook.py` §10 Risk Register table: raw rows, top 15.
- `mop.py :: _blast_for`, the per-wave max blast and the quantified rollback trigger: a withheld row's 0 still sizes it.
- `ops.py :: _facts`: keystones.
- `mcp_server.failure_impact`: returns raw rows to the assistant.
- `design_advisor` `nobackup_high`: reads `backup` 0 on a High row.
- `protocol_assurance` rehearsal: a carrier that already says `not_verified`.
- AssessHub's `summary._keystones`, `cutover._worst_blast_radius` and section routes: W27 (#620) holds those
  surfaces. The engine owner is ready for them.

## Regeneration (W31)

Expected to fail until W31 regenerates, all because the output changed honestly:

- `tests/test_pipeline_golden.py::test_snapshot_matches_golden`
- `tests/test_pipeline_golden.py::test_dossiers_do_not_depend_on_the_wall_clock_even_past_the_eol_registry_window`
  (its recompute now passes the verdicts, so it matches the regenerated golden, not the current one)
- `tests/test_sample_fleet.py::test_sample_architecture_review_matches_engine_exactly`
- `webapp/sample_data/build_sample.py --check`, wherever CI runs it

Changes in `tests/golden/snapshot.json`, read with `json.load`:

1. **`attestation`.** The two module-count strings ("across N modules", "across M analysis modules") move
   by one, for the new module.
2. **`architecture_review` RES-4 `observed`.** The text gains " 1 simulated device(s) are not graded, because
   their blast radius is not a measurement on this evidence: core2 (lower bound — it faces 1 uncollected
   neighbour(s) that can carry endpoints)." `core2` is cabled to the uncollected router
   `wan-edge-rtr1.lab`. The verdict stays advisory on `core1`.
3. **`device_dossiers.per_device[*]`.** Each record gains `impact_assessability`. `core2`'s verdict changes
   from "No stacked risk — routine migration handling." to the lower-bound sentence. Scores, bands, compound
   patterns and order are unchanged: `core2`'s values are kept as floors, and no golden row is not assessed.

`tests/golden/sheet_schema.json` is unchanged: no sheet or header was added.

Changes in `webapp/sample_data/sample_fleet.snapshot.json` (`build_sample.py`):

- The same attestation strings.
- RES-4 `observed` gains `core2 (strands at least 42 endpoint(s); lower bound — …)`.
- Every dossier gains `impact_assessability`. `core2`'s impact phrase becomes "removal strands at least 42
  endpoint(s) across at least 3 VLAN(s); the blast radius is only a lower bound (…)". A device with no
  failure-impact row reads "not assessed".
- Derived copies of the sample, such as the Atlas Scope compiled fabric (Codex-held), follow their own
  regeneration owners.

The projection's own output over the committed golden and sample is unchanged by this change: the
refactor is byte for byte, and the projection reads neither the new dossier field nor RES-4. No schema,
limitation text or native pin changed.

## Residuals

- The four W23 residuals stand: the 2026-06-26 to 2026-07-28 rows; snapshots before the
  `run_config_observed` marker; a missing gateway capture skewing other rows; and evidence-less links on a
  partially simulated row (R3-3, a producer change).
- The F6 sites above.
- The dossier floor for a not-assessed row is the absent-row floor (impact 1). It is disclosed in the verdict
  and the `impact_assessability` field, but it can still understate the band. Any stronger rule is an owner
  decision, not a W33 change.
