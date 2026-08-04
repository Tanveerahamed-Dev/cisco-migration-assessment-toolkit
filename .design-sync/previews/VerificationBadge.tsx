import { VerificationBadge } from "assesshub-frontend";

/* Fixtures shaped to the SnapshotVerification contract (contract_version 3). These satisfy
 * normalizedVerification EXACTLY — a "verified" value only survives the guard when its integrity
 * is verified AND every reason/phase/authority list is empty, so a sloppy fixture would silently
 * render as "Unverified coverage" and make this card lie about what it is showing. */
const VERIFIED = {
  contract_version: 3,
  origin: "cisco-assess 3.32.1",
  integrity_status: "verified",
  status: "verified",
  label: "Verified coverage",
  verified: true,
  coverage_honest: true,
  reasons: [],
  failed_phases: [],
  missing_authorities: [],
  non_authoritative_authorities: [],
  integrity_failed_authorities: [],
  integrity_unknown_authorities: [],
};

const PARTIAL = {
  contract_version: 3,
  origin: "cisco-assess 3.32.1",
  integrity_status: "verified",
  status: "partial",
  label: "Partial coverage — 2 authorities unattested",
  verified: false,
  coverage_honest: true,
  reasons: [
    "EoL registry carries transcription provenance only for this run.",
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
  ],
  failed_phases: ["enrich"],
  missing_authorities: ["oui", "ports", "eol"],
  non_authoritative_authorities: [],
  integrity_failed_authorities: [],
  integrity_unknown_authorities: ["oui", "ports", "eol"],
};

/* Claims "verified" while carrying a failed phase — the guard rejects the whole object. */
const INCONSISTENT = { ...VERIFIED, failed_phases: ["enrich"] };

/** The three states, full labels — how the badge reads in a page header. */
export const AllStates = () => (
  <div className="panel">
    <h3>Verification states</h3>
    <div className="row-flex" style={{ gap: 10, flexWrap: "wrap" }}>
      <VerificationBadge value={VERIFIED} />
      <VerificationBadge value={PARTIAL} />
      <VerificationBadge value={UNVERIFIED} />
    </div>
  </div>
);

/** `compact` — one word instead of the full label, for table cells and dense rows. */
export const Compact = () => (
  <div className="panel">
    <h3>Compact</h3>
    <div className="row-flex" style={{ gap: 10, flexWrap: "wrap" }}>
      <VerificationBadge value={VERIFIED} compact />
      <VerificationBadge value={PARTIAL} compact />
      <VerificationBadge value={UNVERIFIED} compact />
    </div>
  </div>
);

/** The guard: absent metadata and self-contradicting metadata both normalise DOWN to
 *  unverified. The badge never over-claims, so it is safe against any snapshot. */
export const NeverOverClaims = () => (
  <div className="panel">
    <h3>Coverage-honesty guard</h3>
    <table className="tbl">
      <thead>
        <tr><th>Snapshot metadata</th><th>Renders as</th></tr>
      </thead>
      <tbody>
        <tr>
          <td className="dim">absent (legacy snapshot)</td>
          <td><VerificationBadge value={undefined} /></td>
        </tr>
        <tr>
          <td className="dim">claims verified, carries a failed phase</td>
          <td><VerificationBadge value={INCONSISTENT} /></td>
        </tr>
      </tbody>
    </table>
  </div>
);

/** Realistic composition — the badge where it actually lives, beside a snapshot title. */
export const InSnapshotHeader = () => (
  <div className="panel">
    <div className="spread">
      <div>
        <h3>Meridian campus · snapshot 14</h3>
        <span className="dim" style={{ fontSize: 12 }}>253 of 303 switches collected</span>
      </div>
      <VerificationBadge value={PARTIAL} />
    </div>
    <table className="tbl" style={{ marginTop: 12 }}>
      <thead>
        <tr><th>Snapshot</th><th>Collected</th><th>Coverage</th></tr>
      </thead>
      <tbody>
        <tr>
          <td className="mono">2026-06-13 06:32</td>
          <td className="num">253</td>
          <td><VerificationBadge value={PARTIAL} compact /></td>
        </tr>
        <tr>
          <td className="mono">2026-05-28 21:04</td>
          <td className="num">303</td>
          <td><VerificationBadge value={VERIFIED} compact /></td>
        </tr>
        <tr>
          <td className="mono">2026-04-02 11:19</td>
          <td className="num">198</td>
          <td><VerificationBadge value={undefined} compact /></td>
        </tr>
      </tbody>
    </table>
  </div>
);
