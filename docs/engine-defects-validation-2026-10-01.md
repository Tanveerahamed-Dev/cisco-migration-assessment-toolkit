# W2b engine defects: validation and integration handoff (2026-10-01)

**Partial: local integration gates and independent reviews complete; exact-head hosted gates and merge remain.**
Branch: `fix/engine-contract-defects`, continuing interrupted checkpoint `3cb8891d`.
Design owner: `docs/engine-defects-design-2026-10-01.md`. Queue owner: `docs/NOW.md`.

## Result

- **G13:** the producer writes stable snapshot-local move-group labels. Consumers join on those
  labels and order multi-group values by the owner ordinal. Anonymous legacy rows retain their
  positional fallback; a mismatched written label cannot borrow another group's endpoint count.
  Ungrouped devices carry the shared unscheduled sentinel. Custom labels no longer crash NRFU.
- **G15:** one classifier owns unique/ambiguous/unobserved roots, with undetermined default
  election retained. PVST and MST remain separate through failover and readiness. Malformed
  evidence is preserved, numeric keys are bounded consistently, and no malformed token bypasses
  the owner. Workbook/design/NRFU/explorer consume the verdict, disclose actual claimant counts,
  and abstain visibly. The explorer's legacy mirror is parity-pinned and prototype-safe.
- **G49:** every dossier exposure carries its input state. A canonical capture record gates all
  config axes; sparse hygiene cleanliness requires an unambiguous successful parser receipt.
  Protocol cleanliness requires a validated receipt. Failed sections, malformed inputs, numeric
  overflow, ambiguous host aliases, and empty assessments fail closed. Context, pipeline,
  backend recomputation and golden recomputation pass the same inputs.

The SSOT registry names the owners. Presentation test fixtures now use real producers rather than
invented input shapes; the coverage and rendering assertions are retained.

## Decisive verification

- Initial related Python/Node-backed/backend selection: **1,022 passed**, one Starlette deprecation
  warning, exit 0. It covers the four new/checkpoint defect suites, VLAN/failover, endpoint/subnet/
  application intelligence, decisions, NRFU/MOP/design/architecture, workbook/explorer/STP,
  evidence pointers, dossiers/adapters/absence, SSOT, crash safety, review-round-two, deck,
  runbook, MCP, and the cutover label join.
- Additional current-producer wall-clock check: **1 passed**, exit 0; current dossiers agree
  across 2026 and 2027 without rewriting the deferred golden.
- Repository-wide `py -3.12 -m ruff check .`: pass.
- CI's exact eight-module mypy gate: pass.
- Frontend `npx --no-install tsc -p tsconfig.json --noEmit`: pass; no distribution regenerated.
- Independent read-only auditors replayed the concrete refutations. G13/G15's final residual
  selection: **19 passed**. G49's six initial review findings replayed successfully; its final
  input-state suite, including the overflow repair: **45 passed**.
- `git diff --check`: pass. No changes to `tests/golden/snapshot.json` or `webapp/sample_data/*`.

## Negative evidence and limits

### Additional full-suite check while waiting for W1

At source `e74a4c42`, the full default selection ran with four workers, `--dist loadfile`,
and `UPDATE_GOLDEN` unset. The completed JUnit report records **9,744 tests: 9,684 passed,
40 skipped, 20 failed, 0 errors**, in 1,892 seconds. Its SHA-256 is
`68a4802fb904e2d15dc0d03c1223626650cbce8840fb61fee697108e7445c536`.
The original XML and partial text log are preserved privately outside the repository.

The wrapper failed with `UnicodeEncodeError` while printing the completed failure tracebacks;
the child's terminal exit code was not captured. The child was no longer running and the XML
was complete. Counts above come from that XML, not from an inferred successful shell exit.
Subsequent focused commands explicitly use UTF-8 output. The golden, sheet schema, sample
builder and sample snapshot were separately verified byte-identical to their HEAD blobs.

