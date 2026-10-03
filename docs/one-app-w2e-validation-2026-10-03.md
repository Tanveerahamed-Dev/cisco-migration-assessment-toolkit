# W2e: Topology & Paths validation

Status: PR #591 is published at `998fa5ff`. Local integration and the exact-head
hosted performance gate passed. Full hosted checks exposed the concrete failures
recorded below; integration repairs and the dependency decision remain open.
W2d merged as `828847f14c908fa7b725fe97fdff9cee5f115178`; its receipts
do not certify this changed source.

## Contract and source custody

The fifth core screen consumes the engine's `Topology` projection and separate
`PathDocument`. The engine owns node/cable/structural-link/impact/address facts,
states, evidence joins, limitations and visual descriptors. Stored host-pair
centrality is separate from physical cable redundancy; uncollected and ambiguous
records remain visible. Address suggestions are positive observations, not a
management-address or unique-source assertion.

Path investigation delegates to `fib.trace_fib_path` with the disclosed result,
32-hop bound and no requested MTU. It preserves all 14 owner result fields,
including dropping ECMP legs, candidate sets and MTU limitations. Computed-hop
evidence references actual stored rows; it does not invent snapshot `/path`
pointers or infer physical cables from host pairs. No route observation, an
observed discard and a reaching path with dropping alternatives remain distinct.

Every request rereads authoritative stored bytes. The cache admits the complete
main document before selection; a path query receives a private source copy and
runs after cache locks are released. Query results are not cached. A separate
Python-only path response model validates the full result, exact query echo and
engine context. Its identity and global limitation registry match the topology
view. JSON-native/finite, Pydantic, complete-schema and applicable pagination
checks remain in place.

The existing Atlas Scope hub gains an early contract mode, selected before its
ordinary dataset/analysis boot. The shared protocol binds version, mount nonce,
exact origin/window source, all four stored-identity fields and a canonical
SHA-256 digest of engine/limitation metadata. Each renderer fetches facts from
the guarded API; cross-frame messages supply coordination, not substitute facts.
The digest compares context and does not authenticate code or qualify a network.
Actual same-hub browser evidence is recorded below, separately from mocks and
the required final-source hosted checks.

Scope capability is additive to the existing legacy link and requires one exact
supported declaration in the validated startup shell. Missing, duplicate,
unsupported or withdrawn capability cannot enable the iframe. Capability reads
use `no-store`; a renderer/resource refusal leaves the 2-D/evidence surface.
Interactive rendering/assembly limits disclose their scope and retain paged
evidence; they are not source-artifact or network-size assertions.

## Native schema delta review

W2d's reviewed provider, `jsonschema-rs==0.58.4`, and private-interface guard for
`jsonschema==4.26.0` are unchanged. This review changes only the two literal
transport schema fingerprints:

| Profile | Reviewed W2e SHA-256 |
|---|---|
| View | `b7f82b857a91771f933c0487eb687327354fe49612c7ef2c16f17455fed3f3b7` |
| List | `b9dc903eb0fa6a07379c4bcf6b83f44a8a1a8ed90f4295c0ab55aa819fe56c8d` |

The complete delta adds 47 definitions and changes only `LimitationId` and
`Trust` among existing definitions. Independent inspection/recomputation found
no new schema keyword, regex pattern, resource/dialect feature or unresolved
reference. All references remain direct local definitions. AST comparison to
W2d confirms that native eligibility, hashing, provider selection and the
validation/fallback facade are unchanged.

The bounded differential experiment captured 53 actual HTTP responses and made
146 eligible direct native-versus-closed-Python comparisons: 84 accepted and
62 rejected, all matching. Sixteen unsupported cases stayed on Python: six
float-bearing cases, one unsafe integer, two non-JSON values, five unsafe-string
cases, one depth case and one cycle. Three schema-valid but inconsistent page
metadata cases still failed the full response model. Source/provider bytes were
stable; production pins remained unchanged and native-disabled during the
experiment. Receipt SHA-256:
`94e4e029fb97e0fe909925e5237e3ca5c72ecee1b69320822c3cc13355e74f36`.

