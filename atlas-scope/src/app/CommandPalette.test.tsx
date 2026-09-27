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
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { actAsync } from "../test-support/act-turns";
import ts from "typescript";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import { rankedSearch } from "../core/query";
import { useInvestigation } from "../core/store";
import type { SceneStatsEx } from "../fabric3d/scene";
import { publishSceneStats, releaseSceneStats } from "../fabric3d/telemetry";
import { citesIn } from "../panels/cited-text";
import { Dialog } from "../ui/primitives";
import { CommandPalette, FIELD_WORDS, MatchReason } from "./CommandPalette";
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

/* Records every `startTransition` call made by the app's source (React's own scheduling does not go
   through this export), with the palette pre-warm state at the moment of the call. It delegates
   unchanged; nothing else is observed or altered. See "the pre-warm renders in a transition". */
const transitionProbe = vi.hoisted(() => ({ calls: [] as (string | undefined)[] }));
vi.mock("react", async (importOriginal) => {
  const m = await importOriginal<typeof import("react")>();
  const startTransition: typeof m.startTransition = (cb) => {
    transitionProbe.calls.push(typeof document === "undefined" ? undefined : document.documentElement.dataset.paletteWarm);
    return m.startTransition(cb);
  };
  return { ...m, startTransition };
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

  it("prints no citation inside a command's row: activating the row runs the command, not the record (B6)", () => {
    /* A palette row is one role=option whose activation RUNS its command. A suggested flow's detail
       used to carry its rationale's citations (acls.core1.PROTECT_SERVERS[2], l3_forwarding[4], [5]),
       so the record was named where choosing it re-ran the flow and opened nothing — the Path preset
       shape, in the palette (inert-cite-census). An option may not hold a control, so the citation
       stays out of the option; the trace the flow opens cites every hop. Every command, not the flows. */
    const commands = allCommands();
    expect(commands.some((c) => c.id.startsWith("path.flow."))).toBe(true);
    const cited = commands.flatMap((c) => {
      const text = `${c.title} ${typeof c.detail === "string" ? c.detail : ""}`;
      const cites = citesIn(text);
      return cites.length === 0 ? [] : [`${c.id}: ${cites.join(", ")}`];
    });
    expect(cited).toEqual([]);
    // the verdict the row states is kept: only the citations left the text
    for (const c of commands.filter((x) => x.id.startsWith("path.flow."))) {
      expect(c.detail, c.id).toContain(c.verdict!.sentence.replace(/\s*\([^()]*\)/g, "").slice(0, 20));
    }
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
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(stage);
  });

  it("prints no citation in a search hit it cannot open, says in words why it matched, and lands where the record is (B6)", () => {
    /* A search hit is one role=option whose activation SELECTS something (a device, a finding, a
       host). It used to print the record it matched as a "Source record" chip — `endpoint_identity[3]`
       on a row that selects access10 — so the reader was shown a citation that choosing the row did
       not open (inert-cite-census). An option may not hold a control, so the citation leaves the row
       and the reason stays, in words; the record is one step away on the host's pane. */
    const ep = fabric.endpoints.find((e) => e.ip !== null && e.host !== null);
    const intf = Object.entries(fabric.interfaces).flatMap(([host, rows]) => rows.map((r) => ({ host, r })))[0];
    const device = fabric.devices.find((d) => d.collected);
    expect(ep && intf && device, "the snapshot holds an endpoint with an address, an interface and a collected device").toBeTruthy();
    openPaletteUI();
    const READER = ["title", "aria-label", "aria-description", "placeholder", "alt"];
    for (const term of [ep!.ip!, `${intf!.host}:${intf!.r.port}`, device!.host, fabric.findings[0]!.id]) {
      type(term);
      act(() => {});
      const hits = options().filter((o) => o.closest(".palette__group") !== null && o.querySelector(".palette__matched") !== null);
      expect(hits.length, `"${term}" returns search hits`).toBeGreaterThan(0);
      for (const o of hits) {
        const said = [o.textContent ?? "", ...[o, ...o.querySelectorAll("*")].flatMap((e) => READER.map((a) => e.getAttribute(a) ?? ""))].join(" ");
        expect(citesIn(said), `a hit for "${term}" names no record it does not open: ${o.textContent}`).toEqual([]);
        expect(o.querySelector(".palette__cite")).toBeNull();
        // the reason is a sentence, not a field token: "matched this endpoint's IP address"
        expect(o.querySelector(".palette__matched")?.textContent ?? "").toMatch(/^matched this [\w -]+'s \w/);
      }
    }
    type(ep!.ip!);
    act(() => {});
    // The first endpoint hit for that address: its reason in words, and the host it selects.
    const row = options().find((o) => /, Ports tab/.test(o.textContent ?? "") && /endpoint/.test(o.querySelector(".palette__matched")?.textContent ?? ""))!;
    expect(row, "an endpoint hit is on screen").toBeDefined();
    expect(row.querySelector(".palette__matched")?.textContent).toBe("matched this endpoint's IP address");
    const selects = /select (\S+), Ports tab/.exec(row.textContent ?? "")?.[1];
    expect(fabric.endpoints.some((e) => e.host === selects && e.ip === ep!.ip), "the row selects a host holding an endpoint record with that address").toBe(true);

    // Choosing the endpoint row selects its host AND opens the tab that holds the record's citation.
    act(() => row.click());
    const st = useInvestigation.getState();
    expect(st.deviceId).toBe(selects);
    expect(st.evidenceTab).toBe("ports");
    expect(st.paletteOpen).toBe(false);
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

/* ══ the match reason breaks like prose, and never names a field it has no words for (C2) ═══ */

describe("the match reason (C2, repair wave 8)", () => {
  /* 34bd435 set `overflow-wrap: anywhere` on `.palette__matched` so that a field name with no entry in
     FIELD_WORDS — printed raw, `hit.field` is typed `string` — could not overrun the 45 % side column.
     That licence is inherited by every token in the sentence and is how "(num_power_supplie / s)" was
     split (primitives.css, "wrapping"); `node review/capture.mjs text` failed C2 on it. The licence is
     gone. What replaces it: (1) FIELD_WORDS is TOTAL over the fields `rankedSearch` can emit, proved from
     query.ts's own index construction, not from a list; (2) a field it cannot name is an IDENTIFIER, in
     a <code> element that breaks only at a separator, never between two letters. */
  const QUERY_TS = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "..", "core", "query.ts"), "utf8");

  /** Every field name query.ts indexes: the first argument of every `iv(…)` / `ivList(…)` call. A call
   *  INSIDE `iv`/`ivList`'s own definition that forwards that function's own parameter is the
   *  indexer passing its caller's field through (ivList → iv), and every such caller is scanned. */
  const INDEXERS = new Set(["iv", "ivList"]);
  function indexedFields(code: string): { fields: Set<string>; unprovable: string[] } {
    const sf = ts.createSourceFile("query.ts", code, ts.ScriptTarget.Latest, true);
    const fields = new Set<string>();
    const unprovable: string[] = [];
    const visit = (n: ts.Node, forwarded: ReadonlySet<string>): void => {
      if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && INDEXERS.has(n.name.text) && n.initializer !== undefined && ts.isArrowFunction(n.initializer)) {
        const params = new Set(n.initializer.parameters.flatMap((p) => (ts.isIdentifier(p.name) ? [p.name.text] : [])));
        ts.forEachChild(n, (c) => visit(c, params));
        return;
      }
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && INDEXERS.has(n.expression.text)) {
        const a = n.arguments[0];
        if (a !== undefined && (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a))) fields.add(a.text);
        else if (!(a !== undefined && ts.isIdentifier(a) && forwarded.has(a.text)))
          unprovable.push(`query.ts:${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1} ${n.getText(sf).slice(0, 60)}`);
      }
      ts.forEachChild(n, (c) => visit(c, forwarded));
    };
    visit(sf, new Set());
    return { fields, unprovable };
  }

  it("FIELD_WORDS has words for every field query.ts indexes (read from its iv/ivList calls)", () => {
    const { fields, unprovable } = indexedFields(QUERY_TS);
    expect(unprovable, "an indexed field whose name is not a literal cannot be proved to have words").toEqual([]);
    expect(fields.size, "the scan found no indexed field at all").toBeGreaterThan(20);
    expect([...fields].filter((f) => FIELD_WORDS[f] === undefined), "fields the palette would print raw").toEqual([]);
    // Nothing constructs an indexed value except `iv`: the only `field:` written in query.ts's search
    // index is the one `iv` itself returns and the winner copied from it.
    const sf = ts.createSourceFile("query.ts", QUERY_TS, ts.ScriptTarget.Latest, true);
    const writers: string[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isPropertyAssignment(n) && n.name.getText(sf) === "field") writers.push(n.initializer.getText(sf));
      if (ts.isShorthandPropertyAssignment(n) && n.name.text === "field") writers.push("field");
      ts.forEachChild(n, visit);
    };
    visit(sf);
    expect([...new Set(writers)].sort()).toEqual(["field", "v.field", "winner.field"].sort());
  });

  it("the scan fails a field FIELD_WORDS does not know, and a field name it cannot read (positive control)", () => {
    const planted = indexedFields('add({ values: ivs(iv("zzNotAField", x), iv(name, y)), ...ivList("hosts", h) });');
    expect([...planted.fields].filter((f) => FIELD_WORDS[f] === undefined)).toEqual(["zzNotAField"]);
    expect(planted.unprovable.length).toBe(1);
  });

  it("every field a real search over the snapshot emits has words", () => {
    const seen = new Set<string>();
    for (const term of [..."abcdefghijklmnopqrstuvwxyz0123456789.:-/"]) {
      for (const h of rankedSearch(term, { limit: 1_000_000 }).hits) seen.add(h.field);
    }
    expect(seen.size).toBeGreaterThan(10);
    expect([...seen].filter((f) => FIELD_WORDS[f] === undefined)).toEqual([]);
  });

  it("renders a field it has no words for as an identifier that breaks only at a separator", () => {
    const hit = { ...rankedSearch(fabric.devices[0]!.host).hits[0]!, field: "zz_unmapped.field-name" };
    const c = mount(<MatchReason hit={hit} />);
    const code = c.querySelector(".palette__matched code");
    expect(code, "an unknown field is printed as prose").not.toBeNull();
    expect(code!.textContent).toBe("zz_unmapped.field-name");
    // a <wbr> after every separator, and nowhere else
    const runs = [...code!.childNodes].map((n) => (n.nodeName === "WBR" ? "|" : (n.textContent ?? ""))).join("");
    expect(runs).toBe("zz_|unmapped.|field-|name");
    // a known field stays words, in no <code>
    const known = mount(<MatchReason hit={{ ...hit, field: "ip" }} />);
    expect(known.querySelector(".palette__matched")?.textContent).toMatch(/'s IP address$/);
    expect(known.querySelector(".palette__matched code")).toBeNull();
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
    await actAsync(async () => {
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
function datasetReads(fn: () => void, dataset: object = fabric): number {
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
  walk(dataset as unknown as Record<string, unknown>, 3);
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

/* ══ the cold first open: the pre-warm (acceptance E2/E3, 2026-09-26) ══════
   THE DEFECT. The first Ctrl+K after load, in a fresh browser at 1280x800, measured worst-interaction
   p95 320 ms (E2) with a 51-83 ms `#document.onkeydown` long task (E3). Two costs, measured apart:
   the main thread built and styled the palette's DOM for the first time inside the keydown (render,
   then the forced style/layout of `focus()`), and the GPU compiled the Skia programs for the
   palette's paint operations the first time they were rasterised. Every later open was warm.

   THE REPAIR (owner decision, cluster E2E3). Once the scene has converged, in idle time, the
   palette's own frame is mounted once, invisibly but REALLY rasterised (opacity 0.001 — measured: at
   opacity 0 the compositor never rasterises it and the GPU half remains), for a few presented frames,
   then PARKED (`visibility: hidden`) until the first real open, which turns those same nodes into the
   dialog — so the first Ctrl+K creates no DOM (the first repair removed the frame, and the first open
   still built and laid out the subtree inside the keydown). What that frame must never do is what
   these tests pin: it is hidden from assistive technology and inert, it takes no focus, it traps no
   key, it makes nothing outside itself inert, it announces nothing, it collides with no id, it adds
   no render work to other interactions, and a real Ctrl+K always wins.

   jsdom rasterises nothing, so the timing claim is the browser harness's (review/measure-inp.mjs,
   `J5-first-open-palette`); these tests pin the structure that claim depends on. Idle callbacks and
   animation frames are driven by hand, so the order of events is the test's, not the host's. */

describe("the palette pre-warm (E2/E3: the first Ctrl+K after load)", () => {
  type IdleCb = () => void;
  const w = window as unknown as {
    requestIdleCallback?: (cb: IdleCb, o?: { timeout: number }) => number;
    cancelIdleCallback?: (id: number) => void;
  };
  const saved = {
    ric: w.requestIdleCallback,
    cic: w.cancelIdleCallback,
    raf: window.requestAnimationFrame,
    caf: window.cancelAnimationFrame,
  };
  let idle = new Map<number, IdleCb>();
  let frames = new Map<number, FrameRequestCallback>();
  let nextId = 1;

  beforeEach(() => {
    idle = new Map();
    frames = new Map();
    w.requestIdleCallback = (cb) => {
      const id = nextId++;
      idle.set(id, cb);
      return id;
    };
    w.cancelIdleCallback = (id) => void idle.delete(id);
    window.requestAnimationFrame = (cb) => {
      const id = nextId++;
      frames.set(id, cb);
      return id;
    };
    window.cancelAnimationFrame = (id) => void frames.delete(id);
    delete document.documentElement.dataset.paletteWarm;
    releaseSceneStats();
  });

  afterEach(() => {
    w.requestIdleCallback = saved.ric;
    w.cancelIdleCallback = saved.cic;
    window.requestAnimationFrame = saved.raf;
    window.cancelAnimationFrame = saved.caf;
    releaseSceneStats();
    delete document.documentElement.dataset.paletteWarm;
  });

  /** Run every queued idle callback, including those the callbacks queue, one slice per act. */
  const flushIdle = (): number => {
    let ran = 0;
    for (let guard = 0; idle.size > 0 && guard < 50; guard++) {
      const [id, cb] = idle.entries().next().value as [number, IdleCb];
      idle.delete(id);
      act(() => cb());
      ran += 1;
    }
    return ran;
  };
  /** Present `n` frames, then let the zero-delay timers the frames scheduled run. */
  const presentFrames = async (n: number): Promise<void> => {
    for (let i = 0; i < n; i++) {
      const due = [...frames.values()];
      frames.clear();
      act(() => {
        for (const cb of due) cb(0);
      });
      await actAsync(async () => {
        await new Promise((r) => setTimeout(r, 5));
      });
    }
  };
  /** Let the drawn phase's minimum hold (WARM_MIN_HOLD_MS, 250 ms) run out, in real time. */
  const holdElapsed = async (): Promise<void> => {
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 320));
    });
  };
  const stats = (converged: boolean): SceneStatsEx =>
    ({
      fps: 60,
      frameMs: 16,
      drawCalls: 10,
      triangles: 100,
      programs: 4,
      quality: "high",
      converged,
      qualityAuto: true,
      warmupStage: null,
      programsLinked: 4,
      programsTotal: 4,
      frameRateBelowBar: false,
    }) as unknown as SceneStatsEx;
  const converge = (): void => act(() => publishSceneStats(stats(true)));

  const warmFrame = (): HTMLElement | null => document.querySelector<HTMLElement>(".ui-dialog[data-dialog-prewarm]");
  const warmNodes = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>("[data-dialog-prewarm]")];
  const duplicateIds = (): string[] => {
    const seen = new Map<string, number>();
    for (const el of document.querySelectorAll("[id]")) seen.set(el.id, (seen.get(el.id) ?? 0) + 1);
    return [...seen].filter(([, n]) => n > 1).map(([id]) => id);
  };
  const outsideButton = (): HTMLButtonElement => {
    const b = document.createElement("button");
    b.textContent = "page control";
    document.body.appendChild(b);
    b.focus();
    return b;
  };

  it("waits for the scene to converge, then mounts the palette's own frame once in idle time", () => {
    mount(<CommandPalette />);
    flushIdle();
    expect(warmFrame(), "no pre-warm before the scene has converged").toBeNull();
    expect(document.documentElement.dataset.paletteWarm).toBe("waiting");
    converge();
    expect(warmFrame(), "the pre-warm waits for an idle slice, it is not mounted by the convergence itself").toBeNull();
    flushIdle();
    expect(warmFrame(), "the pre-warm mounted once the page was idle").not.toBeNull();
    expect(document.documentElement.dataset.paletteWarm).toBe("mounted");
    expect(useInvestigation.getState().paletteOpen, "the pre-warm is not an open").toBe(false);
  });

  it("draws the real empty state, so the first open's paint operations are the ones rasterised", () => {
    mount(<CommandPalette />);
    converge();
    flushIdle();
    const frame = warmFrame();
    expect(frame, "precondition: the pre-warm mounted").not.toBeNull();
    expect(frame!.classList.contains("palette"), "the palette's own frame, not a stand-in").toBe(true);
    expect(frame!.getAttribute("data-width")).toBe("lg");
    expect(frame!.querySelectorAll(".palette__row").length, "the empty state's rows").toBeGreaterThan(0);
    const text = frame!.querySelector(".palette__results")?.textContent ?? "";
    for (const ex of grammarExamples()) expect(text).toContain(ex.query);
    expect(frame!.querySelector(".palette__input"), "the search row").not.toBeNull();
    expect(frame!.querySelector(".palette__foot"), "the footer").not.toBeNull();
    expect(frame!.querySelector('.palette__row[data-active="true"]'), "the active row's fill, as the first open draws it").not.toBeNull();
  });

  it("is hidden from assistive technology and inert, and is rasterised (opacity above zero), never visible", () => {
    mount(<CommandPalette />);
    converge();
    flushIdle();
    const nodes = warmNodes();
    expect(nodes.length, "the scrim and the panel both carry the pre-warm marking").toBe(2);
    for (const el of nodes) {
      expect(el.getAttribute("data-dialog-prewarm"), `${el.className}: being rasterised`).toBe("raster");
      expect(el.style.visibility, `${el.className}: drawn (not yet parked), so it is rasterised`).toBe("");
      expect(el.getAttribute("aria-hidden"), `${el.className}: aria-hidden`).toBe("true");
      expect(el.hasAttribute("inert"), `${el.className}: inert`).toBe(true);
      const opacity = Number.parseFloat(el.style.opacity);
      /* NOT zero: an opacity-0 layer is never rasterised, which leaves the GPU half of the cold cost
         (measured: first-open p95 152 ms at opacity 0 against 64 ms at 0.001). */
      expect(opacity, `${el.className}: opacity is non-zero, so the frame is really rasterised`).toBeGreaterThan(0);
      expect(opacity, `${el.className}: opacity is below one 8-bit step, so nothing is seen`).toBeLessThan(1 / 255);
      expect(el.style.pointerEvents, `${el.className}: takes no pointer`).toBe("none");
    }
  });

  it("exposes no dialog, combobox, listbox, option or live region while pre-warming, rasterising or parked", async () => {
    mount(<CommandPalette />);
    converge();
    flushIdle();
    for (const phase of ["raster", "parked"]) {
      if (phase === "parked") {
        await presentFrames(4);
        await holdElapsed();
      }
      const frame = warmFrame();
      expect(frame, `precondition: the pre-warm frame is in the document (${phase})`).not.toBeNull();
      expect(frame!.getAttribute("data-dialog-prewarm"), "precondition: the phase under test").toBe(phase);
      expect(document.querySelectorAll('[role="dialog"], [aria-modal]').length, `${phase}: no dialog role anywhere`).toBe(0);
      expect(frame!.querySelectorAll('[role="combobox"], [role="listbox"], [role="option"], [role="group"]').length, phase).toBe(0);
      expect(frame!.querySelectorAll('[aria-live], [role="status"], [role="alert"], [role="log"]').length, `${phase}: no live region: the pre-warm announces nothing`).toBe(0);
      expect(duplicateIds(), `${phase}: no duplicate id`).toEqual([]);
    }
  });

  it("takes no focus, traps no key and makes nothing outside itself inert", () => {
    const outside = outsideButton();
    mount(<CommandPalette />);
    converge();
    flushIdle();
    expect(warmFrame(), "precondition: the pre-warm mounted").not.toBeNull();
    expect(document.activeElement, "focus stayed where the user left it").toBe(outside);
    const inert = [...document.querySelectorAll("[inert]")].filter((el) => !el.hasAttribute("data-dialog-prewarm"));
    expect(inert.map((el) => el.tagName), "inertOutside was not run for a pre-warm").toEqual([]);
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    act(() => void document.dispatchEvent(tab));
    expect(tab.defaultPrevented, "no Tab trap while pre-warming").toBe(false);
    const esc = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => void outside.dispatchEvent(esc));
    expect(warmFrame(), "Escape is not the pre-warm's to take").not.toBeNull();
  });

  it("parks after it has been presented: paints nothing, stays hidden and inert, and is never re-warmed", async () => {
    const outside = outsideButton();
    mount(<CommandPalette />);
    converge();
    flushIdle();
    const drawn = warmFrame();
    expect(drawn, "precondition: the pre-warm mounted").not.toBeNull();
    await presentFrames(1);
    expect(warmFrame()?.getAttribute("data-dialog-prewarm"), "held for more than one presented frame, so it is rasterised before it parks").toBe("raster");
    await presentFrames(3);
    expect(warmFrame()?.getAttribute("data-dialog-prewarm"), "and for its minimum time, not frames alone (the GPU compile outlasts three quick frames)").toBe("raster");
    expect(document.documentElement.dataset.paletteWarm).toBe("mounted");
    await holdElapsed();
    expect(document.documentElement.dataset.paletteWarm).toBe("done");
    const nodes = warmNodes();
    expect(nodes.length, "parked, not removed: the scrim and the panel are still in the document").toBe(2);
    expect(warmFrame(), "the SAME panel, parked in place").toBe(drawn);
    for (const el of nodes) {
      expect(el.getAttribute("data-dialog-prewarm"), el.className).toBe("parked");
      expect(el.style.visibility, `${el.className}: parked paints nothing`).toBe("hidden");
      expect(el.getAttribute("aria-hidden"), `${el.className}: aria-hidden`).toBe("true");
      expect(el.hasAttribute("inert"), `${el.className}: inert`).toBe(true);
      expect(el.style.pointerEvents, `${el.className}: takes no pointer`).toBe("none");
    }
    expect(document.activeElement).toBe(outside);
    /* One-shot: a later convergence (the scene settles again after every camera move) re-warms nothing. */
    act(() => publishSceneStats(stats(false)));
    act(() => publishSceneStats(stats(true)));
    expect(flushIdle(), "nothing was scheduled").toBe(0);
    await presentFrames(2);
    expect(warmFrame()?.getAttribute("data-dialog-prewarm"), "still parked, never drawn again").toBe("parked");
  });

  it("parks on a bounded timer when no frame is ever presented (an occluded window)", async () => {
    mount(<CommandPalette />);
    converge();
    flushIdle();
    expect(warmFrame(), "precondition: the pre-warm mounted").not.toBeNull();
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 1100));
    });
    expect(warmFrame()?.getAttribute("data-dialog-prewarm"), "a drawn layer must not outlive its purpose: it is parked").toBe("parked");
    expect(warmFrame()?.style.visibility).toBe("hidden");
    expect(document.documentElement.dataset.paletteWarm, "and it says it was never presented").toBe("unpresented");
  });

  it("a parked frame adds no render work to other interactions: its rows do not follow the command owners", async () => {
    mount(<CommandPalette />);
    converge();
    flushIdle();
    await presentFrames(4);
    await holdElapsed();
    expect(warmFrame()?.getAttribute("data-dialog-prewarm"), "precondition: parked").toBe("parked");
    const rows = warmFrame()!.querySelectorAll(".palette__row").length;
    expect(rows, "precondition: the parked frame holds rows").toBeGreaterThan(0);
    /* A surface mounting (it registers a command owner) re-renders the palette component. */
    renderProbe.paletteRows = 0;
    act(() => void teardown.push(registerCommandTarget("fabric.resetCamera", () => {})));
    expect(renderProbe.paletteRows, `a surface mount re-rendered ${renderProbe.paletteRows} of the parked frame's ${rows} rows`).toBe(0);
    /* The probe can see it (its red branch, executed): the same change while OPEN does re-render them. */
    press("k", MOD);
    expect(useInvestigation.getState().paletteOpen, "precondition: opened").toBe(true);
    renderProbe.paletteRows = 0;
    act(() => void teardown.push(registerCommandTarget("fabric.toggleLegend", () => {})));
    expect(renderProbe.paletteRows, "an open palette follows its owners").toBeGreaterThan(0);
  });

  it("waits no longer than its ceiling for a scene that never converges", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      mount(<CommandPalette />);
      act(() => void vi.advanceTimersByTime(9_900));
      expect(document.documentElement.dataset.paletteWarm, "before the ceiling it waits for convergence").toBe("waiting");
      act(() => void vi.advanceTimersByTime(200));
      expect(document.documentElement.dataset.paletteWarm, "a scene that never converges does not leave the palette cold").toBe("scheduled");
    } finally {
      vi.useRealTimers();
    }
  });

  it("the pre-warm renders in a transition, so a keystroke is never queued behind it", () => {
    mount(<CommandPalette />);
    converge();
    transitionProbe.calls.length = 0;
    flushIdle();
    expect(warmFrame(), "precondition: the pre-warm mounted").not.toBeNull();
    /* What this pins: the update that mounts the frame is issued through `startTransition` (a probe
       over React's export — the only call site, CommandPalette's final idle step — records it). That
       React yields a transition render to a discrete update is React's contract, not re-proven here. */
    expect(transitionProbe.calls, "the frame was mounted by a transition issued from the scheduled idle step").toEqual(["scheduled"]);
  });

  it("neither the pre-warm's render nor the first open traces the grammar examples: the idle slices already did", async () => {
    /* Fresh modules: the grammar examples and the command list are memoised at module scope, so any
       earlier test in this file would have computed them already and the count below would pass
       without the idle slices. React itself is not re-instantiated (a dependency, not a source module). */
    vi.resetModules();
    const fresh = {
      data: await import("../core/data"),
      store: await import("../core/store"),
      telemetry: await import("../fabric3d/telemetry"),
      palette: await import("./CommandPalette"),
    };
    expect(fresh.data.fabric, "precondition: a fresh dataset instance, so these memos are cold").not.toBe(fabric);
    mount(<fresh.palette.CommandPalette />);
    act(() => fresh.telemetry.publishSceneStats(stats(true)));
    let mountingSliceReads: number | null = null;
    let idleReads = 0;
    for (let guard = 0; idle.size > 0 && guard < 50; guard++) {
      const [id, cb] = idle.entries().next().value as [number, IdleCb];
      idle.delete(id);
      const before = warmFrame();
      const reads = datasetReads(() => act(() => cb()), fresh.data.fabric);
      if (before === null && warmFrame() !== null) mountingSliceReads = reads;
      else idleReads += reads;
    }
    expect(idleReads, "precondition: the idle slices did the dataset work (a probe that saw nothing proves nothing)").toBeGreaterThan(0);
    expect(mountingSliceReads, "precondition: the pre-warm mounted in one of the slices").not.toBeNull();
    expect(mountingSliceReads, "the slice that renders the pre-warm frame read the dataset").toBe(0);
    await presentFrames(4);
    await holdElapsed();
    const openReads = datasetReads(() => act(() => fresh.store.useInvestigation.getState().setPaletteOpen(true)), fresh.data.fabric);
    expect(document.querySelector(".palette__input")?.getAttribute("role"), "precondition: the first open happened").toBe("combobox");
    expect(openReads, "the first open read the dataset").toBe(0);
    act(() => fresh.store.useInvestigation.getState().setPaletteOpen(false));
    act(() => fresh.telemetry.releaseSceneStats());
  });

  it("a real Ctrl+K before the idle slice cancels the pre-warm; the open is the ordinary dialog", () => {
    mount(<CommandPalette />);
    converge();
    press("k", MOD);
    expect(useInvestigation.getState().paletteOpen).toBe(true);
    flushIdle();
    expect(warmNodes(), "no hidden copy beside the real palette").toEqual([]);
    expect(document.querySelectorAll(".ui-dialog")).toHaveLength(1);
    expect(document.querySelector(".ui-dialog")?.getAttribute("role")).toBe("dialog");
    expect(document.documentElement.dataset.paletteWarm).toBe("superseded");
  });

  it("a real Ctrl+K while the pre-warm is mounted becomes the real dialog: exposed, visible, focused", async () => {
    mount(<CommandPalette />);
    converge();
    flushIdle();
    const drawn = warmFrame();
    expect(drawn, "precondition: the pre-warm mounted").not.toBeNull();
    const drawnInput = drawn!.querySelector(".palette__input");
    press("k", MOD);
    expect(warmNodes(), "no pre-warm marking survives the open").toEqual([]);
    const dialogs = document.querySelectorAll<HTMLElement>(".ui-dialog");
    expect(dialogs).toHaveLength(1);
    const panel = dialogs[0]!;
    expect(panel, "UPDATED in place: the pre-warm's own panel node became the dialog (not a remount)").toBe(drawn);
    expect(paletteInput(), "and its own search box").toBe(drawnInput);
    expect(panel.getAttribute("role")).toBe("dialog");
    expect(panel.getAttribute("aria-modal")).toBe("true");
    expect(panel.hasAttribute("aria-hidden")).toBe(false);
    expect(panel.hasAttribute("inert")).toBe(false);
    expect(panel.style.opacity, "fully visible").toBe("");
    const scrim = document.querySelector<HTMLElement>(".ui-dialog__scrim")!;
    expect(scrim.hasAttribute("inert") || scrim.hasAttribute("aria-hidden") || scrim.style.opacity !== "").toBe(false);
    expect(document.activeElement, "focus is in the search box").toBe(paletteInput());
    expect(paletteInput().getAttribute("role")).toBe("combobox");
    expect(panel.querySelectorAll('[role="status"]').length, "the palette's live region is back").toBe(1);
    expect(duplicateIds()).toEqual([]);
    expect(document.documentElement.dataset.paletteWarm).toBe("superseded");
    await presentFrames(4);
    expect(useInvestigation.getState().paletteOpen, "the pre-warm's own teardown does not close a real open").toBe(true);
    expect(document.querySelectorAll('.ui-dialog[role="dialog"]')).toHaveLength(1);
  });

  it("the first Ctrl+K after parking flips the parked nodes into the dialog; after it closes, nothing is left", async () => {
    const outside = outsideButton();
    mount(<CommandPalette />);
    converge();
    flushIdle();
    await presentFrames(4);
    await holdElapsed();
    const parked = warmFrame();
    expect(parked?.getAttribute("data-dialog-prewarm"), "precondition: parked").toBe("parked");
    const parkedInput = parked!.querySelector(".palette__input");
    const parkedRows = parked!.querySelectorAll(".palette__row").length;
    press("k", MOD);
    const panel = document.querySelector<HTMLElement>(".ui-dialog");
    expect(panel, "the first open creates no panel: it is the parked one").toBe(parked);
    expect(paletteInput(), "the same search box").toBe(parkedInput);
    expect(panel!.querySelectorAll(".palette__row").length, "the same rows it drew while parked").toBe(parkedRows);
    expect(warmNodes(), "no pre-warm marking survives the open").toEqual([]);
    expect(panel!.getAttribute("role")).toBe("dialog");
    expect(panel!.getAttribute("aria-modal")).toBe("true");
    expect(panel!.hasAttribute("aria-hidden") || panel!.hasAttribute("inert")).toBe(false);
    expect(panel!.style.visibility, "visible").toBe("");
    expect(panel!.style.opacity, "fully opaque").toBe("");
    const scrim = document.querySelector<HTMLElement>(".ui-dialog__scrim")!;
    expect(scrim.hasAttribute("inert") || scrim.hasAttribute("aria-hidden") || scrim.style.visibility !== "" || scrim.style.opacity !== "").toBe(false);
    expect(document.activeElement, "focus is in the search box").toBe(parkedInput);
    expect(paletteInput().getAttribute("role")).toBe("combobox");
    expect(panel!.querySelectorAll('[role="option"]').length, "its rows are options now").toBe(parkedRows);
    expect(panel!.querySelectorAll('[role="status"]').length, "the palette's live region is there").toBe(1);
    expect(duplicateIds()).toEqual([]);
    expect(document.documentElement.dataset.paletteWarm, "a parked frame is not superseded: it WAS this open").toBe("done");
    press("Escape", {}, paletteInput());
    expect(useInvestigation.getState().paletteOpen).toBe(false);
    expect(document.querySelector(".ui-dialog, .ui-dialog__scrim"), "closed, the palette renders nothing again — parking ended at the first open").toBeNull();
    expect(document.activeElement, "focus went back").toBe(outside);
    press("k", MOD);
    expect(document.querySelectorAll('.ui-dialog[role="dialog"]'), "a later open is the ordinary one").toHaveLength(1);
    expect(warmNodes()).toEqual([]);
  });

  it("Dialog: a pre-warm renders the frame only — no focus, no key handling, no inert page", () => {
    const outside = outsideButton();
    const onClose = vi.fn();
    mount(
      <Dialog open={false} prewarm="raster" onClose={onClose} title="Probe" footer={<button type="button">foot</button>}>
        <button type="button">inside</button>
      </Dialog>,
    );
    const frame = warmFrame();
    expect(frame, "the frame rendered").not.toBeNull();
    expect(frame!.textContent).toContain("inside");
    expect(document.activeElement).toBe(outside);
    press("Escape");
    expect(onClose).not.toHaveBeenCalled();
    act(() => {
      document.querySelector<HTMLElement>(".ui-dialog__scrim")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(onClose, "the scrim of a pre-warm closes nothing").not.toHaveBeenCalled();
    expect([...document.querySelectorAll("[inert]")].every((el) => el.hasAttribute("data-dialog-prewarm"))).toBe(true);
  });

  it("Dialog: a parked pre-warm paints nothing and is the same nodes when it opens", () => {
    const outside = outsideButton();
    const onClose = vi.fn();
    const Probe = ({ open, prewarm }: { open: boolean; prewarm: "raster" | "parked" | false }): ReactNode => (
      <Dialog open={open} prewarm={prewarm} onClose={onClose} title="Probe">
        <button type="button">inside</button>
      </Dialog>
    );
    const container = mount(<Probe open={false} prewarm="raster" />);
    const drawn = warmFrame();
    expect(drawn?.style.visibility, "rasterising: drawn").toBe("");
    const root = mounted.find((m) => m.container === container)!.root;
    act(() => root.render(<Probe open={false} prewarm="parked" />));
    expect(warmFrame(), "parking keeps the node").toBe(drawn);
    for (const el of warmNodes()) {
      expect(el.style.visibility, el.className).toBe("hidden");
      expect(el.getAttribute("aria-hidden"), el.className).toBe("true");
      expect(el.hasAttribute("inert"), el.className).toBe(true);
    }
    expect(document.activeElement).toBe(outside);
    act(() => root.render(<Probe open prewarm="parked" />));
    const panel = document.querySelector<HTMLElement>('.ui-dialog[role="dialog"]');
    expect(panel, "open: the parked node, exposed").toBe(drawn);
    expect(panel!.style.visibility).toBe("");
    expect(panel!.contains(document.activeElement), "focus moved into the dialog").toBe(true);
  });

  it("Dialog: closed and not pre-warming still renders nothing", () => {
    mount(
      <Dialog open={false} onClose={() => {}} title="Probe">
        x
      </Dialog>,
    );
    expect(document.querySelector(".ui-dialog, .ui-dialog__scrim")).toBeNull();
  });
});
