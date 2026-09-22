/**
 * sticky-layer.test.ts — structural tripwire for acceptance F6 (byte-identical captures).
 *
 * Measured defect: the findings grid's sticky column header sat at a fractional CSS y, and Chrome
 * decided per load whether to give it its own compositing layer. The glyphs rasterized at a
 * different sub-pixel offset each way, so 9 of 32 dev-server capture frames differed. Pinning the
 * layer (`will-change: transform`) made 12 of 12 loads identical.
 *
 * WHAT THIS GUARD DOES NOT COVER — an open F6 residual, measured 2026-09-21. A rare capture (about
 * 1 frame in 64-100) differs from its twin by exactly 1 in 8 bits across the cut-row scrim gradients
 * (`background-attachment: local` scrollers at fractional offsets) and a few anti-aliased header-icon
 * edges; the alternate frame is the same bytes each time it appears, so it is a second raster
 * outcome, not noise. Two remedies were built and MEASURED, and neither removed it, so neither is
 * guarded here (a guard enforcing a measured non-fix would be worse than none):
 *   1. pinning every local-background scroller with `will-change: transform`, as for sticky boxes:
 *      3 of 192 frames still varied, same signature;
 *   2. disabling GPU-raster MSAA in the capture harness: 0 of 192 in one sample, then
 *      `capture.mjs twice` failed 1 of 32 with the same signature.
 * LOCATED 2026-09-21 (after the two failed remedies above): the alternate is page-wide — every
 * scrim band flips at once, with some SVG icon edges — and it did not recur once the capture
 * browser rasterized page tiles on the CPU (`--disable-gpu-rasterization` in review/capture.mjs,
 * whose GPU_ARGS comment carries the measurement). It is GPU tile-raster state, not a paint
 * property of this product. Do not extend this file's selector class to scrollers on the
 * strength of the scrim signature alone.
 *
 * This is a source-text tripwire, not behavioural evidence. It does not establish that no OTHER
 * paint source varies between loads; the proof that captures are byte-identical is
 * `node review/capture.mjs twice`, run more than once, on the server being cited.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function cssFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...cssFiles(p));
    else if (p.endsWith(".css")) out.push(p);
  }
  return out;
}

type Block = { file: string; selector: string; body: string };

const stripComments = (s: string): string => s.replace(/\/\*[\s\S]*?\*\//g, "");

/** Innermost `{ ... }` bodies (declaration blocks) whose DECLARATIONS (comments removed) match. */
function blocksDeclaring(file: string, css: string, declares: RegExp): Block[] {
  const out: Block[] = [];
  const re = /([^{}]*)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css))) {
    // Both groups always participate in this pattern; the fallbacks satisfy noUncheckedIndexedAccess.
    const body = m[2] ?? "";
    if (declares.test(stripComments(body))) {
      out.push({ file: relative(SRC, file), selector: stripComments(m[1] ?? "").trim(), body });
    }
  }
  return out;
}

const STICKY = /position\s*:\s*sticky\b/;

const PINNED = /will-change\s*:\s*transform\b/;
// A reason must FOLLOW the marker. `\S` used to be enough, and the asterisk of the comment's own
// closing delimiter satisfied it, so a bare `sticky-layer: exempt.` exempted a rule with no reason.
const EXEMPT = /sticky-layer:\s*exempt\.\s*[\w`]/;

const files = cssFiles(SRC);
const sources = files.map((f) => ({ f, css: readFileSync(f, "utf8") }));
const sticky = sources.flatMap(({ f, css }) => blocksDeclaring(f, css, STICKY));

const offenders = (blocks: Block[]): string[] =>
  blocks.filter((b) => !PINNED.test(stripComments(b.body)) && !EXEMPT.test(b.body)).map((b) => `${b.file} :: ${b.selector}`);

describe("every sticky box pins its compositing layer or states why not (F6)", () => {
  it("finds the sticky rules it guards (the scan is not vacuous)", () => {
    expect(sticky.length).toBeGreaterThanOrEqual(1);
    expect(sticky.some((b) => b.selector.includes(".ag__head"))).toBe(true);
  });

  it("each is pinned with will-change: transform or carries a sticky-layer: exempt reason", () => {
    expect(offenders(sticky)).toEqual([]);
  });

  it("the findings grid header, the measured offender, is pinned rather than exempted", () => {
    const head = sticky.find((b) => /(^|\s|,)\.ag__head$/.test(b.selector));
    expect(head?.body).toMatch(PINNED);
  });
});

describe("the detector itself", () => {
  /* Tested on inline CSS so a regression in the regexes cannot hide behind the real stylesheets
     happening to be compliant. */
  const scan = (css: string, re: RegExp) => offenders(blocksDeclaring(join(SRC, "x.css"), css, re));

  it("flags an unpinned sticky box, and passes a pinned or exempted one", () => {
    expect(scan(".a { position: sticky; top: 0; }", STICKY)).toHaveLength(1);
    expect(scan(".a { position:sticky; will-change: transform; }", STICKY)).toEqual([]);
    expect(scan(".a { position: sticky; /* sticky-layer: exempt. it holds a fixed panel */ }", STICKY)).toEqual([]);
  });

  it("is not satisfied by prose: a `will-change` inside a comment does not pin anything", () => {
    expect(scan(".a { position: sticky; /* will-change: transform */ }", STICKY)).toHaveLength(1);
  });

  it("does not count a bare exemption with no reason", () => {
    expect(scan(".a { position: sticky; /* sticky-layer: exempt. */ }", STICKY)).toHaveLength(1);
  });

  it("ignores rules that only mention the words in a comment", () => {
    expect(scan(".a { color: red; /* position: sticky */ }", STICKY)).toEqual([]);
  });
});
