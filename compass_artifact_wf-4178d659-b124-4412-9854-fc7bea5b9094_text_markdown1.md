# Rebuilding the Blast-Radius Explorer: A Best-Practice Design & Interaction Playbook

## TL;DR
- **Replace the force-directed "wheel of spokes" with a Sugiyama-style layered (tiered) layout** that puts core/distribution at the top and access at the bottom, bundle port-channels into single visual edges, and keep all five modes but unify them under one shared canvas with a mode switcher and a single results drawer — this directly fixes the three biggest complaints (uninformative layout, dated look, confusing UX).
- **Adopt a Radix/Carbon-style semantic color-token system on a desaturated dark (or light) surface, never neon-on-black**, and encode state with color + shape + label (never color alone) so health bands, link states, and SPOFs are legible at a glance and colorblind-safe.
- **Kill the "sea of red" by de-duplicating and weighting findings into a transparent 0–100 score with explicit severity bands and a ranked "fix-this-first" list**; use degree-of-interest expand-on-demand and search/filter to explore 349 endpoints / 764 ports / 23 VLANs without cluttering the graph — all achievable in vanilla JS + SVG.

## Key Findings

1. **A star network must NOT be drawn with a force-directed layout.** Force-directed (spring) embedders place a single hub with ~12 spokes as a radially symmetric "wheel" that conveys no role hierarchy and wastes the strongest visual channel (vertical position). The literature is explicit that force-directed methods degrade and get stuck in local minima, while **layered (Sugiyama) and radial-tree layouts are purpose-built for directed, tiered, and hub-and-spoke structures.** For a core→distribution→access campus network, a **layered top-to-bottom layout** (the model used by Cisco's own topology tool, Graphviz/dot, and dagre) is the correct default, with **radial** as an optional "single-core-at-center" alternate.

2. **Encode every state with redundant cues.** Across Carbon, PatternFly, and NASA's Astro design systems, the consistent rule is that **status/severity is communicated through the combination of color + icon/shape + text label**, never color alone, and consolidated indicators should use the highest urgency present. Status colors need ≥3:1 contrast against background and against each other. Use a **temperature-based severity ramp** (neutral grey → blue/teal → amber → red) rather than red/green, because — per Colour Blind Awareness — "worldwide 8% of men and 0.5% of women have a red/green type of colour vision deficiency."

3. **Modern technical-tool aesthetics = semantic design tokens, not terminal neon.** Current (2024–2026) observability/network UIs (Grafana, Radix, Carbon) use a **12-step semantic color scale** with tokens assigned by *role* (background, subtle surface, border, hover, solid, text), a **desaturated/tinted-grey dark surface** (not pure black), and **proportional sans-serif type with tabular figures** for data — reserving monospace only for code/CLI/IP strings. Monospace for entire UIs hurts readability and wastes space.

4. **A multi-mode tool feels coherent when modes share one canvas, one selection model, and one results surface.** The dominant pattern is **one persistent graph + a mode switcher (tabs/segmented control) + a single right-hand detail drawer** that re-skins per mode, following Shneiderman's mantra: *overview first, zoom and filter, then details on demand.*

5. **The "cry wolf" problem is a calibration/deduplication failure with a well-known fix.** Every alerting discipline (SecOps, SRE, clinical) prescribes the same remedy: **deduplicate repeated/identical findings, weight by asset criticality and impact, roll up to a transparent additive score, and present a *ranked* shortlist** rather than a flat wall of equally-urgent flags. If "nearly everything lands in the highest-priority category, that may be a sign that the definitions are too broad."

6. **Dense data (349 endpoints, 764 ports, 23 VLANs) is explored via aggregation + degree-of-interest expand-on-demand + search/filter**, not by drawing everything. The canonical technique is van Ham & Perer's "Search, Show Context, Expand on Demand," which shows a focus node plus its most-relevant neighborhood and expands on click. SVG is performant enough for this tool's scale.

## Details

### 1. Hub-and-spoke / tiered topology layout (the single biggest win)

**Why the current force-directed star fails.** Force-directed/spring embedders (Eades; Fruchterman–Reingold; Kamada–Kawai) position nodes by simulating attractive/repulsive forces. For a star, the energy minimum is a symmetric ring of spokes around the hub — visually tidy but information-free: it hides the core/distribution/access hierarchy, can't show which switches are siblings, and the arXiv survey on spring embedders notes that for force-directed methods "results are poor for graphs with more than a few hundred vertices" and that the physical model "typically has many local minima." A star is exactly the case where force-direction adds nothing.

**Use the Sugiyama (layered/hierarchical) framework as the default.** This is the algorithm behind Graphviz `dot`, dagre, and yWorks' "layered" layout. The four classic steps (Sugiyama, Tagawa & Toda; refined by Gansner et al. 1993) are directly implementable in vanilla JS:
1. **Cycle removal** — temporarily reverse edges to make the graph acyclic (skip if already a tree/DAG, which a campus L2 hierarchy effectively is).
2. **Layer/rank assignment** — assign each node to a horizontal tier. For this network the ranks are explicit and *should be derived from device role, not computed*: rank 0 = VSS core/distribution, rank 1 = access switches, rank 2 = endpoints (shown on demand). dagre's three rankers are `network-simplex` (best quality, default), `tight-tree`, and `longest-path` (simplest — a DFS); longest-path is trivial to hand-code and is fine when you already know the ranks.
3. **Crossing minimization** — order nodes within each layer to reduce edge crossings, using the **barycenter/median heuristic** (Eades & Kelly) over a couple of sweeps. With ~12 access switches this is cheap.
4. **Coordinate assignment** — space nodes evenly within each rank; dagre uses Brandes–Köpf "Fast and Simple Horizontal Coordinate Assignment," but for 12–15 nodes simple even spacing centered under the core is sufficient.

Because the ranks are known a priori, you do **not** need to import dagre — you can hand-roll a ~50-line layered layout: bucket nodes by role into rows, sort each row by barycenter of its neighbors, assign x by even spacing, y by rank. This stays within the zero-dependency constraint.

**Offer a radial alternate for the "one core" view.** A radial-tree layout (yWorks, Cambridge Intelligence) places the core at the center and arranges access switches on a concentric ring, with endpoints on an outer ring revealed on demand. Cambridge Intelligence notes radial layout "is particularly useful if your data contains many child nodes for each parent" — exactly the hub-with-many-access-switches case. Use BFS-from-core for ring assignment and even angular distribution within each ring. Radial keeps the core from "dominating" because it occupies a small central disc rather than a giant central node.

**Tiered "rack/row" layout as a third option.** Cisco DNA/Catalyst Center's topology tool itself offers role-based layouts ("Enterprise Collapsed," "Enterprise Expanded") and lets users **assign device roles (Access, Distribution, Core, Border)** that drive placement — strong precedent that role-driven tiering, not physics, is the professional norm. It also supports pinning, saved layouts, and VLAN/Layer-2 filtering.

**Bundle parallel/port-channel links.** A star where each access switch has a port-channel (multiple member links) to the core produces visual clutter. Two complementary techniques:
- **Aggregate member links into one logical edge** by default (mirroring how a port-channel *is* one logical link), with a thickness or a "×N" badge encoding member count — Cisco's own tool shows "aggregated links" as a single line that expands to list underlying links.
- For genuinely many crossing edges, **edge bundling** (Holten & van Wijk's force-directed edge bundling; Holten's hierarchical edge bundles) routes similar edges along shared spline paths to "reduce visual clutter and reveal high-level edge patterns." For this tool's scale, simple aggregation is enough; reserve full bundling for the endpoint-expanded view.

**Curved edges for radial.** yFiles guidance: "For radial/hub-spoke layouts, use curved edges (Bezier, arc, or cardinal splines) that follow the natural radial flow from hub to nodes." SVG `<path>` with quadratic/cubic Béziers handles this natively.

### 2. Readability of node / link / state

**Node encoding (role, health band, selected/failed):**
- **Role → shape/icon.** Distinct glyphs per tier (e.g., core = layered/stacked rectangle, access = single switch rectangle, endpoint = small circle). Shape carries role even in greyscale.
- **Health band → fill color from a sequential temperature ramp**, bucketed into named bands (e.g., Healthy / Watch / At-Risk / Critical) rather than a raw continuous gradient — banding is more legible and ties directly to the severity system. Always pair the color with the numeric score as a label.
- **Selected → a high-contrast focus ring** (Radix uses step-8 of the scale for focus outlines); **failed/removed (blast-radius sim) → desaturate + diagonal-hatch pattern + an explicit "REMOVED" tag**, so the state survives colorblind viewing and printing.
- **Size** can encode endpoint count or port density, but keep the core from ballooning — cap node size and instead show magnitude as a badge.

**Link encoding (forwarding / STP-blocked / port-channel / SPOF):** network-diagram convention plus STP semantics give a clean vocabulary:
- **Forwarding link** → solid line.
- **STP-blocked/redundant standby link** → dashed line (mirrors how STP "blocks redundant links"; a blocked port is the classic dashed/amber state in switch UIs). Optionally an amber color token.
- **Port-channel/aggregated link** → thicker solid line or double stroke with a "×N members" badge. (Cisco's Nexus 9000 NX-OS guide notes you can "bundle up to 32 individual active links into a port channel"; note classic Catalyst/IOS EtherChannel is lower — 16 configured / 8 active — so the badge should reflect actual member count from the snapshot, not a fixed assumption.)
- **Single point of failure** → red/critical color **plus** a warning glyph **plus** thicker weight; never rely on red alone. SPOFs are the headline output of Path-trace and Flow modes, so they deserve the strongest, most redundant encoding.
- **Directionality/flow** (Flow mode L1→L3) → arrowheads or animated dash-offset along the path.

**Reduce clutter:** label on hover/focus rather than always-on; fade non-relevant nodes/edges to low opacity when a node is selected (focus+context); use a legend keyed to the exact tokens in use.

### 3. Modern professional UI for a technical tool

**Color system — adopt a semantic token layer (Radix/Carbon model).** Define a 12-step scale where each step has a fixed UI role: step 1–2 = app/surface background, 3–5 = component/subtle surfaces & hover, 6–8 = borders & focus rings, 9–10 = solid accents, 11–12 = secondary/primary text. This is exactly how Radix Colors and Carbon structure tokens, and it lets colors "be quickly adapted to dark mode or branding changes without overhauling the scheme." Implement as CSS custom properties (`--surface-1`, `--border`, `--text-hi`, `--accent`, `--status-critical`, …) on `:root`, with a `.light` / `.dark` class swap — pure inline CSS, no dependency.

**Dark done right (not terminal neon).** Use a **tinted dark grey** background (Radix "slate/sage/olive" tinted greys), not pure `#000`, with text at step 11–12 for contrast. Radix/Grafana both ship light + dark; offer both via a toggle. Keep accents desaturated; reserve saturated red strictly for genuine critical states — NASA's Astro UXDS is explicit: "Reserve red for states that are urgent and require immediate attention" (its critical fill token is `#FF2A04`).

**A recommended status palette** (blue/orange/teal family, colorblind-robust, per Tableau/Wong/IBM guidance and the SaaS-dashboard token example): success/healthy `#22c55e`-class green *with* a check glyph, warning/watch amber `#eab308`, critical red `#ef4444`, plus a neutral grey for "off/unknown," and a distinct **blue `#3b82f6`/teal accent** for selection and interactive elements so "selected" never competes with "critical."

**Typography.** Use a proportional sans (Inter, IBM Plex Sans, Source Sans 3 — all chosen for clear `1/l/I/0/O` differentiation and tabular figures) for UI and data tables, with `font-variant-numeric: tabular-nums` on all numeric columns so health scores and port counts align. Reserve a monospace (JetBrains Mono / system `ui-monospace`) **only** for IPs, interface names, and CLI snippets. Body/table text 12–14px, line-height ~1.4. (Since no web fonts are allowed, use a robust system stack: `system-ui, -apple-system, Segoe UI, Roboto, …` plus `ui-monospace` — both support tabular-nums on modern OSes.)

**Spacing & layout.** Adopt an 8px spacing scale; group related controls; generous white space between rows. Use a **left or top mode switcher**, a **persistent central graph**, and a **right detail drawer**. Provide proper **empty states** ("Select a switch to simulate its removal") and **legends** per mode.

**Information hierarchy.** Lead each mode with the single most important number (blast radius: # stranded endpoints; flow: risk score; health: readiness verdict), then progressive detail — Grafana's "one page = one decision" and RED-method "most important KPI where the eye lands first" principles.

### 4. Interaction ergonomics

- **Pan/zoom on SVG with zero dependencies:** manipulate the root `<svg viewBox>` (x, y, w, h) for pan/zoom, or wrap content in a `<g transform="translate() scale()">` and update the transform; keep UI chrome/legend *outside* the transformed group so it stays fixed. Mouse-wheel = zoom toward cursor (recompute viewBox origin from pointer position), drag = pan, with `min/max` scale clamps. Arrow keys nudge the viewBox for keyboard users.
- **Click-to-select** (blast radius, health): single click selects a node, populates the drawer, dims the rest.
- **Two-step source→destination** (path trace): first click sets source (badge "A"), second sets destination (badge "B"), Esc resets; show a persistent "Click source, then destination" hint until both are set.
- **Drag to reposition** with pinning (like Cisco's "pin to map"); persist positions in `localStorage` so a hand-tuned layout survives reloads.
- **Filter by VLAN/role** via a multi-select chip bar that fades-or-hides non-matching nodes (Cisco DNA supports "filter devices based on a specific Layer-2 VLAN").
- **Keyboard affordances:** `1–5` switch modes; `/` focuses search; `Esc` clears selection; `f` fit-to-screen; arrow keys pan. Document these in a `?` overlay.
- **Coherence across modes:** keep the same graph, camera, and selection when switching modes so the user never loses their place; only the overlay encoding and drawer contents change. This is what makes five modes feel like one tool rather than "five bolted-on screens."

### 5. Surfacing migration risk without "cry wolf"

**Diagnose the current bug first.** The symptom — "essentially every device flagged Critical/Poor because one finding type is counted many times" — is the textbook **duplicate-alert / opportunity-weighting** failure. The fix has three parts, all from established alerting and composite-index practice:

1. **Deduplicate and group.** Collapse repeated identical findings into one weighted finding with a count ("uplink-not-redundant ×6 ports → one finding"). SecOps practice: "collapse duplicates" and "group related alerts"; SRE practice: "you do not want 50 separate alerts for every failing health check."
2. **Weight, don't sum raw counts.** Replace naive additive counting (which lets one finding type dominate) with a **transparent additive risk model**: `score = base_severity × asset_criticality × impact`, capped and normalized to 0–100. Prophet Security's recommended model — "base severity, asset criticality, … exploitability, external exposure" yielding a 0–100 score "analysts can recalculate by hand" — is the right template. Composite-index research (UNECE) warns explicitly that weighting choices can produce a "perverse outcome where it appears the situation improves whilst it is actually getting worse," and recommends indices "be accompanied by dashboards … that give information about the" components — i.e., always expose the drill-down, never a black box.
3. **Band and rank.** Map 0–100 to a small set of severity bands (Astro/Carbon temperature ramp: Healthy / Watch / At-Risk / Critical) and route by band — the migration-readiness analog of Prophet Security's "route 80+ to senior triage, 50–79 to standard, sub-50 to auto-closure." Present a **ranked "fix-this-first" list** (top N issues by score) rather than a flat table. Use a **likelihood × impact risk matrix** mental model: SPOFs that strand many endpoints sit top-right (fix first); cosmetic findings sit bottom-left.

**The self-check:** the Security-Boulevard guidance is the exact rule the current tool violates — "if nearly everything lands in the highest-priority category, that may be a sign that the definitions are too broad." A healthy readiness dashboard should show a *distribution* across bands, with only a few genuine Criticals.

**READY / CAUTION / NOT READY** per move-group should be driven by the *worst unresolved high-weight finding* in that group, following Astro UXDS's consolidated-status rule verbatim: "Use the highest level of urgency status if multiple statuses are consolidated. For example, if the statuses of underlying components are green, yellow, and red, the consolidated indicator is red." Contributing findings should be expandable beneath the verdict.

### 6. Dense data at scale (349 endpoints / 764 ports / 23 VLANs)

**Default to aggregation; reveal on demand.** Don't render 349 endpoints by default. Show the ~13 infrastructure nodes; represent each access switch's endpoints as a **count badge** ("42 hosts") that expands to a list/sub-graph on click — Cisco's tool does exactly this with device aggregation ("Click a group of aggregated devices… Disaggregate All to ungroup").

**Degree-of-interest (DOI) expand-on-demand** is the canonical scholarly technique for this and maps perfectly to vanilla JS. Frank van Ham & Adam Perer — "'Search, Show Context, Expand on Demand': Supporting Large Graph Exploration with Degree-of-Interest," *IEEE Transactions on Visualization and Computer Graphics*, Vol. 15, No. 6 (Nov/Dec 2009), pp. 953–960, doi:10.1109/TVCG.2009.108 — advocate an interaction model where the user picks a focus node and the system shows an "optimal relevant context" subgraph, "expand[able] in any direction." They frame it as an explicit alternative to overview-first: "an alternative to the traditional 'overview, zoom, details on demand' browsing model … loosely characterized as 'search, show context, expand on demand'." Their motivating example is decisive — without DOI, a two-hop neighborhood "would contain 2345 nodes and 2847 edges … and would be impractical to visualize using a node link diagram," versus a compact ~25-node context. The DOI concept originates with Furnas's "Generalized Fisheye Views" (CHI 1986, pp. 16–23). Implement a simple `DOI = α·role_priority + β·distance_from_focus` and show only the top-N neighbors per expansion (van Ham & Perer keep expansion directions "small, n<5").

**Search + filter as first-class navigation.** A search box that highlights matching switches/VLANs/endpoints within the topology (Cisco supports fragmented search), plus VLAN and role filters, plus a **per-VLAN view** that isolates one of the 23 VLANs at a time. This is Shneiderman's "zoom and filter."

**Details on demand in the drawer**, not on the canvas: clicking a port/endpoint/VLAN opens its full attributes in the side panel, keeping the graph uncluttered.

**Rendering technology — SVG is sufficient here, no library needed.** Per Cylynx's review of yWorks' rendering benchmark (on a 2015 MacBook): "SVG performance … gives workable performance until it reaches 2k nodes and 2k edges. Canvas performance reaches the limit at 5k nodes and 5k edges while WebGL is usable until 10k nodes and 11k edges." This tool's *visible* graph is ~13 infrastructure nodes plus on-demand expansions — two orders of magnitude below the SVG ceiling — so **SVG (with per-node `<g>` groups) is the right choice**: it gives free hit-testing, hover, focus rings, and CSS styling. Only if a future "show all 349 endpoints at once" view is required would Canvas become necessary; even then, keep SVG for the infrastructure layer and draw endpoints to a Canvas overlay.

## Recommendations

**Stage 1 — Layout & legibility (highest impact, do first).**
1. Replace force-directed with a **hand-rolled layered layout** keyed off device role: core/distribution row on top, access row beneath, endpoints hidden behind count badges. Add a **radial alternate** toggle for the single-core view.
2. **Aggregate port-channels into single logical edges** with a member-count badge.
3. Implement **redundant state encoding**: shape=role, fill-band=health, dashed=STP-blocked, thick+icon+red=SPOF, hatch+tag=failed/removed.
*Benchmark to proceed:* a network engineer can identify the core, every access switch, and any SPOF in <5 seconds without interacting.

**Stage 2 — Visual system & coherence.**
4. Introduce **semantic CSS-variable tokens** (12-step scale, light+dark), swap neon-on-black for tinted-grey dark with a light option.
5. Switch UI/data type to a **system sans with `tabular-nums`**; confine monospace to IPs/interfaces/CLI.
6. Restructure to **persistent graph + mode switcher + single right drawer**, with per-mode empty states and legends, and shared selection/camera across modes.

**Stage 3 — Fix the risk signal.**
7. **Deduplicate findings**, replace raw-count health with a **transparent weighted 0–100 score** (`base_severity × asset_criticality × impact`), shown with its component breakdown.
8. Add a **ranked "fix-this-first" list** and band-driven READY/CAUTION/NOT-READY per move-group.
*Benchmark to proceed:* health scores show a *spread* across bands; only genuine SPOF/redundancy gaps read Critical. If everything is still red, the weighting is still wrong.

**Stage 4 — Scale & polish.**
9. Add **search, VLAN/role filters, per-VLAN view, and DOI expand-on-demand** for endpoints/ports.
10. Add **vanilla pan/zoom (viewBox), drag-to-pin with localStorage, and keyboard shortcuts** with a `?` help overlay.

**What would change these recommendations:** If the network grows beyond a few thousand simultaneously-visible elements, move endpoint rendering to a Canvas overlay. If the tool ever becomes a client deliverable, add a print/export-to-SVG path and tighten to WCAG AA across all tokens.

## Caveats
- **Quantitative thresholds are device-dependent.** The "SVG ~2k / Canvas ~5k / WebGL ~10k+ elements" figures come from a yWorks benchmark on a 2015 MacBook, summarized by the third-party Cylynx blog; treat them as order-of-magnitude, not exact. They comfortably support the conclusion that SVG suffices for this tool.
- **No-library layout is a deliberate trade-off.** A hand-rolled layered layout won't match dagre/ELK on crossing-minimization for large dense graphs, but at ~13 infrastructure nodes the difference is invisible — and it preserves the hard zero-dependency / offline / single-file constraint.
- **Color values are starting points.** The specific hex values cited (e.g., `#22c55e`, `#3b82f6`, Astro's `#FF2A04`) are illustrative tokens from published palettes; validate the final palette with a colorblind simulator (Coblis, Chrome DevTools rendering emulation) and a ≥3:1 / 4.5:1 contrast check before shipping.
- **The risk-scoring weights require domain calibration.** The additive model is a framework; the actual `base_severity` and `asset_criticality` values for each finding type must be tuned by the engineer against real migration outcomes, and re-reviewed periodically (the alerting literature recommends monthly tuning) — otherwise a new miscalibration can reintroduce the cry-wolf problem.
- **Design-system references are conventions, not laws.** Carbon, Radix, PatternFly, and Astro agree on the big principles (tokens, redundant state encoding, temperature ramps) but differ in specifics; adopt one as the backbone (Radix is the lightest to replicate in plain CSS) rather than mixing.