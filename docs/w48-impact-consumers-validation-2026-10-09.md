# W48 failure-impact consumers read the engine owner (validation record)

Branch `claude/w48-impact-consumers`, cut from `origin/claude/train-engine-sample` at `bb024ef0` (W45, PR #629).
It is stacked on #629, which carries the owner `cisco_toolkit/impact_assessability.py` (W33 plus W32's blind-link
rule). After #629 merges, the supervisor merges main into this branch.

No local test, build, engine, pipeline or sample/golden writer ran (owner GitHub-only rule). The checks run locally
were static: compilation, `ruff check` on the changed files, an AST shadow scan, and the new guard's own AST scanner
executed on its own (stdlib only, no package import) against this tree, against the `bb024ef0` tree, and against its
synthetic tree. The hosted gates decide.

## The problem

On the regenerated sample the owner bounds core1: one inter-switch link with no trunk/STP evidence (`blind_links: 1`),
so its 45 stranded endpoints are a floor. The dossier, RES-4, the workbook, the explorer and AssessHub's
summary/cutover already printed `≥ 45 (lower bound)`. Five consumers still read the raw rows and printed 45 as exact,
or 0 as a measured zero.

## Consumer census (line numbers at `bb024ef0`)

**Raw, presenting to an operator: moved onto the owner.**

| Site | What it presented |
|---|---|
| `cisco_toolkit/mop.py:281-293` `_blast_for`, fed by `:517` | Per-wave max blast radius (§1 overview, §x.1) and the quantified rollback trigger |
| `cisco_toolkit/runbook.py:302`, `:2265-2273` | §10 Risk Register: severity, VLANs, stranded, hard, backup, FHRP, ranked |
| `cisco_toolkit/ops.py:33-39` `_facts`, `:424-436` | §2.1 keystone table, ranked |
| `cisco_toolkit/mcp_server.py:191-195` `failure_impact` (+ `:590` dispatch) | Raw rows handed to the assistant |
| `webapp/backend/app.py:3307` dossier recompute | The pre-W33 impact phrasing, because the owner's verdicts were not passed (W33's ratchet) |

**Raw, presenting, persisted: STOPPED (see below).**

- `cisco_toolkit/design_advisor.py:1244-1245` (`_signals`, `nobackup_high`).
- `cisco_toolkit/protocol_assurance.py:2204-2219` (`cutover_operator_evidence`, `rehearsal.impacts`).

**Already read through the owner.**

- `impact_assessability.py` itself.
- `excel.py:5968` (Failure Impact sheet) and `:6414` (Executive Summary).
- `design.py:310`, `:466-504`.
- `deck.py:451-514`.
- `archreview.py:419-501`.
- `analyze.py:12649-13186` (`compute_device_dossiers` with the document). The score reads the stored row by W33's
  design, and the stored dossier keeps `stranded`/`vlans_impacted` with `impact_assessability` beside them.
- `html.py:3462-3470` (`_slim_for_embed`), with the explorer `blast_radius_explorer.html:11424-11431` reading the
  embedded verdicts.
- `COLLECT_PARSE_V3_23_0.py`: `:4899-4930` (the verdict phase and the sheets), `:5126` (the summary) and `:6301` (the
  `_device_dossiers` adapter, a carrier).

**Reading the projection.**

- `ui_projection.py` (`_topology_impact`, `_device_page:4201`).
- `webapp/backend/engine.py:47-56` (`failure_impact_projection`).
- `summary.py:243-290` (`impact_view`), `:423` (`failure_impact_table`) and `:440` (`_keystones`).
- `cutover.py:165-235` (`_keystone_hosts`, `_worst_blast_radius`).
- `cutover_docx.py:195-213`.
- `graph.py:17-118` (its keystone list comes from `summary._keystones`, `app.py:3349`).
- `app.py:3280-3284` (the Failure impact tab).

**Not readers.** These only name the section or use the word:

- `ssot.py:468` (the phase map) and `context.py:41,58` (carrier fields).
- `app.py:185` (Scope section names) and the producer `analyze.py:1216`.
- The application "keystone domain" (`analyze.py:9201+`, `excel.py:1102`, `runbook.py:1901`). It is a different keystone.
- Prose in `cutover_sim.py`, `failover.py` and `design_kb.py`.
- The explorer's own in-browser simulation.

