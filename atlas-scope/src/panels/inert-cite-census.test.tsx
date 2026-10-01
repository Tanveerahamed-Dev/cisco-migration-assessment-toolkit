/**
 * inert-cite-census.test.tsx — the class: citation-shaped text that is not a working citation
 * control, anywhere the app renders (acceptance B6, wave 7).
 *
 * THE DEFECT SHAPE. B6 has failed three times on the same shape in three places: a sentence that
 * names its record ("…(l3_forwarding[5])…") printed where the reader cannot open it. First as plain
 * prose (R81, fixed by `cited-text.tsx`), then as a sentence assembled from cited records that dropped
 * their cites, then — at 8eac055 — as prose INSIDE a run-this-flow button: the Path presets printed
 * five citations inside `<button onClick={run}>`, so clicking the `l3_forwarding[5]` sentence re-ran
 * the flow and opened nothing. Each fix guarded the surface the last report named. The report's own
 * words for what was never swept: the blast-radius stage button, the status-bar denominators, and the
 * DevicePane / EvidencePane prose.
 *
 * THE CLASS, NOT THE NAMES. So this census is stated over what a citation IS, not over components or
 * class names:
 *   1. A citation is whatever the shipped resolver recognises — `citesIn` (./cited-text.tsx), which
 *      asks the Inspector's own `citationCandidates` whether the compiled model holds a record for the
 *      token. Every text run and every reader-facing attribute (`title`, `aria-label`,
 *      `aria-description`, `placeholder`, `alt`, `aria-valuetext`) of the rendered document is read.
 *   2. Each one must be OWNED by a control, and that control must WORK: activating it must put the
 *      Inspector on that record (`#inspector[data-cite]`, or the model path it shows,
 *      `[data-model-path]`). Its label is not trusted — it is activated (clicked; a treeitem is
 *      activated by Enter, as its role defines). A citation in a button that does something else
 *      (the preset shape) fails exactly as a citation in no control does. The one other working
 *      outcome is a COPY TOOL: a control named "Copy …" whose activation writes that citation to the
 *      clipboard (observed, not assumed — see `verifyAll`).
 *   3. No control is nested inside another: a citation inside a run button must be restructured, not
 *      nested, because nested interactive content is invalid HTML and unreachable to assistive tech.
 * Two things are not citations to open, stated by what they are rather than by name: the Inspector's
 * own label for the record it is showing (the same `data-cite` / `data-model-path`), and a
 * screen-reader announcement (a visually hidden live region), which cannot hold a control.
 *
 * EVERY STATE THE APP CAN REACH, derived from the snapshot rather than listed: every surface at one
 * width per ladder rung, every device on every evidence tab, every finding, every link, every
 * suggested flow on every hop with its counterexample, every searchable intent, the palette, the
 * header's More popover, the queue's cross-layer corpus, the command palette with each suggested
 * flow's source typed — and the Inspector, at one record of every rendering shape among every record
 * the model cites and every record a control in those states was proven to open (see its block for why
 * a shape, not every record). Activations are batched into one React commit per state and read off the
 * Inspector's own citation (`inspectorCite`), which is what lets the census afford to activate every
 * control it finds (a render per activation measured 65-245 ms, over a thousand activations).
 *
 * `INERT_CITE_CENSUS_OUT=<file>` appends every state's findings and timing to a file, for diagnosis.
 *
 * SCOPED OUT, EXPLICITLY. Surfaces this wave does not own (the brief names DevicePane, EvidencePane,
 * StatusBar, CoverageBar and Fabric3D) are still censused: an inert citation there is found, attributed
 * to the component that WROTE the element (React's own owner record, `_debugOwner`, resolved to the
 * source file that declares that component — no class-name map), and held to a ratchet of known
 * classes below. A new class of inert citation anywhere fails; one in a file this wave owns fails
 * outright; a known one fixed by its owner simply drops out.
 */
import * as fs from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { describeGolden, isGoldenSample } from "../test-support/golden-sample";
import { fabric } from "../core/data";
import { EVIDENCE_TABS, decodeInvestigation, useInvestigation } from "../core/store";
import { counterexample, suggestedFlows, traceFlow } from "../forwarding/engine";
import { App } from "../app/App";
/* Preloaded while the file is collected, as composite-tabstop.test.tsx does: the stage's lazy chunk
   then resolves on its first turn in every case, so every case censuses the same frame. */
import "../fabric3d/Fabric3D";
import { citesIn } from "./cited-text";
import { Inspector, citeBearers, documentOf, inspectorCite, resolveCitation, setInspectorCite } from "./Inspector";
import { intentCatalog } from "./PathTrace";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* ══ who wrote an element: React's owner record, resolved to a source file ══════════════════════ */

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const walkTsx = (dir: string): string[] =>
  fs.readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (fs.statSync(p).isDirectory()) return walkTsx(p);
    return p.endsWith(".tsx") && !/\.test\.tsx$/.test(p) ? [p] : [];
  });

