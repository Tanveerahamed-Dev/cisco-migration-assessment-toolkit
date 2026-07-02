import { SevChip } from "assesshub-frontend";

/** The five canonical engine severities. */
export const AllSeverities = () => (
  <div className="row-flex">
    <SevChip sev="Critical" />
    <SevChip sev="High" />
    <SevChip sev="Medium" />
    <SevChip sev="Low" />
    <SevChip sev="Info" />
  </div>
);

/** Label overrides keep the severity colour but replace the text. */
export const CustomLabels = () => (
  <div className="row-flex">
    <SevChip sev="Critical" label="3 critical findings" />
    <SevChip sev="High" label="fix before wave 1" />
    <SevChip sev="Info" label="not observed" />
  </div>
);

/** Realistic composition — a findings table inside its panel surface (tables always
 *  live on a .panel in AssessHub; bare text on the card canvas has no contrast). */
export const InFindingsTable = () => (
  <div className="panel">
    <h3>Findings</h3>
    <table className="tbl">
    <thead>
      <tr><th>Device</th><th>Severity</th><th>Finding</th></tr>
    </thead>
    <tbody>
      <tr>
        <td className="mono">MBG-CORE-01</td>
        <td><SevChip sev="Critical" /></td>
        <td>No first-hop redundancy on 18 user VLANs</td>
      </tr>
      <tr>
        <td className="mono">STU-AS-02</td>
        <td><SevChip sev="High" /></td>
        <td>Uplink Gi1/0/50 down — dual-homing degraded</td>
      </tr>
      <tr>
        <td className="mono">NOC-AS-01</td>
        <td><SevChip sev="Medium" /></td>
        <td>Config archive 90+ days stale</td>
      </tr>
    </tbody>
    </table>
  </div>
);
