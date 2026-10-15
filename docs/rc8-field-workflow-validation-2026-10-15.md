# RC8 P0: saved-plan field workflow evidence

This is a source and hosted-evidence record for PRs [#666](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/666)
and [#667](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/667).
Final-head readiness belongs to their live checks and closing review comments. This record grants no
merge, document approval, field qualification, signing or release authority.

## Product boundary

The baseline is RC7/main `3401627f6fd69bb838a2c921d7f95c77b2373623`, retaining G14. Foundation
`f66dc68e62560af343c3ca4bddd1a0423d16dfdc` adds immutable saved planning projections, append-only
selection events and assessment-linked document identity. Foundation correction
`3d73a58a3c0e3c42d4fc342f0956ea93a1e9a656` adds plan-only UTC-Z compatibility without rewriting
timestamp/hash bytes. The visible app workflow is their dependent
change. Product/schema versions, engine writers, tracked golden files and sample outputs are unchanged.

| Operator outcome | Source owners | Validation owners |
|---|---|---|
| Open saved plans directly from an assessment | `CoreSnapshot.tsx`, `Snapshot.tsx`, `App.tsx` | navigation/component tests and real-backend browser journey |
| Save requirements, reopen the same projection and explicitly select a revision | `storage.py`, `deliverables.py`, `app.py`, `SavedPlan.tsx` | saved-plan storage/API/export suites; frozen restart qualification |
| Download matching MOP/NRFU drafts | `generate_saved_plan`, `savedPlanDocument`, `saveVerifiedDocument` | actual DOCX tests, native browser downloads and frozen Windows HTTP journey |
| Keep references distinct from requirements-derived documents | `deliverables.saved_plan_basis`, `/api/meta` | closed ten-writer partition and unknown-writer refusal tests |
| Refuse dirty, stale, cross-source or corrupt contexts | Store integrity/CAS, API pre/post render checks, UI epochs and download admission | adversarial storage/API/client/component tests and two-tab browser refusal |
| Generate offline with the bundled Windows application | `portable/atlas_bundle.py`, `qualify_atlas.py`, `release_contract.py` | exact-source `Build and qualify Atlas.exe`; physical/managed-host gates remain separate |

Design, CRD, MOP, NRFU and the deck consume the selected requirements/design. Other documents retain
explicit assessment-baseline sections. Original snapshot/Protocol Assurance JSON remain separate.
The full workbook remains CLI-only. Saving/selecting and generated NRFU checklists never mean approval
or passed acceptance tests. Windows and a supported local browser are prerequisites; document generation
uses bundled libraries and requires no host Python, Node, Office installation or remote service.

## Hosted operator journey

Producer head `80f38cacb80e0c62d6f856a29812513b7780f9bb` was tested as merge
`ecc3de74ab5969cbb58ea16f886ab426392240ff` (parents foundation `f66dc68e` and that head;
tree `ed7533a1353e2637db396fa50beb841f93670d4d`, equal to the head tree).
[Webapp run 38798213389](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38798213389)
completed **SUCCESS**. Its frontend job `116645147880`, existing browser checks, Windows visual checks,
real-backend browser job `116645147894` and complete backend suite all succeeded.

The synthetic real-browser record proves ordinary upload, keyboard controls, two persisted revisions
(ACI and NX-OS EVPN, retaining convergence zero), reload/reopen, actual distinct MOP and NRFU native
downloads, dirty-form blocking, a competing selection, HTTP 409 with no download/automatic latest
substitution, explicit reload and recovery export. Final selection is older revision 1/event 3.
The original 2,513,782 assessment bytes remain unchanged; browser/API errors and foreign-origin
requests are empty. The 728px layout is checked. `physical_host_qualified=false` remains explicit.

The real-browser artifact is `12003892552`, 231,347 bytes, SHA-256
`4da945bc36253fbea2a1831516723be7230f04913438d5fd508cec8e65117cc6`.
Its JSON evidence and actual three DOCX members were independently read as data and reconciled:

| Document | Revision / selection | Bytes | SHA-256 |
|---|---|---:|---|
| MOP | 1 / 1 | 60,398 | `20f5f00cdfb049698182f1254d2e5c7c13ab969b0aa39dd8b2237202e4e98176` |
| NRFU | 1 / 1 | 53,976 | `c6469f5a78eea5c386f7f45c1da116f29f5d3c4af53e24da007e203bed956076` |
| Recovery MOP | 1 / 3 | 60,404 | `2f49355cea865d75e09304699c3603940d4d0bfe425e46b02c83aa7f08bc732b` |

These are synthetic draft document observations, not release ZIP identities or network acceptance.

## Source-bound frontend transfer

The independently selected Git profile has **164 inputs**. Producer handoff artifact `12003258036`
is 583,072 bytes, SHA-256 `694c562c0f4437a698ece5916abd015493953f4afc1b80e3620fd4956422e52a`.
Node `v24.19.0`, npm `11.17.0`, source-before/after records, all input identities, five output members,
member hashes, index/dynamic links and canonical marker policy reconcile. Generated JavaScript was
reviewed as data and never executed locally.

[Hosted receiver 38802429323](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38802429323)
frontend job `116654768384` completed **SUCCESS** on receiver head `80f38cac`. Its receipt artifact
`12004133741` is 1,114,512 bytes, SHA-256
`678db124b08297784545cf64ce6fb85bd79bf5c99e25ebd4bd1c4bec6e0c0a24`.
The receipt is `frontend-artifact-receive/1`, `ADMITTED_EDIT_DATA_REVIEW_REQUIRED`, with no errors.
Acceptance, compatibility, dependency validation, current-source readiness and release authority are
all **false**; `final_source_rebuild_required=true`. The manual receiver's other app checks are separate
from this admission result; its whole-run conclusion must be read live rather than inferred.

The receipt preserves the exact selected producer, archive, source/parents and seven receiver-current
policy inputs. Its opening/closing API observations are byte-identical. Only `admitted.patch` is eligible
for import: SHA-256 `6c72c8513dfaee11bc416bac846aa498a5a44a748c5259caeed463ff76de3b9d`.
It closes to five regular output files, with nine changed paths including two explicit chunk renames.
No authored frontend source or dependency manifest is changed by the transfer. The final published
source must independently rebuild these committed bytes and pass every applicable gate.

## Negative evidence retained

- Foundation `ecb4b091`: six CI legs stop at two stale full-source download-name pins; canonical API
  observation also finds missing generated route types. Reconcile only the changed owner pins and
  source-bound generated types. No discovery exclusion or existing negative control is removed.
- Foundation `5ddc5ce4`: complete backend testing finds recursive validation-error encoding for deep
  plan JSON, a missing explicit digest string cap and an inconsistent synthetic baseline fixture.
  `f66dc68e` adds pre-decoder depth admission using the unchanged 64 ceiling and exact 71-character
  digest bounds. The fixture is repaired to the producer contract with all original assertions retained;
  the former malformed case now explicitly proves INDETERMINATE/no invented blockers/MOP HOLD.
  Full webapp run `38796794068` succeeds on `f66dc68e`, closing these three findings on that source.
- UI `71dd9386`: three client tests fail (615 pass) at cross-realm native response bytes; Scope's
  stricter indexed access finds TS2532; the added callout shifts the unchanged graph guard past the
  viewport by 0.125px; the new upload test incorrectly assumes automatic navigation. Fix exact
  intrinsic byte admission, optional media parsing, only the new heading's line box, and actual visible
  upload-roster navigation. Existing tests, budgets, tolerances and timeouts remain.
- UI `144c6ca6`: exact label lookup includes nested select option text although accessible names are
  correct. Caption-only sibling labels preserve the IDs, options and order. Exact selectors and all
  assertions remain, with enabled/focused keyboard preconditions. The superseded failed-source run
  `38796819206` finishes cancelled; its failed job/log/artifact remain preserved, never treated as green.
  The complete corrected producer on `80f38cac` closes the supported journey.
- Foundation `f66dc68e` Python 3.10 job `116635407602` fails its complete default suite with 39 failures,
  19,229 passes, 297 skips, 3 expected failures and 26 passing subtests. All failures are original
  export fixtures with terminal UTC `Z`, which the older interpreter's ISO parser rejects. The actual
  Store producer uses `+00:00`. Correction `3d73a58a` preserves all 39 fixtures/assertions and adds a
  plan-only parsing adapter for both envelope and selection validation, keeping the shared legacy
  parser and original stored/digested strings unchanged. Added controls prove distinct raw Z/+00
  hashes, malformed/naive/nonstring refusals and Store save/reselect/context/source-byte preservation.
  The new combined source requires fresh supported-runtime validation; earlier passes do not close it.
- UI `15ec794d`: CI run `38805134587`, Python 3.14 job `116664462330`, fails the complete default
  suite with 19 failures, 19,393 passes, 165 skips, 3 expected failures and 26 passing subtests.
  Eighteen failures arise from a middle-dot added to the ASCII-only Windows field guide. Restore
  ASCII wording; retain its existing encoding guard. The other failure is the real-browser tier's
  unchanged prohibition on request interception: replace the new journey's HTTP/WebSocket routing
  with passive request/socket observers on the initial and subsequent pages. Traffic stays unmodified;
  all original foreign-origin, browser-error, native-download and stale-plan assertions remain.
  No existing test, gate, timeout, budget or generated output changes. Earlier hosted browser and
  frozen-package passes on this head do not close the failed complete suite. The observer edit changes
  a frontend-profile input: the earlier 164-input receipt remains the import event's evidence only;
  require a fresh complete hosted producer and post-import receipt for the corrected profile.
- UI `848030b4`: real-browser run `38812233814`, job `116688127197`, reports one failure and
  two passes. The native MOP and NRFU downloads exist, but the second document's late
  `response.body()` call, after saving the native file, receives Chromium's `Network.getResponseBody`
  resource-not-found error. Artifact `12009640412` is 6,800,421 bytes, SHA-256
  `566cfa8d80edf0e03123841cec78ae928561abcd7a32e7df3553a0f19a000918`.
  Its trace shows MOP body retention succeeds and NRFU HTTP 200/identity headers and native download
  precede the failed body read. The generic navigation diagnostic does not establish an actual page
  navigation or a product rendering failure. Start retaining the original response body directly in
  the registered response continuation before awaiting the button click. Still compare those exact
  bytes against the native file; retain every status/header/provenance assertion. No separate GET,
  request interception, retry, body fallback or relaxed check is introduced. Require a fresh complete
  browser journey, whole producer and corrected-profile receipt; the failed run cannot supply them.

## Review and delivery boundary

Require all 15 live protected contexts on each final head, complete applicable application/visual/
reference/source checks, and fresh frozen Windows qualification after this import. Earlier-head passes,
partial receipts and cancelled runs do not transfer. #666 is reviewed first; after its owner merge,
#667 must be retargeted to main and revalidated before any merge. Neither PR is merged by this task.

All runtime tests, builds, engine runs, browsers and verification controllers remain GitHub-hosted.
Local work is Git/static reads, permitted privacy/marker checks and reviewed data-only transfers.
All 14 external gates remain pending. No version/release cut, signing, physical field qualification or
publication is performed; existing releases remain draft-only.
