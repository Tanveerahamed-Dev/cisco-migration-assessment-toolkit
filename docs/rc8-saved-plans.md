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

Normalized requirements use the existing engine owner. The derived projection persists the blueprint,
design NRFU and their owner-computed coverage/SSOT/lineage companions. It does not replace observed
devices, topology, original protocol evidence, validation facts or baseline negative gates.

Design, CRD, MOP, NRFU and the deck consume the saved planning projection. Other existing documents
may be associated with the revision, but their assessment-baseline sections are labelled explicitly.
In particular, current cutover and engagement owners do not transform their wave/gate content from
requirements; association is not a universal wave-parity claim or a new execution plan approval.

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
