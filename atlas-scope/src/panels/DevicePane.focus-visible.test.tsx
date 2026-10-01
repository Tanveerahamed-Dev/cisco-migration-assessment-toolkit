/**
 * DevicePane.focus-visible.test.tsx — a focused tab panel shows its focus ring INSIDE the box that
 * scrolls it (acceptance D3, "focus is always visible").
 *
 * MEASURED 2026-09-23 (independent acceptance review, then `review/audit-d3-focus.mjs`): Tab from
 * the device pane's selected tab lands on its [role=tabpanel] (APG: the panel is a tab stop), and
 * the app-wide `:focus-visible` ring is drawn 2 px OUTSIDE the element's box. Every tab panel fills
 * the `.dp__body` scroller edge to edge, and a scroller clips whatever paints outside its padding
 * box, so the whole ring was clipped: "0 pixels at >=3:1", focus on screen and invisible. The
 * Inspector's panels sit in the same shape.
 *
 * jsdom lays nothing out, so this pins the CONTRACT that makes the ring survive any scroller, for
 * every panel the pane renders: of all the focus rules in the stylesheets that match a rendered
 * panel, the one that wins the cascade draws the outline wholly inside the border box
 * (outline-offset <= -outline-width). The real-pixel proof is the audit's visibility check, which
 * photographs each focused panel against the same pixels unfocused.
 *
 * The CLASS, not the instance: `role="tabpanel"` has exactly one producer (TabPanel in
 * src/ui/primitives.tsx), asserted below, so a rule on the primitive covers every panel in the app.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { DevicePane } from "./DevicePane";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function walk(dir: string, ext: RegExp): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p, ext));
    else if (ext.test(name)) out.push(p);
  }
  return out.sort();
}

/* ── a small, honest cascade over the project's own stylesheets ─────────────── */

type Rule = { file: string; selector: string; body: string; media: string | null; order: number };

function rules(): Rule[] {
  const out: Rule[] = [];
  let order = 0;
  for (const file of walk(SRC, /\.css$/)) {
    const css = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, " ");
    const re = /(@[^{;]*)\{|([^{}]+)\{([^{}]*)\}|\}/g;
    const stack: string[] = [];
    for (let m = re.exec(css); m !== null; m = re.exec(css)) {
      if (m[1] !== undefined) stack.push(m[1].trim());
      else if (m[2] !== undefined) {
        for (const selector of m[2].split(",")) {
          out.push({ file: relative(SRC, file), selector: selector.trim(), body: m[3] ?? "", media: stack[stack.length - 1] ?? null, order: order++ });
        }
      } else stack.pop();
    }
  }
  return out;
}

/** Selector specificity as a comparable tuple. `:where()` counts nothing; `:not/:is/:has` count their argument. */
function specificity(sel: string): [number, number, number] {
  let s = sel.replace(/:where\([^)]*\)/g, "");
  s = s.replace(/:(?:not|is|has)\(([^)]*)\)/g, " $1 ");
  const ids = (s.match(/#[\w-]+/g) ?? []).length;
  const cls = (s.match(/\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+/g) ?? []).length;
  const types = (s.replace(/\[[^\]]*\]/g, "").match(/(^|[\s>+~(])[a-z][\w-]*/gi) ?? []).length + (s.match(/::[\w-]+/g) ?? []).length;
  return [ids, cls, types];
}

const cmp = (a: [number, number, number], b: [number, number, number]): number => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

const TOKENS = readFileSync(join(SRC, "core", "tokens.css"), "utf8");
function tokenPx(name: string): number {
  const m = new RegExp(`${name}\\s*:\\s*([\\d.]+)px`).exec(TOKENS);
  if (m === null) throw new Error(`token ${name} has no px value in tokens.css`);
  return Number(m[1]);
}

/** A length in px: `2px`, `-2px`, `var(--x)`, `calc(-1 * var(--x))`, `calc(var(--x) * -1)`. */
function px(value: string): number {
  const expr = value
    .trim()
    .replace(/var\((--[\w-]+)\)/g, (_m, n: string) => String(tokenPx(n)))
    .replace(/(\d)px/g, "$1")
    .replace(/^calc\((.*)\)$/, "$1");
  if (!/^[\d.\s*+\-/()]+$/.test(expr)) throw new Error(`cannot evaluate "${value}"`);
  return Number(Function(`"use strict"; return (${expr});`)());
}

/** The declaration of `prop` that wins for `el` in its focus-visible state, among rules outside @media. */
function focusWinner(el: Element, prop: RegExp): { rule: Rule; value: string } | null {
  let best: { rule: Rule; value: string; spec: [number, number, number] } | null = null;
  for (const rule of rules()) {
    if (rule.media !== null) continue; /* forced-colors and print carry their own system; not this contract */
    if (!/:focus-visible|:focus(?![\w-])/.test(rule.selector)) continue;
    const bare = rule.selector.replace(/:focus-visible|:focus(?![\w-])/g, "").trim() || "*";
    let hit = false;
    try {
      hit = el.matches(bare.endsWith(" ") || /[>+~]$/.test(bare) ? `${bare}*` : bare);
    } catch {
      continue; /* a selector jsdom cannot parse cannot be asserted about here */
    }
    if (!hit) continue;
    const decl = [...rule.body.matchAll(/([\w-]+)\s*:\s*([^;]+)/g)].filter((d) => prop.test(d[1] ?? "")).pop();
    if (decl === undefined) continue;
    const spec = specificity(rule.selector);
    if (best === null || cmp(spec, best.spec) >= 0) best = { rule, value: (decl[2] ?? "").trim(), spec };
  }
  return best === null ? null : { rule: best.rule, value: best.value };
}

/* ── the rendered pane ─────────────────────────────────────────────────────── */

let root: Root | null = null;
let host: HTMLElement | null = null;

function mount(ui: ReactNode): HTMLElement {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root!.render(ui));
  return host;
}

