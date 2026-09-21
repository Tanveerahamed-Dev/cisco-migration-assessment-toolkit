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

/** Let React resolve the lazy component and commit the result. */
const flush = async (): Promise<void> => {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
};

beforeEach(() => {
  act(() => useInvestigation.getState().reset());
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

      act(() => useInvestigation.getState().setSurface("path"));
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
