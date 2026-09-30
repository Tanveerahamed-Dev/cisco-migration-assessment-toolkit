# Single Source of Truth (SSOT) contract

> This is the **assessment-facts** contract — one domain of the project-wide SSOT registry.
> For the full map of every fact-domain and its owner, see [`docs/ssot.md`](ssot.md).

The assessment publishes each **headline fact exactly once** and every downstream surface — the
DOCX/PPTX/XLSX deliverables, the HTML explorer, the campaign trend, and the AssessHub web
dashboard — **reads** that one canonical value. No surface recomputes a headline number from the
raw arrays, and no surface conflates a sibling field. This document is the contract; it is enforced
mechanically (see *Enforcement* below), not by convention.

## Why this exists

A headline number that is computed in two places will eventually disagree. The recurring failure
this contract kills — found and fixed by hand, one surface at a time, across several audit waves —
is the **end-of-support conflation**: a surface reads `lifecycle_risk.summary.n_past_eos` (0 on the
Meridian reference fleet) where it means the *past-support population*, which is `n_past_ldos` (152). The result is a
false "healthy" reading that silently drops 152 end-of-support devices. Its near-twin is a device
count rendered from `len(devices)` / `len(health_scores)` instead of the published
`executive_brief.scale.n_devices`.

The lifecycle bands are **mutually exclusive**: `Past-EoS` means *past end-of-sale but not yet past
LDoS*; every `Past-LDoS` device is also past end-of-sale. So the migration-critical "past support"
headline population is **`n_past_ldos`**, never `n_past_eos`.

## The canonical facts

The single authoritative location for each fact (see `cisco_toolkit/ssot.py :: CANONICAL_FACTS`):

| Fact | Canonical path | Raw-evidence derivation it must equal |
|---|---|---|
| `n_devices` | `executive_brief.scale.n_devices` | `len(health_scores)` == `collection_completeness.summary.inventory` |
| `n_collected` | `executive_brief.scale.n_collected` | `collection_completeness.summary.complete` |
| `n_endpoints` | `executive_brief.scale.n_endpoints` | `len(endpoint_identity)` |
| `n_vlans` | `executive_brief.scale.n_vlans` | `len(analyze.vlan_inventory(snap))` |
| `n_domains` | `executive_brief.scale.n_domains` | — |
| `avg_health` | `executive_brief.posture.avg_health` | `round(mean(score))` over the health-**scored** rows (finite score, band ≠ `Insufficient Data`); `null` when none is scored |
| `n_critical` | `executive_brief.posture.n_critical` | `count(health_scores[].band == "Critical")`; `null` when nothing is scored and no Critical band is observed |
| `n_poor` | `executive_brief.posture.n_poor` | `count(health_scores[].band == "Poor")`; `null` when nothing is scored and no Poor band is observed |
| `worst_band` | `executive_brief.posture.worst_band` | most-severe band present in `health_scores[].band`; `null` when nothing is scored and no band is observed |
| `n_past_ldos` | `lifecycle_risk.summary.n_past_ldos` | `count(per_device[].band == "Past-LDoS")` |
| `n_past_eos` | `lifecycle_risk.summary.n_past_eos` | `count(per_device[].band == "Past-EoS")` |
| `n_near` | `lifecycle_risk.summary.n_near` | `count(per_device[].band == "Near-LDoS")` |
| `n_active` | `lifecycle_risk.summary.n_active` | `count(per_device[].band == "Active")` |
| `n_design_decisions` | `design_blueprint.summary.n_decisions` | `len(design_blueprint.decisions)` |

## How to read a headline fact

Use the accessor — never re-derive:

```python
from cisco_toolkit import ssot
facts = ssot.canonical_facts(snap)   # {"n_devices": 303, "n_past_ldos": 152, ...}
```

