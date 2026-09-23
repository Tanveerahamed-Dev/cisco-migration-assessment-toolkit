/**
 * measure-fps.mjs — the acceptance E4 instrument: a frame-rate figure that cannot be taken off an
 * idle loop, with the render target it was taken at recorded beside it.
 *
 * WHY THIS FILE EXISTS. E4 asks for ">= 55 fps ... with a trace animating", and until now the only
 * E4 instruments were ad-hoc `_audit_*` probes with no verdict and no exit code. Two things about
 * that were wrong, and both are fixed here rather than argued:
 *
 *   1. AN IDLE LOOP LOOKS LIKE 60 fps. Everything the fabric draws is dirty-flag gated: when
 *      nothing is animating, `requestAnimationFrame` still ticks at the display rate while the
 *      renderer does nothing. A frame-time series collected then measures the browser's clock, not
 *      the renderer. `stats().converged` is false exactly while the scene is drawing
 *      (src/fabric3d/emphasis.ts :: isConverged), so every sample here is gated on it: a window in
 *      which the scene stayed converged is NOT MEASURED, never a pass.
 *
 *   2. "A TRACE ANIMATING" IS NOT A STATE THIS SNAPSHOT CAN ALWAYS REACH. The packet only runs when
 *      the stitched path has length, which needs at least two hops joined by a cable
 *      (src/fabric3d/flow.ts). On a snapshot where traces return a single hop there is no packet to
 *      measure, and quoting a 60 fps figure from such a page would be quoting the idle loop. So the
 *      harness ESTABLISHES its render condition and NAMES it: it prefers the trace packet when the
 *      scene is genuinely non-converged after a trace, and otherwise drives sustained camera
 *      motion — the product's own focus-to-device affordance — and says which one produced the
 *      number. A run that could not reach either condition reports NOT MEASURED and exits non-zero.
 *
 *   3. 1920x1080 IS THE VIEWPORT, NOT THE RENDER TARGET. At that viewport the fabric is one region
 *      of a four-surface layout; the canvas is about 1160x962 there. Every figure below therefore
 *      carries the canvas dimensions, the device pixel ratio and the drawing-buffer size it was
 *      measured at, so no one can read a half-area figure as a full-screen one. `ATLAS_FULLBLEED=1`
 *      hides the rails through the app's own single-column ladder so the fabric gets the width.
 *
 *   3b. THE CONDITION USERS PRODUCE IS AN ORBIT, NOT A FLIGHT (review finding, E4, 2026-09-22).
 *      focusDevice flights passed at a 55.6-56.7 fps median while an 8 s continuous orbit drag —
 *      the commonest thing a reader does to a 3-D fabric — rendered at 53.9-54.5 fps on the same
 *      build and machine. So the harness now ALSO drives a continuous pointer-drag orbit through the
 *      canvas, split into its own replicate windows, and E4 passes only when BOTH conditions hold the
 *      bar. It also records whether the scene SAID so when a condition fell below the bar
 *      (`stats().frameRateBelowBar` or a lowered tier): E4 requires degradation to be explicit.
 *
 *   4. ONE RUN IS NOT A MEASUREMENT. The gate is replicated across the run's own sample windows and
 *      records how busy the host was while it measured; see REPLICATION beside the verdict. A run
 *      that holds the bar on a contended machine is a PASS but is NOT acceptance evidence, and the
 *      report says so in a field rather than leaving the reader to infer it.
 *
 * Usage:
 *     npm run build && npm run preview
 *     node review/measure-fps.mjs                 # evidence lane: release build, headed, real GPU
 *     ATLAS_FULLBLEED=1 node review/measure-fps.mjs
 *
 * Exit code: 0 only when a render condition was established, at least five sample windows were
 * genuinely rendering, the MEDIAN window held the bar and no window fell through the stated floor.
 * NOT MEASURED exits non-zero: an absent measurement is not a passing one.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { cpus } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { checkBuildFreshness } from "./build-freshness.mjs";
import {
  FULL_RATE_MAX_RAF_MS,
  createLoadMeter,
  describePower,
  ensurePresenting,
  gatedBusy,
  headedWindow,
  hostPower,
  idleBaseline,
  presentationState,
  rafCadence,
  windowBoundsCheck,
  windowFitsOf,
} from "./host-env.mjs";

/**
 * Host busyness across the run, from the OS scheduler's own cumulative per-core times.
 *
 * A point sample before the run says nothing about the nine seconds the figure was taken in, and a
 * shell-out to Get-Counter is Windows-only and can be absent or localised. `os.cpus()` carries
 * cumulative idle/busy tick counters on every platform Node supports, so the DELTA across the run
 * is the fraction of all core-time that was not idle while this script was measuring.
 *
 * Returns null when the counters are unavailable or did not advance — which is refused as evidence
 * rather than treated as a quiet machine.
 */
