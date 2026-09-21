/**
 * measure-inp.mjs — laboratory responsiveness measurement for the declared journeys.
 *
 * HONESTY NOTE, and it is the point of this file: these are LABORATORY measurements on one machine
 * with a scripted actor. They are not field INP. Real INP is a field metric collected from real
 * users on real devices, and no lab number can substitute for it. What a lab number CAN do is catch
 * a regression and prove an interaction is not doing 300 ms of synchronous work. Every number this
 * script prints is labelled accordingly, and the report must carry that label onward.
 *
 * HOW TO RUN IT, and which run counts as evidence:
 *
 *     npm run build && npm run preview          # serves the RELEASE build on :4181
 *     node review/measure-inp.mjs               # EVIDENCE lane: release build, headed, real GPU
 *     ATLAS_HEADLESS=1 node review/measure-inp.mjs   # FLOOR lane: SwiftShader, CI tripwire only
 *
 * The defaults are the evidence lane on purpose. The previous defaults — the Vite dev server on
 * :4180, headless — changed the verdict by an order of magnitude (see the block above the APP
 * constant for the three measured configurations), so a red from them was not evidence about the
 * product and a green would not have been either. Never point ATLAS_URL at :4180.
 *
 * Method: PerformanceObserver on 'event' entries with durationThreshold 0, which is what the Event
 * Timing API exposes and what INP is computed from — the full input-delay + processing + presentation
 * delay window, not just the handler. We also record long tasks so a slow interaction can be
 * attributed rather than merely observed.
 *
 * ATTRIBUTION NOTE (added by the perf audit, 2026-09-21). Pooling every interaction entry across a
 * journey and taking the p95 UNDERSTATES the journey when one repetition produces several
 * interactions of which only one is the journey. `Control+k` yields three interactions per rep
 * (Control keydown, k keydown, Escape keydown); two of them are trivial keypresses that nothing
 * handles, and they drag the pooled p95 down towards them. So the harness now windows the Event
 * Timing buffer PER REPETITION and reports two figures:
 *
 *   inp.p95          — pooled over every interaction, the previous (looser) figure.
 *   worstPerRep.p95  — p95 over the SLOWEST interaction in each repetition.
 *
 * `worstPerRep` is what INP actually means for a journey — the worst thing the user waited on in
 * that interaction — and it is the figure the verdict is taken from. When the two diverge, the
 * divergence is printed, because it is exactly the measurement-honesty defect this file is meant
 * not to have.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));

/* ── WHICH BUILD, ON WHICH RENDERER — the two settings that decide the verdict ─────────────────
 *
 * The responsiveness criterion is about the REAL BUILD on a REAL GPU. This harness used to default
 * to neither, and the defaults moved the answer by an order of magnitude. Measured 2026-09-21,
 * same five journeys, three configurations:
 *
 *   :4180 (Vite DEV server) + headless      -> 1 pass, 4 fail   J4 worst 1152 ms
 *   :4181 (release preview) + headless      -> 2 pass, 3 fail   J4 worst  384 ms
 *   :4181 (release preview) + HEADED        -> 5 pass, 0 fail   J4 worst   80 ms
 *
 * Both defaults were wrong in the same direction. `http://localhost:4180` serves the dev bundle —
 * unminified, StrictMode double-invoking, `/@vite/client` and `@react-refresh` attached — which is
 * not the artefact any criterion is written about. And headless Chromium has no GPU: WebGL runs on
 * SwiftShader, the application's own capability probe detects the software rasteriser and drops
 * itself to quality tier "low" with shadows and SSAO disabled, and every rendered frame becomes a
 * long task. Headless renderer string here is
 *   "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)" -> tier low
 * against headed
 *   "ANGLE (Intel, Intel(R) Graphics (0x00007D41) Direct3D11 vs_5_0 ps_5_0, D3D11)"   -> tier high
 *
 * So there are two lanes, and the report says which one produced every number:
 *
 *   EVIDENCE lane (the default, and the only one whose numbers may be quoted against the 200 ms
 *                  bar): release build, headed, real GPU.
 *   FLOOR lane    (ATLAS_HEADLESS=1): software rasteriser. Useful as a regression tripwire and for
 *                  CI, worthless as evidence about the product. Its verdicts are spelled
 *                  FLOOR-PASS / FLOOR-FAIL so a number from it cannot be pasted into an acceptance
 *                  table without the label coming with it.
 *
 * The lane is not taken on trust either: the harness fetches the served HTML and reports whether it
 * is a dev server, and reads the renderer string and the quality tier out of the running page. If
 * you point ATLAS_URL at :4180, the run still happens — but `devServer: true` lands in the report
 * envelope and `acceptanceEvidence` goes false, because a dev-bundle number is not E2 evidence. */
const RELEASE_URL = "http://localhost:4181"; // `npm run build && npm run preview`
const APP = process.env.ATLAS_URL || RELEASE_URL;
const HEADED = process.env.ATLAS_HEADLESS !== "1";
const LANE = HEADED ? "evidence" : "floor";
const REPS = Number(process.env.ATLAS_REPS || 25);

