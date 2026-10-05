/**
 * history-hop-step.c6.test.tsx — Back and Forward across a hop step are hop steps (acceptance C6).
 *
 * THE DEFECT (independent refuter, C6 round 2, 2026-10-03). `hop` is a navigation field, so every
 * `]` pushes a history entry and Back is the ordinary way to undo it. Back ran `applyHistoryState`,
 * which `reset()` the store — the trace became null — and then hydrated the flow; the path panel
 * re-traced it a frame later into a NEW Trace object of the same content. So the fabric was handed
 * "no trace" (the drawn path erased, 135 ms after Back) and then a new trace (the 240 ms draw-on and
 * all three 1600 ms packet loops, again). Alternating Back and Forward every 1.5 s kept the canvas
 * moving for 15 s — the symptom C6 was overturned for, through the door the first repair left open.
 *
 * THE RULE THESE TESTS HOLD, through the real `useUrlSync` popstate handler in the real App: a
 * history step between entries naming the SAME flow keeps the trace the store already holds — the
 * fabric is never handed null and never a different object — and changes only what the entry
 * changes (the hop, the device). The selection it lands on is the one a cold load of that entry
 * gives (acceptance A4): the entry's `d=` when it names one, kept as the reader's explicit choice;
 * the active hop's host otherwise. The flows are every suggested flow whose real trace has two or
 * more hops (a hop step needs somewhere to step to), not one hand-picked preset.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { actAsync } from "../test-support/act-turns";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Flow, Trace } from "../core/types";
import { suggestedFlows, traceFlow } from "../forwarding/engine";

/* What the real Fabric3D forwards to `scene.setTrace` is exactly the store's (trace, hopIndex) on
   each render (Fabric3D.tsx, the setTrace effect), so the stand-in records the store's trace on every
   render it makes. Anything the fabric would have been handed shows up here. */
const handed: (Trace | null)[] = [];
vi.mock("../fabric3d/Fabric3D", async () => {
  const { useInvestigation: store } = await import("../core/store");
  const Stand = (): ReactNode => {
    handed.push(store((s) => s.trace));
    return <div />;
  };
  return { default: Stand, Fabric3D: Stand };
});

import { App } from "./App";
import "../fabric3d/Fabric3D";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): void {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
}