/** Component name -> the source files that declare it. Read from the source, not listed. */
const COMPONENT_FILES: ReadonlyMap<string, string[]> = (() => {
  const m = new Map<string, string[]>();
  for (const f of walkTsx(SRC)) {
    const rel = f.slice(SRC.length + 1).replace(/\\/g, "/");
    const src = fs.readFileSync(f, "utf8");
    for (const x of src.matchAll(/function\s+([A-Z]\w*)\s*[(<]|const\s+([A-Z]\w*)\s*=\s*(?:memo|forwardRef|lazy)?\s*\(/g)) {
      const name = x[1] ?? x[2]!;
      const list = m.get(name) ?? [];
      if (!list.includes(rel)) list.push(rel);
      m.set(name, list);
    }
  }
  return m;
})();

type Fiber = { type?: unknown; _debugOwner?: Fiber | null };
function fiberOf(n: Node): Fiber | null {
  for (const k of Object.keys(n)) if (k.startsWith("__reactFiber$")) return (n as unknown as Record<string, Fiber>)[k] ?? null;
  return null;
}
/** A function component's name; a `memo` / `forwardRef` wrapper is unwrapped to the function inside. */
const componentName = (t: unknown): string | null => {
  if (typeof t === "function") return (t as { displayName?: string }).displayName ?? (t as { name?: string }).name ?? null;
  if (typeof t === "object" && t !== null) {
    const inner = (t as { type?: unknown; render?: unknown }).type ?? (t as { render?: unknown }).render;
    return inner === undefined ? null : componentName(inner);
  }
  return null;
};

/**
 * Who wrote this node: the component that created its element, and the component that rendered THAT
 * one — so text a panel hands to a generic primitive (a `Chip`, an `IconButton`'s label) is attributed
 * to the panel as well as to the primitive. For a text node, the element that holds it.
 */
function authorOf(n: Node): { component: string; file: string } {
  for (let e: Node | null = n; e !== null; e = e.parentNode) {
    const f = fiberOf(e);
    if (f === null) continue;
    const names: string[] = [];
    for (let o: Fiber | null | undefined = f._debugOwner; o && names.length < 2; o = o._debugOwner) {
      const name = componentName(o.type);
      if (name !== null && !names.includes(name)) names.push(name);
    }
    if (names.length === 0) continue;
    return {
      component: names.join(" < "),
      file: names.map((x) => COMPONENT_FILES.get(x)?.join(" | ") ?? "unknown").join(" < "),
    };
  }
  return { component: "unknown", file: "unknown" };
}

/** The files held to the bar outright: an inert citation written by any of them fails, list or no list.
 *  The first three are the W7-B6 cluster's; the merged-tree gate after wave 7 fixed every DevicePane
 *  and EvidencePane class and added those files. */
const OWNED_FILES: readonly string[] = [
  "panels/PathTrace.tsx",
  "panels/cited-text.tsx",
  "panels/Inspector.tsx",
  "panels/DevicePane.tsx",
  "panels/EvidencePane.tsx",
];

/* ══ the census ═══════════════════════════════════════════════════════════════════════════════ */

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}
function unmountAll(): void {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
}

/** Until the document stops changing: two quiet turns in a row (at most 60 turns). */
async function settle(): Promise<void> {
  let quiet = 0;
  for (let turns = 0; quiet < 2 && turns < 60; turns += 1) {
    let changed = false;
    const mo = new MutationObserver(() => {
      changed = true;
    });
    mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
    mo.disconnect();
    quiet = changed ? 0 : quiet + 1;
  }
}

/** Answer the ladder's rem media queries for `width`, as composite-tabstop.test.tsx does. */
function setViewport(width: number): () => void {
  const real = window.matchMedia;
  const px = (rem: string): number => Number.parseFloat(rem) * 16;
  window.matchMedia = ((q: string) => {
    let matches = true;
    for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)rem\)/g)) {
      const bound = px(m[2] as string);
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

afterEach(() => {
  unmountAll();
  document.body.innerHTML = "";
  window.history.replaceState(null, "", "/");
  act(() => { useInvestigation.setState(useInvestigation.getInitialState(), true); });
});

/** What a reader can operate — the owner a citation needs, and what must not nest. */
const CONTROL =
  "button, a[href], summary, select, option, textarea, input, [role=button], [role=link], [role=menuitem], [role=option], [role=tab], [role=radio], [role=checkbox], [role=switch], [role=gridcell][tabindex], [role=treeitem]";
/** The containers whose content model forbids another control inside them. */
const NO_NESTING = "button, a[href], summary, [role=button], [role=link], [role=menuitem], [role=option], [role=tab], [role=radio], [role=checkbox], [role=switch]";
const READER_ATTRIBUTES = ["title", "aria-label", "aria-description", "placeholder", "alt", "aria-valuetext"] as const;

interface Occurrence {
  cite: string;
  /** The text node, or the element carrying the attribute. */
  node: Node;
  where: Element;
  owner: HTMLElement | null;
  how: string;
}

const hidden = (el: Element): boolean =>
  el.closest("[hidden], [aria-hidden='true'], [inert], script, style, template") !== null ||
  /* A screen-reader announcement: visually hidden AND live. It is the only non-visual form of what the
     panel just drew, and a control inside it would never be announced as one. */
  (el.closest("[aria-live]") !== null && el.closest(".visually-hidden") !== null);

/** Every citation the rendered document prints, one text run (or attribute) at a time. */
function occurrences(root: Element): Occurrence[] {
  const out: Occurrence[] = [];
  const visit = (el: Element): void => {
    if (hidden(el)) return;
    let run = "";
    let first: Node | null = null;
    const flush = (): void => {
      for (const c of citesIn(run)) out.push({ cite: c, node: first ?? el, where: el, owner: el.closest<HTMLElement>(CONTROL), how: `text "${run.replace(/\s+/g, " ").trim().slice(0, 90)}"` });
      run = "";
      first = null;
    };
    for (const n of el.childNodes) {
      if (n.nodeType === Node.TEXT_NODE) {
        first ??= n;
        run += n.nodeValue ?? "";
      } else if (n instanceof Element && n.tagName === "WBR") continue; /* the Cite primitive's break hints */
      else if (n instanceof Element) {
        flush();
        visit(n);
      }
    }
    flush();
    for (const a of READER_ATTRIBUTES) {
      const v = el.getAttribute(a);
      if (v) for (const c of citesIn(v)) out.push({ cite: c, node: el, where: el, owner: el.closest<HTMLElement>(CONTROL), how: `@${a} "${v.replace(/\s+/g, " ").slice(0, 90)}"` });
    }
  };
  visit(root);
  return out;
}

function pathOf(el: Element | null): string {
  const parts: string[] = [];
  for (let e = el; e && e !== document.body && parts.length < 3; e = e.parentElement)
    parts.push(`${e.tagName.toLowerCase()}${typeof e.className === "string" && e.className.trim() ? `.${e.className.trim().split(/\s+/)[0]}` : ""}`);
  return parts.join(" < ");
}

interface Finding {
  kind: "inert" | "dead-control" | "nested-control";
  cite: string;
  how: string;
  where: string;
  component: string;
  file: string;
  state: string;
}
/** The class a finding belongs to: who wrote it, what kind, and the element shape — never the cite. */
const classOf = (f: Finding): string => `${f.kind} :: ${f.component} (${f.file}) :: ${f.where}`;

/** Controls already proven, by citation and control shape: the same control code for the same record. */
const verified = new Map<string, boolean>();
/** Every record the Inspector has been censused at. */
const inspected = new Set<string>();
const sigOf = (o: HTMLElement, cite: string): string => `${cite}|${o.tagName}.${o.className}|${o.getAttribute("role") ?? ""}|${o.closest("[id]")?.id ?? ""}`;

const inspector = (): HTMLElement | null => document.getElementById("inspector");
/** The record the Inspector is on: the citation opened, and the model path shown for it. */
const onScreen = (): string[] => {
  const i = inspector();
  return i === null ? [] : [i.dataset.cite ?? "", i.dataset.modelPath ?? ""].filter(Boolean);
};

/** What a reader's selection is — the investigation a control that is not a citation would move. */
const investigation = (): string => {
  const s = useInvestigation.getState();
  return JSON.stringify([s.deviceId, s.linkId, s.findingId, s.hopIndex, s.flow, s.surface, s.evidenceTab, s.paletteOpen, s.query]);
};

const timing = { clicks: 0, ms: 0 };

/**
 * Activate every owner and record whether it pointed the Inspector at its citation.
 *
 * All activations run inside ONE `act`, so React renders once for the batch rather than once per
 * control (a render per click measured 65-245 ms, and the app prints over a thousand citations). The
 * observable is still the control's own effect, read synchronously after its handler ran: the
 * citation the Inspector was pointed at (`inspectorCite`), cleared before each activation. A control
 * that opens a record by moving the Inspector's OWN view (its bearer switch) is then checked once
 * more on the rendered panel's `data-model-path`. Returns whether any control failed — a control that
 * is not a citation control may have moved the investigation (the preset shape: a run button, whose
 * store write lands a frame later), so the caller then waits and compares before going on.
 */
/**
 * Activate a control the way its role is activated. A treeitem is activated by Enter (APG treeview:
 * Enter performs the item's default action; a click on a treeitem SELECTS it, which is not
 * activation). Every other control is clicked. By role, never by component or class.
 */
function activate(owner: HTMLElement): void {
  if (owner.getAttribute("role") === "treeitem") owner.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  else owner.click();
}

/** A control's accessible name: its `aria-label`, else its text. */
const accessibleName = (el: HTMLElement): string => (el.getAttribute("aria-label") ?? el.textContent ?? "").replace(/\s+/g, " ").trim();

/**
 * THE COPY-TOOL RULE. A control whose accessible name begins "Copy" and whose activation writes the
 * citation's text to the clipboard is a citation TOOL, not a dead citation: its name promises the
 * citation as text, and activating it hands the reader exactly that text to paste. It is recognised
 * by what it DOES — the clipboard is replaced by a recorder for the duration of the activations, and
 * the write is observed — and by the name that promises it, never by file, class or list. So a
 * control named "Copy …" that does anything else is still dead, and so is a control that copies
 * under a name that does not say it copies (the reader cannot know that is what it will do). Both
 * are planted and required to fail below ("the copy-tool rule").
 */
function withClipboardRecorder<T>(body: (written: string[]) => T): T {
  const had = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  const written: string[] = [];
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    /* A write that never settles: the recorder observes the call, and no status update lands later,
       outside the batch that caused it. */
    value: { writeText: (t: string) => (written.push(t), new Promise<void>(() => {})) },
  });
  try {
    return body(written);
  } finally {
    if (had) Object.defineProperty(navigator, "clipboard", had);
    else delete (navigator as unknown as Record<string, unknown>)["clipboard"];
  }
}

