/**
 * CommandPalette.test.tsx — the keyboard model, the command registry and the palette.
 *
 * These tests exist for defects a visual review cannot see:
 *
 *   - a shortcut that fires while the user is typing (the app feels broken and the author, who
 *     never typed an `f` into the query bar, never sees it);
 *   - a sequence that swallows the key after it;
 *   - a modifier rendered as Cmd on a Windows machine;
 *   - a help sheet that has drifted from the bindings it documents;
 *   - a command that claims an action it cannot perform, or a palette row that renders a missing
 *     field as a blank instead of as "not observed";
 *   - per-keystroke work heavy enough to make typing stutter — measured here, not asserted.
 *
 * No testing-library: this project does not depend on one. React's own `act` over a real
 * `createRoot` in jsdom is enough, and it keeps the dependency surface honest.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import { rankedSearch } from "../core/query";
import { useInvestigation } from "../core/store";
import { CommandPalette } from "./CommandPalette";
import { ShortcutHelp } from "./ShortcutHelp";
import {
  allCommands,
  commandAvailability,
  grammarExamples,
  installAppCommands,
  parseFlowQuery,
  registerCommandTarget,
} from "./commands";
import {
  activeScope,
  formatShortcut,
  installKeyboardManager,
  isTextEntry,
  parseSpec,
  registerShortcuts,
  shortcutConflicts,
  shortcuts,
  clearPendingKeys,
  pendingKeys,
  setHelpOpen,
  type Shortcut,
} from "./keyboard";

/* Counts renders of the palette's rows (see "per-keystroke work" at the end of this file): the JSX
   runtime is wrapped, for this file only, so that every creation of a palette row's root element is
   counted. It delegates unchanged; nothing else is observed or altered. */
const renderProbe = vi.hoisted(() => ({ paletteRows: 0 }));
vi.mock("react/jsx-dev-runtime", async (importOriginal) => {
  const m = await importOriginal<typeof import("react/jsx-dev-runtime")>();
  const jsxDEV: typeof m.jsxDEV = (type, props, ...rest) => {
    if (type === "div" && (props as { className?: unknown } | null)?.className === "palette__row") renderProbe.paletteRows += 1;
    return m.jsxDEV(type, props, ...rest);
  };
  return { ...m, jsxDEV };
});
vi.mock("react/jsx-runtime", async (importOriginal) => {
  const m = await importOriginal<typeof import("react/jsx-runtime")>();
  const seen = (type: unknown, props: unknown): void => {
    if (type === "div" && (props as { className?: unknown } | null)?.className === "palette__row") renderProbe.paletteRows += 1;
  };
  const jsx: typeof m.jsx = (type, props, ...rest) => (seen(type, props), m.jsx(type, props, ...rest));
  const jsxs: typeof m.jsxs = (type, props, ...rest) => (seen(type, props), m.jsxs(type, props, ...rest));
  return { ...m, jsx, jsxs };
});

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* ── harness ─────────────────────────────────────────────────────────────── */

const mounted: { root: Root; container: HTMLElement }[] = [];
const teardown: (() => void)[] = [];

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

const press = (key: string, init: KeyboardEventInit = {}, target: EventTarget = document): void => {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
  });
};

/** The one key that reaches the manager on this platform for a `mod+` chord. */
const MOD: KeyboardEventInit = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
  ? { metaKey: true }
  : { ctrlKey: true };

beforeEach(() => {
  useInvestigation.getState().reset();
  useInvestigation.getState().setPaletteOpen(false);
  /* Module-level state outlives a mount: a help sheet left open by one test would put the next
     test's focus inside a modal, where global bindings correctly do not fire. */
  act(() => setHelpOpen(false));
  clearPendingKeys();
});

afterEach(() => {
  act(() => setHelpOpen(false));
  for (const t of teardown.splice(0)) t();
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  clearPendingKeys();
});

/* ══ spec parsing and platform display ═════════════════════════════════════ */

