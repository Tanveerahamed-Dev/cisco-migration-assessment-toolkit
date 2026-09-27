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
 *                                                        # nine points, More -> Path, and the evidence
 *                                                        # drawer pass (its open/close/resize cases)
 *
 *   node review/audit-d3-focus.mjs --vp=390              # any mode, narrowed to the listed widths —
 *                                                        # diagnostic only, never the acceptance run
 *   node review/audit-d3-focus.mjs --sweep --state=off-view   # the sweep narrowed to the states whose
 *                                                        # name contains the text — diagnostic only
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
 * The default run is the sweep, then the surface passes below at all of those widths. The
 * visibility hit test samples NINE points of the focused element's visible part (focusGeometry);
 * until 2026-09-24 it sampled the centre only, and the surface passes never drove 768 or 390.
 *
 * Exit 0: every case driven, none on BODY, and every focus stop visible. Exit 1: a case landed on
 * BODY or did not run, a focus stop was not visible, or a required kind was never driven or never
 * checked for visibility. Exit 2: nothing was driven at all.
 */
import { readFileSync } from "node:fs";
import { chromium } from "@playwright/test";
import ts from "typescript";

const APP = process.env["ATLAS_URL"] ?? "http://localhost:4181";
const SETTLE_MS = 1000;

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
const seen = new Set();

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
    if (seen.has(id)) continue;
    seen.add(id);
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
async function paletteToggle(page) {
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(300);
  await page.keyboard.type(PALETTE_TOGGLE);
  await page.waitForTimeout(300);
  const top = await page.evaluate(() => {
    const input = document.querySelector('[role="dialog"] [role="combobox"]');
    const id = input?.getAttribute("aria-activedescendant");
    return (id ? document.getElementById(id)?.textContent : "") ?? "";
  });
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
  } else if (!(await paletteToggle(page))) return "the palette's top row was not the evidence toggle";
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
  if (notOpened !== null) return drawerResult(where, scenario, false, `NOT DRIVEN: ${notOpened}`);
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
    if (!(await paletteToggle(page))) return drawerResult(where, scenario, false, "NOT DRIVEN: the palette's top row was not the evidence toggle");
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
async function runDrawer(browser, only) {
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
  /* One page per width, in parallel: most of a case is waiting (a load, the settle). */
  await Promise.all(
    plan.map(async ([w, cases, reducedMotion]) => {
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
    }),
  );
  return plan.length > 0;
}

async function runSweep(browser) {
  /* `--vp=390,768` narrows a diagnostic run; a run so narrowed says so, and is not the acceptance run. */
  const only = process.argv.find((a) => a.startsWith("--vp="))?.slice(5).split(",").map(Number);
  if (only) console.log(`INFO  sweep narrowed to ${only.join(", ")} px by --vp: NOT an acceptance run`);
  /* `--state=<text>` narrows to the states whose name contains it: diagnostic only, like --vp. */
  const onlyState = process.argv.find((a) => a.startsWith("--state="))?.slice(8);
  if (onlyState) console.log(`INFO  sweep narrowed to states matching "${onlyState}" by --state: NOT an acceptance run`);
  for (const [w, h, vp] of SWEEP_VIEWPORTS.filter(([w]) => !only || only.includes(w))) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    await ctx.addInitScript(() => {
      try {
        localStorage.clear();
        sessionStorage.clear();
      } catch {
        /* storage blocked: nothing persists anyway */
      }
    });
    const page = await ctx.newPage();
    for (const [state, query, prep] of sweepStates().filter(([name]) => !onlyState || name.includes(onlyState))) await sweepState(page, `${vp} ${w}x${h}`, state, query, prep);
    await sweepJourney(page, `${vp} ${w}x${h}`);
    await ctx.close();
  }
  /* The evidence drawer: its own widths (derived from LADDER_REM) and its own resize targets. A
     `--state` narrowing that does not name it leaves it out, and says so. */
  const drawerNamed = !onlyState || "evidence drawer".includes(onlyState);
  const drawerInScope = drawerNamed ? await runDrawer(browser, only) : false;
  if (!drawerNamed) console.log(`INFO  drawer pass left out by --state="${onlyState}"`);
  console.log(`DRAWER: ${drawerCount.cases} case(s) driven.`);
  console.log(
    `\nSWEEP: ${sweepCount.widgets} composite widget(s) counted, ${sweepCount.stops} tab stop(s) walked, ` +
      `${sweepCount.hitTests} nine-point hit test(s), ${sweepCount.journeys} More -> Path journey(s), ` +
      `${sweepCount.operable} operable element(s) censused by behaviour (${sweepCount.operableRoleless} with no role and no tabindex), ` +
      `${sweepCount.offViewPointers} off-view pointer(s) drawn; ${sweepFails.length} failure(s).`,
  );
  for (const f of sweepFails) console.log(`  FAIL ${f.where} :: ${f.what}`);
  /* Zero of a denominator is a sweep that proved nothing about it. */
  /* `operableRoleless` is a breakdown, not a denominator: zero of it is the fixed state. */
  const empty = Object.entries(sweepCount).filter(([k, n]) => n === 0 && k !== "operableRoleless").map(([k]) => k);
  if (drawerInScope && drawerCount.cases === 0) empty.push("drawer cases");
  if (empty.length > 0) console.log(`SWEEP NEVER EXERCISED: ${empty.join(", ")}`);
  return sweepFails.length === 0 && empty.length === 0;
}

if (process.argv.includes("--sweep")) {
  const b = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  let ok = false;
  try {
    ok = await runSweep(b);
  } finally {
    await b.close();
  }
  process.exit(ok ? 0 : 1);
}

/* ── run ───────────────────────────────────────────────────────────────────── */

const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
/* The sweep runs first, at all five widths: the composite-widget census and the whole tab order
   hit-tested at nine points. Its verdict is part of this run's exit code. */
let sweepOk = false;
try {
  sweepOk = await runSweep(browser);
  const onlyVp = process.argv.find((a) => a.startsWith("--vp="))?.slice(5).split(",").map(Number);
  for (const [w, h, vp] of VIEWPORTS.filter(([vw]) => !onlyVp || onlyVp.includes(Number(vw)))) {
    const ctx = await browser.newContext({ viewport: { width: Number(w), height: Number(h) } });
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
    const page = await ctx.newPage();
    await load(page, `${APP}/`);
    await auditDialogs(page, `${vp}/idle`);
    for (const [state, enter] of STATES) {
      seen.clear();
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
  }
} finally {
  await browser.close();
}

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

if (results.length === 0) {
  console.log("No surface was driven: the audit proved nothing.");
  process.exit(2);
}
if (!sweepOk) console.log("SWEEP FAILED: see the SWEEP block above (composite tab stops, painted-over focus, More -> Path).");
process.exit(sweepOk && failed.length === 0 && missing.length === 0 && visFailed.length === 0 && visMissing.length === 0 ? 0 : 1);
