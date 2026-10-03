/**
 * focus-return.sight.test.ts — "can the reader see ANY part of this element?" is ONE definition, the CSS class it
 * means, shared by the owner and by the browser audit (independent refuter W5-X3; verifier V2-4 of cluster R-D3).
 *
 * THE DEFECT. The owner's `sightOf` and `review/audit-d3-focus.mjs`'s `focusGeometry` each walked the
 * containing-block chain with their OWN hand list of what makes an ancestor contain a `position: fixed` box —
 * transform, filter, perspective, contain — and the audit clipped BOTH axes when either overflow was not visible,
 * where the owner clips per axis. The list omits properties this codebase itself says create one (`will-change:
 * transform`, shell.css and DataGrid.css), so neither walk could see a
 * fixed control clipped by such an ancestor — and since the audit shared the gap, the audit could not catch it.
 * The absolute-box half of the rule (an absolute box escapes every STATIC ancestor) was pinned by no test at all.
 *
 * THE RULE UNDER TEST. `containsFixedBoxes` states the CSS class once (CSS Position 3 and the specifications it
 * defers to: every property whose non-initial value makes an element the containing block of its fixed descendants,
 * and `will-change` naming any of them — derived from the same table, not listed again); `visiblePartOf` is the one
 * walk; the owner's sight is its answer, and the audit runs THIS source in the page. jsdom computes none of these
 * properties, so the ancestors' computed values are STATED here, and geometry likewise (everything else measures
 * 0x0, "unknown"). Chromium's own answer for every declaration the codebase writes is the audit's
 * `--containing-blocks` census.
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import { containsFixedBoxes, releaseFocusLeftUnseen, visiblePartOf } from "./focus-return";

/* ── geometry and computed style, stated ──────────────────────────────────── */

type Box = { x: number; y: number; w: number; h: number };
const boxes = new Map<Element, Box>();
const styles = new Map<Element, Record<string, string>>();
const viewport = { w: 390, h: 800 };
const realRect = Element.prototype.getBoundingClientRect;
const realClientWidth = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
const realClientHeight = Object.getOwnPropertyDescriptor(Element.prototype, "clientHeight");
const realStyleOf = window.getComputedStyle;
const realGlobalStyleOf = globalThis.getComputedStyle;

const kebab = (p: string): string => p.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);

function stateGeometry(): void {
  Element.prototype.getBoundingClientRect = function (this: Element): DOMRect {
    const b = boxes.get(this) ?? { x: 0, y: 0, w: 0, h: 0 };
    return { left: b.x, top: b.y, right: b.x + b.w, bottom: b.y + b.h, width: b.w, height: b.h, x: b.x, y: b.y, toJSON: () => ({}) } as DOMRect;
  };
  Object.defineProperty(Element.prototype, "clientWidth", {
    configurable: true,
    get(this: Element) {
      return this === document.documentElement ? viewport.w : (boxes.get(this)?.w ?? 0);
    },
  });
  Object.defineProperty(Element.prototype, "clientHeight", {
    configurable: true,
    get(this: Element) {
      return this === document.documentElement ? viewport.h : (boxes.get(this)?.h ?? 0);
    },
  });
  /* A computed style with the STATED values laid over jsdom's own: read by name (getPropertyValue) or as a property. */
  const styleOf = ((el: Element, pseudo?: string | null) => {
    const real = realStyleOf.call(window, el, pseudo);
    const over = styles.get(el);
    if (over === undefined) return real;
    return new Proxy(real, {
      get(t, p) {
        if (p === "getPropertyValue") return (name: string) => (name in over ? over[name] : t.getPropertyValue(name));
        if (typeof p === "string" && kebab(p) in over) return over[kebab(p)];
        const v = Reflect.get(t, p, t) as unknown;
        return typeof v === "function" ? (v as (...a: unknown[]) => unknown).bind(t) : v;
      },
    });
  }) as typeof window.getComputedStyle;
  window.getComputedStyle = styleOf;
  globalThis.getComputedStyle = styleOf;
}

