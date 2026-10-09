# W34 — stored STP observations in VLAN selections

Status: draft PR #627 on `codex/stp-root-facts`, based on owner-merged main
`fa110851275405c9e89d4b72d498e67a10f1377d`. The initial hosted diagnostic is
independently reviewed; this candidate applies its exact generated TypeScript and
two literal native pins. Complete fresh product/native/runtime qualification is
**not yet verified**. The failed bootstrap is preserved below.

## Product boundary

G15's existing VLAN election verdict remains owned by the stored
`vlan_cutover` fields. This residual replaces each VLAN row's
`selections.stp_roots` pointer list with a closed fact list of the selected stored
`/stp_roots/<host>/<vid>` observations. Each item retains the original host and
escaped pointer and exposes `is_root`, `root_address` and `root_priority` facts.
It neither invokes an election nor chooses a winner from duplicates. Readable
duplicate claims remain beside an already ambiguous VLAN verdict.

The parser can create a row from a VLAN header and default `is_root` to false
without parsing a root identity. That case is disclosed as root not parsed, not
as an observed negative. A present malformed flag is unverified, never false.
An explicit true claim survives independently absent identity fields. A stored
false with readable identity remains only the parser's stored flag: the old
record does not retain `bridge_address`, so it cannot independently establish
complete negative capture. Missing and malformed address/priority fields are
held separately; a priority of zero is not absence.

Original VLAN-key spelling, aliases, escaped hosts, namespace selection, source
failures and pointer collisions retain their evidence boundaries. The nested
fact list travels whole within the existing `/vlans/rows` view/list page. It
does not create an arbitrary nested pagination endpoint. No parser, snapshot,
golden, sample, engine election or frontend renderer change is intended.

## Closed schema and native review

The new observation uses existing fact states/types and local schema references.
Closed records and lists, flag typing, withheld null values/reasons and priority
domain must agree under native and stock validation. Both view/list schema pins
will change because they include the owner definitions. No runtime calculation
may populate an acceptance pin; provider/version/domain/offline/copy/refusal and
public-error behavior stay intact.

The hosted frontend job produces bounded `ui-projection-contract` review
material before its unchanged blocking `api:check`. The canonical generator's
exclusive `--review` mode writes to a fresh fixed directory outside the checkout.
The observer retains the actual app OpenAPI, generated TypeScript, exact native
schema bytes and owner hash observations, dependency identities, and before/after
tracked source byte/mode/tree/parent bindings. It never changes committed API
types or native pins. A bootstrap with stale committed types/pins must still fail
the ordinary gates; preserving its diagnostic is not a waiver or qualification.

Observed material and schema deltas require independent review before literal
pins/types are applied. Final source must independently pass canonical
regeneration, stock/native valid and hostile envelope parity, source/binary
workflows and all current protected checks. Producer digests and ordinary
diagnostic transport are not independent archive custody or release acceptance.

## Authored control obligations — execution pending

- Real parser root/non-root and header-only records; explicit true with missing
  identity; malformed flags before default handling; zero/missing/malformed
  priorities; readable fields retained beside malformed cells.
- Duplicate claimants and unchanged ambiguous VLAN verdict; original aliases,
  escaped host pointers, selected non-mapping rows, MST separation, unavailable
  sources, blind-host custody, collisions and malformed VLAN selectors.
- Complete closed-schema validation, source purity, nested view/list equality,
  rejection of invented nested selectors, native/stock rejection of old pointer
  arrays, wrong flag/value states and extra/missing members.
- Hosted observer source drift, dirty index/worktree, assumed-unchanged bytes,
  unknown/overwritten/oversized review members, canonical owner serialization,
  exclusive generator modes and workflow failure-evidence/byte-check ordering.

These controls were authored before initial publication; actual bootstrap
execution and its limits are recorded below. Existing tests are retained;
pointer-only expectations are adapted to the new fact envelope with their
original counterexamples intact. All runtime/generation/schema calculations
remain on GitHub. Concurrent Claude projection/native changes must be integrated
with a reviewed re-pin and wholly fresh gates. W26's owner merge and historical
focus proof do not qualify this new source.

## Hosted bootstrap and reviewed contract delta