function verifyAll(pending: { owner: HTMLElement; cite: string; key: string }[]): boolean {
  if (pending.length === 0) return false;
  const t = performance.now();
  const results: boolean[] = [];
  withClipboardRecorder((written) => {
    act(() => {
      for (const { owner, cite } of pending) {
        setInspectorCite(null);
        written.length = 0;
        activate(owner);
        results.push(inspectorCite() === cite || (/^Copy\b/.test(accessibleName(owner)) && written.some((w) => w === cite)));
      }
    });
  });
  pending.forEach(({ owner, cite, key }, i) => {
    let ok = results[i] ?? false;
    if (!ok && owner.isConnected && inspector()?.contains(owner)) {
      act(() => activate(owner));
      ok = onScreen().includes(cite);
    }
    verified.set(key, ok);
  });
  timing.clicks += pending.length;
  timing.ms += performance.now() - t;
  return pending.some(({ key }) => verified.get(key) === false);
}

/**
 * Census the document as it stands. `restore` puts the state back when a control that is NOT a
 * citation control was activated and moved it (that control is then already a finding).
 */
async function census(state: string, restore: () => Promise<void>, root: Element = document.body): Promise<Finding[]> {
  const found: Finding[] = [];
  const note = (kind: Finding["kind"], o: { cite: string; how: string; node: Node }, at: Element, known?: { author: { component: string; file: string }; where: string }): void => {
    const a = known?.author ?? authorOf(o.node);
    found.push({ kind, cite: o.cite, how: o.how, where: known?.where ?? pathOf(at), component: a.component, file: a.file, state });
  };

  /* Nesting: a control inside a control. */
  for (const c of root.querySelectorAll<HTMLElement>(CONTROL)) {
    if (hidden(c)) continue;
    const outer = c.parentElement?.closest<HTMLElement>(NO_NESTING);
    if (outer && !hidden(outer)) note("nested-control", { cite: "", how: `${pathOf(c)} inside ${pathOf(outer)}`, node: c }, outer);
  }

  const self = new Set(onScreen());
  const insp = inspector();
  const occ = occurrences(root);
  const pending = new Map<string, { owner: HTMLElement; cite: string; key: string }>();
  for (const o of occ) {
    if (insp?.contains(o.where) && self.has(o.cite)) continue; /* the Inspector naming the record it shows */
    if (o.owner === null) note("inert", o, o.where);
    else {
      const key = sigOf(o.owner, o.cite);
      if (!verified.has(key) && !pending.has(key) && o.owner.isConnected) pending.set(key, { owner: o.owner, cite: o.cite, key });
    }
  }
  /* Read who wrote each owned citation BEFORE anything is activated: a control that closes its surface
     (a palette row) takes its elements out of the tree, and React clears a deleted node's owner
     record, so asked afterwards every such finding would read "unknown". */
  const before = new Map<Occurrence, { author: { component: string; file: string }; where: string }>();
  for (const o of occ) {
    if (o.owner === null) continue;
    const key = sigOf(o.owner, o.cite);
    if (pending.has(key) || verified.get(key) === false) before.set(o, { author: authorOf(o.node), where: pathOf(o.owner) });
  }
  const was = investigation();
  const anyDead = verifyAll([...pending.values()]);
  if (anyDead) await settle();
  const moved = anyDead && investigation() !== was;
  for (const o of occ) {
    if (o.owner === null || (insp?.contains(o.where) && self.has(o.cite))) continue;
    if (verified.get(sigOf(o.owner, o.cite)) === false) note("dead-control", o, o.owner, before.get(o));
  }
  if (moved) await restore();
  return found;
}

