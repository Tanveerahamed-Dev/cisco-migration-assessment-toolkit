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
import { readFileSync, writeFileSync } from "node:fs";
import { cpus } from "node:os";
import { setTimeout as sleep } from "node:timers/promises";
import { chromium } from "@playwright/test";
import { checkBuildFreshness } from "./build-freshness.mjs";
import { VISIBLE_AFFORDANCE_JS, affordancePaintedAt } from "./working-affordance.mjs";
import { FULL_RATE_MAX_RAF_MS, createLoadMeter, describePower, gatedBusy, headedWindow, hostPower, idleBaseline, presentationState, rafCadence, windowBoundsCheck, windowFitsOf } from "./host-env.mjs";

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
/* NOT SANCTIONED BY DEFAULT (acceptance report E5, 2026-09-22). The carve-out above was written into
   this harness and never into the criterion: docs/acceptance.md does not exempt pre-first-paint frames,
   and a 294.5 ms frame with no working affordance on screen was passing E5 on this file's word alone.
   A harness may not grant its own exemption. So the carve-out now applies ONLY when docs/acceptance.md
   carries the owner's sanction as a line of its own, beginning exactly with
       E5 EXEMPTION (owner-sanctioned): pre-first-paint
   (read at run time, below). Without that line every such frame is JUDGED — counted as an unannounced
   frame and failing the bar — and still listed separately so the owner can see what the decision
   covers. Adding the line is the owner's decision; this harness never writes it. */
const SANCTION_LINE = /^E5 EXEMPTION \(owner-sanctioned\): pre-first-paint\b/m;
const CARVE_OUT_SANCTIONED = (() => {
  try {
    return SANCTION_LINE.test(readFileSync(new URL("../docs/acceptance.md", import.meta.url), "utf8"));
  } catch {
    return false; // an unreadable criterion sanctions nothing
  }
})();
const CARVE_OUT = "pre-first-paint: a frame that began before first-contentful-paint, ran no page script and blocked input for 0 ms is not judged against the 200 ms affordance bar (no screen existed for an affordance to be on)";
const isBrowserOnlyFrame = (e, fcp) =>
  (e.blockingDuration ?? 0) === 0 &&
  (e.scripts || []).every((sc) => sc.instrument === true) &&
  typeof fcp === "number" &&
  e.startTime < fcp;

/** The fixed keystroke instants every run probes (page clock, ms after navigation commit). */
const FIXED_PROBES_MS = [600, 1200, 1800, 2400, 3000, 3600, 4400];
/** A post-first-paint frame that blocked input for longer than this is one a keystroke must be aimed at. */
const PROBE_FRAME_MIN_MS = 50;
/** At most this many targeted probes per run, so the probes themselves do not become the load. */
const MAX_TARGETED_PROBES = 12;
/** Frames observed by earlier runs, aimed at by later ones: { atMs, frameAtMs, frameMs, fromRun }. */
const probeTargets = [];
/** The post-first-paint frames over PROBE_FRAME_MIN_MS that blocked input (blockingDuration > 0). */
const blockingFramesAfterPaint = (loaf, fcp) =>
  typeof fcp === "number" ? loaf.filter((e) => e.duration > PROBE_FRAME_MIN_MS && (e.blockingDuration ?? 0) > 0 && e.startTime >= fcp) : [];

/* The headed window is planned inside the screen's work area once, before the runs (acceptance report
   item 15; host-env.mjs owns the plan), and every run's window is checked against it: an off-screen
   window region is not a measurement environment. */
