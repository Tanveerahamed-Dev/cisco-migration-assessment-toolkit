import { DemoDataProvider, Kpi, TopologyGraph } from "assesshub-frontend";

/** The canonical composition: wrap once at the top, then any snapshot widget renders
 *  with the built-in sample fleet. (Nesting-safe — an outer provider wins.) */
export const WrappedDashboardRegion = () => (
  <DemoDataProvider>
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="grid cols-3">
        <Kpi label="switches" value={9} hint="8 collected · 1 not" />
        <Kpi label="critical findings" value={2} tone="crit" />
        <Kpi label="readiness" value="CAUTION" tone="watch" />
      </div>
      <div className="panel">
        <h3>Topology · blast radius</h3>
        <TopologyGraph snapId={1} />
      </div>
      <div className="cmd">{`<DemoDataProvider>\n  <TopologyGraph snapId={1} />\n</DemoDataProvider>`}</div>
    </div>
  </DemoDataProvider>
);
