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
- `projectionImpactBound(field, fact)` reads the projection's own mark on a core-page failure-impact row: a published
  measure (`summary.IMPACT_MEASURES`) that cites a `witness` ref. This is the mark `summary._impact_bounds` reads. It
  is applied only to the failure-impact list, because a witness ref on any other projection fact means something else
  (the existing FactView test pins a published 0 with a witness as 0).
- `<ImpactValue state>` renders the four states, and `<ImpactLowerBoundTag>` tags a figure that is a lower bound as a
  whole.

Classification never coerces. A count that is not a finite number is unavailable, never read as a number, and a
published 0 stays 0.

| State | Shows | Accessible explanation |
|---|---|---|
| measured | the value, in an unstyled span | none needed |
| lower bound | `≥ N`, with a dashed underline (`.impact-bound`) | `title` and screen-reader text: "At least N: a lower bound, not an exact measurement (why)" |
| not assessed | the neutral, hatched `NOT ASSESSED` tag (`.impact-na`) | `title` and screen-reader text carry the engine's reason |
| unavailable | faint italic `unavailable` (`.impact-unavailable`) | `title` and screen-reader text: withheld, "not a measured 0" |

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
   - The `{state, reason}` disclosure of an unlistable section reads NOT ASSESSED, with the reason visible.
4. **Core topology failure-impact rows:** `pages/core/TopologyPaths.tsx`, `RowFacts`, in the evidence list and the
   record inspector, through `pages/core/ProjectionEvidence.tsx` `FactView`'s new optional `lowerBound` prop.
   - A published measure citing a witness reads `≥ N`.
   - Withheld cells already showed their state label and reason, so they are unchanged.

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

Each new assertion would fail on the previous source. The old card and table printed the bare count (`42`), a blank or
"—" for null, and the tab's reason text with no state marker.

## Not verified here

- vitest, `tsc`, the Vite build and every browser run. The hosted "Frontend test + type-check + build" job decides,
  and the supervisor's UI train imports its dist.
- Pixel baselines. The design-sync demo plan (`.design-sync/providers/sample-data.ts`) carries only measured
  blast-radius values with no W27 flags, and a measured value renders in an unstyled span. So the CutoverPlanner card
  should be pixel-identical, but no capture confirmed it.
- Screen-reader output was not checked with assistive technology. The text is in `.sr-only` spans and `title`s.

## Residuals outside this slice

- `atlas-scope/` renders failure impact in its own embed and is not touched here (owner rule).
- The device page payload carries a `failure_impact` selection (W23), but no SPA surface renders it yet.
- Engine-rendered deliverables still read raw rows (W27's recorded F5).
