# 0001 — Two-store knowledge architecture (repo/graphify vs personal vault)

**Date:** 2026-07-05 · **Status:** accepted · **related:** `docs/ssot.md`, `CLAUDE.md` (graphify section),
`docs/MASTER_PLAN_2026-07-05.md` §5.2, `C:\Vaults\brain\CLAUDE.md`

## Context
The Karpathy "LLM wiki" pattern (raw/ → wiki/ → schema; ingest/query/lint) is being adopted on the new
laptop. This repo already has a working knowledge layer: the AST-extracted graphify graph (regenerable,
Stop-hook-refreshed, fuses docs/) plus the docs/ planning corpus. A single merged wiki would create a second,
rotting source of truth for code facts — violating SSOT Law 1 — and would put client-confidential engagement
material one sync away from a personal knowledge base.

## Decision
Two stores, one contract each, never merged:
1. **This repo + graphify** own code structure, engagement evidence, and engineering decisions
   (docs/decisions/, docs/log.md). Nothing changes about the no-egress doctrine.
2. **`C:\Vaults\brain`** (Obsidian + Claude Code vault, private git) owns career/domain knowledge —
   concepts, vendors, patterns. Its contract forbids client identifiers outright.
3. **Bridge is one-way and sanitized:** generic lessons (e.g. "bare `show logging` on NX-OS is a
   false-health trap") may be promoted repo→vault with client identity stripped. Raw evidence never crosses.
   Nothing flows vault→repo.

## Consequences
- Wiki pages that mention engine behavior must cite the symbol name and defer to graphify, not restate.
- Claude Cowork/Desktop folder grants: vault only, never this repo.
- The vault's lint cadence (weekly) is independent of this repo's hooks.