const cpuTicks = () => {
  try {
    let idle = 0;
    let total = 0;
    for (const c of cpus()) {
      for (const [k, v] of Object.entries(c.times)) {
        total += v;
        if (k === "idle") idle += v;
      }
    }
    return total > 0 ? { idle, total } : null;
  } catch {
    return null;
  }
};
const hostBusyFraction = (start) => {
  const end = cpuTicks();
  if (start === null || end === null) return null;
  const dTotal = end.total - start.total;
  const dIdle = end.idle - start.idle;
  if (dTotal <= 0) return null;
  return Number((1 - dIdle / dTotal).toFixed(3));
};
const hostCpuAtStart = cpuTicks();

/* HOST POWER, PRESENTATION AND NET CONTENTION (perf audit, 2026-09-22) — see ./host-env.mjs.
   Measured on the reference machine: on battery with Energy Saver ON the browser presented at 30 Hz
   or stopped presenting altogether. Three runs of one unchanged build gave FAIL, NOT MEASURED (a
   "1016.8 ms STALL" that was the window not presenting) and PASS, none of them recording power, and
   this report was stamped "unthrottled". Power is now read at the start and end; the window must be
   presenting at full rate before and after the measured conditions; and the busy figure the gate
   reads excludes this harness's own browser. */
const hostPowerAtStart = hostPower();
const hostIdleBaseline = await idleBaseline(3000);
const hostLoadMeter = createLoadMeter();
hostLoadMeter.start();

const HERE = dirname(fileURLToPath(import.meta.url));
const APP = process.env.ATLAS_URL || "http://localhost:4181";
const FLOW = process.env.ATLAS_FLOW || "10.0.10.50>10.0.20.10>tcp>443";
const PAGE_URL = `${APP}/?s=fabric&flow=${FLOW}`;
const HEADED = process.env.ATLAS_HEADLESS !== "1";
const FULLBLEED = process.env.ATLAS_FULLBLEED === "1";
/** The bar E4 states. Kept as a named constant so the report can print the bar next to the figure. */
const FPS_BAR = 55;
/** Frames below this are counted individually: a p50 can hold the bar while the reader sees hitches. */
const SLOW_FRAME_MS = 1000 / FPS_BAR;

const pct = (xs, p) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return Number(s[Math.min(s.length - 1, Math.max(0, Math.ceil((p / 100) * s.length) - 1))].toFixed(2));
};

const summarise = (xs, label, lo, hi) => ({
  label,
  windowMs: [Math.round(lo), Math.round(hi)],
  frames: xs.length,
  meanFps: xs.length ? Number((1000 / (xs.reduce((a, b) => a + b, 0) / xs.length)).toFixed(2)) : null,
  frameMs: {
    p50: pct(xs, 50),
    p95: pct(xs, 95),
    p99: pct(xs, 99),
    max: xs.length ? Number(Math.max(...xs).toFixed(2)) : null,
  },
  worstFps: xs.length ? Number((1000 / Math.max(...xs)).toFixed(2)) : null,
  framesUnderBar: xs.filter((d) => d > SLOW_FRAME_MS).length,
});

const INSTRUMENT = `
  window.__atlasExposeScene = true;
  window.__f = [];
  window.__c = [];
  (function () {
    let last = 0;
    const tick = (now) => {
      if (last !== 0) window.__f.push([Number(now.toFixed(2)), Number((now - last).toFixed(2))]);
      last = now;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    /* The convergence trace is what turns a frame series into evidence: it says which intervals the
       renderer was actually working in. 40 ms is fast enough that a 200 ms span is sampled five
       times and cheap enough that it does not perturb what it measures. */
    setInterval(() => {
      const s = window.__atlasScene && window.__atlasScene.stats ? window.__atlasScene.stats() : null;
      window.__c.push([Number(performance.now().toFixed(1)), s ? s.converged : null]);
    }, 40);
  })();
`;

/* The headed window is planned inside the screen's work area (acceptance report item 15; host-env.mjs
   owns the plan). A fixed 1940x1180 window was larger than the reference host's 1280x752 DIP work
   area, and an off-screen window region is not a measurement environment. */
