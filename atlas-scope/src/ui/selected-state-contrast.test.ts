/**
 * selected-state-contrast.test.ts — a selected / current / checked / pressed / active state must be
 * carried by at least one visual channel that differs from the UNSELECTED appearance by >= 3:1
 * (WCAG 2.2 SC 1.4.11, "visual information required to identify … states"), in BOTH themes.
 *
 * THE DEFECT THIS PINS (acceptance D4, overturned 2026-09-24 by an independent refuter, measured on
 * rendered pixels): the Queue/Evidence pane switch (`.paneswitch__btn`, role=radio) marked its
 * checked option with a fill change of 1.17:1 (light) / 1.20:1 (dark) and an ink change of
 * 2.52:1 / 2.20:1, and its checked rule restated the SAME `--border-strong` edge the unchecked
 * option already drew — so the border was present in both states and carried no state at all.
 * The same fill-plus-ink-only shape sat in `.ui-btn[aria-pressed="true"]`.
 *
 * STATED OVER THE CLASS, NOT A LIST OF NAMES.
 *   - The state VOCABULARY is derived from what the components render: the four ARIA selection
 *     states (aria-selected / aria-checked / aria-pressed / aria-current), plus every `data-*`
 *     attribute a component renders ON THE SAME ELEMENT as one of those and following the SAME
 *     boolean (the visual twin of an ARIA state, e.g. `data-highlight` beside `aria-current`), plus
 *     every `data-*` attribute whose own name says it is a selection state (a hyphen segment
 *     `active`, `selected`, `current`, `checked` or `pressed`), plus a predicate whose VALUE is one
 *     of those words on an attribute some component writes (in JSX, `el.dataset.x = …` or
 *     `setAttribute`) — the 3D label's `data-state="selected"`. `:checked` and `--active`-style
 *     class modifiers are matched too.
 *   - EVERY rule in EVERY stylesheet under src/ whose selector carries one of those predicates is
 *     collected (forced-colors and print blocks excepted: the system palette owns those, and D8
 *     covers them). A new selected state is audited the moment it is written.
 *   - Each state is paired with its unselected appearance (the base rules for the same subject),
 *     and every channel the state rule changes is measured against the SAME spot in the unselected
 *     state, with tokens resolved from tokens.css in the light AND dark blocks:
 *        fill    on-fill vs off-fill (transparent resolves to the ground under it)
 *        ink     on-ink vs off-ink
 *        border  on-edge vs off-edge, per side (transparent resolves to the fill behind it)
 *        bar     an inset box-shadow, or a generated ::before/::after, against BOTH the on-fill it
 *                is drawn over and whatever occupied that spot in the off state
 *        outline against what is beside it (the ground, or the fill for a negative offset) and
 *                against what occupied that spot in the off state
 *     Only what actually DIFFERS after the cascade (specificity, then source order) is a channel.
 *   - A selected state must survive every other persistent state the same element can carry at the
 *     same time (a co-state: same stylesheet, same element class, an attribute condition that does
 *     not exclude the selection, and evidence in the components that both attributes sit on one
 *     element). Each pairing is measured as selected-with-co-state against unselected-with-co-state:
 *     the 3D label's accent outline was repainted by the cut-point, finding and alarm outlines, so a
 *     selected label under any of them was identical to an unselected one.
 *   - The ground is unknown to a source reader, so every surface token is tried and the WORST one
 *     decides. The state passes when, on every ground, its best channel reaches 3:1.
 *
 * This is a tripwire on source + tokens (acceptance D4 says so of every source-reading test); the
 * rendered measurement is the browser figure recorded with the repair.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TOKENS = join(SRC, "core", "tokens.css");

const walk = (dir: string, ext: string): string[] =>
  readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return walk(p, ext);
    return p.endsWith(ext) && !/\.test\.tsx?$/.test(p) ? [p] : [];
  });
const rel = (p: string): string => p.slice(SRC.length + 1).replace(/\\/g, "/");

/* ── colour maths: WCAG 2.x, the same formulae as src/core/contrast.test.ts ──────────────── */

