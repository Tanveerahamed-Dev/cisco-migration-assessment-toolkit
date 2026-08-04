---
category: ui-kit
---
The snapshot-verification pill — states whether an assessment's coverage is **verified**, **partial** or **unverified**, coloured from the posture tokens (`--ok` / `--watch` / `--crit`). It is the compact half of AssessHub's coverage-honesty rule: an empty or absent result must never be rendered as a healthy one.

Pass the snapshot's `verification` object straight through. Anything absent, legacy, or internally inconsistent is normalised **down** to `Unverified` by `normalizedVerification`, so the badge can never over-claim and is safe to render against any snapshot — including old ones that predate the attestation contract. The `reasons` array is surfaced as the pill's `title` tooltip.

`compact` swaps the full `label` for a one-word status (`Verified` / `Partial` / `Unverified`) — use it in table cells and dense list rows; use the default full label in page headers where there is room to be explicit.

```tsx
<VerificationBadge value={snapshot.verification} />
<VerificationBadge value={snapshot.verification} compact />
<VerificationBadge value={undefined} />   {/* → "Unverified coverage", never a blank */}
```

Pair it with `VerificationWarning` on any page that shows assessment results: the badge is the label, the warning is the explanation.