An unpublished block reads back as `None`, never a silent `0` (coverage-honest — "not published" is
distinct from "zero"). A surface may keep a `len(...)` fallback for the pre-brief assembly window
(the brief's scale is injected late), but the canonical value must take precedence when present —
the established `_scale.get("n_devices") if ... is not None else len(...)` idiom (e.g.
`cisco_toolkit/html.py`, `webapp/backend/nrfu_docx.py`).

### A fleet with nothing health-scored (`avg_health: null`)

When no device produced a health score (every row is `Insufficient Data`, or there are no rows), the
engine publishes the **abstention**, not a number: `posture = {avg_health: null, worst_band: null,
n_critical, n_poor, n_scored: 0, not_assessed: "no_health_rows" | "all_insufficient_data" |
"no_scored_rows"}` (`n_scored` / `not_assessed` appear only on this path, so the scored posture keeps
its four keys). `n_critical` / `n_poor` are `null` there too unless that band was actually observed (a
zero count over a fleet with nothing scored is the same absence), and with no health rows at all
`scale.n_devices` is `null` (`len([])` is not an inventory; consumers fall back to their own count).
The "Fleet health" axis reads `NOT ASSESSED` at severity `Info`, and the posture statement carries a
"fleet health is NOT ASSESSED" flag, so it can never conclude "no top-tier blockers". A **partially**
scored fleet is not the clean-fleet `Low` either: with no adverse band the axis is `Info`, its headline
names the `k of N NOT ASSESSED`, and the posture statement carries the same flag for the remainder.

Every surface reads the average through **`ssot.fleet_avg_health(snap)`** (the explorer mirrors it in
`fleetHealthState`), which returns `measured` / `not_assessed` / `unverified` / `unpublished`. It
decides on the **key**, not the value: `avg_health` present and `null` is the published abstention and
must never be replaced by a recompute (an `Insufficient Data` row keeps its deduction-free score, so an
all-rows mean fabricates ~100). A stored **number** over zero scored rows — every pre-G15 snapshot's
hard `0` — is `not_assessed` too, and a non-numeric value is `unverified` (never "0 of N scored"). Only
an `unpublished` brief (absent / failed / pre-posture) may recompute, over scored rows only.
`ssot.reconcile` checks both directions for `avg_health`, `n_critical` and `n_poor`: a number published
for zero scored rows, and `null` published while rows are scored (or the band is observed), are
violations. When the `Health Scores` phase itself failed, its `[]` is not a raw basis: nothing is
checked against it and nothing is counted as verified.

### Abstention states

`ssot.abstention_reason` (and the `schema_census` built on it) returns one of `ssot.ABSTENTION_STATES`:
`published`, `collected_but_empty` (collected, genuinely nothing found), `not_collected` (a blind spot),
or `analysis_unavailable` — the section's analysis phase failed this run (`assessment_integrity`
`failed_phases` / a failure-token stamp / an `_unavailable` sentinel), so its value is a fallback and
not evidence. Failure labels are attributed to sections through `ssot.PHASE_SECTIONS`, which an AST
ratchet (`tests/test_ssot_failed_phase_abstention.py`) keeps complete against
`COLLECT_PARSE_V3_23_0.main()`; a label that cannot be attributed fails closed (every evidence-free
section reads `analysis_unavailable`). `schema_census.summary.n_analysis_unavailable` is emitted only
when non-zero.

A headline fact stored under `executive_brief` is **derived** from other sections, so the abstention
core also checks its raw basis: `ssot.DERIVED_FACT_BASIS` maps each dotted prefix
(`executive_brief.posture` -> `health_scores`, `executive_brief.scale.n_endpoints` ->
`endpoint_identity`, ...) and `ssot.fact_basis(path)` resolves the longest one. A fact whose basis phase
failed is `analysis_unavailable` in the lineage and the assertion pack — never a `collected_but_empty`
zero that a `n_critical == 0` assertion passes over. The same ratchet file requires a basis for every
`CANONICAL_FACTS` path under `executive_brief`.

## Enforcement (mechanical — runs in CI)

1. **Producer invariant** — `ssot.reconcile(snap)` returns every published canonical value that
   disagrees with its independent raw-evidence derivation, and is asserted empty on the *real,
   in-process-assembled* snapshot (`tests/test_pipeline_inprocess.py`). Coverage-honest: a fact is
   only checked when both the published value and its raw basis are present.
2. **Cross-surface render lock** — `tests/test_ssot_reconciliation.py` renders the lifecycle/scale
   deliverables (crd, engagement, runbook, archreview, mop, design) from a fixture carrying the Meridian
   trap values (`n_past_ldos=152`, `n_past_eos=0`) and asserts each surface headlines the
   past-support population (152), never the conflated sibling (0). Mutation-proven to bite.
3. **Dashboard lock** — the explorer / campaign-trend header (`html._trend_point`) is unit-tested
   to read canonical scale/posture/lifecycle, not a recount.
4. **Webapp locks** — the web layer's canonical reads are locked in `webapp/tests/test_backend.py`
   (e.g. `test_nrfu_devices_in_scope_reads_canonical_scale`, the architecture-coverage SSOT).

## Adding a new canonical fact

1. Publish it once, in a canonical block, at snapshot assembly.
2. Add it to `CANONICAL_FACTS` in `cisco_toolkit/ssot.py` with its raw-evidence derivation.
3. Add a `check(...)` for it in `ssot.reconcile`.
4. If any deliverable headlines it, extend the cross-surface lock in
   `tests/test_ssot_reconciliation.py`.
5. Every surface reads it via `ssot.canonical_facts` — never a second computation.
