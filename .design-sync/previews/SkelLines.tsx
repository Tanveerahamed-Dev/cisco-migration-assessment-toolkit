import { SkelLines } from "assesshub-frontend";

/** Default panel-body silhouette (heading + 4 lines). */
export const Default = () => (
  <div className="panel" style={{ minHeight: 180 }}>
    <SkelLines />
  </div>
);

/** Taller body with a contextual announcement, as the widgets use it. */
export const ContextLabel = () => (
  <div className="panel" style={{ minHeight: 220 }}>
    <SkelLines n={6} label="Building cutover plan…" />
  </div>
);
