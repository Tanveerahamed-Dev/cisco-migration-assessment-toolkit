/**
 * audit-e5-coldload.mjs — E5 / E3 on the COLD LOAD, the one part of the product the INP harness
 * never touches.
 *
 * `measure-inp.mjs` waits for `networkidle` and then a further 2500 ms before it records anything,
 * so every number it reports is steady state. E5 is about the other thing: "work that is genuinely
 * slow is budgeted separately and communicated, not hidden behind a frozen UI". This probe measures
 * the cold load on a fresh context (empty HTTP cache, empty session), using:
 *
 *   - the Long Animation Frames API (`long-animation-frame`), which reports `blockingDuration` and
 *     attributes the frame to the scripts that ran in it — a bare `longtask` entry says only that
 *     the main thread was gone, not where;
 *   - Event Timing for keystrokes fired DURING the load, which is the only honest answer to "is the
 *     UI frozen or merely busy";
 *   - a DOM snapshot at the moment of the worst frame, to check what the user was being told.
 *
 * IT HAS A VERDICT AND AN EXIT CODE. See THE GATE at the foot of this file — it did not, and E5 was
 * the only performance criterion whose named evidence command could not go red.
 */
import { writeFileSync } from "node:fs";
import { cpus } from "node:os";
import { chromium } from "@playwright/test";
import { checkBuildFreshness } from "./build-freshness.mjs";
import { VISIBLE_AFFORDANCE_JS, affordancePaintedAt } from "./working-affordance.mjs";
import { FULL_RATE_MAX_RAF_MS, NO_OCCLUSION_ARGS, createLoadMeter, describePower, gatedBusy, hostPower, idleBaseline, presentationState, rafCadence } from "./host-env.mjs";

const APP = process.env.ATLAS_URL || "http://localhost:4181";
const PAGE_URL = `${APP}/?s=findings`;
const RUNS = Number(process.env.ATLAS_RUNS || 3);

/* Host busyness across the run — the same OS-counter method and the same 25% bar as measure-inp,
   measure-fps and audit-e5-sweep (review finding, 2026-09-21: this was the one E5/E3 instrument that
   recorded none, so its verdict could not be told apart from machine contention). A contended run
   still prints its verdict; it is simply not acceptance evidence. */
const MAX_HOST_BUSY_FRACTION = 0.25;
const cpuTicks = () => {
  try {
    let idle = 0;
    let total = 0;
    for (const c of cpus()) for (const [k, v] of Object.entries(c.times)) { total += v; if (k === "idle") idle += v; }
    return total > 0 ? { idle, total } : null;
  } catch {
    return null;
  }
};
const hostCpuAtStart = cpuTicks();
/* Power, presentation and contention net of the harness — see ./host-env.mjs (perf audit
   2026-09-22: battery + Energy Saver capped the browser at 30 Hz or stopped it presenting, and no
   instrument but measure-inp recorded it). */
const hostPowerAtStart = hostPower();
const hostIdleBaseline = await idleBaseline(3000);
const hostLoadMeter = createLoadMeter();
hostLoadMeter.start();
const freshness = await checkBuildFreshness(APP);