/* ══ the ratchet: inert classes on surfaces this wave does not own ════════════════════════════════
   Each entry is a CLASS (the component that wrote it, the kind, the element shape) — not a citation —
   found by this census on the tree this wave started from, with the file that owns the fix. A new
   class anywhere fails; a class in a file this wave owns fails regardless of this list; an entry
   whose class no longer occurs is reported by the last test so the list cannot rot silently. */
const KNOWN_ELSEWHERE: readonly string[] = [
  /* Empty. The last three classes were closed on the owner's decision (B6, after wave 7):
     - app/CommandPalette.tsx: a search hit (an option that SELECTS a device, finding or host) printed
       the record it matched as a "Source record" chip its activation did not open. The chip is gone;
       the row states why it matched in words, and an endpoint or interface hit lands on the host's
       Ports tab, where the record is a working citation (CommandPalette.test.tsx pins both).
     - panels/JsonView.tsx: a tree row whose key or value is a resolvable record path was a treeitem
       that only selected the node. Activating it (Enter, double-click) now opens that record through
       `openInspector` (Inspector.test.tsx pins it); the census activates a treeitem by Enter.
     - panels/JsonView.tsx: the row's "Copy path <path>" button copies its citation — a citation tool,
       recognised by what it does (the copy-tool rule in `verifyAll`), not a dead citation. */
];