**Raw, outside the guard's Python roots: a Codex handoff (not edited here).**

| Site | What it presents |
|---|---|
| `atlas-scope/tools/lib/compile-model.mjs:988` (`compileFabric`) | Builds `impactByHost` from raw `snap.failure_impact` |
| `atlas-scope/tools/lib/compile-model.mjs:1063-1073` | Copies `severity`, `vlans_impacted`, `stranded`, `hard`, `backup`, `fhrp` and `detail` raw into each device's `impact` record |

The guard in `tests/test_impact_consumers.py` scans Python only, so it cannot see this reader; its docstring lists it
as a known limit. The stored owner output Scope can read is
`device_dossiers.per_device[*].impact_assessability` (`{assessable, why, pointer}`, W33). A lower-bound row should
compile its worst band and positive counts as floors and its zeros and lower bands as not measured. A held or
ambiguous row should compile with no measured value. The compiled-fabric golden then needs Codex's re-bind.

## What moved, and the one rule

Every moved site reads `impact_assessability.rows_with_verdicts` / `assess_failure_impact`. Each value is the
owner's: `table_value` / `ranked_value` / `table_detail`. Rankings use `ranks` / `ranking_floor`, and a row that is
not ranked is named with `disclose`. A published row renders exactly as before.

- **MOP.** A published row contributes its count. A lower-bound row contributes only its floor. A held, doubted or
  zero-bounded row, and a wave device with no row, contribute none. Since the refutation follow-up (below) the wave
  rule is the owner's `wave_blast`, which AssessHub's cutover plan reads too. The figure is exact only when every
  device in the wave has a published count, no stored row names no readable host, and the projection's fleet
  qualifier lists no partial or never-collected device. Otherwise it is `≥ N (lower bound)` with why. A lower bound
  of 0, or no count at all, is `not assessed`. The rollback trigger keeps its quantified clause on a positive lower
  bound and says the worst case can be larger. It withdraws the clause on `not assessed`, as it already did on
  `[NOT OBSERVED]`.
- **Runbook §10.** Ranked rows come first, ordered by count or floor alone (stored order on a tie, as the workbook,
  design, deck, archreview and ops rankings order them), with every cell as the owner publishes it. Rows the owner
  does not rank follow them. One sentence names the lower bounds, and one names the rows that are not ranked.
- **Ops §2.1.** The keystones rank by count or floor, and their cells are written the same way. The section now also
  renders when only rows that are not ranked exist, so they are named and never omitted.
- **MCP `failure_impact`.** Each measure is the owner's value. `detail` leads with the verdict, and each row adds
  `assessable` and `why`.
- **AssessHub dossier recompute.** It passes `assessment_document(snap)` as `main()` does, falling back to
  `unavailable_document()` on a fault. W33's ratchet in `tests/test_dossier_input_state.py` is emptied.

## The guard (`tests/test_impact_consumers.py`, part 1), as first built

The refutation follow-up below replaced this design; this section records what the review found weak.

The class is defined by what a function reads. A unit is a top-level function, a method, or a module-level
assignment such as a dispatch table. The scan covers every such unit under `cisco_toolkit/`, `webapp/backend/` and
`COLLECT_PARSE_V3_23_0.py`.

A unit counts as reading the stored section when it uses `"failure_impact"` as a call argument or a subscript key,
loads `.failure_impact`, or loads a `failure_impact` name that is not one of the module's own functions.

Every such unit must reach the owner, through its own code or its call closure. The closure follows:

- same-module calls;
- imported project functions;
- `module.function` attributes;
- `self.method` calls;
- module-level tables.

The owner, the projection and AssessHub's surfaces pass by that property, not by name.

The only named entries are `_RAW_RATCHET`: the two STOPPED sites, each with its reason and a strict `xfail`.
Fixing one fails the guard until both the entry and the `xfail` are deleted.

Two checks keep the guard honest:

- A textual cross-check fails if a module whose code (comments and docstrings blanked) reads the section by text has
  no reader unit.
- A synthetic tree pins each read shape (`get`, key, parameter, attribute) as raw and each route as admitted:
  direct, lazy import, transitive, method, dispatch table, and webapp through `engine`.

