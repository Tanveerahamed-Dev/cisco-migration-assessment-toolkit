/**
 * contrast.test.ts — the audit that makes tokens.css's central claim true.
 *
 * `tokens.css` states: "Every ratio quoted in a comment below was COMPUTED, not estimated. The
 * audit script lives at `tools/…`". That script did not exist. A claim of verification with no
 * verifier is the exact defect this project is built to prevent — and it is the worse kind,
 * because the header reads as evidence and invites everyone downstream to stop checking.
 *
 * So this is the audit, and it lives in the test suite rather than in `tools/` on purpose: a gate
 * that has to be remembered is a gate that rots. It does three things:
 *
 *   1. Parses the real token values out of tokens.css for BOTH themes.
 *   2. Computes WCAG 2.x relative-luminance contrast for every pairing the UI actually uses and
 *      asserts the floors — 4.5:1 for text (1.4.3), 3:1 for non-text UI and state (1.4.11).
 *   3. Re-derives every ratio QUOTED in a comment and fails if the quoted number is wrong, so the
 *      comments cannot drift away from the values they describe.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const TOKENS = resolve(dirname(fileURLToPath(import.meta.url)), "tokens.css");
const css = readFileSync(TOKENS, "utf8");

/* ── colour maths, straight from WCAG 2.x ──────────────────────────────────── */