const INIT = `
  window.__loaf = []; window.__lt = []; window.__ev = []; window.__dom = [];
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__loaf.push({
      startTime: +e.startTime.toFixed(1), duration: +e.duration.toFixed(1),
      blockingDuration: +(e.blockingDuration ?? 0).toFixed(1),
      renderStart: +(e.renderStart ?? 0).toFixed(1),
      /* forcedStyleAndLayout is reported beside every script, and a script this HARNESS injected
         (addInitScript code has no sourceURL; its only callbacks are timers and frame callbacks) is
         labelled INSTRUMENT. REVIEW FIX, 2026-09-21: the old 100 ms setInterval sampler called
         checkVisibility/querySelectorAll mid-load, forced a synchronous style+layout, and was then
         printed as the app's top "attributed script" — measured 310 of a 318 ms entry was layout
         forced by the probe itself, attributed to 'TimerHandler:setInterval' with an empty URL. */
      scripts: (e.scripts || []).map((s) => ({
        name: s.name,
        dur: +s.duration.toFixed(1),
        forcedStyleAndLayout: +(s.forcedStyleAndLayoutDuration ?? 0).toFixed(1),
        invoker: s.invoker,
        sourceURL: (s.sourceURL||'').slice(-40),
        instrument: !s.sourceURL && /^(TimerHandler|FrameRequestCallback)/.test(String(s.invoker || '')),
      })).sort((a,b)=>b.dur-a.dur).slice(0,3),
    }); }).observe({ type: 'long-animation-frame', buffered: true });
  } catch (e) { window.__loafError = String(e); }
  new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lt.push({ startTime: +e.startTime.toFixed(1), duration: +e.duration.toFixed(1) }); }).observe({ type: 'longtask', buffered: true });
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.interactionId) window.__ev.push({ name: e.name, startTime: +e.startTime.toFixed(1), duration: +e.duration.toFixed(1), inputDelay: +(e.processingStart-e.startTime).toFixed(1) }); }).observe({ type: 'event', buffered: true, durationThreshold: 0 });
  ${VISIBLE_AFFORDANCE_JS}
  /* SAMPLED AFTER PAINT, not on a free-running interval. A 100 ms setInterval fired at arbitrary
     points in the load, and its checkVisibility()/querySelector reads forced a synchronous style and
     layout of whatever the app had just changed — the probe was measurably perturbing the thing it
     measured (see the INSTRUMENT label on attributed scripts above). rAF -> setTimeout(0) lands the
     sample just after a frame has been rendered, when layout is already clean, so the read costs
     almost nothing and moves no work. Throttled to one sample per ~100 ms, as before. */
  let __lastSample = -Infinity;
  const __sample = () => {
    if (performance.now() - __lastSample < 100) return;
    __lastSample = performance.now();
    const pend = document.querySelector('.stage-pending');
    /* A WORKING affordance that names the loading work, not any busy element anywhere.
       REVIEW FIX, 2026-09-21: this was a document-wide existence test for any [aria-busy=true],
       [role=progressbar], progress or .stage-pending, so an unrelated busy element (a grid showing
       aria-busy during a filter debounce, say) would have excused a frozen fabric. Now it counts
       only the affordances that say what is loading: the boot line in index.html (before React
       mounts) and the stage's own pending / warm-up surfaces inside the fabric region. */
    const busy = window.__visibleAffordance();
    window.__dom.push([ +performance.now().toFixed(0), Boolean(pend), pend ? (pend.textContent||'').slice(0,40) : null, Boolean(document.querySelector('canvas')), Boolean(busy) ]);
  };
  const __tick = () => { setTimeout(__sample, 0); requestAnimationFrame(__tick); };
  requestAnimationFrame(__tick);
`;

/* ── frames the PAGE did not produce ──────────────────────────────────────────────────────────
 *
 * REVIEW FIX, 2026-09-22. With the boot line credited only once it is PAINTED (working-affordance.mjs),
 * a class of frame surfaced that no page change can remove: in a freshly launched headed Chromium the
 * first presentation takes ~500-750 ms, and the Long Animation Frames API reports the wait as one or
 * two 200-380 ms frames with NO page script in them and a blockingDuration of 0 — nothing held the
 * main thread, so input was not frozen. CONTROL (review/_scratch/_perf_fix_control.mjs): a static page
 * with no script at all, the boot line only, served the same way, measured 206-246 ms frames at
 * ~30 ms with blocking 0 and FCP at 476-720 ms. Those frames are the harness's fresh browser process,
 * not the application.
 *
 * So a frame is excluded from the bar only when BOTH hold: no script attributed to the page ran in it
 * (the harness's own INSTRUMENT callbacks do not count as the page), and its blockingDuration is 0.
 * Any frame in which the application ran code — the 675 kB bundle evaluation this gate originally
 * caught, a React slice, a fabric warm-up step — is still judged, and keystrokes are still judged
 * separately. Excluded frames are listed in the report (`browserOnlyFramesOver200ms`), not hidden. */