Bootstrap head `567d460ba07cbbeb4efb04a7701822708b35ca92` executed as merge
`3e623d9c7ab71e669887e88ac513b11eab307433` (ordered `fa110851 + 567d460b`),
tree `9548139d0427ec4347d84851f195abd8524254fe`. Webapp run `37866614655`,
attempt 1, frontend job `113614943713` completed **FAILURE** at
`2026-10-09T00:53:22Z`. Observer controls, actual observation and upload steps
25–27 succeeded. The controls printed a quiet complete pytest line, with no
standalone numeric summary. API generation-policy controls printed 10 passes;
the unchanged canonical byte check then failed because committed types differed.
Subsequent frontend tests/build/SPA handoff steps 29–33 were skipped, not passes.
Other bootstrap workflows must retain their own outcomes and failure causes.

The same bootstrap's Linux 3.12 job `113614726646` reports 119 failed, 11,362
passed, 144 skipped, 1 xfailed, 8 warnings and 26 subtests passed. Backend job
`113614943625` has the same 119 failed identities; its double-quiet output does
not print a pass/skip aggregate. The failures are the existing 99 literal-pin,
native-admission/proof cases and 20 new G15 native controls. The latter receive
the real transport response and four nested rows, then stop at missing native
admission before exercising hostile-body parity. No individual passing census
for the pure G15 controls is printed. These are real failures, not proof that the
proposed re-pin has passed; every final native/refusal control must execute again.

The selected seven-file diagnostic `11587939852` is named
`ui-projection-contract-3e623d9c7ab71e669887e88ac513b11eab307433-37866614655-1`.
Uploader/API size is 385,546 bytes and their reported SHA-256 is
`2f7b1cf5355cc66ce76f299d916515f279934a15472658722b4ca7153a640b4d`.
It was independently selected, read once as inert review data, and independently
reviewed. Both complete before/after ledgers bind the actual tested commit and
1,714 tracked paths/modes/Git blobs/sizes; no missing, extra or mismatching entry
was found. No local archive/hash/receipt controller verified those producer hashes.

The canonical TypeScript delta consists only of two new STP definitions and
`VlanSelections.stp_roots` changing to their FactList. The emitted native view/list
schemas share 288 equal definitions and preserve the existing page selectors and
whole-row behavior. New closed records require exactly host, pointer and three
facts; the published list is nonempty and withheld lists require a reason. Existing
fact typing/state/paired-owner/ref constraints are reused. No new schema keyword,
native provider, instance-domain rule or runtime auto-pin is introduced.

Reviewed prospective literal pins from these actual hosted schema bytes:

| Schema | Previous W24 pin | W34 candidate pin |
|---|---|---|
| view | `732c68c3d762f2b3d4d0329582bd32f3842567feef9cab20960f6959eef07372` | `16b8095765891cebb3fe94d01d9c3ebfa966f7ead8ae9a139d84499d39b4db34` |
| list | `7f256f809f1d9e0754a2312579ee6afdfe3ae5e58c2b5dd7b44fbfd32b5369b5` | `bca688bd5a3991c70005e20c68a0be5c2d4f3c58aa6cc2a254a51fcc2a6b8c22` |

This is a current emitted-schema plus source-delta review, not an actual
old-main/native-schema byte comparison. The observer used npm 11.17.0; it does not
claim portable's separate tool profile. Native/stock hostile-body parity, the
unchanged refusal/domain controls, actual packaged native proof, canonical API
regeneration and every applicable exact-head workflow remain mandatory after
adoption. None is certified by the proposed hashes or this diagnostic.

Initial source review also rejected a namespace-completeness gap: malformed
`is_mst` could disappear from a published nonempty selection. The corrected
source retains the matching original row/marker witnesses and withholds selection
certainty without changing the owner's election/eligibility rule; falsey malformed
selected rows have unverified child facts. Failed-source/blind precedence,
integer-key round trips, unrelated VLANs, legitimate booleans and legacy absence
have explicit controls. That initial negative and both earlier diagnostic-source
refusals remain preserved; static source clearance never constituted runtime proof.

## Main integration before contract publication

Before the local contract correction `56d80d68` was published, the supervisor
merged W31/#622 as `a06d1d27a1ee190597683630636f2099105378c8` at
`2026-10-09T01:28:25Z`. Its raw parents are `fa110851 + 95320428`, and the
reviewed/head/merged/clean tree is `da6ee09cfbbd517874e3b67e7514b126f9028596`.
W34 integrates that main with a merge commit. Only NOW required conflict
resolution; every parent handoff remains. SSOT combines both owners automatically.
The incoming eight paths are the engine-output helper/workflow/docs/tests and
runner census; STP product, schema, generator and native-input code are unchanged.
This source-family equality preserves the reviewed proposed pin/type delta, not
qualification of the changed complete source. All gates must run on the combined
head; no stale-base push or body edit occurred before reconciliation.

