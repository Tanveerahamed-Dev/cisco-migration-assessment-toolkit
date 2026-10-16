# RC8 P0: saved plans and matching portable exports

Status: implementation for independent review. Baseline is RC7/main
`3401627f6fd69bb838a2c921d7f95c77b2373623`. Product release preparation and all external
field/signing/acceptance gates remain separate. No release is published by this workstream.

## Operator outcome

Atlas keeps one Windows entry point. The app will expose a visible saved-plan and document workflow:
import evidence, review the assessment, enter requirements, save a revision, reopen/select it, and
download the matching Design/CRD/MOP/NRFU/deck. Office-format generation uses bundled libraries;
it does not require host Python, Node, Docker, Office or a remote service. Windows and a supported
local browser remain host prerequisites.

The backend foundation is a separate reviewable change from its visible app workflow. A backend API
alone does not establish a complete operator journey. Both the source/backend tests and the exact frozen
Windows qualification must succeed before that journey is reported as verified.

## Separate identities

- The assessment is the exact persisted snapshot JSON and its existing snapshot/campaign/engagement
  binding. Saving a plan never edits its bytes, original source authority or baseline observations.
- A plan revision is an append-only, source-linked envelope containing normalized requirements and the
  derived planning sections. The storage owner hashes its complete immutable envelope once. Reopen uses
  the saved result; a newer planner must not silently change the same revision.
- Selection is an append-only event. Save/select requires the previous selection ID. Selecting A, then B,
  then A creates three different selections; the first request cannot masquerade as current again.
- New-plan metadata accepts aware UTC `Z` and `+00:00` consistently on supported Python runtimes.
  Validation never rewrites the original timestamp string or its immutable hash/authority bytes;
  legacy execution/receipt timestamp parsing remains its separate owner.
  The UTC-Z spelling uses ASCII `YYYY-MM-DDTHH:MM:SS[.1-6 digits]Z`; lowercase, interior or duplicate
  designators and an offset plus `Z` refuse. Hours are 00-23 and minutes/seconds 00-59. Its bounded
  numeric fields construct an aware UTC datetime directly, keeping ISO-parser normalization outside
  this boundary. Calendar validity remains constructor-owned. Fraction expansion occurs only in
  temporary validation values. Non-Z aware timestamp behavior remains unchanged.
- Every saved plan is `UNAPPROVED_DRAFT`. Saving and selecting do not grant document approval, CAB,
  execution authority, signing, qualification or publication authority.

`webapp/backend/storage.py` owns the envelope/digest and finite revision/selection/payload limits;
`webapp/backend/deliverables.py` owns supported requirements, planning projection and document semantics.
`docs/ssot.md` registers these owners. This document describes the contract, not a second fact engine.

## HTTP contract

| Request | Behavior |
|---|---|
| `GET /api/snapshots/{id}/plans` | Verified revision metadata, complete assessment binding and current selection ID; zero selection means no saved plan |
| `POST /api/snapshots/{id}/plans` | Accept label, requirements, exact assessment binding and expected selection ID; derive outside the Store lock, append and select atomically |
| `POST /api/snapshots/{id}/plans/{revision}/select` | Require exact plan digest and expected previous selection; append a new selection event |
| `GET /api/snapshots/{id}/plans/{revision}` | Require plan digest and current selection ID; reopen the verified saved record |
| `GET /api/snapshots/{id}/plans/{revision}/deliverable/{kind}` | Require the same pins; render outside the Store lock and recheck before sending bytes |

All routes inherit the existing origin/token/session/request-body guards. New heavy planning/export
work uses the existing nonblocking, memory-bounded generation admission. Invalid input, unavailable
renderer, exhausted limits, changed selection and corrupted data retain distinct refusal states.
Errors do not disclose requirements or database contents.

The download carries `X-Atlas-Assessment-SHA256`, `X-Atlas-Plan-Revision`, `X-Atlas-Plan-SHA256`,
`X-Atlas-Plan-Selection` and `X-Atlas-Plan-Status`. Visible document provenance and bounded machine
identity name the same source/revision/selection. The file is deleted on successful response construction,
render failure or a selection conflict. Legacy exports without a saved-plan context keep their behavior.

## Planning and evidence boundaries

Normalized requirements use `cisco_toolkit.design_advisor`. The saved projection contains exactly
`requirements_register`, `design_blueprint` and `design_nrfu`. Only these three plan-owned sections
overlay the assessment copy passed to a planning writer. Architecture coverage, coverage matrix,
unknown evidence, schema census, fact lineage and executive brief retain their stored assessment
basis; saving a plan does not recompute or promote them. Projection/derivation profile `/2` refuses
older profiles and additional observed sections, even when an envelope has been rehashed.

