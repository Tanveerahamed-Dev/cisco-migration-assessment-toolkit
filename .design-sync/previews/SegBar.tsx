import { SegBar, bandColor, gateColor } from "assesshub-frontend";

/** Fleet health-band distribution — the dashboard's signature strip. */
export const HealthBands = () => (
  <div className="panel">
    <h3>Fleet health</h3>
    <SegBar
      data={{ Excellent: 41, Good: 118, Fair: 62, Poor: 22, Critical: 10 }}
      colorFor={bandColor}
    />
  </div>
);

/** Cutover gate mix using the gate vocabulary. */
export const GateMix = () => (
  <div className="panel">
    <h3>Wave gates</h3>
    <SegBar
      data={{ "GO": 1, "CONDITIONAL GO": 1, "NO-GO": 1 }}
      colorFor={gateColor}
    />
  </div>
);

/** Migration strategy split — make-before-break vs hard-cutover. */
export const StrategySplit = () => (
  <div className="panel">
    <h3>Endpoint moves</h3>
    <SegBar
      data={{ "make-before-break": 1060, "hard-cutover": 420 }}
      colorFor={(k) => (k === "make-before-break" ? "var(--ok)" : "var(--risk)")}
    />
  </div>
);
