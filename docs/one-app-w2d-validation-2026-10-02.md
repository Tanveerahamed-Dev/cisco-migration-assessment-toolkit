# W2d: immutable snapshot projection performance

Status: published implementation remains held by a failed reference gate. A local concurrency correction passes independent verification; its uncontended timing confirmation is pending. This record does not claim
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

## Subsequent concurrency and hosted-gate findings

An additional 200-row device sweep at `b54a59be` covered all 23 sample hosts and all
device selectors, with three repeats each. Its repeated-call maximum was 186.2 ms;
first lazy device creation reached 342.2 ms. Those cold calls remain distinct.

A synchronized refutation then showed a cached core read waiting 414.4 ms behind
an intentionally held cold device producer. This proves unnecessary lock contention,
not a measured real-device build duration. The correction uses a short publication
lock for lookup/publication and retains the per-source builder lock only for misses.
No publication lock is held while waiting, binding, projecting or validating.
All **84 focused tests** pass. Independent replay verifies cached core/device and
other-snapshot reads during a held build, single-flight duplicate misses, exactly
one successful retry after a failed builder, and fresh HTTP 409 on source corruption.

The subsequent timing run missed the target under current conditions: maximum
1,281.9 ms, with an observed 87% host CPU load and other pytest/Node processes active.
It remains failed evidence. A controlled same-process comparison alternated the old
and corrected cache-hit methods over one warmed app: old median 1,035.7 ms / 906.3 ms
process CPU; new 964.5 ms / 835.9 ms process CPU. All eight 938,913-byte responses
were identical. This does not implicate the lock change, but high process CPU means
it does not uniquely establish scheduler contention as the cause. A quiet-host replay
of the corrected source remains required; earlier passing timings are not relabeled.

Required reference run `36985790137` failed during outer deployment-manifest
finalization after compression. Its public error is deliberately redacted and no
artifacts were retained. Cause is **unconfirmed** until the reserved read-only copy
reproduces it. The actual hosted source is merge commit
`a1bcc46d917a2279e0deaad1d6f66bdb25004935`; its Git tree equals `b54a59be`:
`ab6df5bff6ec218eb301fc20042eaccdfd0b1f36`. The expected compiler source-tree digest is
`cd1f6b30f3ecfca8adcc96845f4e22f089f706e67f488cdcbd0c8db98f3ab7c7`.
The copy contains no Graphify input, matching hosted coverage, and uses fresh compiler
and projection outputs. The cap and all verification gates remain unchanged.

### Exact-source reference diagnosis

The reproduction completed compiler census, schema validation (1,797 chunks),
projection generation (4,110 source modules), and Vinext compilation. Finalization
then failed at the same boundary as hosted CI. Invoking the unchanged internal
builder with its default hooks exposed `deployment member aggregate exceeds the
Sites expanded limit` at `digestPayload`, `deployment-manifest.mjs:1025`.

The preserved `dist` has **14,848 regular files / 260,505,355 physical bytes**, already
**458,507 bytes above** the unchanged **260,046,848-byte** repository cap, before an
outer receipt exists. Its compression receipt covers 14,785 modules, 1,378,692,627
original bytes and 250,453,066 compressed bytes; the compressed receipt itself is
1,320,013 bytes. Before/after counts and sizes match. The exact hosted merge and tree
remain tracked-clean. The private receipt is
`reference-a1bcc46d-private-diagnostic.json` in the external task test-run directory.
This confirms the local exact-source capacity failure; the hosted exception remains
redacted, so attribution of its same-boundary failure is a supported inference.

No generated fixtures, build outputs or unexpected dependencies entered the six-file
W2d source diff. Required content cannot be discarded to pass the cap. Available
Sites tooling and official Sites documentation expose no numeric deployment cap;
the plugin-submission archive limits apply to Skills, not Sites. A cap increase is
therefore not justified by current evidence.

