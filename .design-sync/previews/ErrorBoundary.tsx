import { ErrorBoundary, Kpi } from "assesshub-frontend";

function Bomb(): never {
  throw new Error("render exploded: cannot read snapshot section 'topology'");
}

/** A child that throws is caught and rendered as the critical panel — no white screen. */
export const CatchesRenderError = () => (
  <ErrorBoundary>
    <Bomb />
  </ErrorBoundary>
);

/** Healthy children pass through untouched. */
export const PassesChildrenThrough = () => (
  <ErrorBoundary>
    <div className="grid cols-2">
      <Kpi label="switches" value={303} />
      <Kpi label="avg health" value={72.4} tone="watch" />
    </div>
  </ErrorBoundary>
);
