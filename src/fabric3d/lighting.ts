/**
 * lighting.ts — one shadow-casting key, two unshadowed shaping lights, and a fitted frustum.
 *
 * Deviation from design-brief.md §4.6, recorded deliberately: the brief says "one key light plus an
 * image-based environment. No light rigs." The build task requires a key/fill/rim rig. Both are
 * served by keeping the *shadowing* and most of the energy in a single key and adding two very low
 * directional lights purely for shape — a rim that separates the chassis from the backdrop and a
 * fill that keeps the shadow side from going to the environment floor. What the brief actually
 * forbids is a pile of point lights and a flattening ambient (§4.9 items 7 and 8); neither is here.
 *
 * Shadow quality is dominated by frustum tightness, not map size, so the key's orthographic box is
 * fitted to the real layout bounds every time the data changes. A 2048 map over a loose frustum is
 * blurrier than a fitted 1024, and a frustum that misses part of the fabric produces the worst
 * failure of all: a hard line across the scene where shadows simply stop.
 */
import { Color, DirectionalLight, Group, Object3D, Vector3 } from "three";
import type { QualityProfile } from "./quality";
import type { TokenPalette } from "./materials";

export interface LightingBounds {
  min: [number, number, number];
  max: [number, number, number];
}

export interface LightingRig {
  group: Group;
  key: DirectionalLight;
  fill: DirectionalLight;
  rim: DirectionalLight;
  /** Re-fit the shadow frustum after the fabric's extent changes. */
  fit(bounds: LightingBounds): void;
  retint(tokens: TokenPalette): void;
  applyProfile(profile: QualityProfile): void;
  dispose(): void;
}

/**
 * Direction vectors, normalised at use. Chosen so the key agrees with the environment rig's key
 * panel (env.ts places it front-left-high): a specular highlight that disagrees with the diffuse
 * shading direction is subtle, pervasive, and reads as "wrong" without a viewer being able to say
 * why.
 */
const KEY_DIR = new Vector3(-0.42, 0.82, 0.48).normalize();
const FILL_DIR = new Vector3(0.62, 0.28, 0.55).normalize();
const RIM_DIR = new Vector3(0.38, 0.34, -0.86).normalize();

const scratchCenter = new Vector3();
const scratchSize = new Vector3();

/** Shadow-frustum half-extent for a fabric of this bounding radius. Used by fit() and by the bias. */
function shadowHalfExtent(radius: number): number {
  return radius + radius * 0.06 + 8;
}

/**
 * normalBias, derived rather than guessed: 1.5 shadow-map texels, measured in world units.
 *
 * normalBias offsets the shadow lookup along the surface normal to hide self-shadowing, and the
 * self-shadowing it hides is exactly one map texel wide — so the only defensible value is a small
 * multiple of the texel's WORLD size, which is `2 * halfExtent / mapSize`. That is why the brief's
 * published 0.022 could not be used literally: it is a world distance written for a scene about
 * 140 units across, and this fabric is ~360 across with a frustum fitted to it, where one 2048 map
 * texel is ~0.19 units. 0.022 is a ninth of a texel — no acne protection at all.
 *
 * What was here instead (`Math.max(0.4, radius * 0.006)`, measured live at 1.075) is ~5.5 texels:
 * five times more offset than the artefact it suppresses, which detaches the shadow from its
 * caster. That is peter-panning, the precise failure design-brief.md §4.6 pairs the two values to
 * avoid, and it was visible as hard dark rectangles sitting on empty floor.
 *
 * 1.5 texels at 2048 over this fabric is ~0.29 world units, and it tracks the map size: dropping to
 * a 1024 map doubles the texel, and the bias with it, instead of leaving a value tuned for 2048.
 *
 * RAISED to 4 texels, 2026-09-21, on measurement rather than taste. At 1.5 texels the shadow map's
 * ENTIRE contribution to the composed frame was self-shadowing artefacts: an A/B against a real GPU
 * (tier high, dark, 1280x800, one focused chassis) found shadows-on vs shadows-off changed 1.32 %
 * of the crop at mean delta 10.7, and raising normalBias alone to 3.0 world units changed 1.29 % at
 * mean 9.3 — i.e. essentially the whole difference between "shadows on" and "shadows off" was acne,
 * not shadow. The acne is inter-PART, not inter-object: body, bezel, dark and rail are four separate
 * meshes that interpenetrate inside one chassis, so each is a caster a fraction of a texel in front
 * of the next at a grazing angle. 4 texels (~0.77 units at 2048 over this fabric) clears it while
 * still being far smaller than the ~1.6-unit contact crescent the geometry can actually produce.
 *
 * WHY THE CAST SHADOW IS SMALL HERE, stated so the next reader does not diagnose "shadows broken"
 * again: KEY_DIR sits 52 degrees above the horizon and a rack unit is 3.04 tall and 16 wide, so the
 * shadow it throws clears its own footprint by 1.56 units in x and 1.78 in z against half-extents
 * of 8 and 5.5. The cast shadow is a thin crescent at the base BY CONSTRUCTION, which is also what
 * a real switch lying on a real shelf does. Grounding therefore comes from the contact decals
 * (geometry/ground.ts + materials.ts `contactFade`), and those are load-bearing, not decoration.
 */
function normalBiasFor(mapSize: number, radius: number): number {
  const texelWorld = (2 * shadowHalfExtent(radius)) / Math.max(1, mapSize);
  return texelWorld * 4;
}

