/**
 * A6 audit, 2026-09-21: the blast-radius comparison (`.dp-cmp`) split into two columns on a
 * VIEWPORT media query, but it lives in Rail B, which is 380-420 px wide at every desktop viewport.
 * At 1920x1080 that produced two 190 px columns with 34 px value cells ("partiti / on"). jsdom does
 * no layout, so this pins the rule's SHAPE: the column count must come from the space the grid
 * actually has (an intrinsic auto-fit/auto-fill track with a minimum), never from the viewport.
 */
import { readFileSync } from "node:fs";
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
