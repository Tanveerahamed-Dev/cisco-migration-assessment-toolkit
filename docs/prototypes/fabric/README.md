# Fabric — a coverage-honest topology engine (prototype)

A single self-contained HTML file that renders a role-tiered network fabric on WebGL2
and answers the question an engineer actually asks before a maintenance window:
**not** "what can this device reach" but **"what goes dark if it fails"**.

```
node docs/prototypes/fabric/verify.mjs     # 18 checks, exit 0 on pass
```
Open `fabric.html` directly in a browser to use it. No build, no dependencies, no network.

## Status: prototype, not shipping code

It runs on a **synthetic, wholly fictional** fleet generated in-file. It is not wired to
`/api/snapshots/{id}/graph`, and it is deliberately parked under `docs/prototypes/` rather
than in `webapp/frontend/` so it cannot be mistaken for a product surface. The field names
it models are the backend's real ones, so binding it to a live payload is a small change —
but that change has not been made or tested.

Its sibling in spirit is `cisco_toolkit/blast_radius_explorer.html`, whose design tokens
`webapp/frontend/src/theme.css` already mirrors verbatim. Fabric uses that same token set,
copied in, so it reads as the same product in both themes.

## Why it exists

`webapp/backend/graph.py` publishes three coverage-honesty fields — `bridge_assessed`,
`link_centrality_assessed`, `offscan_peers` — that no shipped frontend surface read when this
prototype exposed the gap. The shipped `TopologyGraph` now consumes them; this standalone file
remains the high-scale WebGL experiment. A fast picture that renders "not measured" identically
to "measured redundant" is a lie with a frame budget, and that is precisely what this repo's
third guardrail forbids.

So the organising rule here is that absence is drawn **louder** than health. Structural
totals are exact counts for the **resolved synthetic topology**, not bounds on a network
that collection did not fully resolve:

> 70 single points of failure and 344 critical links in the resolved topology. The real
> network's count and failure impact may be smaller if links missing from this graph provide
> alternate paths, or larger if uncollected devices introduce dependencies or chokepoints
> that are absent here.

## What it does

- **Counterfactual failure.** Click a device and the fabric is re-solved *without* it;
  every baseline-reachable device in the resolved topology that loses its path to the
  deterministic reference anchor turns red. The anchor is the highest-degree observed
  device, with ties settled by stable fleet order, and its name is shown with the result.
  One BFS, ~0.3 ms at 5,000 devices, so it runs live on click. This is a different analysis
  from the articulation-point pass: `isArt` says a device *is* a cut vertex, while this says
  exactly **which resolved devices** are stranded relative to that anchor. A cut vertex
  stranding two access switches and one stranding eight hundred are not the same finding.
  Selecting the anchor itself is explicitly **[REFERENCE ANCHOR] / unassessable**: deleting
  the reference cannot yield a meaningful stranded count. A device that had no baseline
  path to it is **[OUTSIDE BASELINE]**, also unassessable rather than a false zero.
- **Four evidence states on redundant channels** — observed-healthy, observed-degraded,
  **not observed**, collected-but-unparsed. Absence gets full opacity, a 68%-duty ink hatch
  and a broken ring, so it out-contrasts every health hue instead of receding.
- **Tier-gap edge bundling** (Holten Eq.1, β = 0.85) so a dense gap reads as trunks rather
  than a hairball. β is a live slider; **β = 0 is exactly the straight-line renderer**.
- **Deterministic layout** — role-tiered lanes, barycentre ordering, aspect-aware row wrap,
  seeded from the fleet content (FNV-1a → mulberry32, integer-only). The same fleet always
  produces the same picture, because engineers compare snapshots.
- **An honest substrate A/B.** The same layout and data rendered through SVG DOM instead of
  WebGL. The SVG path is capped, and the bench reports `svgElements` so the comparison is
  never presented as like-for-like.

## Decisions worth knowing, and what refuted the alternatives

**Layout is the performance decision, not rendering.** Measured on an Intel iGPU: 8,000
random "hairball" edges cost 12.4 ms of GPU time; the same count in tier-adjacent lanes cost
0.56 ms — a 22× gap, larger than every other lever combined. Edge length is an *output* of
layout, not a rendering parameter.