An independent reviewer inspected both the complete delta and the experiment's
source/receipt before recommending the explicit literal pin update. The static
review receipt has SHA-256
`91333d97610e7f03f658e048c595889de3051140923c58df4a7e6853616d5fa4`.
This is bounded equivalence evidence, not a claim that two schema implementations
are universally equivalent. Public error preservation also relies on the
unchanged Python fallback and its retained regression suite.

The admitted domain remains exact JSON builtins, safe 53-bit integers, no floats,
cycles, excessive depth, CR/LF/U+2028/U+2029 or surrogate strings. Actual sample
topology views and structural-link lists contain floats and use Python unchanged.
Other eligible topology lists may use native validation. Path responses remain
Python-only. After the literal pin update, the full 143-test API suite passed,
including actual nonce-bound native proof for node/cable/impact/address lists and
absence of native proof for float-bearing topology/structural lists and paths.
Unsupported data is never coerced to gain native acceptance.

## Focused evidence and retained failures

- The first engine run passed 30 cases and failed one: a malformed cable-map
  parent was labelled absent. The next run passed 36 and failed eight because
  new hostile numeric paths lacked explanatory slot labels. Both failures were
  corrected and their logs retained. A subsequent 44-case run passed.
- Later source review corrected blank node classifications, blind-device
  witnesses/precedence, malformed summary-source lists and malformed route-source
  tokens. These preserve schema shapes. The 62-case replay passed, including the
  existing main-document limitation-pointer invariant.
- The first four-suite projection regression passed 568 tests and failed six.
  Five failures correctly detected a missing topology location in the existing
  one-hop-failure caveat. The sixth exposed the owner's existing eight-example
  failure-impact prose limit. The correction adds the caveat location, retains
  complete counts and verbatim prose including its `+N more` suffix, discloses
  the eight-example summary scope, and registers that exact reviewed prose
  exemption. A real 10-VLAN producer fixture proves ten in the full counts,
  eight prose examples and `+2 more`; no producer/golden/sample was changed.
  The cap walk now explicitly includes `fib.trace_fib_path`. All seven targeted
  correction cases passed; the complete four-suite replay then passed all 574
  tests in 281.00 seconds. Existing 30-second projection and 5-second device
  assertions passed unchanged. The original 568-pass/six-failure receipt remains.
- Thirty-three targeted API checks passed before the last engine-only honesty
  corrections. The subsequent full API suite passed all 143 tests in 375.38
  seconds on the reviewed pins before the final engine limitation-text/location
  corrections (which preserve schema shapes). It covers authority, complete
  source admission, query/context mismatch, copying, retry, concurrency, the
  separate path model and retained native/private-interface regressions. A
  FastAPI test-client deprecation warning remains an environment warning.
- Ten Scope capability checks passed, including declaration versions/duplicates,
  absent/legacy hubs, current privacy withdrawal and `no-store` behavior.
- Full Scope typecheck passed, followed by 63 focused cases in nine files.
  A first unused-import typecheck failure is retained. Independent review found
  that initial renderer failure could allocate again after disposal; initialization
  now propagates that failure to cleanup and refuses updates after disposal.
  Its regression passed. Source-bound peer review is closed; it does not replace
  real browser/WebGL or production-build verification.
- The complete local Scope run exposed three adapter property-inspection sites
  that must use `core/own.ts`, plus the committed-source guard's refusal of the
  new files absent from HEAD. The known-failing run was deliberately stopped,
  preserving 46 passing files, four known failures and 182 unfinished files.
  The adapter now uses the unchanged safe-access helper, with descriptor checks
  still refusing getters. Full typecheck and 188 focused cases passed (122
  unchanged access-guard cases and 66 adapter/legacy-entry cases). After the local
  checkpoint, all nine committed-source guard cases passed. The full exact-head hosted Scope suite remains
  a mandatory merge gate; a focused pass does not close the cancelled full run.
