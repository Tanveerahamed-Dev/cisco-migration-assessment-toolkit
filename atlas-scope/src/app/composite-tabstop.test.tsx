/**
 * composite-tabstop.test.tsx — every composite widget the app renders exposes exactly ONE tab stop,
 * and every item of a one-dimensional group is reachable from it with the arrow keys (acceptance D1).
 *
 * THE DEFECT (acceptance report, D1 overturned PASS -> FAIL, 2026-09-24). At 768 px on the Path
 * surface the "Which panel to show" radiogroup rendered Queue and Evidence, both `tabindex="-1"`:
 * the value was `path`, `pathAvailable` was false (no flow yet), so the `path` radio was left out of
 * the list and the roving rule `value === id ? 0 : -1` matched nothing. "paneswitch focused during
 * 60 Tabs: 0". The state is reached with the keyboard alone (More -> Path), not only by deep link.
 *
 * WHERE IT CAME FROM. Not a code change between the PASS (443a05a) and the FAIL (70bea72): `git diff
 * 443a05a 70bea72 -- src/app/surfaces.tsx` is empty, and `git log -S 'tabIndex={value === p.id ? 0
 * : -1}'` names only 50a3dc5, the repository's baseline import. The roving rule and the
 * `pathAvailable ? [path] : []` omission both arrived there, together; the state that exposes them
 * (Path with no flow) became a reachable, rendered one in 443a05a when the path rail began to mount
 * on `surface === "path"` alone. The PASS was a grading that never visited it.
 *
 * THE CLASS, NOT THE INSTANCE. A roving tabindex written as `selected === id ? 0 : -1` has no tab
 * stop whenever the value names no rendered item — and nothing about that shape says so. So the
 * guard is not "PaneSwitch has a tab stop": the whole app is mounted at one width per ladder rung
 * (the runtime audit derives its own coverage from LADDER_REM: 390/768/1000/1440/1920, 1152 for the
 * drawer rung, and a drawer pass at 1024/1152/1270 with and without reduced motion), in the states a
 * reader reaches, and EVERY rendered
 * element whose role is a composite widget (derived from the role, not from a list of components)
 * must hold exactly one sequential-focus stop. `review/audit-d3-focus.mjs --sweep` checks the same
 * rule in a real browser, where CSS decides what is rendered.
 */
import { act, type ReactNode, useEffect, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { isDeepStrictEqual } from "node:util";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";

import { fabric } from "../core/data";
import { EVIDENCE_TABS, useInvestigation } from "../core/store";

/* No module is mocked: the REAL frame is censused, fabric included (jsdom has no WebGL, so the stage
   renders whatever it renders without one). A mock would also make this a fixture test under F2's
   module-mocking declaration, which it is not meant to be. */
import { App } from "./App";
import { PaneSwitch, type PaneId } from "./surfaces";
/* The stage's lazy chunk, loaded while this file is COLLECTED rather than inside the first test that
   mounts the app (acceptance F2, 2026-09-24). surfaces.tsx requests it on the first render (jsdom has
   no requestIdleCallback, so the idle wait is one timer turn), and loading it means transforming the
   whole fabric3d module graph through the runner. Measured on a clean clone at ~80 % host load, that
   landed inside the first three app-mounting tests of this file — 21 s, 37 s and 26 s, one of them a
   timeout — while every later case took 1-3 s. It also made the first census load-dependent: whether
   the stage had resolved by the end of `settle()` depended on how busy the host was. Preloaded, the
   lazy import resolves on its first turn in every case, so every case censuses the same frame. This
   is the same module the app loads; nothing is mocked or replaced. */
import "../fabric3d/Fabric3D";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

/** Answer the ladder's rem media queries for `width`, as surfaces.test.tsx does. */
function setViewport(width: number): () => void {
  const real = window.matchMedia;
  const px = (rem: string): number => Number.parseFloat(rem) * 16;
  window.matchMedia = ((q: string) => {
    let matches = true;
    for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)(rem|px)\)/g)) {
      const bound = m[3] === "px" ? Number.parseFloat(m[2] as string) : px(m[2] as string);
      matches &&= m[1] === "min" ? width >= bound : width <= bound;
    }
    if (/prefers-reduced-motion/.test(q)) matches = false;
    return {
      matches,
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
  }) as typeof window.matchMedia;
  return () => {
    window.matchMedia = real;
  };
}

