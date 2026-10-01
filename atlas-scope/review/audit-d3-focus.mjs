/**
 * audit-d3-focus.mjs — acceptance D3 in a real browser: no surface that closes, unmounts or is left
 * with Escape ever drops keyboard focus to <body>.
 *
 * WHY THIS EXISTS. The unit suite drives each surface in jsdom, which lays nothing out and fires no
 * native focus moves of its own. The D3 regression the independent review measured (snapshot
 * popover, Tab, Escape: activeElement BODY, 2 of 2) was invisible to every test that existed, and
 * the same review listed as NOT EXAMINED the unmount-return paths in the inspector tabs, the JSON
 * find bar and toasts. So every surface this script can open is driven the way a keyboard reader
 * drives it, and `document.activeElement` is read ONE SECOND later — after React has unmounted
 * whatever closed, which is when a return to a vanished element shows up.
 *
 * SURFACES ARE DISCOVERED, NOT LISTED. On every page state (idle, a finding selected, the device
 * view of the evidence rail, the Inspector opened with `i`, the Inspector opened from a citation)
 * the script enumerates what is on screen:
 *   - popovers and menus: every visible `[aria-haspopup]` trigger — open → Escape, open → Tab →
 *     Escape, and open → Tab until focus leaves the panel → Escape (the D3 regression's path);
 *   - tabs: every visible `[role=tab]` (the Inspector's and the device pane's included), with focus
 *     on the tab and with focus inside its panel;
 *   - find bars: every text field inside a tab panel, driven with its tab selected (the Inspector's
 *     JSON "Search this document" among them);
 *   - text fields outside tab panels: the query bars and filters;
 *   - grids: every visible `[role=grid]`;
 *   - the Inspector's own close paths (its close button, and its `i` toggle pressed from inside);
 *   - dialogs bound to keys (the command palette and the keyboard reference);
 *   - toasts: any VISIBLE status/alert element that appears after a copy action. A visually
 *     hidden live region is an announcement, not a toast, and is not counted as one. MEASURED
 *     2026-09-22: none appears — copy outcomes are announced in a live region (the copy helper in
 *     src/ui/primitives.tsx says so), so the count is printed and the copy action itself is a case.
 * Every state is driven in full: where focus returns to depends on what is on screen around it.
 * A find bar is a text field inside a tab panel; it is driven with its tab selected, since a panel
 * that is not selected is not mounted.
 *
 * A CASE THAT DID NOT RUN IS NOT A PASS. Every case checks that the surface actually opened (the
 * trigger reports `aria-expanded=true`, a new dialog is on screen, the Inspector mounted) and
 * records NOT-DRIVEN otherwise, which fails the run. The denominators are printed and the run also
 * fails when a kind the acceptance review named (popover, dialog, tab, find bar, the Inspector) was never
 * driven at all — "0 inspector tabs" once printed as an INFO line under an exit 0, which proved
 * nothing about the path it was written to examine.
 *
 * FOCUS MUST ALSO BE SEEN (acceptance D3, "focus is always visible"; WCAG 2.2 SC 2.4.7). Until
 * 2026-09-23 this script checked only where focus RETURNED, and passed 210 of 210 while two focus
 * stops it drove every run were invisible: the device pane's tab panel, whose 2 px outline sat
 * outside the `.dp__body` scroll box and was clipped whole ("0 pixels at >=3:1"), and the snapshot
 * popover's first control, "Copy the snapshot sha256", which the unwrapped 64-digit sha pushed to
 * x=641–668 outside a popover ending at x=554 — `elementFromPoint` at its centre was the 3-D canvas.
 * So EVERY focus stop the script reaches — the control a surface moves focus to as it opens, the
 * next control after Tab, a tab after an arrow, a tab panel entered with Tab (APG: the panel is a
 * tab stop), a field, a grid cell, and the element focus returns to — is now also checked for
 * VISIBILITY, in two independent ways:
 *   - HIT TEST: `elementFromPoint` at the centre of the element's VISIBLE part (its box intersected
 *     with the viewport and with every ancestor that clips it) must be the element or a descendant.
 *     An element with no visible part fails outright.
 *   - INDICATOR PIXELS: the region around the element (and around any ancestor that draws the ring
 *     for it, the `:focus-within` query-bar pattern) is photographed focused, then again with the
 *     outline removed from the element and those ancestors (and the element's own box-shadow), all
 *     by inline `!important` style so no stylesheet can override it. A pixel counts as indicator
 *     only when its two colours differ by at least 3:1 — the non-text contrast floor this project
 *     applies (D4), measured as the change of contrast SC 2.4.13 defines. Only what is PAINTED can
 *     differ, so an outline clipped by a scroller, or painted off screen, or covered by another
 *     layer, counts for nothing. The floor is HALF the perimeter of the element's visible box, in
 *     CSS pixels: a 1 px line along at least half of what the reader can see. Why half and not the
 *     whole perimeter, MEASURED 2026-09-23: the findings grid's focused 24x17 severity cell draws
 *     a plainly visible 2 px inset ring, yet only 66 of its pixels change by >=3:1 against a full
 *     perimeter of 82 — the box sits at y=421.19, so each horizontal edge keeps one full-strength
 *     row and one antialiased row, the rounded corners lose more, and an inset ring is shorter
 *     than the box it is inside. A painted 2 px ring gives ~0.8 of the perimeter; a ring clipped
 *     whole gives 0; one clipped on three sides of four gives well under half. It is a floor for
 *     "visible" (SC 2.4.7), not a grade against the 2 px area SC 2.4.13 asks for.
 *   - KEYBOARD MODALITY: a stop the script reaches with `focus()` after a mouse click would not
 *     match `:focus-visible` — but a keyboard reader reaches it with Tab, and Chromium re-evaluates
 *     on the next key. Shift (which nothing in the app binds on its own) is pressed before measuring.
 * A stop that is not visible fails the run exactly as a return to <body> does.
 *
 *   node review/audit-d3-focus.mjs                       # the production preview on :4181
 *   ATLAS_URL=http://localhost:4180 node review/audit-d3-focus.mjs
 *   node review/audit-d3-focus.mjs --self-removing       # ONLY the self-removing-control pass, at
 *                                                        # 1440, 768 and 390 (see that section)
 *   node review/audit-d3-focus.mjs --sweep               # ONLY the sweep (see that section): at 390,
 *                                                        # 768, 1000, 1440, 1920 and every rung those
 *                                                        # miss (LADDER_REM), every composite widget's
 *                                                        # tab stops, the whole tab order hit-tested at
 *                                                        # nine points, More -> Path, the evidence
 *                                                        # drawer pass (its open/close/resize cases),
 *                                                        # and the RUNG-CROSSING pass: every focusable
 *                                                        # element at every rung, crossed to each
 *                                                        # neighbouring rung (see that section)
 *
 *   node review/audit-d3-focus.mjs --vp=390              # any mode, narrowed to the listed widths —
 *                                                        # diagnostic only, never the acceptance run
 *   node review/audit-d3-focus.mjs --sweep --state=off-view   # the sweep narrowed to the states whose
 *                                                        # name contains the text — diagnostic only
 *   node review/audit-d3-focus.mjs --crossings           # ONLY the rung-crossing pass (diagnostic)
 *   node review/audit-d3-focus.mjs --render-check        # ONLY the proof that the geometry passes'
 *                                                        # render mode changes no focus outcome (RENDER)
 *   node review/audit-d3-focus.mjs --sweep --render=full # the geometry passes with every frame drawn
 *                                                        # (the reference; hours on a software renderer)
 *
 * TRACTABLE BY CONSTRUCTION (phase 3.5): the geometry passes run with the fabric's WebGL draw calls
 * suspended (RENDER, proved by --render-check), the rung crossing runs as (crossing x state) units
 * ATLAS_CROSS_PARALLEL at a time, and every phase prints its wall time (TIME / WALL TIME lines).
 *
 * The sweep also runs the OPERABLE-ELEMENT CENSUS (operableCensus, 2026-09-25): every element that
 * is operated by the pointer — found by its handler or its cursor, never by role or tabindex — must
 * be reached by the Tab walk, be outside aria-hidden, and measure >= 24x24 CSS px.
 *
 * EVERY WIDTH LIST COVERS EVERY RUNG (2026-09-26). The lists are checked against `LADDER_REM`, read
 * from src/app/surfaces.tsx; a rung a list misses gets its midpoint added and printed. The drawer rung
 * (1024-1279 px) was missing from all three lists, which is how the evidence drawer's focus loss went
 * unseen. The drawer itself has its own pass (see "the evidence drawer" below), part of the sweep.
 *
 * The default run is the sweep beside the surface passes below at all of those widths. The
 * visibility hit test samples NINE points of the focused element's visible part (focusGeometry);
 * until 2026-09-24 it sampled the centre only, and the surface passes never drove 768 or 390.
 *
 * Exit 0: every case driven, none on BODY, and every focus stop visible. Exit 1: a case landed on
 * BODY or did not run, a focus stop was not visible, or a required kind was never driven or never
 * checked for visibility. Exit 2: nothing was driven at all.
 */
import { readFileSync } from "node:fs";
import { freemem } from "node:os";
import { chromium } from "@playwright/test";
import ts from "typescript";
import { PALETTE_WARM_TERMINAL, appModalDialogs, checkPaletteOverDialog } from "./palette-warm.mjs";

const APP = process.env["ATLAS_URL"] ?? "http://localhost:4181";
const SETTLE_MS = 1000;

/* ── the render mode of the passes judged by GEOMETRY (phase 3.5: the audit must be tractable) ─────────
 * MEASURED (phase 3, this host): the full --sweep ran ~10 hours before it was stopped. The headless
 * renderer rasterises the 3-D fabric in SOFTWARE (SwiftShader) for every frame it draws, and every
 * rung-crossing case resizes twice: a probe of four pages at 1440 -> 1152 -> 1440 read 2.7-3.0 s per
 * resize with every frame drawn, and 0.34-0.36 s with the WebGL draw calls suspended (probe-render.mjs,
 * phase 3.5; the platform GPU read 0.43-0.48 s).
 *
 * So the passes whose verdicts are GEOMETRY — the rung crossing (focus, `checkVisibility`, the nine-point
 * hit test) and the sweep's Tab walk (the hit test, the operable census) — run by default with the
 * fabric's draw calls SUSPENDED: an init script turns the WebGL contexts' draw, clear and blit calls into
 * no-ops before the app runs. Everything else is untouched: the scene graph, the camera, the labels'
 * projection, the quality tier (the renderer string still names SwiftShader, so it is `low` in both
 * modes), every DOM node, style, layout, frame callback and timer. The canvas is still in the page, still
 * a tab stop and still hit-testable — it shows nothing. What a draw call changes is canvas PIXELS, and no
 * verdict of these passes reads a pixel.
 *
 * The passes that DO read pixels — the ≥3:1 indicator-ring measurement (checkVisible: the surface passes,
 * the drawer pass, the self-removing pass) and the rendered D1 dialog stack — always draw every frame.
 *
 * THE MODE IS PROVED, NOT ASSUMED: every geometry page reports whether the suspension was installed and how
 * many draw calls it suppressed (a page without it, or a run that suppressed none at all, did not run in the
 * mode, and fails the run), and `--render-check` drives a sample of
 * rung-crossing cases — every family, three crossings, two page states — in BOTH modes on the same
 * build and fails on any case whose focus outcome differs (renderCheck). `--render=full` runs the
 * geometry passes with every frame drawn, as before (the reference, and the slow path).
 */
