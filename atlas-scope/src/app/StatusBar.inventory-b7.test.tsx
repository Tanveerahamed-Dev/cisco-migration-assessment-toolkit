/**
 * B7's permanent inventory denominator and shared overlay wording only.
 * No module is mocked. Real validateSnapshot/compileAll output enters through installDataset;
 * the shipped four-member set is also read as source data and installed through that same door.
 * Removed collection sections, a recordless collected node and a false record flag are explicitly
 * synthetic snapshot perturbations. Mixed/no-record/empty arrays below are labelled component
 * contract fixtures, not evidence that the compiler accepts an empty snapshot. CoverageBar's
 * separate collector row/classification and the broader B7 grade remain outside this repair.
 * DOM assertions establish neither pixels nor mobile geometry nor acceptance.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { compileAll } from "../../tools/lib/compile-model.mjs";
import { validateSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import { bindSource } from "../../tools/source-binding.mjs";
import type { CompiledDataset } from "../core/dataset/types";
import { asOpenedFile, PKG, SAMPLE_SNAPSHOT } from "../test-support/dataset/testing";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const sample = (): Record<string, any> => JSON.parse(readFileSync(SAMPLE_SNAPSHOT, "utf8")) as Record<string, any>;
const LIMIT = "Inventory-record presence does not establish collection completeness.";
const OUTCOME = /\b\d+\s*(?:\/\s*\d+\s*)?(?:not\s+)?collected\b|\ball(?:\s+devices)?\s+collected\b|\banswered the collector\b/i;
const mounted: { root: Root; host: HTMLElement }[] = [];

beforeEach(() => { window.localStorage.clear(); });
afterEach(() => {
  for (const { root, host } of mounted.splice(0)) {
    act(() => { root.unmount(); });
    host.remove();
  }
  vi.resetModules();
});

function compiled(snap: Record<string, any>): CompiledDataset {
  const bytes = new TextEncoder().encode(JSON.stringify(snap));
  const validated = validateSnapshot(bytes);
  expect(validated.ok, JSON.stringify(validated.errors)).toBe(true);
  return compileAll(validated.snap!, bindSource(bytes, { source: "b7-inventory-synthetic-variant.json", sourceOrigin: "external-file" }),
    { schemaAssumed: validated.schemaAssumed });
}

function shipped(): CompiledDataset {
  // Explicit files rather than a module alias: these assertions concern the actual shipped
  // source data even when the surrounding suite is run against a different dataset override.
  const read = (path: string): unknown => JSON.parse(readFileSync(resolve(PKG, path), "utf8"));
  return {
    fabric: read("src/data/fabric.json"), aclBindings: read("src/forwarding/acl-bindings.json"),
    ribEvidence: read("src/forwarding/rib-evidence.json"), producerEmission: read("src/panels/producer-emission.json"),
  } as CompiledDataset;
}

async function loadGraph(set: CompiledDataset) {
  vi.resetModules();
  (await import("../core/dataset/slot")).installDataset(asOpenedFile(set, "inventory-fixture.json"));
  const data = await import("../core/data");
  const store = await import("../core/store");
  store.useInvestigation.getState().reset();
  return {
    fabric: data.fabric,
    StatusBar: (await import("./StatusBar")).StatusBar,
    CoverageStatement: (await import("../ui/primitives")).CoverageStatement,
    coverageLine: (await import("../core/claims")).T8_coverageLine,
  };
}
type Graph = Awaited<ReturnType<typeof loadGraph>>;

function mount(graph: Graph, onOpenCoverage?: (rowId: string) => void): HTMLElement {
  const host = document.createElement("section");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  act(() => { root.render(<><graph.StatusBar onOpenCoverage={onOpenCoverage} /><graph.CoverageStatement /></>); });
  return host;
}

function inventoryControl(host: HTMLElement): HTMLButtonElement {
  const control = host.querySelector<HTMLButtonElement>('#status-bar [role="group"] button.sb__cov');
  expect(control, "the actual first coverage denominator is an operable control").not.toBeNull();
  return control!;
}

function expectedMembership(snap: Record<string, any>): { records: number; total: number } {
  const records = Object.keys(snap.devices);
  return { records: records.length, total: new Set([...records, ...snap.cable_map.nodes.map((node: { host: string }) => node.host)]).size };
}

function expectMembership(host: HTMLElement, graph: Graph, records: number, total: number): void {
  const label = `${records}/${total} inventory records`;
  const button = inventoryControl(host);
  expect(button.textContent).toBe(label);
  expect(button.title).toContain(`${records} of ${total} devices have inventory records.`);
  expect(button.title).toContain(LIMIT);
  expect(button.textContent + " " + button.title).not.toMatch(OUTCOME);
  expect(graph.coverageLine().split(" · ")[0]).toBe(label);
  const statement = host.querySelector('[data-overlay-coverage]');
  expect(statement?.textContent).toContain(label);
  expect(statement?.textContent).not.toMatch(OUTCOME);
  expect(statement?.querySelector("button, a, input, [tabindex]")).toBeNull();
  const status = host.querySelector("#status-bar")?.textContent ?? "";
  expect(status).toContain(`RIBs ${graph.fabric.coverage.hostsWithRoutes}/${total}`);
  expect(status).toContain(`ACLs ${graph.fabric.coverage.hostsWithAcls}/${total}`);
  expect(status).toContain(`centrality ${graph.fabric.coverage.linksWithCentrality}/${graph.fabric.links.length}`);
  expect(host.querySelector(".sb__scene")?.textContent).toContain("not observed");
}

describe("StatusBar inventory membership without collection conclusions", () => {
  it("renders actual shipped records and the complete device denominator", async () => {
    const snap = sample();
    const expected = expectedMembership(snap);
    const graph = await loadGraph(shipped());
    expect(graph.fabric.devices.length).toBe(expected.total);
    expectMembership(mount(graph), graph, expected.records, expected.total);
  });

  it("collection wording witness: absent collection basis is not a collector outcome", async () => {
    const snap = sample();
    delete snap.collection_completeness;
    delete snap.coverage_matrix;
    const expected = expectedMembership(snap);
    const graph = await loadGraph(compiled(snap));
    const host = mount(graph);
    const button = inventoryControl(host);
    expect(button.title, "collection wording witness").toContain(LIMIT);
    expect(Object.hasOwn(snap, "collection_completeness")).toBe(false);
    expect(Object.hasOwn(snap, "coverage_matrix")).toBe(false);
    expect(expected.records).toBeGreaterThan(0);
    expectMembership(host, graph, expected.records, expected.total);
  });

  it("inventory membership witness: recordless collected nodes do not change inventory counts", async () => {
    const snap = sample();
    const recordless = "b7-inventory-recordless-fixture";
    expect(Object.hasOwn(snap.devices, recordless)).toBe(false);
    expect(snap.cable_map.nodes.some((node: { host: string }) => node.host === recordless)).toBe(false);
    snap.cable_map.nodes.push({ ...snap.cable_map.nodes[0], host: recordless, collected: true });
    const expected = expectedMembership(snap);
    const graph = await loadGraph(compiled(snap));
    expect(graph.fabric.devices.find((device) => device.host === recordless)).toMatchObject({ inventoried: false, collected: true });
    expect(graph.fabric.devices.filter((device) => device.collected).length).toBeGreaterThan(expected.records);
    const host = mount(graph);
    const actual = inventoryControl(host).textContent;
    const label = `${expected.records}/${expected.total} inventory records`;
    expect(actual, "inventory membership witness").toBe(label);
    expectMembership(host, graph, expected.records, expected.total);
  });

  it("shared coverage witness: overlays state inventory presence rather than collection outcomes", async () => {
    const expected = expectedMembership(sample());
    const graph = await loadGraph(shipped());
    const host = mount(graph);
    const first = host.querySelector('[data-overlay-coverage] .ui-overlay-cov__fig');
    expect(first?.textContent, "shared coverage witness").toBe(`${expected.records}/${expected.total} inventory records`);
    expectMembership(host, graph, expected.records, expected.total);
  });

  it("a real inventory record remains present when its synthetic collected flag is false", async () => {
    const snap = sample();
    const host = Object.keys(snap.devices)[0]!;
    expect(host).toBeDefined();
    snap.devices[host].collected = false;
    for (const node of snap.cable_map.nodes) if (node.host === host) node.collected = false;
    const expected = expectedMembership(snap);
    const graph = await loadGraph(compiled(snap));
    // This is the compiler's current meaning, not a mutation of its output flags.
    expect(graph.fabric.devices.find((device) => device.host === host)).toMatchObject({ inventoried: true, collected: true });
    expectMembership(mount(graph), graph, expected.records, expected.total);
  });

  it.each(["mixed", "no-record", "empty"] as const)("keeps exact %s component-fixture membership", async (kind) => {
    const set = shipped();
    expect(set.fabric.devices.length).toBeGreaterThanOrEqual(3);
    // Deliberately post-compiler component fixtures. No claim that these empty/mismatched
    // documents are source snapshots; retained source bindings only allow the test dataset door.
    set.fabric.devices = kind === "empty" ? [] : set.fabric.devices.slice(0, kind === "mixed" ? 3 : 2).map((device, index) => ({
      ...device, inventoried: kind === "mixed" && index !== 1, collected: index === 1,
    }));
    set.fabric.links = [];
    set.fabric.coverage.devicesInventoried = 91; // stale stated field must not own either numerator
    const graph = await loadGraph(set);
    const expected = kind === "mixed" ? [2, 3] : kind === "no-record" ? [0, 2] : [0, 0];
    expectMembership(mount(graph), graph, expected[0]!, expected[1]!);
  });

  it("opens the actual inventory row, preserves its membership and returns focus on Escape", async () => {
    const expected = expectedMembership(sample());
    const graph = await loadGraph(shipped());
    const calls: string[] = [];
    const host = mount(graph, (rowId) => { calls.push(rowId); });
    const button = inventoryControl(host);
    act(() => { button.focus(); button.click(); });
    expect(calls).toEqual(["inventory"]);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const panel = document.querySelector<HTMLElement>(".covpanel");
    expect(panel).not.toBeNull();
    expect(document.activeElement).toBe(panel);
    const current = panel!.querySelector('tr[aria-current="true"]');
    expect(current?.querySelector(".cov__label")?.textContent).toBe("Inventory record");
    expect(current?.querySelector('[data-state="observed"]')?.textContent).toBe(String(expected.records));
    expect(current?.querySelector(".cov__c-of")?.textContent).toBe(`${expected.total} devices`);
    expect(panel!.querySelector('[data-overlay-coverage] .ui-overlay-cov__fig')?.textContent).toBe(button.textContent);
    act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
    expect(document.querySelector(".covpanel")).toBeNull();
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(button);
    expectMembership(host, graph, expected.records, expected.total);
  });
});
