import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { layout } from "./TopologyGraph";
import { switchMesh } from "./Topology3D";

// The signature feature's PURE logic, tested without a GPU: the d3-force graph positioning and the
// three.js node-geometry builder both run headless (only the react-force-graph WebGL *render* needs a
// browser — that is Playwright/E2E territory, deliberately out of jsdom scope, see vite.config).

describe("layout — d3-force graph positioning", () => {
  const raw = {
    nodes: [{ id: "core", degree: 2 }, { id: "dist", degree: 1 }, { id: "acc", degree: 1 }],
    edges: [{ source: "core", target: "dist" }, { source: "core", target: "acc" }],
  };

  it("clamps every node into the padded viewbox and keeps coordinates finite", () => {
    const { nodes } = layout(raw);
    expect(nodes).toHaveLength(3);
    for (const n of nodes) {
      expect(Number.isFinite(n.x)).toBe(true);
      expect(Number.isFinite(n.y)).toBe(true);
      expect(n.x).toBeGreaterThanOrEqual(26); // W=840, clamp pad 26
      expect(n.x).toBeLessThanOrEqual(814); //   840 - 26
      expect(n.y).toBeGreaterThanOrEqual(26); // H=470
      expect(n.y).toBeLessThanOrEqual(444); //   470 - 26
    }
  });

  it("resolves edge endpoints from ids to the actual node objects (forceLink)", () => {
    const { links } = layout(raw);
    expect(links).toHaveLength(2);
    expect((links[0].source as unknown as { id: string }).id).toBe("core");
    expect((links[0].target as unknown as { id: string }).id).toBe("dist");
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
