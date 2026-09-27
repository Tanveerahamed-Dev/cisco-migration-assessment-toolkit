/**
 * self-removing-focus.test.tsx — acceptance D3 for the class the first-pass audit did not drive: a
 * control whose OWN activation unmounts it.
 *
 * MEASURED (acceptance report, D3 overturned PASS to FAIL): "reached 'Remove the Critical severity
 * filter' after 7 Tabs (focus-visible=true) / after Enter + 2.5s: {tag: BODY}" — and the same for
 * "Remove the High severity filter", "Clear scope", "Deselect device core1" and "Stop investigating
 * the flow …". Each is a control that removes itself when pressed, so the element holding focus
 * leaves the document and the browser parks focus on <body>. The keyboard reader's next Tab starts
 * again from the top of the page and a screen reader announces nothing.
 *
 * THE DENOMINATOR IS DISCOVERED, NOT LISTED. The whole application is mounted with every kind of
 * scope token the query bar can carry (a query, two severities, a role, the uncollected-only
 * restriction, a finding, a device, a link and a flow). EVERY tab stop on screen is then pressed —
 * with Enter, and separately with Space — from the seeded state, and a control that is no longer in
 * the document afterwards IS a self-removing control, whatever it is called and wherever it lives.
 * For each of those, focus must have been handed to a connected, unhidden focus target; and no press
 * at all may leave focus on <body>, whether or not the control survived. The only thing asserted
 * about the SET is a floor: every Chip primitive's remove control on screen is in it — so the drive
 * cannot pass by pressing nothing.
 *
 * `:focus-visible` IS THE BROWSER AUDIT'S, NOT THIS FILE'S. MEASURED 2026-09-23 in this runner:
 * jsdom matches `:focus-visible` on a focused text input and NEVER on a focused button or a
 * `tabindex=-1` heading, whatever input preceded it — it has no input-modality heuristic. Asserting
 * it here would fail every correct hand-off to a button. Chromium's heuristic (a script focus after
 * a key press is focus-visible) is measured, with the ring's pixels, by the real-browser pass.
 *
 * FROM THE SEEDED STATE, EVERY TIME. Between presses the investigation is restored in place (the
 * store is re-hydrated with the seeded snapshot, dialogs are closed, per-reader preferences are
 * cleared). If the tab stops on screen then differ in any way from the seeded page's — a press
 * changed something the store does not hold — the application is unmounted and mounted afresh
 * before the next press. Remounting for every press is the same check and ~5x slower.
 *
 * KEYBOARD, AS JSDOM CAN DO IT. jsdom runs no activation behaviour for keys, so `press` dispatches
 * the real keydown (and keyup, for Space) to the focused control — every key handler in the app
 * sees what a browser would send — and then performs the browser's own default action for that key
 * on that element (Enter: click a button, link or summary on keydown; Space: click a button,
 * summary, checkbox or radio on keyup) unless a handler cancelled the key. The real-browser
 * counterpart, reached by real Tab presses at 1440, 768 and 390 px, is
 * `node review/audit-d3-focus.mjs --self-removing`.
 *
 * ONE TIMEOUT IS ONE RED (acceptance F2, the load cascade). At 85-100 % host CPU one case here timed
 * out at 37 s and the 277 cases after it all failed "the seeded flow had not been traced": Vitest
 * does not stop a timed-out body, its act() scope closed out of order with the next case's, and
 * React's act depth stuck so nothing committed again. Every async act() here now goes through
 * `src/test-support/act-turns.ts` (a checkpoint on this case's own signal on each side of it), each
 * case's work is `track()`ed, and the after-each hook settles it BEFORE touching React — so an
 * abandoned case stops within one turn and the next one starts from a clean root.
 *
 * THE UNIT OF WORK. Restoring the seeded page (sometimes a full remount: ~6 s at ~99 % load) runs in
 * the case's before-each hook, with its own budget; the case itself is focus, press and verdict.
 * React 19's development build captures an `Error` stack for every element it creates (measured:
 * ~25 % of this file's CPU); the synchronous React work of mounting, restoring and pressing runs
 * with `Error.stackTraceLimit` lowered for its duration only (`reactWork`), and an error raised
 * inside it is re-raised with a full stack of its own. Assertion stacks are untouched.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation, type InvestigationState } from "../core/store";
import { flushTurns, settleActTurns, track } from "../test-support/act-turns";
import { setCharacterKeyShortcuts, setHelpOpen } from "./keyboard";

vi.mock("../fabric3d/Fabric3D", () => ({ default: () => <div />, Fabric3D: () => <div /> }));

import { App } from "./App";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* ── the seeded investigation: one token of every kind the scope bar renders ── */

