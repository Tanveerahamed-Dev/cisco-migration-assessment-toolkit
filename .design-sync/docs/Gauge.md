---
category: ui-kit
---
A donut gauge with an animated centre number (CountUp inside). `value`/`max` set the sweep, `color` is REQUIRED and should be a token expression — `"var(--ok)"`, `"var(--crit)"`, or a vocabulary helper like `bandColor("Fair")`. `label` renders under the number inside the donut. Default `size` is 132px.

```tsx
<div className="row-flex" style={{ gap: 24 }}>
  <Gauge value={72} color="var(--watch)" label="avg health" />
  <Gauge value={94} color="var(--ok)" label="collected %" />
  <Gauge value={22} color="var(--crit)" label="worst device" size={110} />
</div>
```