/** Ask the page for the renderer it is actually using, and for the tier the app chose from it. */
const RENDERER_PROBE = `(() => {
  let renderer = null, vendor = null, webglError = null;
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    if (gl) {
      const dbg = gl.getExtension("WEBGL_debug_renderer_info");
      renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
      vendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
    } else webglError = "no webgl context";
  } catch (e) { webglError = String(e).slice(0, 120); }
  const s = window.__atlasScene?.stats?.() ?? null;
  return {
    renderer, vendor, webglError,
    quality: s?.quality ?? null,
    qualityReasons: s?.qualityReasons ?? null,
    sceneHandle: Boolean(window.__atlasScene),
  };
})()`;

const INSTRUMENT = `
  window.__ev = [];
  window.__long = [];
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) {
      window.__ev.push({
        name: e.name, duration: e.duration, startTime: e.startTime,
        processingStart: e.processingStart, processingEnd: e.processingEnd,
        inputDelay: e.processingStart - e.startTime,
        processing: e.processingEnd - e.processingStart,
        presentation: e.startTime + e.duration - e.processingEnd,
        interactionId: e.interactionId,
      });
    }
  }).observe({ type: 'event', buffered: true, durationThreshold: 0 });
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) window.__long.push({ name: e.name, duration: e.duration, startTime: e.startTime });
  }).observe({ type: 'longtask', buffered: true });
`;

const pct = (xs, p) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const i = Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1);
  return Number(s[Math.max(0, i)].toFixed(1));
};

/** Collapse Event Timing entries to one duration per interactionId, as INP is defined. */
const interactionDurations = (entries) => {
  const byId = new Map();
  for (const e of entries) {
    if (!e.interactionId || e.interactionId <= 0) continue;
    byId.set(e.interactionId, Math.max(byId.get(e.interactionId) ?? 0, e.duration));
  }
  return [...byId.values()];
};

/** Canvas points proven to select a device, found once per run by `J2`'s `prime`. */
const J2_HITS = [];

const deviceAnchors = async (page) => {
  /* Scan the canvas for points that actually pick a DEVICE, and keep only those.
     The selection is read back from the URL (`d=` is a navigation field in urlSync), so a point is
     kept only when the APPLICATION says a device became selected. That is deliberately independent
     of `window.__atlasScene`: the scene handle is an instrument, and an instrument should not be
     the thing that decides whether the actuation worked. The scan runs once, in `prime`. */
  const canvas = page.locator("canvas").first();
  const b = await canvas.boundingBox();
  if (!b) return [];
  const hits = [];
  const seen = new Set();
  for (let gy = 0; gy < 9 && hits.length < 12; gy++) {
    for (let gx = 0; gx < 9 && hits.length < 12; gx++) {
      const x = b.x + b.width * (0.1 + 0.8 * (gx / 8));
      const y = b.y + b.height * (0.1 + 0.8 * (gy / 8));
      await page.mouse.click(x, y);
      await page.waitForTimeout(120);
      const id = await page.evaluate(() => (location.search.match(/[?&]d=([^&]*)/) || [])[1] ?? null);
      if (id && !seen.has(id)) {
        seen.add(id);
        hits.push({ id, x, y });
      }
    }
  }
  return hits;
};

/**
 * Each journey is a named, repeatable interaction. `act` performs ONE interaction; the harness
 * repeats it and reports the distribution. Selectors are resilient: a journey that cannot find its
 * target is reported as NOT MEASURED rather than silently contributing zero samples — an
 * unmeasured journey must never read as a fast one.
 *
 * `prime` runs ONCE before the measured loop. Setup clicks belong there, not in `act`: a click that
 * focuses an input is a cheap interaction, and repeating it inside the loop doubles the sample count
 * with samples that are not the journey and halves the reported p95.
 */
