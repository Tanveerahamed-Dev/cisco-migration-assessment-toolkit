---
category: ui-kit
---
The severity chip — dot + label, coloured from the engine's severity vocabulary via the `--sev-<Sev>` / `--sev-<Sev>-soft` token pairs. Pass the canonical severities `Critical | High | Medium | Low | Info` (spaces are stripped when resolving the token). `label` overrides the visible text while keeping the severity colour.

```tsx
<div className="row-flex">
  <SevChip sev="Critical" />
  <SevChip sev="High" />
  <SevChip sev="Medium" />
  <SevChip sev="Low" />
  <SevChip sev="Info" label="not observed" />
</div>
```