/* STATED CARVE-OUT (perf audit, 2026-09-22). The exclusion used to be a CATEGORY ("browser-only"),
   so a 218-264 ms frame 148-219 ms after navigation, with nothing on screen, passed the 200 ms bar
   by classification rather than by the bar. It is now a named acceptance carve-out with a third,
   positional condition: the frame must BEGIN BEFORE THE PAGE'S FIRST PAINT (first-contentful-paint).
   Before the first presentation there is no screen for an affordance to be on — index.html's static
   boot line cannot be painted by a frame that precedes every paint — so the bar's "visible working
   affordance" test is not applicable to it, and saying so is the honest form. A script-free,
   non-blocking frame AFTER the first paint is judged like any other. When FCP was never observed the
   carve-out does not apply (absence is not permission). */
const CARVE_OUT = "pre-first-paint: a frame that began before first-contentful-paint, ran no page script and blocked input for 0 ms is not judged against the 200 ms affordance bar (no screen existed for an affordance to be on)";
const isBrowserOnlyFrame = (e, fcp) =>
  (e.blockingDuration ?? 0) === 0 &&
  (e.scripts || []).every((sc) => sc.instrument === true) &&
  typeof fcp === "number" &&
  e.startTime < fcp;

const runs = [];
for (let r = 0; r < RUNS; r++) {
  const browser = await chromium.launch({ headless: false, args: ["--window-size=1940,1180", ...NO_OCCLUSION_ARGS] });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, reducedMotion: "no-preference" });
  await ctx.addInitScript(`window.__atlasExposeScene = true;`);
  await ctx.addInitScript(INIT);
  const page = await ctx.newPage();
  const nav = page.goto(PAGE_URL, { waitUntil: "commit", timeout: 30000 });
  await nav;
  /* Type into the page at intervals across the load. Every keystroke is a real user input, so its
     Event Timing duration is the honest answer to "was the UI responsive at that moment". */
  const presses = [];
  for (const at of [600, 1200, 1800, 2400, 3000, 3600, 4400]) {
    const now = await page.evaluate(() => performance.now());
    if (now < at) await page.waitForTimeout(at - now);
    const t = await page.evaluate(() => performance.now());
    await page.keyboard.press("k").catch(() => {});
    presses.push({ requestedAtMs: at, firedAtMs: +t.toFixed(0) });
  }
  await page.waitForTimeout(6000);
  const data = await page.evaluate(() => ({
    loaf: window.__loaf,
    lt: window.__lt,
    ev: window.__ev,
    dom: window.__dom,
    aff: window.__affTimeline || [],
    affPaint: window.__affPaint || { fcp: null, elements: {} },
    loafError: window.__loafError ?? null,
    /* The artefact this run describes. Without it a report outlives the build it measured. */
    bundle: performance
      .getEntriesByType("resource")
      .filter((r) => /\.(js|css)(\?|$)/.test(r.name))
      .map((r) => ({ url: r.name.split("/").pop(), bytes: r.encodedBodySize }))
      .sort((a, b) => a.url.localeCompare(b.url)),
  }));
  /* Was the window presenting (at full rate) during this cold load? Read after the load, before close. */
  const presentation = presentationState(await rafCadence(page).catch(() => null));
  hostLoadMeter.sample();
  await browser.close();

  const worstLoaf = data.loaf.length ? data.loaf.reduce((a, b) => (b.duration > a.duration ? b : a)) : null;
  /* The same sample the verdict below uses: the last one at or before the frame began (see there).
     This line used to take the first sample AFTER the frame, so the printed diagnostic described
     the screen once the work was over and could contradict the verdict for the same frame. */
  const sampleBefore = (start) => [...data.dom].reverse().find(([t]) => t <= start) ?? data.dom.find(([t]) => t >= start) ?? null;
  const domAt = worstLoaf ? sampleBefore(worstLoaf.startTime) : null;
  /* What was ON SCREEN when a frame began, from the browser's own rendering-step timestamps (see
     working-affordance.mjs) rather than from the last time a sampler got to run: a sampler on the
     blocked thread cannot run during the freeze it is being asked about. */
  /* ...and PAINTED: an affordance counts only once the browser reported a presentation that could
     contain it (Element Timing for the boot line, first-contentful-paint for anything else) — see
     affordancePaintedAt in working-affordance.mjs. Intersection alone credited a boot line that was
     removed before the page was ever presented. */
  const affordanceAt = (t) => affordancePaintedAt(data.aff, data.affPaint, t) !== null;
  runs.push({
    run: r + 1,
    loafError: data.loafError,
    presentation,
    bundle: data.bundle,
    paint: data.affPaint,
    over200ms: data.loaf.filter((e) => e.duration > 200).sort((a, b) => b.duration - a.duration),
    longTasksOver200ms: data.lt.filter((e) => e.duration > 200).sort((a, b) => b.duration - a.duration),
    longTasksOver50ms: data.lt.filter((e) => e.duration > 50).length,
    worstLoaf,
    domDuringWorstFrame: domAt ? { atMs: domAt[0], stagePendingPresent: domAt[1], text: domAt[2], canvasPresent: domAt[3], workingAffordancePresent: affordanceAt(worstLoaf.startTime) } : null,
    /* Every long frame, paired with what the user was being told AT that frame. This is the pair
       the gate below reads: a long frame is acceptable while the product says it is working, and
       is a finding when the screen claims nothing. */
    unannouncedFramesOver200ms: data.loaf
      .filter((e) => e.duration > 200)
      .map((e) => {
        /* The LAST sample at or before the frame began, not the first one after it. The sampler is
           a 100 ms interval on the same thread the frame is blocking, so during a 1.3 s frame it
           does not run at all — "the next sample" is taken after the work finished and says what
           the screen looked like once it was over, which is the wrong question. */
        const at = sampleBefore(e.startTime);
        return {
          atMs: e.startTime,
          durationMs: e.duration,
          blockingMs: e.blockingDuration,
          domSampleAtMs: at ? at[0] : null,
          workingAffordancePresent: affordanceAt(e.startTime),
          browserOnly: isBrowserOnlyFrame(e, data.affPaint.fcp),
        };
      })
      .filter((e) => !e.workingAffordancePresent && !e.browserOnly)
      .sort((a, b) => b.durationMs - a.durationMs),
    /* Reported, never silently dropped: the frames the rule below did not count, and why. */
    browserOnlyFramesOver200ms: data.loaf
      .filter((e) => e.duration > 200 && isBrowserOnlyFrame(e, data.affPaint.fcp) && !affordanceAt(e.startTime))
      .map((e) => ({ atMs: e.startTime, durationMs: e.duration, renderStartMs: e.renderStart })),
    stagePendingWindowMs: (() => {
      const on = data.dom.filter((d) => d[1]).map((d) => d[0]);
      return on.length ? [on[0], on[on.length - 1]] : null;
    })(),
    presses,
    keystrokes: data.ev,
    worstKeystrokeMs: data.ev.length ? Math.max(...data.ev.map((e) => e.duration)) : null,
  });
  console.log(`run ${r + 1}: worst animation frame ${worstLoaf ? worstLoaf.duration : "-"}ms (blocking ${worstLoaf ? worstLoaf.blockingDuration : "-"}ms) at ${worstLoaf ? worstLoaf.startTime : "-"}ms`);
  console.log(`         frames over 200ms: ${runs[r].over200ms.map((e) => e.duration + "ms@" + e.startTime).join(", ") || "none"}`);
  console.log(`         presentation: rAF median ${presentation.rafMedianMs ?? "none"} ms${presentation.fullRate ? "" : " — NOT FULL RATE"}; first paint ${data.affPaint.fcp ?? "never"} ms`);
  console.log(`         carve-out pre-first-paint frames (no page script, blocking 0, began before FCP — not counted): ${runs[r].browserOnlyFramesOver200ms.map((e) => e.durationMs + "ms@" + e.atMs).join(", ") || "none"}`);
  console.log(`         .stage-pending visible ${runs[r].stagePendingWindowMs ? runs[r].stagePendingWindowMs.join("..") + "ms" : "NEVER"}; during worst frame: ${JSON.stringify(runs[r].domDuringWorstFrame)}`);
  console.log(`         keystrokes during load (ms): ${data.ev.map((e) => e.name + " " + e.duration + "@" + e.startTime).join(", ") || "none observed"}`);
  if (worstLoaf?.scripts?.length) {
    console.log(`         attributed scripts: ${JSON.stringify(worstLoaf.scripts)}`);
    const inst = worstLoaf.scripts.filter((x) => x.instrument);
    if (inst.length) console.log(`         NOTE: ${inst.length} of those script(s) are INSTRUMENT (this harness's own sampler), not the app`);
  }
}
/* ── THE GATE ──────────────────────────────────────────────────────────────────────────────────
 *
 * This probe is cited by docs/acceptance.md as E5's evidence and, until now, it printed numbers and
 * always exited 0. A run reporting a 956 ms blocking frame and a 1024 ms keystroke exited 0 exactly
 * like a clean one, so E5 could be recorded green off an instrument that was structurally incapable
 * of going red — the same defect that was found and fixed in measure-inp.mjs's E3 axis, whose
 * header now documents that it "used to be unable to fail".
 *
 * Two bars, both derivable from what this probe already collects, both stated here rather than left
 * to the reader:
 *   1. NO ANIMATION FRAME OVER 200 ms WITHOUT A VISIBLE WORKING AFFORDANCE. Slow work is allowed;
 *      E5's words are "budgeted separately and communicated, not hidden behind a frozen UI". A long
 *      frame while the product says nothing is the failure, not the long frame.
 *   2. NO KEYSTROKE OVER 200 ms DURING THE LOAD. That is the INP bar, applied to the one window the
 *      steady-state harness never measures.
 *
 * NOT MEASURED is a THIRD outcome and it also exits non-zero: if the Long Animation Frames API did
 * not report and no keystroke was observed, nothing was measured, and an unmeasured criterion is
 * not a passing one. */
