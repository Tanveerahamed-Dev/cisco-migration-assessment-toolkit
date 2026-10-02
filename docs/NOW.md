# NOW: the one live work board

This file is the single tracked answer to four questions: **what are we building right now, on
which branch, who holds it, and what is next.** Every session reads it first and updates it last,
whether it runs in Claude Code or Codex.
- Dated plans, handoffs, chats and agent memories are history, not work queues (see the precedence
  list in root `AGENTS.md`).
- Where this board and live Git disagree, live Git wins. Correct the board in the same change.
- Read the board from `main` (`git show origin/main:docs/NOW.md`). A work branch's copy may be
  behind.

Last reconciled: **2026-10-02** (Codex). Reasoning behind the current direction:
`docs/ui-direction-verdict-2026-09-29.md` (dated record).

---

## The one product

There is **one application**: the `main` branch of this repository on GitHub.

- **Intelligence (target):** the Python engine (`cisco_toolkit/` + `COLLECT_PARSE_V3_23_0.py`)
  must become the only owner of every analysis fact. Screens render engine output; they never
  invent, restate or default a fact (`docs/ssot.md`). Some screens still compute facts
  themselves; see the dated verdict.
- **The one door:** AssessHub (`webapp/`). Atlas Scope (`atlas-scope/`) is its integrated
  preview 3-D investigation module.
- **Other surfaces:**
  - The engine HTML explorer stays an offline deliverable.
  - Atlas (`portable/`) packages AssessHub for the USB stick.
  - `master-reference/` and the MCP server are existing derivatives, not further products.
- **Not allowed:** a new app, repository, product line or long-lived parallel branch.

## Working rules (Claude Code and Codex alike)

1. **`main` is the application.** Work that is not merged into `main` does not exist yet.
2. **Work only on a branch listed in the Active table below.** New work gets its row in the same
   pull request as the work. Never use an unlisted branch, worktree or project.
3. **One writer per workstream: the "Held by" column.** Do not edit a branch another row holds.
   To take over, record the handoff in the log below.
