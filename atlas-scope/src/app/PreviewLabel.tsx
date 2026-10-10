/**
 * PreviewLabel.tsx — Atlas Scope ships as a LABELLED PREVIEW (owner decision, 2026-10-09).
 *
 * WHERE. On the status bar, because the bar is the one piece of chrome that is present on every
 * surface and in view at every width: below 768 px the header scrolls away with the document while
 * the bar stays pinned to the viewport's bottom edge (shell.css). The label is a direct child of the
 * bar, OUTSIDE `.sb__rest` — the only part of the bar that scrolls sideways — so a narrow viewport
 * never carries it off screen; like the coverage group, it wraps onto its own line instead.
 *
 * WHAT. The word "Preview" and the reason in words: Atlas Scope's acceptance is not complete. The
 * figures behind that sentence are a dated cache of their owner, the "Totals" line of
 * `atlas-scope/docs/acceptance-report.md`; `PreviewLabel.test.tsx` fails when the two disagree, so a
 * re-grade cannot leave the chrome quoting an older one.
 *
 * Not a control and not a live region: it never changes during a session, so it takes no tab stop
 * and announces nothing. It is read in document order inside the status bar's footer landmark, and
 * its full sentence is in the accessible text as well as the tooltip.
 */
import type { ReactElement } from "react";

/** The latest acceptance grade — a cache of `docs/acceptance-report.md` (its "Graded" and "Totals" lines). */
export const ACCEPTANCE_GRADE = {
  graded: "2026-10-02/03",
  report: "atlas-scope/docs/acceptance-report.md",
  pass: 12,
  fail: 24,
  unproven: 3,
  criteria: 39,
} as const;

/** The words the bar shows. */
export const PREVIEW_WORD = "Preview";
export const PREVIEW_REASON = "acceptance not complete";

/** The whole statement: the tooltip and the accessible text. */
export const PREVIEW_STATEMENT =
  `Atlas Scope is a preview. Its acceptance is not complete: the latest grade (${ACCEPTANCE_GRADE.graded}, ` +
  `${ACCEPTANCE_GRADE.report}) records ${ACCEPTANCE_GRADE.fail} of ${ACCEPTANCE_GRADE.criteria} criteria as FAIL ` +
  `and ${ACCEPTANCE_GRADE.unproven} as UNPROVEN.`;

export function PreviewLabel(): ReactElement {
  return (
    <p className="sb__preview" data-preview="" title={PREVIEW_STATEMENT}>
      <span className="sb__preview-badge">{PREVIEW_WORD}</span>
      <span className="sb__preview-reason">{PREVIEW_REASON}</span>
      <span className="visually-hidden">{` — ${PREVIEW_STATEMENT}`}</span>
    </p>
  );
}
