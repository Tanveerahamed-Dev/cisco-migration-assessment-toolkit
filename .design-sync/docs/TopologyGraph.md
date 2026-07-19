---
category: snapshot-widgets
---
The L2/L3 topology fabric in the product's device-fidelity language (shared with CableMap and the 3D mode): switch-chassis rects laid out in deterministic role-tiered lanes (core → distribution → access → edge, unclassified last), wrapped into rows at fleet scale. Health band is the chassis status LED + a subtle chassis tint (legend derives from bands actually present, including "Insufficient Data" for uncollected devices, which also get a dashed border); keystones carry an accent corner badge; single-point-of-failure links are drawn in the critical token and thicken with blast weight; link stubs sit on the chassis edges like ports. Hover/click focuses a switch's neighborhood; a detail card shows band, score, role and degree; a "Linked only" toggle hides link-less switches with the hidden count always disclosed. Scroll zooms, drag pans; a 3D toggle renders the same fabric as rack-mount meshes.

Data contract: takes `snapId` and fetches the snapshot graph — it does NOT take data props. **Always compose it inside `DemoDataProvider`**, which serves a built-in sample fleet (any `snapId` works) and is how every design should mount it.

```tsx
<DemoDataProvider>
  <div className="panel">
    <h3>Topology · blast radius</h3>
    <TopologyGraph snapId={1} />
  </div>
</DemoDataProvider>
```
