# Atlas Release 2 Current-Main Reconciliation Addendum — 2026-08-26

State: `CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT`

Promotion effect: none

## Relationship to the historical closeout

This addendum re-forms the incomplete Release 2 closeout on exact current main. It does not replace or rewrite `docs/atlas-release-2-administrative-closeout-2026-08-24.md`. That dated document remains the historical record of the canonical closeout at `4cd647d1fa20e188b714f0edca3c70bb7cb6f792` / tree `18868df240917ecd21e948a6779043e540ab4f36`, including its then-current GitHub state and verification ledger. Current facts are recorded here. The historical authoritative full-suite result also remains non-green: 8,159 collected, 8,117 passed, 41 skipped, and one timeout in `tests/test_redact_e2e.py::test_redact_workbook_does_not_leak_real_inventory`. A later narrower or isolated pass does not erase that result.

## Preserved lineages

| Evidence | Exact value | Meaning |
|---|---|---|
| Current-main parent | `b92b5db4250a68a6624d4aa850944a5070275296` / tree `3871b2a566abd4f87b2982bd6e331d7c2141c8c5` | Exact live-main checkpoint reconciled here. |
| Canonical R2 closeout parent | `4cd647d1fa20e188b714f0edca3c70bb7cb6f792` / tree `18868df240917ecd21e948a6779043e540ab4f36` | Historical incomplete closeout; ancestry retained without squash or rewrite. |
| Reconciliation merge anchor | `bf113644eedc39249a710fc7005226f560af8bb9` / tree `5d1988a5e82f5120976d1aca1ca9f57c8a29874e` | Two-parent local merge, parents ordered current main then canonical R2 closeout. |
| Evidence-regeneration commit | `18c942f08654c3bb1c2b5b5c82b345bba009cbc9` / tree `b7d49bc144d650a3520bba5c034a89217754ef27` | Exact commit containing the regenerated machine-owned chain and its digest ratchets. |
| Local branch | `codex/atlas-r2-reconcile-current-main-b92b5db4` | Local only; no remote publication authority is implied. |

The merge base is `7ae372f9745173ef7d1e12f72cd76cb8c7043831`. Relative to it, the R2 closeout changes 82 paths and current main changes 19; their sole shared path is `docs/ssot.md`. The merge retains the updated current-main Graphify owner row, all five R2 owner rows, and all three R2 authority-consumption rules, with zero conflict markers. Relative to the R2 parent, the merge adds exactly the 19 current-main paths and no other drift; therefore every non-overlapping R2 blob is preserved exactly.

## Regenerated machine-owned state

Dependency-ordered regeneration changed only these generated artifacts and their two exact digest pins in `tests/test_transition_schema_assets.py`:

| Artifact | Exact-byte SHA-256 |
|---|---|
| `cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json` | `447a4e27eb7bea4fe4ee32173fc16a10ba8d65474c578179975b4faa3a33719c` |
| `cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json` | `d6147f0a211b8cdd313b3e815d9f4d3df9561a75e93415c5aeb84fef30ea496d` |
| `cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json` | `8fce258d323fb5aad3a904c3e7490e34504c250f56055d457dfdb033b53f8436` |
| `cisco_toolkit/data/atlas-r2-tcb-budget-proposal.v1.json` | `1d483abd1e362cdb062e36fcb58939c1b0bd95522cd86be70d395ef76cdfbd65` |

The packaged denominator, input, experimental pack, program, TCB manifest, and QCP-001 manifest remain byte-identical to the canonical R2 closeout and must be verified, not regenerated gratuitously. Their relevant SHA-256 values remain pack `78e8c9690f7833bf32f8347aac54aa8d9ab8f8b49543603f20f52d8fbee51a0e`, TCB manifest `b47c208c64448495f736dcb027bbca5571a6959a552ee38b068404ed29f2c9c9`, and QCP-001 `5c820c7128b50abf40d3f23dbb01251795a977d22b3c05e327b5c4eef432f8ac`.