/* ══ the states ═══════════════════════════════════════════════════════════════════════════════════ */

const seen: Finding[] = [];
const OUT = process.env["INERT_CITE_CENSUS_OUT"];

/**
 * A session: the app mounted once at one width, and moved from state to state the way a reader moves
 * it — through the store the URL grammar writes (`decodeInvestigation`). A state that needs a gesture
 * after its link (`then`) is loaded fresh, and so is a state whose census activated a control that
 * moved the investigation, before the census goes on.
 */
async function session(width: number, body: (go: (state: string, query: string, then?: () => Promise<void>) => Promise<void>) => Promise<void>): Promise<void> {
  const restoreViewport = setViewport(width);
  const stack = Error.stackTraceLimit;
  let mountedOnce = false;
  try {
    /* React's development build records an owner stack for every element it creates; no assertion
       here reads a stack, so capture is off while the frames are built (composite-tabstop.test.tsx
       measured a third of a case's cost in it). Restored before any assertion runs. */
    Error.stackTraceLimit = 0;
    const go = async (state: string, query: string, then?: () => Promise<void>): Promise<void> => {
      const load = async (fresh: boolean): Promise<void> => {
        if (fresh || !mountedOnce) {
          unmountAll();
          act(() => { useInvestigation.setState(useInvestigation.getInitialState(), true); });
          window.history.replaceState(null, "", query === "" ? "/" : `/?${query}`);
          mount(<App />);
          mountedOnce = true;
          await settle();
        } else {
          act(() => { useInvestigation.setState({ ...useInvestigation.getInitialState(), ...decodeInvestigation(query === "" ? "" : `?${query}`) }, true); });
          await settle();
        }
        if (then) await then();
      };
      const tl = performance.now();
      await load(then !== undefined);
      const loadMs = performance.now() - tl;
      Object.assign(timing, { clicks: 0, ms: 0 });
      const tc = performance.now();
      const found = await census(`${width}px ${state}`, () => load(true));
      if (OUT) fs.appendFileSync(OUT, `## ${state}: load ${loadMs.toFixed(0)} ms, census ${(performance.now() - tc).toFixed(0)} ms (${timing.clicks} activations ${timing.ms.toFixed(0)} ms)\n`);
      seen.push(...found);
      if (OUT) fs.appendFileSync(OUT, [`== ${width}px ${state}`, ...found.map((f) => `${classOf(f)} :: ${f.cite} :: ${f.how}`), ""].join("\n"));
    };
    await body(go);
  } finally {
    Error.stackTraceLimit = stack;
    restoreViewport();
  }
}

const flowParam = (f: { srcIp: string; dstIp: string; protocol: string; dstPort: number | null }): string =>
  encodeURIComponent(`${f.srcIp}>${f.dstIp}>${f.protocol}>${f.dstPort ?? ""}`);

const clickFirst = (sel: string, text?: RegExp) => async (): Promise<void> => {
  const el = [...document.querySelectorAll<HTMLElement>(sel)].find((e) => !hidden(e) && (text === undefined || text.test(e.textContent ?? "")));
  if (el === undefined) return;
  act(() => el.click());
  await settle();
};

const CASE_TIMEOUT = 300_000;

