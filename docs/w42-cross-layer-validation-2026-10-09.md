# W42 cross-layer correlations on the Findings screen (G24)

Branch `claude/g24-cross-layer`, started from main `a06d1d27`. This record covers contract gap
G24 (`docs/one-app-contract-gaps-2026-09-30.md`, section 25). `findings.cross_layer` now carries
the engine's stored cross-layer correlation rows and the health deduction each row drives on each
device it names.

This is a source checkpoint. No local test, build, OpenAPI export, type check, projection run or
browser run was made; the owner's rule is GitHub-hosted only. Every runtime verdict is pending
hosted evidence and an independent refutation.

## What the contract now says

`findings.cross_layer` is a `CrossLayerRowList`: the stored `cross_layer` list from
`analyze.compute_cross_layer_correlations`, in the producer's order, never recomputed.

Each row (`CrossLayerRow`) carries:
- `index` and `pointer` (`/cross_layer/<k>`);
- `id`, `layers`, `title`, `detail` and `recommendation` as text facts;
- `severity` as the existing `SeverityFact` (the punch-list severities, already ranked by the
  G43 `vocab` block), so no new closed vocabulary is introduced;
- `hosts`, a `CrossLayerHostRowList`.

Each host (`CrossLayerHostRow`) is kept at its own index (`/cross_layer/<k>/hosts/<j>`) and
carries four facts:
- `host`: the stored text;
- `device`: a new `PointerFact` whose value is the devices-map record of exactly that name
  (`/devices/<host>`);
- `deduction_ref`: the existing `EvidenceRefFact`. It is the one reference the device's
  `health_scores` row publishes to this cross-layer row, with subject
  `/health_scores/<i>/deduction_refs/<m>`;
- `deduction`: a text fact. It is the line item that reference sits beside, with subject
  `/health_scores/<i>/deductions/<n>`, for example `CL-01 Critical (-18)`.

### Why the deduction is a selection, not a derivation

`analyze.compute_health_scores` turns each cross-layer row into one line item per host it names.
It writes the text `f"{id} {severity}"` plus ` (-{points})`, and a reference
`_evidence_ref("analysis_row", host, ("cross_layer", k), "derived_from", ...)`. It then cuts both
lists after the same first eight deductions. The projection therefore:
- selects the reference by its exact pointer `/cross_layer/<k>`;
- selects the line item by the row's own `<id> <severity>` label, never by position (the
  `deduction_refs_are_subsequence` rule still holds: references are not index-aligned).

The points are the scorer's per-item weight as published. They come before the scorer's
per-category cap and the device's criticality factor, so they are not the change in the score.
The `row_selection_by_exact_key` limitation says so, and every published line item cites it.

The device page needs no change for the gap's second screen ("health deduction sources"): its
existing `health.deduction_refs` items point at `/cross_layer/<k>`, which is exactly the
`pointer` of a `findings.cross_layer` row. That is a join by exact key, which the register
already classes as layout. A new test pins it.

### States (coverage honesty)

Absence is never health. First match wins.

