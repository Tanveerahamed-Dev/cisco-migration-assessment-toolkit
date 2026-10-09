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

The two per-host predicates are memoized per host in `ImpactSnapshot` (review P2-3). The interface
running-config scan is `run_config_captured`, and the uncollected-neighbour join is `neighbour_bound`. Both are
pure functions of the host and the cached sources. R rows naming one host now cost one scan and one join, not R
of each. `ImpactSnapshot.neighbour` returns a copy of the cached witness list, so a caller can never change what
another row reads.

**Rankings use the per-cell decision, not the row verdict** (review P2-1). The owner never withholds a
lower-bound row's positive `stranded` count. `ranking_floor` returns that floor, and `ranks` admits a published
row or a row with a floor. `ranked_value` writes a floor as `≥ N (lower bound)` and the worst band as
`High (lower bound)`. A held, ambiguous or zero-floor row is still disclosed and never ranked.

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
| `excel.write_executive_summary_sheet` | Top 10 raw rows; "top keystone" = first row. | Ranks published rows and each lower-bound row with a floor, ordered by count or floor. A floor is written `≥ N (lower bound)`. One "Not ranked" line names the rest with why. "Where to start" names the first ranked row that strands someone, never a measured 0 and never a withheld row. New keyword `impact_evidence`. |
| `design.write_design_doc_docx` §2.1 / §2.4 | Keystones = raw rows with `stranded > 0`. | Published rows plus lower-bound floors, as `host (≥ N endpoints; lower bound — why)`. A "Blast radius not a measurement" paragraph and a §2.4 row disclose the rest. |
| `deck.write_executive_deck_pptx` keystone slide | Raw ranking. The INDETERMINATE count read only `off_scan_gw_vlans`. | Published rows plus lower-bound floors (stat `≥ N`, label "stranded (lower bound)", the owner's detail). Every other non-published row counts as INDETERMINATE and is named, so the slide never reads "well distributed". |
| `archreview` RES-4 | A raw zero conformed; raw rows ranked. | A published row is graded by its `stranded`, and a lower-bound row ranks by its floor ("strands ≥ N endpoint(s) (lower bound — why)"). A floor in the hidden tail is counted. The keystone branch is checked first, so a floor alone makes the check advisory. Other withheld rows are disclosed ("not graded"), and the check never conforms while a row is withheld. |
| `analyze.compute_device_dossiers` impact term | Raw row; "no modeled reachability impact". | New keyword `failure_impact_assessability`, which `main()` passes. The score always reads the stored row, so a withheld impact never lowers risk (review P2-2; design below). A lower-bound row's phrase says "at least". A not-assessed or ambiguous row's phrase quotes its stored values as unverified and says why. A device with no row keeps the absent-row floor, disclosed. A Low/Guarded verdict over an unmeasured impact says so instead of "routine migration handling". Each dossier carries `impact_assessability` `{assessable, why, pointer}`, the pointer naming the scored row. Without the keyword the term is unchanged. |
| `html._slim_for_embed` + explorer `cockpitKeystones` / `keystoneCard` | Ranked `SNAP.failure_impact[].stranded`; a missing row read as 0. | The embed carries `failure_impact_assessability`, index-aligned, with the owner's `floor` on a lower-bound row that has one. The card ranks published rows and floors (`≥ N`, with the reason). It names every other switch, including a scanned switch with no row and a row with no verdict. The page holds no rule of its own. |

**The dossier design for a withheld impact (review P2-2).** The first W33 cut gave a not-assessed or ambiguous
row the absent-row floor. A held High row then scored impact 1 and lost CR-01/04/05/06 and its band, which is
absence-as-health. Making the impact term an unassessed axis (`n_na` plus an `input_state`) does not fit the
axis model:

- `n_na` counts `na` entries over the closed eleven-axis exposure census (`DOSSIER_AXIS_INPUTS`, pinned by
  `tests/test_dossier_input_state.py`).
- Every deliverable recomputes `n_na` from `exposures` (`excel.dossier_coverage`, deck, runbook, MCP). A bumped
  `n_na` would be overridden everywhere except the projection's `dossier_band_over_unassessed_axes` caveat.
- An unassessed axis still contributes its floor, so the band would fall exactly as before, only with a caveat.

So the term keeps scoring the stored row, exactly as without the keyword:

- A lower bound scores its floors.
- A held or ambiguous row's stored values still drive the multiplicand and the CR rules.
- The CR basis and verdict quote those values as unverified and say why.
- `impact_assessability` records the verdict and the scored row.

The score never moves in either direction; only the disclosure is new.

`main()` moves the Cable map phase before the Device risk register. No sheet is written between the two
points, so the tab order is unchanged. One guarded phase, `Failure Impact assessability`, builds the evidence
view (`interfaces` marks, `cable_map`, failures so far) and the verdict document. The evidence goes to the
dossier, both sheets and the architecture review view. If the phase raises, it records a failure, attributed
to `device_dossiers` in `ssot.PHASE_SECTIONS`. The sheets then get no evidence, so every row reads not assessed.
The dossier gets `impact_assessability.unavailable_document()`, so each row is disclosed as having no verdict
and its score is unchanged.

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

**The hosted W31 regeneration is authoritative.** The values below were derived by statically reading the
committed snapshots (`json.load`) against the code, not by running it. They are the complete set of changes that
reading finds, after the review follow-up; any difference the hosted regeneration shows is to be explained, not
waved through.

Expected to fail until W31 regenerates, all because the output changed honestly:

- `tests/test_pipeline_golden.py::test_snapshot_matches_golden`
- `tests/test_pipeline_golden.py::test_dossiers_do_not_depend_on_the_wall_clock_even_past_the_eol_registry_window`
  (its recompute now passes the verdicts, so it matches the regenerated golden, not the current one)
- `tests/test_pipeline_golden.py::test_golden_does_not_depend_on_the_wall_clock_past_every_registry_window`
  (it compares every snapshot section with the committed golden, so it carries the same three changes below;
  added after the first hosted run on `43f41c80`)
- `tests/test_sample_fleet.py::test_sample_architecture_review_matches_engine_exactly`
- `webapp/sample_data/build_sample.py --check`, wherever CI runs it

Changes in `tests/golden/snapshot.json`, read with `json.load`:

1. **`attestation`.** The two module-count strings ("across N modules", "across M analysis modules") move
   by one, for the new module.
2. **`architecture_review` RES-4 `observed`.** The text gains " 1 simulated device(s) are not graded, because
   their blast radius is not a measurement on this evidence: core2 (lower bound — it faces 1 uncollected
   neighbour(s) that can carry endpoints)." `core2` is cabled to the uncollected router
   `wan-edge-rtr1.lab`; its `stranded` is 0, a bounded zero, so it has no floor and stays unranked. The
   keystone list ("Losing core1 strands 3 endpoint(s).") and `evidence` (`["core1"]`) are unchanged, and the
   verdict stays advisory.
3. **`device_dossiers.per_device[*]`.** Each record gains `impact_assessability`. `core2`'s verdict changes
   from "No stacked risk — routine migration handling." to the lower-bound sentence. Scores, bands, compound
   patterns and order are unchanged: `core2`'s values are kept as floors, and no golden row is not assessed.
   No golden row is held, ambiguous or missing, and no cable row is unreadable.

`tests/golden/sheet_schema.json` is unchanged: no sheet or header was added.

Changes in `webapp/sample_data/sample_fleet.snapshot.json` (`build_sample.py`):

- The same attestation strings.
- **RES-4 `observed`: one clause changes.** `core2` (High, 42 stranded) is the sample's only bounded row. It
  faces `wan-edge-rtr1.lab`; its AP and phone peers are edge gear, and no cable row is unreadable. It keeps its
  place as the third keystone, ranked by its floor, so the list, the order, the tail and `evidence` (19 hosts)
  are unchanged. The only difference from the committed text is that `core2 strands 42 endpoint(s)` becomes
  `core2 strands ≥ 42 endpoint(s) (lower bound — it faces 1 uncollected neighbour(s) that can carry
  endpoints)`. The tail is still "and 14 further device(s) strand 30-39 endpoint(s) each", with no floor in it.
  No "not graded" sentence is added, because no row is withheld without a floor.
  - The first W33 cut dropped `core2` from the keystones. That would have moved `access13`/`access14` up and
    turned the tail into "13 further device(s)" — the incompleteness the review found. That variant is gone.
- Every dossier gains `impact_assessability`. `core2`'s impact phrase becomes "removal strands at least 42
  endpoint(s) across at least 3 VLAN(s); the blast radius is only a lower bound (…)". No sample row is held,
  ambiguous or missing, so no score, band, compound pattern or order changes.
- Derived copies of the sample, such as the Atlas Scope compiled fabric (Codex-held), follow their own
  regeneration owners.

The projection's own output over the committed golden and sample is unchanged by this change: the
refactor is byte for byte, and the projection reads neither the new dossier field nor RES-4. No schema,
limitation text or native pin changed.

## Independent review follow-up (on `ad34ba53`)

- **P2-1:** keystone rankers ranked on the row verdict, which dropped a lower-bound row with a published floor.
  They now use `ranking_floor` / `ranks` / `ranked_value` in the workbook, design, deck, RES-4 and the explorer.
  Tests cover the review's counterexample on each ranker (`core1` High, ≥ 300, beside the uncollected router
  `wan1`, and `acc1` Info/0), built from the real producers.
