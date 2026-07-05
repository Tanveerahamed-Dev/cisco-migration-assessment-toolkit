---
category: ui-kit
---
A horizontal bar list — name, track, count per row, scaled to the max value. The workhorse for "top N by category" panels (findings by category, endpoints by VLAN, models by count). `colorFor` is optional; bars default to the accent token. Renders "None." when every value is zero.

```tsx
<Bars
  data={{ "No FHRP": 18, "Past EoS": 7, "Single-homed": 5, "AAA gap": 4 }}
  colorFor={(k) => (k === "No FHRP" ? "var(--crit)" : "var(--risk)")}
/>
```
