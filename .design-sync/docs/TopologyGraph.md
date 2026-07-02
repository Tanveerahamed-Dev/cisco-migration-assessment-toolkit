---
category: snapshot-widgets
---
The L2/L3 topology graph: a deterministic force-directed layout of the fleet, nodes coloured by health band (legend derives from bands actually present, including "Insufficient Data" for uncollected devices), keystones ringed with a dashed accent halo, single-point-of-failure links drawn in the critical token. Hover/click focuses a node's neighborhood; a detail card shows band, score, role and degree. Scroll zooms, drag pans.

Data contract: takes `snapId` and fetches the snapshot graph — it does NOT take data props. **Always compose it inside `DemoDataProvider`**, which serves a built-in sample fleet (any `snapId` works) and is how every design should mount it.

```tsx
<DemoDataProvider>
  <div className="panel">
    <h3>Topology · blast radius</h3>
    <TopologyGraph snapId={1} />
  </div>
</DemoDataProvider>
```
