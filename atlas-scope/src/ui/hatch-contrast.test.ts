/**
 * hatch-contrast.test.ts — text on the not-observed hatch clears 4.5:1 on the STRIPE, not just on
 * the ground between stripes.
 *
 * THE DEFECT THIS PINS (A11Y critic, 2026-09-21, D4, measured on rendered pixels):
 *   The stripe was `color-mix(in oklab, var(--unobserved) 14%, transparent)` — a translucent wash.
 *   Translucent layers compound, and hatched boxes nest (a not-observed chip inside an
 *   UNDETERMINED hop), so the doubled stripe took `.ui-notobs__text` to 3.90:1 and the
 *   `--text-faint` captions (`.ui-cite__path`, `dt.hop__key`) to 4.36:1 in light and 4.32:1 in dark.
 *   Every one of those texts is 11px, so the floor is 4.5:1.
 *
 * The fix is structural rather than a smaller number: the stripe is mixed into the page ground and
 * is OPAQUE, so it is one colour however deep the nesting goes. That turns "every surface x every
 * nesting depth" into one pairing per ink per theme, which is what this file checks — computed from
 * the real token values, with the real oklab mix, rather than restated.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../core/tokens.css"), "utf8");

type RGB = [number, number, number];

const toLin = (c: number): number => {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const fromLin = (c: number): number => {
  const s = c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055;
  return Math.min(255, Math.max(0, s * 255));
};
const hex = (h: string): RGB => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as RGB;
const lum = (c: RGB): number => 0.2126 * toLin(c[0]) + 0.7152 * toLin(c[1]) + 0.0722 * toLin(c[2]);
const contrast = (a: RGB, b: RGB): number => {
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};

/* Björn Ottosson's oklab, the space CSS Color 5 `color-mix(in oklab, ...)` interpolates in. */
function toOklab(c: RGB): RGB {
  const [r, g, b] = c.map(toLin) as RGB;
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}
function fromOklab([L, A, B]: RGB): RGB {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  return [
    fromLin(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    fromLin(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    fromLin(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}
const mixOklab = (a: RGB, pct: number, b: RGB): RGB => {
  const [x, y] = [toOklab(a), toOklab(b)];
  return fromOklab(x.map((v, i) => v * pct + y[i]! * (1 - pct)) as RGB);
};

function block(selector: RegExp): Record<string, string> {
  const m = selector.exec(css);
  if (!m) return {};
  const start = css.indexOf("{", m.index);
  let depth = 0;
  let i = start;
  for (; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) break;
  }
  const out: Record<string, string> = {};
  for (const t of css.slice(start, i).matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) out[t[1]!] = t[2]!;
  return out;
}

const light = block(/^:root\s*\{/m);
const dark = { ...light, ...block(/^\[data-theme="dark"\]\s*\{/m) };

/** The stripe stop of --unobserved-hatch, parsed from the token itself. */
const stripe = /--unobserved-hatch:\s*repeating-linear-gradient\(([\s\S]*?)\);/.exec(css)?.[1] ?? "";
const mix = /color-mix\(in oklab,\s*var\((--[a-z-]+)\)\s*(\d+)%,\s*(var\((--[a-z0-9-]+)\)|transparent)\)/.exec(stripe);

/** Every ink that paints text inside a hatched region (chips, hop facts, banners, verdicts). */
const INKS = ["--text", "--text-muted", "--text-faint", "--unobserved", "--claim-indeterminate"];

describe("the not-observed hatch stripe", () => {
  it("is parseable, so the audit below cannot pass by auditing nothing", () => {
    expect(mix, `could not parse the stripe stop out of: ${stripe}`).not.toBeNull();
  });

  it("is OPAQUE — mixed into a ground, not into transparent — so nested hatches cannot compound", () => {
    expect(mix?.[3], "a translucent stripe darkens once per nesting level").not.toBe("transparent");
  });

  for (const [name, t] of [
    ["light", light],
    ["dark", dark],
  ] as const) {
    it(`${name}: every hatched-region ink clears 4.5:1 on the stripe itself`, () => {
      const [, ink, pct, , ground] = mix!;
      const s = mixOklab(hex(t[ink!]!), Number(pct) / 100, hex(t[ground!]!));
      const failures = INKS.filter((k) => t[k] !== undefined)
        .map((k) => [k, contrast(hex(t[k]!), s)] as const)
        .filter(([, r]) => r < 4.5)
        .map(([k, r]) => `${k} on the stripe = ${r.toFixed(2)}:1`);
      expect(failures).toEqual([]);
    });
  }
});
