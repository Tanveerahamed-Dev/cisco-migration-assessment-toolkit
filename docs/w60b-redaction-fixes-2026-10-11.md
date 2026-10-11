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