- The initial focused frontend batch passed 69 and failed two handshake cases.
  Synchronous listener registration corrected the missed-ready condition. The
  final focused batch passed 82 tests, and 21 API-client checks passed. Typecheck
  passed. The initial failed batch remains a diagnostic receipt, including its
  concurrent shared-protocol source correction.
- The complete frontend run then passed 365 and failed five old Scope-link
  fetch-argument expectations. The client intentionally requires `cache: no-store`;
  updating those five exact expectations preserved every link rendering, refusal
  and withdrawal assertion. The complete replay passed 370 tests in 32 files.
- Independent client review found trailing-line-terminator digest/nonce/request
  admission, shared mutable assembly/progress values and duplicate row identities.
  Strict guards, owned/frozen values and per-list `(index, pointer)` uniqueness
  now have focused counterexamples. Distinct address observations may share a
  source-container pointer; they are not deduplicated by pointer alone.
- Initial actual OpenAPI export was 819,638 bytes. Generated TypeScript SHA-256
  is `bf35b81a801f83e5935bc6c998fd9982712528cb3c62719c2045eaa253ca4581`.
  The final actual export at `090c3bc0` passed all nine generation-policy cases
  and byte-for-byte TypeScript equality. Scoped Ruff also passed.

Local Node 24.19.0/npm 11.16.0 were acquired to an external task directory, with
the signed Node checksums and pinned archive/executable/npm hashes verified.
The first Git gpgv call rejected an absolute Windows keyring path; the preserved
retry used a relative path and verified the clear-signed checksum output. No
global installation or machine PATH change was made.

Workstation memory briefly fell to about 80 MiB while other Scope worktrees ran
Vitest. Heavy local checks paused, unrelated processes remained untouched, and
checks resumed serially after recovery. Local timings under contention are not
performance acceptance.

## Production builds, browser evidence and presentation correction

The pinned frontend production build passed with 491 modules and 79 unchanged
inputs. Three actual-Chromium frontend integration cases passed against synthetic
HTTP responses and a mock child window; these prove parent behavior and refusal,
not genuine Scope rendering.

The actual hub build at `a40f59ee` passed with 18 files, 2,026,805 bytes, both
required declarations exactly once, no source maps or active source-map URLs,
and unchanged source inputs. A fresh loopback backend served the committed sample,
the tracked frontend build and this real hub. An independent browser probe passed
at desktop and mobile sizes with no substituted responses or forbidden raw,
graph or dataset requests. Both clients reconciled 26 nodes, 44 cables, 25
structural links, 23 impact rows and 33 addresses; complete identity/context,
selection, path-result equality, clear and teardown checks passed. Actual WebGL2
pixels were observed in both sizes. The observed route result was
`computed:reached`; this describes the sample computation only.

Screenshot inspection nevertheless found overlapping labels and insufficient
graph coverage. The bounded correction at `090c3bc0` changes camera fitting and
shows one hovered-or-selected label, preserving node positions and every engine
fact/join. The first framing run passed 190 cases and failed the unchanged 60%
coverage assertion (59.9666%). Tightening the camera margin corrected production
behavior without relaxing assertions; all 191 focused cases then passed. An
additional resize/user-navigation/Reset test passed with all eight final scene
cases, and final full typecheck passed. Independent source review is clear.
The fresh hub build and unchanged real-browser probe at `090c3bc0` then passed
for desktop and mobile, preserving all five censuses, painted WebGL, bidirectional
selection, complete path equality, clear/teardown and zero forbidden requests.
Root screenshot inspection confirmed readable framing without overlapping labels.
The earlier functional pass and its visual defect remain in the evidence record.