Codex's independently reviewed W31 source findings remain unresolved in that
merged tree: the local receipt route violates the hosted-only boundary; hidden
index states are not closed by status alone; declared ZIP lengths do not close
actual streams; and matching module paths do not bind executable marker-policy
bytes. Those counterexamples remain unexecuted and the owner merge does not
waive them. G15 uses none of that receiver. Future G14 generation/adoption needs
an admissible reviewed hosted route and fresh exact-source/output verification;
the documented local receiver and dry-run remain prohibited.

## Independent bootstrap architecture failure

Reference job `113614726348` on bootstrap tested `3e623d9c` completed its quiet
tests and lint, then failed **Compile exact tracked Git tree** with three
undeclared `release_distribution -> assesshub_backend` edges (5/6/7), exit 2.
Downstream steps 10–16 were skipped. This is separate from the API/native-pin
failures and is not attributed to them. Portable binary job `113614726199`
separately passed 1,714-file immutability, PyInstaller and selftest 13/13, then
failed the frozen projection smoke; its log exposes no exact native/header
subcause, so none is asserted here.

The diagnostic's original `.github/scripts/` location classified its actual
backend imports and exporter call as release tooling. The correction moves its
unchanged implementation to `webapp/backend/observe_ui_projection_contract.py`,
beside the contract owners it observes. Workflow invocation, direct path guards
and test loading follow that owner. Architecture policy/allowlists and all
conformance checks remain unchanged. No diagnostic, schema, pin or generated-type
logic is altered by this relocation. Fresh Reference compilation, observer
execution and all other gates must verify the corrected combined source.

## Native-return proof correction after the passing wrapper suite

On `6471d7d9` / tested `3aaf9131`, the current frontend and whole six-job webapp
workflow pass; the unfiltered backend command reaches 100% with all three Scope
flags enabled and no printed numeric aggregate. Independent review nevertheless
found a narrower proof boundary in the 20 new G15 cases: their observer recorded
that native validation was called, then asserted effective-wrapper/stock parity.
The wrapper intentionally falls back to Python when native returns false or
raises. Thus that success establishes construction, invocation and wrapper
behavior, but could mask a native rejection/exception on the valid nested body.
This is a source-derived test-proof gap, not an observed product/native failure;
the passing job results remain recorded with this limit.

The same 20 cases now record each actual native return and any exception before
re-raising. They require literal `True` for the valid body, literal `False` for
each hostile body (including the public-error comparison), and no exception.
Identity checks avoid treating 1/0 as the native Boolean result. No production
fallback, domain, schema, provider, literal pin, generated type, case or guard is
changed. Fresh hosted execution must establish this stronger acceptance/refusal
proof; no old passing receipt supplies it.

## Hosted LF path-set ratchet

Supervisor comment `6073194032` identifies a separate mechanical failure on
`6471d7d9`: Linux 3.11 job `113633171567` (actual tested `3aaf9131`) reports one
failed LF-custody test, 11,520 passed, 279 skipped, 1 xfailed, 1 warning and
26 subtests passed. The failure prints the exact actual LF receipt:
182 paths, `sha256:3dfb75b912fcf6e8fa80b01544e97464e128e79643892f62a45cf33b59ad276e`.
The observer's move into `webapp/backend/` adds one path to the unchanged LF rule.
Git shows only three existing test/doc files changed from `6471d7d9` to `c9cfedc5`;
the LF policy, matching path set and owner inputs are unchanged. The hosted
receipt therefore applies to this same path set without local hash computation.

The fixture's `lf_scope` adopts that observed receipt. Its separate
`broader_declared_lf_scope` ratchet also needs attention: the derived owner set is
still 38, so the broader cardinality is 144. That later assertion was not reached
in the selected failing job, and its actual hash remains unobserved. The existing
test now runs early on only the Ubuntu 24.04 / Python 3.11 leg to surface this
companion receipt promptly; it remains in every complete suite. Its first failure
message also prints the broader receipt for future combined path-set updates.
No assertion, LF rule, publisher exception, derived-owner membership, byte check
or full-suite requirement changes. The broader pin must come from hosted output,
not a guessed digest or hand-merged receipt; final qualification remains pending.

Supervisor comment `6073401209` supersedes the W36-only Scope re-bind request.
No W36 branch, artifact intake or re-bind is authorized to proceed now. Wait for
the single five-path request on the W45 integration train, with its exact head,
artifact and new sample identity. Separate sample/receipt-byte claims in peer
comments are declarations until independently joined to hosted evidence.
