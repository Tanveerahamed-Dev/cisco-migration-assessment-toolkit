/**
 * The real device pane renders owner admission, rather than turning a retained raw zero into a
 * measurement. These counterfactual verdicts change only the impact on a real collected device;
 * its topology, independent blast radius, other evidence and pane controls remain the real model.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Cite, FailureImpact } from "../core/types";
import { DevicePane } from "./DevicePane";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const subject = fabric.devices.find((d) => d.collected)!;
const originalImpact = subject.impact;
const OWNER_CITE = "device_dossiers.per_device[0].impact_assessability";
const ROW_CITE = "failure_impact[0]";
const mounted: { root: Root; container: HTMLElement }[] = [];

const impactWith = (patch: Partial<FailureImpact> = {}): FailureImpact => ({
  assessable: "published", why: "The owner admits this exact synthetic row.", unavailable: null,
  severity: "Info", stranded: 0, vlans: 0, hard: 0, backup: 0, fhrp: 0,
  detail: "The producer's recorded detail.", cite: OWNER_CITE,
  row: {
    host: subject.host, severity: "Info", stranded: 0, vlans: 0, hard: 0, backup: 0, fhrp: 0,
    detail: "The producer's recorded detail.", cite: ROW_CITE,
  },
  ...patch,
});

beforeEach(() => {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().setEvidenceTab("summary");
  });
});
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  subject.impact = originalImpact;
});

function show(impact: FailureImpact, opened: Cite[] = []): HTMLElement {
  subject.impact = impact;
  act(() => { useInvestigation.getState().selectDevice(subject.id); });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<DevicePane onOpenCite={(cite) => opened.push(cite)} />));
  mounted.push({ root, container });
  const section = [...container.querySelectorAll<HTMLElement>(".dp-sec")]
    .find((s) => s.querySelector(".dp-sec__title")?.textContent === "Failure impact");
  expect(section, "the real pane rendered its failure-impact section").toBeDefined();
  return section!;
}

function rowIn(section: HTMLElement, label: string): HTMLElement {
  const row = [...section.querySelectorAll<HTMLElement>(".dp-cmp__col:first-child .dp-kv__row")]
    .find((r) => r.querySelector(".dp-kv__k")?.textContent === label);
  expect(row, `engine impact row ${label} exists`).toBeDefined();
  return row!;
}
function valueOf(section: HTMLElement, label: string): string {
  const value = rowIn(section, label).querySelector(".dp-kv__v")!.cloneNode(true) as HTMLElement;
  value.querySelectorAll(".ui-cite").forEach((c) => c.remove());
  return (value.textContent ?? "").replace(/\s+/g, " ").trim();
}
const COUNTS = ["Endpoints stranded", "VLANs", "Hard partitions", "Backed up", "FHRP covered"];

describe("failure impact follows the engine owner through the real pane", () => {
  it("an exact zero remains measured zero, including backup and FHRP counts", () => {
    const section = show(impactWith());
    expect(valueOf(section, "Assessment")).toBe("exact");
    for (const label of COUNTS) expect(valueOf(section, label), label).toBe("0");
    expect(rowIn(section, "Severity").querySelector(".ui-sev")).not.toBeNull();
  });

  it("a positive bound is qualified in both the value rows and comparison narrative", () => {
    const section = show(impactWith({
      assessable: "lower_bound", stranded: 45, vlans: 3, hard: 3, backup: null, fhrp: null,
      why: "The count excludes one blind link.",
    }));
    expect(valueOf(section, "Assessment")).toBe("lower bound");
    expect(valueOf(section, "Endpoints stranded")).toBe("at least 45 (lower bound)");
    expect([...rowIn(section, "Endpoints stranded").querySelectorAll(".ui-cite")].map((c) => c.getAttribute("aria-label"))).toEqual([
      `Open source record ${ROW_CITE}`, `Open source record ${OWNER_CITE}`,
    ]);
    expect(valueOf(section, "VLANs")).toBe("at least 3 (lower bound)");
    expect(valueOf(section, "Hard partitions")).toBe("at least 3 (lower bound)");
    expect(section.textContent).toContain("lower bounds, not exact totals");
    expect(valueOf(section, "Owner reason")).toBe("The count excludes one blind link.");
    expect(rowIn(section, "Severity").querySelector(".ui-sev")).toBeNull();
  });

  it("a zero lower bound cannot render like the exact zero positive control", () => {
    const section = show(impactWith({ assessable: "lower_bound", why: "Only a floor is assessed." }));
    for (const label of COUNTS) expect(valueOf(section, label), label).toBe("not assessed");
    expect(section.textContent).toContain("zero floor cannot establish no impact");
    expect(rowIn(section, "Severity").querySelector(".ui-sev")).toBeNull();
  });

  it.each(["not_assessed", "ambiguous"] as const)("a %s owner keeps held zero rows distinct from measurements", (assessable) => {
    const section = show(impactWith({ assessable, why: "The owner withholds this row." }));
    expect(valueOf(section, "Assessment")).toBe("not assessed");
    for (const label of COUNTS) expect(valueOf(section, label), label).toBe("not assessed");
    expect(valueOf(section, "Owner reason")).toBe("The owner withholds this row.");
    expect(rowIn(section, "Severity").querySelector(".ui-sev")).toBeNull();
    expect(section.querySelector("[data-impact-check]")).toBeNull();
    expect(section.textContent).not.toContain("The two measures disagree");
  });

  it.each(["No persisted owner verdict exists.", "The persisted owner verdict is unreadable."])("missing or unreadable owner: %s", (unavailable) => {
    const section = show(impactWith({ assessable: null, why: null, unavailable, stranded: 45 }));
    expect(valueOf(section, "Assessment")).toBe("not assessed");
    for (const label of COUNTS) expect(valueOf(section, label), label).toBe("not assessed");
    expect(valueOf(section, "Evidence unavailable")).toBe(unavailable);
    expect(rowIn(section, "Severity").querySelector(".ui-sev")).toBeNull();
  });

  it("a held raw 'No reachability impact' sentence remains explicitly unverified", () => {
    const section = show(impactWith({
      assessable: "not_assessed", detail: null, why: "Insufficient evidence holds this assessment.",
      row: { ...impactWith().row!, detail: "No reachability impact" },
    }));
    expect(valueOf(section, "Recorded detail (unverified)")).toBe("No reachability impact");
    expect(valueOf(section, "Assessment")).toBe("not assessed");
    expect(valueOf(section, "Owner reason")).toBe("Insufficient evidence holds this assessment.");
    expect(section.querySelector(".dp-disagree")?.textContent).not.toContain("No reachability impact");
    expect(rowIn(section, "Severity").querySelector(".ui-sev")).toBeNull();
  });

  it("the owner reason and retained raw detail open their own citation controls", () => {
    const opened: Cite[] = [];
    const section = show(impactWith({ assessable: "not_assessed", why: "An evidence gap holds the result." }), opened);
    const ownerButton = rowIn(section, "Owner reason").querySelector<HTMLButtonElement>(".ui-cite")!;
    expect(ownerButton.getAttribute("aria-label")).toBe(`Open source record ${OWNER_CITE}`);
    act(() => ownerButton.click());
    const detail = rowIn(section, "Recorded detail (unverified)");
    expect(valueOf(section, "Recorded detail (unverified)")).toBe("The producer's recorded detail.");
    const cites = [...detail.querySelectorAll<HTMLButtonElement>(".ui-cite")];
    expect(cites.map((c) => c.getAttribute("aria-label"))).toEqual([
      `Open source record ${ROW_CITE}`, `Open source record ${OWNER_CITE}`,
    ]);
    act(() => cites[0]!.click());
    expect(opened).toEqual([OWNER_CITE, ROW_CITE]);
    expect(section.querySelectorAll(".dp-cmp__head")).toHaveLength(2);
    expect(section.querySelector(".dp-cmp__col:last-child")?.textContent).toContain("Our computed blast radius");
  });
});