const RENDER = process.argv.find((a) => a.startsWith("--render="))?.slice(9) ?? "suspended";
if (RENDER !== "suspended" && RENDER !== "full") throw new Error(`--render=${RENDER}: the render mode is "suspended" (default) or "full"`);
/** In-page (an init script): the WebGL draw, clear and blit calls become no-ops, counted. */
const suspendDraws = () => {
  const DRAWS = ["drawArrays", "drawElements", "drawArraysInstanced", "drawElementsInstanced", "drawRangeElements", "clear", "blitFramebuffer"];
  window.__d3DrawsSuspended = 0;
  const skip = function () {
    window.__d3DrawsSuspended += 1;
  };
  for (const C of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {
    if (C === undefined) continue;
    for (const m of DRAWS) if (typeof C.prototype[m] === "function") Object.defineProperty(C.prototype, m, { value: skip, configurable: true, writable: true });
  }
  /* The multi-draw extension draws too: its calls are suspended on the object the extension hands out. */
  for (const C of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {
    if (C === undefined) continue;
    const getExtension = C.prototype.getExtension;
    C.prototype.getExtension = function (name) {
      const ext = getExtension.call(this, name);
      if (ext !== null && typeof name === "string" && /multi_draw/i.test(name)) {
        for (let p = ext; p !== null && p !== Object.prototype; p = Object.getPrototypeOf(p)) {
          for (const k of Object.getOwnPropertyNames(p)) if (/^multiDraw/.test(k) && typeof ext[k] === "function") ext[k] = skip;
        }
      }
      return ext;
    };
  }
};
/** Pages that ran with draws suspended, and the draw calls they suppressed: the mode's own denominator. A page on
 *  which the suspension was NOT installed (`pagesNotSuspended`) means the mode did not take effect. (A page may
 *  suppress nothing and be right: a fabric at the stacked rung, never shown, draws no frame.) */
const renderCount = { pages: 0, suppressed: 0, pagesNotSuspended: 0 };
/** A new context for a GEOMETRY pass, in this run's render mode (`mode` overrides it: renderCheck). */
async function geometryContext(browser, options, mode = RENDER) {
  const ctx = await browser.newContext(options);
  if (mode === "suspended") await ctx.addInitScript(suspendDraws);
  return ctx;
}
/** Read (and account for) the draws a suspended page suppressed, before it closes. A page on which the
 *  suspension is not installed is counted, and fails the run. (A closed or crashed page cannot be read.) */
async function accountRender(page, mode = RENDER) {
  if (mode !== "suspended") return;
  const n = await page.evaluate(() => (typeof window.__d3DrawsSuspended === "number" ? window.__d3DrawsSuspended : -1)).catch(() => null);
  if (n === null) return;
  renderCount.pages += 1;
  if (n >= 0) renderCount.suppressed += n;
  else renderCount.pagesNotSuspended += 1;
}
/** Wall time of each phase of this run, printed at the end (the tractability budget is measured, not assumed). */
const phaseTimes = [];
async function timed(name, fn) {
  const t0 = Date.now();
  try {
    return await fn();
  } finally {
    phaseTimes.push([name, Date.now() - t0]);
    console.log(`TIME  ${name}: ${((Date.now() - t0) / 60000).toFixed(1)} min`);
  }
}
const RUN_T0 = Date.now();

/* ── the viewport ladder, READ from its one owner ──────────────────────────────
 * MEASURED (acceptance report D3, overturned PASS -> FAIL, 2026-09-26): every width list in this file
 * was typed by hand — 1920/1440/1000/768/390 — and none fell in the drawer rung (1024-1279 px), where
 * Rail B is an overlay drawer. So the drawer's close paths, which dropped focus to <body>, were never
 * driven, and the run said "547 case(s), 0 failed" with the defect present. The rungs are now read from
 * `LADDER_REM` in src/app/surfaces.tsx (parsed with the TypeScript compiler, not restated), every
 * width list is checked to hold at least one width in EVERY rung, and a rung a list misses gets that
 * rung's midpoint added — printed, so the addition is visible. The drawer pass below derives its
 * widths (the rung's lower edge, its midpoint, and just under its upper edge) from the same owner. */
function readLadderRem() {
  const file = new URL("../src/app/surfaces.tsx", import.meta.url);
  const sf = ts.createSourceFile("surfaces.tsx", readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let found = null;
  const visit = (n) => {
    if (found !== null) return;
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === "LADDER_REM" && n.initializer !== undefined) {
      let init = n.initializer;
      while (ts.isAsExpression(init) || ts.isSatisfiesExpression(init) || ts.isParenthesizedExpression(init)) init = init.expression;
      if (ts.isObjectLiteralExpression(init)) {
        found = {};
        for (const p of init.properties) {
          if (ts.isPropertyAssignment(p) && ts.isIdentifier(p.name) && ts.isNumericLiteral(p.initializer)) found[p.name.text] = Number(p.initializer.text);
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  if (found === null || Object.keys(found).length === 0) throw new Error("LADDER_REM could not be read from src/app/surfaces.tsx: the audit will not guess the ladder");
  return found;
}
const LADDER_REM = readLadderRem();
const REM_PX = 16; /* a media query's rem is the initial 16 px, whatever the page's root size (surfaces.tsx) */
/** The rungs, in px: [from, to) — the first has no lower owner boundary and is "stacked". */
const RUNGS = (() => {
  const edges = Object.entries(LADDER_REM)
    .map(([name, rem]) => [name, rem * REM_PX])
    .sort((a, b) => a[1] - b[1]);
  const out = [{ name: "stacked", from: 0, to: edges[0][1] }];
  edges.forEach(([name, px], i) => out.push({ name, from: px, to: edges[i + 1]?.[1] ?? Infinity }));
  return out;
})();
const rungOf = (w) => RUNGS.find((r) => w >= r.from && w < r.to)?.name ?? "none";
const midpointOf = (r) => (Number.isFinite(r.to) ? Math.round((r.from + r.to) / 2) : r.from + 160);
/** `list` with a width added for every rung it does not reach. */
function coverRungs(list, label) {
  const out = [...list];
  for (const r of RUNGS) {
    if (out.some(([w]) => rungOf(Number(w)) === r.name)) continue;
    const w = midpointOf(r);
    console.log(`INFO  ${label}: no width in the ${r.name} rung (${r.from}-${Number.isFinite(r.to) ? r.to - 1 : "up"} px, LADDER_REM); added ${w} px`);
    out.push([w, 800, `${r.name} rung`]);
  }
  return out;
}
const DRAWER_RUNG = RUNGS.find((r) => r.name === "drawer");
if (DRAWER_RUNG === undefined) throw new Error("LADDER_REM has no `drawer` rung: the drawer pass has nothing to derive its widths from");
/** The drawer rung's lower edge, midpoint, and just under its upper edge. */
const DRAWER_WIDTHS = [DRAWER_RUNG.from, midpointOf(DRAWER_RUNG), DRAWER_RUNG.to - 10];

const VIEWPORTS = coverRungs(
  [
    [1920, 1080, "wide"],
    [1440, 900, "desktop"], // the acceptance review's 1440 measurement of the snapshot popover
    [1000, 800, "compact"], // below the header's 1024px breakpoint: the "More" popover exists
    /* 2026-09-24: the two narrow rungs were never driven here, and both acceptance findings of that
       date live there — D1's pane switch at 768 and D3's covered status bar at 390. */
    [768, 1024, "tablet"],
    [390, 844, "phone"],
  ],
  "surface passes",
);

/** @type {{surface: string, scenario: string, ok: boolean, why: string}[]} */
const results = [];
/** kind -> number of cases driven, across the whole run. */
const driven = new Map();
/** Per page (the surface passes run one page per width, several widths at once): the surfaces already
 *  driven in the current state. */
const seenByPage = new WeakMap();
const seenOf = (page) => {
  let s = seenByPage.get(page);
  if (s === undefined) seenByPage.set(page, (s = new Set()));
  return s;
};

const record = (kind, surface, scenario, active) => {
  const ok = active.tag !== "BODY" && active.tag !== "NONE";
  results.push({ surface, scenario, ok, why: ok ? "" : "landed on BODY" });
  driven.set(kind, (driven.get(kind) ?? 0) + 1);
  console.log(`${ok ? "PASS" : "FAIL"}  ${surface} :: ${scenario} -> ${active.desc}`);
};
const notDriven = (surface, scenario, why) => {
  results.push({ surface, scenario, ok: false, why: `NOT DRIVEN: ${why}` });
  console.log(`FAIL  ${surface} :: ${scenario} -> NOT DRIVEN (${why})`);
};

/**
 * Put focus on `loc` and confirm it got there. A case whose focus never reached the element under
 * test proves nothing about that element, so it is NOT DRIVEN (a failure) — never a PASS of wherever
 * focus happened to be. MEASURED (independent verifier, 2026-09-26, --vp=1152): the previous case's
 * Escape had closed the evidence drawer, the next case's tab.focus() ran while the drawer was still
 * sliding shut, and cases whose focus never reached their tab were printed as PASS with focus on
 * #stage.
 */
async function focusOn(page, loc, surface, scenario) {
  await loc.focus().catch(() => {});
  const ok = await loc.evaluate((el) => el === document.activeElement || el.contains(document.activeElement)).catch(() => false);
  if (!ok) notDriven(surface, scenario, "focus never reached the element under test");
  return ok;
}

/** @type {{stop: string, surface: string, scenario: string, ok: boolean, why: string}[]} */
const visResults = [];
/** stop kind -> number of focus stops checked for visibility. */
const visChecked = new Map();

/* ── in-page helpers (serialised into the browser) ─────────────────────────── */

const describeActive = () => {
  const a = document.activeElement;
  if (a === null) return { tag: "NONE", desc: "null" };
  /* <body>'s "name" would be the whole page's text, which reads as if focus were on its first
     control (the skip link). Nothing on <body> is focused; say exactly that. */
  if (a === document.body) return { tag: "BODY", desc: "BODY (nothing focused)" };
  const name = (a.getAttribute("aria-label") ?? (a.textContent ?? "")).trim().replace(/\s+/g, " ").slice(0, 40);
  const cls = typeof a.className === "string" ? a.className.split(" ")[0] : "";
  return { tag: a.tagName, desc: `${a.tagName}${a.id ? `#${a.id}` : ""}${cls ? `.${cls}` : ""} "${name}"` };
};

/** Visible elements matching `sel`, as {name, ident, occurrence} — occurrence disambiguates equal identities. */
const listIn = (sel) => {
  const vis = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const nameOf = (el) => {
    const by = el.getAttribute("aria-labelledby");
    const labelled = by ? by.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ") : "";
    const lab = el.labels?.[0]?.textContent ?? "";
    return (el.getAttribute("aria-label") ?? (labelled || lab || el.textContent || el.getAttribute("placeholder") || el.tagName))
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 48);
  };
  const counts = new Map();
  return [...document.querySelectorAll(sel)].filter(vis).map((el) => {
    const name = nameOf(el);
    /* Identity is the element's id when it has one: a tab's accessible name carries a live count
       ("Data12" becomes "Data24" when the selection changes) and would not be found again. */
    const ident = el.id !== "" ? `#${el.id}` : name;
    const occurrence = counts.get(ident) ?? 0;
    counts.set(ident, occurrence + 1);
    return { name, ident, occurrence };
  });
};

/** Mark the `occurrence`-th visible element with identity `ident` so a locator can reach it. */
const markIn = ([sel, ident, occurrence]) => {
  for (const el of document.querySelectorAll("[data-d3-probe]")) el.removeAttribute("data-d3-probe");
  const vis = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const nameOf = (el) => {
    const by = el.getAttribute("aria-labelledby");
    const labelled = by ? by.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ") : "";
    const lab = el.labels?.[0]?.textContent ?? "";
    return (el.getAttribute("aria-label") ?? (labelled || lab || el.textContent || el.getAttribute("placeholder") || el.tagName))
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 48);
  };
  const hit = [...document.querySelectorAll(sel)].filter(vis).filter((el) => (el.id !== "" ? `#${el.id}` : nameOf(el)) === ident)[occurrence];
  if (!hit) return false;
  hit.setAttribute("data-d3-probe", "");
  return true;
};

const visibleDialogs = () =>
  [...document.querySelectorAll('[role="dialog"], [role="menu"], [role="listbox"], [role="alertdialog"]')].filter(
    (el) => el.getClientRects().length > 0,
  ).length;

/* ── focus visibility (serialised into the browser) ────────────────────────── */

/**
 * Where the focused element can be seen. Its box is intersected with the viewport and with the
 * padding box of every ancestor that CLIPS it — an ancestor whose overflow is not `visible`, taken
 * along the containing-block chain, so a `position: fixed` popover portalled under <body> is not
 * "clipped" by a scroller it merely follows in the DOM. Returns the visible rect, the hit test at
 * its centre, and the region the indicator can occupy (the element's box and that of any ancestor
 * drawing an outline for it, grown by the outline's reach), clamped to the viewport.
 */
const focusGeometry = () => {
  const a = document.activeElement;
  if (a === null || a === document.body || a === document.documentElement) return null;
  const name = (a.getAttribute("aria-label") ?? (a.textContent ?? "")).trim().replace(/\s+/g, " ").slice(0, 40);
  const cls = typeof a.className === "string" ? a.className.split(" ")[0] : "";
  const desc = `${a.tagName}${a.id ? `#${a.id}` : ""}${cls ? `.${cls}` : ""} "${name}"`;
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  const meet = (p, q) => ({ l: Math.max(p.l, q.l), t: Math.max(p.t, q.t), r: Math.min(p.r, q.r), b: Math.min(p.b, q.b) });
  const box = (r) => ({ l: r.left, t: r.top, r: r.right, b: r.bottom });
  let clip = { l: 0, t: 0, r: vw, b: vh };
  const clippers = [];
  /* The containing-block walk: a fixed box escapes every ancestor that does not establish a
     containing block for it; an absolute box escapes every static ancestor. */
  const containsFixed = (cs) =>
    cs.transform !== "none" || cs.filter !== "none" || cs.perspective !== "none" || /paint|layout|strict|content/.test(cs.contain);
  let pos = getComputedStyle(a).position;
  for (let el = a.parentElement; el !== null && el !== document.body && el !== document.documentElement; el = el.parentElement) {
    const cs = getComputedStyle(el);
    const applies = pos === "fixed" ? containsFixed(cs) : pos === "absolute" ? cs.position !== "static" || containsFixed(cs) : true;
    if (!applies) continue;
    if (cs.overflowX !== "visible" || cs.overflowY !== "visible") {
      const r = el.getBoundingClientRect();
      const l = r.left + el.clientLeft;
      const t = r.top + el.clientTop;
      clip = meet(clip, { l, t, r: l + el.clientWidth, b: t + el.clientHeight });
      const c = typeof el.className === "string" ? el.className.split(" ")[0] : "";
      clippers.push(`${el.tagName.toLowerCase()}${c ? `.${c}` : ""}`);
    }
    pos = cs.position;
  }
  const vis = meet(box(a.getBoundingClientRect()), clip);
  const w = vis.r - vis.l;
  const h = vis.b - vis.t;
  if (w < 1 || h < 1) return { desc, visible: false, clippers, perimeter: 0 };
  /* NINE points, not the centre. MEASURED 2026-09-24 (acceptance report D3): at 390x844 the status
     bar's "23/26 collected" was painted over whole by `.rail--b` once the page had scrolled to 10537,
     and this file reported "0 not visible" — it never visited 390, and a single centre sample
     cannot tell a covered corner from a covered control. Every point of a 3x3 lattice inset 15% into
     the visible part must hit the element or a descendant: a focused control another layer paints
     over, in whole or in part, is a focused control the reader cannot fully see. */
  const hits = [];
  for (const fy of [0.15, 0.5, 0.85]) {
    for (const fx of [0.15, 0.5, 0.85]) {
      const el = document.elementFromPoint(vis.l + fx * w, vis.t + fy * h);
      if (el !== null && (el === a || a.contains(el))) continue;
      const c = el && typeof el.className === "string" ? el.className.split(" ")[0] : "";
      hits.push(el === null ? "nothing" : `${el.tagName}${c ? `.${c}` : ""}`);
    }
  }
  const hitOk = hits.length === 0;
  const hitDesc = hitOk ? "the element" : `${9 - hits.length}/9 points on the element; the rest on ${[...new Set(hits)].join(", ")}`;
  /* The indicator region: the element and every ancestor painting an outline (the ring-on-the-form
     pattern of the query bars), each grown by how far its outline reaches. */
  let zone = null;
  for (let el = a; el !== null && el !== document.body; el = el.parentElement) {
    const cs = getComputedStyle(el);
    const ow = cs.outlineStyle === "none" ? 0 : parseFloat(cs.outlineWidth) || 0;
    if (el !== a && ow === 0) continue;
    const reach = Math.max(0, parseFloat(cs.outlineOffset) || 0) + ow + 3;
    const r = el.getBoundingClientRect();
    const z = { l: r.left - reach, t: r.top - reach, r: r.right + reach, b: r.bottom + reach };
    zone = zone === null ? z : { l: Math.min(zone.l, z.l), t: Math.min(zone.t, z.t), r: Math.max(zone.r, z.r), b: Math.max(zone.b, z.b) };
  }
  zone = meet(zone, { l: 0, t: 0, r: vw, b: vh });
  const x = Math.floor(zone.l);
  const y = Math.floor(zone.t);
  return {
    desc,
    visible: true,
    clippers,
    vis: [Math.round(vis.l), Math.round(vis.t), Math.round(vis.r), Math.round(vis.b)],
    perimeter: Math.round(2 * (w + h)),
    hitOk,
    hitDesc,
    zone: { x, y, width: Math.ceil(zone.r) - x, height: Math.ceil(zone.b) - y },
  };
};

/** Remove (on=true) or restore (on=false) the focus indicator, by inline `!important` style. */
const suppressIndicator = (on) => {
  const KEY = "__d3Suppressed";
  if (!on) {
    for (const [el, prop, value, prio] of window[KEY] ?? []) {
      if (value === "") el.style.removeProperty(prop);
      else el.style.setProperty(prop, value, prio);
    }
    window[KEY] = [];
    return;
  }
  const a = document.activeElement;
  const saved = [];
  const set = (el, prop, value) => {
    saved.push([el, prop, el.style.getPropertyValue(prop), el.style.getPropertyPriority(prop)]);
    el.style.setProperty(prop, value, "important");
  };
  for (let el = a; el !== null && el !== document.body; el = el.parentElement) {
    const cs = getComputedStyle(el);
    if (el === a) {
      set(el, "transition", "none");
      set(el, "box-shadow", "none");
    }
    if (cs.outlineStyle !== "none") {
      set(el, "transition", "none");
      set(el, "outline-style", "none");
    }
  }
  window[KEY] = saved;
};

/** Count the pixels whose colour changes by at least `floor`:1 between two same-size PNGs. */
const indicatorPixels = async ([focused, bare, floor]) => {
  const load = async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width;
    c.height = img.height;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(img, 0, 0);
    return g.getImageData(0, 0, c.width, c.height).data;
  };
  const A = await load(focused);
  const B = await load(bare);
  const lin = (v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const lum = (d, k) => 0.2126 * lin(d[k]) + 0.7152 * lin(d[k + 1]) + 0.0722 * lin(d[k + 2]);
  let n = 0;
  let best = 1;
  for (let k = 0; k < Math.min(A.length, B.length); k += 4) {
    if (A[k] === B[k] && A[k + 1] === B[k + 1] && A[k + 2] === B[k + 2]) continue;
    const la = lum(A, k);
    const lb = lum(B, k);
    const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    if (ratio > best) best = ratio;
    if (ratio >= floor) n += 1;
  }
  return { n, best: Math.round(best * 100) / 100 };
};

/* ── node-side plumbing ─────────────────────────────────────────────────────── */

const INDICATOR_CONTRAST = 3;

/**
 * Is the focused element SEEN? Hit test at the centre of its visible part, then count indicator
 * pixels at >= 3:1 against the same pixels unfocused. Records one visibility result for `stop`.
 */
async function checkVisible(page, stop, surface, scenario) {
  await page.keyboard.press("Shift");
  await page.waitForTimeout(50);
  const geo = await page.evaluate(focusGeometry);
  if (geo === null) return; /* nothing focused: the return check already records that */
  visChecked.set(stop, (visChecked.get(stop) ?? 0) + 1);
  const fail = (why) => {
    visResults.push({ stop, surface, scenario, ok: false, why: `${geo.desc}: ${why}` });
    console.log(`FAIL  ${surface} :: ${scenario} -> NOT VISIBLE [${stop}] ${geo.desc}: ${why}`);
  };
  if (!geo.visible) return fail(`no part of it is on screen (clipped by ${geo.clippers.join(" > ") || "the viewport"})`);
  if (!geo.hitOk) return fail(`elementFromPoint over its visible box ${JSON.stringify(geo.vis)}: ${geo.hitDesc}`);
  if (geo.zone.width < 1 || geo.zone.height < 1) return fail("its indicator region is off screen");
  const focused = await page.screenshot({ clip: geo.zone, animations: "disabled", caret: "hide" });
  await page.evaluate(suppressIndicator, true);
  let bare;
  try {
    bare = await page.screenshot({ clip: geo.zone, animations: "disabled", caret: "hide" });
  } finally {
    await page.evaluate(suppressIndicator, false);
  }
  const px = await page.evaluate(indicatorPixels, [focused.toString("base64"), bare.toString("base64"), INDICATOR_CONTRAST]);
  const floor = Math.ceil(geo.perimeter / 2);
  if (px.n < floor) {
    return fail(
      `${px.n} indicator pixel(s) at >=${INDICATOR_CONTRAST}:1 (floor ${floor}, half the perimeter of its visible box; ` +
        `strongest change ${px.best}:1; clipped by ${geo.clippers.join(" > ") || "nothing"})`,
    );
  }
  visResults.push({ stop, surface, scenario, ok: true, why: "" });
  console.log(`PASS  ${surface} :: ${scenario} -> VISIBLE [${stop}] ${geo.desc}: ${px.n} px at >=${INDICATOR_CONTRAST}:1 (floor ${floor})`);
}

async function settled(page) {
  await page.waitForTimeout(SETTLE_MS);
  return page.evaluate(describeActive);
}

/** Settle, record where focus returned, and check that the element it returned to is visible. */
async function landed(page, kind, surface, scenario) {
  const active = await settled(page);
  record(kind, surface, scenario, active);
  if (active.tag !== "BODY" && active.tag !== "NONE") await checkVisible(page, "returned", surface, scenario);
}

/** Close whatever was left open. The next case sets its own focus explicitly. */
async function reset(page) {
  for (let i = 0; i < 3; i += 1) await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
}

/** A locator for one discovered element, re-found after every state change. */
async function pick(page, sel, item) {
  const ok = await page.evaluate(markIn, [sel, item.ident, item.occurrence]);
  return ok ? page.locator("[data-d3-probe]").first() : null;
}

async function load(page, url) {
  await page.goto(url, { waitUntil: "load" });
  await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(2000);
}

/* ── page states, each re-entered idempotently before every case ──────────── */

async function ensureFinding(page) {
  const current = await page.locator('#rail-queue [role="row"][aria-current="true"]').count();
  if (current > 0) return true;
  const row = page.locator("#rail-queue .ag__row--data").first();
  if ((await row.count()) === 0) return false;
  await row.click();
  await page.waitForTimeout(500);
  return (await page.locator('#rail-queue [role="row"][aria-current="true"]').count()) > 0;
}

/** Returns "n/a" when the evidence rail is not on screen at this viewport (it is hidden, not
 *  unmounted, below the rail breakpoint): a state that does not exist is reported, not failed. */
/** At the drawer rung Rail B is a CLOSED overlay, not an absent one: open it (with `e`, from the grid
 *  cell, as a reader does) so the states that live in it are driven there too. Anywhere else a no-op. */
/*  Keyed on the drawer's STATE (`data-drawer`) at a width of the drawer rung (LADDER_REM), never on
 *  its computed visibility: a drawer still sliding shut is `visibility: visible` for its 240 ms step,
 *  and a visibility test read it as open and left it closing (independent verifier, 2026-09-26). */
async function ensureRailShown(page) {
  if (rungOf(page.viewportSize()?.width ?? 0) !== "drawer") return;
  const isOpen = () =>
    page.evaluate(() => {
      const rail = document.getElementById("rail-evidence");
      return (
        document.querySelector(".app")?.getAttribute("data-drawer") === "open" &&
        rail !== null &&
        !rail.hasAttribute("inert") &&
        getComputedStyle(rail).visibility === "visible"
      );
    });
  if (await isOpen()) return;
  const cell = page.locator('#rail-queue [role="grid"] [tabindex="0"]').first();
  if ((await cell.count()) > 0) await cell.focus();
  await page.keyboard.press("e");
  await page.waitForTimeout(400);
  if (!(await isOpen())) console.log(`INFO  ensureRailShown: e did not open the evidence drawer at ${page.viewportSize()?.width}px`);
}

async function ensureDeviceView(page) {
  if (!(await ensureFinding(page))) return false;
  await ensureRailShown(page);
  const radio = page.locator('#rail-evidence [role="radio"]', { hasText: /device/i }).first();
  if ((await radio.count()) === 0) return false;
  if (!(await radio.isVisible())) return "n/a";
  const tabs = page.locator('#rail-evidence [role="tablist"]');
  if ((await radio.getAttribute("aria-checked")) === "true" && (await tabs.count()) > 0) return true;
  /* The device view is empty until a device is chosen: pick the finding's own device from its
     evidence chain, as a reader does. */
  const back = page.locator('#rail-evidence [role="radio"]', { hasText: /finding/i }).first();
  if ((await back.getAttribute("aria-checked")) !== "true") {
    await back.click();
    await page.waitForTimeout(300);
  }
  /* The chain's buttons select a device OR a sibling finding; try them in order until the device
     view shows a device (its tablist mounts). */
  const devs = page.locator("#rail-evidence .ev-devbtn:visible");
  const n = Math.min(await devs.count(), 6);
  for (let i = 0; i < n; i += 1) {
    await devs.nth(i).click();
    await page.waitForTimeout(600);
    if ((await radio.getAttribute("aria-checked")) === "true" && (await tabs.count()) > 0) return true;
    await back.click();
    await page.waitForTimeout(300);
  }
  return false;
}

/* The Inspector counts as open only when it is ON SCREEN. Until 2026-09-24 this read "is #inspector in
   the DOM", and at 390 px with the fabric collapsed the Inspector mounts inside the display:none
   stage: in the DOM, never seen — measured, a citation's Enter left getClientRects() 0 and focus on
   the citation, and every "inspector" case there passed as "[still open]". */
const inspectorShown = (page) =>
  page.evaluate(() => {
    const i = document.getElementById("inspector");
    return i !== null && i.getClientRects().length > 0;
  });

async function ensureInspector(page) {
  if (await inspectorShown(page)) return true;
  if (!(await ensureFinding(page))) return false;
  const cell = page.locator('#rail-queue [role="grid"] [tabindex="0"]').first();
  if ((await cell.count()) === 0) return false;
  await cell.focus();
  await page.keyboard.press("i");
  await page.waitForTimeout(400);
  return inspectorShown(page);
}

/** The Inspector opened from a citation affordance — the path `openInspector` records an origin for. */
/*  The state is "the Inspector, opened from a citation that is still in the page". An Inspector left
 *  open by an earlier case is that state only while the citation it was opened from is still
 *  connected and on screen: MEASURED (this cluster, --vp=1152, 2026-09-26), the grid cases before
 *  it (ArrowDown selects another finding) re-rendered the evidence pane, the marked citation left the
 *  page, and the Inspector's close cases then measured the owner's fallback (#stage) under the name
 *  "inspector (citation)". So the citation is marked, and a drifted state is closed and re-entered. */
async function ensureInspectorFromCite(page) {
  const citeLive = () =>
    page.evaluate(() => {
      const c = document.querySelector("[data-d3-cite-origin]");
      return c !== null && c.isConnected && c.getClientRects().length > 0 && getComputedStyle(c).visibility === "visible";
    });
  if ((await inspectorShown(page)) && (await citeLive())) return true;
  if (await inspectorShown(page)) {
    const tab = page.locator('#inspector [role="tab"][aria-selected="true"]').first();
    if ((await tab.count()) > 0) {
      await tab.focus();
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
    }
  }
  if (!(await ensureFinding(page))) return false;
  await ensureRailShown(page);
  const cite = page.locator("#rail-evidence button.ui-cite:visible").first();
  if ((await cite.count()) === 0) return (await page.locator("#rail-evidence").isVisible()) ? false : "n/a";
  await page.evaluate(() => {
    for (const el of document.querySelectorAll("[data-d3-cite-origin]")) el.removeAttribute("data-d3-cite-origin");
  });
  await cite.evaluate((el) => el.setAttribute("data-d3-cite-origin", ""));
  await cite.focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);
  return inspectorShown(page);
}

const STATES = [
  ["idle", async () => true],
  ["finding", ensureFinding],
  ["device", ensureDeviceView],
  ["inspector (i)", ensureInspector],
  ["inspector (citation)", ensureInspectorFromCite],
];

/** Drive `fn` once per discovered element of `sel` (once per state: `seen` is cleared per state). */
async function eachSurface(page, kind, sel, where, enter, fn) {
  const items = await page.evaluate(listIn, sel);
  for (const item of items) {
    const id = `${kind}|${item.ident}|${item.occurrence}`;
    if (seenOf(page).has(id)) continue;
    seenOf(page).add(id);
    await fn(item, `${where} ${kind} "${item.name}"${item.occurrence > 0 ? ` #${item.occurrence + 1}` : ""}`, async () => {
      await reset(page);
      if ((await enter(page)) !== true) return null;
      return pick(page, sel, item);
    });
  }
}

/* ── popovers and menus ────────────────────────────────────────────────────── */
async function auditPopovers(page, where, enter) {
  const sel = "[aria-haspopup]:not([disabled])";
  await eachSurface(page, "popover", sel, where, enter, async (_item, name, fresh) => {
    for (const scenario of ["open → Escape", "open → Tab → Escape", "open → Tab out of the panel → Escape"]) {
      const t = await fresh();
      if (t === null) {
        notDriven(name, scenario, "trigger not found after re-entering the state");
        continue;
      }
      const before = await page.evaluate(visibleDialogs);
      await t.scrollIntoViewIfNeeded().catch(() => {});
      if (!(await focusOn(page, t, name, scenario))) continue;
      await page.keyboard.press("Enter");
      await page.waitForTimeout(250);
      const expanded = (await t.getAttribute("aria-expanded").catch(() => null)) === "true";
      if (!expanded && (await page.evaluate(visibleDialogs)) <= before) {
        notDriven(name, scenario, "Enter did not open it");
        continue;
      }
      /* Where the popover put focus as it opened: its first control, or the panel itself. */
      if (scenario === "open → Escape") await checkVisible(page, "popover initial focus", name, scenario);
      if (scenario === "open → Tab → Escape") {
        await page.keyboard.press("Tab");
        await page.waitForTimeout(100);
        await checkVisible(page, "popover after Tab", name, scenario);
      }
      if (scenario === "open → Tab out of the panel → Escape") {
        for (let i = 0; i < 40; i += 1) {
          if ((await t.getAttribute("aria-expanded").catch(() => null)) !== "true") break;
          await page.keyboard.press("Tab");
          await page.waitForTimeout(40);
        }
      }
      await page.keyboard.press("Escape");
      await landed(page, "popover", name, scenario);
    }
  });
}

/* ── dialogs bound to keys ─────────────────────────────────────────────────── */
async function auditDialogs(page, where) {
  const openers = [
    ["command palette (Ctrl+K)", "Control+k"],
    ["keyboard reference (?)", "Shift+Slash"],
  ];
  for (const [label, chord] of openers) {
    const name = `${where} dialog ${label}`;
    for (const scenario of ["open → Escape", "open → Tab → Escape"]) {
      await reset(page);
      /* Start from a real control so there is an invoker to return to, as a reader would. */
      const start = page.locator("#rail-queue [role='grid'] [tabindex='0']").first();
      if ((await start.count()) > 0) await start.focus();
      const before = await page.evaluate(visibleDialogs);
      await page.keyboard.press(chord);
      await page.waitForTimeout(300);
      if ((await page.evaluate(visibleDialogs)) <= before) {
        notDriven(name, scenario, `${chord} did not open it`);
        continue;
      }
      if (scenario.includes("Tab")) await page.keyboard.press("Tab");
      await page.waitForTimeout(100);
      await checkVisible(page, scenario.includes("Tab") ? "dialog after Tab" : "dialog initial focus", name, scenario);
      await page.keyboard.press("Escape");
      await landed(page, "dialog", name, scenario);
    }
  }
}

/* ── tablists: every tab, including the Inspector's ────────────────────────── */
async function auditTabs(page, where, enter) {
  await eachSurface(page, "tab", '[role="tab"]', where, enter, async (_item, name, fresh) => {
    /* Arrowing moves selection, so the panel the reader was in unmounts under them. */
    let tab = await fresh();
    if (tab === null) return notDriven(name, "tab → ArrowRight → Escape", "tab not found");
    if (!(await focusOn(page, tab, name, "tab → ArrowRight → Escape"))) return;
    await checkVisible(page, "tab", name, "tab → ArrowRight → Escape");
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(150);
    await checkVisible(page, "tab after arrow", name, "tab → ArrowRight → Escape");
    await page.keyboard.press("Escape");
    await landed(page, "tab", name, "tab → ArrowRight → Escape");

    /* The tab's PANEL, entered with Tab from its selected tab (APG: the panel is itself a tab stop,
       so the reader lands on the panel before anything in it). This is the stop the device pane's
       `.dp__body` scroller clipped whole. Every tab's panel is entered, not only the first. */
    tab = await fresh();
    if (tab === null) return notDriven(name, "tab → Tab into its panel", "tab not found");
    await tab.click();
    await page.waitForTimeout(250);
    const panelId = await tab.getAttribute("aria-controls");
    if (!(await focusOn(page, tab, name, "tab → Tab into its panel"))) return;
    await page.keyboard.press("Tab");
    await page.waitForTimeout(150);
    const intoPanel = panelId
      ? await page.evaluate((id) => {
          const p = document.getElementById(id);
          return p !== null && document.activeElement !== null && p.contains(document.activeElement);
        }, panelId)
      : false;
    if (intoPanel) await checkVisible(page, "tab panel", name, "tab → Tab into its panel");
    else if (panelId) {
      const panelFocusable = await page.evaluate((id) => document.getElementById(id)?.tabIndex === 0, panelId);
      if (panelFocusable) {
        visResults.push({ stop: "tab panel", surface: name, scenario: "tab → Tab into its panel", ok: false, why: "Tab from the selected tab did not enter its focusable panel" });
        console.log(`FAIL  ${name} :: tab → Tab into its panel -> NOT DRIVEN (Tab did not enter the panel)`);
      }
    }

    /* Focus INSIDE the tab's panel, then Escape: whatever Escape closes takes that panel with it. */
    tab = await fresh();
    if (tab === null) return notDriven(name, "panel control → Escape", "tab not found");
    await tab.click();
    await page.waitForTimeout(250);
    const inner = panelId
      ? page.locator(`[id="${panelId}"]`).locator("button:visible, input:visible, [tabindex='0']:visible, a[href]:visible").first()
      : null;
    if (inner === null || (await inner.count()) === 0) {
      console.log(`INFO  ${name} :: panel holds no focusable control; panel case not applicable`);
      return;
    }
    if (!(await focusOn(page, inner, name, "panel control → Escape"))) return;
    await checkVisible(page, "panel control", name, "panel control → Escape");
    await page.keyboard.press("Escape");
    await landed(page, "tab", name, "panel control → Escape");

    /* Every find bar the panel holds (the Inspector's JSON "Search this document" among them). */
    const fieldSel = 'input:not([type]), input[type="text"], input[type="search"], textarea';
    const t1 = await fresh();
    if (t1 !== null) {
      await t1.click();
      await page.waitForTimeout(250);
    }
    const fields = t1 !== null && panelId ? await page.locator(`[id="${panelId}"]`).locator(fieldSel).count() : 0;
    for (let k = 0; k < fields; k += 1) {
      for (const scenario of ["type → Enter → Escape", "type → Enter → Tab → Escape"]) {
        const t2 = await fresh();
        if (t2 === null) {
          notDriven(`${name} find bar #${k + 1}`, scenario, "tab not found");
          continue;
        }
        await t2.click();
        await page.waitForTimeout(200);
        const pid = await t2.getAttribute("aria-controls");
        const fb = page.locator(`[id="${pid}"]`).locator(fieldSel).nth(k);
        if ((await fb.count()) === 0 || !(await fb.isVisible())) {
          notDriven(`${name} find bar #${k + 1}`, scenario, "find bar not visible");
          continue;
        }
        const label = await fb.evaluate((el) => (el.getAttribute("aria-label") ?? el.labels?.[0]?.textContent ?? "input").trim());
        if (!(await focusOn(page, fb, `${name} find bar "${label}"`, scenario))) continue;
        await page.keyboard.type("up");
        await page.keyboard.press("Enter");
        if (scenario.includes("Tab")) await page.keyboard.press("Tab");
        await page.waitForTimeout(150);
        await checkVisible(page, scenario.includes("Tab") ? "find bar after Tab" : "find bar", `${name} find bar "${label}"`, scenario);
        await page.keyboard.press("Escape");
        await landed(page, "find bar", `${name} find bar "${label}"`, scenario);
      }
    }
  });
}

/* ── text fields and find bars ─────────────────────────────────────────────── */
async function auditFields(page, where, enter) {
  const outside = ':not([role="tabpanel"] *)';
  const sel = [`input:not([type])${outside}`, `input[type="text"]${outside}`, `input[type="search"]${outside}`, `textarea${outside}`].join(", ");
  await eachSurface(page, "field", sel, where, enter, async (_item, name, fresh) => {
    const kind = "field";
    for (const scenario of ["type → Escape", "type → Tab → Escape"]) {
      const f = await fresh();
      if (f === null) {
        notDriven(name, scenario, "field not found after re-entering the state");
        continue;
      }
      if (!(await focusOn(page, f, name, scenario))) continue;
      await page.keyboard.type("up");
      await page.keyboard.press("Enter");
      if (scenario.includes("Tab")) await page.keyboard.press("Tab");
      await page.waitForTimeout(150);
      await checkVisible(page, scenario.includes("Tab") ? "field after Tab" : "field", name, scenario);
      await page.keyboard.press("Escape");
      await landed(page, kind, name, scenario);
      /* Leave no filter behind for the next case. */
      const again = await fresh();
      if (again !== null) await again.fill("").catch(() => {});
    }
  });
}

/* ── grids ─────────────────────────────────────────────────────────────────── */
async function auditGrids(page, where, enter) {
  await eachSurface(page, "grid", '[role="grid"]', where, enter, async (_item, name, fresh) => {
    for (const scenario of ["cell → Escape", "cell → ArrowDown → Escape"]) {
      const g = await fresh();
      const cell = g?.locator('[tabindex="0"]').first();
      if (!cell || (await cell.count()) === 0) {
        notDriven(name, scenario, "no roving cell");
        continue;
      }
      if (!(await focusOn(page, cell, name, scenario))) continue;
      if (scenario.includes("ArrowDown")) await page.keyboard.press("ArrowDown");
      await page.waitForTimeout(150);
      await checkVisible(page, "grid cell", name, scenario);
      await page.keyboard.press("Escape");
      await landed(page, "grid", name, scenario);
    }
  });
}

/* ── the Inspector's own close paths ───────────────────────────────────────── */
async function auditInspectorClose(page, where, enter) {
  const name = `${where} inspector`;
  const cases = [
    ["close button → Enter", async (scenario) => {
      if (!(await focusOn(page, page.locator('#inspector button[aria-label="Close the inspector"]'), name, scenario))) return false;
      await checkVisible(page, "inspector control", name, "close button → Enter");
      await page.keyboard.press("Enter");
      return true;
    }],
    ["tab → i (toggles it closed from inside)", async (scenario) => {
      if (!(await focusOn(page, page.locator('#inspector [role="tab"][aria-selected="true"]'), name, scenario))) return false;
      await page.keyboard.press("i");
      return true;
    }],
    ["tab → Escape", async (scenario) => {
      if (!(await focusOn(page, page.locator('#inspector [role="tab"][aria-selected="true"]'), name, scenario))) return false;
      await page.keyboard.press("Escape");
      return true;
    }],
  ];
  for (const [scenario, act] of cases) {
    await reset(page);
    if ((await enter(page)) !== true) {
      notDriven(name, scenario, "the Inspector did not open");
      continue;
    }
    if (!(await act(scenario))) continue;
    const gone = (await page.locator("#inspector").count()) === 0;
    await landed(page, "inspector", `${name}${gone ? "" : " [still open]"}`, scenario);
  }
}

/* ── toasts ─────────────────────────────────────────────────────────────────── */
async function auditToasts(page, where) {
  /* A toast is a VISIBLE transient notice. A visually-hidden live region is an announcement. */
  const toasts = () =>
    [...document.querySelectorAll('[role="status"], [role="alert"], [aria-live], [data-toast], .toast')]
      .filter((el) => {
        const r = el.getBoundingClientRect();
        return r.width > 2 && r.height > 2 && (el.textContent ?? "").trim() !== "";
      })
      .map((el) => (el.textContent ?? "").trim().slice(0, 40));
  await reset(page);
  const before = new Set(await page.evaluate(toasts));
  const copy = page.locator('button[aria-label^="Copy"]:visible').first();
  if ((await copy.count()) === 0) {
    console.log(`INFO  ${where} toasts: no copy action on screen to provoke one`);
    return;
  }
  if (!(await focusOn(page, copy, `${where} copy action`, "copy → wait"))) return;
  await checkVisible(page, "copy action", `${where} copy action`, "copy → wait");
  await page.keyboard.press("Enter");
  await landed(page, "copy", `${where} copy action`, "copy → wait");
  const fresh = (await page.evaluate(toasts)).filter((t) => !before.has(t));
  console.log(`INFO  ${where} toasts: ${fresh.length} visible notice(s) appeared after a copy action`);
  for (const text of fresh) {
    const loc = page.getByText(text, { exact: false }).first();
    await loc.focus().catch(() => {});
    await checkVisible(page, "toast", `${where} toast "${text}"`, "focus → Escape");
    await page.keyboard.press("Escape");
    await landed(page, "toast", `${where} toast "${text}"`, "focus → Escape");
  }
}

/* ── self-removing controls (`--self-removing`) ────────────────────────────────
 * MEASURED (acceptance report, D3 overturned PASS to FAIL): the passes above open and close
 * surfaces; none of them pressed a control that takes ITSELF out of the page. 'Remove the Critical
 * severity filter', reached after 7 Tabs, Enter, 2.5 s: activeElement BODY, no :focus/:focus-visible
 * element at all — and the same for 'Remove the High severity filter', 'Clear scope', 'Deselect
 * device core1' and 'Stop investigating the flow …'. 390, 768 and the Inspector/evidence panes were
 * never checked.
 *
 * THE CLASS IS DISCOVERED BY DRIVING, NOT LISTED. The page is loaded with every kind of scope token
 * (query, two severities, a role, the uncollected-only restriction, a finding, a device, a link, a
 * flow). The tab order is walked ONCE with real Tab presses from the top of the document to record
 * every stop. Then, for every stop k, from that seeded page: Tab k+1 times from the top (the stop
 * reached must be the one recorded), press Enter — and, on a page of its own, Space — and read the page
 * one second later. A stop whose element is no longer in the document IS a self-removing control,
 * whatever it is called and whichever pane it lives in. For each of those, focus must have moved to
 * an element that is SEEN (the same hit test and >=3:1 indicator pixels as every other stop in this
 * file); and no press of any stop may leave focus on <body>. The page is reloaded before a press
 * only when the previous press changed it (the URL, the tab stops or the open dialogs differ from
 * the seeded page), which, with the six (width, key) sweeps on parallel pages, keeps ~100 stops x 2 keys x 3
 * widths inside one run. MEASURED 2026-09-23 on a host saturated by four other agents: 53 min with
 * three pages (pre-fix build, where every self-removing press forced a reload), 30 min with six
 * (fixed build: 574 presses, 154 self-removing cases, exit 0). Run it on its own, not inside the
 * default pass, whose own three widths already approach a 1500 s budget.
 *
 *   node review/audit-d3-focus.mjs --self-removing       # against ATLAS_URL, default :4181
 *
 * Exit 1 if any press landed on BODY, any successor was not visible, a recorded stop could not be
 * reached again, or a width found NO self-removing control at all (the seed then did not reach the
 * screen, and the pass proved nothing).
 */
const SR_VIEWPORTS = coverRungs(
  [
    [1440, 900, "desktop"],
    [768, 1024, "tablet"],
    [390, 844, "phone"],
  ],
  "self-removing pass",
);

const srSeedUrl = () => {
  const fabricJson = JSON.parse(readFileSync(new URL("../src/data/fabric.json", import.meta.url), "utf8"));
  const p = new URLSearchParams();
  p.set("s", "findings");
  p.set("q", "gateway");
  p.set("sev", "CH");
  p.set("role", "access");
  p.set("unc", "1");
  p.set("f", fabricJson.findings[0].id);
  p.set("d", "core1");
  if (fabricJson.links?.[0]?.id) p.set("l", fabricJson.links[0].id);
  p.set("flow", "10.0.10.50>10.0.30.10>tcp>3389");
  return `${APP}/?${p.toString()}`;
};

/**
 * The focused element's identity — its STRUCTURAL path (tag and child index from <body>), because a
 * name can be live: the status bar's scene readout reads "refining" and later "settled", and a
 * name-based identity failed to find that stop again after a reload. The name is carried for the
 * report only. Keeps a live handle to the element on `window.__srProbe`.
 */
const srIdentify = () => {
  const a = document.activeElement;
  window.__srProbe = a;
  if (a === null || a === document.body) return null;
  const path = [];
  for (let n = a; n !== null && n !== document.body; n = n.parentElement) {
    path.push(`${n.tagName}:${n.parentElement ? [...n.parentElement.children].indexOf(n) : 0}`);
  }
  const name = (a.getAttribute("aria-label") ?? (a.textContent ?? "")).trim().replace(/\s+/g, " ").slice(0, 60);
  return { path: path.reverse().join("/"), label: `${a.tagName}${a.getAttribute("role") ? `[${a.getAttribute("role")}]` : ""} "${name}"` };
};

/** What a reload would restore: the URL, the DOM-order tab stops and the open dialogs. */
const srSignature = () => {
  const sel = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable='true']";
  const stops = [...document.querySelectorAll(sel)]
    .filter((el) => el.tabIndex >= 0 && !el.disabled && el.getClientRects().length > 0 && el.closest("[inert]") === null)
    .map((el) => `${el.tagName}|${el.id}|${el.className}`);
  const dialogs = [...document.querySelectorAll("[role=dialog], [role=menu], [role=listbox], [role=alertdialog]")].filter(
    (el) => el.getClientRects().length > 0,
  ).length;
  return `${location.search}\n${dialogs}\n${stops.join("\n")}`;
};

/** Put the sequential-focus starting point back at the top of the document. */
const srToTop = () => {
  window.scrollTo(0, 0);
  /* A click-free way to reset the navigation starting point: a focusable probe at the very top. */
  let probe = document.getElementById("__sr-top");
  if (probe === null) {
    probe = document.createElement("span");
    probe.id = "__sr-top";
    probe.tabIndex = -1;
    document.body.prepend(probe);
  }
  probe.focus();
};

async function srLoad(page, url) {
  await page.goto(url, { waitUntil: "load" });
  await page.waitForSelector("#query-bar .ui-chip__remove", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
}

async function srAudit(browser, [w, h, vp], key) {
  const out = { vp: `${vp} [${key}]`, members: [], notDriven: [], pressed: 0 };
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
  /* Every load starts from the SAME page: a press that stores a per-reader preference (the fabric
     legend's open state, a column choice) must not change the tab order of every later load —
     MEASURED: Space on "Legend" left it stored open, and the next load's order no longer matched. */
  await ctx.addInitScript(() => {
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch {
      /* storage blocked: nothing persists anyway */
    }
  });
  const page = await ctx.newPage();
  const url = srSeedUrl();
  await srLoad(page, url);
  const seededSig = await page.evaluate(srSignature);
  /* One lap of real Tab presses from the top of the page records the order. */
  await page.evaluate(srToTop);
  const order = [];
  for (let i = 0; i < 300; i += 1) {
    await page.keyboard.press("Tab");
    const id = await page.evaluate(srIdentify);
    if (id === null) break;
    if (i > 0 && (await page.evaluate(() => window.__srFirst === window.__srProbe))) break;
    if (i === 0) await page.evaluate(() => (window.__srFirst = window.__srProbe));
    order.push(id);
  }
  console.log(`INFO  ${out.vp}: ${order.length} tab stops on the seeded page, walked by Tab`);
  let dirty = false;
  for (let k = 0; k < order.length; k += 1) {
    const name = `${vp} ${order[k].label} (stop ${k + 1})`;
    if (!dirty && (await page.evaluate(srSignature)) !== seededSig) dirty = true;
    let reached = false;
    for (let attempt = 0; attempt < 2 && !reached; attempt += 1) {
      if (dirty || attempt > 0) {
        await srLoad(page, url);
        dirty = false;
      }
      await page.evaluate(srToTop);
      for (let i = 0; i <= k; i += 1) await page.keyboard.press("Tab");
      reached = (await page.evaluate(srIdentify))?.path === order[k].path;
      if (!reached) dirty = true;
    }
    if (!reached) {
      out.notDriven.push(name);
      notDriven(name, `Tab x${k + 1} → ${key}`, "the recorded stop was not reached again by Tab");
      continue;
    }
    out.pressed += 1;
    await page.keyboard.press(key === "Space" ? " " : "Enter");
    const active = await settled(page);
    const removed = await page.evaluate(() => window.__srProbe instanceof Element && !window.__srProbe.isConnected);
    if (removed) out.members.push(order[k].label);
    if (!removed && active.tag !== "BODY" && active.tag !== "NONE") continue;
    dirty = true;
    record(removed ? "self-removing" : "activation", `${name}${removed ? " (removed itself)" : ""}`, `Tab x${k + 1} → ${key}`, active);
    if (active.tag !== "BODY" && active.tag !== "NONE") await checkVisible(page, "self-removing successor", name, `Tab x${k + 1} → ${key}`);
  }
  await ctx.close();
  return out;
}

async function runSelfRemoving() {
  const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  let outs;
  try {
    /* One page per width AND key: most of a case is waiting (the load, the one-second settle), so
       six pages in parallel keep the pass near the time of one. */
    outs = await Promise.all(SR_VIEWPORTS.flatMap((v) => ["Enter", "Space"].map((key) => srAudit(browser, v, key))));
  } finally {
    await browser.close();
  }
  console.log("");
  for (const o of outs) console.log(`${o.vp}: ${o.pressed} press(es); ${o.members.length} self-removing: ${o.members.join("; ") || "NONE"}`);
  const failed = results.filter((r) => !r.ok);
  const visFailed = visResults.filter((r) => !r.ok);
  const empty = outs.filter((o) => o.members.length === 0).map((o) => o.vp);
  console.log(`\n${results.length} self-removing/BODY case(s), ${failed.length} failed.`);
  for (const f of failed) console.log(`  FAIL ${f.surface} :: ${f.scenario} (${f.why})`);
  console.log(`${visResults.length} successor(s) checked for visibility, ${visFailed.length} not visible.`);
  for (const f of visFailed) console.log(`  NOT VISIBLE [${f.stop}] ${f.surface} :: ${f.scenario} (${f.why})`);
  if (empty.length > 0) console.log(`NO SELF-REMOVING CONTROL FOUND at ${empty.join(", ")}: the seed did not reach the screen.`);
  process.exit(failed.length === 0 && visFailed.length === 0 && empty.length === 0 ? 0 : 1);
}

if (process.argv.includes("--self-removing")) await runSelfRemoving();

/* ── the sweep (`--sweep` alone; also the first phase of the default run) ───────
 * TWO CLASSES the passes above could not see, both measured by the acceptance review 2026-09-24:
 *
 *  1. A COMPOSITE WIDGET WITH NO TAB STOP (D1, overturned PASS -> FAIL). At 768 px on the Path
 *     surface the "Which panel to show" radiogroup held Queue and Evidence, both `tabindex="-1"`:
 *     "paneswitch focused during 60 Tabs: 0". So at every width in SWEEP_VIEWPORTS and in every
 *     state in sweepStates(), EVERY rendered element whose role is a composite widget — whatever
 *     component drew it — is enumerated, and must hold exactly one sequential-focus stop (zero when a
 *     combobox drives it through aria-activedescendant). And the keyboard journey the review named,
 *     More -> Path, is driven with real keys, after which Tab (and Shift+Tab) must reach the radios.
 *
 *  2. A FOCUSED ELEMENT ANOTHER LAYER PAINTS OVER (D3). At 390x844 `?d=core1&s=fabric` the status
 *     bar's coverage buttons, reached by Tab, sat inside the viewport while `.rail--b` painted over
 *     them: elementFromPoint gave `LI.dp-list__row` at 9 of 9 points, 0 of 4,400 ring pixels changed.
 *     This file said "0 not visible": it never drove 390, sampled one point, and never scrolled. So
 *     the WHOLE tab order is walked with real Tab presses, and every stop is hit-tested at nine
 *     points (focusGeometry) where Tab left the page, then with the document scrolled to its END and
 *     to its TOP (a sticky layer is only covered at some scroll offsets: the review's case appears at
 *     10537 and not at 2000, 6000 or the end). A stop scrolled out of view is not judged at that offset.
 *
 * The hit test is the class check here; the >=3:1 ring-pixel measurement stays with the surface
 * passes above, which run it on every stop they reach.
 */
const SWEEP_VIEWPORTS = coverRungs(
  [
    [390, 844, "phone"],
    [768, 1024, "tablet"],
    [1000, 800, "compact"],
    [1440, 900, "desktop"],
    [1920, 1080, "wide"],
  ],
  "sweep",
);

/** Keyboard-only, as the refuter drove it: frame the fabric, zoom in, then pan (Alt+arrow) until a
 *  finding pointer is drawn. Leaves the page as it stands; returns whether one showed. */
async function panUntilOffViewPointer(page) {
  const shown = () => page.evaluate(() => document.querySelectorAll('[data-pointer-for][data-visible="true"]').length > 0);
  /* Below the stacked breakpoint the fabric is off until the reader turns it on (App.tsx,
     `fabricOptional`): turn it on the way a keyboard reader does, so the phone rung reaches this
     state instead of leaving `offViewPointers` unexercised on a narrowed run. */
  const turnOn = page.locator('.paneswitch__fabric[aria-pressed="false"]').first();
  if ((await page.locator(".fabric3d__canvas").count()) === 0 && (await turnOn.count()) > 0 && (await turnOn.isVisible())) {
    await turnOn.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.querySelector(".fabric3d__canvas") !== null, null, { timeout: 30000 }).catch(() => {});
  }
  const canvas = page.locator(".fabric3d__canvas").first();
  if ((await canvas.count()) === 0 || !(await canvas.isVisible())) return false;
  await page.waitForFunction(() => document.querySelector(".fabric3d__canvas") !== null, null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  if (await shown()) return true;
  for (const mv of ["Alt+ArrowLeft", "Alt+ArrowRight", "Alt+ArrowUp", "Alt+ArrowDown"]) {
    await canvas.focus();
    await page.keyboard.press("Home");
    await page.waitForTimeout(900);
    for (let k = 0; k < 5; k += 1) await page.keyboard.press("+");
    for (let n = 0; n < 25; n += 1) {
      await page.keyboard.press(mv);
      await page.waitForTimeout(250);
      if (await shown()) {
        await page.waitForTimeout(800);
        return true;
      }
    }
  }
  return false;
}

const sweepStates = () => {
  const fabricJson = JSON.parse(readFileSync(new URL("../src/data/fabric.json", import.meta.url), "utf8"));
  const flow = encodeURIComponent("10.0.10.50>10.0.30.10>tcp>3389");
  return [
    ["idle", ""],
    ["path surface, no flow", "s=path"],
    ["findings surface", "s=findings"],
    ["evidence surface", "s=evidence"],
    ["a device selected", "d=core1&s=fabric"],
    ["a finding selected", `f=${encodeURIComponent(fabricJson.findings[0].id)}&s=findings`],
    ["a traced flow", `s=path&flow=${flow}`],
    /* The acceptance review's D1/D5 subject: the off-view finding pointer, which is drawn only while
       a selected finding's host projects outside the canvas. The refuter's route (ptr3.mjs): F094,
       which names only access5, then the camera panned with the keyboard until the pointer shows.
       Pinned by id because which host leaves the view is a camera fact no data file states;
       `offViewPointers` fails the run if no width ever drew one, so the state can never pass by
       quietly not reaching its subject. */
    ["a finding naming an off-view host", "f=F094", panUntilOffViewPointer],
  ];
};

/** In-page: every rendered composite widget and its sequential-focus stops. */
const compositeCensus = () => {
  const ROLES = ["radiogroup", "tablist", "toolbar", "grid", "treegrid", "tree", "listbox", "menu", "menubar"];
  const shown = (el) =>
    el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden" && el.closest("[inert], [aria-hidden='true']") === null;
  const out = [];
  for (const w of document.querySelectorAll(ROLES.map((r) => `[role="${r}"]`).join(","))) {
    if (!shown(w)) continue;
    const stops = [w, ...w.querySelectorAll("*")].filter((el) => el.tabIndex >= 0 && !el.disabled && shown(el));
    const owned =
      w.id !== "" &&
      [...document.querySelectorAll("[aria-controls]")].some(
        (el) => (el.getAttribute("aria-controls") ?? "").split(/\s+/).includes(w.id) && (el.getAttribute("role") === "combobox" || el.hasAttribute("aria-activedescendant")),
      );
    out.push({
      name: `${w.getAttribute("role")} "${w.getAttribute("aria-label") ?? w.id ?? ""}"`,
      want: owned ? 0 : 1,
      stops: stops.map((s) => `${s.tagName}${s.getAttribute("role") ? `[${s.getAttribute("role")}]` : ""} "${(s.getAttribute("aria-label") ?? s.textContent ?? "").trim().slice(0, 24)}"`),
      items: w.querySelectorAll("*").length,
    });
  }
  return out;
};

/**
 * In-page: THE OPERABLE-ELEMENT CENSUS (acceptance D1 and D5, repair wave 6).
 *
 * MEASURED (acceptance report, D1 and D5 overturned PASS -> FAIL at 78bdba5): the off-view finding
 * pointer was a `<span onClick>` — no role, no tabindex, inside an `aria-hidden` layer. A click at
 * its centre framed access5; a 250-stop Tab walk never reached it; it measured 141.23 x 16.84. Every
 * census in this file selected elements by ROLE or by being a TAB STOP, so the one control that was
 * neither was invisible to all of them, and the sweep's "every stop hit-tested" was true of a set
 * that could not contain it.
 *
 * So this census finds a control by what it DOES, whatever its role or tabindex:
 *   - a pointer handler React attached to it (onClick, onPointerDown, onMouseDown, onPointerUp,
 *     onMouseUp, onDoubleClick — read from the element's React props), or
 *   - an OPERABLE cursor that starts on it (its computed cursor is not an inert value and differs
 *     from its parent's: a child inheriting its button's `pointer` is the same target).
 * Rendered ones only (a box, not `visibility: hidden`, not `pointer-events: none`, not inert). Each
 * must be
 *   REACHABLE: itself a stop of the real Tab walk just made (`tabbed`), or containing one (a row
 *     whose cells take focus), or inside one, or inside a composite widget (grid, tree, toolbar, …)
 *     one of whose items took Tab focus — the APG roving-focus contract, where arrows reach the rest;
 *   EXPOSED: not inside an `aria-hidden="true"` subtree — an operable control assistive technology
 *     is told does not exist;
 *   and at least 24 x 24 CSS px by getBoundingClientRect (acceptance D5, WCAG 2.5.8). An element may
 *     carry `data-target-exempt="<the reason>"`; that is printed with its reason and counted, never
 *     passed silently. None does today.
 */
const operableCensus = () => {
  const INERT = new Set(["default", "auto", "text", "vertical-text", "not-allowed", "no-drop", "wait", "progress", "help", "none"]);
  const HANDLERS = ["onClick", "onPointerDown", "onMouseDown", "onPointerUp", "onMouseUp", "onDoubleClick"];
  const COMPOSITE = '[role="grid"], [role="treegrid"], [role="tree"], [role="toolbar"], [role="tablist"], [role="radiogroup"], [role="listbox"], [role="menu"], [role="menubar"]';
  const tabbed = window.__tabbed instanceof Set ? window.__tabbed : new Set();
  const reactHandlers = (el) => {
    const key = Object.keys(el).find((k) => k.startsWith("__reactProps"));
    if (key === undefined) return [];
    const props = el[key] ?? {};
    return HANDLERS.filter((h) => typeof props[h] === "function");
  };
  const describe = (el) => {
    const name = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
    const cls = typeof el.className === "string" ? el.className.split(" ")[0] : "";
    return `${el.tagName}${el.id ? `#${el.id}` : ""}${cls ? `.${cls}` : ""}${el.getAttribute("role") ? `[${el.getAttribute("role")}]` : ""} "${name}"`;
  };
  const out = [];
  for (const el of document.body.querySelectorAll("*")) {
    if (el.id === "__sr-top") continue;
    const cs = getComputedStyle(el);
    const handlers = reactHandlers(el);
    const parentCursor = el.parentElement ? getComputedStyle(el.parentElement).cursor : "auto";
    const cursorStarts = !INERT.has(cs.cursor) && cs.cursor !== parentCursor;
    if (handlers.length === 0 && !cursorStarts) continue;
    if (el.getClientRects().length === 0 || cs.visibility === "hidden" || cs.pointerEvents === "none" || el.closest("[inert]") !== null) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    /* A target is what a pointer can land on NOW: nine points of its box inside the viewport, and at
       least one must hit it (or a descendant). None does for a visually-hidden element (the fabric
       tree's clip recipe), one scrolled out of its scroller, or one wholly covered — those are
       counted, not judged. One partly covered IS judged: a pointer still lands on it. */
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    let hits = 0;
    for (const fy of [0.15, 0.5, 0.85]) {
      for (const fx of [0.15, 0.5, 0.85]) {
        const x = r.left + fx * r.width;
        const y = r.top + fy * r.height;
        if (x < 0 || y < 0 || x >= vw || y >= vh) continue;
        const at = document.elementFromPoint(x, y);
        if (at !== null && (at === el || el.contains(at))) hits += 1;
      }
    }
    if (hits === 0) {
      window.__censusUnhittable = (window.__censusUnhittable ?? 0) + 1;
      continue;
    }
    /* THE TARGET A CLICK REACHES. A click bubbles: on a region that is not a control of its own (a
       grid cell, a tree row's text) it also reaches the nearest ancestor with a click handler of its
       own, and that ancestor's box is where the pointer lands to get that action — DataGrid hangs the
       row's activation on the ROW for exactly this reason ("what looks clickable is clickable"). A
       distinct control (a native one, or a control role) is always its own target and is judged by
       its own box. */
    const CONTROL_ROLES = /^(button|link|checkbox|switch|menuitem|menuitemcheckbox|menuitemradio|option|tab|radio|slider|spinbutton|textbox|combobox|searchbox)$/;
    const distinct = /^(BUTTON|A|INPUT|SELECT|TEXTAREA|SUMMARY)$/.test(el.tagName) || CONTROL_ROLES.test(el.getAttribute("role") ?? "");
    let box = { w: r.width, h: r.height, via: "" };
    if (!distinct) {
      for (let a = el.parentElement; a !== null && a !== document.body; a = a.parentElement) {
        if (!reactHandlers(a).includes("onClick")) continue;
        const ar = a.getBoundingClientRect();
        if (ar.width >= box.w && ar.height >= box.h) box = { w: ar.width, h: ar.height, via: describe(a) };
        break;
      }
    }
    let reach = null;
    if (tabbed.has(el)) reach = "a Tab stop";
    else if ([...tabbed].some((t) => el.contains(t))) reach = "contains a Tab stop";
    else if ([...tabbed].some((t) => t.contains(el))) reach = "inside a Tab stop";
    else {
      const widget = el.closest(COMPOSITE);
      if (widget !== null && [...tabbed].some((t) => widget.contains(t))) reach = `inside ${widget.getAttribute("role")} whose item took Tab`;
    }
    out.push({
      desc: describe(el),
      by: handlers.length > 0 ? handlers.join("+") : `cursor: ${cs.cursor}`,
      roleless: el.getAttribute("role") === null && !el.hasAttribute("tabindex") && !/^(BUTTON|A|INPUT|SELECT|TEXTAREA|SUMMARY)$/.test(el.tagName),
      reach,
      ariaHidden: el.closest('[aria-hidden="true"]') !== null,
      w: Math.round(box.w * 100) / 100,
      h: Math.round(box.h * 100) / 100,
      via: box.via,
      exempt: el.getAttribute("data-target-exempt"),
    });
  }
  return out;
};

/** In-page: let every FINITE animation and transition finish (a skip link sliding away is judged
 *  where it comes to rest, not mid-flight), then two frames. Infinite ones (a progress shimmer)
 *  are not waited for. Capped at 1.5 s. */
const settleAnimations = async () => {
  const finite = document.getAnimations().filter((a) => {
    const end = a.effect?.getComputedTiming().endTime;
    return typeof end === "number" && Number.isFinite(end);
  });
  await Promise.race([Promise.all(finite.map((a) => a.finished.catch(() => {}))), new Promise((r) => setTimeout(r, 1500))]);
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
};

/** In-page: is the focused element inside a layer that stays on screen while the document scrolls? */
const focusInPinnedLayer = () => {
  for (let el = document.activeElement; el !== null && el !== document.documentElement; el = el.parentElement) {
    const p = getComputedStyle(el).position;
    if (p === "sticky" || p === "fixed") return true;
  }
  return false;
};

/** In-page: scroll the document to `y` and let sticky layout and scroll listeners settle. */
const scrollDocTo = async (y) => {
  window.scrollTo(0, y);
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  return Math.round(window.scrollY);
};

/** @type {{where: string, what: string}[]} */
const sweepFails = [];
const sweepCount = { widgets: 0, stops: 0, hitTests: 0, journeys: 0, operable: 0, operableRoleless: 0, offViewPointers: 0 };
const sweepFail = (where, what) => {
  sweepFails.push({ where, what });
  console.log(`FAIL  ${where} :: ${what}`);
};

async function sweepState(page, vp, state, query, prep) {
  const where = `${vp}/${state}`;
  await page.goto(`${APP}/${query === "" ? "" : `?${query}`}`, { waitUntil: "load" });
  await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  if (prep !== undefined) console.log(`INFO  ${where}: ${(await prep(page)) ? "state reached" : "state NOT reached at this width"}`);

  for (const w of await page.evaluate(compositeCensus)) {
    sweepCount.widgets += 1;
    if (w.stops.length !== w.want) sweepFail(where, `${w.name}: ${w.stops.length} tab stop(s), expected ${w.want}${w.stops.length ? ` — ${w.stops.join(", ")}` : ""}`);
  }

  await page.evaluate(srToTop);
  /* Every element the real Tab walk lands on, kept live for the operable-element census below. */
  await page.evaluate(() => (window.__tabbed = new Set()));
  const seenStops = new Set();
  let lapClosed = false;
  for (let i = 0; i < 400; i += 1) {
    await page.keyboard.press("Tab");
    const id = await page.evaluate(srIdentify);
    if (id === null) continue; /* focus left the document for the browser chrome; the next Tab re-enters */
    if (seenStops.has(id.path)) {
      lapClosed = true;
      break;
    }
    seenStops.add(id.path);
    await page.evaluate(() => window.__tabbed.add(document.activeElement));
    sweepCount.stops += 1;
    await page.evaluate(settleAnimations);
    /* Where Tab left the page: the state SC 2.4.11 is about ("when a component receives focus"). */
    const natural = await page.evaluate(() => Math.round(window.scrollY));
    const offsets = [["as Tab left it", natural]];
    /* A stop in a sticky or fixed layer stays on screen while the document moves under it, so it is
       judged across the whole scroll range too: the review's case is covered at 10537 and clear at
       the very end. Nine offsets (0, 1/8 ... 8/8 of the range); the reader's position is restored
       after, so the next Tab starts where the last one really left the page. */
    if (await page.evaluate(focusInPinnedLayer)) {
      const max = await page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight);
      if (max > 0) for (let k = 0; k <= 8; k += 1) offsets.push([`${k}/8 of the scroll range`, Math.round((max * k) / 8)]);
    }
    for (const [at, target] of offsets) {
      const y = at === "as Tab left it" ? natural : await page.evaluate(scrollDocTo, target);
      const geo = await page.evaluate(focusGeometry);
      if (geo === null || !geo.visible) continue; /* scrolled out of view at this offset: not judged here */
      sweepCount.hitTests += 1;
      if (!geo.hitOk) sweepFail(where, `${id.label} (stop ${seenStops.size}) painted over, document at y=${y} (${at}): ${geo.hitDesc}`);
    }
    if (offsets.length > 1) await page.evaluate(scrollDocTo, natural);
  }

  /* THE OPERABLE-ELEMENT CENSUS, against the lap just walked. A lap that never came back to its
     first stop is not the whole tab order, and "not reached" would then be a guess. */
  if (!lapClosed) return sweepFail(where, "the Tab walk never closed its lap in 400 presses: the operable census cannot judge reach");
  await page.evaluate(srToTop);
  for (const c of await page.evaluate(operableCensus)) {
    sweepCount.operable += 1;
    if (c.roleless) sweepCount.operableRoleless += 1;
    if (c.exempt !== null) console.log(`INFO  ${where} :: ${c.desc} [${c.by}] ${c.w}x${c.h} EXEMPT: ${c.exempt}`);
    if (c.reach === null) sweepFail(where, `${c.desc} [${c.by}] is operable and no Tab stop reaches it (${c.roleless ? "no role, no tabindex" : "not in the tab order"})`);
    if (c.ariaHidden) sweepFail(where, `${c.desc} [${c.by}] is operable inside an aria-hidden subtree`);
    if (c.exempt === null && (c.w < 24 || c.h < 24)) {
      sweepFail(where, `${c.desc} [${c.by}] measures ${c.w}x${c.h} CSS px${c.via ? ` (its click reaches ${c.via})` : ""}, under 24x24 with no stated exemption`);
    }
  }
  /* A state named for a subject must have put it on screen, or it proved nothing about it. */
  const pointers = await page.evaluate(() => document.querySelectorAll('[data-pointer-for][data-visible="true"]').length);
  if (pointers > 0) sweepCount.offViewPointers += pointers;
}

/** More -> Path with real keys, then Tab / Shift+Tab must reach the pane switch's radios. */
async function sweepJourney(page, vp) {
  const where = `${vp}/journey More -> Path`;
  await page.goto(`${APP}/`, { waitUntil: "load" });
  await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const more = page.locator("button.hdr-more");
  if ((await more.count()) === 0 || !(await more.isVisible())) return; /* no More control at this width */
  const radiosShown = async () => page.locator('[role="radiogroup"][aria-label="Which panel to show"]').isVisible().catch(() => false);
  sweepCount.journeys += 1;
  await page.evaluate(srToTop);
  let onMore = false;
  for (let i = 0; i < 40 && !onMore; i += 1) {
    await page.keyboard.press("Tab");
    onMore = await page.evaluate(() => document.activeElement?.classList.contains("hdr-more") === true);
  }
  if (!onMore) return sweepFail(where, "Tab never reached the More control");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(300);
  const isPath = () => page.evaluate(() => (document.activeElement?.textContent ?? "").trim().startsWith("Path"));
  /* Inside the popover the surface controls are a toolbar (one tab stop, arrows inside): Tab until
     focus is in it, then arrow along it, as a keyboard reader does. */
  for (let i = 0; i < 16 && !(await isPath()); i += 1) {
    const inToolbar = await page.evaluate(() => document.activeElement?.closest('[role="toolbar"]') != null);
    await page.keyboard.press(inToolbar ? "ArrowRight" : "Tab");
    await page.waitForTimeout(60);
  }
  if (!(await isPath())) return sweepFail(where, "the Path control was not reached with Tab/arrows inside More");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(600);
  if (!/[?&]s=path\b/.test(page.url())) return sweepFail(where, `Enter on Path did not select the path surface (url ${page.url()})`);
  if (!(await radiosShown())) return; /* stacked rung: every rail is on screen and there is no switch to reach */
  for (const [key, label] of [["Tab", "Tab"], ["Shift+Tab", "Shift+Tab"]]) {
    let hits = 0;
    for (let i = 0; i < 60; i += 1) {
      await page.keyboard.press(key);
      if (await page.evaluate(() => document.activeElement?.closest(".paneswitch__group") != null)) hits += 1;
    }
    console.log(`${hits > 0 ? "PASS" : "FAIL"}  ${where} :: pane switch focused during 60 ${label}s: ${hits}`);
    if (hits === 0) sweepFail(where, `pane switch focused during 60 ${label}s: 0`);
  }
}

/* ── the evidence drawer (part of --sweep, and so of the default run) ───────────
 * MEASURED (acceptance report D3, overturned PASS -> FAIL, 2026-09-26): at 1100, 1024 and 1270 px Rail
 * B is an overlay drawer. With focus on its "Finding" radio, `e` and the palette's "Toggle the
 * evidence rail" closed it and Chromium parked focus on <body> when the delayed 240 ms `visibility`
 * step landed; Escape did not close it at all; a resize to 900 px lost focus the same way; and `g e`
 * with the drawer closed announced "Moved to the evidence rail." while focus stayed put. This file
 * had no drawer case: it never drove a width in that rung, and its surface discovery (`aria-haspopup`
 * triggers, a two-key dialog list) cannot see a surface with no trigger element.
 *
 * So, at every width DRAWER_WIDTHS derives from LADDER_REM, and from a real control (the findings
 * grid's roving cell, marked as the INVOKER):
 *   OPENERS  `e`, the palette's "Toggle the evidence rail", `v` (a finding is selected), and `g e`;
 *   CLOSES   `e`, the palette's toggle, and Escape (pressed again while an inner layer — the
 *            configuration overlay — closes first; at most three presses),
 * each close made with focus INSIDE the drawer, reached by real Tab presses. A case is NOT DRIVEN
 * unless the drawer really opened (`data-drawer="open"` and the rail's computed visibility
 * "visible"). After SETTLE_MS (longer than the 240 ms step) it FAILS when focus is on <body>, still
 * inside the closed rail, or anywhere but the invoker while the invoker is still in the page; the
 * element it returned to is then checked for VISIBILITY like every other stop in this file. `g e`
 * must announce "Moved to" exactly when focus is inside the rail.
 *   MOTION   every opener with the Escape close, and both re-entry shapes, again under
 *            prefers-reduced-motion: reduce; and `v` must have moved focus INTO the drawer.
 *   REENTRY  open with `e`, Tab inside, close with `e`, then at once Tab seven times, or focus() a
 *            control inside the rail, while it is still sliding shut: focus must end neither on
 *            <body> nor inside the closed rail.
 *   RESIZE   open with `e`, Tab inside, resize to a width in every OTHER rung (the sweep's widths):
 *            focus must not be on <body>, nor inside the rail where the rail is no longer shown, and
 *            must be visible; back at the drawer width the drawer must be CLOSED (its state does not
 *            outlive its rung).
 * `--vp=` narrows it like everything else: open/close cases run at a listed drawer width; a resize
 * case runs when its start or its end width is listed (so `--vp=390` drives the resizes to 390).
 */
const DRAWER_OPENERS = ["e", "palette", "v", "g e"];
const DRAWER_CLOSES = ["e", "palette", "Escape"];
const PALETTE_TOGGLE = "Toggle the evidence rail";

/** In-page: the drawer's rendered state and where focus is, relative to the rail and the invoker. */
const drawerState = () => {
  const app = document.querySelector(".app");
  const rail = document.getElementById("rail-evidence");
  const a = document.activeElement;
  const cs = rail ? getComputedStyle(rail) : null;
  const railShown = rail !== null && rail.getClientRects().length > 0 && cs.visibility === "visible";
  const inv = document.querySelector("[data-d3-invoker]");
  const name = a && a !== document.body ? (a.getAttribute("aria-label") ?? (a.textContent ?? "")).trim().replace(/\s+/g, " ").slice(0, 40) : "";
  return {
    drawer: app?.getAttribute("data-drawer") ?? null,
    railShown,
    body: a === null || a === document.body,
    inRail: rail !== null && a !== null && rail.contains(a),
    onInvoker: inv !== null && a === inv,
    invokerConnected: inv !== null && inv.isConnected,
    desc: a === null ? "null" : a === document.body ? "BODY (nothing focused)" : `${a.tagName}${a.id ? `#${a.id}` : ""} "${name}"`,
    status: (document.getElementById("sr-status")?.textContent ?? "").replace(/​/g, ""),
  };
};

const drawerCount = { cases: 0 };
function drawerResult(where, scenario, ok, why) {
  results.push({ surface: where, scenario, ok, why: ok ? "" : why });
  driven.set("drawer", (driven.get("drawer") ?? 0) + 1);
  drawerCount.cases += 1;
  /* A failure is printed once, by sweepFail, and counted in the sweep's verdict. */
  if (ok) console.log(`PASS  ${where} :: ${scenario}`);
  else sweepFail(where, `${scenario}: ${why}`);
}
/** checkVisible, with its verdict carried into the sweep's. */
async function drawerVisible(page, stop, where, scenario) {
  const before = visResults.filter((r) => !r.ok).length;
  await checkVisible(page, stop, where, scenario);
  const failed = visResults.filter((r) => !r.ok).slice(before);
  for (const f of failed) sweepFail(where, `${scenario}: focus NOT VISIBLE [${stop}] ${f.why}`);
}

async function drawerLoad(page) {
  const fabricJson = JSON.parse(readFileSync(new URL("../src/data/fabric.json", import.meta.url), "utf8"));
  await page.goto(`${APP}/?s=findings&f=${encodeURIComponent(fabricJson.findings[0].id)}`, { waitUntil: "load" });
  await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1200);
  const cell = page.locator("#rail-queue [role='grid'] [tabindex='0']").first();
  if ((await cell.count()) === 0) return false;
  await cell.focus();
  await page.evaluate(() => {
    for (const el of document.querySelectorAll("[data-d3-invoker]")) el.removeAttribute("data-d3-invoker");
    document.activeElement?.setAttribute("data-d3-invoker", "");
  });
  await page.keyboard.press("Shift");
  return true;
}

/** Run the palette's evidence toggle. Returns false when the palette did not offer it on top. */
/* Waits on the palette's STATE, not on fixed 300 ms sleeps: MEASURED (R5 repair, default run on a busy
   host, twice, at 1024 and at 1270 reduced-motion) the case went NOT DRIVEN while the concurrent --sweep
   of the same build drove it — typed before the combobox held focus, or read before the ranking had
   re-rendered. The palette still has to rank the evidence toggle first, within 5 s, or the case is NOT
   DRIVEN exactly as before. */
/** Per page (the drawer pass drives six pages at once — a module-wide record was read by one page after
 *  another page's toggle had overwritten it): the palette's last top row, and what its search box held as
 *  it took focus when that was not empty (a reopened stale query). */
const paletteRead = new WeakMap();
/** Why the page's last paletteToggle did not run the toggle: a PALETTE DEFECT (a failure) or the harness's NOT DRIVEN. */
const paletteMiss = (page) => {
  const { top = "", stale = null } = paletteRead.get(page) ?? {};
  return stale !== null
    ? `PALETTE DEFECT: the palette opened holding a query from an earlier opening ("${stale.slice(0, 60)}"), so what a reader types is appended to it (independent verifier R5-V2-2)`
    : `NOT DRIVEN: the palette's top row was not the evidence toggle (it read "${top.slice(0, 60)}")`;
};
async function paletteToggle(page) {
  paletteRead.set(page, { top: "", stale: null });
  /* The previous palette (open by palette -> close by palette) must be gone first: MEASURED (R5 repair,
     default run) mod+k pressed while it was still closing read an empty top row ("it read \"\""). */
  await page
    .waitForFunction(() => ![...document.querySelectorAll('[aria-modal="true"]')].some((d) => d.getClientRects().length > 0), null, { timeout: 5000 })
    .catch(() => {});
  await page.keyboard.press("Control+k");
  await page
    .waitForFunction(() => document.activeElement?.getAttribute("role") === "combobox" && document.activeElement.closest('[role="dialog"]') !== null, null, { timeout: 5000 })
    .catch(() => {});
  /* The box must be EMPTY as it takes focus (independent verifier R5-V2-2): a query left from the previous
     opening doubled what was typed here, nothing matched, and the case read as NOT DRIVEN — a palette defect
     reported as the harness's. It is reported as what it is, never cleared silently. */
  const held = await page.evaluate(() => {
    const a = document.activeElement;
    return a instanceof HTMLInputElement && a.getAttribute("role") === "combobox" ? a.value : "";
  });
  if (held !== "") {
    paletteRead.set(page, { top: "", stale: held });
    await page.keyboard.press("Escape");
    return false;
  }
  await page.keyboard.type(PALETTE_TOGGLE);
  const readTop = () =>
    page.evaluate(() => {
      const input = document.querySelector('[role="dialog"] [role="combobox"]');
      const id = input?.getAttribute("aria-activedescendant");
      return (id ? document.getElementById(id)?.textContent : "") ?? "";
    });
  await page
    .waitForFunction(
      (want) => {
        const input = document.querySelector('[role="dialog"] [role="combobox"]');
        const id = input?.getAttribute("aria-activedescendant");
        return ((id ? document.getElementById(id)?.textContent : "") ?? "").includes(want);
      },
      PALETTE_TOGGLE,
      { timeout: 5000 },
    )
    .catch(() => {});
  /* A reader's cadence before Enter, as this helper always had. MEASURED (R5 repair): with Enter pressed
     the instant the active row read as the toggle, the narrowed drawer pass (--sweep --vp=1024,1270
     --state=drawer) failed 4 and 2 of 50 cases in two runs — the palette stayed open ("the drawer did
     not close (focus INPUT …)") or focus went to #stage instead of the drawer's opener — where this
     cadence failed 0 of 50 twice. That is the palette acting on a render that has not settled; it is
     routed to the palette's owner (open-issues), not absorbed here by a longer sleep. */
  await page.waitForTimeout(300);
  const top = await readTop();
  paletteRead.set(page, { top, stale: null });
  if (!top.includes(PALETTE_TOGGLE)) {
    await page.keyboard.press("Escape");
    return false;
  }
  await page.keyboard.press("Enter");
  return true;
}

async function drawerOpen(page, opener) {
  if (opener === "e") await page.keyboard.press("e");
  else if (opener === "v") await page.keyboard.press("v");
  else if (opener === "g e") {
    await page.keyboard.press("g");
    await page.keyboard.press("e");
  } else if (!(await paletteToggle(page))) return paletteMiss(page);
  await page.waitForTimeout(500);
  /* And eight animation frames: `v` moves focus a frame (up to six under reduced motion) after the
     open commits. MEASURED (this cluster, 2026-09-26, reduced motion at 1152 px, 8 runs): that frame
     arrived 100-190 ms after the key in six runs and 790 ms and 3.2 s in two, while the lazy fabric
     chunk was evaluating under software GL — a fixed 500 ms judged a race, not the app. */
  for (let i = 0; i < 4; i += 1) await framesSettled(page);
  const st = await page.evaluate(drawerState);
  return st.drawer === "open" && st.railShown ? null : `after ${opener}: data-drawer=${st.drawer} railShown=${st.railShown}`;
}

/** Tab (real presses) until focus is inside the rail. */
async function tabIntoDrawer(page) {
  for (let i = 0; i < 150; i += 1) {
    if ((await page.evaluate(drawerState)).inRail) return true;
    await page.keyboard.press("Tab");
  }
  return (await page.evaluate(drawerState)).inRail;
}

async function drawerCase(page, w, opener, close, motion = "") {
  const where = `drawer ${w}px${motion}`;
  const scenario = `open by ${opener} → focus inside → close by ${close}`;
  if (!(await drawerLoad(page))) return drawerResult(where, scenario, false, "NOT DRIVEN: no grid cell to start from");
  const notOpened = await drawerOpen(page, opener);
  if (notOpened !== null) return drawerResult(where, scenario, false, /^(?:PALETTE DEFECT|NOT DRIVEN):/.test(notOpened) ? notOpened : `NOT DRIVEN: ${notOpened}`);
  if (opener === "g e") {
    const st = await page.evaluate(drawerState);
    const claims = /^Moved to/.test(st.status);
    if (claims !== st.inRail) return drawerResult(where, scenario, false, `announced "${st.status}" with focus ${st.inRail ? "inside" : "outside"} the rail (${st.desc})`);
  }
  /* `v` opens the configuration evidence AND moves focus to it, as it does at every other rung.
     MEASURED (independent verifier, 2026-09-26): under reduced motion at 1100 px focus stayed on the
     grid cell; the Tab walk below then reached the rail anyway and the case passed without noticing. */
  if (opener === "v") {
    const st = await page.evaluate(drawerState);
    if (!st.inRail) return drawerResult(where, scenario, false, `v opened the drawer but focus stayed outside it (${st.desc})`);
  }
  if (!(await tabIntoDrawer(page))) return drawerResult(where, scenario, false, "NOT DRIVEN: Tab never reached the open drawer");
  await drawerVisible(page, "drawer control", where, scenario);
  if (close === "e") await page.keyboard.press("e");
  else if (close === "palette") {
    if (!(await paletteToggle(page))) return drawerResult(where, scenario, false, paletteMiss(page));
  } else {
    /* Escape: an inner layer (the configuration overlay) closes first; the drawer on a later press. */
    for (let k = 0; k < 3; k += 1) {
      const st = await page.evaluate(drawerState);
      if (st.drawer !== "open" || !st.inRail) break;
      if (st.body) break;
      await page.keyboard.press("Escape");
      await page.waitForTimeout(150);
      const after = await page.evaluate(drawerState);
      if (after.body) break;
    }
  }
  await page.waitForTimeout(SETTLE_MS);
  const st = await page.evaluate(drawerState);
  if (st.drawer === "open") return drawerResult(where, scenario, false, `the drawer did not close (focus ${st.desc})`);
  if (st.body) return drawerResult(where, scenario, false, "focus landed on BODY");
  if (st.inRail) return drawerResult(where, scenario, false, `focus left inside the closed rail (${st.desc})`);
  /* The invoker is the element marked before the open. If it left the page (a re-render replaced the
     cell), "returned to the invoker" was not tested at all: say so, never pass it (verifier D3-V5). */
  if (!st.invokerConnected) return drawerResult(where, scenario, false, `NOT DRIVEN: the invoker left the page, so the return to it was not tested (focus ${st.desc})`);
  if (!st.onInvoker) return drawerResult(where, scenario, false, `focus returned to ${st.desc}, not to the control that opened the drawer`);
  drawerResult(where, scenario, true, "");
  await drawerVisible(page, "returned", where, scenario);
}

/**
 * RE-ENTRY DURING THE CLOSING SLIDE. MEASURED (independent verifier, 2026-09-26, release build at
 * 1100 px): open with `e`, Tab inside, close with `e`, then Tab seven times at once — focus walked
 * back INTO the rail, still `visibility: visible` for its 240 ms step, and 600 ms later it was on
 * <body>. The programmatic shape (a focus() into the rail right after the close) did the same.
 * The release on hide ran once; nothing kept focus out afterwards. Both shapes are driven here:
 * after SETTLE_MS focus must not be on <body> and not inside the closed rail.
 */
const DRAWER_REENTRIES = ["Tab x7 at once", "focus() into the rail"];
async function drawerReenter(page, w, how, motion = "") {
  const where = `drawer ${w}px${motion}`;
  const scenario = `open by e → focus inside → close by e → ${how} during the slide`;
  if (!(await drawerLoad(page))) return drawerResult(where, scenario, false, "NOT DRIVEN: no grid cell to start from");
  const notOpened = await drawerOpen(page, "e");
  if (notOpened !== null) return drawerResult(where, scenario, false, `NOT DRIVEN: ${notOpened}`);
  if (!(await tabIntoDrawer(page))) return drawerResult(where, scenario, false, "NOT DRIVEN: Tab never reached the open drawer");
  await page.keyboard.press("e");
  if (how.startsWith("Tab")) {
    for (let i = 0; i < 7; i += 1) await page.keyboard.press("Tab");
  } else {
    await page.evaluate(() => document.querySelector('#rail-evidence [role="radio"]')?.focus());
  }
  const during = await page.evaluate(drawerState);
  await page.waitForTimeout(SETTLE_MS);
  const st = await page.evaluate(drawerState);
  if (st.drawer === "open") return drawerResult(where, scenario, false, `the drawer did not close (focus ${st.desc})`);
  if (st.body) return drawerResult(where, scenario, false, `focus landed on BODY (right after the close it was ${during.inRail ? "back inside the rail" : "outside the rail"}: ${during.desc})`);
  if (st.inRail) return drawerResult(where, scenario, false, `focus left inside the closed rail (${st.desc})`);
  drawerResult(where, scenario, true, "");
  await drawerVisible(page, "returned", where, scenario);
}

/**
 * Wait until the page has PROCESSED a viewport change: two animation frames, which cannot run until
 * the resize has been dispatched and the app's synchronous re-render committed. MEASURED (this pass,
 * 2026-09-26, 2 runs of 3): at 1024 px the first resize case landed while the lazy fabric chunk was
 * evaluating under software GL; a fixed 1 s wait elapsed before the page had even seen the resize to
 * 390, the resize back to 1024 followed, and the app never observed the crossing — the harness then
 * reported the drawer "reopened by itself". A case must judge the state it drove, not a race.
 */
const framesSettled = (page) =>
  page.evaluate(
    () =>
      new Promise((resolve) => {
        const t = setTimeout(resolve, 10000);
        requestAnimationFrame(() => requestAnimationFrame(() => (clearTimeout(t), resolve())));
      }),
  );

async function drawerResize(page, w, t) {
  const where = `drawer ${w}px`;
  const scenario = `open by e → focus inside → resize to ${t}px (${rungOf(t)} rung) → back to ${w}px`;
  if (!(await drawerLoad(page))) return drawerResult(where, scenario, false, "NOT DRIVEN: no grid cell to start from");
  const notOpened = await drawerOpen(page, "e");
  if (notOpened !== null) return drawerResult(where, scenario, false, `NOT DRIVEN: ${notOpened}`);
  if (!(await tabIntoDrawer(page))) return drawerResult(where, scenario, false, "NOT DRIVEN: Tab never reached the open drawer");
  const size = page.viewportSize();
  await page.setViewportSize({ width: t, height: size?.height ?? 800 });
  await framesSettled(page);
  await page.waitForTimeout(SETTLE_MS);
  let st = await page.evaluate(drawerState);
  if (st.body) return drawerResult(where, scenario, false, `at ${t}px focus landed on BODY`);
  if (st.inRail && !st.railShown) return drawerResult(where, scenario, false, `at ${t}px focus left inside the rail, which is not shown (${st.desc})`);
  await drawerVisible(page, "after resize", where, scenario);
  await page.setViewportSize({ width: w, height: size?.height ?? 800 });
  await framesSettled(page);
  await page.waitForTimeout(SETTLE_MS);
  st = await page.evaluate(drawerState);
  if (st.drawer === "open") return drawerResult(where, scenario, false, `back at ${w}px the drawer reopened by itself: its open state outlived its rung`);
  if (st.body) return drawerResult(where, scenario, false, `back at ${w}px focus landed on BODY`);
  drawerResult(where, scenario, true, "");
}

/** The drawer pass. `only` is the --vp list (or undefined). Returns whether it was in scope at all. */
async function runDrawer(browser, only, push = null) {
  const targets = SWEEP_VIEWPORTS.map(([w]) => Number(w)).filter((w) => rungOf(w) !== "drawer");
  const plan = [];
  for (const w of DRAWER_WIDTHS) {
    const cases = [];
    if (!only || only.includes(w)) for (const o of DRAWER_OPENERS) for (const c of DRAWER_CLOSES) cases.push((page) => drawerCase(page, w, o, c));
    if (!only || only.includes(w)) for (const how of DRAWER_REENTRIES) cases.push((page) => drawerReenter(page, w, how));
    for (const t of targets) if (!only || only.includes(w) || only.includes(t)) cases.push((page) => drawerResize(page, w, t));
    if (cases.length > 0) plan.push([w, cases, "no-preference"]);
    /* REDUCED MOTION: the 240 ms step becomes 1 ms, and every `.ev *` / `.dp *` descendant gains a
       1 ms transition of the visibility it inherits (the `v` finding above). Every opener with the
       Escape close, and both re-entry shapes, run again in a reduced-motion context. */
    const reduced = [];
    if (!only || only.includes(w)) {
      for (const o of DRAWER_OPENERS) reduced.push((page) => drawerCase(page, w, o, "Escape", " reduced-motion"));
      for (const how of DRAWER_REENTRIES) reduced.push((page) => drawerReenter(page, w, how, " reduced-motion"));
    }
    if (reduced.length > 0) plan.push([w, reduced, "reduce"]);
  }
  console.log(
    `INFO  drawer pass: widths ${DRAWER_WIDTHS.join(", ")} px (LADDER_REM drawer rung ${DRAWER_RUNG.from}-${DRAWER_RUNG.to - 1} px), ` +
      `resize targets ${targets.join(", ")} px; ${plan.reduce((n, [, c]) => n + c.length, 0)} case(s) planned${only ? " (narrowed by --vp)" : ""}`,
  );
  /* One page per width, in parallel: most of a case is waiting (a load, the settle). With `push` (runSweep's shared
     pool) each page is a task of that pool, at its front. */
  const lanes = plan.map(([w, cases, reducedMotion]) => async () => {
      const ctx = await browser.newContext({ viewport: { width: w, height: 800 }, reducedMotion });
      await ctx.addInitScript(() => {
        try {
          localStorage.clear();
          sessionStorage.clear();
        } catch {
          /* storage blocked: nothing persists anyway */
        }
      });
      const page = await ctx.newPage();
      try {
        for (const run of cases) {
          if (page.viewportSize()?.width !== w) await page.setViewportSize({ width: w, height: 800 });
          await run(page);
        }
      } finally {
        await ctx.close();
      }
    });
  if (push !== null) for (const lane of lanes) push(lane, true);
  else await Promise.all(lanes.map((lane) => lane()));
  return plan.length > 0;
}

/* ── the rung crossing (part of --sweep, and so of the default run) ───────────
 * MEASURED (independent verifier, D3-R2-1, release build): the drawer was ONE instance of a class.
 * Across 7 rung crossings, 11 of 74 tab stops were lost to <body> — the pane switch App.tsx mounts only
 * below 1024 px ('900->1100 BUTTON.paneswitch__btn "Queue"'), the header's More button, popover and
 * inline toolbar ('inside More popover (thm__opt) -> 900->1100', '1100 "Copy the link…" -> 1100->900'),
 * the queue's View disclosure ('1100->1440 BUTTON.ui-btn "View"') and the fabric's controls when the
 * stage collapses ('768->390 BUTTON.fabric3d__btn "Legend"'). This file's resize cases were drawer-only,
 * so it could not see any of them. A list of those five would be the named-subset shape again.
 *
 * So the pass is the CLASS: one width per rung, derived from LADDER_REM (the sweep's width in that rung),
 * and every crossing to a NEIGHBOURING rung, both ways. At the start width, in every state below, EVERY
 * focusable element is a case:
 *   - every rendered tab stop (tabindex >= 0, not disabled, not inert, not aria-hidden) — the stops a
 *     keyboard reader holds; a roving group's other items are reached through its one stop;
 *   - every rendered tab stop of every SURFACE a reader can open there, FOUND BY ITS EFFECT (independent
 *     verifier R5-V2-3: a hand-kept list of surface states, and popovers found only through
 *     `[aria-haspopup]`, left disclosures, the status bar's coverage panel and the evidence drawer at its
 *     own rung outside the denominator). The CANDIDATES are every rendered, enabled control, whatever its
 *     role (crossOpeners; phase 3.5 repair, independent verifier QH-V1-2: an ARIA-contract selector never
 *     activated the `aria-pressed` "Show the 3-D fabric", which reveals seven stops at 390 px) — every
 *     control that announces a state, one representative per collection (a grid's rows) and per kind of
 *     stateless control (tag, class, role, name with its numbers folded) — every keyed command the app
 *     declares (read from the keyboard reference it renders — crossChords: the Inspector's `i`, the drawer's
 *     `e`, the palette's mod+k, the reference's `?`), and, ONE LEVEL DOWN, every candidate inside a surface
 *     one of those revealed (activated with that surface open). Each is activated on a clean page; the
 *     rendered tab stops that were NOT there before — and not stops of the clean page itself (a dialog's Close
 *     makes the page under it live again) — are the surface it revealed. A surface opened by an announcing
 *     control or a keyed command is cased stop by stop; one opened by any other control, or one level down, one
 *     stop per kind (see scheduleSurfaces). Openers that leave the page in the same state are one surface. An
 *     activation that changed the URL moved to another page state (the page states own those): counted, not
 *     cased. The per-family denominators are printed. The verifier's `thm__opt` inside More is one;
 *   - every PROGRAMMATIC LANDING: a rendered element focusable by script but not by Tab (an explicit
 *     `tabindex="-1"` that is not a roving item of a composite widget — `#stage` — and every named
 *     landmark, or the heading that labels it, which focus-return.ts makes focusable for exactly as
 *     long as it holds focus). Those are where the owner itself hands focus, so a crossing that took
 *     focus from one of them is the class too (independent verifier R5-V3: the pass drove none).
 * THE STATES (crossStates) are the PAGE states a URL restores (idle, a finding selected, a device
 * selected, a traced flow) and the one view state no control reaches (the fabric's off-view finding
 * pointer, drawn by panning the camera until a selected finding's host leaves the view). The modal
 * denominator is the source's own — the modules that own a modal dialog, found by the rendered dialog
 * primitive (review/palette-warm.mjs appModalDialogs) — and every one must have been opened by a
 * discovered opener, or the pass fails NEVER EXERCISED. A state that does not exist at a start width is
 * reported as such; a state no crossing could drive at all fails the run, and so does a pass whose
 * openers revealed no surface anywhere, or a keyed command it could not press.
 * Each case: focus the element (and confirm focus got there, or it is NOT DRIVEN), resize to the
 * neighbouring rung's width, let the page process it (two frames) and CROSS_SETTLE_MS more (longer
 * than the drawer's 240 ms visibility step), then FAIL when focus is on <body>, or on an element that
 * is not rendered (`checkVisibility`, inert), or on one with no part on screen, or one another layer
 * paints over (the nine-point hit test every other stop in this file must pass). The page stays where the
 * case left it: the next case starts from its own start width (every crossing at one viewport height,
 * CROSS_HEIGHT), and a tab-stop job holds both directions of a rung pair and picks, case by case, one that can
 * start where the page is clean without a load (crossStopsJob). A page whose signature (crossSignature — every
 * control's state, React's mount-order ids folded) is not one its start width loads clean with is restored —
 * the drifting opener undone, Escape, else a reload at that width — before the next case (crossSession's
 * `fresh`), and every read of it waits out the palette's pre-warm (crossWarmSettled).
 * The denominators — cases per crossing and per state, openers activated, surfaces revealed per
 * crossing and state — are printed; a crossing in scope that drove no case fails the run (SWEEP NEVER
 * EXERCISED: rung crossings).
 * `--vp=` narrows it: a crossing runs when its start or end width is listed. `--state=` narrows the
 * states like the rest of the sweep.
 */
const CROSS_SETTLE_MS = 500;
/** The settle of a return to a start width (crossSession's `ensure`): see there. */
const RETURN_SETTLE_MS = 100;
const crossCount = { cases: 0, crossings: 0, openersFound: 0, openersTried: 0, surfaces: 0, unstable: 0, landings: 0, lost: 0, recovered: 0, reloads: 0, undone: 0, reused: 0, sameSurface: 0, representedStops: 0, warmTimeouts: 0, unreadChords: [] };
/** The candidate openers by family (crossOpeners: state / collection / stateless, the keyed commands, and the nested
 *  ones a surface revealed): candidates activated, the members they stand for, how many revealed a surface, and how
 *  many navigated to another page state instead. */
const crossFamilies = {};
/** Why pages were reloaded between cases (state, width, the first line of the signature that differed): printed. */
const crossReloadWhy = new Map();
/** The first line by which signature `now` differs from `clean` ("+" present only now, "-" gone), cut short. */
const crossFirstDiff = (clean, now) => {
  const a = clean.split("\n");
  const b = now.split("\n");
  const count = (xs) => xs.reduce((m, x) => m.set(x, (m.get(x) ?? 0) + 1), new Map());
  const ca = count(a);
  const cb = count(b);
  for (const x of b) if ((cb.get(x) ?? 0) > (ca.get(x) ?? 0)) return `+ ${x.slice(0, 90)}`;
  for (const x of a) if ((ca.get(x) ?? 0) > (cb.get(x) ?? 0)) return `- ${x.slice(0, 90)}`;
  return "the same lines in another order";
};
/** Surfaces revealed, per crossing and state (`crossing … / state`): the denominator of family 2. */
const crossSurfaces = new Map();
/** Surface states that did not exist at a crossing's start width, by state name (reported, not failed). */
const crossAbsent = new Map();
/** The modal dialogs (by accessible name) a surface state opened, over the whole pass. */
const crossDialogsOpened = new Set();

/* The modal dialogs the SOURCE renders, found by the RENDERED dialog primitive (review/palette-warm.mjs
   `appModalDialogs`: a modal element, or a component that renders one or a primitive, resolved through
   imports and aliases — independent verifier R6 VR2-3), not by the spelling `<Dialog`: the modules that own
   a dialog the app opens. */
const SOURCE_DIALOGS = [...new Set((await appModalDialogs(new URL("../src/", import.meta.url))).owners.map((o) => o.file))].sort();
/* How many units (a crossing in one state) run at once. Each holds a page with a WebGL fabric; MEASURED,
   eight at once crashed a renderer on this shared host WITH every frame drawn in software. With the draws
   suspended a page's frame work is a fraction of that (see RENDER), so the default is fourteen (MEASURED, phase 3.5
   repair, a full --crossings on this 14-core, 15.4 GB host: 14 at once left 2.0 GB free and no renderer crashed; 16
   at once left 0.7 GB); with every frame drawn it stays three. `ATLAS_CROSS_PARALLEL` overrides it (>= 1). */
const CROSS_PARALLEL_DEFAULT = RENDER === "suspended" ? 14 : 3;
const CROSS_PARALLEL = Math.max(1, Number(process.env["ATLAS_CROSS_PARALLEL"] ?? CROSS_PARALLEL_DEFAULT) || CROSS_PARALLEL_DEFAULT);
const crossPerCrossing = new Map();

/** One width per rung: the sweep's own width in that rung (coverRungs guarantees there is one). */
const RUNG_WIDTHS = RUNGS.map((r) => SWEEP_VIEWPORTS.find(([w]) => rungOf(Number(w)) === r.name)).filter((v) => v !== undefined);
/* ONE viewport height for every crossing: the SHORTEST of the rungs' own heights (SWEEP_VIEWPORTS). A crossing
   changes the WIDTH, across a rung of LADDER_REM (a width ladder); each crossing held its height through the
   resize, and one height for all of them lets the two directions of a rung pair start on the same viewport, so a
   case's arrival (at `to`) can be the next, reverse case's start (at its `from`): one resize a case, not two.
   WHY THE SHORTEST (independent verifier QH-V1-4): until phase 3 each crossing ran at its start rung's height
   (390x844, 768x1024, 1152x800, 1440x900, 1920x1080); the first single height (900, the reference rung's) no longer
   drove the 800 and 844 px viewports, where "no part on screen" is likeliest to fail. The shortest height is at
   most every pair's shorter one, so every crossing is now driven on a viewport no taller than any it ran on
   before. It is read from the width lists, not typed. */
const CROSS_HEIGHT = Math.min(...RUNG_WIDTHS.map(([, h]) => Number(h)));

/**
 * In-page, before an opener is activated: mark every element that could hold focus and is rendered now —
 * tab stops AND programmatically focusable ones (a roving item's tabindex=-1) — so what the activation
 * REVEALS is judged by element identity: a roving stop that moved, or a button whose label changed, is not a
 * surface (measured on the first run: a tree item's Enter "revealed" the grid's moved roving cell, and the
 * status bar's re-labelled scene button). Clears any earlier marking first.
 */
const crossMarkSeen = () => {
  for (const el of document.querySelectorAll("[data-d3-seen]")) el.removeAttribute("data-d3-seen");
  const SEL = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable='true']";
  /* Rendered and reachable as crossUnseenStops judges it: a closed drawer's controls (visibility:hidden, inert)
     are NOT seen, so opening it reveals them. */
  const rendered = (el) =>
    el.isConnected &&
    (typeof el.checkVisibility === "function" ? el.checkVisibility({ visibilityProperty: true }) : el.getClientRects().length > 0) &&
    el.closest("[inert], [aria-hidden='true']") === null;
  for (const el of document.querySelectorAll(SEL)) if (rendered(el)) el.setAttribute("data-d3-seen", "");
};
/** In-page: the rendered tab stops that were NOT marked by crossMarkSeen — what the activation revealed. */
const crossUnseenStops = () => {
  const SEL = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable='true']";
  const rendered = (el) =>
    el.isConnected &&
    (typeof el.checkVisibility === "function" ? el.checkVisibility({ visibilityProperty: true }) : el.getClientRects().length > 0) &&
    el.closest("[inert], [aria-hidden='true']") === null;
  const pathOf = (el) => {
    const parts = [];
    for (let n = el; n !== null && n !== document.body; n = n.parentElement) parts.push(`${n.tagName}:${n.parentElement ? [...n.parentElement.children].indexOf(n) : 0}`);
    return parts.reverse().join("/");
  };
  const out = [];
  for (const el of document.querySelectorAll(SEL)) {
    if (el.hasAttribute("data-d3-seen") || el.id === "__sr-top" || el.tabIndex < 0 || el.disabled || !rendered(el)) continue;
    const cls = typeof el.className === "string" ? el.className.split(" ")[0] : "";
    out.push({ path: pathOf(el), label: `${el.tagName}${cls ? `.${cls}` : ""}${el.getAttribute("role") ? `[${el.getAttribute("role")}]` : ""}` });
  }
  return out;
};

