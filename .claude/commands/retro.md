---
description: End-of-session retro — append a session entry with !lesson bullets to docs/log.md (what broke, the fix, vendor quirks); tag client-generic lessons bridge-candidate for later vault promotion.
argument-hint: [optional focus — e.g. "the parser fix" or "wave-5 review"]
---
Write the session retro into `docs/log.md`.

FOCUS: $ARGUMENTS

Procedure (docs/log.md is append-only, newest first — insert the new entry directly under the format header, never rewrite old entries):

1. Reconstruct what this session actually did from the conversation and `git log` since the session started. No padding — if nothing failed and nothing surprised, say so in one line.
2. Append one entry in the established format: `## [YYYY-MM-DD] — <headline>` + 3–6 bullets.
3. Every failure worth remembering gets a `!lesson` bullet stating **what broke, why, and the fix** — concrete enough that a future session avoids the same trap. Vendor/platform quirks (NX-OS output formats, PowerShell 5.1 traps, tool version gotchas) always qualify.
4. Tag each `!lesson` that is **client-generic** — i.e. it would survive full anonymization and teach something beyond this repo (a failure mode, a decision rule, a vendor quirk, a testing trap) — with `bridge-candidate` at the end of the bullet. These are the promotion queue for the personal vault: a separate vault session ingests them via its `/ingest` (which strips/refuses client identifiers per its Rule 3). Lessons that only make sense inside this codebase (golden re-bless mechanics, a specific test file) get NO tag.
5. NEVER write to `C:\Vaults\brain` from this session (ADR 0001: the bridge is one-way and sanitized, and promotion happens from a vault-cwd session, not here). The tag is the handoff.
