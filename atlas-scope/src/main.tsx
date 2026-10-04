import "./core/tokens.css";
import "./app/shell.css";
import { applyTheme, readThemePreference } from "./app/theme-preference";
import { hasOpenedMarker } from "./core/dataset/marker";
import { showDatasetRefusal } from "./core/dataset/refusal";
import { readContractMode } from "./contract-mode/entry";

/* ── The reader's theme, before ANYTHING can paint in the wrong one (acceptance C4) ─────────────
 *
 * No page ships a `data-theme` (a hard-coded `data-theme="dark"` painted the boot line dark for a
 * light-OS reader for ~190-330 ms: the attribute survived until the application chunk's ThemeToggle
 * removed it, and since 254694b that chunk loads only AFTER the boot line has painted). With no
 * attribute, tokens.css follows the OS — which is exactly "system". An EXPLICIT stored choice is
 * applied here, synchronously, as this entry's first statement: before its wait for the boot line's
 * paint and before `import("./mount")`. One localStorage read, no import beyond a module with no
 * dependencies, so it adds nothing measurable to the boot path E5 guards.
 *
 * This is the owner, not the only line of defence: a module runs after parsing, so index.html's
 * inline <head> script applies the same choice during parsing, ahead of every paint (measured with
 * a slow entry fetch on the release build). theme-boot.test.ts executes both and requires agreement.
 */
applyTheme(readThemePreference());

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("#root missing from index.html");
const el: HTMLElement = rootEl;

// The leaf theme/marker/refusal helpers above import no dataset or application code.
// An attempted engine mode, including an invalid one, never enters ordinary dataset boot.
const contractMode = readContractMode(window.location, import.meta.env.MODE);
if (contractMode.selected) {
  if (!contractMode.valid) {
    const boot = el.querySelector(".boot");
    if (boot) showDatasetRefusal(boot, new Error("E_CONTRACT_MODE: Open the 3D view from AssessHub's Topology & Paths screen."));
  } else {
    void import("./contract-mode/boot")
      .then(({ bootContractMode }) => { bootContractMode(el, contractMode); })
      .catch((error: unknown) => {
        const boot = el.querySelector(".boot");
        if (boot) showDatasetRefusal(boot, error);
      });
  }
} else {
  startOrdinaryScope();
}

function startOrdinaryScope(): void {

/* ── Paint the boot line BEFORE the application evaluates ──────────────────────────────────────
 *
 * Acceptance E5, cold load (review/audit-e5-coldload.mjs, release build, 2026-09-22): the entry used
 * to BE the application — one 675 kB chunk that statically imported App, React and every surface.
 * The browser parsed index.html, then fetched and evaluated that chunk (70-105 ms of script) and ran
 * React's first scheduling slices, all back to back, before its first rendering step: a 203-248 ms
 * animation frame that began at 15-43 ms, i.e. on a page that had never been painted. The boot line
 * in index.html existed in the DOM throughout, but it was never on screen — first-contentful-paint
 * landed after React had already replaced it — so the "Loading Atlas Scope" status told nobody
 * anything.
 *
 * So this entry is deliberately tiny: the two base stylesheets (which Vite links in the document
 * head, so the boot line paints on the product's own ground rather than a white default) and this
 * scheduler. It waits until the boot line has been PAINTED and only then imports the application
 * chunk, so that chunk's evaluation and React's first render land in frames that begin with the
 * boot line already on screen.
 *
 * "Painted" is the browser's own presentation signal where it has one: the boot line carries
 * `elementtiming="atlas-boot"`, and the Element Timing entry for it arrives once its text has been
 * presented. A rendering step is NOT enough on its own — measured in a freshly launched Chromium, a
 * requestAnimationFrame-then-timeout wait released the import at the first rendering step (~450 ms)
 * while the first frame was not presented until ~1000 ms, so React replaced the line before anyone
 * saw it. Where Element Timing is unsupported the wait falls back to one rendering opportunity
 * (requestAnimationFrame, then a task after the step), the best signal that browser offers.
 *
 * A hidden document is never presented (a background tab, a preview pane), so it does not wait at
 * all, and a document hidden mid-wait stops waiting. The ceiling bounds a visible document whose
 * presentation is late for any other reason. No path can leave the application unmounted.
 */
const BOOT_ELEMENT_ID = "atlas-boot";
const MAX_WAIT_MS = 2000;
const FALLBACK_MAX_WAIT_MS = 200;

function afterBootLinePainted(): Promise<void> {
  return new Promise((resolve) => {
    if (document.visibilityState === "hidden") {
      resolve();
      return;
    }
    let done = false;
    let observer: PerformanceObserver | null = null;
    const finish = (): void => {
      if (done) return;
      done = true;
      observer?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      resolve();
    };
    const onVisibility = (): void => {
      if (document.visibilityState === "hidden") finish();
    };
    document.addEventListener("visibilitychange", onVisibility);

    const elementTiming =
      typeof PerformanceObserver === "function" &&
      (PerformanceObserver.supportedEntryTypes ?? []).includes("element");
    if (elementTiming) {
      observer = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          if ((e as PerformanceEntry & { identifier?: string }).identifier === BOOT_ELEMENT_ID) {
            /* The entry is delivered after presentation; one more task lets that frame finish. */
            setTimeout(finish, 0);
            return;
          }
        }
      });
      observer.observe({ type: "element", buffered: true });
      setTimeout(finish, MAX_WAIT_MS);
      return;
    }
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => setTimeout(finish, 0));
    setTimeout(finish, FALLBACK_MAX_WAIT_MS);
  });
}

