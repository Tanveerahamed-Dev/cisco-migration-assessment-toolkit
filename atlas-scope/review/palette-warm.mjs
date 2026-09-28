/**
 * palette-warm.mjs — the one wait every settle-gated harness takes for the command palette's pre-warm.
 *
 * After the scene converges, `src/app/CommandPalette.tsx` draws the palette's frame ONCE at opacity
 * 0.001 for at least WARM_MIN_HOLD_MS and WARM_HOLD_FRAMES presented frames (that raster carries a
 * one-time GPU program compile, measured at ~120 ms), then PARKS it (visibility:hidden, inert, no
 * roles) until the first Ctrl+K. It publishes its phase on `<html data-palette-warm>`:
 *   waiting | scheduled | mounted            — still ahead of, or inside, the drawn window;
 *   done | unpresented | superseded          — terminal: nothing more is drawn by the pre-warm.
 * A capture taken inside the drawn window can differ by one 8-bit step, and a timed action taken
 * inside it pays the compile. So a harness that waits for the scene to settle before photographing
 * or timing anything also waits for a terminal pre-warm phase. `src/core/palette-warm-harness.test.ts`
 * derives that class from the harness sources (every one that reads the scene's `converged`) and
 * holds each to this module, and pins PALETTE_WARM_TERMINAL to the component's own state type.
 *
 * NOT in the class, on purpose: `audit-e5-coldload.mjs` (the pre-warm is part of the cold load it
 * measures) and `measure-inp.mjs` (it records the phase at every press and reports overlapping reps
 * apart rather than waiting them away).
 *
 * The wait is bounded (15 s by default) and FAILS LOUDLY with the phase it last saw: a pre-warm that
 * never reaches a terminal phase is a finding, never silently photographed through.
 */

import { pathToFileURL } from "node:url";

/** The phases after which the pre-warm draws nothing more. */
export const PALETTE_WARM_TERMINAL = Object.freeze(["done", "unpresented", "superseded"]);

/** Default bound on the wait, in ms. */
export const PALETTE_WARM_WAIT_MS = 15000;

/**
 * Wait until `<html data-palette-warm>` reads a terminal phase. Throws, naming the last phase seen
 * (or "absent"), when it does not within `timeoutMs`.
 * @param {import("@playwright/test").Page} page
 * @param {number} [timeoutMs]
 * @returns {Promise<string>} the terminal phase reached
 */
export async function awaitPaletteWarm(page, timeoutMs = PALETTE_WARM_WAIT_MS) {
  const terminal = [...PALETTE_WARM_TERMINAL];
  try {
    const handle = await page.waitForFunction(
      (t) => {
        const s = document.documentElement.dataset.paletteWarm;
        return s !== undefined && t.includes(s) ? s : false;
      },
      terminal,
      { timeout: timeoutMs },
    );
    return String(await handle.jsonValue());
  } catch (err) {
    const seen = await page
      .evaluate(() => document.documentElement.dataset.paletteWarm ?? "absent")
      .catch(() => "unreadable");
    throw new Error(
      `the command palette's pre-warm did not reach a terminal phase (${terminal.join("/")}) within ` +
        `${timeoutMs} ms; last phase: ${seen} (${err instanceof Error ? err.message.split("\n")[0] : String(err)})`,
    );
  }
}

/* ── the parked palette opens ON TOP (acceptance D1, WCAG 2.4.11; verifier R6 round 1, V4) ─────────
 *
 * The pre-warm parks the palette's frame in <body> long before its first open. MEASURED (verifier
 * round 2, E2/E3, 2026-09-27, release build, 1280x800): with the keyboard reference open, the first
 * Ctrl+K drew that parked palette UNDER the reference, its search box focused and out of sight, and one
 * Escape closed both. The dialog stack (src/ui/primitives.tsx) now decides paint order from the order
 * dialogs were opened; its jsdom sweeps pin attributes, and this is the RENDERED half: the procedure a
 * browser audit runs (review/audit-d3-focus.mjs is its intended durable caller) and a CLI that runs it
 * on its own.
 *
 * PAINT ORDER, NOT HIT TESTING. Chromium does not hit-test inert nodes, so `elementFromPoint` looks
 * straight THROUGH an inert dialog painted over the focused control — a probe built that way passed on
 * the broken build. Every dialog scrim and panel covering the focused control's centre (body children,
 * fixed, in the root stacking context) is ranked by computed z-index, then DOM order.
 */