| Failure group | Count | Disposition |
|---|---:|---|
| Listed worktree/graph context failures | 8 | Four guarded-Graphify receipt failures (`G017`), three graph-invariant failures, one `STANDALONE_GIT_DIRECTORY_REQUIRED`. Preserved; no guard or graph was changed. |
| Deferred golden/sample comparisons | 9 | Four pipeline golden tests, all three injected-registry-clock dossier comparisons, and sample detector-schema / architecture-review comparisons. Refresh remains held for #579 and W2a. |
| G49 duplicated protocol vocabulary | 1 | Fixed by consuming `_protocol_assessability_conclusion` rather than repeating receipt states. Seven real-capture/future-consumer cases added; the existing vocabulary ratchet is unchanged. |
| Invalid cutover-simulator STP fixtures | 2 | Non-root rows wrongly advertised a different incumbent. Corrected those two `root_address` values while retaining every assertion. Conflicting identities still abstain. No simulator production change. |

Independent verification after those repairs: **146 focused tests passed**, repository-wide
ruff passed, and `git diff --check` passed. The future-state tests isolate the already-validated
receipt boundary; they do not claim future producer/validator support. The full suite has not
been rerun after these small repairs, and no all-green full-suite result is claimed.

### Earlier evidence retained

- The inherited checkpoint's passing G13/G15 tests did not establish completion: G49 was absent
  and owner registration, malformed-input, namespace and renderer defects remained.
- Test-first failures were observed before repair: G49's initial 22 failures, 14 independent-review
  cases and two overflow cases; G13/G15's malformed-key, dropped-evidence, custom-label and
  renderer cases. The first broad related run had **711 passed / 2 failed** on obsolete explorer
  fixtures. Those fixtures were corrected and the final related selection passed; the earlier
  failure is retained here.
- Pipeline golden run with `UPDATE_GOLDEN` unset: **17 passed / 4 failed**. Failures:
  `test_snapshot_matches_golden`,
  `test_dossiers_do_not_depend_on_the_wall_clock_even_past_the_eol_registry_window`,
  `test_golden_does_not_depend_on_the_wall_clock_past_every_registry_window`, and
  `test_excel_sheet_schema_matches_golden`. Fixture refresh waits for #579 and W2a integration.
  The new current-producer clock check supplements these failures; it does not replace them.
- A separate expanded, report-only mypy invocation produced **328 diagnostics in 10 files**.
  The new helper's narrowing error was repaired; the wider report remains untriaged and is not
  represented as a green gate. CI deliberately gates eight other modules.
- An all-green full suite, archive build, final hosted W2b checks and merge are **not verified**.
  The additional full-suite run above preserves the board's eight context failures as failures.
- Graph navigation used the canonical checkout as a lead. No graph/vault refresh, W1 branch,
  W1 folder, device, release, qualification, signing or publication action was performed.
- Initial mandatory privacy verifier: **failed** on pre-existing untracked `.codex/hooks.json`
  containing absolute machine paths. The owner subsequently approved the six-command path-only
  repair and branch push. The repair is now applied; the repository verifier and history marker
  scan both pass. Fresh successful gate reruns are required immediately before publication.
  `.agents/` and `.codex/` remain preserved and excluded from staging.

### Approved local hook-path repair

The configuration has six absolute script paths (the initial approval question said seven):
`vault-guard.sh`, `vault-guard-bash.sh`, `session-brief.sh`, `scorecard-append.sh`,
`verify-green.sh`, and `graph-refresh.sh`. Git Bash resolved this worktree's root from both
the root folder and `docs/`; all six targets are readable and byte-identical to their existing
`.claude/hooks/` counterparts. No hook was executed.

