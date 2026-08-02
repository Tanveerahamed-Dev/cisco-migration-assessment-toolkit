import type { SnapshotVerification } from "../api";

export const VERIFICATION_CONTRACT_VERSION = 3;

const LEGACY_UNVERIFIED: SnapshotVerification = {
  contract_version: VERIFICATION_CONTRACT_VERSION,
  integrity_status: "unknown",
  status: "unverified",
  label: "Unverified coverage",
  verified: false,
  coverage_honest: true,
  reasons: [
    "This legacy snapshot has no current phase-integrity and source-authority attestation.",
  ],
  failed_phases: [],
  missing_authorities: ["oui", "ports", "eol"],
  non_authoritative_authorities: [],
  integrity_failed_authorities: [],
  integrity_unknown_authorities: ["oui", "ports", "eol"],
};

export function normalizedVerification(
  value?: SnapshotVerification | null,
): SnapshotVerification {
  const structurallyCurrent = (
    value
    && value.contract_version === VERIFICATION_CONTRACT_VERSION
    && ["verified", "partial", "unverified"].includes(value.status)
    && Array.isArray(value.reasons)
    && ["verified", "failed", "unknown"].includes(value.integrity_status)
    && value.coverage_honest === true
    && value.verified === (value.status === "verified")
    && Array.isArray(value.failed_phases)
    && Array.isArray(value.missing_authorities)
    && Array.isArray(value.non_authoritative_authorities)
    && Array.isArray(value.integrity_failed_authorities)
    && Array.isArray(value.integrity_unknown_authorities)
    && (
      value.status !== "verified"
      || (
        value.integrity_status === "verified"
        && value.reasons.length === 0
        && value.failed_phases.length === 0
        && value.missing_authorities.length === 0
        && value.non_authoritative_authorities.length === 0
        && value.integrity_failed_authorities.length === 0
        && value.integrity_unknown_authorities.length === 0
      )
    )
  );
  if (structurallyCurrent) {
    return value;
  }
  return {
    ...LEGACY_UNVERIFIED,
    reasons: [
      value
        ? "Verification metadata is stale or internally inconsistent; it cannot support a verified claim."
        : LEGACY_UNVERIFIED.reasons[0],
    ],
  };
}

export function VerificationBadge({
  value,
  compact = false,
}: {
  value?: SnapshotVerification | null;
  compact?: boolean;
}) {
  const verification = normalizedVerification(value);
  const text = compact
    ? verification.status === "verified"
      ? "Verified"
      : verification.status === "partial"
        ? "Partial"
        : "Unverified"
    : verification.label;
  return (
    <span
      className={`verification-badge verification-${verification.status}`}
      title={verification.reasons.join(" ") || "All required integrity and authority checks passed."}
    >
      <span aria-hidden="true">
        {verification.status === "verified" ? "✓" : verification.status === "partial" ? "!" : "?"}
      </span>
      {text}
    </span>
  );
}

export function VerificationWarning({
  value,
}: {
  value?: SnapshotVerification | null;
}) {
  const verification = normalizedVerification(value);
  if (verification.status === "verified") return null;
  const headline = verification.status === "partial"
    ? "Partial assessment coverage"
    : "Assessment coverage is unverified";
  return (
    <section
      className={`verification-warning verification-${verification.status}`}
      role="alert"
      aria-label={headline}
    >
      <div>
        <strong>{headline}</strong>
        <p>
          Empty or absent results must not be read as healthy. Use the available evidence, but do
          not treat this snapshot as a complete verified assessment.
        </p>
      </div>
      <ul>
        {(verification.reasons.length
          ? verification.reasons
          : LEGACY_UNVERIFIED.reasons
        ).map((reason) => <li key={reason}>{reason}</li>)}
      </ul>
    </section>
  );
}