/**
 * The box painted on top among `boxes` (each `{ z, index }`: computed z-index and DOM order among the
 * body's children), or null when there is none. A later DOM position wins a z-index tie. Pure.
 * @template {{ z: number, index: number }} B
 * @param {readonly B[]} boxes
 * @returns {B | null}
 */
export function topmostByPaint(boxes) {
  let top = null;
  for (const b of boxes) if (top === null || b.z > top.z || (b.z === top.z && b.index > top.index)) top = b;
  return top;
}

/** In the page: the focused control, and every visible dialog scrim/panel covering its centre. */
const STACK_STATE = () => {
  const a = document.activeElement;
  const body = [...document.body.children];
  const dialogs = [...document.querySelectorAll('.ui-dialog[role="dialog"]')].map((p) => ({
    cls: String(p.className),
    layer: p.getAttribute("data-dialog-layer"),
    inert: p.closest("[inert]") !== null,
    insideInert: p.querySelectorAll("[inert]").length,
  }));
  let covering = [];
  if (a && a !== document.body) {
    const r = a.getBoundingClientRect();
    const x = r.left + Math.min(r.width / 2, 20);
    const y = r.top + r.height / 2;
    covering = body
      .filter((el) => el.matches(".ui-dialog, .ui-dialog__scrim"))
      .filter((el) => getComputedStyle(el).visibility !== "hidden" && Number(getComputedStyle(el).opacity) > 0.01)
      .filter((el) => {
        const b = el.getBoundingClientRect();
        return x >= b.left && x <= b.right && y >= b.top && y <= b.bottom;
      })
      .map((el) => ({ label: `${el.tagName.toLowerCase()}.${el.className}`, z: Number(getComputedStyle(el).zIndex) || 0, index: body.indexOf(el), holdsFocus: el.contains(a) }));
  }
  return {
    active: a ? `${a.tagName.toLowerCase()}.${a.className}` : null,
    activeIn: a?.closest(".ui-dialog")?.className ?? null,
    activeInert: a ? a.closest("[inert]") !== null : null,
    covering,
    dialogs,
    layers: document.querySelectorAll("[data-dialog-layer]").length,
    inertOutsidePrewarm: [...document.querySelectorAll("[inert]")].filter((e) => !e.closest("[data-dialog-prewarm]")).length,
  };
};

/**
 * Whether the focused control is inside a dialog whose class names `want`, live, and inside the box
 * painted on top of every dialog box covering it. Pure over a STACK_STATE reading.
 * @param {{ covering: { z: number, index: number, holdsFocus: boolean }[], activeInert: boolean | null, activeIn: string | null }} s
 * @param {string} want
 */
export function focusedOnTop(s, want) {
  const top = topmostByPaint(s.covering);
  return top !== null && top.holdsFocus && s.activeInert === false && (s.activeIn ?? "").split(/\s+/).includes(want);
}

/**
 * The D1 procedure on a loaded app page: wait for the palette's frame to park, open the keyboard
 * reference with a click, press the FIRST Ctrl+K over it, then Escape once, then a second Ctrl+K, then
 * close everything. Returns every failed condition, each in words ([] when the stack held), and the
 * states it read.
 * @param {import("@playwright/test").Page} page
 * @returns {Promise<{ failures: string[], states: Record<string, unknown> }>}
 */