const headedPlan = HEADED ? await headedWindow(chromium, { width: 1920, height: 1080 }) : null;
if (headedPlan) console.log(headedPlan.line);
const browser = await chromium.launch(HEADED ? { headless: false, args: headedPlan.args } : {});
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  reducedMotion: "no-preference",
});
await ctx.addInitScript(INSTRUMENT);
const page = await ctx.newPage();
const windowCheck = HEADED ? await windowBoundsCheck(ctx, page, headedPlan.plan) : { checked: false, skipped: "headless" };
const windowFits = !HEADED || windowFitsOf(headedPlan.plan, windowCheck);
await page.goto(PAGE_URL, { waitUntil: "load", timeout: 30000 });
await page.waitForSelector("canvas", { timeout: 25000 });
/* Let the cold load finish. The warm-up (scene.ts) deliberately spends several frames linking
   programs before the first painted frame, and those frames are not the subject of E4. */
await page.waitForTimeout(9000);

if (FULLBLEED) {
  /* The app's own route to a wide fabric: the single-column ladder hides the rails below 1024, and
     the fabric keeps the stage. Done by resizing the viewport rather than by injecting CSS, so what
     is measured is a layout the product actually produces. */
  await page.setViewportSize({ width: 1020, height: 1080 });
  await page.waitForTimeout(1200);
}

/* Before anything is measured: is the window presenting, and at what rate? */
const presentationBefore = HEADED ? await ensurePresenting(ctx, page) : { presenting: true, fullRate: true, rafMedianMs: null, skipped: "headless" };

const environment = await page.evaluate(() => {
  const s = window.__atlasScene;
  const c = document.querySelector("canvas");
  const gl = c ? c.getContext("webgl2") || c.getContext("webgl") : null;
  const dbg = gl ? gl.getExtension("WEBGL_debug_renderer_info") : null;
  return {
    sceneHandle: Boolean(s),
    stats: s && s.stats ? s.stats() : null,
    canvas: c ? { cssW: c.clientWidth, cssH: c.clientHeight, bufferW: c.width, bufferH: c.height } : null,
    dpr: window.devicePixelRatio,
    viewport: { w: window.innerWidth, h: window.innerHeight },
    renderer: gl && dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    hopsInDom: document.querySelectorAll(".hoplist li, #rail-path .hop").length,
    url: location.href,
  };
});

/* ── establish a render condition, and name it ────────────────────────────────────────────────
 *
 * Condition A — the trace packet. Re-arm the trace and watch for a sustained non-converged run.
 * Condition B — sustained camera motion through the product's focus-to-device affordance.
 * A is preferred because it is the condition E4 names; B is used, and labelled, when A does not
 * sustain on this snapshot. */
const packetProbeStart = await page.evaluate(() => performance.now());
await page.evaluate(() => {
  const el = document.querySelector("canvas");
  if (el) el.focus();
});
await page.waitForTimeout(2500);
const packetProbeEnd = await page.evaluate(() => performance.now());

const devices = await page.evaluate(() =>
  [...document.querySelectorAll(".fabric3d-label[data-device]")].map((e) => e.dataset.device).slice(0, 12),
);
const cameraStart = await page.evaluate(() => performance.now());
/* Each focus step is recorded as its OWN window. One run therefore yields ten replicate samples of
   the same condition instead of one pooled figure — see REPLICATION above the verdict. */
const cameraSteps = [];
for (let i = 0; i < 10; i++) {
  const lo = await page.evaluate(() => performance.now());
  await page.evaluate((id) => window.__atlasScene?.focusDevice?.(id), devices[i % Math.max(1, devices.length)] ?? null);
  await page.waitForTimeout(900);
  const hi = await page.evaluate(() => performance.now());
  cameraSteps.push({ index: i + 1, start: lo, end: hi });
}
const cameraEnd = await page.evaluate(() => performance.now());
await page.waitForTimeout(800);

/* Condition C — a continuous orbit drag through the canvas, the render condition a user produces
   by hand. Each ~1 s of drag is its own replicate window, exactly like the focus steps above. The
   scene's own telemetry is read at the end of the drag, while the window it judged is the drag. */
