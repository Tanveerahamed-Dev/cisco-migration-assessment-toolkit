# W2d: immutable snapshot projection performance

Status: implementation, independent review and performance target verified; local backend/custody gates passed; publication/hosted gates pending. This record does not claim
readiness, merge, release qualification or field acceptance.

## Source and scope

Base: `db9d8534cd93f62379d2cfda8fa37090b710c0e7`, the merge of #584 from
`61961ca371392c99f209c604456a99cc6e19b04e`. Their trees are identical. Work is on
`codex/ui-projection-performance` in the existing UI checkout. The merged W2c row
is removed under board rule 8. W2e, W6 and W7 remain ordered follow-ups; #582 belongs
to the separate Scope session.

The requested boundary is one computed and validated projection for immutable
stored bytes and engine/projection semantics, reused across views and pages.
Current store authority, exact digest form, deletion behavior, all owner fact
states, full-document validation before selection, and HTTP response validation
remain required. Schema-validator construction was already reused on the base;
repeated projection, full validation, transport validation and list copies were
the measured request costs.

## Implemented boundary

The cache lives with one application/store and keys documents by exact stored-byte
SHA-256, engine schema version, release identity and projection-schema digest. The
four core views share one complete document; device documents are lazy and keyed
by the exact host string. A per-source lock coalesces concurrent misses. Every
request still calls `get_snapshot_blob`, preserving current-byte authority failure
and deletion refusal; response identity is rebuilt from that same read. Failed
admission stays retryable. Source binding occurs once, and the producer receives
an isolated copy on each document miss. Cached documents and outgoing pages have
separate containers. Paging copies only the selected rows and retained metadata.

Compiled validation narrows only provably impossible `oneOf` alternatives using
required finite string discriminators. Complete remaining constraints and exact-one
semantics still run. Root definition and unique-branch validators are compiled once
and reused with their root resolver. Ambiguous references, nested resources,
dynamic/recursive scope and alternate dialects fall back to stock validation.
Canonical owner schemas, OpenAPI and real HTTP
response guards remain intact, including non-finite/non-JSON-native rejection.

There is no size eviction: reopening a touched snapshot or device does not trigger
recomputation during this application's lifetime. The operational tradeoff is memory
growth with touched snapshots and exact host selections, including unknown hosts.
Restart releases the cache. RSS measurements below describe the whole process, not
an isolated cache allocation; this is not a persistent cache across restarts.

## Reproducible measurement

`tests/perf_ui_projection.py` exercises actual ASGI HTTP responses, including store
reads, authority verification, projection, validation, paging and serialization.
It uses a temporary database, explicit loopback peer and unchanged committed
sample. The scale load is the existing synthetic `_big` fixture from
`tests/test_ui_projection_inventory.py`: 300 devices, 20,100 interfaces and 9,000
endpoints. It is load evidence, not a newly assessed or accepted network.

Run the benchmark with `--all-lists --repeats 5 --output <external receipt.json>`.
Use `--limit 200` to exercise the maximum page size and
`--require-sample-warm-ms 300` to make the sample target an explicit exit gate.
Receipts include individual timings, source hashes, runtime/dependency versions,
stored-byte identity, response sizes and response digests. Each endpoint's first
request is recorded separately; later view requests can already benefit from an
earlier view's snapshot cache. Repeated response bytes must match exactly.

Base measurement on Python 3.12.10 / Windows, 50-row limit, two repeated calls per
endpoint (preliminary baseline, not a percentile estimate):

| Endpoint | Warm median ms | Warm maximum ms |
|---|---:|---:|
| Overview | 2165.1 | 2417.9 |
| Trust | 2650.1 | 2866.2 |
| Inventory | 2777.5 | 2943.8 |
| Findings | 2513.8 | 2795.5 |
| Device | 456.1 | 528.8 |
| Inventory device list | 1871.4 | 2057.4 |
| Findings list | 2153.0 | 2400.8 |
| Device interface list | 295.8 | 351.4 |

The stored sample is 2,473,211 compact JSON bytes; its store digest is
`sha256:d7d887336b7d85f71d3ce95a7a32a8a912dc7e50b039dec86f51f567f039ffaf`.
Its source file and upload digest are different identities. The first benchmark
attempt received the expected 403 for a symbolic non-loopback ASGI client;
the harness was corrected to specify a numeric loopback peer. No application
guard was relaxed.

## Review corrections and negative evidence

Independent review found unsafe discriminator proofs for nested schema resources,
escaped/complex references and boolean definitions. Conservative fallback and
counterexamples close those cases without weakening the canonical schema. It also
found a retained producer-input alias that could affect a later device document;
copying the bound input on a miss isolates it. Final executable review is pending.