afterEach(() => {
  Element.prototype.getBoundingClientRect = realRect;
  if (realClientWidth) Object.defineProperty(Element.prototype, "clientWidth", realClientWidth);
  if (realClientHeight) Object.defineProperty(Element.prototype, "clientHeight", realClientHeight);
  window.getComputedStyle = realStyleOf;
  globalThis.getComputedStyle = realGlobalStyleOf;
  boxes.clear();
  styles.clear();
  document.body.innerHTML = "";
});

const $ = (id: string): HTMLElement => document.getElementById(id)!;

/**
 * A region with a SEEN heading (so a wrong verdict has somewhere to send focus, and the case depends on the verdict —
 * independent verifier V1-2), a clipping ancestor 200 px wide, and the focused control at x = 250..274: inside the
 * 390 px viewport, outside the clip.
 */
function mount(controlPosition: "fixed" | "absolute" | "static", clipStyle: string): { control: HTMLElement; heading: HTMLElement } {
  document.body.innerHTML = `
    <main id="outer" aria-label="Fabric" style="position: relative">
      <section id="region" aria-labelledby="region-title">
        <h2 id="region-title">Inspector</h2>
        <div id="clip" style="${clipStyle}">
          <button id="control" style="position: ${controlPosition}">Copy</button>
        </div>
      </section>
    </main>`;
  stateGeometry();
  boxes.set($("clip"), { x: 0, y: 0, w: 200, h: 800 });
  boxes.set($("control"), { x: 250, y: 182, w: 24, h: 24 });
  boxes.set($("region-title"), { x: 12, y: 140, w: 70, h: 24 });
  return { control: $("control"), heading: $("region-title") };
}

/* ── the containing block of a FIXED box: the class, not four of its members ── */

/** Each member of the class, as a computed value Chromium reports for it. */
const ESTABLISHING: readonly (readonly [string, string])[] = [
  ["transform", "matrix(1, 0, 0, 1, 1, 0)"],
  ["translate", "1px"],
  ["rotate", "1deg"],
  ["scale", "2"],
  ["offset-path", 'path("M 0 0 L 10 10")'],
  ["offset-position", "1px 2px"],
  ["perspective", "100px"],
  ["transform-style", "preserve-3d"],
  ["filter", "blur(1px)"],
  ["backdrop-filter", "blur(1px)"],
  ["contain", "paint"],
  ["contain", "layout"],
  ["contain", "strict"],
  ["contain", "content"],
  ["content-visibility", "auto"],
  ["content-visibility", "hidden"],
  /* will-change: DERIVED — naming any property above (the codebase's own `will-change: transform`, shell.css:703). */
  ["will-change", "transform"],
  ["will-change", "scroll-position, filter"],
  ["will-change", "backdrop-filter"],
  ["will-change", "perspective"],
  ["will-change", "translate"],
  ["will-change", "contain"],
  ["will-change", "offset-position"],
  /* An ALIAS names its property (independent verifier SD3V-6, MEASURED in Chromium: `will-change: -webkit-transform`
     contains a fixed box; the computed value keeps the alias as written, so a match on canonical names alone missed
     it). The census enumerates every alias Chromium knows as well. */
  ["will-change", "-webkit-transform"],
  ["will-change", "opacity, -webkit-filter"],
  /* A SHORTHAND that sets a member names it too (MEASURED by the census once its domain was every name Chromium
     accepts: `will-change: offset` contains a fixed box — `offset` sets offset-path and offset-position). Property
     names are ASCII case-insensitive, and so is the match (the census announces every name in capitals too). */
  ["will-change", "offset"],
  ["will-change", "TRANSFORM"],
];

