# 0008: The engine computes, the interface displays

**Date:** 2026-10-16 · **Status:** accepted ·
**Decided by:** the owner, through Claude Code under an explicit full delegation ("take the best
possible decision … I need a single source of truth. The engine provides the information. The front
end … I don't want it to bring up its own thing") ·
**Amends:** `0007-one-application-direction.md` D9 (adds enforcement) ·
**Related:** `docs/ssot.md`, `docs/ssot-contract.md`, `cisco_toolkit/ssot.py`,
`cisco_toolkit/ui_projection.py`, `docs/NOW.md`

## Context

D9 (2026-09-30) already said "facts in Python, geometry in the browser", and `docs/NOW.md` names the
engine as the target owner of every analysis fact. That rule was never comprehensively enforced. Scoped
mechanical guards exist: the headline-fact reconcile (`docs/ssot-contract.md`,
`tests/test_ssot_reconciliation.py`) and the projection's reconciled paths. But nothing stops an
interface from computing its own version of a fact. Surfaces built before and after D9 kept their own
calculations.

A read-only audit with an adversarial refuter on 2026-10-16 (main `9112a16e`) confirmed the result:
the engine contract holds, but several surfaces compute the same fact a second time with different
rules. The examples are:
- the AssessHub dashboard and Tools recounts in `webapp/backend/summary.py`;
- the browser failure simulation in `TopologyGraph.tsx` and the second topology in
  `webapp/backend/graph.py`;
- two cutover Go/No-Go rule sets, in `webapp/backend/cutover.py` and `cisco_toolkit/mop.py`;
- the Atlas Scope TypeScript forwarding and blast engines;
- the explorer's JavaScript failure, flow, ACL, VLAN-carriage and causal engines;
- local tallies in the deck and workbook.

The application is used in production with customers, so two numbers for one fact is a defect, not a
style choice. Every new feature built on a split foundation repeats the split.

## Decision

1. **One owner of truth.** The engine (`cisco_toolkit/` and `COLLECT_PARSE_V3_23_0.py`) is the only
   place facts and analyses are computed. That covers counts, bands, scores, lifecycle, findings,
   topology, failure impact and blast radius, paths and flows, ACL verdicts, VLAN carriage, readiness,
   and cutover Go/No-Go. Every value a user sees comes from the engine snapshot, either directly or
   through the `ui_projection` contract and its API.
2. **Interfaces display only.** The AssessHub app, the topology workspace, Atlas Scope, the generated
   HTML explorer and every document may format, sort, filter, page, lay out, colour and animate
   engine output.
   - They must not count, band, score, simulate failures, trace paths, evaluate ACLs, decide
     readiness or Go/No-Go, or infer anything.
   - When a screen needs a value the engine does not publish, the engine gains an owned fact first,
     registered in `docs/ssot.md` with a reconcile or owner test. The screen then displays it.
3. **One application, one home.** The AssessHub app is the product. A snapshot opens in the
   Investigate workspace, whose canvas is the engine topology. Every tool is reachable from a focused
   subject (device, port, link, VLAN, endpoint, path) or from the Find bar. Each surface that
   duplicates the engine is either rewired to the projection or retired. While a duplicate still
   exists, a two-sided parity gate must pin it.
4. **Enforcement is code, not prose.** CI is the authority. These guards are implemented by
   RC8-P1-H and are not yet in force; until they merge with exact-head evidence, reviewers enforce
   the rule.
   - (a) Every `CANONICAL_FACTS` entry must have a reconcile check (ratchet).
   - (b) A closed **interface-computation debt register** lists each known duplicate computation by
     file and symbol. A test fails when a new one appears in interface or report code, or when a
     listed one reappears after removal. The register may only shrink.
   - (c) Any duplicate kept temporarily has an executed two-sided parity gate.
5. **Features go in through the engine.** A new capability (for example digital-twin style queries)
   is built engine first (owned fact plus test), then projection, then interface. It is never built
   in the interface first.
6. **Every session follows this record.** Claude Code and Codex read it through `AGENTS.md` and
   `CLAUDE.md` before work. A change that conflicts with it needs an owner decision recorded as an
   amendment here, not a local workaround.

## One front end (owner decision, 2026-10-16)

The owner asked for a single front end that covers everything a network engineer needs, designed
from the view of a Cisco Advanced Services consultant. It should be simple to navigate and to
explain, and it should scale.

**The Atlas app is the only front end:** the AssessHub React app (`webapp/frontend`).
- **Shell.** The target shell is a native Atlas window. Today `Atlas.exe` starts the server and opens
  the app in the default browser (`portable/atlas_entry.py`, `webapp/backend/serve.py`). The native
  window is RC8 app-shell work, and the one-front-end decision does not depend on it.
- **Retired front ends.** The HTML explorer and Atlas Scope stop being separate user-facing front ends.
  Their best ideas are rebuilt as views inside the Atlas app on engine data: the topology canvas, the
  cable map and the tool side panel. The 2-D topology uses the app's existing `d3-force` dependency.
  The `/scope` entry and the explorer link leave the app.
- **Customer outputs.** These are the generated documents (workbook, HLD/LLD, MOP, NRFU, deck,
  runbook), not another interactive surface.

**Navigation follows the consultant's jobs, not a list of screens.** The interaction is one loop:
focus a subject → ask a question → the engine answers → confirm on the device → save and hand over.
The questions come from one engine question registry. The answers come from the engine, with the
evidence, the limits and the confirm-on-device command and expected value.

The **engagement home** holds campaigns, New assessment, snapshots, saved plan revisions and the wave
calendar. Inside a snapshot there are five job workspaces:

| Workspace | What it answers | Engine source |
|---|---|---|
| **Investigate** (default) | What is out there, how it connects, what happens on it, and how to confirm it. The canvas is the topology and cable map with one lens at a time (health, lifecycle, findings, VLAN). The answer panel offers the questions valid for the focused subject: device, failure impact ("if this fails"), path between A and B, endpoint finder (MAC or IP to switch, port and VLAN), VLAN carriage. A Browse drawer replaces the old Inventory tab: devices, interfaces, VLANs, endpoints, subnets, software and lifecycle. | `project_topology`, `project_device`, `project_path`, `project_vlan_carriage`, `project_inventory`; the question registry |
| **Fix** | What to fix first, and why. Engine findings and checks grouped by rule, each with evidence, remediation, confirm-on-device, and links to its design decision, MOP step and wave. | `project_findings`; check owners |
| **Migrate** | Design (HLD/LLD), discovery questions, move groups and waves, the port migration matrix, and saved plan revisions | design owners, saved plans |
| **Cut over** | Pre-change baseline, run-of-show, the one engine Go/No-Go shown beside the human sign-off, per-switch field cards, NRFU, pre/post compare, and PIR | `mop`, cutover gate owner, `--compare` diff |
| **Deliver** | Every deliverable with its evidence, scope, plan revision and gate state; saved investigations and handovers | deliverable generators |

**Shared by every workspace:**
- **Find bar** (Ctrl/Cmd+K). It finds any object or takes a typed question; with the subject menu, it
  is one of two doors into the same registry.
- **Trust drawer.** Coverage, collection completeness, lineage and attestation, opened from the
  coverage chip.
- **Snapshot selector.** History and compare.

**Evidence control.** Every number shows one small evidence control: what it is based on and its
engine evidence state. It keeps every state the projection publishes (`ui_projection` `STATES`, for
example not collected, collected but empty, analysis unavailable, unverified, not assessed), with its
reason, caveats and any lower-bound disclosure. It replaces the repeated "Published / Qualifications"
labels; no honesty state is removed or merged.

New capabilities (for example digital-twin style queries, protocol packs, a device console)
**arrive as engine question kinds and checks**. The workspaces show them through the same
registries. The structure does not change per feature.

## Consequences

- Workstream RC8-P1-H (single-source hardening) implements point 4 and retires or rewires the
  audited duplicates. Point 4 is in force only once that work merges with exact-head evidence.
  RC8-P1-G (the Investigate canvas) reads only the projection. Other work builds on that foundation
  rather than adding surfaces.
- Some interface features temporarily lose interactivity until the engine publishes the matching
  owned result. That is accepted: a missing feature is visible, while a wrong number is not.
- The offline HTML explorer becomes a rendering of engine output. Analysis it cannot get from the
  engine is removed from it, not reimplemented in JavaScript.
