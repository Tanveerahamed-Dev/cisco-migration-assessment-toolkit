/**
 * probe-a4-surface-switch.mjs — A4 (repair wave 8): replay the acceptance report's failing sequence
 * and print the selected row's rect against the queue's visible port after every step.
 *
 * Sequence (acceptance-report.md at 34bd435, A4): fresh load, queue at scrollTop 1000, orbit; click
 * F026 in the queue; pick access5, core1, L33 and access5 (canvas where a canvas pick lands, else the
 * fabric's DOM mirror); press the Path surface button; submit the flow ("Trace this flow"); double-click
 * dist1. After each step, 700 ms settle, then: F026's row rect, the queue's VISIBLE band (the grid's
 * box below its sticky header, clipped by every clipping ancestor and the viewport, trimmed above the
 * status bar), whether the row is inside it, and whether `elementFromPoint` at the row's centre lands
 * on the row (hit-testable). Also: whether the focused element (if in the grid) is on screen.
 *
 * Verdict per step: IN (fully inside the band and hit-testable), OUT, or N/A where the grid is not
 * its own scroll port (narrow layouts: the page scrolls it, and the page position is the reader's),
 * reported with the row's position relative to the grid instead. Exit 0 only if every applicable
 * step is IN; 1 on any OUT or on a step that could not be driven; 2 if nothing ran.
 *
 *   node review/probe-a4-surface-switch.mjs                 # the production preview on :4181
 *   ATLAS_URL=http://localhost:4180 node review/probe-a4-surface-switch.mjs --vp=1920,1440 [--shots=DIR]
 *   EMPTY_FLOW=1 ...                                        # submit the flow with its fields empty (the error block grows the path panel)
 *
 * Pinned in jsdom by src/panels/PriorityQueue.a4-surface-switch.test.tsx.
 */
import { chromium } from "@playwright/test";
import { awaitPaletteWarm } from "./palette-warm.mjs";

const APP = process.env.ATLAS_URL ?? "http://localhost:4181";
const VIEWPORTS = [
  [1920, 1080],
  [1440, 900],
  [768, 1024],
  [390, 844],
];
const only = process.argv.find((a) => a.startsWith("--vp="))?.slice(5).split(",").map(Number);
const shotDir = process.argv.find((a) => a.startsWith("--shots="))?.slice(8);
const TARGET = "F026";
let out = 0;
let applicable = 0;
let failures = 0;
let offscreen = 0;

const measure = (target) => {
  const grid = document.querySelector("#rail-queue .ag__grid");
  if (!grid) return { error: "no queue grid" };
  const head = grid.querySelector(".ag__head");
  const row = [...grid.querySelectorAll(".ag__row--data")].find((r) => r.querySelector('[role="rowheader"]')?.textContent?.trim().startsWith(target));
  const box = grid.getBoundingClientRect();
  let top = Math.max(box.top, head ? head.getBoundingClientRect().bottom : box.top);
  let bottom = box.bottom;
  for (let a = grid.parentElement; a && a !== document.documentElement; a = a.parentElement) {
    const oy = getComputedStyle(a).overflowY;
    if (oy === "visible" || oy === "") continue;
    if (a === document.body) continue;
    const r = a.getBoundingClientRect();
    top = Math.max(top, r.top);
    bottom = Math.min(bottom, r.bottom);
  }
  top = Math.max(top, 0);
  bottom = Math.min(bottom, innerHeight);
  const bar = document.querySelector(".app__status")?.getBoundingClientRect();
  if (bar && bar.top < bottom && bar.bottom >= bottom - 1) bottom = Math.min(bottom, bar.top);
  const ownPort = grid.scrollHeight > grid.clientHeight + 1;
  const res = { scrollTop: Math.round(grid.scrollTop), band: [Math.round(top), Math.round(bottom)], ownPort, active: null, row: null, inBand: false, hit: false, focus: null };
  if (row) {
    const r = row.getBoundingClientRect();
    res.row = [Math.round(r.top), Math.round(r.bottom)];
    res.active = row.getAttribute("data-active");
    res.inBand = r.top >= top - 1 && r.bottom <= bottom + 1;
    const h = document.elementFromPoint(Math.min(r.left + r.width / 3, innerWidth - 1), (r.top + r.bottom) / 2);
    res.hit = h !== null && row.contains(h);
    res.inGrid = [Math.round(r.top - box.top), Math.round(r.bottom - box.top)];
    const ownTop = head ? Math.max(box.top, head.getBoundingClientRect().bottom) : box.top;
    res.inOwn = r.top >= ownTop - 1 && r.bottom <= box.bottom + 1;
    res.ownBox = `${Math.round(ownTop - box.top)}-${Math.round(box.height)}`;
  }
  const a = document.activeElement;
  if (a && grid.contains(a) && a !== grid) {
    const r = a.getBoundingClientRect();
    const h = document.elementFromPoint(r.left + r.width / 2, (r.top + r.bottom) / 2);
    res.focus = { rect: [Math.round(r.top), Math.round(r.bottom)], hit: h !== null && (a === h || a.contains(h)) };
  }
  return res;
};