/** Values that do NOT make a containing block for a fixed box (each property's initial value among them). */
const NOT_ESTABLISHING: readonly (readonly [string, string])[] = [
  ["transform", "none"],
  ["filter", "none"],
  ["contain", "none"],
  ["contain", "size"],
  ["contain", "style"],
  ["container-type", "normal"],
  /* MEASURED in Chromium (the audit's --containing-blocks census): CSS Containment 3 no longer has `container-type`
     apply layout containment, so it makes no containing block — PathTrace.css's `container-type: inline-size` is no
     gap. And `will-change` naming `content-visibility` makes none, although the property itself does. */
  ["container-type", "inline-size"],
  ["container-type", "size"],
  ["will-change", "container-type"],
  ["will-change", "content-visibility"],
  ["offset-position", "normal"],
  ["offset-position", "auto"],
  ["content-visibility", "visible"],
  ["transform-style", "flat"],
  ["will-change", "auto"],
  ["will-change", "opacity"],
  ["will-change", "scroll-position"],
  ["clip-path", "inset(0px)"],
  ["opacity", "0.5"],
  ["isolation", "isolate"],
  ["mix-blend-mode", "multiply"],
];

describe("a fixed box is clipped by an ancestor exactly when that ancestor contains it — every member of the CSS class", () => {
  it.each(ESTABLISHING)("%s: %s on the clipping ancestor contains the fixed control: no part of it is seen, focus moves to the heading", (prop, value) => {
    const { control, heading } = mount("fixed", "overflow-x: clip");
    styles.set($("clip"), { [prop]: value });
    control.focus();
    expect(releaseFocusLeftUnseen(), `${prop}: ${value} makes the clip its containing block, so the clip applies`).toBe(heading);
    expect(document.activeElement).toBe(heading);
  });

  it.each(NOT_ESTABLISHING)("%s: %s does not: the fixed control escapes the clip, is seen, and keeps focus", (prop, value) => {
    const { control } = mount("fixed", "overflow-x: clip");
    styles.set($("clip"), { [prop]: value });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBeNull();
    expect(document.activeElement).toBe(control);
  });

  it("the predicate itself answers from the computed value by name, for each member and its initial value", () => {
    const cs = (v: Record<string, string>): Pick<CSSStyleDeclaration, "getPropertyValue"> => ({ getPropertyValue: (n: string) => v[n] ?? "" });
    for (const [p, v] of ESTABLISHING) expect(containsFixedBoxes(cs({ [p]: v })), `${p}: ${v}`).toBe(true);
    for (const [p, v] of NOT_ESTABLISHING) expect(containsFixedBoxes(cs({ [p]: v })), `${p}: ${v}`).toBe(false);
    /* A DOM that computes nothing ("" everywhere) states nothing: no containing block is invented. */
    expect(containsFixedBoxes(cs({}))).toBe(false);
  });
});

/* ── the containing block of an ABSOLUTE box (independent verifier V2-4) ───── */

describe("an absolutely positioned control escapes every STATIC clipping ancestor, and only those", () => {
  it("a static clipping ancestor does not clip it: it is seen and keeps focus", () => {
    const { control } = mount("absolute", "overflow-x: clip; position: static");
    control.focus();
    expect(releaseFocusLeftUnseen(), "a static ancestor is not the containing block of an absolute box").toBeNull();
    expect(document.activeElement).toBe(control);
  });

  it("a POSITIONED clipping ancestor does: no part of it is seen, focus moves to the heading", () => {
    const { control, heading } = mount("absolute", "overflow-x: clip; position: relative");
    control.focus();
    expect(releaseFocusLeftUnseen()).toBe(heading);
  });

  it("a static clipping ancestor that contains fixed boxes contains absolute ones too (will-change: transform)", () => {
    const { control, heading } = mount("absolute", "overflow-x: clip; position: static");
    styles.set($("clip"), { "will-change": "transform" });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBe(heading);
  });
});

/* ── per axis ──────────────────────────────────────────────────────────────── */

