/**
 * selection-origin.test.tsx — acceptance A6 over A5: WHO made the device selection during a trace.
 *
 * THE DEFECT (acceptance report at 70bea72, A6 overturned to FAIL; refuter scripts ui7/ui9). The
 * fabric withholds the blast radius while the selection is "the trace's own" (A5: one question per
 * picture), and it decided that from `deviceId === the active hop's host` alone. The automatic hop
 * re-aim (App.tsx) satisfies that — and so do a palette selection of the same host, a click on it,
 * the fabric list and a restored `?d=core1&flow=…`. So core1, the fabric's main cut point, read
 * `data-stranded=yes` on 0 of 26 hosts during any investigation until a button was pressed.
 *
 * THE RULE PINNED HERE, at the level that owns it — the store and the shell. Nothing is mocked: the
 * shell runs at a phone-width layout, where the stage defaults to collapsed and the renderer chunk
 * is never loaded (design brief 2.5), so the real App, store, URL writer and path panel run and the
 * 3-D stage is simply not on screen. What the fabric DRAWS for each origin is Fabric3D.test.tsx's.
 *   - the trace's own re-aim is marked `deviceOrigin: "hop"`, including when it lands on a host that
 *     was already selected — a new trace re-asks the question;
 *   - every other device selection is explicit — `selectDevice` defaults to it, so a new caller
 *     cannot forget to say so (the class, not a list of the six known callers);
 *   - a restored `d=` is explicit (A4: the reader's device choice is part of the investigation);
 *   - the LINK tells the two apart with the existing grammar: the trace's own selection is written
 *     WITHOUT `d=` (A4 already defines "a flow and no `d=` selects the hop's host"), so a copied
 *     trace link reloads as the trace's picture rather than as an explicit blast question, and an
 *     explicit one keeps its `d=`.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { decodeInvestigation, encodeInvestigation, useInvestigation } from "../core/store";
import type { Flow } from "../core/types";
import { traceFlow } from "../forwarding/engine";

import { App } from "../app/App";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/** The flow the A6 refutation used: tcp/3389 into 10.0.30.10, denied at its single hop. */
const FLOW_TEXT = "10.0.10.50>10.0.30.10>tcp>3389";
const FLOW: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null };
const HOP_HOST = traceFlow(FLOW).hops[0]!.host;

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): void {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
}

const tick = async (n = 4): Promise<void> => {
  for (let i = 0; i < n; i += 1) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
};

/** Until the trace has landed and the shell's hop effect has committed after it. */
const settle = async (): Promise<void> => {
  const deadline = Date.now() + 8000;
  while (useInvestigation.getState().trace === null && Date.now() < deadline) await tick(1);
  await tick(4);
};

const linkParams = (): URLSearchParams => new URLSearchParams(encodeInvestigation(useInvestigation.getState()));

