/**
 * layers.ts — the one registry of every three.js render layer this subsystem uses.
 *
 * Why a registry rather than a constant next to each use site:
 *
 * A three.js layer is a shared 32-bit namespace, and `postprocessing` allocates into that
 * namespace BEHIND OUR BACK. Every `Selection` it constructs (one inside SelectiveBloomEffect, one
 * inside each OutlineEffect) takes the next id from a MODULE-GLOBAL counter that starts at 2 and
 * never resets for the lifetime of the page:
 *
 *     // postprocessing/src/core/Selection.js
 *     const idManager = new IdManager(2);
 *     constructor(iterable, layer = idManager.getNextId()) { ... }
 *
 * So the layers a post chain occupies depend on HOW MANY POST CHAINS HAVE EVER BEEN BUILT in the
 * page. The first chain takes 2, 3, 4; the second takes 5, 6, 7; the third 8, 9, 10. React 19
 * StrictMode mounts twice in development, and a quality-tier change rebuilds the chain — so the
 * live chain's layer numbers are a function of the app's mount history.
 *
 * MEASURED, dev server, 2026-09-21: on a settled /fabric-preview.html page `new Selection().layer`
 * returned 8, i.e. layers 2..7 were already handed out and the SECOND chain owned 5, 6 and 7.
 * `PICK_LAYER` is 7. OutlineEffect's constructor sets `forceUpdate = true`, so on its first frame
 * it runs the mask pass even with an empty selection, doing `camera.layers.set(selection.layer)` —
 * layer 7 — and rendering the hit-test proxies into the outline mask. `forceUpdate` then goes
 * false and the mask target is never re-rendered or cleared, so that one frame's mask is
 * composited into EVERY later frame: all 26 chassis wearing the blocked-outline's `--sev-critical`
 * red, permanently, on the development surface (C5 "bloom applied indiscriminately" /
 * "colour not tied to meaning"). A tier change moved the chain to 8, 9, 10 and the red vanished —
 * which is why the same build looked fine after touching the quality control and why production,
 * where StrictMode does not double-invoke, never showed it.
 *
 * The fix is not a different magic number for PICK_LAYER: a hand-picked number is exactly as
 * exposed to the next allocation. The fix is that WE own the namespace — every layer this
 * subsystem uses is declared here, the post chain's selections are pinned to declared values
 * instead of being handed whatever the counter is on, and `assertLayerRegistry` fails loudly if
 * the two ever meet again.
 */

/** Layer reserved for hit-test proxies. The camera renders layer 0 only, so nothing here is drawn. */
export const PICK_LAYER = 7;

/**
 * Layers pinned onto the `Selection` inside each post effect, immediately after construction.
 *
 * High in the range and contiguous so they are obvious in a `layers.mask` dump, and far from
 * anything the library's counter reaches in a session: it would take 20+ post-chain rebuilds to
 * walk up here, and `assertLayerRegistry` catches that case rather than rendering it.
 */
export const SELECTION_LAYERS = {
  bloom: 24,
  selectionOutline: 25,
  blockedOutline: 26,
} as const;

/** Every layer the subsystem claims, as (name, layer) pairs — the input to the invariant below. */
export const LAYER_REGISTRY: readonly (readonly [string, number])[] = [
  ["pick", PICK_LAYER],
  ["bloom", SELECTION_LAYERS.bloom],
  ["selectionOutline", SELECTION_LAYERS.selectionOutline],
  ["blockedOutline", SELECTION_LAYERS.blockedOutline],
];

/**
 * Check the registry, plus any layers observed on live effects, for collisions and range errors.
 *
 * Returns a list of human-readable violations; empty means healthy. Callers decide what to do with
 * it — `createPostChain` logs it in dev and the unit test asserts it is empty, so a regression
 * surfaces as a test failure rather than as a red fabric nobody can explain.
 *
 * `observed` exists because pinning is only half the guarantee: a future postprocessing version
 * could ignore the assignment, and a silent no-op would put us back where we started. The post
 * chain passes what the effects actually report after it has set them.
 */
export function assertLayerRegistry(
  observed: readonly (readonly [string, number])[] = [],
): string[] {
  const violations: string[] = [];
  const declared = new Map<string, number>(LAYER_REGISTRY.map(([n, l]) => [n, l]));
  const seen = new Map<number, string>();

  for (const [name, layer] of LAYER_REGISTRY) {
    if (!Number.isInteger(layer) || layer < 1 || layer > 31) {
      violations.push(`${name} uses layer ${layer}, which is outside the usable range 1..31`);
      continue;
    }
    const prior = seen.get(layer);
    if (prior !== undefined) {
      violations.push(
        `${name} and ${prior} both use layer ${layer}; a post effect would render the other one's objects`,
      );
      continue;
    }
    seen.set(layer, name);
  }

  /* An observed layer is what an effect REPORTS after we pinned it. Two ways it can be wrong: it
     is not the layer we asked for (the assignment was ignored), or it is some other registered
     owner's layer (we pinned it on top of something). Both are reported by owner name. */
  for (const [name, layer] of observed) {
    const want = declared.get(name);
    const owner = seen.get(layer);
    const stolen =
      owner !== undefined && owner !== name
        ? `, which belongs to ${owner}; that effect would render ${owner}'s objects`
        : "";
    if (want !== undefined && want !== layer) {
      violations.push(`${name} reports layer ${layer} after being pinned to ${want}${stolen}`);
      continue;
    }
    if (stolen !== "") violations.push(`${name} reports layer ${layer}${stolen}`);
  }

  return violations;
}
