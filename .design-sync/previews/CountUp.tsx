import { CountUp } from "assesshub-frontend";

/** Big stat glyphs — CountUp eases to the value (respects reduced motion). */
export const StatStrip = () => (
  <div className="panel">
    <div className="row-flex" style={{ gap: 32 }}>
      <div>
        <div style={{ font: "800 30px var(--sans)", letterSpacing: "-.02em" }}><CountUp value={5127} /></div>
        <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".6px" }}>endpoints</div>
      </div>
      <div>
        <div style={{ font: "800 30px var(--sans)", color: "var(--ok)" }}><CountUp value={98.4} decimals={1} suffix="%" /></div>
        <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".6px" }}>located</div>
      </div>
      <div>
        <div style={{ font: "800 30px var(--sans)", color: "var(--crit)" }}><CountUp value={12} /></div>
        <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".6px" }}>critical</div>
      </div>
    </div>
  </div>
);

/** Formatting: decimals, prefix, suffix. */
export const Formats = () => (
  <div className="panel">
    <div className="dim" style={{ fontSize: 14, display: "flex", flexDirection: "column", gap: 6 }}>
      <span>Health score: <b style={{ color: "var(--text)" }}><CountUp value={72.4} decimals={1} suffix=" /100" /></b></span>
      <span>Est. saving: <b style={{ color: "var(--ok)" }}><CountUp value={41250} prefix="$" /></b></span>
      <span>Window used: <b style={{ color: "var(--watch)" }}><CountUp value={87} suffix="%" /></b></span>
    </div>
  </div>
);
