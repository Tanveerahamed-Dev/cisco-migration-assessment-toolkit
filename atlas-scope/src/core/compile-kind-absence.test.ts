// @vitest-environment node
/**
 * compile-kind-absence.test.ts — a node kind the snapshot does not state compiles as NOT STATED (null).
 *
 * WHAT WAS WRONG. tools/lib/compile-model.mjs compiled a device's kind as
 * `term(n?.kind) ?? (d ? "switch" : "unknown")`: a host with an inventory record but no cable-map kind became a
 * "switch", and one with neither became the engine's "unknown". Neither is stated anywhere. The engine writes a kind
 * only on a cable-map node (cisco_toolkit/analyze.py compute_cable_map: CABLE_MAP_COLLECTED_KIND "device" for a
 * collected host, a _KIND_RANK member from _node_kind for an uncollected one); it documents no default for a host it
 * did not map, and "unknown" is its CLASSIFIER's verdict about a mapped neighbour, not "the snapshot is silent". The
 * defaulted value even carried no field cite (deviceFieldCites cites `kind` only where the node states one), so the
 * model asserted a kind no record supports — absence rendered as a value.
 *
 * WHAT THIS PINS. Against the real producer's output (the tracked sample), with the kind REMOVED in each way it can
 * be absent: the compiled kind is null and uncited. A stated kind still compiles verbatim and cited (control).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { bindSource } from "../../tools/source-binding.mjs";
import { compileAll } from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import type { Device } from "./types";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const sample = (): Record<string, any> =>
  JSON.parse(readFileSync(resolve(REPO, "webapp", "sample_data", "sample_fleet.snapshot.json"), "utf8")) as Record<string, any>;

function devicesOf(snap: Record<string, unknown>): Map<string, Device> {
  const bytes = new TextEncoder().encode(JSON.stringify(snap));
  const v = assertValidSnapshot(bytes);
  const set = compileAll(v.snap, bindSource(bytes, { source: "case.json", sourceOrigin: "external-file" }), { schemaAssumed: v.schemaAssumed });
  return new Map(set.fabric.devices.map((d) => [d.host, d]));
}

describe("an absent node kind is not stated, never a value", () => {
  const base = sample();
  const nodes = base.cable_map.nodes as Record<string, any>[];
  const inventoried = nodes.find((n) => Object.hasOwn(base.devices, n.host) && n.kind === "device")!.host as string;
  const neighbour = nodes.find((n) => !Object.hasOwn(base.devices, n.host))!.host as string;

  it("control: a stated kind compiles verbatim and cites its node", () => {
    const d = devicesOf(base);
    expect(d.get(inventoried)!.kind).toBe("device");
    expect(d.get(inventoried)!.fieldCites.kind).toBe(`cable_map.nodes[host=${inventoried}]`);
    expect(d.get(neighbour)!.kind).toBe(nodes.find((n) => n.host === neighbour)!.kind);
  });

  it("an inventoried host whose cable-map node states no kind is NOT a switch", () => {
    const s = structuredClone(base);
    delete (s.cable_map.nodes as Record<string, any>[]).find((n) => n.host === inventoried)!.kind;
    const d = devicesOf(s).get(inventoried)!;
    expect(d.kind).toBeNull();
    expect(d.fieldCites.kind).toBeUndefined();
  });

  it("an inventoried host with no cable-map node at all is NOT a switch", () => {
    const s = structuredClone(base);
    s.cable_map.nodes = (s.cable_map.nodes as Record<string, any>[]).filter((n) => n.host !== inventoried);
    const d = devicesOf(s).get(inventoried)!;
    expect(d.collected).toBe(true);
    expect(d.kind).toBeNull();
    expect(d.fieldCites.kind).toBeUndefined();
  });

  it("an uninventoried node that states no kind is NOT the engine's classifier verdict \"unknown\"", () => {
    const s = structuredClone(base);
    delete (s.cable_map.nodes as Record<string, any>[]).find((n) => n.host === neighbour)!.kind;
    const d = devicesOf(s).get(neighbour)!;
    expect(d.kind).toBeNull();
    expect(d.fieldCites.kind).toBeUndefined();
  });

  it("an absence marker the engine writes for an unobserved value is not stated either", () => {
    const s = structuredClone(base);
    (s.cable_map.nodes as Record<string, any>[]).find((n) => n.host === inventoried)!.kind = "";
    expect(devicesOf(s).get(inventoried)!.kind).toBeNull();
  });
});
