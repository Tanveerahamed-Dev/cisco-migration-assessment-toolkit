# W2e: Topology & Paths validation

Status: implementation and focused validation in progress. Full regressions,
real browser/build proof, hosted performance, privacy/publication and merge gates
remain open. W2d merged as `828847f14c908fa7b725fe97fdff9cee5f115178`; its receipts
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
Real-browser proof of this mode remains pending.

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
  seconds on the final engine and reviewed pins. It covers authority, complete
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
  unchanged access-guard cases and 66 adapter/legacy-entry cases). The HEAD guard
  requires the local checkpoint. The full exact-head hosted Scope suite remains
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
  Final export/generation equality must be rechecked after integration.

Local Node 24.19.0/npm 11.16.0 were acquired to an external task directory, with
the signed Node checksums and pinned archive/executable/npm hashes verified.
The first Git gpgv call rejected an absolute Windows keyring path; the preserved
retry used a relative path and verified the clear-signed checksum output. No
global installation or machine PATH change was made.

Workstation memory briefly fell to about 80 MiB while other Scope worktrees ran
Vitest. Heavy local checks paused, unrelated processes remained untouched, and
checks resumed serially after recovery. Local timings under contention are not
performance acceptance.

## Remaining delivery gates

Final full Scope regression, genuine hub and tracked frontend
builds, integrated browser proof, the original 36 HTTP request shapes plus new
topology shapes, five repeats at page limits 50/200 and the unchanged hosted
300 ms gate remain required. Receipts report actual topology row cardinalities;
300 synthetic devices do not imply 300 topology nodes. Route computation is a
separate diagnostic. Publication requires fresh stable-tree, full-history and
PR-body privacy gates. Merge requires all exact-head required checks, independent
review and tested-tree reconciliation. W7 follows the authorized W2e merge.