describe("every citation the app prints is a working citation control", () => {
  describe("the shell, at one width per ladder rung", () => {
    for (const width of [390, 768, 1100, 1440]) {
      it(`${width} px: every surface, the More popover, the queue's cross-layer corpus, the fabric list, the palette`, { timeout: CASE_TIMEOUT }, async () => {
        await session(width, async (go) => {
          for (const [state, q] of [
            ["idle", ""],
            ["path, no flow", "s=path"],
            ["findings", "s=findings"],
            ["evidence", "s=evidence"],
          ] as const)
            await go(state, q);
          await go("More popover", "s=path", clickFirst("button.hdr-more"));
          await go("cross-layer corpus", "s=findings", clickFirst('[role="tab"]', /Cross-layer/));
          await go("fabric list", "", clickFirst("button", /^Fabric list$/));
          await go("palette open", "", async () => {
            act(() => { useInvestigation.getState().setPaletteOpen(true); });
            await settle();
          });
        });
        expect(verified.size, "the census activated controls").toBeGreaterThan(0);
      });
    }
  });

  describe("the Path surface: every suggested flow, on every hop, with its counterexample", () => {
    for (const s of suggestedFlows()) {
      it(s.id, { timeout: CASE_TIMEOUT }, async () => {
        const t = traceFlow(s.flow);
        await session(1440, async (go) => {
          for (let hop = 0; hop < Math.max(1, t.hops.length); hop += 1) await go(`${s.id} hop ${hop}`, `s=path&flow=${flowParam(s.flow)}&hop=${hop}`);
          const ce = counterexample(t.flow, t);
          if (ce.found) await go(`${s.id} counterexample`, `s=path&flow=${flowParam(ce.flow)}`);
          /* The palette with the flow's source typed: the rows it offers restate this flow. */
          await go(`${s.id} palette rows`, "", async () => {
            act(() => { useInvestigation.getState().setPaletteOpen(true); });
            await settle();
            const input = document.querySelector<HTMLInputElement>(".palette__input");
            if (input !== null) {
              act(() => {
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, s.flow.srcIp);
                input.dispatchEvent(new Event("input", { bubbles: true }));
              });
              await settle();
            }
          });
        });
        expect(t.flow).toEqual(s.flow);
      });
    }
    it("a shared link whose flow is refused", { timeout: CASE_TIMEOUT }, async () => {
      await session(1440, async (go) => {
        await go("refused link", `s=path&flow=${encodeURIComponent("10.0.10.50>10.0.20.10>tcp>abc")}`);
      });
      expect(useInvestigation.getState().flow).toBeNull();
    });
    it("every intent the snapshot can construct, searched to its verdict", { timeout: CASE_TIMEOUT }, async () => {
      const catalog = intentCatalog();
      expect(catalog.length).toBeGreaterThan(0);
      let verdicts = 0;
      await session(1440, async (go) => {
        for (const intent of catalog) {
          await go(`intent ${intent.id}`, "s=path", async () => {
            await clickFirst('[role="tab"]', /Verify an intent/)();
            const select = document.querySelector<HTMLSelectElement>(".pt-intent select");
            if (select !== null) {
              act(() => {
                select.value = intent.id;
                select.dispatchEvent(new Event("change", { bubbles: true }));
              });
            }
            await clickFirst("button", /Search for a counterexample/)();
            await settle();
            if (document.querySelector(".claim--intent") !== null) verdicts += 1;
          });
        }
      });
      expect(verdicts, "every intent reached its verdict card").toBeGreaterThanOrEqual(catalog.length);
    });
  });

  describe("every device, on every evidence tab", () => {
    for (const d of fabric.devices) {
      it(d.id, { timeout: CASE_TIMEOUT }, async () => {
        await session(1440, async (go) => {
          for (const tab of EVIDENCE_TABS) await go(`${d.id} ${tab}`, `d=${encodeURIComponent(d.id)}&s=fabric&tab=${tab}`);
        });
        expect(EVIDENCE_TABS.length).toBeGreaterThan(0);
      });
    }
  });

  describe("every finding", () => {
    const CHUNK = 8;
    const ids = fabric.findings.map((f) => f.id);
    for (let i = 0; i < ids.length; i += CHUNK) {
      const part = ids.slice(i, i + CHUNK);
      it(`findings ${i + 1}-${i + part.length} of ${ids.length}`, { timeout: CASE_TIMEOUT }, async () => {
        await session(1440, async (go) => {
          for (const id of part) await go(`finding ${id}`, `f=${encodeURIComponent(id)}&s=findings`);
        });
        expect(part.length).toBeGreaterThan(0);
      });
    }
  });

  describe("every link", () => {
    const CHUNK = 15;
    const ids = fabric.links.map((l) => l.id);
    for (let i = 0; i < ids.length; i += CHUNK) {
      const part = ids.slice(i, i + CHUNK);
      it(`links ${i + 1}-${i + part.length} of ${ids.length}`, { timeout: CASE_TIMEOUT }, async () => {
        await session(1440, async (go) => {
          for (const id of part) await go(`link ${id}`, `l=${encodeURIComponent(id)}&s=fabric`);
        });
        expect(part.length).toBeGreaterThan(0);
      });
    }
  });

  describe("the Inspector, at one record of every shape it renders", () => {
    /* The Inspector is where every citation lands, so it is censused as a surface of its own, mounted
       alone (the component the shell docks) and re-pointed record to record.

       WHICH RECORDS. Not all of them: at one render per record the census measured 18-155 s per 150
       records on a loaded host, and the JSON view's tree multiplied that past ten minutes. What the Data
       view prints is decided by the resolution layer (model, model-and-source, carried by a record,
       unresolved), the compiled document, and the record's own field names and value types — every
       string value goes through the same `CitedText`, whatever it says. So one record is censused per
       distinct SHAPE of those, over every record the model cites and every record a control in the
       states above was proven to open; the Provenance and Coverage views once per resolution layer;
       the JSON view once per compiled document. The shapes are derived from the records, not listed,
       and their count is asserted, so a shape the data grows is censused without anyone adding it. */
    const typeOf = (v: unknown): string => (v === null ? "null" : Array.isArray(v) ? "array" : typeof v);
    const layerOf = (cite: string): string => {
      const r = resolveCitation(cite);
      return r.kind === "model" && (citeBearers().get(cite)?.length ?? 0) > 0 ? "model+source" : r.kind;
    };
    const shapeOf = (cite: string): string => {
      const r = resolveCitation(cite);
      const at = r.modelPath ?? cite;
      const rec = r.record;
      const fields =
        rec !== null && typeof rec === "object" && !Array.isArray(rec)
          ? Object.entries(rec as Record<string, unknown>)
              .map(([k, v]) => `${k}:${typeOf(v)}`)
              .sort()
              .join(",")
          : typeOf(rec);
      return `${layerOf(cite)}|${documentOf(at)}|${/^(?:[\w-]+\.json#)?([A-Za-z_][\w-]*)/.exec(at)?.[1] ?? at}|${r.bearers.length > 1 ? "switch" : "one"}|${fields}`;
    };

    it("every rendering shape of every record the model cites or a control opened", { timeout: CASE_TIMEOUT }, async () => {
      const opened = [...verified.entries()].filter(([, ok]) => ok).map(([k]) => k.slice(0, k.indexOf("|")));
      const universe = [...new Set([...citeBearers().keys(), ...opened])].sort();
      const byShape = new Map<string, string>();
      for (const cite of universe) if (!byShape.has(shapeOf(cite))) byShape.set(shapeOf(cite), cite);
      const layers = new Map<string, string>();
      const documents = new Map<string, string>();
      for (const cite of byShape.values()) {
        if (!layers.has(layerOf(cite))) layers.set(layerOf(cite), cite);
        const at = resolveCitation(cite).modelPath;
        if (at !== null && !documents.has(documentOf(at))) documents.set(documentOf(at), cite);
      }
      const stack = Error.stackTraceLimit;
      let rendered = 0;
      try {
        Error.stackTraceLimit = 0;
        const host = mount(<></>);
        const root = mounted[mounted.length - 1]!.root;
        const view = async (cite: string, tab: string): Promise<void> => {
          act(() => root.render(<Inspector key={cite} cite={cite} forceOpen />));
          const t = host.querySelector<HTMLElement>(`#inspector-tab-${tab}`);
          if (t !== null && tab !== "data") act(() => t.click());
          seen.push(...(await census(`inspector ${cite} (${tab})`, async () => {}, host)));
          inspected.add(cite);
          rendered += 1;
        };
        for (const cite of byShape.values()) await view(cite, "data");
        for (const cite of layers.values()) for (const tab of ["provenance", "coverage"]) await view(cite, tab);
        for (const cite of documents.values()) await view(cite, "json");
      } finally {
        Error.stackTraceLimit = stack;
      }
      if (OUT) fs.appendFileSync(OUT, `## inspector: ${universe.length} records, ${byShape.size} shapes, ${layers.size} layers, ${documents.size} documents\n`);
      /* Not vacuous on ANY dataset: every finding's own citation is among the records censused (the 500 floor below is
         the reference sample's size, which the 7-device engine golden does not reach — 224 records there). */
      const findingCites = new Set(fabric.findings.map((f) => f.cite));
      expect(findingCites.size, "precondition: the dataset has findings to cite").toBeGreaterThan(0);
      expect([...findingCites].filter((c) => !universe.includes(c)), "finding citations the census never reached").toEqual([]);
      if (isGoldenSample()) expect(universe.length, "the reference sample cites more than 500 records").toBeGreaterThan(500);
      expect(byShape.size, "the records fall into more than a handful of rendering shapes").toBeGreaterThan(10);
      expect([...layers.keys()].sort(), "every resolution layer the data holds is censused").toEqual(expect.arrayContaining(["bearer", "model+source"]));
      expect(rendered).toBe(byShape.size + layers.size * 2 + documents.size);
    });
  });

  describe("the copy-tool rule exempts what a control DOES, and nothing else", () => {
    /* Planted controls, censused exactly as the app's are. Each names the same resolvable record in
       its accessible name; only the one whose name says it copies AND whose activation writes that
       citation to the clipboard is a citation tool. The planted proofs are removed from `verified`
       afterwards, so they cannot stand in for the app's own controls in the verdict below. */
    it("a copy control that copies the citation passes; a 'Copy' name that does something else, a copy under another name, and a copy of other text are dead", { timeout: CASE_TIMEOUT }, async () => {
      const cite = [...citeBearers().keys()].sort()[0]!;
      expect(citesIn(`Copy path ${cite}`), "the planted name carries a citation the resolver recognises").toEqual([cite]);
      const before = new Set(verified.keys());
      let other = 0;
      const write = (t: string): void => void navigator.clipboard?.writeText?.(t);
      const host = mount(
        <>
          <div id="plant-copies" className="plant-copies">
            <button type="button" aria-label={`Copy path ${cite}`} onClick={() => write(cite)} />
          </div>
          <div id="plant-copy-named-does-other" className="plant-copy-named-does-other">
            <button type="button" aria-label={`Copy path ${cite}`} onClick={() => (other += 1)} />
          </div>
          <div id="plant-copies-unnamed" className="plant-copies-unnamed">
            <button type="button" aria-label={`Keep ${cite}`} onClick={() => write(cite)} />
          </div>
          <div id="plant-copies-other-text" className="plant-copies-other-text">
            <button type="button" aria-label={`Copy path ${cite}`} onClick={() => write("something else")} />
          </div>
        </>,
      );
      try {
        const found = await census("planted copy controls", async () => {}, host);
        expect(found.every((f) => f.kind === "dead-control" && f.cite === cite), "every finding is a dead control for the planted record").toBe(true);
        /* The one that copies its citation under a "Copy" name is absent; the other three are dead. */
        expect(found.map((f) => f.where).sort()).toEqual([
          "button < div.plant-copies-other-text < div",
          "button < div.plant-copies-unnamed < div",
          "button < div.plant-copy-named-does-other < div",
        ]);
        expect(other, "the Copy-named control that does something else was activated").toBeGreaterThan(0);
      } finally {
        for (const k of [...verified.keys()]) if (!before.has(k)) verified.delete(k);
      }
    });
  });

  describe("the verdict", () => {
    it("the census is not vacuous: it opened records", () => {
      expect([...verified.values()].filter(Boolean).length, "controls proven to open their record").toBeGreaterThan(500);
      expect(inspected.size, "the Inspector was censused at records of many shapes").toBeGreaterThan(10);
    });

    /* The refuter's three preset citations name records of the tracked sample by its own host and array
       positions ("acls.core1…"), so they are GOLDEN facts: on another dataset (the rename leg's "acls.rn-07…")
       they name nothing. Split out 2026-09-30 (phase 3.5 close) so the invariant half above runs on every leg. */
    describeGolden("the census clicked the refuter's preset citations", () => {
      it("each preset citation was among the controls proven to open their record", () => {
        for (const c of ["l3_forwarding[5]", "l3_forwarding[4]", "acls.core1.PROTECT_SERVERS[2]"]) expect([...verified.keys()].some((k) => k.startsWith(`${c}|`)), c).toBe(true);
      });
    });

    it("no file this wave owns prints an inert citation, a dead one, or a control inside a control", () => {
      /* Owned = the component that CREATED the element lives in a file this wave owns. A primitive
         rendering text one of these files handed it is a class of its own, and meets the ratchet below. */
      const mine = seen.filter((f) => OWNED_FILES.some((o) => (f.file.split(" < ")[0] ?? "").split(" | ").includes(o)));
      expect([...new Set(mine.map((f) => `${classOf(f)} :: e.g. ${f.cite} ${f.how} [${f.state}]`))]).toEqual([]);
    });

    it("no class of inert citation exists outside the known, scoped-out ones", () => {
      const byClass = new Map<string, Finding>();
      for (const f of seen) if (!KNOWN_ELSEWHERE.includes(classOf(f)) && !byClass.has(classOf(f))) byClass.set(classOf(f), f);
      expect([...byClass].map(([k, f]) => `${k} :: e.g. ${f.cite} ${f.how} [${f.state}]`)).toEqual([]);
    });

    it("every scoped-out class still occurs (a fixed one is taken off the list, not left to rot)", () => {
      const classes = new Set(seen.map(classOf));
      expect(KNOWN_ELSEWHERE.filter((k) => !classes.has(k))).toEqual([]);
    });
  });
});
