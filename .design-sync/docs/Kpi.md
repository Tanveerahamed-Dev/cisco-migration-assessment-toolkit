---
category: ui-kit
---
A single KPI stat tile: small uppercase label, large value, optional hint line. `tone` tints the tile with the posture palette (`ok` green, `watch` amber, `risk` orange, `crit` red); omit it for a neutral tile. Compose several in a `.grid.cols-4` (or `cols-3`) container for a dashboard header row. The value is a ReactNode — pair with `<CountUp>` for animated numbers.

```tsx
<div className="grid cols-4">
  <Kpi label="switches" value={<CountUp value={303} />} hint="303 inventoried · 253 collected" />
  <Kpi label="avg health" value={72.4} tone="watch" />
  <Kpi label="critical findings" value={12} tone="crit" hint="fix before wave 1" />
  <Kpi label="readiness" value="CAUTION" tone="watch" />
</div>
```
