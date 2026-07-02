---
category: snapshot-widgets
---
The CCDE-grounded target-state design blueprint: a trade-off scorecard (0–4 per axis), a requirements form that right-sizes the blueprint server-side, evidence-grounded decision cards (priority, driver, target pattern, alternatives, trade-offs, principle citation), the target-state section (architecture dimensions, replacement BoM, IP plan, migration waves, segmentation), open design questions, and the architecture-coverage map. A second tab carries the design-driven NRFU/ATP checklist phased across pre/post-cutover.

Takes `snapId` and fetches the blueprint (+ NRFU + coverage) — **always wrap in `DemoDataProvider`**. It is the largest widget; give it a full-width column. Brings its own `.panel` chrome.

```tsx
<DemoDataProvider>
  <DesignBlueprintPanel snapId={1} />
</DemoDataProvider>
```
