import { describe, it, expect } from "vitest";
import { shortName, majorityRole, filterModel } from "./CableMap";
import type { CableMap as CableMapModel, CableMapNode, CableMapCable } from "../api";

function node(host: string, tier: number, kind: string, role = ""): CableMapNode {
  return { host, role, tier, order: 0, collected: true, op_status: "up", badges: [], ports: [], kind };
}
function cable(a: string, b: string): CableMapCable {
  return { a, a_port: "e1", b, b_port: "e2", is_pc: false, members: [], op_status: "up", confirmation: "", speed: "1000" };
}

// A 3-tier fleet: core → access → edge (an AP + a phone hang off the access switch).
function model(): CableMapModel {
  return {
    nodes: [
      node("core1", 0, "switch", "core"),
      node("acc1", 1, "switch", "access"),
      node("ap1", 2, "ap"),
      node("phone1", 2, "phone"),
    ],
    cables: [cable("core1", "acc1"), cable("acc1", "ap1"), cable("acc1", "phone1")],
    tiers: [["core1"], ["acc1"], ["ap1", "phone1"]],
    summary: { n_nodes: 4, n_cables: 3, n_tiers: 3, op: { up: 3, down: 0, unknown: 0 } },
  };
}

describe("shortName", () => {
  it("passes names of 22 chars or fewer through untouched (the boundary is inclusive)", () => {
    expect(shortName("core1")).toBe("core1");
    expect(shortName("a".repeat(22))).toHaveLength(22);
    expect(shortName("a".repeat(22))).toBe("a".repeat(22));
  });

  it("truncates longer names to 21 chars + an ellipsis (22 visible)", () => {
    const out = shortName("a".repeat(30));
    expect(out).toBe("a".repeat(21) + "…");
    expect(out).toHaveLength(22);
    expect(out.endsWith("…")).toBe(true);
  });
});

describe("majorityRole", () => {
  it("returns the most common role in a tier", () => {
    const cm: CableMapModel = {
      ...model(),
      nodes: [node("a", 1, "switch", "access"), node("b", 1, "switch", "access"), node("c", 1, "switch", "distribution")],
      tiers: [[], ["a", "b", "c"]],
    };
    expect(majorityRole(cm, 1)).toBe("access");
  });

  it("returns an empty string for a tier with no nodes (or no roles)", () => {
    expect(majorityRole(model(), 9)).toBe("");
  });
});

describe("filterModel", () => {
  it("is a no-op (identity tiers) with no filters, but stamps the raw pre-filter counts", () => {
    const out = filterModel(model(), false, null);
    expect(out.nodes).toHaveLength(4);
    expect(out.cables).toHaveLength(3);
    expect(out.tiers).toHaveLength(3);
    expect(out._raw).toEqual({ n: 4, c: 3 });
  });

  it("fabric-only hides positively-identified edge endpoints (AP/phone) and compacts the empty lane", () => {
    const out = filterModel(model(), true, null);
    const hosts = out.nodes.map((n) => n.host);
    expect(hosts).toContain("core1"); // switches always stay
    expect(hosts).toContain("acc1");
    expect(hosts).not.toContain("ap1"); // AP / phone are the only things hidden
    expect(hosts).not.toContain("phone1");
    // the now-empty edge tier is compacted away…
    expect(out.tiers).toHaveLength(2);
    // …but _raw still reports the original fleet size (coverage-honest "showing N of M")
    expect(out._raw).toEqual({ n: 4, c: 3 });
    // cables touching a hidden node are dropped, leaving only core↔access
    expect(out.cables).toHaveLength(1);
  });

  it("tier focus keeps the chosen lane plus its direct peers, dropping the rest", () => {
    // focus the core (tier 0): keeps core1 + its one peer acc1, drops the edge tier entirely
    const out = filterModel(model(), false, 0);
    const hosts = out.nodes.map((n) => n.host).sort();
    expect(hosts).toEqual(["acc1", "core1"]);
    expect(out.cables).toHaveLength(1);
    expect(out.tiers).toHaveLength(2);
  });

  it("does not mutate the source model (filters operate on copies)", () => {
    const cm = model();
    filterModel(cm, true, 0);
    expect(cm.nodes).toHaveLength(4);
    expect(cm.cables).toHaveLength(3);
    expect(cm.tiers).toHaveLength(3);
  });
});
