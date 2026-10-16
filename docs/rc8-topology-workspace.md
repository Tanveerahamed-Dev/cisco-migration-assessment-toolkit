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
