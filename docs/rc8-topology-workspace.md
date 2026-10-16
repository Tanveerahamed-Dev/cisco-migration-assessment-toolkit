# RC8-P1-G: one topology-first snapshot workspace

Owner direction, 2026-10-16: the default snapshot experience is the existing
Explorer's interactive topology and Cable Map, with every tool reachable from
that working surface. Judge it as a Cisco Advanced Services consultant carrying
out a brownfield assessment and migration. Design for the Atlas desktop window.
This supersedes the earlier proposal to deliver each investigation as a primary
page. There is one Atlas application and one snapshot workspace.

## Delivery stages

1. **Default workspace foundation (this PR).** Open the existing Explorer at
   Cable Map immediately, using the remaining application-window area. Retain
   its health, layers, search, right-hand drawer and complete mode registry.
   Preserve that frame across secondary Core tabs. Keep exact Core deep links
   and Tools/downloads available. Replace repeated per-value Published,
   Evidence and Qualifications controls with one Info control; keep withheld
   states, immediate reasons and minimum-count markers visible.
2. **Source-bound selection and dossier.** Separate the selected subject from
   mode-local choices. Device, interface, link, VLAN and endpoint selection
   drives the right-hand dossier and evidence drawer. A strict adapter must
   preserve snapshot bytes/form, exact subject identity, ambiguity and stale
   response rejection across the opaque iframe boundary. Keep the sandbox.
3. **Investigation panels.** Launch device failure/stranded-endpoint analysis,
   source/destination path and traffic questions, MAC/IP endpoint identification
   and VLAN carriage overlays from the selected topology. New facts come from
   Python/`ui_projection`; preserve each model's own meaning and limits.
4. **Assessment overlays.** Health, findings, lifecycle, protocol and cross-layer
   overlays expose a selected subject's deciding evidence and next check. Retain
   the engine's ordering, severity, absent evidence and bounded population.
5. **Comparison, migration and handover.** Launch before/after inspection,
   proposed moves, prerequisites, validation, rollback and draft handover from
   the same topology. Keep observations, model results, proposals, approval and
   execution distinct. Integrate the separately owned saved-plan/document
   contracts; do not duplicate them.
6. **Desktop field refinement.** Verify application-window scaling, keyboard
   operation, interrupted work/recovery, accessibility, larger-network behavior
   and a consultant/operator study. The separate WebView2 packaging workstream
   owns the native host. Essential workflows must not depend on a browser popup.

Each stage is delivered as bounded reviewable PRs. Complete all 15 protected
contexts and applicable whole workflows on the final head, then stop for
independent review. This workstream has no merge or release authority.

## The next complete consultant journey

Start with **select a device -> understand collection and dossier -> inspect a
cited finding/interface -> open its evidence -> state the next check**. The
existing Python projection already owns these answers. Keep the topology visible
and change the right panel; do not create another primary assessment page.

The panel leads with a useful name/role and collection boundary, followed by the
deciding assessment, relevant interfaces/relationships, findings, and next
evidence request. Basis, source pointers, indices and full qualification text
stay in Info. A withheld answer, Unknown, a lower bound or a material modeling
limit must remain understandable before the engineer opens that detail.

Stage 2's first exit is one joined investigation, not universal dossier parity:
select a collected device -> select one engine-ordered finding -> inspect its
cited interface/relationship -> open that exact envelope -> return to the same
device and topology context. Verify both a valid citation and a missing or
ambiguous citation. A nearby finding on the same device is not causal evidence.

Distinguish collection time from import time, and show unknown collection time
as unknown. Source identity is not freshness or complete coverage. A collected
device can still have an unassessable protocol, gateway or other domain; retain
that material limit beside the conclusion using the supplied owner state.

Finish with a concrete evidence request: exact subject, requested command/data,
uncertainty it would resolve and decision still pending. At this stage it is an
on-screen investigation/request, not a promised saved case. First-PR frame
retention across Core tabs is session-only. Durable reopening belongs to the
reviewed saved-plan/handover integration, which must retain these exact sources.

