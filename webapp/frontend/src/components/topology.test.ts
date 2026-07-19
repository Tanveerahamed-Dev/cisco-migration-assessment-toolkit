import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { layout, linkPath } from "./TopologyGraph";
import { switchMesh, topoNodeLabel } from "./Topology3D";

// The signature feature's PURE logic, tested without a GPU: the role-tiered lane positioning and the
// three.js node-geometry builder both run headless (only the react-force-graph WebGL *render* needs a
// browser — that is Playwright/E2E territory, deliberately out of jsdom scope, see vite.config).

describe("layout — role-tiered lane positioning (device-fidelity 2D)", () => {
  const raw = {
    nodes: [
      { id: "acc-1", band: "Good", score: 80, role: "access", degree: 1, keystone: false },
      { id: "core-1", band: "Fair", score: 61, role: "core", degree: 2, keystone: true },
      { id: "dist-1", band: "Poor", score: 44, role: "distribution", degree: 2, keystone: false },
    ],
    edges: [
      { source: "core-1", target: "dist-1", is_bridge: false, pairs_cut: 0 },
      { source: "dist-1", target: "acc-1", is_bridge: true, pairs_cut: 2 },
    ],
  };

  it("stacks lanes in role order (core above distribution above access) with finite in-bounds coords", () => {
    const { nodes, lanes, W, H } = layout(raw);
    const y = (id: string) => nodes.find((n) => n.id === id)!.y;
    expect(y("core-1")).toBeLessThan(y("dist-1"));
    expect(y("dist-1")).toBeLessThan(y("acc-1"));
    expect(lanes.map((l) => l.label)).toEqual(["CORE", "DISTRIBUTION", "ACCESS"]);
    for (const n of nodes) {
      expect(Number.isFinite(n.x)).toBe(true);
      expect(Number.isFinite(n.y)).toBe(true);
      expect(n.x).toBeGreaterThan(0); expect(n.x).toBeLessThan(W);
      expect(n.y).toBeGreaterThan(0); expect(n.y).toBeLessThan(H);
    }
  });

  it("resolves edge endpoints to the laid-out node objects and anchors stubs on the facing chassis edges", () => {
    const { links } = layout(raw);
    expect(links).toHaveLength(2);
    const cd = links[0];
    expect((cd.source as { id: string }).id).toBe("core-1");
    expect((cd.target as { id: string }).id).toBe("dist-1");
    // core sits above distribution: its stub is on the BOTTOM chassis edge (y + 25), the peer's on TOP
    expect(cd.a.y).toBeCloseTo(cd.source.y + 25);
    expect(cd.b.y).toBeCloseTo(cd.target.y - 25);
    expect(cd.pairs_cut).toBe(0);
    expect(links[1].is_bridge).toBe(true);
  });

  it("keeps band / keystone / degree on the laid nodes (the chassis renders from them)", () => {
    const { nodes } = layout(raw);
    const core = nodes.find((n) => n.id === "core-1")!;
    expect(core.keystone).toBe(true);
    expect(core.band).toBe("Fair");
    expect(core.degree).toBe(2);
  });

  it("is deterministic — the same input always lays out identically", () => {
    expect(JSON.stringify(layout(raw))).toBe(JSON.stringify(layout(raw)));
  });

  it("works on fresh copies — the caller's raw graph is never mutated", () => {
    const before = JSON.stringify(raw);
    layout(raw);
    expect(JSON.stringify(raw)).toBe(before); // ids on raw.edges stay strings, no x/y leaks onto raw.nodes
  });

  it("handles an empty graph without error", () => {
    const out = layout({ nodes: [], edges: [] });
    expect(out.nodes).toEqual([]);
    expect(out.links).toEqual([]);
  });

  it("puts unclassified (blank-role) switches in the LAST lane — coverage-honest, never guessed into a tier", () => {
    const { nodes, lanes } = layout({
      nodes: [
        { id: "mystery", band: "", score: null, role: "", degree: 0, keystone: false },
        { id: "core-1", band: "Good", score: 90, role: "core", degree: 0, keystone: false },
      ],
      edges: [],
    });
    expect(lanes[lanes.length - 1].label).toBe("UNCLASSIFIED");
    const y = (id: string) => nodes.find((n) => n.id === id)!.y;
    expect(y("mystery")).toBeGreaterThan(y("core-1"));
  });

  it("wraps a fleet-scale lane into multiple rows instead of one endless strip", () => {
    const many = Array.from({ length: 25 }, (_, i) => ({
      id: `acc-${String(i).padStart(2, "0")}`, band: "Good", score: 80, role: "access", degree: 0, keystone: false,
    }));
    const { nodes, lanes } = layout({ nodes: many, edges: [] });
    const ys = new Set(nodes.map((n) => n.y));
    expect(ys.size).toBe(3); // 25 nodes at 10/row → 3 rows
    expect(lanes[0].count).toBe(25);
  });

  it("arcs same-row links over the lane (both anchors on the top edges, control points above)", () => {
    const { links } = layout({
      nodes: [
        { id: "core-1", band: "Good", score: 90, role: "core", degree: 1, keystone: false },
        { id: "core-2", band: "Good", score: 88, role: "core", degree: 1, keystone: false },
      ],
      edges: [{ source: "core-1", target: "core-2", is_bridge: false, pairs_cut: 0 }],
    });
    const l = links[0];
    expect(l.a.y).toBeCloseTo(l.source.y - 25);
    expect(l.b.y).toBeCloseTo(l.target.y - 25);
    const path = linkPath(l);
    const ctrlY = Number(path.split("C")[1].trim().split(/[ ,]/)[1]);
    expect(ctrlY).toBeLessThan(l.a.y); // the cable lifts above the chassis row
  });
});

