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
