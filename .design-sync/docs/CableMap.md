---
category: snapshot-widgets
---
The Nokia-EDA-style physical cable map: devices as rects in role-tiered lanes (core → distribution → access → edge), cables anchored to per-port stubs and coloured by operational status — green up, red down, grey **dashed** for `[NOT OBSERVED]` (uncollected is never painted healthy). Port-channels draw thick with member counts; the cable detail panel also shows link **speed** (verbatim from `show interface status`, e.g. "1000", "10G" — blank when not observed). Click a node for its port table (now also showing device **kind** — switch/router/firewall/ap/phone/endpoint/unknown), a cable for its endpoints; a toolbar flips vertical/horizontal and resets the view.

**Fleet-scale declutter**, for large topologies: a **"Fabric only"** toggle hides positively-identified edge endpoints (APs, IP phones) while switches/routers/unknowns always stay visible; a **tier row** (ALL + one button per tier, e.g. "T0 · CORE") isolates a single lane plus its direct peers, with empty lanes compacting. A status line reports the filtered vs. total node/cable counts whenever either filter is active.

Takes `snapId` and fetches the cable-map model — **always wrap in `DemoDataProvider`** (built-in sample fleet; any `snapId`).

```tsx
<DemoDataProvider>
  <div className="panel">
    <h3>Physical cabling · CDP/LLDP</h3>
    <CableMap snapId={1} />
  </div>
</DemoDataProvider>
```
