import { SkelTable } from "assesshub-frontend";

/** Default table silhouette. */
export const Default = () => (
  <div className="panel" style={{ minHeight: 180 }}>
    <SkelTable />
  </div>
);

/** The Snapshot detail-section shape (6 rows × 4 columns). */
export const DetailSection = () => (
  <div className="panel" style={{ minHeight: 220 }}>
    <SkelTable rows={6} cols={4} />
  </div>
);
