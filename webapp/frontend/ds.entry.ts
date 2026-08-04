/* Design-system entry for design-sync (claude.ai/design import).
 *
 * The app itself has no library build — this barrel is what `window.AssessHub` exposes to the
 * design agent. Named re-exports only: the snapshot widgets are default exports in their files,
 * and a `export *` synth entry would silently drop them. Outside tsconfig's `include: ["src"]`
 * on purpose, so the app build never type-checks it.
 */
// Token layer rides the JS bundle: esbuild emits it as CSS, and the converter appends
// cfg.cssEntry (styles.css) after it — so _ds_bundle.css = tokens first, component classes second.
import "./src/theme.css";

export {
  CountUp, Loading, ErrorBox, Kpi, Gauge, SegBar, Bars, SevChip,
  Skeleton, SkelLines, SkelTable,
  useReducedMotion, useAsync, useToast, useViewTransition, usePositionTween,
} from "./src/components/ui";
export { ErrorBoundary } from "./src/components/ErrorBoundary";
// Coverage-honesty surface: the badge/banner pair that keeps "not observed" from reading as
// "healthy". normalizedVerification is the guard itself — stale, legacy or absent metadata is
// normalised DOWN to unverified, so neither component can ever over-claim.
export {
  VerificationBadge, VerificationWarning, normalizedVerification, VERIFICATION_CONTRACT_VERSION,
} from "./src/components/VerificationStatus";
export { default as TopologyGraph } from "./src/components/TopologyGraph";
export { default as CableMap } from "./src/components/CableMap";
export { default as CausalFlowPanel } from "./src/components/CausalFlow";
export { default as CutoverPlanner } from "./src/components/CutoverPlanner";
export { default as DesignBlueprintPanel } from "./src/components/DesignBlueprint";
export { default as ArchReviewPanel } from "./src/components/ArchReview";
// Engine-vocabulary → token helpers (severity/band/readiness/gate colours).
export { sevColor, sevSoft, bandColor, readyColor, gateColor } from "./src/api";
