/**
 * env.ts — the image-based lighting, built in code.
 *
 * Metal does not read as metal under lights; it reads as metal under an *environment*, because what
 * a rough metal surface shows you is a blurred image of the room it is in. So the scene gets a room:
 * a gradient box with three emissive panels in it, rendered to a cubemap and prefiltered by
 * PMREMGenerator into the roughness-indexed mip chain three's standard material samples.
 *
 * Built from a scene rather than loaded from an HDR file for three reasons that all matter here:
 * the app must work offline from a USB stick, a fetched asset would make the first frame
 * non-deterministic, and a generated rig can be re-derived from the theme tokens when the user
 * flips from dark to light — a baked HDR cannot.
 */
import {
  BackSide,
  BoxGeometry,
  BufferAttribute,
  Color,
  DataTexture,
  DataUtils,
  HalfFloatType,
  LinearFilter,
  LinearSRGBColorSpace,
  type Material,
  Mesh,
  MeshBasicMaterial,
  OrthographicCamera,
  PMREMGenerator,
  PlaneGeometry,
  RGBAFormat,
  Scene,
  type Texture,
  type WebGLRenderTarget,
  type WebGLRenderer,
} from "three";
import type { TokenPalette } from "./materials";

/**
 * Emissive panel radiances, in linear working-space units. Values above 1 are the entire point:
 * a light source is brighter than white paper, and an environment whose brightest pixel is 1.0
 * produces the flat, chalky "unlit" look that the brief names as a cheap-render tell.
 */
interface RigRecipe {
  /** Room walls: bottom colour, top colour. */
  roomLow: [number, number, number];
  roomHigh: [number, number, number];
  /** Large soft key, above / front / left. Slightly warm. */
  key: [number, number, number];
  /** Cooler, dimmer, behind and to the right — separates the chassis from the backdrop. */
  fill: [number, number, number];
  /** Floor bounce. Dim and neutral; it fills the underside so nothing reads as a cut-out. */
  bounce: [number, number, number];
}

const DARK_RIG: RigRecipe = {
  roomLow: [0.02, 0.022, 0.03],
  roomHigh: [0.3, 0.33, 0.42],
  key: [9.5, 9.2, 8.6],
  fill: [1.6, 1.95, 2.7],
  bounce: [0.5, 0.52, 0.62],
};

/**
 * The light theme is not the dark theme brightened. A pale product photograph is lit by a bright
 * room — most of the energy arrives as diffuse bounce, not as a hard key — so the room itself is
 * two orders of magnitude brighter here while the key is only modestly stronger.
 */
const LIGHT_RIG: RigRecipe = {
  roomLow: [0.16, 0.17, 0.2],
  roomHigh: [0.62, 0.64, 0.7],
  key: [5.2, 5.1, 4.9],
  fill: [0.95, 1.02, 1.2],
  bounce: [0.4, 0.41, 0.45],
};

const ROOM = 50;

function panel(
  width: number,
  height: number,
  rgb: [number, number, number],
  place: (m: Mesh) => void,
): Mesh {
  const geom = new PlaneGeometry(width, height);
  const mat = new MeshBasicMaterial({ toneMapped: false });
  mat.color.setRGB(rgb[0], rgb[1], rgb[2], LinearSRGBColorSpace);
  const mesh = new Mesh(geom, mat);
  place(mesh);
  return mesh;
}

/**
 * The room box, coloured by vertex rather than by a custom shader. A gradient shader would be one
 * more program to compile and one more thing to keep in step with colour management; per-vertex
 * colour on an eight-vertex box is exact, free, and cannot drift.
 */
function room(recipe: RigRecipe): Mesh {
  const geom = new BoxGeometry(ROOM * 2, ROOM * 2, ROOM * 2);
  const pos = geom.getAttribute("position");
  const colors = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i += 1) {
    const t = Math.min(1, Math.max(0, (pos.getY(i) + ROOM) / (ROOM * 2)));
    // Squared so the ceiling stays the dominant source and the horizon does not wash out.
    const k = t * t;
    colors[i * 3] = recipe.roomLow[0] + (recipe.roomHigh[0] - recipe.roomLow[0]) * k;
    colors[i * 3 + 1] = recipe.roomLow[1] + (recipe.roomHigh[1] - recipe.roomLow[1]) * k;
    colors[i * 3 + 2] = recipe.roomLow[2] + (recipe.roomHigh[2] - recipe.roomLow[2]) * k;
  }
  geom.setAttribute("color", new BufferAttribute(colors, 3));
  const mat = new MeshBasicMaterial({ side: BackSide, vertexColors: true, toneMapped: false });
  return new Mesh(geom, mat);
}