| Selection or intent | Right-panel behavior | Python contract and remaining work |
|---|---|---|
| Device | Dossier, collection, health/lifecycle, relevant interfaces, findings and evidence; offer explicit failure investigation. | `ui_projection._device_page` / `project_device`, served by `/ui-projection/device?host=...`. Use exact host joins and supplied states; uncollected is not an empty healthy dossier. |
| If this device fails | Present the stored model's own scope, impact and limits; keep the hypothetical target visible. | Device/fleet `failure_impact` uses `_topology_impact` and the existing `analyze.compute_failure_impact` rows. Complete identities of stranded endpoints and arbitrary cable cuts need new Python result contracts; current counts exclude the removed host's own endpoints. |
| Connection | Show both device/port ends, bundle/member identity, reporting basis and relevant VLAN context. | Join by published cable/member identity. Never infer a peer port, bundle member or carrier from proximity in the drawing. |
| MAC/IP search | Present distinguishing attachment candidates; require a deliberate choice before filling a path or flow question. | Current `_endpoint_rows` projects a port-level summary, not a complete full-observation lookup. Extend Python upstream of first-MAC loss, with aliases, ambiguity, no-match, partial evidence and complete-source pagination. Shared IP alone is not a duplicate-IP fault. |
| Source/destination path | Preserve both chosen endpoint observations and exact addresses; explain ordered hops and deciding evidence. | `project_path` and `/ui-projection/topology/path` disclose the stored IP route model. They do not evaluate ports, ACL/NAT/stateful policy, reverse delivery or VRF selection. Keep legacy L2 Path trace and Flow separately named. |
| VLAN overlay | Highlight the stored relation/basis for that VLAN and expose cable/member evidence. | `/ui-projection/inventory/carriage` selects the exact VLAN source index and typed stored page. Configured allowance, observed STP, unsupported and unknown states remain different; this is not end-to-end service proof. |
| Findings/lifecycle overlay | Select the affected host or cited record; retain engine severity, dates, source states, order and remediation references. | Device facts, `_findings` and their published row memberships supply the meaning. No client rescoring, recount, positional correlation or Unknown-to-healthy mapping. |
| Why / evidence | Open the exact selected envelope with source identity, basis, references, reason and qualifications. | The current drawer reads snapshot pointers. Original command/line evidence needs a separate retained, scrubbed-capture custody/content contract; never manufacture CLI evidence from a summary. |

## Selection and mode are different

- Clicking an object inspects its observed context. It does not remove it from
  the network or silently start a simulation.
- A selected subject is typed and source-bound: snapshot bytes/form plus exact
  host, interface, cable/member, VLAN or attachment identity. Display names and
  an IP string alone cannot establish that identity.
- Use as source/destination is an explicit action. Preserve the chosen alias
  and observation; never silently select the first ambiguous match.
- The same incident can inspect a related observation without changing its
  question. If a different hypothetical is retained, label both contexts rather
  than applying the hypothesis to the newly selected object.
- Current topology, hypothetical failure, observed comparison and proposed move
  have distinct states and visual patterns. Returning to the current model
  clears incompatible graph/list/answer overlays together.
- Source, subject or question changes invalidate incompatible answers. Ignore
  late responses and old restored state. Back returns to a meaningful prior
  investigation, not just a tool name.
- The eventual iframe adapter accepts selection intents only, with exact
  window/session/source validation and closed messages. Opaque `origin: null`
  is not sufficient authentication. The child cannot publish its own facts or
  gain same-origin access to the parent API.

Canonical Traffic Assurance remains a separate Python-owned finite saved-intent
result. These owners have no existing typed UI projection for it, and the
Explorer embed omits that section. A future panel needs an exact retained-result
lookup contract, not a new browser evaluation or a relabeled legacy Flow result.