/** In-page: the accessible names of the modal dialogs on screen now (never a React useId): an aria-modal dialog or
 *  alert dialog, or a native <dialog> shown with showModal() (`:modal`; it carries no aria-modal). */
const crossModalNames = () =>
  [...document.querySelectorAll('[aria-modal="true"], dialog:modal')]
    .filter((el) => el.getClientRects().length > 0)
    .map((d) => {
      const by = (d.getAttribute("aria-labelledby") ?? "").split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
      return (d.getAttribute("aria-label") ?? by).replace(/\s+/g, " ").trim() || "(an unnamed modal dialog)";
    });

/**
 * [name, query, prep, scope]: the PAGE states — what a URL restores (idle, a selection, a trace), and the one
 * view state no control reaches (the off-view finding pointer, drawn by panning the camera). `prep` (after the
 * load) brings the state about and returns true, or "n/a"/false when it does not exist at this width; `scope`
 * is the selector of the surface whose elements are this state's cases (null: the whole page).
 *
 * THE SURFACES ARE NOT LISTED HERE (independent verifier R5-V2-3: the Inspector, the device view, the
 * palette and the keyboard reference were hand-kept states, and an `aria-expanded` disclosure, the status
 * bar's coverage panel or the evidence drawer at its own rung were outside the denominator). In every page
 * state the pass DISCOVERS them: every control whose activation reveals new focusables — see crossOpeners
 * and crossChords — is activated, and the tab stops that were not there before are that surface's cases.
 */