const headedPlan = await headedWindow(chromium, { width: 1920, height: 1080 });
console.log(headedPlan.line);
const runs = [];
for (let r = 0; r < RUNS; r++) {
  const browser = await chromium.launch({ headless: false, args: headedPlan.args });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, reducedMotion: "no-preference" });
  await ctx.addInitScript(`window.__atlasExposeScene = true;`);
  await ctx.addInitScript(INIT);
  const page = await ctx.newPage();
  const nav = page.goto(PAGE_URL, { waitUntil: "commit", timeout: 30000 });
  await nav;
  /* Type into the page at intervals across the load. Every keystroke is a real user input, so its
     Event Timing duration is the honest answer to "was the UI responsive at that moment".

     PROBES AIMED AT THE LONG FRAMES (acceptance report E5 / open-issues O20, 2026-09-22). The probes
     used to fire only at seven FIXED times, so the ~145 ms post-first-paint blocking frames were
     simply never under a keystroke, and "no keystroke over 200 ms" was a statement about seven
     instants rather than about the load. Every run after the first now ALSO fires a probe into each
     post-first-paint blocking frame over 50 ms that an EARLIER run observed (40 % of the way into
     it — cold loads repeat closely but not exactly), and each run reports how many of ITS OWN such
     frames a keystroke actually landed in (`keystrokeCoverage`), so an unprobed frame is visible
     rather than silently read as responsive.
     And the probes are timed on the NODE clock mapped to the page clock once, not by asking the page
     for performance.now() before each one: that evaluate waits for the very main thread the probe
     is trying to catch busy, so the old loop could only ever fire BETWEEN long frames. */
  const presses = [];
  const schedule = [
    ...FIXED_PROBES_MS.map((at) => ({ at, kind: "fixed" })),
    ...probeTargets.map((t) => ({ at: t.atMs, kind: "targeted", target: t })),
  ].sort((a, b) => a.at - b.at);
  const tA = performance.now();
  const pageAt = await page.evaluate(() => performance.now());
  const clockOffset = pageAt - (tA + performance.now()) / 2;
  const pageNow = () => performance.now() + clockOffset;
  for (const p of schedule) {
    const wait = p.at - pageNow();
    if (wait > 0) await sleep(wait);
    const firedAtMs = +pageNow().toFixed(0);
    await page.keyboard.press("k").catch(() => {});
    presses.push({ kind: p.kind, requestedAtMs: +p.at.toFixed(0), firedAtMs, ...(p.target ? { aimedAtFrame: p.target } : {}) });
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
  /* ...and was it inside the screen? Read after the load, so the CDP session is not part of it. */
  const windowCheck = await windowBoundsCheck(ctx, page, headedPlan.plan);
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
    window: windowCheck,
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
      .filter((e) => !e.workingAffordancePresent && !(e.browserOnly && CARVE_OUT_SANCTIONED))
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
    /* Which of THIS run's post-first-paint blocking frames a keystroke actually landed in (by the
       keystroke's own Event Timing startTime), so the keystroke bar's reach is stated, not assumed. */
    keystrokeCoverage: (() => {
      const frames = blockingFramesAfterPaint(data.loaf, data.affPaint.fcp).map((e) => {
        const hit = data.ev.find((k) => k.name === "keydown" && k.startTime >= e.startTime && k.startTime <= e.startTime + e.duration);
        return { atMs: e.startTime, durationMs: e.duration, blockingMs: e.blockingDuration, probedBy: hit ? { startTime: hit.startTime, durationMs: hit.duration } : null };
      });
      return { frameMinMs: PROBE_FRAME_MIN_MS, frames, probed: frames.filter((f) => f.probedBy !== null).length, total: frames.length };
    })(),
  });
  /* Aim the later runs at what this one observed (see the probe note above). */
  for (const e of blockingFramesAfterPaint(data.loaf, data.affPaint.fcp)) {
    if (probeTargets.length >= MAX_TARGETED_PROBES) break;
    const atMs = e.startTime + e.duration * 0.4;
    if (probeTargets.some((t) => Math.abs(t.atMs - atMs) < 40)) continue;
    probeTargets.push({ atMs: +atMs.toFixed(0), frameAtMs: e.startTime, frameMs: e.duration, fromRun: r + 1 });
  }
  console.log(`run ${r + 1}: worst animation frame ${worstLoaf ? worstLoaf.duration : "-"}ms (blocking ${worstLoaf ? worstLoaf.blockingDuration : "-"}ms) at ${worstLoaf ? worstLoaf.startTime : "-"}ms`);
  console.log(`         frames over 200ms: ${runs[r].over200ms.map((e) => e.duration + "ms@" + e.startTime).join(", ") || "none"}`);
  console.log(`         presentation: rAF median ${presentation.rafMedianMs ?? "none"} ms${presentation.fullRate ? "" : " — NOT FULL RATE"}; first paint ${data.affPaint.fcp ?? "never"} ms`);
  console.log(`         pre-first-paint frames (no page script, blocking 0, began before FCP) — ${CARVE_OUT_SANCTIONED ? "carve-out SANCTIONED by docs/acceptance.md, not counted" : "carve-out NOT sanctioned by docs/acceptance.md, COUNTED against the bar"}: ${runs[r].browserOnlyFramesOver200ms.map((e) => e.durationMs + "ms@" + e.atMs).join(", ") || "none"}`);
  console.log(`         .stage-pending visible ${runs[r].stagePendingWindowMs ? runs[r].stagePendingWindowMs.join("..") + "ms" : "NEVER"}; during worst frame: ${JSON.stringify(runs[r].domDuringWorstFrame)}`);
  console.log(`         keystrokes during load (ms): ${data.ev.map((e) => e.name + " " + e.duration + "@" + e.startTime).join(", ") || "none observed"}`);
  const cov = runs[r].keystrokeCoverage;
  console.log(
    `         probes: ${presses.filter((p) => p.kind === "fixed").length} fixed + ${presses.filter((p) => p.kind === "targeted").length} aimed at earlier runs' long frames; ` +
      `post-first-paint blocking frames over ${PROBE_FRAME_MIN_MS} ms with a keystroke IN them: ${cov.probed} of ${cov.total}` +
      `${cov.total > cov.probed ? ` — unprobed: ${cov.frames.filter((f) => f.probedBy === null).map((f) => f.durationMs + "ms@" + f.atMs).join(", ")}` : ""}`,
  );
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
/* Every run's window must have been inside the screen (see headedPlan above). */
const windowFits = runs.length > 0 && runs.every((x) => windowFitsOf(headedPlan.plan, x.window));

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
      acceptanceEvidence: verdict !== "NOT MEASURED" && hostQuiet && freshness.fresh && windowFits,
      window: { screen: headedPlan.screen, plan: headedPlan.plan, fits: windowFits, runsOutside: runs.filter((x) => !x.window.inside).map((x) => x.run) },
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
      carveOuts: [{ rule: CARVE_OUT, sanctionedByAcceptanceMd: CARVE_OUT_SANCTIONED, sanctionLine: String(SANCTION_LINE) }],
      buildFreshness: freshness,
      bar: { animationFrameMs: FRAME_BAR_MS, keystrokeMs: KEYSTROKE_BAR_MS, rule: "a frame over the bar is a finding only when no working affordance was on screen" },
      unannouncedFramesOver200ms: unannounced,
      keystrokeCoverage: { perRun: runs.map((r) => ({ run: r.run, probed: r.keystrokeCoverage.probed, total: r.keystrokeCoverage.total })), targetsAimedAt: probeTargets },
      keystrokesOverBar: slowKeys,
      url: PAGE_URL,
      runs,
    },
    null,
    1,
  ),
);