The first focused run had 66 passes and two newly authored test setup failures:
the application correctly translated integrity failure to HTTP 409, and SQLite
correctly refused an authority-row update. The tests now assert HTTP 409 and exercise
a missing-authority-row corruption. A subsequent complete run passed 74 tests;
later resource/dialect/input-alias hardening passed 11 targeted tests, then the
independent complete rerun passed 77 tests and 12 separate refutation groups.
An initial reviewer run could not create its nested temporary directory; that
harness setup failure is retained separately from the successful unchanged-source
replay. Further performance changes still require fresh verification.

The first cached 50-row sweep measured all 36 request shapes on both fleets, with
five repeated calls each: sample maximum 210.2 ms; synthetic maximum 267.5 ms.
The synthetic first projection took 20.88 s. This was before the cold-only producer
input isolation. The subsequent 200-row sample sweep exposed a remaining failure:
Findings view median 408.4 ms / maximum 461.1 ms; Findings list median 489.3 ms /
maximum 526.5 ms. Its explicit 300 ms gate exited 1. This is an open performance
finding, not superseded by the passing 50-row result. The correction must also
improve a first new page after the snapshot is warm, rather than only repeated
identical responses.

## Final source results

Resolved the maximum-page failure by reusing root-reference and proven unique-branch
validators. Every response still runs its complete applicable schema constraints;
there is no response-success memoization. Final focused suite: **83 passed**.
Independent replay passed 73 reference/recursion/constraint/error-path cases, 200
concurrent validator runs, complete sample/off-page malformed-source parity, and
five hostile mutations injected after warming a 200-row HTTP response. The valid
retry remained unchanged. Repository Ruff, diff checks and the API-generation gate
(nine policy tests plus exact generated-type equality) pass.

Final sequential HTTP measurements: **36 request shapes per fleet/page limit,
five repeated calls each**. Both sample sweeps' explicit 300 ms gate passed; it
includes first visits to later views/pages after the initial Overview as well as
repeated responses.

| Fleet | Page limit | First complete projection ms | Largest first later call ms | Largest repeated call ms |
|---|---:|---:|---:|---:|
| 23-device sample | 50 | 386.0 | 115.7 | 145.2 |
| 23-device sample | 200 | 479.9 | 273.9 | 273.1 |
| 300-device synthetic | 50 | 11945.3 | 489.3 | 275.6 |

The synthetic 489.3 ms call creates its first lazy device document; its repeated
device calls were 104.9 ms median. It contains 20,027,142 stored bytes. Process RSS
rose from about 113 MiB to 133 MiB for the sample and from 185 MiB to 446 MiB for the
synthetic run. These observations include fixtures, SQLite, validation allocations
and retained documents; they do not isolate cache allocation or establish a memory
ceiling. No fixture was regenerated.

Private receipts are `final-50.json` and `final-200.json` in this task's test-run
directory. Both bind the final API source SHA-256
`5fa4780aa0fa939561105871cca21a1e7c0b9a39e3fbe93f7c2c120925438c32`, all listed
source files, commit/diff identity and runtime versions. Subsequent documentation
updates do not change those measured implementation bytes.

The full local backend plus snapshot-binding and transition-custody selection
passed **1,357 tests / one existing Windows symlink-privilege skip** in 689.965 s.
Real Scope toolchain, hub-build and browser-markup prerequisites were required.
JUnit reports zero failures and errors. This is not a full repository Python-suite
or portable-candidate qualification claim.

The initial publication privacy gate refused untracked reviewer test databases in
this checkout and detected the candidate-set change when they were relocated.
All 70 evidence files were preserved outside the checkout and verified byte-for-byte;
none was staged. Rule 7's description is corrected to match the live verifier:
Git index plus stable working-tree candidates, including non-ignored untracked files.
The unchanged verifier and complete new-commit history scan must pass again before push.

The stable-tree privacy rerun passed at `ad2c0b3b`. Its complete three-commit
message/patch scan passed with zero matches across 83,113 bytes and 12 patterns.
Draft [#586](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/586)
now owns hosted validation. This documentation handoff needs its own fresh privacy
scan and exact-head CI before merge; the earlier failure remains recorded above.

## Closing evidence still required

- Required hosted repository, distribution, reference and portable checks.
- Repository privacy and complete new-commit message/patch scan before push.
- Every required hosted check green on the final PR head, followed by the
  authorized exact-head admin merge commit and tree reconciliation.

The canonical Graphify graph was used only for navigation. It belongs to the
protected main checkout, not this linked checkout; no graph refresh or claim of
current-tree graph coverage is made here.