Measured statically: on this tree the scan finds 16 reader units, and exactly the two ratchet units are raw. On
`bb024ef0` it finds 20, with 7 raw: the two ratchet units plus `mop.write_mop_docx`, `runbook.write_runbook_docx`,
`ops._facts`, `mcp_server.failure_impact` and `mcp_server.build_server`, so the guard fails on the old code.

The guard works per function. A function that reaches the owner could still print another raw value, and part 2
pins what each moved consumer prints.

## Tests (written, not run)

`tests/test_impact_consumers.py` part 2 uses the committed sample. The precondition is read from the owner: core1 is
`lower_bound` and its floor equals its stored `stranded`. The held variant removes core1's `off_scan_gw_vlans`, so
the owner reads it as `not_assessed` (`legacy_row`).

| Consumer | Lower bound (sample) | Held |
|---|---|---|
| MOP | The core1 wave cell reads `≥ N (lower bound) — …core1 (strands at least 45 …)`. The overview column is the same. The trigger says "only a lower bound". | The cell names `core1 (not assessed — …)` and never sizes on 45 |
| Runbook §10 | The core1 row is exactly the owner's `ranked_value` cells. The raw row is absent. The lower-bound sentence names core1. | The raw row is absent. The "not ranked above" sentence names core1. |
| Ops §2.1 | The core1 row is the owner's cells. The raw row is absent. The lower-bound sentence names core1. | The raw row is absent. The "not ranked as keystones" sentence names core1. |
| MCP | `stranded == "≥ 45"`, every measure is `table_value`, and `assessable`/`why` are present | Every measure is `not assessed`, and `detail` is the owner's verdict |
| design_advisor, protocol_assurance | strict `xfail` (STOP) | strict `xfail` (STOP) |

Each non-xfail test fails on `bb024ef0`, which printed the raw 45 or carried no verdict.

Existing tests adjusted. None was weakened:

- `test_r4_deliverable_writers.py::test_mop_observed_blast_radius_still_renders_the_quantified_trigger`: the figure is
  still a number, never `[NOT OBSERVED]`, but may now be the owner's `≥ N`.
- `test_r6_runbook_ops_caps.py`: the two ops keystone-cap fixtures gain the evidence a real run's rows carry
  (`tests/impact_fixtures.assessable`), because their subject is the cap.
- `test_dossier_input_state.py`: W33's app.py ratchet is emptied.

## STOPPED: persisted output, routed to the supervisor

1. **`design_advisor._signals` → `nobackup_high`.** It counts raw `severity == "High"` with a raw zero `backup`. On a
   lower-bound row the zero `backup` is withheld, and on a held row everything is. The persisted leaves in
   `webapp/sample_data/sample_fleet.snapshot.json` that an owner read changes are:
   - `design_blueprint.decisions[13].evidence.summary` (id `topology-triangles-not-squares-rings`): "…; 19 device(s)
     strand endpoints with no backup path on failure.";
   - `design_blueprint.tradeoff_scorecard[0].evidence` (axis `availability`): "…; 19 node(s) with no backup path.".

   Measured from the owner, 17 rows are High with a measured zero backup. core1 and core2 are lower bounds whose zero
   is not a measurement. The `availability` score stays 0 while the measured count is positive. The golden has no
   `design_blueprint`, so it is unchanged. AssessHub's `/design` recompute renders the same text.
2. **`protocol_assurance.cutover_operator_evidence` → `rehearsal.impacts`.** It copies whole raw rows, and
   `webapp/frontend/src/components/ComparisonDecision.tsx:421-426` renders their `severity` and `detail`. The payload
   is not in the golden or the sample: the tracked `cisco_toolkit/data/atlas-r1-retrospective-comparison.json` has
   `impacts: []`. It is persisted, though, in every AssessHub execution comparison receipt, and it is re-verified
   against an exact-source recomputation on every read: `webapp/backend/storage.py` `_execution_receipt_authority_locked`
   (`:2076`) and `append_execution_comparison_if_unchanged` (`:2789`). Changing the rows would make each stored receipt
   whose after-snapshot carries failure-impact rows read as not matching, so it needs a supervisor-routed contract
   decision, such as a versioned owner field or a migration. A frontend-only fix would need a hosted SPA rebuild.

