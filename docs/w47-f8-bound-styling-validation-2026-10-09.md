# W47 failure-impact value styling in the SPA (follow-up F8)

Started from main `7d547890`, which includes #620 (W27). W27 made the AssessHub backend read failure impact from the
engine-owned projection (`webapp/backend/summary.py::impact_view`). So a failure-impact or keystone value now reaches
the React SPA in one of four states:
- a measured value;
- a lower bound (`lower_bound`, the tab's `≥ N — …` cell, or a witness ref on a published projection measure);
- NOT ASSESSED (`summary.IMPACT_NOT_ASSESSED`, or a withheld tab cell carrying the projection's reason);
- a withheld value (`None` / null).

The SPA still rendered every one of them as a plain number, a blank or truncated text. This slice changes frontend
source only. `webapp/frontend/dist` is unchanged and stale until the next UI train imports one hosted dist for the
combined head.

No local test, type-check, build, browser or Playwright run took place; the owner's rule is GitHub-hosted only.

## The rule: one classifier and one renderer

`webapp/frontend/src/components/ImpactValue.tsx` owns the class:
- `impactEntryValue(entry, "stranded" | "vlans_impacted")` reads a keystone or a worst-case blast radius
  (`summary.impact_entry`).
- `impactTableCell(field, value)` reads one tab cell (`summary.failure_impact_table`). A `≥`-led cell is parsed as
  `summary.impact_bound_cell` writes it. Any other string in a value column is the projection's own reason, so it is
  not assessed.
- `projectionImpactBound(field, fact, rowPointer)` reads the projection's own mark on a core-page failure-impact row:
  a published measure (`summary.IMPACT_MEASURES`) that cites a `witness` ref. This is the mark `summary._impact_bounds`
  reads. It is applied only to failure-impact rows, because a witness ref on any other projection fact means something
  else (the existing FactView test pins a published 0 with a witness as 0). It names each cited witness relative to the
  row: the row's own record, one of the row's cells, or another record by its pointer.
- `pages/core/ProjectionEvidence.tsx` `ImpactFactView` is the one view for a failure-impact row cell on the core pages.
  The fleet topology rows and the device page rows both come from `ui_projection._topology_impact`, and both render
  through it.
- `<ImpactValue state>` renders the four states, and `<ImpactLowerBoundTag>` tags a figure that is a lower bound as a
  whole.

Classification never coerces. A count that is not a finite number is unavailable, never read as a number, and a
published 0 stays 0.

| State | Shows | Accessible explanation |
|---|---|---|
| measured | the value, in an unstyled span | none needed |
| lower bound | `≥ N`, with a dashed underline (`.impact-bound`) | "At least N: a lower bound, not an exact measurement. Why: …" |
| not assessed | the neutral, hatched `NOT ASSESSED` tag (`.impact-na`) | the engine's reason |
| unavailable | faint italic `unavailable` (`.impact-unavailable`) | withheld, "not a measured 0" |

The explanation is never hover-only (fix round, P3-1; reworked in fix round 2). In sentences and small tables the value
is a toggletip: a non-submitting `<button type="button">`, reset to look like the text it replaces. Its accessible name
is the state text and its accessible description is the reason (`aria-describedby` on a `.impact-why` element), and it
has no `title`. The `.impact-why` element is visually hidden but read by assistive tech. It is shown in place, in the
normal flow, while the button has keyboard focus or after it is activated; Escape or leaving the button hides it. Being
in the flow, it is never clipped by a scrolling table.

A caller that makes the reason reachable itself passes `reasonShown`, and the value is then a plain span with no tab
stop. Its `title` stays for hover, since no description is present. Those callers are:
- the core pages' `FactView`, where a lower bound's explanation is a visible `.projection-reason` line, as a withheld
  state's reason already is;
- a disclosure whose reason is visible text beside the tag;
- the snapshot "Failure impact" tab, where each row has one disclosure listing its qualified cells' reasons.

Text, not colour, carries every state.

The CSS in `styles.css` uses existing tokens only, and no colour of health. The hatch is the one the core projection
already uses for a withheld state (`coreSnapshot.css .projection-state`). `theme.css` is untouched, because it is
reconcile-guarded against the explorer. A severity chip for `NOT ASSESSED` resolves to SevChip's neutral
`--text-faint` fallback, since no `--sev-NOTASSESSED` token exists.

## Every consumer, and how it renders now

Located by grep across `webapp/frontend/src` for `stranded`, `vlans_impacted`, `blast_radius`, `keystones`,
`lower_bound`, `complete`, `n_not_ranked`, `keystone_contract`, `failure_impact` and `api.section`.

1. **Cutover planner worst-case blast radius:** `components/CutoverPlanner.tsx`, `WorstCase` (used by `WaveCard`).
   - A lower bound reads `≥ N` for both counts.
   - A wave nothing could be ranked in reads "no switch ranked · NOT ASSESSED", with both counts NOT ASSESSED. Before,
     it read a blank host and blank counts.
   - A withheld VLAN count reads unavailable.
   - `lower_bound: true` or `complete: false` adds a "lower bound" tag to the heading: the wave's worst case may be
     larger. The row's own exact counts stay exact, matching `cutover_docx`, which prints "at least" only for
     `lower_bound`.
2. **Dashboard keystones:** `pages/Snapshot.tsx`, `Keystones`. The Stranded and VLANs columns go through
   `impactEntryValue`.
   - core2-style lower bounds read `≥ N`.
   - The `NOT ASSESSED` disclosure entry reads NOT ASSESSED in both columns, and its device cell says "N row(s) not
     ranked" (or "ranking qualified"). Before, all three cells read "—".
   - A withheld VLAN count reads unavailable. Before, it read "—".
3. **Snapshot "Failure impact" tab:** `pages/Snapshot.tsx`, `FailureImpactPane`, routed from `SectionPane`.
   - It replaces `GenericTable` for this section.
   - All nine producer fields show. `GenericTable`'s eight-column cap had dropped `detail`.
   - Each value column goes through `impactTableCell`. Severity renders as a chip, and as `≥ chip` when it is a lower
     bound.
   - The `{state, reason}` disclosure of an unlistable section reads NOT ASSESSED, with the reason visible beside the
     tag. The tag is not a tab stop (fix round 2).
   - Each row has at most one tab stop: a disclosure in its host cell that lists the row's qualified cells' reasons in
     a row beneath (fix round 2).
4. **Core topology failure-impact rows:** `pages/core/TopologyPaths.tsx`, `RowFacts`, in the evidence list and the
   record inspector, through `ImpactFactView` and `FactView`'s optional `lowerBound` prop.
   - A published measure citing a witness reads `≥ N`, with its reason as a visible line.
   - Withheld cells already showed their state label and reason, so they are unchanged.
5. **Core device page failure-impact row (W29, fix round P1):** `pages/CoreSnapshot.tsx`, `FailureImpactRow` under
   "If this device fails". Its six measures and the off-scan count go through the same `ImpactFactView`. The original
   slice missed it: W29 was not yet on main, and this doc wrongly said no SPA surface rendered the device selection.

**Types.** `api.ts` gains `ImpactEntry`, `KeystoneEntry`, `BlastRadius`, `FailureImpactTableRow` and
`FailureImpactTable`, and `Summary.keystone_contract`. `Summary.keystones` (was `Record<string, any>[]`) and
`CutoverWave.blast_radius` (was `stranded: number`, `vlans_impacted: number`) now admit null counts and the W27 flags.
`src/generated/openapi.ts` needs no change: W27 changed no projection schema, and neither the summary nor the cutover
response is in the generated contract.

**Not a W27 value, left unchanged:**
- the `/graph` keystone badge (`TopologyGraph`, `Topology3D`), a boolean host flag with no count;
- the per-wave keystone chips (host names only);
- `TopologyGraph`'s `stranded`, which is the client counterfactual's node-id list, a different quantity.

## Tests (written, not run)

- `components/ImpactValue.test.tsx` covers four groups:
  - classification of entries, tab cells and projection facts, including non-coercion ("3", NaN, Infinity) and a
    witness on a non-measure or withheld cell;
  - a lower bound renders `≥ 42` with its explanation, and never as the bare "42";
  - NOT ASSESSED is never 0 or blank;
  - unavailable is distinct from 0, and a measured 0 stays 0.
- `components/CutoverPlanner.test.tsx`, four cases:
  - a lower-bound worst case: no bare "42" or "3", `≥ N` with its title and reasons, and the heading tag;
  - a NOT ASSESSED wave: both counts NOT ASSESSED, no "0", and no measured or unavailable cell;
  - a withheld VLAN count reads unavailable, with an exact count as the control;
  - `complete: false` over an exact row: the count stays measured, and the tag appears.
- `pages/Snapshot.test.tsx`, three cases:
  - keystones: a lower bound, the disclosure entry, a withheld VLAN count and an exact control;
  - the tab: nine columns; core2 lower bounds; held zeros read NOT ASSESSED; a fully held row; a published 0 stays 0;
  - the non-list section disclosure.
- `pages/core/TopologyPaths.test.tsx`: a witness on the severity and stranded measures reads `≥`. A witness on
  `off_scan_gw_vlans` does not, and unbounded zeros stay zeros, in both the list and the inspector.

- Fix round:
  - `pages/CoreSnapshot.test.tsx`: a W29 device row whose measures cite a witness renders `≥ 42`, `≥ High` and `≥ 3`
    with a visible reason naming "this row's off_scan_gw_vlans cell"; its held zeros keep their reason, and the
    off-scan count stays plain. The existing unbounded row is the negative control: a published 42 with no witness
    has no lower-bound treatment. The Trust cases cover the W46 items, and the paging test is deterministic.
  - `pages/core/TopologyPaths.test.tsx`: the realistic bounded row (four `≥` measures, two held zeros, one plain 0),
    plus the list-gate case.
  - `components/ImpactValue.test.tsx`: row-relative witness wording (the row itself, a row cell, another record, a
    look-alike pointer of another row); focus, `aria-describedby` and tap focus for every qualified state and the tag;
    `reasonShown` is neither focusable nor described twice.
  - `pages/Snapshot.test.tsx`: an empty keystone list reads NOT ASSESSED and never "no single switch dominates"; an
    absent list reads unavailable (Unit 10); an unknown tab column is disclosed and its value is not shown, with a
    control that has no note.
  - `pages/core/ProjectionList.test.tsx`: the deterministic reproduction of the paging race.
  - `webapp/tests/test_impact_surfaces.py`: the constant reconcile guard and its non-vacuity test.

Each new assertion would fail on the previous source. The old card and table printed the bare count (`42`), a blank or
"—" for null, and the tab's reason text with no state marker.

## Fix round after independent review (2026-10-09)

The W46 UI train (#628: W28, W29, W30) was merged into this branch first, so the W29 device page is covered. Only
`docs/NOW.md` conflicted; every row and handoff line from both sides is kept. Everything below is source and tests
only, and was written without running any of it (owner rule).

| Finding | Resolution |
|---|---|
| P1: the device page showed a lower bound as a plain number | Fixed. `CoreSnapshot.tsx` `FailureImpactRow` routes its measures and off-scan count through `ImpactFactView`, the one view `TopologyPaths` also uses, so both projection surfaces share one rule. |
| P2: hand-copied owner constants with no reconcile guard | Fixed. `webapp/tests/test_impact_surfaces.py::test_the_spa_impact_constants_equal_their_python_owners_in_order` reads `ImpactValue.tsx` and requires exact, ordered equality with `summary.IMPACT_FIELDS`, `summary.IMPACT_MEASURES` (and `ui_projection._IMPACT_MEASURES`), `ui_projection.IMPACT_SEVERITIES`, `summary.IMPACT_NOT_ASSESSED`, `summary.IMPACT_BOUND_MARK` and `summary._R_BOUND_LEAD`. The reader refuses a spread or computed entry, and a non-vacuity test proves it sees drift. |
| P2: `FailureImpactPane` dropped an unknown row key | Fixed by disclosure. A visible note names every key outside `IMPACT_FIELDS` and says its values are not shown. Its values are deliberately not rendered: the pane cannot classify a column it does not know, and a bare value could read as a measurement. |
| P3-1: hover-only reasons | Fixed, as described under the table above. `ImpactLowerBoundTag` gets the same treatment. |
| P3-2: unrealistic fixture | Fixed. The topology test builds the bounded row as `_topology_impact` emits it: every measure cites the witness, the zero counts are withheld with the bound's zero reason, and the non-measures cite none. A new test puts a witness-carrying, measure-named fact on a node row and shows it stays plain, while the same fact on a failure-impact row is a bound. That exercises the list gate itself. |
| P3-3: generic bound wording | Fixed, with one part rejected with evidence. Summary surfaces already show the backend's own reasons (`lower_bound_reasons`, the tab cell's text). On the core pages the projection publishes no reason on a published cell, so the wording names each witness relative to the row: "this row's own record (/failure_impact/i)", "this row's off_scan_gw_vlans cell (…)", or "the record at …". A row-level bound, such as the one #629 proposes, therefore reads accurately without depending on #629. Rejected: borrowing a withheld sibling cell's reason. `_topology_impact` cites the bound's witnesses on every measure whatever its state (`ui_projection.py` `_cell(..., witness=cite if measure else ())`, and `_cell` appends `witness` to the refs in every state). So a measure withheld for another cause (a missing key, a mistyped value) cites them too, and its reason would not explain the bound. |
| P3-4: an empty keystone list read as healthy | Fixed in the SPA, with a backend follow-up. `summary._keystones` lists every rankable row and adds a NOT ASSESSED entry for any unranked row, any lower bound below the cut, a withheld list or a blind spot. So `keystones: []` arises only when there is no failure-impact row to rank. A real "no dominant switch" result is never computed. The panel now reads NOT ASSESSED: no ranking was computed, which is not a finding that no switch dominates. A summary with no keystone list says the ranking is unavailable. **Backend follow-up:** the summary carries no failure-impact list state beside `keystones` (`impact_view`'s `state` and `withheld` are dropped), so the panel cannot quote the projection's own state and reason. Carrying them would let it. |

**W46 review items, added on the supervisor's instruction:**
- The `hostList` fixture now attaches the `trust_inputs_scope` caveat to a published or collected-but-empty list even
  when it is empty, as `ui_projection._listing`'s `kept` rule does. The Health case asserts the qualification control
  on the count, on the ratio sentence and on the list.
- The ratio sentence carries the count's qualifications control beside it (`InputGap`; the control is now exported
  from `ProjectionEvidence.tsx`).
- A device the input could not assess, whose custody is collected but empty, reads "Evidence collected, nothing
  assessable", the limitation's own meaning. The state and its style are kept (`StateLabel`'s new optional `text`).
- The vacuous guard is fixed: `ratio` is now `/inventory devices could not be assessed/`, so a sentence rendered over
  a withheld count or denominator ("3 of null …") fails the tests that forbid it.
- The Trust disclosure now says the projection counts each input's devices from the engine's per-device custody. It
  no longer says the engine publishes each count.
- **W29 flaky paging test (webapp-ci run 37883394667).** The cause was established statically: a component race,
  not a test-only artifact. The paging state starts from `initial` through `useState`. `ProjectionList`'s reset
  effect still ran on mount, aborting `request.current` and resetting to `initial`. A render outside a discrete event
  (here, the fetched document arriving) commits the DOM but flushes passive effects later. A click landing in that
  window started the page request, and the late mount effect then aborted it and reset the list. The result is
  exactly the observed state: Next enabled, `aria-busy` false, the first page shown and no error. Whether the click
  lands first depends on macrotask ordering, hence 1 in 453. Fix: the effect now resets and aborts only when its
  source (`initial`, `document`, `host`, the reference) really changed. A user's in-flight request is never
  overridden by the reference hint, and unmount aborts through its own effect. The test now holds the page response,
  asserts the request is in flight (`aria-busy` true, Next disabled), releases it inside `act` and asserts the next
  page; there are no sleeps or retries. A new `ProjectionList` test reproduces the window deterministically: a
  sibling's layout effect clicks Next after the list's DOM is committed and before its passive effect runs. It fails
  on the old effect.

## Fix round 2 after independent re-review (2026-10-09)

Source and tests only, on top of `a76be1c4`, written without running any of it (owner rule).

| Finding | Resolution |
|---|---|
| P3: `<span tabIndex=0>` puts a generic element in the focus order, and its `title` could become the name | Fixed. `ImpactValue.tsx` `Explained` renders a `<button type="button">` toggletip with `aria-describedby`. Its name is the state text ("At least 42", NOT ASSESSED, "unavailable", "lower bound") and its description is the reason. It has no `title` while a description is present. The reason shows on keyboard focus (`:focus-visible`) or activation (`data-open`, toggled by click, tap, Enter or Space). Escape or blur hides it. A click also focuses the button, because Safari does not. `styles.css` `.impact-toggletip` resets the button before the state classes, so each state keeps its own border, padding and font. |
| P3: up to 1,200 tab stops in the Failure impact tab | Fixed with the simpler pattern the SPA already uses: one `aria-expanded` disclosure per row, as in CutoverPlanner's evidence toggle. `Snapshot.tsx` `FailureImpactRow` puts a "Reasons" button in the host cell. Its accessible name is "Reasons for HOST: N value(s) not measured", and it controls a `hidden` row beneath, which lists each qualified cell as "field (state): reason". The cells are `reasonShown` spans. A fully measured row has no tab stop. A roving tabindex was not chosen: it would add grid keyboard semantics that no other SPA table has. |
| P3: the ratio sentence carried only the count's qualifications | Fixed. `CoreSnapshot.tsx` `InputGap` adds the denominator's own control. `ui_projection._inventory_total` publishes `published_caveats=_brief_caveats(ctx)`, which the count does not inherit. `Qualifications` gains an optional `text`, so the two controls read "Qualifications (k)" and "Denominator qualifications (k)", and each accessible name starts with its visible text. Each control opens its own fact's caveats. |
| P3: an absent keystone list showed NOT ASSESSED beside "unavailable" text | Fixed, per the P3-4 decision. An absent list uses the `unavailable` kind (`data-keystones="unavailable"`). A present but empty list stays NOT ASSESSED (`data-keystones="not_ranked"`). |
| P3: the tab's non-list disclosure duplicated its visible reason in a focusable copy | Fixed. It passes `reasonShown`. |
| P3: the component-level negative control for `off_scan_gw_vlans` was lost | Restored in `TopologyPaths.test.tsx`. A witness on the off-scan count of a failure-impact row renders the plain published 3 in the list and in the inspector, while the same witness on `stranded` (the control) renders `≥ 42`. |
| P3: root-pointer witness wording | Fixed ahead of PR #626 (W35). `witnessText` words `""` as `IMPACT_ROOT_WITNESS`, "the snapshot as a whole (no nearer record was collected)", instead of "the record at " followed by nothing. `projectionImpactBound` is the only bound-wording helper that names witnesses. The evidence drawer's generic reference list still prints a raw pointer, so a root reference there renders an empty `<code>`. That drawer is not a bound-wording helper and is left unchanged. |

Tests (written, not run):
- `ImpactValue.test.tsx`:
  - queries every toggletip by role `button` and its name, and checks its exact accessible description;
  - checks that the toggletip has no `title` and that activation, Escape and blur toggle the reveal;
  - checks that a form is not submitted;
  - checks that `reasonShown` is a plain span that keeps its `title`;
  - adds unit tests for the `""` witness wording (alone, without a row pointer, beside a nearer witness, and through
    `impactReasonText`) and for `impactStateText` and `impactReasonText`.
- `CutoverPlanner.test.tsx` and the keystone case in `Snapshot.test.tsx` check role, name and description in place
  of `title`.
- `Snapshot.test.tsx`:
  - an absent list reads `unavailable` and not NOT ASSESSED, with no button;
  - an empty list never reads `unavailable`;
  - a new tab case covers 14 rows: at most one tab stop per row, `rows - 1` stops for the table, and none for the
    measured control row. It also checks the disclosure's `aria-expanded` and `aria-controls`, the hidden reasons row,
    and the listed fields, states and reasons, including an `unavailable` off-scan count;
  - the non-list disclosure has no button, no `tabindex` and one visible copy of its reason.
- `CoreSnapshot.test.tsx`: a denominator caveat gets its own control inside the sentence, opening only its own caveat.
  A count with no caveat still shows the denominator's control, and a denominator with no caveat shows none.
- `TopologyPaths.test.tsx`: the restored off-scan negative control.

No existing assertion was removed. The `title` assertions on toggletips became accessible-description assertions,
which is the stronger check. The `title` assertions on `reasonShown` cells still hold unchanged.

## Not verified here

- vitest, `tsc`, the Vite build and every browser run. The hosted "Frontend test + type-check + build" job decides,
  and the supervisor's UI train imports its dist.
- Pixel baselines. The design-sync demo plan (`.design-sync/providers/sample-data.ts`) carries only measured
  blast-radius values with no W27 flags, and a measured value renders in an unstyled span. So the CutoverPlanner card
  should be pixel-identical, but no capture confirmed it. The toggletip button's reset was not compared visually with
  the span it replaced.
- Screen-reader and touch behaviour were not checked with assistive technology or a touch device, and no axe run took
  place. Each reason sits in an `aria-describedby` target with a focus or activation reveal, in the row disclosure,
  or in a visible line.

## Residuals outside this slice

- `atlas-scope/` renders failure impact in its own embed and is not touched here (owner rule).
- Engine-rendered deliverables still read raw rows (W27's recorded F5).
