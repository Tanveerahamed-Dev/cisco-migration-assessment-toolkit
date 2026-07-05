import { TopologyGraph } from "assesshub-frontend";

/** The demo fleet — nodes coloured by health band, keystones ringed, SPOF links red.
 *  (The preview harness wraps everything in DemoDataProvider, so snapId renders sample data.) */
export const MeridianFleet = () => <TopologyGraph snapId={1} />;

/** As the app frames it — inside a panel with the section heading. */
export const InPanel = () => (
  <div className="panel">
    <h3>Topology · blast radius</h3>
    <TopologyGraph snapId={1} />
  </div>
);
