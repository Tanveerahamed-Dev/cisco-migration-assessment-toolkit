/**
 * scene.test.ts — what can be proven about the 3-D subsystem without a GPU, and nothing else.
 *
 * WHAT THESE TESTS PROVE
 *   - Every device in the real compiled snapshot becomes exactly one object in the scene graph,
 *     including the three the collector never reached.
 *   - Every link with two placed endpoints becomes drawn segments, and the honesty encoding on
 *     those segments matches the snapshot's own nulls.
 *   - The per-instance recession attribute exists on every geometry whose material reads it — the
 *     fail-safe that keeps a forgotten attribute from receding the whole fabric.
 *   - Materials satisfy the authoring bands the design brief sets.
 *   - `dispose()` releases geometries and is idempotent.
 *   - The render loop body allocates nothing.
 *
 * WHAT THEY DO NOT PROVE, stated plainly rather than faked with a skip:
 *   - Nothing here renders a pixel. jsdom has no WebGL context, so `WebGLRenderer`, the
 *     PMREM environment prefilter and the whole `EffectComposer` chain are never constructed. The
 *     post-processing pass ORDER, the colour-management assertions, SSAO quality, bloom
 *     thresholding, shadow-map fitting and the measured frame rate are all unverified by this file
 *     and are verified by the capture harness against a real browser instead.
 *   - The allocation test is STRUCTURAL: it reads the render loop's source and asserts the body
 *     constructs nothing. It cannot see allocations inside the functions that body calls, and it
 *     is not a heap measurement.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Color, InstancedMesh, MeshStandardMaterial } from "three";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { buildFabricGraph, createScene, runWarmupPassStep } from "./scene";
import { classifyLink, createCableMaterial, routeCable, surfaceAnchor } from "./geometry/cables";
import { buildStudioRig, disposeScene } from "./env";
import { checkAuthoringBands, readTokens, RECEDE_ATTRIBUTE } from "./materials";
import { chooseQuality, profileFor, type GpuCapabilities } from "./quality";
import { Vector3 } from "three";
import ts from "typescript";
import { describeGolden } from "../test-support/golden-sample";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];
const layout = computeLayout({ devices, links, tiers: fabricJson.tiers });
const profile = profileFor("high");

function buildDark() {
  return buildFabricGraph({ devices, links, layout, theme: "dark", profile });
}

describe("buildFabricGraph — every device is placed, none is omitted", () => {
  it("creates exactly one instance slot per device in the layout", () => {
    const graph = buildDark();
    try {
      expect(graph.order).toHaveLength(devices.length);
      const ids = new Set(graph.order.map((s) => s.id));
      expect(ids.size).toBe(devices.length);
      for (const d of devices) expect(ids.has(d.id)).toBe(true);
    } finally {
      graph.dispose();
    }
  });

  it("renders uncollected devices rather than dropping them", () => {
    const graph = buildDark();
    try {
      const uncollected = devices.filter((d) => !d.collected);
      // Guard the guard: if the snapshot ever stops carrying topology-only devices this test would
      // silently become vacuous, which is the exact failure mode it exists to catch elsewhere.
      expect(uncollected.length).toBeGreaterThan(0);

      const ghostSlots = graph.order.filter((s) => s.ghost);
      expect(ghostSlots.map((s) => s.id).sort()).toEqual(uncollected.map((d) => d.id).sort());

      let ghostInstances = 0;
      for (const group of graph.groups.values()) {
        if (group.ghost !== null) ghostInstances += group.ghost.count;
      }
      expect(ghostInstances).toBe(uncollected.length);

      // ...and they carry the two positive "not observed" marks, not merely a different colour.
      // Two decal meshes, one per lid shape (rectangular rack lids, the round access-point lid).
      expect(graph.hatch !== null || graph.hatchRound !== null).toBe(true);
      expect((graph.hatch?.count ?? 0) + (graph.hatchRound?.count ?? 0)).toBe(uncollected.length);
      expect(graph.ghostEdges).not.toBeNull();
    } finally {
      graph.dispose();
    }
  });

  it("gives a device with no observed role the outlined glyph, not no glyph", () => {
    const graph = buildDark();
    try {
      const unobserved = devices.filter((d) => d.role === null).length;
      expect(unobserved).toBeGreaterThan(0);
      const glyph = graph.roleGlyphs.find((m) => m.name === "role:unobserved");
      expect(glyph).toBeDefined();
      expect(glyph?.count).toBe(unobserved);

      const total = graph.roleGlyphs.reduce((n, m) => n + m.count, 0);
      expect(total).toBe(devices.length);
    } finally {
      graph.dispose();
    }
  });

  it("encodes operational state as a ring SHAPE, so it survives a greyscale capture", () => {
    const graph = buildDark();
    try {
      const byShape = new Map(graph.stateRings.map((m) => [m.name, m.count]));
      expect([...byShape.values()].reduce((a, b) => a + b, 0)).toBe(devices.length);

      const unknown = devices.filter((d) => d.opStatus !== "up" && d.opStatus !== "down").length;
      expect(unknown).toBeGreaterThan(0);
      expect(byShape.get("state:dashed")).toBe(unknown);

      const up = devices.filter((d) => d.opStatus === "up").length;
      expect(byShape.get("state:solid")).toBe(up);
    } finally {
      graph.dispose();
    }
  });

  it("tints a null health band as indeterminate, never as a healthy band", () => {
    const graph = buildDark();
    try {
      const tokens = readTokens("dark");
      const indeterminate = tokens.color("--claim-indeterminate");
      const good = tokens.color("--band-good");
      /* EVERY null-band device, whatever its collection state (O38, repair wave 7). This loop used to
         judge only the COLLECTED null-band devices while its precondition counted both kinds; on the
         compiled snapshot there are 0 collected and 3 uncollected, so the colour assertion never
         ran. The loop's own set is now the denominator, and each device is judged by the colour the
         scene actually draws for it: a collected chassis by its body's instance colour, an
         uncollected one by its translucent shell (the ghost mesh's material, times any per-instance
         colour it carries). */
      const nullBand = devices.filter((d) => d.band === null);
      expect(nullBand.length, "precondition: the snapshot holds a device with no health band").toBeGreaterThan(0);

      let judged = 0;
      const read = new Color();
      for (const d of nullBand) {
        const slot = graph.slots.get(d.id);
        expect(slot, d.id).toBeDefined();
        expect(slot!.ghost, `${d.id}: drawn as a ghost exactly when it was not collected`).toBe(!d.collected);
        if (slot!.ghost) {
          const shell = slot!.group.ghost;
          expect(shell, d.id).toBeInstanceOf(InstancedMesh);
          const material = shell!.material;
          expect(material, d.id).toBeInstanceOf(MeshStandardMaterial);
          read.copy((material as MeshStandardMaterial).color);
          if (shell!.instanceColor !== null) read.multiply(shell!.getColorAt(slot!.slot, new Color()));
        } else {
          const body = slot!.group.body;
          expect(body, d.id).toBeInstanceOf(InstancedMesh);
          body!.getColorAt(slot!.slot, read);
        }
        // The body carries the band as a wash (mixed toward white), and the shell is mixed toward the
        // stage, so compare direction rather than value: it must lie nearer the indeterminate hue
        // than the "Good" hue.
        const dIndeterminate = hueDistance(read, indeterminate);
        const dGood = hueDistance(read, good);
        expect(dIndeterminate, `${d.id} (${d.collected ? "collected" : "uncollected"})`).toBeLessThan(dGood);
        judged += 1;
      }
      expect(judged, "every null-band device's drawn colour was judged").toBe(nullBand.length);
    } finally {
      graph.dispose();
    }
  });
});

function hueDistance(a: Color, b: Color): number {
  // Compare chromaticity, not brightness: the wash changes luminance by design.
  const na = a.r + a.g + a.b || 1;
  const nb = b.r + b.g + b.b || 1;
  return Math.hypot(a.r / na - b.r / nb, a.g / na - b.g / nb, a.b / na - b.b / nb);
}

describe("buildFabricGraph — every link becomes drawn geometry", () => {
  it("draws a segment run for every link whose endpoints are both placed", () => {
    const graph = buildDark();
    try {
      const placed = new Set(graph.order.map((s) => s.id));
      const drawable = links.filter((l) => placed.has(l.a) && placed.has(l.b));
      expect(drawable.length).toBeGreaterThan(0);

      const drawn = new Set<string>();
      for (const batch of graph.cables.batches) {
        for (const id of batch.segmentLinkIds) drawn.add(id);
      }
      for (const l of drawable) expect(drawn.has(l.id)).toBe(true);
      expect(drawn.size).toBe(drawable.length);
    } finally {
      graph.dispose();
    }
  });

  it("keeps the batch count inside a sane draw-call share", () => {
    const graph = buildDark();
    try {
      // Cables are batched by (dash style, width, opacity). If this ever climbs it means an
      // encoding channel leaked into a material uniform and the budget is about to go with it.
      expect(graph.cables.batches.length).toBeLessThanOrEqual(12);
      expect(graph.cables.batches.length).toBeGreaterThan(0);
    } finally {
      graph.dispose();
    }
  });
});

describe("link encoding honesty, against the real snapshot", () => {
  it("never renders an uncomputed centrality as a measured non-bridge", () => {
    const unmeasured = links.filter((l) => l.isBridge === null);
    expect(unmeasured.length).toBeGreaterThan(0);
    for (const l of unmeasured) {
      const v = classifyLink(l);
      expect(v.notObserved).toContain("centrality");
      expect(v.reason).toContain("centrality not computed");
      expect(v.doubled).toBe(false);
    }
  });

  it("never renders an unobserved speed at the same weight as an observed one", () => {
    const widths = new Set<number>();
    for (const l of links) {
      const v = classifyLink(l);
      if (l.speedMbps === null || l.speedMbps <= 0) {
        expect(v.notObserved).toContain("speed");
      } else {
        widths.add(v.widthPx);
      }
    }
    const unobservedWidth = classifyLink({ ...links[0]!, speedMbps: null }).widthPx;
    for (const w of widths) expect(w).toBeGreaterThan(unobservedWidth);
  });

  it("never draws an unobserved operational state as a solid, up-looking cable", () => {
    const unknown = links.filter((l) => l.opStatus !== "up" && l.opStatus !== "down");
    expect(unknown.length).toBeGreaterThan(0);
    for (const l of unknown) {
      const v = classifyLink(l);
      expect(v.dash).not.toBe("solid");
      expect(v.notObserved).toContain("operational state");
      expect(v.colorToken).toBe("--state-unknown");
    }
  });

  it("lets an observed failure outrank a measurement gap", () => {
    // A link that is DOWN and also unmeasured must read as DOWN: the observed fact is the louder
    // one, and the gap is still reported through notObserved.
    const base = links[0];
    expect(base).toBeDefined();
    const v = classifyLink({ ...base!, opStatus: "down", isBridge: null });
    expect(v.colorToken).toBe("--state-down");
    expect(v.dash).toBe("dashed");
    expect(v.notObserved).toContain("centrality");
  });

  it("draws a port channel as a bundle and claims no member count it does not have", () => {
    const pc = links.filter((l) => l.isPortChannel);
    // The shipped data has port channels, and every one of them lacks a member list (measured:
    // 44 of 44 links carry < 2 members). So the real-data loop exercises ONLY the gap branch; the
    // >= 2-member branch is pinned by the explicit cases below, derived from a real port channel.
    expect(pc.length).toBeGreaterThan(0);
    for (const l of pc) {
      const v = classifyLink(l);
      expect(v.strands).toBeGreaterThanOrEqual(2);
      expect(v.notObserved.includes("port-channel member count")).toBe(l.members.length < 2);
    }
    const base = pc[0]!;
    const cases: Array<[string[], number, boolean]> = [
      [[], 2, true],
      [["Eth1/1"], 2, true],
      [["Eth1/1", "Eth1/2"], 2, false],
      [["Eth1/1", "Eth1/2", "Eth1/3"], 3, false],
      [["Eth1/1", "Eth1/2", "Eth1/3", "Eth1/4", "Eth1/5", "Eth1/6"], 4, false],
    ];
    for (const [members, strands, gap] of cases) {
      const v = classifyLink({ ...base, members });
      expect(v.strands).toBe(strands);
      expect(v.notObserved.includes("port-channel member count")).toBe(gap);
    }
  });
});

