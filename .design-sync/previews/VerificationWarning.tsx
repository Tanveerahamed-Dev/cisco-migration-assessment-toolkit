import { VerificationBadge, VerificationWarning } from "assesshub-frontend";

/* SnapshotVerification fixtures (contract_version 3) — see VerificationBadge.tsx for why these
 * must satisfy normalizedVerification exactly. Note there is deliberately NO "verified" story
 * here: VerificationWarning renders null for a verified snapshot, so such a cell would be an
 * empty box — correct behaviour, but a useless card. The docs carry that rule instead. */
const PARTIAL = {
  contract_version: 3,
  origin: "cisco-assess 3.32.1",
  integrity_status: "verified",
  status: "partial",
  label: "Partial coverage — 2 authorities unattested",
  verified: false,
  coverage_honest: true,
  reasons: [
    "EoL registry carries transcription provenance only — hardware-lifecycle rollups are indicative, not attested.",
    "Port-capability authority was not consulted for 50 of 303 devices.",
  ],
  failed_phases: [],
  missing_authorities: [],
  non_authoritative_authorities: ["eol"],
  integrity_failed_authorities: [],
  integrity_unknown_authorities: ["ports"],
};

const UNVERIFIED = {
  contract_version: 3,
  integrity_status: "unknown",
  status: "unverified",
  label: "Unverified coverage",
  verified: false,
  coverage_honest: true,
  reasons: [
    "This collection ran without a source-authority manifest, so phase integrity cannot be attested.",
    "OUI, port-capability and EoL authorities are all unattested for this snapshot.",
    "50 of 303 devices were never reached; their absence from every finding table is a collection gap, not a clean result.",
  ],
  failed_phases: ["enrich"],
  missing_authorities: ["oui", "ports", "eol"],
  non_authoritative_authorities: [],
  integrity_failed_authorities: [],
  integrity_unknown_authorities: ["oui", "ports", "eol"],
};

/* The page background, so the banner is read in the surface context it ships in. */
const page = { background: "var(--bg)", padding: 16, borderRadius: "var(--radius)" };

/** Unverified — the `--crit` escalation, with every reason the engine gave. */
export const Unverified = () => (
  <div style={page}>
    <VerificationWarning value={UNVERIFIED} />
  </div>
);

/** Partial — the `--watch` tone, for a run that attested most but not all of its authorities. */
export const PartialCoverage = () => (
  <div style={page}>
    <VerificationWarning value={PARTIAL} />
  </div>
);

/** Absent metadata still warns: a legacy snapshot gets the banner rather than silence. */
export const LegacySnapshot = () => (
  <div style={page}>
    <VerificationWarning value={undefined} />
  </div>
);

/** Realistic page composition — badge in the header, banner above the first grid,
 *  mounted unconditionally because it hides itself when a snapshot is verified. */
export const InSnapshotPage = () => (
  <div style={page}>
    <div className="page-head" style={{ marginBottom: 12 }}>
      <div className="spread">
        <h1 style={{ margin: 0 }}>Meridian campus · snapshot 14</h1>
        <VerificationBadge value={UNVERIFIED} />
      </div>
    </div>
    <VerificationWarning value={UNVERIFIED} />
    <div className="panel">
      <h3>Fleet health</h3>
      <span className="dim" style={{ fontSize: 12 }}>
        253 of 303 switches collected · read every count below against the banner above.
      </span>
    </div>
  </div>
);