describe("shortcut specs", () => {
  it("parses chords, sequences and symbol keys", () => {
    expect(parseSpec("mod+k")).toEqual([
      { key: "k", mod: true, ctrl: false, meta: false, alt: false, shift: false },
    ]);
    expect(parseSpec("g f").map((c) => c.key)).toEqual(["g", "f"]);
    expect(parseSpec("?")[0]?.key).toBe("?");
    expect(parseSpec("mod+\\")[0]?.key).toBe("\\");
    expect(parseSpec("shift+v")[0]).toMatchObject({ key: "v", shift: true });
  });

  it("renders the platform's own modifier, not a hard-coded one", () => {
    const tokens = formatShortcut("mod+k").map((t) => t.text);
    const mac = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent);
    expect(tokens).toEqual(mac ? ["⌘", "K"] : ["Ctrl", "K"]);
    expect(formatShortcut("g f").map((t) => t.text)).toEqual(["G", "then", "F"]);
  });
});

/* ══ the text-entry guard — the defect that makes an app feel broken ═══════ */

describe("text-entry guard", () => {
  it("classifies the things a keystroke would be typed into", () => {
    const input = document.createElement("input");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    const div = document.createElement("div");
    div.setAttribute("role", "combobox");
    expect(isTextEntry(input)).toBe(true);
    expect(isTextEntry(document.createElement("textarea"))).toBe(true);
    expect(isTextEntry(div)).toBe(true);
    expect(isTextEntry(checkbox)).toBe(false);
    expect(isTextEntry(document.createElement("button"))).toBe(false);
  });

  it("does not fire a plain-key binding while focus is in a text field", () => {
    const fired: string[] = [];
    teardown.push(
      registerShortcuts([
        { id: "t.plain", keys: "f", scope: "global", label: "plain", group: "Test", run: () => fired.push("f") },
        { id: "t.mod", keys: "mod+k", scope: "global", label: "mod", group: "Test", allowInInput: true, run: () => fired.push("mod+k") },
        { id: "t.esc", keys: "escape", scope: "global", label: "esc", group: "Test", allowInInput: true, run: () => fired.push("escape") },
      ]),
    );
    teardown.push(installKeyboardManager());

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    press("f", {}, input);
    press("k", MOD, input);
    press("Escape", {}, input);

    expect(fired).toEqual(["mod+k", "escape"]);
  });

  it("refuses to honour allowInInput for an unmodified printable key, and reports it", () => {
    const fired: string[] = [];
    teardown.push(
      registerShortcuts([
        {
          id: "t.unsafe",
          keys: "f",
          scope: "global",
          label: "unsafe",
          group: "Test",
          allowInInput: true,
          run: () => fired.push("f"),
        },
      ]),
    );
    teardown.push(installKeyboardManager());

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    press("f", {}, input);
    expect(fired).toEqual([]);

    const conflict = shortcutConflicts().find((c) => c.ids.includes("t.unsafe"));
    expect(conflict?.kind).toBe("unsafe-in-input");
  });
});

/* ══ scope ═════════════════════════════════════════════════════════════════ */

describe("scopes", () => {
  it("reads the scope off the focused subtree, and gives a modal priority", () => {
    const grid = document.createElement("div");
    grid.setAttribute("data-kb-scope", "grid");
    const cell = document.createElement("button");
    grid.appendChild(cell);
    document.body.appendChild(grid);
    expect(activeScope(cell)).toBe("grid");

    const modal = document.createElement("div");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("data-kb-scope", "grid");
    const inner = document.createElement("button");
    modal.appendChild(inner);
    document.body.appendChild(modal);
    expect(activeScope(inner)).toBe("dialog");
  });

  it("keeps a grid binding out of the fabric, and both out of an open modal", () => {
    const fired: string[] = [];
    teardown.push(
      registerShortcuts([
        { id: "t.grid", keys: "x", scope: "grid", label: "grid", group: "Test", run: () => fired.push("grid") },
        { id: "t.global", keys: "y", scope: "global", label: "global", group: "Test", run: () => fired.push("global") },
      ]),
    );
    teardown.push(installKeyboardManager());

    const fabricPane = document.createElement("div");
    fabricPane.setAttribute("data-kb-scope", "fabric");
    const canvasStandIn = document.createElement("button");
    fabricPane.appendChild(canvasStandIn);
    document.body.appendChild(fabricPane);
    canvasStandIn.focus();
    press("x", {}, canvasStandIn);
    press("y", {}, canvasStandIn);
    expect(fired).toEqual(["global"]);

    fired.length = 0;
    const modal = document.createElement("div");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    const inner = document.createElement("button");
    modal.appendChild(inner);
    document.body.appendChild(modal);
    inner.focus();
    press("y", {}, inner);
    expect(fired).toEqual([]);
  });
});

