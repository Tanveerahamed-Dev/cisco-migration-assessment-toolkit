import { Skeleton } from "assesshub-frontend";

/** The base bar, heading-sized and body-sized, on a panel surface. */
export const Bars = () => (
  <div className="panel" style={{ minHeight: 120, display: "grid", gap: 10, alignContent: "start" }}>
    <Skeleton className="skel-h" />
    <Skeleton />
    <Skeleton announce={false} />
  </div>
);
