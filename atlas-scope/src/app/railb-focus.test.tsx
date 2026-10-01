/**
 * railb-focus.test.tsx — activating a device chip in the finding's evidence chain does not drop
 * focus to <body>.
 *
 * D3, 2026-09-21, measured with trusted keys: Enter on "core1 assessed" (flow A1, step 2) re-aimed
 * Rail B to the Device pane, hid the Finding pane that held the chip, and left
 * `document.activeElement` as <body> with nothing announced. The fix lives at the one place a pane
 * is hidden (RailB), so this drives the real chip and asserts where focus ends up.
 */
import { act, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { RailB, type EvidenceView } from "./surfaces";

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

function Harness(): ReactNode {
  const [view, setView] = useState<EvidenceView>("finding");
  return <RailB onOpenCite={() => {}} view={view} onView={setView} />;
}

beforeEach(() => {
  useInvestigation.getState().reset();
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  useInvestigation.getState().reset();
});

/* A finding that names at least one device with a record — read from the data, not hardcoded. */
const finding = fabric.findings.find((f) => f.devices.length > 0 && fabric.devices.some((d) => d.id === f.devices[0]));

describe("Rail B keeps focus when a chip sends the reader to the Device pane", () => {
  it("focus lands on the Device pane's heading, never on <body> or inside the hidden pane", () => {
    expect(finding, "the snapshot holds no finding naming a device; this test has nothing to drive").toBeDefined();
    act(() => { useInvestigation.getState().selectFinding(finding!.id); });
    const c = mount(<Harness />);

    const chip = c.querySelector<HTMLButtonElement>(".ev-devices .ev-devbtn");
    expect(chip, "the evidence chain rendered no device chip").not.toBeNull();
    act(() => chip!.focus());
    expect(document.activeElement).toBe(chip);

    act(() => chip!.click());

    expect(useInvestigation.getState().deviceId).toBe(finding!.devices[0]);
    const active = document.activeElement as HTMLElement;
    expect(active, "focus was dropped to <body> by the pane switch").not.toBe(document.body);
    expect(active.closest("[hidden]"), "focus was left inside the pane that was just hidden").toBeNull();
    expect(active.tagName).toBe("H2");
    expect(active.textContent).toContain(finding!.devices[0]);
  });

  it("does not move focus when the switch was made from outside the hidden pane", () => {
    act(() => { useInvestigation.getState().selectFinding(finding!.id); });
    const c = mount(<Harness />);
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    act(() => outside.focus());

    act(() => { useInvestigation.getState().selectDevice(finding!.devices[0]!); });

    expect(c.querySelector('[role="radio"][aria-checked="true"]')?.textContent).toBe("Device");
    expect(document.activeElement, "a selection made elsewhere must not pull focus into the rail").toBe(outside);
  });
});
