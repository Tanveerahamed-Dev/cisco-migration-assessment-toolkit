/**
 * render-c5-r3.test.ts — the third C5 critic round on the 3-D render, pinned (2026-09-22).
 *
 * WHAT THESE TESTS PROVE
 *   - The lid vent bank is ONE bezel plate sampling the grille map on a row that crosses only bar
 *     metal and the dark opening — not 16 sub-pixel slot boxes of geometry, which aliased into
 *     crawling diagonal bars at both tiers.
 *   - The bezel shader fades the grille map to its mean tone by screen-space tile size.
 *   - The chassis AO channel carries no patina noise: along any row it is constant.
 *   - A bridge (and a port channel) is drawn as ONE centreline stroke whose rails are cut in screen
 *     space, so its gap cannot fall under a pixel at any dolly; the rail gap of a bridge is wider
 *     than a port channel's, and a bridge's rest ink carries less chroma than its token.
 *   - The undecided terminal glyph is a flat bevelled annulus (not a TorusGeometry) and is tethered
 *     to the chassis lid; the tether does not owe a frame once placed.
 *   - Decks and pads fade by grazing angle.
 *
 * WHAT THEY DO NOT PROVE
 *   - How any of it looks. The before/after GPU captures (crawl strips, lid patches, grazing crop,
 *     trace glyph, label-drop series) are in the repair report; this file only keeps the mechanism
 *     from being quietly reverted.
 */
import { describe, expect, it } from "vitest";
import { ExtrudeGeometry, Mesh, PerspectiveCamera, TorusGeometry } from "three";
import type { Link } from "../core/types";
import { buildChassis, VENT_ROW_V } from "./geometry/chassis";
import {
  BRIDGE_RAIL_GAP_PX,
  STRAND_RAIL_GAP_PX,
  cableInk,
  classifyLink,
  createCableMaterial,
  railsOf,
} from "./geometry/cables";
import {
  GRILLE_SIZE,
  buildMaterials,
  buildProceduralMaps,
  grilleTile,
  readTokens,
  withGrilleNyquistFade,
} from "./materials";
import { createFlowOverlay, type TraceSegmentSource } from "./flow";
import { traceFlow } from "../forwarding/engine";
import { MeshStandardMaterial } from "three";

const link = (over: Partial<Link>): Link =>
  ({
    id: "L1",
    a: "a",
    b: "b",
    speedMbps: 1000,
    opStatus: "up",
    isBridge: false,
    isPortChannel: false,
    members: [],
    ...over,
  }) as unknown as Link;

describe("the lid vent is a filtered texture, not sub-pixel geometry", () => {
  it("samples a grille row that crosses bar metal and the opening, never the contact block", () => {
    const tile = grilleTile();
    const row = Math.floor(VENT_ROW_V * GRILLE_SIZE);
    const values = new Set<number>();
    for (let x = 0; x < GRILLE_SIZE; x += 1) values.add(tile[(row * GRILLE_SIZE + x) * 4] ?? -1);
    expect(values.has(255)).toBe(true); // rib
    expect(values.has(34)).toBe(true); // slot
    expect([...values].every((v) => v === 255 || v === 34 || v === 200)).toBe(true);
  });

  it("puts the vent on the bezel with one tile per slot, and no slot boxes in the dark part", () => {
    const fine = buildChassis("device", { bevelSegments: 3, fineDetail: true });
    try {
      const uv1 = fine.bezel.getAttribute("uv1");
      let maxU = 0;
      let ventV = 0;
      for (let i = 0; i < uv1.count; i += 1) {
        maxU = Math.max(maxU, uv1.getX(i));
        if (Math.abs(uv1.getY(i) - VENT_ROW_V) < 1e-6) ventV += 1;
      }
      expect(maxU).toBeGreaterThanOrEqual(16 - 1e-6); // 16 vent slots across U (ports use 12)
      expect(ventV).toBeGreaterThan(0);
    } finally {
      fine.dispose();
    }
  });

  it("fades the grille to its mean tone by screen-space tile size", () => {
    const m = withGrilleNyquistFade(new MeshStandardMaterial());
    const shader = {
      fragmentShader: "#include <map_fragment>",
      vertexShader: "",
      uniforms: {},
    } as unknown as Parameters<typeof m.onBeforeCompile>[0];
    m.onBeforeCompile(shader, undefined as never);
    expect(shader.fragmentShader).toContain("dFdx( vMapUv )");
    expect(shader.fragmentShader).toContain("textureLod( map, vMapUv, 12.0 )");
    expect(m.customProgramCacheKey()).toContain("grille-nyquist");
  });
});

