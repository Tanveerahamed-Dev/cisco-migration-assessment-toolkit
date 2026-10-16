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
timestamp/hash bytes; `bee0dba2b81e5386932a7ca5e5b0271356d7e80d` closes malformed-Z admission
with an ASCII extended timestamp grammar and transient fraction padding, preserving the same bytes.
`8fca0ddda1017f2d9c2e5e8e77b7ac67ff47e41b` bounds UTC-Z clock fields and constructs aware UTC
directly, keeping interpreter ISO-parser normalization outside that validation boundary.
The visible app workflow is their dependent
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
- Foundation `3d73a58a`: CI `38804920843`, Python 3.10 job `116663859609`, closes all 39 valid-Z
  export failures but reports one failure, 19,277 passes, 297 skips, 3 expected failures and 26 passing
  subtests in 3,564.47 seconds. The unchanged malformed `2026-10-15T00:00:00ZZ` negative is accepted
  after suffix replacement leaves `Z+00:00` for that older parser. `bee0dba2` closes UTC-Z lexical
  admission before conversion and retains all original fixtures/assertions, raw envelope/hash bytes
  and the shared legacy parser. Additional controls cover fractional hash preservation, malformed
  designators, calendar validity, early refusal and unchanged non-Z offset handling. Its corrected
  source is merged into this dependent branch; fresh final-head hosted gates remain mandatory.
- Foundation `3d73a58a` portable source/frontend job `116663739701` in run `38804920913` ends
  cancelled, but its pre-cancellation log already contains two real failures in the new large-child
  output test. Both success/failure variants see an empty readiness file: existence precedes the
  synthetic child's `write_text` completion. `acf55054cf94a5aeee4e06dc622aeda617da4b17` changes only
  that child fixture to close a sibling pending file and atomically publish it afterward. All 21
  assertion ASTs, output/sentinel/flush ordering, variants, cleanup, failure-tail bounds and timing
  values remain unchanged. The blocked-PIPE control still cannot publish readiness. Old Windows and
  coverage jobs cancel without a completed pass. Their logs and the two failures remain evidence;
  fresh exact-source validation must close this separate correction too.
- Foundation `acf55054` Python 3.14.8 job `116697640808`, CI `38815006575`, reports one failure,
  19,448 passes, 165 skips, 3 expected failures, 8 warnings and 26 passing subtests in 4,064.78 seconds.
  Dependent `8327211d` separately reports the same sole failure in job `116698855883`, CI
  `38815376708`: one failure, 19,450 passes, the same skips/expected failures/warnings/subtests,
  in 4,104.89 seconds. The retained `2026-10-15T24:00:00Z` negative is accepted when ISO parsing
  normalizes that clock value. `8fca0ddd` closes hours to 00-23 and minutes/seconds to 00-59, then
  constructs an aware UTC datetime directly from bounded fields. It preserves the original negative,
  shared non-Z behavior and every raw timestamp/hash/authority byte. Seven positive and eighteen
  negative boundary cases forbid legacy-parser use for valid and invalid Z inputs. The prior-head
  app, frozen Windows, reference and frontend receipt successes remain bounded to those sources;
  no failure is waived. The corrected combined head needs fresh full hosted gates before review.

## Windows framework setup failure and bounded case identities

Foundation `8fca0ddd` source/frontend run `38823760099`, attempt 1/job `116726629411`,
ends CANCELLED at 2026-10-16 01:34:27 UTC with the unchanged two-hour job-limit annotation.
Dependent `bf2f0af6` run `38824182870`, attempt 1/job `116727926794`, separately has that
timeout at 01:38:20 UTC. The initial archives omit those job logs, so they do not establish a last
test or rule out preceding failures. One independently reviewed selected-job debug observation per
head changes logging only; it does not change source, commands, tests, budgets or deadlines.

