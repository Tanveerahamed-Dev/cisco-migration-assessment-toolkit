---
category: ui-kit
---
An animated number that eases to `value` (700ms ease-out cubic by default) and tweens from the previously shown value on updates. Respects the OS reduced-motion setting (jumps straight to the value). Renders inline — drop it wherever a number goes, typically inside `Kpi` values or stat rows. `decimals`, `prefix`, `suffix` format the output; non-finite values render as "—".

```tsx
<span style={{ font: "800 26px var(--sans)" }}>
  <CountUp value={5127} /> endpoints · <CountUp value={98.4} decimals={1} suffix="%" /> located
</span>
```
