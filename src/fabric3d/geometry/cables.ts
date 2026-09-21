/**
 * cables.ts — links as cables: real width, real curvature, real encoding.
 *
 * `LineBasicMaterial` is forbidden here and the reason is worth stating once, because it is the
 * single most common way a three.js network view ends up looking cheap: WebGL silently ignores
 * `linewidth > 1` on essentially every platform. It does not warn, it does not throw, it renders a
 * one-pixel hairline forever, and no post-processing pass can rescue it. Every visible link in this
 * scene is therefore a `LineSegments2` with a `LineMaterial`, which expands each segment into
 * camera-facing quads in the vertex shader and gives genuine, anti-aliased width.
 *
 * What a cable encodes, and the rule that governs it: FOUR independent channels, none of which is
 * colour alone.
 *
 *   width   → observed link speed, with a distinct THINNEST step for "speed not observed"
 *   dash    → operational state: solid = up, long-dash = down, dotted = unknown
 *   colour  → the loudest fact about the link (down, bridge, unmeasured, ordinary)
 *   strands → a port-channel is drawn as a bundle; a graph bridge is drawn doubled
 *
 * `null` never becomes a healthy default. A link whose centrality was never computed — 19 of the
 * 44 in this snapshot — is drawn in `--claim-indeterminate` with a short dash and reports
 * `notObserved: ["centrality"]`, because "we did not measure whether cutting this partitions the
 * graph" and "cutting this is safe" are opposite claims.
 */
import {
  Color,
  DynamicDrawUsage,
  InstancedBufferAttribute,
  InstancedInterleavedBuffer,
  InterleavedBufferAttribute,
  Vector3,
} from "three";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import type { Link } from "../../core/types";
import { RECEDE_ATTRIBUTE, type TokenPalette } from "../materials";
import type { Vec3 } from "../layout";

export type DashStyle = "solid" | "dashed" | "dotted" | "short";

export interface LinkVisual {
  linkId: string;
  /** Line width in CSS pixels. `worldUnits` is false, so a link's weight does not change with dolly. */
  widthPx: number;
  /** A CSS custom property name — never a literal colour. */
  colorToken: string;
  dash: DashStyle;
  /** Parallel strands. > 1 only for a port channel: one cable drawn for a bundle is a lie. */
  strands: number;
  /** A second offset polyline: this link's removal partitions the graph. */
  doubled: boolean;
  /** Fields that were null or absent in the snapshot. Rendered as unmeasured, never as healthy. */
  notObserved: string[];
  /** One sentence a tooltip or legend can print verbatim. */
  reason: string;
}

/** Width steps. The thinnest is reserved for "speed not observed" so absence has its own weight. */
const WIDTH_SPEED_UNOBSERVED = 1.5;
const WIDTH_100M = 2.1;
const WIDTH_1G = 2.7;
const WIDTH_FAST = 3.3;

/**
 * Width of the analytic edge filter on a cable, in pixels — and, by the same number, how much
 * wider the drawn quad is than the width the encoding asks for.
 *
 * The two uses have to be one constant, because together they are what keeps the width CHANNEL
 * intact. The filter is linear and centred ON the nominal edge, so half of it falls inside the
 * stroke and half in the margin the quad was widened by; the ink that lands on screen is therefore
 * the nominal width, at every width. The four speed steps keep their exact relative weight
 * (1.5 : 2.1 : 2.7 : 3.3) and only the outer EXTENT grows, by the same amount on every cable —
 * a constant, not a distortion of the encoding.
 *
 * It was measured, not chosen. On review/_audit_cableaa.mjs at `high` (real GPU, dark), the share
 * of background-to-cable crossings that are zero-intermediate hard steps, and the single-pixel
 * holes punched into the strokes:
 *
 *   no term at all (shipped)   77.1 %   108 holes
 *   no term, tone split only   63.5 %   108 holes
 *   filter 1.0 px              69.7 %   105 holes
 *   filter 1.6 px              64.1 %    45 holes
 *   filter 2.2 px              57.7 %    17 holes
 *
 * 2.2 keeps winning on the metric and loses on the picture: at that width a 1.5 px cable never
 * reaches full coverage anywhere across its section, so the thinnest speed step — the one reserved
 * for "speed not observed" — starts reading as a smear instead of a wire. 1.6 is the last value
 * where every width still has an opaque core.
 *
 * The first attempt ramped INWARD from the quad edge without widening the quad, and that is the
 * mistake this constant's double duty exists to prevent: `cablePixels` fell from 2882 to 1195 and
 * the cables had quietly gone translucent while the aliasing metric looked like it had improved.
 *
 * In CSS pixels where it widens the quad (`LineMaterial.linewidth` is), in device pixels where it
 * filters (`fwidth` is). They coincide at DPR 1; at DPR 2 the residual is a fraction of a pixel.
 */
