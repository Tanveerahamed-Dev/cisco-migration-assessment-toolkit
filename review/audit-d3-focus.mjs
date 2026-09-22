/**
 * audit-d3-focus.mjs — acceptance D3 in a real browser: no surface that closes, unmounts or is left
 * with Escape ever drops keyboard focus to <body>.
 *
 * WHY THIS EXISTS. The unit suite drives each surface in jsdom, which lays nothing out and fires no
 * native focus moves of its own, and the independent acceptance review listed as NOT EXAMINED the
 * unmount-return paths in the inspector tabs, the JSON find bar and toasts. The D3 regression it did
 * examine (snapshot popover, Tab, Escape: activeElement BODY, 2 of 2) was invisible to every test
 * that existed. So every surface this script can open is driven the way a keyboard reader drives
 * it, and `document.activeElement` is read ONE SECOND later — after React has unmounted whatever
 * closed, which is when a return to a vanished element shows up.
 *
 * SURFACES ARE DISCOVERED, NOT LISTED. Popovers and menus: every visible `[aria-haspopup]` trigger
 * on each page state. Dialogs: the capabilities bound to keys (Ctrl+K palette, `?` help). Find bars:
 * every visible `input` labelled "Search this document" in the evidence rail, across every inspector
 * tab. Inspector tabs: every `[role=tab]` in the rail, switched by keyboard so the focused panel
 * unmounts. Grids: every `[role=grid]` left with Escape. Toasts: any `[data-toast]`, `.toast` or
 * `[role=alert]` element; the count found is printed, so "none exist" is a stated observation.
 *
 * For each surface: open → Tab → Escape, and open → Escape. One line per case; exit 1 on any BODY.
 *
 *   node review/audit-d3-focus.mjs                       # the production preview on :4181
 *   ATLAS_URL=http://localhost:4180 node review/audit-d3-focus.mjs
 */
import { chromium } from "@playwright/test";

const APP = process.env["ATLAS_URL"] ?? "http://localhost:4181";
const SETTLE_MS = 1000;
const VIEWPORTS = [
  [1920, 1080, "wide"],
  [1000, 800, "compact"], // below the header's 1024px breakpoint: the "More" popover exists
];

const results = [];
const record = (surface, scenario, active) => {
  const ok = active.tag !== "BODY" && active.tag !== "NONE";
  results.push({ surface, scenario, ok, active });
  console.log(`${ok ? "PASS" : "FAIL"}  ${surface} :: ${scenario} -> ${active.desc}`);
};

