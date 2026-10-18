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

## Canonical generated requirements contract: bounded source-edit import

Run38872276264/attempt1/frontend116880486439 checks out the frozen old mergec3cb790c,
ordered parentsfb6+2cde, and finishes FAILURE at08:55:02Z on generated-API drift. Its observer
and upload steps succeed, with OBSERVED_REVIEW_REQUIRED/errors[]; all20 generation-policy
tests pass before the required byte comparison refuses. The complete114,385-byte EOF log has
SHA-256 2402f84273058d35498b7549c91f98824b02dbc23db02d25f9e45e26f58fe029. No frontend or
whole-workflow pass is inferred.

Artifact12036006113 is selected before its single download:456,852 bytes, SHA-256
b12e3e7a8aac20cd5e839d175405b15ab68a2536e3d8b0ee91a63009d0ffe8da, matching the API and
terminal upload log. Its exact nine regular members pass complete raw local/central/descriptor/
deflate/CRC closure, source-before/source-after byte identity to the independently frozen1,836-file
Git ledger (82,258,309 bytes), the full eight-member observation hash ledger, four unchanged native
literal pins, actual requirements-owner metadata and all12 current marker rules. GitHub's untruncated
tree separately agrees with every path/mode/blob. No archive code or project generator executes.

The first scratch suffix expectation incorrectly followed alphabetical schema JSON order. The
reviewer's correction follows the already-reviewed generator's explicit seven-field order and
retains exact byte comparison; it changes no artifact, source, policy or gate. The initial refusal
and its diagnosis are preserved. Independent review confirms current local integrationa69724fe
has the same generation-owner whole-file/AST closure after the helper relocation. This does not
relabel the old-base observation as current-source validation.

ONLY openapi.ts is imported:542,034 bytes, SHA-256
1828bcc99911d4a5756d376ab1d4aa9f19e079cdcf0727139970c580db9f3981. Its original540,981-byte
generated prefix is unchanged; the1053-byte suffix contains exactly the generator-owned requirements
constant and mapped type. No schema JSON, native pin or other artifact member is imported.
The first DATA proof has SHA-256 db6c013fc1c450eb45f99b6f61856c3c2b2bf387f671dd936a70b3a57a14c033;
the independent6,619-byte proof has SHA-256
64ac614145b14c4f962033321913e8104db1337a0a3fd03c6697164d47bbf528.

Fresh current-source api:check and all Scope/backend/visual/browser/portable checks must close the
actual missing-export and additional type diagnostics. New SPA producer/receiver/import and all15
required-context equivalents/applicable whole workflows remain mandatory. The import is reviewable
source-edit data, not runtime success, approval, signing, field qualification or release authority.

## B738 cold-path successes, warm-cache failure and corrected owner

On source9bc8a1be (head73841b7d/base0b48), frontend116905035462 succeeds at09:42:28Z:
fresh api:check,41files/627tests,TypeScript/Vite, index/tree privacy and the immutable SPA
handoff all pass. Its full143,135-byte log has SHA-256
e3f58db69a6b6b15a28df5275800c377c6d4b34e325ed8b34d4f10fdf7a77fdc. Visual116905035739
passes22 cases (36,684 bytes, SHA-2569e7e2fce9506861c735ba6de239c0830fab61028f97ca43465ecf59a34856777).
Real-browser116905035465 passes all3 specs at09:42:50Z, including saved plans and MOP/NRFU
downloads (102,273 bytes, SHA-256dab8b420eb7fa85e53fb818bb481c1d78efc0daaf03fa2a9734410cdfb518e7d).
Their actual document/archive contents are not independently intaken or qualified here.
Scope38880134949/job116904601039 is wholeSUCCESS:256files/7,633passes/27existing skips,
followed by its mutation/browser/focus/build checks;518,658-byte EOF log SHA-256
af9636b74713f4bbd38b5430eedc300a85b2b51822f22c05925cdcc708a1741a. These are source-bound
positives, not a complete producer or current-source readiness claim.

Portable38880135046/job116904710445 fails step7 after successful TypeScript/Vite compilation:
git diff --exit-code refuses the rebuilt output against stale tracked dist. Its2,258,848-byte log
has SHA-2561c28da627ad040ea839c54a202bbdf41109eac5e10bd0ed05430cf296c8c81f0; no frozen
package is produced. Distribution116905069122 similarly passes41files/627tests and compilation,
then fails its immutable-checkout step8 on actual dist drift (46,123-byte EOF, SHA-256
50caa56e41dc20147fd49c8032537a34fa5ea987d0605fc3280748926bc5ef63). Installed-transition
116911207845 isSKIPPED because Distribution fails; it does not satisfy its required context.
No reproducibility gate is waived.

Backend116905035547 independently fails step11 at10:01:46Z on test_saved_plan_api.py302:
consumer_only survives a second app.openapi() call. The complete94,536-byte log has SHA-256
e61fb13bf1ee9e50328e21d4ad79729aea4e98c973d5a652039d01889c6c4f37. No numeric aggregate is
printed. Gate116918755633 fails at10:01:51Z (3,642 bytes, SHA-256
92ac55f29f8539870401fa2ba267968a33a5ca34d117393c10e316705baf9f19), making whole producer
38880135003FAILURE. Consequently no SPA artifact is selected/downloaded and no receiver is
dispatched from this producer, despite the frontend job's success. Its165/7/5 pre-intake ledger
remains historical. The old2cde supersession record also retains20negative jobs/17EOF logs plus
3no-step/runner404 cases, SHA-256a8afad0be104bd70d0a9c8938b429b970d3cde73f6299e200006279dd7c0cbcd;
none is a full-suite pass or inferred timeout.

Foundatione695f445 fixes the final OpenAPI wrapper that bypassed the constructor refresh on
warm reads. It removes the redundant subclass and replaces only engine metadata after the
unchanged native-cache boundary. Original assertions remain, with nested mutation, native identity/
content and per-app construction-count controls. Native pins, canonical cold schema/generated
TypeScript bytes and all limits remain unchanged. Independent static review and fresh Rule7 precede
publication; new-source warm/cold schema/backend, complete successful SPA producer/receipt,
all15/applicable whole workflows and native/frozen checks remain required. No local test/build/
engine run, PR merge, version/golden/sample change, signing or release is performed.

## Current-main union, actual documents and bounded SPA admission

