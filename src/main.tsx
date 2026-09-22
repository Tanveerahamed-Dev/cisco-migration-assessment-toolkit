import "./core/tokens.css";
import "./app/shell.css";

const el = document.getElementById("root");
if (!el) throw new Error("#root missing from index.html");

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

afterBootLinePainted()
  .then(() => import("./mount"))
  .then(({ mount }) => mount(el))
  .catch((err: unknown) => {
    /* The application chunk failed to load or to mount. The boot line must stop claiming work is in
       progress — a busy status that never resolves is degradation reported as health. */
    const boot = el.querySelector(".boot");
    if (boot) {
      boot.setAttribute("aria-busy", "false");
      boot.textContent = "Atlas Scope could not load. Reload the page; if it fails again, the build is incomplete.";
    }
    throw err;
  });