const JOURNEYS = [
  {
    id: "J1-select-finding",
    url: "/?s=findings",
    /* AUDIT FIX. `[role="row"]` was NOT the declared journey. The "Findings, ranked" grid is
       grouped by severity, and its group headers are rows too (`.ag__row--group`, with
       aria-expanded). Measured 2026-09-21: of the first five reps, every one clicked a group
       header — "Critical3", "High104", "Medium33", "Low6", "Info0" — which COLLAPSES that group.
       The visible row count fell 152 -> 149 -> 45 -> 12 -> 6 within four repetitions, so the
       journey spent most of its reps toggling group collapse on a grid it had already emptied,
       and the figure it reported was not "select a finding" at all.
       A data row is a row that is not a group row; that is what this journey is about. */
    /* Selection is wired on the CELL (`onActivate` in DataGrid's gridcell onClick), not the row,
       and Playwright's `row.click()` targets the row's centre — which lands in the grid gap
       BETWEEN cells. Measured 2026-09-21 on the production build: clicking every one of the six
       cells of a data row sets `?f=F004` and re-aims the evidence pane; clicking the same row's
       centre leaves the URL at `?s=findings` and changes nothing. So the journey must click a
       cell, and `verify` asserts the selection actually happened rather than trusting the click. */
    ready: ".ag__row--data [role=\"gridcell\"]",
    verify: async (page) => {
      const n = await page.locator(".ag__row--data").count();
      if (n < 5) return `only ${n} finding data rows present`;
      const before = await page.evaluate(() => location.search);
      await page.locator(".ag__row--data").nth(2).locator('[role="gridcell"]').first().click();
      await page.waitForTimeout(400);
      const after = await page.evaluate(() => location.search);
      return /[?&]f=/.test(after) && after !== before
        ? null
        : `selecting a finding did not change the investigation (URL ${before} -> ${after})`;
    },
    act: async (page, i) => {
      const rows = page.locator(".ag__row--data");
      const n = await rows.count();
      if (n < 2) throw new Error("no finding data rows");
      // Column 2 is the title cell — the one a reader actually aims at.
      await rows.nth(i % n).locator('[role="gridcell"]').nth(1).click();
    },
  },
  {
    id: "J2-select-device-3d",
    url: "/?s=fabric",
    ready: "canvas",
    /* AUDIT FIX. The old actuation swept a fixed lattice of canvas fractions and clicked whatever
       was under them. Measured 2026-09-21 on the production build (review/_audit_j2.mjs): of 25
       such clicks, only 11 selected anything at all and 4 of those picked a LINK — so just 7 of 25
       repetitions were the declared journey, "select a device in 3-D". The other 14 hit empty
       space, which is the cheapest interaction the app has, and they dominated the percentile.
       A journey whose actuation misses its target 56% of the time reports the cost of missing.

       Devices are now aimed at through their own labels: FabricLabels writes one
       `.fabric3d-label[data-device]` per host and positions it with a translate3d whose x/y is the
       device's projected screen anchor, so the label's transform gives a point that is ON the
       device. The click still goes to the CANVAS at that point — this remains a real 3-D pick, not
       a DOM shortcut. */
    prime: async (page) => {
      J2_HITS.length = 0;
      J2_HITS.push(...(await deviceAnchors(page)));
      await page.waitForTimeout(400);
    },
    /* No `verify` here: `prime` IS the verification, and it is stronger than one. It keeps a canvas
       point only when the application reports a device selected, so if fewer than three such points
       exist the journey cannot run and `act` throws, which the harness reports as NOT MEASURED. */
    act: async (page, i) => {
      if (J2_HITS.length < 3) throw new Error(`only ${J2_HITS.length} canvas points select a device`);
      const a = J2_HITS[i % J2_HITS.length];
      await page.mouse.click(a.x, a.y);
    },
  },
  {
    id: "J3-type-query",
    url: "/?s=findings",
    /* AUDIT FIX. This journey was NOT MEASURED because the selector looked for
       `input[type="search"]` and the application's query bar is `<input type="text"
       class="hdr-query__input">` (src/app/Header.tsx). There is no type=search input anywhere in
       the build — verified by enumerating every input on all four surfaces. The journey was
       unmeasurable only because the harness was pointed at an element that does not exist. */
    ready: ".hdr-query__input, .pq-query__input, [data-journey=\"query-input\"]",
    verify: async (page) => {
      const input = page.locator(".hdr-query__input, [data-journey=\"query-input\"]").first();
      await input.click();
      await input.press("a");
      await page.waitForTimeout(200);
      const v = await input.inputValue();
      if (!v.includes("a")) {
        await input.fill("");
        return "typing into the query bar did not change its value";
      }
      /* The journey is a filter over the corpus, so the corpus must still be there. A keystroke
         that empties the grid measures the cheapest render this surface has; if the characters this
         harness types stopped matching anything, the journey would silently become that. */
      const rows = await page.locator(".ag__row--data").count();
      // Leave the field as we found it so the measured loop starts from empty.
      await input.fill("");
      await page.waitForTimeout(100);
      return rows > 0
        ? null
        : "typing one character emptied the findings grid — the measured keystroke would not be a filter over the corpus";
    },
    prime: async (page) => {
      // Focus once, outside the measured window. Inside it, the focus click would be a second,
      // much cheaper interaction per rep and would drag the p95 down.
      await page.locator(".hdr-query__input, [data-journey=\"query-input\"]").first().click();
      await page.waitForTimeout(200);
    },
    /* PERF AUDIT FIX, 2026-09-21 (second pass). The previous `act` pressed successive characters of
       "severity:Critical" into a field it NEVER CLEARED, so the query grew without bound across the
       25 repetitions. Measured on the release build (review/_audit_perf_j3_valid.mjs), rep-by-rep
       visible data-row count:

         rep  0 "s"                        146 rows
         rep  8 "severity:"                146 rows
         rep 16 "severity:Critical"          3 rows
         rep 17 "severity:Criticals"         0 rows   <- and 0 for every rep thereafter
         ... 17 of the 25 repetitions rendered ZERO data rows.

       The declared journey (design-brief 8.2, row 3) is "a candidate filter over 146 findings".
       A keystroke that re-renders an EMPTY grid is the cheapest thing this surface can do, and it
       was two thirds of the sample — so the reported p95 was the cost of typing into a dead filter,
       not the cost of the journey. Same defect shape as the J1 group-header bug above: the
       actuation drifted off the declared journey and the number stayed plausible.

       Fixed by resetting the field between repetitions through `fill()` — which sets the value
       without a keyboard interaction, so it contributes no Event Timing entry (verified by the
       eventHistogram staying at one keydown/keypress/keyup per rep) — and settling the 146-row
       re-render BEFORE the measured keystroke, so the keystroke is timed against the full grid.
       Every measured character is therefore the first character typed into a 146-row result, which
       is the heaviest and most representative case the journey has. */
    act: async (page, i) => {
      /* The reset must emit NO key event: Playwright's `fill()` on a non-empty field presses a
         delete key, which the Event Timing API records as a second interaction in the repetition —
         measured, eventHistogram went to `keydown 50, keypress 25` over 25 reps — and harness setup
         must not be inside the measured journey. Writing through the native value setter and
         dispatching `input` is the React-controlled-input reset that produces no keyboard entry. */
      await page.evaluate(() => {
        const el = document.querySelector(".hdr-query__input, [data-journey=\"query-input\"]");
        if (!(el instanceof HTMLInputElement) || el.value === "") return;
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        setter?.call(el, "");
        el.dispatchEvent(new Event("input", { bubbles: true }));
      });
      /* Wait for the restored grid to COMMIT, rather than sleeping a guessed interval: otherwise
         the reset's own re-render spills into the measured keystroke and the journey is charged
         for harness setup. The row count is the app's own signal that the commit landed; the
         settle afterwards lets its long task drain off the main thread. */
      await page
        .waitForFunction(() => document.querySelectorAll(".ag__row--data").length >= 100, null, { timeout: 5000 })
        .catch(() => {});
      await page.waitForTimeout(400);
      const CHARS = "coreaccesswitdb";
      await page.keyboard.press(CHARS.charAt(i % CHARS.length));
    },
  },
  {
    id: "J4-run-path-trace",
    /* AUDIT FIX. This journey was NOT MEASURED because `#rail-path` — and with it the "Trace this
       flow" button — is ABSENT from the DOM until a flow is being investigated (src/app/surfaces.tsx
       RailA: `hasPath ? <PathTrace/> : null`). `/?s=path` sets the surface but no flow, so the panel
       never mounts and the harness waited 15 s for a button that cannot exist yet. The URL now
       carries a flow, which is the app's own documented way to reach that state (urlSync carries
       `flow=src>dst>proto>port`). Addresses are real: 10.0.10.50 is an observed endpoint
       (endpoint_identity[0]) and 10.0.20.0/24 is a connected route on core1 (routes.core1[4]). */
    url: "/?s=path&flow=10.0.10.50>10.0.20.10>tcp>443",
    ready: '#rail-path form.pt-form button[type="submit"]',
    verify: async (page) => {
      const btn = page.locator('#rail-path form.pt-form button[type="submit"]').first();
      const txt = (await btn.textContent()) ?? "";
      if (!/trace/i.test(txt)) return `submit button reads ${JSON.stringify(txt)}, not a trace action`;
      const result = await page.locator("#rail-path .pt-result__title, #rail-path h3").count();
      return result > 0 ? null : "no trace result rendered for the seeded flow — the panel mounted but did not trace";
    },
    act: async (page) => {
      /* Every repetition must be a genuinely NEW flow: re-submitting the identical flow is
         short-circuited (`flowKey(trace.flow) === flowKey(flow)` in PathTrace), so a fixed flow
         would measure a no-op and report it as a fast trace.

         The obvious way to vary it — typing a new destination port — CANNOT be used: every text
         field in this form crashes the panel on one keystroke under the dev server, because the
         onChange handlers read `e.currentTarget.value` from inside the `setForm` UPDATER, and an
         updater runs after React has nulled `currentTarget` (StrictMode double-invokes it during
         render, which is when it bites). Measured 2026-09-21: one real keystroke in Source IP,
         Destination IP or Destination port replaces `#rail-path` with the error boundary on
         :4180; :4181 (production) survives, so it is dev-only TODAY but it is the same code.

         So the flow is varied with the SWAP button, whose handler takes no event: it alternates
         A->B and B->A, and each submit therefore traces a flow the store has not got. Swap is
         itself an interaction, but it is a trivial one, and the verdict figure is the WORST
         interaction in the repetition — which is the submit, i.e. the trace. */
      await page.locator("#rail-path .pt-form__swap").first().click();
      await page.waitForTimeout(80);
      await page.locator('#rail-path form.pt-form button[type="submit"]').first().click();
    },
  },
  {
    id: "J5-open-palette",
    url: "/",
    ready: "body",
    /* `ready: "body"` is always satisfiable, so this journey NEEDS an effect check — without one it
       measures the browser's response to a keypress that did nothing and reports PASS. It did
       exactly that against the scaffold: 16 ms, one sample, no palette in the application at all.
       A journey that can pass while the feature is absent measures nothing. */
    verify: async (page) => {
      await page.keyboard.press("Control+k");
      await page.waitForTimeout(250);
      const open = await page
        .locator('[role="dialog"], [role="combobox"][aria-expanded="true"], [data-journey="palette"]')
        .first()
        .isVisible()
        .catch(() => false);
      await page.keyboard.press("Escape");
      await page.waitForTimeout(150);
      return open ? null : "Cmd/Ctrl+K opened no dialog or combobox — the palette is absent or not wired";
    },
    act: async (page) => {
      await page.keyboard.press("Control+k");
      await page.waitForTimeout(60);
      await page.keyboard.press("Escape");
    },
  },
];