const FRAME_BAR_MS = 200;
const KEYSTROKE_BAR_MS = 200;

const unannounced = runs.flatMap((r) => r.unannouncedFramesOver200ms.map((f) => ({ run: r.run, ...f })));
const slowKeys = runs.flatMap((r) => r.keystrokes.filter((e) => e.duration > KEYSTROKE_BAR_MS).map((e) => ({ run: r.run, ...e })));
const measured = runs.some((r) => r.loafError === null && (r.worstLoaf !== null || r.keystrokes.length > 0));

const hostEnd = cpuTicks();
const hostBusyGross =
  hostCpuAtStart && hostEnd && hostEnd.total - hostCpuAtStart.total > 0
    ? Number((1 - (hostEnd.idle - hostCpuAtStart.idle) / (hostEnd.total - hostCpuAtStart.total)).toFixed(3))
    : null;
const hostLoad = hostLoadMeter.finish();
/* The figure the gate reads: busy core-time NOT spent by this harness (gross where unreadable). */
const hostBusy = gatedBusy(hostLoad) ?? hostBusyGross;
const hostPowerAtEnd = hostPower();
const hostPowerThrottled = Boolean(hostPowerAtStart.throttled || hostPowerAtEnd.throttled);
const notFullRate = runs.filter((r) => !r.presentation.fullRate).map((r) => r.run);
const hostQuiet = hostBusy !== null && hostBusy <= MAX_HOST_BUSY_FRACTION && !hostPowerThrottled && notFullRate.length === 0;