/* Long enough for the deferred panes (the evidence chain renders behind useDeferredValue): measured,
   four 10 ms turns left the chain's citations unrendered, so a census would have counted a frame
   the reader never sees. */
const settle = async (): Promise<void> => {
  for (let i = 0; i < 12; i += 1) {
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
};

/* Each case starts from the store's OWN initial state, every field of it, replaced whole. This used
   to be `reset()` plus the fields someone had been bitten by (surface, palette, inspector) — a list —
   and `reset()` clears the investigation only; `evidenceTab` and `focusReturn` survived from one case
   into the next (see "each case starts from the store's own initial state", below). */
const clean = (): void =>
  act(() => {
    useInvestigation.setState(useInvestigation.getInitialState(), true);
  });

beforeEach(clean);

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  window.history.replaceState(null, "", "/");
  clean();
});

/* ── the census ─────────────────────────────────────────────────────────────── */

/** Every ARIA composite-widget role whose keyboard model is "one tab stop, arrows inside". */
const COMPOSITE_ROLES = ["radiogroup", "tablist", "toolbar", "grid", "treegrid", "tree", "listbox", "menu", "menubar"] as const;
/** The one-dimensional ones, where every item must be reachable by repeated ArrowRight/ArrowDown. */
const LINEAR: Readonly<Record<string, string>> = { radiogroup: "radio", tablist: "tab", toolbar: "" };

const rendered = (el: Element): boolean => el.closest("[hidden], [inert], [aria-hidden='true']") === null;

/** Sequential-focus stops inside `w` (the widget itself included), as the browser would count them. */
function tabStops(w: HTMLElement): HTMLElement[] {
  const all = [w, ...w.querySelectorAll<HTMLElement>("*")];
  return all.filter((el) => el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled && rendered(el) && el.getAttribute("contenteditable") !== "false");
}

/**
 * A listbox or grid whose focus stays on a combobox — the palette's results, a filter's completions
 * — is driven through `aria-activedescendant` and legitimately holds NO stop of its own. It is
 * recognised structurally: some rendered element names it in `aria-controls` and is a combobox or
 * carries `aria-activedescendant`. It must then hold zero stops, not one.
 */
function popupOwned(w: HTMLElement): boolean {
  if (w.id === "") return false;
  return [...document.querySelectorAll<HTMLElement>("[aria-controls]")].some(
    (el) =>
      (el.getAttribute("aria-controls") ?? "").split(/\s+/).includes(w.id) &&
      (el.getAttribute("role") === "combobox" || el.hasAttribute("aria-activedescendant")),
  );
}

const nameOf = (w: HTMLElement): string =>
  `${w.getAttribute("role")} "${w.getAttribute("aria-label") ?? w.id ?? w.className}"`;

function compositeViolations(root: ParentNode = document): string[] {
  const out: string[] = [];
  const sel = COMPOSITE_ROLES.map((r) => `[role="${r}"]`).join(",");
  for (const w of root.querySelectorAll<HTMLElement>(sel)) {
    if (!rendered(w)) continue;
    const stops = tabStops(w);
    const want = popupOwned(w) ? 0 : 1;
    if (stops.length !== want) {
      out.push(`${nameOf(w)}: ${stops.length} tab stop(s), expected ${want}${stops.length > 0 ? ` (${stops.map((s) => (s.textContent ?? "").trim().slice(0, 20)).join(" | ")})` : ""}`);
    }
  }
  return out;
}

/** Every arrow press the walk below makes, counted so its cost is asserted rather than timed. */
let pressesMade = 0;

const press = (el: Element, key: string): void => {
  pressesMade += 1;
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
};

/**
 * From the widget's stop, ArrowRight/ArrowDown must visit every enabled item. The widget is re-found
 * by its accessible name after every press, because a radio's arrow SELECTS, and selecting may
 * re-render the group (the pane switch re-routes the column).
 */
