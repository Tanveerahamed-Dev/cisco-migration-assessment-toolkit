# W34 — stored STP observations in VLAN selections

Status: source/control authoring on `codex/stp-root-facts`, based on owner-merged
main `fa110851275405c9e89d4b72d498e67a10f1377d`. Hosted execution, generated API
agreement and the new native audit pins are **not yet verified**. This record must
be updated with actual source-bound results before a supervisor handoff.

## Product boundary

G15's existing VLAN election verdict remains owned by the stored
`vlan_cutover` fields. This residual replaces each VLAN row's
`selections.stp_roots` pointer list with a closed fact list of the selected stored
`/stp_roots/<host>/<vid>` observations. Each item retains the original host and
escaped pointer and exposes `is_root`, `root_address` and `root_priority` facts.
It neither invokes an election nor chooses a winner from duplicates. Readable
duplicate claims remain beside an already ambiguous VLAN verdict.

The parser can create a row from a VLAN header and default `is_root` to false
without parsing a root identity. That case is disclosed as root not parsed, not
as an observed negative. A present malformed flag is unverified, never false.
An explicit true claim survives independently absent identity fields. A stored
false with readable identity remains only the parser's stored flag: the old
record does not retain `bridge_address`, so it cannot independently establish
complete negative capture. Missing and malformed address/priority fields are
held separately; a priority of zero is not absence.

Original VLAN-key spelling, aliases, escaped hosts, namespace selection, source
failures and pointer collisions retain their evidence boundaries. The nested
fact list travels whole within the existing `/vlans/rows` view/list page. It
does not create an arbitrary nested pagination endpoint. No parser, snapshot,
golden, sample, engine election or frontend renderer change is intended.

## Closed schema and native review

The new observation uses existing fact states/types and local schema references.
Closed records and lists, flag typing, withheld null values/reasons and priority
domain must agree under native and stock validation. Both view/list schema pins
will change because they include the owner definitions. No runtime calculation
may populate an acceptance pin; provider/version/domain/offline/copy/refusal and
public-error behavior stay intact.

The hosted frontend job produces bounded `ui-projection-contract` review
material before its unchanged blocking `api:check`. The canonical generator's
exclusive `--review` mode writes to a fresh fixed directory outside the checkout.
The observer retains the actual app OpenAPI, generated TypeScript, exact native
schema bytes and owner hash observations, dependency identities, and before/after
tracked source byte/mode/tree/parent bindings. It never changes committed API
types or native pins. A bootstrap with stale committed types/pins must still fail
the ordinary gates; preserving its diagnostic is not a waiver or qualification.

Observed material and schema deltas require independent review before literal
pins/types are applied. Final source must independently pass canonical
regeneration, stock/native valid and hostile envelope parity, source/binary
workflows and all current protected checks. Producer digests and ordinary
diagnostic transport are not independent archive custody or release acceptance.

## Authored control obligations — execution pending

- Real parser root/non-root and header-only records; explicit true with missing
  identity; malformed flags before default handling; zero/missing/malformed
  priorities; readable fields retained beside malformed cells.
- Duplicate claimants and unchanged ambiguous VLAN verdict; original aliases,
  escaped host pointers, selected non-mapping rows, MST separation, unavailable
  sources, blind-host custody, collisions and malformed VLAN selectors.
- Complete closed-schema validation, source purity, nested view/list equality,
  rejection of invented nested selectors, native/stock rejection of old pointer
  arrays, wrong flag/value states and extra/missing members.
- Hosted observer source drift, dirty index/worktree, assumed-unchanged bytes,
  unknown/overwritten/oversized review members, canonical owner serialization,
  exclusive generator modes and workflow failure-evidence/byte-check ordering.

No authored control is described as executed yet. Existing tests are retained;
pointer-only expectations are adapted to the new fact envelope with their
original counterexamples intact. All runtime/generation/schema calculations
remain on GitHub. Concurrent Claude projection/native changes must be integrated
with a reviewed re-pin and wholly fresh gates. W26's owner merge and historical
focus proof do not qualify this new source.