const LINK = fabric.links[0]?.id ?? null;
const FLOW = "10.0.10.50>10.0.30.10>tcp>3389";
const SEEDED = (): string => {
  const p = new URLSearchParams();
  p.set("s", "findings");
  p.set("q", "gateway");
  p.set("sev", "CH");
  p.set("role", "access");
  p.set("unc", "1");
  p.set("f", fabric.findings[0]!.id);
  p.set("d", "core1");
  if (LINK !== null) p.set("l", LINK);
  p.set("flow", FLOW);
  return `/?${p.toString()}`;
};

/* ── the tab stops, by a stable identity ── */

const hiddenByAncestor = (el: Element): boolean => {
  for (let n: Element | null = el; n !== null; n = n.parentElement) {
    if (n.hasAttribute("hidden") || n.hasAttribute("inert") || n.getAttribute("aria-hidden") === "true") return true;
    if (n instanceof HTMLElement && (n.style.display === "none" || n.style.visibility === "hidden")) return true;
  }
  return false;
};

const FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable='true']";

/** Every tab stop in document order: focusable, not disabled, tabIndex >= 0, not hidden. */
function tabStops(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (el) =>
      el.tabIndex >= 0 &&
      !(el as HTMLButtonElement).disabled &&
      !hiddenByAncestor(el) &&
      !(el instanceof HTMLInputElement && el.type === "hidden"),
  );
}

const nameOf = (el: Element): string => {
  const label = el.getAttribute("aria-label");
  if (label !== null && label.trim() !== "") return label.trim();
  const by = (el.getAttribute("aria-labelledby") ?? "")
    .split(/\s+/)
    .map((id) => (id === "" ? "" : (document.getElementById(id)?.textContent ?? "")))
    .join(" ")
    .trim();
  return by || (el.textContent ?? "").trim() || el.getAttribute("placeholder") || el.tagName;
};

interface Stop {
  ident: string;
  occurrence: number;
  el: HTMLElement;
}

function identify(els: readonly HTMLElement[]): Stop[] {
  const seen = new Map<string, number>();
  return els.map((el) => {
    const role = el.getAttribute("role");
    const ident = `${el.tagName.toLowerCase()}${role ? `[${role}]` : ""} "${nameOf(el).replace(/\s+/g, " ").slice(0, 60)}"`;
    const occurrence = seen.get(ident) ?? 0;
    seen.set(ident, occurrence + 1);
    return { ident, occurrence, el };
  });
}

const keyOf = (s: { ident: string; occurrence: number }): string => `${s.ident}${s.occurrence > 0 ? ` #${s.occurrence + 1}` : ""}`;

/* ── mounting and restoring ── */

let current: { root: Root; container: HTMLElement } | null = null;
const MOUNT_TURNS = 50;
let seeded: { state: InvestigationState; signature: string; search: string } | null = null;

/* Checkpointed act turns: an abandoned case stops at the next one instead of opening a scope inside
   a later case. */
const flush = (ms = 10, rounds = 3): Promise<void> => flushTurns(ms, rounds);

/**
 * Synchronous React work (render, hydrate, a key press) with React 19 dev's per-element stack
 * capture made cheap: `Error.stackTraceLimit` is lowered for exactly this call and restored in
 * `finally`. Nothing else runs while it is low (the work is synchronous), and an error raised
 * inside is re-raised from here, after the limit is restored, so its report carries a full stack.
 */
function reactWork<T>(work: () => T): T {
  const limit = Error.stackTraceLimit;
  let raised: unknown = undefined;
  let failed = false;
  let value: T | undefined;
  Error.stackTraceLimit = 1;
  try {
    value = work();
  } catch (e) {
    failed = true;
    raised = e;
  } finally {
    Error.stackTraceLimit = limit;
  }
  if (failed) {
    const message = raised instanceof Error ? raised.message : String(raised);
    throw new Error(`${message} (raised inside React work run with a 1-frame stack limit; its own stack is truncated, see cause)`, { cause: raised });
  }
  return value as T;
}

/** State outside the investigation store that a press can leave behind. */
function clearGlobals(): void {
  act(() => {
    setHelpOpen(false);
    useInvestigation.setState({ paletteOpen: false, inspectorOpen: false });
    setCharacterKeyShortcuts(true);
  });
  try {
    localStorage.clear();
    sessionStorage.clear();
  } catch {
    /* no storage: nothing to clear */
  }
}

function unmount(): void {
  if (current === null) return;
  const c = current;
  current = null;
  act(() => c.root.unmount());
  c.container.remove();
  document.body.innerHTML = "";
}

