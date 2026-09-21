/**
 * devHandle.ts — expose the live scene to the capture and measurement harnesses.
 *
 * Why this exists: `review/capture.mjs` screenshots each investigation state, and a 3-D frame is
 * only meaningful once the progressive passes have settled. Waiting a fixed number of milliseconds
 * instead produces a different frame on a different machine — and it fails in the least visible
 * way possible, because the screenshots still look fine while quietly breaking the byte-identical
 * capture requirement (acceptance F6) and making every visual regression check unreliable.
 *
 * So the harness waits on `window.__atlasScene.stats().converged`, and this is the one line that
 * makes that true. `scene.ts` already reports `converged` in `SceneStats` for exactly this purpose.
 *
 * Usage, from wherever the scene is created:
 *
 *     const scene = createScene(canvas, opts, callbacks);
 *     const release = exposeSceneForCapture(scene);
 *     return () => { release(); scene.dispose(); };
 *
 * ── WHY THIS IS NOT GATED ON `import.meta.env.DEV` ──────────────────────────────────────────────
 *
 * It was, and that made the frame-rate criterion unevidenceable on the artefact it is about. The
 * scene handle is the ONLY route to the frame-time series and to the quality tier actually in
 * force, so gating it on DEV meant every frame-rate and tier number in an audit came from the dev
 * server — a different bundle, unminified, with StrictMode double-invokes and HMR client attached —
 * and never from the build that ships. Measured 2026-09-21: on the preview of the release build
 * `window.__atlasScene` was `undefined` mid-journey and the probes reported "NO SCENE HANDLE",
 * while the identical probe against the dev server returned a full stats object. A criterion whose
 * evidence can only be collected from a build nobody runs is not being measured.
 *
 * The replacement is an explicit, per-session OPT-IN that survives the production build. Nothing is
 * published unless the page was asked for it, so an ordinary visitor still gets no global handle to
 * the renderer:
 *
 *   - `?__atlasScene=1` in the URL, which is what the harnesses set; or
 *   - `sessionStorage["atlas.exposeScene"] === "1"`, for a session that navigates around; or
 *   - `window.__atlasExposeScene === true` set before the app mounts (an init script); or
 *   - a development build, where it stays on unconditionally as before.
 *
 * The flag is read ONCE, at module evaluation, so a later `history.pushState` that drops the query
 * parameter cannot revoke a handle the harness is already holding, and a page that was not opened
 * with the flag cannot have one turned on by anything that happens afterwards.
 */
import type { FabricScene } from "./contract";

declare global {
  interface Window {
    /** Present in dev, and in any build explicitly opened with the opt-in below. */
    __atlasScene?: FabricScene;
    /** Set before the app mounts to publish the handle on a production build. */
    __atlasExposeScene?: boolean;
  }
}

/** The query parameter, the sessionStorage key and the pre-mount global, in one place. */
export const SCENE_HANDLE_PARAM = "__atlasScene";
export const SCENE_HANDLE_STORAGE_KEY = "atlas.exposeScene";

/**
 * Whether this page was asked to publish the scene handle.
 *
 * Exported so a test can assert the decision directly rather than inferring it from a side effect,
 * and evaluated eagerly below so the answer cannot change mid-session.
 */
export function sceneHandleRequested(): boolean {
  if (typeof window === "undefined") return false;
  if (import.meta.env?.DEV === true) return true;
  if (window.__atlasExposeScene === true) return true;
  /* BOTH the current URL and the URL this document was NAVIGATED to.
   *
   * The current URL alone is not enough on the release build, and this was measured rather than
   * reasoned about (2026-09-21, `vite preview` of a production bundle): opening
   * `?s=fabric&__atlasScene=1` left `window.__atlasScene === undefined`, because `urlSync`
   * normalises the address bar to the fields it owns — `location.href` had already become
   * `?v=1&snap=9cc348bd58bb` — and this module lives in the LAZY `Fabric3D` chunk, which is
   * fetched and evaluated after that rewrite has happened. Reading the flag "once, eagerly" is
   * only eager relative to this chunk, not to the page.
   *
   * `performance.getEntriesByType("navigation")[0].name` is the URL the document was fetched
   * with. `replaceState` does not touch it, so it answers "was this page OPENED with the flag?"
   * no matter how late the question is asked. Measured on the same build: href
   * `…?v=1&snap=9cc348bd58bb`, navigation entry `…?s=fabric&__atlasScene=1`.
   */
  const asked = (href: string): boolean => {
    try {
      const q = new URL(href).searchParams.get(SCENE_HANDLE_PARAM);
      return q === "1" || q === "true";
    } catch {
      return false; /* A URL we cannot parse is not an opt-in. */
    }
  };
  try {
    if (asked(window.location.href)) return true;
    for (const nav of performance?.getEntriesByType?.("navigation") ?? []) {
      if (asked(nav.name)) return true;
    }
  } catch {
    /* No Performance Timeline is not an opt-in either. */
  }
  try {
    if (window.sessionStorage?.getItem(SCENE_HANDLE_STORAGE_KEY) === "1") return true;
  } catch {
    /* sessionStorage throws under some privacy settings; that is not an opt-in either. */
  }
  return false;
}

const REQUESTED = sceneHandleRequested();

/**
 * Publish the scene handle. Returns a cleanup function that removes it again — call it on unmount,
 * because React 19 StrictMode mounts twice in development and a stale handle pointing at a disposed
 * scene would make the harness wait on a renderer that no longer exists.
 */
export function exposeSceneForCapture(scene: FabricScene): () => void {
  if (typeof window === "undefined" || !REQUESTED) return () => {};
  window.__atlasScene = scene;
  return () => {
    // Only clear it if we are still the owner: a second mount may already have replaced us.
    if (window.__atlasScene === scene) delete window.__atlasScene;
  };
}
