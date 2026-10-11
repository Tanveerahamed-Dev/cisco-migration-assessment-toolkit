# W60b: required credential slots and semantic arguments

Owner assignment: 2026-10-11 (Qatar). Branch `codex/w60b-redaction-fixes`, from
`origin/main` `0b411c16347a0f1651b88cae52b58555701e4db3`. Scope is every finding in
[the independent #647 refutation](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/647#issuecomment-6107159328).

## Source changes and evidence boundary

Implementation is authored; runtime behavior is **not verified** until the exact-head hosted
checks complete. No local test, reproduction, engine, browser, build, Graphify or custody-controller
execution is authorized. Only edits, Git/GitHub, touched-file syntax/lint and Rule-7 static scans run
locally. No persisted output is regenerated. A changed persisted output or redacted golden/sample
view is a stop condition, not an invitation to update its expected bytes.

| Finding | Change | Hosted closing evidence |
|---|---|---|
| R1/P0 | Required username, neighbor and enable password/secret value slots run before generic structural/prose stops; independent verifier reads the required slot. Required OSPF/NTP key values are also positional. | Every exempted structural word in required value slots, quoted/typed/privilege forms, structural look-alikes; exact pre-W60 and round-3 differentials. |
| L1/L2 | Decode shell/config quote and escape semantics before strong/weak SNMP pair and option recognition; keep raw offsets for replacement. Creator commands have their own required password and public algorithm option contexts. | Quoted/escaped strong and weak witnesses, quoted options, attached/standalone operands, single-weak controls and algorithm-shaped creator passwords. |
| L3 | Bounded nested quoted command coverage prevents the outer argument-word index hiding a recognized credential command. | Quoted shell command, raw refusal, scrub certification/idempotence, round-3 comparison. |
| L4 | USM positional fields use escape-aware words, not a separate naive quote expression. | Valid escaped/single-quoted names, auth/priv keys removed, protocol OIDs preserved. |
| L5/O3 | Captured prefixes are preserved before taking a scheme continuation; an empty authorization header carries a whole pending header value. | Diff/comment/quote/grep/cat prefixes, different line numbers, empty-header scheme/value wrap. |
| L6 | Check-ID vocabulary remains engine-derived, but only complete engine evidence/deduction formats are exempt. | Assignment and trailing-value counterexamples plus byte-identical engine cite/deduction controls. |
| O1 | Case-insensitive directives require configuration operand shape, preserving uppercase prose controls. | Mixed/uppercase trap and proxy config plus the existing prose look-alike. |
| O2/O4 | Explicit credential slots do not exempt punctuation or a key value because it resembles structure. | Punctuation-only argv/USM/SMUX slots, required key-slot collisions and empty/placeholder controls. |
| Structural loss | Semantic USM indices preserve protocol OIDs; explicit shape-only wrapper look-alikes remain structure. | OID and wrapper option assertions, with no blanket exemption for attached SNMP values. |
| T1 | Stop once a SMUX rest-of-line credential covers the remaining suffix. | Deterministic copy-work bound and scaled real producer/verifier calls. |
| T2 | Index exact digest/public-key label endpoints; merge ordered entropy spans without growing-prefix searches or all-prior-span overlap scans. | Clean labelled and unlabelled entropy inputs, deterministic copy-work and scaled real calls. |
| Refused disagreements | A command-shaped operand cannot split its current credential vector; mixed quote fragments are replaced as coherent words. | First-pass certification and fixpoint checks for command-shaped passwords and adjacent quote fragments. |

The original W60 corpus and its assertions are retained. The W60b corpus contains hand-authored
strict scenarios and the complete fresh review corpus for archival differential replay. Baseline
implementations come from real Git archives of `2c927d0209e4c4928c3f29d8747d648f930ddade`
and `d05ff1aa`, never a frozen copied implementation. Their source blobs and the tested byte custody
are checked in the focused hosted lane. The existing 15 protected contexts remain unchanged.

## Handoff gate

The requested endpoint is an open PR with all 15 required contexts GREEN on its exact final head,
plus the focused archival differential/output-custody lane. A different reviewer independently
refutes the final source before the supervisor considers merge. CI is implementation evidence,
not privacy certification, field acceptance, release approval or authority to merge.

Hosted results and any failures will be recorded here and in the live board before handoff.

## First hosted head: e411b50f (negative evidence)

Draft [PR #656](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/656)
is published after complete Rule-7 privacy and history/publication marker scans passed.
The [focused run 38131711274](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38131711274)
failed during collection: the two new required-slot families were missing their corresponding
prefilter and cross-line metadata entries, and the unchanged length assertion refused import.
The portable/full-source run and distribution contract also failed on that import assertion.
No behavioral, archival differential or persisted-view custody pass is claimed for this head.

The correction adds the two aligned metadata entries; it does not remove or relax the assertion.
All earlier failures remain bound to `e411b50f`. Fresh hosted checks must validate the corrected
head. The corpus now contains 689 strict rows plus the complete 599-row review corpus.

## STOP: golden engine view moves at 894c8175

The [focused hosted run 38132545956](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38132545956)
tested exact head `894c8175e101a48cd2ec8cb569abd95ef94d9158` and ended with **157 failed,
541 passed**, in 181.38 seconds. The user explicitly requires stopping if an existing engine
output would move. Implementation is therefore stopped; no output or assertion is rebaselined.

The tracked golden/sample/compiled/distribution output files are unchanged. The hosted comparison
of the existing golden snapshot's **redacted view** failed with ten changed leaves:

- `$["framework_coverage"]["frameworks"]["CIS"]["controls"][0]["title"]`
- `$["framework_coverage"]["frameworks"]["NIST"]["controls"][8]["title"]`
- `$["framework_coverage"]["frameworks"]["PCI"]["controls"][7]["title"]`
- `$["framework_coverage"]["frameworks"]["STIG"]["controls"][9]["control"]`
- `$["framework_coverage"]["frameworks"]["STIG"]["controls"][9]["title"]`
- `$["punchlist"][32]["title"]`
- `$["remediation_plan"]["by_device"]["access1"][1]["title"]`
- `$["remediation_plan"]["items"][6]["title"]`
- `$["security"]["access1"]["findings"][0]["title"]`
- `$["security"]["core1"]["findings"][0]["title"]`

Serialized-view SHA-256 before: `6fb01cc4781e1db9b637722f2a6e1e9dbe6724a3140e007306baffd27f150445`.
After: `ef5d0dc0a0d3a03199911b7e9fc603e38b1963d1d013b398457b8bb9185ef562`.
The first failed view assertion prevents a completed sample-view comparison verdict; sample-view
identity remains **not verified**. The views were generated only in hosted scratch, never imported.

### Other decisive hosted evidence

- Both reported R1 unquoted P0 cases (`review:p0_user_plain`, `review:p0_bgp_plain`) passed the real
  producer/verifier test. This focused result does not qualify the whole change.
- The archive replay covered 2,994 cases. Against pre-W60 `2c927d02`, 1,449 removed secret slots
  were checked and **two differential failures** remain (`crypto isakmp key chain`, `crypto isakmp
  key 14`, originally incomplete-command probes). Against `d05ff1aa`, 2,270 removed slots were
  checked and **zero regressions** were observed. The requested zero-regression gate on both is
  not met; the incomplete probes are retained, not silently removed from the differential.
- A quoted recognition-witness example still leaked and certified: `poll-wrapper -v "2c" -c
  JuniperBrook0 inlet-hill-0` was unchanged and accepted. The remaining quoted-shape and uppercase
  directive failures are not closed. Root cause is **unconfirmed**; the raw prefilter/semantic
  recognition boundary is a specific source-review lead.
- Quoted required-value output assertions and the attached public-algorithm structural assertion
  failed. Their exact outputs/expectations are retained in the hosted log; no assertion is weakened.
- The deterministic copy-work bound and all three real producer/verifier scaling tests passed.
  Eight-times input yielded about eight-times median time: SMUX 86,952 to 709,784 bytes, about
  0.0338 to 0.2685 seconds; labelled digest 21,505 to 172,033 bytes, about 0.0244 to 0.1905 seconds;
  unlabelled entropy 17,409 to 139,265 bytes, about 0.0225 to 0.1720 seconds. These are focused
  regression results, not universal linearity or privacy qualification.

The remaining four exact-head workflows were requested cancelled after revalidating their branch
and SHA, because the user stop condition had fired. Cancellation is incomplete validation, not a
passing gate. PR #656 remains open **draft**, with no merge or release action. All 15 required
contexts are **not GREEN**. No local test, reproduction, measurement or build ran.

This stop record and the board update are committed locally only, avoiding a new hosted run after
the stop. Published code remains at `894c8175`. The next permitted step is an owner-reviewed
continuation decision: preserve the ten existing engine-authored leaves, close the remaining
behavior/differential failures, and re-run every unchanged hosted gate before independent refutation.

## Owner-delegated continuation after 2e213e72

The supervisor explicitly authorized continuation and publication of the stop record with the next
repair. The ten changed leaves are over-redaction of engine vocabulary, not credential material.
Their two literals originate in `parse._SEC_CHECKS` and the framework catalog. The repair derives
exact vocabulary from trusted registry findings passed through the actual framework, punch-list
and remediation builders. Only structurally bound snapshot fields with matching owner values
are exempted. Raw collection text, altered titles, unbound title fields and credential containers
remain subject to scrubbing. No output is regenerated or rebaselined.

The continuation also gives ISAKMP key values a required slot, including incomplete `chain` and
`14` operands; admits quoted/escaped argument witnesses to the semantic observer; handles case
variants of complete directives; preserves quotes around required-slot placeholders; and removes
explicit argv/positional credential contents before the generic keyword observer can mistake an
embedded `Auth` for an anchor that consumes later options and the target host. The verifier's
required-slot and recognition checks remain independent. Existing assertions are retained.

Hosted custody will compare both full golden and sample redacted views with the original W60
main and current main `3f1d844cfabd60b901a0adb68a246bd45bdcf1d0`, printing both verdicts before
asserting. Relevant redaction owners and snapshot inputs are unchanged between those revisions.
The original protected-output guard and both zero-regression differentials remain in place.
This source repair is pending hosted validation; earlier failures and cancellations remain evidence.

### Current-main integration required to start PR gates

Published continuation `42bd8bfe` included `2e213e72`. Both Rule-7 scans passed. GitHub then
reported the PR unmergeable because the live work board conflicted with main `3f1d844c`; the
required PR workflows and focused lane did not start. CodeQL activity alone is not that gate.
Merge `b7d618f1` reconciles the board and retains all upstream work and published frontend bytes.
No engine output was regenerated. Output custody binds the candidate to current main's exact
published files and separately proves every protected difference introduced upstream is inherited
byte-for-byte. The original golden/sample input equality and both full redacted-view oracles
remain unchanged. Both pre-W60 and round-3 zero-regression requirements remain unchanged.

## e7e05409 hosted evidence and narrowed owner decision

The [focused run 38144605136](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38144605136)
completed **151 failed / 563 passed** in 46.50 seconds. It checked 3,000 archive cases:
pre-W60 main had 1,452 removed slots checked with **zero regressions**; round 3 had 2,272
removed slots checked with **zero regressions**. The quoted recognition witness, uppercase
directive and attached public-algorithm assertions passed. Both original pathological mechanisms
and all three scaling families passed. The original ten changed leaves no longer differ.

Broad owner-vocabulary preservation exposed prior main redactions instead: golden changed eleven
leaves and sample changed thirty-one. Those include the `weak-user-pw` title/control projections,
the STIG `SNMPv3 auth/priv` control, and two sample design recommended-action projections.
Golden SHA-256 was `4ff3faf51118a9961adc2eed7192620f5822201010991fa40ff9645fb5140bee` versus
main `6fb01cc4781e1db9b637722f2a6e1e9dbe6724a3140e007306baffd27f150445`; sample was
`2017137e08678c09239c140e63b8024f642631c9106ade476d28eead4ab839fc` versus main
`67debf50b2fb6ee09471c181b4d876acd59b4b50f683a7554880f57cd72c2552`. Both immutable
main oracles agreed. Tracked outputs remained unchanged; no baseline was moved.

The supervisor resolved the conflict explicitly: **“Keep exact main views; narrow the vocabulary
requirement.”** Preservation is therefore limited to exact, structurally bound engine vocabulary
whose password follow-word belongs to the existing structural registry. Other engine vocabulary
retains main's existing transform. The two design actions are derived from `design_kb.all_principles()`
and require their real decision/doctrine projection IDs and domains. No title or action is hand-listed.
All eleven security checks remain covered against the real archived main projection; the earlier
broad all-raw-title assertion is replaced to reflect this explicit owner decision. Secret corpus
assertions and the full golden/sample byte oracles are unchanged.

Other failures were quoted placeholder rejection by the legacy verifier, after the producer had
already met exact quote expectations, and a new complete IKE policy structural control. The verifier
now accepts only one balanced quote pair containing exactly the placeholder. The producer and
independent verifier preserve `authentication pre-share` only deeper inside a complete ISAKMP
policy stanza, outside credential blocks/banners and without a pending credential. No global
`pre-share` exemption is added. Fresh hosted evidence must verify these changes; earlier failures
remain bound to e7e05409.

## 85fc5a1f: byte identity verified; four focused assertions remain

The [focused run 38145783395](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38145783395)
completed **four failed / 730 passed** in 40.53 seconds. The full golden AND sample redacted views
were byte-identical to BOTH immutable main oracles, with no changed leaves and the original
SHA-256 values above. All protected files and upstream inherited Git entries passed custody.
The 3,002-case archive replay checked 1,452 pre-W60 removed slots and 2,273 round-3 removed slots,
with **zero regressions against both**. All engine-registry main-view and owner-binding tests passed.

Remaining assertions identified an escaped public SNMP level being mistaken for an auth keyword;
an extra ISAKMP policy operand accepted without scrubbing; and a corpus classification mistake.
The `review:snmp_shape_quoted_4` fixture incorrectly called the `-3m` hex master-key operand
structural. The original input and ID are retained; its assertion is strengthened to require removal
of BOTH master key and community, while preserving the option, quotes and target host exactly.
No private operand is permitted merely to obtain a passing structural assertion.

The continuation observes known public protocol/version/level operands only in their actual argv
slots and masks their raw quote/escape bytes from the generic keyword observer. Unknown values
and actual private slots remain scrubbed. The independent verifier observes the original args.
An admitted ISAKMP policy's unexpected authentication tail is scrubbed whole and must contain
exactly the placeholder before certification. The strict corpus now has 699 rows; the original
599 review inputs and both full-view oracles are retained. Fresh hosted verification is pending.

## 4cfe8bb2: focused pass and full-suite compatibility failures

The [focused run 38147009070](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38147009070)
passed **736 tests** in 47.48 seconds. Its 3,004 archive cases checked 1,452 pre-W60 removed slots
and 2,275 round-3 removed slots with **zero regressions on both**. All four full golden/sample
view comparisons were byte-identical to W60/current main with the hashes recorded above.
Protected and inherited output custody, owner binding, and reported work-bound checks passed.

The broader [CI run 38147009011](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/actions/runs/38147009011)
failed all six Python-version/platform suites and coverage. Python 3.12 on Linux reported
**38 failed / 16,993 passed / 149 skipped / 3 xfailed**, with 26 passing subtests, in 2,439.78 seconds.
Failures cover legacy registry parity, public structural/show statements, enable-password prose,
Junos NTP container IDs, wrapped authorization certification, legacy sudo formatting, the new
workflow's runner census, and two assertions pinning the over-redaction expressly being repaired.
This full-suite failure remains evidence; a focused pass does not close it.

The next repair keeps required-slot handling independent of the existing 32-family metadata and
verifier registry. An ordered qualifier parser consumes at most one explicit password type; the
following token is a required value even when it is another type digit or qualifier word. Terminal
wrap behavior remains for the first type when its value actually follows on the next line.
The verifier checks these required values independently. Complete Junos NTP statements preserve
their numeric key ID and public type/hash/value markers, while the actual value remains required.
Closed structural/show and descriptive statements preserve their whole public syntax without
exempting a username/neighbor/enable value that spells the same word.

Creator arguments follow the upstream `net-snmp-create-v3-user.in` script's exact dispatch:
both `-A`/`-a` can name the script's supported auth algorithm or a private auth value; both `-X`/`-x`
do the same for its supported privacy algorithm or a private privacy value. Unsupported aliases
such as `SHA256` remain private in creator slots, even though ordinary snmpcmd uses a broader
algorithm vocabulary. Only escaped public argv bytes require masking from the generic observer.
Wrapped authorization checks accept a placeholder plus closing structural punctuation and
recognize complete subsequent Host/Accept headers without accepting an unsanitized wrapped value.

The strict corpus grows to **870 rows**, retaining all **599** original review inputs and every
previous strict input. Typed numeric/qualifier values, valid first-type wraps, descriptions, and
creator public/private look-alikes have exact byte assertions. The original 1,706 W60 inputs and
private sentinel lists remain intact. Two historical expectations (`create-v3-user` public DES and
`config-after-2c` public wrapper) are retained as history; explicit W60b expectations additionally
require their complete public syntax to survive. No private-value assertion or byte oracle is
weakened. The focused lane now executes the entire W60 suite as well as W60b and runner contracts.
No local runtime, test, build, output generation or rebaseline occurred. Fresh exact-head all 15
required contexts and the focused lane must pass before stopping for independent refutation.