/* ══ sequences ═════════════════════════════════════════════════════════════ */

describe("sequences", () => {
  const seqShortcuts = (fired: string[]): Shortcut[] => [
    { id: "t.gf", keys: "g f", scope: "global", label: "go fabric", group: "Test", run: () => fired.push("gf") },
    { id: "t.gq", keys: "g q", scope: "global", label: "go queue", group: "Test", run: () => fired.push("gq") },
    { id: "t.r", keys: "r", scope: "global", label: "reset", group: "Test", run: () => fired.push("r") },
  ];

  it("completes g then f, and shows the pending key in between", () => {
    const fired: string[] = [];
    teardown.push(registerShortcuts(seqShortcuts(fired)));
    teardown.push(installKeyboardManager());

    press("g");
    expect(pendingKeys()).toEqual(["G"]);
    expect(fired).toEqual([]);
    press("f");
    expect(fired).toEqual(["gf"]);
    expect(pendingKeys()).toEqual([]);
  });

  it("does not swallow the key that abandons a sequence", () => {
    const fired: string[] = [];
    teardown.push(registerShortcuts(seqShortcuts(fired)));
    teardown.push(installKeyboardManager());

    press("g");
    press("r");
    // `r` is a binding in its own right: dropping the half-typed sequence must not drop the key.
    expect(fired).toEqual(["r"]);
    expect(pendingKeys()).toEqual([]);
  });
});

/* ══ conflicts ═════════════════════════════════════════════════════════════ */

describe("conflict reporting", () => {
  it("names a duplicate and a sequence made unreachable by its own prefix", () => {
    teardown.push(
      registerShortcuts([
        { id: "t.a", keys: "z", scope: "global", label: "a", group: "Test", run: () => {} },
        { id: "t.b", keys: "z", scope: "grid", label: "b", group: "Test", run: () => {} },
        { id: "t.c", keys: "q", scope: "global", label: "c", group: "Test", run: () => {} },
        { id: "t.d", keys: "q e", scope: "global", label: "d", group: "Test", run: () => {} },
      ]),
    );
    const kinds = shortcutConflicts().map((c) => c.kind);
    expect(kinds).toContain("duplicate");
    expect(kinds).toContain("sequence-prefix");
  });

  it("the application's own bindings are conflict-free", () => {
    teardown.push(installAppCommands());
    expect(shortcutConflicts(shortcuts())).toEqual([]);
  });
});

/* ══ the command registry ══════════════════════════════════════════════════ */

describe("commands", () => {
  it("is derived from the compiled snapshot, not from a written-down list", () => {
    const ids = allCommands().map((c) => c.id);
    const severities = new Set(fabric.findings.map((f) => f.severity));
    for (const s of severities) expect(ids).toContain(`filter.severity.${s}`);
    // Info has zero findings in this snapshot, so no Info filter may be offered.
    if (!severities.has("Info")) expect(ids).not.toContain("filter.severity.Info");
  });

  it("states why a command that needs an absent surface cannot run, instead of hiding it", () => {
    const reset = allCommands().find((c) => c.id === "view.resetCamera");
    expect(reset).toBeDefined();
    const before = commandAvailability(reset!);
    expect(before.ok).toBe(false);
    expect(before.reason).toMatch(/not on screen/i);

    let ran = 0;
    teardown.push(registerCommandTarget("fabric.resetCamera", () => void ran++));
    expect(commandAvailability(reset!).ok).toBe(true);
    reset!.run();
    expect(ran).toBe(1);
  });

  it("finds a DOM control that published itself as the owner of a capability", () => {
    const btn = document.createElement("button");
    btn.setAttribute("data-atlas-command", "fabric.toggleLegend");
    let clicks = 0;
    btn.addEventListener("click", () => void clicks++);
    document.body.appendChild(btn);

    const legend = allCommands().find((c) => c.id === "view.legend");
    expect(commandAvailability(legend!).ok).toBe(true);
    legend!.run();
    expect(clicks).toBe(1);
  });

  it("runs a suggested flow into the shared investigation context", () => {
    const flowCommand = allCommands().find((c) => c.id.startsWith("path.flow."));
    expect(flowCommand, "the engine offered no traceable flow").toBeDefined();
    flowCommand!.run();
    const st = useInvestigation.getState();
    expect(st.flow).not.toBeNull();
    expect(st.trace).not.toBeNull();
    expect(st.surface).toBe("path");
    // A verdict is never shipped without its scope: the engine's own claim comes with it.
    expect(st.trace?.claim.length ?? 0).toBeGreaterThan(0);
  });
});