/* Is the thing at ATLAS_URL the release build, or a dev server wearing its port?
   `/@vite/client` and `@react-refresh` are only ever in the dev bundle's HTML. This is asked of the
   server rather than assumed from the port number, because the port is a convention and the
   distinction is the whole point of the lane. */
const probeServer = async (url) => {
  try {
    const res = await fetch(url, { redirect: "follow" });
    const html = await res.text();
    return {
      reachable: true,
      status: res.status,
      devServer: /\/@vite\/client|@react-refresh/.test(html),
    };
  } catch (e) {
    return { reachable: false, status: null, devServer: null, error: String(e).slice(0, 160) };
  }
};

/**
 * Navigate, retrying ONCE on a transport-level failure.
 *
 * Observed 2026-09-21: one run in four reported J5 as NOT MEASURED with
 * `net::ERR_HTTP_RESPONSE_CODE_FAILURE at http://localhost:4181/`, while curl got 200 from the same
 * three URLs seconds later and `ATLAS_ONLY=J5` passed on its own. That is the preview server
 * hiccuping on one navigation; it says nothing about the product, and NOT MEASURED is supposed to
 * mean "the app could not be exercised" — a claim about the app.
 *
 * So a transport failure is retried once and, if it persists, recorded as its own outcome. The
 * run still exits non-zero (a journey nobody measured is not a pass), but the report says whether
 * the failure was the transport or the application.
 */