Regeneration changed bindings and bounded reference measurements, not authority. The final local post-repair observation refresh changed only timing/peak-memory observations and their downstream census/proposal digests; measured boundary outcomes and authority fields did not change. QCP-001 remains `EXPERIMENTAL` / `CONTRACT_ONLY` with no qualification receipt. Measurements remain `authoritative=false`, `approved_budget=null`, and `promotion_eligible=false`. Runtime remains `PARTIAL_NONPORTABLE_PROTOTYPE` with `complete_exact_runtime_closure=false`. The census remains `PROTOTYPE_MEASURED_PARTIAL_RUNTIME_TCB_PENDING_INDEPENDENT_REVIEW` and `BLOCKS_R2_0_COMPLETION`; selected commit remains null. The proposal remains non-authoritative and unapproved, selected commit/tree remain null, source binding remains `SAME_CHECKOUT_SELF_CHECK_ONLY`, and promotion remains false. Release 3 is not included in any of these artifacts.

## Technical merge is not independent approval

PR #534 is technically merged at `0998af50c769f11c3b8afb2070f91ca8f7a575eb` from exact head `9b129b99d84584c8d84b226ff2ac3a8fd2ce3340`; PR #531 is technically merged at `b92b5db4250a68a6624d4aa850944a5070275296` from exact head `f8edbf5a1ec6c302ad6741e21ce559bc9fae9a3b`. GitHub records zero reviews and `REVIEW_REQUIRED` for both. These are real code integrations but not independent approval, qualification, selected-source authority, or promotion authority. PR #530 is closed unmerged. There are no open pull requests and no Release 2 version tag or GitHub Release.

## Verification ledger boundary

Final exact-tree drift gates, focused R2 suite, packaging/archive/source-binding/installed smoke, full default suite, frontend/Master Reference checks, detached replay, and guarded Graphify/Obsidian refresh are recorded in the task-local handoff against their exact commit/tree. They do not rewrite this source-state record. The historical 8,159-test timeout and every current result remain separate evidence rows; a passing current run proves only the current exact tree and its stated scope.

## Separate Release 3 predecessor evidence

BAR-040 is not Release 2 evidence and changes no Release 2 state. Exactly one authorized local observation was attempted against R3 discovery commit `2bbafde1656737b1487bd5d5b06a292569e2ccc2` / tree `5a67851bfa029a1fb05700e95056ca0fe1de7d8a`. The frozen runner exited `2` at P0 with `P0_BROWSER_CONTRACT_INCOMPLETE`; the requested output path was absent. No receipt, staging/temp residue, P1/P2 result, or N1–N7 control evidence exists. The exact failed P0 predicate remains `UNKNOWN`. The three prior `FINAL GO` decisions covered the frozen harness bytes only; they do not convert this failed attempt into a valid observation or authorize a rerun. Release 3 remains `DISCOVERY_PLANNING_ONLY`.

The predecessor status report has SHA-256 `c529836600a0ac842d53ca11e1d87b3b7bff57e5d5ebed407317717b190b6d31`; its postmortem has SHA-256 `367f79034cedc7449c10de506a52a310d7b9b4b91f3f88081b91e47713e2cd2c`. These digests identify the read-only predecessor records; they are not BAR evidence receipts.

## Distinct next authority boundaries

1. **Release 2:** no local producer can create complete runtime closure, representative-workload adequacy, independent numeric approval, selected-source/provenance authority, a detached signed review, or independent acceptance of the technically merged #534/#531 heads. Those require accountable external decisions bound to an exact selected commit/tree. Any push, PR/issue mutation, tag, release, or publication additionally requires explicit user authorization.
2. **Release 3 / BAR-040:** the one-observation authority is consumed. Any new observation requires corrected and newly frozen harness bytes, three fresh exact-byte reviews, fresh custody validation, and an explicit new one-observation authorization. Static diagnosis may continue, but the failed observation must not be rerun or relabeled.
