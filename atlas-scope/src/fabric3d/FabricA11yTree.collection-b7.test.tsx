/**
 * B7's Fabric-list footer only: inventory/topology membership is not collection outcome.
 * No module is mocked. The real tree renders shipped compiled data and actual compileAll
 * output from the sample. Collection-section removal and a node-only collected:true flag
 * are declared synthetic snapshot perturbations; small mixed/empty arrays are component
 * contract fixtures, not collection evidence or a claim that empty snapshots are accepted.
 * Row/status/camera behavior and the broader B7 grade remain outside this footer repair.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { compileAll } from "../../tools/lib/compile-model.mjs";
import { validateSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import { bindSource } from "../../tools/source-binding.mjs";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Device, Fabric, Link } from "../core/types";
import { FabricA11yTree, TREE_GESTURES } from "./FabricA11yTree";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SAMPLE_TEXT = readFileSync(resolve(PKG, "..", "webapp/sample_data/sample_fleet.snapshot.json"), "utf8");
const sample = (): Record<string, any> => JSON.parse(SAMPLE_TEXT) as Record<string, any>;
const LIMIT = "Inventory and topology presence do not establish collection completeness.";
const COLLECTION_CLAIM = /\b\d+\s+not collected\b|\ball(?:\s+devices)?\s+collected\b/i;
const mounted: { root: Root; host: HTMLElement }[] = [];

beforeEach(() => { useInvestigation.getState().reset(); });
afterEach(() => {
  for (const { root, host } of mounted.splice(0)) {
    act(() => { root.unmount(); });
    host.remove();
  }
  useInvestigation.getState().reset();
});

function footer(devices: readonly Device[], links: readonly Link[], tiers = [devices.map((d) => d.host)]): { host: HTMLElement; text: string } {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  act(() => {
    root.render(<FabricA11yTree devices={devices} links={links} tiers={tiers} visible onHide={() => {}} onFocusDevice={() => {}} />);
  });
  return { host, text: host.querySelector(".fabric3d__tree-foot")?.textContent ?? "" };
}

function expectTreeParts(host: HTMLElement): void {
  expect(host.querySelector('[role="tree"]')).not.toBeNull();
  expect(host.querySelector(".fabric3d__tree-gestures")?.textContent).toBe(TREE_GESTURES);
  expect(host.querySelector(".fabric3d__tree-foot")).not.toBeNull();
}

function compile(snap: Record<string, any>): Fabric {
  const bytes = new TextEncoder().encode(JSON.stringify(snap));
  const validated = validateSnapshot(bytes);
  expect(validated.ok, JSON.stringify(validated.errors)).toBe(true);
  return compileAll(validated.snap!, bindSource(bytes, { source: "b7-footer-synthetic-variant.json", sourceOrigin: "external-file" }),
    { schemaAssumed: validated.schemaAssumed }).fabric as unknown as Fabric;
}

describe("Fabric-list footer inventory presence without collection conclusions", () => {
  it("renders the actual shipped compiled denominator and preserves link-centrality wording", () => {
    const raw = sample();
    const inventoryHosts = Object.keys(raw.devices);
    const allHosts = new Set([...inventoryHosts, ...raw.cable_map.nodes.map((node: { host: string }) => node.host)]);
    expect(new Set(fabric.devices.map((d) => d.host))).toEqual(allHosts);
    const { host, text } = footer(fabric.devices, fabric.links, fabric.tiers);
    expect(text).toContain(`${allHosts.size} devices, ${fabric.links.length} links.`);
    expect(text).toContain(`${inventoryHosts.length} with inventory records; ${allHosts.size - inventoryHosts.length} without inventory records.`);
    const unmeasured = fabric.links.filter((link) => link.isBridge === null).length;
    expect(text).toContain(`${unmeasured} links have no centrality measurement, so whether cutting them partitions the fabric is unknown.`);
    expect(text).toContain(LIMIT);
    expect(text).not.toMatch(COLLECTION_CLAIM);
    expectTreeParts(host);
  });

  it("collection wording witness: inventory records do not establish collection outcomes", () => {
    for (const basis of ["absent", "stated"] as const) {
      const snap = sample();
      if (basis === "absent") {
        delete snap.collection_completeness;
        delete snap.coverage_matrix;
      } else {
        expect(snap.collection_completeness.summary.inventory).toBeGreaterThan(0);
      }
      const model = compile(snap);
      const inventoryHosts = new Set(Object.keys(snap.devices));
      // Isolate the real compiled inventory members: the old footer claims literal
      // "0 not collected" here, even when no collection-basis sections were supplied.
      const present = model.devices.filter((d) => inventoryHosts.has(d.host));
      expect(present.length).toBe(inventoryHosts.size);
      expect(present.length).toBeGreaterThan(0);
      expect(present.every((d) => d.inventoried && d.collected)).toBe(true);
      const { host, text } = footer(present, []);
      expect(text, "collection wording witness").not.toMatch(COLLECTION_CLAIM);
      expect(text).toContain(`${inventoryHosts.size} devices, 0 links. ${inventoryHosts.size} with inventory records; 0 without inventory records.`);
      expect(text).toContain(LIMIT);
      expectTreeParts(host);
    }
  });

  it("inventory membership witness: collected flags cannot change record counts", () => {
    const snap = sample();
    const host = "b7-topology-only-fixture";
    expect(Object.hasOwn(snap.devices, host)).toBe(false);
    expect(snap.cable_map.nodes.some((node: { host: string }) => node.host === host)).toBe(false);
    // Compiler-reachable disagreement: a cable-map flag is true, but there is no
    // inventory record. No compiled flag or imported module is mocked/replaced.
    snap.cable_map.nodes.push({ ...snap.cable_map.nodes[0], host, collected: true });
    const model = compile(snap);
    expect(model.devices.find((d) => d.host === host)).toMatchObject({ inventoried: false, collected: true });
    const recordCount = Object.keys(snap.devices).length;
    expect(model.devices.filter((d) => d.collected).length).toBeGreaterThan(recordCount);
    const { host: rendered, text } = footer(model.devices, model.links, model.tiers);
    expect(text, "inventory membership witness").toContain(`${recordCount} with inventory records; ${model.devices.length - recordCount} without inventory records.`);
    expect(text).toContain(`${model.devices.length} devices, ${model.links.length} links.`);
    expect(text).toContain(LIMIT);
    expectTreeParts(rendered);
  });

  it.each(["mixed", "topology-only", "empty"] as const)("keeps exact %s component-fixture denominators", (kind) => {
    expect(fabric.devices.length).toBeGreaterThanOrEqual(3);
    expect(fabric.links.length).toBeGreaterThan(0);
    const devices: Device[] = kind === "empty" ? [] : fabric.devices.slice(0, kind === "mixed" ? 3 : 2).map((device, index) => ({
      ...device, inventoried: kind === "mixed" && index !== 1, collected: index === 1,
    }));
    const links: Link[] = devices.length === 0 ? [] : [{ ...fabric.links[0]!, id: "b7-link-fixture", a: devices[0]!.host, b: devices[1]!.host, isBridge: null }];
    const { host, text } = footer(devices, links);
    const expected = kind === "mixed" ? "3 devices, 1 links. 2 with inventory records; 1 without inventory records."
      : kind === "topology-only" ? "2 devices, 1 links. 0 with inventory records; 2 without inventory records."
      : "0 devices, 0 links. 0 with inventory records; 0 without inventory records.";
    expect(text).toContain(expected);
    expect(text).toContain(`${kind === "empty" ? 0 : 1} links have no centrality measurement, so whether cutting them partitions the fabric is unknown.`);
    expect(text).toContain(LIMIT);
    expect(text).not.toMatch(COLLECTION_CLAIM);
    expectTreeParts(host);
  });
});
