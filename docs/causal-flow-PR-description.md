# PR: Causal Flow for every finding family (explorer + AssessHub)

> Branch: `feat/asne-rig-and-ssot` · 3 commits: `9327bba` (engine) · `6875e2d` (explorer) · `058e34f` (webapp)
> Paste the body below into the GitHub PR when reopening.

**Suggested title:** `feat: Causal Flow for every finding family (explorer + AssessHub)`

---

## What & why
The blast-radius explorer had one standout visual — a **Trigger → Mechanism → Impact → Mitigation** "causal flow" — but it only covered 3 structural-SPOF types. This generalises it to **every finding family the assessment surfaces** (19 on the AJ fleet) across **both** surfaces — the offline explorer *and* the AssessHub web platform — and adds a **bowtie** layout for multi-cause cross-layer compounds.

On the AJ fleet that's **2,152 causal flows across 19 families** (Structural SPOF 324, Cross-layer 513, Compound risk 665, Health 200, Inventory 143, STP 104, Protocol 75, FHRP 52, Design decisions 30, Addressing 11, Security, Operational-logs, False-health, L1/L3, Software, QoS, Multicast, Timing).

## What's in it (3 commits)
- **`feat(causal)`** — `cisco_toolkit/causal.py::compute_causal_flows(snap)`: the canonical normalization that maps `causality`, `cross_layer`, `design_blueprint` and the `punchlist` into one trigger→mechanism→impact→mitigation list (cross-layer ⇒ bowtie). Pure function of the snapshot and the canonical source the explorer JS and the webapp both mirror.
- **`feat(explorer)`** — generalises the explorer's Causality mode to all families with family + severity filters and the bowtie renderer.
- **`feat(webapp)`** — `GET /api/snapshots/{id}/causal_flows` + a React `CausalFlow.tsx` panel, matching the webapp's "server computes, the UI never re-derives" doctrine.

## The visual (research-grounded)
Two parallel research passes (bowtie/barrier analysis, FTA, Ishikawa, Sankey, WCAG colour + motion; Datadog/IP-Fabric blast-radius patterns) drove the design:
- Linear chain by default; **bowtie** when a finding has multiple contributing causes (cross-layer compounds) — causes converge on a centre *top-event*, then a single propagation edge reaches the impact.
- **Connector width ∝ blast magnitude** (Sankey); **severity = colour + shape glyph + label** (WCAG redundant encoding, colour-blind-safe); evidence chips + confidence.
- Cross-layer bowties render an **absent-preventive-control** glyph (⊘) per cause and a **✓ FIX** barrier on the recovery edge — honest: the *missing* control is the finding; the FIX renders the engine's own recommendation.
- Cross-layer magnitude surfaces the **VLAN count** ("53 VLANs"), matching the finding's own title, instead of "1 device".

## One source of truth
The engine `compute_causal_flows` is canonical; the explorer JS is a verified port; the webapp reads the engine output verbatim. Output is **byte-identical** across all three surfaces for any given snapshot (verified at runtime). The webapp computes `design_blueprint` on the fly when not stored (mirroring `/design`) so the design-decision family appears on demo snapshots too.

## Robustness & two bugs that runtime refutation caught
A multi-agent adversarial QA pass HELD on SSOT, dedup and coverage-honesty — but **missed two real bugs that runtime refutation then caught**:
1. **Malformed-snapshot crash** — a truthy non-list field (e.g. a string where a list was expected) slipped past an `x or []` idiom and 500'd the endpoint. Fixed with `Array.isArray`-style type guards + per-item dict skips + hashable-safe severity; the function is now total over any dict.
2. **505 duplicate React keys** — cross-layer `CL-xx` ids repeat (303 findings share `id="CL-02"`), so id-based keys collided. Fixed to index-based keys.

Both fixed **test-first**. (Lesson worth keeping: a verifier reasoning from code without running real data can miss a data-shape bug.)

## Testing
Engine causal-flow suite + webapp endpoint tests cover: family counts, cross-layer dedup, coverage-honest blast units, malformed-snapshot robustness, key-uniqueness (incl. the repeated-CL-id regression), the xlayer-only VLAN magnitude, and cross-endpoint SSOT. **Engine suite green · webapp 41 passed · `tsc` + `vite build` clean · `node --check` on the explorer script OK.**

## Notes
- **Purely additive** — no change to `analyze.py`, the frozen golden, `COLLECT_PARSE`, or `pyproject` (the schema/version is untouched; this is feature work, not a release).
- Reduced-motion-safe; the explorer mode button is relabeled "Causality" → "Causal Flow" with the mode key unchanged (hash routes/tests intact).
