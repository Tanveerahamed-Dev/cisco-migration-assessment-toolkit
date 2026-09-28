/**
 * primitives.test.tsx — the accessibility and honesty behaviour of the component vocabulary.
 *
 * These tests exist because the defects they catch are invisible to a visual review: a dialog
 * that looks modal but lets Tab escape behind it, a tab strip that looks like tabs but ignores
 * arrow keys, a tooltip that only a mouse can reach, and — the one that matters most here — an
 * absence renderer that quietly produces an empty node and turns "we never collected this" into
 * a blank cell that reads as zero.
 *
 * No testing-library: this project does not depend on one. React's own `act` plus a real
 * `createRoot` over jsdom is enough, and it keeps the dependency surface honest.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  Band,
  Button,
  Cite,
  Dialog,
  Disclosure,
  IconButton,
  Meter,
  NotObserved,
  Popover,
  Sparkline,
  SeverityBadge,
  StateDot,
  TabPanel,
  Tabs,
  Toolbar,
  Tooltip,
  inertOutside,
  isObserved,
  orNotObserved,
} from "./primitives";
import { IconCopy } from "./icons";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

interface Mounted {
  container: HTMLElement;
  render: (ui: ReactNode) => void;
}

const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(ui: ReactNode): Mounted {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return { container, render: (next) => act(() => root.render(next)) };
}

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
});

const key = (target: EventTarget, k: string, init: KeyboardEventInit = {}): void => {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, ...init }));
  });
};

const click = (el: Element): void => {
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
};

/** A real focus() call, not a synthesised focusin: React binds onFocus to focusin, and jsdom
 *  emits focusin from focus(). Dispatching one by hand as well delivers the event TWICE, which is
 *  how this helper originally made the handler-passthrough test read as a component defect. */
const focus = (el: HTMLElement): void => {
  act(() => el.focus());
};

/* ══ absence — the highest-priority correctness rule in the project ═════════ */

describe("NotObserved / orNotObserved", () => {
  it("renders explicit words, never an empty node", () => {
    const { container } = mount(<NotObserved what="CRC errors" />);
    const el = container.querySelector(".ui-notobs");
    expect(el).not.toBeNull();
    expect(el?.textContent ?? "").toContain("not observed");
    expect((el?.textContent ?? "").trim().length).toBeGreaterThan(0);
    // The glyph is the non-colour channel and must be present even in the default form.
    expect(el?.querySelector("svg")).not.toBeNull();
  });

  it("separates the words from the visible reason in the accessible text, not only by layout", () => {
    // The reason sits in its own box, so it LOOKS separated; but the text a screen reader or a copy
    // reads was "not observedno RIB was collected" — two sentences fused into one word.
    const { container } = mount(<NotObserved what="next hop" why="no RIB was collected on this device" />);
    const text = container.querySelector(".ui-notobs")?.textContent ?? "";
    expect(text).toContain("not observed — no RIB was collected on this device");
    expect(text).not.toMatch(/not observedno/);
  });

  it("keeps the words in the accessible name when the visible form is compact", () => {
    const { container } = mount(<NotObserved what="uptime" compact />);
    expect(container.textContent).toContain("not observed");
    // The dashed hatched frame is what carries it visually in a dense cell.
    expect(container.querySelector(".ui-notobs--compact")).not.toBeNull();
  });

  it("orNotObserved(null) never yields an empty string", () => {
    const { container } = mount(<span>{orNotObserved(null)}</span>);
    const text = container.textContent ?? "";
    expect(text.trim()).not.toBe("");
    expect(text).toContain("not observed");
  });

  it("treats undefined, empty string, whitespace and NaN as absence, not as a value", () => {
    for (const absent of [undefined, "", "   ", Number.NaN]) {
      const { container } = mount(<span>{orNotObserved(absent as string | number | undefined)}</span>);
      expect(container.textContent ?? "").toContain("not observed");
    }
  });

  it("parses the engine's own [NOT OBSERVED] marker and keeps its reason verbatim", () => {
    // This exact string shape appears in the compiled snapshot (L3Interface.trackingUnobserved).
    const raw = "[NOT OBSERVED] - no 'show track' evidence; object tracking NOT assessed";
    const { container } = mount(<span>{orNotObserved(raw)}</span>);
    const text = container.textContent ?? "";
    expect(text).toContain("not observed");
    expect(text).toContain("object tracking NOT assessed");
    // The machine marker itself must not reach the reader.
    expect(text).not.toContain("[NOT OBSERVED]");
  });

  it("renders a real value through the formatter and does not reach the absence path", () => {
    const { container } = mount(<span>{orNotObserved(0, (n) => `${n} errors`)}</span>);
    expect(container.textContent).toBe("0 errors");
    // Zero is evidence. It must NOT be swallowed as absence.
    expect(container.querySelector(".ui-notobs")).toBeNull();
  });

  it("isObserved separates a collected zero from an absent measurement", () => {
    expect(isObserved(0)).toBe(true);
    expect(isObserved(false)).toBe(true);
    expect(isObserved(null)).toBe(false);
    expect(isObserved(undefined)).toBe(false);
    expect(isObserved(Number.NaN)).toBe(false);
    expect(isObserved("")).toBe(false);
    expect(isObserved("[NOT OBSERVED] - reason")).toBe(false);
    expect(isObserved("up")).toBe(true);
  });

  it("Band(null) renders not-observed rather than a band pill", () => {
    const { container } = mount(<Band band={null} />);
    expect(container.querySelector(".ui-band")).toBeNull();
    expect(container.textContent ?? "").toContain("not observed");
  });

  it("Meter(null) renders not-observed rather than an empty or zero bar", () => {
    const { container } = mount(<Meter label="Port errors" value={null} />);
    expect(container.querySelector('[role="meter"]')).toBeNull();
    expect(container.textContent ?? "").toContain("not observed");
  });
});

/* ══ no meaning in colour alone ════════════════════════════════════════════ */