/** Cables that run across an endpoint's own lid, and how many links join two chassis that overlap in X/Z (stacked). */
function lidCrossings(graph: ReturnType<typeof buildDark>): { crossings: string[]; stackedSeen: number } {
  const crossings: string[] = [];
  let stackedSeen = 0;
  for (const link of links) {
    const poly = graph.cables.polylines.get(link.id);
    if (poly === undefined) continue;
    const a = graph.slots.get(link.a);
    const b = graph.slots.get(link.b);
    if (a === undefined || b === undefined) continue;
    if (Math.abs(a.centre[0] - b.centre[0]) < a.half[0] + b.half[0] && Math.abs(a.centre[2] - b.centre[2]) < a.half[2] + b.half[2]) {
      stackedSeen += 1;
    }
    for (const s of [a, b]) {
      for (let i = 0; i < poly.length / 3; i += 1) {
        const x = poly[i * 3] ?? 0;
        const y = poly[i * 3 + 1] ?? 0;
        const z = poly[i * 3 + 2] ?? 0;
        if (Math.abs(x - s.centre[0]) < s.half[0] && Math.abs(z - s.centre[2]) < s.half[2] && y > s.centre[1] - s.half[1]) {
          crossings.push(`${link.id} over ${s.id}`);
          break;
        }
      }
    }
  }
  disposeScene(graph.scene);
  return { crossings, stackedSeen };
}
/** [mover, onto]: every vertical link (endpoints on different planes), in link order, whose endpoints no earlier pair
 *  has used — so each mover is moved once and no anchor moves. */
function verticalPairs(): [string, string][] {
  const used = new Set<string>();
  const out: [string, string][] = [];
  for (const l of [...links].sort((x, y) => (x.id < y.id ? -1 : 1))) {
    const a = layout.byId.get(l.a);
    const b = layout.byId.get(l.b);
    if (a === undefined || b === undefined || a.y === b.y || used.has(l.a) || used.has(l.b)) continue;
    used.add(l.a);
    used.add(l.b);
    out.push(a.y > b.y ? [l.b, l.a] : [l.a, l.b]);
  }
  return out;
}
/** The shipped layout with each mover moved onto its partner's X/Z, keeping its own Y plane. */
function stackedLayout(pairs: readonly (readonly [string, string])[]): typeof layout {
  const onto = new Map(pairs);
  const nodes = layout.nodes.map((n) => {
    const t = onto.get(n.id);
    const at = t === undefined ? undefined : layout.byId.get(t);
    return at === undefined ? n : { ...n, x: at.x, z: at.z };
  });
  return { ...layout, nodes, byId: new Map(nodes.map((n) => [n.id, n])) };
}

describe("cable routing", () => {
  it("anchors a cable on the chassis surface, never at its centre", () => {
    const out = new Vector3();
    surfaceAnchor([0, 0, 0], [8, 1.5, 5], [100, 0, 0], out);
    expect(out.x).toBeGreaterThan(8);
    expect(Math.abs(out.z)).toBeLessThan(0.001);
  });

  it("never runs a cable across its own endpoint's lid — including a vertically stacked pair", () => {
    /* Render audit #8. dist1/podacc1 and dist2/podacc2 were stacked (XZ offsets under half a unit),
       so the per-end face choice took OPPOSITE faces and L39/L43 crossed podacc1/podacc2's whole
       footprint while climbing: 13 and 12 of 29 samples over the lid. Asserted on the REAL graph's
       sampled polylines, so it is the producer's output under test, not a re-derivation.

       The shipped layout no longer stacks linked pairs (each layer now steps toward the camera in Z),
       so the stacked case is reconstructed. RE-EXPRESSED 2026-09-29 (P3C-V2-3): the pairs used to be
       typed (podacc1 onto dist1, podacc2 onto dist2), which exist only in the sample — on the rename leg
       the stacked graph stacked nothing and the guard failed as inert. Every VERTICAL link (endpoints on
       different planes) whose endpoints no earlier such link has moved is now stacked, its second
       endpoint moved onto its first's X/Z on its own Y plane; the audited sample pairs are asserted by
       name in the golden block below. Both the shipped graph and the stacked one are asserted. */
    expect(lidCrossings(buildDark()).crossings).toEqual([]);
    const pairs = verticalPairs();
    expect(pairs.length, "the fabric holds a link between two planes to stack").toBeGreaterThan(0);
    const stacked = lidCrossings(buildFabricGraph({ devices, links, layout: stackedLayout(pairs), theme: "dark", profile }));
    expect(stacked.stackedSeen, "the stacked case this guards must exist in the data, or the test is inert").toBeGreaterThanOrEqual(pairs.length);
    expect(stacked.crossings).toEqual([]);
  });

  it("is deterministic: two runs produce identical samples", () => {
    const a = new Float32Array(29 * 3);
    const b = new Float32Array(29 * 3);
    const from = new Vector3(-40, 64, 12);
    const to = new Vector3(70, 0, -18);
    routeCable(from, to, null, 28, a);
    routeCable(from, to, null, 28, b);
    expect(Array.from(a)).toEqual(Array.from(b));
  });

  it("sags a cable without letting it reach the tier below", () => {
    const pts = new Float32Array(29 * 3);
    const from = new Vector3(-120, 64, 0);
    const to = new Vector3(60, 64, 0);
    routeCable(from, to, null, 28, pts);
    let lowest = Infinity;
    for (let i = 0; i < 29; i += 1) lowest = Math.min(lowest, pts[i * 3 + 1] ?? 0);
    expect(lowest).toBeLessThan(64); // it does sag
    expect(64 - lowest).toBeLessThan(32); // ...by well under the 64-unit tier pitch
  });
});

describe("the recession attribute — the fail-safe that keeps the fabric visible", () => {
  it("is present on every geometry whose material reads it", () => {
    const graph = buildDark();
    try {
      for (const group of graph.groups.values()) {
        for (const mesh of group.meshes) {
          expect(mesh.geometry.getAttribute(RECEDE_ATTRIBUTE)).toBeDefined();
        }
        if (group.ghost !== null) {
          expect(group.ghost.geometry.getAttribute(RECEDE_ATTRIBUTE)).toBeDefined();
        }
      }
      for (const batch of graph.cables.batches) {
        expect(batch.object.geometry.getAttribute(RECEDE_ATTRIBUTE)).toBeDefined();
        expect(batch.recede.count).toBe(batch.segmentLinkIds.length);
      }
    } finally {
      graph.dispose();
    }
  });

  it("starts fully present, so a freshly built fabric is never born dimmed", () => {
    const graph = buildDark();
    try {
      for (const group of graph.groups.values()) {
        if (group.recede === null) continue;
        for (let i = 0; i < group.recede.count; i += 1) expect(group.recede.getX(i)).toBe(0);
      }
    } finally {
      graph.dispose();
    }
  });
});

describe("materials", () => {
  it("satisfies the authoring bands in both themes", () => {
    for (const theme of ["dark", "light"] as const) {
      const graph = buildFabricGraph({ devices, links, layout, theme, profile });
      try {
        const violations = checkAuthoringBands(graph.materials.all());
        expect(violations).toEqual([]);
      } finally {
        graph.dispose();
      }
    }
  });

  it("falls back visibly when the stylesheet does not declare a token", () => {
    // jsdom serves no stylesheet, so every token falls back — which is the condition under which
    // the fallback list must be reported rather than silently used.
    const tokens = readTokens("dark");
    expect(tokens.missing.length).toBeGreaterThan(0);
    expect(tokens.color("--accent").getHexString()).not.toBe("ffffff");
  });
});

describe("state mutation does not throw and does not relayout", () => {
  it("accepts selection, hover and highlight against the real graph", () => {
    const graph = buildDark();
    try {
      const before = graph.order.map((s) => [...s.centre] as [number, number, number]);
      // The graph itself is what selection reads; the scene handle needs a GPU, so this asserts the
      // data half — that the ids selection will be given actually resolve to slots and neighbours.
      const first = graph.order[0];
      expect(first).toBeDefined();
      expect(graph.slots.get(first!.id)).toBeDefined();
      expect(graph.neighbours.get(first!.id) ?? []).toBeInstanceOf(Array);
      const after = graph.order.map((s) => s.centre);
      expect(after).toEqual(before);
    } finally {
      graph.dispose();
    }
  });
});

describe("dispose", () => {
  it("releases geometries and empties the scene, idempotently", () => {
    const graph = buildDark();
    let released = 0;
    const watched = [
      ...[...graph.groups.values()].flatMap((g) => g.meshes.map((m) => m.geometry)),
      ...graph.roleGlyphs.map((m) => m.geometry),
      ...graph.stateRings.map((m) => m.geometry),
      ...graph.cables.batches.map((b) => b.object.geometry),
      graph.ground.floor.geometry,
    ];
    expect(watched.length).toBeGreaterThan(5);
    for (const g of watched) g.addEventListener("dispose", () => (released += 1));

    graph.dispose();
    expect(released).toBe(watched.length);
    expect(graph.scene.children).toHaveLength(0);

    // Idempotent: a second call must not throw and must not double-fire.
    const afterFirst = released;
    expect(() => graph.dispose()).not.toThrow();
    expect(released).toBe(afterFirst);
  });
});

describe("quality tiering is explicit", () => {
  const base: GpuCapabilities = {
    webgl2: true,
    maxTextureSize: 16384,
    maxSamples: 8,
    maxAnisotropy: 16,
    rendererName: "Test GPU",
    software: false,
    floatLinearFiltering: true,
    hardwareConcurrency: 16,
    deviceMemoryGb: 16,
  };

  it("always states a reason, including when nothing is wrong", () => {
    const high = chooseQuality(base);
    expect(high.tier).toBe("high");
    expect(high.reasons.length).toBeGreaterThan(0);
  });

  it("drops to low on a software rasteriser and says which one", () => {
    const d = chooseQuality({ ...base, software: true, rendererName: "Google SwiftShader" });
    expect(d.tier).toBe("low");
    expect(d.reasons.join(" ")).toContain("SwiftShader");
    // ...and the low profile must ground objects some other way, or everything floats.
    expect(profileFor("low").shadows).toBe(false);
  });
});

describe("createScene without a GPU", () => {
  it("fails loudly rather than returning a handle that renders nothing", () => {
    // jsdom's canvas has no WebGL context. The required behaviour is a thrown error: a scene that
    // constructed "successfully" and then drew nothing would be reported as working by every
    // caller, which is the silent-degradation failure this subsystem is built to avoid.
    const canvas = document.createElement("canvas");
    expect(() =>
      createScene(
        canvas,
        { devices, links, layout, theme: "dark", reducedMotion: false },
        { onEvent: () => {} },
      ),
      /* Anchored to the failure it is about. A bare `.toThrow()` was satisfied by ANY earlier
         exception — a TypeError from a regression before the renderer is constructed would have
         passed as "fails loudly without a GPU". What throws here is three's WebGLRenderer. */
    ).toThrow(/WebGL context/);
  });
});

