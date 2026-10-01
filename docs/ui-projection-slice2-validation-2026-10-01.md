# UI projection slice 2 validation (2026-10-01)

## Scope and source

W2a / PR #580 projects Inventory, device documents and Findings through the existing
`ui_projection/1` contract. Main after #579 (`d92fcb1f`) was merged into the existing branch
with merge commit `b504948e`; both parents and all board handoffs were retained.

The evidence integration preserves producer `evidence_basis`, `evidence_refs`, optional
`evidence_refs_total`, and health `deduction_refs`. Evidence references remain distinct from
fact-envelope references. Health references are an ordered subsequence, never index-paired
with deduction text. Reference truncation follows the first eight deductions even when fewer
references survive. Only a producer-published total can state an uncapped finding-reference count.

Final reviewed `cisco_toolkit/ui_projection.py` SHA-256:
`9e528e941af2cd40f8f6eba7f34b6dc8955956fe1bd0273b2b850b1b2fa2e0d7`.

## Test-first and independent review

- Reproduced I23's deliberate failure after merging #579. New evidence tests were red before
  implementation; I23 now demands parity for all four source-owned evidence fields.
- Adversarial cases cover closed reference shapes and vocabulary, RFC 6901 escaping,
  unresolved/null targets, malformed and oversized array indexes, numeric map-key collisions,
  oversized integers, orphan totals, inconsistent bases, invalid capped totals, legacy rows,
  source failure precedence and the real producer's deduction-reference subsequence.
- Independent probes found and closed numeric-key crashes/collisions, orphan-total handling
  and failed-source fallback precedence. The final reviewer reported no remaining actionable
  findings; seven final import/parity/cap/subsequence/failure cases passed.
- The initial broader focused run had 536 passes and one import-boundary failure. The direct
  `analyze` import was removed. Immutable vocabulary/rule copies now follow the module's
  established stdlib-plus-SSOT boundary and are exactly parity-pinned to their owners.
  The subsequent focused evidence/producer/import gate passed 101 tests.
- Two inherited sample assumptions were reconciled without relaxing their intent: the missing
  security-host denominator is derived independently from raw sections, and the producer's
  retrieval-date formatting slice is a reviewed exemption from list-cap disclosure.

## Local gates

- Complete final projection and golden regression: passed (exit 0), using `test_ui_projection.py`,
  `test_ui_projection_inventory.py`, `test_ui_projection_evidence.py` and `test_pipeline_golden.py`
  with four workers and `--dist loadfile`. No fixtures were regenerated.
- Ruff: passed across the repository. CI's eight-module mypy gate: passed.
- Frontend: 274 unit tests passed; production build passed; tracked distribution bytes unchanged.
- Browser E2E: five passed, one explicitly opt-in performance probe skipped.
- Visual types and all 22 local Windows Chromium baseline comparisons passed; no baseline updated.
- Atlas Scope hub build passed; the real toolchain, hub build and Chromium prerequisites were present.

The full local coverage invocation used four workers and strict Scope prerequisites:

```text
py -3.12 -m pytest -n 4 --dist loadfile --cov=cisco_toolkit   --cov-report=term-missing:skip-covered --cov-fail-under=85
ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN=1
ATLAS_SCOPE_REQUIRE_HUB_BUILD=1
ATLAS_SCOPE_REQUIRE_MARKUP_ORACLE=1
```

**Incomplete, not a passing gate.** It was deliberately cancelled after 1,628.78 seconds,
with the final progress log around 38%. Seven failures and one expected failure had appeared;
no final named report or coverage percentage was emitted. Those seven failures are unclassified
and are not asserted to be the board's eight known worktree failures. The wrapper's exit 1
records cancellation, not a completed pytest verdict. Its private log and cancellation receipt
are retained outside the repository. Required hosted CI provides the complete suite and coverage
verdict on the pushed head; this PR stays draft until that gate is green.

`UPDATE_GOLDEN` was unset. Before/after SHA-256 inventories prove all tracked golden, sample-data
and frontend distribution bytes unchanged. The existing main merge carries five EOF-blank-line
warnings in Scope files; each was verified byte-identical to main. W2a's own diff check is clean.

## Hosted CI receipt on implementation head `c8a78732`

CI run `36889899742` completed all five Linux matrix jobs with the same sole failure:
`test_every_module_that_reads_the_receipt_is_classified_with_a_mechanical_proof` names
`cisco_toolkit/ui_projection.py` as an unclassified receipt reader.

| Python | Passed | Failed | Skipped | Expected failure |
|---|---:|---:|---:|---:|
| 3.10 | 9,733 | 1 | 283 | 1 |
| 3.11 | 9,742 | 1 | 274 | 1 |
| 3.12 | 9,877 | 1 | 139 | 1 |
| 3.13 | 9,866 | 1 | 150 | 1 |
| 3.14 | 9,865 | 1 | 151 | 1 |

Source review locates the receipt name only in `PUNCHLIST_INPUTS`. The projection delegates
section/census state to SSOT; its coverage and unknown-evidence vocabularies have separate owners.
The missing classification is corrected by a scoped `section_dependency` proof in the guard.
It permits only the literal dependency registry and its four existing SSOT-delegating argument
forms, rejects ordinary named shadowing/binding and alias/index/iteration uses, and pins the
two overlapping unknown-evidence vocabularies to their owners. Behavioral probes hold SSOT's
answer fixed while varying every producer receipt row and all rows together across declared
states plus a future unknown state. They check actual owner delegation and a published finding.

Independent refutation found later-row and all-assessed aggregate survivors in the initial
behavioral proof, then parameter shadowing in the initial structural check. All three were
closed with failing-before/passing-after regressions. Fifteen independent ordinary binding/use
mutations are rejected. These bounded probes do not claim exhaustive behavioral proof.

Validation: the broader protocol plus all three projection test modules passed 536 tests before
the final proof refinements. The final complete protocol file then passed 32 tests; the reviewer
independently passed its three focused proof tests. Ruff and diff checks passed. Production
source remains byte-identical to reviewed `c8a78732`; only the guard and this handoff changed.
Final reviewed guard SHA-256:
`db2d97a5b132dc1477438cd66ecc6e7cf99dd43adeb81a946e3e6e8351adfc89`.

The existing receipt-reader census remains mandatory. The original hosted runs are failed
runs; their many passing tests do not make that head eligible to merge. Complete hosted gates
must pass again on the follow-up commit.

## Remaining gates and handoff

Before push, both public-repository privacy gates must pass on the final commit history.
Then require all hosted checks on the exact PR head, mark #580 ready, and merge with a merge
commit under the owner's authorization. CI conclusions and the tested head are authoritative
on the PR, not inferred from this local record. W2b integration and its single LF-preserving
fixture regeneration follow W2a's merge; its validation record stays on its own branch.