async function report(page, vp, step) {
  await page.waitForTimeout(700);
  const m = await page.evaluate(measure, TARGET);
  if (m.error || m.row === null) {
    failures += 1;
    console.log(`FAIL  ${vp} ${step}: ${m.error ?? `${TARGET} not rendered`}`);
    return;
  }
  let verdict;
  if (!m.ownPort) verdict = `N/A (the page scrolls the grid; ${TARGET} at ${m.inGrid.join("-")} inside the grid's box, active=${m.active})`;
  else if (m.band[1] - m.band[0] < 1) {
    /* The grid's whole port is scrolled out of the rail/page that carries it (the surface switched
       put another panel there): nothing of the queue is on screen, so the question is whether the
       row is still where the grid's OWN port shows it. Reported, not counted as IN. */
    offscreen += 1;
    verdict = `QUEUE OFF SCREEN (band empty; ${TARGET} at ${m.inGrid.join("-")} in a grid box of ${m.ownBox}, own-port ${m.inOwn ? "shows it" : "does NOT show it"})`;
    if (!m.inOwn) out += 1;
  } else {
    applicable += 1;
    const ok = m.inBand && m.hit && m.active === "yes";
    if (!ok) out += 1;
    verdict = ok ? "IN" : `OUT (inBand=${m.inBand} hit=${m.hit} active=${m.active})`;
  }
  const f = m.focus ? ` focus ${m.focus.rect.join("-")} hit=${m.focus.hit}` : "";
  console.log(`${verdict.startsWith("OUT") ? "FAIL" : "INFO"}  ${vp} ${step}: ${TARGET} ${m.row.join("-")} in band ${m.band.join("-")} scrollTop ${m.scrollTop} -> ${verdict}${f}`);
  if (shotDir) await page.screenshot({ path: `${shotDir}/a4-${vp}-${step.replace(/\W+/g, "_")}.png` });
}