const crossStates = () => {
  const fabricJson = JSON.parse(readFileSync(new URL("../src/data/fabric.json", import.meta.url), "utf8"));
  const flow = encodeURIComponent("10.0.10.50>10.0.30.10>tcp>3389");
  const first = fabricJson.findings[0];
  const finding = `f=${encodeURIComponent(first.id)}&s=findings`;
  const device = first.devices?.[0] ?? fabricJson.devices[0].id;
  return [
    ["idle", "", null, null],
    ["a finding selected", finding, null, null],
    ["a device selected", `d=${encodeURIComponent(device)}&s=evidence`, null, null],
    ["a traced flow", `s=path&flow=${flow}`, null, null],
    /* The off-view finding pointer (FabricLabels.tsx), hidden from script when a re-projection brings
       its device into view: the imperative member of the class (independent verifier R5-V2). */
    ["an off-view pointer drawn", "f=F094", panUntilOffViewPointer, '[data-testid="fabric3d-pointers"]'],
  ];
};

/**
 * In-page: THE CANDIDATE OPENERS — every rendered, enabled CONTROL on the page (`unseenOnly`: only those the last
 * activation revealed), whatever its role, because what reveals a surface is decided by the EFFECT
 * (crossDiscover activates each and keeps the ones that reveal new focusables), never by an ARIA contract.
 * Independent verifier QH-V1-2: the phase-3 candidates were the controls whose contract announces a reveal
 * (`aria-haspopup`, `aria-expanded="false"`, `<summary>`, an unselected tab, an unchecked radio), so an
 * `aria-pressed` toggle that reveals seven tab stops at 390 px — "Show the 3-D fabric" — was never activated.
 * Three families, each reported with its own count:
 *   - STATE: a control that announces a state its activation changes (`aria-expanded`, `aria-pressed`,
 *     `aria-haspopup`, `aria-controls`, `aria-checked`, a tab, a `<summary>`, a checkbox or radio, a `<select>`),
 *     whatever that state's value: EVERY one is activated;
 *   - COLLECTION: a member of a composite widget's collection (a grid's rows and cells, a tree's items, a
 *     listbox's options, a menu's items): the members of one collection are one component repeated, so ONE per
 *     collection, role, class and state set is activated, and the rest are counted as represented by it;
 *   - STATELESS: every other control (a button, a link, a focusable element): one per KIND — tag, class, role and
 *     accessible name with its numbers folded ("Open the source record for F#") — is activated, the rest counted.
 * Text entry (a field typed into, not activated) is not a candidate unless it announces a popup (a combobox). The
 * key each is activated with is the one its role takes: Space checks a radio, checkbox or switch; ArrowRight
 * EXPANDS a tree item or grid row/cell that has an expanded state (Enter there selects); ArrowDown moves a
 * <select>; everything else takes Enter.
 */
