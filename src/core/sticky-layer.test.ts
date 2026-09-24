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

/* ══ the status bar paints above every body region at every narrow width (D3, 2026-09-24) ══════════
 *
 * MEASURED DEFECT. Below 768px the status bar is `position: sticky; z-index: 5` at the viewport's
 * bottom edge. The drawer rung's `.rail--b { z-index: var(--z-overlay) }` (30) was never reset for
 * the narrower rungs, and because the rail is a FLEX ITEM of the body, a z-index makes it a stacking
 * context even while `position: static`. At 390x844 `?d=core1`, Tab to "23/26 collected" at scroll
 * 10537: elementFromPoint gave `LI.dp-list__row` at 9 of 9 points; 0 of 4,400 ring pixels changed.
 *
 * THE INVARIANT, resolved from the stylesheets rather than restated: for every width in the narrow
 * rungs (the single-column rung's upper bound is read from `useLadder` in surfaces.tsx; the sample
 * widths are every media-query bound the stylesheets declare below it, and one pixel either side),
 * every z-index a body region (each `className="rail rail--*"` and the stage, read from the TSX) CAN
 * resolve to under the cascade, plus every z-index a rule scoped under a region declares, is below
 * the LOWEST z-index the status bar can resolve to. "Can resolve to": a rule whose selector depends
 * on state (an ancestor, an attribute, a pseudo-class, a non-width media feature) may or may not
 * apply, so every value down to the first unconditional winner is a possible value. The browser-side
 * proof is `review/audit-d3-focus.mjs --sweep`; this is the static tripwire that runs on every build.
 */
const APP_DIR = join(SRC, "app");
const TOKENS = readFileSync(join(SRC, "core", "tokens.css"), "utf8");
const REM = 16;

/** `--z-*` tokens, resolved to numbers. */
const zTokens = new Map<string, number>([...TOKENS.matchAll(/(--z-[\w-]+)\s*:\s*(-?\d+)\s*;/g)].map((m) => [m[1] ?? "", Number(m[2])]));

type Rule = { selector: string; decls: string; media: string[]; order: number; file: string };

/** A small CSS walker: every style rule with the @media / @container conditions around it. */
function rulesOf(file: string, css: string, startOrder: number): Rule[] {
  const src = stripComments(css);
  const out: Rule[] = [];
  const stack: (string | null)[] = []; /* a condition for @media/@container, "skip" for @keyframes, null otherwise */
  let buf = "";
  let order = startOrder;
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (ch === "{") {
      const prelude = buf.trim();
      buf = "";
      if (prelude.startsWith("@media") || prelude.startsWith("@container")) {
        stack.push(prelude);
      } else if (prelude.startsWith("@")) {
        stack.push(prelude.startsWith("@keyframes") || prelude.startsWith("@font-face") ? "skip" : null);
      } else {
        const end = src.indexOf("}", i);
        const decls = src.slice(i + 1, end);
        i = end;
        if (!stack.includes("skip")) {
          out.push({ selector: prelude, decls, media: stack.filter((s): s is string => s !== null && s !== "skip"), order: order++, file });
        }
      }
    } else if (ch === "}") {
      stack.pop();
      buf = "";
    } else if (ch === ";" && stack.length === 0 && buf.trim().startsWith("@")) {
      buf = ""; /* @import / @charset statements */
    } else {
      buf += ch;
    }
  }
  return out;
}

/** "yes" / "no" at `px`, or "maybe" when the condition depends on something other than the width. */
function mediaAt(conds: readonly string[], px: number): "yes" | "no" | "maybe" {
  let verdict: "yes" | "maybe" = "yes";
  for (const c of conds) {
    if (/\bprint\b/.test(c)) return "no";
    if (c.startsWith("@container")) {
      verdict = "maybe";
      continue;
    }
    const q = c.replace(/^@media/, "");
    for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)(rem|px)\)/g)) {
      const bound = Number(m[2]) * (m[3] === "rem" ? REM : 1);
      if (m[1] === "min" ? px < bound : px > bound) return "no";
    }
    if (/\((?!(min|max)-width)[a-z-]+\s*:/.test(q) || /\b(hover|forced-colors|prefers-[a-z-]+)\b/.test(q)) verdict = "maybe";
  }
  return verdict;
}

/** The one element a compound can be said to target: its classes, id and tag. */
type Target = { tag: string; id: string | null; classes: ReadonlySet<string> };

const compounds = (sel: string): string[] => sel.trim().split(/\s*[>+~]\s*|\s+/).filter((s) => s !== "");