Main d73d33e28bafe91f750e25f20dee559d412ac485 (#671 knowledge diagnostics) is integrated
through foundation4d140ea9 and local B856b3f6a, retaining normal merge parents and both full
handoff histories. The seven incoming paths retain exact owner code and the joined census pins.
Independent review proves all165 frontend source inputs/seven receiver policies/five old outputs
byte-, mode-, blob- and SHA-identical before the bounded SPA import. This is input continuity,
not a transfer of earlier-source runtime readiness. No knowledge generation or vault refresh runs.

Old B4f0bdbc6 ordinary application workflow38885889939/attempt1 completes SUCCESS with all
seven jobs on tested mergecb7cbac62d126bd965695658f5980b58feb9097c, ordered parents e695+4f
and tree8042eb46. Full backend116923677109 succeeds at10:47:19Z and reaches100% without a
printed numeric aggregate; its87,713-byte EOF log has SHA-256
25c4b63bcdb2cd83e6dc5d45ac851c964cd765c1cb32693c7215a12bea810602. It includes the retained
warm-cache/native-construction control. Frontend116923676933 passes actual api:check,41files/
627tests,TypeScript/Vite, privacy and handoff;144,118-byte EOF SHA-256
3f05ce1e51d1f51584b635afe31e153348245de61f13f8c0a4fda7fbf1e57fb4. Gate116935349971 succeeds
(3,486 bytes, SHA-25610f6b9aac161797679d04828ad6d3642c13a65dad31fef45213dd4f31d34b79a).
Scope38885889943/job116923404811 succeeds with256files/7,633passed/27existing skips and
all downstream mutation/browser/focus/build checks;499,677-byte EOF SHA-256
e029f3c9791aced5d5407b1e62af7a0e6b977f997a46c3f3a2e816ef0e2e3c7b. Full Python3.14
116923769756 separately passes19,562/165skipped/3xfailed/26subtests (137,732-byte EOF, SHA-256
4a0bc6955dede83b2b0d869a43c823439c144095283d8df4b4e332da4f8c8efd). These are old-source
controls; all final-head matrix and whole workflows remain required.

Actual real-browser artifact12039900506 (247,500 bytes, SHA-256
848b5aadee6ff49351187d48f1eded049e6bb5a32ef580ebbfebe1e5dcbadeea) is selected before one
inert download. Its exact six regular outer members and three actual DOCX files pass raw ZIP/CRC/
span closure; each document has18 closed OOXML members. The native files independently match
the source-bound hosted receipt: MOP revision1/selection1,60,454 bytes/SHA-256
817d451a04f2ab02e460ada673be77d886fdc7287ba72fdf2ead11c008699228; NRFU revision1/selection1,
54,040 bytes/d6413003753fb6defc4bee19fd8789e7f2cdab657a997698fc2e4b9396db5ac4; MOP
revision1/selection3,60,459 bytes/f684810149b56ea855da0963fc1f92432b829c1faf1278fd3bf87fdd35f0fe1f.
Visible text, headers and machine IDs match the assessment/plan/revision/selection hashes and
UNAPPROVED DRAFT. MOP ownership_unbound remains disclosed. Original persisted-assessment
before/after equality and HTTP/native equality are hosted assertions; the distinct uploaded Git
fixture is not relabelled as the persisted raw bytes. No screenshot, physical-host or approval
claim is added. Independent actual-DOCX DATA proof SHA-256
2e32b84afb78ad16d95f58c36deeae22c782bd19b56378a09bbb43c8f1a0fe97.

Three B4f gates fail on actual stale tracked dist, without a gate waiver. Distribution116923769494
passes627tests/compilation then refuses immutable output bytes (48,384-byte EOF SHA-256
152de0c8c32c71bb39e837d9c5234a45f7f13cf011419afe792d37e26f4afe65). Portable build116923604587
fails step7 after successful TypeScript/Vite (2,259,054 bytes, SHA-256
931a63e5e40e792bd7422ca407678983019ea3563717b72fd1f9e13dbcf6dc00). Full source116923605004
reaches100%/exit0 in quiet default Python with no numeric aggregate, then627frontend tests and
compilation pass before its dist comparison fails at11:23:56Z (2,344,866-byte EOF SHA-256
7c10bdcf1038589a0cf13c7ed5c71e56f7c0b10f8d183161aa53fe934ccc0bfc). No frozen package,
reverify/attach or installed-runtime pass is inferred from these failures or dependency skips.

The successful ordinary producer's seven-member SPA artifact12040060149 is frozen before one
download:583,291 bytes/SHA-256d595f23b59ee34dbeabd84a3c13478e846a86bea5e45e92ddb3a2f2d8482d4d3,
Node24.19.0/npm11.17.0. Independent raw ZIP/CRC/deflate/closed-path admission binds all165
source inputs, seven policies and five current outputs, actual metadata and asset links. Source-edit
DATA proof SHA-2561a5b1963b3060d34b4b11aa53775f69e14e91b27a49ffcbf1b33568de2851b5f.

One finite hosted receipt dispatch38891078410 remains bound to controller4f and subjectcb7/e695.
Its frontend116945249991 is SUCCESS11:35:41Z;145,169-byte EOF SHA-256
e337c36bdb14a72b2b7b3359c75df7daf347e54fe8b563725e7603ef298bc917. Artifact12043476217 is
selected before one inert download:1,108,245 bytes/SHA-256
5d769213d75052bb7decce665e29aa230ef68eb4eec890f031267cc3333513b2. Its nine regular members
close raw ZIP/CRC/spans/deflate, contain the exact original subject.zip, and bind selector, all165
Git inputs/seven policies, member observations, five admitted files, complete patch and stable
opening/closing API identities for the successful ordinary producer. Result is
ADMITTED_EDIT_DATA_REVIEW_REQUIRED, errors[], compatibility/dependency_validation/acceptance/
release_authority/current_source_ready=false and final_source_rebuild_required=true. Receipt DATA
proof SHA-256b3e7f16e83e8a43df6e0ea5ccc2591e4ca4dbdf150555e5b0d9bb895d39a8347; independent
root proof9c0d524bdb14211812caf30c874cd7255990c183fabd6849465528716b2c9ba0.

Only the five admitted compiled outputs (2,086,461 bytes) are imported by checked Git patch: CSS
is byte-identical, index changes, and three JS outputs replace three old hashed chunks. The patch
has five blocks, including two near-identical renames. Index and physical output bytes/hash/census
match the receipt; applied proof SHA-256
81b5624070e97b12c53b30d2307be278aa5c42f3a4dacdd54a5f6f15585084db. No archive code, local
controller, Node build, engine or test executes. The unchanged raw12 publication helper passes
the staged import/history:32commits/45parent patches/58subjects, zero violations. The separate
raw full-asset scan's four minifier-initials tokens are governed by the already-existing exact JS
path exception; no raw-history match, new exception, helper exit change or scanner waiver is
inferred. Final actual post-commit scans and repository privacy remain required.

## Manual real-browser negative and passive original-response observation

The same manual run's real-browser116945249940 fails at11:29:12Z:1failed/2passed in48.6s.
Original saved-plan.real.spec.ts120:29 rejects Response.body() with Network.getResponseBody:
No data found for resource with given identifier. Complete101,598-byte EOF SHA-256
a0768f86327640cdd62d0248b1262640e4456aeadf502f5f4303893fee2e071e. Diagnostic artifact
12043266474 is independently selected as6,663,415 bytes/SHA-256
b0338ff3f4b9185ea9642fdaf08331b8d3b5e553f791c17dffa106532d23d3cb. The earlier immediate
CDP-capture correction did not close the observation failure. The precise Chromium unavailability
cause is unconfirmed; no application root cause is invented. This failed job prevents whole-manual
SUCCESS even though finite receipt admission and its frontend succeed. No pass or runtime
readiness transfers from the earlier ordinary run or admitted edit data.

A source-only correction observes the same original browser fetch response by a bounded native
Response.clone before the UI consumer, rather than depending on CDP's retained-body retrieval.
The passive Proxy forwards this/arguments once and returns the identical native promise/Response;
no extra export request, mocked response, network-route interception, synthetic body, delay or retry is added.
The existing32MiB limit remains. Original status/media/five identity headers/query assertions and
native DOCX hash/OOXML-visible identity checks remain, with added original-response header/URL/
single-request/restoration checks. The complete original operator-walk body and earlier DOCX/
saved-view helpers remain byte-identical. An additional real /api/meta control checks original
promise and response identity, one actual request, restoration and independently consumed body
equality. This correction is authored/static-only here; hosted runtime closure is not verified.

The observer change intentionally changes one of the165 frontend source inputs. Final receipt
must therefore select a NEW exact-source ordinary producer whose complete workflow succeeds,
then use its artifact/source/run/job/digest and current import_commit for the post-import profile.
The oldcb7 receipt is bounded compiled edit DATA only. Fresh required15/15, every applicable whole
workflow (including all original real specs and the new identity control), exact tracked-dist rebuild,
post-import receiver and native/frozen evidence are mandatory before independent review. No
product/schema version, golden/sample byte, existing test, gate, budget or timeout is weakened.
Plans remain UNAPPROVED DRAFT; all14 external gates, unsigned and draft-only status remain.

Old e695 required closure retains11SUCCESS/4CANCELLED with all15 EOF logs reviewed. CI and
portable whole workflows are CANCELLED; Python3.10 reaches99%, Windows/source80%, Coverage99%
before genuine4d-push supersession, with no final aggregate/coverage or timeout inference. The
30-job extra appendix has26 reviewed EOF logs, two explicit skips and two unstarted cancelled
portable downstream jobs with no runner/steps and terminal log HTTP404. Primary manifest SHA-256
dce9125334a16c3a5dadc6fbdb28a8858e7b31616c934b3ab1d7d7f187d4c8e4; extra manifest
dc8ed8d8c3e4fcb8437db2458bd34077212033722f70760def3cd02866e08162. The earlier0b48 unnamed
Python3.10 F93% before97% cancellation remains unassigned and preserved in the foundation guide.
Neither cancellation nor a later pass retrospectively identifies that old failure.


## Supervisor-scheduled local preparation — 2026-10-17

The supervisor authorizes LOCAL preparation only. Main
`d3c79ae0973cfc59b8c6ff9c821d32b609fade51`, including saved-plan PR #666 merge
`fdd6a7de9b9b2e51fccc54ece5a7b77f6c6a44b1`, is integrated with the existing local
field-workflow parent `856b3f6a6d7d047552e1f6c65963e386109d4d89`. Normal merge ancestry is
retained. The parked index, working patches and affected files were preserved outside the
repository before integration and matched the earlier parked backup byte for byte.

Only `docs/NOW.md` conflicted. It is restored exactly from the pinned main under the
supervisor-only board rule; the older board draft remains in the external preservation copy.
The shared saved-plan export tests merge without a conflict: main's persisted NRFU content
assertions and both field-workflow catalogue/refusal tests remain exact at function-AST level.
The incoming NRFU owner, renderer and other test files retain main's bytes. Both SSOT bases and
both sides' saved-plan documentation remain present.

The previously authored passive original-response browser observer and the previously admitted
compiled assets are carried forward from the preserved work, without rebuilding or executing
anything locally. The historical receipt remains bounded edit data, not current-tree runtime
acceptance. The observer's hosted failure and all earlier cancelled/failed gates remain recorded.
The combined tree still requires its own hosted real-browser, frontend reproduction, source,
portable and complete required checks. No current-tree runtime or debt-register PASS is claimed.

**Hold: no push or CI before P1-H PR-0 (#673) merges and the supervisor confirms it.** Then merge
that newer main, restore its board again, check compliance with its now-enforced shrink-only
interface-computation debt register, and rerun Rule-7 scans before the ONE authorized push.
No new interface-side computation or register growth is permitted. Reach exact-head 15/15 and
all applicable gates, post the completion summary identifying what #667 adds to #666, then stop
for independent review. No PR merge, release, signing or publication is authorized. Every existing
test, gate, budget and timeout remains unchanged; golden/sample and product/schema versions
remain outside this preparation.


Independent local static review identified an observation-window gap in the parked browser test:
the fetch wrapper restores after its first response clone, before native save/hash/XML completion,
so its counter alone cannot exclude a later matching request. A passive Playwright request listener
now spans that full helper, asserts the single exact export URL after the unchanged byte and
visible-document checks, supplies the published request count, and is removed in `finally`.
The original native promise/Response capture, every prior identity/hash/XML assertion, and the
32 MiB limit remain. This strengthens test observation only; no application computation, request,
retry, wait or timeout is added. Hosted execution of the correction is still pending.


## Enforced-main integration preflight — 2026-10-18

The supervisor reports #673 merged as main
`92490340e3c55c34c7a8d26e878ee5de7c729601`; the live PR and main ref confirm it. This
main is integrated locally with parent `0ec0c11f51a0a658a965e0a65442b7944d3fcf10`.
The only source-control conflict is the SSOT index: preserve main's enforcement/shard rows and
this feature's saved-plan workflow ownership pointers. `docs/NOW.md` remains exactly main's copy.
Incoming guards, role declarations, tests, shard workflow and debt register are not changed.

**Pre-push compliance is BLOCKED.** The merged v3 register contains no sites for
`webapp/frontend/src/pages/SavedPlan.tsx`. Its `samePin` return compares the revision, digest and
selection; the unchanged TypeScript detector explicitly emits `returned-comparison` for it.
The same new page's `planDraft` uses `zoneLines.push`, an explicitly detected `collection-update`.
The new `src/api.ts :: planKeys` key counts and `planResponseChunks` byte-counter updates also
have no permitted path/symbol/rule entries. These are direct source/rule/closed-register
counterexamples, not an executed local census or a claimed hosted result.

The registered footprint conservatively includes presentation, client input admission and
transport safety operations as well as analysis. In particular, the new bounded stream reader
and requested-selection validation protect an untrusted HTTP response; moving those checks to
the response-producing server is not equivalent client-side protection. Main has no existing
bounded browser stream reader to reuse in the app or Scope source. Removing checks would weaken
the retained hostile-response and identity tests. Re-expressing operations to evade detection,
misdeclaring browser code as engine code, growing the register or changing the guard is not an
authorized closure.

The ONE authorized push has not been used, and no new CI was started. Main's register remains
byte-identical while the feature's tests and response limits are preserved. A supervisor decision
on a compliant protocol/UI-state boundary is needed before publication; a conservative legacy
footprint is not a semantic admission for this new feature. The exact-source hosted guard,
complete current-tree runtime validation and 15/15 remain unverified. No completion or
independent-review readiness is claimed. The earlier draft-only/unsigned/external-pending and
historical failure records remain unchanged.


## PR-0b advance owner-reuse preparation — 2026-10-18

The supervisor's #682 decision, comment `6247503468`, supersedes the earlier three-candidate
admission intent. PR #667 is retargeted to `main`; the published source head remains
`4f0bdbc66a7cb877751a6d3e8284fabbe5331651`. No local source commit is pushed. #682 is still
open, so boundary admissions and the ONE source push remain held.

The duplicate `api.ts :: planKeys` is removed. All seven callers now call the existing owner
`projectionEmbed.ts :: closed` directly. Its declaration is exported without changing its body.
Besides exact keys, that owner requires a plain/null-prototype object with enumerable own string
data properties. Ordinary JSON and the current literal request bodies fit that contract; this is
not a compatibility claim for arbitrary class, accessor or cross-realm objects. Some callers read
metadata before this check, so reuse is not a blanket no-accessor-evaluation guarantee. No boundary
record is needed for copied key-validation code because that copy no longer exists.

The named snapshot identity helpers are not equivalent to a saved-plan pin: they compare
`snapshot_id`, assessment `sha256`, `bytes` and `digest_form`, whereas a plan pin compares
`revision`, plan `sha256` and `selection_id`. A reselection can change the latter while assessment
identity stays fixed. No field is remapped to a fictitious snapshot field and no cast is added.
Instead, the existing registered generic equality owner `projection.ts :: equalJson` compares
both real, freshly constructed three-field pin objects at the existing download callback.
The duplicate `samePin` predicate is removed. `pin()` keeps exactly the same runtime fields;
its literal shape is inferred and checked with `satisfies SavedPlanPin` for the owner's JSON-data
contract. The generic owner body is unchanged. This checks the true revision/digest/selection
keys, including a new selection event for the same revision; it is owner reuse, not a renamed or
re-expressed comparison to evade discovery. No new comparison boundary record is proposed.

`api.ts :: planResponseChunks` remains the transport-bound candidate for per-site admission
under the MERGED PR-0b mechanism. There is no debt growth, detector/role change, test weakening,
local inspector, test, build or engine execution. Helper reuse is not an admission or runtime PASS.
The production frontend inputs changed, so the older compiled edit receipt cannot establish
reproduction of this source. Tracked compiled assets are preserved without local regeneration;
fresh source-bound GitHub-hosted rebuild/import evidence remains required. Current-tree hosted
type checking and every existing safety assertion must still pass. After #682's reviewed merge,
integrate that main and its exact board, follow its actual site schema/review rules, run Rule-7,
and use the ONE authorized source push only when the prepared source meets those requirements.
No PR merge or release publishing is authorized.


## Merged PR-0b integration and remaining exact-site scope — 2026-10-18

PR #682 is verified MERGED as main `0491291c38f0d50f6d86ee7950666767e1edb6f7`.
That main is integrated locally with prepared owner-reuse parent
`6bab7d891b97825f28b7bc2206240a80b72d493b`. Main's board remains byte-identical.
The SSOT conflict preserves the new installation and schema-/4 admission owner rows together
with this feature's saved-plan workflow owner pointers. The field guide and artifact census
merge both sides; the census functions retain both parents' ASTs. Incoming detector, guard,
workflow, role and test changes remain main-owned, without weakening. Live strict branch
protection now requires 14 named contexts; Master Reference is not one of them.

The prepared comparison is registered `projection.ts :: equalJson` over the genuine fresh
revision/digest/selection pin objects. Snapshot `sameIdentity` remains a different four-field
assessment predicate. The latest naming instruction has been raised for clarification rather
than forcing plan fields into a fabricated snapshot identity.

**The single source push remains unused pending exact-site scope clarification.** V4 requires
all detections to equal debt union exact boundary records (`validate`, lines 696–698); the merged
boundary class starts empty. Admitting the authorized `planResponseChunks` sites cannot cover
other independently identified sites: `SavedPlan.tsx :: planDraft` appends zone lines, and
`api.ts :: ownedPlanChunk` writes the bounded byte copy. Neither has a registered matching
path/symbol/rule. Independent review also identifies the safe-integer and nonempty-string
predicates as additional examples. These are source-based counterexamples, not a full executed
census. Under a literal zero-other-additions instruction, no bounded closure preserving all
current safeguards has been established. No new boundary or debt rows are guessed or added.

Canonical normalized fingerprints and occurrence numbers still require an approved source
observation. The stream function's source is unchanged from the earlier public head, but text
equality alone is not a detector identity or a complete capture for the current tree. No local
inspector, test, build, engine or controller is executed, and no new CI is started. A hosted
observation/acquisition sequence or explicit static-observer direction is still outstanding.
The existing frontend-input/reproduction and independent per-record review requirements remain.
There is no 14/14, runtime, admission or completion claim for this local integration. No PR
merge or release publishing is authorized.

## Owner clarification, main #690 and isolated parser preflight — 2026-10-18

The owner resolves the preceding scope and identity questions: keep the registered `equalJson`
reuse; the earlier `sameIdentity` wording is superseded. Independent static review at local
`268c189e52d75c8d36ad9570387925d85e5ebe9a` confirms that the actual fresh three-field pin
comparison retains revision, digest and selection-event equality. It finds no new engine-owned
network fact in the reviewed page/API additions. Structure, request identity, cancellation,
bounded byte handling and form serialization remain candidates for individual exact-site
review, not a blanket admission or runtime PASS. The independent final reviewer must confirm
equivalence and approve or reject every proposed record by its exact identity.

Zero additions applies to the debt list. The owner permits separately justified boundary
proposals beyond `planResponseChunks`, including pure serialization and transport mechanics.
A user-facing engine-owned fact cannot be admitted. The exact detector result is still needed;
no fingerprint, occurrence or additional allowance is inferred from this semantic review.

Normal merge `268c189e52d75c8d36ad9570387925d85e5ebe9a` integrates specified main
`ee5ee274210d84083b99ae1c407b2c1ca9182e86` (#690) onto local `3de6f5f9`. All seven incoming
non-SSOT files exactly retain main's bytes, including faster parallel CI, the `unshared`
pytest marker and its tests. The merged SSOT retains both main's partition contract and this
feature's saved-plan owner row. `docs/NOW.md` is byte-identical to main. No authored detector,
test, budget, timeout, sample, golden, package manifest, lockfile or compiled asset is changed.

The owner explicitly permits the canonical source-only observer locally: deterministic,
sub-minute source parsing, no tests or application imports, with hosted observation binding on
the pushed head. Exactly `typescript@5.9.3` and `parse5@8.0.1` may be installed outside the
repository with `--ignore-scripts`, after comparing integrity with the repository lockfile;
the scratch installation must be deleted afterward. Both package versions and SHA-512 entries
exist in both repository lockfiles. Static dependency preflight, before any installation,
finds that parse5 also requires `entities` (`^8.0.0`); `atlas-scope/package-lock.json` locks it
to `8.1.0`. That third package is outside the explicit two-package authorization. A required
scope question is pending before any installation; no packages, repository `node_modules` or
lockfiles have been installed or modified. No observer or test function has executed, and no
observer output digest exists. This is a dependency-authorization blocker, not an integrity
mismatch or an executed detector failure.

The one source push remains unused. Exact records, fresh final-tree Rule-7 scans, source-bound
frontend reproduction, the binding hosted observation and all 14 exact-head required contexts
remain pending. Earlier Rule-7 and hosted receipts keep their original source scope. No PR merge,
signing, qualification or release publication is authorized.


## Canonical static observation and remaining form-collision blocker — 2026-10-18

The owner extends the external parser allowance to exactly the locked closure: TypeScript
`5.9.3`, parse5 `8.0.1` and entities `8.1.0`, from `atlas-scope/package-lock.json`.
A fresh external scratch install used `npm ci --ignore-scripts --no-audit --no-fund
--bin-links=false --include=dev` with a three-package lock copied from that owner. Installed
membership was exactly those three; each installed lock integrity and actual downloaded
SHA-512 content matched the owner. Repository node_modules, manifests and lockfiles stayed
unchanged. Both temporary installations and their caches were deleted afterward.

| Package | Actual downloaded integrity, equal to the owner lock |
|---|---|
| `typescript@5.9.3` | `sha512-jl1vZzPDinLr9eUt3J/t7V6FgNEw9QjvBPdysz9KfQDD41fQrC2Y4vKQdiaUpFT4bXlb1RHhLpp8wtm6M5TgSw==` |
| `parse5@8.0.1` | `sha512-z1e/HMG90obSGeidlli3hj7cbocou0/wa5HacvI3ASx34PecNjNQeaHNo5WIZpWofN9kgkqV1q5YvXe3F0FoPw==` |
| `entities@8.1.0` | `sha512-kxL7msIffSuh9aaFAMD7rxAIuTRMAHMeBtgHW2yUdWw732ZNh4MehkF2gdjvtdmikkaIP9bFDDJOPlsvm7avrA==` |

The full `py -3.12 -B tests/interface_computation_guard.py --observe OUTPUT` attempt was
stopped at its explicit 59-second local authorization bound, with no valid output. The cause
is unconfirmed. That remains negative evidence; no timeout was enlarged or passing full
census claimed.

The separately scoped, permitted AST-only discovery then completed in **2.015 seconds**.
Command: `py -3.12 -B scoped-observer.py`, from an external evidence directory, with
`ATLAS_SOURCE_ROOT` naming this checkout and `NODE_PATH` naming only the temporary parser
installation. The helper loads the canonical static observer module and calls its unchanged
`scan(SourceMap(...))` on the whole eight changed interface files and their pinned main
counterparts. It imports no application module and executes no test function, build, engine
or validation/controller. Local Node was `v24.18.0`; the hosted toolchain and full observation
remain binding. This is not full class/import discovery or a required-gate execution.

| Source or output | SHA-256 |
|---|---|
| `tests/interface_computation_guard.py` | `0f80a96dd9b014d3ba0c0bffd19f709675b3c3d0acee19e4017bcd2dd9274b51` |
| `tests/interface_computation_lex.py` | `9bb4ac362db65f5da10f37a3c9c26766afe3f9956e4e46104fae2feaa6f4658c` |
| `tests/interface_computation_sources.py` | `6b29467c0b11ea6e64282e3701031b250f3b332c130fe28aac0e646b28992741` |
| `.github/scripts/interface_computation_ast.mjs` | `f230971bba5c3d6802760164e642d345adbb1c2d57dc8422b40cb0290a2fb6a3` |
| External `scoped-observer.py` | `302b73099ccea3789d652bf7d7747ac4a567e270759bbfbfb13d629877cda63b` |
| Scoped output JSON | `556b4d3e2d010d04592267fa38b63eb12596d204ce6dfd79c67d1e470be4b81c` |
| Scoped proposal normalization | `eb9355bd6324e773231985b7cfe375d99129ba205bd078712098ec4599b38fbc` |

The capture is bound to `7591c533325a571e161085f92f4b5f1a27ebca0a` and its eight
source-byte hashes. It observes 670 current sites and 454 base sites in that scope, initially
217 new exact identities and one stale debt record. These are scoped counts only.

Independent review confirms the added Tools-page navigation changes an entire registered
JSX `fact-decision` return. That whole expression cannot truthfully be admitted as navigation.
Narrow correction `6827440a3d05efe19e117280dee14f2bcbc9fd37` restores `Snapshot.tsx`
byte-identically to main, retaining the primary `CoreSnapshot` saved-plan link covered by
`CoreSnapshot.test.tsx` and the real saved-plan operator journey. No test is removed or
changed. The captured base rows therefore rejoin this byte-identical restored file; all
other captured source hashes are unchanged. This data-only rejoin is not another observer
run. It leaves 216 new scoped identities and no stale scoped debt record.

**BLOCKED before the source push:** 23 new AST instances match current debt forms.
Seven are bare literal returns covered by the existing literal rule; the remaining **16**
instances below are substantive under the executing rule. `validate` lines 709–720 rejects
a `(rule, fingerprint)` match against current or historic debt regardless of path, purpose
or proposed category. Source-only independent review finds no complete semantically
equivalent owner-reuse path for these instances. The result is an inferred refusal from
observed canonical identities and the unchanged guard, not an executed validator result.

| New exact site (path / symbol / rule / occurrence) | Fingerprint | Expression |
|---|---|---|
| `webapp/frontend/src/api.ts / planInteger / returned-comparison / 1` | `769874aa5db9480902186ad363ac8debe4e8131f7f4967c8079ed52519b601e2` | `typeof value === "number"` |
| `webapp/frontend/src/api.ts / planNonempty / count / 1` | `d59d95b6279ab3f715f413e213fd1d50fdefc3905cd0954a0c3a424f30b4a0ac` | `value.trim().length` |
| `webapp/frontend/src/api.ts / planObject / returned-comparison / 1` | `0c826da5d39395e0f298503c4c39c85fa0d1a367359de453fd0c12bbeffac601` | `value !== null` |
| `webapp/frontend/src/api.ts / planObject / returned-comparison / 1` | `6a92bed2ade8168bed69bf6645dbb1685ee7dd7fd87ab06d4d7f90740f61b4fc` | `typeof value === "object"` |
| `webapp/frontend/src/api.ts / planString / returned-comparison / 1` | `5ff5d5487ac5420a2bcd54b5b02ec773d16f8a3aa44664fd8b897b53434e2047` | `typeof value === "string"` |
| `webapp/frontend/src/api.ts / savedPlanDocument / count / 1` | `f0816c33175ecae63d9febc05e784e458bd9f33e6d871f470c851e66ebee9193` | `prefix.length` |
| `webapp/frontend/src/api.ts / savedPlanDocument / count / 2` | `f0816c33175ecae63d9febc05e784e458bd9f33e6d871f470c851e66ebee9193` | `prefix.length` |
| `webapp/frontend/src/api.ts / savedPlanDocument / count / 3` | `f0816c33175ecae63d9febc05e784e458bd9f33e6d871f470c851e66ebee9193` | `prefix.length` |
| `webapp/frontend/src/api.ts / validPlanConvergence / count / 1` | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | `digits.length` |
| `webapp/frontend/src/api.ts / validPlanConvergence / count / 2` | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | `digits.length` |
| `webapp/frontend/src/pages/SavedPlan.tsx / SavedPlanWorkspace / count / 1` | `33dcbe05f48c894f1d9c5f2d7c3a53e276dfddaba60167945f370b0ad55d27c4` | `items.length` |
| `webapp/frontend/src/pages/SavedPlan.tsx / SavedPlanWorkspace / returned-comparison / 1` | `0cc66f17a5cd1f086984db045486e6f76bd644be6c88935cd9fdaa1436719639` | `items.length === 0` |
| `webapp/frontend/src/pages/SavedPlan.tsx / formRequirements / collection-update / 1` | `90b33a0c54e9726ededfcffd48426b4773abaabaae29804fd9b995705d2fc8d3` | `seen.add(vid)` |
| `webapp/frontend/src/pages/SavedPlan.tsx / formRequirements / count / 1` | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | `digits.length` |
| `webapp/frontend/src/pages/SavedPlan.tsx / formRequirements / count / 2` | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | `digits.length` |
| `webapp/frontend/src/pages/SavedPlan.tsx / listText / returned-comparison / 1` | `5ff5d5487ac5420a2bcd54b5b02ec773d16f8a3aa44664fd8b897b53434e2047` | `typeof value === "string"` |

For example, the download ZIP-prefix length matches keyboard-chord and route-prefix
length expressions; convergence-input digit length matches the Master Reference floating
serializer; duplicate input `seen.add(vid)` matches the legacy STP election implementation.
Calling those unrelated algorithms would not be equivalent reuse. Renaming operands or
reshaping expressions solely to change fingerprints is forbidden and was not attempted.

A policy-owner resolution is required for the unresolved form collisions before exact
boundary admission can finish. No boundary record or debt addition is made; register,
detector, roles and tests remain unchanged. The single source push is unused. Fresh final-tree
Rule-7 scans precede any eventual push; all 14 exact-head hosted required contexts, full
binding observation and source-bound frontend reproduction remain pending. No PR merge,
signing, qualification or release publication is authorized.

## Main eedaba40 integration and reviewed collision-policy admission (2026-10-19)

The supervisor explicitly resumed #667 after #691 merged as
`eedaba403a40b9e90ac0bde0e1af14de0dc39543`. Normal merge
`eea41e8ea3251cb2bafad7475658891ee7343aaf` retains both parents. Main's board,
Snapshot source and interim compiled distribution are exact; no dist was hand-merged.
The SSOT preserves both owner changes; census logic is unchanged and its two changed
source-chain hashes were refreshed. The separate auxiliary #691 P3 fixture refinement
is outside #667.

Fresh canonical AST-only observation on nine whole interface files completed in
3.344 seconds: 634 scoped sites, 216 new identities and no stale scoped debt. Its
output SHA-256 is `5623f5851a6a7db5ba6c85c53bc6b81fe0256d4ab72739784fa9a2e125b49737`.
The four canonical observer/parser source hashes and helper hash are listed below.

| Source | SHA-256 |
|---|---|
| `tests/interface_computation_guard.py` | `f83e267362079992d7da07c3e82025da88cc9df3d0f07bcd2f59524f2dcd58e9` |
| `tests/interface_computation_lex.py` | `9bb4ac362db65f5da10f37a3c9c26766afe3f9956e4e46104fae2feaa6f4658c` |
| `tests/interface_computation_sources.py` | `6b29467c0b11ea6e64282e3701031b250f3b332c130fe28aac0e646b28992741` |
| `.github/scripts/interface_computation_ast.mjs` | `f230971bba5c3d6802760164e642d345adbb1c2d57dc8422b40cb0290a2fb6a3` |
| `external scoped-observer.py` | `cfd6ca618197406e7224d461b12c9dcaa6cb5bcbffa6c6150e58c1a652c0eb00` |

Exact invocation was `py -3.12 -B scoped-observer.py` in external scratch, with
`ATLAS_SOURCE_ROOT` and scratch-only `NODE_PATH`. The unchanged canonical
`scan(SourceMap(...))` supplied all identities. The only installed packages were
the owner-approved TypeScript 5.9.3, parse5 8.0.1 and entities 8.1.0, whose downloaded
and resolved integrity hashes matched the repository lock. Installation used
`npm.cmd ci --ignore-scripts --no-audit --no-fund --bin-links=false --include=dev`
with external prefix/cache; both were removed. No repository dependency file or
node_modules changed. No local test, application, build, engine, browser, Graphify
or receipt-controller execution occurred.

The proposal adds 200 ordinary boundary rows and the 16 explicit collision rows
below. The entire 36,784-row debt block is byte-identical to main: zero additions,
removals or modifications. The PR description lists all 216 exact proposals and
one-line justifications; C01-C16 and every unchanged debt witness are also below.
These are proposals, not independent approval. One rejected record blocks merge.
The registered `equalJson` compares revision/digest/selection pins; assessment-only
`sameIdentity` would miss selection changes. Registered `closed` is reused unchanged.

The source push, successful hosted frontend build/receiver, dist-and-receipt-only
import and exact-import post-verification remain separate stages. Hosted full
observation is binding and must match the proposed register. Final-head 14/14,
applicable whole workflows, native browser downloads and frozen portable evidence
are required before the completion comment and STOP for independent review. Prior
source successes and failures stay scoped to their exact subjects. The main
distribution is an interim retained artifact, not rebuilt evidence for this source.
No gate/budget/timeout, golden/sample output, product/schema version, release,
signing or external-acceptance boundary changes.

| Name | Path | Symbol | Rule | Fingerprint | Occurrence | Category | Admission class | One-line justification | All debt witnesses |
|---|---|---|---|---|---:|---|---|---|---|
| C01 | `webapp/frontend/src/api.ts` | `planInteger` | returned-comparison | `769874aa5db9480902186ad363ac8debe4e8131f7f4967c8079ed52519b601e2` | 1 | response-identity | response-shape-validation | Require a numeric JSON field before checking saved-plan transport identity. | D01 (3 unchanged rows) |
| C02 | `webapp/frontend/src/api.ts` | `planNonempty` | count | `d59d95b6279ab3f715f413e213fd1d50fdefc3905cd0954a0c3a424f30b4a0ac` | 1 | response-identity | response-shape-validation | Reject blank transported text; the length is a string-shape check. | D02 (2 unchanged rows) |
| C03 | `webapp/frontend/src/api.ts` | `planObject` | returned-comparison | `0c826da5d39395e0f298503c4c39c85fa0d1a367359de453fd0c12bbeffac601` | 1 | response-identity | response-shape-validation | Reject null saved-plan JSON containers before reading their fields. | D03 (11 unchanged rows) |
| C04 | `webapp/frontend/src/api.ts` | `planObject` | returned-comparison | `6a92bed2ade8168bed69bf6645dbb1685ee7dd7fd87ab06d4d7f90740f61b4fc` | 1 | response-identity | response-shape-validation | Require an object-shaped saved-plan JSON container before reading its fields. | D04 (11 unchanged rows) |
| C05 | `webapp/frontend/src/api.ts` | `planString` | returned-comparison | `5ff5d5487ac5420a2bcd54b5b02ec773d16f8a3aa44664fd8b897b53434e2047` | 1 | response-identity | response-shape-validation | Require a transported saved-plan field to be text before rendering it. | D05 (16 unchanged rows) |
| C06 | `webapp/frontend/src/api.ts` | `savedPlanDocument` | count | `f0816c33175ecae63d9febc05e784e458bd9f33e6d871f470c851e66ebee9193` | 1 | transport-bound | transport-serialization | Stop collecting the received Office ZIP signature after four response bytes. | D06 (10 unchanged rows) |
| C07 | `webapp/frontend/src/api.ts` | `savedPlanDocument` | count | `f0816c33175ecae63d9febc05e784e458bd9f33e6d871f470c851e66ebee9193` | 2 | transport-bound | transport-serialization | Stop traversing response chunks once the four-byte Office ZIP signature is collected. | D06 (10 unchanged rows) |
| C08 | `webapp/frontend/src/api.ts` | `savedPlanDocument` | count | `f0816c33175ecae63d9febc05e784e458bd9f33e6d871f470c851e66ebee9193` | 3 | transport-bound | transport-serialization | Require a complete four-byte Office ZIP signature before offering the received document. | D06 (10 unchanged rows) |
| C09 | `webapp/frontend/src/api.ts` | `validPlanConvergence` | count | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | 1 | response-identity | response-shape-validation | Reject a transported convergence field exceeding the lossless decimal digit bound. | D07 (4 unchanged rows) |
| C10 | `webapp/frontend/src/api.ts` | `validPlanConvergence` | count | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | 2 | response-identity | response-shape-validation | Compare equal-width transported decimal text against its supported transport bound. | D07 (4 unchanged rows) |
| C11 | `webapp/frontend/src/pages/SavedPlan.tsx` | `SavedPlanWorkspace` | count | `33dcbe05f48c894f1d9c5f2d7c3a53e276dfddaba60167945f370b0ad55d27c4` | 1 | ui-state | empty-state-presentation | Select empty-catalogue presentation from the supplied download list. | D08 (26 unchanged rows) |
| C12 | `webapp/frontend/src/pages/SavedPlan.tsx` | `SavedPlanWorkspace` | returned-comparison | `0cc66f17a5cd1f086984db045486e6f76bd644be6c88935cd9fdaa1436719639` | 1 | ui-state | empty-state-presentation | Show the empty-catalogue message when the supplied download list has no entries. | D09 (1 unchanged rows) |
| C13 | `webapp/frontend/src/pages/SavedPlan.tsx` | `formRequirements` | collection-update | `90b33a0c54e9726ededfcffd48426b4773abaabaae29804fd9b995705d2fc8d3` | 1 | ui-state | user-input-validation | Remember submitted VLAN IDs solely to reject duplicate form assignments. | D10 (1 unchanged rows) |
| C14 | `webapp/frontend/src/pages/SavedPlan.tsx` | `formRequirements` | count | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | 1 | ui-state | user-input-validation | Reject form convergence text exceeding the lossless decimal digit bound. | D07 (4 unchanged rows) |
| C15 | `webapp/frontend/src/pages/SavedPlan.tsx` | `formRequirements` | count | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | 2 | ui-state | user-input-validation | Compare equal-width form decimal text against the supported input bound. | D07 (4 unchanged rows) |
| C16 | `webapp/frontend/src/pages/SavedPlan.tsx` | `listText` | returned-comparison | `5ff5d5487ac5420a2bcd54b5b02ec773d16f8a3aa44664fd8b897b53434e2047` | 1 | ui-state | transport-serialization | Choose string or list serialization for already-persisted requirement form text. | D05 (16 unchanged rows) |

The witness groups below name every debt identity sharing the fingerprint, across all rules. Each debt tuple is `path / symbol / rule / occurrence`; its fingerprint is the group fingerprint. All dispositions and complete debt-row bytes remain identical to main `eedaba403a40b9e90ac0bde0e1af14de0dc39543`.

| Group | Shared fingerprint | Every unchanged debt identity |
|---|---|---|
| D01 | `769874aa5db9480902186ad363ac8debe4e8131f7f4967c8079ed52519b601e2` | `atlas-scope/src/contract-mode/load.ts / count / returned-comparison / 1`<br>`atlas-scope/tools/lib/compile-model.mjs / ownedImpact.count / returned-comparison / 1`<br>`webapp/frontend/src/components/ImpactValue.tsx / isCount / returned-comparison / 1` |
| D02 | `d59d95b6279ab3f715f413e213fd1d50fdefc3905cd0954a0c3a424f30b4a0ac` | `master-reference/app/atlas/capabilityLineage.ts / nonemptyString / count / 1`<br>`master-reference/app/atlas/horizonLineage.ts / nonemptyString / count / 1` |
| D03 | `0c826da5d39395e0f298503c4c39c85fa0d1a367359de453fd0c12bbeffac601` | `atlas-scope/src/contract-mode/load.ts / object / returned-comparison / 1`<br>`atlas-scope/src/contract-mode/scene.ts / createContractScene.selectionNodes.<callback> / returned-comparison / 1`<br>`atlas-scope/src/panels/DevicePane.tsx / impactCount / returned-comparison / 1`<br>`atlas-scope/tools/lib/compile-model.mjs / ownedImpact.measure / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _padObj / returned-comparison / 1`<br>`master-reference/build/projection/build.mjs / decodeSourceChunk.record / returned-comparison / 1`<br>`webapp/frontend/src/components/ComparisonDecision.tsx / asRecord / returned-comparison / 1`<br>`webapp/frontend/src/pages/Snapshot.tsx / SubjectEvidenceDetail.<callback> / returned-comparison / 1`<br>`webapp/frontend/src/pages/core/TopologyPaths.tsx / RowEvidence.<callback> / returned-comparison / 1`<br>`webapp/frontend/src/pages/core/TopologyPaths.tsx / RowFacts.<callback> / returned-comparison / 1`<br>`webapp/frontend/src/receiptExport.ts / isRecord / returned-comparison / 1` |
| D04 | `6a92bed2ade8168bed69bf6645dbb1685ee7dd7fd87ab06d4d7f90740f61b4fc` | `atlas-scope/src/contract-mode/load.ts / object / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _fhrpExactKeys / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _padObj / returned-comparison / 1`<br>`master-reference/build/deployment-manifest.mjs / hasExactKeys / returned-comparison / 1`<br>`master-reference/build/projection/build.mjs / decodeSourceChunk.record / returned-comparison / 1`<br>`master-reference/build/projection/build.mjs / hasExactObjectKeys / returned-comparison / 1`<br>`master-reference/build/projection/build.mjs / isObject / returned-comparison / 1`<br>`webapp/frontend/src/components/ComparisonDecision.tsx / asRecord / returned-comparison / 1`<br>`webapp/frontend/src/pages/core/TopologyPaths.tsx / RowEvidence.<callback> / returned-comparison / 1`<br>`webapp/frontend/src/pages/core/TopologyPaths.tsx / RowFacts.<callback> / returned-comparison / 1`<br>`webapp/frontend/src/receiptExport.ts / isRecord / returned-comparison / 1` |
| D05 | `5ff5d5487ac5420a2bcd54b5b02ec773d16f8a3aa44664fd8b897b53434e2047` | `atlas-scope/src/core/query.ts / iv / returned-comparison / 1`<br>`atlas-scope/src/core/types.ts / member / returned-comparison / 1`<br>`atlas-scope/tools/lib/compile-model.mjs / ownedImpact.text / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _fhrpDomainHex / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _fhrpDomainText / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _ipv6RoutingAsciiString / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _padText / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _routeOwnText / returned-comparison / 1`<br>`cisco_toolkit/blast_radius_explorer.html / fhrpConfiguredGroupBaselineFrom.<callback> / returned-comparison / 1`<br>`master-reference/build/projection/build.mjs / graphSourceLocationIsValid / returned-comparison / 1`<br>`master-reference/build/projection/build.mjs / isNonblankString / returned-comparison / 1`<br>`webapp/frontend/src/components/ImpactValue.tsx / text / returned-comparison / 1`<br>`webapp/frontend/src/components/Topology3D.tsx / Topology3D.<callback>.endpoint / returned-comparison / 1`<br>`webapp/frontend/src/projectionEmbed.ts / isContextDigest / returned-comparison / 1`<br>`webapp/frontend/src/projectionEmbed.ts / isEmbedNonce / returned-comparison / 1`<br>`webapp/frontend/src/projectionEmbed.ts / requestId / returned-comparison / 1` |
| D06 | `f0816c33175ecae63d9febc05e784e458bd9f33e6d871f470c851e66ebee9193` | `atlas-scope/src/app/keyboard.ts / dispatch / count / 1`<br>`atlas-scope/src/panels/HopList.tsx / AclFact / count / 1`<br>`atlas-scope/src/panels/HopList.tsx / fallbackLists / count / 1`<br>`cisco_toolkit/blast_radius_explorer.html / _routePrefix / count / 1`<br>`master-reference/build/projection/build.mjs / dossierPrefixFor / count / 1`<br>`master-reference/build/projection/build.mjs / dossierPrefixFor / count / 2`<br>`master-reference/build/projection/build.mjs / splitDossierBucket / count / 1`<br>`master-reference/build/projection/build.mjs / splitDossierBucket.<callback> / count / 1`<br>`master-reference/build/projection/build.mjs / splitSearchBucket / count / 1`<br>`master-reference/build/projection/build.mjs / splitSearchBucket.<callback> / count / 1` |
| D07 | `2eb47204f67cd87a3a1aa93252d51bf9afd23d5031f7c6e9659ab5ac21100bf5` | `master-reference/build/projection/build.mjs / pythonFloatToken / count / 1`<br>`master-reference/build/projection/build.mjs / pythonFloatToken / count / 2`<br>`master-reference/build/projection/build.mjs / pythonFloatToken / count / 3`<br>`master-reference/build/projection/build.mjs / pythonFloatToken / count / 4` |
| D08 | `33dcbe05f48c894f1d9c5f2d7c3a53e276dfddaba60167945f370b0ad55d27c4` | `atlas-scope/review/capture.mjs / readCoverageVisibility / count / 1`<br>`atlas-scope/src/core/data.ts / tallySeverities / count / 1`<br>`atlas-scope/src/core/query.ts / applyClauses / count / 1`<br>`atlas-scope/src/core/query.ts / applyClauses / count / 2`<br>`atlas-scope/src/core/query.ts / applyClauses.<callback> / count / 1`<br>`atlas-scope/src/panels/Inspector.tsx / GapSection / count / 1`<br>`atlas-scope/src/ui/primitives.tsx / Dialog.<callback>.onKey / count / 1`<br>`atlas-scope/src/ui/primitives.tsx / Dialog.<callback>.onKey / count / 2`<br>`cisco_toolkit/blast_radius_explorer.html / abqProg / count / 1`<br>`cisco_toolkit/blast_radius_explorer.html / computeCurrentBaselineGate / count / 1`<br>`cisco_toolkit/blast_radius_explorer.html / computeCurrentBaselineGate / count / 2`<br>`cisco_toolkit/blast_radius_explorer.html / computeCurrentBaselineGate / count / 3`<br>`cisco_toolkit/blast_radius_explorer.html / computeCurrentBaselineGate / count / 4`<br>`cisco_toolkit/blast_radius_explorer.html / drawDesignNrfu / count / 1`<br>`cisco_toolkit/blast_radius_explorer.html / drawDesignNrfu / count / 2`<br>`cisco_toolkit/blast_radius_explorer.html / wavesValidationBlock / count / 1`<br>`cisco_toolkit/blast_radius_explorer.html / wavesValidationBlock / count / 2`<br>`cisco_toolkit/blast_radius_explorer.html / wavesValidationBlock / count / 3`<br>`master-reference/app/atlas/horizonLineage.ts / stringArray / count / 1`<br>`webapp/frontend/src/pages/Snapshot.tsx / DeliverablesPanel / count / 1`<br>`webapp/frontend/src/test/projectionFixtures.ts / carriagePageFixture / count / 1`<br>`webapp/frontend/src/test/projectionFixtures.ts / carriagePageFixture / count / 2`<br>`webapp/frontend/src/test/projectionFixtures.ts / ownerList / count / 1`<br>`webapp/frontend/src/test/projectionFixtures.ts / ownerPage / count / 1`<br>`webapp/frontend/src/test/projectionFixtures.ts / ownerPage / count / 2`<br>`webapp/frontend/src/test/projectionFixtures.ts / requireContractVocab / count / 1` |
| D09 | `0cc66f17a5cd1f086984db045486e6f76bd644be6c88935cd9fdaa1436719639` | `atlas-scope/src/panels/Inspector.tsx / GapSection / returned-comparison / 1` |
| D10 | `90b33a0c54e9726ededfcffd48426b4773abaabaae29804fd9b995705d2fc8d3` | `cisco_toolkit/blast_radius_explorer.html / stpRootElection / collection-update / 1` |