const ORBIT_WINDOWS = 8;
const ORBIT_WINDOW_MS = 1000;
const orbitSteps = [];
let orbitStats = null;
const canvasBox = await page.locator("canvas").first().boundingBox();
if (canvasBox) {
  const cx = canvasBox.x + canvasBox.width / 2;
  const cy = canvasBox.y + canvasBox.height / 2;
  const rx = Math.min(250, canvasBox.width * 0.3);
  const ry = Math.min(120, canvasBox.height * 0.2);
  await page.mouse.move(cx + rx, cy);
  await page.mouse.down();
  let k = 0;
  for (let i = 0; i < ORBIT_WINDOWS; i++) {
    const lo = await page.evaluate(() => performance.now());
    const until = Date.now() + ORBIT_WINDOW_MS;
    while (Date.now() < until) {
      const a = k * 0.05;
      await page.mouse.move(cx + rx * Math.cos(a), cy + ry * Math.sin(a));
      await page.waitForTimeout(16);
      k++;
    }
    const hi = await page.evaluate(() => performance.now());
    orbitSteps.push({ index: i + 1, start: lo, end: hi });
  }
  orbitStats = await page.evaluate(() => window.__atlasScene?.stats?.() ?? null);
  await page.mouse.up();
  await page.waitForTimeout(800);
}

/* ...and after: a window that stopped presenting mid-run turns every stall into an environment fault. */
const presentationAfter = HEADED ? presentationState(await rafCadence(page, 5000).catch(() => null)) : presentationBefore;
const frames = await page.evaluate(() => window.__f);
const converged = await page.evaluate(() => window.__c);
const after = await page.evaluate(() => window.__atlasScene?.stats?.() ?? null);
/* The artefact this figure describes, read from what the page actually loaded. A report that does
   not name its bundle outlives the build it measured, and the only way to notice is to compare
   chunk filenames by eye — which is how a committed report came to cite a chunk `dist/` no longer
   ships. */
const bundle = await page.evaluate(() =>
  performance
    .getEntriesByType("resource")
    .filter((r) => /\.(js|css)(\?|$)/.test(r.name))
    .map((r) => ({ url: r.name.split("/").pop(), bytes: r.encodedBodySize }))
    .sort((a, b) => a.url.localeCompare(b.url)),
);
hostLoadMeter.sample();
await browser.close();

/* Contiguous intervals in which the scene reported itself NOT converged: the intervals it drew in. */
const spans = [];
let cur = null;
for (const [t, c] of converged) {
  if (c === false) {
    if (cur === null) cur = { start: t, end: t };
    cur.end = t;
  } else if (cur !== null) {
    spans.push(cur);
    cur = null;
  }
}
if (cur !== null) spans.push(cur);

const framesIn = (lo, hi) => frames.filter(([t]) => t >= lo && t <= hi).map(([, d]) => d);
/** Fraction of a window the scene reported itself non-converged. 1 = it was drawing throughout. */
const renderingFraction = (lo, hi) => {
  const inWindow = converged.filter(([t]) => t >= lo && t <= hi);
  if (inWindow.length === 0) return 0;
  return Number((inWindow.filter(([, c]) => c === false).length / inWindow.length).toFixed(3));
};

const packetSpans = spans.filter((s) => s.start >= packetProbeStart && s.end <= packetProbeEnd && s.end - s.start >= 400);
const conditionUsed = packetSpans.length > 0 ? "trace-packet" : "sustained-camera-motion";
const window_ =
  conditionUsed === "trace-packet"
    ? { lo: packetSpans[0].start, hi: packetSpans[packetSpans.length - 1].end }
    : { lo: cameraStart, hi: cameraEnd };

const sample = summarise(
  framesIn(window_.lo, window_.hi),
  conditionUsed === "trace-packet"
    ? "trace packet animating on the fabric"
    : "sustained camera motion (10 x focusDevice, 900 ms apart)",
  window_.lo,
  window_.hi,
);
const rendering = renderingFraction(window_.lo, window_.hi);

/* ── REPLICATION ───────────────────────────────────────────────────────────────────────────────
 *
 * This gate used to be decided by ONE pooled window, and an external audit measured the same
 * unchanged `dist/` build at 40.46–60 fps across 15 invocations of this script: 49.03 FAIL, 60
 * PASS, 56.73 PASS, NOT MEASURED, 40.46 FAIL, 44.1 FAIL, then five consecutive PASSes taken while
 * the host was under 25% CPU. Every FAIL coincided with other processes on the box. One run's PASS
 * therefore carried no information about the build — it carried information about the machine, and
 * the report envelope recorded the renderer and the canvas size but nothing about host load, so a
 * green result could not be told apart from a lucky one.
 *
 * Two changes make the figure an answer rather than a sample:
 *   1. every focus step is its own window, so one invocation produces N replicates of the same
 *      condition; the gate is the MEDIAN across windows, with a stated per-window FLOOR so a
 *      healthy median cannot hide one catastrophic window;
 *   2. host busyness is measured across the run from the OS scheduler's own counters and recorded
 *      in the envelope, and `acceptanceEvidence` is refused when the machine was not quiet —
 *      a number taken on a contended host is a measurement of the contention. */