A's attempt 2/job `116769652905` reaches 100% at 02:57:38 UTC, then renders errors until the
03:57:34 UTC timeout. Its recovered raw job log is 2,356,969 bytes, SHA-256
`c2545b7229a10231fe8e36adbbc5230a8b51fe94c2a706004a84cbae14309ae8`.
Pytest's setup writes `PYTEST_CURRENT_TEST` and raises
`ValueError: the environment variable is longer than 32767 characters`. The automatic ID embeds
the 1 MiB plain-string parameter; the setup header alone is 1,048,708 characters. A later teardown
header is observed, but its complete traceback and the final suite aggregate are absent. Reaching
100% is not a pass. The separately downloaded attempt archive is an empty ZIP; the recovered raw
job log, not that archive, supplies this diagnosis.

The correction adds only `plain-1mib-repeated-1024` and `nul-4096-repeated-1024` as explicit IDs
for the two existing alias-overflow cases. Their exact payload expressions/counts, fixtures, function
body, forbidden-encoder guard, 4 MiB refusal and all 106 module assertions are preserved by static
AST comparison. There is no product, gate, timeout, budget, version, golden or sample change.
The shared correction must be integrated from #666, with fresh final-head Windows/default/source,
application, reference, frontend producer/receipt and frozen checks. Earlier positives and every
timeout/cancellation remain source-bound evidence; B's diagnostic and original Windows matrix
results are separate and cannot be inferred from A's trace. No repeated same-head diagnostic
attempt is authorized by this correction.

## Review and delivery boundary

Require all 15 live protected contexts on each final head, complete applicable application/visual/
reference/source checks, and fresh frozen Windows qualification after this import. Earlier-head passes,
partial receipts and cancelled runs do not transfer. #666 is reviewed first; after its owner merge,
#667 must be retargeted to main and revalidated before any merge. Neither PR is merged by this task.

All runtime tests, builds, engine runs, browsers and verification controllers remain GitHub-hosted.
Local work is Git/static reads, permitted privacy/marker checks and reviewed data-only transfers.
All 14 external gates remain pending. No version/release cut, signing, physical field qualification or
publication is performed; existing releases remain draft-only.

## Owner-main integration after complete B control (2026-10-16)

Main advances through owner-merged #665 to `9112a16e4e4d91674ba5cb2881f0d75071c7d78c`.
Foundation `c95c2b745a933510bba3faf6758d79680505797d` merges that source while retaining
all application logic and test/limit/version bytes. This dependent union preserves B's own
API/Snapshot/deliverables source pins, complete census rows and every parent handoff; incoming
knowledge-export writers and the closed manual Linux-job denominator are additive.
The controller remains deliberately bound to RC7 source340. Its actual manual export fails
`report_audit_refused`; it is separate evidence and does not establish a graph/vault refresh.

Immediately preceding B `6f33d57dc810d437555acfebf48ae13f17592b0d` passes all 15
main-protection context equivalents, app15368, and all six applicable whole workflows:
CI `38849752537`, portable `38849752606`, reference `38849752603`, original application
`38849752563`, edited application `38851384099`, and finite post-import `38852385681`.
Every required job's complete raw log is reviewed through EOF with retained byte counts/hashes.
The source job `116809433746` finishes at06:14:15 UTC, with full Python completion,
40 frontend files/623 passing tests, successful build and unchanged tracked distribution.
Its full 135,079-byte log has SHA-256
`54fb7a8e71613942b71670e4674a3c8de4fb4cac1a00bdd410ad4d0a36c5cc64`.
Double-quiet output does not provide a numeric Python aggregate; none is invented.
Coverage `116809461184` is87.44% against the unchanged85% threshold:19,474 passed,
167 skipped,3 expected failures,8 warnings and26 passing subtests. The Windows matrix
`116809461404` separately records19,583 passed,58 skipped,3 expected failures,8 warnings,
26 passing subtests and4,274.03 seconds. The Linux3.12 job also reproduces the committed
sample under UTC with the unchanged wall-clock exclusions.

Native browser documents, frontend producer/receipt and the frozen package have independent
data-only reviews. The package's13 automated checks pass;14 external gates remain pending,
with draft-only, unsigned, field=false and publication=false preserved. These controls belong
to B6f33's old main340/A4a base. The new union needs fresh full gates and source-bound receipt;
no current-source readiness or asset-import authority transfers from the old receipt.

