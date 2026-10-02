# W2 integration preflight (2026-10-01)

**Read-only preparation, not implementation or a new work queue.** Follow `docs/NOW.md`.
Inspected W2b `e74a4c42`, slice 2 `d0a9737a`, and main `497e26b6`. Reverify these owners after
#579 and W2a merge. No W1 files, branches or devices were changed.

## W2a contract integration

- `cisco_toolkit/ui_projection.py`: `_finding_row`, `_findings`, `_FINDING_ROW_CELLS`,
  `_slice2_defs` / `FindingRow` must preserve producer evidence refs, basis and optional total.
  I23 in `tests/test_ui_projection_inventory.py` names `evidence_refs_total` as well as the
  three main fields. Retain the legacy no-pointers limitation only where evidence is absent.
- `_device_page` / `DeviceHealth` must expose `deduction_refs` separately from deduction text.
  The producer defines an ordered subsequence, not an index-aligned array. Do not invent pairs.
- Engine refs have `kind`, `host`, `ref`, `role`, `cite`; they are not the projection envelope's
  existing `{pointer, role}` refs. Preserve source vocabulary, RFC 6901 pointers and caps.
- W2b later requires the exposure record/schema to carry `input_state`, VLAN projection to
  consume the new election owner, and Inventory `DeviceRow` to carry move-group identity.
  Reconcile the old source assertion that groups have no labels without losing legacy cases.

## W2c backend map

- `webapp/backend/storage.py :: Store.get_snapshot` supplies the full stored snapshot;
  metadata's cached summary is a different derivative. `get_bound_snapshot` binds parsing
  to the same store bytes whose binding was checked. `get_snapshot_blob` and `/raw` show the
  existing digest/byte-count/`assesshub-store-blob` transport convention.
- `webapp/backend/app.py :: RowId` bounds SQLite IDs; `_api_access_guard` guards `/api/`
  routes. Preserve its cross-site, remote-authentication, HTTPS, loopback and Host behavior.
  Relevant regression owners: `test_expensive_get_hardening.py`, `test_snapshot_raw.py`,
  and `test_backend.py` under `webapp/tests/`.
- `webapp/backend/engine.py` is the current engine adapter boundary. Projection work belongs
  there; backend/browser code must not create a second owner of analysis facts.
- Slice 2 exposes `project`, `project_inventory`, `project_findings`, `project_device`,
  and `project_devices`. The last shares context across independently owned device documents.
  `ui_projection_schema()` owns the closed Draft 2020-12 contract.
- The inspected backend has no existing typed response-model or pagination implementation
  to reuse. Mechanically bind declared HTTP response models to the engine schema, including
  published/withheld unions; do not silently drop fields through a narrower model.
- Pagination needs an explicit transport/schema boundary. A published list currently requires
  at least one item and disallows extra properties. Slicing it to an empty page or inserting
  paging fields would violate the contract. Preserve original engine state, totals, refs and
  row indexes. Paging after full projection limits response size, not computation cost; measure
  that cost and preserve existing expensive-GET protections.
- Keep snapshot transport identity distinct from an engine fact. The projection engine block
  does not currently publish a content hash/byte size. Unknown-host HTTP behavior also needs
  an explicit contract; the engine currently returns withheld evidence for an unknown host.

## Existing v2 visual reference

The prior Claude project memory points to a surviving `prototype-v2` directory in that session's
private scratchpad. The original transcript records `atlas-one.html` being published as
**v2: engine contract only**. Current local bytes: 4,595,430; SHA-256
`c3a1357ced8df63959579326fd02f4c212bf5305b772df7b7aa71b5d60bd313f`.
The private artifact URL and machine path are deliberately not copied into this public record.

Static source map (no source executed):

| Surface | Reference pattern | Local source within the reference |
|---|---|---|
| Shell | Sticky 56px header, five task tabs, search, evidence drawer, draft strip and campaign rail; 1600px content maximum | `src/shell.html`, `src/js/20-shell.js`, `src/atlas.css` |
| Overview | Posture statement, five metrics, fleet posture, gating items, decisions, risk ledger, lifecycle and readiness placeholders | `src/js/30-overview.js` |
| Trust | Coverage summary/state chips, device-by-axis matrix, lineage, gaps, assurance, limitations and build detail | `src/js/70-trust.js` |
| Inventory/device | Four inventory subtabs, filtering/sorting, paired evidence cards and collapsed engineering sections | `src/js/60-inventory.js` |
| Findings | Punch-list/risk/security/cross-layer/architecture tabs, compact expandable rows, Issue/Remediation/Evidence detail | `src/js/50-findings.js` |

The source declares light/dark tokens, IBM Plex Sans/Mono with fallbacks, 12px cards, 16px gaps,
neutral missing-state hatching, labels alongside colour, mobile bottom navigation and reduced
motion. Reconcile tokens with the repository's existing SSOT owners. Do not import its stored
snapshot claims or introduce runtime font/network dependencies into the offline field app.

**Rendering not verified.** The hosted attempt required sign-in; browser policy rejected the
local `file://` preview. No alternate route around that policy was attempted. No existing
screenshots were found under the reference directory. Local-to-hosted byte equality is also
not verified. This source is a visual reference, not a second application or fact owner.
