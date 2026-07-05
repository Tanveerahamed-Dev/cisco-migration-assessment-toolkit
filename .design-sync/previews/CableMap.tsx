import { CableMap } from "assesshub-frontend";

/** The demo fleet's physical cabling — tier lanes, port stubs, op-status colours,
 *  a down studio leg in red and the uncollected camera switch dashed grey. */
export const MeridianCabling = () => (
  <div className="panel">
    <h3>Physical cabling · CDP/LLDP</h3>
    <CableMap snapId={1} />
  </div>
);