const CABLE_EDGE_AA_PX = 1.6;

/**
 * Classify one link into its visual channels. Pure, total, and the natural unit test for the whole
 * encoding: the honesty rules are all expressible as assertions on the returned record.
 */
export function classifyLink(link: Link): LinkVisual {
  const notObserved: string[] = [];

  const speed = link.speedMbps;
  let widthPx: number;
  if (speed === null || speed <= 0) {
    // 0 Mbps reaches us from the collector for a port whose speed it could not read. Treating it
    // as "zero bandwidth" would invent a fact; it is an absence and is drawn as one.
    notObserved.push("speed");
    widthPx = WIDTH_SPEED_UNOBSERVED;
  } else if (speed <= 100) {
    widthPx = WIDTH_100M;
  } else if (speed <= 1000) {
    widthPx = WIDTH_1G;
  } else {
    widthPx = WIDTH_FAST;
  }

  const status = link.opStatus;
  let dash: DashStyle;
  let colorToken: string;
  let reason: string;

  if (status === "down") {
    dash = "dashed";
    colorToken = "--state-down";
    reason = "operational state: down";
  } else if (status === "up") {
    dash = "solid";
    colorToken = "--claim-out-of-scope";
    reason = "operational state: up";
  } else {
    // Anything that is not literally up or down — including the string "unknown" this snapshot
    // uses — is a third thing. It is never quietly folded into "up".
    dash = "dotted";
    colorToken = "--state-unknown";
    notObserved.push("operational state");
    reason = `operational state not observed (${status})`;
  }

  let doubled = false;
  if (link.isBridge === true) {
    doubled = true;
    colorToken = "--sev-high";
    reason = `${reason}; cutting this link partitions the graph`;
  } else if (link.isBridge === null) {
    notObserved.push("centrality");
    if (status === "up") {
      // Only claim the indeterminate channel when no louder observed fact is using it. A link that
      // is DOWN and also unmeasured is drawn down — the observed failure outranks the gap.
      dash = "short";
      colorToken = "--claim-indeterminate";
    }
    reason = `${reason}; centrality not computed for this link`;
  } else {
    reason = `${reason}; measured non-bridge`;
  }

  let strands = 1;
  if (link.isPortChannel) {
    if (link.members.length >= 2) {
      strands = Math.min(4, link.members.length);
    } else {
      // A port channel has at least two members by definition, so a member list this short is a
      // gap in the record rather than a one-member bundle. Draw a bundle, claim no count.
      strands = 2;
      notObserved.push("port-channel member count");
    }
    reason = `${reason}; port channel`;
  }

  return { linkId: link.id, widthPx, colorToken, dash, strands, doubled, notObserved, reason };
}

/* ── routing ───────────────────────────────────────────────────────────────── */

const _a = new Vector3();
const _b = new Vector3();
const _mid = new Vector3();
const _perp = new Vector3();
const _p = new Vector3();
const _q = new Vector3();

/**
 * Move an endpoint from the node centre out to the chassis surface, facing the far end.
 *
 * Without this every cable vanishes into the middle of a box and the fabric reads as a wire
 * diagram with boxes dropped on top. The intersection is done against the axis-aligned half-extents
 * in the XZ plane, which is exact for the rack-mount kinds and a close enough circumscription for
 * the lathed access point.
 */