/** A bounded count of 10 ms flush turns — never a wall-clock deadline (see reaim-tab-and-restore). */
const turns = async (n: number): Promise<void> => {
  for (let i = 0; i < n; i += 1) {
    await actAsync(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
};
const until = async (what: string, ok: () => boolean): Promise<void> => {
  for (let i = 0; i < 60 && !ok(); i += 1) await turns(1);
  expect(ok(), `${what} after 60 flush turns`).toBe(true);
  await turns(3);
};

/** One genuine history traversal through jsdom: the URL changes, then popstate fires. */
const traverse = async (dir: "back" | "forward", to: string): Promise<void> => {
  if (dir === "back") window.history.back();
  else window.history.forward();
  await until(`the ${dir} traversal to ${to}`, () => window.location.search === to);
};

const realMatchMedia = window.matchMedia;
beforeEach(() => {
  const s = useInvestigation.getState();
  s.reset();
  s.setSurface("fabric");
  s.setEvidenceTab("summary");
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
  handed.splice(0);
});

/** Every flow the reader is offered, plus the source/destination sweep flow-triggers.test.ts draws,
 *  whose real trace has a hop to step to — one per distinct host path. */
const multiHop = (() => {
  const flows: Flow[] = suggestedFlows().map((s) => s.flow);
  const srcs = ["10.0.40.50", "10.0.41.50", "10.0.20.50", "10.0.10.50", "10.0.30.10", "10.0.20.10"];
  const dsts = ["10.0.10.50", "10.0.30.10", "198.51.100.7", "10.0.20.10", "10.0.41.50", "10.0.40.50"];
  for (const src of srcs) for (const dst of dsts) if (src !== dst) flows.push({ srcIp: src, dstIp: dst, protocol: "tcp", dstPort: 22, srcPort: null });
  const seen = new Set<string>();
  const out: { label: string; flow: Flow; link: string; hosts: string[] }[] = [];
  for (const flow of flows) {
    const t = traceFlow(flow);
    const hosts = t.hops.map((h) => h.host);
    if (hosts.length < 2 || seen.has(hosts.join(">"))) continue;
    seen.add(hosts.join(">"));
    const f = flow;
    out.push({ flow: f, label: `${f.protocol}/${f.dstPort ?? "-"} ${f.srcIp} -> ${f.dstIp} (${hosts.join(">")})`, link: `${f.srcIp}>${f.dstIp}>${f.protocol}>${f.dstPort ?? ""}`, hosts });
  }
  return out;
})();

describe("the class is real and non-empty", () => {
  it("the shipped snapshot gives at least one flow with a hop to step to (the refuter's dist1 -> core1 preset among them)", () => {
    expect(multiHop.length).toBeGreaterThan(0);
    expect(multiHop.some((m) => m.label.includes("dist1>core1"))).toBe(true);
  });
});

describe.each(multiHop)("C6 — Back / Forward across a hop step keep the trace: $label", ({ flow, link, hosts }) => {
  /** Land on the flow (a cold restore), let the trace and its hop re-aim settle, and return it. */
  const land = async (): Promise<{ trace: Trace; entry0: string }> => {
    window.history.replaceState(null, "", `/?s=path&flow=${encodeURIComponent(link)}`);
    mount(<App />);
    await until("the restored trace", () => useInvestigation.getState().trace !== null);
    const trace = useInvestigation.getState().trace!;
    expect(handed.length, "the fabric stand-in is mounted, so what it is handed is observed").toBeGreaterThan(0);
    await until("the hop re-aim", () => useInvestigation.getState().deviceId === hosts[0]);
    return { trace, entry0: window.location.search };
  };
  /** What `]` does (commands.ts), then the URL write it pushes. */
  const step = async (to: number): Promise<string> => {
    const before = window.location.search;
    act(() => {
      useInvestigation.getState().selectHop(to);
    });
    await until(`hop ${to} pushed to the URL`, () => window.location.search !== before && new URLSearchParams(window.location.search).get("hop") === String(to));
    return window.location.search;
  };
  const expectKept = (trace: Trace, where: string): void => {
    expect(handed.filter((t) => t === null).length, `${where}: the fabric was handed "no trace"`).toBe(0);
    expect(handed.filter((t) => t !== trace).length, `${where}: the fabric was handed a different trace object`).toBe(0);
    expect(useInvestigation.getState().trace, `${where}: the store's trace`).toBe(trace);
  };

  it("Back to hop 0 and Forward to hop 1, repeatedly: the fabric is only ever handed the one trace", async () => {
    const { trace, entry0 } = await land();
    const entry1 = await step(1);
    for (let round = 0; round < 3; round += 1) {
      handed.splice(0);
      await traverse("back", entry0);
      expectKept(trace, `Back ${round}`);
      let st = useInvestigation.getState();
      expect(st.hopIndex).toBe(0);
      expect(st.deviceId, "the hop re-aim, as a cold load of that entry gives").toBe(hosts[0]);
      expect(st.deviceOrigin).toBe("hop");

      handed.splice(0);
      await traverse("forward", entry1);
      expectKept(trace, `Forward ${round}`);
      st = useInvestigation.getState();
      expect(st.hopIndex).toBe(1);
      expect(st.deviceId).toBe(hosts[1]);
      expect(st.deviceOrigin).toBe("hop");
    }
  });

  it("an entry naming its own device keeps it (A4), whether or not the hop changes, and the trace is kept throughout", async () => {
    const { trace, entry0 } = await land();
    const other = fabric.devices.find((d) => d.collected && !hosts.includes(d.id))!.id;
    /* entry A: hop 0 with an explicit device. */
    act(() => {
      useInvestigation.getState().selectDevice(other);
    });
    await until("the explicit device pushed to the URL", () => new URLSearchParams(window.location.search).get("d") === other);
    const entryA = window.location.search;
    /* entry B: hop 1 — the step re-aims to the hop's host and drops `d=`. */
    const entryB = await step(1);
    expect(new URLSearchParams(entryB).get("d")).toBeNull();
    /* entry C: hop 1 with an explicit device — the hop does NOT change between B and C. */
    act(() => {
      useInvestigation.getState().selectDevice(other);
    });
    await until("the second explicit device pushed", () => new URLSearchParams(window.location.search).get("d") === other);
    const entryC = window.location.search;

    handed.splice(0);
    await traverse("back", entryB); // C -> B: same hop, the device must return to the hop's host
    expectKept(trace, "Back C->B");
    let st = useInvestigation.getState();
    expect([st.hopIndex, st.deviceId, st.deviceOrigin]).toEqual([1, hosts[1], "hop"]);

    handed.splice(0);
    await traverse("back", entryA); // B -> A: the hop changes AND the entry names a device
    expectKept(trace, "Back B->A");
    st = useInvestigation.getState();
    expect([st.hopIndex, st.deviceId, st.deviceOrigin]).toEqual([0, other, "explicit"]);

    handed.splice(0);
    await traverse("back", entry0); // A -> 0: same hop, no device
    expectKept(trace, "Back A->0");
    st = useInvestigation.getState();
    expect([st.hopIndex, st.deviceId, st.deviceOrigin]).toEqual([0, hosts[0], "hop"]);

    handed.splice(0);
    await traverse("forward", entryA);
    await traverse("forward", entryB);
    await traverse("forward", entryC); // B -> C: same hop, the entry names a device
    expectKept(trace, "Forward 0->A->B->C");
    st = useInvestigation.getState();
    expect([st.hopIndex, st.deviceId, st.deviceOrigin]).toEqual([1, other, "explicit"]);
  });

  it("control: Back to an entry with NO flow clears the trace, and Forward to the flow traces it anew", async () => {
    window.history.replaceState(null, "", "/?s=path");
    mount(<App />);
    await turns(3);
    const empty = window.location.search;
    act(() => {
      const s = useInvestigation.getState();
      s.setFlow(flow);
      s.setTrace(traceFlow(flow));
    });
    await until("the run pushed to the URL", () => window.location.search !== empty);
    const withFlow = window.location.search;
    const ran = useInvestigation.getState().trace!;
    await traverse("back", empty);
    expect(useInvestigation.getState().trace, "Back to an entry with no flow leaves no trace").toBeNull();
    await traverse("forward", withFlow);
    await until("the re-traced flow", () => useInvestigation.getState().trace !== null);
    expect(useInvestigation.getState().trace, "the flow is traced again — a new answer object").not.toBe(ran);
  });
});