/* ══ grammar examples and flow parsing ═════════════════════════════════════ */

describe("grammar examples", () => {
  it("offers only queries this snapshot can answer", () => {
    const examples = grammarExamples();
    expect(examples.length).toBeGreaterThan(0);
    for (const ex of examples) {
      expect(ex.query.trim()).not.toBe("");
      expect(ex.detail.trim()).not.toBe("");
    }
    const sev = examples.find((e) => e.query.startsWith("severity:"));
    if (sev) {
      const name = sev.query.slice("severity:".length);
      expect(fabric.findings.some((f) => f.severity === name)).toBe(true);
    }
    const host = examples.find((e) => e.query.startsWith("host:"));
    if (host) {
      const name = host.query.slice("host:".length);
      expect(fabric.devices.some((d) => d.host === name || d.id === name)).toBe(true);
    }
  });

  it("is stable between runs, so a capture is reproducible", () => {
    expect(grammarExamples()).toEqual(grammarExamples());
  });
});

describe("flow-shaped queries", () => {
  it("recognises the shapes a network engineer types", () => {
    expect(parseFlowQuery("10.0.10.50 -> 10.0.30.10:443")?.flow).toMatchObject({
      srcIp: "10.0.10.50",
      dstIp: "10.0.30.10",
      dstPort: 443,
      protocol: "tcp",
    });
    expect(parseFlowQuery("from 10.0.10.50 to 10.0.30.10")?.flow.protocol).toBe("ip");
    expect(parseFlowQuery("10.0.10.50 -> 10.0.30.10:53 udp")?.flow.protocol).toBe("udp");
  });

  it("states every value the grammar supplied rather than the user", () => {
    const withPort = parseFlowQuery("10.0.10.50 -> 10.0.30.10:443");
    expect(withPort?.assumptions.join(" ")).toMatch(/TCP/);
    const explicit = parseFlowQuery("10.0.10.50 -> 10.0.30.10:443 tcp");
    expect(explicit?.assumptions.some((a) => /No protocol given/.test(a))).toBe(false);
  });

  it("rejects things that only look like a flow", () => {
    expect(parseFlowQuery("core1 -> core2")).toBeNull();
    expect(parseFlowQuery("10.0.10.999 -> 10.0.30.10")).toBeNull();
    expect(parseFlowQuery("10.0.10.50 -> 10.0.30.10:99999")).toBeNull();
    expect(parseFlowQuery("severity:Critical")).toBeNull();
  });
});

/* ══ the palette ═══════════════════════════════════════════════════════════ */

const openPaletteUI = (): HTMLElement => {
  const container = mount(<CommandPalette />);
  act(() => useInvestigation.getState().setPaletteOpen(true));
  return container;
};

const paletteInput = (): HTMLInputElement => {
  const el = document.querySelector<HTMLInputElement>(".palette__input");
  if (!el) throw new Error("palette input not rendered");
  return el;
};

const type = (value: string): void => {
  const input = paletteInput();
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

const options = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('[role="option"]')];

