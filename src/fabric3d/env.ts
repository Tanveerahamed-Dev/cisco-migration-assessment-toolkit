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
  LinearFilter,
  LinearSRGBColorSpace,
  Mesh,
  MeshBasicMaterial,
  OrthographicCamera,
  PMREMGenerator,
  PlaneGeometry,
  RGBAFormat,
  SRGBColorSpace,
  Scene,
  UnsignedByteType,
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
      /* The blur material is the one the prefilter uses most and three exposes no public compile
         for it. Reached defensively: if the field or the method is ever renamed upstream, the
         prefilter simply links that one program at first use and costs what it costs today —
         a slower warm-up, never a wrong picture. */
      const internals = pmrem as unknown as {
        _blurMaterial?: unknown;
        _compileMaterial?: (m: unknown) => void;
      };
      if (internals._blurMaterial !== undefined && typeof internals._compileMaterial === "function") {
        internals._compileMaterial(internals._blurMaterial);
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

/**
 * The backdrop: a vertical gradient, not a flat fill and emphatically not `0x000000`.
 *
 * Honest note on colour: this texture is written into the composer's linear HDR buffer and then
 * passes through AgX tone mapping with everything else, so the pixels that reach the screen are not
 * bit-identical to `--stage-bg`. Compensating would mean inverting the tone curve, which is not
 * worth a dependency; the endpoints below are chosen so the tone-mapped result sits on the stage
 * surface rather than above or below it. The alternative — a transparent canvas over a CSS
 * gradient — loses the backdrop from the bloom and SSAO inputs and makes the fabric look pasted on.
 */
export function createBackdrop(tokens: TokenPalette): DataTexture {
  const stage = tokens.color("--stage-bg");
  const top = new Color().copy(stage).multiplyScalar(tokens.theme === "dark" ? 1.55 : 1.08);
  const bottom = new Color().copy(stage).multiplyScalar(tokens.theme === "dark" ? 0.72 : 0.94);

  const data = new Uint8Array(BACKDROP_HEIGHT * 4);
  const c = new Color();
  for (let y = 0; y < BACKDROP_HEIGHT; y += 1) {
    // Row 0 is the BOTTOM of a texture three uploads without flipping for a background quad.
    const t = y / (BACKDROP_HEIGHT - 1);
    c.copy(bottom).lerp(top, t * t * (3 - 2 * t));
    const srgb = c.clone().convertLinearToSRGB();
    data[y * 4] = Math.round(Math.min(1, Math.max(0, srgb.r)) * 255);
    data[y * 4 + 1] = Math.round(Math.min(1, Math.max(0, srgb.g)) * 255);
    data[y * 4 + 2] = Math.round(Math.min(1, Math.max(0, srgb.b)) * 255);
    data[y * 4 + 3] = 255;
  }
  const tex = new DataTexture(data, 1, BACKDROP_HEIGHT, RGBAFormat, UnsignedByteType);
  // This one DOES carry colour, so it is the one texture in the subsystem tagged sRGB.
  tex.colorSpace = SRGBColorSpace;
  tex.magFilter = LinearFilter;
  tex.minFilter = LinearFilter;
  tex.generateMipmaps = false;
  tex.needsUpdate = true;
  return tex;
}