## Refutation follow-up (2026-10-09)

An independent review of `e7c00e12` raised three P2 findings and four P3 findings. All seven are fixed on this branch.
No test, build, engine or pipeline ran (owner GitHub-only rule). The checks below were static: pure functions called
on the stored sample JSON and on in-memory mutations of it, and the guard's own scanner run without pytest.

**P2-1: the MOP printed `≥ 0 (lower bound)` with a live trigger.** A wave whose only counts are published zeros,
beside a held, zero-bounded or missing device, read `≥ 0 (lower bound)`. Its trigger then read "more endpoints than
≥ 0", which fires at the start of every window. Reproduced on the sample with dist2 + dist1 and with dist2 + a
missing host. Fixed: the owner's wave rule reads a lower bound of 0 as `not assessed`
(`impact_assessability.wave_blast`, `WaveBlast.zero_bound`). The MOP cell then reads `not assessed —
R_WAVE_ZERO: why`, and the trigger withdraws its endpoint clause (`cisco_toolkit/mop.py`, `_blast_cell` and the
blast-radius trigger row).

**P2-2: the MOP applied only one of the cutover plan's lower-bound rules.** The cutover plan also bounded every wave
when a row names no readable host, or when the projection carries its fleet caveat
(`fleet_lists_exclude_blind_devices`). The MOP dropped host-less rows and had no fleet caveat. Fixed: the wave rule
moved into the owner.

- `WaveRow`: one stored row as the rule reads it (`key`, `ranked`, `lower_bound`, `stranded`, the reader's row).
  - `wave_rows(snap)` builds them from the owner's verdicts. A published row ranks by its readable count. A
    lower-bound row ranks by its positive floor.
  - The cutover plan builds them from the projected rows (`_impact_wave_rows`). A row ranks when the projection
    publishes its host, severity and stranded count.
- `wave_blast(switches, rows, *, blind)` returns a `WaveBlast`: `assessable` (published, lower bound or not
  assessed), `value`, `complete`, and the ranked, unranked, host-less and bounded rows.
  - Every non-empty text in `switches` is a device. A device is covered by a ranked row naming it exactly.
  - `complete` holds when every device is covered by a row that is not a lower bound, no stored row names no
    readable host, and `blind` is 0.
  - `blind` is read with the owner's count rule, so an unreadable value fails closed.
- `fleet_blind(listing)` reads the projection's fleet qualifier from a projected `failure_impact` list. The
  projection stays its owner and the owner never imports the projection. The cutover plan passes the count
  `summary.impact_view` already reads (summary now reads it through `fleet_blind` too). The MOP projects once
  (`mop._fleet_blind`) and fails closed (`None`) when the projection cannot be built.
- `wave_why(wave)` gives the MOP's reader-facing reasons, using the same fleet sentence the cutover plan prints
  (`summary._R_IMPACT_BLIND` now aliases `R_WAVE_FLEET_BLIND`).

The cutover plan's outputs are unchanged: `_worst_blast_radius` still picks its worst row and words its disclosure
from the projection, and only the classification comes from `wave_blast`. Measured: the plan's `blast_radius` and
keystones were dumped from `e7c00e12` and from this branch for 14 sample variants. The variants are the sample; a
blind spot; a host-less row (`None` and `""`); held, duplicated and mistyped core1; a device with no row; a failed
phase; a section that is absent, empty or not a list; and a non-object row. Five direct `_worst_blast_radius` calls
ran per variant. The dumps are byte-identical. The existing pure cutover tests in
`webapp/tests/test_impact_surfaces.py` also passed when their bodies were run without pytest.

**P2-3: the guard was weaker than its claim.** The redesign:

- every nested function, method, class body, method of a nested class and def inside a module-level `if`/`try`
  is its own unit;
- only a CALL to an owner function or class is a route (a module-level table may hold one uncalled); an owner
  constant, or an owner function named but not called, is not;
- key constants are folded: module-level, imported, once-assigned local, `+`, f-strings, `sep.join`, and a loop
  over a literal table;
- new read shapes: `match` mapping and class patterns, `.items()` loops compared against the section name, and path
  tuples that start with it;
- the rows are followed one assignment into a nested function, a helper that reads a row field (callee or a
  function passed beside them), and a local alias (`P = _PURE`);
- the textual cross-check is line-level. Every line where the tokenizer sees the section name must hold an AST
  occurrence that is a read or one of the closed non-read positions.

Results:

- On this tree, 22 reader units; exactly the two ratchet units are raw, and the line check is clean.
- On `bb024ef0`, eight are raw: the ratchet pair, `mcp_server.failure_impact`, `mcp_server.build_server.failure_impact`,
  `mop.write_mop_docx`, `mop._blast_for` (handed the raw rows), `ops._facts` and `runbook.write_runbook_docx`.
- All 26 pinned evasions are flagged. They are the review's eight, its four extra probes and 14 more shapes.
- The four documented known limits stay unflagged, as pinned: two-hop dataflow, formatted keys, a reference-only
  route and the unit granularity.
- `create_app`'s nested routes: only `create_app.get_section` reads, and it is routed (the Failure impact tab and
  the dossier recompute).