The applied replacement for each command is the following, with `SCRIPT` replaced by its
existing filename. Root/path resolution failures remain nonzero for every hook; the script's
own exit code propagates. No matcher, timeout, status message, script bytes, or working
directory changes. A byte-identical backup and repair receipt were saved outside the checkout;
independent structural and textual comparisons confirmed exactly six command-value changes.
The configuration remains untracked. Repository-root resolution follows the
[official hook guidance](https://learn.chatgpt.com/docs/hooks).

```sh
_atlas_hook_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 2
[ -f "$_atlas_hook_root/.codex/hooks/SCRIPT" ] && [ -r "$_atlas_hook_root/.codex/hooks/SCRIPT" ] || exit 2
bash "$_atlas_hook_root/.codex/hooks/SCRIPT"
```

This preserves the existing `bash` dependency. Bare `bash` was absent from the PowerShell
probe's PATH; actual hook-runner resolution is not verified. The scripts' existing internal
fail-open conditions are not changed or represented as closed. In particular, do not execute
`session-brief.sh` for validation because it reads the vault log. Static inspection confirms
the graph-refresh hook stops at this linked worktree's `.git` file before graph mutation.

### Post-merge verification complete for docs-only #581

On merged #581 commit `497e26b653d2053aaefc8ab8381c921c68ba7321`, hosted CI run
`36858426410` and Master Reference run `36858426344` both completed with **success**.
These results apply to that docs-only merged-main source, not the unmerged W2b implementation.
W1 has advanced to `0345eb1d`, but #579 remains open; W2a and final W2b integration still wait.

## Earlier integration sequence (superseded by the board)

Read-only W2a preflight found the clean listed checkout at `d0a9737a`. No W2a edits or
tests ran before #579. These are concrete integration checks for the existing W2a/W2b rows:

- In `ui_projection.py`, `_finding_row` / `_findings` and their closed schema must carry
  `evidence_refs`, `evidence_basis`, and optional `evidence_refs_total`. The I23 tripwire also
  names that total. Remove the no-pointers limitation only when the producer supplies evidence.
- `_device_page` / `DeviceHealth` must carry `deduction_refs` as the producer's ordered
  subsequence, never positionally zip it with deduction text.
- During W2b integration, `_RECORD_SLOTS["exposure"]` must preserve `input_state`; the slice-2
  version currently drops it. VLAN projection/schema and election preconditions must consume
  the new owner verdict instead of the old first-claimant/integer-only reconstruction.
- The slice-2 source assertion that move groups have no labels needs a legacy-aware replacement.
  Inventory `DeviceRow` currently has no `move_group` field; complete that G13 consumer when
  the new producer is integrated. These omissions are source observations, not runtime results.

1. The owner authorizes publishing `fix/engine-contract-defects`. Rerun the privacy verifier,
   scan every `origin/main..HEAD` commit message and patch with `_client_marker_patterns()`,
   and gate the push on both exit codes. Keep local hook configuration untracked.
2. W1's owning session updates and merges #579; this session does not modify that workstream.
3. In the listed W2a folder, merge main with a merge commit, project the three evidence fields,
   run all gates, make #580 ready, and merge only its green exact head.
4. Merge main into W2b with a merge commit. Regenerate golden, sheet schema and sample once;
   normalize to LF, review `git diff --ignore-cr-at-eol`, rerun all gates, then open/merge W2b
   only when the exact head is green. Check newly added dossier input-state projection and
   the Scope fixture assumptions named in the design during that integration.
5. W2c follows the board. Its branch/folder are not yet listed; obtain that concrete listing
   before creating either.

Docs-only #581 was independently scope-checked and merged after all required checks passed:
head `6a817777c7e2e1b4aacde937c68994ee9d306ea3`, merge
`497e26b653d2053aaefc8ab8381c921c68ba7321`. The merged tree equals the tested head tree.

## Integration after W2a merge (2026-10-01)

#579 and #580 are merged. W2a's final head `1e6268f3` passed all required hosted gates and
merged as `8000adce`, with exact tree equality. W2b merged that main revision in merge commit
`60d97d26`, preserving `f950f888` as its other parent. Only `docs/NOW.md` conflicted; every
handoff line from both parents was retained and the completed W2a active row was removed.

The merge-relative whitespace check reported the imported `tests/test_ssot_owner_robustness.py`
file's 838 CRLF lines. Its indexed bytes equal main exactly; the staged W2b diff against main
passed `git diff --check`. The imported file was preserved rather than normalized as unrelated
work. This is separate from the required LF-only regeneration of generated fixtures.

Before the single regeneration pass, reconcile all three producer changes in the projection:
exact move-group identity, published STP election/metadata with honest legacy/default states,
and exposure input-state preservation. Independent refutation follows. Scope's absence controls
must remain exercised when real findings gain wave labels. The golden source digest and measured
expectations are updated only after regenerated data has been reviewed; a digest-only refresh
is insufficient. No W2b golden/sample/Scope regeneration has run at this integration checkpoint.

The board reserves `codex/core-screens` in the existing UI-projection checkout for W2c after W2b
merges. That branch has not been created. Backend typing/pagination and reference-source notes
are retained in `docs/one-app-w2-integration-preflight-2026-10-01.md`.

### Reviewed consumer source before regeneration

The projection now preserves exact move-group labels/membership, consumes the STP owner's
tri-state verdict and metadata, and carries dossier exposure input states. It withholds
contradictory or ambiguous pointers instead of choosing a claimant or correcting a risk state.
Readiness retains its engine-owned scope: an ambiguous cross-switch root can coexist with a
valid published readiness verdict. Closed schemas and producer-vocabulary parity remain enforced.

- Post-merge engine selection: **178 passed**, exit 0.
- Final projection author selection: **307 passed, 1 deselected**, exit 0. The deselected
  producer-signature/sample comparison must run after the sample acquires the four STP fields.
- Independent final-source review: no actionable residuals; **70 regression tests passed**,
  plus 186 exposure-state/legacy controls, six label/membership controls, nine numeric/null/
  serialization-pointer controls, and duplicate-row/readiness/phase-precedence probes.
- Scope absence controls now use explicit synthetic inputs; **162 passed, zero skipped**.
  No generated fixture or golden digest was changed in this source-freeze step.
- Ruff and diff checks pass. Reviewed `ui_projection.py` SHA-256:
  `79e64599f78e168dd0f3a2b83b5570c166510f69aed77fc780699f5920cd8639`.

These focused passes do not replace the pending regeneration, all applicable integration gates,
hosted full matrix/coverage/distribution checks, or exact-head merge verification.

### Single regeneration and reviewed content

Source was frozen as `e4be15f1`. The two selected golden writers shared one offline pipeline;
the sample builder ran once with its pipeline return code checked; Scope's atomic compiler ran
once against that sample. All seven generated files retain LF bytes. No top-level golden or
sample sections were removed. Sample SHA-256:
`e63d7facd9a6b6e937a2c13ecb8e04692eb955ec66573d39928a5f372eff9dd7`.

The golden writer initially returned **1 passed / 1 failed**: its shrink guard classified the
Risk Register's changed summary banner as a removed header. Independent review verified the
saved workbook and exact schema candidate: all 74 sheets, order, row widths and 17 Risk Register
columns remain. Only `COVERAGE: 11 of 33` becomes `10 of 33`, because access1's successful empty
hygiene parser receipt now supports `ok / collected_but_empty`. The exact saved candidate
(`5b9d597ec3d7eb01e03108da6795cca2db47cfd8dec2232df0c66cc91c3e03ac`) was accepted through the
existing documented `ALLOW_GOLDEN_SHRINK=1` review path. No second pipeline generation or guard
change occurred. The original failed receipt remains preserved.

Independent golden review found 49 expected additions: 33 input states, 12 STP metadata fields,
three ambiguity counts and one move-group label. Golden risk/compound summaries and 41 finding
rows remain. Sample findings change from 146 to 140: five unsupported root-on-degraded-hardware
compound findings disappear; two conflicting VLAN-root findings are replaced by one ambiguity
finding carrying all 17 claimants. Scope's measured golden assertions are updated with that
content, not only a digest. Earlier Scope acceptance reports remain historical measurements;
their old finding IDs/counts do not establish current visual acceptance.

Independent sample review reconciled all 17 changed sections: all 118 sections and 23 devices
remain; 807 evidence references (587 finding references) resolve, and `ssot.reconcile()` reports
no discrepancies. Removing unsupported root impact bonuses changes Severe/Elevated counts from
14/4 to 4/14 and average risk from 44 to 40; health and exposure scores remain unchanged. All
253 exposure records gain input custody. Validation retains 164 cases and NRFU retains 317,
replacing 17 unsupported root expectations with explicit ambiguity/review disclosure. The
unchanged pod access-switch narrative still says routine handling with 9/11 unassessed axes;
that carried limitation is outside this repair's exposure-state scope and is not claimed fixed.

Current local integration evidence:

- Projection, protocol guard, golden guard/drift and sample selection: **665 passed**, no skips
  or deselections, exit 0. This includes the formerly deferred producer-signature comparison.
- Full sample freshness rebuild/check: **pass**, with mandatory pipeline return-code validation;
  tracked sample bytes were not rewritten by the check.
- Full pipeline golden suite with update mode unset: **22 passed**, no skips, exit 0, including
  schema equality and injected future-clock checks.
- Repository-wide Ruff and the eight-module mypy gate: **pass**.
- AssessHub frontend: **274 unit tests passed**, build passed, and all tracked distribution
  bytes remain identical. Browser E2E: **5 passed, 1 existing opt-in performance skip**.
  Visual TypeScript passed; **22 visual browser tests passed** without baseline updates.
  Scope standalone and hub builds passed.
- Backend selection with all three `ATLAS_SCOPE_REQUIRE_*` switches enabled: **1,224 passed,
  1 skipped**, exit 0. The skipped out-of-root file-symlink test needs a Windows privilege absent
  on this host; the Linux hosted gate must execute it. One existing Starlette deprecation warning.

Scope's final complete unit suite: **6,992 passed, 1 skipped, 0 failed** across all **224 files**,
exit 0. The JSON report identifies the skip as the sample-inapplicable no-route preset case
described below. Exact-head hosted checks and merge remain pending. Prior full-suite failures
are retained above.

The first post-regeneration Scope run is also retained as negative evidence: **6,984 passed,
8 failed, 1 skipped**, exit 1 (219 passing / five failing files). All eight failures are stale
sample-count/ID assertions across DevicePane, PriorityQueue and EvidencePane tests. They are
being reconciled by matching the old and new finding content; behavioral assertions and
synthetic absence controls remain required. This initial run is not a passing verdict.
After the measured updates, all **759 tests in 11 affected files passed**, without skips, and
Scope typecheck passed. The final full run also passed as recorded above. Its existing no-route suggestion skip is
inapplicable to this sample, which offers no such preset; a separate counterfactual suite
exercises that branch.

Independent review of the frozen 12-file Scope test/support set found no actionable issue.
It remeasured every changed count and matched 21 changed finding-ID pins by severity, category,
title and device membership. No skip/only/todo was added and no behavior assertion relaxed.
The four former conditional absent-wave query tests now always run on isolated synthetic data;
Inspector continues to exercise actual null rendering. Sample bytes, `GOLDEN_SHA` and all four
compiled binding envelopes agree, and the fail-closed digest guard remains intact.

After all local gates, the reviewed source, all 12 Scope test/support hashes and all seven
generated-file hashes are checked again before commit. Repository privacy and the complete
new-commit marker scan must pass immediately before publication. Hosted full Python matrix,
coverage, distribution/portable and Master Reference gates still bind the eventual PR head;
local results do not stand in for those checks.

### Publication

Repository privacy and the complete new-commit marker scan passed before pushing `087b00c8`.
The marker scan covered all ten commits outside main, including intermediate changes, and
2,104,617 bytes of messages/patches with no matches. PR #583 is open against main `8000adce`.
Hosted checks are running; the final head, including this board/receipt update, requires fresh
successful privacy gates before its push and successful applicable hosted checks before merge.
