# P1-E implementation and evidence ledger

2026-10-19. Author branch: `codex/rc8-native-window`. Initial integration base:
`ee5ee274210d84083b99ae1c407b2c1ca9182e86` (#682 boundary guard and #690 two-pass CI).

The owner approved the design on 2026-10-19. The exact approved design is retained
in [rc8-p1-e-native-window-design-approved.md](rc8-p1-e-native-window-design-approved.md), SHA-256
`4aaac441c575f273233ba5730949bb198856e948aa5c1b50066eff6193d16cd7`.
Its historical “re-review required” footer records the submitted revision; the
subsequent owner approval authorizes implementation, not dependency production.
The [current design](rc8-p1-e-native-window-design.md) preserves that approved
text and appends the owner's named licence BLOCK and evidence-only route request.
The supervisor owns `docs/NOW.md`; this feature does not update the board.

## Dependency authority and current field behavior

Dependency production, signing, promotion, asset publication and a lock pointing
to a produced wheel are **HELD for separate owner authority**, with explicit
`PROXY_TOOLS_010_LICENSE_CONFLICT` **BLOCKED and unresolved**. No such operation
has run. Existing binary-only/hash-required installation remains unchanged.
`require_native_release_admission` refuses unconditionally in this first slice;
an ambient pywebview installation or environment variable cannot enable it.
The dependency lock, PyInstaller specification, smoke and selftest are unchanged.
The packaging entry now takes a narrow presentation-preparation callback after
normal startup fences. While native admission is held it schedules the existing
browser and retains the exact original app/server/lifespan/Store owner.
`--browser` explicitly bypasses the callback; `--no-browser` stays headless. No
native dependency imports, profiles or GUI creation occur. These source slices
cannot claim native rendering or P1-E completion.

## First coherent slice

`portable/native_origin.py` owns strict numeric loopback origin tuples, native
navigation/download URI admission, and the additive native-response CSP wrapper.
The wrapper is authored but not installed into the running server in this slice.
It preserves existing CSP and authentication headers.

`portable/native_window.py` owns presentation-only transitions. Its effect set
can start/show/retire the GUI, wait for its one download, open a browser or print
the URL. It has no server-stop, Store-close, worker-cancellation or replay effect.
BROWSER and MANUAL_REQUIRED cannot return to a retired native presenter. This is
not yet an OS process supervisor and does not attest that a GUI has exited.

`portable/native_ipc.py` owns closed, bounded, directional MAC/sequence/session
frames and peer-identity comparison. The Windows transport must establish actual
pipe peer, held process/creation identity, logon SID, medium integrity and GUI-job
membership; codec acceptance alone proves none of those OS observations.
The codec alone does not enforce the endpoint HELLO/ACK/message-state handshake.
The next source slice adds `portable/native_endpoint.py`: it requires HELLO/ACK,
then the pinned policy digest, actual public instance, document notification and
SHOW in order. Invalid order closes that endpoint; duplicate authenticated fault
notifications coalesce through retirement. Windows transport and actual
HELLO_ACK-before-native-import wiring remain unimplemented and unverified.

`tests/test_native_presentation_contract.py` supplies synthetic URI, transition,
IPC attack and additive-header controls. Time is injected for protocol rate tests;
they have no wall-clock deadline or live UI capture. Future real-time/UI tests
must carry `@pytest.mark.unshared`, without skipping or relaxing them.

## Acceptance items

| Approved item | Source/proof status |
|---|---|
| 1. Isolated proxy_tools producer, complete-wheel/license/provenance checks, immutable admission | Read-only inspector/input record authored; PROXY_TOOLS_010_LICENSE_CONFLICT BLOCKED, unresolved. Actual producer/isolation/attestation/release admission NOT IMPLEMENTED. Execution/publication/produced-wheel lock HELD. |
| 2. Custom collection hook, pinned x64 SDK/NetFX overlay, notices and SBOM | NOT IMPLEMENTED; no dependency or collection exception. |
| 3. Pre-navigation handler/settings order and immutable-origin policy | URI/CSP source controls authored; actual event adapter and frozen integration NOT VERIFIED. |
| 4. Sole profile owner, real browser exit, empty-only identity-bound cleanup | NOT IMPLEMENTED; no cleanup path introduced. |
| 5. Verified production Evergreen and presentation-local unelevated eligibility | NOT IMPLEMENTED; native release admission stays closed. |
| 6. GUI-only state machine and private identity-bound IPC | Pure transitions/codec/stateful endpoint authored; Windows GUI/process handles, job and pipe transport NOT IMPLEMENTED. |
| 7. Protected staging/final targets, same-volume publication and incomplete latch | Admission/revalidation model includes both paths, required inventory and attempt-bound GUI slot. Existing-directory Windows identity reader authored but NOT VERIFIED on Windows. Protected-root inventory, directory creation/private ACL, atomic slot claim, SDK writer/publication and persisted incomplete latch NOT IMPLEMENTED. |
| 8. Genuine same-WebView UI/download proof and strict consumer | NOT IMPLEMENTED; no NATIVE_PASS, FALLBACK_PASS or frozen result claimed. |
| 9. Operator browser escape, size/process/RSS measurement, Windows 10/11 behavior | Existing browser retained; new UI/operator integration and measurements NOT VERIFIED. |

All existing gates, budgets, timeouts, assertions and release/field authority
boundaries remain. Local work is source/text/Git and permitted static lint plus
Rule-7 scans only. Runtime, tests, builds, measurements and native proof are
GitHub-only. Exact-head hosted results must be recorded before any completion
comment or independent implementation verdict. Every negative or unavailable
capability remains explicit; the approved design is not implementation evidence.

## Preserved source-review finding

Independent static review of first commit `b7a78ef4` found that an asynchronous
browser attempt left SERVER_READY and could also admit START_NATIVE. The
correction commits the browser choice in the existing RETIRING phase before
emitting OPEN_BROWSER, rejects late native/manual choices until its result, and
coalesces stale GUI/fault/close events without changing intent. New synthetic
sequences cover both opener results and server exit during the pending attempt.
This finding was source-traced; its new tests still require hosted execution.
The full Rule-7 scan of b7a78ef4 completed PASS, but cannot cover the correction;
the new committed head receives its own full scan before publication.

## Next source slice and preserved limits

`portable/native_download.py` accepts only typed, trusted physical-handle
observations. Both staging and final locations are checked against every named
protected-root category, plus target absence, same NTFS volume and operation
support. Staging is disjoint from protected subtrees in either direction.
Admission requires a complete empty retained-staging inventory and empty GUI
download slot; the real owner must atomically claim that slot, then revalidate
the exact attempt, inventory and paths before any write and again at publication.
It writes nothing. Its tests inject resolved aliases and volume identities; they
do not establish actual short-name/reparse/drive/handle behavior or persistence.

Independent static review identified duplicate-fault endpoint closure and the
initially separate inventory check. Corrections coalesce sequenced FAULTs in
FAULT/RETIRING and make inventory/slot observations mandatory in admission and
revalidation. New tests include the exact fault burst and retained-item/slot
sequences. They require hosted execution; no local test was run.

`portable/native_dependency.py` inspects a closed six-file wheel, source hash,
pure tag, dependency metadata, applicable-text hash, RECORD and ZIP layout. It
rejects added startup hooks/scripts/extensions/packages and unindexed carriers.
Its result explicitly grants no producer identity, legal acceptance, immutable
release or production authority. Synthetic wheel fixtures are not dependency
builds and certify no actual accepted wheel. Provenance/release admission and
the isolated producer workflow remain future work; no dependency build has run.

Independent source review of `0337ae40` identified that ordinary ZIP member
reads could ignore carrier bytes inside a stored/deflated compressed range, and
that required Metadata-Version was not checked. The correction decodes bounded
raw deflate itself, requires EOF with no unused/unconsumed input, exact decoded
length/CRC and exact stored sizes, then verifies the closed central layout and
RECORD. It requires one Metadata-Version 2.4 and strict UTF-8 metadata. Synthetic
regressions preserve logical member bytes/CRC/RECORD while extending compressed
ranges and adjusting offsets, plus missing/duplicate/unsupported version and
invalid-encoding cases. These are authored controls, not executed proof.

### Pinned-source licence evidence — unresolved

Static archive inspection on 2026-10-19 read the public, hash-pinned sdist as data
only: source SHA-256 `ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010`,
2,978 bytes. Metadata declares MIT, while `proxy_tools/__init__.py` declares BSD
and refers to a missing LICENSE. The module is 6,409 bytes, SHA-256
`d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be`.
No source was imported/executed or built. The public input pointer and both
declarations are retained in `portable/native_dependency_inputs.json`.

Cause of the inconsistent declarations is unconfirmed; no legal choice is
inferred. Before promotion, the owner must bind applicable licence/copyright
text to an attributable source record and resolve the conflict. Missing text
cannot be fabricated or replaced by a metadata classifier. Even a future build
or publication authorization does not establish legal acceptance. The native
dependency path remains closed; the browser and existing locked build continue.

The supervisor explicitly retained this as `PROXY_TOOLS_010_LICENSE_CONFLICT`,
not a resolved/accepted licence. Exact archive references are PKG-INFO line 8,
setup.py line 14 and proxy_tools/__init__.py line 8 (under proxy_tools-0.1.0/).
`portable/native_release_gate.py` unconditionally refuses native dependency
promotion under that code, and native admission consumes the same gate. JSON,
environment and selected wheel/text hashes cannot clear it. No licence text is
selected, inferred, synthesized or written. The design addendum records the
owner's decision; the original approved design stays byte-identical separately.

The owner-requested [static route inspection](rc8-p1-e-proxy-tools-static-inspection.md)
finds an unconditional install dependency and root import in unchanged pywebview
6.2.1, including the Windows backend path. A further source/metadata adaptation
is only an evidence-based candidate, not adopted or runtime-verified. No pins
changed and no dependency build/installation was run.

## Shared entry seam

`serve.main`/`_main_scoped` accept an optional `presentation_prepare` callback,
with default call signatures preserved when it is absent. Shared parsing adds
mutually exclusive `--browser`/`--no-browser`. Maintenance/engine/selftest
dispatch, freeze_support, live-network normalization/restoration and write fences
remain before presentation. The adapter is lazy and bypassed for explicit
browser/headless paths. Preparation is not actual bind readiness: the future
native launcher still must prove its own socket/public instance before GUI use.

The callback may configure additive ASGI middleware on the original app; its
return value cannot replace that app. Existing uvicorn.run, signal/lifespan
behavior and the original app's single Store close remain shared.
`portable/native_launch.py` currently always uses browser fallback behind the
unconditional dependency guard; it implements no native/OS operation. New fake
server/store tests exercise ordering, bypasses, opaque engine argv, mutual
exclusion, legacy callback compatibility and exactly-once Store closure without
a clock or live UI. Actual hosted/frozen behavior and ADR guard admission remain
unverified until their exact-head jobs run.
Import spies observe the call phase after module collection; they do not prove a
clean-process first-import or frozen dependency boundary.

## Preserved hosted scheduling evidence

On head `8a6199df697e9a3ca416694795d9a7ea081d2d24`, webapp run
`39169900188` ended CANCELLED. Scope job `117800592964` executed no steps;
its annotation reports a higher-priority waiting request for the same PR's
webapp concurrency group. The dependent jobs deliberately failed their existing
scope-success guard; backend job `117800596004` logged only that guard's exit 1,
not a product test run. The draft description edit triggered the configured
pull_request edited event immediately after the synchronize event.

The already-created replacement run `39169901056` on the same head completed
SUCCESS: scope and webapp gate succeeded; backend/frontend/E2E/visual jobs were
SKIPPED by the unchanged successful classifier because that head changed only
packaging/tests/docs. This is scope-gate evidence, not executed backend/frontend
or native proof. No manual rerun/cancellation was issued. Keep the cancelled
run/guard failures; neither replacement success nor future heads erase them.
Update PR descriptions before future source pushes to avoid duplicating the
final head's synchronize workflow. No hosted result transfers to new source.

## Current-main integration

This preserved-parent merge imports current main
`bc54fa80721adf00f0e4c9f309b7264739ffc6fb` (#681), after the authorized initial
rebase to `ee5ee274210d84083b99ae1c407b2c1ca9182e86`. Its feature parent is
`1427e4938365e14ac9af45883b0f7bc44913f306`. Incoming owner code, frontend receipt
and debt reductions remain main-owned; this feature adds only its native owner
pointer to the SSOT registry. The board is restored byte-identically to main.
CI/portable workflows, shard jobs/pins, dependency/toolchain locks and original
assertions/budgets/timeouts receive no authored change. Fresh committed-head
privacy/every-parent/imported-history scans and hosted checks remain required;
earlier-head source/CI evidence does not qualify this merge or native rendering.

## Existing-directory Windows identity slice

`portable/native_windows_identity.py` reads only existing directories. It opens
every ancestor without delete sharing, refuses reparse/case-sensitive/unsupported
media and holds normalized volume-GUID paths, the FileIdInfo 64-bit volume serial
and 128-bit file ID. It rechecks the complete physical parent chain and identities.
The 64-bit serial is not equated to the separate DWORD volume-information serial.
Actual native AMD64 is required through IsWow64Process2; a 64-bit pointer alone
does not establish architecture. Missing capability refuses admission.

Known Folder lookup requests the current user's LocalAppData with DONT_VERIFY
and no CREATE flag, avoiding Shell's existence probe of a redirected network
location before local namespace refusal. Environment LOCALAPPDATA/TEMP cannot
substitute a path. Its result is still
subject to the same held-directory admission. It creates no profile, staging
directory or download and is not called by the held browser path. It establishes
no DACL/ownership, complete protected-root inventory, runtime trust, GUI group,
same-volume publication or native readiness.

Full paths and components count strict UTF-16 WCHAR units, not Unicode code
points; unpaired surrogates refuse. The observed NTFS maximum must be 255 WCHARs.
Download-plan revalidation now also requires known matching 64-bit volume serials.
Snapshots/plans and peer diagnostics redact private paths/IDs/SIDs; this does not
permit generic field serialization into public evidence.

Review identified an original failed-close reporting gap, a physical-chain
substitution gap, diagnostic repr disclosure, exception-annotation masking and
code-point/WCHAR ambiguity and a default Known Folder existence probe before
namespace admission. The source corrections retain failed handles for
retry, latch retirement against readmission, check each held parent-child pair,
redact diagnostic representations and preserve an original BaseException even
if it refuses diagnostic attributes. Unknown cleanup remains unconfirmed; no
profile/download deletion is introduced.

Authored synthetic controls cover these faults, surrogate/length boundaries and
Known Folder allocation disposal on success/refusal. Two real hosted-Windows
tests require existing NTFS handle identities, deletion/rename exclusion and the
OS-selected Known Folder. Missing APIs fail those Windows cases rather than skip.
Non-Windows cases assert unsupported-platform refusal and do not qualify Windows.
These tests have no wall-clock deadline/live UI capture; none was run locally.
Actual short-name/reparse/DOS-remapping races, real cleanup-failure injection,
private ACLs and native/frozen proof remain NOT VERIFIED.

Primary API contracts: [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[FileIdInfo](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info),
[volume information](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationbyhandlew),
[Known Folder](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath)
and [actual architecture](https://learn.microsoft.com/en-us/windows/win32/api/wow64apiset/nf-wow64apiset-iswow64process2).

The supervisor's current stop boundary is this coherent source slice after
exact-head 14/14 and an itemized proof-status comment, then independent review.
It is not P1-E native completion. PR #693 stays draft; the licence BLOCK and pins
remain unchanged. Terminal hosted failures must be inspected and genuine source
failures corrected without changing gates, budgets, timeouts or assertions.

## Hosted diagnostic-fixture failure and correction

On source head `cddd87ca6598e1f36564bf52329ce132a5945323`, CI run
`39176198136`, Python 3.11 job `117819460127` ended with one failure in the
shared default-suite pass: 20,712 passed, 370 skipped, three xfailed, five warnings
and 26 subtests passed in 1,630.90 seconds. The unshared pass was not reached.
The completed job log is retained outside the checkout; this is an actual test
failure, not the expected old-head/main-parent custody refusal.

`test_diagnostics_do_not_expose_physical_directories_selected_names_or_volume_ids`
used the private fixture component `Protected`, which also appears in the
redacted public type name `ProtectedRoot(<private>)`. The displayed representation
contained no snapshot fields; the test's substring oracle collided with its own
generic fixture name. Change only that synthetic namespace to the distinctive
`ClientNamespaceSentinel` at its three consistent uses: protected-root fixture,
diagnostic sentinel list and protected-path candidate. Every assertion and test
definition is preserved, as is all product redaction code. This repairs the
authored fixture; it does not resolve a demonstrated private-data exposure.

Static round-trip comparison must reproduce the prior test bytes after reversing
those three literal substitutions; assertion ASTs and test names/signatures remain
identical. Fresh independent review, committed-head Rule-7/marker scans and hosted
results are still required. The failed head and any other terminal findings remain
history; no rerun, skip, relaxed assertion or earlier-head acceptance is inferred.

## Windows approved-design byte custody

The same source head's completed Windows job `117819460269` in CI run
`39176198136` reported two failures: the diagnostic-fixture collision above and
`test_current_dependency_record_is_blocked_and_preserves_the_source_license_conflict`.
Its shared-pass summary was two failed, 21,023 passed, 58 skipped, three xfailed,
18 warnings and 26 subtests passed in 2,663.64 seconds. The unshared pass was not
reached. The second failure is independent of licence resolution or the private
fixture: Windows materialized the approved Markdown snapshot with CRLF.

The Git blob remains 44,596 LF-only bytes with approved SHA-256
`4aaac441c575f273233ba5730949bb198856e948aa5c1b50066eff6193d16cd7`.
Converting those exact LF bytes to CRLF yields
`98f53dbdbaf54fc0ac3296b9a4890daf0f83d51d1579241b503a7176d59718f7`, exactly
the observed Windows mismatch. The missing per-file checkout attribution is the
cause; the approved bytes and pinned expectation are not changed.

Add one exact `.gitattributes` rule, outside the existing R1/R2 policy blocks and
domains, marking only `docs/rc8-p1-e-native-window-design-approved.md` as
`-text -eol`. Git must retain that evidence snapshot byte-for-byte, independent of
autocrlf. No other Markdown path, policy receipt/domain, dependency record/hash,
test assertion, gate, budget or timeout changes. Source-only Git filter/hash
observations and independent review precede a fresh committed-head privacy scan
and publication. Only fresh hosted results on the subsequent exact head can
verify the repair; no old Windows or frozen result transfers.

## Independent slice review: two archive-inspector defects

The independent review of `32482da94aaa74702d217c975589c30aeec7b4ea`
([6258189947](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/693#issuecomment-6258189947))
is **BLOCKED** on two P2 source defects. The earlier head's 14 green contexts and
desktop proof do not close these counterexamples or validate a correction head.
The supervisor authorized both repairs and a preserved-parent pure merge of main
`17bd076aca5b18deccdaf659152011410f4987c3`. Merge commit
`7bbcfa70ffb9765fbbb5eb147c0529a304a491ea` has parents `32482da9` and
`17bd076a`; its tree exactly matches `git merge-tree`, with no authored conflict
resolution. The four imported #689 pause files remain main-owned.

1. The wheel inspector compared local names and the closed set with the
   sanitized `ZipInfo.filename`. A NUL followed by carrier bytes in only the
   central-directory name could disappear from that view even with the altered
   wheel's selected digest. The correction refuses original/sanitized name
   differences and any NUL, parses every raw central entry, and binds its name
   bytes and encoding flag to the local header and original name. Exact central
   span consumption, stream EOF/CRC/size, source/license digests, member set,
   metadata and RECORD checks remain required. Hosted controls mutate only the
   central name and its declared size with the matching changed digest, retain
   local headers/payload/RECORD bytes, and exercise encoding disagreements plus
   matched encoding positives. New controls require both the existing public
   archive-refusal code and the exact typed filename/layout cause; the existing
   parser-error normalization is preserved.
2. The sdist inspector required a descendant prefix before allowing its canonical
   root directory. CPython strips that directory's trailing slash, so the only
   pinned archive necessarily refused. The correction admits only the exact
   canonical top-level directory before the prefix check; only the two known
   descendant directories are admitted. Duplicate/link/type/file-set/size/source
   and archive-hash refusals remain. The hosted positive reads the exact public
   2,978-byte pinned archive from an inert base64 JSON fixture; it never imports,
   extracts to disk, installs or executes its source. Synthetic positive and
   directory/name/link/duplicate/file-set/size/hash negatives exercise the inner
   guards with explicitly synthetic identity, separate from the unpatched real
   pinned-archive positive.

These are source corrections pending fresh exact-head hosted evidence. Every
existing assertion is retained. No gate, budget, timeout, scanner, dependency
pin, lock, producer or native startup change is made. The unresolved
`PROXY_TOOLS_010_LICENSE_CONFLICT` remains BLOCKED, and all dependency execution,
build, licence resolution, promotion and publication remain held. Static archive
fixture copying is data handling only. The native path remains inert behind the
browser. Fresh Rule-7/marker scans and independent source review precede the one
push; fresh 14/14 and a bounded completion comment precede the same reviewer's
re-review. PR #693 stays draft, with no PR merge or release authority.