const MIN_RENDERING_FRACTION = 0.6;
/** A window needs enough frames to summarise at all. Below this it is not a sample. */
const MIN_WINDOW_FRAMES = 20;
/** How many usable windows a verdict requires. Fewer than this is NOT MEASURED, never a PASS. */
const MIN_REPLICATES = 5;
/** No single window may fall below this, however good the median. Stated, not implied. */
const WINDOW_FLOOR_FPS = 45;
/** Above this much host CPU across the run, the figure is not acceptance evidence. */
const MAX_HOST_BUSY_FRACTION = 0.25;

const replicates = cameraSteps
  .map((s) => ({
    ...summarise(framesIn(s.start, s.end), `camera step ${s.index}`, s.start, s.end),
    renderingFraction: renderingFraction(s.start, s.end),
  }))
  .map((w) => ({ ...w, usable: w.frames >= MIN_WINDOW_FRAMES && w.renderingFraction >= MIN_RENDERING_FRACTION }));
const usable = replicates.filter((w) => w.usable);
const medianFps = pct(usable.map((w) => w.meanFps ?? 0), 50);
const worstWindowFps = usable.length ? Math.min(...usable.map((w) => w.meanFps ?? 0)) : null;

/* The orbit condition, replicated and gated the same way. */
const orbitReplicates = orbitSteps
  .map((s) => ({
    ...summarise(framesIn(s.start, s.end), `orbit window ${s.index}`, s.start, s.end),
    renderingFraction: renderingFraction(s.start, s.end),
  }))
  .map((w) => ({ ...w, usable: w.frames >= MIN_WINDOW_FRAMES && w.renderingFraction >= MIN_RENDERING_FRACTION }));
const orbitUsable = orbitReplicates.filter((w) => w.usable);
const orbitMedianFps = pct(orbitUsable.map((w) => w.meanFps ?? 0), 50);
const orbitWorstWindowFps = orbitUsable.length ? Math.min(...orbitUsable.map((w) => w.meanFps ?? 0)) : null;
const orbitVerdict =
  orbitUsable.length < MIN_REPLICATES
    ? "NOT MEASURED"
    : (orbitMedianFps ?? 0) >= FPS_BAR && (orbitWorstWindowFps ?? 0) >= WINDOW_FLOOR_FPS
      ? "PASS"
      : "FAIL";
/* E4's second clause: when the orbit fell below the bar, did the product SAY so? */
const orbitDegradationReported =
  orbitStats === null ? null : orbitStats.frameRateBelowBar === true || orbitStats.quality !== "high";

const hostLoad = hostLoadMeter.finish();
const hostBusyGross = hostBusyFraction(hostCpuAtStart);
/* The figure the gate reads: busy core-time NOT spent by this harness (gross where unreadable). */
const hostBusy = gatedBusy(hostLoad) ?? hostBusyGross;
const hostPowerAtEnd = hostPower();
const hostPowerThrottled = Boolean(hostPowerAtStart.throttled || hostPowerAtEnd.throttled);
/* E4 is a 55 fps bar. A window that is not presenting has no frame rate, and one presenting below
   50 Hz cannot reach the bar whatever the renderer does: both make E4 undecidable on this run, and
   the verdict says so instead of printing a FAIL (or a "STALL") that is about the display. */
const presentationFault = !presentationBefore.presenting
  ? `the window was not presenting before measurement (rAF median ${presentationBefore.rafMedianMs ?? "none in 4 s"} ms after restore)`
  : !presentationAfter.presenting
    ? `the window stopped presenting during the run (end-of-run rAF median ${presentationAfter.rafMedianMs ?? "none in 5 s"} ms)`
    : !presentationBefore.fullRate || !presentationAfter.fullRate
      ? `the display presented below 50 Hz (rAF median ${presentationBefore.rafMedianMs} ms before, ${presentationAfter.rafMedianMs} ms after; bar <= ${FULL_RATE_MAX_RAF_MS} ms) — display-limited, so no tier can reach ${FPS_BAR} fps here`
      : null;