The CLI and saved-plan preparation share their complete planning prefix through
`cisco_toolkit.design_advisor.derive_plan_sections`: requirements, blueprint and design NRFU, in
that order. The saved-plan profile publishes an explicit empty register; assessment preserves the
original absent-register behavior. Assessment-only architecture/coverage, unknown evidence,
audit/summary/integrity and census/lineage/recensus/workbook publication remain exclusively in the
CLI, in their original order and four fail-soft boundaries. The canonical SSOT owner remains a
read-only fact reader. Render-time SSOT integrity disclosure remains active on an isolated writer
copy and preserves original failures; it does not rewrite the persisted assessment or turn an
inherited failure into a successful phase.

The engine's requirements contract also owns saved-plan list fields, option values and VLAN bounds.
The actual OpenAPI schema exposes it, and the existing hosted generator emits its runtime metadata
and types into `openapi.ts`. The required generation freshness check compares that complete output.
Legacy CLI normalization keeps its existing behavior. Protocol Assurance dispatch uses one set in
the artifact registry for both HTTP routes and both document-rendering paths.

Design, CRD, MOP, NRFU and the deck consume the saved planning projection. Other existing documents
may be associated with the revision, but their assessment-baseline sections are labelled explicitly.
In particular, current cutover and engagement owners do not transform their wave/gate content from
requirements; association is not a universal wave-parity claim or a new execution plan approval.
Original assessment integrity failures remain in force. In particular, an inherited Design blueprint
or requirements failure can keep the Design document's recommendation section withheld as
UNVERIFIED, even when a new draft blueprint exists. The saved-plan stamp discloses this limit;
saving a draft does not repair or clear the assessment failure. Selected-plan identity and stored
inputs match the export basis, but universal content parity across such withheld sections is not
claimed.

The Protocol Assurance sidecar is built only from the original `BoundSnapshot` and its persisted-byte
binding. Its complete binding must match the plan's assessment. It is passed unchanged to the supported
writers. A derived planning dictionary is never serialized and rebound as fresh observed evidence.

## Persistence, migration and recovery

Empty additive tables and new named protection triggers preserve prior database rows, columns,
schema-object definitions and SQLite sequence state during migration. No synthetic historical plan,
startup reseal or `user_version` change is introduced. Integer digest anchors detect incremental BLOB
rewrites that ordinary UPDATE triggers cannot see. Source/plan/campaign deletion and rebinding refuse
when they would sever saved-plan provenance.

Existing whole-database boot backups and verified staged updater copies retain the plan tables. New
tests exercise populated saved-plan preservation. Physical unplug, full/read-only media, managed policy,
actual Python-absent disconnected host and field-operator acceptance remain external pending gates.

The portable qualification receipt has a schema successor because its closed database census and owned
evidence change. Superseded receipt IDs refuse under the new contract. The engine/schema version
`cisco_toolkit.__version__` and release product version are not bumped during feature implementation.

## Acceptance evidence

The app's primary assessment page links directly to **Saved plans · MOP / NRFU**. That workspace
shows all server-declared document choices, separating selected-requirements documents from
assessment-baseline references. MOP and NRFU have primary download buttons. Original snapshot and
Protocol Assurance JSON stay separate; the full workbook remains an explicitly CLI-only output.
Unsaved edits disable export and selection until saved or discarded. A changed selection, source or
record refuses and requires an explicit reload; there is no automatic fallback to a newer revision.

The simple browser form accepts whole non-negative convergence milliseconds up to
`9007199254740991`, preserving zero and accepted text until server normalization. This is the
browser's exact-integer profile, not a changed engine limit. Larger values refuse before the save
request. Saved documents are bounded, verified against the requested assessment/plan/selection
headers and type before creating a browser download. A server refusal produces no document.

Hosted tests must demonstrate save/reopen/restart, normalized zero and malformed-input behavior,
cross-assessment refusal, stale save/selection including A→B→A, source and plan tamper refusal without
resealing, atomic rollback, and unchanged raw assessment bytes. Actual DOCX/PPTX tests inspect visible
and machine identities, original protocol authority, requirements/wave content and retained draft/gate
posture. A render/selection race must refuse and clean its temporary file.

The exact frozen Windows helper uploads a bundled synthetic snapshot through normal HTTP intake,
saves and selects revisions, restarts on the same database and verifies MOP/NRFU content and identity.
That is a finite hosted synthetic scenario. It is not live-device, physical Windows deployment, signing,
human acceptance or publication evidence. All original gates, budgets, timeouts and negative evidence
remain. Golden and sample outputs stay byte-identical.

Frontend changes use the existing GitHub-hosted API observation and source-bound SPA handoff/receiver
workflow. No local application tests, builds, engine runs, browsers or verification controllers run.

