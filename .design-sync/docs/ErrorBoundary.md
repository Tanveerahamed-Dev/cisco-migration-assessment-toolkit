---
category: ui-kit
---
A React class error boundary that renders a critical-toned panel (with the error message) instead of white-screening when a child throws. Wrap each independent dashboard region so one broken panel never takes down the page.

```tsx
<ErrorBoundary>
  <TopologyGraph snapId={1} />
</ErrorBoundary>
```