The concrete fallback is a separately reviewed W6 change: retain the complete
offline projection and its digest ledger; move the hosted module family to an
immutable R2 namespace; preserve same-origin module URLs, exact-byte verification,
explicit missing-object failures and rollback to the prior namespace/version.
The available Sites tools have no object-upload operation, so actual migration
also needs a bounded private upload path, verified storage binding and a separately
approved deployment/bootstrap step. No R2 writes or deployment have occurred.
Moving this remedy ahead of W2d and implementing the proposal require an owner
decision because the requested sequence and fallback were explicit. W2d remains
unmerged; the cap and required gates remain intact.

### Later corrected-source evidence

A further sample-only, 200-row replay completed all 36 request shapes with five
repeats on tracked-clean `1a20b70d`, with unchanged API SHA-256
`416672bd23fbfdb1419282fefc0531d9d7750ac3a0c86687e3b91333d96aeb07` and the same
recorded interpreter/dependencies. It **failed** the 300 ms gate:
worst repeated request 2,648.3 ms (`findings_page`), worst later first request
2,122.5 ms (`findings:/rows`). Stable-response and source checks passed. The private
receipt is `post-reproduction-200.json`; its paired resource receipt records
88-93% CPU before launch and paging in the post-run observation. These observations
do not uniquely establish the cause. No synthetic run or immediate retry followed;
earlier passing measurements do not close this corrected-source timing gap.

Hosted reference run `37003241563` also failed on PR head `4a2671db`, from synthetic
merge `640c614a054d6d8d29f01640e5a8a57f6fd21f9e`. It passed 269 Node contracts,
validated 1,797 compiler chunks and built 4,111 source modules, then failed at the
same `node build/finalize-deployment.mjs` boundary with a redacted error. Its full
log and terminal run receipt are preserved externally. The earlier 458,507-byte
overage belongs to `a1bcc46d`; no byte count is transferred to this later source.

### Opt-in hosted measurement

The existing CI workflow gains a default-off `measure_projection_performance`
dispatch input and a separate Windows 2025 / Python 3.12.10 measurement job.
When enabled, `expected_source_commit` is mandatory and must equal both checkout
HEAD and the event SHA. Existing jobs remain unchanged; the measurement dispatch
has a separate concurrency group. No Node build or pytest runs on its measurement
runner. Canonical development dependencies and their installed versions are recorded.

The unchanged benchmark runs both profiles sequentially: all selectors/five repeats
at 50 rows for the sample plus 300-device synthetic fleet, then at 200 rows for the
sample alone. Each sample retains the 300 ms gate. Failure of the first profile
does not suppress the second, and either failure makes the measurement job fail.
Logs, exit codes, setup outcomes, source identity and receipts are retained through
an always-attempted artifact upload. This optional check is not a substitute for
any existing required check or for interpreting the measured result.

The ephemeral runner disables checkout newline conversion before checkout. Every
reported source hash is compared with both the expected commit's raw Git blob and
the working file; missing or malformed maps fail closed. Local Git configuration
and the benchmark/thresholds are unchanged.

Forty existing CI/platform policy tests pass. The first run had 39 passes and one
failure in `test_ci_owns_the_outside_checkout_installed_transition_smoke`: its parser
requires the installed-runtime job to remain last. Moving only the new job earlier
closed this without changing the guard. Independent review passed 21 simulated
identity/setup, failure/timeout, source-mutation and LF/hash/map/path cases. The
reviewer's initial test-double setup error is retained separately; it was not a
workflow failure. YAML, inline Python syntax, existing action pins and unchanged
existing-job mappings were checked. Actionlint was unavailable. These checks
preceded hosted execution; the results below retain the local timing failures.

### First hosted measurement result

The opt-in job ran on exact commit `492e42843f76a22711ef49d575471b627f3b601a`
in dispatch `37009338445`, attempt 1. Setup and source checks passed; both benchmark
profiles completed and the measurement job failed its unchanged 200-row timing gate.

| Profile | Cold complete projection ms | Largest repeated call ms | Result |
|---|---:|---:|---|
| 23-device sample, limit 50 | 670.4 | 164.4 | Sample warm gate passed |
| 23-device sample, limit 200 | 669.9 | 406.8 | Sample warm gate failed |
| 300-device synthetic, limit 50 | 17007.6 | 371.1 | Measured; no synthetic latency gate |

