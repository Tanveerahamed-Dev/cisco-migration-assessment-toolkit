/**
 * icons.tsx — the inline SVG glyph set. No icon library, no sprite sheet, no network fetch.
 *
 * Two kinds of glyph live here and they are governed by different rules.
 *
 * SEMANTIC glyphs (severity, operational state, forwarding verdict, not-observed) exist so that
 * meaning never rests on colour alone (WCAG 1.4.1, acceptance D8). Their SILHOUETTES must stay
 * mutually distinguishable at 12px and in greyscale: octagon / triangle / diamond / circle / bar
 * for severity, disc / square / dashed ring for state. Changing one of those shapes to something
 * that shares a silhouette with another is a correctness regression, not a style preference.
 *
 * CHROME glyphs (chevrons, close, copy…) are decoration attached to a control that already has
 * its own accessible name.
 *
 * Every icon renders `aria-hidden` and `focusable="false"`: an icon is never the accessible name
 * of anything. The component wrapping it supplies the name.
 *
 * All geometry is authored on a 16-unit grid and sized in `em`, so a glyph tracks the type size
 * of the row it sits in rather than being pinned to a device pixel.
 */
import type { JSX } from "react";
import type { HopVerdict, Severity } from "../core/types";

export interface IconProps {
  /** CSS length. Defaults to `1em` so the glyph scales with its row's type size. */
  size?: string;
  className?: string;
}

type Glyph = (p: IconProps) => JSX.Element;

function svg(children: JSX.Element, { size = "1em", className }: IconProps): JSX.Element {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/* ── severity silhouettes ──────────────────────────────────────────────────
   Filled, high-coverage shapes: a filled glyph survives downscaling to 12px where a stroked one
   turns to mush. The five silhouettes are chosen to differ at the outline level — corner count
   and aspect — not merely in fill. */

export const IconOctagon: Glyph = (p) =>
  svg(<path fill="currentColor" d="M5.4 1.5h5.2L14.5 5.4v5.2L10.6 14.5H5.4L1.5 10.6V5.4z" />, p);

export const IconTriangle: Glyph = (p) =>
  svg(<path fill="currentColor" d="M8 1.6 15.1 14H.9z" />, p);

export const IconDiamond: Glyph = (p) =>
  svg(<path fill="currentColor" d="M8 .9 15.1 8 8 15.1.9 8z" />, p);

export const IconCircle: Glyph = (p) => svg(<circle cx="8" cy="8" r="6.2" fill="currentColor" />, p);

export const IconBar: Glyph = (p) =>
  svg(<rect x="1.4" y="6" width="13.2" height="4" rx="2" fill="currentColor" />, p);

/* ── operational state ─────────────────────────────────────────────────────
   Disc / square / dashed ring. The dashed ring is the important one: `unknown` must read as a
   third thing at a glance, and an outline-with-gaps is the only treatment here that cannot be
   mistaken for a quieter version of either solid shape. */

export const IconStateUp: Glyph = (p) => svg(<circle cx="8" cy="8" r="5.4" fill="currentColor" />, p);

export const IconStateDown: Glyph = (p) =>
  svg(<rect x="2.6" y="2.6" width="10.8" height="10.8" rx="1.2" fill="currentColor" />, p);

export const IconStateUnknown: Glyph = (p) =>
  svg(
    <circle
      cx="8"
      cy="8"
      r="5.4"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeDasharray="3.1 2.4"
      strokeLinecap="butt"
    />,
    p,
  );

/**
 * The not-observed mark: a dashed rounded square struck through. Deliberately NOT a circle, so it
 * cannot be read as a quieter `unknown` state — "we never looked" and "the device reported that
 * it does not know" are different claims and must not share a silhouette.
 */
export const IconNotObserved: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.6">
      <rect x="2" y="2" width="12" height="12" rx="2.4" strokeDasharray="2.6 2.2" />
      <path d="M4.8 11.2 11.2 4.8" strokeLinecap="round" />
    </g>,
    p,
  );

/* ── forwarding verdicts ───────────────────────────────────────────────────
   One glyph per HopVerdict, so a hop list reads without colour. `unmodeled` reuses the
   not-observed mark on purpose: an unmodelled hop IS an absence of evidence, and giving it its
   own friendlier glyph would be exactly the absence-as-health failure. */

export const IconArrowRight: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M2.2 8h11.2M9.2 3.8 13.4 8l-4.2 4.2"
    />,
    p,
  );

export const IconTarget: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.7">
      <circle cx="8" cy="8" r="5.6" />
      <circle cx="8" cy="8" r="1.7" fill="currentColor" stroke="none" />
    </g>,
    p,
  );

export const IconNoRoute: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M2.2 8h5.1M10.2 8h3.6" />
      <path d="M8.9 5.4 6.3 10.6" />
    </g>,
    p,
  );

export const IconLoop: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M12.8 8a4.8 4.8 0 1 1-1.5-3.5" />
      <path d="M13.3 1.9v3.1h-3.1" strokeLinejoin="round" />
    </g>,
    p,
  );