function unreachableItems(c: HTMLElement, reopen?: () => boolean): string[] {
  const out: string[] = [];
  const groups = [...c.querySelectorAll<HTMLElement>(Object.keys(LINEAR).map((r) => `[role="${r}"]`).join(","))]
    .filter(rendered)
    .map((g) => [g.getAttribute("role") ?? "", g.getAttribute("aria-label")] as const);
  /* A radio's arrow SELECTS, so cycling one group can change what the others are (cycling the pane
     switch off Path unmounts the path panel and its tablist). Each group is walked from the state
     the census started in, restored from the store, never from the state the previous walk left. */
  const initial = { ...useInvestigation.getState() };
  for (const [gi, [role, label]] of groups.entries()) {
    const last = gi === groups.length - 1;
    if (label === null) continue;
    act(() => { useInvestigation.getState().hydrate(initial); });
    const find = (): HTMLElement | null =>
      [...c.querySelectorAll<HTMLElement>(`[role="${role}"]`)].find((x) => x.getAttribute("aria-label") === label && rendered(x)) ?? null;
    /* A popover closes when focus leaves it (walking the previous group does that); its opener is
       the reader's way back to it. */
    if (find() === null) reopen?.();
    const g = find();
    if (g === null) {
      out.push(`${role} "${label}": not rendered again after the store was restored`);
      continue;
    }
    const itemsOf = (w: HTMLElement): HTMLElement[] =>
      [...w.querySelectorAll<HTMLElement>(LINEAR[role] ? `[role="${LINEAR[role]}"]` : "button, [tabindex]")].filter(
        (el) => rendered(el) && !(el as HTMLButtonElement).disabled,
      );
    const names = new Set(itemsOf(g).map((el) => (el.textContent ?? "").trim()));
    if (names.size < 2) continue;
    const start = tabStops(g)[0];
    if (start === undefined) continue; /* counted by compositeViolations */
    act(() => start.focus());
    const startText = (start.textContent ?? "").trim();
    const reached = new Set<string>([startText]);
    /* WHEN THE WALK STOPS (acceptance F2, 2026-09-24). Each press is a full commit of whatever the
       item selects, and the walk used to spend its whole `2 × items` budget every time. The verdict
       (`missing`, below) is computed from `reached` alone, so once every item is reached no press
       can change it; what the remaining presses DID do was return a wrapping group to its start —
       2 × n presses on a cycle of n is two full turns — and the next group's walk depends on that.
       The store restore above does not reach component-local state: measured, stopping at "all
       reached" left the evidence switch on "Finding", and the next group ("Device evidence") was
       then not rendered. So the walk completes the turn and no more: it stops when every item is
       reached AND focus is back on the start (a wrapping group, n presses), or when a press no
       longer moves focus (a group that clamps at its end, where the old walk also stayed). Both
       are exactly the end state the full budget reached, at half its cost or less. The LAST group
       has no walk after it to protect, so it stops as soon as every item is reached (n - 1). */
    const allReached = (): boolean => [...names].every((n) => reached.has(n));
    for (let i = 0; i < names.size * 2; i += 1) {
      const active = document.activeElement;
      if (active === null) break;
      const before = (active.textContent ?? "").trim();
      press(active, g.getAttribute("aria-orientation") === "vertical" ? "ArrowDown" : "ArrowRight");
      const now = find();
      if (now === null || !now.contains(document.activeElement)) break;
      const at = (document.activeElement?.textContent ?? "").trim();
      const complete = allReached(); /* before this press's item is added */
      reached.add(at);
      if (complete && at === before) break; /* clamped at the end: the old walk stayed here too */
      if (allReached() && (last || at === startText)) break; /* back where it started, unless no walk follows */
    }
    const missing = [...names].filter((n) => !reached.has(n));
    if (missing.length > 0) out.push(`${role} "${label}": arrow keys never reach ${missing.map((m) => `"${m}"`).join(", ")}`);
  }
  return out;
}

/* ── D1, the instance: PaneSwitch on Path with no flow ────────────────────────── */

