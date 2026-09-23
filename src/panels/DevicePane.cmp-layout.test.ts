/**
 * A6 audit, 2026-09-21: the blast-radius comparison (`.dp-cmp`) split into two columns on a
 * VIEWPORT media query, but it lives in Rail B, which is 380-420 px wide at every desktop viewport.
 * At 1920x1080 that produced two 190 px columns with 34 px value cells ("partiti / on"). jsdom does
 * no layout, so this pins the rule's SHAPE: the column count must come from the space the grid
 * actually has (an intrinsic auto-fit/auto-fill track with a minimum), never from the viewport.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "DevicePane.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  " ",
);

/** Every declaration block whose selector list is exactly `.dp-cmp`, with the @media it sits in. */
function dpCmpBlocks(): { media: string | null; body: string }[] {
  const out: { media: string | null; body: string }[] = [];
  const re = /(@media[^{]*)\{|([^{}]+)\{([^{}]*)\}|\}/g;
  const stack: (string | null)[] = [];
  for (let m = re.exec(css); m !== null; m = re.exec(css)) {
    if (m[1] !== undefined) stack.push(m[1].trim());
    else if (m[2] !== undefined) {
      if (m[2].trim() === ".dp-cmp") out.push({ media: stack[stack.length - 1] ?? null, body: m[3] ?? "" });
    } else stack.pop();
  }
  return out;
}

describe("the failure-impact comparison sizes its columns from its own width", () => {
  it("declares an intrinsic column track outside any media query", () => {
    const blocks = dpCmpBlocks();
    const base = blocks.find((b) => b.media === null);
    expect(base, ".dp-cmp has no unconditional rule").toBeDefined();
    const cols = /grid-template-columns\s*:\s*([^;]+)/.exec(base!.body)?.[1] ?? "";
    expect(cols).toMatch(/repeat\(\s*auto-(fit|fill)\s*,\s*minmax\(/);
  });

  it("never re-declares its columns under a viewport media query", () => {
    const gated = dpCmpBlocks().filter((b) => b.media !== null && /grid-template-columns/.test(b.body));
    expect(gated.map((b) => b.media)).toEqual([]);
  });
});

/*
 * C2, 2026-09-23 (independent acceptance review): on `?d=core1` the adjacent "Power supplies" and
 * "Modules" rows each hold a not-observed box with a reason, and at 1440 one box laid its reason
 * UNDER the words and the next laid it BESIDE them — measured: Power supplies stacked (76 px tall),
 * Modules side by side (106 px). The reason's basis was a readable measure (`flex: 1 1 16ch`) with a
 * minimum at its longest token, so WHERE it went depended on how long its longest token was:
 * "(num_power_supplies)" did not fit beside the words, "(num_modules)" did. Two rows of the same
 * kind read as two different kinds of thing.
 *
 * The contract, for every not-observed box in the app (the box has one owner, src/ui/primitives.css):
 * the reason's placement is decided by the box's STRUCTURE, never by its text — it always takes a
 * line of its own under the words (a 100% basis on a wrapping flex line). jsdom lays nothing out, so
 * this pins the rule; the orientation was measured in the running app at 1440 and 1920.
 */
const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

function blocksIn(file: string, selector: string): { media: string | null; body: string }[] {
  const text = readFileSync(join(srcRoot, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, " ");
  const out: { media: string | null; body: string }[] = [];
  const re = /(@[^{;]*)\{|([^{}]+)\{([^{}]*)\}|\}/g;
  const stack: string[] = [];
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    if (m[1] !== undefined) stack.push(m[1].trim());
    else if (m[2] !== undefined) {
      if (m[2].split(",").some((s) => s.trim().endsWith(selector))) out.push({ media: stack[stack.length - 1] ?? null, body: m[3] ?? "" });
    } else stack.pop();
  }
  return out;
}

function cssFiles(dir: string, rel = ""): string[] {
  const out: string[] = [];
  for (const name of readdirSync(join(dir, rel))) {
    const r = rel === "" ? name : `${rel}/${name}`;
    if (statSync(join(dir, r)).isDirectory()) out.push(...cssFiles(dir, r));
    else if (name.endsWith(".css")) out.push(r);
  }
  return out;
}

describe("adjacent not-observed boxes lay out the same way whatever their text", () => {
  it("puts the reason on a line of its own under the words, by a 100% basis", () => {
    const base = blocksIn("ui/primitives.css", ".ui-notobs__why").filter((b) => b.media === null);
    expect(base.length, ".ui-notobs__why has no unconditional rule").toBeGreaterThan(0);
    const body = base.map((b) => b.body).join(";");
    const flex = /(?:^|;)\s*flex\s*:\s*([^;]+)/.exec(body)?.[1]?.trim() ?? "";
    const basis = /flex-basis\s*:\s*([^;]+)/.exec(body)?.[1]?.trim() ?? flex.split(/\s+/)[2] ?? "";
    expect(basis, `the reason's basis is "${basis}"; anything short of 100% lets its length decide whether it fits beside the words`).toBe("100%");
    const box = blocksIn("ui/primitives.css", ".ui-notobs").filter((b) => b.media === null).map((b) => b.body).join(";");
    expect(box).toMatch(/flex-wrap\s*:\s*wrap/);
  });

  it("no other stylesheet re-decides where the reason goes", () => {
    const overrides = cssFiles(srcRoot)
      .filter((f) => f !== "ui/primitives.css")
      .flatMap((f) => blocksIn(f, ".ui-notobs__why").filter((b) => /\bflex(-basis|-grow|-shrink)?\s*:|\bwidth\s*:|inline-size\s*:/.test(b.body)).map(() => f));
    expect(overrides).toEqual([]);
  });
});
