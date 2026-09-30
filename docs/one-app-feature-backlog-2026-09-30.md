# One-application feature backlog (2026-09-30)

> **Dated record.** Candidate features, ranked. Before starting one, give it a row in
> `docs/NOW.md`. Direction and decisions: `docs/decisions/0007-one-application-direction.md`.

This backlog comes from a clickable prototype of the one application, built entirely from the
engine's fictional sample fleet (`webapp/sample_data/sample_fleet.snapshot.json`), followed by
independent reviews of data fidelity, visual/UX and product/persona. Each entry names the user
value and the engine data it needs. Items marked **(engine)** belong in `cisco_toolkit/`, because
screens only render engine output (ADR 0007, D9).

## Ranked

1. **Evidence-aware health (engine).**
   - What: publish per-input health states and a data-quality discount, so a device whose security
     or config inputs were never collected cannot score "Good".
   - Why: today the score only knows what it deducted, so absent evidence looks healthy.
2. **Analysis-input axes in `coverage_matrix` (engine).** Add config, logs, platform, lifecycle
   authority, RIB and STP-capture axes, so the Trust view reads coverage from one owner.
3. **Stranded-set blast radius (engine).**
   - What: `failure_impact` gains per-VLAN stranded host, endpoint and link identifiers. Today its
     rows are counts only, and the per-VLAN detail exists only as capped prose.
   - Why: this unlocks an honest animated "what breaks" story.
4. **Rule identifiers on punch-list findings (engine).**
   - What: stable IDs linking each finding to its remediation item, design decision and MOP step,
     with the wave taken from move groups.
   - Why: enables grouped action cards instead of 146 separate rows.
5. **Engine-owned CAB pack, `cutover_plan/1` (engine).**
   - One reconciled wave count: three engine owners currently disagree on the sample.
   - Go/No-Go readiness moves out of `webapp/backend/cutover.py`.
   - Human decision records: window, rollback owner, approver.
6. **Role inference and a published tier basis (engine).**
   - The problem: the sample's core devices carry the role `distribution`, so the cable-map tier
     seed falls back to the highest-degree node, an uncollected access point.
   - The fix: publish the tier basis, and regenerate a realistic sample fleet with RIBs and an
     intent catalogue.
7. **Per-switch field card.** One page per switch for on-site work: validation steps, NRFU cases,
   physical rows, native-VLAN mismatches. Printable through the document generators.
8. **Retained, secret-scrubbed evidence with CLI-line citations** (ADR 0007 D10). The evidence
   drawer then reaches the exact capture line.
9. **Precomputed path catalogue (engine).** FIB traces for endpoint-to-gateway and SVI-to-SVI
   pairs, computed at assessment time. Path & Flow then renders engine results instead of
   recomputing them.
10. **Pre/post-cutover diff on the map.** Stable identifiers across the snapshot delta and the
    cable-map diff, drawn on the same pinned layout.
11. **Site hierarchy and aggregate nodes (e.g. "access ×17").** Needed for legible topology at
    300+ devices.
12. **Architecture-class grid** with "show hosts on map", plus application, segmentation,
    service-map and subnet views.
13. **One checks library.** Architecture review, CIS, readiness and NRFU as pass / fail / not
    assessed, with history across snapshots.
14. **Freshness policy (engine).** A per-section "stale" state based on evidence age.
15. **Requirements capture** for design decisions that are waiting on requirements.
16. **Failover what-if through the backend,** labelled as the exploratory tier, not assurance.
17. **Engine hygiene:**
    - flag capped lists (a list truncated at 20 must say so)
    - JSON-Pointer addressing in `ssot` lineage
    - remove duplicated readiness prose
18. **Task test extensions:** a small-multiples arm and per-task-type verdicts, for the 2-D vs 2.5-D
    decision.
19. **Export to PNG/PDF with a provenance footer** for Overview, Findings and Cutover. Managers and
    CAB mostly see the product through exports and screen share.
