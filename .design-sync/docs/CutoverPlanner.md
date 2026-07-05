---
category: snapshot-widgets
---
The migration cutover plan as a gated, pilot-first run-of-show: a verdict badge + stat strip (waves, devices, make-before-break vs hard-cutover, window), then one card per wave with its gate (GO / CONDITIONAL GO / NO-GO via the `--gate-*` tokens), readiness, endpoint counts, worst-case blast radius, gating blockers, and an expandable run-of-show with remediation and validation tables. Ends with the war-room execution-run strip.

Takes `snapId` and fetches the plan — **always wrap in `DemoDataProvider`** (it also supplies the Router context this component's links need; without it the component throws). Brings its own `.panel` chrome.

```tsx
<DemoDataProvider>
  <CutoverPlanner snapId={1} />
</DemoDataProvider>
```