describe("shader patches — the two silent-failure classes this subsystem actually hit", () => {
  it("declares the recession attribute in every patched line shader", () => {
    const mat = createCableMaterial("solid", 2, 1);
    try {
      expect(mat.vertexShader).toContain("attribute float aRecede");
      expect(mat.vertexShader).toContain("vRecede = aRecede");
      expect(mat.fragmentShader).toContain("varying float vRecede");
      // The replace targets must still exist in three's source, or the patch is a silent no-op.
      expect(mat.vertexShader).toContain("float aspect = resolution.x / resolution.y;");
      expect(mat.fragmentShader).not.toContain("gl_FragColor = vec4( diffuseColor.rgb, alpha );");
    } finally {
      mat.dispose();
    }
  });

  it("never enables vertexColors on a line that carries no per-segment colour", () => {
    // LineMaterial multiplies by vColor under USE_COLOR, and an absent instanceColor attribute
    // reads as zero — a black line, no error. This is how the trace path first shipped, and the
    // trace, the blocked segment and the uncollected wireframe all use colourless geometry.
    const flowLine = createCableMaterial("solid", 4, 1, { vertexColors: false });
    const batched = createCableMaterial("solid", 2, 1);
    try {
      expect(flowLine.vertexColors).toBe(false);
      expect(batched.vertexColors).toBe(true);
    } finally {
      flowLine.dispose();
      batched.dispose();
    }
  });

  it("builds an environment rig whose brightest source is above 1.0 in linear space", () => {
    // An environment whose peak is 1.0 produces the flat, chalky "unlit" look the brief names as a
    // cheap-render tell: there is nothing for a rough metal to reflect that is brighter than paper.
    for (const theme of ["dark", "light"] as const) {
      const rig = buildStudioRig(theme);
      const peaks: number[] = [];
      rig.traverse((o) => {
        const mat = (o as { material?: { color?: { r: number; g: number; b: number } } }).material;
        if (mat?.color !== undefined) peaks.push(Math.max(mat.color.r, mat.color.g, mat.color.b));
      });
      expect(Math.max(...peaks)).toBeGreaterThan(1);
      // ...and a room, a key, a fill and a bounce — four objects, not one glowing box.
      expect(peaks.length).toBe(4);
      disposeScene(rig);
    }
  });
});

/* TRIPWIRES, NOT F2 EVIDENCE. The describe blocks below tagged "(tripwire: source text)" read
   scene.ts as a string. They catch a known defect shape coming back; they do not exercise
   behaviour, a behaviour-preserving rewrite may trip them, and they must not be counted as F2's
   "tests that exercise real behaviour". The behavioural proof for the render loop is the browser
   harness — `review/capture.mjs app`, which fails closed when the scene handle is absent or the
   render has not settled on screen — cited separately in docs/acceptance.md F2. */
describe("the render loop allocates nothing (tripwire: source text)", () => {
  it("constructs no object inside frame()", () => {
    // Structural, and deliberately so: this reads the source rather than measuring the heap. It
    // cannot see allocations inside the functions frame() calls — those are held to the same rule
    // by review and by the scratch-object convention, not by this assertion.
    const source = readFileSync(resolve(process.cwd(), "src/fabric3d/scene.ts"), "utf8");
    const start = source.indexOf("function frame(now: number): void {");
    expect(start).toBeGreaterThan(-1);
    const end = source.indexOf("\n  function converged()", start);
    expect(end).toBeGreaterThan(start);
    const body = source.slice(start, end);
    expect(body).not.toMatch(/\bnew [A-Z]/);
    // No array or object literal either: both allocate just as surely as a constructor.
    expect(body).not.toMatch(/=\s*\[\]/);
    expect(body).not.toMatch(/=\s*\{\s*\}/);
  });
});

/* ══ E4: an absent frame-rate measurement is never published as a healthy one ═══════════════

   Structural, for the reason the file header already states: jsdom has no WebGL context, so the
   render loop cannot be run here and a heap or timing assertion is not available. What CAN be
   pinned without a GPU is the shape of the defect that was found — the counters were seeded with
   `fpsEma = 60` and `lastFrameMs = 16.7` and published from the first snapshot onward, so the
   status bar read "fabric 60 fps" over a blank canvas with 0 draw calls and 0 programs linked
   while the next frame took 483 ms (review/_audit_perf_fpsema.mjs). The real verification is that
   probe against a browser; this is the tripwire that says a seed came back.
*/
describe("frame-rate telemetry is not seeded with a plausible reading (tripwire: source text)", () => {
  const source = readFileSync(resolve(process.cwd(), "src/fabric3d/scene.ts"), "utf8");

  it("does not initialise the reported frame figures to a healthy value", () => {
    expect(source).toMatch(/let fpsEma = 0;/);
    expect(source).toMatch(/let lastFrameMs = 0;/);
    /* Any assignment of a non-zero LITERAL to either figure, anywhere in the file — not only the
       two historical seeds at their declaration. A later `fpsEma = 60` would otherwise pass. */
    //    Comments are stripped first: the file's own history note quotes the old seeds.
    const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    expect(code).not.toMatch(/\bfpsEma\s*=\s*(?!0\s*;)\d/);
    expect(code).not.toMatch(/\blastFrameMs\s*=\s*(?!0\s*;)\d/);
  });

  it("counts timed frames and refuses to publish a reading before there is one", () => {
    expect(source).toMatch(/let framesTimed = 0;/);
    expect(source).toMatch(/framesTimed \+= 1;/);
    const start = source.indexOf("function emitStats(now: number): void {");
    expect(start).toBeGreaterThan(-1);
    // The whole function, to its closing brace at this indentation — not a fixed-width window.
    const end = source.indexOf("\n  }\n", start);
    expect(end).toBeGreaterThan(start);
    const body = source.slice(start, end);
    // The guard must come BEFORE the throttle, or the first reading escapes on the first call.
    const guard = body.indexOf("if (framesTimed === 0) return;");
    const throttle = body.indexOf("lastStatsEmit");
    expect(guard).toBeGreaterThan(-1);
    expect(guard).toBeLessThan(throttle);
  });

  it("publishes the denominator, so a reader can tell a measurement from a placeholder", () => {
    expect(source).toMatch(/framesTimed: number;/);
    const start = source.indexOf("function snapshot(): SceneStatsEx {");
    expect(start).toBeGreaterThan(-1);
    const end = source.indexOf("\n  }", start);
    expect(source.slice(start, end)).toContain("framesTimed,");
  });
});

/* ══ C5: the scene honours the DOM label layer's "still converging" report ═══════════════════

   (tripwire: source text — an AST read, for the reason the file header states.) FabricLabels.tsx
   calls `scene.reportLabelsConverging?.(converging)` every tick: the DOM's settled pass is
   history-free (F6) and has no dwell, so a name it changed fewer than LABEL_MIN_DWELL_PASSES
   passes ago can blink back the moment the scene settles (MEASURED, capture-motion
   `access12 hidden for only 5 frame(s)`). The behavioural contract is pinned by
   FabricLabels.dwell.test.tsx against a fake scene that behaves as below; this pins that the REAL
   scene is that scene: the report is stored without a render request, `labelsSettled()` stays
   false while it is true, and `converged()` — the one predicate captures wait on — counts it as
   dirty. The second block pins that both label surfaces agree on hover urgency (labelResolve
   `labelUrgent`): a hovered device is urgent only on a still camera. */
describe("the DOM label report and hover urgency are honoured by the scene (tripwire: source text)", () => {
  const file = resolve(process.cwd(), "src/fabric3d/scene.ts");
  const sf = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.ES2023, true, ts.ScriptKind.TS);
  const all = (pred: (n: ts.Node) => boolean): ts.Node[] => {
    const out: ts.Node[] = [];
    const visit = (n: ts.Node): void => {
      if (pred(n)) out.push(n);
      n.forEachChild(visit);
    };
    visit(sf);
    return out;
  };
  const idents = (n: ts.Node): Set<string> => {
    const out = new Set<string>();
    const visit = (m: ts.Node): void => {
      if (ts.isIdentifier(m)) out.add(m.text);
      m.forEachChild(visit);
    };
    visit(n);
    return out;
  };
  const method = (name: string): ts.Node | undefined =>
    all((n) => ts.isMethodDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === name)[0];

  it("declares reportLabelsConverging on the widened scene interface", () => {
    const iface = all((n) => ts.isInterfaceDeclaration(n) && n.name.text === "FabricSceneEx")[0];
    expect(iface).toBeDefined();
    expect(idents(iface!).has("reportLabelsConverging")).toBe(true);
  });

  it("stores the report without requesting a render", () => {
    const m = method("reportLabelsConverging");
    expect(m, "scene.ts implements no reportLabelsConverging: the DOM report is a no-op").toBeDefined();
    const ids = idents(m!);
    expect(ids.has("domLabelsConverging")).toBe(true);
    expect(ids.has("markDirty")).toBe(false);
  });

  it("keeps labelsSettled() false while the DOM layer is still converging", () => {
    const m = method("labelsSettled");
    expect(m).toBeDefined();
    expect(idents(m!).has("domLabelsConverging")).toBe(true);
  });

  it("counts a converging DOM label set as dirty in converged()", () => {
    const fn = all((n) => ts.isFunctionDeclaration(n) && n.name?.text === "converged")[0];
    expect(fn).toBeDefined();
    const dirtyProp = all(
      (n) => ts.isPropertyAssignment(n) && ts.isIdentifier(n.name) && n.name.text === "dirty" && fn!.pos <= n.pos && n.end <= fn!.end,
    )[0] as ts.PropertyAssignment | undefined;
    expect(dirtyProp).toBeDefined();
    expect(idents(dirtyProp!.initializer).has("domLabelsConverging")).toBe(true);
  });

  it("treats a hovered device as urgent only on a still camera, as the DOM layer does", () => {
    const fn = all((n) => ts.isFunctionDeclaration(n) && n.name?.text === "recomputeLabels")[0];
    expect(fn).toBeDefined();
    /* Every condition in recomputeLabels that tests the hovered device must also read the camera's
       motion — directly, or through labelResolve's labelUrgent. */
    const hoverTests = all(
      (n) =>
        fn!.pos <= n.pos &&
        n.end <= fn!.end &&
        ts.isIfStatement(n) &&
        idents(n.expression).has("hoverDevice"),
    ) as ts.IfStatement[];
    expect(hoverTests.length).toBeGreaterThan(0);
    for (const t of hoverTests) {
      const ids = idents(t.expression);
      expect(ids.has("labelsCameraMoving") || ids.has("labelUrgent"), t.expression.getText(sf)).toBe(true);
    }
  });
});

/* ══ E3: the warm-up DRAWS through the interaction visuals' programs, off screen ═══════════════

   MEASURED (release build, Intel iGPU / ANGLE D3D11, fresh browser per trial, WebGL entry points
   wrapped): the first device selection after load linked no program, yet the frame that first drew
   the selection spent 105 ms in `getProgramInfoLog` for `outline-proxy` — the first DRAW through a
   program the warm-up had only compiled. After this, 3 of 3 trials showed no program call in that
   frame and no task over 50 ms on the click's path. The schedule is a pure function, so it is
   executed here with stand-in passes: every step whose enabled prefix does not reach the screen
   renders inside the priming wrapper, the one that reaches the screen never does, and every flag is
   restored afterwards — even when a render throws. */