The 200-row Findings median was 358.0 ms; its first list call also exceeded 300 ms
at 394.8 ms. The synthetic fleet's first lazy device call was 799.9 ms. These are
sequential ASGI measurements, not browser/network or concurrent-load results.
The runner used FastAPI 0.142.2, Starlette 1.7.0, Pydantic 2.13.5 and jsonschema
4.26.0. The first three differ from the local runtime; do not attribute all differences
to workstation contention or claim timing for the portable pinned environment.

Independent verification matched the exact artifact ZIP digest, all 15 extracted
members, all 11 source hashes against Git blobs, both clean source identities,
both stored fixture digests, and 36 request shapes with five repeats per profile.
It recomputed medians/maxima and confirmed the failed job verdict. The private
receipt is `hosted-492e4284-independent-review.json`; the artifact is retained under
`hosted-492e4284-run37009338445-attempt1` in the task evidence directory.

A bounded local profile then reproduced the exact 938,913-byte Findings response
and actual HTTP bytes without source changes. One schema validation performed
40,190 child-validator/resource constructions and 40,265 descents. Instrumented
CPU attributed a material share to `evolve`, resource construction and subresource
setup; these instrumented values are not acceptance timings. Construction reuse is
the next in-scope optimization; all per-response validation must remain active.

Independent baseline probes also found five private-compiler schema/context
mutation cases that diverged from stock validation: direct-reference type/constraint
changes, replacement of a discriminator branch's required list, and evolved format
checker/resolver contexts. These are synthetic private-helper probes, not observed
production HTTP faults. The baseline is preserved as
`constructor-mutation-baseline-492e4284.json`. The construction optimization must
close these ownership/context assumptions as well as retain every response check.

### Construction reuse and workflow corrections

The compiler now fingerprints the caller's schema once per external validation and
keeps an unexposed copy for optimized validation. A bounded, eagerly constructed
table retains child validators with their exact initial context. Runtime reads use
a read-only strong-identity map; unknown/evolved objects fall back. Proven resource-free
descents pass the existing resolver through the stock descent implementation.
Every keyword and response validation remains active; validation outcomes are not cached.

Schema changes and unsupported fingerprints use fresh stock validation. Public
`evolve` delegates to stock validation with the requested context. Private validation
failures/exceptions are replayed through stock validation so errors cannot expose
cached schema aliases. Direct context-attribute assignment is explicitly unsupported
by this private facade; callers use `evolve`. This is not a claim of identical mutable
Draft-validator object APIs. The five baseline schema/context mismatches are closed.

Final API SHA-256:
`7c9226a594d3c53aeed1ab99a1efe3ca411ad6ff96ae479b34c6f2610222d537`.
All 99 focused API tests pass. Independent review passed 17 mutation/context/identity
groups, including 400 concurrent calls, bounded ownership and zero runtime private
constructor/registry writes. A fresh final-source replay passed the 73 reference/error
cases, dynamic/resource fallbacks, concurrent error validation, full-sample/off-page
corruption checks and all five warmed HTTP corruptions with valid retry. Earlier
probe assumptions and earlier-source passes remain separate records. API generation
also passed all nine policy checks and exact equality with the actual application schema.

The bounded final profile preserved the exact 938,913-byte HTTP response and all
40,265 stock descents while removing the 40,190 repeated child-validator/resource
constructions. Its local instrumented/CPU timings are diagnostic; a fresh hosted
measurement remains required before claiming the 300 ms target.

Published `492e4284` CI exposed a workflow-format conflict: all six Python jobs and
Coverage failed the literal hosted-runner policy because the optional job quoted
`windows-2025`. Unquoting preserves the same runner. The first local rerun then had
32 passes/eight failures because a mutation test counted that runner globally.
Its marker/count/replacement is now scoped to the uniquely named installed-runtime
job. All eight rejection cases and production guards are unchanged. Forty-two policy
checks pass; independent decoy/missing/duplicate-owner probes also pass. The quoted
runner failure and the intermediate 32/eight result remain preserved. New-head hosted
CI must verify both corrections; no previous failed run is relabeled.

### Owner-directed W6 prerequisite and runner selection