describe("command palette", () => {
  it("opens on the platform's own palette chord, from anywhere", () => {
    mount(<CommandPalette />);
    expect(useInvestigation.getState().paletteOpen).toBe(false);
    press("k", MOD);
    expect(useInvestigation.getState().paletteOpen).toBe(true);
  });

  it("implements the APG combobox contract", () => {
    openPaletteUI();
    const input = paletteInput();
    expect(input.getAttribute("role")).toBe("combobox");
    expect(input.getAttribute("aria-controls")).toBeTruthy();
    expect(input.getAttribute("aria-label")).toBeTruthy();

    const listbox = document.getElementById(input.getAttribute("aria-controls") ?? "");
    expect(listbox?.getAttribute("role")).toBe("listbox");
    expect(input.getAttribute("aria-expanded")).toBe("true");

    const activeId = input.getAttribute("aria-activedescendant");
    expect(activeId).toBeTruthy();
    expect(document.getElementById(activeId ?? "")?.getAttribute("aria-selected")).toBe("true");

    const first = options()[0];
    press("ArrowDown", {}, input);
    const second = document.getElementById(input.getAttribute("aria-activedescendant") ?? "");
    expect(second).not.toBe(first);
    expect(second?.getAttribute("aria-selected")).toBe("true");
    // Exactly one option is selected at a time.
    expect(options().filter((o) => o.getAttribute("aria-selected") === "true")).toHaveLength(1);
  });

  it("teaches the grammar from this snapshot when it is empty", () => {
    openPaletteUI();
    const text = document.querySelector(".palette__results")?.textContent ?? "";
    for (const ex of grammarExamples()) expect(text).toContain(ex.query);
  });

  it("offers a trace for a flow-shaped query, with its assumptions stated", () => {
    openPaletteUI();
    type("10.0.10.50 -> 10.0.30.10:443");
    act(() => {});
    const row = options()[0];
    expect(row?.textContent).toContain("Trace");
    expect(row?.textContent).toMatch(/TCP/);
  });

  it("searches commands and the fabric at once, and names the field that matched", () => {
    openPaletteUI();
    const host = fabric.devices.find((d) => d.collected)?.host ?? "core1";
    type(host);
    act(() => {});
    const text = document.querySelector(".palette__results")?.textContent ?? "";
    expect(text).toContain(host);
    expect(text).toMatch(/matched/);

    type("critical");
    act(() => {});
    const both = document.querySelector(".palette__results")?.textContent ?? "";
    expect(both).toMatch(/Filter: severity Critical/);
  });

  it("runs a key:value query as a filter instead of dead-ending on it", () => {
    /* The empty state teaches `severity:Critical`. If the palette could only substring-search,
       following its own lesson would return nothing — the worst possible answer to a query the
       product just recommended. */
    openPaletteUI();
    type("severity:Critical");
    act(() => {});
    const row = options()[0];
    expect(row?.textContent).toContain("Apply filter");
    expect(row?.textContent).toMatch(/\d+ of \d+ findings match/);

    press("Enter", {}, paletteInput());
    expect(useInvestigation.getState().query).toBe("severity:Critical");
    expect(useInvestigation.getState().surface).toBe("findings");
  });

  it("refuses a clause the data model cannot answer, and says why", () => {
    openPaletteUI();
    type("nosuchkey:whatever");
    act(() => {});
    const row = options().find((o) => o.textContent?.includes("Apply filter"));
    expect(row?.getAttribute("aria-disabled")).toBe("true");
    expect(row?.textContent).toMatch(/not a filter this data model answers/);

    press("Enter", {}, paletteInput());
    // Fails closed: the investigation is untouched rather than filtered by a clause nothing can
    // evaluate, which would show an empty queue that reads as "nothing is wrong".
    expect(useInvestigation.getState().query).toBe("");
    expect(useInvestigation.getState().paletteOpen).toBe(true);
  });

  it("searches on a clause's own value, so host:core1 still surfaces core1", () => {
    const host = fabric.devices.find((d) => d.collected)?.host ?? "core1";
    openPaletteUI();
    type(`host:${host}`);
    act(() => {});
    const text = document.querySelector(".palette__results")?.textContent ?? "";
    expect(text).toContain("Apply filter");
    expect(text).toContain(host);
    expect(text).toContain("matching");
  });

  it("renders an unobserved field as not observed, never as a blank", () => {
    const blind = fabric.devices.find((d) => d.role === null || d.band === null);
    expect(blind, "this snapshot has no device with an unobserved role or band").toBeDefined();
    openPaletteUI();
    type(blind!.host);
    act(() => {});
    const row = options().find((o) => o.textContent?.includes(blind!.host));
    expect(row?.textContent).toMatch(/not observed/);
  });

  it("returns focus to the invoking element when it closes", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();

    mount(<CommandPalette />);
    act(() => useInvestigation.getState().setPaletteOpen(true, trigger));
    expect(document.activeElement).toBe(paletteInput());

    press("Escape", {}, paletteInput());
    expect(useInvestigation.getState().paletteOpen).toBe(false);
    expect(document.activeElement).toBe(trigger);
  });

  it("lands on the stage, never <body>, when the invoker can no longer take focus (D3)", async () => {
    const stage = document.createElement("div");
    stage.id = "stage";
    stage.tabIndex = -1;
    const trigger = document.createElement("button");
    document.body.append(stage, trigger);
    trigger.focus();

    mount(<CommandPalette />);
    act(() => useInvestigation.getState().setPaletteOpen(true, trigger));
    trigger.disabled = true;
    press("Escape", {}, paletteInput());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(stage);
  });

  it("runs the active row on Enter", () => {
    openPaletteUI();
    const device = fabric.devices.find((d) => d.collected);
    type(device?.host ?? "core1");
    act(() => {});
    const first = options()[0];
    expect(first).toBeDefined();
    press("Enter", {}, paletteInput());
    expect(useInvestigation.getState().paletteOpen).toBe(false);
  });
});

