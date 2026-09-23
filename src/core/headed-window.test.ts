/**
 * headed-window.test.ts — acceptance report item 15, as a CLASS: every headed timing harness plans
 * its window inside the screen it runs on.
 *
 * THE DEFECT. `measure-inp.mjs` launched its headed Chromium at a fixed `--window-size=1940,1180`
 * for a 1920x1080 viewport. On the reference host (1920x1200 physical at 150 %: a 1280x752 DIP work
 * area) that window is half again the size of the screen, and most of it — the canvas included — was
 * off-screen. Wave 3 repaired measure-inp alone (planWindow / windowInside), and the SAME fixed size
 * stayed in measure-fps, audit-e5-sweep, audit-e5-coldload and the independent E4 sampler: a fix
 * copied into one of five instruments is a fix for that instrument, not for the class.
 *
 * THE CLASS is read from the directory, not from a list: every `review/*.mjs` that launches a
 * headed browser (`headless: false`) must
 *   - carry no fixed `--window-size=<digits>` of its own (the size is planned from the screen);
 *   - take its plan from `./host-env.mjs`, the one owner of "was this machine a measurement
 *     environment?" — `headedWindow` probes the screen, `windowBoundsCheck` reads what the OS gave;
 *   - and, when it states an `acceptanceEvidence` verdict, gate it on the window fitting.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REVIEW = join(PKG, "review");

const headed = readdirSync(REVIEW)
  .filter((n) => n.endsWith(".mjs") && n !== "host-env.mjs")
  .filter((n) => /headless\s*:\s*false/.test(readFileSync(join(REVIEW, n), "utf8")));

describe("item 15 as a class: every headed harness plans its window inside the screen", () => {
  it("finds the headed harnesses — an empty scan is not a pass", () => {
    for (const known of ["measure-inp.mjs", "measure-fps.mjs", "audit-e5-sweep.mjs", "audit-e5-coldload.mjs"]) expect(headed).toContain(known);
  });

  it("host-env.mjs owns the plan: planWindow, windowInside, headedWindow and windowBoundsCheck", async () => {
    const env = (await import(/* @vite-ignore */ pathToFileURL(join(REVIEW, "host-env.mjs")).href)) as Record<string, unknown>;
    for (const name of ["planWindow", "windowInside", "headedWindow", "windowBoundsCheck"]) expect(typeof env[name], name).toBe("function");
  });

  it("no headed harness carries a fixed window size", () => {
    const fixed = headed.filter((n) => /--window-size=\d/.test(readFileSync(join(REVIEW, n), "utf8")));
    expect(fixed, "a fixed --window-size ignores the screen it runs on (item 15)").toEqual([]);
  });

  it("every headed harness takes its window from host-env.mjs and checks what the OS gave", () => {
    const missing = headed.filter((n) => {
      const t = readFileSync(join(REVIEW, n), "utf8");
      const imports = /import\s*\{[^}]*\bheadedWindow\b[^}]*\}\s*from\s*["']\.\/host-env\.mjs["']/.test(t);
      return !(imports && /\bheadedWindow\s*\(/.test(t) && /\bwindowBoundsCheck\s*\(/.test(t));
    });
    expect(missing).toEqual([]);
  });

  it("a harness that states acceptanceEvidence gates it on the window fitting", () => {
    const ungated = headed.filter((n) => {
      const t = readFileSync(join(REVIEW, n), "utf8");
      const m = /\bconst acceptanceEvidence\s*=([\s\S]*?);/.exec(t);
      const inline = /\bacceptanceEvidence\s*:\s*([^,\n]+)/.exec(t);
      const expr = m?.[1] ?? inline?.[1];
      return expr !== undefined && !/\bwindowFits\b/.test(expr);
    });
    expect(ungated).toEqual([]);
  });
});
