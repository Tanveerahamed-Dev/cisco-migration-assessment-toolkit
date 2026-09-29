# NOW: the one live work board

This file is the single tracked answer to four questions: **what are we building right now, on
which branch, who holds it, and what is next.** Every session reads it first and updates it last,
whether it runs in Claude Code or Codex.
- Dated plans, handoffs, chats and agent memories are history, not work queues (see the precedence
  list in root `AGENTS.md`).
- Where this board and live Git disagree, live Git wins. Correct the board in the same change.
- Read the board from `main` (`git show origin/main:docs/NOW.md`). A work branch's copy may be
  behind.

Last reconciled: **2026-09-29** (Claude Code). Reasoning behind the current direction:
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
| W1 | Atlas Scope 3-D module program (phase 3.5) | `claude/atlas-scope-engine-sot`, **local-only: never pushed** | Claude Code session in the `.claude/worktrees/atlas-scope-engine` checkout | Phase-3 checkpoint committed; phase-3.5 edits uncommitted; a time-boxed focus audit was running (2026-09-29) | Finish 3.5 with the audit bounded, then commit. Run the rule-7 checks. Owner decision D11, then push and open a PR to `main`. |
| W2 | One-application UI consolidation (AssessHub + Scope + explorer) | not started | unassigned | Direction recorded in the dated verdict; waiting on owner decisions (2026-09-29) | P0: owner decisions D0/D9/D10/D11; a disposable prototype (on a listed branch, or a scratch folder deleted after the test, never a new repository or app); a timed 2-D vs 2.5-D test on the reference laptop |
| W3 | This board | `docs/one-app-board` | Claude Code | Pull request for owner review (2026-09-29) | Owner review and merge. Then delete this row (rule 8). |

## Owner decisions pending

- **D0: Release 1.** `pyproject.toml` on `main` is an unreleased release candidate.
  - Choose to ship it or freeze it before the UI program starts.
  - Shipping is only possible after the external advisory/applicability review that `CLAUDE.md`
    names as the remaining release blocker.
  - Every UI change alters release bytes, because `webapp/frontend/dist` is tracked.
- **D9: One engine owner per screen, and one projection owner.** Options: a new Python
  `ui_projection` library that Scope renders, or Scope's compiler
  (`atlas-scope/tools/lib/compile-model.mjs`) with the Python side deferring to it. Measure load
  time on the real fleet before choosing.
- **D10: Keep raw collection evidence after ingest?**
  - Today `webapp/backend/ingest.py` deletes its working directory after a run.
  - Keeping the evidence is required for "click through to the exact CLI line" and for engine
    re-runs such as traffic assurance.
  - Costs: privacy and disk on the stick.
- **D11: Publish the Atlas Scope branch** to this public repository, after the rule-7 checks.
- **Also open, owned by `CLAUDE.md` and not restated here:** the carried-forward review-tail items,
  publishing the master-reference site, and the Claude Design pixel-baseline promotion.

## Handoff log (newest first)

- 2026-09-29, Claude Code:
  - Created this board and recorded the direction verdict (dated record linked above).
  - Removed idle worktrees, fully merged local branches and empty orphan directories, preserving
    all uncommitted work.
  - W1 continues in its own session. W2 waits on the owner decisions above.