- **P2-2:** a withheld impact no longer lowers dossier risk (design above). Tests cover the review's
  counterexample: a past-LDoS High row with no running-config mark keeps CR-01 Critical and band Severe, with
  the owner's document and with the unavailable fallback. They also cover a published row (unchanged) and a
  lower bound (scored by its floor).
- **P2-3:** the per-host memo. A counting wrapper proves one scan and one join per host. A counting cable list
  proves the join reads the same number of cable rows for 10 and for 200 rows naming one host, and that each
  row gets its own witness copy. Neither test uses a clock.
- **P2-4:** the unused `subprocess` import is gone. A static AST scan for F401/F841/F541/E731 over every Python
  file the branch touches, compared with the merge base, finds nothing new.
- **P3:** this declaration is complete as far as a static reading reaches. The pipeline's
  `assessment_document` call is a guarded phase. The XML-illegal-character tests in `tests/test_design.py` and
  `tests/test_deck.py` now corrupt a published keystone row, so their text sinks are exercised and asserted. The
  deck test also renders a held, unreadable host by its row number.

## Residuals

- The four W23 residuals stand: the 2026-06-26 to 2026-07-28 rows; snapshots before the
  `run_config_observed` marker; a missing gateway capture skewing other rows; and evidence-less links on a
  partially simulated row (R3-3, a producer change).
- The F6 sites above.
- A not-assessed row's stored values still score the dossier (review P2-2), so they can over- or understate a
  blast radius the owner cannot vouch for. The dossier discloses this but does not correct it. A worst-case rule
  (scoring an unmeasured impact at the top) would raise every INDETERMINATE row, and that is an owner decision.
- The projection reads the owner uncapped. On a hostile list of unreadable cable rows, each bounds every row, so
  its witness output still grows as rows times cables. That is the projection's output size, which predates W33.
  The per-host join behind it now runs once per host.