beforeEach(() => {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().setEvidenceTab("summary");
  });
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  host?.remove();
  root = null;
  host = null;
});

describe("a focused tab panel keeps its focus ring inside the scroller that holds it", () => {
  it("has one producer of role=tabpanel, so a rule on the primitive covers every panel", () => {
    const producers = walk(SRC, /\.tsx?$/)
      .filter((f) => !/\.test\.tsx?$/.test(f))
      .filter((f) => /role=["{]["']?tabpanel|role:\s*["']tabpanel/.test(readFileSync(f, "utf8")))
      .map((f) => relative(SRC, f).replace(/\\/g, "/"));
    expect(producers).toEqual(["ui/primitives.tsx"]);
  });

  it("the device pane's panels sit in a clipping scroller (the premise of the defect)", () => {
    const device = fabric.devices.find((d) => d.collected) ?? fabric.devices[0]!;
    act(() => { useInvestigation.getState().selectDevice(device.host); });
    const c = mount(<DevicePane />);
    const panels = [...c.querySelectorAll<HTMLElement>('[role="tabpanel"]')];
    expect(panels.length).toBeGreaterThan(1);
    for (const p of panels) {
      expect(p.tabIndex, `${p.id} is not a tab stop`).toBe(0);
      expect(p.parentElement?.classList.contains("dp__body"), `${p.id} is not inside .dp__body`).toBe(true);
    }
    const body = rules().find((r) => r.selector === ".dp__body" && r.media === null);
    expect(body?.body ?? "").toMatch(/overflow\s*:\s*auto/);
  });

  it("every rendered panel's winning focus outline is drawn wholly inside its own box", () => {
    const device = fabric.devices.find((d) => d.collected) ?? fabric.devices[0]!;
    act(() => { useInvestigation.getState().selectDevice(device.host); });
    const c = mount(<DevicePane />);
    const panels = [...c.querySelectorAll<HTMLElement>('[role="tabpanel"]')];
    expect(panels.length).toBeGreaterThan(1);
    for (const p of panels) {
      const offset = focusWinner(p, /^outline-offset$/);
      const outline = focusWinner(p, /^outline(-width)?$/);
      expect(offset, `${p.id}: no focus rule sets an outline-offset`).not.toBeNull();
      expect(outline, `${p.id}: no focus rule draws an outline`).not.toBeNull();
      const width = /var\(--focus-ring-w\)/.test(outline!.value) ? tokenPx("--focus-ring-w") : px(outline!.value.split(/\s+/)[0] ?? "");
      const off = px(offset!.value);
      expect(
        off,
        `${p.id}: the winning focus rule (${offset!.rule.file} "${offset!.rule.selector}") offsets the ${width}px ring by ${off}px — ` +
          `outside the panel's box, where the .dp__body scroller clips it`,
      ).toBeLessThanOrEqual(-width);
    }
  });
});