describe("the pass-by-pass warm-up primes the interaction visuals on every step it does not present", () => {
  const passes = (): { enabled: boolean; renderToScreen: boolean }[] => [
    { enabled: true, renderToScreen: false },
    { enabled: true, renderToScreen: false },
    { enabled: false, renderToScreen: false } /* turned off by the quality profile */,
    { enabled: true, renderToScreen: false },
    { enabled: true, renderToScreen: true },
  ];

  it("primes every step before the presenting one, and never the presenting one", () => {
    const ps = passes();
    const profile = ps.map((p) => p.enabled);
    const log: { step: number; primed: boolean; enabled: boolean[] }[] = [];
    let priming = false;
    const prime = (draw: () => void): void => {
      priming = true;
      try {
        draw();
      } finally {
        priming = false;
      }
    };
    let done = false;
    for (let step = 0; !done; step += 1) {
      done = runWarmupPassStep(ps, profile, step, () => log.push({ step, primed: priming, enabled: ps.map((p) => p.enabled) }), prime);
    }
    expect(log.map((l) => l.primed)).toEqual([true, true, true, true, false]);
    /* The prefix grows one pass per step, and a pass the profile turned off stays off. */
    expect(log[1]?.enabled).toEqual([true, true, false, false, false]);
    expect(log[4]?.enabled).toEqual([true, true, false, true, true]);
    expect(ps.map((p) => p.enabled), "every flag restored").toEqual(profile);
  });

  it("restores every pass flag even when the render throws", () => {
    const ps = passes();
    const profile = ps.map((p) => p.enabled);
    expect(() =>
      runWarmupPassStep(ps, profile, 1, () => {
        throw new Error("lost context");
      }, (draw) => draw()),
    ).toThrow("lost context");
    expect(ps.map((p) => p.enabled)).toEqual(profile);
  });
});

/* ══ C5 (2026-09-23): the scene feeds the motion rules what they judge (tripwire: source text) ════

   The rules themselves are stepped frame by frame where they live (postfx.ts `nextHistoryWeight` in
   render-c5-r4.test.ts; stepdown.ts `createTierFadeHold` in stepdown.fadehold.test.ts). jsdom has
   no WebGL, so `frame` cannot run here; what CAN be pinned is that the render loop hands each rule
   the inputs its tests assume — a rule stepped on inputs the scene never supplies proves nothing.
   The pixels are review/capture-motion.mjs's evidence. */
/* ── Every place a source file touches the DOM, found by TYPE (R4-V1-1, R4-VR1-2; verifier 2026-09-27) ──
 *
 * The C5-R2-1 tripwire first enumerated a VOCABULARY: ten DOM method names and `=` writes whose left
 * side matched `.style.` or `.style[`. A one-frame cut written `running.el.style.setProperty("opacity",
 * "0")` passed it, and so would `removeProperty`, `setAttribute("style" | "hidden")`, `hidden = true`,
 * `classList.*` or `className =`. A longer list is the same defect. The class is decided by the type
 * checker instead: anything whose type is declared by the DOM library (lib.dom*.d.ts) is DOM.
 *
 * Verifier round 1 of R4 then reached the overlay through a value that is not DOM but HOLDS DOM: the
 * overlay RECORD, cast to a structural type (`(rec as { el: { remove(): void } }).el.remove()`), which
 * no rule saw because only the cast of a DOM value was a site. So a type's DOM is followed where it is
 * held: every DOM "path" in it (a property, an element of an array, a type argument — a slot built over
 * `HTMLCanvasElement` holds one), to a stated depth. A site is any of
 *   - a call on a DOM, `any`/`unknown`, or DOM-carrying generic receiver                 `call`
 *   - a DOM (or DOM-carrying generic) value handed to any call                           `arg`
 *   - a write, `delete` or `++`/`--` of a member of a DOM (or `any`/`unknown`) receiver   `write`
 *   - a DOM value put into an object or array literal                                    `member`
 *   - a value that holds DOM at some path flowing where that path is not DOM: an `as`, an
 *     annotated binding, `=`, an argument, a `return`, a literal's property, or a callback's
 *     annotated parameter — every place the checker checks assignability                `launder`
 *   - a METHOD read off a DOM or DOM-carrying receiver anywhere but the callee of a call
 *     made in place: a member access (`const drop = slot.dispose`, `Reflect.apply(slot.dispose,
 *     …)`, `slot.dispose.call(…)`, `slot["dispose"]` handed on) or a destructuring binding or
 *     assignment (`const { dispose: drop } = slot`)                                      `extract`
 * so no DOM effect reaches an element without passing one of them: to change it, the element must be
 * called, written or handed to code that does, and hiding its type anywhere it is held is itself a
 * site. Verifier round 2 of R4 (R4-VR2-1) called the slot's `dispose` through a value read off it
 * (`const drop = tierFade.dispose; drop()`, a destructure, `Reflect.apply`), and the slot's methods
 * close over their state, so the call through the value is a real removal the `call` rule never saw:
 * `drop()` has no DOM receiver and a function value carries no DOM. The method VALUE leaving the
 * receiver is the site, found by the receiver's type, whatever the method is named. Reads of data
 * are not sites. */
const DOM_LIB = /[\\/]lib\.dom(\.[a-z]+)*\.d\.ts$/;
function isDomType(t: ts.Type): boolean {
  if (t.isUnionOrIntersection()) return t.types.some(isDomType);
  const sym = t.aliasSymbol ?? t.getSymbol();
  return sym?.declarations?.some((d) => DOM_LIB.test(d.getSourceFile().fileName)) ?? false;
}
/** How deep a held DOM value is followed (`a.b.c.d`). */
const DOM_PATH_DEPTH = 4;
const LOOSE = ts.TypeFlags.Any | ts.TypeFlags.Unknown;
function typeArgs(checker: ts.TypeChecker, t: ts.Type): readonly ts.Type[] {
  const ref =
    (t.flags & ts.TypeFlags.Object) !== 0 && ((t as ts.ObjectType).objectFlags & ts.ObjectFlags.Reference) !== 0
      ? checker.getTypeArguments(t as ts.TypeReference)
      : [];
  return [...(t.aliasTypeArguments ?? []), ...ref];
}
/** The stored members of `t` (not a method or a function-valued property: those hold no element). */
function storedProps(checker: ts.TypeChecker, t: ts.Type): { name: string; type: ts.Type }[] {
  const out: { name: string; type: ts.Type }[] = [];
  for (const p of checker.getPropertiesOfType(t)) {
    const decl = p.valueDeclaration ?? p.declarations?.[0];
    if (decl === undefined || ts.isMethodSignature(decl) || ts.isMethodDeclaration(decl)) continue;
    const pt = checker.getTypeOfSymbolAtLocation(p, decl);
    if (pt.getCallSignatures().length > 0) continue;
    out.push({ name: p.name, type: pt });
  }
  return out;
}
/* WHERE a held element is followed. An element this file creates can only come to be held by a type
   this project declares (a record, an object literal, a slot) or by a language container (an array, a
   Map, a Promise: their type arguments and elements). A library's own object graph (three.js: a
   texture's image, a renderer's canvas) is not followed — putting an element INTO one is already a
   site (`arg`, `member`, or the `launder` of a DOM value written to a non-DOM member). */