/**
 * Build the rig. Exported so a test can assert the rig's composition without a GPU — every object
 * here is constructible in jsdom, which is exactly why the environment recipe lives in data and
 * not inside a render callback.
 */
export function buildStudioRig(theme: "dark" | "light"): Scene {
  const recipe = theme === "dark" ? DARK_RIG : LIGHT_RIG;
  const scene = new Scene();
  scene.add(room(recipe));

  // Key: large, high, front-left, angled down at the fabric. Large because a small source gives a
  // hard specular dot instead of the long soft streak that makes a brushed faceplate read.
  scene.add(
    panel(70, 46, recipe.key, (m) => {
      m.position.set(-26, 38, 30);
      m.lookAt(0, 0, 0);
    }),
  );
  // Fill: behind and right, cooler, so the far edge of every chassis gets a rim that is not the
  // key's colour. One light temperature everywhere is what flattens a render.
  scene.add(
    panel(58, 40, recipe.fill, (m) => {
      m.position.set(34, 12, -34);
      m.lookAt(0, 0, 0);
    }),
  );
  scene.add(
    panel(90, 90, recipe.bounce, (m) => {
      m.position.set(0, -36, 0);
      m.rotation.x = -Math.PI / 2;
    }),
  );
  return scene;
}

export interface EnvironmentHandle {
  texture: Texture;
  /** Global multiplier applied via `scene.environmentIntensity`, tuned per theme. */
  intensity: number;
  dispose(): void;
}

/**
 * A prefilter in two halves: create the programs, then — once the driver has linked them — run it.
 *
 * WHY IT IS SPLIT. `PMREMGenerator.fromScene` creates its programs and draws through them in the
 * same call, and a program is linked-for-real at its first use, so the whole link cost lands in
 * one unyieldable call. Measured on the release build with a real GPU: 667-1244 ms, and INDEPENDENT
 * of `size` (64 measured the same as 256), which is what identifies it as compile cost rather than
 * fill cost. Splitting it lets the caller spend the link on the driver's thread — see the cold-load
 * warm-up in scene.ts — instead of on the main thread with input queued behind it.
 *
 * `prepare()` must be called with a render target BOUND whose colour space and tone mapping match
 * the one PMREM renders into, or the programs it creates are the wrong variants and are compiled
 * again at first use. Every non-XR render target gives three the same pair (linear, no tone
 * mapping), so any offscreen target will do; the canvas will not.
 */
export interface EnvironmentPrefilter {
  /** Create every program the generation needs, without drawing through any of them. */
  prepare(): void;
  /** Run the prefilter. Cheap once `prepare()`'s programs have finished linking. */
  generate(): EnvironmentHandle;
}

/**
 * Generate the prefiltered environment. `sigma` pre-blurs the rig before prefiltering so the panel
 * edges do not survive into the low-roughness mips as visible rectangles in a specular highlight.
 *
 * The one-call form. It is `prepareEnvironment().prepare(); generate()` back to back, which is what
 * every caller outside the cold-load path wants.
 */
export function createEnvironment(
  renderer: WebGLRenderer,
  theme: "dark" | "light",
  size: number,
): EnvironmentHandle {
  const prefilter = prepareEnvironment(renderer, theme, size);
  prefilter.prepare();
  return prefilter.generate();
}