console.log(`carve-out: ${CARVE_OUT} — ${CARVE_OUT_SANCTIONED ? "SANCTIONED by docs/acceptance.md" : "NOT sanctioned by docs/acceptance.md, so NOT applied: such frames are judged"}`);
{
  const probed = runs.reduce((a, r) => a + r.keystrokeCoverage.probed, 0);
  const total = runs.reduce((a, r) => a + r.keystrokeCoverage.total, 0);
  console.log(
    `keystroke coverage: ${probed} of ${total} post-first-paint blocking frame(s) over ${PROBE_FRAME_MIN_MS} ms had a keystroke land in them across ${runs.length} run(s)` +
      `${total > probed ? " — the keystroke bar says nothing about the unprobed ones" : ""}`,
  );
}
console.log(`power: ${describePower(hostPowerAtStart)}${hostPowerThrottled ? " — THROTTLED" : ""}; presentation below full rate in run(s): ${notFullRate.join(", ") || "none"}`);
console.log(`host: ${hostBusy === null ? "unknown" : Math.round(hostBusy * 100) + "%"} busy excluding this harness (gross ${hostLoad.gross === null ? "?" : Math.round(hostLoad.gross * 100) + "%"}, idle baseline ${hostIdleBaseline === null ? "?" : Math.round(hostIdleBaseline * 100) + "%"}) (bar ${MAX_HOST_BUSY_FRACTION * 100}%); build: ${freshness.fresh ? "fresh" : "NOT FRESH — " + freshness.why}`);
console.log(`${verdict}  E5  ${why}${hostQuiet && freshness.fresh ? "" : "  [NOT ACCEPTANCE EVIDENCE]"}`);
process.exit(verdict === "PASS" ? 0 : 1);