const TS_LIB = /[\\/]typescript[\\/]lib[\\/]lib\.[a-z0-9.]+\.d\.ts$/;
function origin(t: ts.Type): "project" | "lib" | "library" {
  const decl = (t.aliasSymbol ?? t.getSymbol())?.declarations?.[0];
  if (decl === undefined) return "project";
  const file = decl.getSourceFile().fileName;
  if (TS_LIB.test(file)) return "lib";
  return /[\\/]node_modules[\\/]/.test(file) ? "library" : "project";
}
/** Every path at which `t` holds a DOM value ("" is `t` itself; `<i>` a type argument; `[]` an element). */
function domPaths(checker: ts.TypeChecker, t: ts.Type, memo: Map<ts.Type, string[]>, depth = DOM_PATH_DEPTH, seen: Set<ts.Type> = new Set()): string[] {
  if (isDomType(t)) return [""];
  if (depth === 0 || (t.flags & LOOSE) !== 0 || seen.has(t)) return [];
  if (!t.isUnionOrIntersection() && origin(t) === "library") return [];
  const top = depth === DOM_PATH_DEPTH;
  const cached = top ? memo.get(t) : undefined;
  if (cached !== undefined) return cached;
  seen.add(t);
  const out = new Set<string>();
  const join = (head: string, p: string): string => (p === "" ? head : `${head}.${p}`);
  if (t.isUnionOrIntersection()) {
    for (const u of t.types) for (const p of domPaths(checker, u, memo, depth, seen)) out.add(p);
  } else {
    typeArgs(checker, t).forEach((a, i) => {
      if (domPaths(checker, a, memo, depth - 1, seen).length > 0) out.add(`<${i}>`);
    });
    const el = checker.getIndexTypeOfType(t, ts.IndexKind.Number);
    if (el !== undefined) for (const p of domPaths(checker, el, memo, depth - 1, seen)) out.add(join("[]", p));
    if (origin(t) === "project") for (const { name, type } of storedProps(checker, t)) for (const p of domPaths(checker, type, memo, depth - 1, seen)) out.add(join(name, p));
  }
  seen.delete(t);
  const res = [...out];
  if (top) memo.set(t, res);
  return res;
}
/** Is the value at `segs` in `t` still DOM (so a call or write through it is still a site)? */
function domAt(checker: ts.TypeChecker, t: ts.Type, segs: readonly string[], memo: Map<ts.Type, string[]>): boolean {
  if ((t.flags & LOOSE) !== 0) return false;
  /* A union is DOM where any member is, as `isDomType` reads it: a call or write through it is still a site. */
  if (t.isUnionOrIntersection()) return t.types.some((u) => domAt(checker, u, segs, memo));
  if (segs.length === 0) return isDomType(t);
  const [head, ...rest] = segs as [string, ...string[]];
  if (head.startsWith("<")) {
    const a = typeArgs(checker, t)[Number(head.slice(1, -1))];
    return a !== undefined && domPaths(checker, a, memo).length > 0;
  }
  if (head === "[]") {
    const el = checker.getIndexTypeOfType(t, ts.IndexKind.Number);
    return el !== undefined && domAt(checker, el, rest, memo);
  }
  const p = checker.getPropertyOfType(checker.getApparentType(t), head);
  const decl = p?.valueDeclaration ?? p?.declarations?.[0];
  return p !== undefined && decl !== undefined && domAt(checker, checker.getTypeOfSymbolAtLocation(p, decl), rest, memo);
}
function enclosingPath(n: ts.Node): string {
  const names: string[] = [];
  for (let p: ts.Node | undefined = n.parent; p !== undefined; p = p.parent) {
    if (ts.isFunctionDeclaration(p) && p.name !== undefined) names.unshift(p.name.text);
    else if (ts.isMethodDeclaration(p) && ts.isIdentifier(p.name)) names.unshift(p.name.text);
    else if (ts.isArrowFunction(p) || ts.isFunctionExpression(p)) {
      const q = p.parent;
      names.unshift((ts.isVariableDeclaration(q) || ts.isPropertyAssignment(q)) && ts.isIdentifier(q.name) ? q.name.text : "<anonymous>");
    }
  }
  return names.join(" > ");
}
/** Every DOM site in `sf`, as `kind path :: text` (a repeated one numbered ` #2`, ` #3`…), in source order. */
function domSites(checker: ts.TypeChecker, sf: ts.SourceFile): { key: string; line: number }[] {
  const found: { key: string; line: number }[] = [];
  const memo = new Map<ts.Type, string[]>();
  const typeOf = (n: ts.Node): ts.Type => checker.getTypeAtLocation(n);
  const dom = (n: ts.Node): boolean => isDomType(typeOf(n));
  const loose = (n: ts.Node): boolean => (typeOf(n).flags & LOOSE) !== 0;
  /* A generic built over a DOM type (a slot, a map, a list of elements) carries it. */
  const carries = (n: ts.Node): boolean => typeArgs(checker, typeOf(n)).some((a) => domPaths(checker, a, memo).length > 0);
  const first = (n: ts.Node): string => n.getText(sf).split("\n")[0]!.trim();
  const add = (kind: string, n: ts.Node, text = first(n)): void => {
    found.push({ key: `${kind} ${enclosingPath(n)} :: ${text}`, line: sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1 });
  };
  /** A value that holds DOM somewhere flows into `dst`: is any of those paths no longer DOM there? */
  const launders = (src: ts.Type, dst: ts.Type | undefined): boolean => {
    const paths = domPaths(checker, src, memo).filter((p) => p !== "");
    if (paths.length === 0) return false;
    if (dst === undefined) return true;
    return paths.some((p) => !domAt(checker, dst, p.split("."), memo));
  };
  const onDomReceiver = (e: ts.Expression): boolean => {
    let x: ts.Expression = e;
    while (ts.isParenthesizedExpression(x)) x = x.expression;
    return (ts.isPropertyAccessExpression(x) || ts.isElementAccessExpression(x)) && (dom(x.expression) || loose(x.expression) || carries(x.expression));
  };
  /** A value that is a function (a method pulled off its receiver). */
  const callable = (n: ts.Node): boolean => checker.getNonNullableType(typeOf(n)).getCallSignatures().length > 0;
  /** A DOM or DOM-carrying source a method could be pulled off. */
  const holdsDom = (n: ts.Node): boolean => dom(n) || carries(n);
  /** Is `n` the callee of a call made right here (through parentheses and a non-null assertion)? */
  const calledInPlace = (n: ts.Node): boolean => {
    let x: ts.Node = n;
    while (ts.isParenthesizedExpression(x.parent) || ts.isNonNullExpression(x.parent)) x = x.parent;
    return (ts.isCallExpression(x.parent) || ts.isNewExpression(x.parent)) && x.parent.expression === x;
  };
  const visit = (n: ts.Node): void => {
    /* `typeof x.m` only inspects the value; it cannot hand it on, so it is not an extraction. */
    if ((ts.isPropertyAccessExpression(n) || ts.isElementAccessExpression(n)) && holdsDom(n.expression) && callable(n) && !calledInPlace(n) && !ts.isTypeOfExpression(n.parent))
      add("extract", n);
    if (ts.isBindingElement(n) && (ts.isObjectBindingPattern(n.parent) || ts.isArrayBindingPattern(n.parent)) && holdsDom(n.parent) && callable(n)) add("extract", n);
    if (
      ts.isBinaryExpression(n) &&
      n.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      (ts.isObjectLiteralExpression(n.left) || ts.isArrayLiteralExpression(n.left)) &&
      holdsDom(n.right)
    )
      add("extract", n);
    if (ts.isCallExpression(n) || ts.isNewExpression(n)) {
      if (onDomReceiver(n.expression)) add("call", n);
      for (const a of n.arguments ?? []) {
        if (dom(a) || carries(a)) add("arg", a, `${first(a)} -> ${first(n)}`);
        else if (launders(typeOf(a), checker.getContextualType(a))) add("launder", a, `${first(a)} -> ${first(n)}`);
      }
    }
    if (ts.isBinaryExpression(n) && n.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && n.operatorToken.kind <= ts.SyntaxKind.LastAssignment) {
      if (onDomReceiver(n.left)) add("write", n);
      else if ((dom(n.right) && !dom(n.left)) || launders(typeOf(n.right), typeOf(n.left))) add("launder", n);
    }
    if (ts.isDeleteExpression(n) && onDomReceiver(n.expression)) add("write", n);
    /* A spread copies a source's members out of it (P3C-V2-2: `{ ...tierFade }` took the slot's methods into a
       plain object whose calls no rule saw). A DOM value spread into an object literal is a `member` below. */
    if ((ts.isSpreadAssignment(n) && !dom(n.expression) && carries(n.expression)) || (ts.isSpreadElement(n) && holdsDom(n.expression))) add("extract", n);
    if (
      (ts.isPrefixUnaryExpression(n) || ts.isPostfixUnaryExpression(n)) &&
      (n.operator === ts.SyntaxKind.PlusPlusToken || n.operator === ts.SyntaxKind.MinusMinusToken) &&
      onDomReceiver(n.operand)
    )
      add("write", n);
    if ((ts.isPropertyAssignment(n) && dom(n.initializer)) || (ts.isShorthandPropertyAssignment(n) && dom(n.name)) || (ts.isSpreadAssignment(n) && dom(n.expression))) add("member", n);
    else if (ts.isPropertyAssignment(n) && launders(typeOf(n.initializer), checker.getContextualType(n.initializer))) add("launder", n);
    if (ts.isArrayLiteralExpression(n)) for (const e of n.elements) if (dom(e)) add("member", e);
    if ((ts.isAsExpression(n) || ts.isTypeAssertionExpression(n)) && ((dom(n.expression) && !dom(n)) || launders(typeOf(n.expression), typeOf(n)))) add("launder", n);
    if (ts.isVariableDeclaration(n) && n.type !== undefined && n.initializer !== undefined && ((dom(n.initializer) && !dom(n.name)) || launders(typeOf(n.initializer), typeOf(n.name))))
      add("launder", n);
    if (ts.isReturnStatement(n) && n.expression !== undefined && launders(typeOf(n.expression), checker.getContextualType(n.expression))) add("launder", n);
    if ((ts.isArrowFunction(n) || ts.isFunctionExpression(n)) && n.parameters.some((p) => p.type !== undefined)) {
      /* A callback's annotated parameter re-types what its caller passes in. */
      const sig = checker.getContextualType(n)?.getCallSignatures()[0];
      n.parameters.forEach((p, i) => {
        const given = sig?.parameters[i];
        if (p.type === undefined || given === undefined) return;
        const passed = checker.getTypeOfSymbolAtLocation(given, n);
        if ((isDomType(passed) && !dom(p)) || launders(passed, typeOf(p))) add("launder", p);
      });
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  const seen = new Map<string, number>();
  return found.map((f) => {
    const k = (seen.get(f.key) ?? 0) + 1;
    seen.set(f.key, k);
    return k === 1 ? f : { key: `${f.key} #${k}`, line: f.line };
  });
}

/** What a host does on a reduced-motion toggle, read from its source: it calls the scene's setter (`wired`), and/or
 *  its scene-lifetime effect (the `useEffect` whose body calls `createScene`) lists `reducedMotion` among its
 *  dependencies, so a toggle disposes the scene and builds a new one (`recreates`). */
function hostMotionRoute(hostSource: string): { lifetimeEffects: number; wired: boolean; recreates: boolean } {
  const hostSf = ts.createSourceFile("Fabric3D.tsx", hostSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let wired = false;
  const lifetimeDeps: string[][] = [];
  const scan = (n: ts.Node): void => {
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === "setReducedMotion") wired = true;
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "useEffect" && n.arguments.length === 2) {
      const [body, deps] = n.arguments as unknown as [ts.Expression, ts.Expression];
      if (/\bcreateScene\(/.test(body.getText(hostSf)) && ts.isArrayLiteralExpression(deps)) lifetimeDeps.push(deps.elements.map((e) => e.getText(hostSf)));
    }
    ts.forEachChild(n, scan);
  };
  scan(hostSf);
  return { lifetimeEffects: lifetimeDeps.length, wired, recreates: lifetimeDeps.some((d) => d.includes("reducedMotion")) };
}

describe("R4-V1-1: the DOM-site enumerator sees every way to touch an element, by type (known answers)", () => {
  it("flags each mutation shape the name vocabulary missed, a value hidden behind `any`, and no plain read", () => {
    const PLANTED = [
      /*  1 */ "declare const running: { el: HTMLCanvasElement; driver: { value: number } | null } | null;",
      /*  2 */ 'const el = document.createElement("canvas");',
      /*  3 */ 'el.style.setProperty("opacity", "0");',
      /*  4 */ 'el.style.removeProperty("opacity");',
      /*  5 */ 'el.setAttribute("style", "opacity:0");',
      /*  6 */ "el.hidden = true;",
      /*  7 */ 'el.classList.add("gone");',
      /*  8 */ 'el.className = "gone";',
      /*  9 */ 'el.style.cssText = "opacity:0";',
      /* 10 */ "delete el.dataset.testid;",
      /* 11 */ 'Object.assign(el.style, { opacity: "0" });',
      /* 12 */ '(el as unknown as { style: { opacity: string } }).style.opacity = "0";',
      /* 13 */ "const loose: any = el;",
      /* 14 */ "loose.hidden = true;",
      /* 15 */ "const box = { el };",
      /* 16 */ "el.width++;",
      /* 17 */ 'if (running !== null && running.driver !== null && running.driver.value < 0.9) running.el.style.setProperty("opacity", "0");',
      /* 18 */ "const st = el.style;",
      /* 19 */ 'st.opacity = "0";',
      /* 20 */ "const w: number = el.width;",
      /* 21 */ "const h = running?.el.height ?? 0;",
      /* 22 */ 'el.style["opacity"] = "0";',
      /* 23 */ "export { box, w, h };",
      // R4-VR1-2: a value that HOLDS an element, re-typed so the element is no longer DOM where it is held.
      /* 24 */ "declare const rec: { el: HTMLCanvasElement; driver: null } | null;",
      /* 25 */ "if (rec !== null) (rec as { el: { remove(): void } }).el.remove();",
      /* 26 */ "const r2: { el: { remove(): void } } | null = rec;",
      /* 27 */ "const dropIt = (x: { el: { remove(): void } }): void => x.el.remove();",
      /* 28 */ "if (rec !== null) dropIt(rec);",
      /* 29 */ "const blank: {} = rec ?? {};",
      /* 30 */ "interface Holder<E> { dispose(): void; readonly n: number; readonly _e?: E }",
      /* 31 */ "declare const slot: Holder<HTMLCanvasElement>;",
      /* 32 */ "slot.dispose();",
      /* 33 */ "const opaque = slot as unknown as { n: number };",
      /* 34 */ "const same: { el: HTMLCanvasElement; driver: null } | null = rec;",
      /* 35 */ "const n = rec?.el.width ?? 0;",
      /* 36 */ "const takeCb = (f: (el: HTMLCanvasElement) => void): void => { void f; };",
      /* 37 */ "takeCb((el: { remove(): void }) => el.remove());",
      /* 38 */ "export { r2, blank, opaque, same, n, dropIt, slot };",
      // R4-VR2-1: a slot (or element) METHOD read into a value and called later. Each is found by the
      // receiver's type; the later call through the value has no DOM receiver and is not itself a site.
      /* 39 */ "const drop = slot.dispose;",
      /* 40 */ "drop();",
      /* 41 */ "const { dispose: drop2 } = slot;",
      /* 42 */ "Reflect.apply(slot.dispose, undefined, []);",
      /* 43 */ "slot.dispose.call(undefined);",
      /* 44 */ 'const byKey = slot["dispose"];',
      /* 45 */ "const rm = el.remove;",
      /* 46 */ "let drop3: () => void = () => {}; ({ dispose: drop3 } = slot);",
      /* 47 */ "const count = slot.n;",
      /* 48 */ "(slot.dispose)();",
      /* 49 */ 'const probe = typeof slot.dispose === "function";',
      /* 50 */ "export { drop, drop2, byKey, rm, drop3, count, probe };",
      // P3C-V2-2: the slot SPREAD into a plain object carries its methods out with it; the later call through the
      // copy has no DOM-carrying receiver. The spread is the site (emphasis.ts also makes such a copy inert).
      /* 51 */ "const copy = { ...slot };",
      /* 52 */ "copy.dispose();",
      /* 53 */ "const listed = [...[slot]];",
      /* 54 */ "export { copy, listed };",
    ].join("\n");
    const planted = resolve(process.cwd(), "src/fabric3d/__planted_dom_sites__.ts");
    const opts: ts.CompilerOptions = { target: ts.ScriptTarget.ES2022, lib: ["lib.es2022.d.ts", "lib.dom.d.ts"], types: [], strict: true, noEmit: true };
    const host = ts.createCompilerHost(opts);
    const norm = (f: string): string => resolve(f).toLowerCase();
    const base = { getSourceFile: host.getSourceFile.bind(host), fileExists: host.fileExists.bind(host), readFile: host.readFile.bind(host) };
    host.getSourceFile = (f, lang, ...rest) => (norm(f) === norm(planted) ? ts.createSourceFile(f, PLANTED, lang, true) : base.getSourceFile(f, lang, ...rest));
    host.fileExists = (f) => norm(f) === norm(planted) || base.fileExists(f);
    host.readFile = (f) => (norm(f) === norm(planted) ? PLANTED : base.readFile(f));
    const program = ts.createProgram([planted], opts, host);
    const sf = program.getSourceFiles().find((f) => norm(f.fileName) === norm(planted))!;
    const lines = [...new Set(domSites(program.getTypeChecker(), sf).map((s) => s.line))].sort((a, b) => a - b);
    /* The verifier's own cut (line 17) is among them; 1, 18, 20, 21 and 23 are declarations and reads.
       R4-VR1-2's record cast (25) and every other way to re-type an element where a value holds it —
       an annotated binding (26), an argument (28), a binding that drops the path (29), a slot built
       over the element type called (32) or cast away (33), a callback's annotated parameter (37) —
       are sites; a binding that keeps the element DOM (34) and a read through it (35) are not. */
    /* R4-VR2-1: a method pulled off the slot into a value (39), a destructure (41), `Reflect.apply` (42,
       whose `slot.dispose` is a value handed on), `.call` (43), an element access (44), a method pulled off
       an element (45) and a destructuring ASSIGNMENT (46) are sites; the later call through the value (40)
       is not (the site is where the method left its receiver), a data read off the slot (47) is not, and a
       parenthesised call made in place (48) is the ordinary `call` site, and a `typeof` probe (49) cannot
       hand the method on and is not a site. */
    /* P3C-V2-2: a spread of the slot into an object literal (51) or of a list holding it (53) is a site; the call
       through the copy (52) is not (the site is where the methods left the slot). */
    expect(lines).toEqual([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19, 22, 25, 26, 28, 29, 32, 33, 37, 39, 41, 42, 43, 44, 45, 46, 48, 51, 53]);
  }, 60_000);
});

describe("C5: the render loop feeds the history and tier-fade rules their real inputs (tripwire: source text)", () => {
  const source = readFileSync(resolve(process.cwd(), "src/fabric3d/scene.ts"), "utf8");
  const frameBody = source.slice(source.indexOf("function frame(now: number): void {"), source.indexOf("\n  function converged()"));

  it("the history weight is eased from the weight the last presented frame USED, with the camera's known arrival", () => {
    expect(frameBody).toMatch(/nextHistoryWeight\(\s*post\.historyWeightUsed\(\),\s*cameraStep,\s*contentVersion !== renderedContentVersion,\s*cameraArrivalInMs,\s*raw,?\s*\)/);
    expect(frameBody).not.toMatch(/historyWeightFor\(/);
    /* A tween's landing frame arrives now: the rig stops reporting a tween during this frame's update. */
    expect(frameBody).toMatch(/const tweenBefore = cameraRig\.isTweening\(\);\s*const cameraMoved = cameraRig\.update\(now\);/);
    expect(frameBody).toMatch(/tweenBefore && !tweenAfter\s*\?\s*0/);
  });

  it("the tier change's re-presented snapshot frame is weighted like any other frame, never dropped to plain", () => {
    const snap = source.slice(source.indexOf("function snapshotForTierFade(): boolean {"), source.indexOf("\n  function releaseTierFade("));
    expect(snap).toMatch(/post\.setHistoryWeight\(\s*nextHistoryWeight\(post\.historyWeightUsed\(\), cameraStepSinceRenderPx\(\),[^;]*\);\s*post\.render\(0\);/);
  });

  it("a frame drawn with a history keeps frames coming until the weight has drained, and `converged` waits for it", () => {
    expect(frameBody).toContain("if (historyInLastRender && !cameraMoved) requestFrame();");
    expect(source).toMatch(/dirty: dirty \|\| motionReducedRender \|\| domLabelsConverging \|\| historyInLastRender/);
  });

  it("the tier fade's hold is released by a camera move or a content change since the new tier presented", () => {
    const release = source.slice(source.indexOf("function releaseTierFade(now: number): void {"), source.indexOf("\n  function applyQuality("));
    expect(release).toContain("createTierFadeHold(now)");
    expect(release).toMatch(/hold\.frame\(lastNow, lastFrameMs, lastCameraMotionAt > now \|\| contentVersion !== heldContent\)/);
    expect(release).toContain("setTimeout(once, TIER_FADE_HOLD_DEFAULTS.maxHoldMs)");
    expect(frameBody).toContain("releaseTierFade(now);");
    /* ...and the tier change's own owed re-render is not a content change, or it would release it. */
    expect(frameBody).toMatch(/warmupFrames -= 1;\s*requestFrame\(\);/);
  });

  it("the tier fade is STEPPED by the render loop on the frame's real duration, never a CSS transition (C5, 2026-09-26)", () => {
    /* Graded at 7f67013: opacity 1 -> 0.64 across one 116.6 ms frame, because the fade was a CSS
       transition on the wall clock. The per-frame bound is `stepTierFade` (emphasis.ts, stepped
       under hostile frame sequences in emphasis.test.ts); what is pinned here is that the scene
       drives the overlay through it — with `raw`, not the 64 ms-clamped `dt` — and nowhere else. */
    const snap = source.slice(source.indexOf("function snapshotForTierFade(): boolean {"), source.indexOf("\n  function releaseTierFade("));
    const release = source.slice(source.indexOf("function releaseTierFade(now: number): void {"), source.indexOf("\n  function applyQuality("));
    for (const [where, text] of [["snapshotForTierFade", snap], ["releaseTierFade", release]] as const) {
      expect(text, `${where} sets a CSS transition on the overlay`).not.toMatch(/\.transition\s*=/);
      expect(text, `${where} removes the overlay on a timer tied to the fade's duration`).not.toMatch(/TIER_FADE_MS\s*\+/);
    }
    expect(source, "scene.ts declares its own tier-fade duration instead of the ease owner's").not.toMatch(/const TIER_FADE_MS\s*=/);
    /* The overlay's whole life — hand-over, hold, the driver that steps it (on raw, write, remove at
       exactly 0, no timer), removal — is the ease owner's `createTierFadeSlot`, EXECUTED in
       emphasis.test.ts (R4-VR1-4: it used to be a record scene.ts updated inline, which no unit test
       reached). What is pinned here is the wiring a unit test cannot reach: scene.ts lends the slot the
       page and nothing else, the release hands the slot the new tier's composed frame, and frame()
       drives it on every frame. */
    const lent = source.slice(source.indexOf("const tierFade = createTierFadeSlot<HTMLCanvasElement>({"), source.indexOf("\n  });", source.indexOf("const tierFade = createTierFadeSlot<HTMLCanvasElement>({")));
    expect(lent.replace(/\s+/g, " "), "the page the slot is lent: mount over the canvas, unmount, write the opacity — nothing else").toBe(
      "const tierFade = createTierFadeSlot<HTMLCanvasElement>({ mount: (el) => { canvas.parentElement?.appendChild(el); }, unmount: (el) => { el.remove(); }, write: (el, opacity) => { el.style.opacity = String(opacity); },",
    );
    expect(release).toMatch(/const handle = tierFade\.presented\(reducedMotion\);\s*if \(handle === null\) return;/);
    expect(release.match(/handle\.start\(\)/g) ?? [], "the fade starts only through the hold's handle: once calm (or its backstop), or at once without rAF").toHaveLength(2);
    /* C5-R2-1 (2026-09-27): the driver lends itself NO timer (the slot builds it; emphasis.test.ts). Its
       no-frames watchdog was the one path by which it removed an overlay above 0 (a tab hidden 2.4 s
       came back without it); the removal it asserted is inverted, with the first frame back held to the
       cap, in emphasis.test.ts. The only timer here is the hold's START backstop, which can only start
       a fade, never remove one. */
    expect(source, "scene.ts builds a driver itself instead of through the slot").not.toMatch(/createTierFadeDriver\(/);
    expect(snap + release + frameBody, "scene.ts steps or times the fade itself instead of through the driver").not.toMatch(/stepTierFade\(|createTierFade\(\)|idleWindows/);
    expect(release.match(/setTimeout\([^)]*\)/g) ?? [], "the one timer: the hold's start backstop").toEqual(["setTimeout(once, TIER_FADE_HOLD_DEFAULTS.maxHoldMs)"]);
    /* R4-V1-2: the compose that makes a handover a handover (the running overlay painted into the copy
       at its opacity) is the ease owner's `tierFadeCopy`, executed in emphasis.test.ts against a
       compositing 2-D context. The scene hands it the copy element, that element's context and the
       copy's own size, and composes nothing itself. */
    const copyFn = source.slice(source.indexOf("function copyFrameForTierFade("), source.indexOf("\n  /** Called after a composed frame lands on the canvas"));
    expect(copyFn).toMatch(/const w = canvas\.width;\s*const h = canvas\.height;/);
    expect(copyFn).toMatch(/el\.width = w;\s*el\.height = h;\s*ctx = el\.getContext\("2d"\);/);
    expect(copyFn, "the copy is the owner's compose over this element and its context, at its own size").toMatch(/\n {4}return tierFadeCopy<HTMLCanvasElement>\(el, ctx, w, h\);\n {2}\}\s*$/);
    expect(copyFn, "scene.ts composes the running overlay itself instead of through tierFadeCopy").not.toMatch(/globalAlpha|drawOver/);
    /* UNCONDITIONAL: a statement of frame()'s own body (4-space indent), not inside an if. A guard in
       front of it (the verifier's `&& lastNow < 0` mutation) would leave the overlay at opacity 1.
       Its third argument is `compiled` (R4-V1-4): while a warm-up runs the canvas presents nothing new
       and the driver holds the fade (executed in emphasis.test.ts), so a fade kept across a tier change
       cannot end inside the warm-up and leave the new tier's first frame uncovered. */
    const step = frameBody.search(/\n {4}tierFade\.frame\(raw, reducedMotion, compiled\);\n/);
    expect(step, "frame() drives the tier fade, unconditionally, with the frame's raw duration, holding it while nothing new is presented").toBeGreaterThan(-1);
    /* Before every early return of the frame (the idle, warm-up, yield and step-down paths), so the
       fade advances on frames that render nothing — the overlay is DOM and owes no WebGL render. */
    const firstReturn = frameBody.search(/\n\s*if \(landHeldStepDown\(now\)\) return;/);
    expect(firstReturn).toBeGreaterThan(-1);
    expect(step).toBeLessThan(firstReturn);
    /* Code only (comments stripped): the one `return` above it is `if (disposed) return;`. */
    const code = frameBody.slice(0, firstReturn).replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    expect(code.match(/\breturn\b/g) ?? [], "an early return before the fade is stepped").toEqual(["return"]);
    expect(code).toMatch(/if \(disposed\) return;/);
    /* The overlay leaves on the frame the fade reaches exactly 0, not on a timer. That is the driver's
       rule (emphasis.test.ts), reached through the one call above. */
    expect(frameBody.match(/tierFade\.frame\(/g) ?? [], "the fade is driven once per frame").toHaveLength(1);
  });

  it("C5-R2-1: every site in scene.ts that touches the DOM (by type), or holds it, is a stated non-cutting one", () => {
    /* Verifier round 2: `applyQuality -> snapshotForTierFade -> clearTierFade()` removed a half-faded
       overlay in one frame, outside the driver, so no per-frame bound protected it. The class is
       "a path that takes a running overlay off the screen, or changes what it shows, faster than the
       cap". Its denominator is DERIVED here by the type checker (`domSites` above, whose known answers
       are executed in their own test): every call on, write to, hand-off or re-typing of anything the
       DOM library declares, or of anything that holds it — the tier-fade slot is built over
       `HTMLCanvasElement`, so every call on it is found by its type, as is any alias or cast of it —
       anywhere in the file. Each one found must be one of the sites below, with its reason; a new site
       anywhere, of any shape, fails here until it is justified. (Verifier round 1 of R4 cut a running
       overlay with `running.el.style.setProperty("opacity", "0")`, which the earlier name vocabulary
       did not see, and verifier round 1 of this wave with a structural cast of the overlay record,
       which the DOM-only rules did not see.) The behaviour behind the reasons is executed in
       emphasis.test.ts (`createTierFadeSlot`, `handOverTierFade`, `tierFadeCopy`, the driver, and the
       class through the slot on a model of the screen) and measured by review/capture-motion.mjs. */
    const file = resolve(process.cwd(), "src/fabric3d/scene.ts");
    const cfg = ts.readConfigFile(resolve(process.cwd(), "tsconfig.json"), (f) => ts.sys.readFile(f));
    const parsed = ts.parseJsonConfigFileContent(cfg.config, ts.sys, process.cwd());
    const program = ts.createProgram([file], { ...parsed.options, noEmit: true });
    const sf = program.getSourceFile(file)!;
    const checker = program.getTypeChecker();
    /* The enumeration reasons by TYPE, so it is sound only over a file that type-checks: an error there (a method
       called on a spread copy of the slot, whose type has none — P3C-V2-2) is a value whose type the checker
       could not follow. */
    const diagnostics = [...program.getSyntacticDiagnostics(sf), ...program.getSemanticDiagnostics(sf)].map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
    expect(diagnostics, "scene.ts type-checks, so every value's type is the one the enumeration reads").toEqual([]);
    const found = domSites(checker, sf).map((s) => s.key);
    const NOT_OVERLAY = "not the overlay: ";
    const STATED: Record<string, string> = {
      /* The overlay's own life, in order: created (a NEW element, not yet on the page), handed to the
         slot, which mounts it, steps it through the driver and removes it through the page it is lent. */
      'call createSceneImpl > copyFrameForTierFade :: document.createElement("canvas")': "the copy element for a handover, created off the page",
      "write createSceneImpl > copyFrameForTierFade :: el.width = w": "sizes that NEW element, not yet on the page",
      "write createSceneImpl > copyFrameForTierFade :: el.height = h": "sizes that NEW element, not yet on the page",
      'call createSceneImpl > copyFrameForTierFade :: el.getContext("2d")': "the NEW element's 2-D context, to copy the frame into it",
      "call createSceneImpl > copyFrameForTierFade :: ctx.drawImage(canvas, 0, 0)": "copies the frame the canvas shows into the NEW element (the WebGL canvas is only read)",
      "arg createSceneImpl > copyFrameForTierFade :: canvas -> ctx.drawImage(canvas, 0, 0)": "the WebGL canvas handed to drawImage as a SOURCE: read, not changed",
      'write createSceneImpl > copyFrameForTierFade :: el.className = "fabric3d__tier-fade"': "names the NEW element, not yet on the page (no stylesheet targets the name)",
      'call createSceneImpl > copyFrameForTierFade :: el.setAttribute("aria-hidden", "true")': "the NEW element is decoration: hidden from assistive technology, not from view",
      'write createSceneImpl > copyFrameForTierFade :: el.dataset.testid = "fabric3d-tier-fade"': "the harness's handle on the NEW element, not yet on the page",
      "write createSceneImpl > copyFrameForTierFade :: el.style.cssText =": "the NEW element's box, at opacity 1, before it is mounted",
      "arg createSceneImpl > copyFrameForTierFade :: el -> tierFadeCopy<HTMLCanvasElement>(el, ctx, w, h)": "the NEW element handed to the owner's compose (emphasis.ts tierFadeCopy paints the running overlay INTO it at its opacity)",
      "arg createSceneImpl > copyFrameForTierFade :: ctx -> tierFadeCopy<HTMLCanvasElement>(el, ctx, w, h)": "the NEW element's own 2-D context, for that compose; executed in emphasis.test.ts",
      "call createSceneImpl > mount :: canvas.parentElement?.appendChild(el)": "the page the slot is lent: mounts a `new`/`composed` overlay, which already shows the picture on screen, in the task the one it replaces leaves (emphasis.test.ts)",
      "arg createSceneImpl > mount :: el -> canvas.parentElement?.appendChild(el)": "the overlay being mounted (see the line above)",
      "call createSceneImpl > unmount :: el.remove()": "the page the slot is lent: its one DOM removal, reached only for a replaced overlay, the driver's removal at exactly 0, the reduced-motion swap at exactly 1 of an overlay up under reduced motion throughout, and teardown (emphasis.test.ts)",
      "write createSceneImpl > write :: el.style.opacity = String(opacity)": "the page the slot is lent: the driver's per-frame write, capped at FADE_MAX_STEP (emphasis.test.ts)",
      'call createSceneImpl > snapshotForTierFade :: tierFade.tierChange(copyFrameForTierFade, !compiled)': "a tier change handed to the slot (handOverTierFade's plan); `deferred` is honoured by applyQuality (positions pinned below)",
      "call createSceneImpl > releaseTierFade :: tierFade.presented(reducedMotion)": "the new tier's composed frame handed to the slot: a HELD overlay starts its hold; under reduced motion it is swapped at exactly 1 only if it has been up under reduced motion throughout (§4.8), and otherwise finished at the cap (R4-VR2-4, emphasis.test.ts)",
      "call createSceneImpl > frame :: tierFade.frame(raw, reducedMotion, compiled)": "the slot's driver, once per frame on the raw duration, holding while nothing new is presented (pinned above)",
      "call createSceneImpl > dispose :: tierFade.dispose()": "teardown: the WebGL canvas the overlay covers goes with it",
      /* The WebGL canvas and the rest of the page: none of these reaches an overlay element. */
      "member createSceneImpl :: canvas": NOT_OVERLAY + "the WebGL canvas given to WebGLRenderer at construction",
      "arg createSceneImpl :: canvas -> createCameraRig(canvas, {": NOT_OVERLAY + "the WebGL canvas, whose pointer input the camera rig reads",
      "arg createSceneImpl :: canvas -> createInteraction(": NOT_OVERLAY + "the WebGL canvas, which picking reads",
      "arg createSceneImpl > onPanelInput :: canvas -> isFabricTarget(canvas, e.target)": NOT_OVERLAY + "compares an event target with the WebGL canvas",
      "arg createSceneImpl > onPanelInput :: e.target -> isFabricTarget(canvas, e.target)": NOT_OVERLAY + "an event target, only compared",
      "arg buildFabricGraph :: opts.tokenRoot -> readTokens(opts.theme, opts.tokenRoot)": NOT_OVERLAY + "the element design tokens are READ from",
      "call createSceneImpl :: console.error(": NOT_OVERLAY + "a console report",
      "call createSceneImpl > frame :: console.error(": NOT_OVERLAY + "a console report (the draw-call budget)",
      'call createSceneImpl :: console.error("fabric3d: material authoring band violations", bandViolations)': NOT_OVERLAY + "a console report",
      "call createSceneImpl > mark :: performance.now()": NOT_OVERLAY + "a user-timing clock read for a profile mark",
      "call createSceneImpl > mark :: performance.now() #2": NOT_OVERLAY + "a user-timing clock read for a profile mark",
      "call createSceneImpl > mark :: performance.measure(name, { start: t0, end: performance.now() })": NOT_OVERLAY + "a user-timing measure",
      "call createSceneImpl > <anonymous> :: list.getEntries()": NOT_OVERLAY + "long-task entries read by the observer",
      'call createSceneImpl :: longTaskObserver.observe({ type: "longtask" })': NOT_OVERLAY + "starts the long-task observer",
      "call createSceneImpl > dispose :: longTaskObserver?.disconnect()": NOT_OVERLAY + "stops the long-task observer",
      "arg createSceneImpl > onGestureInput :: e -> gestureStamp(e)": NOT_OVERLAY + "an input event, read for its time stamp",
      "arg createSceneImpl > onGesturePointerDown :: e -> gestureStamp(e)": NOT_OVERLAY + "an input event, read for its time stamp",
      "arg createSceneImpl > onGesturePointerUp :: e -> gestureStamp(e)": NOT_OVERLAY + "an input event, read for its time stamp",
      "arg createSceneImpl > onPanelInput :: e -> gestureStamp(e)": NOT_OVERLAY + "an input event, read for its time stamp",
      "arg createSceneImpl > onPanelInput :: e -> gestureStamp(e) #2": NOT_OVERLAY + "an input event, read for its time stamp",
      'call createSceneImpl :: gestureTarget.addEventListener("keydown", onGestureInput, o)': NOT_OVERLAY + "a document input listener",
      'call createSceneImpl :: gestureTarget.addEventListener("wheel", onGestureInput, o)': NOT_OVERLAY + "a document input listener",
      'call createSceneImpl :: gestureTarget.addEventListener("pointerdown", onGesturePointerDown, o)': NOT_OVERLAY + "a document input listener",
      'call createSceneImpl :: gestureTarget.addEventListener("pointerup", onGesturePointerUp, o)': NOT_OVERLAY + "a document input listener",
      'call createSceneImpl :: gestureTarget.addEventListener("pointercancel", onGesturePointerUp, o)': NOT_OVERLAY + "a document input listener",
      'call createSceneImpl :: gestureTarget.addEventListener("keydown", onPanelInput, o)': NOT_OVERLAY + "a document input listener",
      'call createSceneImpl :: gestureTarget.addEventListener("pointerdown", onPanelInput, o)': NOT_OVERLAY + "a document input listener",
      'call createSceneImpl :: gestureTarget.addEventListener("pointerup", onPanelInput, o)': NOT_OVERLAY + "a document input listener",
      'call createSceneImpl :: document.addEventListener("visibilitychange", onVisibility)': NOT_OVERLAY + "the page-visibility listener (it queues a step-up, which lands through the handover)",
      'call createSceneImpl > dispose :: gestureTarget.removeEventListener("keydown", onGestureInput, o)': NOT_OVERLAY + "teardown of a document input listener",
      'call createSceneImpl > dispose :: gestureTarget.removeEventListener("wheel", onGestureInput, o)': NOT_OVERLAY + "teardown of a document input listener",
      'call createSceneImpl > dispose :: gestureTarget.removeEventListener("pointerdown", onGesturePointerDown, o)': NOT_OVERLAY + "teardown of a document input listener",
      'call createSceneImpl > dispose :: gestureTarget.removeEventListener("pointerup", onGesturePointerUp, o)': NOT_OVERLAY + "teardown of a document input listener",
      'call createSceneImpl > dispose :: gestureTarget.removeEventListener("pointercancel", onGesturePointerUp, o)': NOT_OVERLAY + "teardown of a document input listener",
      'call createSceneImpl > dispose :: gestureTarget.removeEventListener("keydown", onPanelInput, o)': NOT_OVERLAY + "teardown of a document input listener",
      'call createSceneImpl > dispose :: gestureTarget.removeEventListener("pointerdown", onPanelInput, o)': NOT_OVERLAY + "teardown of a document input listener",
      'call createSceneImpl > dispose :: gestureTarget.removeEventListener("pointerup", onPanelInput, o)': NOT_OVERLAY + "teardown of a document input listener",
      'call createSceneImpl > dispose :: document.removeEventListener("visibilitychange", onVisibility)': NOT_OVERLAY + "teardown of the page-visibility listener",
    };
    const unexpected = found.filter((k) => !(k in STATED));
    const missing = Object.keys(STATED).filter((k) => !found.includes(k));
    expect(new Set(found).size, "a site counted twice").toBe(found.length);
    expect({ unexpected, missing }, "every DOM site is a stated one, and every stated one still exists").toEqual({ unexpected: [], missing: [] });
    // Not vacuous: the checker resolved the overlay's DOM types (the per-frame opacity write is found by type).
    expect(found).toContain("write createSceneImpl > write :: el.style.opacity = String(opacity)");
    // ...and it resolved the slot's type argument (every call on the slot is found by type, not by name).
    expect(found).toContain("call createSceneImpl > dispose :: tierFade.dispose()");
    expect(Object.values(STATED).every((why) => why.length > 20)).toBe(true);
  }, 240_000);

  it("C5-R2-1: the positions the stated reasons depend on", () => {
    /* The reasons that depend on position, pinned where they are. What each plan DOES to the overlay
       (none / new / composed / deferred / kept, the held release and its reduced-motion swap, the
       driver's removal at 0) is the slot's, executed in emphasis.test.ts; what is pinned here is that
       the scene asks it at the right moments and honours `deferred`. */
    const code = (text: string): string => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    const snap = source.slice(source.indexOf("function snapshotForTierFade(): boolean {"), source.indexOf("\n  /** Copy the frame the OLD tier draws"));
    /* The warm-up flag is the copy's own precondition (`compiled`), so `deferred` is asked exactly when
       no copy can be taken for that reason. */
    expect(code(snap)).toMatch(/return tierFade\.tierChange\(copyFrameForTierFade, !compiled\)\.kind !== "deferred";\s*\}/);
    expect(source).toMatch(/if \(parent === null \|\| typeof document === "undefined" \|\| !compiled \|\| !firstRendered\) return null;/);
    /* A tier change always goes through the handover FIRST, and a deferred one changes nothing yet:
       no decision, no rebuild, no warm-up restarted under the running fade. */
    expect(code(source)).toMatch(
      /function applyQuality\(next: QualityDecision\): void \{\s*if \(!snapshotForTierFade\(\)\) \{\s*deferredQuality = next;\s*judgeQueue\.length = 0;\s*return;\s*\}\s*deferredQuality = null;\s*decision = next;/,
    );
    /* ...and it lands on the first frame after the warm-up that deferred it, through the same path. */
    expect(frameBody).toMatch(/if \(deferredQuality !== null && compiled\) \{\s*applyQuality\(deferredQuality\);\s*emitStats\(now\);\s*return;\s*\}/);
    /* While one is owed, the adaptive rule neither judges frames, lands a held step-down, nor steps up
       (each would decide from the tier being left), and the caller's own pin replaces it. */
    expect(code(source)).toMatch(/if \(heldStepDown === null\) return false;\s*if \(!tierIsAdaptive\(decision\)\) \{\s*heldStepDown = null;\s*return false;\s*\}\s*if \(deferredQuality !== null\) return false;/);
    expect(source).toMatch(/if \(pendingStepUp !== null && decision\.auto && heldStepDown === null && deferredQuality === null\) \{/);
    expect(source).toMatch(/if \(!suspended && deferredQuality === null\) judgeQueue\.push\(/);
    expect(code(source)).toMatch(/setQuality\(q: QualityTier\): void \{\s*deferredQuality = null;\s*const pin = pinQuality\(decision, q\);/);
    /* Every assignment to `deferredQuality` is one of those (and teardown's). */
    const writers: string[] = [];
    const sf = ts.createSourceFile("scene.ts", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const walk = (n: ts.Node): void => {
      if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isIdentifier(n.left) && n.left.text === "deferredQuality") writers.push(`${enclosingPath(n)} :: ${n.getText(sf)}`);
      ts.forEachChild(n, walk);
    };
    walk(sf);
    expect(writers).toEqual([
      "createSceneImpl > applyQuality :: deferredQuality = next",
      "createSceneImpl > applyQuality :: deferredQuality = null",
      "createSceneImpl > setQuality :: deferredQuality = null",
      "createSceneImpl > dispose :: deferredQuality = null",
    ]);
    /* The release hands the slot the new tier's composed frame, after the render that presents it. */
    expect(frameBody).toMatch(/rememberRenderedCamera\(\);\s*releaseTierFade\(now\);/);
  });

  it("C5-R2-1: a reduced-motion toggle reaches the scene by exactly one route, and the prose is true of the host whichever it takes", () => {
    /* R4-V1-3 (verifier, 2026-09-27): the prose said "a reduced-motion switch mid-fade finishes the
       fade at the cap", but the scene never changed `reducedMotion` after construction: the host
       (Fabric3D.tsx) recreates the whole scene on a toggle, taking the overlay down with the canvas.
       The scene now has the setter; whether the toggle reaches it is the host's wiring, and the prose
       is held here to that wiring in both directions. */
    const sf = ts.createSourceFile("scene.ts", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const iface = (() => {
      let hit: ts.InterfaceDeclaration | null = null;
      const walk = (n: ts.Node): void => {
        if (ts.isInterfaceDeclaration(n) && n.name.text === "FabricSceneEx") hit = n;
        ts.forEachChild(n, walk);
      };
      walk(sf);
      return hit as ts.InterfaceDeclaration | null;
    })();
    expect(iface).not.toBeNull();
    expect(iface!.members.map((m) => m.getText(sf).replace(/\/\*\*[\s\S]*?\*\/\s*/g, "").trim())).toContain("setReducedMotion(reduced: boolean): void;");
    // Every assignment to the scene's `reducedMotion` (its declaration aside) is the setter's.
    const writers: string[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isIdentifier(n.left) && n.left.text === "reducedMotion") writers.push(enclosingPath(n));
      ts.forEachChild(n, visit);
    };
    visit(sf);
    expect(writers).toEqual(["createSceneImpl > setReducedMotion"]);
    const setter = source.slice(source.indexOf("    setReducedMotion(reduced: boolean): void {"), source.indexOf("\n    },", source.indexOf("    setReducedMotion(reduced: boolean): void {")));
    expect(setter, "the setter hands the preference to every part that reads it").toMatch(/reducedMotion = reduced;\s*cameraRig\.setReducedMotion\(reduced\);\s*flow\.setReducedMotion\(reduced\);\s*markDirty\(\);/);

    const hostSource = readFileSync(resolve(process.cwd(), "src/fabric3d/Fabric3D.tsx"), "utf8");
    /* R4-VR2-3 (verifier round 2 of R4): this test used to accept `wired || recreates`, so it was green
       while the host still disposed and rebuilt the scene on a toggle — the owner-named cut path — and
       nothing red marked the open requirement. The host now wires the setter (R5), so the ONLY accepted
       route is the setter with no rebuild; a host that recreates the scene on a toggle, alone or beside
       the setter, fails here. The runtime half is Fabric3D.test.tsx ("a reduced-motion toggle reaches the
       running scene through setReducedMotion, never by rebuilding it"), which counts scenes built and
       disposed across a real toggle. The classifier's own known answers are the next test. */
    const route = hostMotionRoute(hostSource);
    expect(route.lifetimeEffects, "exactly one scene-lifetime effect, found by its `createScene` call").toBe(1);
    expect(route, "a reduced-motion toggle reaches the running scene through setReducedMotion and never rebuilds it").toEqual({ lifetimeEffects: 1, wired: true, recreates: false });
    /* The prose in the owner and the scene states what the setter route does and why the rebuild route is
       refused; it never claims the host takes the rebuild route. */
    const flat = (text: string): string => text.replace(/\s*\n\s*\*\s?/g, " ").replace(/\s+/g, " ");
    const doctrine = flat(readFileSync(resolve(process.cwd(), "src/fabric3d/emphasis.ts"), "utf8"));
    const sceneProse = flat(source);
    expect(doctrine, "the unqualified claim is gone").not.toMatch(/a reduced-motion switch mid-fade finishes the fade at the cap/);
    expect(doctrine, "a reduced-motion switch is not listed among the paths no presented frame is cut on").not.toMatch(/a tier change, a reduced-motion switch/);
    expect(doctrine).toMatch(/It reaches a running scene only through the scene's `setReducedMotion`; a host that instead disposes the scene on a toggle takes the overlay down with the canvas it covers/);
    expect(sceneProse).toMatch(/A host that disposes and recreates the scene on a toggle instead takes the overlay down with the canvas/);
    for (const [where, text] of [["emphasis.ts", doctrine], ["scene.ts", sceneProse]] as const) {
      expect(text, `${where} claims the host recreates the scene`).not.toMatch(/(the|so the) host recreates the whole scene|until the host calls it/);
      expect(text, `${where} claims the host calls the setter`).not.toMatch(/the host calls (it|setReducedMotion) now/);
    }
  });

  it("R4-VR2-3: the host-route classifier sees a rebuild on a toggle (known answers over the host's own source)", () => {
    /* Fabric3D.tsx is another cluster's file, so its mutation is made HERE, on a copy of its text: the
       real source with `reducedMotion` added to the scene-lifetime dependencies (the pre-R5 shape) must
       read as `recreates`, and with its setter call renamed away as not `wired`. */
    const hostSource = readFileSync(resolve(process.cwd(), "src/fabric3d/Fabric3D.tsx"), "utf8");
    expect(hostMotionRoute(hostSource)).toEqual({ lifetimeEffects: 1, wired: true, recreates: false });
    const sf = ts.createSourceFile("Fabric3D.tsx", hostSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const ends: number[] = [];
    const find = (n: ts.Node): void => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "useEffect" && n.arguments.length === 2) {
        const [body, d] = n.arguments as unknown as [ts.Expression, ts.Expression];
        if (/\bcreateScene\(/.test(body.getText(sf)) && ts.isArrayLiteralExpression(d)) ends.push(d.getEnd() - 1);
      }
      ts.forEachChild(n, find);
    };
    find(sf);
    expect(ends).toHaveLength(1);
    const end = ends[0]!;
    const rebuilds = `${hostSource.slice(0, end)}, reducedMotion${hostSource.slice(end)}`;
    expect(hostMotionRoute(rebuilds)).toEqual({ lifetimeEffects: 1, wired: true, recreates: true });
    const unwired = hostSource.replace(/\.setReducedMotion\(/g, ".setReducedMotionGone(");
    expect(hostMotionRoute(unwired).wired).toBe(false);
    /* The verifier's case, the pre-R5 host (rebuild, no setter): the old `wired || recreates` accepted it; the
       route the test above now requires does not. */
    const preR5 = `${unwired.slice(0, end)}, reducedMotion${unwired.slice(end)}`;
    const accepted = { lifetimeEffects: 1, wired: true, recreates: false };
    const pre = hostMotionRoute(preR5);
    expect(pre).toEqual({ lifetimeEffects: 1, wired: false, recreates: true });
    expect(pre.wired || pre.recreates, "the old acceptance rule let it through").toBe(true);
    expect(pre).not.toEqual(accepted);
  });

  it("a held step-down lands only with the camera at rest — before the gate, so its 6 s backstop cannot land it mid-orbit", () => {
    const land = source.slice(source.indexOf("function landHeldStepDown(now: number): boolean {"), source.indexOf("\n  /**", source.indexOf("function landHeldStepDown(now: number): boolean {")));
    const rest = land.indexOf("if (cameraRig.isTweening() || now - lastCameraMotionAt < MOTION_HOLD_MS) return false;");
    const gate = land.indexOf("gestureGate.mayLand(");
    expect(rest, "the camera-rest check").toBeGreaterThan(-1);
    expect(gate, "the gesture gate").toBeGreaterThan(rest);
    expect(land.slice(0, rest)).not.toMatch(/applyQuality\(/);
  });
});

describeGolden("cable routing on the reference sample", () => {
  it("the audited stacked pairs (podacc1 onto dist1, podacc2 onto dist2 — render audit #8) run no cable over a lid", () => {
    const pairs: [string, string][] = [
      ["podacc1", "dist1"],
      ["podacc2", "dist2"],
    ];
    const r = lidCrossings(buildFabricGraph({ devices, links, layout: stackedLayout(pairs), theme: "dark", profile }));
    expect(r.stackedSeen).toBeGreaterThanOrEqual(2);
    expect(r.crossings).toEqual([]);
  });
});