/* ══ the help sheet ════════════════════════════════════════════════════════ */

describe("shortcut help", () => {
  it("is generated from the registry, not written down", () => {
    teardown.push(installAppCommands());
    mount(<ShortcutHelp />);
    press("?");
    const sheet = document.querySelector(".kb-help");
    expect(sheet).not.toBeNull();
    const text = sheet?.textContent ?? "";
    for (const s of shortcuts()) expect(text).toContain(s.label);
  });

  it("returns focus to the menu's trigger when the item that opened it has unmounted (D3)", async () => {
    mount(<ShortcutHelp />);
    const trigger = document.createElement("button");
    trigger.setAttribute("aria-controls", "help-origin-menu");
    const menu = document.createElement("div");
    menu.id = "help-origin-menu";
    const item = document.createElement("button");
    menu.appendChild(item);
    document.body.append(trigger, menu);
    item.focus();
    act(() => setHelpOpen(true));
    expect(document.querySelector(".kb-help")).not.toBeNull();
    menu.remove();
    act(() => setHelpOpen(false));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(trigger);
  });

  it("shows a half-typed sequence on screen", () => {
    teardown.push(installAppCommands());
    mount(<ShortcutHelp />);
    press("g");
    expect(document.querySelector(".kb-pending")?.textContent).toMatch(/waiting for the next key/);
    press("f");
    expect(document.querySelector(".kb-pending")).toBeNull();
  });
});

/* ══ per-keystroke work, counted (not timed) ═══════════════════════════════
   Not an INP figure and never reported as one: jsdom has no compositor and no real paint. What the
   unit suite CAN establish is the structure the input handler relies on — the search index built
   once and reused, and a cursor move that re-renders the two rows it changes — and it establishes
   that by COUNTING the work, not by timing it.

   WHY NOT TIME IT (acceptance report F2, 2026-09-23, overturned PASS -> UNPROVEN). This block used
   to assert wall-clock bounds: the median search time under 200 ms, and the worst of nine palette
   opens and of twenty cursor moves under 400 ms. Under a loaded full-suite run the open read
   "expected 533.2958999999992 to be less than 400" with nothing regressed — vitest runs files in
   parallel, so a wall-clock bound in the unit suite measures what the host was doing, and its red
   cannot be told from a regression. Raising the bound would only move the flake. The two regressions
   the bound said it caught — an index rebuilt on open, and every row re-rendered on a cursor move —
   are counted directly below, and a count does not depend on the host. The time budget itself
   belongs to the E harnesses (review/measure-inp.mjs, review/audit-e5-sweep.mjs), which measure the
   built application on a gated host. The timings are still printed, as a report, never asserted.

   HOW IT COUNTS. Dataset reads: every array in the compiled dataset (`fabric`, to three levels) is
   wrapped for the duration of the probe in a Proxy that counts element reads; building the search
   index reads every device, finding and record, so a rebuild cannot hide. Row renders: the JSX
   runtime is wrapped for this file (vi.mock at the top) and counts creations of the palette row's
   own root element (`div.palette__row`), which happens once per PaletteRow render and at no other
   time. LIMIT, stated: a search that stays over the built index but grows super-linearly inside it
   reads no dataset element and is not caught here; that is a time property, and it is the E
   harnesses'. */