export function surfaceAnchor(
  centre: Vec3,
  half: readonly [number, number, number],
  towards: Vec3,
  out: Vector3,
): Vector3 {
  const dx = towards[0] - centre[0];
  const dz = towards[2] - centre[2];
  const len = Math.hypot(dx, dz);
  if (len < 1e-6) {
    return out.set(centre[0], centre[1], centre[2] + half[2] + 0.4);
  }
  const ux = dx / len;
  const uz = dz / len;
  // Slab intersection: the smaller of the two axis crossings is the face the ray actually leaves by.
  const tx = Math.abs(ux) < 1e-6 ? Infinity : half[0] / Math.abs(ux);
  const tz = Math.abs(uz) < 1e-6 ? Infinity : half[2] / Math.abs(uz);
  const t = Math.min(tx, tz) + 0.45;
  // Slightly below the centre plane: cables leave a chassis at its ports, not through its lid.
  return out.set(centre[0] + ux * t, centre[1] - half[1] * 0.22, centre[2] + uz * t);
}

/**
 * Sample a cable into a polyline.
 *
 * A straight segment between two boxes reads as a schematic connector; a curve reads as a cable.
 * The curve is a quadratic Bezier whose control point is the layout's own route hint when one
 * exists — `layout.ts` computes those precisely so a cable arcs AROUND an intervening tier rather
 * than through it — and otherwise the midpoint pulled down by a sag proportional to span, which is
 * what an unsupported cable actually does. The sag is capped well below the 64-unit tier pitch so
 * it can never reach the deck below.
 */
export function routeCable(
  from: Vector3,
  to: Vector3,
  hint: Vec3 | null,
  segments: number,
  out: Float32Array,
): number {
  _a.copy(from);
  _b.copy(to);
  if (hint !== null) {
    _mid.set(hint[0], hint[1], hint[2]);
  } else {
    const span = Math.hypot(_b.x - _a.x, _b.z - _a.z);
    const sag = Math.min(11, Math.max(1.6, span * 0.085));
    _mid.addVectors(_a, _b).multiplyScalar(0.5);
    _mid.y -= sag;
  }
  // Quadratic Bezier, unrolled: a CatmullRomCurve3 would allocate a Vector3 per sample, and this
  // runs for every link every time the topology or quality tier changes.
  for (let i = 0; i <= segments; i += 1) {
    const t = i / segments;
    const it = 1 - t;
    const w0 = it * it;
    const w1 = 2 * it * t;
    const w2 = t * t;
    out[i * 3] = w0 * _a.x + w1 * _mid.x + w2 * _b.x;
    out[i * 3 + 1] = w0 * _a.y + w1 * _mid.y + w2 * _b.y;
    out[i * 3 + 2] = w0 * _a.z + w1 * _mid.z + w2 * _b.z;
  }
  return segments + 1;
}

/** Horizontal perpendicular to a cable, for bundling strands and doubling a bridge. */
function perpendicular(points: Float32Array, count: number, out: Vector3): Vector3 {
  const lastX = points[(count - 1) * 3] ?? 0;
  const lastZ = points[(count - 1) * 3 + 2] ?? 0;
  const firstX = points[0] ?? 0;
  const firstZ = points[2] ?? 0;
  const dx = lastX - firstX;
  const dz = lastZ - firstZ;
  const len = Math.hypot(dx, dz);
  if (len < 1e-6) return out.set(1, 0, 0);
  return out.set(-dz / len, 0, dx / len);
}

/* ── batching ──────────────────────────────────────────────────────────────── */

/**
 * One draw call per (dash style, width) pair. Colour varies per segment through the instance colour
 * attribute, so a batch holds many differently coloured links; width and dash are material uniforms
 * and therefore have to partition the batches.
 */