const verdict = !measured ? "NOT MEASURED" : unannounced.length === 0 && slowKeys.length === 0 ? "PASS" : "FAIL";
const why = !measured
  ? "no animation frame and no keystroke were observed across the runs — the instrument reported nothing, which is not a pass"
  : verdict === "PASS"
    ? `${runs.length} cold loads: every animation frame over ${FRAME_BAR_MS} ms coincided with a visible working affordance, and no keystroke exceeded ${KEYSTROKE_BAR_MS} ms`
    : `${unannounced.length} animation frame(s) over ${FRAME_BAR_MS} ms with NOTHING on screen saying the app was working` +
      `${unannounced.length ? ` (worst ${unannounced[0].durationMs} ms at ${unannounced[0].atMs} ms, run ${unannounced[0].run})` : ""}` +
      `; ${slowKeys.length} keystroke(s) over ${KEYSTROKE_BAR_MS} ms` +
      `${slowKeys.length ? ` (worst ${Math.max(...slowKeys.map((k) => k.duration))} ms)` : ""}`;

writeFileSync(
  "review/reports/e5-coldload.json",
  JSON.stringify(
    {
      criterion: "E5/E3 cold load",
      measurementClass: "LABORATORY — headed Chromium, fresh context per run, localhost preview of the release build.",
      verdict,
      why,
      /* TRUE only when this verdict may be quoted as E5 evidence: a quiet host AND a served build
         that is this checkout's current dist/ (see build-freshness.mjs). */
      acceptanceEvidence: verdict !== "NOT MEASURED" && hostQuiet && freshness.fresh,
      hostQuiescence: {
        busyFractionOfRun: hostBusy,
        basis: hostLoad.excess !== null ? "excess over the harness's own process tree" : "gross",
        grossBusyFraction: hostLoad.gross ?? hostBusyGross,
        harnessFraction: hostLoad.harness,
        idleBaselineBeforeLaunch: hostIdleBaseline,
        maxForAcceptance: MAX_HOST_BUSY_FRACTION,
        cores: cpus().length,
      },
      hostPower: { atStart: hostPowerAtStart, atEnd: hostPowerAtEnd, throttled: hostPowerThrottled },
      presentation: { runsBelowFullRate: notFullRate, fullRateMaxRafMs: FULL_RATE_MAX_RAF_MS },
      carveOuts: [CARVE_OUT],
      buildFreshness: freshness,
      bar: { animationFrameMs: FRAME_BAR_MS, keystrokeMs: KEYSTROKE_BAR_MS, rule: "a frame over the bar is a finding only when no working affordance was on screen" },
      unannouncedFramesOver200ms: unannounced,
      keystrokesOverBar: slowKeys,
      url: PAGE_URL,
      runs,
    },
    null,
    1,
  ),
);

console.log(`carve-out: ${CARVE_OUT}`);
console.log(`power: ${describePower(hostPowerAtStart)}${hostPowerThrottled ? " — THROTTLED" : ""}; presentation below full rate in run(s): ${notFullRate.join(", ") || "none"}`);
console.log(`host: ${hostBusy === null ? "unknown" : Math.round(hostBusy * 100) + "%"} busy excluding this harness (gross ${hostLoad.gross === null ? "?" : Math.round(hostLoad.gross * 100) + "%"}, idle baseline ${hostIdleBaseline === null ? "?" : Math.round(hostIdleBaseline * 100) + "%"}) (bar ${MAX_HOST_BUSY_FRACTION * 100}%); build: ${freshness.fresh ? "fresh" : "NOT FRESH — " + freshness.why}`);
console.log(`${verdict}  E5  ${why}${hostQuiet && freshness.fresh ? "" : "  [NOT ACCEPTANCE EVIDENCE]"}`);
process.exit(verdict === "PASS" ? 0 : 1);