**The list**
- A failed `Cross-Layer correlations` phase is `analysis_unavailable`.
- A failed input (`interfaces`, `physical_health`, `l3_forwarding`; `CROSS_LAYER_INPUTS`, held
  against `build_dependency_map`'s signature) is also `analysis_unavailable`, stated as "may be
  incomplete". The rows it has stay visible.
- An absent section is `not_collected`.
- While `collection_completeness` lists any blind spot, the list carries
  `fleet_lists_exclude_blind_devices` with a witness per blind-spot row, and an empty list is
  `not_collected`. This is the `_fleet_qualify` precedent of the punch-list, VLAN, endpoint and
  topology lists.
- Otherwise an empty list is `collected_but_empty`.

**A host**
- A host that is not text is `unverified`, by its type check.
- A blank host is `unverified`.
- A host the row names twice is `unverified`, with a witness to each entry. The producer writes
  `sorted(set(hosts))`, and a test reads that from its source.
- In each of those cases `device`, `deduction_ref` and `deduction` are withheld with the host's
  own state, reason and witnesses. The entry is never dropped.
- A row naming no host at all is `unverified`.

**The device join**
- A host with no devices-map record is `unverified`, with a witness to the host entry ("joins no
  collected device").
- A device `collection_completeness` lists as not collected is `not_collected`, with that row
  as witness (`_resolve`'s device scope).

**The deduction**
- The health join uses the same device scope.
- No health row is `unverified`: the scorer scores every named host of the interface model the
  rules ran over.
- Two health rows naming the host are `unverified` (`_R_AMBIG`).
- A failed `Health Scores` phase is `analysis_unavailable`.
- An `Insufficient Data` device is `not_assessed`, exactly as its device page withholds its
  deduction references.
- An unreadable reference list keeps that list's own state and reason. The list is read once
  by `_health_deductions`, which the device page now shares.
- No reference to this row while the device's deductions reached the cut of eight is
  `not_collected`, with `engine_list_capped` and a witness to the deductions: it may lie beyond
  the cut. Below the cut it is `unverified`, because the producer always writes one.
- Two references to the row are `unverified`, with a witness to each.
- A reference that is not the scorer's analysis-row reference for this host (kind, role or host
  differs) is `unverified`.
- The line item is `unverified` when the row's id or severity is withheld, when no published
  deduction carries the label, or when several carry it with different points.
- Several byte-identical line items carry the label when two rows of one rule and severity name
  one device. The producer emits that case, and a real-scorer test drives it. They are published
  once, with no subject and a witness to each, because which position belongs to which row is
  not published.

## Limitations (instance data only)

No limitation ID was added. A 30th payload limitation would also flip openapi-typescript's
`--array-length` tuple rendering of every non-device `limitations` member to an unbounded array.

Six existing limitations gain `/findings/cross_layer` in `applies_to`. Four of them also gain
text, where the rule is new:
- `one_hop_failure_attribution` (scope only);
- `abstention_addresses_dict_paths_only` (scope only);
- `projection_owned_verdicts` (the cross-layer checks against their producers);
- `engine_list_capped` (a deduction that may lie beyond the cut is withheld, never absent);
- `row_selection_by_exact_key` (the host, reference and line-item joins, and the points' meaning);
- `fleet_lists_exclude_blind_devices` (correlations are computed over the same collected evidence).

These texts and scopes are instance data, not schema.

## Reviewed transport-schema delta

The native view and list schemas embed every owner definition. Over main the delta is:

1. **Seven added definitions.** Five owner definitions: `PointerFact`, `CrossLayerHostRow`,
   `CrossLayerHostRowList`, `CrossLayerRow` and `CrossLayerRowList`. Two transport definitions:
   `Source_CrossLayerRowList` and `Page_CrossLayerRowList`. No definition is removed. The defs
   count goes from 286 to 293.
2. **`Findings`** gains the required property `cross_layer`, after `rows`. So `LIST_CATALOG`
   gains `findings: /cross_layer`. The findings view payload pages it, and the list union gains
   one branch, after findings `/rows` and before topology `/nodes` (37 branches).
   `next(iter(LIST_CATALOG["findings"]))` is still `/rows`.
3. **No transport envelope changes.** View, path and list responses keep their exact key sets.
   Atlas Scope reads no findings view, so its exact-key `envelope()` is unaffected and no
   `atlas-scope/` edit is needed.

**Keywords.** The added and changed definitions use only `$ref`, `additionalProperties`, `anyOf`,
`const`, `dependentRequired`, `items`, `maxItems`, `maximum`, `minItems`, `minLength`, `minimum`,
`oneOf`, `required`, `title`, `type` and `uniqueItems`. A static sweep finds none outside the
established view and list profile.

**Reachability.** 209 of 293 definitions are reachable from the view branches and 186 of 293 from
the list branches. Six of the seven new ones are reachable; the owner `CrossLayerRowList` is
reached only through its `Source_`/`Page_` pair. The new values add no float (only integer indices
and strings), so the admitted native instance domain is unchanged. So are the provider version
(`jsonschema-rs` 0.58.5), the private resolver guard and the Python fallback.

### Hashes

The hashes are compact `ensure_ascii` JSON plus LF, in owner key order. They were computed
statically with `ui_projection_api._native_schema_hash`, with `backend.ui_projection_api` and
`cisco_toolkit.ui_projection` imported from this worktree (`__file__` asserted). No test,
validator or projection ran.

**Method check.** Main `a06d1d27` reproduces its own pins:
- view: `732c68c3d762f2b3d4d0329582bd32f3842567feef9cab20960f6959eef07372`
- list: `7f256f809f1d9e0754a2312579ee6afdfe3ae5e58c2b5dd7b44fbfd32b5369b5`

**W42.** These are now in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair
(`webapp/tests/test_ui_projection_api.py`):
- view: `bd0702147829feba7dd94517519e5470050a67661b0f6a4350a707b89df7a63c`
- list: `5228e59009aebefbe8f1fabf47f8d74a0801c7d733083e775c085db7ac4762c7`

Any other branch that moves these schemas re-pins on top of whichever merges first.

## Generated types and fixtures

`webapp/frontend/src/generated/openapi.ts` was hand-edited to the generator's style:
`--immutable --alphabetize --array-length`, `localeCompare` order. The edit adds:
- the seven components in alphabetical place;
- `cross_layer` on `UiProjection1_Findings` and on the findings view payload;
- the `/cross_layer` list-response branch, with the unchanged 29-item limitation tuple.

A static census (component names against `openapi_owner_definitions()` plus the transport
definitions, and the property sets of the new objects) finds 293 = 293, nothing missing and
nothing extra. The hosted `npm run api:check` remains the authority.

The synthetic `findingsFixture()` in `webapp/frontend/src/test/projectionFixtures.ts` gains an
empty `cross_layer` page. No runtime frontend source, no `dist` and no `atlas-scope/` file changed.
No screen renders the new list yet; that is a follow-up.

## Tests (written, not run)

`tests/test_ui_projection_cross_layer.py`:
- **Schema and owners.** The closed schema shape. `CROSS_LAYER_INPUTS` held against
  `build_dependency_map`'s signature. `_CL_RANK` held equal to `SEVERITIES`. The producer's
  stored row keys, its `sorted(set(hosts))`, and every severity literal (including CL-09's
  conditional), all read from the producer's AST.
- **Real stored data.** On the sample, all 43 rows are compared field by field with independent
  lookups. All 54 host entries publish their device, reference and line item. 49 sit at the
  scorer's cut and 5 below it, and each line item equals `<id> <severity> (-<the scorer's default
  weight>)`. The golden's 5 host entries publish too. The device page's `/cross_layer/<k>`
  references join the rows by exact pointer.
- **The real scorer** (`analyze.compute_health_scores`):
  - the line-item label;
  - two rows of one rule on one device, giving one value, no subject and two distinct references;
  - nine rows on one device, where the scorer cuts one and that one reads `not_collected` with
    `engine_list_capped`;
  - an unmeasured device, which the scorer bands `Insufficient Data`, reading `not_assessed`.
- **Contradictions.** A missing reference at and below the cut. A repeated reference. A foreign
  kind, role or host. A missing line item, conflicting points and identical items. An unjoinable,
  blank, non-text or repeated host, each kept at its index.
- **Never a clean result.** Blind spots, a failed phase, a failed input, a failed health phase,
  an absent section and garbage inputs.

`tests/test_ui_projection_inventory.py`: two reviewed `CAP_SITES` exemptions. Naming the producer
makes its prefix slices reachable to the cap walk. Both are `(+N more)` disclosures inside a
detail the projection publishes verbatim, and the row's title states the full count:
- CL-06 `pos[:12]`;
- `_vlan_list_summary`'s `vids[:cap]`.

A static replay of the walk finds no other unreviewed or stale site.

`webapp/tests/test_ui_projection_api.py`:
- the re-pinned W12b prospective pair;
- a new test that the findings view pages `/cross_layer` as an owner list with its host joins.

The static guards ran on every changed non-test file: the hand-list scanner, the
section-dependency reader proof and the repository-wide hand-list sweep. Each reported zero
sites. An AST scan for local names shadowing module helpers found none.

## Residuals not closed here

- **Evidence references.** Cross-layer rows also carry `evidence_refs`, which the punch-list
  fold already projects on its own rows. They are not projected on `findings.cross_layer`: they
  have no `evidence_basis`, so the punch-list evidence contract does not apply as written.
- **The score change.** The applied change in score per row is not published by the producer: it
  depends on the per-category cap and the criticality factor over all of a device's items.
  Publishing it needs a producer change, plus golden and sample regeneration through the W31
  handoff.
- **A rendered screen.** No AssessHub or Atlas Scope screen renders `findings.cross_layer` yet.