- `COLLECT_PARSE` `main` and its nested `_failure_impact_assessability` are routed. `main` hands the rows only to
  `write_failure_impact_sheet` and `write_executive_summary_sheet` (both routed through `_run_phase`), to
  `AnalysisContext` (a carrier) and to `_device_dossiers` (routed). No missed raw presenter was found.
- The scan takes about 8 s on this tree and is cached per run.

**P3s.**

1. `runbook.py` §10 ranked a lower-bound row by its raw severity. It now ranks by count or floor alone.
2. The MOP has a positive control: a fully published wave prints the bare count and its quantified trigger. The
   r4 regex is now `^(?:≥ [1-9]\d*|\d+)(?: |$)`, so `≥ 0` fails.
3. `docs/ssot.md` no longer says the runbook, MOP, ops handbook, MCP tool and AssessHub views read raw rows.
4. Atlas Scope's raw reader is recorded in the census above, in `docs/ssot.md` and in the guard's known limits, as
   a Codex handoff.

**Tests added (written, not run under pytest).**

- `tests/test_impact_consumers.py` part 1: the line check and its non-vacuity, the synthetic route tree (now with
  dotted, table, local-alias, owner-table and nested routes), 26 parametrized evasions and four known limits.
- `tests/test_impact_consumers.py` part 2: the MOP zero lower bound, the fully published MOP control, the MOP
  fleet-caveat and host-less bounds, and the runbook floor-only order.
- `tests/test_impact_consumers.py` part 3: the wave rule (exact, missing device, zero bound, not observed, withheld
  zero, host-less row, fleet blind and unreadable blind) and `fleet_blind` on the real projection.
- `webapp/tests/test_impact_surfaces.py`: the MOP and the cutover plan agree, wave by wave, on a fully published
  fleet, a host-less row and a fleet blind spot.

The guard, part 3, the MCP tests and the agreement test were also executed through a harness that fakes only
`pytest`'s decorators: 43 of 43 and 12 of 12 passed. The docx-rendering tests (MOP, runbook) were not executed.
To run the existing cutover tests, the harness called the real producers (`analyze.compute_failure_impact`,
`compute_cable_map`) on those tests' in-memory interface fixtures. They are pure functions and no pipeline ran.

## Not verified here

- No test ran. Every new and adjusted test, the docx rendering, and the MOP/runbook/ops wording are unexecuted.
- `cutover_operator_evidence` on the sample, inside the strict `xfail`, is assumed total. The `xfail` declares
  `raises=AssertionError`, so any other exception would surface as a failure.
- The MOP now treats a wave device with no row as making the figure a lower bound. A hosted run on a fleet with
  routers in a wave will show that wording for the first time.
- The guard's closure is per unit and cannot see dynamic dispatch beyond module-level tables and local aliases (its
  docstring lists the known limits, each pinned).
- The MOP docx rendering of the new zero-lower-bound, fully published, fleet-caveat and host-less cases, and the
  runbook's new order, are unexecuted. `_blast_for` and `_blast_cell` were called statically; the trigger text was
  checked by reading the code.
- The MOP now projects the topology once per document (`mop._fleet_blind`, about 0.1 s on the sample). It was not
  timed on the 303-device reference fleet.
