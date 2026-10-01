// @vitest-environment node
/**
 * palette-warm-harness.test.ts — every harness that waits for the scene to settle before it
 * photographs or times anything also waits for the command palette's pre-warm to finish drawing.
 *
 * THE DEFECT (engine gate, 2026-09-27; routed by cluster E2E3). After the scene converges the palette
 * draws its frame once at opacity 0.001 for at least 250 ms and 3 presented frames, with a one-time
 * GPU program compile of ~120 ms, then parks it (`src/app/CommandPalette.tsx`). A capture inside that
 * window can move a pixel by one 8-bit step, and a timed action inside it pays the compile. Only
 * `review/measure-inp.mjs` knew about it.
 *
 * THE CLASS IS DERIVED, not listed: every `review/*.mjs` that reads the scene's `converged` (its
 * settle signal) — except the two that deliberately measure THROUGH the pre-warm, each named with its
 * reason in review/palette-warm.mjs — must take the one owned wait, `awaitPaletteWarm`, from
 * `./palette-warm.mjs`. The owner's terminal phases are pinned to the component's own state type, so
 * a new phase cannot be silently treated as finished (or as never finishing).
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REVIEW = join(ROOT, "review");
const OWNER = "palette-warm.mjs";

/** Harnesses that measure through the pre-warm on purpose (reasons in review/palette-warm.mjs). */
const MEASURES_THROUGH = new Set(["measure-inp.mjs", "audit-e5-coldload.mjs"]);

const stripComments = (text: string): string =>
  text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

/** A harness reads the scene's settle signal: the stats flag, or the status bar's convergence word. */
const READS_SETTLE = /\.converged\b|sb__converged/;
const TAKES_WAIT = /import\s*\{[^}]*\bawaitPaletteWarm\b[^}]*\}\s*from\s*["']\.\/palette-warm\.mjs["']/;
const CALLS_WAIT = /\bawaitPaletteWarm\s*\(/;

const harnesses = (): string[] =>
  readdirSync(REVIEW)
    .filter((f) => f.endsWith(".mjs") && f !== OWNER)
    .sort();

const settleGated = (): string[] =>
  harnesses().filter((f) => READS_SETTLE.test(stripComments(readFileSync(join(REVIEW, f), "utf8"))));

describe("the palette pre-warm wait covers every settle-gated harness (derived from source)", () => {
  it("finds the class at all (positive control)", () => {
    const cls = settleGated();
    expect(cls).toContain("capture.mjs");
    expect(cls).toContain("capture-motion.mjs");
  });

  it("the deliberate exclusions exist, and are named in the owner module", () => {
    const owner = readFileSync(join(REVIEW, OWNER), "utf8");
    for (const f of MEASURES_THROUGH) {
      expect(harnesses(), `${f} is gone: drop its exclusion`).toContain(f);
      expect(owner, `${f}'s exclusion is not explained in ${OWNER}`).toContain(f);
    }
  });

  for (const f of settleGated().filter((h) => !MEASURES_THROUGH.has(h))) {
    it(`${f}: imports and calls awaitPaletteWarm from ./${OWNER}`, () => {
      const src = stripComments(readFileSync(join(REVIEW, f), "utf8"));
      expect(TAKES_WAIT.test(src), `${f} does not import awaitPaletteWarm`).toBe(true);
      expect(CALLS_WAIT.test(src), `${f} imports but never calls awaitPaletteWarm`).toBe(true);
    });
  }
});

describe("the owner's terminal phases are the component's own", () => {
  const component = readFileSync(join(ROOT, "src/app/CommandPalette.tsx"), "utf8");
  const typeLine = /type WarmState\s*=\s*([^;]+);/.exec(component);

  it("CommandPalette.tsx declares its WarmState union", () => {
    expect(typeLine).not.toBeNull();
  });

  const states = [...(typeLine?.[1] ?? "").matchAll(/"([a-z]+)"/g)].map((m) => m[1] ?? "");

  it("every terminal phase is a declared state, and every declared state is classified", async () => {
    const mod = (await import(pathToFileURL(join(REVIEW, OWNER)).href)) as { PALETTE_WARM_TERMINAL: readonly string[] };
    const terminal = [...mod.PALETTE_WARM_TERMINAL].sort();
    expect(terminal).toEqual(["done", "superseded", "unpresented"]);
    for (const t of terminal) expect(states).toContain(t);
    /* The non-terminal phases are exactly the ones the component still moves out of on its own. */
    expect(states.filter((s) => !terminal.includes(s)).sort()).toEqual(["mounted", "scheduled", "waiting"]);
  });

  it("the component parks (terminal) only through those phases", () => {
    const marked = [...component.matchAll(/markWarm\("([a-z]+)"\)/g)].map((m) => m[1]);
    expect(marked).toEqual(expect.arrayContaining(["waiting", "scheduled", "mounted", "superseded"]));
    /* done/unpresented reach markWarm through `finish(state)`; pin that route. */
    expect(component).toMatch(/const finish = \(state: "done" \| "unpresented"\): void =>/);
  });
});

describe("awaitPaletteWarm fails loudly and returns the phase", () => {
  type Fake = { waitForFunction: () => Promise<{ jsonValue: () => Promise<unknown> }>; evaluate: () => Promise<unknown> };
  const load = async () =>
    (await import(pathToFileURL(join(REVIEW, OWNER)).href)) as { awaitPaletteWarm: (p: Fake, ms?: number) => Promise<string> };

  it("returns the terminal phase reached", async () => {
    const { awaitPaletteWarm } = await load();
    const page: Fake = { waitForFunction: async () => ({ jsonValue: async () => "done" }), evaluate: async () => "done" };
    await expect(awaitPaletteWarm(page, 10)).resolves.toBe("done");
  });

  it("throws naming the last phase seen when the bound passes", async () => {
    const { awaitPaletteWarm } = await load();
    const page: Fake = {
      waitForFunction: async () => {
        throw new Error("Timeout 10ms exceeded.");
      },
      evaluate: async () => "mounted",
    };
    await expect(awaitPaletteWarm(page, 10)).rejects.toThrow(/last phase: mounted/);
  });
});