async function mountSeeded(): Promise<Stop[]> {
  unmount();
  clearGlobals();
  useInvestigation.getState().reset();
  window.history.replaceState(null, "", SEEDED());
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  reactWork(() => act(() => root.render(<App />)));
  current = { root, container };
  /* The restored flow is traced after the first commit; the scope bar then carries every token.
     COUNTED, not timed (acceptance F2, W6 gate 2026-09-25): the wait was a `Date.now() + 8000`
     deadline, which measured the host. The trace lands after one frame and one task, so a bounded
     count of flush turns waits for it whatever the load, and running out is a stated failure. */
  let turns = 0;
  for (; useInvestigation.getState().trace === null && turns < MOUNT_TURNS; turns += 1) await flush(10, 1);
  if (useInvestigation.getState().trace === null) {
    /* Measured over a full run at ~99 % host load: 59 of 59 mounts traced on the FIRST turn. Running
       out of turns is therefore not a slow host; it means React is not committing. */
    throw new Error(
      `the seeded flow had not been traced after ${MOUNT_TURNS} flush turns: React committed no restore effect ` +
        `(an act() scope left open or a corrupted act depth — see any [act-scope guard] error above — or the ` +
        `restore effect itself did not run). The trace lands on the first turn when React commits, so this is ` +
        `not the host being slow.`,
    );
  }
  await flush(10, 4);
  const stops = identify(tabStops());
  if (seeded === null) seeded = { state: { ...useInvestigation.getState() }, signature: stops.map(keyOf).join("\n"), search: window.location.search };
  return stops;
}

/**
 * Back to the seeded page: in place when that reproduces it exactly, by a fresh mount otherwise.
 * Returns the page's tab stops, identified once (the signature check already needs them).
 */
async function restore(): Promise<Stop[]> {
  if (current === null || seeded === null) return mountSeeded();
  clearGlobals();
  const s = seeded;
  reactWork(() =>
    act(() => {
      window.history.replaceState(null, "", `/${s.search}`);
      useInvestigation.getState().hydrate(s.state);
    }),
  );
  await flush(10, 3);
  const stops = identify(tabStops());
  if (stops.map(keyOf).join("\n") !== s.signature) return mountSeeded();
  return stops;
}

/* ── a key press, with the browser's default action ── */

type ActivationKey = "Enter" | "Space";

function press(el: HTMLElement, key: ActivationKey): void {
  const init: KeyboardEventInit = { key: key === "Space" ? " " : "Enter", code: key, bubbles: true, cancelable: true };
  const tag = el.tagName;
  const type = el instanceof HTMLInputElement ? el.type : "";
  reactWork(() =>
    act(() => {
      const down = el.dispatchEvent(new KeyboardEvent("keydown", init));
      if (key === "Enter") {
        const activates = tag === "BUTTON" || tag === "SUMMARY" || (tag === "A" && el.hasAttribute("href")) || ["submit", "button", "reset"].includes(type);
        if (down && activates) el.click();
        el.dispatchEvent(new KeyboardEvent("keyup", init));
        return;
      }
      const up = el.dispatchEvent(new KeyboardEvent("keyup", init));
      const activates = tag === "BUTTON" || tag === "SUMMARY" || ["checkbox", "radio", "submit", "button", "reset"].includes(type);
      if (down && up && activates) el.click();
    }),
  );
}

/* ── the drive ── */

interface Outcome {
  stop: string;
  removed: boolean;
  landed: string;
  ok: boolean;
  why: string;
}

const describeActive = (): string => {
  const a = document.activeElement;
  if (a === null) return "null";
  if (a === document.body) return "BODY";
  return `${a.tagName.toLowerCase()} "${nameOf(a).replace(/\s+/g, " ").slice(0, 50)}"`;
};

/** Press one stop of the page `restore` just produced (its `stops`), from the seeded state. */
async function drive(stops: readonly Stop[], target: { ident: string; occurrence: number }, key: ActivationKey): Promise<Outcome | null> {
  const el = stops.find((s) => s.ident === target.ident && s.occurrence === target.occurrence)?.el;
  if (el === undefined || !el.isConnected) return null;
  act(() => el.focus());
  if (document.activeElement !== el) return null;
  press(el, key);
  await flush(20, 4);
  const removed = !el.isConnected;
  const a = document.activeElement;
  let why = "";
  if (a === null || a === document.body || !a.isConnected) why = "focus was left on <body>";
  else if (hiddenByAncestor(a)) why = "focus went to a hidden element";
  else if (removed && a instanceof HTMLElement && !(a.tabIndex >= 0 || a.hasAttribute("tabindex"))) why = "the successor is not a focus target";
  return { stop: keyOf(target), removed, landed: describeActive(), ok: why === "", why };
}

/* ── the tests ── */

const realMatchMedia = window.matchMedia;