export function createLighting(tokens: TokenPalette, profile: QualityProfile): LightingRig {
  const group = new Group();
  group.name = "lighting";

  /** Bounding radius of the last fit; 180 until one happens, which is this fabric's own order. */
  let fittedRadius = 180;

  const key = new DirectionalLight(0xffffff, 2.1);
  key.name = "key";
  key.castShadow = true;
  key.shadow.mapSize.set(profile.shadowMapSize, profile.shadowMapSize);
  // bias and normalBias are a pair. bias alone removes acne by detaching the shadow from its
  // caster (peter-panning), which reads as every chassis hovering a few millimetres above its deck.
  // design-brief.md §4.6 publishes the pair as (-0.0004, 0.022); `bias` is in normalised depth and
  // carries over unchanged, `normalBias` is in WORLD units and cannot (see normalBiasFor below).
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = normalBiasFor(profile.shadowMapSize, 180);
  key.shadow.radius = 1.6;
  /* Shadows at partial intensity, and this is a composition decision rather than a taste one.
     The fabric is a LAYERED diagram: tiers sit 64 units apart, so a chassis on the access tier
     casts onto the deck two layers down, where the patch has no visible caster and reads as a
     floating dark rectangle. At full strength that is the "bad shadows" case the build task says
     to avoid outright. At 0.5 the near-contact shadow still grounds a chassis on its own deck —
     helped by the contact decals, which carry the grounding on their own when the map is off —
     while the far projections drop to a shading gradient instead of a hard object.

     RAISED 0.5 -> 0.85, 2026-09-21. The "far projection" worry was never realisable on this
     snapshot: only `tier-decks` receives, the floor is opted out (geometry/ground.ts), and the
     decks that could catch a cross-tier projection sit 64 units away with their own chassis in
     front of them. What 0.5 actually did was halve the only shadow this geometry produces — the
     contact crescent at the base of each chassis — on a deck already near black, which is a
     grounding cue spent on a hazard that is not present. */
  key.shadow.intensity = 0.85;
  key.target = new Object3D();
  group.add(key, key.target);

  const fill = new DirectionalLight(0xffffff, 0.34);
  fill.name = "fill";
  fill.castShadow = false;
  group.add(fill);

  const rim = new DirectionalLight(0xffffff, 0.52);
  rim.name = "rim";
  rim.castShadow = false;
  group.add(rim);

  const rig: LightingRig = {
    group,
    key,
    fill,
    rim,

    fit(bounds: LightingBounds): void {
      scratchCenter.set(
        (bounds.min[0] + bounds.max[0]) / 2,
        (bounds.min[1] + bounds.max[1]) / 2,
        (bounds.min[2] + bounds.max[2]) / 2,
      );
      scratchSize.set(
        bounds.max[0] - bounds.min[0],
        bounds.max[1] - bounds.min[1],
        bounds.max[2] - bounds.min[2],
      );
      // The half-extent of the bounding SPHERE, not of the box: the light looks down a diagonal,
      // so fitting the box's own half-widths clips the corners of the fabric out of the map.
      const radius = scratchSize.length() / 2;
      const margin = radius * 0.06 + 8;
      const half = shadowHalfExtent(radius);
      const distance = radius * 2.4 + 40;
      fittedRadius = radius;

      key.target.position.copy(scratchCenter);
      key.position.copy(scratchCenter).addScaledVector(KEY_DIR, distance);
      fill.position.copy(scratchCenter).addScaledVector(FILL_DIR, distance);
      rim.position.copy(scratchCenter).addScaledVector(RIM_DIR, distance);

      const cam = key.shadow.camera;
      cam.left = -half;
      cam.right = half;
      cam.top = half;
      cam.bottom = -half;
      cam.near = Math.max(1, distance - radius - margin);
      cam.far = distance + radius + margin;
      cam.updateProjectionMatrix();
      // The frustum just changed, so the texel changed, so the bias changes with it.
      key.shadow.normalBias = normalBiasFor(key.shadow.mapSize.x, radius);
    },

    retint(tokens2: TokenPalette): void {
      // Chrome is achromatic, and so is the key: a tinted key would put colour on every surface and
      // compete with the four channels that are allowed to carry meaning. What changes between
      // themes is intensity, because the environment's contribution changes underneath it.
      const white = new Color(1, 1, 1);
      key.color.copy(white);
      fill.color.copy(white);
      rim.color.copy(white);
      const dark = tokens2.theme === "dark";
      key.intensity = dark ? 3.1 : 1.9;
      fill.intensity = dark ? 0.5 : 0.3;
      rim.intensity = dark ? 0.85 : 0.42;
    },

    applyProfile(p: QualityProfile): void {
      key.castShadow = p.shadows;
      if (key.shadow.map !== null && key.shadow.mapSize.x !== p.shadowMapSize) {
        // An existing map is sized at allocation; it must be released before the new size takes.
        key.shadow.map.dispose();
        key.shadow.map = null;
      }
      key.shadow.mapSize.set(p.shadowMapSize, p.shadowMapSize);
      // A tier change halves or doubles the texel; a bias tuned for the old map size would either
      // acne or peter-pan at the new one.
      key.shadow.normalBias = normalBiasFor(p.shadowMapSize, fittedRadius);
      key.shadow.needsUpdate = true;
    },

    dispose(): void {
      key.shadow.dispose();
      key.dispose();
      fill.dispose();
      rim.dispose();
      group.clear();
    },
  };

  rig.retint(tokens);
  rig.applyProfile(profile);
  return rig;
}