/* THE GATE. The NOT MEASURED triggers are DIFFERENT FINDINGS and each one now says which it was:
     - the scene never left convergence -> there was nothing to measure;
     - too few frames landed in the window to summarise -> a stall, not a convergence problem;
     - the window was mostly idle -> an idle rAF loop is not a frame rate;
     - too few usable replicate windows -> one sample is not a measurement.
   The old `why` ternary distinguished only the first of those and fell through to the
   rendering-fraction sentence for the rest, which is how a run reporting ELEVEN frames and a
   4066 ms stall printed "rendering only 100% of the time (minimum 60%)" — a self-contradiction
   that sent the reader after a convergence problem that did not exist. */
const focusVerdict =
  spans.length === 0
    ? "NOT MEASURED"
    : sample.frames < 30
      ? "NOT MEASURED"
      : rendering < MIN_RENDERING_FRACTION
        ? "NOT MEASURED"
        : usable.length < MIN_REPLICATES
          ? "NOT MEASURED"
          : (medianFps ?? 0) >= FPS_BAR && (worstWindowFps ?? 0) >= WINDOW_FLOOR_FPS
            ? "PASS"
            : "FAIL";
const focusWhy =
  focusVerdict === "NOT MEASURED"
    ? spans.length === 0
      ? "the scene never reported itself non-converged: nothing was rendering, so there is no frame rate to report"
      : sample.frames < 30
        ? `only ${sample.frames} frames landed in the sample window — too few to summarise (minimum 30). The window was ${Math.round(window_.hi - window_.lo)} ms long and its worst frame took ${sample.frameMs.max} ms, so this is a STALL, not a convergence problem`
        : rendering < MIN_RENDERING_FRACTION
          ? `the sample window was rendering only ${Math.round(rendering * 100)}% of the time (minimum ${Math.round(MIN_RENDERING_FRACTION * 100)}%); an idle rAF loop is not a frame rate`
          : `only ${usable.length} of ${replicates.length} sample windows were usable (minimum ${MIN_REPLICATES}); one window is not a measurement`
    : focusVerdict === "PASS"
      ? `median ${medianFps} fps across ${usable.length} windows, worst window ${worstWindowFps} fps (floor ${WINDOW_FLOOR_FPS}), host busy ${Math.round((hostBusy ?? 0) * 100)}% of the run`
      : (medianFps ?? 0) < FPS_BAR
        ? `median ${medianFps} fps across ${usable.length} windows is below the ${FPS_BAR} fps bar${hostBusy !== null && hostBusy > MAX_HOST_BUSY_FRACTION ? ` — and the host was ${Math.round(hostBusy * 100)}% busy during the run, so this figure is about the machine as much as the build` : ""}`
        : `the median held (${medianFps} fps) but window ${usable.findIndex((w) => w.meanFps === worstWindowFps) + 1} fell to ${worstWindowFps} fps, below the stated ${WINDOW_FLOOR_FPS} fps floor`;

/* BOTH conditions decide E4. Either one unmeasured is NOT MEASURED; either one below the bar is a FAIL. */
const orbitWhy =
  orbitVerdict === "NOT MEASURED"
    ? `only ${orbitUsable.length} of ${orbitReplicates.length} orbit windows were usable (minimum ${MIN_REPLICATES})`
    : orbitVerdict === "PASS"
      ? `orbit median ${orbitMedianFps} fps, worst window ${orbitWorstWindowFps} fps`
      : `orbit median ${orbitMedianFps} fps (worst window ${orbitWorstWindowFps} fps) is below the ${FPS_BAR} fps bar or the ${WINDOW_FLOOR_FPS} fps floor; ` +
        `the scene ${orbitDegradationReported === true ? "DID report it (below-bar flag or lowered tier)" : orbitDegradationReported === false ? "did NOT report it — degradation reported as health" : "could not be read"}`;
const verdict =
  presentationFault !== null || focusVerdict === "NOT MEASURED" || orbitVerdict === "NOT MEASURED"
    ? "NOT MEASURED"
    : focusVerdict === "PASS" && orbitVerdict === "PASS"
      ? "PASS"
      : "FAIL";
const why =
  (presentationFault !== null ? `PRESENTATION — ${presentationFault}; harness environment, not the app. ` : "") +
  `focus flights: ${focusVerdict} — ${focusWhy}. Orbit drag: ${orbitVerdict} — ${orbitWhy}` +
  (hostPowerThrottled ? `. HOST POWER — on battery or Energy Saver (${describePower(hostPowerAtStart)} at start, ${describePower(hostPowerAtEnd)} at end)` : "");

/* Acceptance evidence is a STRONGER claim than a passing run: it says the number describes the
   build. It is refused on a contended host, and refused when host load could not be measured at
   all — an unmeasured machine is not a quiet one. */
/* ...and refused on a stale or foreign build, which is a measurement of a different program
   (review finding, E2 — see build-freshness.mjs). */