describe("PaneSwitch always exposes exactly one tab stop", () => {
  const render = (value: PaneId, pathAvailable: boolean): HTMLElement =>
    mount(
      <PaneSwitch
        value={value}
        onChange={() => {}}
        pathAvailable={pathAvailable}
        showPanes
        fabricVisible
        onToggleFabric={() => {}}
        fabricOptional={false}
      />,
    );

  it('value="path" with pathAvailable={false}: one radio is tabindex=0 and one is checked', () => {
    const c = render("path", false);
    const radios = [...c.querySelectorAll<HTMLElement>('[role="radio"]')];
    expect(radios.length).toBeGreaterThan(0);
    expect(radios.filter((r) => r.getAttribute("tabindex") === "0"), "no radio is in the tab order").toHaveLength(1);
    expect(radios.filter((r) => r.getAttribute("aria-checked") === "true"), "the group names no checked radio").toHaveLength(1);
  });

  for (const value of ["queue", "path", "evidence"] as const) {
    for (const pathAvailable of [true, false]) {
      it(`value="${value}", pathAvailable=${pathAvailable}: exactly one tab stop`, () => {
        const c = render(value, pathAvailable);
        expect(compositeViolations(c)).toEqual([]);
      });
    }
  }

  it("the arrow keys move between the panes (APG radio group), so every pane is reachable", () => {
    let value: PaneId = "queue";
    const c = document.createElement("div");
    document.body.appendChild(c);
    const root = createRoot(c);
    mounted.push({ root, container: c });
    const draw = (): void =>
      act(() =>
        root.render(
          <PaneSwitch
            value={value}
            onChange={(p) => {
              value = p;
              draw();
            }}
            pathAvailable
            showPanes
            fabricVisible
            onToggleFabric={() => {}}
            fabricOptional={false}
          />,
        ),
      );
    draw();
    expect(unreachableItems(c)).toEqual([]);
  });

  /* THE WALK'S COST, COUNTED (acceptance F2, 2026-09-24). Every press is a React commit of whatever
     the item selects — on the full app a pane re-route, an evidence-table swap or an inspector view,
     measured at 0.5-1.2 s each in jsdom on a busy host — and the walk used to spend its whole
     `2 × items` budget on every group: two full turns of a wrapping group. The census cases timed
     out at 30 s on a loaded host because of it. The walk now makes one full turn of a group that
     another walk follows (every item reached, and back on the start, because the store restore
     cannot reach component-local state) and stops at "every item reached" on the last one.

     The fixture is two groups with LOCAL state, the second rendered only while the first is on its
     start — the shape of the real app's evidence switch and its "Device evidence" tablist, which a
     walk that stopped at "every item reached" left unrendered. It is a fixture of the WALK, not of
     the app: the app's own groups are censused by the cases below. Counted, not timed: the full
     budget is 6 + 4 = 10 presses here, one turn plus a reach is 3 + 1 = 4. */
  it("the walk costs one turn per followed group and a reach for the last: 4 presses here, not 10", () => {
    const Roving = ({ label, items, onValue }: { label: string; items: readonly string[]; onValue?: (v: string) => void }): ReactNode => {
      const [value, setValue] = useState(items[0] ?? "");
      const refs = useRef<(HTMLButtonElement | null)[]>([]);
      const group = useRef<HTMLDivElement | null>(null);
      useEffect(() => {
        onValue?.(value);
        if (group.current?.contains(document.activeElement)) refs.current[items.indexOf(value)]?.focus();
      }, [value, items, onValue]);
      return (
        <div
          ref={group}
          role="radiogroup"
          aria-label={label}
          onKeyDown={(e) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowDown") return;
            setValue(items[(items.indexOf(value) + 1) % items.length] ?? value);
          }}
        >
          {items.map((it, i) => (
            <button
              key={it}
              ref={(el) => {
                refs.current[i] = el;
              }}
              role="radio"
              aria-checked={it === value}
              tabIndex={it === value ? 0 : -1}
            >
              {it}
            </button>
          ))}
        </div>
      );
    };
    const Pair = (): ReactNode => {
      const [first, setFirst] = useState("a");
      return (
        <>
          <Roving label="first" items={["a", "b", "c"]} onValue={setFirst} />
          {first === "a" ? <Roving label="second" items={["x", "y"]} /> : null}
        </>
      );
    };
    const c = mount(<Pair />);
    expect(c.querySelectorAll('[role="radiogroup"]'), "precondition: both groups render at the start").toHaveLength(2);
    const before = pressesMade;
    expect(unreachableItems(c)).toEqual([]);
    expect(pressesMade - before).toBe(4);
  });
});

/* ── D1, the class: every composite widget in every rendered app state ───────── */

const FLOW = "10.0.10.50>10.0.30.10>tcp>3389";
const firstFinding = fabric.findings[0]?.id ?? "";
/* The device the device-pane states select, chosen by PROPERTY (phase 3.5 close): the routable host — one whose
   routing table was collected, so its Routing tab has records — with the most links (its Ports tab), ties by
   host. It was the literal "core1", which on the rename leg named no device: every "device evidence: <tab>" case
   there censused a page with no device pane at all, and failed on the tab it could not open. */