type RGB = [number, number, number];
const lin = (c: number): number => {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const luminance = ([r, g, b]: RGB): number => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const contrast = (a: RGB, b: RGB): number => {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
};
const round2 = (n: number): number => Math.round(n * 100) / 100;

const parseHex = (hex: string): RGB | null => {
  const h = hex.trim().replace(/^#/, "");
  const full = h.length === 3 || h.length === 4 ? [...h.slice(0, 3)].map((c) => c + c).join("") : h.slice(0, 6);
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null;
  if (h.length === 8 && h.slice(6).toLowerCase() !== "ff") return null; // translucent: not measurable here
  return [parseInt(full.slice(0, 2), 16), parseInt(full.slice(2, 4), 16), parseInt(full.slice(4, 6), 16)];
};

/* oklab, for `color-mix(in oklab, …)` between two opaque colours. */
const toOklab = ([r, g, b]: RGB): RGB => {
  const [lr, lg, lb] = [lin(r), lin(g), lin(b)];
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
};
const fromOklab = ([L, a, b]: RGB): RGB => {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const enc = (x: number): number => {
    const v = x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055;
    return Math.max(0, Math.min(255, Math.round(v * 255)));
  };
  return [
    enc(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    enc(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    enc(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
};

/* ── the two palettes, read from tokens.css exactly as contrast.test.ts reads them ────────── */

const tokensCss = readFileSync(TOKENS, "utf8");
function tokensIn(selector: RegExp): Record<string, string> {
  const m = selector.exec(tokensCss);
  if (!m) return {};
  let i = tokensCss.indexOf("{", m.index);
  const start = i;
  let depth = 0;
  for (; i < tokensCss.length; i++) {
    if (tokensCss[i] === "{") depth++;
    else if (tokensCss[i] === "}" && --depth === 0) break;
  }
  const out: Record<string, string> = {};
  const body = tokensCss.slice(start + 1, i).replace(/\/\*[\s\S]*?\*\//g, "");
  for (const d of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) out[d[1]!] = d[2]!.replace(/\s+/g, " ").trim();
  return out;
}
const LIGHT = tokensIn(/^:root\s*\{/m);
const DARK = { ...LIGHT, ...tokensIn(/^\[data-theme="dark"\]\s*\{/m) };
const THEMES: [string, Record<string, string>][] = [
  ["light", LIGHT],
  ["dark", DARK],
];
const SURFACES = ["--bg", "--surface-1", "--surface-2", "--surface-3", "--overlay", "--stage-bg"];

/** A colour value → RGB, "transparent", or null when it cannot be measured from source. */
type Paint = RGB | "transparent" | null;
function resolveColour(raw: string, t: Record<string, string>, depth = 0): Paint {
  const v = raw.trim().replace(/\s*!important$/, "");
  if (depth > 8) return null;
  if (/^(transparent|none)$/i.test(v)) return "transparent";
  const hex = /^#[0-9a-fA-F]{3,8}$/.exec(v);
  if (hex) return parseHex(v);
  const rgb = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*(?:[/,]\s*([\d.]+%?))?\s*\)$/.exec(v);
  if (rgb) {
    const a = rgb[4];
    if (a !== undefined && !(a === "1" || a === "100%")) return null;
    return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  }
  const vr = /^var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)$/.exec(v);
  if (vr) {
    const val = t[vr[1]!];
    if (val !== undefined) return resolveColour(val, t, depth + 1);
    return vr[2] !== undefined ? resolveColour(vr[2], t, depth + 1) : null;
  }
  const mix = /^color-mix\(\s*in\s+oklab\s*,\s*(.+?)\s+(\d+(?:\.\d+)?)%\s*,\s*(.+?)(?:\s+(\d+(?:\.\d+)?)%)?\s*\)$/.exec(v);
  if (mix) {
    const a = resolveColour(mix[1]!, t, depth + 1);
    const b = resolveColour(mix[3]!, t, depth + 1);
    if (!Array.isArray(a) || !Array.isArray(b)) return null; // a mix with transparent is translucent
    const p = Number(mix[2]) / 100;
    const [A, B] = [toOklab(a), toOklab(b)];
    return fromOklab([A[0] * p + B[0] * (1 - p), A[1] * p + B[1] * (1 - p), A[2] * p + B[2] * (1 - p)]);
  }
  return null;
}

/** Split a value on top-level whitespace / commas (not inside parentheses). */
function topLevel(value: string, sep: RegExp): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of value) {
    if (ch === "(") depth++;
    if (ch === ")") depth--;
    if (depth === 0 && sep.test(ch)) {
      if (cur.trim()) out.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

/** The colour component of a shorthand (`border`, `background`, one box-shadow), or undefined. */
function colourIn(value: string, t: Record<string, string>): Paint | undefined {
  if (/^(0|none)$/.test(value.trim())) return "transparent";
  for (const part of topLevel(value, /\s/)) {
    if (/^(inset|solid|dashed|dotted|double|none)$/.test(part)) continue;
    const c = resolveColour(part, t);
    if (c !== null) return c;
    if (/^(transparent|#|rgb|color-mix)/.test(part)) return null;
    if (/^var\(/.test(part)) {
      const name = /^var\(\s*(--[\w-]+)/.exec(part)?.[1] ?? "";
      const val = t[name];
      // a var() that resolves to a length (e.g. --hairline) is not the colour; anything else is
      if (val !== undefined && /^-?[\d.]+(px|rem|em|%)?$/.test(val)) continue;
      if (val !== undefined) return null;
    }
  }
  return undefined;
}

/* ── the stylesheet reader ─────────────────────────────────────────────────────────────── */

type Rule = { file: string; line: number; media: string; selector: string; decls: [string, string][] };

function parseCss(file: string): Rule[] {
  const raw = readFileSync(file, "utf8");
  const text = raw.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "));
  const out: Rule[] = [];
  const stack: { at?: string; sel?: string; from: number; line: number }[] = [];
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "{") {
      const prelude = text.slice(start, i).trim();
      const line = text.slice(0, i).split("\n").length;
      stack.push(prelude.startsWith("@") ? { at: prelude, from: i + 1, line } : { sel: prelude, from: i + 1, line });
      start = i + 1;
    } else if (ch === "}") {
      const top = stack.pop();
      if (top?.sel !== undefined) {
        const decls: [string, string][] = [];
        for (const d of text.slice(top.from, i).split(";")) {
          const m = /^\s*([\w-]+)\s*:\s*([\s\S]+?)\s*$/.exec(d);
          if (m) decls.push([m[1]!.toLowerCase(), m[2]!.replace(/\s+/g, " ").replace(/\s*!important$/, "")]);
        }
        const media = stack.filter((s) => s.at !== undefined).map((s) => s.at).join(" ");
        for (const sel of topLevel(top.sel, /,/)) out.push({ file: rel(file), line: top.line, media, selector: sel, decls });
      }
      start = i + 1;
    } else if (ch === ";" && (stack.length === 0 || stack[stack.length - 1]!.at !== undefined)) {
      start = i + 1;
    }
  }
  return out;
}

const RULES: Rule[] = walk(SRC, ".css").flatMap(parseCss);
/** Rules the system palette owns (forced-colors) or paper owns (print) are out of scope. */
const screenRules = RULES.filter((r) => !/forced-colors|\bprint\b/.test(r.media));

/* ── the state vocabulary, derived from what the components render ──────────────────────── */

const ARIA_SELECTION = ["aria-selected", "aria-checked", "aria-pressed", "aria-current"];
const SELECTION_WORD = /(?:^|-)(active|selected|current|checked|pressed)(?:-|$)/;

type Tag = { file: string; text: string; attrs: Map<string, string> };

/** Every JSX opening tag in the component source, with its attributes (incl. spread-object keys). */
function jsxTags(): Tag[] {
  const out: Tag[] = [];
  for (const f of walk(SRC, ".tsx")) {
    const src = readFileSync(f, "utf8");
    for (const m of src.matchAll(/<([A-Za-z][\w.]*)(?=[\s/>])/g)) {
      let i = (m.index ?? 0) + m[0].length;
      let depth = 0;
      let quote: string | null = null;
      for (; i < src.length; i++) {
        const ch = src[i]!;
        if (quote) {
          if (ch === "\\") i++;
          else if (ch === quote) quote = null;
          continue;
        }
        if (depth > 0 && ch === "/" && src[i + 1] === "*") {
          const end = src.indexOf("*/", i + 2);
          i = end === -1 ? src.length : end + 1;
          continue;
        }
        if (depth > 0 && ch === "/" && src[i + 1] === "/") {
          const end = src.indexOf("\n", i);
          i = end === -1 ? src.length : end;
          continue;
        }
        if (ch === '"' || ch === "'" || ch === "`") {
          if (depth > 0 || ch === '"') quote = ch;
          continue;
        }
        if (ch === "{") depth++;
        else if (ch === "}") depth--;
        else if (ch === ">" && depth === 0) break;
      }
      const text = src.slice(m.index ?? 0, i + 1);
      const attrs = new Map<string, string>();
      // attr={expr} or attr="lit": take the balanced value
      for (const a of text.matchAll(/\s((?:aria|data)-[\w-]+)=/g)) {
        let j = (a.index ?? 0) + a[0].length;
        let value = "";
        if (text[j] === '"') value = text.slice(j, text.indexOf('"', j + 1) + 1);
        else if (text[j] === "{") {
          let d = 0;
          const from = j;
          for (; j < text.length; j++) {
            if (text[j] === "{") d++;
            else if (text[j] === "}" && --d === 0) break;
          }
          value = text.slice(from, j + 1);
        }
        attrs.set(a[1]!, value);
      }
      // {...(cond ? { "data-x": "yes" } : {})}
      for (const s of text.matchAll(/\{\.\.\.\(([^?]+)\?\s*\{([^}]*)\}\s*:\s*\{\s*\}\s*\)\}/g)) {
        for (const k of s[2]!.matchAll(/"((?:aria|data)-[\w-]+)"\s*:\s*([^,}]+)/g)) attrs.set(k[1]!, `{${s[1]!.trim()} ? ${k[2]!.trim()} : undefined}`);
      }
      out.push({ file: rel(f), text, attrs });
    }
  }
  return out;
}

/**
 * The boolean an attribute's presence follows: `{c ? "true" : undefined}` → c, `{c || undefined}`
 * → c, `{c}` → c, `{c ? x : undefined}` (x not a literal) → x. A literal value follows nothing.
 */
function stateCondition(v: string): string | null {
  const body = /^\{([\s\S]*)\}$/.exec(v.trim())?.[1]?.replace(/\s+/g, " ").trim();
  if (!body) return null;
  const tern = /^(.+?)\s*\?\s*(.+?)\s*:\s*(undefined|null|false|"false"|"no")$/.exec(body);
  // Any LITERAL on the true branch (`"true"`, `"page"`, `"step"`, `1`) means presence follows the
  // test; only a non-literal (`batchable ? selected : undefined`) hands the boolean on.
  if (tern) return /^(true|"[^"]*"|'[^']*'|-?\d+)$/.test(tern[2]!) ? tern[1]!.replace(/^\((.*)\)$/, "$1") : tern[2]!;
  const or = /^(.+?)\s*\|\|\s*undefined$/.exec(body);
  if (or) return or[1]!;
  return body;
}

const TAGS = jsxTags();

/**
 * The ARIA selection states, plus a `data-*` attribute when its NAME says it is a selection state or
 * when it follows the SAME boolean as an ARIA selection state on the same element (its visual twin:
 * `data-highlight` and `aria-current` both follow `r.id === highlight`). A `data-*` attribute that
 * merely sits beside one — `data-kind`, `data-col`, `data-headhidden` — is not a state of selection.
 */
function stateVocabulary(): Set<string> {
  const vocab = new Set<string>(ARIA_SELECTION);
  for (const tag of TAGS) {
    const ariaConds = new Set(
      ARIA_SELECTION.filter((a) => tag.attrs.has(a))
        .map((a) => stateCondition(tag.attrs.get(a)!))
        .filter((c): c is string => c !== null),
    );
    for (const [name, value] of tag.attrs) {
      if (!name.startsWith("data-")) continue;
      const cond = stateCondition(value);
      if (SELECTION_WORD.test(name.slice(5))) vocab.add(name);
      else if (cond !== null && ariaConds.has(cond)) vocab.add(name);
    }
  }
  return vocab;
}
const VOCAB = stateVocabulary();

/**
 * Every attribute a component WRITES — in JSX, through `el.dataset.x = …`, or through
 * `setAttribute("x", …)`. A state can be named by an attribute's VALUE rather than its name: the 3D
 * stage's labels are written imperatively (`el.dataset.state = "selected" | "hover" | ""`, in
 * FabricLabels.tsx), so no JSX carries them, and `data-state` is not a selection word. A CSS predicate
 * `[attr="<selection word>"]` on an attribute some component writes is a selected state too.
 */
function renderedAttributes(): Set<string> {
  const out = new Set<string>();
  for (const tag of TAGS) for (const a of tag.attrs.keys()) out.add(a);
  const kebab = (camel: string): string => camel.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
  for (const f of [...walk(SRC, ".tsx"), ...walk(SRC, ".ts")]) {
    const src = readFileSync(f, "utf8");
    for (const m of src.matchAll(/\.dataset\.([A-Za-z]\w*)\s*=(?!=)/g)) out.add(`data-${kebab(m[1]!)}`);
    for (const m of src.matchAll(/\.setAttribute\(\s*["']((?:aria|data)-[\w-]+)["']/g)) out.add(m[1]!);
  }
  return out;
}
const RENDERED_ATTRS = renderedAttributes();
const SELECTION_VALUE = /^(active|selected|current|checked|pressed)$/;

/* ── state rules, and the unselected appearance they are measured against ─────────────────── */

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** Attribute predicates that name a selected state; `="false"`/`="no"` and anything under :not() are not one. */
function statePredicates(compound: string): string[] {
  // :not() negates and :has() is about a DESCENDANT: neither states the subject's own selection.
  const outer = compound.replace(/:(?:not|has)\((?:[^()]|\([^()]*\))*\)/g, "");
  const out: string[] = [];
  for (const m of outer.matchAll(/\[\s*([\w-]+)\s*(?:=\s*"([^"]*)")?\s*\]/g)) {
    const byName = VOCAB.has(m[1]!);
    const byValue = m[2] !== undefined && SELECTION_VALUE.test(m[2]) && RENDERED_ATTRS.has(m[1]!);
    if (!byName && !byValue) continue;
    if (m[2] !== undefined && /^(false|no|mixed)$/.test(m[2])) continue;
    out.push(m[0]);
  }
  if (/:checked\b/.test(outer)) out.push(":checked");
  for (const m of outer.matchAll(/\.[\w-]+--(active|selected|current|checked|pressed)\b/g)) out.push(m[0]);
  return out;
}

/** A selector split into compounds (descendant/child combinators only — the stylesheets use no others). */
const compounds = (sel: string): string[] =>
  topLevel(sel.replace(/\s*>\s*/g, " "), /\s/).map((c) => c.replace(/\(\s+/g, "(").replace(/\s+\)/g, ")").replace(/\s+/g, " "));
const stripState = (compound: string, preds: string[]): string =>
  preds.reduce((c, p) => (p.startsWith(".") ? c.replace(new RegExp(`${escapeRe(p)}(?![\\w-])`), "") : c.replace(p, "")), compound);
const pseudoOf = (compound: string): string | null => /::?(before|after)\b/.exec(compound)?.[1] ?? null;
const withoutPseudo = (compound: string): string => compound.replace(/::?(before|after)\b/, "");

type Props = {
  fill?: string;
  ink?: string;
  sides: Record<string, string>;
  inset?: string;
  content: boolean;
  /** `outline` shorthand, a later `outline-color` override, and `outline-offset`. */
  outline?: string;
  outlineColour?: string;
  outlineOffset?: string;
};
const SIDE_KEYS: Record<string, string[]> = {
  border: ["top", "right", "bottom", "left"],
  "border-color": ["top", "right", "bottom", "left"],
  "border-block": ["top", "bottom"],
  "border-inline": ["left", "right"],
  "border-top": ["top"],
  "border-block-start": ["top"],
  "border-bottom": ["bottom"],
  "border-block-end": ["bottom"],
  "border-left": ["left"],
  "border-inline-start": ["left"],
  "border-right": ["right"],
  "border-inline-end": ["right"],
};
function applyDecls(p: Props, decls: [string, string][]): Props {
  const next: Props = { ...p, sides: { ...p.sides } };
  for (const [prop, value] of decls) {
    if (prop === "background" || prop === "background-color") next.fill = value;
    else if (prop === "color") next.ink = value;
    else if (prop === "box-shadow") next.inset = value;
    else if (prop === "content") next.content = !/^none$/.test(value);
    else if (prop === "outline") {
      next.outline = value;
      next.outlineColour = undefined;
    } else if (prop === "outline-color") next.outlineColour = value;
    else if (prop === "outline-offset") next.outlineOffset = value;
    else {
      const side = /^(border(?:-(?:top|bottom|left|right|block|inline|block-start|block-end|inline-start|inline-end))?)(-color)?$/.exec(prop);
      if (side) for (const s of SIDE_KEYS[side[1]!] ?? []) next.sides[s] = value;
    }
  }
  return next;
}
const EMPTY: Props = { sides: {}, content: false };

/** The outline as one comparable string: its colour (after any `outline-color`), or "" when none is drawn. */
const outlineOf = (p: Props): string => {
  // an `outline-color` with no outline style draws nothing (the initial style is none)
  if (p.outline === undefined || /^(none|0)$/.test(p.outline.trim())) return "";
  return p.outlineColour ?? p.outline;
};

/* ── the cascade: specificity, then source order ───────────────────────────────────────────── */

/** CSS specificity [ids, classes+attributes+pseudo-classes, types] of one selector. */
function specificity(selector: string): [number, number, number] {
  let s = selector;
  const acc: [number, number, number] = [0, 0, 0];
  const add = (x: [number, number, number]): void => {
    acc[0] += x[0];
    acc[1] += x[1];
    acc[2] += x[2];
  };
  // :where() counts nothing; :not()/:is()/:has() count their most specific argument.
  for (;;) {
    const m = /:(where|not|is|has)\(/.exec(s);
    if (!m) break;
    let i = m.index + m[0].length;
    let depth = 1;
    for (; i < s.length && depth > 0; i++) {
      if (s[i] === "(") depth++;
      else if (s[i] === ")") depth--;
    }
    const arg = s.slice(m.index + m[0].length, i - 1);
    if (m[1] !== "where") {
      const best = topLevel(arg, /,/)
        .map((a) => specificity(a.replace(/^\s*>\s*/, "")))
        .reduce((x, y) => (x[0] !== y[0] ? (x[0] > y[0] ? x : y) : x[1] !== y[1] ? (x[1] > y[1] ? x : y) : x[2] >= y[2] ? x : y), [0, 0, 0] as [number, number, number]);
      add(best);
    }
    s = s.slice(0, m.index) + " " + s.slice(i);
  }
  s = s.replace(/\[[^\]]*\]/g, () => {
    acc[1] += 1;
    return " ";
  });
  acc[0] += (s.match(/#[\w-]+/g) ?? []).length;
  acc[1] += (s.match(/\.[\w-]+/g) ?? []).length;
  acc[2] += (s.match(/::[\w-]+/g) ?? []).length;
  acc[1] += (s.replace(/::[\w-]+/g, " ").match(/:[\w-]+/g) ?? []).length;
  acc[2] += (s.replace(/[.#:][\w-]+/g, " ").match(/(?:^|[\s>+~])([a-z][\w-]*)/g) ?? []).length;
  return acc;
}
const cmpSpec = (a: [number, number, number], b: [number, number, number]): number => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
/** Rules that apply to one element, applied in cascade order (specificity, then file line). */
function cascade(start: Props, rules: Rule[]): Props {
  const sorted = [...rules].sort((a, b) => cmpSpec(specificity(a.selector), specificity(b.selector)) || a.line - b.line);
  return sorted.reduce((p, r) => applyDecls(p, r.decls), start);
}

/** The unselected appearance of a subject: its single-class rules, then the state-stripped selector. */
function baseProps(subjectCompound: string, strippedSelector: string, pseudo: string | null): Props {
  const plain = withoutPseudo(subjectCompound);
  const classes = [...plain.matchAll(/\.[\w-]+/g)].map((m) => m[0]);
  const want = new Set<string>();
  for (const c of classes) want.add(pseudo ? `${c}::${pseudo}` : c);
  const exact = strippedSelector.trim();
  let props = EMPTY;
  for (const r of screenRules) {
    if (r.media !== "") continue;
    const sel = r.selector.replace(/:(before|after)\b/, "::$1").replace(/:::/, "::");
    if (want.has(sel)) props = applyDecls(props, r.decls);
  }
  for (const r of screenRules) {
    if (r.media !== "") continue;
    const sel = r.selector.replace(/(?<!:):(before|after)\b/, "::$1");
    if (sel === exact && !want.has(sel)) props = applyDecls(props, r.decls);
  }
  return props;
}

type StateRule = { rule: Rule; key: string; ownerIndex: number; subject: string; pseudo: string | null; stripped: string };
function stateRules(): StateRule[] {
  const out: StateRule[] = [];
  for (const rule of screenRules) {
    const parts = compounds(rule.selector);
    parts.forEach((compound, idx) => {
      const preds = statePredicates(compound);
      if (preds.length === 0) return;
      const owner = /\.[\w-]+/.exec(withoutPseudo(stripState(compound, preds)))?.[0] ?? withoutPseudo(stripState(compound, preds));
      for (const p of preds) {
        const stripped = parts
          .map((c) => stripState(c, statePredicates(c)))
          .map((c, i) => (i === parts.length - 1 ? withoutPseudo(c) : c))
          .join(" ");
        const subject = parts[parts.length - 1]!;
        out.push({ rule, key: `${owner}${p}`, ownerIndex: idx, subject, pseudo: pseudoOf(subject), stripped });
      }
    });
  }
  return out;
}
const STATE_RULES = stateRules();

type Channel = { name: string; ratio: number };
/** Every channel one state rule changes, measured on ground `g`. */
function channels(sr: StateRule, t: Record<string, string>, g: RGB, co: Rule[] | null = null): { measured: Channel[]; unmeasured: string[] } {
  const measured: Channel[] = [];
  const unmeasured: string[] = [];
  const subjectPlain = stripState(sr.subject, statePredicates(sr.subject));
  const where = `${sr.rule.file}:${sr.rule.line}`;
  const paint = (v: string | undefined, fallback: RGB): RGB | null => {
    if (v === undefined) return fallback;
    const c = colourIn(v, t);
    if (c === undefined || c === "transparent") return fallback;
    return c;
  };

  if (sr.pseudo === null) {
    /* The unselected and selected appearance of the SAME element: its base rules, then (in cascade
       order) the state rule and any co-occurring state `co` the element also carries. Only what
       actually differs between the two is a channel — a declaration the cascade overrides, or one
       that restates the unselected value, carries no state. */
    const base = baseProps(subjectPlain, sr.stripped, null);
    const off = co ? cascade(base, co) : base;
    const on = cascade(base, co ? [sr.rule, ...co] : [sr.rule]);
    const offFill = paint(off.fill, g);
    const onFill = paint(on.fill, offFill ?? g);
    if (on.fill !== off.fill) {
      if (offFill && onFill) measured.push({ name: "fill", ratio: contrast(onFill, offFill) });
      else unmeasured.push(`${where} fill`);
    }
    if (on.ink !== off.ink) {
      const a = on.ink ? colourIn(on.ink, t) : undefined;
      const b = off.ink ? colourIn(off.ink, t) : undefined;
      if (Array.isArray(a) && Array.isArray(b)) measured.push({ name: "ink", ratio: contrast(a, b) });
      else if (a !== undefined || b !== undefined) unmeasured.push(`${where} ink`);
    }
    for (const side of ["top", "right", "bottom", "left"]) {
      if (on.sides[side] === off.sides[side]) continue;
      const offEdge = paint(off.sides[side], offFill ?? g);
      const onEdge = paint(on.sides[side], onFill ?? g);
      if (offEdge && onEdge) measured.push({ name: `border-${side}`, ratio: contrast(onEdge, offEdge) });
      else unmeasured.push(`${where} border-${side}`);
    }
    if (on.inset !== off.inset) {
      for (const shadow of topLevel(on.inset ?? "", /,/)) {
        if (!/\binset\b/.test(shadow)) continue;
        const c = colourIn(shadow, t);
        if (c === "transparent" || c === undefined) continue;
        const offShadow = topLevel(off.inset ?? "", /,/).find((s) => /\binset\b/.test(s));
        const offSpot = paint(offShadow, offFill ?? g);
        if (Array.isArray(c) && offSpot && onFill) {
          measured.push({ name: "inset bar", ratio: Math.min(contrast(c, onFill), contrast(c, offSpot)) });
        } else unmeasured.push(`${where} inset bar`);
      }
    }
    const [onOutline, offOutline] = [outlineOf(on), outlineOf(off)];
    if (onOutline !== offOutline && onOutline !== "") {
      /* An outline with a non-negative offset is drawn OUTSIDE the box, over whatever is around the
         element (the ground); a negative offset draws it over the element's own fill. It is measured
         against that neighbour and against what occupied the same spot unselected. */
      const inside = /^-/.test((on.outlineOffset ?? "0").trim()) || /^calc\([^)]*\*\s*-1\)$/.test((on.outlineOffset ?? "").trim());
      const beside = inside ? onFill : g;
      const c = colourIn(onOutline, t);
      const offSpot = offOutline === "" ? (inside ? offFill : g) : paint(offOutline, g);
      if (Array.isArray(c) && beside && offSpot) {
        measured.push({ name: "outline", ratio: Math.min(contrast(c, beside), contrast(c, offSpot)) });
      } else if (c !== "transparent") unmeasured.push(`${where} outline`);
    }
  } else {
    // A generated indicator: it exists only if some rule gives it content.
    const basePseudo = baseProps(subjectPlain, sr.stripped, sr.pseudo);
    const on = applyDecls(basePseudo, sr.rule.decls);
    if (!on.content) return { measured, unmeasured };
    // what the indicator is drawn over: the host's selected fill, and the host's unselected fill
    const hostCompound = withoutPseudo(subjectPlain);
    const hostStripped = sr.stripped;
    const hostBase = baseProps(hostCompound, hostStripped, null);
    const hostOff = co ? cascade(hostBase, co) : hostBase;
    const hostOnRules = STATE_RULES.filter(
      (o) => o.key === sr.key && o.pseudo === null && o.subject === withoutPseudo(sr.subject) && o.rule.media === sr.rule.media,
    );
    const hostOn = cascade(hostBase, [...hostOnRules.map((o) => o.rule), ...(co ?? [])]);
    const offFill = paint(hostOff.fill, g) ?? g;
    const onFill = paint(hostOn.fill, offFill) ?? offFill;
    const colours: Paint[] = [];
    if (sr.rule.decls.some(([p]) => p === "background" || p === "background-color") && on.fill) {
      const c = colourIn(on.fill, t);
      colours.push(c === undefined ? null : c);
    }
    for (const side of ["top", "right", "bottom", "left"]) {
      if (on.sides[side] !== undefined && on.sides[side] !== basePseudo.sides[side]) {
        const c = colourIn(on.sides[side]!, t);
        colours.push(c === undefined ? null : c);
      }
    }
    for (const c of colours) {
      if (c === "transparent") continue;
      if (c === null) unmeasured.push(`${where} ::${sr.pseudo}`);
      else {
        const offSpot = paint(basePseudo.content ? basePseudo.fill : undefined, offFill) ?? offFill;
        measured.push({ name: `::${sr.pseudo} bar`, ratio: Math.min(contrast(c, onFill), contrast(c, offSpot)) });
      }
    }
  }
  return { measured, unmeasured };
}

/** Declarations that paint: the only ones a contrast channel can come from. */
const PAINTS = /^(background(-color)?|color|box-shadow|outline(-color)?|border(-[a-z-]+)?)$/;
const paints = (sr: StateRule): boolean => sr.rule.decls.some(([p]) => PAINTS.test(p) && !/-(width|style|radius)$/.test(p));

/**
 * State keys whose every rule only re-weights text (`.hop__head[aria-current] .hop__host
 * { font-weight }`). They declare no paint, so there is nothing to measure: they are supplements to
 * an indicator carried elsewhere, and the orphan check below still requires the element to be styled.
 */
const WEIGHT_ONLY = new Set<string>();

/**
 * The OTHER persistent states the same element can carry at the same time as `sr` — a rule in the
 * same stylesheet (so the cascade order is known) whose single compound is the same element's class
 * plus some attribute condition, that paints, and that cannot exclude `sr`'s state (it names none of
 * `sr`'s state attributes, not even under :not()). User-action pseudo-classes (:hover, :focus…) are
 * transient and left out. A selected state must stay distinguishable while such a state is also on:
 * a later or more specific rule that repaints the selection's only strong channel (the 3D label's
 * accent outline under a finding's or an alarm's outline) makes selected and unselected identical.
 */
const USER_ACTION = /:(hover|focus|focus-visible|focus-within|active|disabled|enabled|visited|target)\b/;
/** The subject's own attribute names (outside :not()/:has()). */
const outerAttrs = (compound: string): string[] =>
  [...compound.replace(/:(?:not|has)\((?:[^()]|\([^()]*\))*\)/g, "").matchAll(/\[\s*([\w-]+)/g)].map((m) => m[1]!);
/** A compound's conditions: its outer attribute predicates and its :not()/:has() groups, as text. */
const conditions = (compound: string): string[] => [
  ...[...compound.matchAll(/:(?:not|has)\((?:[^()]|\([^()]*\))*\)/g)].map((m) => m[0]),
  ...[...compound.replace(/:(?:not|has)\((?:[^()]|\([^()]*\))*\)/g, "").matchAll(/\[[^\]]*\]/g)].map((m) => m[0]),
];
/** Files that write each attribute imperatively (`el.dataset.x =`, `setAttribute("x", …)`). */
const IMPERATIVE_WRITERS = (() => {
  const out = new Map<string, Set<string>>();
  const kebab = (camel: string): string => camel.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
  for (const f of [...walk(SRC, ".tsx"), ...walk(SRC, ".ts")]) {
    const src = readFileSync(f, "utf8");
    const names = [
      ...[...src.matchAll(/\.dataset\.([A-Za-z]\w*)\s*=(?!=)/g)].map((m) => `data-${kebab(m[1]!)}`),
      ...[...src.matchAll(/\.setAttribute\(\s*["']((?:aria|data)-[\w-]+)["']/g)].map((m) => m[1]!),
    ];
    for (const n of names) out.set(n, (out.get(n) ?? new Set()).add(rel(f)));
  }
  return out;
})();
/**
 * Evidence that attributes `a` and `b` can sit on ONE element of the subject `own`: a JSX tag with
 * that class renders both, or renders one and forwards props (`{...rest}`), or one source file writes
 * both imperatively. Without it a pairing is hypothetical (`.fabric3d__btn` is pressed on one button
 * and expanded on another), and is not audited.
 */
function coOccur(own: string, a: string, b: string): boolean {
  const cls = own.startsWith(".") ? own.slice(1) : null;
  for (const tag of TAGS) {
    const named = cls ? new RegExp(`className=[^>]*["'\`\\s]${escapeRe(cls)}["'\`\\s]`).test(tag.text) : new RegExp(`^<${escapeRe(own)}\\b`).test(tag.text);
    if (!named) continue;
    const spread = /\{\s*\.\.\.(?!\()/.test(tag.text);
    if ((tag.attrs.has(a) || spread) && (tag.attrs.has(b) || spread) && (tag.attrs.has(a) || tag.attrs.has(b))) return true;
  }
  for (const f of IMPERATIVE_WRITERS.get(a) ?? []) if (IMPERATIVE_WRITERS.get(b)?.has(f)) return true;
  return false;
}
function coStates(sr: StateRule): Rule[][] {
  if (sr.pseudo !== null || compounds(sr.rule.selector).length !== 1) return [];
  const own = /^(\.[\w-]+|[a-z][\w-]*)/.exec(stripState(sr.subject, statePredicates(sr.subject)))?.[1];
  if (!own) return [];
  const stateAttrs = [...sr.key.matchAll(/\[\s*([\w-]+)/g)].map((m) => m[1]!);
  const candidates = screenRules.filter((r) => {
    if (r === sr.rule || r.file !== sr.rule.file || r.media !== sr.rule.media) return false;
    const parts = compounds(r.selector);
    if (parts.length !== 1) return false;
    const c = parts[0]!;
    if (!new RegExp(`^${escapeRe(own)}(?![\\w-])`).test(c)) return false;
    if (/::?(before|after)\b/.test(c) || USER_ACTION.test(c)) return false;
    if (conditions(c).length === 0) return false; // the unconditioned base is already the off state
    if (stateAttrs.some((a) => new RegExp(`\\[\\s*${escapeRe(a)}\\b`).test(c))) return false;
    if (statePredicates(c).length > 0) return false; // another selection state: audited as its own key
    if (!outerAttrs(c).every((b) => stateAttrs.every((a) => coOccur(own, a, b)))) return false;
    return r.decls.some(([p]) => PAINTS.test(p) && !/-(width|style|radius)$/.test(p));
  });
  /* A co-state brings every rule its selector implies: `[data-finding="yes"]:has(…critical…)` is
     also `[data-finding="yes"]`, so both apply together. */
  return candidates.map((r) => {
    const mine = conditions(compounds(r.selector)[0]!);
    return candidates.filter((o) => conditions(compounds(o.selector)[0]!).every((x) => mine.includes(x)));
  });
}

type Verdict = { key: string; file: string; line: number; theme: string; best: number; channel: string; ground: string; unmeasured: string[] };
/**
 * A rule whose compound requires ANOTHER selection state as well applies only while both are on
 * (`.jsonview__row[aria-selected="true"][data-current-match="true"]`). Credited to either state alone,
 * its channel stood in for that state's own indicator: measured 2026-09-25, the tree row's plain
 * aria-selected bar set to --border (about 1.3:1) still reported 4.86:1, the combination's accent bar.
 * So a key is judged on the rules that need only it; a combination rule counts only for a key that has
 * no rule of its own.
 */
const needsAnotherState = (sr: StateRule): boolean => statePredicates(compounds(sr.rule.selector)[sr.ownerIndex] ?? "").length > 1;
/** Per state (and per state-plus-co-occurring-state), per theme: the worst ground's best channel. */
function verdicts(): Verdict[] {
  const byKey = new Map<string, StateRule[]>();
  for (const sr of STATE_RULES) byKey.set(`${sr.key}@@${sr.rule.media}`, [...(byKey.get(`${sr.key}@@${sr.rule.media}`) ?? []), sr]);
  const out: Verdict[] = [];
  for (const [k, all] of byKey) {
    const key = k.split("@@")[0]!;
    const own = all.filter((sr) => !needsAnotherState(sr));
    const list = own.length > 0 ? own : all;
    if (!list.some(paints)) {
      WEIGHT_ONLY.add(key);
      continue;
    }
    const first = list[0]!;
    const seen = new Set<string>();
    const cos = list.flatMap(coStates).filter((set) => {
      const id = set.map((r) => `${r.file}:${r.line}:${r.selector}`).sort().join("|");
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
    /** A combination is named by its most specific rule, the one that implies the rest. */
    const nameOf = (set: Rule[]): string =>
      [...set].sort((a, b) => conditions(b.selector).length - conditions(a.selector).length)[0]!.selector.replace(/\s+/g, " ");
    for (const co of [null, ...cos]) {
      for (const [theme, t] of THEMES) {
        let worst = { best: Infinity, channel: "", ground: "" };
        const unmeasured = new Set<string>();
        for (const gTok of SURFACES) {
          const g = resolveColour(`var(${gTok})`, t);
          if (!Array.isArray(g)) throw new Error(`${theme} ${gTok} does not resolve`);
          let best = { ratio: 0, name: "none" };
          for (const sr of list) {
            const { measured, unmeasured: u } = channels(sr, t, g, co);
            u.forEach((x) => unmeasured.add(x));
            for (const c of measured) if (c.ratio > best.ratio) best = c;
          }
          if (best.ratio < worst.best) worst = { best: best.ratio, channel: best.name, ground: gTok };
        }
        out.push({
          key: co ? `${key} while ${nameOf(co)}` : key,
          file: first.rule.file,
          line: first.rule.line,
          theme,
          best: worst.best,
          channel: worst.channel,
          ground: worst.ground,
          unmeasured: [...unmeasured],
        });
      }
    }
  }
  return out;
}
const VERDICTS = verdicts();
/* `SELECTED_STATE_REPORT=1 npx vitest run src/ui/selected-state-contrast.test.ts` prints every state's figure. */
if (process.env.SELECTED_STATE_REPORT) {
  for (const v of VERDICTS) {
    console.log(`${v.best >= 3 ? "ok  " : "FAIL"} ${round2(v.best).toFixed(2)} ${v.theme.padEnd(5)} ${v.channel.padEnd(14)} ${v.ground.padEnd(12)} ${v.key}  ${v.file}:${v.line}`);
  }
}

describe("selected-state indicators clear 3:1 against the unselected state (D4, WCAG 1.4.11)", () => {
  it("derives the state vocabulary from the components, so the guard cannot pass by auditing nothing", () => {
    for (const a of ["aria-selected", "aria-checked", "aria-pressed", "aria-current", "data-active", "data-selected", "data-highlight"]) {
      expect([...VOCAB], `vocabulary lacks ${a}`).toContain(a);
    }
    // data-kind is rendered beside aria-selected on tree items but is a constant, not a state
    expect(VOCAB.has("data-kind")).toBe(false);
  });

  it("finds the state rules it is meant to cover, including the pane switch and the pressed button", () => {
    const keys = new Set(VERDICTS.map((v) => v.key));
    for (const k of ['.paneswitch__btn[aria-checked="true"]', '.paneswitch__fabric[aria-pressed="true"]', '.ui-btn[aria-pressed="true"]', '.ui-tab[aria-selected="true"]', '.railb__switch-btn[aria-checked="true"]']) {
      expect([...keys], `state rule ${k} was not collected`).toContain(k);
    }
    expect(keys.size).toBeGreaterThan(15);
    const files = new Set(VERDICTS.map((v) => v.file));
    expect(files.size).toBeGreaterThan(5);
  });

  it("collects a state named by an attribute VALUE, and audits it while each co-occurring state is on", () => {
    // The 3D label's selection is `data-state="selected"`, written both in JSX and imperatively
    // (FabricLabels.tsx). Selecting a device also makes it its own cut point, so selected-while-cut
    // is the ordinary "device selected" state, not an edge case.
    const keys = [...new Set(VERDICTS.map((v) => v.key))];
    expect(keys).toContain('.fabric3d-label[data-state="selected"]');
    const combos = keys.filter((k) => k.startsWith('.fabric3d-label[data-state="selected"] while '));
    for (const co of ['[data-cut="yes"]', '[data-finding="yes"]', '[data-alarm="blocked"]']) {
      expect(combos.some((k) => k.includes(co)), `no combination with ${co}`).toBe(true);
    }
    // a pairing no element renders is not audited: `.fabric3d__btn` is pressed on some buttons and
    // expanded on others, never both
    expect(keys.some((k) => /^\.fabric3d__btn\[aria-pressed="true"\] while .*aria-expanded/.test(k))).toBe(false);
  });

  it("measures the rules correctly: the sibling that is known to pass passes, and on its border", () => {
    // `.railb__switch-btn`: transparent edge -> --border-strong edge; the brief cites it as the pass.
    for (const theme of ["light", "dark"]) {
      const v = VERDICTS.find((x) => x.key === '.railb__switch-btn[aria-checked="true"]' && x.theme === theme)!;
      expect(v.best, `${theme} railb`).toBeGreaterThanOrEqual(3);
      expect(v.channel).toMatch(/^border-/);
    }
  });

  it("judges a state on its own rule, not on a rule that also needs another selected state", () => {
    // The Inspector tree's roving row (aria-selected) draws a neutral --border-strong bar; the row that
    // is ALSO the current search hit draws the accent bar too, in a combination rule. The plain state's
    // figure must be its own bar's, so a weak plain indicator cannot pass on the combination's accent.
    for (const [theme, t] of THEMES) {
      const v = VERDICTS.find((x) => x.key === '.jsonview__row[aria-selected="true"]' && x.theme === theme);
      expect(v, `${theme}: the tree row's aria-selected state was not audited`).toBeDefined();
      const bar = resolveColour("var(--border-strong)", t) as RGB;
      const own = Math.min(...SURFACES.map((g) => contrast(bar, resolveColour(`var(${g})`, t) as RGB)));
      expect(round2(v!.best), `${theme}: judged on a rule other than its own`).toBe(round2(own));
    }
  });

  const files = [...new Set(VERDICTS.map((v) => v.file))].sort();
  for (const file of files) {
    it(`${file}: every selected/current/checked/pressed/active state reaches 3:1 in light and dark`, () => {
      const failures = VERDICTS.filter((v) => v.file === file && v.best < 3).map(
        (v) =>
          `${v.key} (${v.file}:${v.line}) ${v.theme}: best channel ${v.channel} = ${round2(v.best)}:1 on ${v.ground}` +
          (v.unmeasured.length ? ` [unmeasured: ${v.unmeasured.join(", ")}]` : ""),
      );
      expect(failures, `state indicators below 3:1:\n${failures.join("\n")}`).toEqual([]);
    });
  }

  it("every element that renders an ARIA selection state is styled for it by some state rule", () => {
    /* The other half of the class: a state rendered with NO rule at all has no indicator to measure.
       For each ARIA selection state an element renders, some state rule must target one of that
       element's literal classes (or its tag, for a classless row) through the ARIA attribute itself
       or through a `data-*` twin on the same element that follows the SAME boolean. A rule keyed on
       a different state of the same element (a search hit, while aria-selected follows focus) does
       not style this one. */
    const ruleKeys = STATE_RULES.map((s) => s.key);
    const orphans: string[] = [];
    let checked = 0;
    for (const tag of TAGS) {
      const name = /^<([\w.]+)/.exec(tag.text)?.[1] ?? "";
      if (!/^[a-z]/.test(name)) continue; // a component forwards the attribute to an element audited in its own file
      const cls = /className=(?:"([^"]+)"|\{[^}]*?"([^"]+)")/.exec(tag.text);
      const owners = [...(cls?.[1] ?? cls?.[2] ?? "").split(/\s+/).filter(Boolean).map((c) => `.${c}`), name];
      for (const aria of ARIA_SELECTION.filter((a) => tag.attrs.has(a))) {
        checked += 1;
        const cond = stateCondition(tag.attrs.get(aria)!);
        const twins = [aria, ...[...tag.attrs].filter(([n, v]) => n.startsWith("data-") && cond !== null && stateCondition(v) === cond).map(([n]) => n)];
        const covered = ruleKeys.some((k) => owners.some((o) => k.startsWith(`${o}[`)) && twins.some((s) => k.includes(`[${s}`)));
        if (!covered) orphans.push(`${tag.file}: <${name} ${owners.join(" ")}> renders ${aria}={${cond ?? "?"}} with no rule for it`);
      }
    }
    expect(checked, "no rendered selection state was found — the JSX reader is broken").toBeGreaterThan(10);
    expect(orphans, `selection states rendered with no state rule:\n${orphans.join("\n")}`).toEqual([]);
  });
});