Use one selected relationship and one explanation at a time. On a laptop, keep
the deciding neighborhood legible and reveal wider context on demand. In a
narrow window, the same inspector can become a drawer while retaining the
selected subject and return path. Guided next checks and expert tools share this
state; they do not become competing applications.

## Exit criteria for later panels

- Establish essential keyboard focus, panel fit and return navigation in every
  delivered slice; do not defer minimum usability to Stage 6.
- A published modeled result still names its population and material scope:
  excluded local endpoints in the current failure measure; unevaluated traffic
  policy, reverse delivery and VRF choice in the current IP-path result. Info
  retains the full basis, not the only indication of a deciding limitation.
- An absent future contract is a clearly unavailable capability. Do not replace
  it silently with a stronger-looking legacy calculation or an empty answer.
  Stage 2's dossier readings precede Stage 4's fleet overlay integration.
- The migration handover binds each proposed move to exact baseline/follow-up
  evidence, unresolved prerequisites, validation criteria and rollback conditions
  through the separately owned saved-plan/document contracts. Reopening retains
  observed, modeled, proposed and human-approved statements as different kinds.
- Comparison success alone does not establish readiness or acceptance. Name the
  responsible human design/peer-review/CAB checkpoint and the evidence still
  preventing advance; never infer approval or execution from a generated brief.

## First-PR boundary

`SnapshotWorkspace` is the default `/snapshots/:id` entry. It embeds the existing
`/api/snapshots/{id}/explorer#mode=cablemap` response. Query-only Core navigation
keeps the same iframe mounted but hidden and inert; an initial explicit Core
deep link does not generate an unused Explorer. Switching snapshots or explicitly
reloading creates a fresh frame. Existing `?view=...`, device, reference and
stored-source checks still execute in `CoreSnapshot`.

The iframe keeps `allow-scripts allow-downloads allow-modals` and excludes
`allow-same-origin`. No parent access to its DOM, new message protocol or new
analysis is introduced. Browser-level frame errors expose retry; HTTP generation
errors remain visible inside the opaque frame and can be retried with Reload
topology. A frame load event is not treated as successful analysis.

Core values keep their exact envelopes in the same identity-bound Info drawer:
state, reason, basis, subject, references, qualifications, engine state and digest
with its form. Axis indices/basis sections move there as supplied metadata.
Published zero remains zero. Withheld states and their reasons, lower-bound
markers/reasons and separately owned ratio qualifications remain explicit.

## D9 ownership and remaining integration work

ADR 0007 D9 assigns facts to Python and `ui_projection`, and geometry to the
browser; existing calculations converge by rendering or bounded parity tests.
The reused Explorer still contains legacy browser calculations for failure,
VLAN path, IP route and Flow. Their existing parity/safety tests remain unchanged.
Promoting the renderer adds no calculation and does **not** complete D9
convergence or turn legacy Flow into canonical Traffic Assurance.

Likewise, the current renderer intentionally clears some mode-local selections.
Keeping its frame alive across Core tabs does not solve cross-mode subject
handoffs. Stage 2 must establish that contract before new integrated panel facts
or universal selection persistence are claimed. No relaxed iframe origin,
browser inference, hand-maintained duplicate tool registry or guessed identity
is an acceptable shortcut.

## Validation and custody

Runtime tests, builds, browser journeys and artifact admission run on GitHub
only. The existing source-bound frontend producer and hosted dist receiver own
generated output. Import only an independently reviewed admitted patch; the
imported head needs fresh rebuild and required-check evidence.

Before every push, run the repository privacy gate and scan all new commit
messages/per-parent patches and publication text using the canonical client
marker patterns. Preserve golden/sample bytes and every existing gate, budget
and assertion. Failed, superseded, skipped and unrun results remain explicit.
Neither CI nor this plan establishes human field acceptance or release approval.