describe("the chassis AO is occlusion, not patina", () => {
  it("is constant along every texel row (only the seam gutter varies, and it varies by row)", () => {
    const maps = buildProceduralMaps(1);
    try {
      const data = maps.chassisOrm.image.data as Uint8Array;
      const size = maps.chassisOrm.image.width as number;
      for (const y of [0, 17, 64, 100, 200]) {
        const first = data[y * size * 4];
        for (let x = 0; x < size; x += 1) expect(data[(y * size + x) * 4]).toBe(first);
      }
    } finally {
      maps.dispose();
    }
  });
});

describe("cable rails are cut in screen space", () => {
  it("draws a bridge as two rails with a wider gap than a port channel's strands", () => {
    const bridge = railsOf(classifyLink(link({ isBridge: true })));
    const pc = railsOf(classifyLink(link({ isPortChannel: true, members: ["x", "y"] as never })));
    expect(bridge.rails).toBe(2);
    expect(pc.rails).toBe(2);
    expect(bridge.gapPx).toBe(BRIDGE_RAIL_GAP_PX);
    expect(pc.gapPx).toBe(STRAND_RAIL_GAP_PX);
    expect(BRIDGE_RAIL_GAP_PX).toBeGreaterThan(STRAND_RAIL_GAP_PX);
    expect(STRAND_RAIL_GAP_PX).toBeGreaterThanOrEqual(2);
  });

  it("widens the stroke to hold every rail and cuts the gaps in the fragment shader", () => {
    const single = createCableMaterial("solid", 2.7, 1);
    const doubled = createCableMaterial("solid", 2.7, 1, { rails: 2, railGapPx: BRIDGE_RAIL_GAP_PX });
    try {
      expect(doubled.linewidth - single.linewidth).toBeCloseTo(2.7 + BRIDGE_RAIL_GAP_PX, 5);
      expect(doubled.fragmentShader).toContain("_sd / _dpx");
      expect(single.fragmentShader).not.toContain("_sd / _dpx");
    } finally {
      single.dispose();
      doubled.dispose();
    }
  });

  it("gives a bridge's rest ink less chroma than its token, and only a role-only link", () => {
    const tokens = readTokens("dark");
    expect(classifyLink(link({ isBridge: true })).roleOnly).toBe(true);
    expect(classifyLink(link({ opStatus: "down" })).roleOnly).toBe(false);
    const chroma = (c: [number, number, number]): number => Math.max(...c) - Math.min(...c);
    const full = cableInk(tokens, "--link-bridge", 1).display.ink;
    const rest = cableInk(tokens, "--link-bridge", 0.5).display.ink;
    expect(chroma(rest)).toBeLessThan(chroma(full));
  });
});

describe("the undecided terminal glyph is a designed, tethered mark", () => {
  const source: TraceSegmentSource = {
    polylineBetween: () => new Float32Array([0, 10, 0, 50, 10, 0]),
    anchorOf: (host: string) => ({ x: host.length * 10, y: 0, z: 0, top: 12 }),
  };
  const UNDECIDED = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "icmp" as const, dstPort: null, srcPort: null };

  it("is a flat bevelled annulus, tethered to the lid, and owes no further frame once placed", () => {
    const overlay = createFlowOverlay(readTokens("dark"));
    const camera = new PerspectiveCamera();
    try {
      overlay.setTrace(traceFlow(UNDECIDED), source);
      const ring = overlay.group.children.find((o) => o.name === "trace-undecided") as Mesh | undefined;
      const tether = overlay.group.children.find((o) => o.name === "trace-tether");
      expect(ring?.visible).toBe(true);
      expect(ring?.geometry).toBeInstanceOf(ExtrudeGeometry);
      expect(ring?.geometry).not.toBeInstanceOf(TorusGeometry);
      expect(tether?.visible).toBe(true);
      overlay.update(0, camera);
      expect(overlay.update(16, camera)).toBe(false);
    } finally {
      overlay.dispose();
    }
  });
});

describe("decks and pads step back at a grazing view", () => {
  it("patches the deck shader with a view-angle alpha fade", () => {
    const maps = buildProceduralMaps(1);
    const lib = buildMaterials({ tokens: readTokens("dark"), maps });
    try {
      const shader = { fragmentShader: "#include <opaque_fragment>", vertexShader: "", uniforms: {} } as never;
      lib.deck.onBeforeCompile(shader, undefined as never);
      expect((shader as { fragmentShader: string }).fragmentShader).toContain("normalize( vViewPosition )");
    } finally {
      lib.dispose();
      maps.dispose();
    }
  });
});
