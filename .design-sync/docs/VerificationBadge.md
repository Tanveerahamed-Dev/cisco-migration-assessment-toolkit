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

## Building a value in a design (when there is no live snapshot)

`normalizedVerification` is a strict **validator**, not a formatter: anything absent, legacy or
self-inconsistent is normalised **down** to `unverified`. A shorthand mock like `{ status: "verified" }`
therefore renders as **"Unverified coverage"** — not as a bug, but because a partial object cannot
support a verified claim. To show the verified or partial states, pass the whole contract-v3 object:

```tsx
const VERIFIED = {
  contract_version: 3, integrity_status: "verified", status: "verified",
  label: "Verified coverage", verified: true, coverage_honest: true,
  reasons: [], failed_phases: [], missing_authorities: [],
  non_authoritative_authorities: [], integrity_failed_authorities: [],
  integrity_unknown_authorities: [],
};

const PARTIAL = {
  ...VERIFIED, status: "partial", verified: false,
  label: "Partial coverage — 2 authorities unattested",
  reasons: ["EoL registry carries transcription provenance only.",
            "Port-capability authority was not consulted for 50 of 303 devices."],
  non_authoritative_authorities: ["eol"], integrity_unknown_authorities: ["ports"],
};
```

Two rules the validator enforces: `verified` must equal `status === "verified"`, and when `status`
is `"verified"` **every** array (`reasons`, `failed_phases`, and all four authority lists) must be
empty and `integrity_status` must be `"verified"`. Break either and the value silently renders as
unverified. For the unverified state you can simply pass `undefined`.

Pair it with `VerificationWarning` on any page that shows assessment results: the badge is the label, the warning is the explanation.
