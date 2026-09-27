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
