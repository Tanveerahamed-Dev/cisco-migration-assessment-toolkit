# W60c redaction residuals — 2026-10-12

Owner-authorized separate workstream from main `0dc2f5d6f4d122ef74f8098e173e2be0bc2c902f`, after W60b merge `c543f0a181e8db2700007f1658ae0d856dfbbbcd`. Branch: `codex/w60c-redaction-residuals`. The protected original and existing W60b checkout are preserved. Runtime evidence is GitHub-hosted only; local work is source editing, Git/GitHub, static lint and the two required Rule-7 scans.

The independent [BLOCKED verdict](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/656#issuecomment-6112757283) and [narrow round-5 verdict](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/656#issuecomment-6115443347) leave P1-3, P1-4, P2-5 and P2-6 open. W60b's two P0 repairs remain intact. This work does not restore the rejected broad round-4 shell/scalar policy.

## Repairs and source custody

Each finding is paired across producer and independent verifier in its own source commit. Hosted full-view comparisons run after each cumulative source commit and on final HEAD. This prevents a later repair from hiding an earlier golden/sample view change. A view change is an owner-decision stop, not an assertion to rebaseline.

- P1-3 (`b582a63be6eaecbaaf4f3bdf41e02fb74cc41851`): recognize accepted public option words before validating mixed-case SNMPCMD_ARGS targets, and consume the same public operands in the argv walk. Logging consumes its actual priority/destination arity, with attached, equals, quoted and split forms. Metadata operands spelling a credential flag or known command remain operands rather than opening another run.
- P1-4 (`f2b2a6336b7998933ca8d2fe556f6652935aceea`): carry only a directly leading comment marker (`//` or `!`) before the supported authorization header, with optional whitespace and one field-opening quote. Strip a matching continuation marker using that provenance, then require the complete continued credential field to be a physical placeholder; a placeholder before private residue does not certify. Existing unprefixed/capture/curl paths retain their own rules.
- P2-5 (`8b9cf50566649fac97c954beb26411a450dbb93d`, follow-ups `0242751d2b0763770e80b248a61212a9eae731ec` and `fabd9144f3dbf7d5d90098d4acf6ae2154793371`): shell spelling resolution is restricted to actual executable words. A bounded, private-slot witness inside a proven sh/bash -c carrier reuses the existing outer operand path only when the legacy raw command gate cannot reach that spelled executable. Previously reachable plain-name scripts retain their existing structure; quoted literal data does not create a carrier. Attached canonical markers retain their complete word boundaries. No credential operand/configuration decoder or creator exemption is changed.
- P2-6 (`22ac66b347f8946c362320370e6ab7f791eeb2e4`): only complete nonempty scalars inside proven field records are in scope. Quoted syntax/public-vocabulary spellings in a private scalar are values, not structural punctuation or public metadata. Nested actual credential keys remain owned fields; complete public scalar contents cannot introduce fake keys. Empty absence, containers, header owners, prose and configuration clause order retain legacy behavior.

Public option arity follows pinned [Net-SNMP `snmp_parse_args.c`](https://github.com/net-snmp/net-snmp/blob/9f8a86e7ce7f1a491628eead51f5e9a33d04292f/snmplib/snmp_parse_args.c), [logging implementation](https://github.com/net-snmp/net-snmp/blob/9f8a86e7ce7f1a491628eead51f5e9a33d04292f/snmplib/snmp_logging.c) and the trapsess callback in `agent_trap.c` at that same commit. Upper-case logging modes consume priority; F/S also consume file/facility, possibly in the same word. Existing legacy option consumption remains compatibility behavior, not a claim that deprecated options are newly accepted upstream. The independent verifier keeps its own literal grammar; it does not import the producer.

## P3-7 residual

ISAKMP peer-hostname over-redaction remains deferred. The frozen strict W60b row `isakmp-peer:complete-inline-enc-hostname` explicitly requires inline ENC peer-hostname loss. No general proven-operand rule compatible with all immutable legacy controls has been established in this workstream. No EXAMPLE-specific or accidental syntax exception is added to claim closure. The existing fail-safe transform and old assertions remain unchanged.

## Validation contract

Every original W60 and W60b test/corpus record remains unchanged. The existing W60b custody test stays in the hosted lane. Fresh W60c schematic cases use EXAMPLE values for invented credentials, users, hosts and paths; fixed public grammar words/punctuation are retained only as minimal syntax-collision controls whose exact spelling causes the defect. No customer or real credential is used. Expected results are derived from grammar roles and existing assertions, not harvested from candidate output.

The hosted replay includes all legacy/review inputs plus all fresh W60c cases against main `0dc2f5d6` and round 3 `d05ff1aaea85d87ff474f3a9d425eeacfa99a10c`, requiring zero previously removed-secret regressions and no loss of post-scrub certification. Both golden and sample redacted views must be byte-identical to main, with unchanged protected Git entries and full SHA-256 receipts. The existing four W60b view oracles remain active. Required hashes:

- Golden: `6fb01cc4781e1db9b637722f2a6e1e9dbe6724a3140e007306baffd27f150445`.
- Sample: `67debf50b2fb6ee09471c181b4d876acd59b4b50f683a7554880f57cd72c2552`.

No test, private-value assertion, sentinel or gate is weakened or newly skipped. No persisted engine/frontend output is imported, regenerated or changed. Rule-7 index/worktree privacy and all new commit/message/per-parent/publication marker scans precede every push. All fifteen required contexts plus focused validation must be GREEN on the published head before the summary and independent refutation. This record contains an implementation plan and source custody; hosted behavior is not yet verified.

Limits: synthetic corpus and existing hosted integration coverage are finite. No live device/customer captures, actual shell/Net-SNMP daemon/creator-script execution, exhaustive grammar, universal privacy/complexity proof, signing, release or merge authority is claimed. Stop after the exact-head green summary for a separate independent refuter.

## Source-only review probe

Previously reachable plain-name creator commands inside quoted shell strings still use the pre-existing bounded configuration decoder during recursive inspection. A quote-literal algorithm/placeholder alias may normalize there. This is an inherited-source hypothesis, not a locally executed or certified leak and not claimed closed by the executable-spelling repair. The synthetic raw-known creator marker-alias input and declared private bytes are retained in the mandatory main/round-3 archive differential. A proved baseline regression fails that gate; no probe is removed and no assertion weakened to obtain GREEN. The fresh independent refuter must assess the remaining scope boundary.

## Frozen corpus and publication preparation

The fresh fixture is frozen at SHA-25666ecc92f328851996b78541eef549a68a59f19f2094b11b48b12090a384ecc47:154 fresh strict rows (112 required-redaction,42 public preservation), plus18 unchanged historical P1/P2 schematic assertions,13 refusal controls and2 provenance controls. All3428 legacy/fresh/refusal/source-probe inputs participate in mandatory main0dc2f5d6 and round-3 replay. The new module has no env gate or skip; all archive/custody/view tests run in every hosted collector. Six cumulative source refs are pinned through fabd9144f3dbf7d5d90098d4acf6ae2154793371, plus finalHEAD. Legacy fixtures/tests and protected output Gitentries are unchanged. StaticJSON, touched-fileRuff and whitespace checks pass; runtime, differential, view and15-context verdicts remain pending until the published hosted head.

## First hosted negative evidence

Initialhead54462233920304b90798716dfe0b742af745792a focusedrun38199390432/job114649177751 stopped duringcollection with KeyError finding in the new historicalverifier selector. Older five legacyverifiercontrols intentionally omit that optionalclassification field. No behavior, archive, performance orview comparisons ran, so no view-parity orclosure result is claimed. The selector now uses optionalmetadata lookup; exact requiredhistorical-family assertions and everyold/new credential/refusal assertion remain. This is a collection/schema correction only; no productcode or outputbyte changes. FreshRule7 and exact-head hostedqualification are required.