The owner now requires W6 before completing W2d, then main merged into #586 before
new CI/measurement and a green-only merge. W5/#582 and W8/#587 remain with their
owning session. The reviewed construction correction is retained locally at
`bce1d47a`; its publication scans passed, but it was not pushed before this decision.

The measurement job now selects only `windows-latest` through a fixed, single-value
`matrix.os`. This is the existing runner-policy test's supported selector form;
neither the test nor any production guard is changed. The exact runner-policy test
and all eight installed-runtime mutation cases pass. An initial direct-literal
`windows-latest` attempt failed that literal allowlist, and a broader selection also
hit the existing one-second smoke-start/output assertion; those results are retained
and no full rerun pass is inferred. No new measurement is dispatched before W6.

### W6 merged and main integrated

W6/#588 merged as `0577aaf5` after all 15 required checks passed on `1080bfa5`.
The merged-main tree equals the tested tree. Its exact-source hosted reference
build finalized 260,145,929 physical bytes above the former 260,046,848-byte
aggregate quota, then passed all rendered and artifact-family/PDF receipts.
The internal-reference fix preserves integrity/privacy/resource bounds and does
not establish hosting eligibility.

Current main is merged into this W2d branch. Only the board conflicted; its full
handoff history is retained. The final reviewed API hash above is unchanged,
as is the fixed GitHub-hosted `windows-latest` measurement selector. Earlier
measurements retain their own source scope. Fresh privacy/history scans,
publication, hosted sample/300-device measurement and all required CI still
must close on the resulting head before the authorized merge.

### Second hosted measurement and remaining traversal cost

After W6, main was merged and `2a50978a4f8ae376aafaeef8cfc35b6ce982a65f`
was published with fresh repository/history/body privacy receipts. The exact runner
guard and eight installed-runtime mutation cases passed on that integrated tree.
The runner-security owner is byte-identical to main.

Dispatch `37046103736` used the exact reviewed API hash above. Its measurement job
`110967825775` failed the unchanged sample gate. Artifact `11244541464` has ZIP
SHA-256 `9fde990250bc3c7f8f62750962be96e27e704003b1bd6536847b186e60c90b34`.
Independent verification closed all 15 members, 11 source hashes against raw Git
blobs, fixture identities, 36 request shapes and five repeats per profile.

| Profile | Cold complete projection ms | Largest repeated call ms | Result |
|---|---:|---:|---|
| 23-device sample, limit 50 | 726.2 | 192.9 | Snapshot-warm maximum 192.9263 ms passed |
| 23-device sample, limit 200 | 723.4 | 436.7 | First Findings list 445.9400 ms failed |
| 300-device synthetic, limit 50 | 17831.5 | 361.4 | Diagnostic; first lazy device 831.2178 ms |

The 200-row Findings/list/page medians were 365.1541, 371.9375 and 354.3264 ms.
Other 200-row sample responses stayed at or below 121.402 ms. All 108 response
byte counts and SHA-256 values match the earlier hosted artifact; the benchmark
driver is unchanged. Hosted Python was 3.12.10 with FastAPI 0.142.2, Starlette
1.7.0, Pydantic 2.13.5 and jsonschema 4.26.0. These measurements do not establish
timing for the portable pinned runtime or a causal difference between runners.

A fresh external environment matches all 80 hosted third-party versions. A bounded
profile preserves the 938,913-byte response and finds one field validation and one
schema-facade call. In an instrumented HTTP request, the schema walk used 418 ms of
509 ms overall; page copying used 39 ms, JSON-native checking 15 ms and serialization
5 ms. The schema's 9 ms fingerprint is included in its schema cost. These are
diagnostic shared-host measurements, not additive phase accounting or acceptance.
The schema profile still executes 40,265 stock descents, 40,190 evolve-wrapper calls
and 1,644,040 calls overall, despite reusing validator construction.

The bounded next change reuses private retained validators' precomputed rule lists
during descent. Every stock keyword constraint remains evaluated; unsupported
contexts/resources retain stock descent and the existing facade replays all public
failures through fresh stock validation. Private relative errors are not exposed.
Review rejected a child-probe-then-stock-retry approach because invalid nested
subtrees could be repeated recursively. Its valid-payload-only diagnostic remains
separate evidence and is not the implementation or an acceptance result. Focused
negative-depth/parity tests, independent review and a new hosted run must close the
actual direct-reuse correction before any performance success is claimed.