describe("severity and state carry a non-colour signal", () => {
  it("SeverityBadge renders a glyph and the literal word, not only a colour", () => {
    const { container } = mount(<SeverityBadge severity="High" />);
    const el = container.querySelector(".ui-sev");
    expect(el?.getAttribute("data-severity")).toBe("High");
    expect(el?.querySelector("svg")).not.toBeNull();
    expect(el?.textContent).toContain("High");
  });

  it("the compact badge carries the initial as its non-colour channel and the word as its name", () => {
    /* At the 24px grid track the glyph rendered at ~7px, where an octagon and a circle are the
       same dot: the shape channel was not carrying the encoding, it was only putting two icon
       idioms in one column. The INITIAL is legible at that size, so it is the 1.4.1 channel here
       and the glyph is dropped rather than shown at a size that cannot be resolved. */
    const { container } = mount(<SeverityBadge severity="Critical" compact />);
    expect(container.querySelector(".ui-sev svg")).toBeNull();
    expect(container.querySelector(".ui-sev__text")?.textContent).toBe("C");
    expect(container.querySelector(".visually-hidden")?.textContent).toBe("Critical severity");
  });

  it("the five compact badges differ from each other with the hue removed", () => {
    const texts = (["Critical", "High", "Medium", "Low", "Info"] as const).map((s) => {
      const { container } = mount(<SeverityBadge severity={s} compact />);
      return container.querySelector(".ui-sev__text")?.textContent ?? "";
    });
    expect(new Set(texts).size).toBe(5);
  });

  it("every severity gets a distinct glyph, so five chips differ with the hue removed", () => {
    const paths = (["Critical", "High", "Medium", "Low", "Info"] as const).map((s) => {
      const { container } = mount(<SeverityBadge severity={s} />);
      return container.querySelector(".ui-sev svg")?.innerHTML ?? "";
    });
    expect(new Set(paths).size).toBe(5);
  });

  it("StateDot maps an unrecognised engine status to unknown, never to up", () => {
    const { container } = mount(<StateDot state="notconnect" showLabel />);
    expect(container.querySelector(".ui-state")?.getAttribute("data-state")).toBe("unknown");
    // The literal engine value is preserved for the reader rather than being normalised away.
    expect(container.textContent).toContain("notconnect");
  });

  it("StateDot uses a different silhouette for up, down and unknown", () => {
    const shapes = (["up", "down", "unknown"] as const).map((s) => {
      const { container } = mount(<StateDot state={s} />);
      return container.querySelector("svg")?.innerHTML ?? "";
    });
    expect(new Set(shapes).size).toBe(3);
  });
});

/* ══ Tabs — APG keyboard contract ══════════════════════════════════════════ */

const TAB_ITEMS = [
  { id: "summary", label: "Summary" },
  { id: "ports", label: "Ports" },
  { id: "routing", label: "Routing" },
];

function TabsHarness({ activation }: { activation?: "automatic" | "manual" }): ReactNode {
  const [value, setValue] = useState("summary");
  return (
    <Tabs
      id="t"
      label="Evidence"
      items={TAB_ITEMS}
      value={value}
      onChange={setValue}
      {...(activation ? { activation } : {})}
    />
  );
}

describe("Tabs (APG tabs pattern)", () => {
  const tabs = (c: HTMLElement): HTMLElement[] => [
    ...c.querySelectorAll<HTMLElement>('[role="tab"]'),
  ];

  it("puts exactly one tab in the tab order (roving tabindex)", () => {
    const { container } = mount(<TabsHarness />);
    const t = tabs(container);
    expect(t.map((x) => x.tabIndex)).toEqual([0, -1, -1]);
    expect(t[0]?.getAttribute("aria-selected")).toBe("true");
  });

  it("moves selection with ArrowRight and wraps at the end", () => {
    const { container } = mount(<TabsHarness />);
    const t = tabs(container);
    key(t[0]!, "ArrowRight");
    expect(tabs(container)[1]?.getAttribute("aria-selected")).toBe("true");
    key(tabs(container)[1]!, "ArrowRight");
    key(tabs(container)[2]!, "ArrowRight");
    expect(tabs(container)[0]?.getAttribute("aria-selected")).toBe("true");
  });

  it("moves selection with ArrowLeft and wraps at the start", () => {
    const { container } = mount(<TabsHarness />);
    key(tabs(container)[0]!, "ArrowLeft");
    expect(tabs(container)[2]?.getAttribute("aria-selected")).toBe("true");
  });

  it("Home and End jump to the first and last tab", () => {
    const { container } = mount(<TabsHarness />);
    key(tabs(container)[0]!, "End");
    expect(tabs(container)[2]?.getAttribute("aria-selected")).toBe("true");
    key(tabs(container)[2]!, "Home");
    expect(tabs(container)[0]?.getAttribute("aria-selected")).toBe("true");
  });

  it("manual activation moves focus without selecting until Enter", () => {
    const { container } = mount(<TabsHarness activation="manual" />);
    key(tabs(container)[0]!, "ArrowRight");
    expect(tabs(container)[0]?.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tabs(container)[1]);
    key(tabs(container)[1]!, "Enter");
    expect(tabs(container)[1]?.getAttribute("aria-selected")).toBe("true");
  });

  it("wires aria-controls to a panel id the panel actually claims", () => {
    const { container } = mount(<TabsHarness />);
    expect(tabs(container)[0]?.getAttribute("aria-controls")).toBe("t-panel-summary");
    expect(tabs(container)[0]?.id).toBe("t-tab-summary");
  });

  it("renders the not-observed mark for a null count, not a blank", () => {
    const { container } = mount(
      <Tabs
        id="c"
        label="Evidence"
        items={[{ id: "acl", label: "ACL", count: null }]}
        value="acl"
        onChange={() => {}}
      />,
    );
    expect(container.querySelector(".ui-notobs")).not.toBeNull();
  });
});

/* ══ Tooltip — WCAG 1.4.13 ═════════════════════════════════════════════════ */