describe("switchMesh — three.js node geometry (headless, no WebGL)", () => {
  it("builds a chassis Group with the full port/SFP/LED structure", () => {
    const mesh = switchMesh("rgb(255,0,0)", 3, false);
    expect(mesh).toBeInstanceOf(THREE.Group);
    // chassis body + face-plate + 2 port strips + 2 SFP cages + 1 status LED
    expect(mesh.children).toHaveLength(7);
  });

  it("tints the chassis body from the resolved band colour string", () => {
    const body = switchMesh("rgb(255,0,0)", 1, false).children[0] as THREE.Mesh;
    const color = (body.material as THREE.MeshStandardMaterial).color;
    expect(color.r).toBeCloseTo(1);
    expect(color.g).toBeCloseTo(0);
    expect(color.b).toBeCloseTo(0);
  });

  it("scales the chassis width with node degree (bigger fan-out = wider switch)", () => {
    // w = 7 + min(11, degree); the BoxGeometry's width param records it
    const small = switchMesh("rgb(0,0,0)", 1, false).children[0] as THREE.Mesh;
    const large = switchMesh("rgb(0,0,0)", 9, false).children[0] as THREE.Mesh;
    const w = (m: THREE.Mesh) => (m.geometry as THREE.BoxGeometry).parameters.width;
    expect(w(large)).toBeGreaterThan(w(small));
  });
});

describe("topoNodeLabel — the 3D tooltip is XSS-safe", () => {
  // react-force-graph-3d renders a STRING nodeLabel via `tooltipEl.html(content)` (innerHTML), so a
  // device-derived id/band must be HTML-escaped or a crafted uploaded snapshot lands stored XSS (no CSP).
  it("HTML-escapes a device-derived node id so no live markup reaches the innerHTML tooltip", () => {
    const label = topoNodeLabel({ id: 'SW1<img src=x onerror=alert(document.domain)>', band: "Good", score: 80 });
    // XSS-safety = no raw angle bracket survives, so .html() can parse NO element (the onerror text
    // remaining as inert characters is harmless without a tag to attach to).
    expect(label).not.toContain("<");             // NON-VACUOUS: the raw template contains "<img"
    expect(label).not.toContain(">");
    expect(label).toContain("&lt;img");            // the payload is rendered as inert escaped text instead
  });

  it("also escapes a malformed band, and leaves a normal label byte-for-byte intact", () => {
    expect(topoNodeLabel({ id: "n", band: "<b>x</b>" })).not.toContain("<b>");
    expect(topoNodeLabel({ id: "SW-CORE-1", band: "Good", score: 80 })).toBe("SW-CORE-1 · Good 80");
    expect(topoNodeLabel({ id: "R1", band: "Critical", score: 12, keystone: true }))
      .toBe("R1 · Critical 12 · keystone");
  });
});