The direct-reuse candidate has API SHA-256
`5573a2a5eb6e607e1058acb095116e7d6a3fce839486900a59a27ad6829d9c6c`.
All 105 focused API tests pass in the hosted-matched environment, including six
new semantic/complexity regressions; Ruff and diff checks pass. The first targeted
run had five passes and one instrumentation failure: Python's profile hook counts
generator resumes as calls. Counting strongly retained frame entries corrected
that measurement while preserving the linear bound and production code; all six
then passed. Independent refutation/profile results and hosted acceptance remain
pending for this candidate.

Independent review then confirmed a separate repeated-work defect in the existing
unique-discriminator `oneOf` failure path. Nested invalid alternatives at depths
2/4/6/8 performed 18/70/266/1,038 type evaluations, versus stock's 5/9/13/17.
The published `2a50978a` helper has the same counts, so direct descent did not
introduce it; it is nevertheless part of this W2d helper and must be corrected
before merge. The bounded correction is to propagate the uniquely possible private
branch's errors once and retain the existing complete public-stock replay, instead
of checking that branch and then retrying it through `oneOf`. The corresponding
linear-work/error-parity regression now covers both invalid property chains and
unique-discriminator chains at depths 4/8/12. Ordinary, non-generator keyword
wrappers count actual invocations; they avoid delayed generator resume/close events
that made the earlier profiler-based counters unreliable. The original linear
bounds are unchanged and all intermediate instrumentation failures are preserved.

The combined direct-descent/unique-branch correction has API SHA-256
`215c97cd62b8e52eb4c437cf5359ab82f69f52a7dcb63055dd3e6c465ac0572a`.
All 106 focused API tests and 16 targeted checks pass in the matched environment,
with Ruff and diff checks passing. Independent keyword counters confirm linear
work through depth 20 and exact public diagnostics: the unique-alternative case
uses 26 type checks at depth 8 (previously 1,038; stock 17) and 62 at depth 20.
Fresh hosted performance acceptance is still required; local profiles do not
establish the target.

The final independent replay also closes 17 ownership/context groups, 73 reference
cases, 200 concurrent validations, off-page faults and five warmed HTTP corruptions
with valid retry. The response remains exactly 938,913 bytes with SHA-256
`b8d65bdd018f5f90cd2023e8e03c05bbd394b6454c86ce4dd2ecbd6ed4feb022`.
The final schema profile contains 1,221,774 calls; local schema/field medians were
307.5/353.7 ms. Two HTTP observations were 600.5/514.8 ms, so this shared-host
diagnostic proves neither the target nor a reliable regression. The published
hosted failure remains the open acceptance result.

A separate isolated feasibility trial can assess a maintained compiled validator,
with offline retrieval and conservative eligibility before native acceptance.
Every response still needs complete schema, JSON-native/finite, Pydantic and
pagination validation; public errors must retain stock behavior. No production
dependency or portable lock has changed for this trial. Differential semantics,
offline refusal and frozen-runtime packaging must be established before adoption.

### Guarded native response validation (integration in progress)

An isolated trial at `3b286f6f` used `jsonschema-rs==0.58.4` with the same matched
CPython 3.12.10 environment plus a separate target installation. The original
80-package environment and source stayed unchanged. The Windows wheel SHA-256 is
`803612a214ce5ccb2ceefe87b3cab4711a7d04694479b5a22f82cb509635d9cc`;
all RECORD hashes/sizes and the AMD64 native member were verified.

Three paired HTTP observations per endpoint preserved exact response bytes:

| Endpoint | Python median / maximum ms | Native median / maximum ms |
|---|---:|---:|
| Findings, 200 rows | 448.3 / 480.7 | 176.4 / 295.1 |
| Findings list, 200 rows | 468.1 / 894.4 | 194.0 / 199.5 |
| Overview, 50 rows | 36.5 / 42.0 | 33.7 / 34.6 |