const TRANSPORT_FAILURE = /net::ERR_|ERR_CONNECTION|ERR_EMPTY_RESPONSE|ERR_HTTP|socket hang up|ECONNRESET|ECONNREFUSED/i;

const gotoWithRetry = async (page, url) => {
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
    return { ok: true, retried: false, firstError: null };
  } catch (e) {
    const message = String(e);
    if (!TRANSPORT_FAILURE.test(message)) throw e;
    await page.waitForTimeout(500);
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
      return { ok: true, retried: true, firstError: message.slice(0, 200) };
    } catch (again) {
      return { ok: false, retried: true, firstError: message.slice(0, 200), error: String(again).slice(0, 200) };
    }
  }
};

const server = await probeServer(APP);
if (!server.reachable) {
  console.error(
    `Nothing is serving ${APP}. The evidence lane needs the RELEASE build:\n` +
      `  npm run build\n  npm run preview        # serves ${RELEASE_URL}\n` +
      `Set ATLAS_URL only to point at a different release preview — never at the dev server.`,
  );
  process.exit(2);
}
if (server.devServer) {
  console.warn(
    `WARNING: ${APP} is a Vite DEV server (its HTML loads /@vite/client). These numbers describe ` +
      `the dev bundle, not the product. acceptanceEvidence=false in the report.`,
  );
}

const browser = await chromium.launch(
  HEADED ? { headless: false, args: ["--window-size=1940,1180"] } : {},
);
/* Publish the scene handle on the release build too. `devHandle.ts` no longer gates it on
   `import.meta.env.DEV` — which is what made the tier unreadable on the artefact under test — and
   this is the opt-in it now looks for. Set before the app mounts, so it is read at module eval. */
const EXPOSE_SCENE = `window.__atlasExposeScene = true;`;
const results = [];
let environment = null;

