# NOW: the one live work board

This file is the single tracked answer to four questions: **what are we building right now, on
which branch, who holds it, and what is next.** Every session reads it first and updates it last,
whether it runs in Claude Code or Codex.
- Dated plans, handoffs, chats and agent memories are history, not work queues (see the precedence
  list in root `AGENTS.md`).
- Where this board and live Git disagree, live Git wins. Correct the board in the same change.
- Read the board from `main` (`git show origin/main:docs/NOW.md`). A work branch's copy may be
  behind.

Last reconciled: **2026-10-01** (Codex). Reasoning behind the current direction:
`docs/ui-direction-verdict-2026-09-29.md` (dated record).

---

## The one product

There is **one application**: the `main` branch of this repository on GitHub.

- **Intelligence (target):** the Python engine (`cisco_toolkit/` + `COLLECT_PARSE_V3_23_0.py`)
  must become the only owner of every analysis fact. Screens render engine output; they never
  invent, restate or default a fact (`docs/ssot.md`). Some screens still compute facts
  themselves; see the dated verdict.
- **The one door:** AssessHub (`webapp/`). Atlas Scope (`atlas-scope/`, today only on its branch)
  becomes AssessHub's 3-D investigation module.
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
| W2a | `ui_projection` slice 2: Inventory, device page, Findings | `feat/ui-projection-slice2`, draft PR #580; existing `.claude/worktrees/ui-projection-2` checkout | Codex | Main merged after #579; evidence projection and validation in progress (2026-10-01) | Project `evidence_refs`, `evidence_basis`, `evidence_refs_total` and `deduction_refs`; refute, run all gates, pass both privacy checks before push, mark ready and merge the green exact head. |
| W2b | Engine defects G13 / G15 / G49 | `fix/engine-contract-defects`, pushed through `f950f888`; existing `.claude/worktrees/engine-defects` checkout | Codex | Engine fixes/refutation committed. Full run: 9,684 passed / 40 skipped / 20 failed; eight context and nine deferred fixture failures preserved, three actionable failures repaired with 146 focused tests passing. [Validation on its branch](https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit/blob/f950f888/docs/engine-defects-validation-2026-10-01.md). | After W2a merges: merge main with a merge commit, reconcile its projection consumers, regenerate golden/sheet schema/sample ONCE with LF bytes, run all gates, open the PR and merge when green. |
| W2c | Backend endpoint and first core screens | not started; no branch or folder yet | Codex | Read-only API and static prototype-source preflights complete on the W2b branch; implementation waits for W2a/W2b | Add the paged, declared-response-model endpoint and Overview / Trust / Inventory + device / Findings screens using only contract envelopes. List the concrete branch/folder before creating either. |

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

- 2026-10-01, Codex (W2a):
  - Verified #579 merged as `d92fcb1f`; its tree equals tested head `0345eb1d`. Removed W1's active row under rule 8; its branch, checkout and follow-ups remain with their owner.
  - Merged current main into the existing `feat/ui-projection-slice2` checkout with a merge commit. Preserved every handoff entry from both sides of the board conflict.
  - W2b is pushed through `f950f888`: engine fixes and full-suite refutations are saved on that branch. W2a now owns evidence-reference projection and its gates; W2b integration/regeneration follows W2a's merge.

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
