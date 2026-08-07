import { TopologyGraph } from "assesshub-frontend";

/** The demo fleet — switch-chassis rects in role-tiered lanes, band as LED + chassis tint,
 *  keystone badges; assessed SPOF links red, unassessed redundancy dashed; click simulates
 *  failure against the deterministic baseline. This fixture exercises the anchor guard and
 *  honest zero-impact results; it does not fabricate a positive stranded-device state.
 *  (The preview harness wraps everything in DemoDataProvider, so snapId renders sample data.) */
export const MeridianFleet = () => <TopologyGraph snapId={1} />;

/** As the app frames it — inside a panel with the section heading. */
export const InPanel = () => (
  <div className="panel">
    <h3>Topology · blast radius</h3>
    <TopologyGraph snapId={1} />
  </div>
);