/** Element reads of the compiled dataset's collections while `fn` runs. */
function datasetReads(fn: () => void): number {
  let reads = 0;
  const restore: (() => void)[] = [];
  const count = <T extends object>(arr: T): T =>
    new Proxy(arr, {
      get(target, prop, receiver) {
        if (typeof prop === "string" && /^\d+$/.test(prop)) reads += 1;
        return Reflect.get(target, prop, receiver) as unknown;
      },
    });
  const walk = (holder: Record<string, unknown>, depth: number): void => {
    for (const [k, v] of Object.entries(holder)) {
      if (Array.isArray(v)) {
        holder[k] = count(v);
        restore.push(() => {
          holder[k] = v;
        });
      } else if (depth > 1 && v !== null && typeof v === "object") walk(v as Record<string, unknown>, depth - 1);
    }
  };
  walk(fabric as unknown as Record<string, unknown>, 3);
  expect(restore.length, "the probe wrapped the dataset's collections").toBeGreaterThan(5);
  try {
    fn();
  } finally {
    for (const r of restore.reverse()) r();
  }
  return reads;
}

describe("per-keystroke work", () => {
  it("the probe sees a full pass over the dataset (its red branch, executed)", () => {
    const reads = datasetReads(() => {
      for (const f of fabric.findings) void f.id;
      for (const d of fabric.devices) void d.id;
    });
    expect(reads).toBe(fabric.findings.length + fabric.devices.length);
  });

  it("typing reuses the search index built once: a keystroke reads no dataset record", () => {
    // Warm the index exactly as the real app does before the first keystroke lands.
    rankedSearch("warm");
    const term = fabric.devices[0]?.host ?? "core1";
    const prefixes = Array.from({ length: term.length }, (_, i) => term.slice(0, i + 1));
    let hits = 0;
    const t0 = performance.now();
    const reads = datasetReads(() => {
      for (const p of prefixes) hits += rankedSearch(p, { limit: 40 }).hits.length;
    });
    const ms = performance.now() - t0;
    // Reported, not asserted (see above): a figure for a reader, from a host of unknown load.
    console.log(`[laboratory, jsdom, not gated] ${prefixes.length} keystrokes of rankedSearch: ${ms.toFixed(2)} ms total, ${reads} dataset reads`);
    expect(hits, "precondition: the typed term finds something, so the search did real work").toBeGreaterThan(0);
    expect(reads, "a keystroke rebuilt (part of) the search index from the dataset").toBe(0);
  });

  it("opens over an index that already exists, rather than building one", () => {
    rankedSearch("warm");
    mount(<CommandPalette />);
    // The first open pays for the command list and the row builders; every later one is the
    // steady state a user actually experiences.
    act(() => useInvestigation.getState().setPaletteOpen(true));
    act(() => useInvestigation.getState().setPaletteOpen(false));
    let reads = 0;
    for (let i = 0; i < 3; i++) {
      reads += datasetReads(() => act(() => useInvestigation.getState().setPaletteOpen(true)));
      expect(paletteInput(), "precondition: the palette opened").toBeTruthy();
      act(() => useInvestigation.getState().setPaletteOpen(false));
    }
    expect(reads, "opening the palette read the dataset — an index built on open").toBe(0);
  });

  it("a cursor move re-renders the two rows it changes, not every row", () => {
    rankedSearch("warm");
    openPaletteUI();
    type("core");
    const rows = options().length;
    expect(rows, "precondition: enough rows that re-rendering all of them is distinguishable from two").toBeGreaterThanOrEqual(6);
    const input = paletteInput();
    const before = input.getAttribute("aria-activedescendant");
    renderProbe.paletteRows = 0;
    press("ArrowDown", {}, input);
    expect(input.getAttribute("aria-activedescendant"), "precondition: the cursor moved").not.toBe(before);
    const rendered = renderProbe.paletteRows;
    console.log(`[jsdom] one cursor move rendered ${rendered} of ${rows} palette rows`);
    expect(rendered, `one cursor move rendered ${rendered} of ${rows} rows`).toBeLessThanOrEqual(2);
    expect(rendered, "the probe saw the two rows that did change (a count of 0 would prove nothing)").toBeGreaterThan(0);
  });
});
