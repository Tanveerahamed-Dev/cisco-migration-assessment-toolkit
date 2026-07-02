---
category: snapshot-widgets
---
Every finding as a trigger → mechanism → impact → mitigation story. Simple causes render as a four-stage chain with connector width proportional to blast magnitude; multi-cause compounds render as a **bowtie** (causes converge on a top event; ⊘ marks "no preventive control today", ✓ FIX marks the mitigation). Family and severity filter chips at the top; a card list below drives the selected diagram; evidence chips carry the coverage-honest grounding (precision, citations, hosts).

Takes `snapId` and fetches the causal-flow model — **always wrap in `DemoDataProvider`**. Renders a full panel (it brings its own `.panel` chrome and heading).

```tsx
<DemoDataProvider>
  <CausalFlowPanel snapId={1} />
</DemoDataProvider>
```