**Two draw calls, and a third pass that is counted.** Nodes and edges are one instanced call
each. Labels are a Canvas2D pass that the phrase "two draw calls" conveniently excludes —
crossing the label threshold once took a frame from 0.003 ms to 1.60 ms, a 485× cliff. It is
now capped at 400, prioritised by distance from the viewport centre, and shown in the
telemetry as `2 + N lbl`.

**Edge alpha was saturating before bundling existed.** With `over` blending, *n* coincident
strokes reach `1-(1-a)^n`; at the measured 95th-percentile depth of 11 the old 0.42 drove the
pixel to 0.998. Base alpha is `1 - 0.10^(1/11) ≈ 0.18` — derived, not chosen.

**Bundling costs nothing.** `vertexAttribDivisor(S)` means the CPU expands nothing: buffers
stay E-sized and instance *i* reads edge `floor(i/S)`. 5,553 edges × S=12 = **66,636
instances in the same 2 draw calls**, 0.084 → 0.100 ms. Subdividing a curve changes vertices,
not covered pixels, and this pass is fill-bound.

**Joints are crack-free without mitering.** Each segment takes its normal from the curve
derivative at its own endpoint parameter, so segment *j*'s far end and *j+1*'s near end
evaluate an identical expression on identical inputs — no crack outside a turn, no
overlapping sliver darkening the inside.

**Two hypotheses that measurement killed.** Normalising lane widths to shorten tier links made
mean |dx| *worse* (894 → 1228); attaching uplinks in contiguous blocks barely moved it
(1228 → 1211). Once a lane wraps into 37 rows of 120, X is a function of *column*, so a
full-width row attaches to parents clustered at one X and no ordering can align them. Long
world-space edges are inherent to wrapped lanes — and they do not matter, because at fit-zoom
the fabric compresses and screen-space fill stays small. The reasoning is left in the layout
function so it is not re-attempted.

## Verification

`verify.mjs` is the gate — 18 checks, all of which have failed at some point during
development:

| check | why it is there |
|---|---|
| β=0 is exactly the chord | Holten Eq.1 at N=4 has linear precision, so this is an exact identity (worst deviation 5.08e-13 over 2,385 sampled points), not a tolerance. It is the only reason the bundling maths can be trusted. |
| counterfactual ↔ articulation points | two independently written algorithms must agree; they do, 52/52 with 0 violations |
| picking exact across zoom | a fixed 3×3 cell scan silently missed 27% of clicks at minimum zoom, every failure a deselect |
| absence ≥ health, both themes | it was measured **backwards** — absence 2.8–3.5× *quieter* — which is the exact failure the picture exists to prevent |
| bench flags an unpainted frame | a "worst case 0.337 ms" was once a frame painting 0.00% of the buffer |
| SVG never claims GPU draws | the bench once reported `mode:"gpu", draws:2` while the context was dead and the SVG path had run |
| loop does not fork | a context restore used to leave a second self-rescheduling rAF loop alive: 1× → 2× → 4× frame cost |
| layout deterministic | snapshots get compared |
| coverage copy stays scoped | resolved-topology counts must not be advertised as global bounds; the copy names the anchor and both directions of uncertainty |
| rendered failure branches are semantic | the actual `#insp` is asserted for the live anchor, a non-articulation cycle anchor, and a disconnected component; neither unassessable case may masquerade as a count |

**Timing caveat.** `verify.mjs` runs under SwiftShader (software). Correctness results are
valid; frame times from it are **not** hardware figures, and the perf assertions are
deliberately loose. The hardware numbers quoted above came from an Intel iGPU via
`EXT_disjoint_timer_query_webgl2`.

## Known limitations

- Synthetic data only; not bound to the real `/graph` payload.
- `forced-colors` (Windows High Contrast) is implemented but **runtime-unverified** — it was
  not active on any machine available during development.
- With ~38% of links being bridges in the synthetic fleet, emphasis at α 0.9 dominates the
  picture. Correct for a poorly-redundant estate, but emphasis does less work than it would
  on a well-meshed fabric.
- Bundling reduced covered ink by only 1.7% here at fit-zoom (the source spec predicted
  ~10%), because the fan already overlaps heavily at that scale.