const SELECTED_DEVICE = ((): string => {
  const degree = new Map<string, number>();
  for (const l of fabric.links) for (const h of [l.a, l.b]) degree.set(h, (degree.get(h) ?? 0) + 1);
  const routable = new Set(fabric.coverage.routableHosts);
  const pool = fabric.devices.some((d) => routable.has(d.host)) ? fabric.devices.filter((d) => routable.has(d.host)) : fabric.devices;
  const best = [...pool].sort((x, y) => (degree.get(y.host) ?? 0) - (degree.get(x.host) ?? 0) || (x.host < y.host ? -1 : x.host > y.host ? 1 : 0))[0];
  if (best === undefined) throw new Error("precondition: the dataset has a device to select");
  return best.id;
})();
/** The states a reader reaches, as shareable links, so each is one reproducible URL. */
/** Open a surface the way a pointer reader does: click the first rendered control matching `sel`. */
const clickFirst =
  (sel: string) =>
  (): boolean => {
    const el = [...document.querySelectorAll<HTMLElement>(sel)].find(rendered);
    if (el === undefined) return false;
    act(() => el.click());
    return true;
  };
/** [name, shareable-link query, an optional surface opened after the load]. An opener that finds
 *  nothing to open at a width (the More popover exists only below 1024 px) leaves that case equal to
 *  its link's plain state, which is still censused. */
const STATES: readonly (readonly [string, string, (() => boolean)?])[] = [
  ["idle", ""],
  ["path surface, no flow", "s=path"],
  ["findings surface", "s=findings"],
  ["evidence surface", "s=evidence"],
  ["a device selected", `d=${encodeURIComponent(SELECTED_DEVICE)}&s=fabric`],
  ["a finding selected", `f=${encodeURIComponent(firstFinding)}&s=findings`],
  ["a traced flow", `s=path&flow=${encodeURIComponent(FLOW)}`],
  ["the command palette open", "", () => (act(() => { useInvestigation.getState().setPaletteOpen(true); }), true)],
  ["the inspector open from a citation", `f=${encodeURIComponent(firstFinding)}&s=findings`, clickFirst("button.ui-cite")],
  ["the More popover open on Path", "s=path", clickFirst("button.hdr-more")],
  /* Every Device-evidence tab (W6 gate, 2026-09-25). The census used to visit the device pane on its
     default tab only, so the Ports and Routing record grids — 31 and 9 tab stops on core1, one per
     cite button — were never counted. Derived from the tab list the URL parser itself accepts, not
     listed here; the default tab is the "a device selected" state above. */
  ...EVIDENCE_TABS.filter((t) => t !== useInvestigation.getInitialState().evidenceTab).map(
    (t) => [`device evidence: ${t}`, `d=${encodeURIComponent(SELECTED_DEVICE)}&s=fabric&tab=${t}`] as const,
  ),
];
/** One width per ladder rung (1100 is the drawer rung). The runtime audit derives its own widths from
 *  LADDER_REM (review/audit-d3-focus.mjs), so this list is not a copy of them. */
const WIDTHS = [390, 768, 1000, 1100, 1440, 1920] as const;

