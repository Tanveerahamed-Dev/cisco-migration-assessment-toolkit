# P1-E implementation and evidence ledger

2026-10-19. Author branch: `codex/rc8-native-window`. Initial integration base:
`ee5ee274210d84083b99ae1c407b2c1ca9182e86` (#682 boundary guard and #690 two-pass CI).

The owner approved the design on 2026-10-19. The exact approved design is retained
in [rc8-p1-e-native-window-design.md](rc8-p1-e-native-window-design.md), SHA-256
`4aaac441c575f273233ba5730949bb198856e948aa5c1b50066eff6193d16cd7`.
Its historical “re-review required” footer records the submitted revision; the
subsequent owner approval authorizes implementation, not dependency production.
The supervisor owns `docs/NOW.md`; this feature does not update the board.

## Dependency authority and current field behavior

Dependency production, signing, promotion, asset publication and a lock pointing
to a produced wheel are **HELD for separate owner authority**. No such operation
has run. Existing binary-only/hash-required installation remains unchanged.
`require_native_release_admission` refuses unconditionally in this first slice;
an ambient pywebview installation or environment variable cannot enable it.
The shipped entry, browser behavior, lock, PyInstaller specification, smoke and
selftest are unchanged. This slice cannot claim native rendering or P1-E completion.

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
| 1. Isolated proxy_tools producer, complete-wheel/license/provenance checks, immutable admission | Read-only complete-wheel inspector and HELD source-input record authored; actual producer/isolation/attestation/release admission NOT IMPLEMENTED. Execution/publication/produced-wheel lock HELD. Licence declaration conflict below unresolved. |
| 2. Custom collection hook, pinned x64 SDK/NetFX overlay, notices and SBOM | NOT IMPLEMENTED; no dependency or collection exception. |
| 3. Pre-navigation handler/settings order and immutable-origin policy | URI/CSP source controls authored; actual event adapter and frozen integration NOT VERIFIED. |
| 4. Sole profile owner, real browser exit, empty-only identity-bound cleanup | NOT IMPLEMENTED; no cleanup path introduced. |
| 5. Verified production Evergreen and presentation-local unelevated eligibility | NOT IMPLEMENTED; native release admission stays closed. |
| 6. GUI-only state machine and private identity-bound IPC | Pure transitions/codec/stateful endpoint authored; Windows handles, job and pipe transport NOT IMPLEMENTED. |
| 7. Protected staging/final targets, same-volume publication and incomplete latch | Pure admission/revalidation model includes both paths, required inventory and attempt-bound GUI slot. Actual handle owner, atomic slot claim, SDK writer/publication and persisted incomplete latch NOT IMPLEMENTED. |
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
