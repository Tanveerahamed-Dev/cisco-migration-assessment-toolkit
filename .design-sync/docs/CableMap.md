---
category: snapshot-widgets
---
The Nokia-EDA-style physical cable map: devices as rects in role-tiered lanes (core → distribution → access), cables anchored to per-port stubs and coloured by operational status — green up, red down, grey **dashed** for `[NOT OBSERVED]` (uncollected is never painted healthy). Port-channels draw thick with member counts. Click a node for its port table, a cable for its endpoints; a toolbar flips vertical/horizontal and resets the view.

Takes `snapId` and fetches the cable-map model — **always wrap in `DemoDataProvider`** (built-in sample fleet; any `snapId`).

```tsx
<DemoDataProvider>
  <div className="panel">
    <h3>Physical cabling · CDP/LLDP</h3>
    <CableMap snapId={1} />
  </div>
</DemoDataProvider>
```
