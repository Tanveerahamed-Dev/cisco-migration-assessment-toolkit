# UI direction verdict and housekeeping receipt (2026-09-29)

> **Dated record.** This file preserves reasoning. It is not a work queue. Current workstreams,
> holders and pending owner decisions live in `docs/NOW.md`. Revalidate every claim here against
> live owners before acting on it (root `AGENTS.md`, precedence list).

## Question

The owner asked for one top-level, very user-friendly application, including rich 3-D topology
views, whose intelligence all comes from the Python engine. It must serve network engineers,
architects and managers, and must not break work already in flight.

## Method

The research was read-only:
- four codebase mappers: engine capabilities, AssessHub screens, the engine-to-screen data path,
  Atlas Scope
- four web research tracks: comparable network-visualization products, rendering stacks,
  2-D/3-D usability evidence, and UI-as-projection architecture
- one synthesis
- three adversarial reviewers: source-of-truth honesty, feasibility, UX

The key code findings below were then re-verified by direct reads and in-memory probes.

## Verdict

1. **The goal is right; consolidate rather than build new.**
   - AssessHub (`webapp/`) is the one door.
   - Atlas Scope (`atlas-scope/`) becomes its 3-D investigation module.
   - The engine HTML explorer stays an offline deliverable.
   - `master-reference/` and the MCP server (`cisco_toolkit/mcp_server.py`) are existing derivatives, not
     further products.
2. **Several screens compute failure impact outside the engine.**
   - The engine has several distinct failure models:
     - `analyze.compute_failure_impact`, with a parity-tested explorer JavaScript port
     - `whatif.run_scenario`
     - `failover.compute_failover_twin`
     - traffic assurance's single synthetic failure
   - Outside the engine there are two more: `counterfactualFailure` in
     `webapp/frontend/src/components/TopologyGraph.tsx`, and Scope's `blast.ts`.
   - Each screen must render one named engine owner (decision D9). A screen-side model with no
     engine owner moves first.
3. **Honesty before graphics.** "Not known" must never render as "0" or healthy. Verified:
   - `analyze.compute_executive_brief` publishes a fleet health average of `0` when no device
     could be scored.
   - AssessHub's punch-list tile (`webapp/frontend/src/pages/Snapshot.tsx`) tones a missing punch
     list green.
   - `ssot.abstention_reason` never reads the engine's failed-phase record, so a failed phase
     whose fallback is an empty `{}`/`[]` reads as collected-but-empty.
   - `webapp/backend/ingest.py` deletes the raw collection after ingest.
4. **There is no typed engine-to-UI contract.**
   - No API route declares a response model.
   - `webapp/frontend/src/api.ts` mirrors types by hand, and they already drift. Example: a
     numeric `crit_high` versus the backend's empty-string fallback.
5. **3-D must earn its place.**
   - 2-D is the default for path trace, diff, search and reading labels.
   - 2.5-D/3-D goes only where it wins, for example stacked L1/L2/L3 layers or blast-radius
     storytelling, and only after a timed task test on the owner's integrated-GPU laptop. Scope's
     committed 300-device receipts lean negative.
   - No fact may be reachable only in 3-D, and a non-WebGL fallback must always exist.
   - The published 3-D studies found were headset-based, with mixed results. Munzner's "no
     unjustified 3D" rule and St. John et al. (2001) on relative-position judgements still apply
     on monitors.
6. **What makes comparable products feel premium:** global search, a page per device, VLAN and
   endpoint, an evidence drawer ("why is this true"), path and flow trace, a Trust view and a
   one-screen manager overview. Engine outputs with no AssessHub screen today:
   - traffic assurance
   - the VLAN cutover matrix
   - `nrfu_export.compute_nrfu_commands`
   - the failover twin (MCP-only)
   - `cutover_sim.simulate_cutover`
7. **Roadmap order:**
   - P0: decisions, disposable prototype, task test
   - P1: engine honesty fixes and a projection slice
   - P2: land Scope, bounded
   - P3: typed contract and core screens
   - P4: engine-owned what-if and CAB dry-run
   - P5: signature 3-D and scale
   - P6: timed persona validation and the stick build

## Housekeeping receipt

- **Removed:** seven idle agent worktrees, 15 local branches whose commits were already contained
  in `origin/main`, and nine empty orphan directories under `.claude/worktrees/`.
- **Preserved, as local-only refs on the owner's machine:**
  - `refs/preserved/codex-atlas-r2-exec-wip-20260822`: an unfinished `evolution` module and its
    tests, absent from `main`
  - `refs/preserved/main-checkout-wip-20260929`: a snapshot, left in place, of the main checkout's
    uncommitted edits
- **Archived outside the repository:** build outputs, run logs and one July orphan copy of the
  frontend source.
- **Remote branches, not merged:**
  - Dependabot pull requests #571 and #572 are open. The other dependabot branches have closed
    PRs.
  - `codex/graphify-0947-report-compat` (PR #530) was closed unmerged and has been superseded by
    the newer Graphify pin on `main`.