const crossOpeners = ({ root: rootPath, unseenOnly }) => {
  let root = document.body;
  if (rootPath !== null) {
    for (const part of rootPath.split("/")) {
      const [tag, i] = part.split(":");
      const c = root?.children[Number(i)];
      if (!c || c.tagName !== tag) return [];
      root = c;
    }
  }
  const CONTROL =
    'a[href], button, input, select, textarea, summary, [tabindex], [contenteditable="true"], [aria-expanded], [aria-pressed], [aria-haspopup], ' +
    "[role=button], [role=link], [role=tab], [role=radio], [role=checkbox], [role=switch], [role=option], [role=treeitem], [role=row], " +
    "[role=gridcell], [role=rowheader], [role=columnheader], [role=menuitem], [role=menuitemradio], [role=menuitemcheckbox]";
  const STATE_ATTRS = ["aria-expanded", "aria-pressed", "aria-haspopup", "aria-controls", "aria-checked"];
  const COLLECTION = /^(?:row|gridcell|rowheader|columnheader|option|treeitem|menuitem|menuitemradio|menuitemcheckbox)$/;
  const rendered = (el) =>
    el.isConnected &&
    (typeof el.checkVisibility === "function" ? el.checkVisibility({ visibilityProperty: true }) : el.getClientRects().length > 0) &&
    el.closest("[inert], [aria-hidden='true']") === null;
  const pathOf = (el) => {
    const parts = [];
    for (let n = el; n !== null && n !== document.body; n = n.parentElement) parts.push(`${n.tagName}:${n.parentElement ? [...n.parentElement.children].indexOf(n) : 0}`);
    return parts.reverse().join("/");
  };
  const nameOf = (el) => (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().replace(/\s+/g, " ");
  const out = [];
  const kinds = new Map();
  for (const el of root.querySelectorAll(CONTROL)) {
    if (!rendered(el) || el.disabled || el.id === "__sr-top" || el.getAttribute("aria-disabled") === "true") continue;
    if (unseenOnly && el.hasAttribute("data-d3-seen")) continue;
    const role = el.getAttribute("role") ?? "";
    const checkable = (el instanceof HTMLInputElement && /^(?:checkbox|radio)$/.test(el.type)) || /^(?:radio|checkbox|switch)$/.test(role);
    const textEntry =
      (el instanceof HTMLInputElement && !/^(?:checkbox|radio|button|submit|reset|image|file|color|range)$/.test(el.type)) || el instanceof HTMLTextAreaElement || el.isContentEditable;
    if (textEntry && !el.hasAttribute("aria-expanded") && !el.hasAttribute("aria-haspopup")) continue;
    const states = STATE_ATTRS.filter((a) => el.hasAttribute(a));
    const cls = typeof el.className === "string" ? el.className.split(" ")[0] : "";
    let family;
    let kind = null;
    if (COLLECTION.test(role)) {
      family = "collection";
      const owner = el.closest("[role=grid], [role=treegrid], [role=listbox], [role=tree], [role=menu], [role=menubar]");
      kind = `${role}|${cls}|${owner === null ? "" : pathOf(owner)}|${states.join(",")}`;
    } else if (states.length > 0 || role === "tab" || el.tagName === "SUMMARY" || checkable || el instanceof HTMLSelectElement) family = "state";
    else {
      family = "stateless";
      kind = `${el.tagName}|${cls}|${role}|${nameOf(el).replace(/\d+/g, "#").slice(0, 60)}`;
    }
    if (kind !== null && kinds.has(`${family}|${kind}`)) {
      kinds.get(`${family}|${kind}`).members += 1;
      continue;
    }
    const key = el instanceof HTMLSelectElement ? "ArrowDown" : checkable ? "Space" : /^(?:treeitem|row|gridcell)$/.test(role) && el.hasAttribute("aria-expanded") ? "ArrowRight" : "Enter";
    const rec = { path: pathOf(el), key, family, members: 1, label: `${el.tagName}${role ? `[${role}]` : ""} "${nameOf(el).slice(0, 40)}"` };
    out.push(rec);
    if (kind !== null) kinds.set(`${family}|${kind}`, rec);
  }
  return out;
};

/* THE APP'S OWN COMMANDS, read from the keyboard reference it renders (ShortcutHelp: "this list is generated
   from them"), and pressed as a reader presses them. A keyed command that makes a container visible — the
   Inspector's `i`, the drawer's `e`, the palette's mod+k, the reference's own `?` — is an opener with no
   control on screen. The display tokens are mapped back to keys through keyboard.ts's own KEY_DISPLAY and
   modifier table (read from the source, not restated). */
const KEY_DISPLAY_INVERSE = (() => {
  const sf = ts.createSourceFile("keyboard.ts", readFileSync(new URL("../src/app/keyboard.ts", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const inverse = new Map();
  const visit = (n) => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === "KEY_DISPLAY" && n.initializer !== undefined) {
      let init = n.initializer;
      while (ts.isAsExpression(init) || ts.isSatisfiesExpression(init) || ts.isParenthesizedExpression(init)) init = init.expression;
      if (ts.isObjectLiteralExpression(init)) {
        for (const p of init.properties) {
          if (!ts.isPropertyAssignment(p) || !ts.isStringLiteralLike(p.initializer)) continue;
          const key = ts.isIdentifier(p.name) || ts.isStringLiteralLike(p.name) ? p.name.text : null;
          if (key !== null) inverse.set(p.initializer.text, key);
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return inverse;
})();
/** A keyboard.ts key name ("arrowup", " ") as the key Playwright presses ("ArrowUp", "Space"). */
const playwrightKey = (k) =>
  k === " " ? "Space" : k.length === 1 ? k : k.replace(/^(arrow|page)?(.)(.*)$/, (_, pre, c, rest) => (pre ? pre[0].toUpperCase() + pre.slice(1) + c.toUpperCase() + rest : c.toUpperCase() + rest));
const MODIFIER_TOKENS = new Map([
  ["Ctrl", "Control"],
  ["Alt", "Alt"],
  ["Shift", "Shift"],
  ["Win", "Meta"],
]);
/** "Ctrl K" -> ["Control+k"], "G then E" -> ["g", "e"], "Shift V" -> ["Shift+V"]; null when a token cannot be read. */
function chordPresses(text) {
  const out = [];
  for (const chord of text.split(/\s+then\s+/)) {
    const tokens = chord.trim().split(/\s+/).filter((t) => t !== "");
    if (tokens.length === 0) return null;
    const mods = tokens.slice(0, -1).map((t) => MODIFIER_TOKENS.get(t));
    if (mods.some((m) => m === undefined)) return null;
    const last = tokens[tokens.length - 1];
    const name = KEY_DISPLAY_INVERSE.get(last) ?? (last.length === 1 ? (mods.includes("Shift") ? last.toUpperCase() : last.toLowerCase()) : null);
    if (name === null) return null;
    out.push([...mods, playwrightKey(name)].join("+"));
  }
  return out;
}
/** In-page: the keyboard reference's rows (outside the canvas-only section), as label and shortcut text. */
const crossReadChords = () =>
  [...document.querySelectorAll(".kb-help__scope:not([data-testid]) .kb-help__row")].map((row) => {
    const hidden = row.querySelector(".kb-help__label .visually-hidden")?.textContent ?? "";
    const label = (row.querySelector(".kb-help__label")?.firstChild?.textContent ?? "").trim();
    return { label, keys: hidden.replace(/^:\s*/, "").trim() };
  });
/** Every keyed command, read once per run from a fresh page (the reference is the app's own list). */
let chordsRead = null;
async function crossChords(page) {
  if (chordsRead !== null) return chordsRead;
  chordsRead = (async () => {
    await page.keyboard.press("?");
    await page.waitForSelector(".kb-help__row", { timeout: 10000 }).catch(() => {});
    const rows = await page.evaluate(crossReadChords);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    const chords = [];
    const unread = [];
    for (const r of rows) {
      const presses = r.keys === "" ? null : chordPresses(r.keys);
      if (presses === null) unread.push(`${r.label} (${r.keys})`);
      else if (!chords.some((c) => c.presses.join(" ") === presses.join(" "))) chords.push({ label: `the command "${r.label}" (${r.keys})`, presses });
    }
    console.log(`INFO  rung crossing: ${chords.length} keyed command(s) read from the keyboard reference${unread.length > 0 ? `; ${unread.length} not readable as keys: ${unread.join("; ")}` : ""}`);
    if (unread.length > 0) crossCount.unreadChords.push(...unread);
    return chords;
  })();
  return chordsRead;
}

/** In-page: the structural path of the first RENDERED match of `selector` (null when none is). */
const crossScopePath = (selector) => {
  const el = [...document.querySelectorAll(selector)].find(
    (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility === "visible" && e.closest("[inert]") === null,
  );
  if (el === undefined) return null;
  const parts = [];
  for (let n = el; n !== null && n !== document.body; n = n.parentElement) parts.push(`${n.tagName}:${n.parentElement ? [...n.parentElement.children].indexOf(n) : 0}`);
  return parts.reverse().join("/");
};

/**
 * In-page: every PROGRAMMATIC LANDING under `rootPath` (or the document): a rendered element with an
 * explicit tabindex="-1" that is not a roving item of a composite widget, and every named landmark —
 * as the heading that labels it when there is one inside it, which is where focus-return.ts lands.
 * The root itself counts when it is one. Tab stops are family 1's, and are left out here.
 */
const crossLandings = (rootPath) => {
  let root = document.body;
  if (rootPath !== null) {
    for (const part of rootPath.split("/")) {
      const [tag, i] = part.split(":");
      const c = root?.children[Number(i)];
      if (!c || c.tagName !== tag) return [];
      root = c;
    }
  }
  const rendered = (el) =>
    el.isConnected &&
    (typeof el.checkVisibility === "function" ? el.checkVisibility({ visibilityProperty: true }) : el.getClientRects().length > 0) &&
    el.closest("[inert], [aria-hidden='true']") === null;
  const ROVING = "[role=radio],[role=tab],[role=option],[role=gridcell],[role=row],[role=menuitem],[role=menuitemradio],[role=menuitemcheckbox],[role=treeitem],[role=cell],[role=columnheader],[role=rowheader],[role=switch]";
  const COMPOSITE = "[role=grid],[role=treegrid],[role=listbox],[role=tree],[role=tablist],[role=radiogroup],[role=menu],[role=menubar],[role=toolbar]";
  const REGION = "[role='region'],[role='search'],[role='dialog'],[role='complementary'],[role='main'],[role='navigation'],[role='form'],section,form,aside,main,nav";
  const named = (el) => (el.getAttribute("aria-label") ?? "").trim() !== "" || (el.getAttribute("aria-labelledby") ?? "").trim() !== "";
  const pathOf = (el) => {
    const parts = [];
    for (let n = el; n !== null && n !== document.body; n = n.parentElement) parts.push(`${n.tagName}:${n.parentElement ? [...n.parentElement.children].indexOf(n) : 0}`);
    return parts.reverse().join("/");
  };
  const all = (sel) => [...(root.matches?.(sel) ? [root] : []), ...root.querySelectorAll(sel)];
  const picked = new Set();
  for (const el of all("[tabindex='-1']")) if (el.id !== "__sr-top" && rendered(el) && !el.matches(ROVING) && el.closest(COMPOSITE) === null) picked.add(el);
  for (const mark of all(REGION)) {
    if (!named(mark) || !rendered(mark)) continue;
    const by = (mark.getAttribute("aria-labelledby") ?? "").split(/\s+/).find((x) => x !== "");
    const heading = by === undefined ? null : document.getElementById(by);
    const land = heading !== null && mark.contains(heading) && rendered(heading) ? heading : mark;
    if (land.tabIndex >= 0) continue; /* already a tab stop: family 1 drives it */
    picked.add(land);
  }
  return [...picked].map((el) => {
    const name = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
    return { path: pathOf(el), label: `landing ${el.tagName}${el.id ? `#${el.id}` : ""}${el.getAttribute("role") ? `[${el.getAttribute("role")}]` : ""} "${name}"` };
  });
};

/** In-page: mark a landing and make it programmatically focusable as focus-return.ts does (tabindex=-1
 *  for exactly as long as it holds focus). */
const crossMarkLanding = (path) => {
  for (const el of document.querySelectorAll("[data-d3-cross]")) el.removeAttribute("data-d3-cross");
  let n = document.body;
  for (const part of path.split("/")) {
    const [tag, i] = part.split(":");
    const c = n?.children[Number(i)];
    if (!c || c.tagName !== tag) return false;
    n = c;
  }
  if (!n.hasAttribute("tabindex")) {
    n.setAttribute("tabindex", "-1");
    n.addEventListener("blur", () => n.removeAttribute("tabindex"), { once: true });
  }
  n.setAttribute("data-d3-cross", "");
  return true;
};

/** In-page: every rendered tab stop under `rootPath` (or the document), as structural paths. */
const crossStops = (rootPath) => {
  const SEL = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable='true']";
  const pathOf = (el) => {
    const parts = [];
    for (let n = el; n !== null && n !== document.body; n = n.parentElement) parts.push(`${n.tagName}:${n.parentElement ? [...n.parentElement.children].indexOf(n) : 0}`);
    return parts.reverse().join("/");
  };
  const byPath = (p) => {
    let n = document.body;
    for (const part of p.split("/")) {
      const [tag, i] = part.split(":");
      const c = n?.children[Number(i)];
      if (!c || c.tagName !== tag) return null;
      n = c;
    }
    return n;
  };
  const root = rootPath === null ? document.body : byPath(rootPath);
  if (root === null) return [];
  const rendered = (el) =>
    el.isConnected &&
    (typeof el.checkVisibility === "function" ? el.checkVisibility({ visibilityProperty: true }) : el.getClientRects().length > 0) &&
    el.closest("[inert], [aria-hidden='true']") === null;
  const out = [];
  for (const el of root.querySelectorAll(SEL)) {
    if (el.id === "__sr-top" || el.tabIndex < 0 || el.disabled || !rendered(el)) continue;
    const name = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
    const cls = typeof el.className === "string" ? el.className.split(" ")[0] : "";
    out.push({ path: pathOf(el), label: `${el.tagName}${cls ? `.${cls}` : ""}${el.getAttribute("role") ? `[${el.getAttribute("role")}]` : ""} "${name}"` });
  }
  return out;
};

/** In-page: mark the element at a structural path (and return whether it is still the same kind). */
const crossMark = (path) => {
  for (const el of document.querySelectorAll("[data-d3-cross]")) el.removeAttribute("data-d3-cross");
  let n = document.body;
  for (const part of path.split("/")) {
    const [tag, i] = part.split(":");
    const c = n?.children[Number(i)];
    if (!c || c.tagName !== tag) return false;
    n = c;
  }
  n.setAttribute("data-d3-cross", "");
  return true;
};


/** In-page: mark the element at a structural path only if it is still the stop it was (the label
 *  crossUnseenStops gave it), rendered and a tab stop. */
const crossMarkIfLabel = ([path, label]) => {
  for (const el of document.querySelectorAll("[data-d3-cross]")) el.removeAttribute("data-d3-cross");
  let n = document.body;
  for (const part of path.split("/")) {
    const [tag, i] = part.split(":");
    const c = n?.children[Number(i)];
    if (!c || c.tagName !== tag) return false;
    n = c;
  }
  const cls = typeof n.className === "string" ? n.className.split(" ")[0] : "";
  const now = `${n.tagName}${cls ? `.${cls}` : ""}${n.getAttribute("role") ? `[${n.getAttribute("role")}]` : ""}`;
  const rendered =
    n.isConnected &&
    (typeof n.checkVisibility === "function" ? n.checkVisibility({ visibilityProperty: true }) : n.getClientRects().length > 0) &&
    n.closest("[inert], [aria-hidden='true']") === null;
  if (now !== label || !rendered || n.tabIndex < 0 || n.disabled) return false;
  n.setAttribute("data-d3-cross", "");
  return true;
};

/** In-page: for a tab or radio at a structural path, the member of its group selected NOW (what activating it
 *  replaces), as a path and the key that selects it again; null for anything else, or when it is itself selected. */
const crossSelectedSibling = (path) => {
  let n = document.body;
  for (const part of path.split("/")) {
    const [tag, i] = part.split(":");
    const c = n?.children[Number(i)];
    if (!c || c.tagName !== tag) return null;
    n = c;
  }
  const role = n.getAttribute("role");
  if (role !== "tab" && role !== "radio") return null;
  const group = n.closest(role === "tab" ? '[role="tablist"]' : '[role="radiogroup"]');
  if (group === null) return null;
  const selected = [...group.querySelectorAll(`[role="${role}"]`)].find((x) => x.getAttribute(role === "tab" ? "aria-selected" : "aria-checked") === "true");
  if (selected === undefined || selected === n) return null;
  const parts = [];
  for (let m = selected; m !== null && m !== document.body; m = m.parentElement) parts.push(`${m.tagName}:${m.parentElement ? [...m.parentElement.children].indexOf(m) : 0}`);
  return { path: parts.reverse().join("/"), key: role === "radio" ? "Space" : "Enter" };
};

/** In-page: mark the element at a structural path when it is a TOGGLE whose activation undoes itself — a disclosure
 *  left expanded, a toggle button (aria-pressed), a checkbox or switch, a <summary> — so pressing its key again
 *  puts back what the activation changed. (A tab or radio is put back by selecting what it replaced.) */
const crossMarkUndoable = (path) => {
  for (const el of document.querySelectorAll("[data-d3-cross]")) el.removeAttribute("data-d3-cross");
  let n = document.body;
  for (const part of path.split("/")) {
    const [tag, i] = part.split(":");
    const c = n?.children[Number(i)];
    if (!c || c.tagName !== tag) return false;
    n = c;
  }
  const toggle =
    n.getAttribute("aria-expanded") === "true" ||
    n.hasAttribute("aria-pressed") ||
    /^(?:checkbox|switch|menuitemcheckbox)$/.test(n.getAttribute("role") ?? "") ||
    (n instanceof HTMLInputElement && n.type === "checkbox") ||
    n.tagName === "SUMMARY" ||
    n instanceof HTMLSelectElement;
  if (!toggle) return false;
  n.setAttribute("data-d3-cross", "");
  return true;
};

/** In-page: where focus is after the crossing, and whether that element is rendered. */
const crossLanding = () => {
  const a = document.activeElement;
  if (a === null || a === document.body || a === document.documentElement) return { lost: true, desc: "BODY (nothing focused)" };
  const name = (a.getAttribute("aria-label") ?? a.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
  const cls = typeof a.className === "string" ? a.className.split(" ")[0] : "";
  const rendered =
    a.isConnected &&
    (typeof a.checkVisibility !== "function" || a.checkVisibility({ visibilityProperty: true })) &&
    a.closest("[inert]") === null;
  return { lost: false, rendered, connected: a.isConnected, desc: `${a.tagName}${a.id ? `#${a.id}` : ""}${cls ? `.${cls}` : ""} "${name}"` };
};


/**
 * In-page: THE CROSSING PASS'S SIGNATURE — what a reload of the state restores, which a page must match to count
 * as clean. srSignature's (the URL, the open dialogs, the rendered tab stops) and the STATE of every control and
 * the document: each element's aria-checked/-pressed/-selected/-expanded, every field's checked and value, and the
 * root's theme. MEASURED (phase 3.5, --render-check): the queue's "Display" surface revealed 12 stops in one
 * discovery and 9 in another of the same page state, because an earlier opener in the same session (a category
 * radio, a theme radio) had changed state that no tab stop showed, the tab-stop signature still matched, and the
 * page counted as clean. A selection, a toggle or a theme is what a reload resets; it is part of "clean".
 * Live regions are left out (their text is an announcement, not state).
 *
 * React's useId values (`_r_2_`, `«r2»`, `:r2:`) are NORMALISED to one token: they number the components in the
 * order they MOUNTED, which is history, not state. MEASURED (phase 3.5 repair, probe of every rung pair, idle and a
 * traced flow): a page loaded at 768 and resized to 1152 carried `_r_2_-q` where a page loaded at 1152 carried
 * `_r_3_-q` — 76 of 76 differing lines were ids — so no page was ever clean at a width it had not been LOADED at,
 * and every case whose start was the other rung of its pair reloaded. The element's tag, class, every state
 * attribute and value, and the document order are untouched: two pages still match only when every control is in
 * the same state in the same place.
 */
const crossSignature = () => {
  const noUseId = (s) => s.replace(/_r_[0-9a-z]+_/g, "_r_").replace(/«r[0-9a-z]+»/g, "«r»").replace(/:r[0-9a-z]+:/g, ":r:");
  const sel = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable='true']";
  /* The inert and live-region subtrees, found once: a per-element `closest()` over a selector list cost most of this
     function's 69 ms on a traced flow (MEASURED, phase 3.5 repair), and it runs several times a case. */
  const inerts = [...document.querySelectorAll("[inert]")];
  const lives = [...document.querySelectorAll("[aria-live], [role=status], [role=alert], [role=log]")];
  const within = (list, el) => list.length > 0 && list.some((x) => x.contains(el));
  const stops = [...document.querySelectorAll(sel)]
    .filter((el) => el.tabIndex >= 0 && !el.disabled && el.getClientRects().length > 0 && !within(inerts, el))
    .map((el) => `${el.tagName}|${el.id}|${el.className}`);
  const dialogs = [...document.querySelectorAll("[role=dialog], [role=menu], [role=listbox], [role=alertdialog], dialog[open]")].filter((el) => el.getClientRects().length > 0).length;
  const state = [...document.querySelectorAll("[aria-checked], [aria-pressed], [aria-selected], [aria-expanded], input, select, textarea")]
    .filter((el) => !within(lives, el))
    .map(
      (el) =>
        `${el.tagName}|${el.id}|${["aria-checked", "aria-pressed", "aria-selected", "aria-expanded"].map((a) => el.getAttribute(a) ?? "").join(",")}|` +
        `${el instanceof HTMLInputElement ? `${el.checked}|${el.value}` : el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement ? el.value : ""}`,
    );
  const root = document.documentElement;
  return noUseId(`${location.search}\n${root.getAttribute("data-theme") ?? ""}|${root.className}\n${dialogs}\n${stops.join("\n")}\n--\n${state.join("\n")}`);
};

/**
 * Wait (bounded) until the command palette's PRE-WARM has finished, wherever the fabric is on screen. After the scene
 * converges, CommandPalette.tsx mounts its frame once and parks it — and the parked frame's input is a field, so it is
 * part of the signature. MEASURED (phase 3.5 repair, probe of every rung, idle and a traced flow): at 768, 1152, 1440
 * and 1920 a settled load read `data-palette-warm="waiting"`, and 4 s later the SAME untouched page read "done" with
 * one more field (`INPUT.palette__input`). The clean signature was taken in that window, so every later read of the
 * page differed from it, and the page was reloaded before every case — which then read clean again only because the
 * pre-warm had restarted. Where no canvas is rendered (the stacked rung) the scene never converges and the pre-warm
 * waits: there is nothing to wait for. A pre-warm that does not finish in time is left as it is: the signature then
 * differs, and the pass's own rule (restore, else reload) applies — slower, never looser.
 */
const CROSS_WARM_WAIT_MS = 15000;
async function crossWarmSettled(page) {
  await page
    .waitForFunction(
      (terminal) => {
        const canvas = document.querySelector(".fabric3d__canvas");
        const shown = canvas !== null && (typeof canvas.checkVisibility !== "function" || canvas.checkVisibility({ visibilityProperty: true }));
        return !shown || terminal.includes(document.documentElement.dataset.paletteWarm ?? "");
      },
      [...PALETTE_WARM_TERMINAL],
      { timeout: CROSS_WARM_WAIT_MS },
    )
    .catch(() => {
      crossCount.warmTimeouts += 1;
    });
}

/**
 * Load a state and wait until it has SETTLED: the lazy fabric (and its canvas, a tab stop) mounts an
 * idle period after the load, later still on a busy host. MEASURED (this pass, first run): a "clean"
 * tab-stop signature taken before the canvas mounted made every later case reload the page, and the
 * canvas's own cases then ran before it had mounted again — NOT DRIVEN. So the signature is read until
 * it holds still across two reads, and the canvas is waited for wherever the stage is rendered.
 */
async function crossLoad(page, query) {
  /* A load can take longer than Playwright's 30 s default on a saturated host (MEASURED: this pass's
     first full run died on one); one retry, then the error reaches the case that asked for it. */
  const url = `${APP}/${query === "" ? "" : `?${query}`}`;
  try {
    await page.goto(url, { waitUntil: "load", timeout: 90000 });
  } catch {
    await page.goto(url, { waitUntil: "load", timeout: 90000 });
  }
  await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 }).catch(() => {});
  await crossFabricSettled(page);
  /* Settled: the signature unchanged over a 700 ms window, sampled every 350 ms (it was read twice, 700 ms
     apart, after a first 700 ms wait: the same quiet window, sampled more finely, from the first moment it can
     hold — MEASURED, phase 3.5: a reload is the commonest step of this pass, and that wait was half of it). */
  let last = await page.evaluate(crossSignature);
  for (let i = 0, still = 0; i < 60 && still < 2; i += 1) {
    await page.waitForTimeout(350);
    const sig = await page.evaluate(crossSignature);
    still = sig === last ? still + 1 : 0;
    last = sig;
  }
}

/**
 * Wait (bounded) until a fabric the page shows has MOUNTED, reported its first frame and let the palette's pre-warm
 * park: after a load, and after an activation (a chain's step, crossSession's `step`) — the fabric toggle at the
 * stacked rung mounts the scene, whose status-bar control and canvas arrive later. MEASURED (phase 3.5 repair,
 * full run of the nested discovery): "Show the 3-D fabric → a tier of the fabric tree" was credited with the
 * status bar's scene control, which the TOGGLE had mounted a moment late; re-activated, the tree item revealed
 * nothing of the kind, and the case was NOT DRIVEN.
 */
async function crossFabricSettled(page) {
  await page
    .waitForFunction(
      () => {
        const stage = document.getElementById("stage");
        const shown = stage !== null && stage.getClientRects().length > 0 && document.querySelector(".app")?.getAttribute("data-fabric3d") === "on";
        return !shown || document.querySelector(".fabric3d__canvas") !== null || document.querySelector(".fabric3d__fallback") !== null;
      },
      null,
      { timeout: 30000 },
    )
    .catch(() => {});
  /* And, where a canvas mounted, until the 3-D subsystem has reported its first frame: until then the status
     bar says so ("not observed: the 3-D subsystem has not reported a frame yet", `data-tier="unknown"`), and
     when the report lands a control replaces that line. MEASURED (phase 3.5, --crossings --vp=390, reload
     reasons printed): the signature settled before the report, so the "clean" page lacked that control, every
     later read had it, and 31 of 31 family-1 cases of one unit reloaded for it. */
  await page
    .waitForFunction(() => document.querySelector(".fabric3d__canvas") === null || document.querySelector('.sb__scene[data-tier="unknown"]') === null, null, { timeout: 15000 })
    .catch(() => {});
  /* And until the palette's pre-warm, which follows the scene's convergence, has parked its frame (crossWarmSettled). */
  await crossWarmSettled(page);
}

/** Resize, and wait until the page has processed it (framesSettled) and the slowest step has landed. */
async function crossResize(page, width, height, settle = CROSS_SETTLE_MS) {
  await page.setViewportSize({ width, height });
  await framesSettled(page);
  await page.waitForTimeout(settle);
}

/**
 * One case: the marked element holds focus at `from`; cross to `to`; judge where focus is. The page is LEFT
 * at `to`: the next case starts wherever its own `from` is (a session's `fresh`), and when that is `to` — the
 * reverse crossing of the same rung pair — the arrival of this case is the start of the next, one resize each.
 * Returns false when focus never reached the element (the caller retries once from a fresh load, then
 * reports NOT DRIVEN). Focus is judged where it comes to REST: a failing read is taken again once
 * every finite animation has finished (the skip link slides in; MEASURED, one read mid-slide in a long
 * run reported it off screen while a direct probe of the same crossing had it on screen at +100 ms).
 * With a `sink` (renderCheck) the outcome is recorded there, keyed by the case, instead of judged into
 * this run's verdict.
 */
async function crossCase(page, where, label, from, to, height, sink = null) {
  const scenario = `${label} focused at ${from}px (${rungOf(from)}) → resize to ${to}px (${rungOf(to)})`;
  const loc = page.locator("[data-d3-cross]").first();
  await loc.focus().catch(() => {});
  const on = await loc.evaluate((el) => el === document.activeElement).catch(() => false);
  if (!on) return false;
  await page.keyboard.press("Shift");
  if (sink === null) {
    crossCount.cases += 1;
    crossPerCrossing.set(where, (crossPerCrossing.get(where) ?? 0) + 1);
  }
  await crossResize(page, to, height);
  const judge = async () => {
    const st = await page.evaluate(crossLanding);
    if (st.lost) return { st, failed: "focus landed on BODY" };
    if (!st.rendered) return { st, failed: `focus left on ${st.desc}, which is no longer rendered` };
    const geo = await page.evaluate(focusGeometry);
    if (geo === null) return { st, failed: "focus landed on BODY" };
    if (!geo.visible) return { st, failed: `focus on ${st.desc}: no part of it is on screen (clipped by ${geo.clippers.join(" > ") || "the viewport"})` };
    if (!geo.hitOk) return { st, failed: `focus on ${st.desc} is painted over: ${geo.hitDesc}` };
    return { st, failed: null };
  };
  let { st, failed } = await judge();
  if (failed !== null) {
    await page.evaluate(settleAnimations);
    ({ st, failed } = await judge());
  }
  if (sink !== null) sink.set(`${where} :: ${label}`, `${failed === null ? "OK" : `FAIL ${failed}`} -> ${st.desc}`);
  else if (failed !== null) {
    crossCount.lost += 1;
    sweepFail(where, `${scenario}: ${failed}`);
  } else console.log(`PASS  ${where} :: ${scenario} -> ${st.desc}`);
  return true;
}

/** Drive one case; if focus never reached its element, reload the state and try once more. */
async function crossDrive(page, where, label, from, to, height, mark, reload, sink = null) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (attempt > 0) await reload();
    if (!(await mark())) continue;
    if (await crossCase(page, where, label, from, to, height, sink)) return;
  }
  if (sink !== null) sink.set(`${where} :: ${label}`, "NOT DRIVEN");
  else sweepFail(where, `${label} at ${from}px → ${to}px: NOT DRIVEN (focus never reached the element under test, twice, the second time from a fresh load)`);
}

/** `list`, thinned to at most `cap` evenly spaced members (renderCheck's sample); whole when it fits. */
const strideOf = (list, cap) => (list.length <= cap ? list : list.filter((_, i) => i % Math.ceil(list.length / cap) === 0));

/** Elements are matched across pages and loads by what they are and their occurrence among their kind —
 *  `BUTTON.ui-cite "…"#2` — never by an index alone. */
const occurrenceKeys = (list) => {
  const seen = new Map();
  return list.map((s) => {
    const n = (seen.get(s.label) ?? 0) + 1;
    seen.set(s.label, n);
    return `${s.label}#${n}`;
  });
};

/* THE GRAIN OF THE WORK (phase 3.5: tractable). MEASURED (a full --sweep with (crossing x state) units, eight at
   once, 2026-09-29): after 37 minutes 9 of 40 units had started — a traced flow's unit alone held ~450 cases
   (its hop list, the Inspector's tabs, every surface's stops), so the pool's width was idle behind a few long
   units. The work is now cut where it is independent: one ENUMERATION per start width and page state (the same
   page for both crossings that leave that width), openers DISCOVERED in batches, and the cases in JOBS of at
   most JOB_CASES — each job on its own page, loaded fresh, finding its elements again by what they are
   (occurrenceKeys) or where the enumeration read them — so any job can run beside any other. A tab-stop job
   holds BOTH directions of a rung pair, alternating, so each case's arrival is the next one's start. */
const JOB_CASES = 24;
const SURFACE_JOB_CASES = 12;
const DISCOVERY_BATCH = 8;

/**
 * A SESSION: one page in one page state, at one viewport height, moving between the widths of its cases —
 * its load, a clean signature per width (from a load AT that width), the return to it between cases
 * (`fresh`), crash recovery (`guarded`) and opener activation. `where` names what a failure is reported against.
 */
async function crossSession(browser, width0, stateRow, { mode, sink, where, clean }) {
  const [stateName, query, prep, scope] = stateRow;
  const ctx = await geometryContext(browser, { viewport: { width: width0, height: CROSS_HEIGHT } }, mode);
  await ctx.addInitScript(() => {
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch {
      /* storage blocked: nothing persists anyway */
    }
  });
  /* A crashed renderer is replaced, not the end of the pass. MEASURED (this pass, the default run on a
     host shared by ~10 agents): eight crossings in parallel, each with a WebGL fabric, crashed one
     renderer ("page.evaluate: Target crashed"), and every later case of that crossing threw — ~200 NOT
     DRIVEN, then the whole run died on an uncaught error. Now the case that met the crash is retried
     once on a fresh page (a second failure is NOT DRIVEN, a failure like any other), and the rest of
     the crossing carries on. `crossCount.recovered` counts it, so a run that recovered says so. */
  let page = await ctx.newPage();
  const renew = async () => {
    crossCount.recovered += 1;
    const w = page.viewportSize()?.width ?? width0;
    await accountRender(page, mode);
    await page.close().catch(() => {});
    page = await ctx.newPage();
    await page.setViewportSize({ width: w, height: CROSS_HEIGHT });
  };
  const dead = (err) => /Target crashed|Target page, context or browser has been closed|Page crashed/.test(String(err));
  const fail = (what, at = where) => (sink !== null ? sink.set(`${at} :: ${what}`, "NOT DRIVEN") : sweepFail(at, what));
  const close = async () => {
    await accountRender(page, mode);
    await ctx.close().catch(() => {});
  };
  /* The state's load, at the width the page is at: the page, then (for a view state) what brings it about. */
  let present = true;
  const load = async () => {
    await crossLoad(page, query);
    if (prep !== null) present = (await prep(page)) === true;
  };
  const width = () => page.viewportSize()?.width ?? 0;
  /* The RETURN to a start width is not a case: nothing is judged there, only the signature, which is compared again
     after the full settle when it does not match at once (`settledSig`). So it waits two frames and RETURN_SETTLE_MS,
     not CROSS_SETTLE_MS (phase 3.5 repair: a surface case crossed twice, and half of its fixed wait was the return). */
  const ensure = async (w) => {
    if (width() === w) return false;
    await crossResize(page, w, CROSS_HEIGHT, RETURN_SETTLE_MS);
    return true;
  };
  /** The page's signature, read again after the rest of CROSS_SETTLE_MS when it is not `want` at once. */
  const settledSig = async (want) => {
    const now = await page.evaluate(crossSignature);
    if (want(now)) return now;
    await page.waitForTimeout(CROSS_SETTLE_MS - RETURN_SETTLE_MS);
    await framesSettled(page);
    return page.evaluate(crossSignature);
  };
  /** The CLEAN signatures of this state at each width: every one read from a settled page LOADED at that width (what
   *  a reload restores there), by any session of this run's pass — shared (`clean`), so a page may be judged clean
   *  at a width it was not loaded at (the other rung of its pair) without a load there first. A set, not one value:
   *  every settled load IS clean by definition, so two loads that differ both count. */
  const cleanSet = (w) => {
    const k = `${w}|${stateName}`;
    let s = clean.get(k);
    if (s === undefined) clean.set(k, (s = new Set()));
    return s;
  };
  const isClean = async (w) => cleanSet(w).has(await page.evaluate(crossSignature));
  let firstLoad = false;
  for (let attempt = 0; attempt < 2 && !firstLoad; attempt += 1) {
    try {
      if (attempt > 0) await renew();
      await load();
      cleanSet(width0).add(await page.evaluate(crossSignature));
      firstLoad = true;
    } catch (err) {
      if (attempt === 0 && dead(err)) continue;
      fail(`the state could not be loaded: NOT DRIVEN (${String(err).split(String.fromCharCode(10))[0]})`);
    }
  }
  if (!firstLoad) return { ok: false, close, fail };
  /* A view state is cased on the elements INSIDE its surface (the page states drive the rest). */
  const scopePath0 = scope === null ? null : await page.evaluate(crossScopePath, scope);
  if (!present || (scope !== null && scopePath0 === null)) return { ok: true, absent: true, close, fail };
  /** Reload the state at `w` (a settled load is clean by definition: its signature joins the clean set). */
  const reloadAt = async (w) => {
    await ensure(w);
    await load();
    cleanSet(w).add(await page.evaluate(crossSignature));
  };
  /* Back to the state's clean page at `w` before a case. The criterion is the pass's own, unchanged: the page's
     SIGNATURE (crossSignature: URL, tab stops, open dialogs and every control's state) equals the clean one at that
     width. What changed is how a drifted page gets back there: first the opener that drifted it is undone
     (the tab or radio it replaced selected again, the disclosure it expanded collapsed, the keyed command
     pressed again), then Escape (a popover, a dialog, the coverage panel close on it; at most two presses),
     each step followed by two frames and a signature check, and a RELOAD only when none restored it.
     MEASURED (phase 3.5, --crossings --vp=390 --state=idle, 248 cases): 11.3 min reloading whenever the
     signature drifted, 7.8 min with the Escape step (59 restored by it, 163 reloads). */
  let undoOpener = null;
  /** Back to a clean page at `w` WITHOUT a reload, when one of the steps below gets there; false when none does. */
  const restore = async (w) => {
    if (cleanSet(w).size === 0) return false;
    const resized = await ensure(w);
    await crossWarmSettled(page);
    const back = async () => {
      await framesSettled(page);
      if (!(await isClean(w))) return false;
      if (sink === null) crossCount.undone += 1;
      return true;
    };
    const o = undoOpener;
    undoOpener = null;
    if (resized ? cleanSet(w).has(await settledSig((x) => cleanSet(w).has(x))) : await isClean(w)) return true;
    /* The opener's own undo first (Escape on a tab would close the pane that holds it): the selection it
       replaced selected again (a tab, a radio); a disclosure it left expanded collapsed (a tree item or row by
       ArrowLeft, anything else by its own key again); a keyed command pressed again. Then Escape. */
    if (o !== null && o.kind === "control" && o.restore !== null && (await page.evaluate(crossMark, o.restore.path))) {
      await page.locator("[data-d3-cross]").first().focus().catch(() => {});
      await page.keyboard.press(o.restore.key);
      if (await back()) return true;
    } else if (o !== null && o.kind === "control" && (await page.evaluate(crossMarkUndoable, o.pathNow))) {
      await page.locator("[data-d3-cross]").first().focus().catch(() => {});
      await page.keyboard.press(o.key === "ArrowRight" ? "ArrowLeft" : o.key === "ArrowDown" ? "ArrowUp" : o.key);
      if (await back()) return true;
    } else if (o !== null && o.kind === "command") {
      await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : undefined));
      for (const k of o.presses) await page.keyboard.press(k);
      if (await back()) return true;
    }
    for (let i = 0; i < 2; i += 1) {
      await page.keyboard.press("Escape");
      if (await back()) return true;
    }
    return false;
  };
  const fresh = async (w) => {
    if (await restore(w)) return;
    if (sink === null) {
      crossCount.reloads += 1;
      await noteReload(w);
    }
    await reloadAt(w);
  };
  /** Why a page is reloaded: the first line its signature differs from a clean one by (the tally is printed). */
  const noteReload = async (w) => {
    const clean0 = [...cleanSet(w)][0];
    const why = clean0 === undefined || page.viewportSize()?.width !== w ? "no clean page of this width yet" : crossFirstDiff(clean0, await page.evaluate(crossSignature).catch(() => ""));
    const k = `${stateName} @${w}px: ${why}`;
    crossReloadWhy.set(k, (crossReloadWhy.get(k) ?? 0) + 1);
  };
  /* Run one case; on a crashed renderer, renew the page, reload the state and run it once more. */
  const guarded = async (label, run, at = where) => {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        if (attempt > 0) {
          await renew();
          await load();
        }
        await run();
        return;
      } catch (err) {
        if (attempt === 0 && dead(err)) continue;
        fail(`${label}: NOT DRIVEN (${String(err).split(String.fromCharCode(10))[0]})`, at);
        return;
      }
    }
  };
  /** Activate an opener on the clean page at `w`, every element rendered before it marked; false when it could not
   *  be. A control is found at the structural path the enumeration read (as this pass always found it: a clean
   *  page of the state has the same structure), else by what it is — its occurrence among this page's openers. */
  /* One step: a control (found at its recorded path, else by what it is among the candidates the step before it
     revealed — `unseenOnly` — or the page's) or a keyed command. */
  const step = async (o, unseenOnly) => {
    if (o.kind === "control") {
      const find = async () => {
        if (await page.evaluate(crossMark, o.path)) return o.path;
        const list = await page.evaluate(crossOpeners, { root: null, unseenOnly });
        const i = occurrenceKeys(list).indexOf(o.ident);
        return i >= 0 && (await page.evaluate(crossMark, list[i].path)) ? list[i].path : null;
      };
      let pathNow = await find();
      /* A control INSIDE a surface (a chain's later step) may mount after the surface does: the fabric's canvas
         and the status bar's scene control arrive when the lazily mounted scene reports its first frame. MEASURED
         (phase 3.5 repair, first full run of the nested discovery): "Show the 3-D fabric → the scene control" and
         "→ the canvas" were NOT DRIVEN on every 390 px state, found by the discovery and absent 400 ms after the
         re-activation. So such a step waits for its control (bounded) before it is judged missing. */
      for (let t = 0; pathNow === null && unseenOnly && t < 24; t += 1) {
        await page.waitForTimeout(250);
        pathNow = await find();
      }
      if (pathNow === null) return false;
      undoOpener = { ...o, pathNow, restore: await page.evaluate(crossSelectedSibling, pathNow) };
      /* What this step reveals is what was not rendered just before it (its target is marked by crossMark,
         which the seen-marking leaves alone). */
      await page.evaluate(crossMarkSeen);
      await page.locator("[data-d3-cross]").first().focus().catch(() => {});
      await page.keyboard.press(o.key);
    } else {
      await page.evaluate(crossMarkSeen);
      undoOpener = o;
      /* Pressed where a reader presses it: with focus on nothing in particular. */
      await page.evaluate(() => (document.activeElement instanceof HTMLElement ? document.activeElement.blur() : undefined));
      for (const k of o.presses) await page.keyboard.press(k);
    }
    await framesSettled(page);
    await page.waitForTimeout(400);
    /* A step that shows the fabric mounts the scene, whose controls arrive later: what it revealed is judged once
       they have (crossFabricSettled; immediate when no fabric is pending). */
    await crossFabricSettled(page);
    return true;
  };
  /** Activate an opener — or a CHAIN (a control inside the surface another opener revealed: the discovery's one
   *  level of recursion) — on the clean page at `w`, every element rendered before its LAST step marked, so what
   *  that step reveals is judged. Returns false when a step could not be found, else whether the activation
   *  NAVIGATED (changed the URL: a move to another page state, which the page states own, not a surface). */
  const activate = async (o, w) => {
    const steps = o.kind === "chain" ? o.steps : [o];
    const run = async () => {
      const before = await page.evaluate(() => location.pathname + location.search);
      await page.evaluate(crossMarkSeen);
      for (let i = 0; i < steps.length; i += 1) if (!(await step(steps[i], i > 0))) return false;
      const after = await page.evaluate(() => location.pathname + location.search).catch(() => null);
      return { navigated: after !== before };
    };
    await fresh(w);
    const r = await run();
    if (r !== false) return r;
    /* A step not found on a RESTORED page is tried once more on a LOADED one before it is judged missing: a restore
       matches the signature, and a component can keep state no attribute shows. MEASURED (phase 3.5 repair, full
       --sweep): the queue's filter combobox, after an undo and an Escape, read clean — and its next Enter no longer
       offered the suggestions the discovery had found under it (NOT DRIVEN, 24 chains); on a fresh load it offers
       them every time (probe, 3 of 3). */
    if (sink === null) {
      crossCount.reloads += 1;
      await noteReload(w);
    }
    await reloadAt(w);
    return run();
  };
  const revealedNow = () => page.evaluate(crossUnseenStops);
  return { ok: true, absent: false, page: () => page, width, scopePath: async () => (scope === null ? null : page.evaluate(crossScopePath, scope)), ensure, settledSig, reloadAt, restore, fresh, noteReload, guarded, activate, revealedNow, close, fail };
}