The hostile alias-allocation cases retain a 1 MiB plain string and a 4096-NUL string, each repeated
1024 times. Their explicit short pytest IDs keep the framework's `PYTEST_CURRENT_TEST` value below
Windows' environment-variable limit without putting the payload itself into the case name. Both
original encoder-allocation guards, payload expressions and 4 MiB refusal assertions remain intact.
This corrects framework setup/reporting; fresh hosted results must still prove both cases and the
complete source/frontend gate on the final head. Earlier timed-out runs remain negative evidence.

## Current-main integration and retained validation (2026-10-16)

Owner-merged #665 advances main from RC7 source `3401627f` to `9112a16e`. Its hosted
knowledge-export controller, tests and writer census are integrated with this foundation.
The application logic, qualification contract, test inputs/assertions, original limits, versions
and golden/sample bytes are unchanged by this integration. All incoming knowledge-export
source bytes remain owner-owned; its manual controller still deliberately targets RC7 source.
The actual manual generation ends `report_audit_refused`, so no fresh graph or project vault
is established. That separate failure is preserved without granting local generation authority.

On preceding A `4aebecc8`, all six supported-runtime matrix jobs pass. Windows records
19,581 passes, 58 skips, 3 expected failures and 26 passing subtests in 6,523.74 seconds.
This closes the old oversized-case-ID setup failure on that source. The separate pinned
source/frontend job `116806226399`, run `38849132444`, is cancelled at its unchanged
120-minute limit at 06:09:41 UTC. Its last progress is 98%; there is no completed Python
aggregate or frontend result. Its complete 109,721-byte log has SHA-256
`2bdcf6f68cc9ba9fad0bc940075ad48e79f78ee5bde13a66e30b90025ad189aa`.
No earlier F/E progress marker or oversized-ID exception is observed. A cancellation-frame
Pydantic interrupt and pytest temporary-path teardown error do not identify the active test
or prove the runtime-overrun cause. The timeout remains an unsatisfied gate.

Dependent B `6f33d57d` separately passes all 15 required-context equivalents and six
applicable whole workflows, including the same pinned source profile and 87.44% coverage
against the unchanged 85% threshold. Both actual Windows profiles use CPython 3.12.10;
matching base-package lists are not a claim that every matrix/tooling dependency is identical.
An independently recommended one-job repeat of old A is not dispatched: its exact-source
guard detects the main advance first. No source-level performance fix is inferred.

The integrated heads need fresh complete hosted gates and source-bound frontend evidence.
Earlier positives and all timeout/cancellation records do not transfer. A's coverage was pending
at the earlier integration checkpoint; the subsequent source push superseded it, with job
`116807637257` ending CANCELLED at06:31:06 UTC rather than producing a coverage result.
The unchanged gated eight-module type check passes; the full-project advisory report's
1,475 diagnostics match both main340 and preceding Bbf2 exactly. Existing named audit
suppression, unattributed `2 ignored` output, reference capacity warnings and all 14 external
gates remain explicit. No test, budget, timeout, suppression or approval is loosened.

## Supervisor SSOT refutation and required closure (2026-10-16)

Independent audit `wf_f0aab664-711` refutes readiness of foundation `c95c2b74` and dependent
`46ffef86`: the saved projection also overlaid recomputed observed companions, the late pipeline
was duplicated in a different order, sidecar membership and requirements domains had multiple
owners, and two SSOT rows did not distinguish assessment and saved-plan bases. Earlier green
jobs and package receipts remain evidence for their exact sources, not closure of these findings.

The correction limits the saved projection to its three owned sections, shares the complete planning prefix,
centralizes sidecar membership and generates the UI requirements contract from its engine owner.
SSOT rows for assessment headline facts and stored design decisions now point to the saved-plan
owner row for the selected-plan basis. New hostile drift/profile/writer-isolation and metadata
freshness cases accompany the change. Runtime behavior is not verified until the revised heads
pass all 15 required contexts, applicable whole workflows and source-bound frontend/package checks.
The generated contract must come from the hosted observation; no local generator or build runs.
Independent review follows those gates. No PR merge, release cut or publication is authorized.

Static follow-through also finds the existing registry producer-key guard still searches only
the CLI and analysis module. Its source closure now includes only the unique shared planning helper body,
after verifying the CLI calls that owner exactly once with `snap_dict` and the assessment profile.
Every existing required key and assignment assertion remains. This ownership adaptation requires
fresh hosted execution along with the original in-process pipeline and golden/sample checks.

## Hosted architecture refusal and owner correction (2026-10-16)