export const IconClock: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.7">
      <circle cx="8" cy="8" r="6.1" />
      <path d="M8 4.5V8l2.6 1.6" strokeLinecap="round" />
    </g>,
    p,
  );

/* ── chrome ────────────────────────────────────────────────────────────────── */

export const IconChevronRight: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m6 3.4 4.8 4.6L6 12.6"
    />,
    p,
  );

export const IconChevronDown: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M3.4 6 8 10.8 12.6 6"
    />,
    p,
  );

export const IconChevronUp: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M3.4 10.4 8 5.6l4.6 4.8"
    />,
    p,
  );

export const IconClose: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      d="M3.8 3.8l8.4 8.4M12.2 3.8l-8.4 8.4"
    />,
    p,
  );

export const IconCheck: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m3.2 8.4 3.2 3.2 6.4-7.2"
    />,
    p,
  );

export const IconCopy: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.6">
      <rect x="5.4" y="5.4" width="8.2" height="8.2" rx="1.6" />
      <path d="M10.6 3.3a1.9 1.9 0 0 0-1.9-1.9H4.3a2.9 2.9 0 0 0-2.9 2.9v4.4a1.9 1.9 0 0 0 1.9 1.9" />
    </g>,
    p,
  );

export const IconSearch: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <circle cx="7" cy="7" r="4.6" />
      <path d="m10.6 10.6 3.1 3.1" />
    </g>,
    p,
  );

/** The citation affordance: a record opened out of the snapshot into the Inspector. */
export const IconCite: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M8.4 2.6H3.4a1.8 1.8 0 0 0-1.8 1.8v8.2a1.8 1.8 0 0 0 1.8 1.8h8.2a1.8 1.8 0 0 0 1.8-1.8V7.6" />
      <path d="M13.9 2.1 7.4 8.6M10.2 1.9h4v4" strokeLinejoin="round" />
    </g>,
    p,
  );

/**
 * The disclosure affordance for an explanation that used to be printed in full above a working
 * surface. The sentence is not deleted — it moves behind this glyph, which is why the glyph has to
 * read as "there is more here", not as decoration.
 */
export const IconInfo: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <circle cx="8" cy="8" r="6.3" />
      <path d="M8 7.2v4.1" />
      <path d="M8 4.7v.1" strokeWidth="2" />
    </g>,
    p,
  );

export const IconFilter: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M1.9 3.1h12.2l-4.7 5.6v4.6l-2.8 1.6V8.7z"
    />,
    p,
  );

export const IconSortNone: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M5.2 6.4 8 3.6l2.8 2.8M10.8 9.6 8 12.4 5.2 9.6"
    />,
    p,
  );

export const IconSortAsc: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M4.4 9.6 8 6l3.6 3.6"
    />,
    p,
  );

export const IconSortDesc: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M4.4 6.4 8 10l3.6-3.6"
    />,
    p,
  );

export const IconCommand: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      d="M5.6 2.4a2.2 2.2 0 1 0 0 4.4h4.8a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0-2.2 2.2v6.8a2.2 2.2 0 1 1-2.2 2.2 2.2 2.2 0 0 1 2.2-2.2h4.8a2.2 2.2 0 1 1-2.2-2.2"
    />,
    p,
  );

export const IconSun: Glyph = (p) =>
  svg(
    <g fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
      <circle cx="8" cy="8" r="3.2" />
      <path d="M8 1.2v1.6M8 13.2v1.6M1.2 8h1.6M13.2 8h1.6M3.2 3.2l1.1 1.1M11.7 11.7l1.1 1.1M12.8 3.2l-1.1 1.1M4.3 11.7l-1.1 1.1" />
    </g>,
    p,
  );

export const IconMoon: Glyph = (p) =>
  svg(
    <path
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinejoin="round"
      d="M13.4 9.6A5.9 5.9 0 0 1 6.4 2.6a5.9 5.9 0 1 0 7 7z"
    />,
    p,
  );

/* ── semantic maps ─────────────────────────────────────────────────────────
   Exported so every surface resolves a severity, a state or a verdict to the SAME glyph. A
   surface that picks its own icon for "denied" is how two screens end up disagreeing about what
   a stop sign means. */

export const SEVERITY_ICON: Readonly<Record<Severity, Glyph>> = {
  Critical: IconOctagon,
  High: IconTriangle,
  Medium: IconDiamond,
  Low: IconCircle,
  Info: IconBar,
};

export const STATE_ICON: Readonly<Record<"up" | "down" | "unknown", Glyph>> = {
  up: IconStateUp,
  down: IconStateDown,
  unknown: IconStateUnknown,
};

export const VERDICT_ICON: Readonly<Record<HopVerdict, Glyph>> = {
  forwarded: IconArrowRight,
  delivered: IconTarget,
  "no-route": IconNoRoute,
  denied: IconOctagon,
  unmodeled: IconNotObserved,
  loop: IconLoop,
  "ttl-exceeded": IconClock,
};
