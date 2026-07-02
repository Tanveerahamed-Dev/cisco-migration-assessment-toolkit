---
category: providers
---
The wrapper that makes the six snapshot widgets (`TopologyGraph`, `CableMap`, `CausalFlowPanel`, `CutoverPlanner`, `DesignBlueprintPanel`, `ArchReviewPanel`) renderable outside the real AssessHub backend. It intercepts their `/api/...` fetches and serves a built-in, entirely fictional sample fleet (the "Meridian" campus — consistent across all widgets, so the topology, cable map, review and cutover plan all tell the same story), and provides the Router context `CutoverPlanner` needs. Non-`/api` fetches pass through untouched.

Use exactly one, at the top of any design that mounts snapshot widgets; any `snapId` value works. The UI-kit pieces (`Kpi`, `Gauge`, …) don't need it but are unaffected by it.

```tsx
<DemoDataProvider>
  <div className="grid cols-2">
    <div className="panel"><h3>Topology</h3><TopologyGraph snapId={1} /></div>
    <div className="panel"><h3>Cabling</h3><CableMap snapId={1} /></div>
  </div>
</DemoDataProvider>
```
