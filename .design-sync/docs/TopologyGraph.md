---
category: snapshot-widgets
---
The L2/L3 topology fabric in the product's device-fidelity language (shared with CableMap and the 3D mode): switch-chassis rects laid out in deterministic role-tiered lanes (core → distribution → access → edge, unclassified last), wrapped into rows at fleet scale. Health band is the chassis status LED + a subtle chassis tint (the legend derives from bands actually present, including "Insufficient Data" for uncollected devices, which also get a dashed border), and keystones carry an accent corner badge. A link is shown as a critical single point of failure only when its explicit `bridge_assessed: true` authority bit accompanies the verdict; unassessed edges are dashed and disclosed as "redundancy not assessed," never rendered as healthy. The fleet-level `link_centrality_assessed` bit controls the incomplete-assessment notice; it does not authenticate an individual edge verdict. Clicking a chassis runs the deterministic-baseline failure counterfactual and highlights stranded devices and paths in both 2D and 3D. The detail panel shows the selected device plus failure-impact status and count; selecting the reference anchor, or a node outside that anchor's baseline component, renders an explicit unassessable state rather than zero impact. In the built-in Meridian fixture the best-connected anchor is MBG-DS-02; selecting it exercises the anchor guard, while the other current selections legitimately resolve to zero stranded devices rather than demonstrating a positive stranded set. A "Linked only" toggle hides link-less switches with the hidden count always disclosed. Scroll zooms and drag pans; the 3D toggle renders the same fabric as rack-mount meshes.

Data contract: takes `snapId` and fetches the snapshot graph — it does NOT take data props. **Always compose it inside `DemoDataProvider`**, which serves a built-in sample fleet (any `snapId` works) and is how every design should mount it.

```tsx
<DemoDataProvider>
  <div className="panel">
    <h3>Topology · blast radius</h3>
    <TopologyGraph snapId={1} />
  </div>
</DemoDataProvider>
```
