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
 *   1. Parses the real token values out of tokens.css for every palette block: light, explicit
 *      dark, and the OS-preference dark block (which it also pins equal to the explicit one).
 *   2. Computes WCAG 2.x relative-luminance contrast for every pairing the UI actually uses and
 *      asserts the floors — 4.5:1 for text (1.4.3), 3:1 for non-text UI and state (1.4.11).
 *   3. Re-derives every ratio QUOTED in a comment and fails if the quoted number is wrong, so the
 *      comments cannot drift away from the values they describe.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
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

/* The THREE blocks that set a palette. The dark palette is emitted twice (tokens.css, "dark theme"):
   once for an explicit `[data-theme="dark"]`, once for a reader whose OS asks for dark and who has
   not chosen — `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`. The audit
   used to parse only the first two, so the palette most dark-mode readers actually get was never
   measured (independent critic, 2026-09-22). It is now its own audited theme, AND pinned
   declaration-for-declaration to the explicit block below. */
const LIGHT_SEL = /^:root\s*\{/m;
const DARK_SEL = /^\[data-theme="dark"\]\s*\{/m;
const DARK_OS_SEL = /^[ \t]+:root:not\(\[data-theme="light"\]\)\s*\{/m;
const light = tokensIn(LIGHT_SEL);
const darkExplicit = tokensIn(DARK_SEL);
const darkOsExplicit = tokensIn(DARK_OS_SEL);
// Dark inherits everything light defines and overrides only what differs.
const dark = { ...light, ...darkExplicit };
const darkOs = { ...light, ...darkOsExplicit };

/** Every custom-property declaration in a block, whatever its value — not only the hex ones. */
function declarationsIn(selector: RegExp): Map<string, string> {
  const m = selector.exec(css);
  const out = new Map<string, string>();
  if (!m) return out;
  let i = css.indexOf("{", m.index);
  const start = i;
  let depth = 0;
  for (; i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}") {
      depth--;
      if (depth === 0) break;
    }
  }
  const body = css.slice(start + 1, i).replace(/\/\*[\s\S]*?\*\//g, "");
  for (const d of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) out.set(d[1]!, d[2]!.replace(/\s+/g, " ").trim());
  return out;
}

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
  ["dark (OS preference)", darkOs],
];

/** The block each theme's own tokens (and quoted ratios) are written in. */
const THEME_SELECTOR: Record<string, RegExp> = {
  light: LIGHT_SEL,
  dark: DARK_SEL,
  "dark (OS preference)": DARK_OS_SEL,
};

/**
 * Measure `fg` on `bg` for every pair, and account for every pair. A pair whose token is missing
 * or is not a hex value used to be skipped with a bare `continue`, so a renamed token or a value
 * rewritten as `rgb()` / `color-mix()` dropped out of the audit silently and the audit still
 * passed. An unmeasurable pair is now a failure of its own, and the number of pairs actually
 * measured is returned so each caller can pin it to the size of its matrix.
 */
function measure(
  t: Record<string, string>,
  fgs: readonly string[],
  bgs: readonly string[],
  floor: number,
): { failures: string[]; measured: number } {
  const failures: string[] = [];
  let measured = 0;
  for (const fgTok of fgs) {
    for (const bgTok of bgs) {
      const fg = t[fgTok];
      const bg = t[bgTok];
      const r = fg !== undefined && bg !== undefined ? contrast(fg, bg) : null;
      if (r === null) {
        failures.push(`${fgTok} on ${bgTok} could not be measured (${fg ?? "missing"} on ${bg ?? "missing"})`);
        continue;
      }
      measured += 1;
      if (r < floor) failures.push(`${fgTok} on ${bgTok} = ${round2(r)}:1`);
    }
  }
  return { failures, measured };
}

describe("tokens.css parses", () => {
  it("finds every theme block, so an audit cannot pass by having nothing to audit", () => {
    expect(Object.keys(light).length).toBeGreaterThan(20);
    expect(Object.keys(darkExplicit).length).toBeGreaterThan(10);
    expect(Object.keys(darkOsExplicit).length).toBeGreaterThan(10);
    expect(light["--text"]).toBeDefined();
    expect(dark["--text"]).toBeDefined();
    expect(light["--text"]).not.toBe(dark["--text"]);
  });

  it("the OS-preference dark block declares exactly what the explicit dark block declares", () => {
    /* tokens.css: "Keep the two blocks in sync — a divergence here is invisible until someone
       toggles the theme." This is that check, over EVERY declaration (shadows and scrims too, not
       only the hex tokens the contrast audit reads). */
    const os = declarationsIn(DARK_OS_SEL);
    const explicit = declarationsIn(DARK_SEL);
    expect(os.size).toBeGreaterThan(10);
    const diff: string[] = [];
    for (const k of new Set([...os.keys(), ...explicit.keys()])) {
      if (os.get(k) !== explicit.get(k)) diff.push(`${k}: OS block ${os.get(k) ?? "absent"} / explicit ${explicit.get(k) ?? "absent"}`);
    }
    expect(diff, `the two dark blocks diverge:\n${diff.join("\n")}`).toEqual([]);
  });
});

describe("WCAG 1.4.3 — text contrast is at least 4.5:1", () => {
  for (const [themeName, t] of THEMES) {
    it(`${themeName}: every ink token clears 4.5:1 on every surface it can sit on`, () => {
      const { failures, measured } = measure(t, INK_TEXT, SURFACES, 4.5);
      expect(measured, "every ink x surface pair was measured").toBe(INK_TEXT.length * SURFACES.length);
      expect(failures, `${themeName} text pairings below 4.5:1:\n${failures.join("\n")}`).toEqual([]);
    });
  }
});

describe("WCAG 1.4.11 — non-text UI and state indicators are at least 3:1", () => {
  for (const [themeName, t] of THEMES) {
    it(`${themeName}: control boundaries and focus clear 3:1`, () => {
      const { failures, measured } = measure(t, NON_TEXT, SURFACES, 3);
      expect(measured, "every non-text x surface pair was measured").toBe(NON_TEXT.length * SURFACES.length);
      expect(failures, `${themeName} non-text pairings below 3:1:\n${failures.join("\n")}`).toEqual([]);
    });

    it(`${themeName}: every semantic colour clears 4.5:1 on the surfaces it labels`, () => {
      // Semantic tokens always carry a word, so the text floor applies, not the 3:1 floor.
      const LABEL_SURFACES = ["--surface-1", "--surface-2", "--surface-3"];
      const { failures, measured } = measure(t, SEMANTIC, LABEL_SURFACES, 4.5);
      expect(measured, "every semantic x surface pair was measured").toBe(SEMANTIC.length * LABEL_SURFACES.length);
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
      const sel = THEME_SELECTOR[themeName];
      const m = sel?.exec(css);
      expect(m, `${themeName}: its token block was not found`).toBeTruthy();
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

/* ── text under the scroll-edge shadow ───────────────────────────────────────── */

describe("WCAG 1.4.3 — text scrolled under the scroll-edge shadow keeps 4.5:1", () => {
  /*
   * Every scroll region paints a 4px shadow at its bottom edge (shell.css, "THE CUT-ROW SCRIM";
   * Inspector.css has an opt-in copy), and rows scroll UNDER it. At 22% black the light theme's
   * edge-clipped text measured 3.92:1 (5th percentile) and an Inspector key 3.62:1 (acceptance D4,
   * 2026-09-24). The shadow's ink is now the theme token `--scroll-scrim-ink`; this composites it,
   * at its darkest row, over each ground a scroll region has (--bg by default, --surface-1 in the
   * rails and the Inspector) and requires every ink token to keep 4.5:1 there.
   */
  const SCROLL_GROUNDS = ["--bg", "--surface-1"];
  const scrimBlocks: [string, RegExp][] = [
    ["light", LIGHT_SEL],
    ["dark", DARK_SEL],
    ["dark (OS preference)", DARK_OS_SEL],
  ];
  for (const [themeName, sel] of scrimBlocks) {
    it(`${themeName}: every ink token clears 4.5:1 on the shadow's darkest row`, () => {
      const raw = declarationsIn(sel).get("--scroll-scrim-ink");
      expect(raw, `${themeName} declares no --scroll-scrim-ink`).toBeDefined();
      const m = /^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\/\s*([\d.]+)%\s*\)$/.exec(raw ?? "");
      expect(m, `--scroll-scrim-ink must be an rgb()/alpha value this audit can composite, got ${raw}`).toBeTruthy();
      if (!m) return;
      const ink = [Number(m[1]), Number(m[2]), Number(m[3])];
      const a = Number(m[4]) / 100;
      const t = THEMES.find(([n]) => n === themeName)![1];
      const failures: string[] = [];
      let measured = 0;
      for (const gTok of SCROLL_GROUNDS) {
        const g = parseHex(t[gTok]!)!;
        const under = g.map((c, i) => Math.round(c * (1 - a) + ink[i]! * a));
        const hex = `#${under.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
        for (const inkTok of INK_TEXT) {
          const r = contrast(t[inkTok]!, hex)!;
          measured += 1;
          if (r < 4.5) failures.push(`${inkTok} on ${gTok} under the shadow (${hex}) = ${round2(r)}:1`);
        }
      }
      expect(measured).toBe(SCROLL_GROUNDS.length * INK_TEXT.length);
      expect(failures, `${themeName} text under the scroll shadow below 4.5:1:\n${failures.join("\n")}`).toEqual([]);
    });
  }

  it("every use of the shadow ink is the token itself, with no private fallback this audit never composites", () => {
    /* The audit above composites the token's value. A `var(--scroll-scrim-ink, <fallback>)` carries a
       second ink it never reads; the Inspector's copy carried the retired 22% black, the value that
       measured 3.62:1. tokens.css defines the token in every theme block, so a fallback is dead
       today and a regression the moment a block loses the token. */
    const SRC_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
    const walkCss = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
        const p = join(dir, e.name);
        return e.isDirectory() ? walkCss(p) : e.name.endsWith(".css") ? [p] : [];
      });
    let uses = 0;
    const withFallback: string[] = [];
    for (const file of walkCss(SRC_DIR)) {
      const text = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      for (const m of text.matchAll(/var\(\s*--scroll-scrim-ink\s*(,)?/g)) {
        uses += 1;
        if (m[1] !== undefined) withFallback.push(file.slice(SRC_DIR.length + 1).replace(/\\/g, "/"));
      }
    }
    expect(uses, "no stylesheet paints the scroll shadow — the reader is broken").toBeGreaterThanOrEqual(2);
    expect(withFallback).toEqual([]);
  });
});

/* ── non-text tokens are never used as text ink ─────────────────────────────── */

describe("WCAG 1.4.3 — a token tokens.css declares non-text is never a text colour", () => {
  /*
   * The class, not a list: every token whose own definition comment says "non-text" is collected
   * from tokens.css, so a new non-text token is guarded the moment it is written down. The palette
   * citation shipped at 4.09:1 because `.palette__cite` used `--claim-out-of-scope` as `color:`
   * while the token comment said "NON-TEXT only"; only the highlighted row switched ink.
   */
  const nonText = new Set<string>(NON_TEXT);
  for (const line of css.split("\n")) {
    const m = /^\s*(--[\w-]+)\s*:[^;]*;\s*\/\*(.*)$/.exec(line);
    if (m?.[1] && /non-text/i.test(m[2] ?? "")) nonText.add(m[1]);
  }

  const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  function cssFiles(dir: string): string[] {
    const out: string[] = [];
    for (const ent of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, ent.name);
      if (ent.isDirectory()) out.push(...cssFiles(p));
      else if (ent.name.endsWith(".css") && p !== TOKENS) out.push(p);
    }
    return out;
  }

  it("finds the non-text tokens, so the guard cannot pass vacuously", () => {
    expect([...nonText]).toContain("--claim-out-of-scope");
    expect(nonText.size).toBeGreaterThanOrEqual(3);
  });

  it("no `color:` declaration in src/**/*.css names a non-text token", () => {
    const offenders: string[] = [];
    const files = cssFiles(SRC);
    expect(files.length).toBeGreaterThan(5);
    for (const file of files) {
      const text = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "));
      // Rule bodies. A rule whose generated content carries an EMPTY alternative (`/ ""`) is pure
      // decoration with no text node (WCAG 1.4.3 exempts it) — `.sb__dot::before` is the case.
      for (const rule of text.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
        const body = rule[2] ?? "";
        if (/content\s*:[^;]*\/\s*""/.test(body)) continue;
        for (const decl of body.matchAll(/(?:^|[;\s])color\s*:\s*([^;]+)/g)) {
          for (const tok of nonText) {
            if (new RegExp(String.raw`var\(\s*${tok}\s*[,)]`).test(decl[1] ?? "")) {
              offenders.push(`${file.slice(SRC.length + 1)} ${(rule[1] ?? "").trim()} → ${tok}`);
            }
          }
        }
      }
    }
    expect(offenders, `non-text tokens used as text ink:\n${offenders.join("\n")}`).toEqual([]);
  });
});

/* ══ the design brief's colour table is a CACHE of this file (design-brief §3.3, open-issues O20) ══

   The brief states "Owner: src/core/tokens.css. The hex values below are a cache of it". O20 found
   31 colour tokens (18 light, 13 dark) had drifted — `--sev-high` read `#a14a0a` there while this
   file shipped `#803804` — and nothing pinned the cache to its owner, so the drift can recur. The
   denominator is every `--token: #hex` the brief's §3.3.1 and §3.3.2 code blocks state (not a list
   of names), plus every fill in its severity-chip table; each must equal the shipped value. */
describe("design-brief §3.3 restates tokens.css exactly", () => {
  const BRIEF = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "design-brief.md");
  const brief = readFileSync(BRIEF, "utf8").replace(/\r\n/g, "\n");
  /** The first ```css block after a heading line that starts with `heading`. */
  const cssBlockAfter = (heading: string): string => {
    const at = brief.indexOf(`\n${heading}`);
    if (at < 0) return "";
    const open = brief.indexOf("```css\n", at);
    const close = open < 0 ? -1 : brief.indexOf("\n```", open + 7);
    return open < 0 || close < 0 ? "" : brief.slice(open + 7, close);
  };
  const hexTokens = (block: string): [string, string][] =>
    [...block.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;/g)].map((m) => [m[1]!, m[2]!.toLowerCase()]);

  const THEMES: { heading: string; shipped: Record<string, string> }[] = [
    { heading: "#### 3.3.1", shipped: light },
    { heading: "#### 3.3.2", shipped: dark },
  ];

  for (const t of THEMES) {
    it(`${t.heading}: every hex token the brief states equals the shipped token`, () => {
      const stated = hexTokens(cssBlockAfter(t.heading));
      expect(stated.length, `${t.heading} states no colour tokens — the parser or the brief moved`).toBeGreaterThan(20);
      const drift = stated
        .filter(([name, hex]) => (t.shipped[name] ?? "(not shipped)").toLowerCase() !== hex)
        .map(([name, hex]) => `${name}: brief ${hex}, tokens.css ${t.shipped[name] ?? "(not shipped)"}`);
      expect(drift).toEqual([]);
    });
  }

  it("the severity-chip table's fills are the shipped severity tokens", () => {
    const rows = [...brief.matchAll(/^\| (Critical|High|Medium|Low) \| `(#[0-9a-fA-F]{6})` → \*\*[\d.]+:1\*\* \| `(#[0-9a-fA-F]{6})` → \*\*[\d.]+:1\*\* \|$/gm)];
    expect(rows.map((r) => r[1])).toEqual(["Critical", "High", "Medium", "Low"]);
    for (const r of rows) {
      const tok = `--sev-${r[1]!.toLowerCase()}`;
      expect(r[2]!.toLowerCase(), `${tok} dark`).toBe(dark[tok]!.toLowerCase());
      expect(r[3]!.toLowerCase(), `${tok} light`).toBe(light[tok]!.toLowerCase());
    }
  });
});