These are shared-host diagnostic observations, not acceptance. An untimed census
confirmed one native call per validation for all three identical bodies. The
prototype retained store authority, JSON-native/finite, Pydantic and pagination
checks and compiled each unchanged schema once; it cached no validation outcome.

The selected implementation initially accelerates only HTTP view/list transport
validation. Native acceptance requires the explicitly audited, unchanged schema
profile and exact JSON builtin values: integers within plus/minus 2**53-1, no
floats, cycles or depth above 128, and no CR/LF/U+2028/U+2029/surrogate characters
in keys or strings. Unknown schema features, contexts, mutations and unsupported
values must enter Python before native acceptance. The two audited patterns and
local reference closure are fixed; future schema expansion requires re-audit.
The native constructor uses `offline=True`, disabled formats and the pinned
provider. Python fallback uses a closed registry so unknown or mutated HTTP/file
references cannot trigger retrieval. Public errors retain Python-stock behavior.

The 155 differential probes found eight differences involving NaN, floating
multipleOf, surrogate strings and trailing-newline regex behavior. Those cases
are excluded before native acceptance, not excused after a native success. Nine
additional tests on actual Overview facts prove that deleting either paired
engine_state/engine_state_owner field alone fails in both validators; deleting
both remains valid under the unchanged schema. Exact public errors match. These
bounded checks are not a claim of universal equivalence between implementations.

The wheel has no embedded license text. Its pinned upstream MIT file has SHA-256
`117829c3ca21efb132d81a44b55363d395ab8eea18526873bc828da4c0e5f038`.
Its supplied 203-component CycloneDX document has SHA-256
`fc02e97118764c2c8e0e67bc1f0fc554cda259a4925e944677894d0792cf6a88`.
Portable integration must retain that metadata and exact native member custody,
embed the reviewed MIT fallback and reconcile the dependency lock/inventory.
The upstream SBOM supplies declarations, not license texts or independent proof
of which components were linked. The existing notice inference boundary remains.

The smaller fastjsonschema alternative is not selected: direct compilation drops
the current dependentRequired constraints and changes regex handling. It would
require an additional restricted schema adapter. The chosen full-draft path must
still pass production parity, source/distribution, frozen native HTTP, privacy,
supported-Python and unchanged hosted performance gates before merge.

The initial local integration has API SHA-256
`1b25bf3f2fae770804d4b659e5bc75bf4fba5a937d934082778bf31f5987c565`.
All 112 API tests and 21 targeted checks pass, with Ruff/diff checks passing.
Coverage includes pre-acceptance eligibility, pinned provider/schema checks,
owned-copy and public-schema replacement races, offline default/evolved modern
and legacy contexts, paired fields, stock diagnostics and per-request smoke
isolation. A detected stale pre-native schema decision was corrected by refreshing
the identity/fingerprint after native success, failure or exception. The frozen
smoke proof requires its explicit mode and one matching nonce, a real native
acceptance, completed model/pagination validation and a successful response; it
is absent in normal mode and on fallback/failure. Final independent, packaging,
frozen-build and hosted results are not yet established for this integration.

Owner approval for pinned `jsonschema-rs==0.58.4` and the designed fallback,
private-version guard and lock/notice/SBOM custody was explicitly relayed in chat
on 2026-10-03 (owner decision dated 2026-10-02). The dependency hold is lifted.
The exact-head required checks and unchanged hosted 300 ms gate still govern merge;
release publication, signing and deployment remain separate authority.

The requested private-import guard now checks the explicit reviewed jsonschema
version `4.26.0` before lazily importing or using `_RefResolver`. Missing metadata,
version drift, a missing/import-failed symbol or a non-class replacement fails
closed; supported in-memory legacy contexts retain remote denial. The final API
SHA-256 is `1d96342cb543d74994d42b6ac75b01c64484ed1cfa144de8e3acc6233cd4bede`.
All 119 API tests, ten targeted private-guard tests, Ruff and diff checks pass.
Actual OpenAPI export remains byte-identical (682,511 bytes, SHA-256
`7c1240ee7338740f182510435e74aa6563525670db7a00bedf862216d231c333`),
as do generated TypeScript types (389,699 bytes, SHA-256
`2481934ef8985911166ad57ae8a013d6cfe2d289fc813f13f712c1025c73d7eb`);
the nine generation-policy checks pass. The local full suite took 462.43 seconds
under observed host resource pressure; this is correctness evidence, not latency
acceptance. Final packaging/filter review and hosted frozen/performance gates
remain open.

