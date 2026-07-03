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
[HISTORY-REDACTED] fleet) where it means the *past-support population*, which is `n_past_ldos` (152). The result is a
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
| `avg_health` | `executive_brief.posture.avg_health` | mean of `health_scores[].score` |
| `n_critical` | `executive_brief.posture.n_critical` | `count(health_scores[].band == "Critical")` |
| `n_poor` | `executive_brief.posture.n_poor` | `count(health_scores[].band == "Poor")` |
| `worst_band` | `executive_brief.posture.worst_band` | — |
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

## Enforcement (mechanical — runs in CI)

1. **Producer invariant** — `ssot.reconcile(snap)` returns every published canonical value that
   disagrees with its independent raw-evidence derivation, and is asserted empty on the *real,
   in-process-assembled* snapshot (`tests/test_pipeline_inprocess.py`). Coverage-honest: a fact is
   only checked when both the published value and its raw basis are present.
2. **Cross-surface render lock** — `tests/test_ssot_reconciliation.py` renders the lifecycle/scale
   deliverables (crd, engagement, runbook, archreview, mop, design) from a fixture carrying the [HISTORY-REDACTED]
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
