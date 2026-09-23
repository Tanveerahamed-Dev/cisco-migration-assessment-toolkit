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
 *
 * Exit 0: every case driven, none on BODY, and every focus stop visible. Exit 1: a case landed on
 * BODY or did not run, a focus stop was not visible, or a required kind was never driven or never
 * checked for visibility. Exit 2: nothing was driven at all.
 */
import { chromium } from "@playwright/test";

const APP = process.env["ATLAS_URL"] ?? "http://localhost:4181";
const SETTLE_MS = 1000;
const VIEWPORTS = [
  [1920, 1080, "wide"],
  [1440, 900, "desktop"], // the acceptance review's 1440 measurement of the snapshot popover
  [1000, 800, "compact"], // below the header's 1024px breakpoint: the "More" popover exists
];

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
  const cx = (vis.l + vis.r) / 2;
  const cy = (vis.t + vis.b) / 2;
  const hit = document.elementFromPoint(cx, cy);
  const hitOk = hit !== null && (hit === a || a.contains(hit));
  const hitCls = hit && typeof hit.className === "string" ? hit.className.split(" ")[0] : "";
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
    hitDesc: hit === null ? "nothing" : `${hit.tagName}${hitCls ? `.${hitCls}` : ""}`,
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
  if (!geo.hitOk) return fail(`elementFromPoint at the centre of its visible box ${JSON.stringify(geo.vis)} is ${geo.hitDesc}`);
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
async function ensureDeviceView(page) {
  if (!(await ensureFinding(page))) return false;
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

async function ensureInspector(page) {
  if ((await page.locator("#inspector").count()) > 0) return true;
  if (!(await ensureFinding(page))) return false;
  const cell = page.locator('#rail-queue [role="grid"] [tabindex="0"]').first();
  if ((await cell.count()) === 0) return false;
  await cell.focus();
  await page.keyboard.press("i");
  await page.waitForTimeout(400);
  return (await page.locator("#inspector").count()) > 0;
}

/** The Inspector opened from a citation affordance — the path `openInspector` records an origin for. */
async function ensureInspectorFromCite(page) {
  if ((await page.locator("#inspector").count()) > 0) return true;
  if (!(await ensureFinding(page))) return false;
  const cite = page.locator("#rail-evidence button.ui-cite:visible").first();
  if ((await cite.count()) === 0) return (await page.locator("#rail-evidence").isVisible()) ? false : "n/a";
  await cite.focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);
  return (await page.locator("#inspector").count()) > 0;
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
      await t.focus();
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
    await tab.focus();
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
    await tab.focus();
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
    await inner.focus();
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
        await fb.focus();
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
      await f.focus();
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
      await cell.focus();
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
    ["close button → Enter", async () => {
      await page.locator('#inspector button[aria-label="Close the inspector"]').focus();
      await checkVisible(page, "inspector control", name, "close button → Enter");
      await page.keyboard.press("Enter");
    }],
    ["tab → i (toggles it closed from inside)", async () => {
      await page.locator('#inspector [role="tab"][aria-selected="true"]').focus();
      await page.keyboard.press("i");
    }],
    ["tab → Escape", async () => {
      await page.locator('#inspector [role="tab"][aria-selected="true"]').focus();
      await page.keyboard.press("Escape");
    }],
  ];
  for (const [scenario, act] of cases) {
    await reset(page);
    if ((await enter(page)) !== true) {
      notDriven(name, scenario, "the Inspector did not open");
      continue;
    }
    await act();
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
  await copy.focus();
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

/* ── run ───────────────────────────────────────────────────────────────────── */

const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
try {
  for (const [w, h, vp] of VIEWPORTS) {
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
const REQUIRED = ["popover", "dialog", "tab", "find bar", "inspector"];
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
process.exit(failed.length === 0 && missing.length === 0 && visFailed.length === 0 && visMissing.length === 0 ? 0 : 1);
