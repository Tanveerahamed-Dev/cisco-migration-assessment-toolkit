import { Bars, sevColor } from "assesshub-frontend";

/** Findings by category — severity-coloured. */
export const FindingsByCategory = () => (
  <div className="panel">
    <h3>Findings by category</h3>
    <Bars
      data={{ "No FHRP": 18, "Past EoS": 7, "Single-homed": 5, "AAA gap": 4, "Stale archive": 2 }}
      colorFor={(k) => (k === "No FHRP" ? sevColor("Critical") : k === "Past EoS" ? sevColor("High") : sevColor("Medium"))}
    />
  </div>
);

/** Default accent fill — endpoints per VLAN. */
export const EndpointsByVlan = () => (
  <div className="panel">
    <h3>Endpoints by VLAN</h3>
    <Bars data={{ "VLAN 110 · Studio-Video": 430, "VLAN 120 · Studio-Audio": 380, "VLAN 140 · Camera-Feeds": 260, "VLAN 30 · NOC-Mgmt": 120 }} />
  </div>
);
