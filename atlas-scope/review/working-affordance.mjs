/**
 * working-affordance.mjs — the ONE definition of "something on screen says the app is working",
 * shared by every E5 instrument that excuses a long frame because the reader was told.
 *
 * REVIEW FIX, 2026-09-21. audit-e5-coldload.mjs and audit-e5-sweep.mjs each carried their own
 * document-wide existence test for ANY `[aria-busy=true]`, `[role=progressbar]`, `progress` or
 * `.stage-pending`. Any unrelated busy element anywhere on the page — a grid flagging aria-busy for
 * the length of a filter debounce, say — would have excused a frozen fabric. The two copies were
 * also free to drift apart. An affordance counts only when it NAMES the work that is slow:
 *
 *   - the boot line index.html paints before React mounts (`#root > .boot`), which says the
 *     application is loading;
 *   - the stage's own pending and warm-up surfaces, inside the fabric region (`#stage`), which say
 *     the 3-D fabric is being built;
 *   - a progress or busy element inside the fabric region.
 */
export const WORKING_AFFORDANCE_SELECTOR = [
  '#root > .boot[aria-busy="true"]',
  "#stage .stage-pending",
  "#stage .stage-warmup",
  '#stage [role="progressbar"]',
  "#stage progress",
  '#stage [aria-busy="true"]',
].join(", ");


/**
 * In-page source for the ONE predicate: the first element matching the selector that the browser
 * last reported as RENDERED ON SCREEN, or null. Interpolate it into an init script and call
 * `__visibleAffordance()`; register `window.__affListeners.push(fn)` to hear when that changes.
 *
 * REVIEW FIX, 2026-09-21 (E5). The predicate used to be `document.querySelector(selector)` —
 * presence, not visibility. App.css hides `.stage-warmup` (`display: none`) whenever the renderer
 * failed or the chunk is still being fetched, precisely so a broken fabric is never described as
 * "starting"; a presence test still counted that hidden element as the app saying it is working.
 *
 * SECOND REVIEW FIX, 2026-09-21 (E5 cold load): THE PREDICATE MUST NOT FORCE LAYOUT. It then read
 * `checkVisibility()` / `getClientRects()`, which force a synchronous style and layout of whatever
 * the app had just changed — and the sweep called it from a MutationObserver, i.e. in a microtask
 * after EVERY DOM mutation of every React commit. Measured by audit-e5-coldload.mjs: one 758 ms
 * cold-load frame was 753.8 ms of `forcedStyleAndLayout` inside the harness's own sampler, so the
 * instrument was both inflating and mis-attributing the figure it exists to report.
 *
 * Visibility now comes from an IntersectionObserver, which the browser computes during its own
 * rendering steps, after layout, and delivers asynchronously — it cannot force anything. An element
 * counts when its last report had a non-empty intersection with the viewport: a `display: none`
 * element (the case App.css relies on) has no box and never intersects; one scrolled out of view
 * does not count either, because an affordance the reader cannot see tells them nothing.
 * Stated residual: `visibility: hidden` / `opacity: 0` are not detected by this observer. No
 * affordance in the selector above is hidden that way (App.css uses `display: none` for every
 * suppression), and a future rule that did so would need this predicate revisited.
 * Where IntersectionObserver is absent the predicate answers null — nothing is excused, rather
 * than everything.
 */
/*
 * WHEN, not just whether. Each report carries `entry.time` — the rendering step in which the browser
 * computed it, i.e. the frame that painted that state — and the aggregate "any affordance on screen"
 * is kept as a timeline of those times (`window.__affTimeline`). `__affordanceAt(t)` answers "what
 * was on screen at t" from that timeline, NOT from when a sampler or a callback happened to run:
 * during a long frame no callback runs at all, so a callback-time answer describes the screen after
 * the freeze, which is the wrong question. Candidates are observed the moment they are inserted
 * (a MutationObserver doing selector matching only, which reads no style), so the first rendering
 * step that paints one also reports it. A removed candidate is recorded as gone at removal time —
 * earlier than its last paint, so the error is on the strict side.
 */