function srgbToLinear(c: number): number {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function parseHex(hex: string): [number, number, number] | null {
  const h = hex.trim().replace(/^#/, "");
  const full = h.length === 3 ? [...h].map((ch) => ch + ch).join("") : h;
  if (!/^[0-9a-fA-F]{6}$/.test(full.slice(0, 6))) return null;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

function luminance(hex: string): number | null {
  const rgb = parseHex(hex);
  if (!rgb) return null;
  const [r, g, b] = rgb.map(srgbToLinear) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number | null {
  const la = luminance(a);
  const lb = luminance(b);
  if (la === null || lb === null) return null;
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

const round2 = (n: number): number => Math.round(n * 100) / 100;

/* ── parse the two themes out of the stylesheet ────────────────────────────── */

/**
 * Take the slice of CSS between a selector and its closing brace, then read every `--token: #hex`.
 * Deliberately simple: this file is authored by us to a known shape, and a parser clever enough to
 * handle arbitrary CSS would be harder to trust than the thing it is auditing.
 */
function tokensIn(selector: RegExp): Record<string, string> {
  /* The selector is matched ANCHORED TO THE START OF A LINE. A plain indexOf finds
     `[data-theme="dark"]` inside this stylesheet's own header comment, which documents the
     dark-theme strategy — and then parses the light block instead, silently producing an audit
     that compares light against itself and passes. That is precisely the shape of bug this file
     exists to catch, so it is worth the anchoring. */
  const m = selector.exec(css);
  if (!m) return {};
  const at = m.index;
  let depth = 0;
  let i = css.indexOf("{", at);
  if (i === -1) return {};
  const start = i;
  for (; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}") {
      depth--;
      if (depth === 0) break;
    }
  }
  const block = css.slice(start, i);
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    out[m[1]!] = m[2]!;
  }
  return out;
}

const light = tokensIn(/^:root\s*\{/m);
const darkExplicit = tokensIn(/^\[data-theme="dark"\]\s*\{/m);
// Dark inherits everything light defines and overrides only what differs.
const dark = { ...light, ...darkExplicit };

/* ── the pairings the UI actually uses ─────────────────────────────────────── */

const SURFACES = ["--bg", "--surface-1", "--surface-2", "--surface-3", "--overlay", "--stage-bg"];

/** kind decides the floor: text is 4.5:1 (WCAG 1.4.3), non-text UI and state is 3:1 (1.4.11). */
const INK_TEXT = ["--text", "--text-muted", "--text-faint"];
const NON_TEXT = ["--border-strong", "--focus"];

/**
 * Semantic ramps. These are used BOTH as text (a severity label) and as a non-text indicator (a
 * dot, a bar). They are held to the stricter text floor wherever the token file itself says they
 * carry words — which is every one of them, because rule 2 of the design system forbids colour
 * without a word.
 */
const SEMANTIC = [
  "--sev-critical",
  "--sev-high",
  "--sev-medium",
  "--sev-low",
  "--sev-info",
  "--state-up",
  "--state-down",
  "--state-unknown",
  "--band-excellent",
  "--band-good",
  "--band-fair",
  "--band-poor",
  "--band-critical",
];

const THEMES: [string, Record<string, string>][] = [
  ["light", light],
  ["dark", dark],
];

describe("tokens.css parses", () => {
  it("finds both themes, so an audit cannot pass by having nothing to audit", () => {
    expect(Object.keys(light).length).toBeGreaterThan(20);
    expect(Object.keys(darkExplicit).length).toBeGreaterThan(10);
    expect(light["--text"]).toBeDefined();
    expect(dark["--text"]).toBeDefined();
    expect(light["--text"]).not.toBe(dark["--text"]);
  });
});

describe("WCAG 1.4.3 — text contrast is at least 4.5:1", () => {
  for (const [themeName, t] of THEMES) {
    it(`${themeName}: every ink token clears 4.5:1 on every surface it can sit on`, () => {
      const failures: string[] = [];
      for (const ink of INK_TEXT) {
        for (const surf of SURFACES) {
          const fg = t[ink];
          const bg = t[surf];
          if (!fg || !bg) continue;
          const r = contrast(fg, bg);
          if (r === null) continue;
          if (r < 4.5) failures.push(`${ink} on ${surf} = ${round2(r)}:1`);
        }
      }
      expect(failures, `${themeName} text pairings below 4.5:1:\n${failures.join("\n")}`).toEqual([]);
    });
  }
});

describe("WCAG 1.4.11 — non-text UI and state indicators are at least 3:1", () => {
  for (const [themeName, t] of THEMES) {
    it(`${themeName}: control boundaries and focus clear 3:1`, () => {
      const failures: string[] = [];
      for (const tok of NON_TEXT) {
        for (const surf of SURFACES) {
          const fg = t[tok];
          const bg = t[surf];
          if (!fg || !bg) continue;
          const r = contrast(fg, bg);
          if (r !== null && r < 3) failures.push(`${tok} on ${surf} = ${round2(r)}:1`);
        }
      }
      expect(failures, `${themeName} non-text pairings below 3:1:\n${failures.join("\n")}`).toEqual([]);
    });

    it(`${themeName}: every semantic colour clears 4.5:1 on the surfaces it labels`, () => {
      // Semantic tokens always carry a word, so the text floor applies, not the 3:1 floor.
      const failures: string[] = [];
      for (const tok of SEMANTIC) {
        for (const surf of ["--surface-1", "--surface-2", "--surface-3"]) {
          const fg = t[tok];
          const bg = t[surf];
          if (!fg || !bg) continue;
          const r = contrast(fg, bg);
          if (r !== null && r < 4.5) failures.push(`${tok} on ${surf} = ${round2(r)}:1`);
        }
      }
      expect(failures, `${themeName} semantic pairings below 4.5:1:\n${failures.join("\n")}`).toEqual([]);
    });
  }
});

describe("D8 — a semantic ramp survives greyscale", () => {
  for (const [themeName, t] of THEMES) {
    it(`${themeName}: adjacent severity steps differ measurably in luminance`, () => {
      const ramp = ["--sev-info", "--sev-low", "--sev-medium", "--sev-high", "--sev-critical"]
        .map((k) => t[k])
        .filter((v): v is string => typeof v === "string");
      expect(ramp.length).toBe(5);
      const lums = ramp.map((h) => luminance(h)!);
      const failures: string[] = [];
      for (let i = 1; i < lums.length; i++) {
        const a = lums[i - 1]!;
        const b = lums[i]!;
        const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        // 1.12:1 between neighbours is the floor the token file commits to.
        if (ratio < 1.12) failures.push(`steps ${i - 1}->${i} differ by only ${round2(ratio)}:1`);
      }
      expect(failures, `${themeName} severity ramp collapses in greyscale:\n${failures.join("\n")}`).toEqual([]);
    });
  }
});

describe("the ratios quoted in comments are the real ones", () => {
  it("every `N.NN:1` written next to a token matches a computed pairing", () => {
    /* This is what turns the header's claim from an assertion into a fact. For each token line
       carrying quoted ratios, compute that token against every surface in its own theme and
       require each quoted figure to match one of them within rounding. A comment that drifts away
       from its value is worse than no comment: it is documentation that lies. */
    const mismatches: string[] = [];
    let checked = 0;

    for (const [themeName, t] of THEMES) {
      const sel = themeName === "light" ? /^:root\s*\{/m : /^\[data-theme="dark"\]\s*\{/m;
      const m = sel.exec(css);
      if (!m) continue;
      const block = css.slice(m.index);
      const end = block.indexOf("\n}");
      const scope = end === -1 ? block : block.slice(0, end);

      for (const line of scope.split("\n")) {
        const tok = /(--[a-z0-9-]+)\s*:\s*#[0-9a-fA-F]{3,8}\s*;/.exec(line);
        if (!tok) continue;
        const quoted = [...line.matchAll(/(\d+\.\d+):1/g)].map((m) => Number(m[1]));
        if (quoted.length === 0) continue;
        const fg = t[tok[1]!];
        if (!fg) continue;

        /* A token's quoted ratio is usually against a surface, but not always: `--accent-text` is
           the ink used ON `--accent`, and `6.02:1 on --accent` is the pairing that matters for it.
           So the candidate grounds are the surfaces PLUS, for any `--x-text` token, `--x` itself. */
        const base = tok[1]!.endsWith("-text") ? tok[1]!.slice(0, -"-text".length) : null;
        const grounds = [...SURFACES, ...(base ? [base] : [])];
        const computed = grounds
          .map((s) => t[s])
          .filter((bg): bg is string => typeof bg === "string")
          .map((bg) => contrast(fg, bg))
          .filter((r): r is number => r !== null)
          .map(round2);

        for (const q of quoted) {
          checked++;
          const near = computed.some((c) => Math.abs(c - q) <= 0.02);
          if (!near) {
            mismatches.push(
              `${themeName} ${tok[1]}: comment says ${q}:1 but computed values are ${computed.join(", ")}`,
            );
          }
        }
      }
    }

    // Without this, a parser that found no quoted ratios would make the audit vacuously green.
    expect(checked, "no quoted ratios were found to verify — the parser is broken").toBeGreaterThan(10);
    expect(mismatches, `comments disagree with computed contrast:\n${mismatches.join("\n")}`).toEqual([]);
  });
});
