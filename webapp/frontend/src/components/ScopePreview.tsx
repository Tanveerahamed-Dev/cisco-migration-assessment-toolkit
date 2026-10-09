import { useId, type ReactNode } from "react";

// Atlas Scope ships as a LABELLED PREVIEW (owner decision, 2026-10-09). Atlas Scope's own chrome carries
// the label on every view (atlas-scope/src/app/PreviewLabel.tsx); this is AssessHub's matching qualifier,
// placed beside every entry to Scope so the reader is told before following it, not only after. The
// acceptance grade it refers to is owned by atlas-scope/docs/acceptance-report.md and is deliberately not
// restated here: the words say only that acceptance is not complete.
//
// Every AssessHub entry to Scope goes through this module: a link through ScopeEntryLink, any other entry
// (the embedded view's heading) through WithScopePreview. src/scopeEntries.test.ts reads the source and fails
// when a component that consumes the Scope capability (api.scopeView, projectionEmbedUrl) or names a "/scope"
// target renders an entry any other way.
export const SCOPE_PREVIEW_WORD = "Preview";
export const SCOPE_PREVIEW_DETAIL =
  "Atlas Scope is a preview: its acceptance is not complete (see atlas-scope/docs/acceptance-report.md).";

// The qualifier itself: the existing tag chip, a visible word, the full sentence as the tooltip and as
// screen-reader text. Not a control, so it adds no tab stop. `id` lets the entry it qualifies name it as its
// accessible description (aria-describedby), so a screen reader hears the qualifier with the entry itself.
export function ScopePreviewTag({ id }: { id?: string }) {
  return (
    <span className="chip tag" data-scope-preview="" id={id} title={SCOPE_PREVIEW_DETAIL}>
      {SCOPE_PREVIEW_WORD}
      <span className="sr-only">{`: ${SCOPE_PREVIEW_DETAIL}`}</span>
    </span>
  );
}

const ENTRY_STYLE = { display: "inline-flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" } as const;

// An entry to Scope that is not a link (the embedded view's heading) with the qualifier directly beside it. A
// div, so it may hold a heading; inline-flex, so it sits in a header row as one item. A caller that ties the
// qualifier to its entry passes the same `qualifierId` to the entry's aria-describedby.
export function WithScopePreview({ children, qualifierId }: { children: ReactNode; qualifierId?: string }) {
  return (
    <div className="scope-entry" style={ENTRY_STYLE}>
      {children}
      <ScopePreviewTag id={qualifierId} />
    </div>
  );
}

// The one link to Atlas Scope: the anchor and its qualifier, side by side, with the qualifier as the link's
// accessible description. `href` is the caller's already-validated same-hub Scope target (the scope-view
// capability's href); this component does not choose or rewrite it. A `title` (the server's scope-view detail)
// stays the pointer tooltip, and because aria-describedby replaces a title as the description, it is ALSO a
// screen-reader-only description of its own: the link is described by the qualifier and then by that detail.
export function ScopeEntryLink({ href, title, children }: { href: string; title?: string; children: ReactNode }) {
  const qualifier = useId();
  const detail = useId();
  return (
    <div className="scope-entry" style={ENTRY_STYLE}>
      <a className="btn" href={href} title={title} aria-describedby={title ? `${qualifier} ${detail}` : qualifier}>
        {children}
      </a>
      <ScopePreviewTag id={qualifier} />
      {title ? <span id={detail} className="sr-only">{title}</span> : null}
    </div>
  );
}