const describeActive = () => {
  const a = document.activeElement;
  if (a === null) return { tag: "NONE", desc: "null" };
  const name = a.getAttribute("aria-label") ?? (a.textContent ?? "").trim().slice(0, 40);
  const cls = typeof a.className === "string" ? a.className.split(" ")[0] : "";
  return { tag: a.tagName, desc: `${a.tagName}${a.id ? `#${a.id}` : ""}${cls ? `.${cls}` : ""} "${name}"` };
};

async function settled(page) {
  await page.waitForTimeout(SETTLE_MS);
  return page.evaluate(describeActive);
}

/** Close anything left open and park focus on a stable start (the Findings surface button). */
async function reset(page) {
  for (let i = 0; i < 3; i += 1) await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
}

async function load(page, url) {
  await page.goto(url, { waitUntil: "load" });
  await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(2000);
}

/** Stable handle for the n-th element matching a selector at the time of the call. */
const nth = (page, sel, i) => page.locator(sel).nth(i);

async function visibleCount(page, sel) {
  return page.evaluate(
    (s) => [...document.querySelectorAll(s)].filter((el) => el.getClientRects().length > 0).length,
    sel,
  );
}

async function labelOf(loc) {
  return loc.evaluate((el) => (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40));
}

/* ── popovers and menus: every [aria-haspopup] trigger ─────────────────────── */
async function auditPopovers(page, where) {
  const sel = "[aria-haspopup]:not([disabled])";
  const n = await page.locator(sel).count();
  let driven = 0;
  for (let i = 0; i < n; i += 1) {
    const t = nth(page, sel, i);
    if (!(await t.isVisible().catch(() => false))) continue;
    const name = `${where} popover "${await labelOf(t)}"`;
    driven += 1;
    for (const scenario of ["open → Tab → Escape", "open → Escape"]) {
      await reset(page);
      await t.scrollIntoViewIfNeeded().catch(() => {});
      await t.focus();
      await page.keyboard.press("Enter");
      await page.waitForTimeout(200);
      if (scenario.includes("Tab")) await page.keyboard.press("Tab");
      await page.keyboard.press("Escape");
      record(name, scenario, await settled(page));
    }
  }
  return driven;
}

/* ── dialogs bound to keys ─────────────────────────────────────────────────── */
async function auditDialogs(page, where) {
  const openers = [
    ["command palette (Ctrl+K)", "Control+k"],
    ["keyboard reference (?)", "Shift+Slash"],
  ];
  for (const [label, chord] of openers) {
    for (const scenario of ["open → Tab → Escape", "open → Escape"]) {
      await reset(page);
      /* Start from a real control so there is an invoker to return to, as a reader would. */
      await page.locator(".hdr-surface").first().focus().catch(() => {});
      await page.keyboard.press(chord);
      await page.waitForTimeout(300);
      const opened = await visibleCount(page, '[role="dialog"]');
      if (scenario.includes("Tab")) await page.keyboard.press("Tab");
      await page.keyboard.press("Escape");
      record(`${where} dialog ${label}${opened === 0 ? " [did not open]" : ""}`, scenario, await settled(page));
    }
  }
}

/* ── grids left with Escape ────────────────────────────────────────────────── */
async function auditGrids(page, where) {
  const grids = page.locator('[role="grid"]');
  const n = await grids.count();
  for (let i = 0; i < n; i += 1) {
    const g = grids.nth(i);
    if (!(await g.isVisible().catch(() => false))) continue;
    const name = `${where} grid "${await g.getAttribute("aria-label")}"`;
    for (const scenario of ["cell → Escape", "cell → ArrowDown → Escape"]) {
      await reset(page);
      const cell = g.locator('[tabindex="0"]').first();
      if ((await cell.count()) === 0) continue;
      await cell.focus();
      if (scenario.includes("ArrowDown")) await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Escape");
      record(name, scenario, await settled(page));
    }
  }
}

/* ── the evidence rail: inspector tabs and the JSON find bar ───────────────── */
async function auditRail(page, where) {
  const tabSel = '#rail-evidence [role="tab"]';
  const nTabs = await page.locator(tabSel).count();
  for (let i = 0; i < nTabs; i += 1) {
    const tab = nth(page, tabSel, i);
    if (!(await tab.isVisible().catch(() => false))) continue;
    const tname = await labelOf(tab);

    /* Tab switch by keyboard with focus INSIDE the outgoing panel's control: the panel unmounts. */
    await reset(page);
    await tab.click();
    await page.waitForTimeout(250);
    const inner = page.locator('#rail-evidence [role="tabpanel"] button:visible, #rail-evidence [role="tabpanel"] input:visible').first();
    if ((await inner.count()) > 0) {
      await inner.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Escape");
      record(`${where} inspector tab "${tname}"`, "panel control → Shift+Tab → Escape", await settled(page));
      await tab.click();
      await page.waitForTimeout(150);
      await inner.focus().catch(() => {});
      await page.keyboard.press("Escape");
      record(`${where} inspector tab "${tname}"`, "panel control → Escape", await settled(page));
    }
    await tab.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Escape");
    record(`${where} inspector tab "${tname}"`, "tab → ArrowRight (panel unmounts) → Escape", await settled(page));

    /* Every find bar this tab shows. */
    await tab.click();
    await page.waitForTimeout(250);
    const fbCount = await page.locator('#rail-evidence input:visible').count();
    for (let k = 0; k < fbCount; k += 1) {
      const fb = page.locator("#rail-evidence input:visible").nth(k);
      const lbl = await fb.evaluate((el) => el.labels?.[0]?.textContent?.trim() ?? el.getAttribute("aria-label") ?? "input");
      if (!/search/i.test(lbl)) continue;
      for (const scenario of ["type → Tab → Escape", "type → Escape"]) {
        await reset(page);
        await tab.click().catch(() => {});
        await fb.focus().catch(() => {});
        await page.keyboard.type("up");
        await page.keyboard.press("Enter");
        if (scenario.includes("Tab")) await page.keyboard.press("Tab");
        await page.keyboard.press("Escape");
        record(`${where} find bar "${lbl}" (tab "${tname}")`, scenario, await settled(page));
      }
    }
  }
  return nTabs;
}

/* ── toasts ─────────────────────────────────────────────────────────────────── */
async function auditToasts(page, where) {
  const sel = '[data-toast], .toast, [role="alert"]';
  /* Copy actions are the one place a toast would conventionally appear; drive one and look. */
  const copy = page.locator('button[aria-label^="Copy"]:visible').first();
  if ((await copy.count()) > 0) {
    await reset(page);
    await copy.focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(200);
  }
  const n = await visibleCount(page, sel);
  console.log(`INFO  ${where} toasts: ${n} toast element(s) found after a copy action (${sel})`);
  if (n > 0) {
    await page.locator(sel).first().focus().catch(() => {});
    await page.keyboard.press("Escape");
    record(`${where} toast`, "focus → Escape", await settled(page));
  }
}

const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
try {
  for (const [w, h, vp] of VIEWPORTS) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } });
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
    const page = await ctx.newPage();
    await load(page, `${APP}/`);
    await auditPopovers(page, `${vp}/idle`);
    await auditDialogs(page, `${vp}/idle`);
    await auditGrids(page, `${vp}/idle`);

    /* Select a finding from the queue so the evidence rail and its tabs exist. */
    await reset(page);
    const row = page.locator("#rail-queue .ag__row--data").first();
    if ((await row.count()) > 0) {
      await row.click();
      await page.waitForTimeout(800);
    }
    /* And a device, whose inspector carries the JSON view. */
    const device = page.locator("#rail-evidence button", { hasText: /^[A-Za-z][\w.-]*\d/ }).first();
    const tabsFinding = await auditRail(page, `${vp}/finding`);
    await auditPopovers(page, `${vp}/finding`);
    if ((await device.count()) > 0) {
      await reset(page);
      await device.click().catch(() => {});
      await page.waitForTimeout(800);
      await auditRail(page, `${vp}/device`);
      await auditPopovers(page, `${vp}/device`);
    }
    console.log(`INFO  ${vp}: ${tabsFinding} inspector tab(s) on the finding state`);
    await auditToasts(page, vp);
    await ctx.close();
  }
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length} case(s), ${failed.length} landed on BODY.`);
for (const f of failed) console.log(`  FAIL ${f.surface} :: ${f.scenario}`);
if (results.length === 0) {
  console.log("No surface was driven: the audit proved nothing.");
  process.exit(2);
}
process.exit(failed.length === 0 ? 0 : 1);
