/**
 * devHandle.test.ts — the opt-in that makes the frame-rate criterion evidenceable on the artefact.
 *
 * `exposeSceneForCapture` used to be gated on `import.meta.env.DEV`, which meant `window.__atlasScene`
 * — the only route to the frame-time series and to the quality tier actually in force — existed
 * solely on the dev server. Every frame-rate and tier number in an audit therefore came from a
 * build nobody ships.
 *
 * The replacement is an explicit opt-in. This file exists because the FIRST version of that opt-in
 * did not work on the artefact it was written for: measured on a `vite preview` of a real
 * production bundle (2026-09-21), opening `?s=fabric&__atlasScene=1` left `window.__atlasScene`
 * undefined. `urlSync` normalises the address bar to the fields it owns before the lazily-loaded
 * `Fabric3D` chunk — and with it this module — is ever evaluated, so by the time the flag was read
 * it had already been rewritten away. The navigation entry, which `replaceState` cannot touch, is
 * what makes the question answerable late. A gate whose success path was never executed is not a
 * gate, and neither is an opt-in nobody opted in with.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { snapshotTag } from "../app/urlSync";
import { SCENE_HANDLE_PARAM, SCENE_HANDLE_STORAGE_KEY, sceneHandleRequested } from "./devHandle";

/* The address bar as `urlSync` normalises it — with THIS build's snapshot tag, derived rather than
   typed in, so the fixture cannot go stale when the compiled source binding changes. */
const NORMALISED = `/?v=1&snap=${snapshotTag()}`;

const navEntries = (...urls: string[]): void => {
  vi.spyOn(performance, "getEntriesByType").mockImplementation((type: string) =>
    type === "navigation" ? (urls.map((name) => ({ name })) as unknown as PerformanceEntryList) : [],
  );
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
  try {
    window.sessionStorage.removeItem(SCENE_HANDLE_STORAGE_KEY);
  } catch {
    /* not every environment has one */
  }
});

describe("sceneHandleRequested — who gets a handle to the renderer", () => {
  it("says yes in a development build, with no flag at all", () => {
    vi.stubEnv("DEV", true);
    navEntries();
    expect(sceneHandleRequested()).toBe(true);
  });

  it("says NO to an ordinary visitor of a production build", () => {
    vi.stubEnv("DEV", false);
    navEntries(`http://localhost${NORMALISED}`);
    expect(sceneHandleRequested()).toBe(false);
  });

  it("says yes to the query flag in the address bar", () => {
    vi.stubEnv("DEV", false);
    navEntries();
    window.history.replaceState({}, "", `/?${SCENE_HANDLE_PARAM}=1`);
    expect(sceneHandleRequested()).toBe(true);
  });

  it("THE regression: says yes when the app has already normalised the flag out of the URL", () => {
    /* This is the production failure exactly: the page was OPENED with the flag, the router
       rewrote the address bar, and only then did the lazy chunk holding this module evaluate. */
    vi.stubEnv("DEV", false);
    window.history.replaceState({}, "", NORMALISED);
    navEntries(`http://localhost/?s=fabric&${SCENE_HANDLE_PARAM}=1`);
    expect(sceneHandleRequested()).toBe(true);
  });

  it("does not turn itself on from a navigation that never asked", () => {
    vi.stubEnv("DEV", false);
    window.history.replaceState({}, "", NORMALISED);
    navEntries("http://localhost/?s=fabric&other=1");
    expect(sceneHandleRequested()).toBe(false);
  });

  it("honours the session key, for a harness that navigates around", () => {
    vi.stubEnv("DEV", false);
    navEntries();
    window.sessionStorage.setItem(SCENE_HANDLE_STORAGE_KEY, "1");
    expect(sceneHandleRequested()).toBe(true);
  });

  it("honours the pre-mount global, which is what the measurement harness sets", () => {
    vi.stubEnv("DEV", false);
    navEntries();
    window.__atlasExposeScene = true;
    try {
      expect(sceneHandleRequested()).toBe(true);
    } finally {
      delete window.__atlasExposeScene;
    }
  });

  it("survives an environment with no Performance Timeline rather than throwing", () => {
    vi.stubEnv("DEV", false);
    vi.spyOn(performance, "getEntriesByType").mockImplementation(() => {
      throw new Error("no performance timeline here");
    });
    expect(() => sceneHandleRequested()).not.toThrow();
    expect(sceneHandleRequested()).toBe(false);
  });
});
