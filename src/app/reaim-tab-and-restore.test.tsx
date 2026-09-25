/**
 * reaim-tab-and-restore.test.tsx — acceptance A4, two defects an independent critic measured in
 * the running app and no unit test caught.
 *
 * 1. THE TAB DEPENDED ON WHICH SURFACE MADE THE SELECTION. With `?d=core1&f=F099&tab=ports`, a
 *    fabric click on core2 kept `tab=ports`; clicking the "access14 assessed" chip in the evidence
 *    chain dropped it to Summary. One selection change, two behaviours. The rule now is one rule —
 *    a DEVICE selection moves the subject and never the tab, because every Device-pane tab renders
 *    for every device — so the chip is asserted against a plain `selectDevice` (the call every
 *    other surface makes), for every starting tab, rather than against a list of the tabs that
 *    happened to be reported.
 *
 * 2. A SHARED LINK LOST ITS DEVICE. `?s=path&d=dist1&f=F099&flow=…` opened with core1 selected:
 *    the restored trace parked on hop 0 and the shell's hop re-aim overwrote `d=` with the hop's
 *    host. The URL is the investigation, so `d=` must survive; a link with no `d=` still defaults
 *    to the hop's host (the control, so the fix cannot pass by disabling the re-aim).
 */
import { act, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabric } from "../core/data";
import { EVIDENCE_TABS, useInvestigation, type EvidenceTab } from "../core/store";
import { traceFlow } from "../forwarding/engine";

vi.mock("../fabric3d/Fabric3D", () => ({ default: () => <div />, Fabric3D: () => <div /> }));

import { App } from "./App";
import { RailB, type EvidenceView } from "./surfaces";
/* The stage's lazy chunk at collection time, as composite-tabstop.test.tsx does (acceptance F2): here
   it resolves to the mock above, so the first mount never waits on a module load either way. */
import "../fabric3d/Fabric3D";

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

/** Flush until the restored trace has landed AND the shell's hop re-aim has had a commit after it.
 *
 *  COUNTED, not timed (acceptance F2, W6 gate 2026-09-25). This waited against a wall-clock deadline
 *  (`Date.now() + 8000`) and failed on a loaded clone in five of seven runs, at 16-30 s or with
 *  "expected null to be core1": what the deadline measured was the host, not the app. The restore
 *  lands after one frame and one task (PathTrace's `deferPastPaint`), a fixed number of the 10 ms
 *  flush turns below whatever the load; the only wall-clock-bound part, the stage's lazy chunk,
 *  is loaded at collection time (see the import above). So the wait is a bounded count of turns,
 *  and running out of it is a stated failure, not a silent fall-through to a later assertion. */
const RESTORE_TURNS = 50;
const settleRestore = async (): Promise<void> => {
  let turns = 0;
  for (; useInvestigation.getState().trace === null && turns < RESTORE_TURNS; turns += 1) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
  expect(useInvestigation.getState().trace, `the restored trace had not landed after ${RESTORE_TURNS} flush turns`).not.toBeNull();
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
  }
};

function Harness(): ReactNode {
  const [view, setView] = useState<EvidenceView>("finding");
  return <RailB onOpenCite={() => {}} view={view} onView={setView} />;
}

const realMatchMedia = window.matchMedia;

beforeEach(() => {
  const s = useInvestigation.getState();
  s.reset();
  s.setSurface("fabric");
  s.setEvidenceTab("summary");
  /* A desktop viewport, so the shell lays out its full rails (jsdom has no matchMedia). */
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
});

/* Read from the data: a finding naming at least two devices that have records, so the chip can
   move the selection from one named device to another. */
const finding = fabric.findings.find(
  (f) => f.devices.filter((h) => fabric.devices.some((d) => d.id === h)).length >= 2,
);

/* Every tab, from the list the URL parser accepts (not a copy of it). */
const TABS: readonly EvidenceTab[] = EVIDENCE_TABS;

describe("a device selection keeps the Device-pane tab, whichever surface makes it", () => {
  for (const tab of TABS) {
    it(`the evidence chain's device chip keeps "${tab}", exactly as a plain selectDevice does`, () => {
      expect(finding, "the snapshot holds no finding naming two recorded devices").toBeDefined();
      const [from, to] = finding!.devices.filter((h) => fabric.devices.some((d) => d.id === h));

      /* The control: the call the fabric, palette, fabric list and hop list all make. */
      act(() => {
        const s = useInvestigation.getState();
        s.selectDevice(from!);
        s.setEvidenceTab(tab);
        s.selectDevice(to!, { surface: "fabric" });
      });
      const viaPlainSelection = useInvestigation.getState().evidenceTab;

      act(() => {
        const s = useInvestigation.getState();
        s.selectFinding(finding!.id);
        s.selectDevice(from!);
        s.setEvidenceTab(tab);
      });
      const c = mount(<Harness />);
      const chip = [...c.querySelectorAll<HTMLButtonElement>(".ev-devices .ev-devbtn")].find((b) =>
        b.textContent?.includes(to!),
      );
      expect(chip, `the evidence chain rendered no chip for ${to}`).toBeDefined();
      act(() => chip!.click());

      const st = useInvestigation.getState();
      expect(st.deviceId).toBe(to);
      expect(st.evidenceTab).toBe(tab);
      expect(st.evidenceTab).toBe(viaPlainSelection);
      /* And the pane actually shows that tab for the new device — not a silent fallback. */
      const selected = c.querySelector('[role="tab"][aria-selected="true"][id*="dp"]');
      expect(selected?.id ?? "").toContain(tab);
    });
  }
});

describe("a link carrying both a device and a flow restores the device", () => {
  const FLOW = "10.0.10.50>10.0.30.10>tcp>80";
  const hopHost = (): string => {
    const [srcIp, dstIp, protocol, port] = FLOW.split(">");
    const t = traceFlow({ srcIp: srcIp!, dstIp: dstIp!, protocol: protocol as "tcp", dstPort: Number(port), srcPort: null });
    return t.hops[0]!.host;
  };

  it("keeps d= instead of letting the trace's first hop overwrite it", { timeout: 15000 }, async () => {
    const host = hopHost();
    const other = fabric.devices.find((d) => d.id !== host && d.collected)!.id;
    window.history.replaceState(null, "", `/?s=path&d=${other}&f=F099&flow=${encodeURIComponent(FLOW)}`);
    mount(<App />);
    await settleRestore();
    const st = useInvestigation.getState();
    expect(st.trace, "the restored flow was never traced — the path panel did not mount").not.toBeNull();
    expect(st.hopIndex).toBe(0);
    expect(st.deviceId).toBe(other);
  });

  it("control: with no d=, the device defaults to the hop's host", { timeout: 15000 }, async () => {
    window.history.replaceState(null, "", `/?s=path&f=F099&flow=${encodeURIComponent(FLOW)}`);
    mount(<App />);
    await settleRestore();
    const st = useInvestigation.getState();
    expect(st.trace).not.toBeNull();
    expect(st.deviceId).toBe(hopHost());
  });
});