const ONLY = process.env.ATLAS_ONLY ? process.env.ATLAS_ONLY.split(",") : null;
for (const j of JOURNEYS.filter((x) => !ONLY || ONLY.some((o) => x.id.includes(o)))) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await ctx.addInitScript(EXPOSE_SCENE);
  await ctx.addInitScript(INSTRUMENT);
  const page = await ctx.newPage();
  const rec = { id: j.id, measured: false, reason: null, reps: 0, inp: {}, longTasks: {} };
  try {
    const nav = await gotoWithRetry(page, `${APP}${j.url}`);
    if (nav.retried) rec.transportRetry = nav.firstError;
    if (!nav.ok) {
      rec.transportFailure = nav.error ?? nav.firstError;
      rec.reason = `transport: ${rec.transportFailure}`;
      rec.verdict = "TRANSPORT";
      rec.e3Verdict = "NOT MEASURED";
      await ctx.close();
      results.push(rec);
      console.log(`${"TRANSPORT".padEnd(12)} ${rec.id.padEnd(22)} [server did not serve the page twice: ${rec.transportFailure}]`);
      continue;
    }
    await page.waitForSelector(j.ready, { timeout: 15000 });
    await page.waitForTimeout(2500); // let first-paint work drain so we measure steady state

    /* Record the machine that produced these numbers, per journey, so a reader can see which one
       did — and so a SwiftShader figure can never be mistaken for a GPU figure after the fact. */
    rec.environment = await page.evaluate(RENDERER_PROBE).catch(() => null);
    if (environment === null && rec.environment) environment = rec.environment;

    /* Prove the interaction actually DOES something before measuring how fast it does it. A
       latency figure for a no-op is not a fast interaction, it is a missing one — and it is worse
       than no figure at all, because it reports as PASS. */
    if (typeof j.verify === "function") {
      const why = await j.verify(page).catch((e) => `verify threw: ${String(e).slice(0, 120)}`);
      if (why) {
        rec.reason = why;
        rec.verdict = "NOT MEASURED";
        await ctx.close();
        results.push(rec);
        console.log(`${"NOT MEASURED".padEnd(12)} ${rec.id.padEnd(22)} [${why}]`);
        continue;
      }
    }

    if (typeof j.prime === "function") await j.prime(page);

    await page.evaluate(() => {
      window.__ev.length = 0;
      window.__long.length = 0;
    });

    let ok = 0;
    const perRepWorst = [];
    const allEntries = [];
    for (let i = 0; i < REPS; i++) {
      try {
        await j.act(page, i);
        ok++;
      } catch (e) {
        rec.reason = `act failed at rep ${i}: ${String(e).slice(0, 140)}`;
        break;
      }
      await page.waitForTimeout(160); // separate interactions so they get distinct interactionIds
      // Window the buffer per repetition so one rep's interactions can be attributed to that rep.
      const window_ = await page.evaluate(() => {
        const ev = window.__ev.slice();
        window.__ev.length = 0;
        return ev;
      });
      allEntries.push(...window_);
      const d = interactionDurations(window_);
      if (d.length) perRepWorst.push(Math.max(...d));
    }

    const data = await page.evaluate(() => ({ ev: window.__ev, long: window.__long }));
    allEntries.push(...data.ev);
    // INP is computed from interactions — entries with a non-zero interactionId. Discrete events
    // (click, keydown/up) are what count; continuous ones (mousemove) are not interactions.
    const interactions = allEntries.filter((e) => e.interactionId && e.interactionId > 0);
    const durations = interactionDurations(allEntries);

    rec.measured = perRepWorst.length > 0;
    rec.reps = ok;
    rec.samples = durations.length;
    rec.repsWithASample = perRepWorst.length;
    if (!rec.measured) rec.reason = rec.reason ?? "no interaction entries observed";
    rec.inp = {
      p50: pct(durations, 50),
      p75: pct(durations, 75),
      p95: pct(durations, 95),
      max: durations.length ? Number(Math.max(...durations).toFixed(1)) : null,
      inputDelayP95: pct(interactions.map((e) => e.inputDelay), 95),
      processingP95: pct(interactions.map((e) => e.processing), 95),
      presentationP95: pct(interactions.map((e) => e.presentation), 95),
    };
    rec.worstPerRep = {
      p50: pct(perRepWorst, 50),
      p75: pct(perRepWorst, 75),
      p95: pct(perRepWorst, 95),
      max: perRepWorst.length ? Number(Math.max(...perRepWorst).toFixed(1)) : null,
      n: perRepWorst.length,
    };
    // How many interaction entries each repetition produced, and of what kind — the dilution check.
    const hist = {};
    for (const e of interactions) hist[e.name] = (hist[e.name] ?? 0) + 1;
    rec.eventHistogram = hist;
    rec.interactionsPerRep = ok ? Number((durations.length / ok).toFixed(2)) : null;

    const lt = data.long.map((l) => l.duration);
    rec.longTasks = { count: lt.length, over50ms: lt.filter((d) => d > 50).length, maxMs: lt.length ? Number(Math.max(...lt).toFixed(1)) : 0 };
    /* PERF AUDIT 2026-09-21. E3's evidence column asks for a "long-task trace for each journey",
       not a count. A count cannot answer the question E3 actually asks — whether the long task is
       ON THE INTERACTION PATH — so the raw list is kept, and every long task is attributed to the
       interaction whose [startTime, startTime+duration] window it overlaps. A long task that
       overlaps no interaction is off-path (idle-time work); one that overlaps is on-path and is an
       E3 violation regardless of whether the journey's p95 stayed under 200 ms. */
    rec.longTaskList = data.long
      .map((l) => ({ ...l, duration: Number(l.duration.toFixed(1)), startTime: Number(l.startTime.toFixed(1)) }))
      .sort((a, b) => b.duration - a.duration);
    rec.longTasksOnInteractionPath = rec.longTaskList
      .filter((l) => l.duration > 50)
      .map((l) => {
        const hit = interactions.find(
          (e) => l.startTime < e.startTime + e.duration + 1 && l.startTime + l.duration > e.startTime - 1,
        );
        return {
          durationMs: l.duration,
          startTime: l.startTime,
          overlapsInteraction: hit ? hit.name : null,
          interactionDurationMs: hit ? Number(hit.duration.toFixed(1)) : null,
        };
      });
    rec.longTasksOver50OnPath = rec.longTasksOnInteractionPath.filter((x) => x.overlapsInteraction).length;
    /* The verdict is taken from worstPerRep: it is the figure that cannot be diluted by companion
       keypresses, and it is what a user actually waited on in one go at the journey.
       In the FLOOR lane it is spelled FLOOR-PASS / FLOOR-FAIL. A software-rasteriser number is
       still a useful tripwire — a regression shows up in it — but it is not a statement about the
       product, and the label travels with the number so it cannot be quoted as one. */
    const within = (rec.worstPerRep.p95 ?? 1e9) <= 200;
    /* E3 IS A SECOND AXIS, AND IT USED TO BE UNABLE TO FAIL.
     *
     * The verdict below is E2's: worstPerRep.p95 <= 200 ms. E3 is a different criterion — "no
     * single task exceeds 50 ms on the interaction path" — and this harness recorded the long
     * tasks that violate it, printed them, and then took its PASS/FAIL and its exit code from the
     * INP figure alone. Observed: `PASS J2-select-device-3d worstPerRep p95=176ms … longTasks>50ms=12
     * (max 162ms, ON-PATH 12)` followed by "5 pass, 0 fail" and exit 0. The only automated
     * instrument for E3 was structurally incapable of reporting an E3 failure.
     *
     * So the E3 verdict is computed separately, named separately (E3-PASS / E3-FAIL so it can
     * never be read as the INP verdict), and counted into the exit code. A journey can now pass
     * E2 and fail E3 in the same line, which is exactly what this build does. */
    const e3Clean = (rec.longTasksOver50OnPath ?? 0) === 0;
    rec.verdict = !rec.measured
      ? "NOT MEASURED"
      : LANE === "evidence"
        ? within
          ? "PASS"
          : "FAIL"
        : within
          ? "FLOOR-PASS"
          : "FLOOR-FAIL";
    rec.e3Verdict = !rec.measured ? "NOT MEASURED" : e3Clean ? "E3-PASS" : "E3-FAIL";
    rec.e3Why = e3Clean
      ? "no task over 50 ms overlapped an interaction in this journey"
      : `${rec.longTasksOver50OnPath} task(s) over 50 ms overlapped an interaction; worst ${rec.longTasks.maxMs} ms`;
    rec.dilution =
      rec.inp.p95 !== null && rec.worstPerRep.p95 !== null && rec.worstPerRep.p95 > rec.inp.p95 * 1.25
        ? `pooled p95 ${rec.inp.p95}ms understates this journey; the worst interaction per repetition is ${rec.worstPerRep.p95}ms because each rep emits ${rec.interactionsPerRep} interactions`
        : null;
  } catch (e) {
    rec.reason = String(e).slice(0, 300);
    rec.verdict = "NOT MEASURED";
  }
  await ctx.close();
  results.push(rec);
  console.log(
    `${rec.verdict.padEnd(12)} ${(rec.e3Verdict ?? "-").padEnd(9)} ${rec.id.padEnd(22)} worstPerRep p95=${rec.worstPerRep?.p95 ?? "-"}ms p50=${rec.worstPerRep?.p50 ?? "-"}ms max=${rec.worstPerRep?.max ?? "-"}ms | pooled p95=${rec.inp?.p95 ?? "-"}ms  samples=${rec.samples ?? 0}  longTasks>50ms=${rec.longTasks?.over50ms ?? "-"} (max ${rec.longTasks?.maxMs ?? "-"}ms, ON-PATH ${rec.longTasksOver50OnPath ?? "-"})${rec.reason ? "  [" + rec.reason + "]" : ""}`,
  );
  if (rec.dilution) console.log(`             ${" ".repeat(22)} DILUTION: ${rec.dilution}`);
}