export function prepareEnvironment(
  renderer: WebGLRenderer,
  theme: "dark" | "light",
  size: number,
): EnvironmentPrefilter {
  const pmrem = new PMREMGenerator(renderer);
  const rig = buildStudioRig(theme);
  const flat = new OrthographicCamera();
  return {
    prepare(): void {
      pmrem.compileCubemapShader();
      pmrem.compileEquirectangularShader();
      /* The rig's own materials: these are what the six cube-face renders draw with. */
      renderer.compile(rig, flat);
      /* The blur and GGX materials are the ones the prefilter uses most, and three exposes no
         public compile for either.
         RESPONSIVENESS FIX, 2026-09-21 (acceptance E5). This used to compile `_blurMaterial` only,
         and it never did: in three 0.186 both materials are `null` until `_allocateTargets()` runs
         inside `fromScene`, so the guard passed `null` to the compile and nothing was linked. Every
         prefilter program was therefore linked at first USE, inside `generate()` — measured on the
         release build as one `atlas:environment` animation frame of 1009 ms during the cold load.
         Sizing and allocating here is exactly what `fromScene` does first with the same `size`, so
         it finds the ping-pong target and both materials already built and reuses them.

         AND THEY ARE COMPILED AGAINST THE GEOMETRY THEY WILL DRAW. three's `_compileMaterial` puts
         the material on an EMPTY BufferGeometry, but a program's cache key carries the geometry's
         attribute set (`vertexNormals`, bit 23 of the key's boolean mask), and the prefilter's own
         LOD planes have normals. Measured: the compiled key ended `…,0,srgb`, the drawn one
         `…,8388608,srgb`, so both programs were linked a SECOND time at first use and the frame
         still stalled 669-1234 ms. Compiling on one of those planes produces the drawn variant.
         Likewise the background box `_sceneToCubeUV` creates on first use is created here, with
         the same construction, so its program is linked with the rest instead of mid-prefilter.

         Reached defensively: if a field or method is renamed upstream, the prefilter links those
         programs at first use — a slower warm-up, never a wrong picture. */
      const internals = pmrem as unknown as {
        _blurMaterial?: Material | null;
        _ggxMaterial?: Material | null;
        _lodMeshes?: Mesh[];
        _backgroundBox?: Mesh | null;
        _setSize?: (cubeSize: number) => void;
        _allocateTargets?: () => { dispose(): void };
      };
      if (typeof internals._setSize === "function" && typeof internals._allocateTargets === "function") {
        internals._setSize(size);
        /* The output target it hands back is a throwaway — `fromScene` allocates its own. */
        internals._allocateTargets().dispose();
      }
      const plane = internals._lodMeshes?.[1] ?? internals._lodMeshes?.[0];
      if (plane !== undefined) {
        const own = plane.material;
        for (const material of [internals._blurMaterial, internals._ggxMaterial]) {
          if (material === null || material === undefined) continue;
          plane.material = material;
          renderer.compile(plane, flat);
        }
        plane.material = own;
      }
      if (internals._backgroundBox === null) {
        internals._backgroundBox = new Mesh(
          new BoxGeometry(),
          new MeshBasicMaterial({ name: "PMREM.Background", side: BackSide, depthWrite: false, depthTest: false }),
        );
        renderer.compile(internals._backgroundBox, flat);
      }
    },
    generate(): EnvironmentHandle {
      const target: WebGLRenderTarget = pmrem.fromScene(rig, 0.04, 0.1, ROOM * 2.5, { size });
      disposeScene(rig);
      // PMREMGenerator owns process-wide GPU resources; dispose exactly once, here, and never hold
      // an instance across generations (design-brief.md §4.6).
      pmrem.dispose();
      return buildEnvironmentHandle(target, theme);
    },
  };
}

function buildEnvironmentHandle(target: WebGLRenderTarget, theme: "dark" | "light"): EnvironmentHandle {
  return {
    texture: target.texture,
    // Dark UI: the environment is the dominant source, so it carries most of the energy. Light UI:
    // the room is already bright, and leaving intensity at 0.85 would blow the pale chassis out.
    intensity: theme === "dark" ? 0.85 : 0.5,
    dispose(): void {
      target.dispose();
    },
  };
}

/** Free every geometry and material under a scene. Rigs are throwaway, but they are not free. */
export function disposeScene(scene: Scene): void {
  scene.traverse((obj) => {
    const mesh = obj as Partial<Mesh>;
    if (mesh.geometry !== undefined) mesh.geometry.dispose();
    const mat = mesh.material;
    if (Array.isArray(mat)) {
      for (const m of mat) m.dispose();
    } else if (mat !== undefined) {
      mat.dispose();
    }
  });
}

const BACKDROP_HEIGHT = 256;

/* ── AgX, forward and inverse, for choosing backdrop inputs ───────────────────────────────── */