/** Does the LAST compound of `sel` target `t`, and does it do so unconditionally? */
function matchLast(sel: string, t: Target): "no" | "always" | "sometimes" {
  const parts = compounds(sel);
  const last = parts[parts.length - 1] ?? "";
  if (/::/.test(last)) return "no"; /* a pseudo-element is its own box, not the element */
  const tag = /^[a-z][\w-]*/i.exec(last)?.[0];
  if (tag !== undefined && tag.toLowerCase() !== t.tag) return "no";
  const id = /#([\w-]+)/.exec(last)?.[1];
  if (id !== undefined && id !== t.id) return "no";
  const classes = [...last.matchAll(/\.([\w-]+)/g)].map((m) => m[1] ?? "");
  if (classes.length === 0 && id === undefined && tag === undefined) return "no";
  if (!classes.every((c) => t.classes.has(c))) return "no";
  const conditional = parts.length > 1 || /[[:]/.test(last);
  return conditional ? "sometimes" : "always";
}

function specificity(sel: string): number {
  const ids = (sel.match(/#[\w-]+/g) ?? []).length;
  const cls = (sel.match(/\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+/g) ?? []).length;
  const types = compounds(sel).filter((c) => /^[a-z]/i.test(c)).length;
  return ids * 10000 + cls * 100 + types;
}

function zValue(decls: string): number | "auto" | null {
  const m = /(?:^|;)\s*z-index\s*:\s*([^;!]+)/.exec(decls);
  if (!m) return null;
  const v = (m[1] ?? "").trim();
  if (v === "auto") return "auto";
  const tok = /^var\((--z-[\w-]+)\)$/.exec(v);
  if (tok) return zTokens.get(tok[1] ?? "") ?? Number.NaN;
  const n = Number(v);
  return Number.isFinite(n) ? n : Number.NaN;
}

/** Every z-index `t` can resolve to at `px`: the cascade walked down to its first certain winner. */
function possibleZ(rules: readonly Rule[], t: Target, px: number): (number | "auto")[] {
  const cands: { z: number | "auto"; spec: number; order: number; certain: boolean }[] = [];
  for (const r of rules) {
    const m = mediaAt(r.media, px);
    if (m === "no") continue;
    const z = zValue(r.decls);
    if (z === null) continue;
    for (const s of r.selector.split(",")) {
      const hit = matchLast(s, t);
      if (hit === "no") continue;
      cands.push({ z, spec: specificity(s), order: r.order, certain: hit === "always" && m === "yes" });
    }
  }
  cands.sort((a, b) => b.spec - a.spec || b.order - a.order);
  const out: (number | "auto")[] = [];
  for (const c of cands) {
    out.push(c.z);
    if (c.certain) return out;
  }
  out.push("auto"); /* no certain winner: the initial value is possible too */
  return out;
}

/** z-indexes declared by rules scoped UNDER a region (a region class in a non-last compound). */
function scopedZ(rules: readonly Rule[], regionClasses: ReadonlySet<string>, px: number): { z: number; rule: string }[] {
  const out: { z: number; rule: string }[] = [];
  for (const r of rules) {
    if (mediaAt(r.media, px) === "no") continue;
    const z = zValue(r.decls);
    if (typeof z !== "number") continue;
    for (const s of r.selector.split(",")) {
      const parts = compounds(s);
      const scoped = parts.slice(0, -1).some((p) => [...p.matchAll(/\.([\w-]+)/g)].some((m) => regionClasses.has(m[1] ?? "")));
      if (scoped) out.push({ z, rule: `${r.file} :: ${s.trim()}` });
    }
  }
  return out;
}

/** The narrow widths: every media bound up to the single-column rung's top, and one px either side. */
function narrowWidths(rules: readonly Rule[], upperPx: number): number[] {
  const set = new Set<number>([320, upperPx]);
  for (const r of rules) {
    for (const c of r.media) {
      for (const m of c.matchAll(/\((?:min|max)-width:\s*([\d.]+)(rem|px)\)/g)) {
        const px = Math.round(Number(m[1]) * (m[2] === "rem" ? REM : 1));
        for (const w of [px - 1, px, px + 1]) if (w >= 320 && w <= upperPx) set.add(w);
      }
    }
  }
  return [...set].sort((a, b) => a - b);
}

function layerViolations(rules: readonly Rule[], status: Target, regions: readonly Target[], widths: readonly number[]): string[] {
  const out: string[] = [];
  const regionClasses = new Set(regions.flatMap((r) => [...r.classes]));
  for (const px of widths) {
    const statusZ = possibleZ(rules, status, px);
    const numeric = statusZ.filter((z): z is number => typeof z === "number");
    if (numeric.length !== statusZ.length || numeric.some((z) => Number.isNaN(z))) {
      out.push(`${px}px: the status bar can resolve to z-index ${statusZ.join(" / ")} — it must always be a numbered layer`);
      continue;
    }
    const floor = Math.min(...numeric);
    for (const t of regions) {
      for (const z of possibleZ(rules, t, px)) {
        if (typeof z === "number" && !(z < floor)) out.push(`${px}px: .${[...t.classes].join(".")} can take z-index ${z}, not below the status bar's ${floor}`);
      }
    }
    for (const s of scopedZ(rules, regionClasses, px)) {
      if (!(s.z < floor)) out.push(`${px}px: ${s.rule} sets z-index ${s.z} inside a region, not below the status bar's ${floor}`);
    }
  }
  return out;
}

const appTsx = readdirSync(APP_DIR)
  .filter((f) => f.endsWith(".tsx") && !f.includes(".test."))
  .map((f) => readFileSync(join(APP_DIR, f), "utf8"))
  .join("\n");
/** Body regions, from the components: every `className="rail rail--*"` and the stage. */
const REGIONS: Target[] = [
  ...[...appTsx.matchAll(/<(\w+)[^>]*?className="(rail rail--[\w-]+)"/g)].map((m) => ({
    tag: m[1] ?? "",
    id: null,
    classes: new Set((m[2] ?? "").split(" ")),
  })),
  ...[...appTsx.matchAll(/<(\w+)[^>]*?className=\{`(app__stage)\$/g)].map((m) => ({ tag: m[1] ?? "", id: null, classes: new Set([m[2] ?? ""]) })),
];
const statusMatch = /<(\w+)[^>]*?id="status-bar"[^>]*?className="([^"]+)"/.exec(appTsx);
const STATUS: Target = { tag: statusMatch?.[1] ?? "", id: "status-bar", classes: new Set((statusMatch?.[2] ?? "").split(" ")) };
const ladderTop = /singleColumn = useMediaQuery\("\(min-width: [\d.]+rem\) and \(max-width: ([\d.]+)rem\)"\)/.exec(
  readFileSync(join(APP_DIR, "surfaces.tsx"), "utf8"),
);
const NARROW_TOP = Math.round(Number(ladderTop?.[1] ?? Number.NaN) * REM);

let orderBase = 0;
const allRules: Rule[] = [];
for (const f of files.filter((p) => !p.endsWith("tokens.css"))) {
  const r = rulesOf(relative(SRC, f), readFileSync(f, "utf8"), orderBase);
  orderBase += r.length;
  allRules.push(...r);
}

describe("the status bar paints above every body region at every narrow width (D3)", () => {
  it("finds what it guards: the rails and the stage in the TSX, the status bar, the rung, the widths", () => {
    expect(REGIONS.map((r) => [...r.classes].join(" "))).toEqual(expect.arrayContaining(["rail rail--a", "rail rail--b", "app__stage"]));
    expect(STATUS.tag).toBe("footer");
    expect(STATUS.classes.has("app__status")).toBe(true);
    expect(NARROW_TOP).toBe(1023);
    const widths = narrowWidths(allRules, NARROW_TOP);
    expect(widths).toEqual(expect.arrayContaining([320, 767, 768, 1023]));
    expect(zTokens.get("--z-overlay")).toBeGreaterThan(0);
  });

  it("no region, and nothing scoped under one, can resolve to a layer at or above the status bar", () => {
    expect(layerViolations(allRules, STATUS, REGIONS, narrowWidths(allRules, NARROW_TOP))).toEqual([]);
  });

  it("the detector flags the measured defect: an overlay z-index leaking from a wider rung", () => {
    const css =
      ".app__status { position: relative; z-index: 2; }\n" +
      "@media (max-width: 79.9375rem) { .rail--b { position: absolute; z-index: var(--z-overlay); } }\n" +
      "@media (max-width: 63.9375rem) { .rail--b { position: static; } }\n" +
      "@media (max-width: 47.9375rem) { .app__status { position: sticky; z-index: 5; } }";
    const rules = rulesOf("x.css", css, 0);
    const rb: Target = { tag: "aside", id: null, classes: new Set(["rail", "rail--b"]) };
    const bad = layerViolations(rules, STATUS, [rb], [390, 767, 900]);
    expect(bad.length).toBe(3);
    expect(bad[0]).toMatch(/390px: \.rail\.rail--b can take z-index 30, not below the status bar's 5/);
    const fixed = rulesOf("x.css", css.replace("{ position: static; }", "{ position: static; z-index: auto; }"), 0);
    expect(layerViolations(fixed, STATUS, [rb], [390, 767, 900])).toEqual([]);
  });

  it("the detector counts a state-dependent rule as possible, and a rule scoped under a region", () => {
    const rb: Target = { tag: "aside", id: null, classes: new Set(["rail", "rail--b"]) };
    const css =
      ".app__status { z-index: 5; }\n" +
      ".rail--b { z-index: auto; }\n" +
      '.app[data-pane="x"] .rail--b { z-index: 9; }\n' +
      ".rail--b .inner { z-index: 7; }";
    const bad = layerViolations(rulesOf("x.css", css, 0), STATUS, [rb], [390]);
    expect(bad.some((b) => /can take z-index 9/.test(b))).toBe(true);
    expect(bad.some((b) => /\.inner sets z-index 7/.test(b))).toBe(true);
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
