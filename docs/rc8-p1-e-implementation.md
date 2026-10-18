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
The codec does not enforce the endpoint HELLO/ACK or message-state handshake;
that endpoint must reject wrong-state messages and require HELLO_ACK before any
native imports/profile creation. It remains a pre-wiring implementation gate.

`tests/test_native_presentation_contract.py` supplies synthetic URI, transition,
IPC attack and additive-header controls. Time is injected for protocol rate tests;
they have no wall-clock deadline or live UI capture. Future real-time/UI tests
must carry `@pytest.mark.unshared`, without skipping or relaxing them.

## Acceptance items

| Approved item | Source/proof status |
|---|---|
| 1. Isolated proxy_tools producer, complete-wheel/license/provenance checks, immutable admission | NOT IMPLEMENTED; execution/publication/produced-wheel lock HELD. All approved admission conditions remain mandatory. |
| 2. Custom collection hook, pinned x64 SDK/NetFX overlay, notices and SBOM | NOT IMPLEMENTED; no dependency or collection exception. |
| 3. Pre-navigation handler/settings order and immutable-origin policy | URI/CSP source controls authored; actual event adapter and frozen integration NOT VERIFIED. |
| 4. Sole profile owner, real browser exit, empty-only identity-bound cleanup | NOT IMPLEMENTED; no cleanup path introduced. |
| 5. Verified production Evergreen and presentation-local unelevated eligibility | NOT IMPLEMENTED; native release admission stays closed. |
| 6. GUI-only state machine and private identity-bound IPC | Pure transitions/codec authored; Windows handles, job and pipe transport NOT IMPLEMENTED. |
| 7. Protected staging/final targets, same-volume publication and incomplete latch | NOT IMPLEMENTED; no native download writer introduced. |
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
