import type { ReactNode } from "react";

// Atlas Scope ships as a LABELLED PREVIEW (owner decision, 2026-10-09). Atlas Scope's own chrome carries
// the label on every view (atlas-scope/src/app/PreviewLabel.tsx); this is AssessHub's matching qualifier,
// placed beside every entry to Scope so the reader is told before following it, not only after. The
// acceptance grade it refers to is owned by atlas-scope/docs/acceptance-report.md and is deliberately not
// restated here: the words say only that acceptance is not complete.
export const SCOPE_PREVIEW_WORD = "Preview";
export const SCOPE_PREVIEW_DETAIL =
  "Atlas Scope is a preview: its acceptance is not complete (see atlas-scope/docs/acceptance-report.md).";

// The qualifier itself: the existing tag chip, a visible word, the full sentence as the tooltip and as
// screen-reader text. Not a control, so it adds no tab stop.
export function ScopePreviewTag() {
  return (
    <span className="chip tag" data-scope-preview="" title={SCOPE_PREVIEW_DETAIL}>
      {SCOPE_PREVIEW_WORD}
      <span className="sr-only">{`: ${SCOPE_PREVIEW_DETAIL}`}</span>
    </span>
  );
}

// An entry to Scope (a link, or the embedded view's heading) with the qualifier directly beside it. A div,
// so it may hold a heading as well as a link; inline-flex, so it sits in a header row as one item.
export function WithScopePreview({ children }: { children: ReactNode }) {
  return (
    <div className="scope-entry" style={{ display: "inline-flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
      {children}
      <ScopePreviewTag />
    </div>
  );
}