export interface CableBatch {
  key: string;
  object: LineSegments2;
  material: LineMaterial;
  /** Link id for every segment, parallel to the geometry's instance array — the pick mapping. */
  segmentLinkIds: string[];
  /** Per-segment recession, 0 = fully present. Shared buffer; write then flag once. */
  recede: InstancedBufferAttribute;
}

export interface CableSet {
  batches: CableBatch[];
  visuals: Map<string, LinkVisual>;
  /** First and last sampled point of each link's primary strand, for trace anchoring. */
  endpoints: Map<string, { a: Vector3; b: Vector3 }>;
  /** Every sampled point of each link's primary strand, so a trace can follow the real cable. */
  polylines: Map<string, Float32Array>;
  setResolution(width: number, height: number): void;
  retint(tokens: TokenPalette): void;
  dispose(): void;
}

const DASH_PARAMS: Readonly<Record<DashStyle, { dashSize: number; gapSize: number }>> = Object.freeze({
  // World units, scaled from design-brief.md §4.5 by the ratio between this fabric's ~330-unit
  // span and the ~140-unit scene the brief's figures were written against.
  solid: { dashSize: 1, gapSize: 0 },
  dashed: { dashSize: 3.8, gapSize: 2.6 },
  dotted: { dashSize: 0.85, gapSize: 2.4 },
  short: { dashSize: 2.4, gapSize: 2.4 },
});

/**
 * Every link is painted at FULL opacity, and that is a deliberate departure from
 * design-brief.md §4.5's "ordinary link at 55 %".
 *
 * WCAG 1.4.11 covers graphical objects, and a canvas is not exempt — the brief says so itself and
 * publishes the measured ratios. But those ratios are measured on SOLID colours: it quotes a
 * dimmed off-path link as `#5c6678` on `#0a0d13`, 3.36:1. Compositing `--claim-out-of-scope` at
 * 55 % alpha over the stage does not produce that colour; it produces roughly `#3a4351`, about
 * 2.0:1, which fails. So the hierarchy the 55 % was buying is bought instead by the recession
 * channel, which dims off-path links only when there IS an on-path subject to contrast them
 * against. With nothing selected every link is legible; with a trace up, the trace is loudest.
 */
const BASE_OPACITY = 1;
const ORDINARY_OPACITY = 1;

export interface CableMaterialOptions {
  /**
   * Per-segment colour from `instanceColorStart/End`. MUST be false for a geometry that does not
   * carry those attributes: LineMaterial's shader multiplies by `vColor` under `USE_COLOR`, and an
   * absent attribute reads as zero, so the line renders BLACK with no error anywhere. That is
   * exactly how the trace path first shipped.
   */
  vertexColors?: boolean;
}

export function createCableMaterial(
  dash: DashStyle,
  widthPx: number,
  opacity: number,
  opts: CableMaterialOptions = {},
): LineMaterial {
  const params = DASH_PARAMS[dash];
  const mat = new LineMaterial({
    color: 0xffffff,
    // + CABLE_EDGE_AA_PX so the coverage ramp is added outside the encoded width, not taken
    // out of it. See the constant: the ink this carries is exactly widthPx.
    linewidth: widthPx + CABLE_EDGE_AA_PX,
    worldUnits: false,
    vertexColors: opts.vertexColors !== false,
    transparent: true,
    depthWrite: true,
    dashed: dash !== "solid",
    dashScale: 1,
    dashSize: params.dashSize,
    gapSize: params.gapSize,
    opacity,
  });
  /* `alphaToCoverage` is NOT set here, and the claim that used to sit on this line — that it "is
   * what removes the stair-stepping from long diagonal cable runs" — was false and is recorded as
   * such rather than quietly deleted.
   *
   * Read three 0.186.0's LineMaterial shader: the `USE_ALPHA_TO_COVERAGE` branch replaces a
   * `discard` with a smoothstep ONLY inside `if (abs(vUv.y) > 1.0)`, i.e. only on the ROUND CAP at
   * each end of a segment. The long edges of the segment body are the rasterised edges of a
   * camera-facing quad and are untouched by it. There was never an analytic coverage term on the
   * thing the comment named.
   *
   * MEASURED (review/_audit_cableaa.mjs, real GPU, dark, tier high, the cable-over-background band
   * y 270-345): with it ON, 675 of 876 background-to-cable crossings were zero-intermediate hard
   * steps; with it OFF, 609 of 828 — 77.1 % against 73.6 %. It was slightly WORSE than nothing,
   * which is what an unused multisample coverage path does when the composer runs multisampling: 0.
   * The stair-stepping is fixed in postfx.ts, by feeding SMAA an image it can actually read. */
  patchRecession(mat, widthPx);
  return mat;
}

