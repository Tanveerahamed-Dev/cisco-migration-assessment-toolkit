# Vault digest — one-way, sanitized, read-only recall store (ADR-0001 Amendment 1)

The **recall** nerve's third store (Phase 5, D3/D4 of `docs/autonomous-brain-plan-v4-final-2026-07-06.md`).
It lets an `/ask` / `recall` answer fuse **graph + docs + the operator's own distilled domain knowledge** —
without breaking the two-store knowledge architecture (`docs/decisions/0001-two-store-knowledge-architecture.md`).

## The fence (non-negotiable — ADR-0001 Amendment 1)
1. **Digest, not pages.** Only distilled, generic domain facts (concepts / patterns / vendor quirks) cross —
   a title + a length-**capped** summary + tags per note, **never** a raw note. Client-adjacent notes are
   **dropped** before anything else.
2. **Rule-3 sanitized at the boundary**, then **signed.** The producer scrubs every entry via
   `research_lane/sanitize.py` (forbidden tokens / IPv4 / email) and records the redactions as proof, then
   signs with `cisco_toolkit.intel_feed.build_feed`. The entry `id` is slugged from the **sanitized** title,
   so a client token cannot leak through the id.
3. **Produced in the fenced lane, never from an air-gapped repo session.** The vault read happens in
   `research_lane/vault_digest.py` (outside `cisco_toolkit/`, run from a **vault-connected** session). The
   air-gapped repo only ever **verifies + reads** the frozen signed digest — its no-egress invariant is
   unchanged. Reading the vault from a normal repo session is **not** granted by this amendment.
4. **Read-only + additive.** The repo consumes it; it never writes back to the vault. Recall **degrades
   gracefully** to graph + docs + code when no digest is present (reported honestly, never "no results").

## Produce a digest (from a vault-connected session only)
```
python -m research_lane.vault_digest --vault C:\Vaults\brain --subdir wiki \
    --generated 2026-07-07 --forbidden Acme,SiteA [--max-chars 600]
```
- `--vault` is **required** (there is no silent vault read), mirroring how the intel producer gates live
  egress behind `--live --url`.
- `--subdir wiki` targets the already-distilled wiki layer (recommended over raw notes).
- `--forbidden` adds engagement-specific client/site tokens to the Rule-3 scrub.
- Writes `docs/vault-digest/digest-<date>.jsonl` — a manifest line (kind/sha256/**sanitized:true**/producer/n)
  followed by one JSON entry per line.

## How it is consumed (air-gapped repo, no egress)
- `cisco_toolkit.recall.load_vault_digest()` verifies each digest via `intel_feed.verify_feed`
  (sanitized-attested **and** SHA-256-intact **and** free of forbidden identifiers) — a bad digest is
  **refused whole**, never partially consumed — and builds a `{id: text}` corpus.
- `vault_digest_rank()` ranks it **lexically** (TF-IDF) — fence-clean, always available when a digest exists.
- `ollama_digest_rank()` is an **optional** local-Ollama semantic re-rank (D4), invoked as a **subprocess**
  into `ollama_recall.py` (which lives outside `cisco_toolkit/` so its `urllib`/Ollama use never trips the
  no-egress attestation). Ollama absent ⇒ it returns nothing ⇒ recall uses the lexical signal. **Ollama is
  optional** — install with `winget install Ollama.Ollama` then `ollama pull nomic-embed-text` (the model
  this defaults to); the `/api/embeddings` path is validated against Ollama 0.31.1. The test suite never
  requires a running Ollama (it stays hermetic; the semantic path is validated manually).
- All signals fuse via Reciprocal Rank Fusion (`hybrid_recall`); a fused answer draws on ≥ 2 stores.

## Not committed by default
Real digests are **gitignored** (`docs/vault-digest/digest-*.jsonl`) — they are derived from the personal
vault, so even sanitized they are local-only by default (like the generated morning briefings). The
producer, consumer, gate, and this doc **are** committed. Un-ignore deliberately if you decide a sanitized
digest may live in the pushable repo.
