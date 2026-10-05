/**
 * surfaces.test.tsx — the renderer chunk is fetched only when the fabric is actually mounted.
 *
 * WHAT WENT WRONG. three.js IS code-split into its own chunk (measured: `three-*.js`, 797,340
 * bytes, not a static import of the entry chunk, not in `index.html`'s modulepreload list). But
 * the split only saves anything if the lazy component's mount is genuinely conditional, and it was
 * not: `App` seeded `fabricVisible` to `true` and corrected it in an effect one commit later,
 * while `Stage` latches `mounted` the first time it is told "visible" and never un-latches. So on
 * a 375x812 viewport — where the design brief says the stage defaults to COLLAPSED and the DOM
 * mirror stands in for it — the production build fetched the whole renderer anyway.
 *
 * Measured on the built app served by `vite preview`, cold load, every js/css/html response:
 *   before — phone 375x812: 1,767,100 B total, `three-*.js` 797,340 B at +624 ms.
 *   after  — phone 375x812:   849,042 B total, three-*.js NOT FETCHED.
 *   after  — desktop 1440x900 is unchanged and still fetches it, which is correct: at the
 *            reference width the brief puts the fabric on screen, so it is not optional there.
 *
 * WHY THE ASSERTION IS "WAS THE MODULE IMPORTED" rather than a byte count: a bundle-size test
 * needs a build, and the thing that actually regressed is a render-order decision that a build
 * cannot see. `React.lazy` calls its factory exactly when the component first renders, so spying
 * on the factory measures the real question — did anything ask for the renderer? — in jsdom.
 */