beforeAll(() => {
  /* Copy actions are tab stops too; jsdom has no clipboard, and a rejection there is not what this
     file measures. */
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: () => Promise.resolve(), readText: () => Promise.resolve("") },
  });
});

/** A desktop viewport, so the shell lays out every rail (jsdom has no matchMedia). */
function desktopViewport(): void {
  window.matchMedia = ((q: string) => {
    let matches = true;
    for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)rem\)/g)) {
      const bound = Number.parseFloat(m[2] as string) * 16;
      matches &&= m[1] === "min" ? 1600 >= bound : 1600 <= bound;
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
}

beforeEach(() => {
  desktopViewport();
  vi.spyOn(window, "open").mockImplementation(() => null);
});

/* The seeded page is KEPT between cases — each case restores it in place (`restore`, which remounts
   when the in-place restore does not reproduce it exactly), as the single drive did between presses.
   Only per-case globals are cleared here; the page itself goes once, after the last case.

   FIRST, the case's own work is settled: a case the runner abandoned (a timeout under load) is still
   running, parked in an act() turn. It stops at its next checkpoint, and nothing here touches React
   until it has — clearGlobals() opens an act() scope of its own. A case that failed or was abandoned
   may have left the page in any state, so the next case remounts rather than restoring in place. */
afterEach(async (ctx) => {
  await settleActTurns();
  if (ctx.signal.aborted || ctx.task.result?.state === "fail") unmount();
  clearGlobals();
  window.matchMedia = realMatchMedia;
  vi.restoreAllMocks();
});

afterAll(() => {
  unmount();
  seeded = null;
  clearGlobals();
  window.history.replaceState(null, "", "/");
  useInvestigation.getState().reset();
});

/* ── the denominator, discovered once, at collection ──
 *
 * ONE CASE PER TAB STOP PER KEY (acceptance F2, W6 gate 2026-09-25). The drive was two tests, one
 * per key, each pressing every tab stop in turn: 55 s each on a quiet host, 168-206 s on a saturated
 * clone, under a 1 200 s limit of its own — a unit of work the size of the page. The page is now
 * mounted once while this file is COLLECTED, its tab stops are identified exactly as the drive
 * identifies them, and each (stop, key) is a case. The denominator is still discovered, not listed;
 * the floor (every Chip remove control on screen is among the stops, and each removes itself) is
 * asserted per remove control and as a count. */
interface Discovered {
  ident: string;
  occurrence: number;
  /** A Chip primitive's remove control: the floor, so the drive cannot pass by pressing nothing. */
  remover: boolean;
}
async function discover(): Promise<Discovered[]> {
  desktopViewport();
  try {
    await mountSeeded();
    return identify(tabStops()).map(({ ident, occurrence, el }) => ({ ident, occurrence, remover: el.matches(".ui-chip__remove") }));
  } finally {
    unmount();
    seeded = null;
    clearGlobals();
    window.matchMedia = realMatchMedia;
    window.history.replaceState(null, "", "/");
    useInvestigation.getState().reset();
  }
}
const DISCOVERED = await discover();

describe("D3: a control that removes itself hands focus to a visible successor", () => {
  it("the seeded page renders its tab stops and its remove controls (the floor)", () => {
    expect(DISCOVERED.length, "precondition: the seeded page rendered tab stops").toBeGreaterThan(20);
    /* One per token, in the scope bar and again in the queue's own chip row. */
    expect(DISCOVERED.filter((d) => d.remover).length, "precondition: the seeded scope rendered its remove controls").toBeGreaterThanOrEqual(9);
  });

  describe("each tab stop, pressed from the seeded page", () => {
    /* The seeded page is restored in each case's before-each hook: a remount is the largest unit of
       work here (~6 s at ~99 % load, against ~1.6 s for a whole in-place case), and it gets a hook's own
       budget instead of eating the case's. The case is the focus, the press and the verdict. */
    let stops: Stop[] = [];
    beforeEach(async () => {
      stops = [];
      stops = await track(restore());
    });

    for (const key of ["Enter", "Space"] as const) {
      for (const stop of DISCOVERED) {
        it(`${keyOf(stop)} pressed with ${key}: focus is not left on <body>${stop.remover ? ", and the remove control removes itself and hands focus on" : ""}`, async () => {
          const o = await track(drive(stops, stop, key));
          expect(o, "the tab stop could not be found again and focused from the seeded state").not.toBeNull();
          if (stop.remover) expect(o!.removed, "a remove control that did not remove itself").toBe(true);
          expect(o!.ok ? "" : `${o!.stop} [${key}]${o!.removed ? " (removed itself)" : ""} -> ${o!.landed}: ${o!.why}`).toBe("");
        });
      }
    }
  });
});