/**
 * Teach a LineMaterial two things it does not know: the per-segment recession channel, and how to
 * anti-alias its own long edges.
 *
 * Patched by string surgery on the shader source rather than through `onBeforeCompile`, because
 * LineMaterial is a ShaderMaterial whose source we own outright here; editing the strings keeps the
 * whole transformation visible in one place instead of split across a callback and a cache key.
 *
 * ── THE EDGE COVERAGE TERM, and why the library has no equivalent ───────────────────────────────
 *
 * Read three 0.186.0's LineMaterial fragment shader. In the screen-space (non-WORLD_UNITS) path,
 * `vUv.x` is the ACROSS-WIDTH coordinate and `vUv.y` runs ALONG the segment — which you can read
 * straight off the endcap test, `a = vUv.x; b = vUv.y -/+ 1; if (a*a + b*b > 1.0) discard`, a unit
 * circle centred on each segment END. Every smoothing term the library has, `alphaToCoverage`
 * included, lives inside `if (abs(vUv.y) > 1.0)` — i.e. it applies ONLY to the round caps. The two
 * long edges of the stroke, which are essentially all of a cable's visible perimeter, are the raw
 * rasterised edges of a camera-facing quad and get nothing at all.
 *
 * That is why the fabric's dominant geometry was stair-stepped no matter what the post chain did:
 * SMAA was being asked to reconstruct an edge from a 1.5-3 px stroke, which is below the several
 * consistent pixels its pattern classifier needs.
 *
 * So the coverage is computed where it is known exactly. `fwidth(vUv.x)` is the width of one pixel
 * measured in the same units the edge is expressed in, so the ramp is always one pixel wide
 * whatever the dolly, the line width or the device pixel ratio. It fades INWARD from the quad
 * boundary rather than straddling it, because fragments outside the quad do not exist to be shaded.
 *
 * MEASURED, review/_audit_cableaa.mjs at `high` on a real GPU, background-to-cable crossings that
 * are zero-intermediate hard steps: see docs/render-decisions.md for the full table.
 */
function patchRecession(mat: LineMaterial, nominalWidthPx: number): void {
  /* Where the NOMINAL edge sits in the drawn quad. vUv.x spans [-1, 1] over the drawn half-width,
     which is (nominalWidthPx + CABLE_EDGE_AA_PX) / 2, so the encoded edge is at this fraction. */
  const edgeU = nominalWidthPx / (nominalWidthPx + CABLE_EDGE_AA_PX);
  mat.vertexShader = mat.vertexShader
    .replace(
      "attribute vec3 instanceStart;",
      "attribute vec3 instanceStart;\n\t\tattribute float aRecede;\n\t\tvarying float vRecede;",
    )
    .replace(
      "float aspect = resolution.x / resolution.y;",
      "vRecede = aRecede;\n\t\t\tfloat aspect = resolution.x / resolution.y;",
    );
  mat.fragmentShader = mat.fragmentShader
    .replace("uniform vec3 diffuse;", "uniform vec3 diffuse;\n\t\tvarying float vRecede;")
    .replace(
      "gl_FragColor = vec4( diffuseColor.rgb, alpha );",
      [
        // Matched to the chassis recession in materials.ts: desaturate, then dim the radiance,
        // then thin the alpha. A cable that only lost saturation would stay just as prominent,
        // because an off-path cable is already achromatic.
        "float _r = clamp( vRecede, 0.0, 1.0 );",
        "float _lum = dot( diffuseColor.rgb, vec3( 0.2126, 0.7152, 0.0722 ) );",
        "vec3 _rgb = mix( diffuseColor.rgb, vec3( _lum ), _r ) * ( 1.0 - _r * 0.72 );",
        // One device pixel, measured in the coordinate the stroke's edge is expressed in.
        "float _px = max( fwidth( vUv.x ), 1e-5 );",
        /* Distance from this fragment to the stroke's TRUE edge, in device pixels, run through a
           filter CABLE_EDGE_AA_PX pixels wide and centred ON the edge — so half the ramp falls
           inside the nominal stroke and half in the margin the quad was widened by. Coverage, not
           blur: a fragment a filter-width inside is opaque, one exactly on the edge is half
           covered, and the ramp is the same width at every dolly, line width and pixel ratio. */
        `float _d = ( ${edgeU.toFixed(5)} - abs( vUv.x ) ) / _px;`,
        `float _cov = clamp( _d / ${CABLE_EDGE_AA_PX.toFixed(2)} + 0.5, 0.0, 1.0 );`,
        "gl_FragColor = vec4( _rgb, alpha * ( 1.0 - _r * 0.55 ) * _cov );",
      ].join("\n\t\t\t"),
    );
  mat.needsUpdate = true;
}