const realMatchMedia = window.matchMedia;
beforeEach(() => {
  useInvestigation.getState().reset();
  window.matchMedia = ((q: string) =>
    ({
      /* Phone width: every min-width query false, so the stage stays collapsed (see the header). */
      matches: /max-width/.test(q),
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList) as typeof window.matchMedia;
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  window.matchMedia = realMatchMedia;
  window.history.replaceState(null, "", "/");
  useInvestigation.getState().reset();
});

describe("the store: selectDevice is explicit unless the trace says otherwise", () => {
  it("defaults every selection to explicit, and records the trace's re-aim as the hop's", () => {
    const s = useInvestigation.getState();
    s.selectDevice("core1");
    expect(useInvestigation.getState().deviceOrigin).toBe("explicit");
    s.selectDevice("core1", { origin: "hop" });
    expect(useInvestigation.getState().deviceOrigin).toBe("hop");
    s.selectDevice("core1");
    expect(useInvestigation.getState().deviceOrigin, "re-choosing the same host is a new, explicit question").toBe("explicit");
  });

  it("reads a restored d= as explicit", () => {
    useInvestigation.getState().selectDevice("core1", { origin: "hop" });
    useInvestigation.getState().hydrate(decodeInvestigation(`d=core1&flow=${FLOW_TEXT}&hop=0`));
    expect(useInvestigation.getState().deviceOrigin).toBe("explicit");
  });

  it("decodes every link it decoded before exactly as before (the grammar is unchanged)", () => {
    for (const q of ["d=core1", `d=core1&flow=${FLOW_TEXT}&hop=0`, `flow=${FLOW_TEXT}&hop=0`, "l=L18&s=path", "f=F001&tab=raw"]) {
      const patch = decodeInvestigation(q);
      expect("deviceOrigin" in patch, q).toBe(false);
    }
    expect(decodeInvestigation(`d=core1&flow=${FLOW_TEXT}&hop=0`).deviceId).toBe("core1");
  });
});

describe("the shell: the trace's re-aim versus the reader's choice (A6 over A5)", () => {
  it("marks the trace's own re-aim as the hop's, and writes its link without d=", { timeout: 20000 }, async () => {
    window.history.replaceState(null, "", `/?s=path&flow=${encodeURIComponent(FLOW_TEXT)}&hop=0`);
    mount(<App />);
    await settle();
    const st = useInvestigation.getState();
    expect(st.trace, "the restored flow was traced").not.toBeNull();
    expect(st.deviceId).toBe(HOP_HOST);
    expect(st.deviceOrigin).toBe("hop");
    expect(linkParams().get("d"), "the link reproduces the trace's picture: no d=").toBeNull();
    expect(linkParams().get("flow")).toBe(FLOW_TEXT);
  });

  it("does not book the next keystroke as a navigation after a landing that left the link unchanged", { timeout: 20000 }, async () => {
    /* The trace's own selection writes no `d=`, so its landing can change the navigation signature
       (device, origin) without changing the link. The URL writer must still record that step as
       seen: otherwise the next in-progress edit (a query keystroke) is compared with the signature
       from BEFORE the landing and pushed as a history entry of its own. */
    window.history.replaceState(null, "", `/?s=path&flow=${encodeURIComponent(FLOW_TEXT)}&hop=0`);
    mount(<App />);
    await settle();
    expect(useInvestigation.getState().deviceOrigin).toBe("hop");
    const depth = window.history.length;
    await act(async () => useInvestigation.getState().setQuery("c"));
    await tick(3);
    expect(window.location.search).toContain("q=c");
    expect(window.history.length, "a query keystroke replaces the entry; it is not a step").toBe(depth);
  });

  it("treats a restored d= naming the hop's host as the reader's choice", { timeout: 20000 }, async () => {
    window.history.replaceState(null, "", `/?s=path&d=${HOP_HOST}&flow=${encodeURIComponent(FLOW_TEXT)}&hop=0`);
    mount(<App />);
    await settle();
    const st = useInvestigation.getState();
    expect(st.deviceId).toBe(HOP_HOST);
    expect(st.deviceOrigin).toBe("explicit");
    expect(linkParams().get("d")).toBe(HOP_HOST);
  });

  it("makes a selection of the hop's host DURING the trace explicit, and the link carries it", { timeout: 20000 }, async () => {
    window.history.replaceState(null, "", `/?s=path&flow=${encodeURIComponent(FLOW_TEXT)}&hop=0`);
    mount(<App />);
    await settle();
    expect(useInvestigation.getState().deviceOrigin).toBe("hop");
    await act(async () => useInvestigation.getState().selectDevice(HOP_HOST));
    await tick(2);
    expect(useInvestigation.getState().deviceOrigin).toBe("explicit");
    expect(linkParams().get("d")).toBe(HOP_HOST);
  });

  it("lets a NEW trace landing on an already-selected host claim that selection", { timeout: 20000 }, async () => {
    window.history.replaceState(null, "", "/?s=path");
    mount(<App />);
    await tick(4);
    await act(async () => useInvestigation.getState().selectDevice(HOP_HOST));
    expect(useInvestigation.getState().deviceOrigin).toBe("explicit");
    await act(async () => {
      const s = useInvestigation.getState();
      s.setFlow(FLOW);
      s.setTrace(traceFlow(FLOW));
    });
    await tick(4);
    const st = useInvestigation.getState();
    expect(st.trace).not.toBeNull();
    expect(st.deviceId).toBe(HOP_HOST);
    expect(st.deviceOrigin, "the new trace re-asks the question: one question per picture").toBe("hop");
  });
});
