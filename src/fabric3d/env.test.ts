/**
 * env.test.ts — the backdrop lands on `--stage-bg` AFTER tone mapping (render audit #9).
 *
 * The light stage used to reach the screen at (199,200,201) against a token of (238,241,245): the
 * texture was the token times 1.08 / 0.94, and AgX compressed it 39-44 levels dark and grey. These
 * tests pin the pre-image arithmetic without a GPU. What they do NOT prove is the rendered pixel.
 * That was measured ONCE, on a real GPU, by a one-off repair probe that is not part of this
 * repository: it survives only as gitignored scratch on the workstation that ran it
 * (`review/_scratch/_repair_r3d_corners.mjs`), so a clone cannot re-run it, and no tracked instrument
 * re-measures these corners. The figures it read — light top corners (241,244,248), bottom
 * (233,237,241); dark (13,17,23) against (10,13,19) — are a historical record, not a pin.
 */
import { describe, expect, it } from "vitest";
import { Color, DataUtils } from "three";
import { BACKDROP_DISPLAY_SPAN, agxForward, agxInverse, createBackdrop } from "./env";
import { readTokens } from "./materials";

const to8 = (v: number): number => Math.round(new Color(v, v, v).convertLinearToSRGB().r * 255);

describe("the backdrop's tone-mapped colour", () => {
  it("the AgX port reproduces the measured failure it replaces", () => {
    // Token straight through AgX — what the old texture approximately did. The render measured
    // (199,200,201); the port says (196,197,199). Same grey, same lost cool cast.
    const s = readTokens("light").color("--stage-bg");
    const out = agxForward([s.r, s.g, s.b]).map(to8);
    expect(out[0]).toBeLessThan(205);
    expect((out[2] ?? 0) - (out[0] ?? 0)).toBeLessThan(4);
  });

  for (const theme of ["dark", "light"] as const) {
    it(`${theme}: the texture's middle row tone-maps to within 3 levels of --stage-bg`, () => {
      const tokens = readTokens(theme);
      const s = tokens.color("--stage-bg");
      const tex = createBackdrop(tokens);
      const data = tex.image.data as Uint16Array;
      const mid = Math.floor((tex.image.height as number) / 2) * 4;
      const lin: [number, number, number] = [
        DataUtils.fromHalfFloat(data[mid] ?? 0),
        DataUtils.fromHalfFloat(data[mid + 1] ?? 0),
        DataUtils.fromHalfFloat(data[mid + 2] ?? 0),
      ];
      const shown = agxForward(lin).map(to8);
      const want = [s.r, s.g, s.b].map(to8);
      for (let k = 0; k < 3; k += 1) expect(Math.abs((shown[k] ?? 0) - (want[k] ?? 0))).toBeLessThanOrEqual(3);
    });

    it(`${theme}: both ends invert exactly`, () => {
      const s = readTokens(theme).color("--stage-bg");
      for (const k of Object.values(BACKDROP_DISPLAY_SPAN[theme])) {
        const target: [number, number, number] = [s.r * k, s.g * k, s.b * k];
        const back = agxForward(agxInverse(target)).map(to8);
        expect(back).toEqual(target.map(to8));
      }
    });
  }
});