type Vec3 = [number, number, number];
/** GLSL `mat3(c0, c1, c2) * v`, column-major, exactly as three's tonemapping chunk writes it. */
const mul = (c: readonly [Vec3, Vec3, Vec3], v: Vec3): Vec3 => [
  c[0][0] * v[0] + c[1][0] * v[1] + c[2][0] * v[2],
  c[0][1] * v[0] + c[1][1] * v[1] + c[2][1] * v[2],
  c[0][2] * v[0] + c[1][2] * v[1] + c[2][2] * v[2],
];
const SRGB_TO_REC2020: [Vec3, Vec3, Vec3] = [[0.6274, 0.0691, 0.0164], [0.3293, 0.9195, 0.088], [0.0433, 0.0113, 0.8956]];
const REC2020_TO_SRGB: [Vec3, Vec3, Vec3] = [[1.6605, -0.1246, -0.0182], [-0.5876, 1.1329, -0.1006], [-0.0728, -0.0083, 1.1187]];
const AGX_INSET: [Vec3, Vec3, Vec3] = [
  [0.856627153315983, 0.137318972929847, 0.11189821299995],
  [0.0951212405381588, 0.761241990602591, 0.0767994186031903],
  [0.0482516061458583, 0.101439036467562, 0.811302368396859],
];
const AGX_OUTSET: [Vec3, Vec3, Vec3] = [
  [1.1271005818144368, -0.1413297634984383, -0.14132976349843826],
  [-0.11060664309660323, 1.157823702216272, -0.11060664309660294],
  [-0.016493938717834573, -0.016493938717834257, 1.2519364065950405],
];
const AGX_MIN_EV = -12.47393;
const AGX_MAX_EV = 4.026069;
const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

/**
 * three 0.186's `AgXToneMapping` (tonemapping_pars_fragment), ported line for line, exposure 1 —
 * the curve postprocessing's ToneMappingEffect applies to every pixel of the live scene, backdrop
 * included. Linear sRGB in, linear sRGB out.
 */
export function agxForward(rgb: Vec3): Vec3 {
  let c = mul(AGX_INSET, mul(SRGB_TO_REC2020, rgb));
  c = c.map((v) => {
    const x = clamp01((Math.log2(Math.max(v, 1e-10)) - AGX_MIN_EV) / (AGX_MAX_EV - AGX_MIN_EV));
    const x2 = x * x;
    const x4 = x2 * x2;
    return 15.5 * x4 * x2 - 40.14 * x4 * x + 31.96 * x4 - 6.868 * x2 * x + 0.4298 * x2 + 0.1191 * x - 0.00232;
  }) as Vec3;
  c = mul(AGX_OUTSET, c).map((v) => Math.pow(Math.max(0, v), 2.2)) as Vec3;
  return mul(REC2020_TO_SRGB, c).map(clamp01) as Vec3;
}

/**
 * The linear input AgX maps to `target`. AgX mixes channels, so there is no per-channel inverse;
 * a multiplicative fixed-point iteration converges on this curve's monotone range in a few dozen
 * steps and is run once per backdrop build, never per frame.
 */
export function agxInverse(target: Vec3): Vec3 {
  let x: Vec3 = [...target];
  for (let i = 0; i < 60; i += 1) {
    const y = agxForward(x);
    x = x.map((v, k) => Math.max(1e-6, v * Math.pow(Math.max(1e-6, target[k] ?? 0) / Math.max(1e-6, y[k] ?? 0), 0.8))) as Vec3;
  }
  return x;
}

/**
 * Where the backdrop's two ends should LAND on screen, as multiples of `--stage-bg` in linear
 * light. The token sits between them, so the stage reads as the surface the brief names with a
 * gentle vertical light rather than as a darker panel set into the chrome.
 */
export const BACKDROP_DISPLAY_SPAN = {
  dark: { top: 1.35, bottom: 0.78 },
  light: { top: 1.03, bottom: 0.965 },
} as const;

const displayLuminance = (c: Vec3): number => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];

/**
 * The ground a mark drawn over the stage has to hold its contrast against, and which way the mark
 * must go to do it. The one ground owner for every contrast floor in the scene: the cable inks
 * (geometry/cables.ts `cableGround`) and the receded chassis (materials.ts `CHASSIS_RECEDED_FLOOR`).
 */
export function stageGround(tokens: TokenPalette): { y: number; inkDarker: boolean } {
  const s = tokens.color("--stage-bg");
  const stageY = displayLuminance([s.r, s.g, s.b]);
  const span = BACKDROP_DISPLAY_SPAN[tokens.theme === "dark" ? "dark" : "light"];
  // A pale ground takes dark ink and vice versa. Decided from the ground itself, not the theme
  // name, so a retuned stage cannot silently flip the direction the floor pushes.
  const inkDarker = stageY > 0.18;
  // The worst case is the end of the backdrop gradient CLOSEST to the ink: its darkest end for dark
  // ink, its brightest end for light ink.
  const k = inkDarker ? Math.min(span.top, span.bottom) : Math.max(span.top, span.bottom);
  return { y: Math.min(1, stageY * k), inkDarker };
}