/* ── The dataset, installed BEFORE the application loads ───────────────────────────────────────
 *
 * The application reads its four compiled documents once, at import (core/dataset.ts is the one door;
 * core/data.ts builds every index from it). So whichever dataset this page shows must be installed
 * before `import("./mount")`:
 *
 *   - an AssessHub build (`vite build --mode hub`, served at /scope/) carries NO dataset. It reads the
 *     snapshot id from /scope/snapshots/{id}/, fetches /api/snapshots/{id}/raw same-origin, verifies it
 *     (WebCrypto, where the page is a secure context — otherwise it says "server-attested, not
 *     re-verified"), compiles it with the one compiler in a worker, and installs it;
 *   - a standalone build shows its bundled sample, unless the reader opened a snapshot file — then a
 *     localStorage marker says so, and the compiled set is restored from IndexedDB and installed.
 *
 * The standalone sample path pays ONE localStorage read here and nothing else (no fetch, no database,
 * no extra chunk: acceptance E5), and the dataset work runs alongside the boot line's paint rather than
 * after it. A failure is a coded, plain-language refusal in place of the boot line — never the sample
 * shown under a snapshot's URL, and never a spinner that does not resolve.
 */
const HUB = import.meta.env.MODE === "hub";

function datasetReady(): Promise<void> {
  if (!HUB && !hasOpenedMarker()) return Promise.resolve();
  return import("./core/dataset/boot").then(({ prepareDataset }) =>
    prepareDataset({
      target: HUB ? "hub" : "standalone",
      pathname: location.pathname,
      base: import.meta.env.BASE_URL,
      secure: window.isSecureContext,
      fetch: window.fetch.bind(window),
      compilerId: __ATLAS_COMPILER_ID__,
      onProgress: (message) => {
        const boot = el.querySelector(".boot");
        if (boot) boot.textContent = message;
      },
    }),
  );
}

Promise.all([afterBootLinePainted(), datasetReady()])
  .then(() => import("./mount"))
  .then(({ mount }) => mount(el))
  .catch((err: unknown) => {
    /* The dataset could not be installed, or the application chunk failed to load or to mount. The boot
       line must stop claiming work is in progress — a busy status that never resolves is degradation
       reported as health — and every failure is a coded refusal (core/dataset/refusal.ts). */
    const boot = el.querySelector(".boot");
    if (boot) showDatasetRefusal(boot, err);
    throw err;
  });
}