import { act, StrictMode, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { actAsync } from "../test-support/act-turns";

import { useInvestigation } from "../core/store";

/* Hoisted above the App import below. The factory records that something asked for the renderer
   and then returns a stand-in, because jsdom has no WebGL and the real component must not run. */
const fabricImported = vi.fn();
vi.mock("../fabric3d/Fabric3D", () => {
  fabricImported();
  return { default: () => <div data-testid="fabric-mounted" />, Fabric3D: () => <div /> };
});

import { App } from "./App";

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

/**
 * Report the viewport the ladder asks about. `useMediaQuery` reads `matchMedia` synchronously on
 * every render, so this decides what the FIRST render sees — which is the whole point.
 */
function setViewport(width: number): () => void {
  const real = window.matchMedia;
  const px = (rem: string): number => Number.parseFloat(rem) * 16;
  window.matchMedia = ((q: string) => {
    /* Evaluate the real min-width/max-width rem queries this app uses against `width`. */
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

/** Let React resolve the lazy component and commit the result. */
const flush = async (): Promise<void> => {
  await actAsync(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
};

beforeEach(() => {
  act(() => { useInvestigation.getState().reset(); });
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
});

describe("the renderer chunk is only fetched when the fabric is mounted", () => {
  it("withholds it while the stage is collapsed and fetches it the moment the reader opens it", async () => {
    /* ONE test, walking the sequence, deliberately. A dynamic import resolves once per module
       registry, so a pair of tests asserting "not imported" then "imported" would be order-
       dependent — and the "not imported" half would also pass if the import had merely not
       RESOLVED yet, which is the false green this whole file exists to avoid. The transition
       inside one sequence is what proves the first half was real. */
    const restore = setViewport(375);
    try {
      const c = mount(
        <StrictMode>
          <App />
        </StrictMode>,
      );
      expect(c.querySelector('[data-fabric3d="off"]'), "the frame must start collapsed").not.toBeNull();
      await flush();
      expect(
        fabricImported,
        "something imported the 3-D renderer on a viewport where the fabric is collapsed — " +
          "797 KB of three.js for a reader who was never shown a fabric",
      ).not.toHaveBeenCalled();
      expect(c.querySelector('[data-testid="fabric-mounted"]')).toBeNull();

      const toggle = [...c.querySelectorAll("button")].find((b) =>
        (b.textContent ?? "").includes("Show the 3-D fabric"),
      );
      expect(toggle, "a collapsed stage must offer a control that opens it").toBeTruthy();
      act(() => toggle!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
      await flush();

      expect(fabricImported, "opening the fabric must actually load the renderer").toHaveBeenCalled();
      expect(c.querySelector('[data-fabric3d="on"]')).not.toBeNull();
      expect(c.querySelector('[data-testid="fabric-mounted"]')).not.toBeNull();
    } finally {
      restore();
    }
  });

  it("mounts it at the reference width, where the brief puts the fabric on screen", async () => {
    /* The other half: a test that only proves "not fetched" would also pass if the fabric never
       loaded at all. Asserted on the rendered component, which is registry-independent. */
    const restore = setViewport(1440);
    try {
      const c = mount(
        <StrictMode>
          <App />
        </StrictMode>,
      );
      await flush();
      expect(c.querySelector('[data-fabric3d="on"]')).not.toBeNull();
      expect(c.querySelector('[data-testid="fabric-mounted"]')).not.toBeNull();
    } finally {
      restore();
    }
  });
});

/* ── a fractional viewport width is in a rung too (F4 regression, repair wave 8) ───────────────── */

describe("a fractional viewport width lands in exactly one rung of the ladder", () => {
  /* Windows 125/150/175 % scaling gives media widths that are not whole CSS pixels. MEASURED by the
     independent refuter (headed Chromium, --force-device-scale-factor=1.5 --window-size=781,900):
     mediaWidth 767.3490, `(max-width: 47.9375rem)` false AND `(min-width: 48rem)` false, so the frame
     was in no rung — `data-fabric3d="on"`, no "Show the 3-D fabric" control, and three.js fetched at
     985 ms on a viewport the brief collapses. 767.44 is the dsf-1.75 case. The ladder's rungs are now
     the complement of ONE boundary each (`LADDER_REM`, surfaces.tsx), so nothing falls between them;
     `src/core/breakpoint-ladder.test.ts` proves it for every stylesheet rule and the hook itself. */
  for (const w of [767.349, 767.44, 767.99]) {
    it(`${w}px is the stacked rung: the fabric starts collapsed behind its toggle`, async () => {
      const restore = setViewport(w);
      try {
        const c = mount(<App />);
        await flush();
        expect(c.querySelector('[data-fabric3d="off"]'), `at ${w}px the frame must start collapsed`).not.toBeNull();
        const toggle = [...c.querySelectorAll("button")].find((b) => (b.textContent ?? "").includes("Show the 3-D fabric"));
        expect(toggle, `at ${w}px the collapsed stage must offer its toggle`).toBeTruthy();
        expect(c.querySelector(".app")?.hasAttribute("data-pane"), "the stacked rung chooses no single pane").toBe(false);
      } finally {
        restore();
      }
    });
  }

  for (const w of [1023.01, 1023.5, 1023.99]) {
    it(`${w}px is the single-column rung: one pane, chosen by the segmented control`, async () => {
      const restore = setViewport(w);
      try {
        const c = mount(<App />);
        await flush();
        expect(c.querySelector(".app")?.getAttribute("data-pane"), `at ${w}px the frame must be single-column`).toBe("queue");
        expect(c.querySelector('[data-fabric3d="on"]'), `at ${w}px the stage is on screen`).not.toBeNull();
      } finally {
        restore();
      }
    });
  }
});

/* ── the Path surface has a way in (acceptance A2) ─────────────────────────── */

describe("the path surface is reachable before a flow exists", () => {
  it("mounts the flow form when Path is selected with no flow set", async () => {
    /* The header's Path control — described in its own help as "a forwarding question and its
       hop-by-hop answer" — set ?s=path, marked itself selected, and changed NOTHING on screen: the
       panel was gated on `flow !== null`, so #rail-path was absent from the DOM until a flow
       already existed. The only remaining routes to the trace engine were the command palette and
       a query-bar syntax the placeholder never advertises, so a reader who could not guess
       "10.0.10.50 -> 10.0.30.10:443 tcp" could not reach the product's central feature at all.
       What mounts now is not a "no path yet" placeholder — which the brief rightly calls chrome —
       but the real form and the snapshot-derived presets. Both halves are asserted, because a
       panel that mounts empty would pass a mere presence check while fixing nothing. */
    const restore = setViewport(1440);
    try {
      const container = mount(<App />);
      await flush();
      expect(container.querySelector("#rail-path")).toBeNull();

      act(() => { useInvestigation.getState().setSurface("path"); });
      await flush();

      const panel = container.querySelector("#rail-path");
      expect(panel).not.toBeNull();
      expect(useInvestigation.getState().flow).toBeNull();

      // An answer-shaped affordance: the flow form's own controls, and real presets to run.
      expect(panel?.querySelector("form.pt-form")).not.toBeNull();
      expect(panel?.querySelectorAll("input").length ?? 0).toBeGreaterThanOrEqual(3);
      expect(panel?.querySelectorAll(".pt-preset__btn").length ?? 0).toBeGreaterThan(0);
    } finally {
      restore();
    }
  });
});

/* ── a shared link carrying an invalid flow is refused in words, never traced (B1) ─────────────── */

describe("a shared link with an invalid flow", () => {
  /* Measured 2026-09-23 on the dev server: each of these restored and TRACED, rendering
     "tcp 10.0.10.50 → 10.0.20.10:NaN" and "delivered". The whole shell is mounted from the URL — the
     decoder, the rail's mount rule and the panel — because the defect lived in the seam between them. */
  const LINKS: readonly [string, RegExp][] = [
    ["10.0.10.50>10.0.20.10>tcp>abc", /destination port "abc" in the shared link is not a port number/],
    ["10.0.10.50>10.0.20.10>tcp>70000", /destination port "70000" in the shared link is outside the port range/],
    ["10.0.10.50>10.0.20.10>bogus>443", /protocol "bogus" in the shared link is not a protocol/],
  ];
  const settle = async (): Promise<void> => {
    for (let i = 0; i < 6; i += 1) {
      await actAsync(async () => {
        await new Promise((r) => setTimeout(r, 10));
      });
    }
  };

  for (const [flow, named] of LINKS) {
    for (const withSurface of [true, false]) {
      it(`${flow}${withSurface ? "" : " (no s=path)"}: names the bad field and shows no verdict`, async () => {
        const restore = setViewport(1440);
        try {
          window.history.replaceState(null, "", `/?${withSurface ? "s=path&" : ""}flow=${encodeURIComponent(flow)}`);
          const c = mount(<App />);
          await settle();
          const panel = c.querySelector("#rail-path");
          expect(panel, "a link that carried a flow must open the path panel, even to refuse it").not.toBeNull();
          /* The presets under the form are the snapshot's own example questions and legitimately carry
             verdict words ("denied by list text"); everything else in the panel — the form, its errors,
             any result, the live announcement — must carry none. */
          const rest = panel!.cloneNode(true) as HTMLElement;
          for (const p of rest.querySelectorAll(".pt-presets")) p.remove();
          const text = (rest.textContent ?? "").replace(/\s+/g, " ");
          expect(panel?.querySelector(".pt-result"), "a refused link must not render a result").toBeNull();
          expect(panel?.querySelector(".hop")).toBeNull();
          expect(text).not.toContain("NaN");
          expect(text).not.toMatch(/\bdelivered\b|\bdenied\b/);
          expect(text).toMatch(named);
          expect(text).toContain("The flow in the shared link was not run");
          expect(useInvestigation.getState().trace).toBeNull();
          expect(useInvestigation.getState().flow).toBeNull();
        } finally {
          restore();
          window.history.replaceState(null, "", "/");
        }
      });
    }
  }
});
