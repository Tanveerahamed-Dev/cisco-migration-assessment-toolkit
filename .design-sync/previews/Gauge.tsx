import { Gauge, bandColor } from "assesshub-frontend";

/** The dashboard trio — posture-coloured donuts with centre labels. */
export const HealthTrio = () => (
  <div className="panel">
    <div className="row-flex" style={{ gap: 26, justifyContent: "center" }}>
      <Gauge value={72} color="var(--watch)" label="avg health" />
      <Gauge value={94} color="var(--ok)" label="collected %" />
      <Gauge value={22} color="var(--crit)" label="worst device" />
    </div>
  </div>
);

/** Colour via the engine band vocabulary helper. */
export const BandColours = () => (
  <div className="panel">
    <div className="row-flex" style={{ gap: 22, justifyContent: "center" }}>
      <Gauge value={92} color={bandColor("Excellent")} label="Excellent" size={110} />
      <Gauge value={61} color={bandColor("Fair")} label="Fair" size={110} />
      <Gauge value={31} color={bandColor("Poor")} label="Poor" size={110} />
    </div>
  </div>
);