describe("every rendered composite widget has exactly one tab stop, and its items are arrow-reachable", () => {
  /* WHAT A CASE ALSO PROVES, AT NO EXTRA MOUNT (acceptance F2, 2026-09-24). "The census is not
     vacuous" and "the opener opens what it names" were four more tests, each mounting the app in a
     state that a case below ALSO mounts — idle at 1440 px, and each opener's state at its width —
     so four extra full mounts per run. Measured on a clean clone at ~80 % host load they were the
     slowest tests in the file (16-37 s; the palette opener timed out at 30 s twice), because they
     ran first, in the suite's most contended minutes. Each is now asserted INSIDE the case that
     mounts the identical state, against the identical frame: the claims are unchanged and each
     costs one mount. The test below keeps the proof honest: every opener has one, and every proof
     sits on a width and a state the loop actually runs. */
  const OPENED: readonly (readonly [string, number, string])[] = [
    ["the command palette open", 1440, '[role="dialog"]'],
    ["the inspector open from a citation", 1440, '#inspector [role="tablist"]'],
    ["the More popover open on Path", 768, '[role="toolbar"]'],
  ];
  /** The census is not vacuous: this frame renders radio groups and a grid. */
  const NON_VACUOUS = { state: "idle", width: 1440, roles: ["radiogroup", "grid"] } as const;

  it("every state that carries an opener is proven to open something, by a case the loop runs", () => {
    const withOpener = STATES.filter(([, , open]) => open !== undefined).map(([n]) => n);
    expect(withOpener.length, "precondition: some states carry an opener").toBeGreaterThan(0);
    expect([...OPENED.map(([n]) => n)].sort()).toEqual([...withOpener].sort());
    const states = STATES.map(([n]) => n);
    for (const [name, width] of [...OPENED, [NON_VACUOUS.state, NON_VACUOUS.width] as const]) {
      expect(WIDTHS as readonly number[], `${name}: its proof names a width the loop does not run`).toContain(width);
      expect(states, `${name}: its proof names a state the loop does not run`).toContain(name);
    }
  });

  /* QUIET STACKS (acceptance F2, 2026-09-24). React 19's development build constructs an Error for
     every element it creates, to record the element's owner stack (react-jsx-dev-runtime:
     `Error("react-stack-top-frame")`, up to 10 000 per batch), and V8 captures up to
     `Error.stackTraceLimit` frames into each. A case here creates hundreds of thousands of elements
     — a mount, the settles, and every press of the walk re-render the whole app — and that capture
     was about a third of a case's cost: measured on the same subset back to back, median 2.3-2.5 s a
     case with the default limit of 10 and 1.6 s with 0. The census reads the DOM; no assertion here
     reads a stack. So the frame is built with capture off, every observation is taken inside that
     window, and the limit is restored BEFORE any assertion runs, so a failure still reports where it
     failed. What is lost while it is off is only React's debug owner stack, and the stack (not the
     message) of an exception thrown by the app itself. */
  for (const width of WIDTHS) {
    for (const [state, query, open] of STATES) {
      const proof = OPENED.find(([n, w]) => n === state && w === width);
      const nonVacuous = state === NON_VACUOUS.state && width === NON_VACUOUS.width;
      /* A device-tab state at 1440 px proves its link opens that tab, so the case censuses the tab's
         grids and not the default panel. */
      const tabProof = width === 1440 ? /^device evidence: (.+)$/.exec(state)?.[1] : undefined;
      it(`${width} px, ${state}`, { timeout: 30000 }, async () => {
        const restore = setViewport(width);
        const stackLimit = Error.stackTraceLimit;
        let roles: (string | null)[] = [];
        let opened: boolean | undefined;
        let openedSurface: Element | null = null;
        let violations: string[];
        let unreachable: string[];
        let tabShown: string | null | undefined;
        try {
          Error.stackTraceLimit = 0;
          window.history.replaceState(null, "", query === "" ? "/" : `/?${query}`);
          const c = mount(<App />);
          await settle();
          if (nonVacuous) roles = [...new Set([...c.querySelectorAll(COMPOSITE_ROLES.map((r) => `[role="${r}"]`).join(","))].map((e) => e.getAttribute("role")))];
          if (tabProof !== undefined) tabShown = document.querySelector('[role="tab"][aria-selected="true"][id^="dp-tab-"]')?.id ?? null;
          if (open !== undefined) {
            opened = open();
            await settle();
            if (proof !== undefined) openedSurface = document.querySelector(proof[2]);
          }
          /* The whole document, not the container: dialogs and popovers are portalled to <body>. */
          violations = compositeViolations(document.body);
          unreachable = unreachableItems(document.body, open);
        } finally {
          Error.stackTraceLimit = stackLimit;
          restore();
        }
        if (nonVacuous) expect(roles, "the census is not vacuous").toEqual(expect.arrayContaining([...NON_VACUOUS.roles]));
        if (proof !== undefined) {
          expect(opened, `${state}: nothing to open at ${width} px`).toBe(true);
          /* The opener opens what it names, so this case censuses that surface and not an idle frame. */
          expect(openedSurface, `${state}: ${proof[2]} not rendered`).not.toBeNull();
        }
        if (tabProof !== undefined) expect(tabShown, `${state}: the link did not open that tab`).toBe(`dp-tab-${tabProof}`);
        expect(violations, `at ${width} px, ${state}`).toEqual([]);
        expect(unreachable, `at ${width} px, ${state}`).toEqual([]);
      });
    }
  }
});

