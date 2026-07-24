# 0005 — Cognee evaluated: don't adopt as memory/graph substrate; cite two things

**Date:** 2026-07-19 · **Status:** accepted · **related:**
`cisco_toolkit/recall.py`, `cisco_toolkit/learnings.py`, `cisco_toolkit/memory_guard.py`, `graphify-out/` (AST-only graph),
`docs/decisions/0001-two-store-knowledge-architecture.md`, `docs/decisions/0003-agent-brain-hybrid-substrate.md`,
`memory/cognee-evaluation-2026-07-19.md`, `memory/external-plans-map-to-code.md`,
arXiv 2601.07978 v4 (Wolff & Bennati, independent LoCoMo benchmark; the Cognee row is present only from v3)

## Context

A `/deep-research` run (90 agents, 3-vote adversarial verification, full cited report at
`https://claude.ai/code/artifact/754bf3f7-025b-4678-a2ba-752886409762`) evaluated Cognee
(cognee.ai, github.com/topoteretes/cognee) — an open-source AI-agent-memory framework — against the same
three blockers that already got Graphiti/Zep rejected for this repo (see the "Rejected with verified reasons"
list in `memory/second-brain-plan-v2.md`): a Docker requirement, a mandatory external graph database, and
mandatory cloud LLM calls.

Cognee clears the first two by default (zero-extras `pip install cognee` runs embedded SQLite + LanceDB + an
in-process graph engine; Neo4j is an opt-in extra, never required). It does not clear the third by default:
the LLM and embedding providers default to OpenAI, and — the decisive footgun — configuring only one of the
two to a local Ollama backend leaves the other silently on OpenAI. An independent, statistically-controlled
benchmark (arXiv 2601.07978 v4) further found Cognee's retrieval accuracy on LoCoMo (55.27%) statistically tied
with Graphiti (56.03%, p=0.845) and well below the mem0/RAG/full-context cluster (77–81%, p=0.002), with
Cognee's own extraction step in that test run against cloud `gpt-4o-mini`, never a local model. Cognee's own
self-published benchmark claiming to beat Graphiti is confounded — it ran a tuned Cognee against every
competitor's stock defaults, a caveat Cognee's own methodology write-up acknowledges.

This is the same failure mode `docs/decisions/0003-agent-brain-hybrid-substrate.md` and
`memory/external-plans-map-to-code.md` already document for Fable and Perplexity plans blind to this repo — a
polished external proposal mostly re-derives what's shipped — one step further this time: the one genuinely
new idea (a small, verb-based memory-lifecycle API) had *already* been adopted here from a different source
(SelfMem, arXiv 2607.03726, ADR-0003), so Cognee's `remember/recall/forget/improve` API only corroborates a
decision already made, rather than contributing new work.

## Decision

1. **Do not adopt Cognee** as a memory or knowledge-graph substrate, in whole or in part. Three independent
   reasons converge, not one: (a) its core mechanism — an LLM reads text and writes the graph ("cognify") —
   is exactly what this repo's AST-only doctrine excludes, independent of where the LLM call runs; the
   local-Ollama carve-out (CLAUDE.md) licenses inference only, never LLM-derived graph nodes. A fully-local
   Ollama-run Cognee would still conflict with this repo's doctrine, not just its egress policy. (b) Cognee's
   default configuration has a weaker no-egress posture than what's already shipped — `cisco_toolkit/recall.py`
   and `ollama_recall.py` are local-only by construction with hermetic tests (never require a live Ollama),
   where Cognee's default silently falls back to OpenAI on whichever of {LLM, embeddings} is left unconfigured.
   (c) an independent benchmark shows Cognee's retrieval quality tied with Graphiti and well below the
   architectural family (mem0/RAG) that `graphify` + RRF hybrid recall already sits closer to.

2. **Adopt now — cheap, already landed, not a new instrument:** two citations, the same "Phase 0" move
   ADR-0003 made for SelfMem's citations:
   - arXiv 2601.07978 as independent evidence for staying with AST-only `graphify` + lexical/local-semantic
     RRF recall rather than adopting an LLM-cognify graph — cited in `cisco_toolkit/recall.py`'s module
     docstring, next to the existing D10 rationale.
   - Cognee's `remember/recall/forget/improve` API as a second, independently-arrived-at corroboration of the
     SelfMem write-operator vocabulary already adopted — cited in `cisco_toolkit/learnings.py`'s docstring,
     next to the existing SelfMem citation.

3. **No new build triggered.** Nothing here moves the data-first frontier (`memory/feedback-loops-data-gated.md`):
   the calibration real-data floor stays at N=0 REAL until an actual post-cutover PIR: the D10 retrieval gate's
   next step is a human-pre-registered instrument v3, not a Cognee-shaped fix; nightly-arming and the Batfish
   twin-verify spike remain user-gated infra/spend decisions, unrelated to this evaluation.

## Consequences

- `memory/cognee-evaluation-2026-07-19.md` is the working-memory record (verdict + reasoning, linked from
  `memory/second-brain-plan-v2.md`'s "Rejected with verified reasons — don't re-research" list, alongside
  Graphiti/getzep, claude-mem, and Obsidian MCP). This ADR is the durable, repo-tracked record.
- The two citations are committed in code, not just this document — `python -m graphify explain recall` /
  `explain learnings` should surface them once the graph re-extracts docs alongside this ADR.
- Cognee's own capabilities around custom ontologies/Pydantic schema support and temporal/bi-temporal fact
  invalidation were NOT resolved by the underlying research (claims either didn't survive verification or
  were never attempted) — this ADR takes no position on those and neither should any future session without
  fresh verification; naming drift was also observed mid-research (Cognee's embedded graph engine renamed
  Kuzu→Ladybug after upstream Kuzu was archived Oct 2025), so treat Cognee as a fast-moving target and re-verify
  specifics before citing them again.
- Plan-only decision beyond the two docstring edits already applied; no engine behavior changed. Guardrails
  intact: read-only, no-egress, AST-only graph unchanged.