/** Pick a device or link: a real canvas pick when its projection lands on the canvas, else the DOM mirror. */
async function pick(page, id, dbl = false) {
  const p = await page.evaluate((d) => {
    const s = window.__atlasScene;
    const c = document.querySelector("canvas");
    if (!s || !c || typeof s.chassisScreenBox !== "function") return null;
    const b = s.chassisScreenBox(d);
    if (!b) return null;
    const cr = c.getBoundingClientRect();
    const x = cr.left + (b.x0 + b.x1) / 2;
    const y = cr.top + (b.y0 * 0.4 + b.y1 * 0.6);
    return document.elementFromPoint(x, y) instanceof HTMLCanvasElement ? { x, y } : null;
  }, id);
  if (p) {
    if (dbl) await page.mouse.dblclick(p.x, p.y);
    else await page.mouse.click(p.x, p.y);
    const got = new URL(page.url()).searchParams.get("d");
    return `canvas (d=${got})`;
  }
  const item = page.locator(`[role="treeitem"][data-target="${id}"]`).first();
  if ((await item.count()) > 0 && (await item.isVisible())) {
    if (dbl) await item.dblclick();
    else await item.click();
    return "mirror";
  }
  /* A link on the canvas: aim at the midpoint of its two chassis boxes (the rendered cable runs
     between them); accepted only if the URL then names the link. */
  const link = await page.evaluate((l) => {
    const s = window.__atlasScene;
    const c = document.querySelector("canvas");
    const f = window.__atlasLinkEnds?.[l];
    if (!s || !c || !f) return null;
    const a = s.chassisScreenBox(f[0]);
    const b = s.chassisScreenBox(f[1]);
    if (!a || !b) return null;
    const cr = c.getBoundingClientRect();
    return { x: cr.left + (a.x0 + a.x1 + b.x0 + b.x1) / 4, y: cr.top + (a.y0 + a.y1 + b.y0 + b.y1) / 4 };
  }, id);
  if (link) {
    await page.mouse.click(link.x, link.y);
    return `canvas-link (l=${new URL(page.url()).searchParams.get("l") ?? "none"})`;
  }
  /* Narrow layouts show no canvas: the command palette is the reader's device/link entry there
     (one of A4's named entry paths). Ctrl+K, the id, Enter on the option naming it. */
  await page.keyboard.press("Control+k");
  const input = page.locator('[role="combobox"]').last();
  if ((await input.count()) === 0) return null;
  await input.fill(id);
  await page.waitForTimeout(250);
  /* The option whose LABEL is the id (a device or link row), never a finding that merely names it. */
  const at = await page.evaluate((want) => {
    const opts = [...document.querySelectorAll('[role="option"]')];
    const i = opts.findIndex((o) => {
      const l = (o.querySelector(".palette__row-label")?.textContent ?? "").trim();
      return l === want || l.startsWith(`${want} `) || l.startsWith(`${want}\u00a0`);
    });
    if (i === -1) return null;
    opts[i].setAttribute("data-a4-probe", "");
    return (opts[i].textContent ?? "").trim().slice(0, 40);
  }, id);
  if (at === null) {
    await page.keyboard.press("Escape");
    return null;
  }
  await page.locator("[data-a4-probe]").first().click();
  return `palette ("${at}")`;
}