/* ── the harness's isolation ──────────────────────────────────────────────────── */

describe("each case starts from the store's own initial state", () => {
  /* Found 2026-09-24 while cutting the walk's cost (acceptance F2): the walk left the "Device
     evidence" tablist on its last tab, `clean()` restored only the fields it NAMED (reset() plus
     surface, palette and inspector), and the next case mounted with `evidenceTab` still on
     "routing" — a census of a state no link in STATES names, 1440 and 1920 px only, in file order
     only. The old walk hid it by turning every group twice, back to its start. A reset that lists
     fields is the named-subset shape; this pins the class: every field, whatever a case did. */
  it("clean() returns every field of the store to its initial value", () => {
    const initial = useInvestigation.getInitialState();
    const fields = Object.keys(initial).filter((k) => typeof initial[k as keyof typeof initial] !== "function");
    expect(fields.length, "precondition: the store has state fields").toBeGreaterThan(5);
    act(() => {
      const s = useInvestigation.getState();
      s.hydrate({ deviceId: SELECTED_DEVICE, findingId: firstFinding, query: "x", onlyUncollected: true });
      s.setSurface("path");
      s.setEvidenceTab("routing");
      s.setPaletteOpen(true, document.createElement("button"));
      s.setInspectorOpen(true);
    });
    const moved = fields.filter((k) => !isDeepStrictEqual(useInvestigation.getState()[k as keyof typeof initial], initial[k as keyof typeof initial]));
    expect(moved, "precondition: the probe moved fields reset() does not name").toEqual(expect.arrayContaining(["evidenceTab", "surface"]));
    clean();
    const after = useInvestigation.getState();
    const left = fields.filter((k) => !isDeepStrictEqual(after[k as keyof typeof initial], initial[k as keyof typeof initial]));
    expect(left, "fields clean() left as the previous case set them").toEqual([]);
  });
});

/* ── the detector itself ──────────────────────────────────────────────────────── */

describe("the census detector", () => {
  const html = (s: string): HTMLElement => {
    const d = document.createElement("div");
    d.innerHTML = s;
    document.body.appendChild(d);
    return d;
  };

  it("flags a group whose roving value matches no item, and one with two stops", () => {
    const none = html('<div role="radiogroup" aria-label="g"><button role="radio" tabindex="-1">a</button><button role="radio" tabindex="-1">b</button></div>');
    expect(compositeViolations(none)).toHaveLength(1);
    const two = html('<div role="tablist" aria-label="t"><button role="tab">a</button><button role="tab">b</button></div>');
    expect(compositeViolations(two)).toHaveLength(1);
    const ok = html('<div role="radiogroup" aria-label="g"><button role="radio" tabindex="0">a</button><button role="radio" tabindex="-1">b</button></div>');
    expect(compositeViolations(ok)).toEqual([]);
  });

  it("does not count a hidden widget, a disabled item, or an inert one", () => {
    const d = html(
      '<div hidden><div role="radiogroup" aria-label="h"><button role="radio" tabindex="-1">a</button></div></div>' +
        '<div role="toolbar" aria-label="t"><button tabindex="0">a</button><button disabled>b</button></div>',
    );
    expect(compositeViolations(d)).toEqual([]);
  });

  it("requires ZERO stops in a listbox driven by a combobox's aria-activedescendant", () => {
    const d = html(
      '<input role="combobox" aria-controls="lb" aria-activedescendant="o1"><ul role="listbox" id="lb"><li role="option" id="o1">x</li></ul>',
    );
    expect(compositeViolations(d)).toEqual([]);
    const bad = html('<input role="combobox" aria-controls="lb2"><ul role="listbox" id="lb2"><li role="option" tabindex="0">x</li></ul>');
    expect(compositeViolations(bad)).toHaveLength(1);
  });

  it("reports a group whose arrows reach nothing", () => {
    const d = html('<div role="radiogroup" aria-label="g"><button role="radio" tabindex="0">a</button><button role="radio" tabindex="-1">b</button></div>');
    expect(unreachableItems(d)).toEqual(['radiogroup "g": arrow keys never reach "b"']);
  });
});