interface Accum {
  key: string;
  dash: DashStyle;
  widthPx: number;
  opacity: number;
  positions: number[];
  colors: number[];
  distances: number[];
  segmentLinkIds: string[];
}

export interface CableBuildInput {
  links: readonly Link[];
  /** Node centre and half-extents for both ends; a link naming an unplaced host is skipped. */
  anchorOf(host: string): { centre: Vec3; half: readonly [number, number, number] } | null;
  midpointOf(linkId: string): Vec3 | null;
  segments: number;
  tokens: TokenPalette;
}

export function buildCables(input: CableBuildInput): CableSet {
  const { links, segments, tokens } = input;
  const visuals = new Map<string, LinkVisual>();
  const endpoints = new Map<string, { a: Vector3; b: Vector3 }>();
  const polylines = new Map<string, Float32Array>();
  const accum = new Map<string, Accum>();
  const colour = new Color();
  const sample = new Float32Array((segments + 1) * 3);

  for (const link of links) {
    const av = input.anchorOf(link.a);
    const bv = input.anchorOf(link.b);
    if (av === null || bv === null) continue; // layout.diagnostics.linksWithUnplacedEndpoint owns this

    const visual = classifyLink(link);
    visuals.set(link.id, visual);

    surfaceAnchor(av.centre, av.half, bv.centre, _p);
    surfaceAnchor(bv.centre, bv.half, av.centre, _q);
    const count = routeCable(_p, _q, input.midpointOf(link.id), segments, sample);
    polylines.set(link.id, sample.slice(0, count * 3));
    endpoints.set(link.id, { a: _p.clone(), b: _q.clone() });

    colour.copy(tokens.color(visual.colorToken));
    const opacity =
      visual.colorToken === "--claim-out-of-scope" ? ORDINARY_OPACITY : BASE_OPACITY;
    const key = `${visual.dash}|${visual.widthPx}|${opacity}`;
    let bucket = accum.get(key);
    if (bucket === undefined) {
      bucket = {
        key,
        dash: visual.dash,
        widthPx: visual.widthPx,
        opacity,
        positions: [],
        colors: [],
        distances: [],
        segmentLinkIds: [],
      };
      accum.set(key, bucket);
    }

    perpendicular(sample, count, _perp);
    const strandGap = 0.62;
    const offsets: number[] = [];
    for (let s = 0; s < visual.strands; s += 1) {
      offsets.push((s - (visual.strands - 1) / 2) * strandGap);
    }
    if (visual.doubled) {
      // The bridge channel: a second rail either side of wherever the bundle already sits.
      const spread = 0.45;
      const widened: number[] = [];
      for (const o of offsets) widened.push(o - spread, o + spread);
      offsets.length = 0;
      offsets.push(...widened);
    }

    for (const off of offsets) {
      // Distance resets to zero at the start of every strand, so a dash pattern begins at the
      // chassis instead of inheriting a phase from whichever link was batched before it.
      let run = 0;
      for (let i = 0; i < count - 1; i += 1) {
        const x0 = (sample[i * 3] ?? 0) + _perp.x * off;
        const y0 = sample[i * 3 + 1] ?? 0;
        const z0 = (sample[i * 3 + 2] ?? 0) + _perp.z * off;
        const x1 = (sample[(i + 1) * 3] ?? 0) + _perp.x * off;
        const y1 = sample[(i + 1) * 3 + 1] ?? 0;
        const z1 = (sample[(i + 1) * 3 + 2] ?? 0) + _perp.z * off;
        const segLen = Math.hypot(x1 - x0, y1 - y0, z1 - z0);
        bucket.positions.push(x0, y0, z0, x1, y1, z1);
        bucket.colors.push(colour.r, colour.g, colour.b, colour.r, colour.g, colour.b);
        bucket.distances.push(run, run + segLen);
        bucket.segmentLinkIds.push(link.id);
        run += segLen;
      }
    }
  }

  const batches: CableBatch[] = [];
  for (const bucket of accum.values()) {
    const geometry = new LineSegmentsGeometry();
    geometry.setPositions(new Float32Array(bucket.positions));
    geometry.setColors(new Float32Array(bucket.colors));
    const distanceBuffer = new InstancedInterleavedBuffer(new Float32Array(bucket.distances), 2, 1);
    geometry.setAttribute("instanceDistanceStart", new InterleavedBufferAttribute(distanceBuffer, 1, 0));
    geometry.setAttribute("instanceDistanceEnd", new InterleavedBufferAttribute(distanceBuffer, 1, 1));
    const recede = new InstancedBufferAttribute(new Float32Array(bucket.segmentLinkIds.length), 1);
    recede.setUsage(DynamicDrawUsage);
    geometry.setAttribute(RECEDE_ATTRIBUTE, recede);

    const material = createCableMaterial(bucket.dash, bucket.widthPx, bucket.opacity);
    const object = new LineSegments2(geometry, material);
    object.name = `cables:${bucket.key}`;
    object.frustumCulled = false; // a single batch spans the whole fabric; its bounds are never off-screen
    object.castShadow = false;
    object.receiveShadow = false;
    // Cables draw after the opaque chassis so their blended edges composite against a finished
    // frame rather than against whatever happened to be rasterised first.
    object.renderOrder = 2;
    batches.push({ key: bucket.key, object, material, segmentLinkIds: bucket.segmentLinkIds, recede });
  }

  const set: CableSet = {
    batches,
    visuals,
    endpoints,
    polylines,
    setResolution(width: number, height: number): void {
      for (const b of batches) b.material.resolution.set(width, height);
    },
    retint(next: TokenPalette): void {
      for (const b of batches) {
        const colours = b.object.geometry.getAttribute("instanceColorStart") as
          | InterleavedBufferAttribute
          | undefined;
        const ends = b.object.geometry.getAttribute("instanceColorEnd") as
          | InterleavedBufferAttribute
          | undefined;
        if (colours === undefined || ends === undefined) continue;
        for (let i = 0; i < b.segmentLinkIds.length; i += 1) {
          const id = b.segmentLinkIds[i];
          const v = id === undefined ? undefined : set.visuals.get(id);
          if (v === undefined) continue;
          const c = next.color(v.colorToken);
          colours.setXYZ(i, c.r, c.g, c.b);
          ends.setXYZ(i, c.r, c.g, c.b);
        }
        colours.needsUpdate = true;
        ends.needsUpdate = true;
      }
    },
    dispose(): void {
      for (const b of batches) {
        b.object.geometry.dispose();
        b.material.dispose();
        b.object.removeFromParent();
      }
      batches.length = 0;
    },
  };
  return set;
}