export async function checkPaletteOverDialog(page) {
  const failures = [];
  const states = {};
  states.warm = await awaitPaletteWarm(page, 90000);
  states.parked = await page.evaluate(() => document.querySelector('.ui-dialog[data-dialog-prewarm="parked"]') !== null);
  if (!states.parked) failures.push(`the palette's frame was not parked before the first Ctrl+K (pre-warm ${states.warm}), so the parked open was not tested`);
  await page.getByRole("button", { name: "Keyboard reference" }).first().click();
  await page.waitForSelector('.ui-dialog.kb-help[role="dialog"]');
  await page.keyboard.press("Control+k");
  await page.waitForSelector('.ui-dialog.palette[role="dialog"]');
  await page.waitForTimeout(400);
  const first = (states.firstOpenOverHelp = await page.evaluate(STACK_STATE));
  if (!focusedOnTop(first, "palette"))
    failures.push(`first Ctrl+K over the keyboard reference: the focused control is not the palette's, live, on top (top: ${JSON.stringify(topmostByPaint(first.covering))})`);
  if (first.dialogs.some((d) => /\bpalette\b/.test(d.cls) && d.insideInert > 0)) failures.push("first Ctrl+K: a node inside the open palette is inert");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  const back = (states.afterOneEscape = await page.evaluate(STACK_STATE));
  if (back.dialogs.length !== 1) failures.push(`one Escape left ${back.dialogs.length} dialog(s) open; it must close the palette alone`);
  if (!focusedOnTop(back, "kb-help")) failures.push("after one Escape: focus is not back in the keyboard reference, live and on top");
  if (back.inertOutsidePrewarm === 0) failures.push("after one Escape: the page behind the keyboard reference, still open, is not inert");
  await page.keyboard.press("Control+k");
  await page.waitForSelector('.ui-dialog.palette[role="dialog"]');
  await page.waitForTimeout(400);
  const again = (states.secondOpenOverHelp = await page.evaluate(STACK_STATE));
  if (!focusedOnTop(again, "palette")) failures.push("second Ctrl+K over the keyboard reference: the palette is not on top with focus");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  const closed = (states.allClosed = await page.evaluate(STACK_STATE));
  if (closed.dialogs.length !== 0 || closed.layers !== 0 || closed.inertOutsidePrewarm !== 0)
    failures.push(`with every dialog closed: ${closed.dialogs.length} open, ${closed.layers} layer(s), ${closed.inertOutsidePrewarm} node(s) left inert`);
  return { failures, states };
}

/* `node review/palette-warm.mjs --dialog-stack [url]`: the D1 procedure at 1280x800, dark and light,
   against a release preview (default http://localhost:4181). Exit 0 only when both legs held. Imported,
   this module runs nothing. */
const IS_MAIN = typeof process.argv[1] === "string" && import.meta.url === pathToFileURL(process.argv[1]).href;
if (IS_MAIN && process.argv.includes("--dialog-stack")) {
  const url = process.argv.find((a) => /^https?:\/\//.test(a)) ?? "http://localhost:4181";
  const { chromium } = await import("@playwright/test");
  const browser = await chromium.launch();
  let failed = 0;
  try {
    for (const colorScheme of ["dark", "light"]) {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme });
      const page = await ctx.newPage();
      await page.goto(url.replace(/\/$/, "") + "/");
      await page.waitForSelector("canvas", { timeout: 30000 });
      const { failures, states } = await checkPaletteOverDialog(page).catch((e) => ({ failures: [`the procedure threw: ${String(e).split("\n")[0]}`], states: {} }));
      failed += failures.length;
      console.log(`1280x800 ${colorScheme}: ${failures.length === 0 ? "the most recently opened dialog held the top layer" : failures.join("; ")}`);
      console.log(JSON.stringify(states));
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
  console.log(failed === 0 ? "D1 RENDERED: HELD (2 of 2 legs)" : `D1 RENDERED: BROKEN (${failed} failed condition(s))`);
  process.exit(failed === 0 ? 0 : 1);
}