4. **Start of a session.**
   - Run `git fetch`, then read this board from `main`, root `AGENTS.md` and `CLAUDE.md`.
   - **Work in the checkout that already has the row's branch.** Git refuses to check out one
     branch in two places.
   - In the Codex app, open that folder as the project and use **Local** mode there. Do not start
     a new Worktree thread: each one begins on a detached copy per chat, and that is how the old
     copies piled up ([Codex worktrees](https://developers.openai.com/codex/app/worktrees)).
   - If the checkout is on a branch not in the table, or `git status` shows edits you did not
     make, stop and record it here. Do not build on them.
5. **End of a session, including when a quota is about to run out.**
   - Commit to the row's branch (never directly to `main`).
   - **Push only with the owner's explicit authority for this session** (root `AGENTS.md`), and
     never for a row marked local-only. Rule 7 applies first. If you did not push, say so in your
     handoff line: the work then exists only on this machine.
   - Update the row's Status and Next columns, and add one handoff line.
   - Board edits ride in the work's own pull request. On a conflict in this file, keep every
     handoff line and the newest Status per row.
6. **Merge small and often.** Open a pull request, preserving merge commits (`CLAUDE.md`, *Shared
   Git and host operating doctrine*), and ask the owner to merge within a few days. Never leave a
   week of work on one laptop only.
7. **The repository is public.** Before the first push of any branch:
   - Run `py -3.12 -I -B .github/scripts/verify_repository_privacy.py --root .` (it checks the tip
     tree and index only).
   - Scan every new commit's message and patch (`git log -p origin/main..HEAD`) with
     `cisco_toolkit.distribution_verify._client_marker_patterns()`. Intermediate and imported
     commits are published too.
8. **When a row's pull request merges,** the next session deletes the row and adds a handoff line.

## Active workstreams

| # | Workstream | Branch | Held by | Status (as of) | Next step |
|---|---|---|---|---|---|
| W0 | Main checkout hygiene | main checkout on `codex/atlas-master-reference` (already merged, behind `main`); its uncommitted edits are preserved at `refs/preserved/main-checkout-wip-20260929` | owner | Sessions started there load an old `CLAUDE.md` that does not mention this board (2026-09-29) | Owner: keep or drop the preserved edits, then switch the main checkout to `main` once W1 no longer needs its launch configuration |
| W5 | Atlas Scope preview-scope repairs: the D3 citation-path clipping, the `/scope` reader, the C1 KEY validator, engine-owned display vocabularies and bundle receipts, then the C1 critic panel and an independent 39-criterion re-grade | `claude/scope-preview-fixes` (pushed), against `main` | Claude Code session in the `.claude/worktrees/scope-preview` checkout | PR #582, with `main` merged in again after #583 and #584 (2026-10-02). C1 panel ran: UNPROVEN, protocol limit (O70). D3: no complete audit is tractable on this host, so UNPROVEN (O68). The first re-grade lost 35 of 39 graders to the account usage limit. Residuals in `atlas-scope/docs/open-issues.md` O78. | Re-grade this head, record the report, then the owner reviews and merges #582, preserving merge commits. |
| W2c | Backend endpoint and first core screens | `codex/core-screens`; existing `.claude/worktrees/ui-projection-2` checkout; [PR #584](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/pull/584) | Codex | Application and portable gates passed; hosted full suites found three integration failures in Design inventory, the npm test entry and LF custody receipt. Corrections pass locally with unchanged guards and byte-identical app output; review/publication follows. [Validation](one-app-w2c-validation-2026-10-02.md). (2026-10-02) | Publish the reviewed integration corrections after both privacy gates, then require all checks on the latest head before readiness/owner merge. Reference capacity remains gated (322,332 bytes locally at `c5519bdf`). No further golden/sample regeneration. |

## Owner decisions

**Decided 2026-09-30** (full record and reasoning: `docs/decisions/0007-one-application-direction.md`):

- **D0: Release 1 is frozen as a draft candidate.** The UI program proceeds on `main`. The next
  release candidate is cut from `main` after the core-screens milestone (P3).
- **D9: Facts in Python, geometry in the browser.**
  - Every on-screen fact comes from the engine through a typed projection
    (`cisco_toolkit/ui_projection.py`).
  - Scope's compiler owns only 3-D geometry, layout and visual encoding.
  - Browser-side and webapp verdict logic become renderers or are parity-pinned.
- **D10: Raw evidence is retained, secret-scrubbed.**
  - Retention happens only after the engine's raw-capture scrubber runs and the independent
    verifier proves the capture clean.
  - A retention indicator and a per-campaign purge are shown.
  - Implementation waits for W1 to merge (`webapp/backend/ingest.py` is on its freeze list).
- **D11: Publishing the Atlas Scope branch is approved.** The W1 holder pushes and opens the PR
  after phase 3.5 is committed, the rule-7 checks pass, and the remaining FAIL items are listed as
  preview scope.

**Still open, owned by `CLAUDE.md` and not restated here:** the carried-forward review-tail items,
publishing the master-reference site, and the Claude Design pixel-baseline promotion.

## Handoff log (newest first)

- 2026-10-02, Codex (W2c hosted integration corrections):
  - The completed Linux jobs at `2525e58b` agree on three failures; none is a linked-worktree exception. The webapp, CodeQL, dependency/distribution and portable-build gates passed on that head.
  - Kept the public Design inventory and canonical `vitest run` contract intact: moved application-only helpers into the feature folder and gated generation-policy tests through `api:check`. Reconciled the LF receipt to the exact two new backend files without changing owner/attribute policy. Focused guards, 306 frontend tests, nine policy tests and 14 custody tests pass; runtime app bytes and generated types are unchanged.
  - Independent review closed all three corrections, including failing-policy short-circuit, a rejected undeclared public component, and omitted/extra/swapped LF-path counterexamples. The follow-up needs fresh privacy gates and exact-head CI. Earlier failures and partial/cancelled runs remain distinct evidence. Protected fixtures and W1 remain untouched.

- 2026-10-02, Codex (W2c published):
  - Pushed `c5519bdf` after the repository privacy verifier and full four-commit marker scan both exited zero; opened draft #584. The endpoint, generated types, core screens, evidence drawer and portable runtime are implemented and independently reviewed. Required hosted CI must close on the final head before readiness/merge.
  - Closed the JSON-native/finite HTTP refutation with 89 focused passes, independent negative/positive replay, 1,281 full backend passes and fresh frozen smoke. Closed the four reference architecture edges by using the existing adapter and relocating the exporter; no architecture policy changed. The complete reference build and its existing size gate passed with 322,332 bytes of headroom at `c5519bdf`.
  - This documentation handoff follows the implementation without changing app/runtime bytes. Fresh privacy gates remain mandatory for its push. The generated root test cache remains untracked after automatic approval review rejected cleanup; it is excluded from publication. W1 and golden/sample/Scope data remain untouched.

- 2026-10-02, Codex (W2c local validation and final boundary probe):
  - Committed the endpoint/runtime checkpoint as `a4c898a9`; no W2c push or PR yet. Core screens now consume generated engine-contract types and preserve source-bound evidence, withheld rows and exact reference joins. Final frontend gates: 306 unit tests, nine generator-policy tests, six E2E passes with one existing opt-in skip, and 22 unchanged visual comparisons.
  - Independent review closed wrong-host/stale-context pagination, stale evidence identity, retry-offset, interface-order, Scope-link normalization and offline-generator resource-resolution findings. Live browser checks covered the actual synthetic-fleet app, drawer keyboard behavior and corrected 390-pixel layout. The full UI-bearing frozen smoke passed.
  - A later producer-fault probe showed a published NaN could escape the actual HTTP boundary as null despite direct model rejection. Publication remains held for explicit JSON-native/finite guards, independent replay and fresh backend/frozen evidence. Earlier successful paths remain scoped in the validation record; no golden/sample regeneration or W1 changes.

- 2026-10-02, Codex (W2b merged / W2c started):
  - All 15 required checks passed on `b2c13407`; all 28 check runs were terminal (26 successful, two inapplicable draft-publication jobs skipped). Merged #583 with the authorized exact-head merge command as `a0c727bd`. Main's tree `b2adece2e21c4ea44f2eae0c009c0a92ae882b49` equals the tested head. Removed W2b's row under rule 8.
  - Final local complete Master Reference deployment, including its outer receipt: 256,488,364 bytes, with 3,558,484 bytes of headroom under the unchanged limit. Hosted Master Reference validation also passed; exact receipts and residual limits are in the W2b validation record. Golden/sample/Scope fixture bytes retain their single reviewed generation.
  - Created the already-listed `codex/core-screens` branch from current main in the clean existing UI checkout. Backend owns only contract transport and exact-store binding; the engine remains the fact owner. Implementation order remains endpoint, independent contract validation, then core screens. W1 and the protected root checkout remain untouched.

- 2026-10-02, Claude Code (W5):
  - #582's two red checks (Windows tests and the full source/frontend gate, both on `windows-2025`) were one test:
    the `/scope` XML-asset source scan read every quoted string as an import, and the hosted Windows registry types
    `.config` as XML, so the command id `select.config` was flagged there and nowhere else. The scan now counts only
    path-shaped references or references to a real file, covers the package's HTML entries, and a new test pins it on
    every host by forcing `.config` into the suffix set. A mutation that restores the old behaviour fails it.
  - Merged `main` after #583 (`a7016984`); conflicts in `analyze.py` and this board resolved by keeping both sides.
    The sample fleet is fresh against the merged engine.
  - The first re-grade (`b342a05d`) lost 35 of 39 graders to the account usage limit; it is re-run on this head.

- 2026-10-02, Codex (compaction source freeze):
  - Closed the metadata-string numeric overflow refutation and generated-decoder EOL drift test-first. Final projection suite: 90 passed / one existing POSIX-only skip; TypeScript, lint and diff checks passed.
  - Independent bounded review and a repeated all-chunk payload/gzip comparison preserve record values, ordering, indexes, digests, text and terminators. The original chunk partition and limits remain. The explicit pre-existing legacy fallback key limitation is recorded rather than claimed repaired.
  - Full deployment size is still pending. Source-chunk savings alone are not a successful deployment gate. Golden/sample/Scope fixture bytes remain unchanged.

- 2026-10-02, Codex (approved W2b compaction):
  - Owner approved the pending bounded lossless Master Reference compaction request. It is now part of W2b on the existing branch and checkout.
  - Scope: existing projection encoder/generated decoder, round-trip and hostile-input tests, documentation and exact-source rebuild validation. Public payloads, all source records/text/digests/terminators/census denominators, the decoded 256 KiB ceiling and the existing deployment/privacy gates stay intact. Net savings must be measured after decoder and receipt overhead.
  - No additional golden/sample regeneration, W1 changes, new branch/worktree, release publication or qualification authority is included. W2c follows the already reserved route after #583 merges.

- 2026-10-01, Claude Code (W1, closing):
  - #579 merged as `d92fcb1f` on the owner's instruction, after every required check was green on head
    `0345eb1d` and `main`'s tree was confirmed equal to that head's. Row W1 deleted (rule 8).
  - The W1 branch and its worktree stay until #582 lands; the main checkout's launch configuration still
    points at that worktree (W0).
  - #582 (W5) retargeted to `main` while open, and `main` merged in.

- 2026-10-01, Claude Code (W5):
  - Ran the W5 repair wave and its W5b follow-up, each with independent verifiers and refuters.
  - Re-ran the engine gate after a network drop killed it mid-wave.
  - A whole-branch refuter found no blocker or major; its minors are fixed or recorded in O78.
  - Pushed after the rule-7 checks passed (0 hits over 50 commits since `main`) and opened #582, stacked on #579.

- 2026-10-01, Codex (W2b Master Reference capacity gate):
  - The final-head Master Reference run `36918999658` passed compiler/schema validation and 264 contract tests, then failed deployment finalization. Its public error is intentionally redacted; there were no retained CI artifacts.
  - Reproduced from the same tracked tree and compiler census locally. The compressed deployment is 260,473,519 bytes before its outer receipt, exceeding the unchanged 260,046,848-byte limit by 426,671. The private existing diagnostic confirms the aggregate-size rejection. No tracked source or fixture changed during reproduction.
  - Requested owner approval for lossless projection compaction because the earlier board assigns that follow-up to its owner and the current W2 queue does not list it. No compaction edits, budget increase or coverage reduction have been made. Remaining CI is allowed to finish; the PR is held.

- 2026-10-01, Codex (W2b PR publication):
  - Repository privacy passed; the complete marker scan passed across all ten new commits and 2,104,617 patch/message bytes. Pushed `087b00c8` and opened #583 against main `8000adce`.
  - Hosted Python, coverage, distribution, portable, Master Reference and UI checks are in progress. This board update records the publication; its final head must receive its own successful checks before the authorized merge. W2c remains held until that merge.

- 2026-10-01, Codex (W2b single regeneration):
  - Regenerated golden, sample and four Scope bindings once from reviewed source `e4be15f1`, preserving LF. Independent review reconciled the finding/risk changes and all 807 sample evidence references.
  - The sheet guard initially rejected a summary-banner count change. Review proved all 74 sheets and columns unchanged; accepted the exact saved candidate through the documented reviewed-change path without rerunning the pipeline. The initial failure is retained.
  - Projection/sample 665 tests, golden 22 tests, frontend 274 unit tests, five E2E tests and 22 visual checks pass. Backend: 1,224 passed / one Windows privilege skip. Final Scope: 6,992 passed / one sample-inapplicable skip; independent review verified every remapped assertion without weakening coverage. Earlier failures are preserved. No hosted W2b or merge pass is claimed.
  - Integration is committed on this branch for publication, gated by fresh repository privacy and complete new-commit marker checks. Next: open W2b's PR and await the exact-head hosted gates before the authorized merge.

- 2026-10-01, Codex (W2b consumer source freeze):
  - Closed the projection's G13 labels, G15 owner metadata/pointers/readiness scope and G49 input-state handling test-first. Independent final-source refutation found no residual actionable defects.
  - Engine selection: 178 passed. Projection selection: 307 passed with one sample-signature check deferred until regeneration; independent regression replay: 70 passed. Scope synthetic absence controls: 162 passed, zero skipped.
  - Consumer integration is committed locally before the one regeneration pass; no protected fixture has been regenerated. Fresh privacy gates are required before the next push.

- 2026-10-01, Codex (W2a merged / W2b integration):
  - Marked #580 ready after all 15 required checks passed on `1e6268f3`; the applicable webapp and CodeQL checks also passed. Merged with the authorized merge-commit command as `8000adce`. Its tree `3a99bc64d24b5892d4880810ab59a2da3c0280ab` equals the tested head's tree. Removed W2a's active row under rule 8.
  - Merged current main into the existing W2b checkout. The only conflict was this board; every handoff line from both parents is retained. W1's branch/folder remain untouched.
  - W2b now owns projection/Scope consumer reconciliation and the single fixture-regeneration pass. Reserved W2c's concrete branch and existing folder here before creation; it starts only after W2b merges.

- 2026-10-01, Codex (W2a hosted gate):
  - Pushed implementation `c8a78732` after repository privacy and all seven new commits' marker scans passed. Updated draft #580 to its complete scope.
  - Five completed Linux full-suite jobs found the same sole receipt-reader classification gap. The projection's section-level dependency needs a mechanical SSOT-delegation proof; the guard remains mandatory. The scoped correction now passes the final 32-test protocol suite and independent refutation, including later-row, aggregate and shadowing counterexamples. Production source is unchanged.
  - The full local coverage cancellation and hosted failure receipts remain explicit in the validation record. W2b integration still waits for #580 to pass and merge.

- 2026-10-01, Codex (W2a evidence integration):
  - Projected finding evidence and health deduction references with closed schemas, owner-vocabulary parity, cap disclosure, source-failure precedence and legacy handling. Independent review closed the refutations; final focused and frontend results are in the validation record.
  - The instrumented full local suite was cancelled incomplete at about 38% after 1,628.78 seconds. Seven reported failures remain unclassified; no full-suite or coverage pass is claimed. Required hosted CI must close those gates before #580 is ready or merged.
  - Golden, sample-data and frontend distribution bytes were preserved. W2b remains pushed through `f950f888`; its consumer repairs and regeneration wait for #580.

- 2026-10-01, Codex (W2a):
  - Verified #579 merged as `d92fcb1f`; its tree equals tested head `0345eb1d`. Removed W1's active row under rule 8; its branch, checkout and follow-ups remain with their owner.
  - Merged current main into the existing `feat/ui-projection-slice2` checkout with a merge commit. Preserved every handoff entry from both sides of the board conflict.
  - W2b is pushed through `f950f888`: engine fixes and full-suite refutations are saved on that branch. W2a now owns evidence-reference projection and its gates; W2b integration/regeneration follows W2a's merge.

- 2026-10-01, Codex (W2 full-suite refutation):
  - Full JUnit result at `e74a4c42`: 9,684 passed, 40 skipped, 20 failed. Classified eight listed context failures, nine deferred golden/sample comparisons, and three actionable failures. The log wrapper's Unicode printing failure is preserved in the validation record; the completed XML is the count source.
  - Closed the three actionable failures: G49 now consumes the protocol conclusion owner; two simulator fixtures now describe a consistent incumbent root. All assertions retained. Post-fix focused suite: 146 passed; repository-wide ruff and diff checks pass.
  - No golden/sample regeneration. #579 checks are green but it remains unmerged under W1 ownership. W2a implementation still waits; read-only API and prototype-source preflights are in `docs/one-app-w2-integration-preflight-2026-10-01.md`.

- 2026-10-01, Codex (approved W2 publication):
  - Owner approved the six-command path-only repair and push of `fix/engine-contract-defects`. Repaired only the untracked hook command values, preserved an external local backup, and independently verified six syntax checks plus 12 path-resolution probes; no hooks executed.
  - Repository privacy verifier and full new-commit message/patch marker scan passed. Publication is authorized and gated on fresh successful reruns; local tooling stays untracked.
  - #581 exact-main CI `36858426410` and Master Reference `36858426344` both completed successfully on `497e26b6`.
  - W1 advanced to `0345eb1d`; #579 remains unmerged. W2a implementation and W2b golden/sample regeneration remain held for its merge.

- 2026-10-01, Codex (W2 blocked audit):
  - The same hook-repair approval and W1 merge dependency remain after three consecutive goal turns. #579 is still open/behind; the local hook marker is still present. Goal marked blocked, not complete.
  - The fixes and handoff are committed locally; no push is permitted until the mandatory privacy verifier passes. The existing approval request remains pending.
  - Stopped only the two local `gh run watch` clients. Hosted #581 main runs `36858426410` and `36858426344` remain live; query their terminal verdicts on resume. No W1 or fixture changes.

- 2026-10-01, Codex (W2 continuation):
  - Re-fetched and confirmed #579 remains open/behind; #581 is merged, with exact-main CI run `36858426410` and Master Reference run `36858426344` still live.
  - Prepared and independently reviewed the six-command hook-path repair read-only; approval remains pending. No hooks were executed or modified. Concrete replacement and limits are in the W2b validation record.
  - `ebb5a368` and this handoff remain local only; the mandatory privacy failure still prevents push. No new implementation or fixture changes.

- 2026-10-01, Codex (W2):
  - Merged docs-only #581 at `6a817777` after every required check passed; merge `497e26b6` has the tested head tree.
  - Took over W2b, finished G13/G15/G49 test-first and closed independently reproduced refutations; 1,022 related tests pass. Details and preserved negative evidence: `docs/engine-defects-validation-2026-10-01.md`.
  - No golden/sample refresh and no W1 branch/folder changes. #579 remains open/behind main; W2a and the W2b integration/PR wait for its owning session.
  - Fixes are **local only, not pushed**: the required privacy gate rejects pre-existing untracked `.codex/hooks.json`. Requested approval for a path-only local repair; `.agents/` and `.codex/` were preserved and excluded from staging.

- 2026-10-01, Claude Code (W1):
  - Made #579's CI honest. Each red check was fixed at its root, with a test that fails without the fix:
    - a cross-drive `relpath` in a test helper;
    - a case-folding test that assumed the file system;
    - CodeQL;
    - the master-reference contract, its allowlist, its TypeScript resolution and its size bounds.
  - The CodeQL finding led to a snapshot-name defect class that three independent refuters widened until it was
    closed by structure.
  - `atlas-scope/` is censused at identity depth in the master reference, with a named BLOCK category. The
    reference's deployment bundle is at 256 of 260 MB. Compact per-line encoding is urgent for its owner.
  - The required dependency audit now covers every tracked npm lockfile.
  - Merged #578. Regenerated the demo fleet and re-bound Atlas Scope to it.
  - Pushed. The owner lifted "finish 3.5 only" in chat; that preview-scope work is row W5, stacked on this branch.

- 2026-09-30, Claude Code (W1):
  - The owner confirmed D11 in the W1 session. Phase 3.5 is committed, and `main` is merged in (#573, #574,
    #575, #577).
  - Found while merging, and fixed in the branch:
    - The assessability guard now tells #575's census vocabulary apart from the receipt's.
    - Importing the engine no longer opens its audit log, which removes the `-n auto` collection
      `PermissionError`.
  - Rule-7 checks passed. Pushed the branch and opened #579 with the preview scope listed.

- 2026-09-30, Claude Code:
  - Merged #574 (npm advisories), #575 (engine honesty) and #573 (this board + ADR 0007); deleted
    rows W3 and W4 (rule 8).
  - Opened #577 (`ui_projection/1` slice 1).

- 2026-09-30, Claude Code:
  - The owner delegated D0/D9/D10/D11 with full authority; recorded in ADR 0007.
  - Opened #574 to clear new npm advisories, which were failing a required check for every pull
    request.
  - W2 started.

- 2026-09-30, Claude Code:
  - Merged #577 (`ui_projection` slice 1) and #578 (`ssot` owner robustness).
  - The owner confirmed D11, so W1 is published as PR #579; its compile diagnosis was sent to its
    holder.
  - Slice 2 is held as a draft until W1 merges.

- 2026-09-29, Claude Code:
  - Created this board and recorded the direction verdict (dated record linked above).
  - Removed idle worktrees, fully merged local branches and empty orphan directories, preserving
    all uncommitted work.
  - W1 continues in its own session. W2 waits on the owner decisions above.

## W2 handoff notes (2026-10-01)

W2 was transferred from Claude Code to Codex. The Active table is now the current queue.
W1 / #579 has merged; its follow-ups remain with its own holder.

**Notes for the W2 holder (verified on this host):**
- **Linked worktrees always show 8 test failures:** `test_graphify_guarded` (4), `test_graph_invariants` (3) and
  `test_atlas_r2_authority_decision_binding` (1). They fail identically on an unchanged `main` in a linked
  worktree, so they are environment failures. A rare `make_stick` / venv-redirector failure under load
  passes when re-run alone.
- **Adding a `cisco_toolkit` module moves two zero-egress attestation strings in the golden snapshot** ("across N
  modules"). RUN `tests/test_pipeline_golden.py`; a byte-identical golden file proves nothing.
- **Do not run a full `UPDATE_GOLDEN=1` regeneration on Windows:** it rewrites every line ending to CRLF (tens of
  thousands of churned lines). Regenerate, then compare with `git diff --ignore-cr-at-eol`, and commit LF bytes
  that change only the real content.
- **Merges:**
  - Use merge commits (never squash or rebase) and `gh pr merge <n> --merge --admin --match-head-commit <tested sha>`.
  - Only do this after every required check is green and with the owner's standing merge authority: branch
    protection needs one review, and authors cannot self-approve.
  - Merging one PR puts the others behind `main` (the strict rule), so merge `main` in again.
  - A clean 3-way merge of the same two commits always gives the same tree. Confirm it after merging:
    `git rev-parse origin/main^{tree}` must equal the tested merge's tree.
- **Before every push (public repo):**
  - `py -3.12 -I -B .github/scripts/verify_repository_privacy.py --root .`
  - a scan of `git log -p origin/main..HEAD` with `cisco_toolkit.distribution_verify._client_marker_patterns()`
  - Gate each step on its exit code; never chain gates with `;`.
