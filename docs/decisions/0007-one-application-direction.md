# 0007: One application, and owner decisions D0 / D9 / D10 / D11

**Date:** 2026-09-30 · **Status:** accepted; D10's owner control amended 2026-10-09 (Amendment 1) ·
**Decided by:** Claude Code under an explicit, full delegation from the owner ("take the best
decision; you have full authority") ·
**Related:** `docs/NOW.md` (live board), `docs/ui-direction-verdict-2026-09-29.md` (dated research
record), `docs/decisions/0004-atlas-portable-app-p0.md` (Atlas), `docs/ssot.md`

## Context

The owner builds one product from both Claude Code and Codex sessions. By 2026-09-29 it had four
network-facing surfaces:
- AssessHub (`webapp/`)
- Atlas Scope (`atlas-scope/`, still on an unmerged branch)
- the engine HTML explorer
- the MCP server

Several of them compute failure impact or verdicts outside the engine. The owner asked for one
top-level, very user-friendly application whose intelligence all comes from the Python engine.
They delegated the four open decisions below.

## Decision

**One application.**
- AssessHub is the one door.
- Atlas Scope becomes its 3-D investigation module.
- The engine HTML explorer remains an offline deliverable.
- The MCP server and `master-reference/` remain derivatives.
- Work is coordinated through `docs/NOW.md`.

### D0: Release 1 is FROZEN as a draft candidate

- The `v3.33.0-rc.3` draft release and its tag stay as they are. Nothing is shipped from them now.
- The UI program proceeds on `main`. The next release candidate is cut from `main` after the first
  UI milestone (core screens, roadmap P3), with its version set in `pyproject.toml` at that time
  (`CLAUDE.md`, *Tests* entry-point rule).
- **Why:** shipping requires the external advisory/applicability review that `CLAUDE.md` names as
  the remaining release blocker. No agent can supply that, so waiting for it would stall the UI
  program for nothing. Freezing costs nothing and keeps the candidate reproducible.

### D9: Facts in Python, geometry in the browser

- **Every fact on screen comes from the engine** (`cisco_toolkit/`). That covers every verdict,
  count, rollup, denominator, severity band and evidence state on any screen.
- **It reaches the screen through one typed projection:** a new `cisco_toolkit/ui_projection.py`
  with schema-tagged payloads, served by the backend with declared response models.
- **Atlas Scope's compiler (`atlas-scope/tools/lib/compile-model.mjs`) owns only 3-D
  geometry,** layout and visual encoding, and it consumes engine verdicts.
- **Existing browser-side and backend verdict logic must converge on engine owners:**
  - Scope's TypeScript forwarding/blast engines
  - AssessHub's client-side failure search (`TopologyGraph.tsx`, `counterfactualFailure`)
  - the webapp's cutover Go/No-Go (`webapp/backend/cutover.py`)

  Each becomes a renderer or is parity-pinned against its engine owner. The existing
  explorer-parity tests are the pattern.
- **Why:** the owner's requirement ("intelligence from my Python code") and `docs/ssot.md` Law 1.
  Layout is legitimately a presentation concern; verdicts are not.

### D10: Raw collection evidence is RETAINED, secret-scrubbed

- After ingest, AssessHub keeps each collection inside the Atlas data store.
- **Before retention,** the capture is scrubbed with the engine's existing raw-capture secret
  scrubber (the `--redact-collection` path). It is then proven clean by the independent verifier
  (`webapp/backend/redaction_verify.verify_collection_secret_scrub`), and digest-bound to its
  snapshot.
- **A failed or incomplete scrub means the capture is not retained.** The UI states that
  drill-down is unavailable. It must never silently keep plaintext.
- **Owner control:** the UI shows a retention indicator and a per-campaign purge. *Superseded on
  2026-10-09 by Amendment 1: no in-app purge or retention indicator is built.*
- **Never in the repository.** Share-safe client delivery stays governed by
  `Atlas.exe --redact-folder`.
- **Why:**
  - Evidence drill-down ("show me the exact CLI line") and engine re-runs such as traffic
    assurance are the features that make the product trustworthy, and both need the raw capture.
  - Raw configurations can carry passwords, SNMP communities and keys, which snapshots do not.
    So retention is only acceptable after a verified scrub.
- **Deferred until W1 merges:** `webapp/backend/ingest.py` is on the Atlas Scope branch's freeze
  list, so implementation waits for that merge.

### D11: Publishing the Atlas Scope branch is APPROVED, with conditions

The session holding W1 may push `claude/atlas-scope-engine-sot` and open a pull request to `main`
once all four conditions hold:
- phase 3.5 is committed, leaving no uncommitted edits
- `.github/scripts/verify_repository_privacy.py --root .` passes
- the client-marker scan (`cisco_toolkit.distribution_verify._client_marker_patterns()`) finds no
  hits in every commit message and patch in `origin/main..HEAD`
- the remaining FAIL items are listed in the pull request as a known "preview" scope rather than
  an open-ended repair loop

Merging follows the normal gates.

## Consequences

- **The roadmap follows the dated verdict:**
  - P0: prototype + 2-D vs 2.5-D task test
  - P1: engine honesty fixes and projection slice
  - P2: land Scope
  - P3: typed contract + core screens
  - P4: engine-owned what-if and CAB dry-run
  - P5: signature 3-D and scale
  - P6: validate and ship
- **What can start on `main` now without colliding with W1:** engine-only honesty fixes in
  modules outside W1's freeze list.
- **What waits for W1 to merge:** frontend, `webapp/frontend/dist`, `app.py`, `ingest.py` and
  golden changes.
- **Revisit:**
  - D0 when the external review arrives.
  - D10 if a field deployment forbids client evidence at rest on removable media. BitLocker To Go
    remains the owner's recommended control.

## Amendment 1 (2026-10-09): D10's in-app purge is superseded by keep-everything

**Decided by:** the owner, relayed by the supervising session on 2026-10-09 and recorded on the board
(`docs/NOW.md`, Owner decisions, 2026-10-09 entry, with the other three decisions of that day).

- **Keep everything.** Comparison receipts stay immutable, and AssessHub has **no in-app purge and no retention indicator**. D10's "Owner
  control" bullet above (a per-campaign purge and a retention indicator) is superseded and is not
  built.
- **Disposal is a manual operator step outside the application.** At the end of an engagement,
  and only when the client agreement allows it, the operator removes the whole data folder and
  every other copy with the operating system. The procedure and the list of locations are owned
  by `docs/operator-guide-core-screens.md` (section 10, *Disposing of client data*) and
  `portable/README-FIELD.txt` (DISPOSING OF CLIENT DATA).
- **An in-app delete is not disposal.** Unreceipted campaigns, snapshots and execution runs can
  still be deleted, but a deleted row can stay readable inside the database file and in its
  start-time backups.
- **Unchanged:** the rest of D10 (scrubbed retention of raw collection evidence, never in the
  repository, share-safe delivery through `Atlas.exe --redact-folder`) and D10's revisit trigger
  under Consequences. This amendment changes no code.