describe("Tooltip", () => {
  it("opens on keyboard focus, not only on hover", () => {
    const { container } = mount(
      <Tooltip content="Coverage is 2 of 26 hosts">
        <Button>Coverage</Button>
      </Tooltip>,
    );
    const btn = container.querySelector("button")!;
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
    focus(btn);
    const tip = document.querySelector('[role="tooltip"]');
    expect(tip).not.toBeNull();
    expect(tip?.textContent).toBe("Coverage is 2 of 26 hosts");
    // Described-by, never labelled-by: the trigger keeps its own accessible name.
    expect(btn.getAttribute("aria-describedby")).toBe(tip?.id);
    expect(btn.textContent).toBe("Coverage");
  });

  it("is dismissible with Escape without moving focus", () => {
    const { container } = mount(
      <Tooltip content="hint">
        <Button>Trigger</Button>
      </Tooltip>,
    );
    const btn = container.querySelector("button")!;
    focus(btn);
    expect(document.querySelector('[role="tooltip"]')).not.toBeNull();
    key(document, "Escape");
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
    expect(document.activeElement).toBe(btn);
    expect(btn.hasAttribute("aria-describedby")).toBe(false);
  });

  it("does not swallow the trigger's own handlers", () => {
    const onFocus = vi.fn();
    const { container } = mount(
      <Tooltip content="hint">
        <Button onFocus={onFocus}>Trigger</Button>
      </Tooltip>,
    );
    focus(container.querySelector("button")!);
    expect(onFocus).toHaveBeenCalledTimes(1);
  });
});

/* ══ a subtree hidden while it holds focus (the third door, src/app/focus-return.ts) ═══════ */

describe("TabPanel / Disclosure / Tooltip never strand focus", () => {
  function TabsHarness({ tab }: { tab: string }): ReactNode {
    return (
      <>
        <Tabs id="h" label="Views" value={tab} onChange={() => {}} items={[{ id: "a", label: "A" }, { id: "b", label: "B" }]} />
        <TabPanel id="h" tabId="a" active={tab === "a"}>
          <button type="button" id="in-a">inside A</button>
        </TabPanel>
        <TabPanel id="h" tabId="b" active={tab === "b"}>
          <button type="button" id="in-b">inside B</button>
        </TabPanel>
      </>
    );
  }

  it("a tab panel hidden by its owner while focus is inside it hands focus to the selected tab, never <body>", () => {
    const { render } = mount(<TabsHarness tab="a" />);
    focus(document.getElementById("in-a")!);
    render(<TabsHarness tab="b" />);
    expect(document.getElementById("h-panel-a")!.hidden).toBe(true);
    expect(document.activeElement).toBe(document.getElementById("h-tab-b"));
  });

  it("a controlled disclosure closed by its owner while focus is in its region hands focus to its trigger", () => {
    const harness = (open: boolean): ReactNode => (
      <Disclosure summary="More" open={open} onOpenChange={() => {}}>
        <button type="button" id="in-region">inside</button>
      </Disclosure>
    );
    const { container, render } = mount(harness(true));
    focus(document.getElementById("in-region")!);
    render(harness(false));
    expect(container.querySelector<HTMLElement>(".ui-disclosure__region")!.hidden).toBe(true);
    expect(document.activeElement).toBe(container.querySelector(".ui-disclosure__trigger"));
  });

  it("an Escape that dismisses an open tooltip is consumed, so the global Escape does not also close a surface", () => {
    const { container } = mount(
      <Tooltip content="hint">
        <Button>Trigger</Button>
      </Tooltip>,
    );
    const btn = container.querySelector("button")!;
    const press = (): KeyboardEvent => {
      const e = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
      act(() => {
        btn.dispatchEvent(e);
      });
      return e;
    };
    focus(btn);
    expect(document.querySelector('[role="tooltip"]')).not.toBeNull();
    expect(press().defaultPrevented, "the dismissing Escape").toBe(true);
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
    expect(press().defaultPrevented, "an Escape with no tooltip open is left to the app").toBe(false);
  });
});

/* ══ Dialog — focus trap and restore ═══════════════════════════════════════ */

function DialogHarness({ open }: { open: boolean }): ReactNode {
  return (
    <>
      <button type="button" id="opener">
        Open
      </button>
      <Dialog open={open} onClose={() => {}} title="Confirm" footer={<Button>Cancel</Button>}>
        <Button>First</Button>
        <Button>Second</Button>
      </Dialog>
    </>
  );
}

