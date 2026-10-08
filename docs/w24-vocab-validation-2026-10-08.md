# W24 engine-owned vocabulary rank and class (G43) validation

Branch `claude/vocab-rank` (#617). Every fleet, device and path engine document carries the
constant `vocab` block (`ui_projection_vocab/1`). No transport envelope carries it: every view,
path and list response keeps its key set from main. Exposing the block through the transport is
a recorded follow-up.

This is a source checkpoint. No local test, build, OpenAPI export, type check, projection or
browser run was made, because the owner's rule is GitHub-hosted only. Every runtime verdict is
pending hosted evidence.

## Reviewed transport-schema delta

The native view and list schemas embed every owner definition in `$defs`
(`{**_DEFS, **_TRANSPORT_DEFS}` in `webapp/backend/ui_projection_api.py`). So owner definitions
move the pinned bytes even when no transport branch reaches them. Over main, the delta is:

1. **23 added definitions:**
   - `Vocab`, `VocabClass`, `VocabRanked` and `VocabUnranked`;
   - one closed `Vocab<Name>Item` for each of the 19 ranked vocabularies.

   No definition is removed. The existing `$defs` keep their order, and the additions follow
   the topology definitions.
2. **`DeviceDocument` and `PathDocument`** each gain the required property `vocab`, a `$ref` to
   `Vocab`.
3. **No transport branch changes.** The `oneOf` view and list branches are byte-equal to
   main's. The 23 definitions, `DeviceDocument` and `PathDocument` are unreachable from every
   branch: 203 of 286 definitions are reachable for views and 180 of 286 for lists, none of them
   `Vocab*`. So the native instance domain, `_native_instance_allowed`, the provider version
   (`jsonschema-rs` 0.58.5), the private resolver guard and the Python fallback are unchanged.

**Keywords.** The added and changed definitions use only `$ref`, `additionalProperties`,
`const`, `enum`, `items`, `maxItems`, `maximum`, `minItems`, `minLength`, `minimum`,
`properties`, `required`, `title`, `type` and `uniqueItems`. Every one of them is already in
main's established view and list profile, so none is outside the established domain.

**Catalogue closure.** A static sweep of the combined owner schema runs without projecting a
snapshot. It finds 55 string enums in 48 token sets outside the `Vocab*` closure. Each token set
is classified exactly once by the catalogue (19 ranked, 29 unranked); none is unclassified and
none is invented.

## Combined with W23 (main `d0e10888`)

#616 (W23: `DevicePage.failure_impact` and `structural_links`, impact holds, 18 device
limitations) merged as `d0e10888`. This branch merged that main with a merge commit and re-pinned
on the combined schema. W23 adds no string enum and no limitation ID, so the G43 catalogue needed
no change.

The hashes are compact `ensure_ascii` JSON plus LF, in owner key order. They were computed
statically with `ui_projection_api._native_schema_hash`, with `backend.ui_projection_api` and
`cisco_toolkit.ui_projection` imported from this worktree (`__file__` asserted).

**Method check.** An extract of main computes main's own pins:
- view: `a2fd2b9994569b2fd3a3df72e3410ae1b74ff41c26833a62239514c677f9de32`
- list: `c47a6ceff24a7392fa9b248ece33b36381f9fd27fc67d3d52ea3d8238a37e0c9`

**W24 alone, before this merge (from `a97fdfc9`).** These were never pinned, and the branch
still carried the older pair:
- view: `72a437f656078e7480424d770d7661e19ca343b93d2295791a8e93299e91598d`
- list: `501806faefb4987f88453ad8cf5c27e89199153008c40297070cda52200af34e`

**Combined W23 + W24.** These are now in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective
pair:
- view: `732c68c3d762f2b3d4d0329582bd32f3842567feef9cab20960f6959eef07372`
- list: `7f256f809f1d9e0754a2312579ee6afdfe3ae5e58c2b5dd7b44fbfd32b5369b5`

**`openapi.ts`.** The W23 and W24 hand edits touch disjoint generated members, so Git merged them
without conflict:
- W23 changed `DevicePage`, the 18-item device limitation tuples and the two device list variants.
- W24 changed the `vocab` member of `DeviceDocument`/`PathDocument` and the `UiProjection1_Vocab*`
  components.

openapi-typescript 7.13.0 renders each component independently, so the union is the expected
output. Hosted `api:check` remains the authority.

**W28 moves the same pins.** W28 (`claude/trust-inputs`, G08) moves the same pins and
regenerates the Trust limitation copies. Whichever of W24 and W28 merges second must:
- re-pin again on top of the other;
- regenerate `openapi.ts` on that combined schema;
- classify W28's `TrustInputHost.custody` enum in this catalogue.

That enum's token set (`collected_but_empty`, `not_collected`, `analysis_unavailable`,
`unverified`) matches no current vocabulary, so `tests/test_ui_projection_vocab.py` v1 would
report it unclassified. `TrustInput.input` reuses the `dossier_axis` token set and is already
classified. Neither pin set on this page is valid for that combination.

## Verification boundary

Local evidence:
- `py_compile` of the touched Python files;
- the static assessability guard helpers from `tests/test_protocol_assessability.py`;
- the static pin, delta, keyword and enum-sweep computations above.

Still required before merge:
- every protected exact-head hosted check, including the native-parity group and `api:check`;
- independent Codex refutation;
- the supervisor's merge.
