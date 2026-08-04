---
category: ui-kit
---
The full-width banner that spells out **why** a snapshot's coverage is not verified — the headline, the standing "absence is not health" caution, and the specific `reasons` the engine gave.

It **renders `null` when the status is `verified`**, so mount it unconditionally at the top of a snapshot or campaign page: it appears only when it has something to say, and never needs a guard at the call site. Absent or stale metadata normalises down to `unverified`, so a legacy snapshot gets the banner rather than silence.

Two tones, driven entirely by the value: `partial` uses the `--watch` gradient and left rule, `unverified` escalates to `--crit`. It carries `role="alert"` and an `aria-label` of its own headline.

```tsx
{/* top of the snapshot page — shows for partial and unverified, vanishes when verified */}
<VerificationWarning value={snapshot.verification} />
```

It is a page-level banner, not a panel: give it the full content width above the first `.grid`, and pair it with a `VerificationBadge` in the page header.
