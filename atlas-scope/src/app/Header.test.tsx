/**
 * Header.test.tsx — the frame's behaviour, against the REAL compiled snapshot.
 *
 * What these tests are for. The frame is where the two failures that matter most are cheapest to
 * commit and hardest to see: a reader who cannot tell which snapshot they are looking at, and a
 * coverage figure that quietly turns "we did not collect this" into "there is nothing here". Both
 * pass a visual review — the header looks fine with a stale identity, and a two-state coverage bar
 * looks tidier than a three-state one. So they are asserted mechanically instead.
 *
 * Every figure is compared against `fabric` itself, never against a number written into this file.
 * A test that hardcodes 26 stops failing on the day the snapshot changes and the UI does not.
 *
 * No testing-library: React's own `act` over a real `createRoot` in jsdom, matching
 * `src/ui/primitives.test.tsx`.
 */
import { act, useEffect, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { aclUndecidability } from "../core/acl-coverage";
import { forbiddenWordsIn } from "../core/claims";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { CoverageBar, agrees, coverageRows } from "./CoverageBar";
import { registerCommandTarget, useAppCommands } from "./commands";
import { Header, QUERY_DEBOUNCE_MS, exampleQuery } from "./Header";
import { ShortcutHelp } from "./ShortcutHelp";
import { StatusBar } from "./StatusBar";
import { setThemePreference } from "./ThemeToggle";

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

const key = (target: EventTarget, k: string, init: KeyboardEventInit = {}): void => {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }));
  });
};

const click = (el: Element): void => {
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
};