/*
 * INTERSECTING IS NOT PAINTED (review finding, E5, 2026-09-22). An IntersectionObserver entry is
 * computed in a rendering step, but a rendering step is not a presented frame: in 3 of 3 cold loads
 * the boot line was reported intersecting at 220-294 ms and removed at 279-442 ms while
 * first-contentful-paint landed at 448-640 ms — the line was credited as "on screen" for frames in
 * which the page was still blank. So an affordance is now credited only from the moment the browser
 * reports a PRESENTATION that could contain it:
 *
 *   - an element carrying an `elementtiming` attribute (the boot line does) is credited from its own
 *     Element Timing `renderTime` — the presentation time of that element's first paint; one that
 *     never received an entry was never painted and is never credited;
 *   - any other element is credited no earlier than first-contentful-paint: nothing is on screen in a
 *     document that has not yet presented any content, whatever the observer computed.
 *
 * The paint facts are collected in-page (`window.__affPaint`) and applied by ONE rule,
 * `affordancePaintedAt`, which the page (`__affordanceAt`) and the node-side instruments share, so
 * the harnesses cannot drift apart on what "on screen" means.
 */
export function affordancePaintedAt(timeline, paint, t) {
  let at = null;
  for (const rec of timeline) {
    if (rec.t > t) break;
    at = rec;
  }
  if (at === null || at.on !== true) return null;
  const fcp = paint && Number.isFinite(paint.fcp) ? paint.fcp : null;
  if (fcp === null || fcp > t) return null;
  if (at.et) {
    const rt = paint.elements ? paint.elements[at.et] : undefined;
    if (!Number.isFinite(rt) || rt > t) return null;
  }
  return at;
}

export const VISIBLE_AFFORDANCE_JS = `
  (function () {
    const SEL = ${JSON.stringify(WORKING_AFFORDANCE_SELECTOR)};
    const state = new Map(); /* element -> currently shown */
    const observed = new WeakSet();
    window.__affListeners = window.__affListeners || [];
    window.__affTimeline = [];
    window.__affPaint = { fcp: null, elements: {} };
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) if (e.name === "first-contentful-paint") window.__affPaint.fcp = +e.startTime.toFixed(1);
      }).observe({ type: "paint", buffered: true });
    } catch (_) {}
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) {
          if (!e.identifier) continue;
          const rt = e.renderTime || e.loadTime;
          if (rt > 0 && !(e.identifier in window.__affPaint.elements)) window.__affPaint.elements[e.identifier] = +rt.toFixed(1);
        }
      }).observe({ type: "element", buffered: true });
    } catch (_) {}
    const affordancePaintedAt = ${affordancePaintedAt.toString()};
    const scopeOf = (el) => el.parentElement || el;
    const describe = (el) => {
      const scope = scopeOf(el);
      const cancel = [...scope.querySelectorAll("button")].some((b) =>
        /cancel|stop|abort/i.test((b.textContent || "") + " " + (b.getAttribute("aria-label") || "")));
      return { cancel, what: (el.getAttribute("aria-label") || el.textContent || "").slice(0, 50), et: el.getAttribute("elementtiming") || null };
    };
    const firstShown = () => {
      for (const [el, on] of state) if (on && el.isConnected) return el;
      return null;
    };
    const record = (t) => {
      const el = firstShown();
      const on = el !== null;
      const last = window.__affTimeline[window.__affTimeline.length - 1];
      if (last && !last.on && !on) return;
      if (last && last.on && on) {
        /* Still on screen, but maybe a DIFFERENT affordance with a different paint signal. */
        const d = describe(el);
        if (d.et === last.et) return;
        window.__affTimeline.push(Object.assign({ t: +t.toFixed(1), on }, d));
        return;
      }
      window.__affTimeline.push(Object.assign({ t: +t.toFixed(1), on }, on ? describe(el) : { cancel: false, what: null, et: null }));
    };
    const io = typeof IntersectionObserver === "function"
      ? new IntersectionObserver((entries) => {
          for (const e of [...entries].sort((a, b) => a.time - b.time)) {
            const r = e.intersectionRect;
            state.set(e.target, e.isIntersecting && r.width > 0 && r.height > 0);
            record(e.time);
          }
          for (const f of window.__affListeners) { try { f(); } catch (_) {} }
        })
      : null;
    const adopt = () => {
      if (io === null) return;
      for (const el of document.querySelectorAll(SEL)) {
        if (!observed.has(el)) { observed.add(el); io.observe(el); }
      }
      let removed = false;
      for (const el of [...state.keys()]) {
        if (!el.isConnected) { state.delete(el); removed = true; }
      }
      if (removed) record(performance.now());
    };
    new MutationObserver(adopt).observe(document, {
      subtree: true, childList: true, attributes: true, attributeFilter: ["aria-busy", "role", "class"],
    });
    adopt();
    window.__visibleAffordance = () => {
      if (io === null) return null;
      adopt();
      return firstShown();
    };
        /* The affordance record the reader could SEE at time t — on screen per the observer AND inside a
       presented frame per the paint signals above — or null. */
    window.__affordanceAt = (t) => affordancePaintedAt(window.__affTimeline, window.__affPaint, t);
  })();
`;
