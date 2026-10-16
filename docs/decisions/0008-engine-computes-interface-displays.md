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
engine as the target owner of every analysis fact. That rule was never enforced mechanically. Surfaces
built before and after it kept their own calculations.

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
2. **Interfaces display only.** The AssessHub app (in the native Atlas window), the topology
   workspace, Atlas Scope, the generated HTML explorer and every document may format, sort, filter,
   page, lay out, colour and animate engine output.
   - They must not count, band, score, simulate failures, trace paths, evaluate ACLs, decide
     readiness or Go/No-Go, or infer anything.
   - When a screen needs a value the engine does not publish, the engine gains an owned fact first,
     registered in `docs/ssot.md` with a reconcile or owner test. The screen then displays it.
3. **One application, one home.** AssessHub in the native Atlas window is the product. A snapshot
   opens in the topology-first workspace, with every tool reachable from the topology. Each surface
   that duplicates the engine is either rewired to the projection or retired. While a duplicate
   still exists, a two-sided parity gate must pin it.
4. **Enforcement is code, not prose.** CI is the authority.
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

**The Atlas app is the only front end:** the AssessHub React app (`webapp/frontend`) in the native
Atlas window.
- The HTML explorer and Atlas Scope stop being separate user-facing front ends.
- Their best ideas are rebuilt as views inside the Atlas app on engine data: the topology canvas,
  the cable map and the tool side panel.
- The 2-D topology uses the app's existing `d3-force` dependency.
- The `/scope` entry and the explorer link leave the app.
- Customer-facing outputs are the generated documents (workbook, HLD/LLD, MOP, NRFU, deck,
  runbook), not another interactive surface.

**Navigation follows the consultant's engagement lifecycle (Assess, Plan, Change, Validate, Report).**
Left rail: **Engagements** (campaigns, New assessment). Inside an engagement and snapshot, six tabs:

| Tab | What it answers | Engine source |
|---|---|---|
| **Network** (default) | What is out there and how it connects. Topology and cable map with search and overlays: health, lifecycle, findings, VLAN. The side panel opens a device, failure impact ("if this fails"), a path between A and B, endpoint finder (MAC or IP to switch, port and VLAN), and VLAN carriage. | `project_topology`, `project_device`, `project_path`, `project_vlan_carriage`, `project_inventory` |
| **Findings** | What to fix first: the prioritised punch list, filterable, each item linked to its device on the map | `project_findings` |
| **Inventory** | Devices, software, lifecycle and EoX, VLANs and endpoints, with export | `project_inventory` |
| **Plan** | Requirements, design (HLD/LLD), move groups and waves, saved plan revisions | design owners, saved plans |
| **Change** | Cutover runbook and MOP, per-wave Go/No-Go (one engine gate), NRFU, and pre/post compare | `mop`, cutover gate owner, `--compare` diff |
| **Reports** | Download every deliverable for the customer | deliverable generators |

Every number shows one small evidence control: what it is based on, and whether it was not
collected or collected empty. That replaces the repeated "Published / Qualifications" labels; no
honesty state is removed. Coverage (the old Trust screen) appears as a banner on every tab and as a
filter on the Network tab. History and compare are reached from the snapshot selector.

New capabilities (for example digital-twin style queries) attach to one of these tabs after the
engine publishes them. The structure does not change per feature.

## Consequences

- Workstream RC8-P1-H (single-source hardening) implements point 4 and retires or rewires the
  audited duplicates. RC8-P1-G (topology workspace) reads only the projection. Other work builds on
  that foundation rather than adding surfaces.
- Some interface features temporarily lose interactivity until the engine publishes the matching
  owned result. That is accepted: a missing feature is visible, while a wrong number is not.
- The offline HTML explorer becomes a rendering of engine output. Analysis it cannot get from the
  engine is removed from it, not reimplemented in JavaScript.