describe("an ancestor clips only on the axis whose computed overflow is not visible", () => {
  it("overflow-x: clip with overflow-y visible does not clip a control below its box", () => {
    const { control } = mount("static", "overflow-x: clip");
    styles.set($("clip"), { "overflow-x": "clip", "overflow-y": "visible" });
    boxes.set($("clip"), { x: 0, y: 0, w: 390, h: 100 });
    boxes.set(control, { x: 20, y: 300, w: 24, h: 24 });
    control.focus();
    expect(releaseFocusLeftUnseen()).toBeNull();
    expect(document.activeElement).toBe(control);
  });

  it("the visible part is the box met with the viewport and with each clipping axis", () => {
    mount("static", "overflow-x: clip");
    styles.set($("clip"), { "overflow-x": "clip", "overflow-y": "visible" });
    boxes.set($("control"), { x: 150, y: 790, w: 100, h: 30 });
    expect(visiblePartOf($("control"))).toMatchObject({ l: 150, t: 790, r: 200, b: 800, clippers: ["div"] });
    /* No box to measure: unknown, never "unseen". */
    expect(visiblePartOf($("outer"))).toBeNull();
  });
});

/* ── ONE definition in the APP as well (independent verifier SD3V-5) ─────── */

/* Every module of the app that decides "does this ancestor contain a fixed box?" must do it through
   containsFixedBoxes. The class is detected by what such a decision cannot do without — reading `will-change` from a
   computed style (a rule without it is the defect W5-X3 named) — not by a list of the modules known today. A copy that
   still exists is named here with the change its owner must make, so the list can only shrink: a NEW copy fails, and
   so does a listed one that is gone (its line is then deleted). */
const KNOWN_COPIES: Readonly<Record<string, string>> = {};
describe("no module of the app states a containing-block rule of its own", () => {
  it("only focus-return.ts reads will-change to decide a containing block (the listed copies are owed by their owners)", () => {
    const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
    const files = (readdirSync(SRC, { recursive: true }) as string[])
      .map((f) => f.split("\\").join("/"))
      .filter((f) => /\.(?:ts|tsx)$/.test(f) && !/\.test\.tsx?$/.test(f) && f !== "app/focus-return.ts");
    const readsWillChange = (f: string): boolean => /\bwillChange\b|["']will-change["']/.test(readFileSync(resolve(SRC, f), "utf8"));
    expect(files.length, "no source module was found: the scan proves nothing").toBeGreaterThan(20);
    expect(files.filter(readsWillChange).sort(), "a module decides containing blocks with a rule of its own: import containsFixedBoxes instead").toEqual(
      Object.keys(KNOWN_COPIES).sort(),
    );
  });
});

/* ── ONE definition, run by the audit as well ─────────────────────────────── */

describe("the audit measures with THIS definition, not a copy", () => {
  it("the definition is self-contained: its source alone, evaluated where nothing else of this module exists, gives the same answer", () => {
    const { control } = mount("fixed", "overflow-x: clip");
    styles.set($("clip"), { "will-change": "transform" });
    const isolated = new Function(`${containsFixedBoxes.toString()}\n${visiblePartOf.toString()}\nreturn visiblePartOf;`)() as typeof visiblePartOf;
    expect(isolated(control)).toEqual(visiblePartOf(control));
    expect(isolated(control)?.clippers).toEqual(["div"]);
  });

  it("review/audit-d3-focus.mjs states no containing-block or clipping rule of its own: it reads both functions from this module", () => {
    const audit = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "review", "audit-d3-focus.mjs"), "utf8");
    /* The two hand lists the refuter found: a `containsFixed` of its own and a property comparison to "none". */
    expect(audit).not.toMatch(/containsFixed\s*=/);
    expect(audit).not.toMatch(/\.(?:transform|filter|perspective)\s*!==\s*"none"/);
    expect(audit).not.toMatch(/overflowX\s*!==\s*"visible"/);
    /* What it does instead: extract the owner's declarations by name and run them in the page. */
    expect(audit).toMatch(/SIGHT_FUNCTIONS\s*=\s*\[\s*"containsFixedBoxes",\s*"visiblePartOf"\s*\]/);
    expect(audit).toMatch(/src\/app\/focus-return\.ts/);
  });
});