A4a's source job `116806226399` times out at98% under the unchanged120-minute limit.
No preceding F/E progress marker, full aggregate or completed frontend result is present.
Its cancellation-frame Pydantic interrupt/tmp-path teardown error does not prove a cause.
All six A matrix jobs pass, including Windows19,581 passes in6,523.74 seconds. A Coverage
`116807637257` is superseded by the actual current-main integration push and endsCANCELLED
at06:31:06 UTC; it is not a pass. An independently proposed old-head one-job repeat never
runs: its exact-source guard detects main9112 before dispatch. No blind retry, performance
fix, budget/timeout change or local runtime is inferred by integrating owner changes.

The eight-module type gate passes. The broader explicitly report-only mypy2.4.0 result has
1,475 diagnostics/89 files/104 checked, identical by path/message to both main340 and Bbf2.
All60 diagnostics in edited backend files map to byte-identical prior source lines. This is
pre-existing advisory debt, not universal type cleanliness. The unchanged portable-lock audit
uses its registered PYSEC-2026-2858 suppression and emits `2 ignored` without naming those
records; no alias attribution or zero-vulnerability claim follows. Reference warns at85.55%
of its release census-byte ceiling and85.00% of its compiler JSON-string ceiling; neither
ceiling changes. Preserve every earlier failure, cancellation and external approval boundary.

## Supervisor SSOT refutation before review (2026-10-16)

Independent audit `wf_f0aab664-711` refutes #666 at `c95c2b74` and this dependent PR at
`46ffef86`. Their green jobs, actual downloads and frozen package controls do not prove that
recomputed observed companions retain the stored assessment basis. Stop old-source frontend
intake and review readiness; retain all previous results and failures as source-bound evidence.

The foundation correction overlays only requirements register, design blueprint and design NRFU.
Assessment architecture/coverage/unknown-evidence/census/lineage and executive brief stay on their
stored basis. One shared late-derivation owner preserves CLI phase order and failure callbacks;
Protocol Assurance membership has one artifact-registry owner. Original assessment failure details
and render-time SSOT integrity disclosure remain active. Two assessment SSOT rows explicitly link
the separate saved-plan basis.
An inherited Design blueprint/requirements failure can still withhold Design recommendations as
UNVERIFIED. A visible saved-plan stamp discloses that retained assessment limit; generating a draft
does not repair original failures or establish universal parity across withheld sections.

Frontend keys, list fields, tiers, fabric choices and VLAN limits consume the requirements contract
owned by `cisco_toolkit.design_advisor`. Actual OpenAPI exposes that contract, and the existing
generator emits its runtime constant and types into `openapi.ts`; required freshness checks compare
the complete output. Synthetic changed domains/ranges exercise the consumer. Legacy engine input
normalization is preserved. Generated exports are not hand-authored: a fresh hosted observation
must supply the canonical bytes before the new frontend can pass its required checks.

Applied static review, Rule7 and marker scans precede publication. Corrected foundation integration,
fresh hosted API observation, reviewed source-bound SPA import/receiver, all15 required-context
equivalents and all applicable whole workflows are still required on the revised source. Runtime
closure is not verified here. Stop for independent review; no merge, version/release cut, signing,
physical field qualification or publication is authorized. All14 external gates remain pending.

## Generated-contract bootstrap failures and architecture follow-through

