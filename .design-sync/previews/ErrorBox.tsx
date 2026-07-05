import { ErrorBox } from "assesshub-frontend";

/** The error branch of a data-bound panel. */
export const ApiError = () => (
  <ErrorBox msg="503 Service Unavailable — the engine is still parsing this snapshot" />
);

/** In context — where Loading would have been. */
export const InDashboardSlot = () => (
  <div className="panel">
    <h3>Topology · blast radius</h3>
    <ErrorBox msg="snapshot 7 not found" />
  </div>
);