/**
 * The ENUMERATION of one width in one page state: its tab stops (family 1), its programmatic landings (family 3)
 * and its openers (family 2's discovery, in batches). Its tab stops and landings go to the pair registry, per
 * crossing leaving `from` (`tos`); the surfaces its discovery finds become jobs per crossing.
 */
async function crossEnumerate(browser, from, stateRow, tos, env) {
  const { mode, sample, sink, push } = env;
  const [state, , , scope] = stateRow;
  const here = `${from}px / ${state}`;
  const ats = tos.map((to) => [to, `crossing ${from}px (${rungOf(from)}) -> ${to}px (${rungOf(to)}) / ${state}`]);
  const deposited = new Set();
  const deposit = (to, items) => {
    deposited.add(to);
    pairDeposit(browser, env, stateRow, from, to, items);
  };
  const s = await crossSession(browser, from, stateRow, { mode, sink, where: ats[0][1], clean: env.clean });
  try {
    if (!s.ok) {
      for (const [, at] of ats.slice(1)) s.fail("the state could not be loaded: NOT DRIVEN", at);
      return;
    }
    if (s.absent) {
      console.log(`INFO  ${here}: the state does not exist at ${from}px (its surface is not on screen there); no case`);
      if (sink === null) for (const [to] of ats) crossAbsent.set(state, [...(crossAbsent.get(state) ?? []), `${from}->${to}`]);
      return;
    }
    const page = s.page();
    /* Family 1: every rendered tab stop of the page (of the surface, in a view state). */
    const allStops = await page.evaluate(crossStops, await s.scopePath());
    const stops = sample ? strideOf(allStops, 10) : allStops;
    /* Family 3: every programmatic landing (tabindex=-1 non-roving, named landmarks / their headings). */
    const allLandings = await page.evaluate(crossLandings, await s.scopePath());
    const landings = sample ? strideOf(allLandings, 4) : allLandings;
    console.log(
      `INFO  ${here}: ${allStops.length} tab stop(s)${scope === null ? "" : ` inside ${scope}`} and ${allLandings.length} programmatic landing(s)` +
        `${sample ? ` (render-check sample: ${stops.length} and ${landings.length})` : ""}, each crossed to ${tos.join(" and ")} px`,
    );
    if (sink === null) crossCount.landings += allLandings.length * tos.length;
    const stopKeys = occurrenceKeys(allStops);
    const landingKeys = occurrenceKeys(allLandings);
    const items = [
      ...stops.map((x) => ({ family: 1, key: stopKeys[allStops.indexOf(x)], label: x.label, path: x.path })),
      ...landings.map((x) => ({ family: 3, key: landingKeys[allLandings.indexOf(x)], label: x.label, path: x.path })),
    ];
    for (const [to] of ats) deposit(to, items);
    /* Family 2: every SURFACE a reader can open here, found by its EFFECT (independent verifier R5-V2-3: the
       hand-kept surface states and `[aria-haspopup]`-only popovers left disclosures, the coverage panel and
       the drawer at its own rung outside the denominator). Only in the page states: a view state's surface
       is already open. Each opener — every control whose ARIA contract says it reveals something
       (crossOpeners) and every keyed command of the app (crossChords) — is activated on a clean page; the
       rendered tab stops that were NOT there before are the surface it revealed, and each is a case. An
       opener that reveals nothing is counted, not cased. The dialogs a surface opens feed the modal
       denominator. */
    if (scope !== null) return;
    /* The clean page's own stops, in the form a discovery reads what an activation revealed (crossUnseenStops, with no
       element marked seen): a stop among them is not revealed by anything (crossDiscover). */
    env.cleanStops.set(
      `${from}|${state}`,
      new Set(
        (
          await page.evaluate(() => {
            for (const el of document.querySelectorAll("[data-d3-seen]")) el.removeAttribute("data-d3-seen");
          }).then(() => page.evaluate(crossUnseenStops))
        ).map((x) => `${x.path}|${x.label}`),
      ),
    );
    const controls = await page.evaluate(crossOpeners, { root: null, unseenOnly: false });
    const controlKeys = occurrenceKeys(controls);
    const chords = await crossChords(page);
    const openers = [
      ...controls.map((c, i) => ({ kind: "control", ident: controlKeys[i], path: c.path, key: c.key, label: c.label, family: c.family, members: c.members })),
      ...chords.map((c) => ({ kind: "command", ident: c.label, presses: c.presses, label: c.label, family: "command", members: 1 })),
    ];
    const tally = (list) => {
      if (sink !== null) return;
      crossCount.openersFound += list.length;
      for (const o of list) {
        const f = (crossFamilies[o.family] ??= { candidates: 0, members: 0, surfaces: 0, navigated: 0 });
        f.candidates += 1;
        f.members += o.members;
      }
    };
    tally(openers);
    /* Surfaces, in discovery order; the jobs are made when the last discovery batch (nested ones included) is in. */
    const found = [];
    const nestedSeen = new Set();
    let remaining = 0;
    const scheduleSurfaces = () => {
      /* ONE PAGE STATE, ONE SURFACE. Openers that leave the page in the SAME state — the same signature (every
         control's state, the URL, the open dialogs and the tab stops) and the same revealed stops — opened the same
         surface: the evidence rail by `e`, by `g e`, by the palette's command and by each coverage figure that
         opens it (MEASURED, 390 px idle: eight openers, one rail of nine stops). A case is its page state and its
         element, so the surface is cased once, under the first opener, and the others are counted against it. */
      const bySurface = new Map();
      for (const f of found.sort((a, b) => a.seq - b.seq)) {
        const k = [f.opened, "==", ...f.stable.map((x) => x.key)].join("\n");
        const first = bySurface.get(k);
        if (first === undefined) bySurface.set(k, f);
        else if (sink === null) {
          crossCount.sameSurface += 1;
          console.log(`INFO  ${here}: ${f.o.label} opened the same surface as ${first.o.label} (same page state): cased once`);
        }
      }
      /* WHAT IS CASED IN FULL. A surface opened by a control that ANNOUNCES what it reveals (the state family: the
         phase-3 openers and every other ARIA state, `aria-pressed` included) or by a keyed command is cased stop by
         stop, as before. A surface opened by any other control (a stateless kind, a collection's representative) or
         one level down (a control inside another surface) is cased ONE STOP PER KIND — tag, class and role, the
         revealed stops' own identity — and the kind's other stops are counted as represented by it. MEASURED (phase
         3.5 repair, full --crossings at 14 at once, every surface cased stop by stop): 16,652 cases in 85.9 min, 4,508
         of them the page's own stops re-read after a dialog's Close, and the rest over a third more than phase 3's
         8,911 — past the 60-minute budget on this host. The phase-3 denominator is kept whole; what is new is added,
         each kind of control it revealed crossed. */
      const surfaces = [...bySurface.values()].map((f) => {
        if (f.o.family === "state" || f.o.family === "command") return f;
        const kinds = new Map();
        for (const x of f.stable) if (!kinds.has(x.s.label)) kinds.set(x.s.label, x);
        if (sink === null) crossCount.representedStops += f.stable.length - kinds.size;
        return { ...f, stable: [...kinds.values()] };
      });
      for (const [to, at] of ats) {
        for (const surface of surfaces) {
          if (sink === null) crossSurfaces.set(at, (crossSurfaces.get(at) ?? 0) + 1);
          const stable = sample ? surface.stable.slice(0, 1) : surface.stable;
          /* A surface's cases are the costly ones (an activation each time the surface cannot be reused, a reload
             each time the page cannot be restored), so they go to the FRONT of the pool, in jobs of half the size:
             the cheap tab-stop jobs, which alternate directions with one resize a case, are what is left at the end.
             MEASURED (phase 3.5 repair, full --sweep): with surface jobs queued last, the final ten minutes ran a few
             device-view surface jobs at 768 px, each case a reload. */
          for (let k = 0; k < stable.length; k += SURFACE_JOB_CASES) {
            push(() => crossSurfaceJob(browser, from, to, stateRow, surface.o, stable.slice(k, k + SURFACE_JOB_CASES), env), true);
          }
        }
      }
    };
    /* ONE LEVEL OF RECURSION (QH-V1-2: the 11 disclosures inside the drawer `e` opens were never candidates): the
       controls a surface revealed are candidates too, each activated with that surface open (a chain). A control
       two openers reveal (the drawer's, by `e` and by `g e`) is one candidate, under the first. */
    let seq = 0;
    const runBatch = (batch) => {
      remaining += 1;
      push(async () => {
        try {
          const r = await crossDiscover(browser, from, stateRow, batch, env, ats[0][1]);
          for (const f of r.found) found.push({ ...f, seq: f.o.seq });
          const nested = r.nested.filter((c) => !nestedSeen.has(c.dedupe) && nestedSeen.add(c.dedupe));
          for (const c of nested) c.seq = (seq += 1);
          tally(nested);
          for (let k = 0; k < nested.length; k += DISCOVERY_BATCH) runBatch(nested.slice(k, k + DISCOVERY_BATCH));
        } finally {
          remaining -= 1;
          if (remaining === 0) scheduleSurfaces();
        }
      }, true);
    };
    for (const o of openers) o.seq = (seq += 1);
    for (let k = 0; k < openers.length; k += DISCOVERY_BATCH) runBatch(openers.slice(k, k + DISCOVERY_BATCH));
    if (remaining === 0) scheduleSurfaces();
  } finally {
    for (const [to] of ats) if (!deposited.has(to)) deposit(to, []);
    await s.close();
  }
}

