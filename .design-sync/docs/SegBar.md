---
category: ui-kit
---
A one-line segmented distribution bar with a legend underneath — the fleet-composition glance (health bands, gate mix, strategy split). `data` is `Record<label, count>` (zero entries are dropped); `colorFor(key)` maps each label to a colour — use the vocabulary helpers (`bandColor`, `gateColor`, `sevColor`) or token strings so it matches the rest of the product.

```tsx
<SegBar
  data={{ Excellent: 41, Good: 118, Fair: 62, Poor: 22, Critical: 10 }}
  colorFor={(k) => `var(--band-${k}, var(--text-faint))`}
/>
```