const freshness = await checkBuildFreshness(APP);
const acceptanceEvidence =
  verdict === "PASS" && hostBusy !== null && hostBusy <= MAX_HOST_BUSY_FRACTION && !hostPowerThrottled && presentationFault === null && freshness.fresh && windowFits;

const report = {
  criterion: "E4 — the fabric holds >= 55 fps on the reference machine, degradation explicit.",
  measurementClass: "LABORATORY — scripted actor, single machine, no CPU/GPU emulation; host power and presentation cadence recorded in hostPower / presentation. Not a field figure.",
  verdict,
  why,
  /** TRUE only when this figure may be quoted as acceptance evidence. See the REPLICATION note. */
  acceptanceEvidence,
  replication: {
    windows: replicates.length,
    usableWindows: usable.length,
    minUsableWindows: MIN_REPLICATES,
    medianFps,
    worstWindowFps,
    windowFloorFps: WINDOW_FLOOR_FPS,
    perWindow: replicates,
  },
  orbit: {
    condition: `continuous pointer-drag orbit through the canvas, ${ORBIT_WINDOWS} x ${ORBIT_WINDOW_MS} ms windows`,
    verdict: orbitVerdict,
    usableWindows: orbitUsable.length,
    medianFps: orbitMedianFps,
    worstWindowFps: orbitWorstWindowFps,
    degradationReported: orbitDegradationReported,
    sceneAtEndOfDrag: orbitStats
      ? { tier: orbitStats.quality, frameRateBelowBar: orbitStats.frameRateBelowBar ?? null, reasons: orbitStats.qualityReasons }
      : null,
    perWindow: orbitReplicates,
  },
  buildFreshness: freshness,
  /* A headed window that is not inside the screen is not a measurement environment (host-env.mjs). */
  window: { screen: headedPlan?.screen ?? null, plan: headedPlan?.plan ?? null, check: windowCheck, fits: windowFits },
  hostPower: { atStart: hostPowerAtStart, atEnd: hostPowerAtEnd, throttled: hostPowerThrottled },
  presentation: { before: presentationBefore, after: presentationAfter, fault: presentationFault, fullRateMaxRafMs: FULL_RATE_MAX_RAF_MS },
  hostQuiescence: {
    /* The other half of "a green result cannot be told from a lucky one": without this the report
       recorded the renderer and the canvas size but nothing about what else the machine was doing. */
    measured: hostBusy !== null,
    busyFractionOfRun: hostBusy,
    basis: hostLoad.excess !== null ? "excess over the harness's own process tree" : "gross (harness tree unreadable on this platform)",
    grossBusyFraction: hostLoad.gross ?? hostBusyGross,
    harnessFraction: hostLoad.harness,
    idleBaselineBeforeLaunch: hostIdleBaseline,
    maxForAcceptance: MAX_HOST_BUSY_FRACTION,
    cores: cpus().length,
    note:
      hostBusy === null
        ? "host load could not be measured; the run is not acceptance evidence"
        : hostBusy > MAX_HOST_BUSY_FRACTION
          ? "the host was busy during the run; the figure describes the machine as much as the build"
          : "the host was quiet during the run",
  },
  renderCondition: {
    used: conditionUsed,
    /* Named because E4's own wording says "with a trace animating", and on a snapshot whose traces
       return a single hop there is no packet: flow.ts starts one only when the stitched path has
       non-zero length, which needs at least two hops joined by a cable. */
    tracePacketObserved: packetSpans.length > 0,
    hopsInDom: environment.hopsInDom,
    renderingFractionOfSample: rendering,
  },
  bar: { fps: FPS_BAR, frameMs: Number(SLOW_FRAME_MS.toFixed(2)) },
  sample,
  otherRenderingSpans: spans
    .filter((s) => s.end - s.start >= 200)
    .map((s, i) => ({
      ...summarise(framesIn(s.start, s.end), `rendering span #${i + 1}`, s.start, s.end),
      renderingFraction: renderingFraction(s.start, s.end),
    })),
  /* The render TARGET, recorded with the figure. E4 says 1920x1080; at that viewport the fabric is
     one region of a four-surface layout and the canvas is roughly 1160x962 — 1.12 MPix against
     2.07 — so the two numbers must travel together or the figure will be read as the wrong one. */
  target: {
    viewport: environment.viewport,
    canvasCss: environment.canvas ? { w: environment.canvas.cssW, h: environment.canvas.cssH } : null,
    drawingBuffer: environment.canvas ? { w: environment.canvas.bufferW, h: environment.canvas.bufferH } : null,
    devicePixelRatio: environment.dpr,
    megapixels: environment.canvas
      ? Number(((environment.canvas.bufferW * environment.canvas.bufferH) / 1e6).toFixed(2))
      : null,
    fullBleed: FULLBLEED,
  },
  quality: {
    tier: after?.quality ?? environment.stats?.quality ?? null,
    reasons: after?.qualityReasons ?? null,
    auto: after?.qualityAuto ?? null,
    drawCalls: after?.drawCalls ?? null,
    drawCallBudget: after?.drawCallBudget ?? null,
    overBudget: after?.overBudget ?? null,
    triangles: after?.triangles ?? null,
  },
  bundle,
  environment: {
    url: PAGE_URL,
    headed: HEADED,
    renderer: environment.renderer,
    reducedMotion: environment.reducedMotion,
    sceneHandle: environment.sceneHandle,
    node: process.version,
    platform: process.platform,
    capturedAt: new Date().toISOString(),
  },
  totalFramesObserved: frames.length,
};