/**
 * THE PAIR REGISTRY: a tab-stop job holds both directions of a rung pair in one state, alternating (A->B, B->A,
 * A->B, …), so every case's arrival is the next case's start. Each enumeration deposits its items per crossing;
 * when every direction of the pair that the plan holds has deposited, the jobs are made (a direction with no
 * partner, or the longer side's rest, runs alone: its cases then return to their start width first).
 */
function pairDeposit(browser, env, stateRow, from, to, items) {
  const [state] = stateRow;
  const a = Math.min(from, to);
  const b = Math.max(from, to);
  const rec = env.pairs.get(`${a}|${b}|${state}`);
  if (rec === undefined) throw new Error(`no pair ${a}|${b} in the plan for ${state}`);
  rec.got.push({ from, to, items });
  if (rec.got.length < rec.expect) return;
  const sides = rec.got.map((g) => g.items.map((item) => ({ from: g.from, to: g.to, item })));
  const cases = [];
  for (let i = 0; i < Math.max(...sides.map((x) => x.length)); i += 1) for (const side of sides) if (i < side.length) cases.push(side[i]);
  for (let k = 0; k < cases.length; k += JOB_CASES) {
    const chunk = cases.slice(k, k + JOB_CASES);
    env.push(() => crossStopsJob(browser, stateRow, chunk, env));
  }
}

/** Family 2's DISCOVERY for a batch of openers at `from`: what each reveals, reliably (see below); and, for an opener
 *  that is not itself nested, the candidate controls inside what it revealed (the one level of recursion). */
async function crossDiscover(browser, from, stateRow, batch, env, where) {
  const { mode, sink } = env;
  const [state] = stateRow;
  const s = await crossSession(browser, from, stateRow, { mode, sink, where, clean: env.clean });
  const found = [];
  const nested = [];
  try {
    if (!s.ok || s.absent) {
      for (const o of batch) s.fail(`the opener ${o.label}: NOT DRIVEN (the state did not load for its discovery)`);
      return { found, nested };
    }
    for (const o of batch) {
      let revealed = [];
      let activated = false;
      await s.guarded(`the opener ${o.label}`, async () => {
        activated = await s.activate(o, from);
        if (!activated) return;
        if (sink === null) crossCount.openersTried += 1;
        revealed = await s.revealedNow();
        if (sink === null) for (const name of await s.page().evaluate(crossModalNames)) crossDialogsOpened.add(name);
      });
      /* renderCheck compares what each opener revealed in each mode, not only the cases. */
      const noteDiscovery = (what) => {
        if (sink !== null) sink.set(`${from}px / ${state} :: discovery :: ${o.label}`, what);
      };
      if (!activated) {
        s.fail(`the opener ${o.label}: NOT DRIVEN (not found again on a clean page of this state)`);
        continue;
      }
      /* An activation that changed the URL moved to another PAGE STATE (a finding or a device selected, a record
         opened): what it shows is that state's, which the page states own. Counted, not cased. */
      /* An activation that changed the URL is counted, and judged like any other by what it revealed: the app keeps
         its UI state in the URL (the device pane's tabs, the Inspector), so a URL change is not "another page".
         MEASURED (phase 3.5 repair): excluding those dropped the device pane's tab surfaces phase 3 cased. */
      if (activated.navigated && sink === null) crossFamilies[o.family].navigated += 1;
      if (revealed.length === 0) {
        noteDiscovery("revealed nothing");
        continue;
      }
      /* A stop is the OPENER's only if a second activation reveals it again: one that appeared the first time
         and not the second came with something else (the status bar's scene button, mounted when the scene
         settled — MEASURED, run 1: "revealed" by a disclosure, then never again, NOT DRIVEN twice). Such stops
         are counted and named, not cased. The candidates INSIDE the surface are read on this second activation
         (every element rendered before its last step is marked, so they are exactly what it revealed). */
      let again = [];
      let inside = [];
      let opened = "";
      await s.guarded(`the opener ${o.label}, again`, async () => {
        if (await s.activate(o, from)) {
          again = await s.revealedNow();
          /* The page state it opened (see scheduleSurfaces). */
          opened = await s.page().evaluate(crossSignature);
          /* The one level of recursion goes into a surface that did NOT change the URL: one that did moved to a
             state a URL restores (a finding or device selected, a pane's tab), whose contents are a page state's —
             MEASURED (phase 3.5 repair): recursing into those too kept the discovery alone running past 30 minutes. */
          if (o.kind !== "chain" && !activated.navigated) inside = await s.page().evaluate(crossOpeners, { root: null, unseenOnly: true });
        }
      });
      const againKeys = new Set(occurrenceKeys(again));
      const keys = occurrenceKeys(revealed);
      /* A stop the CLEAN page already has is family 1's, whatever made it re-appear: closing a modal dialog makes the
         whole page under it live again (MEASURED, phase 3.5 repair: "the keyboard reference → Close dialog" and "the
         palette → Close dialog" "revealed" the page's own stops, 4,508 duplicate cases in one full run). */
      const onClean = env.cleanStops.get(`${from}|${state}`) ?? new Set();
      const stable = revealed
        .map((x, i) => ({ s: x, key: keys[i] }))
        .filter((x) => againKeys.has(x.key) && !onClean.has(`${x.s.path}|${x.s.label}`));
      const unstable = keys.filter((k) => !againKeys.has(k));
      noteDiscovery(unstable.length > 0 ? `UNSTABLE (${stable.length} reliably, ${unstable.length} once)` : `revealed ${stable.length}: ${stable.map((x) => x.key).join(", ")}`);
      if (unstable.length > 0) {
        if (sink === null) crossCount.unstable += unstable.length;
        console.log(`INFO  ${from}px / ${state}: ${o.label}: ${unstable.length} stop(s) appeared on one activation and not on the next (not the opener's; not cased): ${unstable.join(", ")}`);
      }
      if (stable.length === 0) continue;
      if (sink === null) {
        crossCount.surfaces += 1;
        crossFamilies[o.family].surfaces += 1;
      }
      console.log(`INFO  ${from}px / ${state}: ${o.label} revealed ${stable.length} tab stop(s)${inside.length > 0 ? `; ${inside.length} candidate(s) inside it` : ""}`);
      found.push({ o, stable, opened });
      const insideKeys = occurrenceKeys(inside);
      for (const [i, c] of inside.entries()) {
        const child = { kind: "control", ident: insideKeys[i], path: c.path, key: c.key, label: c.label, family: c.family, members: c.members };
        nested.push({
          kind: "chain",
          steps: [o, child],
          ident: `${o.ident} → ${child.ident}`,
          label: `${o.label} → ${c.label}`,
          family: `nested ${c.family}`,
          members: c.members,
          /* One candidate however many openers reveal it: where it is, and what it is. */
          dedupe: `${c.path}|${c.label}`,
        });
      }
    }
    return { found, nested };
  } finally {
    await s.close();
  }
}

/** The name a crossing's cases are reported under. */
const crossAt = (from, to, state) => `crossing ${from}px (${rungOf(from)}) -> ${to}px (${rungOf(to)}) / ${state}`;

/**
 * A TAB-STOP JOB: tab stops and landings (each found again on this page by its key, or its path), in both
 * directions of a rung pair. The ORDER adapts to the page, the criterion does not: every case still starts on a
 * page whose signature is a clean one of its start width. The next case is one that starts where the page is, when
 * the page is clean there; else one that starts at the pair's other width, when the page is clean THERE after the
 * resize (both through `restore`: the same undo / Escape / signature steps, never a reload); and only when neither
 * holds, a reload, at the start width with the most cases left. MEASURED (phase 3.5 repair, the rung-pair probe): a
 * crossing to the stacked rung leaves the fabric mounted (its tree, its buttons, the status bar's scene control),
 * so a 390 px page is never clean again after one — and a strict alternation reloaded before every other case,
 * where the 768 -> 390 cases can all run from the one clean 768 page and only the 390 -> 768 cases need a load.
 */
async function crossStopsJob(browser, stateRow, cases, env) {
  const { mode, sink } = env;
  const [state] = stateRow;
  const s = await crossSession(browser, cases[0].from, stateRow, { mode, sink, where: crossAt(cases[0].from, cases[0].to, state), clean: env.clean });
  try {
    if (!s.ok || s.absent) {
      for (const c of cases) s.fail(`${c.item.label} at ${c.from}px → ${c.to}px: NOT DRIVEN (the state ${s.ok ? "was not present" : "did not load"} on this job's page)`, crossAt(c.from, c.to, state));
      return;
    }
    /* The cases by start width, each queue in the order the pair registry gave it. */
    const queues = new Map();
    for (const c of cases) queues.set(c.from, [...(queues.get(c.from) ?? []), c]);
    const left = () => [...queues].filter(([, q]) => q.length > 0);
    while (left().length > 0) {
      /* Where to start the next case: here, else the pair's other width, each only when clean without a reload. */
      let start = null;
      const here = s.width();
      const order = left()
        .map(([w]) => w)
        .sort((a, b) => (a === here ? -1 : b === here ? 1 : 0));
      await s.guarded(`the start of the next case of ${crossAt(order[0], queues.get(order[0])[0].to, state)}`, async () => {
        for (const w of order) {
          if (await s.restore(w)) {
            start = w;
            return;
          }
        }
        /* No clean start without a load: reload where the most cases are left. */
        const [w] = left().sort((a, b) => b[1].length - a[1].length)[0];
        if (sink === null) {
          crossCount.reloads += 1;
          await s.noteReload(s.width());
        }
        await s.reloadAt(w);
        start = w;
      });
      if (start === null) start = left()[0][0]; /* the step itself failed (reported); the case reloads on its own */
      const { from, to, item } = queues.get(start).shift();
      const at = crossAt(from, to, state);
      await s.guarded(
        item.label,
        async () => {
          await s.fresh(from); /* clean already (above): one signature read — unless a crashed page was replaced */
          const page = s.page();
          const list = await page.evaluate(item.family === 1 ? crossStops : crossLandings, await s.scopePath());
          /* Found again by what it is; where its name is live and no longer matches, by the structural path the
             enumeration read (a path is what every earlier version of this pass marked by, reload after reload). */
          const i = occurrenceKeys(list).indexOf(item.key);
          const path = i >= 0 ? list[i].path : item.path;
          const mark = async () => s.page().evaluate(item.family === 1 ? crossMark : crossMarkLanding, path);
          await crossDrive(page, at, item.label, from, to, CROSS_HEIGHT, mark, () => s.reloadAt(from), sink);
        },
        at,
      );
    }
  } finally {
    await s.close();
  }
}

/**
 * A SURFACE JOB: one opener's revealed stops, across one crossing. The surface as the last activation left it —
 * its signature and what it revealed — is reused for the next stop when the page, back at `from`, has exactly
 * that signature (the case crossed and nothing drifted: the criterion `fresh` applies to the clean page) and the
 * stop at the recorded path is still the one named; otherwise the opener is activated again.
 */
async function crossSurfaceJob(browser, from, to, stateRow, o, stable, env) {
  const { mode, sink } = env;
  const [state] = stateRow;
  const at = crossAt(from, to, state);
  const s = await crossSession(browser, from, stateRow, { mode, sink, where: at, clean: env.clean });
  try {
    if (!s.ok || s.absent) {
      for (const { s: stop } of stable) s.fail(`revealed by ${o.label}: ${stop.label} at ${from}px → ${to}px: NOT DRIVEN (the state ${s.ok ? "was not present" : "did not load"} on this job's page)`);
      return;
    }
    let opened = null;
    for (const { s: stop, key } of stable) {
      const label = `revealed by ${o.label}: ${stop.label}`;
      await s.guarded(label, async () => {
        const mark = async () => {
          if (opened !== null) {
            const resized = await s.ensure(from);
            const page = s.page();
            await crossWarmSettled(page);
            if ((resized ? await s.settledSig((x) => x === opened.sig) : await page.evaluate(crossSignature)) === opened.sig) {
              const i = occurrenceKeys(opened.list).indexOf(key);
              if (i >= 0 && (await page.evaluate(crossMarkIfLabel, [opened.list[i].path, opened.list[i].label]))) {
                if (sink === null) crossCount.reused += 1;
                return true;
              }
            }
          }
          opened = null;
          if (!(await s.activate(o, from))) return false;
          /* A stop that mounts after its surface (the fabric's controls, once the lazily mounted scene has a frame) is
             waited for, bounded, as a chain's later step is (activate). */
          let now = await s.revealedNow();
          for (let t = 0; !occurrenceKeys(now).includes(key) && t < 24; t += 1) {
            await s.page().waitForTimeout(250);
            now = await s.revealedNow();
          }
          opened = { sig: await s.page().evaluate(crossSignature), list: now };
          const i = occurrenceKeys(now).indexOf(key);
          return i >= 0 && (await s.page().evaluate(crossMark, now[i].path));
        };
        await crossDrive(s.page(), at, label, from, to, CROSS_HEIGHT, mark, () => s.reloadAt(from), sink);
      });
    }
  } finally {
    await s.close();
  }
}

/**
 * A pool of `n` workers over a queue that TASKS MAY GROW while it runs (an enumeration queues its jobs). The
 * pool drains when the queue is empty and no task is running. A task's uncaught error is reported, never lost.
 */
const POOL_MIN_FREE_BYTES = 700 * 1024 * 1024;
const POOL_MIN_ACTIVE = 4;
function taskPool(n) {
  const queue = [];
  const waiters = [];
  let active = 0;
  const notify = () => {
    while (waiters.length > 0) waiters.shift()();
  };
  /* `first`: a task that MAKES work (an enumeration, a discovery batch) goes to the front, so every job exists
     early and the pool's width stays full to the end. MEASURED (phase 3.5 repair, full --crossings, 60.0 min): with
     one FIFO queue the discovery batches waited behind the tab-stop jobs, their surfaces' jobs were made last, and
     the final ~11 minutes ran two or three jobs at once on a host at 16% CPU. */
  const push = (task, first = false) => {
    if (first) queue.unshift(task);
    else queue.push(task);
    notify();
  };
  const drain = async () => {
    const worker = async () => {
      for (;;) {
        /* MEMORY BACKPRESSURE: a new task opens a page; on a host that other work has pushed near its memory limit a
           fourteenth page pages the whole machine out. MEASURED (phase 3.5 repair): a full --sweep that ran at ~290
           cases a minute fell to ~25 once another process took 2.7 GB and free memory read 0.3 GB. So while free
           memory is under POOL_MIN_FREE_BYTES and at least POOL_MIN_ACTIVE tasks run, no new task starts. */
        while (queue.length > 0 && active >= POOL_MIN_ACTIVE && freemem() < POOL_MIN_FREE_BYTES) await new Promise((r) => setTimeout(r, 1000));
        const task = queue.shift();
        if (task !== undefined) {
          active += 1;
          try {
            await task();
          } catch (err) {
            sweepFail("rung crossing", `a task threw: NOT DRIVEN (${String(err).split(String.fromCharCode(10))[0]})`);
          } finally {
            active -= 1;
            notify();
          }
          continue;
        }
        if (active === 0) return;
        await new Promise((r) => waiters.push(r));
      }
    };
    await Promise.all(Array.from({ length: n }, worker));
  };
  return { push, drain };
}

