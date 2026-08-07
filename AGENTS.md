# Shared agent bootstrap

This is the Codex entry point for this repository. `CLAUDE.md` is the shared
operating-doctrine and current-state owner; its name does not make it
Claude-only. Before substantive work:

1. Read `CLAUDE.md` completely.
2. Read `docs/ssot.md` before using or repeating a shared fact. Read the fact
   from the owner named there rather than from a cached count or plan.
3. Read `docs/quality/learnings.md` when its verified engine lessons are
   relevant to the task.
4. Inspect the live repository with `git status --short --branch` and recent
   `git log`. When inheriting work from another agent or session, also inspect
   `git worktree list --porcelain`, relevant local branches, and any explicitly
   referenced uncommitted or ignored workspace. A clean root status does not
   prove that an abandoned agent worktree contains nothing useful.

Use this precedence when sources disagree:

1. Current owner code, tests, manifests, runtime evidence, and live Git state.
2. Explicit current/reconciled sections in `CLAUDE.md` and owner documents.
3. Accepted ADR decisions.
4. Dated plans, handoffs, closeouts, review ledgers, chats, and agent memories.

Dated records preserve reasoning; they are not automatically current work
queues. Never execute their `next`, `remaining`, `resume`, phase, branch, or PR
instructions without revalidating them against the live owners and Git state.

## Cross-agent continuity

- `.claude/settings.json`, Claude hooks, slash commands, custom agents, and
  Claude auto-memory are Claude Code facilities. Codex does not automatically
  execute or load them.
- Preserve the shared safety doctrine manually: no device writes; no writes to
  the personal vault; no external egress from the engine or graph; evidence-
  grounded, coverage-honest output; and an independent verification pass for
  consequential changes. Run the Python, frontend, distribution, and graphify
  gates appropriate to the files changed.
- When a task explicitly continues Claude work on the same host, locate the
  project memory index under
  `%USERPROFILE%\.claude\projects\<project-slug>\memory\MEMORY.md` and consult
  only relevant entries. Treat them as hints and verify every current claim
  against tracked owners; do not copy the whole machine-local memory store into
  the repository.
- Cross-agent state is synchronized only when it is represented in tracked
  source, an owner document, or Git history. Record durable decisions there,
  not only in a chat or platform-specific memory.
- Do not push, merge, write to a device or the vault, or bypass a human gate
  without the explicit authority required by `CLAUDE.md` and the user.
