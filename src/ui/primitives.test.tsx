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
import { act, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  Band,
  Button,
  Dialog,
  IconButton,
  Meter,
  NotObserved,
  Sparkline,
  SeverityBadge,
  StateDot,
  Tabs,
  Toolbar,
  Tooltip,
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
