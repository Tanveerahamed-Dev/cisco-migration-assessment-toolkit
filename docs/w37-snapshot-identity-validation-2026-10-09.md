# W37 snapshot identity in the engine block (G41) validation

Branch `claude/g41-snapshot-identity`, from main `a06d1d27`. This record covers gap G41 of
`docs/one-app-contract-gaps-2026-09-30.md`: the snapshot's content hash and byte size in the
projection's `engine` block, so every pointer names the exact byte string it resolves in.

This is a source checkpoint. No local test, build, OpenAPI export, type check, projection, browser
run or benchmark was made, because the owner's rule is GitHub-hosted only. Every runtime verdict is
pending hosted evidence.

## What changed

Every fleet, device and path document's `engine` block gains three members:

- `snapshot_sha256`: a new closed `Sha256Fact` (`^sha256:[0-9a-f]{64}$`), basis
  `protocol_assurance.bound_snapshot_source:sha256`;
- `snapshot_bytes`: the existing `PositiveCountFact`, basis
  `protocol_assurance.bound_snapshot_source:bytes`;
- `snapshot_digest_form`: the constant `exact-parsed-bytes`.

Both facts are computed from bytes, not read at a snapshot address, so they carry no subject and no
ref. They always share one state and one reason.

## Where the bytes come from

The projection receives a parsed snapshot, so it cannot know the bytes itself. The engine already has
one owner for this: `cisco_toolkit/protocol_assurance.py`.

- `bind_snapshot_json_bytes` parses and hashes one byte string and mints a `BoundSnapshot`. That is
  a process-local marker which JSON output and `dict()` copies drop.
- `bound_snapshot_source` reads the marker back. It re-derives the content digest, so any change to
  the content after binding refuses the marker.

The projection reads that receipt once per context and never hashes anything. Its import allowlist
admits only `BoundSnapshot` and `bound_snapshot_source`, and still no `hashlib` or `json`.

| Input | `snapshot_sha256` / `snapshot_bytes` |
|---|---|
| A `BoundSnapshot` its owner verifies | `published`: the owner's values, verbatim |
| A plain parsed mapping (or not a mapping) | `not_collected`, with the reason that no bytes were handed over and a re-serialisation is never hashed in their place |
| A `BoundSnapshot` changed after binding | `unverified` |
| An owner fault | `unverified`, with the owner fault text |
| A malformed receipt (digest spelling, a non-positive, boolean, fractional or unsafe byte count, a missing or non-true `source_bound`) | `unverified` |

**AssessHub.** The transport cache already binds the store blob with
`engine.bind_ui_projection_snapshot(raw)`. It hands each producer call a `deepcopy`, and the copy
keeps the marker. The existing hosted test
`test_projection_reads_one_bound_source_and_no_legacy_backfill` asserts `source_bound is True` on
exactly that copy. So every real view, list, device and path response now publishes the identity.

**Byte form.** `docs/ssot.md` requires a digest to be shown with its form and never compared across
forms. The engine's form is `exact-parsed-bytes`: the byte string the reader parsed, with no newline
or encoding normalisation. Equal JSON content in other bytes therefore has another identity.

In AssessHub that byte string is the persisted store blob. The engine fact and the envelope's
`assesshub-store-blob` identity are then two SHA-256 computations over one `raw` object, not two
forms being compared.

**Path ordering.** `project_path` now reads the engine block before the FIB owner runs. Before this
change it read it last.

## Transport rule

`webapp/backend/ui_projection_api.py :: _require_engine_source` runs at cache admission, after the
complete owner-schema validation.

- A **published** identity that names any byte string other than the admitted blob raises. This
  covers the digest and the count, and equal content in other bytes. The admission is not cached and
  is retried on the next request.
- A **withheld** identity is served exactly as the owner wrote it. The transport never writes or
  fills an engine fact.

The real path always binds, so a withheld identity occurs only when a producer is substituted (for
example the existing synthetic-state tests). A dedicated test pins that every real response
publishes.

The path route already refuses a path document whose engine block differs from the admitted
document's.

## Atlas Scope

`atlas-scope/src/contract-mode/load.ts :: envelope` requires an exact envelope key set. G41 adds
**no envelope key**: the identity rides inside the existing `engine` member. Scope checks `engine`
only as an object. It compares it whole across pages and hashes it with `limitations` into the
context digest (`projectionContextDigest`).

So no Atlas Scope edit is needed, and no Codex handoff is raised. As a side effect, the Scope context
digest now also binds the source identity.

Scope's tests build their documents from `webapp/frontend/src/test/projectionFixtures.ts`, which is
updated here. The envelope key sets stay pinned by
`test_owner_vocab_stays_in_engine_documents_and_out_of_every_transport_envelope`.

## Native transport schema re-pin

The hashes were computed statically with `ui_projection_api._native_schema_hash`. Both
`cisco_toolkit.ui_projection` and `backend.ui_projection_api` were imported from the source root
under test, with `__file__` asserted. They are compact `ensure_ascii` JSON plus LF, in owner key
order.

**Method check.** A `git archive` extract of main `a06d1d27` reproduces main's own pins:
- view: `732c68c3d762f2b3d4d0329582bd32f3842567feef9cab20960f6959eef07372`
- list: `7f256f809f1d9e0754a2312579ee6afdfe3ae5e58c2b5dd7b44fbfd32b5369b5`

**This branch.** These are now in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair:
- view: `f718cd0b4cb32454d61ab2b3c2e6f2364c660eaf1020cf06c7235ed7143e669e`
- list: `b514aff49c63661aea7135517cc0e5242f9c6f7959d755a374b4d3b014d01b37`

