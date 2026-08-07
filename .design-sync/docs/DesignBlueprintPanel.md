---
category: snapshot-widgets
---
The CCDE-grounded target-state design blueprint: a trade-off scorecard (0–4 per axis), a requirements form that right-sizes the blueprint server-side, evidence-grounded decision cards (priority, driver, target pattern, alternatives, trade-offs, principle citation), the target-state section (architecture dimensions, lifecycle-disposition BoM, IP plan, migration waves, segmentation), open design questions, and the architecture-coverage map with its evidence-selected domain-lens chips (a red chip = the pack's observed classes carry findings, green = observed and clean; a lens loads only where its architecture is observed). The BoM keeps three coverage-honest dispositions separate: Past-LDoS assets are replace-now, Near-LDoS and Past-EoS assets enter owned refresh planning before recorded LDoS, and Unknown or missing lifecycle rows say "Resolve before procurement" rather than inheriting a healthy or costed default. Lifecycle date bands never establish serial-numbered support entitlement; verify that separately. A second tab carries the design-driven NRFU/ATP checklist phased across pre/post-cutover.

Takes `snapId` and fetches the blueprint (+ NRFU + coverage) — **always wrap in `DemoDataProvider`**. It is the largest widget; give it a full-width column. Brings its own `.panel` chrome.

```tsx
<DemoDataProvider>
  <DesignBlueprintPanel snapId={1} />
</DemoDataProvider>
```