mkdirSync(resolve(HERE, "reports"), { recursive: true });
writeFileSync(resolve(HERE, "reports", "fps.json"), JSON.stringify(report, null, 1));

console.log(`${verdict}  E4  ${why}`);
console.log(
  `  condition=${conditionUsed} tracePacket=${report.renderCondition.tracePacketObserved} ` +
    `rendering=${Math.round(rendering * 100)}% frames=${sample.frames}`,
);
console.log(
  `  replicates: ${usable.length}/${replicates.length} usable, median ${medianFps}fps, worst window ${worstWindowFps}fps ` +
    `(floor ${WINDOW_FLOOR_FPS}); per-window fps [${replicates.map((w) => (w.usable ? w.meanFps : "-")).join(", ")}]`,
);
console.log(
  `  orbit: ${orbitVerdict} ${orbitUsable.length}/${orbitReplicates.length} usable, median ${orbitMedianFps}fps, worst window ${orbitWorstWindowFps}fps; ` +
    `per-window fps [${orbitReplicates.map((w) => (w.usable ? w.meanFps : "-")).join(", ")}]; scene said: tier ${orbitStats?.quality ?? "?"}, belowBar ${orbitStats?.frameRateBelowBar ?? "?"}`,
);
console.log(
  `  host: ${hostBusy === null ? "load NOT MEASURED" : Math.round(hostBusy * 100) + "% busy across the run excluding this harness"} ` +
    `(gross ${hostLoad.gross === null ? "?" : Math.round(hostLoad.gross * 100) + "%"}, harness ${hostLoad.harness === null ? "?" : Math.round(hostLoad.harness * 100) + "%"}, idle baseline ${hostIdleBaseline === null ? "?" : Math.round(hostIdleBaseline * 100) + "%"}); ` +
    `power ${describePower(hostPowerAtStart)}${hostPowerThrottled ? " THROTTLED" : ""}; presentation ${presentationBefore.rafMedianMs ?? "-"}/${presentationAfter.rafMedianMs ?? "-"} ms rAF; ` +
    `over ${cpus().length} cores; build ${freshness.fresh ? "fresh" : "NOT FRESH (" + freshness.why + ")"}; ` +
    `window ${windowFits ? "inside the screen" : `NOT inside the screen (${JSON.stringify(windowCheck.bounds ?? windowCheck.error ?? null)})`} -> acceptanceEvidence=${acceptanceEvidence}`,
);
console.log(
  `  mean=${sample.meanFps}fps p50=${sample.frameMs.p50}ms p95=${sample.frameMs.p95}ms p99=${sample.frameMs.p99}ms ` +
    `max=${sample.frameMs.max}ms worst=${sample.worstFps}fps under-bar-frames=${sample.framesUnderBar}`,
);
console.log(
  `  target: viewport ${report.target.viewport.w}x${report.target.viewport.h}, canvas ` +
    `${report.target.canvasCss?.w}x${report.target.canvasCss?.h} css / ${report.target.drawingBuffer?.w}x${report.target.drawingBuffer?.h} buffer ` +
    `(${report.target.megapixels} MPix, dpr ${report.target.devicePixelRatio})`,
);
console.log(
  `  quality: tier ${report.quality.tier}, drawCalls ${report.quality.drawCalls}/${report.quality.drawCallBudget}, overBudget ${report.quality.overBudget}`,
);
console.log(report.measurementClass);
process.exit(verdict === "PASS" ? 0 : 1);
