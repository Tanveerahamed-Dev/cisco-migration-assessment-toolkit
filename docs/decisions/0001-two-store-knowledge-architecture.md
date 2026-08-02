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

---

## Amendment 1 (2026-07-07) — one-way, sanitized, read-only vault **digest** for recall (D3/D4)

**Status:** accepted (authorized 2026-07-07) · **enables:** the *recall* nerve of
`docs/autonomous-brain-plan-v4-final-2026-07-06.md` (D3/D4) · **related:** `research_lane/`,
`cisco_toolkit/intel_feed.py`, `research_lane/sanitize.py`

### Context
Decision point 3 above states "**Nothing flows vault→repo**." That is correct for *raw* vault pages
(client-adjacent career/domain notes) and stays in force. But the autonomous-brain plan needs *recall* — an
`/ask` answer that fuses graph + docs + the operator's own distilled domain knowledge. The plan resolved
this (D3) as an **additive, one-way, read-only DIGEST**, not raw pages, behind the same Rule-3 sanitization
that the repo→vault bridge already uses.

### Amended decision
Point 3 is narrowed, not reversed. Raw vault pages still never cross. **One new, tightly-fenced exception:**
a **sanitized vault digest** may cross vault→repo for recall, subject to all of:
1. **Digest, not pages** — only distilled, generic domain facts (concepts/patterns/vendor quirks), never a
   raw note, never client-adjacent material.
2. **Rule-3 sanitized at the boundary** — passed through `research_lane/sanitize.py` (forbidden-token / IP /
   email scrub) with a recorded redaction audit, exactly like the intel feed; the crossing artifact is
   **SHA-256 hash-sealed** (the `intel_feed.build_feed` contract) and the repo **verifies** it before use.
   The digest is unkeyed and declares `authentication: none`: this establishes corruption evidence, not
   producer identity.
3. **Read-only + additive** — the repo consumes it; it never writes back to the vault, and the digest is
   supplementary to graph+docs (recall degrades gracefully to graph+docs if the digest is absent).
4. **Produced in the fenced lane** — the vault read + sanitize + hash-seal happens in a network/vault-connected
   worktree (like the research lane), never from an air-gapped repo session. The air-gapped repo only ever
   reads the frozen, hash-sealed, sanitized digest — its no-egress invariant is unchanged.

### Ollama vault-digest RAG — planned (D4); **since installed — see status update below**
The digest is retrieved locally via **Ollama** (zero-egress, offline embeddings/LLM) so recall needs no
network at query time. At decision time this was a **plan, not an install** — the dependency is **optional and
gracefully-degrading**: no Ollama ⇒ the vault-digest store is simply unavailable and recall falls back to
graph+docs (reported honestly, never silently "no results"). Implementation (the RRF hybrid retriever over
graph ⊕ docs ⊕ vault-digest, D10) was gated on the Ollama install + a first sanitized digest (both since
satisfied — see the status update below), and ships as an experiment with its own eval (D10), not as
proven SOTA.

> **Status update (2026-07-10):** the D4 gate is satisfied — Ollama + `nomic-embed-text` are installed
> locally (semantic path validated via local `/api/embeddings`; read the version from `ollama --version`,
> not from any doc) and the first sanitized digest (`digest-2026-07-07.jsonl`, owner-machine only,
> gitignored) has been produced. The graceful-degradation contract above is unchanged and implemented
> (`ollama_recall.py`, subprocess, fast-fail to lexical). Live status is owned by the `docs/ssot.md`
> vault-digest row (freshness-guarded by `tests/test_registry_freshness.py`); this ADR records the
> decision, not current state.

### Consequences
- The sanitizer (`research_lane/sanitize.py`) is now the shared Rule-3 boundary for **both** crossings (intel
  feed and vault digest).
- `docs/ssot.md` gains the vault-digest as a *gated* store (like the intel feed): registered, but no data
  until the digest producer + Ollama are wired *(both wired since — see the 2026-07-10 status update above;
  the ssot.md row owns current state)*.
- This amendment grants the mechanism; it does **not** grant reading arbitrary vault pages from repo sessions
  (that would need a further amendment).