The local 42-shape sample diagnostic at `a40f59ee` used five repeats and page
limit 200. Its maximum was 434.1103 ms (first Device); topology's first request
was 365.1393 ms and repeat median 244.0536 ms. This does **not** meet the unchanged
300 ms acceptance bound. The log is retained; the final exact-head hosted gate
at both 50 and 200 remains decisive and must pass. Float-bearing responses stay
on Python. Neither the accepted input domain nor the threshold is widened.

## Remaining delivery gates

The Scope owner subsequently merged #582 as `e50c3cde`. Its stricter shell reader,
engine vocabulary and complete bundle dependency custody are integrated before
publication. Earlier local results remain source-scoped. The combined source's
fresh hub build and real desktop/mobile probe passed with the same complete
censuses, path equality, painted WebGL, selection and clear/teardown checks,
and zero forbidden requests. Root reviewed the fresh screenshots. The obsolete privacy run was
intentionally stopped, and the history scan refused the base movement; neither
is a passing publication receipt.

The combined source keeps the new shell/CSS refusals and adds the capability
declaration through that same reader. A non-ASCII long-s counterexample first
failed (two passed, one failed); matching now uses the owner's ASCII rules.
All 25 selected capability/mount checks passed. Upstream health-band membership
also exposed an unhashable list/dict regression: the old owner returned
`analysis_unavailable`, while the incoming set lookup raised `TypeError`. A
string guard restores that behavior; ten malformed/valid-band cases passed.
Explicit native-profile recomputation confirms the same two reviewed hashes;
no native eligibility, provider or schema-pin change was needed.

The new package module recorder correctly refuses arbitrary outside-project
code. W2e shares one protocol source between the two frontends, so its integration
adds only `atlas-scope/dist-hub` to
`webapp/frontend/src/projectionEmbed.ts` as an explicit first-party relationship.
The source must be committed, regular and free of reparse indirection; its size
and hash are checked around recording/attribution, alongside the unchanged
rebuilt-output equality check. Unknown siblings, outside npm code and unbound
shared-source claims remain refused. This changes no dependency denominator.
Independent review found that status/diff alone can miss modified bytes hidden
by Git index flags. The correction compares the observed raw bytes directly to
the committed HEAD blob. All 22 focused cases passed, including actual
`assume-unchanged` and `skip-worktree` counterexamples; Ruff and diff checks passed.
The real module-recording rebuild remains a separate integration proof.

That real rebuild subsequently passed at `998fa5ff`: all 18 shipped hub files
(2,034,979 bytes) reproduced exactly; the single 12,743-byte shared protocol
module matched committed source. The two additional bundler-runtime packages
were the existing reviewed Rolldown 1.2.9 and Vite 8.2.1. No new dependency
inventory or licence denominator was introduced.

## Hosted results at `998fa5ff` and open corrections

PR #591 was published after full index/working-tree privacy, complete history
and PR-body scans. The raw history scan retains matches in the generated vendor
chunk; independent review applied only the existing owner's minified-identifier
exclusion, retaining all other patterns. All four new commits and five complete
parent patches (9,980,610 bytes) were accounted for; no scanner or source history
was weakened or rewritten.

Performance run `37093209993` passed. Independent verification of artifact
`11262998230` rehashed its 28,466-byte archive (SHA-256
`cd0bfd67b354e1cc878f44520af6befd657c37fc9bacc369d8260bbace3f4bf7`),
all 12 source inputs, all 42 request shapes and five repeats. The unchanged
300 ms sample gate measured a worst request of 208.8909 ms at limit 50 and
189.2650 ms at limit 200, both topology. Source identity and response integrity
checks passed. The earlier local 434.1103 ms miss remains source-scoped evidence.

The synthetic 300-device case contains 20,100 interfaces and 9,000 endpoints,
but its topology still has 26 nodes: device count is not topology coverage.
Its 503.4631 ms first Device, 299.9603 ms repeated maximum and 10,725.58 ms cold
load remain diagnostics. Sample path repeated maxima were 60.272/62.971 ms;
the synthetic path diagnostic was absent because the first address page did
not supply two published choices. No result is transferred to subsequent edits.

