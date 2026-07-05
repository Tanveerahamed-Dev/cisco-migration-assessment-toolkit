---
category: snapshot-widgets
---
"Ask the engineer" — the senior-engineer architecture review, interactive. A letter-grade header (A–F coloured by posture) with the conformance statement, then deterministic question chips ("Where do we start?", "What blocks the migration?", "How resilient is the fabric?", "Judge every design domain", "What couldn't you assess?") that each route into a slice of the review object: ranked actions, hard blockers, per-domain verdict tables, and the coverage-honest not-assessable list.

Takes `snapId` and fetches the review — **always wrap in `DemoDataProvider`**. Brings its own `.panel` chrome.

```tsx
<DemoDataProvider>
  <ArchReviewPanel snapId={1} />
</DemoDataProvider>
```