const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
try {
  for (const [w, h] of VIEWPORTS.filter(([vw]) => !only || only.includes(vw))) {
    const vp = `${w}x${h}`;
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: "light" });
    await ctx.addInitScript(() => {
      window.__atlasExposeScene = true;
      window.__atlasLinkEnds = { L33: ["core2", "access3"] };
    });
    const page = await ctx.newPage();
    await page.goto(`${APP}/`, { waitUntil: "load" });
    await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 });
    await page.waitForFunction(() => window.__atlasScene?.stats?.().converged === true, null, { timeout: 20000 }).catch(() => {});
    /* A diagnostic probe: a pre-warm that never parks is printed, not waited through silently. */
    await awaitPaletteWarm(page).catch((e) => console.log(`palette pre-warm: ${e instanceof Error ? e.message : String(e)}`));
    await page.waitForTimeout(800);
    // The reader scrolls the queue (wheel over it, as a reader does), then orbits.
    const grid = page.locator("#rail-queue .ag__grid");
    const gb = await grid.boundingBox();
    const own = await grid.evaluate((g) => g.scrollHeight > g.clientHeight + 1);
    if (gb && own) {
      await page.mouse.move(gb.x + gb.width / 2, gb.y + Math.min(gb.height, h - gb.y) / 2);
      for (let i = 0; i < 40 && (await grid.evaluate((g) => g.scrollTop)) < 1000; i += 1) await page.mouse.wheel(0, 100);
      await grid.evaluate((g) => g.scrollTop);
    }
    const canvas = page.locator("canvas").first();
    if ((await canvas.count()) > 0 && (await canvas.isVisible())) {
      const cb = await canvas.boundingBox();
      if (cb) {
        await page.mouse.move(cb.x + cb.width * 0.5, cb.y + cb.height * 0.6);
        await page.mouse.down();
        await page.mouse.move(cb.x + cb.width * 0.56, cb.y + cb.height * 0.62, { steps: 8 });
        await page.mouse.up();
      }
    }
    // Click F026 in the queue (scroll it into the queue's view first, by the reader's wheel, if needed).
    const row = page.locator("#rail-queue .ag__row--data", { has: page.locator('[role="rowheader"]', { hasText: TARGET }) }).first();
    if ((await row.count()) === 0) {
      failures += 1;
      console.log(`FAIL  ${vp}: ${TARGET} is not in the queue`);
      await ctx.close();
      continue;
    }
    await row.scrollIntoViewIfNeeded();
    await row.locator(".pq-title, [aria-colindex='3']").first().click();
    await report(page, vp, "after clicking F026");
    for (const id of ["access5", "core1", "L33", "access5"]) {
      const how = await pick(page, id);
      if (how === null) {
        failures += 1;
        console.log(`FAIL  ${vp}: could not pick ${id} (no canvas projection, no visible mirror row)`);
      } else console.log(`INFO  ${vp}: picked ${id} via ${how}`);
      await report(page, vp, `after picking ${id}`);
    }
    // The Path surface button (in the header, or behind "More" on compact headers).
    let pathBtn = page.locator(".hdr-surface", { hasText: /^Path/ }).first();
    if ((await pathBtn.count()) === 0 || !(await pathBtn.isVisible())) {
      const more = page.locator(".hdr-more").first();
      if ((await more.count()) > 0) {
        await more.click();
        await page.waitForTimeout(200);
      }
      pathBtn = page.locator(".hdr-surface", { hasText: /^Path/ }).first();
    }
    if ((await pathBtn.count()) === 0) {
      failures += 1;
      console.log(`FAIL  ${vp}: no Path surface button`);
    } else {
      await pathBtn.click();
      await report(page, vp, "after the Path surface switch");
    }
    /* The report's flow submit selected hop 0 (core1): an actual trace. The form starts empty, so
       the example flow its own placeholders name is typed in first. Both are recorded. */
    const fields = page.locator(".pt-form input");
    const nf = await fields.count();
    for (let i = 0; i < nf; i += 1) {
      const el = fields.nth(i);
      const ph = await el.getAttribute("placeholder");
      if (!process.env.EMPTY_FLOW && ph && (await el.inputValue()) === "" && (await el.isVisible())) await el.fill(ph);
    }
    const submit = page.locator(".pt-form button[type='submit']").first();
    if ((await submit.count()) > 0 && (await submit.isVisible())) {
      await submit.click();
      await page.waitForTimeout(600);
      console.log(`INFO  ${vp}: flow submitted (hop=${new URL(page.url()).searchParams.get("hop")}, d=${new URL(page.url()).searchParams.get("d")})`);
      await report(page, vp, "after the flow submit");
    } else {
      failures += 1;
      console.log(`FAIL  ${vp}: no visible "Trace this flow" button`);
    }
    const how = await pick(page, "dist1", true);
    if (how === null) {
      failures += 1;
      console.log(`FAIL  ${vp}: could not double-click dist1`);
    } else {
      console.log(`INFO  ${vp}: double-clicked dist1 via ${how}`);
      await report(page, vp, "after double-clicking dist1");
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}
console.log(`\n${applicable} applicable step(s), ${out} OUT, ${offscreen} with the queue off screen, ${failures} not driven/failed.`);
const verdict = applicable === 0 ? "NOT RUN" : out > 0 || failures > 0 ? "FAIL" : "PASS";
console.log(`verdict: ${verdict}`);
process.exit(applicable === 0 ? 2 : out > 0 || failures > 0 ? 1 : 0);
