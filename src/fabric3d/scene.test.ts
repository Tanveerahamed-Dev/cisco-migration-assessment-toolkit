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
import { Color, InstancedMesh } from "three";
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
      const nullBand = devices.filter((d) => d.band === null && d.collected);
      expect(nullBand.length + devices.filter((d) => d.band === null && !d.collected).length)
        .toBeGreaterThan(0);

      const read = new Color();
      for (const d of nullBand) {
        const slot = graph.slots.get(d.id);
        expect(slot).toBeDefined();
        const body = slot?.group.body;
        expect(body).toBeInstanceOf(InstancedMesh);
        body?.getColorAt(slot!.slot, read);
        // The body carries the band as a wash (mixed toward white), so compare direction rather
        // than value: it must lie nearer the indeterminate hue than the "Good" hue.
        const dIndeterminate = hueDistance(read, indeterminate);
        const dGood = hueDistance(read, good);
        expect(dIndeterminate).toBeLessThan(dGood);
      }
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

describe("cable routing", () => {
  it("anchors a cable on the chassis surface, never at its centre", () => {
    const out = new Vector3();
    surfaceAnchor([0, 0, 0], [8, 1.5, 5], [100, 0, 0], out);
    expect(out.x).toBeGreaterThan(8);
    expect(Math.abs(out.z)).toBeLessThan(0.001);
  });

  it("never runs a cable across its own endpoint's lid — including a vertically stacked pair", () => {
    /* Render audit #8. dist1/podacc1 and dist2/podacc2 are stacked (XZ offsets under half a unit),
       so the per-end face choice took OPPOSITE faces and L39/L43 crossed podacc1/podacc2's whole
       footprint while climbing: 13 and 12 of 29 samples over the lid. Asserted on the REAL graph's
       sampled polylines, so it is the producer's output under test, not a re-derivation.

       The shipped layout no longer stacks those pairs (each layer now steps toward the camera in Z),
       so the stacked case is reconstructed exactly: podacc1/podacc2 are moved onto dist1/dist2's
       X/Z, keeping their own Y plane. Both the shipped graph and the stacked one are asserted. */
    const at = (id: string) => layout.byId.get(id)!;
    const stackedNodes = layout.nodes.map((n) =>
      n.id === "podacc1" ? { ...n, x: at("dist1").x, z: at("dist1").z }
      : n.id === "podacc2" ? { ...n, x: at("dist2").x, z: at("dist2").z }
      : n,
    );
    const stackedLayout = { ...layout, nodes: stackedNodes, byId: new Map(stackedNodes.map((n) => [n.id, n])) };
    for (const [graph, mustStack] of [
      [buildDark(), false],
      [buildFabricGraph({ devices, links, layout: stackedLayout, theme: "dark", profile }), true],
    ] as const) {
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
    if (mustStack) {
      expect(stackedSeen, "the stacked case this guards must exist in the data, or the test is inert").toBeGreaterThan(0);
    }
    expect(crossings).toEqual([]);
    disposeScene(graph.scene);
    }
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