/** Run `tasks` (thunks) at most `n` at a time. */
async function pool(tasks, n) {
  const p = taskPool(n);
  for (const t of tasks) p.push(t);
  await p.drain();
}

/** The directed crossings between neighbouring rungs, narrowed by `only` (the --vp list). */
function crossPlan(only) {
  const plan = [];
  for (let i = 0; i + 1 < RUNG_WIDTHS.length; i += 1) {
    const [a] = RUNG_WIDTHS[i];
    const [b] = RUNG_WIDTHS[i + 1];
    for (const [from, to] of [[a, b], [b, a]]) if (!only || only.includes(from) || only.includes(to)) plan.push([from, to]);
  }
  return plan;
}

/** Every crossing of `plan` in every state of `states`, on one pool of `parallel` workers. */
async function runCrossTasks(browser, plan, states, { mode = RENDER, sample = false, sink = null, parallel = CROSS_PARALLEL, pool: shared = null } = {}) {
  /* `pool`: a pool the caller shares with other passes (runSweep) — draining it waits for them too. */
  const p = shared ?? taskPool(parallel);
  const env = { mode, sample, sink, push: p.push, pairs: new Map(), clean: new Map(), cleanStops: new Map() };
  for (const [state] of states) {
    for (const [from, to] of plan) {
      const k = `${Math.min(from, to)}|${Math.max(from, to)}|${state}`;
      const rec = env.pairs.get(k) ?? { expect: 0, got: [] };
      rec.expect += 1;
      env.pairs.set(k, rec);
    }
  }
  /* One enumeration per start width and state, serving every crossing that leaves that width. */
  const byFrom = new Map();
  for (const [from, to] of plan) byFrom.set(from, [...(byFrom.get(from) ?? []), to]);
  for (const s of states) for (const [from, tos] of byFrom) p.push(() => crossEnumerate(browser, from, s, tos, env));
  await p.drain();
}

/** The rung-crossing pass. `only` is the --vp list (or undefined). Returns whether it was in scope. */
async function runCrossings(browser, only, onlyState, pool = null) {
  const plan = crossPlan(only);
  const states = crossStates().filter(([name]) => !onlyState || name.includes(onlyState));
  console.log(
    `INFO  rung-crossing pass: one width per rung (${RUNG_WIDTHS.map(([w]) => `${w} ${rungOf(w)}`).join(", ")}; LADDER_REM), ` +
      `${plan.length} directed crossing(s)${only ? " (narrowed by --vp)" : ""}: ${plan.map(([f, t]) => `${f}->${t}`).join(", ")}; ` +
      `${states.length} state(s); viewport height ${CROSS_HEIGHT} px; jobs of at most ${JOB_CASES} cases, ${CROSS_PARALLEL} at once, render mode "${RENDER}"`,
  );
  crossCount.crossings = plan.length;
  await runCrossTasks(browser, plan, states, { pool });
  for (const [from, to] of plan) {
    const where = `crossing ${from}px (${rungOf(from)}) -> ${to}px (${rungOf(to)})`;
    const n = [...crossPerCrossing].filter(([k]) => k.startsWith(where)).reduce((s, [, c]) => s + c, 0);
    console.log(`INFO  ${where}: ${n} case(s) driven`);
    if (n === 0) sweepFail(where, "NEVER EXERCISED: no focusable element was driven across this crossing");
  }
  /* Per state: a state no crossing drove proved nothing about it (a surface absent at SOME widths is
     reported; absent at every width in the plan, or present and caseless, is a failure). */
  if (plan.length > 0) {
    /* Family 2's own denominator: the openers found and activated, and the surfaces their activation revealed.
       A pass that activated nothing, or whose openers revealed nothing anywhere, exercised no surface at all. */
    console.log(
      `INFO  rung crossing: ${crossCount.openersFound} candidate opener(s) found (every control, judged by its effect; every keyed command; one level inside each surface), ` +
        `${crossCount.openersTried} activated, ${crossCount.surfaces} revealed a surface; ${crossCount.unstable} stop(s) appeared on one activation only (not cased)`,
    );
    for (const [family, f] of Object.entries(crossFamilies).sort()) {
      console.log(
        `INFO  rung crossing / candidates, ${family}: ${f.candidates} activated (standing for ${f.members} control(s)), ${f.surfaces} revealed a surface, ${f.navigated} of them changed the URL`,
      );
    }
    for (const [k, n] of [...crossSurfaces].sort()) console.log(`INFO  ${k}: ${n} surface(s) revealed and cased`);
    /* Where the reloads went (the pass's largest cost after the cases themselves): the commonest reasons. */
    for (const [k, n] of [...crossReloadWhy].sort((a, b) => b[1] - a[1]).slice(0, 20)) console.log(`INFO  rung crossing / reloaded ${n}x: ${k}`);
    if (!onlyState && (crossCount.openersTried === 0 || crossCount.surfaces === 0)) {
      sweepFail("rung crossing / surfaces", `NEVER EXERCISED: ${crossCount.openersTried} opener(s) activated, ${crossCount.surfaces} revealed a surface`);
    }
    if (crossCount.openersTried < crossCount.openersFound) {
      sweepFail("rung crossing / surfaces", `NOT DRIVEN: ${crossCount.openersFound - crossCount.openersTried} of ${crossCount.openersFound} opener(s) found were never activated`);
    }
    if (crossCount.unreadChords.length > 0) {
      sweepFail("rung crossing / keyed commands", `NOT DRIVEN: the keyboard reference lists commands the pass could not press: ${[...new Set(crossCount.unreadChords)].join("; ")}`);
    }
    for (const [state] of states) {
      const n = [...crossPerCrossing].filter(([k]) => k.endsWith(` / ${state}`)).reduce((s, [, c]) => s + c, 0);
      const absent = crossAbsent.get(state) ?? [];
      console.log(`INFO  rung crossing / ${state}: ${n} case(s) driven${absent.length > 0 ? `; not present at the start of ${absent.join(", ")}` : ""}`);
      if (n === 0) sweepFail(`rung crossing / ${state}`, "NEVER EXERCISED: no crossing drove a case in this state");
    }
    /* The modal denominator is the source's (the modules that own a modal dialog, by the rendered primitive):
       every one must have been opened by some discovered opener. */
    console.log(`INFO  rung crossing: ${crossDialogsOpened.size} modal dialog(s) opened (${[...crossDialogsOpened].join("; ")}) of ${SOURCE_DIALOGS.length} owned by the source (${SOURCE_DIALOGS.join(", ")})`);
    if (!onlyState && crossDialogsOpened.size < SOURCE_DIALOGS.length) {
      sweepFail("rung crossing / modal dialogs", `NEVER EXERCISED: the source owns ${SOURCE_DIALOGS.length} modal dialog(s) but the discovered openers opened ${crossDialogsOpened.size}: a dialog no control or keyed command opens`);
    }
  }
  return plan.length > 0;
}

/**
 * THE RENDER MODE'S PROOF (`--render-check`): a sample of rung-crossing cases, driven in BOTH render modes on
 * the same build, must come to the same focus outcome — where focus landed, and the verdict (on <body>, not
 * rendered, not on screen, painted over, or OK). The sample takes every family: tab stops (up to ten, evenly
 * spaced), programmatic landings (up to four), and the first stop of EVERY surface the discovered openers
 * reveal — and what every opener revealed, compared as a record of its own; in the two page states "idle"
 * and "a finding selected"; over three
 * crossings that each change what is rendered — the stage collapsing (singleColumn -> stacked), the evidence
 * rail becoming a drawer (reference -> drawer), and the drawer rung giving way to one column (drawer ->
 * singleColumn). A record present in one mode only (the modes discovered different denominators) is a
 * difference too, unless the discovery's own stability rule found that opener unstable in a mode (see
 * below). Exit 0 only when at least RENDER_CHECK_MIN cases came out the same in both modes and none differs.
 */
const RENDER_CHECK_MIN = 60;
async function renderCheck(browser) {
  const w = (name) => RUNG_WIDTHS.find(([x]) => rungOf(x) === name)?.[0];
  const pairs = [
    ["singleColumn", "stacked"],
    ["reference", "drawer"],
    ["drawer", "singleColumn"],
  ]
    .map(([a, b]) => [w(a), w(b)])
    .filter(([a, b]) => a !== undefined && b !== undefined);
  const states = crossStates().filter(([name]) => name === "idle" || name === "a finding selected");
  const outcomes = { full: new Map(), suspended: new Map() };
  const half = Math.max(1, Math.floor(CROSS_PARALLEL / 2));
  console.log(`INFO  render check: ${pairs.map(([f, t]) => `${f}->${t}`).join(", ")} in ${states.map(([n]) => `"${n}"`).join(", ")}, both render modes, ${half} at once each`);
  await Promise.all(["full", "suspended"].map((mode) => runCrossTasks(browser, pairs, states, { mode, sample: true, sink: outcomes[mode], parallel: half })));
  /* Two kinds of record: what each OPENER revealed (discovery), and each CASE's focus outcome. An opener
     the discovery's own rule found UNSTABLE in a mode (a stop that appeared on one activation and not the
     next) is not the render mode's doing — the same rule leaves such stops out of the sweep's denominator
     in either mode — so a surface present in one mode only is excused exactly when its opener was unstable
     in the other; every other difference fails. */
  const keys = [...new Set([...outcomes.full.keys(), ...outcomes.suspended.keys()])].sort();
  const discoveryKey = (k) => / :: discovery :: /.test(k);
  const unstableIn = (mode, caseKey) => {
    const m = / \/ ([^/]+?) :: revealed by (.+?): /.exec(caseKey);
    const from = /^crossing (\d+)px/.exec(caseKey)?.[1];
    if (m === null || from === undefined) return false;
    return /^UNSTABLE/.test(outcomes[mode].get(`${from}px / ${m[1]} :: discovery :: ${m[2]}`) ?? "");
  };
  const differ = [];
  const excused = [];
  for (const k of keys) {
    const a = outcomes.full.get(k);
    const b = outcomes.suspended.get(k);
    if (a === b) {
      console.log(`SAME  ${k} -> ${a}`);
      continue;
    }
    const line = `${k}\n      full:      ${a ?? "(no such record)"}\n      suspended: ${b ?? "(no such record)"}`;
    const flaky = discoveryKey(k)
      ? /^UNSTABLE/.test(a ?? "") || /^UNSTABLE/.test(b ?? "")
      : (a === undefined && unstableIn("full", k)) || (b === undefined && unstableIn("suspended", k));
    (flaky ? excused : differ).push(line);
  }
  for (const e of excused) console.log(`  EXCUSED (the opener was unstable in a mode, by the discovery's own rule) ${e}`);
  const notDriven = keys.filter((k) => outcomes.full.get(k) === "NOT DRIVEN" || outcomes.suspended.get(k) === "NOT DRIVEN").length;
  console.log(
    `\nRENDER CHECK: ${[...outcomes.full.keys()].filter((k) => !discoveryKey(k)).length} case(s) with every frame drawn, ${[...outcomes.suspended.keys()].filter((k) => !discoveryKey(k)).length} with draws suspended, ` +
      `${keys.filter(discoveryKey).length} opener discovery record(s); ${keys.length} compared, ${differ.length} differ, ${excused.length} excused (an opener unstable in a mode), ` +
      `${notDriven} not driven in a mode; ${renderCount.pages} suspended page(s) suppressed ${renderCount.suppressed} draw call(s)` +
      `${renderCount.pagesNotSuspended > 0 ? `, ${renderCount.pagesNotSuspended} WITHOUT the suspension installed` : ""}.`,
  );
  for (const d of differ) console.log(`  DIFFER ${d}`);
  const sameCases = keys.filter((k) => !discoveryKey(k) && outcomes.full.get(k) !== undefined && outcomes.full.get(k) === outcomes.suspended.get(k)).length;
  const tooFew = sameCases < RENDER_CHECK_MIN;
  if (tooFew) console.log(`RENDER CHECK NEVER EXERCISED: ${sameCases} case(s) compared in both modes, fewer than ${RENDER_CHECK_MIN}`);
  return differ.length === 0 && notDriven === 0 && !tooFew && renderCount.suppressed > 0 && renderCount.pagesNotSuspended === 0;
}

/** The render mode's own line, and whether it holds: a suspended run whose pages suppressed nothing, or none of
 *  whose pages carried a fabric, did not run in the mode it names. */
function renderSummary() {
  if (RENDER !== "suspended") {
    console.log(`RENDER: every frame drawn (--render=full) on the geometry passes, as on the pixel passes.`);
    return true;
  }
  console.log(
    `RENDER: geometry passes ran with the fabric's draw calls suspended: ${renderCount.pages} page(s), ` +
      `${renderCount.suppressed} draw call(s) suppressed${renderCount.pagesNotSuspended > 0 ? `, ${renderCount.pagesNotSuspended} page(s) WITHOUT the suspension installed` : ""}; ` +
      `the pixel passes drew every frame. The mode's equivalence is --render-check's.`,
  );
  const ok = renderCount.pages > 0 && renderCount.suppressed > 0 && renderCount.pagesNotSuspended === 0;
  if (!ok) console.log("RENDER MODE NOT IN EFFECT: a geometry page ran without the suspension, or no draw was suppressed at all");
  return ok;
}

async function runSweep(browser, extraLanes = []) {
  /* `--vp=390,768` narrows a diagnostic run; a run so narrowed says so, and is not the acceptance run. */
  const only = process.argv.find((a) => a.startsWith("--vp="))?.slice(5).split(",").map(Number);
  if (only) console.log(`INFO  sweep narrowed to ${only.join(", ")} px by --vp: NOT an acceptance run`);
  /* `--state=<text>` narrows to the states whose name contains it: diagnostic only, like --vp. */
  const onlyState = process.argv.find((a) => a.startsWith("--state="))?.slice(8);
  if (onlyState) console.log(`INFO  sweep narrowed to states matching "${onlyState}" by --state: NOT an acceptance run`);
  /* ONE POOL OF CROSS_PARALLEL PAGES for every pass of the sweep (phase 3.5 repair, tractability): the sweep's
     widths, the drawer's pages and any lanes the caller adds (the default run's surface passes) go to its FRONT,
     the rung crossing's enumerations after them, and the whole is drained once. MEASURED (full --sweep, the passes
     one after another): sweep 2.0 min, drawer 6.6 min, then the crossing 49.2 — 57.8 min, the first 8.6 of them on
     at most six pages of a fourteen-page budget. Each pass keeps its own pages, its own order within a page, and
     its own verdict. */
  const shared = taskPool(CROSS_PARALLEL);
  for (const lane of extraLanes) shared.push(lane, true);
  const sweepLanes = SWEEP_VIEWPORTS.filter(([w]) => !only || only.includes(w)).map(([w, h, vp]) => async () => {
        const ctx = await geometryContext(browser, { viewport: { width: w, height: h } });
        await ctx.addInitScript(() => {
          try {
            localStorage.clear();
            sessionStorage.clear();
          } catch {
            /* storage blocked: nothing persists anyway */
          }
        });
        const page = await ctx.newPage();
        try {
          for (const [state, query, prep] of sweepStates().filter(([name]) => !onlyState || name.includes(onlyState))) await sweepState(page, `${vp} ${w}x${h}`, state, query, prep);
          await sweepJourney(page, `${vp} ${w}x${h}`);
        } finally {
          await accountRender(page);
          await ctx.close();
        }
      });
  for (const lane of sweepLanes) shared.push(lane, true);
  /* The evidence drawer: its own widths (derived from LADDER_REM) and its own resize targets. A
     `--state` narrowing that does not name it leaves it out, and says so. It measures indicator PIXELS
     (checkVisible), so it draws every frame whatever the render mode. */
  const drawerNamed = !onlyState || "evidence drawer".includes(onlyState);
  const drawerInScope = drawerNamed ? await runDrawer(browser, only, shared.push) : false;
  if (!drawerNamed) console.log(`INFO  drawer pass left out by --state="${onlyState}"`);
  /* The rung crossing: every focusable element at every rung, across every neighbouring rung. A
     `--state` narrowing applies to its states too; one that names none of them leaves it out. */
  const crossNamed = !onlyState || crossStates().some(([name]) => name.includes(onlyState));
  const crossInScope = await timed(`sweep, drawer${extraLanes.length > 0 ? ", surface passes" : ""} and rung crossing, ${CROSS_PARALLEL} pages at once`, async () => {
    if (crossNamed) return runCrossings(browser, only, onlyState, shared);
    await shared.drain();
    return false;
  });
  if (!crossNamed) console.log(`INFO  rung-crossing pass left out by --state="${onlyState}"`);
  console.log(`DRAWER: ${drawerCount.cases} case(s) driven.`);
  console.log(crossingLine());
  console.log(
    `\nSWEEP: ${sweepCount.widgets} composite widget(s) counted, ${sweepCount.stops} tab stop(s) walked, ` +
      `${sweepCount.hitTests} nine-point hit test(s), ${sweepCount.journeys} More -> Path journey(s), ` +
      `${sweepCount.operable} operable element(s) censused by behaviour (${sweepCount.operableRoleless} with no role and no tabindex), ` +
      `${sweepCount.offViewPointers} off-view pointer(s) drawn; ${sweepFails.length} failure(s).`,
  );
  for (const f of sweepFails) console.log(`  FAIL ${f.where} :: ${f.what}`);
  const renderOk = renderSummary();
  /* Zero of a denominator is a sweep that proved nothing about it. */
  /* `operableRoleless` is a breakdown, not a denominator: zero of it is the fixed state. */
  const empty = Object.entries(sweepCount).filter(([k, n]) => n === 0 && k !== "operableRoleless").map(([k]) => k);
  if (drawerInScope && drawerCount.cases === 0) empty.push("drawer cases");
  if (crossInScope && crossCount.cases === 0) empty.push("rung crossings");
  if (empty.length > 0) console.log(`SWEEP NEVER EXERCISED: ${empty.join(", ")}`);
  return sweepFails.length === 0 && empty.length === 0 && renderOk;
}

/** The rung-crossing pass's one-line account. */
const crossingLine = () =>
  `RUNG CROSSING: ${crossCount.cases} case(s) driven over ${crossCount.crossings} directed crossing(s) ` +
  `(${crossCount.openersFound} candidate opener(s) found and ${crossCount.openersTried} activated — ` +
  `${Object.entries(crossFamilies)
    .sort()
    .map(([k, f]) => `${k} ${f.candidates}/${f.members}`)
    .join(", ")} (activated/controls) — ${crossCount.surfaces} opener(s) revealed a surface, ${crossCount.sameSurface} of them the same page state as an earlier one (cased once), ${crossCount.representedStops} stop(s) of the non-announcing and nested surfaces represented by another of their kind, ` +
  `${[...crossSurfaces.values()].reduce((s, n) => s + n, 0)} surface case-set(s) driven, ${crossCount.landings} programmatic landing(s), ` +
  `${crossStates().length} page state(s), ${crossDialogsOpened.size} of ${SOURCE_DIALOGS.length} modal dialog owner(s) opened); ` +
  `${crossCount.lost} landed on <body> or out of sight; ${crossCount.recovered} crashed renderer(s) replaced; ` +
  `between cases ${crossCount.undone} page(s) restored by an undo or Escape, ${crossCount.reloads} reloaded, ${crossCount.reused} surface stop(s) reached with the surface still open; ` +
  `${crossCount.warmTimeouts} wait(s) for the palette pre-warm ran out (CROSS_WARM_WAIT_MS).`;

/** The whole run's wall time, and each timed phase's. */
function timeSummary() {
  console.log(`\nWALL TIME: ${((Date.now() - RUN_T0) / 60000).toFixed(1)} min (${phaseTimes.map(([n, ms]) => `${n} ${(ms / 60000).toFixed(1)}`).join("; ")})`);
}

/* `--render-check`: ONLY the render mode's proof (renderCheck). */
if (process.argv.includes("--render-check")) {
  const b = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  let ok = false;
  try {
    ok = await timed("render check", () => renderCheck(b));
  } finally {
    await b.close();
  }
  timeSummary();
  process.exit(ok ? 0 : 1);
}

/* `--crossings`: ONLY the rung-crossing pass (diagnostic; the sweep and the default run include it). */
if (process.argv.includes("--crossings")) {
  const b = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  let inScope = false;
  try {
    const only = process.argv.find((a) => a.startsWith("--vp="))?.slice(5).split(",").map(Number);
    const onlyState = process.argv.find((a) => a.startsWith("--state="))?.slice(8);
    inScope = await timed("rung crossing", () => runCrossings(b, only, onlyState));
  } finally {
    await b.close();
  }
  console.log(`\n${crossingLine().replace(/\.$/, `; ${sweepFails.length} failure(s).`)}`);
  for (const f of sweepFails) console.log(`  FAIL ${f.where} :: ${f.what}`);
  const renderOk = renderSummary();
  if (!inScope || crossCount.cases === 0) console.log("SWEEP NEVER EXERCISED: rung crossings");
  timeSummary();
  process.exit(inScope && crossCount.cases > 0 && sweepFails.length === 0 && renderOk ? 0 : 1);
}

if (process.argv.includes("--sweep")) {
  const b = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  let ok = false;
  try {
    ok = await runSweep(b);
  } finally {
    await b.close();
  }
  timeSummary();
  process.exit(ok ? 0 : 1);
}

/* ── run ───────────────────────────────────────────────────────────────────── */

const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
/** The rendered D1 legs (dark, light) and what each read; part of this run's exit code. */
const dialogStack = [];
/* The sweep (the composite-widget census, the whole tab order hit-tested at nine points, the drawer pass and
   the rung crossing) runs beside the surface passes. Its verdict is part of this run's exit code. */
let sweepOk = false;
try {
  const onlyVp = process.argv.find((a) => a.startsWith("--vp="))?.slice(5).split(",").map(Number);
  /* The surface passes measure indicator PIXELS, so they draw every frame. One page per width, as before. */
  const surfaceWidth = async ([w, h, vp]) => {
    const ctx = await browser.newContext({ viewport: { width: Number(w), height: Number(h) } });
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
    const page = await ctx.newPage();
    await load(page, `${APP}/`);
    await auditDialogs(page, `${vp}/idle`);
    for (const [state, enter] of STATES) {
      seenOf(page).clear();
      await reset(page);
      const entered = await enter(page);
      if (entered === "n/a") {
        console.log(`INFO  ${vp}/${state}: not present at this viewport; not driven`);
        continue;
      }
      if (entered !== true) {
        notDriven(`${vp}/${state}`, "enter the state", "could not reach it");
        continue;
      }
      const where = `${vp}/${state}`;
      await auditPopovers(page, where, enter);
      await auditTabs(page, where, enter);
      await auditFields(page, where, enter);
      await auditGrids(page, where, enter);
      if (state.startsWith("inspector")) await auditInspectorClose(page, where, enter);
    }
    await auditToasts(page, vp);
    await ctx.close();
  };
  /* The surface passes and the sweep are independent (their own pages, their own verdicts), so they run
     side by side: the default run is the sweep's time, not the sum (the tractability budget, phase 3.5). */
  /* The surface passes are lanes of the sweep's one pool (runSweep), at its front: one page per width, each keeping
     its own order; the pool's width is CROSS_PARALLEL. */
  const surfaceLanes = VIEWPORTS.filter(([vw]) => !onlyVp || onlyVp.includes(Number(vw))).map((v) => () => surfaceWidth(v));
  sweepOk = await runSweep(browser, surfaceLanes);
  /* D1, RENDERED: the dialog stack's paint order at 1280x800, dark and light, each on a fresh page after
     the app has loaded (review/palette-warm.mjs owns the procedure; it waits out the parked pre-warm and
     judges paint order, not elementFromPoint, which looks through inert dialogs in Chromium). */
  await timed("D1 dialog stack", async () => {
  for (const colorScheme of ["dark", "light"]) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme });
    const page = await ctx.newPage();
    await load(page, `${APP}/`);
    const { failures, states } = await checkPaletteOverDialog(page).catch((e) => ({
      failures: [`the procedure threw: ${String(e).split("\n")[0]}`],
      states: {},
    }));
    dialogStack.push({ leg: `1280x800 ${colorScheme}`, failures, states });
    await ctx.close();
  }
  });
} finally {
  await browser.close();
}

console.log("\nD1 dialog stack (palette over the keyboard reference), rendered:");
for (const leg of dialogStack) {
  console.log(`  ${leg.leg}: ${leg.failures.length === 0 ? "HELD" : "BROKEN — " + leg.failures.join("; ")}`);
  console.log(`    states ${JSON.stringify(leg.states)}`);
}
const dialogStackFailed = dialogStack.length !== 2 || dialogStack.some((leg) => leg.failures.length > 0);
if (dialogStackFailed) console.log("D1 DIALOG STACK FAILED (see above).");

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length} case(s), ${failed.length} failed.`);
console.log(`Driven, by kind: ${[...driven].map(([k, n]) => `${k}=${n}`).join(" ")}`);
for (const f of failed) console.log(`  FAIL ${f.surface} :: ${f.scenario} (${f.why})`);

/* The kinds the acceptance review named. Zero of one is a gap in this audit, not a pass. */
/* "drawer" since 2026-09-26: the evidence drawer's close paths, which the review found dropping focus
   to <body> while this list — and so this run — had no case for them. */
const REQUIRED = ["popover", "dialog", "tab", "find bar", "inspector", "drawer"];
const missing = REQUIRED.filter((k) => (driven.get(k) ?? 0) === 0);
if (missing.length > 0) console.log(`NOT DRIVEN AT ALL: ${missing.join(", ")}`);

/* Visibility: its own denominator, and the stops the acceptance review found invisible must have
   been checked at all — a visibility pass over zero tab panels would say nothing about them. */
const visFailed = visResults.filter((r) => !r.ok);
console.log(`\n${visResults.length} focus stop(s) checked for visibility, ${visFailed.length} not visible.`);
console.log(`Checked, by stop: ${[...visChecked].map(([k, n]) => `${k}=${n}`).join(" ")}`);
for (const f of visFailed) console.log(`  NOT VISIBLE [${f.stop}] ${f.surface} :: ${f.scenario} (${f.why})`);
const REQUIRED_VIS = ["popover initial focus", "tab panel", "tab", "returned"];
const visMissing = REQUIRED_VIS.filter((k) => (visChecked.get(k) ?? 0) === 0);
if (visMissing.length > 0) console.log(`NEVER CHECKED FOR VISIBILITY: ${visMissing.join(", ")}`);

timeSummary();
if (results.length === 0) {
  console.log("No surface was driven: the audit proved nothing.");
  process.exit(2);
}
if (!sweepOk) console.log("SWEEP FAILED: see the SWEEP block above (composite tab stops, painted-over focus, More -> Path).");
process.exit(sweepOk && !dialogStackFailed && failed.length === 0 && missing.length === 0 && visFailed.length === 0 && visMissing.length === 0 ? 0 : 1);