Foundation fb6acc0e Reference run38871468415/job116876310326 fails exact-tree compilation:
`edge:3129:undeclared:canonical_snapshot->design_intelligence`, plus edges3134/3135 from
canonical_snapshot to governance. The helper's placement in ssot.py introduced forbidden reverse
dependencies. Its full75,089-byte log has SHA-256
`a95f4e3a5c1aa5671bbdafdd54dd2dd92b246494b4dd119b7b249b7ea13a663b`.
The capacity step then refuses21 unmeasured walls because compiler/downstream receipts are absent;
zero measured walls exceed95% and none lie between85% and95%. This is not a measured capacity breach.

The correction moves the entire shared three-section planning prefix to its existing design owner
and restores the assessment-only blocks to their original CLI location/order/boundaries. It adds no
module, reverse-dependency exception or architecture allow-list entry. The dependency policy,
compiler gate and every capacity ceiling remain unchanged. Existing hostile observation/profile/
writer-isolation controls remain, while shared-prefix and actual CLI order/failure tests bind the
corrected ownership. Fresh exact-source Reference, runtime, golden/sample and all15 gates must pass;
prior bounded static review and old successful jobs did not close this architectural failure.

## Hosted cached-OpenAPI failure and final-owner correction

Foundation0b48a64a backend run38876448685/job116905008015 fails step11 at09:50:25Z.
The actual-owner freshness control at test_saved_plan_api.py302 mutates the returned contract's
list_fields, then a second app.openapi() still returns consumer_only instead of the owner value.
The94,614-byte complete raw log has SHA-256
f87b2ab08e5a782f37083b30013703e8bad0f697553ade10deb8d065e182d440. This is an actual failed
backend gate; its quiet summary provides no numerical passing aggregate.

The cause is the final projection OpenAPI wrapper installed after the app constructor. It calls
the earlier subclass method only on cold construction, then serves the cache directly. The new
subclass therefore cannot refresh metadata on cached calls. The correction removes that redundant
subclass and places the fresh engine-contract assignment after the final wrapper's unchanged native
cache boundary. Native schema creation stays lazy/cached; no schema reset or recomputation is used.
The original mutation/domain assertions remain, with added nested mutation, native identity/content
and per-app construction-count controls. No native pin, generated type, limit or gate is changed.

On0b48, Reference38876448865/job116892547721 separately succeeds with complete162,418-byte
log SHA-25668af452185ad7077cbefdcbd823a48deddb5acfcdab41c46fbd9e48f77af79a4. All45 capacity
walls are measured:43 below85%,2 warnings,0 at95% and0 unmeasured. The warnings remain release
census85.24% and longest JSON string85.00%, within unchanged ceilings. Release status remains
unsigned_preview_incomplete. That closes the old architecture failure on0b48 only; it does not
close the new backend failure or transfer validation to this correction. Require fresh exact-head
backend/cache/export, full source/matrix/Reference/golden/sample and all15/whole workflows before
independent review. All existing source-bound negatives and external gates remain preserved.

## Current-main integration after the corrected warm-cache control

Foundation e695f445 full application workflow38884733578 succeeds, including full webapp/tests
job116919702637 (88,346-byte EOF, SHA-256
6224618acf594285d00cadf94fafb7ccfcee0fd9d7fe02151dceb07dbb39a2bf; no printed numeric aggregate).
Python3.14 job116919903073 succeeds with19,560passed/165skipped/3xfailed/26subtests,
137,634-byte EOF SHA-256205623e123817f3533fa63749cfb1cf35c4450dae3b3753ea7989914cd54f60d.
Only7/15 required contexts were green before main advanced; none qualifies the integration.

The previous0b48 Python3.10 job116892958485 prints an unidentified F at93%09:58:53Z,
then reaches97% before supersession cancellation. It has no final failing identity or aggregate.
Do not attribute that marker only to the known warm-cache test, infer a timeout or call the suite
a pass. Its frozen required ledger retains7SUCCESS/8CANCELLED with all15 terminal EOF logs
reviewed; ledger SHA-256e9139567d2c178db6b0fdaf406e7b5c0dd6b6587a712b0a055b103df8be7e71b.
Fresh full Python3.10 success is required without retrospectively identifying the old marker.

Supervisor main d73d33e28bafe91f750e25f20dee559d412ac485 merges #671 knowledge diagnostics
with parents9112a16e and34f71d25. The six-file incoming change is preserved, including its
knowledge-writer census count, alongside the saved-plan endpoint pins. NOW keeps both parent
handoff histories and the merged K2 row historically. No knowledge generation or local Graphify
runs here. Independent static union review and stable Rule7/marker scans precede the integrated
push; all15 required contexts and every applicable whole workflow must pass on that new head.
The earlier B4f actual-document/SPA reviews remain source-edit DATA, not integrated-source
readiness or a replacement for the final source-bound rebuild/receipt. No existing test, verifier,
budget, timeout, golden/sample byte, product/schema version or external gate is relaxed.
