---
category: ui-kit
---
The base loading-placeholder bar: a token-surfaced block that shimmers while content loads (static under reduced motion). Carries a visually-hidden "Loading…" announcement for assistive tech — pass `label` to customise it, or `announce={false}` when a composed parent already announces once. Prefer the shaped presets (`SkelLines`, `SkelTable`) over raw bars; reach for `Skeleton` directly only for one-off shapes.

```tsx
<div className="panel">
  <Skeleton className="skel-h" />
  <Skeleton label="Building topology…" />
</div>
```