On B2cde, tested merge c3cb790c has ordered parents fb6acc0e and2cde2417, treeb46db0b7.
Portable run38872276159/job116879139954 fails step7, pinned npm/frontend rebuild, at08:20:31Z:
api.ts cannot import generated designRequirementsContract/DesignRequirements. SavedPlan.tsx also
reports unknown-value and implicit-any tier/model diagnostics; those may cascade but remain
unclosed until a fresh post-import compiler succeeds. No frozen build or ZIP is produced. Its full
46,075-byte log has SHA-256 cc37836b8ca4bfb14820e96c0fd27140faefb5790f2cb6f3e84fb9449aa152c4.
Backend job116880486297 fails the Scope hub build at08:21:41Z on the same missing exports;
backend pytest is not reached. Its55,213-byte log has SHA-256
e474155ff22c5e0666193db26393e529ae260bb62a000da22e099c94430d248f.
Visual116880486340 fails its type check before comparisons (34,922 bytes, SHA-256
b1addcf46d76094a4074e2e7592cd50b8a11e73aaa8100629bb698c5de5602e7).
Real-browser116880486320 cannot start its server, so no specs/native journey run (82,159 bytes,
SHA-256 4fb3054f4f26c397350ec27bdf374e4dbfe203f8d00ccbc50f27eba258109746).
These are actual failed gates. They are not waived or labelled backend/browser passes.

Reference run38872276228/job116878929631 separately fails exact-tree compilation at08:34:10Z
on undeclared canonical_snapshot-to-design_intelligence/governance dependencies from the shared
helper in ssot.py. Its75,088-byte EOF log has SHA-256
0c6b72937d9eeacd8680ca83439f99bd4b5752db27c889a2546e00645f7ba62a.
Capacity then refuses21 unmeasured walls from absent downstream receipts, with zero measured
walls at95%: this is not a measured budget breach. Foundation0b48a64a corrects ownership by moving
the complete common requirements/blueprint/NRFU prefix to design_advisor.derive_plan_sections and
restoring assessment-only CLI blocks. ssot.py returns byte-exactc95; no dependency exception,
new module or ceiling change is introduced. All twelve failure/order cases are retained using
actual CLI blocks in hosted pytest, alongside full in-process wiring and original negative controls.

The old c95 source job116844806054 succeeds at07:49:56Z (132,819-byte raw log, SHA-256
cfb80699885b31e8c8e4f4064269da2ec265cf72565998eb69525d89f95f753b): Python reaches100%
without a printed aggregate, then frontend38files/537tests/build/dist equality pass. Its later
Coverage116845086939 and Linux3.12 job116845087164 are superseded by the genuine fb6 push and
cancel at08:07:37Z/08:07:26Z, last93%/99%. Their logs are100,022/163,322 bytes, SHA-256
41ddda0302d98ca70c1159a17e40bac4bec55f914a068b6fbd8478e0a4df2d2b and
7bfc1f0908cfe18640d6fe352f96b0f17d8b64837d5e597de90f4896c2cc8aa2. Linux's sample step
is skipped; neither has a final passing aggregate. Old B46 source116849155875 is superseded by
the2cde push and cancels at08:14:10Z, last81%, with no aggregate/frontend completion; full104,110-byte
log SHA-256 c0261af97e84f2ed70c79de5e14dbdaba85068b529ff42215e3af3c6a546c94e. These are
cancellations, not inferred timeouts or passes. All remain supervisor-refuted historical controls.

The ordinary B2cde schema observation is pinned to c3cb790c/basefb6 and its independently frozen
1,836-file Git ledger. Any eventual artifact remains old-base source-edit data. It must not be
relabelled as a new-source receipt after the foundation advances. Only an independently reviewed
canonical openapi.ts may be imported, followed by fresh exact-source generation/build, complete
165-file frontend inputs, SPA producer/receiver and all15/applicable whole/native/frozen gates.
Nothing in this record establishes current readiness, approval, qualification or release authority.

The genuine0b48 corrective push also supersedes fb6's incomplete source/matrix/Coverage work.
Five started-job EOF logs are retained; three cancelled matrix jobs have no steps/runner and their
one terminal log request returns404, so no runnable evidence is invented. Last source/Windows/
Linux3.12/Python3.13/Coverage progress is65%/18%/1%/32%/35%. Windows' partial3,640 passed/
4 skipped is followed by interruption, not a completed suite. Explicit higher-priority CI/portable
annotations support supersession, not timeout. The separate negative-closure record has SHA-256
19367b22972469ebcced9c98cd71552f9319ec7c005f2324d9e443d4fa7b0d1b; the earlier Reference
architecture failure remains an independent failed gate. None transfers to0b48 readiness.
