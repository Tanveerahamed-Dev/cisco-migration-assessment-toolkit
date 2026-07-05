import { Loading } from "assesshub-frontend";

/** Default pending state — centred spinner. */
export const Default = () => (
  <div className="panel" style={{ minHeight: 180 }}>
    <Loading />
  </div>
);

/** Contextual label, as the widgets use it. */
export const CustomLabel = () => (
  <div className="panel" style={{ minHeight: 180 }}>
    <Loading label="Building cable map…" />
  </div>
);