**Reviewed structural delta**, for both view and list:
- one added definition, `Sha256Fact`, at position 41, just before `Engine`;
- one changed definition, `Engine`;
- no definition removed, and every existing definition keeps its order;
- the `oneOf` branches are byte-equal to main's: 6 view and 36 list;
- `Engine` is reachable from every branch, so `Sha256Fact` becomes reachable. Views go from 203 to
  204 of 287 definitions; lists from 180 to 181. `PositiveCountFact` was already reachable through
  the topology rows.

The reachable keyword profile is unchanged at 20 keywords: `$ref`, `additionalProperties`, `allOf`,
`anyOf`, `const`, `dependentRequired`, `enum`, `items`, `maxItems`, `maximum`, `minItems`,
`minLength`, `minimum`, `oneOf`, `pattern`, `properties`, `required`, `title`, `type` and
`uniqueItems`. `pattern` was already reachable through `Pointer` and the envelope identity.

The new values are `sha256:`-prefixed lowercase hex strings and safe integers. Both are inside
`_native_instance_allowed`'s audited domain. The path schema reaches 30 definitions instead of 28.
It stays a Python-only contract.

**Catalogue.** The static enum sweep still finds 55 string enums in 48 token sets, each classified
exactly once. `snapshot_digest_form` is a `const`, like the other schema constants, not an enum, so
the G43 catalogue needs no change.

## Generated types and fixtures

`webapp/frontend/src/generated/openapi.ts` was hand-edited to openapi-typescript 7.13.0's output
(`--alphabetize`):
- `UiProjection1_Engine` gains `snapshot_bytes`, `snapshot_digest_form` (a `/** @constant */`
  literal) and `snapshot_sha256`, in the generator's collation order. That order is the one that
  already puts `Source_*` before `SourceFact`.
- The new component `UiProjection1_Sha256Fact` sits between `SeverityFact` and `SharedIpFact`. Its
  `value` is `string`, because a `pattern` renders as plain `string`, as `Pointer` and the envelope
  `identity.sha256` already do.

No runtime frontend source or tracked `dist` changed, because type-only edits are erased. The
hosted `api:check` remains the authority.

The synthetic `common()` engine block in `projectionFixtures.ts` and the typed `ProjectionEngine`
literal in `projectionEmbed.test.ts` carry the three members. The latter also asserts that a changed
identity changes the context digest.

## Atlas frozen smoke

`portable/build_atlas.py :: _smoke_ui_projection` now builds its owner expectation from
`bind_ui_projection_snapshot(raw)` over the exact served bytes, as the hub does, instead of
`json.loads(raw)`. Without this the served (published) engine block could never equal the expectation.

`tests/test_atlas_projection_smoke.py` builds its fixture the same way and asserts that the fixture
publishes the identity, so the comparison is not vacuous. It also adds four refusals:
- a served digest for other bytes;
- a wrong byte count;
- a withheld identity;
- a later list page whose engine copy names other bytes.

## Tests written (not run)

- `tests/test_ui_projection_snapshot_identity.py` (new) covers:
  - the real sample's exact bytes in fleet, device and path documents, each schema-validated;
  - binding changes the two identity facts and nothing else in the whole payload;
  - byte-not-content identity: whitespace variants and a compact re-encoding;
  - the no-hash rule: no digest of the file, any common re-serialisation or the owner's canonical
    form appears;
  - detached, deep-copied and plain-copied snapshots;
  - an owner fault;
  - 19 malformed or negative receipts, plus a well-formed control published verbatim;
  - one owner read per context, with fresh containers per document;
  - the identity read before the FIB owner runs;
  - the closed schema and 13 forgeries.

  Every expected digest is computed independently with `hashlib` over the bytes the test read.
- `tests/test_ui_projection.py`: the minimal snapshot's identity is `not_collected`, and the import
  allowlist names the owner (with a reason).
- `webapp/tests/test_ui_projection_api.py`:
  - every view, list and path response names the store bytes, and one digest spelling serves both
    the envelope and the engine;
  - refusal and retry for three forgeries, including equal content in other bytes;
  - the withheld pass-through;
  - the existing owner-equality view test now projects from the same exact-byte binding;
  - the pins are re-pinned.

## Cost

`bound_snapshot_source` re-derives the canonical content digest to verify the marker. That is one
pass per projection context; each transport document has its own context. The local diagnostic
timing below is not hosted evidence:
- about 30 ms for the 3,333,301-byte sample;
- the transport's existing per-document `deepcopy` of the same sample takes about 50 ms.

The hosted 300 ms sample gate counts the first lazy device document, so this pass is added there. It
must stay green on the exact head.

## Unchanged

- No new `cisco_toolkit` module and no new file under `cisco_toolkit/` or `webapp/backend/`. So the
  LF byte-custody receipt and the golden attestation module-count strings do not move.
- No golden, sample or snapshot section change.
- No limitation was added.

## Follow-ups

- The SPA's "Snapshot and engine identity" panel already shows the envelope identity. Showing the
  engine-owned facts with their states needs a runtime-source edit and a hosted `dist` refresh.
- A command-line or MCP consumer that reads snapshot files would publish the identity by binding the
  file bytes with `bind_snapshot_json_bytes` before projecting. None projects today.

## Verification boundary

Local evidence:
- `py_compile` of every touched Python file;
- an AST scan for locals that shadow a called module-level name (none);
- the static helpers of `tests/test_protocol_assessability.py`:
  - no hand-listed receipt states in the touched scanned files;
  - the section-dependency proof passes;
  - the receipt-reader set is unchanged;
- the enum-catalogue sweep;
- the static pin, method-check and structural-delta computations above;
- the rule-7 privacy and marker scans.

Still required before merge:
- every protected exact-head hosted check, including the native-parity group, `api:check`, the
  Atlas frozen smoke and the 300 ms projection gate;
- independent refutation;
- the supervisor's merge.