const type = (el: HTMLInputElement, value: string): void => {
  act(() => {
    /* React 19 tracks the DOM value to decide whether onChange fires; writing through the native
       setter is what makes a dispatched input event look like a real keystroke. */
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

beforeEach(() => {
  useInvestigation.getState().reset();
  window.localStorage.clear();
  setThemePreference("system");
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  document.documentElement.removeAttribute("data-theme");
});

/* ── snapshot identity ─────────────────────────────────────────────────────── */

describe("the header names the snapshot it is showing", () => {
  it("renders the source file, its schema and its collection date from the compiled meta", () => {
    const c = mount(<Header />);
    const text = c.textContent ?? "";
    const file = fabric.meta.source.split("/").pop() ?? fabric.meta.source;

    expect(text).toContain(file);
    expect(text).toContain(fabric.meta.sourceSha256.slice(0, 8));
    if (fabric.meta.schema !== null) expect(text).toContain(fabric.meta.schema);
    if (fabric.meta.collectedAt !== null) {
      expect(text).toContain(fabric.meta.collectedAt.slice(0, 10));
    }
  });

  it("puts the full sha256, the byte count and the compile time one click away", () => {
    const c = mount(<Header />);
    const trigger = c.querySelector<HTMLButtonElement>(".hdr-snap");
    expect(trigger).not.toBeNull();
    click(trigger!);

    const panel = document.querySelector('[role="dialog"][aria-label="Snapshot provenance"]');
    expect(panel).not.toBeNull();
    const text = panel?.textContent ?? "";
    expect(text).toContain(fabric.meta.sourceSha256);
    expect(text).toContain(fabric.meta.source);
    // Grouped with spaces, not `toLocaleString()`: a locale-dependent render cannot be compared
    // byte for byte between two capture machines (acceptance F6).
    expect(text).toContain(String(fabric.meta.sourceBytes).replace(/\B(?=(\d{3})+(?!\d))/g, " "));
  });

  /* D3 visibility, 2026-09-23: the popover opens with focus on "Copy the snapshot sha256", and the
     unwrapped 64-digit sha pushed that button outside the popover (x=641–668 against a panel ending
     at x=554, measured at 1440 and 1920). The sha is a DIGEST: it wraps inside its box (the
     primitive's UNBREAKABLE-TOKEN CONTAINER variant) and is shown whole, and the Copyable is bounded
     by its row, so the button stays inside. The layout itself is measured by
     review/audit-d3-focus.mjs; this pins that the header asks for it. */
  it("renders the sha as a digest that wraps inside the popover, with its copy button first to focus", () => {
    const c = mount(<Header />);
    const trigger = c.querySelector<HTMLButtonElement>(".hdr-snap")!;
    act(() => trigger.focus());
    click(trigger);
    const panel = document.querySelector('[role="dialog"][aria-label="Snapshot provenance"]')!;
    const copyable = panel.querySelector(".ui-copyable");
    expect(copyable?.classList.contains("ui-copyable--digest"), "the sha256 is not rendered as a wrapping digest").toBe(true);
    expect(copyable?.querySelector(".ui-copyable__value")?.textContent).toBe(fabric.meta.sourceSha256);
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Copy the snapshot sha256");
    expect(copyable?.contains(document.activeElement)).toBe(true);
  });

  it("names the byte form the digest and the byte count are taken over (O15)", () => {
    const c = mount(<Header />);
    const trigger = c.querySelector<HTMLButtonElement>(".hdr-snap")!;
    expect(trigger.title).toContain(`sha256 (${fabric.meta.sourceDigestForm}) ${fabric.meta.sourceSha256}`);
    click(trigger);
    const panel = document.querySelector('[role="dialog"][aria-label="Snapshot provenance"]')!;
    const text = panel.textContent ?? "";
    expect(text).toContain("bytes (LF-normalised)");
    expect(text).toContain("LF-normalised form");
  });

  it("teaches the query grammar with values that exist in this snapshot", () => {
    const example = exampleQuery();
    const c = mount(<Header />);
    const input = c.querySelector<HTMLInputElement>(".hdr-query__input");
    expect(input?.placeholder).toContain(example);

    // Every literal in the example must be real, or the placeholder sends the reader to an empty
    // result and teaches them the product is broken.
    for (const clause of example.split(" ")) {
      const [k, v] = clause.split(":");
      if (k === "severity") expect(fabric.findings.some((f) => f.severity === v)).toBe(true);
      if (k === "host") expect(fabric.devices.some((d) => d.host === v || d.id === v)).toBe(true);
    }
  });
});

/* ── keyboard ──────────────────────────────────────────────────────────────── */

/* ── the wiring App.tsx supplies, so key bindings resolve the way they do in the product ──────
   `/` is not Header's binding: `commands.ts` declares `query.focus` as a capability and
   `App.tsx` registers the query input as its target. Header used to install `/` with a raw
   `window.addEventListener`, which duplicated that capability and was invisible to the generated
   help sheet. These three tests exercise the real path, so they mount the same wiring. */
function Wired(): ReactNode {
  useAppCommands();
  useEffect(
    () =>
      registerCommandTarget("query.focus", () => {
        const el = document.querySelector<HTMLInputElement>('#app-header form[role="search"] input');
        el?.focus();
        el?.select();
      }),
    [],
  );
  return (
    <>
      <Header />
      <ShortcutHelp />
    </>
  );
}

describe("the query bar is reachable and escapable from the keyboard", () => {
  /*
   * WHERE `/` lands is App-level and is proven in the running application, not here.
   * `commands.ts` declares `query.focus`; `App.tsx` registers the query input as its target with
   * the selector below. Verified against the live app with Playwright:
   *     after '/': {"tag":"input","type":"text","inQueryBar":true}
   *
   * What this test pins is the SEAM between those two files, which is the thing that can silently
   * break: App.tsx finds the input by selector, so a rename in Header would leave `/` resolving to
   * a capability whose target matches nothing — and the key would quietly do nothing at all.
   */
  it("exposes the query input at the selector App.tsx targets", () => {
    const c = mount(<Header />);
    const viaAppSelector = c.querySelector<HTMLInputElement>('#app-header form[role="search"] input');
    expect(
      viaAppSelector,
      "App.tsx focuses the query bar with '#app-header form[role=\"search\"] input' — Header must keep rendering that shape",
    ).not.toBeNull();
    expect(viaAppSelector).toBe(c.querySelector(".hdr-query__input"));
  });

  it("stands down when another surface has already claimed the key", () => {
    const c = mount(<Header />);
    const input = c.querySelector<HTMLInputElement>(".hdr-query__input");
    /* Capture phase runs before the header's window listener, so this stands in for a command
       palette that owns Ctrl+K. The header must not act on an event someone else handled. */
    const claim = (e: KeyboardEvent): void => e.preventDefault();
    window.addEventListener("keydown", claim, true);
    key(document.body, "k", { ctrlKey: true });
    window.removeEventListener("keydown", claim, true);

    expect(document.activeElement).not.toBe(input);
  });

  it("does not hijack / while the reader is typing somewhere else", () => {
    const c = mount(<Header />);
    const input = c.querySelector<HTMLInputElement>(".hdr-query__input");
    const other = document.createElement("input");
    document.body.appendChild(other);
    other.focus();

    key(other, "/");
    expect(document.activeElement).toBe(other);
    expect(document.activeElement).not.toBe(input);
    other.remove();
  });

  it("Escape leaves the query bar and returns focus where it came from", () => {
    const c = mount(<Wired />);
    const input = c.querySelector<HTMLInputElement>(".hdr-query__input");
    const origin = document.createElement("button");
    document.body.appendChild(origin);
    origin.focus();

    /* Focus directly: how focus ARRIVES is the capability's business (see the seam test above).
       The subject here is what Escape does once the reader is in the field. */
    input?.focus();
    expect(document.activeElement).toBe(input);
    key(input!, "Escape");
    expect(document.activeElement).toBe(origin);
    origin.remove();
  });

  it("echoes every keystroke at once and writes the shared state once typing pauses", () => {
    vi.useFakeTimers();
    try {
      const c = mount(<Header />);
      const input = c.querySelector<HTMLInputElement>(".hdr-query__input");
      type(input!, "sev");
      type(input!, "severity:Critical");
      /* Design brief §8.2 journey 3: the echo and the filter are never coupled. The field shows the
         text in the keystroke's own commit; the store — and every surface that filters on it — does
         not move until the burst pauses. */
      expect(input!.value).toBe("severity:Critical");
      expect(useInvestigation.getState().query).toBe("");
      act(() => {
        vi.advanceTimersByTime(QUERY_DEBOUNCE_MS);
      });
      expect(useInvestigation.getState().query).toBe("severity:Critical");
    } finally {
      vi.useRealTimers();
    }
  });

  it("an external write replaces the draft, and Clear writes through immediately", () => {
    const c = mount(<Header />);
    const input = c.querySelector<HTMLInputElement>(".hdr-query__input");
    act(() => { useInvestigation.getState().setQuery("host:core1"); });
    expect(input!.value).toBe("host:core1");
    const clear = c.querySelector<HTMLButtonElement>('button[aria-label="Clear the query"]');
    expect(clear).not.toBeNull();
    click(clear!);
    expect(input!.value).toBe("");
    expect(useInvestigation.getState().query).toBe("");
  });

  it("opens the keyboard reference on ? and lists only bindings that exist", () => {
    mount(<Wired />);
    key(document.body, "?");
    const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
    expect(dialog).not.toBeNull();
    const text = dialog?.textContent ?? "";
    expect(text).toContain("Focus the query bar");
    // A binding nobody wired would be a false claim made to a reader who is already stuck.
    expect(text).not.toContain("Reset camera");
  });
});

/* ── surface switcher ──────────────────────────────────────────────────────── */

describe("the surface switcher is one tab stop", () => {
  it("marks the active surface and moves the investigation when pressed", () => {
    const c = mount(<Header />);
    const buttons = [...c.querySelectorAll<HTMLButtonElement>(".hdr-surface")];
    expect(buttons.length).toBe(4);
    expect(buttons[0]?.getAttribute("aria-pressed")).toBe("true");

    click(buttons[1]!);
    expect(useInvestigation.getState().surface).toBe("findings");
  });

  it("puts exactly one control of the toolbar in the tab order, and arrows move inside it", () => {
    const c = mount(<Header />);
    const toolbar = c.querySelector<HTMLElement>('[role="toolbar"]');
    const buttons = [...(toolbar?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
    expect(buttons.filter((b) => b.tabIndex === 0).length).toBe(1);

    buttons[0]?.focus();
    key(buttons[0]!, "ArrowRight");
    expect(document.activeElement).toBe(buttons[1]);
  });
});

/* ── narrow viewports ──────────────────────────────────────────────────────── */

describe("at a narrow viewport the header moves controls, it does not drop them", () => {
  /** A narrow viewport: every ladder edge (`(min-width: …)`, the only width query the app asks since
   *  wave 8 — see LADDER_REM in surfaces.tsx) is NOT reached, and every other query matches, so the
   *  system still reads as dark for the theme-shortcut case below. */
  const forceCompact = (): (() => void) => {
    const real = window.matchMedia;
    window.matchMedia = ((q: string) =>
      ({
        matches: !/min-width/.test(q),
        media: q,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList) as typeof window.matchMedia;
    return () => {
      window.matchMedia = real;
    };
  };

  it("keeps the surface switcher and the utilities reachable behind one control", () => {
    const restore = forceCompact();
    try {
      const c = mount(<Header />);
      // Gone from the bar...
      expect(c.querySelector(".hdr-surface")).toBeNull();
      const more = c.querySelector<HTMLButtonElement>(".hdr-more");
      expect(more).not.toBeNull();

      // ...and present behind the overflow control, with the toolbar semantics intact.
      click(more!);
      const panel = document.querySelector('[role="dialog"][aria-label="More controls"]');
      expect(panel?.querySelectorAll(".hdr-surface").length).toBe(4);
      expect(panel?.querySelector('[role="toolbar"]')).not.toBeNull();
      expect(panel?.querySelectorAll('[role="radio"]').length).toBe(3);
    } finally {
      restore();
    }
  });

  it("keeps the theme shortcut bound even though the control is inside a closed popover", () => {
    const restore = forceCompact();
    try {
      mount(<Header />);
      /* The binding belongs to the frame, not to the button: a shortcut that disappears with its
         control is exactly the function a keyboard user needs most at this width.
         The stub reports every query as matching, so the system here reads as dark — and the
         first press must therefore land on LIGHT. That is the point of toggling the effective
         theme rather than cycling the preference: the result is always the opposite of what is
         on screen, never a no-op. */
      key(document.body, "\\", { ctrlKey: true });
      expect(document.documentElement.getAttribute("data-theme")).toBe("light");
      key(document.body, "\\", { ctrlKey: true });
      expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    } finally {
      restore();
    }
  });

  it("is compact at every width below the single-column rung's top, fractional ones included (F4, wave 8)", () => {
    /* The header's own rung used to be `(max-width: 63.9375rem)`, a second number beside the shell's
       `(min-width: 64rem)`: at 1023.5 CSS px (Windows display scaling) it was neither, so the header
       laid out its full toolbar in the single-column frame. It now reads the ONE ladder
       (`useLadder`, surfaces.tsx), so its compact rung is the complement of the same boundary. */
    const atWidth = (width: number): (() => void) => {
      const real = window.matchMedia;
      window.matchMedia = ((q: string) => {
        let matches = /width/.test(q);
        for (const m of q.matchAll(/\((min|max)-width:\s*([\d.]+)(rem|px)\)/g)) {
          const bound = Number.parseFloat(m[2] as string) * (m[3] === "px" ? 1 : 16);
          matches &&= m[1] === "min" ? width >= bound : width <= bound;
        }
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
    };
    const compactAt = (w: number): boolean => {
      const restore = atWidth(w);
      try {
        const c = mount(<Header />);
        const compact = c.querySelector(".hdr-more") !== null;
        expect(compact, `at ${w}px the header is ${compact ? "compact" : "full"} and must not also be the other`).toBe(c.querySelector(".hdr-surface") === null);
        return compact;
      } finally {
        restore();
      }
    };
    expect([767.349, 1023.01, 1023.5, 1023.99].map(compactAt)).toEqual([true, true, true, true]);
    expect([1024, 1024.5, 1279.5, 1440].map(compactAt)).toEqual([false, false, false, false]);
  });

  it("still names the snapshot, by its sha when the file name will not fit", () => {
    const restore = forceCompact();
    try {
      const c = mount(<Header />);
      expect(c.querySelector(".hdr-snap")?.textContent).toContain(
        fabric.meta.sourceSha256.slice(0, 8),
      );
    } finally {
      restore();
    }
  });
});

/* ── theme ─────────────────────────────────────────────────────────────────── */

describe("the theme control", () => {
  it("defaults to the system preference and writes no attribute for it", () => {
    mount(<Header />);
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("applies and persists an explicit choice", () => {
    const c = mount(<Header />);
    const dark = c.querySelector<HTMLButtonElement>('[role="radio"][aria-label^="Dark"]');
    expect(dark).not.toBeNull();
    click(dark!);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(window.localStorage.getItem("atlas-scope.theme")).toBe("dark");
  });

  it("returns to the live system preference when System is chosen again", () => {
    const c = mount(<Header />);
    click(c.querySelector<HTMLButtonElement>('[role="radio"][aria-label^="Dark"]')!);
    click(c.querySelector<HTMLButtonElement>('[role="radio"][aria-label^="System"]')!);
    // The attribute is REMOVED, not set to a resolved value: tokens.css falls back to
    // prefers-color-scheme, so a mid-session OS change is honoured without a reload.
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("is one tab stop with arrow-key selection", () => {
    const c = mount(<Header />);
    const radios = [...c.querySelectorAll<HTMLButtonElement>('.thm [role="radio"]')];
    expect(radios.length).toBe(3);
    expect(radios.filter((r) => r.tabIndex === 0).length).toBe(1);

    radios[2]?.focus(); // "system" is the checked one by default
    key(radios[2]!, "ArrowRight");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("flips the effective theme on Ctrl+backslash", () => {
    mount(<Header />);
    key(document.body, "\\", { ctrlKey: true });
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    key(document.body, "\\", { ctrlKey: true });
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});

/* ── status bar ────────────────────────────────────────────────────────────── */

describe("the status bar states the denominators permanently (acceptance B7)", () => {
  it("reads every figure from fabric.coverage rather than from a literal", () => {
    const c = mount(<StatusBar />);
    const text = c.textContent ?? "";
    const total = fabric.devices.length;
    const collected = fabric.devices.filter((d) => d.collected).length;

    expect(text).toContain(`${collected}/${total} collected`);
    expect(text).toContain(`RIBs ${fabric.coverage.hostsWithRoutes}/${total}`);
    expect(text).toContain(`ACLs ${fabric.coverage.hostsWithAcls}/${total}`);
    expect(text).toContain(`centrality ${fabric.coverage.linksWithCentrality}/${fabric.links.length}`);
  });

  it("renders missing scene telemetry as not observed, never as zero", () => {
    const c = mount(<StatusBar stats={null} />);
    const scene = c.querySelector(".sb__scene");
    expect(scene?.textContent).toContain("not observed");
    expect(scene?.querySelector('[data-unobserved="true"]')).not.toBeNull();
    expect(scene?.textContent).not.toContain("0 fps");
  });

  it("names the active quality tier, and marks a reduced one in words", () => {
    const c = mount(
      <StatusBar
        stats={{
          fps: 58.4,
          frameMs: 17.1,
          drawCalls: 28,
          triangles: 55935,
          programs: 9,
          quality: "low",
          converged: false,
        }}
      />,
    );
    const scene = c.querySelector(".sb__scene")?.textContent ?? "";
    expect(scene).toContain("tier low");
    expect(scene).toContain("reduced");
    // Progressive refinement is not finished, and a screenshot taken now is not the final frame.
    expect(scene).toContain("refining");

    /* AMENDED 2026-09-21. This test used to assert "58 fps" in the PERMANENT line. A repair
       agent measured that two consecutive capture runs differed in 23 of 32 frames, every
       differing pixel inside the box holding those digits ("fabric 43 fps" vs "fabric 56 fps"),
       which made acceptance F6 (byte-identical captures) impossible by construction. The frame
       rate moved one click away into the disclosure, and the permanent line now carries only
       values that are a function of the DATA. So the assertion is inverted rather than deleted:
       what matters is that no frame-timing digit is painted into the chrome. */
    expect(scene, "a frame-timing number in the permanent line breaks byte-identical captures").not.toMatch(
      /\d+\s*fps/,
    );
  });

  it("still shows the frame rate — one click away, in the disclosure", () => {
    // Moving it out of the permanent line must not remove it: nothing is hidden, it is behind a
    // control that says so. BEHAVIOURAL, not a grep of StatusBar.tsx (the earlier form of this test
    // matched the source text and passed even if the disclosure never opened or never got stats):
    // mount the bar with a reading, click the renderer control, read what the disclosure RENDERS.
    // The live publish channel feeding this prop is exercised in status-telemetry.test.tsx.
    const c = mount(
      <StatusBar
        stats={{ fps: 47.6, frameMs: 21.0, drawCalls: 31, triangles: 55935, programs: 9, quality: "high", converged: true }}
      />,
    );
    expect(document.querySelector(".covpanel"), "the disclosure is closed before the click").toBeNull();
    const control = c.querySelector<HTMLButtonElement>("button.sb__scene");
    expect(control, "the renderer readout must be a control").not.toBeNull();
    click(control!);
    expect(control!.getAttribute("aria-expanded")).toBe("true");
    const diag = document.querySelector(".covpanel__renderer")?.textContent ?? "";
    expect(diag, "the opened disclosure must render the measured frame rate").toContain("48 fps");
    expect(diag).toContain("21.0 ms");
    // ...and still not on the permanent line.
    expect(c.querySelector(".sb__scene")?.textContent ?? "").not.toMatch(/\d+\s*fps/);
  });

  it("opens the coverage disclosure at the row the reader asked about, and returns focus", () => {
    const c = mount(<StatusBar />);
    const ribButton = [...c.querySelectorAll<HTMLButtonElement>(".sb__cov")].find((b) =>
      (b.textContent ?? "").startsWith("RIBs"),
    );
    expect(ribButton).toBeDefined();

    ribButton!.focus();
    click(ribButton!);
    expect(ribButton!.getAttribute("aria-expanded")).toBe("true");

    const panel = document.querySelector<HTMLElement>(".covpanel");
    expect(panel).not.toBeNull();
    const current = panel?.querySelector('tr[aria-current="true"]');
    expect(current?.textContent).toContain("Routing table");

    key(document, "Escape");
    expect(document.querySelector(".covpanel")).toBeNull();
    expect(document.activeElement).toBe(ribButton);
  });
});

/* ── coverage honesty ──────────────────────────────────────────────────────── */

describe("coverage is reported in three states, never two", () => {
  const rows = coverageRows();

  it("partitions every category, with no member falling out of the count", () => {
    for (const r of rows) {
      expect(
        r.observed + r.absent + r.notApplicable,
        `${r.id}: ${r.observed} + ${r.absent} + ${r.notApplicable} != ${r.total}`,
      ).toBe(r.total);
      // Non-negative AND integral: a negative or fractional part could still satisfy the sum
      // above (e.g. 27 + -1 + 0 = 26), so each part is pinned as a count, not only as a summand.
      for (const part of [r.observed, r.absent, r.notApplicable]) {
        expect(Number.isInteger(part) && part >= 0 && part <= r.total, `${r.id}: part ${part} is not a count in 0..${r.total}`).toBe(true);
      }
    }
  });

  it("derives each figure from the records, and it agrees with the snapshot's own figure", () => {
    const rib = rows.find((r) => r.id === "rib");
    const acl = rows.find((r) => r.id === "acl");
    const centrality = rows.find((r) => r.id === "centrality");

    expect(rib?.observed).toBe(fabric.coverage.hostsWithRoutes);
    expect(acl?.observed).toBe(fabric.coverage.hostsWithAcls);
    expect(centrality?.observed).toBe(fabric.coverage.linksWithCentrality);
    for (const r of rows) expect(agrees(r), `${r.id} disagrees with ${r.statedField}`).toBe(true);
  });

  it("calls a device not-applicable only when the collector never reached it", () => {
    const uncollected = fabric.devices.filter((d) => !d.collected).length;
    for (const r of rows) {
      if (r.unit !== "devices") continue;
      if (r.id === "collected") {
        // The first row MEASURES reachability, so routing its members into not-applicable would
        // leave the row measuring nothing.
        expect(r.notApplicable).toBe(0);
        expect(r.absent).toBe(uncollected);
        continue;
      }
      expect(r.notApplicable).toBeLessThanOrEqual(uncollected);
    }
  });

  it("reports the disagreement path in both directions — it cannot be exercised by this data", () => {
    // The live snapshot agrees everywhere, so the branch that surfaces a disagreement would never
    // run. An unexercised branch is not a check; this is where it is exercised.
    expect(agrees({ observed: 2, stated: 2 })).toBe(true);
    expect(agrees({ observed: 2, stated: 3 })).toBe(false);
    expect(agrees({ observed: 2, stated: null })).toBe(true);
  });

  it("renders all three states for every row, including the ones that are zero", () => {
    const c = mount(<CoverageBar />);
    const bodyRows = [...c.querySelectorAll("tbody tr")];
    expect(bodyRows.length).toBe(rows.length);

    for (const tr of bodyRows) {
      for (const state of ["observed", "absent", "na"]) {
        const cell = tr.querySelector(`td[data-state="${state}"]`);
        expect(cell, `a row is missing its "${state}" cell`).not.toBeNull();
        // A blank cell where a count belongs is the exact defect this table exists to prevent.
        expect((cell?.textContent ?? "").trim()).toMatch(/^\d+$/);
      }
    }

    const headers = [...c.querySelectorAll("thead th")].map((th) => th.textContent);
    expect(headers).toContain("Observed");
    expect(headers).toContain("Not observed");
    expect(headers).toContain("Not applicable");
  });

  /**
   * This assertion used to read `expect(text).toContain(String(coverage.aclLinesUnevaluable))`,
   * which could only ever prove that the UI echoed one compiled field. It passed for the whole
   * life of the build while the rendered sentence understated the undecidable ACL surface 6x and
   * named a member disjoint from the lines the engine actually refuses. Echoing a field is not
   * a check on the claim the field is used to make.
   *
   * The replacement asserts the property that bounds the verdicts — see
   * `src/core/acl-coverage.test.ts` for the whole-class version across every rendering surface.
   */
  it("names the forwarding scope and every access-list line that cannot be decided", () => {
    const c = mount(<CoverageBar />);
    const text = c.textContent ?? "";
    for (const host of fabric.coverage.routableHosts) expect(text).toContain(host);

    const u = aclUndecidability();
    expect(text).toContain(String(u.count));
    expect(
      u.count,
      "the rendered count must never be narrower than the set the engine refuses to evaluate",
    ).toBeGreaterThanOrEqual(u.engineRefused.length);
    for (const m of u.engineRefused) {
      expect(text, `${m.label} poisons verdicts but is not named in the coverage note`).toContain(
        m.label,
      );
    }
  });
});

/* ── claim discipline and determinism ──────────────────────────────────────── */

describe("the frame keeps the claim grammar", () => {
  it("emits no forbidden claim word anywhere in the rendered chrome", () => {
    const header = mount(<Header />);
    const status = mount(<StatusBar stats={null} />);
    click([...status.querySelectorAll<HTMLButtonElement>(".sb__cov")][0]!);
    key(document.body, "?");

    const rendered = [
      header.textContent ?? "",
      status.textContent ?? "",
      document.querySelector(".covpanel")?.textContent ?? "",
      document.querySelector('[role="dialog"][aria-modal="true"]')?.textContent ?? "",
    ].join("\n");

    expect(rendered.length).toBeGreaterThan(200);
    expect(forbiddenWordsIn(rendered)).toEqual([]);
  });

  it("renders the same text twice — nothing on the path depends on a clock or a random", () => {
    const first = mount(<StatusBar stats={null} />).textContent;
    const second = mount(<StatusBar stats={null} />).textContent;
    expect(second).toBe(first);
  });
});