Full hosted verification exposed these additional failures, retained in full:

- Scope run `37092710421`: six failed assertions in five files, 7,250 passed
  and 27 skipped. Focus custody, the initial-payload census, explicit mock
  classification, test-support placement and wrapping policy need correction.
- Reference run `37092710427`: exact-tree compilation refuses 15 undeclared
  static imports from Scope to frontend protocol/type/test-fixture owners.
  The correction must be exact-file declarations, retaining forbidden-edge
  precedence and refusing unlisted callers or production fixture use.
- Python 3.13 job `111116240939`: three failed, 10,569 passed, 153 skipped and
  one expected failure. One portable shape must use its existing declaration;
  two projection receipt-interpretation proof guards must be resolved through
  their owner contracts. Other matrix results are tracked separately.
- Required Dependency audit: one affected Master Reference braces chain yields
  six high findings under [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm).
  No patched upstream release is listed, and the latest vinext retains the chain.
  The owner assigned its remediation to W11 in the Claude Atlas Scope session,
  branch `claude/master-ref-bounded-braces`, and explicitly declined duplicating
  it in #591. Merge current main after W11 lands, then rerun #591's gates.
  No dependency patch, suppression, forced downgrade or package relabelling
  is applied in this workstream.

These failures prevent merge despite the timing and webapp passes. Final repaired
source requires fresh exact-head checks, the full Scope run and the unchanged
hosted performance gate; W7 follows only after the authorized green merge.

## Prepared integration corrections after the hosted failures

The Python correction reuses the existing canonical material shape and the
SSOT-owned unavailable token. All 25 scoped checks passed, including the three
failed guards and retained receipt-access/vocabulary-drift and source-byte
counterexamples. Ruff passed. The actual sample projection document, sample
path, unavailable path and complete owner schema are byte-equal to `998fa5ff`;
the two native schema hashes remain unchanged. No scanner exemption or schema
pin change was introduced.

Architecture contract 2.1.0 adds only the 15 explicit source-file/target-file
pairs needed for the shared protocol, generated types and test fixtures. It
preserves component ownership and forbidden-edge precedence, rejects malformed,
duplicate or unowned declarations, and disables all path allowances on a bad
declaration even for direct validator callers. All 34 governance tests and a
bounded actual TypeScript import replay passed: 16 source files yield exactly
the 15 declared imports, and removing the declarations restores 15 errors.
Independent review is clear. Full committed-tree compilation remains a hosted
gate; this replay is not a claim about a complete compiled reference.

Scope now releases focus through the existing owner before label hiding/text
replacement, preserves wrapper classes, moves fixtures to its test-support
boundary, honestly declares the mock-only entry tests, and contains long text
with normal wrapping and local scrolling. The initial-payload census adds only
the exact admission/protocol pair, backed by a guard for their closed runtime
import graph and inert, identifier-bound const declarations. Planted declaration
negatives include destructuring defaults, calls, mutable bindings and await-using.
Independent source review is clear; the existing focus, wrapping, mock and
test-support guard implementations are unchanged.

The local typecheck attempt was deliberately stopped after measured free memory
fell to about 0.45 GiB and the owned process remained silent. Its cancellation is
retained, not a pass. No full local suite or fresh browser run was substituted
for the required hosted checks. Other owners' processes were left untouched.
W11's owner supplies the dependency remedy; #591 will integrate that merged main
before its final exact-head validation and authorized merge.

Final full hosted Scope regression, the original 36 HTTP request shapes plus new
topology shapes, five repeats at page limits 50/200 and the unchanged hosted
300 ms gate remain required. Receipts report actual topology row cardinalities;
300 synthetic devices do not imply 300 topology nodes. Route computation is a
separate diagnostic. Publication requires fresh stable-tree, full-history and
PR-body privacy gates. Merge requires all exact-head required checks, independent
review and tested-tree reconciliation. W7 follows the authorized W2e merge.