describe("Dialog", () => {
  it("moves focus into the dialog on open and restores it to the invoker on close", () => {
    const { container, render } = mount(<DialogHarness open={false} />);
    const opener = container.querySelector<HTMLElement>("#opener")!;
    act(() => opener.focus());
    expect(document.activeElement).toBe(opener);

    render(<DialogHarness open={true} />);
    const panel = document.querySelector<HTMLElement>('[role="dialog"]')!;
    expect(panel.contains(document.activeElement)).toBe(true);

    render(<DialogHarness open={false} />);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("traps Tab at the last element and Shift+Tab at the first", () => {
    mount(<DialogHarness open={true} />);
    const panel = document.querySelector<HTMLElement>('[role="dialog"]')!;
    const items = [...panel.querySelectorAll<HTMLElement>("button")];
    const first = items[0]!;
    const last = items[items.length - 1]!;
    expect(items.length).toBeGreaterThan(2);

    act(() => last.focus());
    key(last, "Tab");
    expect(document.activeElement).toBe(first);

    act(() => first.focus());
    key(first, "Tab", { shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    mount(
      <Dialog open onClose={onClose} title="Confirm">
        <Button>Only</Button>
      </Dialog>,
    );
    key(document, "Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("names itself from its own title", () => {
    mount(
      <Dialog open onClose={() => {}} title="Blast radius">
        <Button>Only</Button>
      </Dialog>,
    );
    const panel = document.querySelector('[role="dialog"]')!;
    const labelledBy = panel.getAttribute("aria-labelledby")!;
    expect(panel.getAttribute("aria-modal")).toBe("true");
    expect(document.getElementById(labelledBy)?.textContent).toBe("Blast radius");
  });
});

/* ══ Dialog stack — the most recently OPENED dialog is the top layer (D1) ═══
   MEASURED (verifier round 2, E2/E3, 2026-09-27, release build, 1280x800): the command palette is
   parked in <body> long before its first open, so with the keyboard reference open a first Ctrl+K
   drew the palette UNDER the reference — both dialogs sat at z-index --z-dialog, and the reference
   came later in the DOM. Focus was in the palette's search box, which nobody could see (WCAG 2.4.11),
   and the reference was inert, so it could not be used either. Paint order had been an accident of
   DOM order. The class is "two open dialogs", not the palette: whatever order the dialogs were
   mounted, parked or pre-warmed in, the one opened LAST is on top, holds focus, owns the keyboard,
   and every open dialog under it is inert. Swept here over every mount order, opening order and
   pre-warm mode a Dialog has; the app's own dialogs are swept pairwise in CommandPalette.test.tsx.
   This file pins attributes, not pixels: what a browser was observed to paint, and where a durable
   rendered check belongs, is stated in that file's header. */

type Warm = false | "raster" | "parked";
type Which = "alpha" | "beta";
const WARMS: readonly Warm[] = [false, "raster", "parked"];
const PAIRS: readonly (readonly [Which, Which])[] = [
  ["alpha", "beta"],
  ["beta", "alpha"],
];

function StackHarness({
  open,
  warm,
  order,
  onClose,
}: {
  open: Record<Which, boolean>;
  warm: Record<Which, Warm>;
  order: readonly Which[];
  onClose: Record<Which, () => void>;
}): ReactNode {
  return (
    <>
      <button type="button" id="page-control">
        Page control
      </button>
      {order.map((w) => (
        <Dialog key={w} open={open[w]} prewarm={warm[w]} onClose={onClose[w]} title={`Dialog ${w}`} className={`stack-${w}`} footer={<Button>{`${w} last`}</Button>}>
          <Button>{`${w} first`}</Button>
          {/* A live region inside the dialog, as the palette has one: the page-wide inert descends into a
              subtree that holds one, which is how a dialog's insides could be left inert. */}
          <p aria-live="polite">{`${w} status`}</p>
        </Dialog>
      ))}
    </>
  );
}

const stackPanel = (w: Which): HTMLElement | null => document.querySelector<HTMLElement>(`.ui-dialog.stack-${w}`);
/** A dialog's scrim is the portal sibling rendered immediately before its panel. */
const stackScrim = (w: Which): HTMLElement | null => {
  const s = stackPanel(w)?.previousElementSibling;
  return s instanceof HTMLElement && s.classList.contains("ui-dialog__scrim") ? s : null;
};
/** Inert itself or through an ancestor: `inertOutside` marks the highest subtree it can. */
const isInert = (el: Element): boolean => el.closest("[inert]") !== null;
const layerOf = (el: HTMLElement | null): number | null => {
  const a = el?.getAttribute("data-dialog-layer");
  return a === null || a === undefined ? null : Number(a);
};
/** Paint order in the root stacking context, as primitives.css declares it (pinned below). */
const paintKey = (el: HTMLElement): number => 2 * (layerOf(el) ?? -1) + (el.classList.contains("ui-dialog") ? 1 : 0);

/** The CSS rule every dialog layer's z-index comes from (read from primitives.css, comments stripped). */
function zIndexRule(selector: string): string | null {
  const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "primitives.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const block = new RegExp(`(?:^|\\})\\s*${esc}\\s*\\{([^}]*)\\}`, "m").exec(css);
  const z = block === null ? null : /z-index:\s*([^;]+);/.exec(block[1]!);
  return z === null ? null : z[1]!.replace(/\s+/g, " ").trim();
}

describe("Dialog stack: the most recently opened dialog is the top layer", () => {
  const saved = { raf: window.requestAnimationFrame, caf: window.cancelAnimationFrame };
  let frames = new Map<number, FrameRequestCallback>();
  let nextFrame = 1;

  beforeEach(() => {
    frames = new Map();
    window.requestAnimationFrame = (cb) => {
      const id = nextFrame++;
      frames.set(id, cb);
      return id;
    };
    window.cancelAnimationFrame = (id) => void frames.delete(id);
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  });

  afterEach(() => {
    vi.useRealTimers();
    window.requestAnimationFrame = saved.raf;
    window.cancelAnimationFrame = saved.caf;
  });

  /** Present a frame and let every deferred timer run: the page-wide inert of every open dialog lands. */
  const settle = (): void => {
    for (let i = 0; i < 3; i++) {
      const due = [...frames.values()];
      frames.clear();
      act(() => {
        for (const cb of due) cb(0);
        vi.advanceTimersByTime(150);
      });
    }
  };

  /** `top` is the top layer: exposed, live, painted over every node of `under`, holding focus; `under` is inert. */
  const expectOnTop = (top: Which, under: Which, where: string): void => {
    const tp = stackPanel(top)!;
    const ts = stackScrim(top)!;
    const up = stackPanel(under)!;
    const us = stackScrim(under)!;
    expect(tp.getAttribute("role"), `${where}: ${top} is an open dialog`).toBe("dialog");
    expect(up.getAttribute("role"), `${where}: ${under} is still an open dialog`).toBe("dialog");
    expect(ts, `${where}: ${top} has its scrim`).not.toBeNull();
    for (const el of [tp, ts]) {
      expect(el.hasAttribute("inert"), `${where}: the top dialog ${top} is inert`).toBe(false);
      expect(el.hasAttribute("aria-hidden"), `${where}: the top dialog ${top} is hidden from AT`).toBe(false);
    }
    for (const el of [up, us]) expect(el.hasAttribute("inert"), `${where}: ${under}, underneath, is live`).toBe(true);
    for (const el of [tp, ts, up, us]) {
      expect(layerOf(el), `${where}: a node of an open dialog carries no layer`).not.toBeNull();
      expect(el.style.getPropertyValue("--dialog-layer"), `${where}: the CSS reads the same layer the stack assigned`).toBe(String(layerOf(el)));
    }
    expect(layerOf(tp), `${where}: ${top}'s scrim and panel are one layer`).toBe(layerOf(ts));
    expect(paintKey(ts), `${where}: ${top}'s scrim paints over ${under}'s panel`).toBeGreaterThan(paintKey(up));
    expect(paintKey(tp), `${where}: ${top}'s panel paints over its own scrim`).toBeGreaterThan(paintKey(ts));
    expect(tp.contains(document.activeElement), `${where}: focus is in ${top} (WCAG 2.4.11: the focused control is the visible one)`).toBe(true);
    expect([...tp.querySelectorAll("[inert]")].map((el) => el.outerHTML.slice(0, 80)), `${where}: a node INSIDE the top dialog ${top} is inert`).toEqual([]);
  };

  it("the z-index of a dialog's scrim and panel comes from its stack layer (the rule paintKey reads)", () => {
    expect(zIndexRule(".ui-dialog__scrim")).toBe("calc(var(--z-dialog) + var(--dialog-layer, 0) * 2)");
    expect(zIndexRule(".ui-dialog")).toBe("calc(var(--z-dialog) + var(--dialog-layer, 0) * 2 + 1)");
  });

  for (const order of PAIRS)
    for (const [first, second] of PAIRS)
      for (const warmFirst of WARMS)
        for (const warmSecond of WARMS)
          for (const settleBetween of [true, false])
            it(`mounted ${order.join(",")}; ${first} (${warmFirst || "not pre-warmed"}) opened, then ${second} (${warmSecond || "not pre-warmed"})${settleBetween ? "" : " before the first's deferred inert landed"}`, () => {
              const closes = { alpha: vi.fn(), beta: vi.fn() };
              const open: Record<Which, boolean> = { alpha: false, beta: false };
              const warm = { [first]: warmFirst, [second]: warmSecond } as Record<Which, Warm>;
              const ui = (): ReactNode => <StackHarness open={{ ...open }} warm={warm} order={order} onClose={closes} />;
              const { render } = mount(ui());
              const page = document.getElementById("page-control")!;
              act(() => page.focus());

              open[first] = true;
              render(ui());
              if (settleBetween) settle();
              expect(stackPanel(first)!.contains(document.activeElement), "the first dialog took focus").toBe(true);
              expect(layerOf(stackPanel(first)), "the one open dialog is the bottom layer").toBe(0);

              open[second] = true;
              render(ui());
              expectOnTop(second, first, "as it opens");
              settle();
              expectOnTop(second, first, "after both dialogs' deferred page-wide inert");
              expect(isInert(page), "the page behind both is inert").toBe(true);

              /* Only the top dialog owns the keyboard: its Tab trap wraps inside it, and one Escape closes it alone. */
              const buttons = [...stackPanel(second)!.querySelectorAll<HTMLElement>("button")];
              act(() => buttons[buttons.length - 1]!.focus());
              key(buttons[buttons.length - 1]!, "Tab");
              expect(document.activeElement, "Tab wrapped inside the top dialog").toBe(buttons[0]);
              key(buttons[0]!, "Tab", { shiftKey: true });
              expect(document.activeElement, "Shift+Tab wrapped inside the top dialog").toBe(buttons[buttons.length - 1]);
              key(document.activeElement!, "Escape");
              expect(closes[second], "Escape closed the top dialog").toHaveBeenCalledTimes(1);
              expect(closes[first], "the same Escape did not also close the one underneath").not.toHaveBeenCalled();

              open[second] = false;
              render(ui());
              settle();
              const back = stackPanel(first)!;
              expect(back.getAttribute("role"), "the first dialog is still open").toBe("dialog");
              expect(back.hasAttribute("inert") || stackScrim(first)!.hasAttribute("inert"), "the first dialog is live again").toBe(false);
              expect(back.contains(document.activeElement), "focus came back into the first dialog").toBe(true);
              expect([...back.querySelectorAll("[inert]")].map((el) => el.outerHTML.slice(0, 80)), "nothing inside the first dialog, on top again, is inert").toEqual([]);
              expect(isInert(page), "the page stays inert under the first dialog").toBe(true);

              open[first] = false;
              render(ui());
              settle();
              expect(isInert(page), "nothing is left inert").toBe(false);
              expect(document.querySelectorAll("[inert]").length, "no node is left inert by either dialog").toBe(
                document.querySelectorAll("[data-dialog-prewarm][inert]").length,
              );
              expect(document.activeElement, "focus is back where it started").toBe(page);
            });

  it("a dialog UNDER another that closes leaves the top one on top, focused, and the page inert", () => {
    const closes = { alpha: vi.fn(), beta: vi.fn() };
    const open: Record<Which, boolean> = { alpha: false, beta: false };
    const ui = (): ReactNode => <StackHarness open={{ ...open }} warm={{ alpha: false, beta: false }} order={["alpha", "beta"]} onClose={closes} />;
    const { render } = mount(ui());
    const page = document.getElementById("page-control")!;
    act(() => page.focus());
    open.alpha = true;
    render(ui());
    settle();
    open.beta = true;
    render(ui());
    settle();
    const focused = document.activeElement;
    open.alpha = false;
    render(ui());
    settle();
    const top = stackPanel("beta")!;
    expect(top.getAttribute("role")).toBe("dialog");
    expect(top.hasAttribute("inert")).toBe(false);
    expect(layerOf(top), "the one open dialog is the bottom layer again").toBe(0);
    expect(document.activeElement, "the dialog underneath did not pull focus out of the top one as it closed").toBe(focused);
    expect(isInert(page), "the page stays inert under the dialog still open").toBe(true);
    open.beta = false;
    render(ui());
    settle();
    expect(isInert(page)).toBe(false);
  });

  it("a dialog closing from UNDER another does not pull focus out of it, even to a control that is still live", () => {
    /* A live region is exempt from the page-wide inert (inertOutside), so a control inside one stays
       focusable behind every dialog: the one case where a lower dialog's focus return would succeed,
       and take focus out of the dialog the user is in. */
    const live = document.createElement("div");
    live.setAttribute("aria-live", "polite");
    const liveButton = document.createElement("button");
    liveButton.textContent = "in a live region";
    live.appendChild(liveButton);
    document.body.appendChild(live);
    const closes = { alpha: vi.fn(), beta: vi.fn() };
    const open: Record<Which, boolean> = { alpha: false, beta: false };
    const ui = (): ReactNode => <StackHarness open={{ ...open }} warm={{ alpha: false, beta: false }} order={["alpha", "beta"]} onClose={closes} />;
    const { render } = mount(ui());
    act(() => liveButton.focus());
    open.alpha = true;
    render(ui());
    settle();
    open.beta = true;
    render(ui());
    settle();
    const focused = document.activeElement;
    expect(stackPanel("beta")!.contains(focused), "precondition: focus is in the top dialog").toBe(true);
    expect(isInert(liveButton), "precondition: the live region's control is still live").toBe(false);
    open.alpha = false;
    render(ui());
    settle();
    expect(document.activeElement, "focus stayed in the dialog on top").toBe(focused);
    open.beta = false;
    render(ui());
    settle();
  });

  /* Verifier (R6 round 1, V3, 2026-09-27): each dialog's page-wide inert is deferred to its own frame,
     so the two can land in EITHER order. When the upper one landed first it covered the page, and the
     lower one's, landing second, found everything already inert and held nothing; when the upper one
     then closed it released the page, and the dialog still open sat over a live page. The class is
     every order the deferred inerts can land in (lower first, upper first, only one, none) x which
     dialog closes first, over every mount order and with the pair cold or parked: once the page has
     been covered, no close uncovers it while a dialog is still open, and a dialog still open always
     ends up over an inert page. */
  type Landing = "first,second" | "second,first" | "first" | "second" | "none";
  const LANDINGS: readonly Landing[] = ["first,second", "second,first", "first", "second", "none"];
  for (const order of PAIRS)
    for (const [first, second] of PAIRS)
      for (const warmBoth of [false, "parked"] as const)
        for (const landing of LANDINGS)
          for (const closing of ["top", "under"] as const)
            it(`mounted ${order.join(",")}; ${first} then ${second} opened (${warmBoth || "cold"}); deferred inert lands ${landing}; the ${closing} dialog closes first: the page stays covered`, () => {
              const closes = { alpha: vi.fn(), beta: vi.fn() };
              const open: Record<Which, boolean> = { alpha: false, beta: false };
              const warm = { alpha: warmBoth, beta: warmBoth } as Record<Which, Warm>;
              const ui = (): ReactNode => <StackHarness open={{ ...open }} warm={warm} order={order} onClose={closes} />;
              const { render } = mount(ui());
              settle();
              const page = document.getElementById("page-control")!;
              act(() => page.focus());
              /* The frames each open registers are that dialog's deferred inert; run them, and the timer each schedules, one dialog at a time. */
              const framesOf: Record<Which, number[]> = { alpha: [], beta: [] };
              const openOne = (w: Which): void => {
                const before = new Set(frames.keys());
                open[w] = true;
                render(ui());
                framesOf[w] = [...frames.keys()].filter((k) => !before.has(k));
              };
              const land = (w: Which): void => {
                const due = framesOf[w].map((k) => frames.get(k)).filter((cb): cb is FrameRequestCallback => cb !== undefined);
                for (const k of framesOf[w]) frames.delete(k);
                act(() => {
                  for (const cb of due) cb(0);
                  vi.advanceTimersByTime(1);
                });
              };
              openOne(first);
              openOne(second);
              expect(framesOf[first].length + framesOf[second].length, "precondition: each open deferred its page-wide inert to a frame").toBeGreaterThanOrEqual(2);
              const landed = landing === "none" ? [] : (landing.split(",") as ("first" | "second")[]).map((k) => (k === "first" ? first : second));
              for (const w of landed) land(w);
              if (landed.length > 0) expect(isInert(page), `precondition: with ${landed.join(" then ")} landed, the page is inert`).toBe(true);
              else expect(isInert(page), "precondition: nothing has landed yet, so the open stays off the page (E3)").toBe(false);

              const leaving = closing === "top" ? second : first;
              const staying = closing === "top" ? first : second;
              open[leaving] = false;
              render(ui());
              expect(stackPanel(staying)!.getAttribute("role"), `${staying} is still open`).toBe("dialog");
              /* A close never uncovers the page while a dialog is still open: not even for a frame. */
              if (landed.length > 0) expect(isInert(page), `the page behind ${staying} is still inert the moment ${leaving} closes`).toBe(true);
              settle();
              expect(isInert(page), `the page behind ${staying}, still open, is inert`).toBe(true);
              expect(isInert(stackPanel(staying)!) || isInert(stackScrim(staying)!), `${staying} itself is live`).toBe(false);
              expect([...stackPanel(staying)!.querySelectorAll("[inert]")].map((el) => el.outerHTML.slice(0, 80)), `nothing inside ${staying} is inert`).toEqual([]);
              expect(stackPanel(staying)!.contains(document.activeElement), `focus is in ${staying}`).toBe(true);

              open[staying] = false;
              render(ui());
              settle();
              expect(isInert(page), "nothing is left inert").toBe(false);
              expect(document.querySelectorAll("[inert]").length, "no node is left inert by either dialog").toBe(
                document.querySelectorAll("[data-dialog-prewarm][inert]").length,
              );
            });
});

describe("inertOutside and a subtree that is already inert", () => {
  it("does not descend into a dialog's pre-warm frame for its live region, and releases only what it made", () => {
    /* A pre-warm frame is inert as a whole, and its inert is the dialog's own, lifted when it opens.
       Descending into it for a live region marked its children one by one; they then stayed inert inside
       the open dialog (verifier R6 round 1, V3). */
    const kept = document.createElement("div");
    const covered = document.createElement("div");
    covered.innerHTML = '<p aria-live="polite">status</p><button type="button">control</button>';
    covered.setAttribute("inert", "");
    covered.setAttribute("data-dialog-prewarm", "parked");
    const page = document.createElement("div");
    page.innerHTML = '<p aria-live="polite">page status</p><button type="button">page control</button>';
    document.body.append(kept, covered, page);
    try {
      const undo = inertOutside([kept]);
      expect([...covered.querySelectorAll("[inert]")], "nothing inside the already-inert subtree was marked").toEqual([]);
      expect(page.querySelector("button")!.hasAttribute("inert"), "precondition: the rest of the page is covered, past its live region").toBe(true);
      expect(page.querySelector("[aria-live]")!.closest("[inert]"), "the page's live region still speaks").toBeNull();
      undo();
      expect(covered.hasAttribute("inert"), "an inert it did not make survives its undo").toBe(true);
      expect(document.querySelectorAll("[inert]").length, "its undo releases exactly what it made").toBe(1);
    } finally {
      kept.remove();
      covered.remove();
      page.remove();
    }
  });

  it("covers the CHILDREN of anyone else's inert subtree, so lifting that inert under an open modal exposes nothing (VR2-1)", () => {
    /* The hidden evidence rail is inert (useReleaseFocusOnHide) and holds a live region. Skipping it left it
       wholly out of the cover: shown while a modal was open, the whole rail was live behind the modal. */
    const kept = document.createElement("div");
    const rail = document.createElement("div");
    rail.innerHTML = '<p aria-live="polite">rail status</p><div><button type="button">rail control</button></div>';
    rail.setAttribute("inert", "");
    document.body.append(kept, rail);
    try {
      const undo = inertOutside([kept]);
      rail.removeAttribute("inert"); // the rail is shown while the modal is still open
      expect(rail.querySelector("button")!.closest("[inert]"), "a control in the shown rail is live behind the modal").not.toBeNull();
      expect(rail.querySelector("[aria-live]")!.closest("[inert]"), "the rail's live region still speaks").toBeNull();
      rail.setAttribute("inert", ""); // hidden again before the modal closes
      undo();
      expect(rail.hasAttribute("inert"), "the rail's own inert is not the cover's to release").toBe(true);
      expect([...rail.querySelectorAll("[inert]")], "the cover released every child it marked").toEqual([]);
    } finally {
      kept.remove();
      rail.remove();
    }
  });
});

/* ══ Popover — the panel stays inside the viewport ═════════════════════════
   MEASURED 2026-09-25 (390 and 768 px, light and dark, headless Chromium): the priority queue's
   "What the collection gap means" popover opens start-aligned under a trigger at the right edge,
   and its panel ran to x 908 in a 768 px viewport — the explanation, and the coverage line every
   overlay carries (B7), were cut off by the screen edge. Only the LEFT edge was nudged. */

describe("Popover stays inside the viewport", () => {
  /** Open a popover whose panel the layout engine would place at [left, left + width). */
  function openAt(left: number, width: number, viewport: number): HTMLElement {
    const realRect = HTMLElement.prototype.getBoundingClientRect;
    const realWidth = Object.getOwnPropertyDescriptor(window, "innerWidth");
    Object.defineProperty(window, "innerWidth", { configurable: true, value: viewport });
    HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
      if (!this.classList.contains("ui-popover")) return realRect.call(this);
      return { left, right: left + width, width, top: 100, bottom: 200, height: 100, x: left, y: 100, toJSON: () => ({}) } as DOMRect;
    };
    try {
      mount(
        <Popover label="Probe" open trigger={<button type="button">t</button>}>
          <p>body</p>
        </Popover>,
      );
    } finally {
      HTMLElement.prototype.getBoundingClientRect = realRect;
      if (realWidth) Object.defineProperty(window, "innerWidth", realWidth);
    }
    const panels = document.querySelectorAll<HTMLElement>(".ui-popover");
    return panels[panels.length - 1]!;
  }
  const shift = (el: HTMLElement): number => Number.parseFloat(el.style.marginLeft || "0");

  it("pulls a panel that would run past the right edge back inside an 8 px gutter", () => {
    const panel = openAt(740, 168, 768); // right edge 908 in a 768 px viewport, as measured
    expect(740 + 168 + shift(panel)).toBeLessThanOrEqual(768 - 8);
    expect(740 + shift(panel)).toBeGreaterThanOrEqual(8);
  });

  it("keeps the panel's START on screen when it is wider than the viewport", () => {
    const panel = openAt(300, 500, 390);
    expect(300 + shift(panel)).toBe(8);
  });

  it("still pushes a panel off the left edge back in, and leaves one that fits alone", () => {
    expect(-6.7 + shift(openAt(-6.7, 200, 1024))).toBeGreaterThanOrEqual(8);
    expect(shift(openAt(100, 200, 1024))).toBe(0);
  });

  /* The bottom edge. MEASURED 2026-09-25 at 320x568: the same popover's trigger sits at y 420-436,
     the panel's height floor (160 px) is more than the 116 px left below it, and the panel ran to
     y 600 — over the status bar's coverage group, with its own coverage line cut off by the
     screen edge. So a panel that does not fit below opens above when there is more room there,
     and otherwise is capped to the room below; either way it ends inside the viewport. */
  type Box = { top: number; height: number };
  function openBelow(trigger: Box, panel: Box, viewportH: number): HTMLElement {
    const realRect = HTMLElement.prototype.getBoundingClientRect;
    const realH = Object.getOwnPropertyDescriptor(window, "innerHeight");
    Object.defineProperty(window, "innerHeight", { configurable: true, value: viewportH });
    const box = (b: Box, left: number, width: number): DOMRect =>
      ({ left, right: left + width, width, top: b.top, bottom: b.top + b.height, height: b.height, x: left, y: b.top, toJSON: () => ({}) }) as DOMRect;
    HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
      if (this.classList.contains("ui-popover")) return box(panel, 20, 200);
      if (this.id === "pop-trigger") return box(trigger, 20, 24);
      return realRect.call(this);
    };
    try {
      mount(
        <Popover label="Probe" open trigger={<button type="button" id="pop-trigger">t</button>}>
          <p>body</p>
        </Popover>,
      );
    } finally {
      HTMLElement.prototype.getBoundingClientRect = realRect;
      if (realH) Object.defineProperty(window, "innerHeight", realH);
    }
    const panels = document.querySelectorAll<HTMLElement>(".ui-popover");
    return panels[panels.length - 1]!;
  }
  const px = (v: string): number => Number.parseFloat(v);

  it("opens ABOVE its trigger when it does not fit below and there is more room above", () => {
    const panel = openBelow({ top: 420, height: 16 }, { top: 440, height: 160 }, 568);
    expect(panel.style.top, "the panel was left hanging below the trigger").not.toBe("");
    const top = px(panel.style.top) + px(getComputedStyle(panel).marginTop || "0");
    expect(top).toBeGreaterThanOrEqual(8);
    expect(top + Math.min(160, px(panel.style.maxHeight || "1e9"))).toBeLessThanOrEqual(420);
  });

  it("is capped to the room below when that is where the room is", () => {
    const panel = openBelow({ top: 100, height: 16 }, { top: 120, height: 440 }, 400);
    expect(panel.style.top).toBe("");
    expect(120 + px(panel.style.maxHeight)).toBeLessThanOrEqual(400 - 8);
  });

  it("leaves a panel that fits below exactly where it is", () => {
    const panel = openBelow({ top: 100, height: 16 }, { top: 120, height: 160 }, 800);
    expect(panel.style.top).toBe("");
    expect(panel.style.maxHeight).toBe("");
  });
});

/* ══ Popover — the panel follows its trigger across a viewport resize ═══════
   MEASURED (D3 rung crossing, 768 -> 390): the panel kept the coordinates it had when it opened, so
   "More"'s panel sat wholly off screen with focus inside it. A resize re-measures the trigger. */

describe("Popover follows its trigger across a resize", () => {
  const saved = { raf: window.requestAnimationFrame, caf: window.cancelAnimationFrame };
  let frames = new Map<number, FrameRequestCallback>();
  let nextFrame = 1;
  beforeEach(() => {
    frames = new Map();
    window.requestAnimationFrame = (cb) => {
      const id = nextFrame++;
      frames.set(id, cb);
      return id;
    };
    window.cancelAnimationFrame = (id) => void frames.delete(id);
  });
  afterEach(() => {
    window.requestAnimationFrame = saved.raf;
    window.cancelAnimationFrame = saved.caf;
  });

  it("re-reads the trigger's position on resize, once per frame, and stops listening when closed", () => {
    let triggerLeft = 600;
    const realRect = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
      if (this.id !== "pop-resize-trigger") return realRect.call(this);
      return { left: triggerLeft, right: triggerLeft + 24, width: 24, top: 40, bottom: 56, height: 16, x: triggerLeft, y: 40, toJSON: () => ({}) } as DOMRect;
    };
    try {
      const ui = (open: boolean): ReactNode => (
        <Popover label="Probe" open={open} trigger={<button type="button" id="pop-resize-trigger">t</button>}>
          <p>body</p>
        </Popover>
      );
      const { render } = mount(ui(true));
      const panel = (): HTMLElement => [...document.querySelectorAll<HTMLElement>(".ui-popover")].at(-1)!;
      expect(panel().style.getPropertyValue("--pop-left")).toBe("600px");

      triggerLeft = 120;
      act(() => {
        window.dispatchEvent(new Event("resize"));
        window.dispatchEvent(new Event("resize"));
      });
      expect(frames.size, "a burst of resize events is coalesced into one frame").toBe(1);
      act(() => {
        const due = [...frames.values()];
        frames.clear();
        for (const cb of due) cb(0);
      });
      expect(panel().style.getPropertyValue("--pop-left"), "the panel still sits where the trigger was at open").toBe("120px");

      render(ui(false));
      triggerLeft = 300;
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      expect(frames.size, "a closed popover no longer re-measures").toBe(0);
    } finally {
      HTMLElement.prototype.getBoundingClientRect = realRect;
    }
  });
});

/* ══ Toolbar — APG roving tabindex ═════════════════════════════════════════ */

describe("Toolbar", () => {
  const items = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>("button")];

  it("is one tab stop, and arrows move between its controls", () => {
    const { container } = mount(
      <Toolbar label="Display options">
        <Button>One</Button>
        <Button>Two</Button>
        <Button>Three</Button>
      </Toolbar>,
    );
    const b = items(container);
    expect(b.map((x) => x.tabIndex)).toEqual([0, -1, -1]);

    act(() => b[0]!.focus());
    key(b[0]!, "ArrowRight");
    expect(document.activeElement).toBe(b[1]);
    expect(b.map((x) => x.tabIndex)).toEqual([-1, 0, -1]);

    key(b[1]!, "End");
    expect(document.activeElement).toBe(b[2]);
    key(b[2]!, "Home");
    expect(document.activeElement).toBe(b[0]);
  });
});

/* ══ names, and the sparkline's treatment of missing samples ═══════════════ */

describe("miscellaneous guarantees", () => {
  it("IconButton has an accessible name that does not depend on a tooltip", () => {
    const { container } = mount(<IconButton label="Copy sha256" icon={<IconCopy />} />);
    const btn = container.querySelector("button")!;
    expect(btn.getAttribute("aria-label")).toBe("Copy sha256");
  });

  it("Button defaults to type=button so it cannot submit a surrounding form", () => {
    const { container } = mount(<Button>Apply</Button>);
    expect(container.querySelector("button")?.getAttribute("type")).toBe("button");
  });

  it("Sparkline marks missing samples instead of interpolating across them", () => {
    const { container } = mount(
      <Sparkline label="Input errors" values={[1, 2, null, 4, 5]} />,
    );
    const svg = container.querySelector("svg")!;
    // One break in the line, and a visible tick where the sample is missing.
    expect(svg.querySelectorAll("polyline").length).toBe(2);
    expect(svg.querySelectorAll(".ui-spark__gap").length).toBe(1);
    expect(svg.getAttribute("aria-label")).toContain("4 of 5 samples observed");
    expect(svg.getAttribute("aria-label")).toContain("1 not observed");
  });

  it("Sparkline with nothing observed renders the absence treatment, not a flat line", () => {
    const { container } = mount(<Sparkline label="Input errors" values={[null, null]} />);
    expect(container.querySelector("polyline")).toBeNull();
    expect(container.textContent ?? "").toContain("not observed");
  });

  it("Button click reaches its handler", () => {
    const onClick = vi.fn();
    const { container } = mount(<Button onClick={onClick}>Go</Button>);
    click(container.querySelector("button")!);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

/* C2-1: an identifier path never breaks mid-word. CSS offers no break opportunity at `.` or `_`,
   and a token longer than its column otherwise splits between two letters under an
   `overflow-wrap` licence ("acls.core1.PROTECT_SERV / ERS[3]", measured at 1440 px). The Cite
   offers a <wbr> after every identifier separator instead; text and accessible name are unchanged. */
describe("Cite", () => {
  it("offers a line break only after identifier separators, without changing its text", () => {
    const path = "acls.core1.PROTECT_SERVERS[3]";
    const { container } = mount(<Cite cite={path} onOpen={() => {}} />);
    const el = container.querySelector(".ui-cite__path")!;
    expect(el.textContent).toBe(path);
    expect(el.querySelectorAll("wbr")).toHaveLength(3);
    for (const w of el.querySelectorAll("wbr")) expect(w.previousSibling?.textContent).toMatch(/[._/:-]$/);
    expect(container.querySelector("button")!.getAttribute("aria-label")).toBe(`Open source record ${path}`);
  });

  it("breaks a visible label the same way and leaves a separator-free token whole", () => {
    const { container } = mount(<Cite cite="x" label="collection_completeness" onOpen={() => {}} />);
    const el = container.querySelector(".ui-cite__path")!;
    expect(el.textContent).toBe("collection_completeness");
    expect(el.querySelectorAll("wbr")).toHaveLength(1);
    const { container: c2 } = mount(<Cite cite="core1" onOpen={() => {}} />);
    expect(c2.querySelectorAll(".ui-cite__path wbr")).toHaveLength(0);
  });
});
