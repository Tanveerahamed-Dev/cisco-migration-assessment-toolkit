# W2b engine defects: validation and integration handoff (2026-10-01)

**Partial: implementation and related validation complete; integration and push remain gated.**
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

- Final related Python/Node-backed/backend selection: **1,022 passed**, one Starlette deprecation
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
- The full suite, archive build, final hosted W2b checks and merge are **not verified**. The board's
  eight linked-worktree environmental failures were not rerun or silently counted as passes.
- Graph navigation used the canonical checkout as a lead. No graph/vault refresh, W1 branch,
  W1 folder, device, release, qualification, signing or publication action was performed.
- Mandatory privacy verifier: **failed** on pre-existing untracked `.codex/hooks.json` containing
  absolute machine paths. No push attempted. A narrow local hook-path repair is awaiting owner
  approval because the board does not list that tooling change. `.agents/` and `.codex/` remain
  preserved and excluded from staging.

## Exact next action

1. If authorized, repair only the local hook script paths with a backup and prove equivalent
   Git-root resolution. Rerun the privacy verifier, scan every `origin/main..HEAD` commit message
   and patch with `_client_marker_patterns()`, and gate the push on both exit codes.
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