Final local packaging validation passed 253 tests with nine explicit platform/tool
skips (one POSIX FIFO, one Windows symlink privilege, seven unavailable bash
verify-green cases), followed by eight final private-guard/metadata-filter checks.
No native-related check was skipped. Independent delta review refused five
unreviewed/missing versions before private import, four non-class symbols and
missing/import-failed private interfaces, while preserving supported in-memory
contexts. Metadata refutations removed 32 installer-path variants, retained the
12 required/upstream/unrelated rows and left inputs unchanged. Required native
metadata remains exactly METADATA/WHEEL/upstream SBOM; jsonschema's upstream
metadata/license is retained while installer provenance is excluded. These final
delta receipts supplement the earlier source-bound native/reference/HTTP review;
they do not transfer old-source timing or claim a frozen build.

All final local worker/reviewer processes are terminal and no source finding
remains. The canonical hosted Windows job, rather than a competing heavy local
build on the memory-constrained workstation, will establish the committed-source
asset, executable, actual-native HTTP and private-version proof. The unchanged
hosted benchmark must separately establish both sample page-size gates.

## Final W2d closure — 2026-10-03

W2d merged in [PR #586](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/586)
as `828847f14c908fa7b725fe97fdff9cee5f115178`. All 15 required contexts from
GitHub Actions app 15368 and all six latest applicable workflows passed on
`18fac335e76cdeab530203bebfc9cd6a489e857f`. The exact-head admin merge used the
owner's standing authority; branch policy was not changed. Merged-main tree
`179710d24c3eb11772d6223bbae4ec252deab155` equals the tested head and PR merge tree.

The unchanged [hosted performance gate](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/37067520985)
passed with sample maxima of **91.8337 ms at 50 rows** and **143.6550 ms at
200 rows**. Independent review bound all source hashes and 36 request shapes with
five repeats per dataset. All 108 response sizes/hashes equal the earlier failed
`2a50978a` hosted baseline. Artifact 11252693973 is 25,084 bytes, SHA-256
`20dac193fd3631cc26efffc5612057bdc8240581dc4c37c97726adf639a70166`.
Sample cold Overview remains outside the existing gate (444.2991/446.7840 ms).
The synthetic 300-device profile is diagnostic: 104.3249 ms repeated maximum,
577.1617 ms first Device and 10,193.1427 ms cold Overview. These distinctions and
all earlier failed measurements remain part of the record.

The [portable workflow](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/37067501879)
passed both the full source/frontend gate and real Windows binary build. Its
producer is the tested PR merge `875847749cc665e868487881028edf576fa45238`, whose
tree equals the approved head. Independent review rehashed all 860 runtime members
and eight receipts, checked the pinned native binary/MIT/upstream SBOM custody,
and confirmed two frozen native/private-version HTTP smoke runs. Artifact
11253677200 is 51,629,250 bytes, SHA-256
`56269770950bfb48a0aa21d454c2544dac1999181ca537f7d757279e8fa0142d`.
It remains unsigned with 14 external qualification gates pending; its supplied
203-component native SBOM is still an upstream declaration, not legal or linked
component closure.

Publication followed terminal stable-index/working-tree privacy verification,
all 14 new commits and 16 parent-relative patches (791,721 bytes, zero marker
matches), and a separate PR-body scan. The first same-head webapp run was
automatically superseded after the PR-body update; its cancellation and failed
dependent checks remain preserved alongside the successful replacement. A local
review parser's editable-install assumption was also corrected without changing
the benchmark. No CI rerun or cancellation was used to discard negative evidence.

This closes W2d at the exact source above. Its receipts do not certify later W2e
schema or feature changes, which require their own validation and hosted gate.

The canonical Graphify graph was used only for navigation. It belongs to the
protected main checkout, not this linked checkout; no graph refresh or claim of
current-tree graph coverage is made here.