/** The luminance that sits exactly `floor`:1 from the ground, on the ink's side of it. */
export function floorLuminance(groundY: number, floor: number, inkDarker: boolean): number {
  return inkDarker
    ? Math.max(0, (groundY + 0.05) / floor - 0.05)
    : Math.min(1, floor * (groundY + 0.05) - 0.05);
}

/**
 * Move `c` to luminance `y`: DOWN by scaling toward black (keeps chroma), UP by mixing toward white
 * (the only way up that cannot leave the gamut). Chosen by the direction of travel, not by theme —
 * the ink floor moves dark ink down on the pale stage, and recession moves light ink down on the
 * dark one; an earlier version keyed this on the theme and silently left dark-stage recession as a
 * no-op (the receded fan measured 8.7:1, i.e. not receded at all).
 */
export function toLuminance(c: Vec3, y: number): Vec3 {
  const cy = displayLuminance(c);
  if (y <= cy) {
    if (cy <= 1e-6) return [y, y, y];
    const k = y / cy;
    return [c[0] * k, c[1] * k, c[2] * k];
  }
  if (cy >= 1 - 1e-6) return [1, 1, 1];
  const t = Math.min(1, Math.max(0, (y - cy) / (1 - cy)));
  return [c[0] + (1 - c[0]) * t, c[1] + (1 - c[1]) * t, c[2] + (1 - c[2]) * t];
}

/**
 * The backdrop: a vertical gradient, not a flat fill and emphatically not `0x000000`.
 *
 * This texture is written into the composer's linear HDR buffer and then passes through AgX tone
 * mapping with everything else. It used to compensate by multiplying the token (1.08 / 0.94 in
 * light) and hoping; MEASURED (render audit #9), the light stage then reached the screen at
 * (199,200,201)/(194,195,196) against a token of (238,241,245) — 39-44 levels dark, its cool cast
 * gone — so the 3-D canvas read as a greyer panel set into the chrome. The endpoints are now the
 * AgX PRE-IMAGES of where they should land (`agxInverse`, no dependency: the curve is ported from
 * the three version this app pins), so the tone-mapped result sits on `--stage-bg`. The
 * alternative — a transparent canvas over a CSS gradient — loses the backdrop from the bloom and
 * SSAO inputs and makes the fabric look pasted on.
 */
export function createBackdrop(tokens: TokenPalette): DataTexture {
  const stage = tokens.color("--stage-bg");
  const span = BACKDROP_DISPLAY_SPAN[tokens.theme === "dark" ? "dark" : "light"];
  const pre = (k: number): Color => {
    const [r, g, b] = agxInverse([stage.r * k, stage.g * k, stage.b * k].map(clamp01) as Vec3);
    return new Color(r, g, b);
  };
  const top = pre(span.top);
  const bottom = pre(span.bottom);

  /* HALF FLOAT and LINEAR, because the pre-images are not display values: the light stage's lands
     at ~3.7-6.0 linear before AgX compresses it back to #eef1f5, which an 8-bit sRGB texture would
     clamp to 1.0 — the very clamp that produced the grey panel. The composer's buffer is half float
     already (postfx.ts), so nothing downstream narrows it again before the tone map. */
  const data = new Uint16Array(BACKDROP_HEIGHT * 4);
  const c = new Color();
  const one = DataUtils.toHalfFloat(1);
  for (let y = 0; y < BACKDROP_HEIGHT; y += 1) {
    // Row 0 is the BOTTOM of a texture three uploads without flipping for a background quad.
    const t = y / (BACKDROP_HEIGHT - 1);
    c.copy(bottom).lerp(top, t * t * (3 - 2 * t));
    data[y * 4] = DataUtils.toHalfFloat(c.r);
    data[y * 4 + 1] = DataUtils.toHalfFloat(c.g);
    data[y * 4 + 2] = DataUtils.toHalfFloat(c.b);
    data[y * 4 + 3] = one;
  }
  const tex = new DataTexture(data, 1, BACKDROP_HEIGHT, RGBAFormat, HalfFloatType);
  tex.colorSpace = LinearSRGBColorSpace;
  tex.magFilter = LinearFilter;
  tex.minFilter = LinearFilter;
  tex.generateMipmaps = false;
  tex.needsUpdate = true;
  return tex;
}
