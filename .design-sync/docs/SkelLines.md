---
category: ui-kit
---
Structure-shaped loading placeholder for prose/panel bodies: one heading-width bar plus `n` varying-width body lines (default 4), announcing "Loading…" (or a custom `label`) exactly once for assistive tech. Use as the pending branch of any KNOWN-shape panel so loading reads as the content's silhouette instead of a spinner; keep `Loading` for full-page or unknown-shape contexts.

```tsx
{loading
  ? <div className="panel"><h3>Ask the engineer</h3><SkelLines n={5} /></div>
  : <ArchReviewPanel snapId={snapId} />}
```