await browser.close();

const softwareRasteriser = /swiftshader|llvmpipe|software|microsoft basic render/i.test(
  environment?.renderer ?? "",
);
/* Acceptance evidence requires ALL of: the release bundle, a headed browser, and a renderer that is
   not a software rasteriser. Any one of them missing and these are floor numbers, whatever port
   they came from — which is why this is computed from what was OBSERVED rather than from the lane
   that was requested. */
const acceptanceEvidence = LANE === "evidence" && server.devServer === false && !softwareRasteriser;

const out = {
  measurementClass: "LABORATORY — scripted actor, single machine, unthrottled. NOT field INP.",
  threshold:
    "INP p95 <= 200 ms per web.dev/articles/inp (good threshold is p75 <= 200 ms in the field; we hold ourselves to p95 in the lab).",
  verdictBasis:
    "worstPerRep.p95 — the slowest interaction within each repetition, p95 across repetitions.",
  lane: LANE,
  /* The single field a reader should look at before quoting any number below. */
  acceptanceEvidence,
  acceptanceEvidenceWhy: acceptanceEvidence
    ? "release bundle, headed browser, hardware renderer — these numbers are about the product."
    : [
        LANE === "evidence" ? null : "FLOOR lane: run without ATLAS_HEADLESS=1 for evidence.",
        server.devServer ? `${APP} serves the Vite DEV bundle, not the release build.` : null,
        softwareRasteriser
          ? `renderer is a software rasteriser (${environment?.renderer ?? "unknown"}); the app drops to quality tier "${environment?.quality ?? "unknown"}".`
          : null,
        environment === null ? "no renderer could be read from the page." : null,
      ]
        .filter(Boolean)
        .join(" "),
  /* The machine that produced the numbers. Recorded because the same five journeys measured
     1152 ms and 80 ms on this one machine depending only on these two settings. */
  environment: {
    headed: HEADED,
    url: APP,
    devServer: server.devServer,
    httpStatus: server.status,
    renderer: environment?.renderer ?? null,
    vendor: environment?.vendor ?? null,
    softwareRasteriser,
    qualityTier: environment?.quality ?? null,
    qualityReasons: environment?.qualityReasons ?? null,
    sceneHandle: environment?.sceneHandle ?? false,
    node: process.version,
    platform: process.platform,
    capturedAt: new Date().toISOString(),
  },
  url: APP,
  reps: REPS,
  journeys: results,
  summary: {
    pass: results.filter((r) => r.verdict === "PASS" || r.verdict === "FLOOR-PASS").length,
    fail: results.filter((r) => r.verdict === "FAIL" || r.verdict === "FLOOR-FAIL").length,
    notMeasured: results.filter((r) => r.verdict === "NOT MEASURED").length,
    /* Journeys whose navigation the SERVER failed twice. Counted apart from notMeasured because
       "the app could not be exercised" and "the page was never served" are different findings. */
    transportFailures: results.filter((r) => r.verdict === "TRANSPORT").length,
    /* The E3 axis. Separate names, separate counts: a journey can pass the 200 ms INP bar and
       still put a 162 ms task on the interaction path, and for as long as this harness reported
       only the first of those, E3 could not go red. */
    e3Pass: results.filter((r) => r.e3Verdict === "E3-PASS").length,
    e3Fail: results.filter((r) => r.e3Verdict === "E3-FAIL").length,
  },
  e3: {
    criterion: "E3 — no single task exceeds 50 ms on the interaction path.",
    basis:
      "longTasksOver50OnPath: long tasks over 50 ms whose [startTime, startTime+duration] window overlaps an Event Timing interaction in the same journey.",
    verdict: results.some((r) => r.e3Verdict === "E3-FAIL")
      ? "FAIL"
      : results.some((r) => r.e3Verdict === "E3-PASS")
        ? "PASS"
        : "NOT MEASURED",
    offenders: results
      .filter((r) => r.e3Verdict === "E3-FAIL")
      .map((r) => ({ id: r.id, onPath: r.longTasksOver50OnPath, worstMs: r.longTasks?.maxMs ?? null, why: r.e3Why })),
  },
};
mkdirSync(resolve(HERE, "reports"), { recursive: true });
writeFileSync(resolve(HERE, "reports", "inp.json"), JSON.stringify(out, null, 1));
console.log(
  `\n${out.summary.pass} pass, ${out.summary.fail} fail, ${out.summary.notMeasured} NOT MEASURED` +
    `${out.summary.transportFailures > 0 ? `, ${out.summary.transportFailures} TRANSPORT (server, not app)` : ""}`,
);
console.log(
  `E3 (no task over 50 ms on the interaction path): ${out.e3.verdict} — ` +
    `${out.summary.e3Pass} clean, ${out.summary.e3Fail} violating` +
    `${out.e3.offenders.length ? ": " + out.e3.offenders.map((o) => `${o.id} ${o.onPath} on-path, worst ${o.worstMs}ms`).join("; ") : ""}`,
);
console.log(
  `lane=${LANE}  url=${APP}  devServer=${server.devServer}  headed=${HEADED}\n` +
    `renderer=${JSON.stringify(environment?.renderer ?? null)}  qualityTier=${environment?.quality ?? "unknown"}`,
);
console.log(
  acceptanceEvidence
    ? "ACCEPTANCE EVIDENCE: these numbers are from the release build on a hardware renderer."
    : `NOT ACCEPTANCE EVIDENCE — do not quote these against the 200 ms bar. ${out.acceptanceEvidenceWhy}`,
);
console.log(out.measurementClass);
/* A journey we could not measure is not a pass, and a journey that violated E3 is not a pass
   either — the exit code carries BOTH axes now. It used to carry only the INP verdicts, which is
   what let a run print twelve on-path long tasks over 50 ms and exit 0. */
process.exit(
  out.summary.fail + out.summary.notMeasured + out.summary.transportFailures + out.summary.e3Fail > 0 ? 1 : 0,
);
