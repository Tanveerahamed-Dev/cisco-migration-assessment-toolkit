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
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cpus } from "node:os";
import { checkBuildFreshness } from "./build-freshness.mjs";
import {
  FULL_RATE_MAX_RAF_MS,
  PRESENTING_MAX_RAF_MS,
  closeMeasured,
  createLoadMeter,
  describePower,
  gatedBusy,
  harnessBasis,
  headedWindow,
  hostPower,
  idleBaseline,
  planWindow,
  rafCadence,
  windowBoundsCheck,
  windowFitsOf,
  windowInside,
} from "./host-env.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
/* Executed (`node review/measure-inp.mjs`), not imported: see `main` at the bottom. */
const IS_MAIN = typeof process.argv[1] === "string" && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

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
/* PERF AUDIT 2026-09-21 (third pass). E2 says "over >= 20 repetitions". The harness used to mark a
   journey `measured` when ONE repetition produced an Event Timing entry, and then took its verdict
   from however many did. Observed on the release build, headed: `J1 ... samples=4` (4 of 25 reps,
   with 60 long tasks up to 8153 ms in the same window) printed FAIL, and `J4 ... samples=6`
   (repsWithASample 3 of 25) printed PASS at p95=168 ms — a p95 over three numbers. A rep that
   yields no entry is a rep whose interaction was NOT observed, not a fast one; when too few reps
   were observed the journey is NOT MEASURED, which exits non-zero. */
const MIN_REPS_WITH_SAMPLE = Number(process.env.ATLAS_MIN_SAMPLED_REPS || 20);
/* Host busyness across the run, from the OS scheduler's cumulative per-core counters — the same
   method and bar as measure-fps.mjs. INP numbers taken while other processes held the CPU are about
   the machine; they are still printed, but acceptanceEvidence goes false. */
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
const hostBusySince = (start) => {
  const end = cpuTicks();
  if (!start || !end || end.total - start.total <= 0) return null;
  return Number((1 - (end.idle - start.idle) / (end.total - start.total)).toFixed(3));
};

/* HOST POWER STATE (perf audit, 2026-09-22). Measured on the reference machine during this audit: on
   battery at 15 %, Windows Energy Saver ON — and the headed page's rAF ran at a 33.4 ms (30 Hz)
   median in a normal, focused window, and twice stopped presenting altogether mid-journey. The CPU
   busy fraction cannot see any of that: a throttled, quiet host passes the 25 % bar. Power source and
   Energy Saver are therefore read from the OS at the start and end of the run, recorded in the
   report, and either one wrong (on battery, or saver on) withholds acceptanceEvidence and keeps the
   run out of the across-runs E3 verdict. Unknown (non-Windows, probe failed) is recorded as unknown
   and does not by itself withhold evidence. */
/* The probe itself is owned by ./host-env.mjs, shared with measure-fps, audit-e5-coldload and
   audit-e5-sweep: a guard copied into one instrument of four is not a guard for the class. */
/* CONTENTION NET OF THE HARNESS (perf audit, 2026-09-22). The gross busy fraction counted this
   harness's own headed Chromium and GPU work, and the reference host idles at 15-33 % before any
   harness runs, so the 25 % bar was unattainable (0 quiet runs) and could not tell contention from
   measurement load. The gate now reads the EXCESS over the harness's own process tree; the gross
   figure and a pre-launch idle baseline are recorded beside it (see ./host-env.mjs). */

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
  /* PERF AUDIT (2026-09-22, fifth pass). A full run reported J1 NOT MEASURED with zero Event Timing
     entries and 25 long tasks of 1003-1035 ms spaced ~2017 ms apart, one per repetition; the same
     journey measured cleanly (p95 48 ms) in two isolated reruns. Event Timing entries only finalise
     at the next PRESENTED frame, so a headed window the OS has occluded or throttled produces that
     signature. The harness recorded nothing that could tell that from an app defect, so visibility
     transitions and rAF cadence are now recorded per journey and printed with NOT MEASURED. */
  window.__vis = [{ t: performance.now(), state: document.visibilityState }];
  document.addEventListener('visibilitychange', () => window.__vis.push({ t: performance.now(), state: document.visibilityState }));
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
  /* ATTRIBUTION (review finding, E3, 2026-09-21). A 'longtask' entry is always {name:'self'} with
     no script, so the E3 verdict could say a task was on the path but not WHOSE it was; the offender
     had to be found with a separate probe. Long Animation Frames carry the scripts that ran in the
     frame (invoker, source file, forced style+layout), so every on-path long task is joined to the
     animation frame that contains it. Feature-detected: without LoAF the verdict is unchanged and
     the attribution field says it was not available. */
  window.__loaf = [];
  window.__loafSupported = false;
  try {
    if (PerformanceObserver.supportedEntryTypes?.includes('long-animation-frame')) {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) window.__loaf.push({
          startTime: e.startTime, duration: e.duration,
          renderStart: e.renderStart ?? 0, styleAndLayoutStart: e.styleAndLayoutStart ?? 0,
          scripts: (e.scripts || []).map((s) => ({
            invoker: s.invoker, sourceURL: (s.sourceURL || '').split('/').pop(),
            sourceFunctionName: s.sourceFunctionName || '',
            durationMs: Math.round(s.duration),
            forcedStyleAndLayoutMs: Math.round(s.forcedStyleAndLayoutDuration || 0),
          })).filter((s) => s.durationMs >= 5).sort((a, b) => b.durationMs - a.durationMs).slice(0, 4),
        });
      }).observe({ type: 'long-animation-frame', buffered: true });
      window.__loafSupported = true;
    }
  } catch { window.__loafSupported = false; }
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

/** Canvas points proven to select a device, found once per run by `discoverJ2Anchors` in a
 *  THROWAWAY browser — never on a page whose interactions are measured. */
export const J2_HITS = [];
/** The characters J3 types, one per repetition; shared by its act and its per-rep effect check. */
const J3_CHARS = "coreaccesswitdb";

/** Label candidates reordered tier-by-tier, heaviest (link degree) first — see `deviceAnchors`. */
const stratifyByTier = (labels) => {
  let fabric = null;
  try {
    fabric = JSON.parse(readFileSync(resolve(HERE, "..", "src", "data", "fabric.json"), "utf8"));
  } catch {
    return labels; // no compiled data: DOM order, as before, rather than no journey
  }
  const degree = new Map();
  for (const l of fabric.links ?? []) {
    degree.set(l.a, (degree.get(l.a) ?? 0) + 1);
    degree.set(l.b, (degree.get(l.b) ?? 0) + 1);
  }
  const tierOf = new Map((fabric.devices ?? []).map((d) => [d.id, d.tier]));
  const byTier = new Map();
  for (const l of labels) {
    const t = tierOf.get(l.id) ?? "unknown";
    if (!byTier.has(t)) byTier.set(t, []);
    byTier.get(t).push(l);
  }
  const deg = (id) => degree.get(id) ?? 0;
  const tiers = [...byTier.values()]
    .map((ls) => ls.sort((a, b) => deg(b.id) - deg(a.id) || a.id.localeCompare(b.id)))
    .sort((a, b) => deg(b[0].id) - deg(a[0].id));
  const out = [];
  for (let i = 0; out.length < labels.length; i++) for (const ls of tiers) if (i < ls.length) out.push(ls[i]);
  return out;
};

const deviceAnchors = async (page, priority = []) => {
  /* Scan the canvas for points that actually pick a DEVICE, and keep only those.
     The selection is read back from the URL (`d=` is a navigation field in urlSync), so a point is
     kept only when the APPLICATION says a device became selected. That is deliberately independent
     of `window.__atlasScene`: the scene handle is an instrument, and an instrument should not be
     the thing that decides whether the actuation worked.
     This CLICKS, so it spends the page's first device selections. It therefore runs ONLY in the
     throwaway browser `discoverJ2Anchors` launches and closes before any measured page exists
     (acceptance report E3, 2026-09-23: running it as J2's `prime` spent the first selection after
     load — the one with the 55-79 ms task on its path — outside the measurement). */
  const canvas = page.locator("canvas").first();
  const b = await canvas.boundingBox();
  if (!b) return [];
  const hits = [];
  const seen = new Set();
  /* Aim through the devices' own labels FIRST, as the journey's note says it does. REVIEW FIX,
     2026-09-21: the code only ever swept a fixed lattice of canvas fractions, so whether J2 could be
     measured at all depended on where the camera's default framing happened to put the chassis —
     after a framing change, 2 of 81 lattice points hit a device and J2 went NOT MEASURED on a build
     whose picking was fine. Each label sits just above its chassis, so the candidates are points a
     little below the label's centre; a point is still kept only when the APPLICATION reports that
     device selected, and the click still goes to the canvas (a real 3-D pick, not a DOM shortcut). */
  const domLabels = await page.evaluate(() =>
    [...document.querySelectorAll(".fabric3d-label[data-device]")].map((el) => {
      const r = el.getBoundingClientRect();
      return { id: el.getAttribute("data-device"), x: r.left + r.width / 2, y: r.bottom };
    }),
  );
  /* STRATIFIED BY TIER, HEAVIEST FIRST (review finding, E1, 2026-09-21). The labels used to be
     taken in DOM order and the first 12 hits kept, which on this snapshot is access1..access4 and
     access10..access17: every J2 sample was an access switch, and the core and distribution
     devices — the most links, the heaviest selection emphasis — were never measured. The order is
     now read from the compiled data the app renders: devices grouped by layout tier, each tier
     sorted by link degree (descending), and the tiers interleaved heaviest-tier first, so the 12
     anchors cover every tier and start with the most expensive selections. */
  /* The first-selection trials' targets go first, so each of them gets an anchor whatever the
     stratified order would have kept (the scan stops at 12). */
  const stratified = stratifyByTier(domLabels);
  const labels = [...priority.flatMap((id) => stratified.filter((l) => l.id === id)), ...stratified.filter((l) => !priority.includes(l.id))];
  for (const l of labels) {
    if (hits.length >= 12) break;
    if (seen.has(l.id)) continue;
    for (const dy of [22, 34, 12, 48]) {
      const x = l.x;
      const y = l.y + dy;
      if (x < b.x || x > b.x + b.width || y < b.y || y > b.y + b.height) continue;
      await page.mouse.click(x, y);
      await page.waitForTimeout(120);
      const id = await page.evaluate(() => (location.search.match(/[?&]d=([^&]*)/) || [])[1] ?? null);
      if (id && !seen.has(id)) {
        seen.add(id);
        hits.push({ id, x, y });
        break;
      }
    }
  }
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
export const JOURNEYS = [
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
    /* HARNESS FIX (acceptance report E3, 2026-09-22). `verify` used to CLICK a finding before the
       measured loop to prove selection worked — which spent the first selection after load, the
       expensive one (measured by the sweep at worstLoAF 93.4 ms in 1 of 3 reps), outside the
       measurement. Every J1 figure was therefore a SECOND-or-later selection. The pre-loop check now
       only counts rows (no interaction), and the proof that each measured click selected a finding is
       taken AFTER that rep's timing has been captured (`effect`), so rep 0 is the first selection
       after load and a click that selected nothing is excluded from the figure rather than counted
       as a fast one. */
    verify: async (page) => {
      const n = await page.locator(".ag__row--data").count();
      return n < 5 ? `only ${n} finding data rows present` : null;
    },
    verifyInteracts: false,
    effect: {
      before: (page) => page.evaluate(() => location.search),
      check: async (page, before) => {
        const ok = await page
          .waitForFunction((prev) => location.search !== prev && /[?&]f=/.test(location.search), before, { timeout: 3000 })
          .then(() => true)
          .catch(() => false);
        if (ok) return null;
        const after = await page.evaluate(() => location.search);
        return `the click selected no finding (URL ${before} -> ${after})`;
      },
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
    /* HARNESS FIX (acceptance report E3, 2026-09-23). The anchors used to be found HERE, in `prime`,
       by clicking the canvas until the app reported a device selected — so the first device
       selections after load were spent before the loop, and J2 only ever measured warm selections
       while the first one put a 55-79 ms task on its path in 15 of 15 fresh-browser trials. They are
       now found once per run in a THROWAWAY browser (`discoverJ2Anchors`, closed before any measured
       page opens; the points are a function of the layout and the default framing at this viewport,
       which F6 pins byte-identical), and this journey has no pre-loop input at all: rep 0 IS the first
       selection after load, and each rep's own effect check still proves the click selected the
       device it aimed at. The first selection is ALSO measured on its own, in a fresh browser per
       trial, by FIRST_SELECTION below — one sample per run is not a distribution. */
    effect: {
      before: async () => null,
      check: async (page, _before, i) => {
        const want = J2_HITS[i % J2_HITS.length]?.id ?? null;
        const ok = await page
          .waitForFunction((id) => (location.search.match(/[?&]d=([^&]*)/) || [])[1] === id, want, { timeout: 3000 })
          .then(() => true)
          .catch(() => false);
        if (ok) return null;
        const got = await page.evaluate(() => (location.search.match(/[?&]d=([^&]*)/) || [])[1] ?? null);
        return `the click aimed at ${want} selected ${got ?? "nothing"}`;
      },
    },
    /* No `verify` here: the anchor discovery IS the verification, and it is stronger than one. It
       keeps a canvas point only when the application reports a device selected, so if fewer than
       three such points exist the journey cannot run and `act` throws, which the harness reports as
       NOT MEASURED. */
    act: async (page, i) => {
      if (J2_HITS.length < 3)
        throw new Error(`only ${J2_HITS.length} canvas points select a device${J2_ANCHOR_REASONS.length ? ` (anchor discovery: ${J2_ANCHOR_REASONS.join("; ")})` : ""}`);
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
    /* HARNESS FIX (2026-09-22, the J1 defect's class). This verify TYPES a character, so run before
       the loop it spent the first keystroke after load outside the measurement. It now runs AFTER the
       loop (`verifyAfter`), and each measured keystroke's own effect is checked once its timing is
       captured (`effect`), so rep 0 is the first keystroke and a keystroke that changed nothing is
       excluded rather than counted as fast. */
    verifyAfter: true,
    effect: {
      before: async () => null,
      check: async (page, _before, i) => {
        const want = J3_CHARS.charAt(i % J3_CHARS.length);
        const v = await page.locator(".hdr-query__input, [data-journey=\"query-input\"]").first().inputValue();
        return v === want ? null : `the keystroke "${want}" left the query reading ${JSON.stringify(v)}`;
      },
    },
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
      await page.keyboard.press(J3_CHARS.charAt(i % J3_CHARS.length));
    },
  },
  {
    id: "J3b-type-and-erase",
    url: "/?s=findings",
    /* REVIEW FINDING, 2026-09-21 (E2). J3 measures the CHEAPEST keystroke the query bar has: the
       first character typed into an EMPTY field after a 400 ms settle, with the field reset between
       repetitions through a non-keyboard path. "Type in the query bar" is also every later character
       and every Backspace, typed at a human cadence while the previous keystroke's filter is still
       landing — and a headed probe measured exactly those as the slow ones (later characters p95
       232 ms, Backspace with 106-119 ms tasks on the interaction path) while J3 stayed green.

       So this journey types the way a reader does: "core" at ~150 ms between keys, then four
       Backspaces at the same cadence, which empties the field again BY KEYBOARD — no harness reset,
       nothing measured is setup. Each repetition therefore carries eight real keystrokes, and the
       E2 figure is the worst of them per repetition (worstPerRep), so one slow later character or
       Backspace cannot be diluted by seven fast ones. */
    ready: ".hdr-query__input, [data-journey=\"query-input\"]",
    /* Types "core" and erases it: run AFTER the loop, so the first measured repetition is the first
       typing after load (the J1 defect's class, 2026-09-22). Each rep's own effect — the field back to
       empty by keyboard — is checked once its timing is captured. */
    verifyAfter: true,
    effect: {
      before: async () => null,
      check: async (page) => {
        const v = await page.locator(".hdr-query__input, [data-journey=\"query-input\"]").first().inputValue();
        return v === "" ? null : `four Backspaces left the query reading ${JSON.stringify(v)}`;
      },
    },
    verify: async (page) => {
      const input = page.locator(".hdr-query__input, [data-journey=\"query-input\"]").first();
      await input.click();
      for (const ch of "core") await input.press(ch);
      await page.waitForTimeout(400);
      const v = await input.inputValue();
      const rows = await page.locator(".ag__row--data").count();
      for (let i = 0; i < 4; i++) await input.press("Backspace");
      await page.waitForTimeout(400);
      const after = await input.inputValue();
      if (v !== "core") return `typing "core" left the field reading ${JSON.stringify(v)}`;
      if (after !== "") return `four Backspaces left the field reading ${JSON.stringify(after)}`;
      return rows > 0 ? null : "\"core\" emptied the findings grid — the measured keystrokes would filter nothing";
    },
    prime: async (page) => {
      await page.locator(".hdr-query__input, [data-journey=\"query-input\"]").first().click();
      await page.waitForTimeout(200);
    },
    act: async (page) => {
      /* Start every repetition from the restored 146-row grid, settled — the previous
         repetition's last Backspace put it back, and its filter commit must not spill into this one. */
      await page
        .waitForFunction(() => document.querySelectorAll(".ag__row--data").length >= 100, null, { timeout: 5000 })
        .catch(() => {});
      await page.waitForTimeout(400);
      for (const ch of "core") {
        await page.keyboard.press(ch);
        await page.waitForTimeout(150);
      }
      for (let i = 0; i < 4; i++) {
        await page.keyboard.press("Backspace");
        await page.waitForTimeout(150);
      }
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
    /* HARNESS FIX (acceptance report E1, 2026-09-22). `verify` ran BEFORE the measured act and
       proved only that the URL-SEEDED flow had rendered a result — not that any timed swap+submit
       traced anything. A submit that was short-circuited (same flow) or ignored would have been
       timed as a fast trace. The pre-loop check below still reads the button and the seeded result
       (neither is an interaction); the proof now belongs to the SAME act that was timed: after each
       rep's timing is captured, `effect` requires the investigated flow in the URL AND the rendered
       result to have changed, and every rep's outcome is reported (`repEffects`, `repsWithEffect`). */
    verify: async (page) => {
      const btn = page.locator('#rail-path form.pt-form button[type="submit"]').first();
      const txt = (await btn.textContent()) ?? "";
      if (!/trace/i.test(txt)) return `submit button reads ${JSON.stringify(txt)}, not a trace action`;
      const result = await page.locator("#rail-path .pt-result__title, #rail-path h3").count();
      return result > 0 ? null : "no trace result rendered for the seeded flow — the panel mounted but did not trace";
    },
    verifyInteracts: false,
    effect: {
      before: (page) =>
        page.evaluate(() => ({
          flow: new URLSearchParams(location.search).get("flow"),
          result: document.querySelector("#rail-path .pt-result")?.textContent ?? null,
        })),
      check: async (page, before) => {
        const ok = await page
          .waitForFunction(
            (prev) => {
              const flow = new URLSearchParams(location.search).get("flow");
              const result = document.querySelector("#rail-path .pt-result")?.textContent ?? null;
              return flow !== null && flow !== prev.flow && result !== null && result !== prev.result;
            },
            before,
            { timeout: 3000 },
          )
          .then(() => true)
          .catch(() => false);
        if (ok) return null;
        const now = await page.evaluate(() => new URLSearchParams(location.search).get("flow"));
        return `the timed swap+submit produced no new trace (flow ${before?.flow} -> ${now}; result ${before?.result === null ? "absent" : "unchanged or absent"})`;
      },
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
         interaction in the repetition — which is the submit, i.e. the trace.
         SCOPE (decided 2026-09-23, docs/acceptance.md "E3's scope"): a declared journey is exactly
         what its act times, so BOTH the swap and the submit belong to J4 — E3 counts a long task on
         either — and review/audit-e5-sweep.mjs must not time them again as an "outside" action
         (src/core/journey-scope.test.ts derives that from both files). */
      await page.locator("#rail-path .pt-form__swap").first().click();
      await page.waitForTimeout(80);
      await page.locator('#rail-path form.pt-form button[type="submit"]').first().click();
    },
  },
  {
    id: "J5-open-palette",
    url: "/",
    ready: "body",
    /* Opens the palette, so it runs AFTER the loop: before it, it spent the first palette open after
       load (the chunk/first-mount cost) outside the measurement (the J1 defect's class, 2026-09-22).
       The palette is closed again within the rep, so no per-rep effect can be read after timing. */
    verifyAfter: true,
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

/* ── THE FIRST DEVICE SELECTION AFTER LOAD, one fresh browser per trial ──────────────────────────
 *
 * Acceptance report E3 (2026-09-23, overturned PASS): "in a fresh browser, the first canvas click on
 * core2 gave ONPATH>50 in 15 of 15 trials (d = 55-79 ms) ... core1 did so in 1 of 3 trials and dist1
 * in 0 of 3", while this harness reported J2 clean because it had spent that selection in `prime`
 * and measured a warm browser. J2's rep 0 is now the first selection in its own page, but that is ONE
 * sample per run; a first-after-load cost is a distribution over loads. So it is measured on its own:
 * every trial launches a NEW browser (a new GPU process too, so no shader or program cache from an
 * earlier trial can hide anything), loads the fabric, waits until it is drawn and settled — a click
 * on a canvas that has not drawn is ignored by the product, and would time a no-op — and then makes
 * exactly ONE click, whose effect (the URL naming the aimed device) is checked after its timing is
 * captured. `ATLAS_FIRST_TARGETS=id:trials,...` overrides the default sample. */
const parseTargets = (spec) =>
  spec
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => {
      const [id, n] = x.split(":");
      return { id, trials: Math.max(1, Math.floor(Number(n) || 1)) };
    });

export const FIRST_SELECTION = {
  id: "J2-first-select-device-3d",
  url: "/?s=fabric",
  targets: parseTargets(process.env.ATLAS_FIRST_TARGETS || "core2:15,core1:3,dist1:3"),
  /** Everything between navigation and the measured click. It reads and waits; it never actuates. */
  async beforeClick(page) {
    await page.waitForSelector("canvas", { timeout: 15000 });
    await page.waitForFunction(() => window.__atlasScene?.stats?.().converged === true, null, { timeout: 30000 });
    await page.waitForTimeout(2500); // the same drain every journey gets before its loop
  },
  /** The one measured interaction of a trial. */
  async act(page, anchor) {
    await page.mouse.click(anchor.x, anchor.y);
  },
};

/* ── WINDOW GEOMETRY (acceptance report item 15, 2026-09-23) ──────────────────────────────────────
 *
 * The headed window used to be launched at a fixed 1940x1180 window size for a 1920x1080
 * viewport. On the reference host the screen is 1920x1200 physical at 150 % scaling — a 1280x752 DIP
 * work area — so the window was half again the size of the screen and most of it, the canvas
 * included, was off-screen (the report attributes off-screen "8096 ms" keyboard artefacts to it).
 * The viewport stays the render target E2 is written about (1920x1080 CSS px at DSF 1); the WINDOW is
 * now sized to hold it and placed inside the screen's work area. When the work area cannot hold it at
 * the display's own scale, the browser is started with a smaller device scale factor
 * (`--force-device-scale-factor`), which changes the browser's DIP-to-pixel ratio and nothing about
 * the page: the page is emulated at DSF 1, so the canvas draws the same 1920x1080 buffer either way.
 * The screen, the plan and the window the OS actually gave are recorded in the report, and a window
 * that does not fit withholds acceptanceEvidence. */
export const VIEWPORT = { width: 1920, height: 1080 };

/* planWindow / windowInside moved to ./host-env.mjs (the class: every headed instrument plans its
   window there, src/core/headed-window.test.ts). Re-exported for the known-answer tests. */
export { planWindow, windowInside };

/**
 * Long tasks over 50 ms that overlap an interaction, each with WHERE on the path it ran — the one
 * rule every E3 figure in this file is taken with (the journeys and the first-selection trials).
 * `attribute(l)` joins a task to its Long Animation Frame, or returns null.
 */
export function onPathLongTasks(longTasks, interactions, attribute = () => null) {
  return longTasks
    .filter((l) => l.duration > 50)
    .map((l) => {
      const hit = interactions.find((e) => l.startTime < e.startTime + e.duration + 1 && l.startTime + l.duration > e.startTime - 1);
      /* WHERE on the path (review finding, E3, 2026-09-21). "On-path" pooled three different
         defects: a task that held the input back before its handler could run (input delay), a task
         that ran the handler, and a task that starts after the handler returned but before the 8 ms
         rounded presentation time (deferred work that still lands inside the frame the interaction is
         presented in). They have different fixes, so each is named. Classified against the HANDLER
         window [processingStart, processingEnd], with 1 ms of slack for timestamp rounding. */
      const phase = !hit
        ? null
        : l.startTime + l.duration <= hit.processingStart + 1
          ? "input-delay"
          : l.startTime >= hit.processingEnd - 1
            ? "post-handler-pre-present"
            : "in-handler";
      return {
        durationMs: l.duration,
        startTime: l.startTime,
        overlapsInteraction: hit ? hit.name : null,
        interactionDurationMs: hit ? Number(hit.duration.toFixed(1)) : null,
        phase,
        attribution: hit ? attribute(l) : null,
      };
    });
}

/** The longest Long Animation Frame that overlaps an interaction's [start, start + duration]. */
export function worstLoafOnPath(loafs, interactions) {
  let worst = null;
  for (const f of loafs) {
    if (!interactions.some((e) => f.startTime < e.startTime + e.duration + 1 && f.startTime + f.duration > e.startTime - 1)) continue;
    if (worst === null || f.duration > worst.duration) worst = f;
  }
  return worst;
}

/**
 * Why a journey's FIRST interaction after load is not its rep 0 — or null when it is.
 *
 * Recorded per journey in the report, and pinned by `src/fabric3d/Fabric3D.test.tsx` (describe
 * "measure-inp: no journey spends its first interaction before the measured loop"), which also
 * executes every journey's pre-loop hooks against a recording page: a journey whose setup
 * performs the kind of input it measures spends the most expensive instance of it (the first after
 * load) outside the measurement, and that is the defect E3's grading found in J2 (2026-09-23).
 */
export function firstInteractionConsumedBeforeLoop(j) {
  return (
    j.consumesFirstInteraction ??
    (typeof j.verify === "function" && !j.verifyAfter && j.verifyInteracts !== false ? "verify performs the journey's interaction before the loop" : null)
  );
}

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

/**
 * Why J2's anchor discovery found what it found — every reason it did not find more, in words.
 * Empty when discovery ran cleanly. Read by J2's `act`, so a NOT MEASURED J2 names its cause.
 */
export const J2_ANCHOR_REASONS = [];

/**
 * Find J2's canvas anchors ONCE, in a throwaway browser that is closed before any measured page
 * opens (finding them clicks the canvas, and a click on a measured page would spend its first
 * selection).
 *
 * HARNESS FIX (acceptance report, E harness item 12a, 2026-09-23). This used to be inline in `main`
 * and ended `FIRST_SELECTION.beforeClick(spage).catch(() => null)`: when the fabric never reached a
 * drawn, settled state, the failure was swallowed, the scan ran on an unsettled canvas, and the run
 * printed "J2 anchors …: none" with no reason — so a NOT MEASURED J2 could not be told from a
 * picking defect, a slow host or a server that served nothing. Every failure is now recorded and
 * printed on the same line, and the scan still runs (an unsettled canvas may still pick) with its
 * precondition named rather than assumed.
 *
 * @param {() => Promise<any>} launch  starts the throwaway browser
 * @param {{ app: string, context: object, initScript: string, log?: (line: string) => void, meter?: { sample(): void } | null }} opts
 * @returns {Promise<{ hits: { id: string, x: number, y: number }[], reasons: string[] }>}
 */
export async function discoverJ2Anchors(launch, { app, context, initScript, log = console.log, meter = null }) {
  const reasons = [];
  let hits = [];
  let scout = null;
  try {
    scout = await launch();
    const sctx = await scout.newContext(context);
    await sctx.addInitScript(initScript);
    const spage = await sctx.newPage();
    const nav = await gotoWithRetry(spage, `${app}${FIRST_SELECTION.url}`);
    if (!nav.ok) {
      reasons.push(`the server did not serve ${FIRST_SELECTION.url} (${nav.error ?? nav.firstError})`);
    } else {
      try {
        await FIRST_SELECTION.beforeClick(spage);
      } catch (e) {
        reasons.push(`the fabric never reached a drawn, settled state before the scan (${String(e).split("\n")[0].slice(0, 160)}); the scan ran on an unsettled canvas`);
      }
      hits = await deviceAnchors(spage, FIRST_SELECTION.targets.map((t) => t.id));
      if (hits.length === 0) reasons.push("no scanned canvas point made the application report a device selected");
    }
  } catch (e) {
    reasons.push(`anchor discovery threw: ${String(e).split("\n")[0].slice(0, 160)}`);
  } finally {
    /* Through the run's meter (host-env.mjs :: closeMeasured); a unit test's fake browser has none. */
    if (scout !== null) await closeMeasured(meter, scout).catch(() => null);
  }
  J2_HITS.length = 0;
  J2_HITS.push(...hits);
  J2_ANCHOR_REASONS.length = 0;
  J2_ANCHOR_REASONS.push(...reasons);
  log(
    `  J2 anchors (found in a throwaway browser; first-selection targets first, then tier-stratified): ${hits.map((h) => h.id).join(", ") || "none"}` +
      (reasons.length ? ` — ${reasons.join("; ")}` : ""),
  );
  return { hits, reasons };
}

/**
 * E3 across runs of one build, for one journey. HARNESS FIX (acceptance report, E harness item 12c,
 * 2026-09-23): a run in which the journey was NOT MEASURED used to be counted as "not clean", so
 * three clean runs and one unmeasured run read UNSTABLE — and the roll-up then printed E3 FAIL for a
 * journey no run had ever seen violate. An unmeasured run is neither clean nor a violation: it is
 * counted apart (`notMeasured`), and the stable verdict is taken over the runs that measured.
 * (A run whose journey was under-sampled but DID observe an on-path violation is E3-FAIL, not NOT
 * MEASURED — see `rec.e3Verdict` — so it still counts against the journey.)
 *
 * @param {{ journeys?: Record<string, { e3?: string }> }[]} runs
 * @param {string} id
 * @param {number} minRuns
 */
export function e3StableVerdict(runs, id, minRuns) {
  const seen = runs.map((h) => h.journeys?.[id]?.e3).filter(Boolean);
  const measured = seen.filter((v) => v === "E3-PASS" || v === "E3-FAIL");
  const clean = measured.filter((v) => v === "E3-PASS").length;
  const stable =
    measured.length < minRuns ? "INSUFFICIENT RUNS" : clean === measured.length ? "STABLE PASS" : clean === 0 ? "STABLE FAIL" : "UNSTABLE";
  return { runs: seen.length, measured: measured.length, notMeasured: seen.length - measured.length, clean, stable };
}

/* ── the run ──────────────────────────────────────────────────────────────────────────────
   Everything that launches a browser, reads the host or writes a report lives in `main`, and
   `main` runs only when this file is EXECUTED. Imported — by `src/fabric3d/Fabric3D.test.tsx` (the
   first-interaction, window-plan, anchor-discovery and across-runs rules) and by
   `src/core/journey-scope.test.ts` (the journeys' acts against the E5 sweep's and the declaration in
   docs/acceptance.md) — it is a module of pure journey definitions and helpers, so the rules the
   measurement depends on can be pinned by a test instead of trusted. */
async function main() {
  const { chromium } = await import("@playwright/test");
  const hostCpuAtStart = cpuTicks();
  const hostPowerAtStart = hostPower();
  const hostIdleBaseline = await idleBaseline(3000);
  const hostLoadMeter = createLoadMeter();
  hostLoadMeter.start();
  const server = await probeServer(APP);
  /* A stale or foreign build measures a different program (review finding, E2). See build-freshness.mjs. */
  const freshness = await checkBuildFreshness(APP, server);
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

  /* The screen, read once from a throwaway headed browser at the display's own scale (no viewport
     emulation, so outer - inner is the browser chrome), and the window plan made from it — see
     planWindow. A probe that fails leaves the plan null: the old fixed size is used, and the window
     check below then withholds acceptanceEvidence rather than guessing. */
  const headedPlan = HEADED ? await headedWindow(chromium, VIEWPORT, hostLoadMeter) : null;
  const screenProbe = headedPlan?.screen ?? null;
  const windowPlan = headedPlan?.plan ?? null;
  /* Occlusion flags (perf audit, 2026-09-22): Chromium on Windows stops presenting a window the OS
     reports as covered, and an unpresented window yields no Event Timing entries. headedWindow's
     args carry them. */
  const LAUNCH = HEADED ? { headless: false, args: headedPlan.args } : {};
  const CONTEXT = { viewport: VIEWPORT, deviceScaleFactor: 1 };
  if (HEADED) console.log(headedPlan.line);
  /** The window the OS actually gave the first measured page, checked against the plan. */
  let windowCheck = HEADED ? { checked: false } : { checked: false, skipped: "headless" };
  const checkWindow = async (ctx, page) => {
    if (!HEADED || windowCheck.checked) return;
    windowCheck = await windowBoundsCheck(ctx, page, windowPlan);
  };

  const browser = await chromium.launch(LAUNCH);

  /* PRESENTATION PRECONDITION (perf audit, 2026-09-22). Reproduced deliberately: with the headed window
     MINIMISED, J1 reported both failure modes seen in full runs — the verify click's URL change had not
     landed after 400 ms ("selecting a finding did not change the investigation"), and the measured loop
     observed ZERO interactions while recording ~1000 ms long tasks and ~2 s per repetition.
     document.visibilityState stayed "visible" throughout, so visibility cannot detect it; the rAF
     cadence can. Before each journey the window is therefore required to be presenting (median rAF
     interval under 25 ms). If it is not, it is restored and brought to front once, and a window that
     still is not presenting makes the journey NOT MEASURED with that cause named — an environment
     failure, never a verdict about the app. ATLAS_TEST_MINIMIZE=1 minimises the window before the
     check, to prove the guard works. */
  /* "Not presenting" means no frames, or a median rAF over 100 ms (measured signature: ~1000 ms). A 30 Hz
     cadence (Energy Saver, measured 33.4 ms) IS presenting: its numbers are an upper bound on a throttled
     machine, recorded per journey as rafMedianMs and withheld from acceptance by the host-power gate. */
  /* PRESENTING_MAX_RAF_MS and rafCadence are owned by ./host-env.mjs. */
  async function ensurePresenting(ctx, page) {
    if (!HEADED) return { ok: true, skipped: "headless" };
    const cdp = await ctx.newCDPSession(page);
    const { windowId } = await cdp.send("Browser.getWindowForTarget");
    if (process.env.ATLAS_TEST_MINIMIZE === "1") {
      await cdp.send("Browser.setWindowBounds", { windowId, bounds: { windowState: process.env.ATLAS_TEST_MINIMIZE_LATE === "1" ? "normal" : "minimized" } });
      await page.waitForTimeout(3000);
    }
    const first = await rafCadence(page);
    if (first !== null && first < PRESENTING_MAX_RAF_MS) return { ok: true, rafMedianMs: first, restored: false };
    await cdp.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "normal" } });
    await page.bringToFront();
    await page.waitForTimeout(800);
    const second = await rafCadence(page);
    return { ok: second !== null && second < PRESENTING_MAX_RAF_MS, rafMedianMs: second, firstRafMedianMs: first, restored: true };
  }
  /* Publish the scene handle on the release build too. `devHandle.ts` no longer gates it on
     `import.meta.env.DEV` — which is what made the tier unreadable on the artefact under test — and
     this is the opt-in it now looks for. Set before the app mounts, so it is read at module eval. */
  const EXPOSE_SCENE = `window.__atlasExposeScene = true;`;
  const results = [];
  let environment = null;

  const ONLY = process.env.ATLAS_ONLY ? process.env.ATLAS_ONLY.split(",") : null;
  const selected = (id) => !ONLY || ONLY.some((o) => id.includes(o));

  /* J2's anchors, found ONCE, in a browser of their own that is closed before any measured page is
     opened: finding them clicks the canvas (see deviceAnchors), and a click on a measured page would
     spend its first selection. */
  let anchorDiscovery = null;
  if (selected("J2-select-device-3d") || selected(FIRST_SELECTION.id)) {
    anchorDiscovery = await discoverJ2Anchors(() => chromium.launch(LAUNCH), {
      app: APP,
      context: CONTEXT,
      initScript: EXPOSE_SCENE,
      meter: hostLoadMeter,
    });
  }

  for (const j of JOURNEYS.filter((x) => selected(x.id))) {
    const ctx = await browser.newContext(CONTEXT);
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
        await hostLoadMeter.close(ctx);
        results.push(rec);
        console.log(`${"TRANSPORT".padEnd(12)} ${rec.id.padEnd(22)} [server did not serve the page twice: ${rec.transportFailure}]`);
        continue;
      }
      await page.waitForSelector(j.ready, { timeout: 15000 });
      await page.waitForTimeout(2500); // let first-paint work drain so we measure steady state

      /* Record the machine that produced these numbers, per journey, so a reader can see which one
         did — and so a SwiftShader figure can never be mistaken for a GPU figure after the fact. */
      rec.presenting = await ensurePresenting(ctx, page).catch((e) => ({ ok: false, error: String(e).slice(0, 120) }));
      if (!rec.presenting.ok) {
        rec.reason = `window not presenting (median rAF ${rec.presenting.rafMedianMs ?? "none in 4 s"} ms after restore, bar < ${PRESENTING_MAX_RAF_MS} ms) — harness environment, not the app`;
        rec.verdict = "NOT MEASURED";
        rec.e3Verdict = "NOT MEASURED";
        await hostLoadMeter.close(ctx);
        results.push(rec);
        console.log(`${"NOT MEASURED".padEnd(12)} ${rec.id.padEnd(22)} [${rec.reason}]`);
        continue;
      }
      if (rec.presenting.restored)
        console.log(`  ${rec.id}: window was not presenting (median rAF ${rec.presenting.firstRafMedianMs} ms); restored -> ${rec.presenting.rafMedianMs} ms`);
      await checkWindow(ctx, page);
      rec.environment = await page.evaluate(RENDERER_PROBE).catch(() => null);
      if (environment === null && rec.environment) environment = rec.environment;

      /* Prove the interaction actually DOES something before measuring how fast it does it. A
         latency figure for a no-op is not a fast interaction, it is a missing one — and it is worse
         than no figure at all, because it reports as PASS. */
      /* A verify that PERFORMS the journey's own interaction runs after the measured loop instead
         (`verifyAfter`), so it cannot spend the first interaction after load outside the measurement.
         Recorded either way, per journey, so a reader can see whether rep 0 was the first. */
      rec.firstInteractionConsumedBeforeLoop = firstInteractionConsumedBeforeLoop(j);
      if (typeof j.verify === "function" && !j.verifyAfter) {
        const why = await j.verify(page).catch((e) => `verify threw: ${String(e).slice(0, 120)}`);
        if (why) {
          /* A verify failure on a window that is not presenting is the environment, not the app
             (reproduced: minimised window -> "selecting a finding did not change the investigation"). */
          const cad = HEADED ? await rafCadence(page).catch(() => null) : 0;
          rec.reason = cad !== null && cad < PRESENTING_MAX_RAF_MS ? why : `${why} — BUT the window was not presenting (rAF median ${cad ?? "none in 4 s"}); harness environment, not the app`;
          rec.verdict = "NOT MEASURED";
          await hostLoadMeter.close(ctx);
          results.push(rec);
          console.log(`${"NOT MEASURED".padEnd(12)} ${rec.id.padEnd(22)} [${rec.reason}]`);
          continue;
        }
      }

      if (typeof j.prime === "function") await j.prime(page);

      /* PERF AUDIT FIX (2026-09-21, third pass). Event Timing entries are delivered AFTER the next
         paint, not when the event fires, so on a loaded host the prime's own focus click arrived after
         the buffer was cleared below and was pooled into rep 0: measured, J3-type-query's
         eventHistogram read `pointerdown 1, pointerup 1, click 1` beside 25 keydowns (samples=26 for
         25 reps). Let two frames present and the observer drain before the measured window opens. */
      await page.evaluate(
        () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 300)))),
      );

      await page.evaluate(() => {
        window.__ev.length = 0;
        window.__long.length = 0;
        window.__loaf.length = 0;
      });

      /* PERF AUDIT FIX, 2026-09-22 (fourth pass). Repetitions used to be windowed by DELIVERY time:
         after each act the harness waited 160 ms and took whatever the observer had delivered. Event
         Timing entries are delivered after the next paint, so on a loaded host an interaction whose
         presentation took ~200 ms arrived in the NEXT repetition's window, where only that window's
         max survived. Measured on the release build, host 77% busy: J3-type-query recorded 25
         interactions (samples=25, keydown 25) yet only 19 reps "produced an entry" -> NOT MEASURED.
         Every keystroke WAS observed; the harness misfiled six of them. Repetitions are now binned
         by the interaction's own startTime against a per-rep start mark taken in the page's clock,
         and the buffer is drained (two frames + 300 ms) before the final read so the last rep's
         entry is not lost either. */
      let ok = 0;
      const repStarts = [];
      const allEntries = [];
      /* PER-REP EFFECT (acceptance report E1/E3, 2026-09-22). The proof that a timed act DID what the
         journey claims is taken from THAT act, after its timing has been captured: one entry per
         successful act, null = effect observed, a string = why not. A rep whose act had no observed
         effect timed a no-op and is excluded from the figure (never counted as a fast interaction). */
      const repEffects = [];
      for (let i = 0; i < REPS; i++) {
        if (process.env.ATLAS_TEST_MINIMIZE_LATE === "1" && i === 3 && HEADED) {
          const cdp2 = await ctx.newCDPSession(page);
          const { windowId } = await cdp2.send("Browser.getWindowForTarget");
          await cdp2.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "minimized" } });
        }
        const effectBefore = j.effect ? await j.effect.before(page).catch(() => null) : null;
        repStarts.push(await page.evaluate(() => performance.now()));
        try {
          await j.act(page, i);
          ok++;
        } catch (e) {
          repStarts.pop();
          rec.reason = `act failed at rep ${i}: ${String(e).slice(0, 140)}`;
          break;
        }
        await page.waitForTimeout(160); // separate interactions so they get distinct interactionIds
        const window_ = await page.evaluate(() => {
          const ev = window.__ev.slice();
          window.__ev.length = 0;
          return ev;
        });
        allEntries.push(...window_);
        if (j.effect) repEffects.push(await j.effect.check(page, effectBefore, i).catch((e) => `effect check threw: ${String(e).slice(0, 120)}`));
      }
      await page.evaluate(
        () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 300)))),
      );

      const data = await page.evaluate(() => ({
        ev: window.__ev,
        long: window.__long,
        loaf: window.__loaf,
        loafSupported: window.__loafSupported === true,
      }));
      /* The animation frame a long task belongs to: the LoAF entry whose window contains most of it. */
      const frameFor = (l) => {
        let best = null;
        let bestOverlap = 0;
        for (const f of data.loaf) {
          const overlap = Math.min(l.startTime + l.duration, f.startTime + f.duration) - Math.max(l.startTime, f.startTime);
          if (overlap > bestOverlap) {
            best = f;
            bestOverlap = overlap;
          }
        }
        return best;
      };
      const attribute = (l) => {
        if (!data.loafSupported) return { available: false };
        const f = frameFor(l);
        if (f === null) return { available: true, frame: null };
        const scripted = f.scripts.reduce((a, s) => a + s.durationMs, 0);
        return {
          available: true,
          frame: { startTime: Number(f.startTime.toFixed(1)), durationMs: Number(f.duration.toFixed(1)) },
          scripts: f.scripts,
          /* A frame whose scripts account for little of it spent its time in style, layout or paint:
             named as such rather than left as an empty script list. */
          renderOnly: f.scripts.every((s) => s.durationMs < 50) && scripted < f.duration / 2,
        };
      };
      allEntries.push(...data.ev);
      // INP is computed from interactions — entries with a non-zero interactionId. Discrete events
      // (click, keydown/up) are what count; continuous ones (mousemove) are not interactions.
      const interactions = allEntries.filter((e) => e.interactionId && e.interactionId > 0);
      const durations = interactionDurations(allEntries);
      // Bin each interaction (grouped by interactionId, earliest startTime) into the repetition whose
      // start mark precedes it; the worst interaction per bin is that repetition's figure.
      const byInteraction = new Map();
      for (const e of interactions) {
        const cur = byInteraction.get(e.interactionId);
        byInteraction.set(e.interactionId, {
          start: Math.min(cur?.start ?? Infinity, e.startTime),
          dur: Math.max(cur?.dur ?? 0, e.duration),
        });
      }
      const repWorst = new Array(repStarts.length).fill(null);
      rec.interactionsBeforeFirstRep = 0;
      for (const { start, dur } of byInteraction.values()) {
        let bin = -1;
        for (let k = 0; k < repStarts.length; k++) if (start >= repStarts[k]) bin = k;
        if (bin < 0) { rec.interactionsBeforeFirstRep++; continue; }
        repWorst[bin] = Math.max(repWorst[bin] ?? 0, dur);
      }
      rec.firstInteraction = {
        worstMs: repWorst[0] === null || repWorst[0] === undefined ? null : Number(repWorst[0].toFixed(1)),
        effectObserved: j.effect ? repEffects[0] === null : null,
        consumedBeforeLoop: rec.firstInteractionConsumedBeforeLoop,
      };
      if (j.effect) {
        rec.repEffects = repEffects.map((why, k) => ({ rep: k, effect: why === null, why }));
        rec.repsWithEffect = repEffects.filter((w) => w === null).length;
        for (let k = 0; k < repWorst.length; k++) if (repEffects[k] !== null && repEffects[k] !== undefined) repWorst[k] = null;
      }
      const perRepWorst = repWorst.filter((v) => v !== null);
      /* WARM, reported apart from the first (acceptance report E3, 2026-09-23): rep 0 is the first
         interaction after load, every later rep a warm one, and the two have different costs. */
      const warmWorst = repWorst.slice(1).filter((v) => v !== null);
      rec.worstPerRepWarm = { p50: pct(warmWorst, 50), p95: pct(warmWorst, 95), max: warmWorst.length ? Number(Math.max(...warmWorst).toFixed(1)) : null, n: warmWorst.length };
      /* A verify that interacts runs here, after every timed rep, and a failure still withholds the
         verdict: a feature that does not work was not measured, however fast the keypresses were. */
      const postVerifyWhy =
        typeof j.verify === "function" && j.verifyAfter
          ? await j.verify(page).catch((e) => `verify threw: ${String(e).slice(0, 120)}`)
          : null;

      /* Presentation health at the end of the measured window (see the INSTRUMENT note). */
      rec.presentation = await page
        .evaluate(
          () =>
            new Promise((resolve) => {
              const base = { visibilityLog: window.__vis, visibilityNow: document.visibilityState, hasFocus: document.hasFocus() };
              const ts = [];
              const tick = (t) => {
                ts.push(t);
                if (ts.length < 21) requestAnimationFrame(tick);
                else {
                  const d = ts.slice(1).map((x, k) => x - ts[k]).sort((p, q) => p - q);
                  resolve({ ...base, rafIntervalMedianMs: Number(d[10].toFixed(1)), rafIntervalMaxMs: Number(d[d.length - 1].toFixed(1)) });
                }
              };
              requestAnimationFrame(tick);
              setTimeout(() => resolve({ ...base, rafIntervalMedianMs: null, note: "rAF did not deliver 20 frames in 5 s" }), 5000);
            }),
        )
        .catch((e) => ({ error: String(e).slice(0, 120) }));
      rec.measured = perRepWorst.length >= MIN_REPS_WITH_SAMPLE;
      /* The pre-check is not sufficient on its own: measured, a minimised window kept a 16.7 ms rAF for
         a moment and then stopped mid-journey. A window that is not presenting at the END of the
         measured loop invalidates the journey, with the cause named. */
      const pr = rec.presentation ?? {};
      if (HEADED && !(typeof pr.rafIntervalMedianMs === "number" && pr.rafIntervalMedianMs < PRESENTING_MAX_RAF_MS)) {
        rec.measured = false;
        rec.presentationFailure = true;
        rec.reason = `window stopped presenting during the measured loop (end-of-loop rAF median ${pr.rafIntervalMedianMs ?? "none in 5 s"} ms, bar < ${PRESENTING_MAX_RAF_MS} ms) — harness environment, not the app; ${perRepWorst.length} of ${ok} reps had entries`;
      }
      if (postVerifyWhy) {
        rec.measured = false;
        rec.reason = `verify (after the loop): ${postVerifyWhy}`;
      }
      rec.reps = ok;
      rec.samples = durations.length;
      rec.repsWithASample = perRepWorst.length;
      if (!rec.measured)
        rec.reason =
          rec.reason ??
          /* The effect is asked FIRST: a no-op act yields entries too (measured: a J4 whose submit was
             never clicked still produced 25 swap-click entries), so "no entries" would misname it. */
          (j.effect && rec.repsWithEffect < ok
            ? `only ${perRepWorst.length} of ${ok} repetitions both produced an Event Timing entry and had a verified effect — ${ok - rec.repsWithEffect} timed act(s) changed nothing (first: ${repEffects.find((w) => w !== null)}); E2 needs >= ${MIN_REPS_WITH_SAMPLE}, and a no-op is not a fast interaction`
            : perRepWorst.length === 0
              ? `no interaction entries observed (presentation: visibility=${rec.presentation?.visibilityNow}, visibility changes=${(rec.presentation?.visibilityLog?.length ?? 1) - 1}, focus=${rec.presentation?.hasFocus}, rAF median=${rec.presentation?.rafIntervalMedianMs}ms max=${rec.presentation?.rafIntervalMaxMs}ms)`
              : `only ${perRepWorst.length} of ${ok} repetitions produced an Event Timing entry; E2 needs >= ${MIN_REPS_WITH_SAMPLE} — a rep with no entry was not observed, it was not fast`);
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
      /* The one on-path rule (onPathLongTasks), shared with the first-selection trials. */
      rec.longTasksOnInteractionPath = onPathLongTasks(rec.longTaskList, interactions, attribute);
      rec.longTasksOver50OnPath = rec.longTasksOnInteractionPath.filter((x) => x.overlapsInteraction).length;
      rec.onPathByPhase = { "input-delay": 0, "in-handler": 0, "post-handler-pre-present": 0 };
      for (const x of rec.longTasksOnInteractionPath) if (x.phase) rec.onPathByPhase[x.phase] += 1;
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
      /* An on-path violation that WAS observed is E3 evidence even when too few reps were sampled for
         an E2 verdict; an absence of violations over an under-sampled journey is not a pass. */
      rec.e3Verdict = !e3Clean ? "E3-FAIL" : !rec.measured ? "NOT MEASURED" : "E3-PASS";
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
    await hostLoadMeter.close(ctx);
    results.push(rec);
    console.log(
      `${rec.verdict.padEnd(12)} ${(rec.e3Verdict ?? "-").padEnd(9)} ${rec.id.padEnd(22)} worstPerRep p95=${rec.worstPerRep?.p95 ?? "-"}ms p50=${rec.worstPerRep?.p50 ?? "-"}ms max=${rec.worstPerRep?.max ?? "-"}ms | pooled p95=${rec.inp?.p95 ?? "-"}ms  samples=${rec.samples ?? 0}  longTasks>50ms=${rec.longTasks?.over50ms ?? "-"} (max ${rec.longTasks?.maxMs ?? "-"}ms, ON-PATH ${rec.longTasksOver50OnPath ?? "-"}${rec.onPathByPhase ? ` = input-delay ${rec.onPathByPhase["input-delay"]} / in-handler ${rec.onPathByPhase["in-handler"]} / post-handler ${rec.onPathByPhase["post-handler-pre-present"]}` : ""})${rec.reason ? "  [" + rec.reason + "]" : ""}`,
    );
    if (rec.dilution) console.log(`             ${" ".repeat(22)} DILUTION: ${rec.dilution}`);
    if (rec.firstInteraction)
      console.log(
        `             ${" ".repeat(22)} first interaction after load: ${rec.firstInteraction.consumedBeforeLoop ? `NOT MEASURED HERE — ${rec.firstInteraction.consumedBeforeLoop}` : `rep 0 worst ${rec.firstInteraction.worstMs ?? "-"} ms`}; warm (reps 2..${rec.reps}) p95 ${rec.worstPerRepWarm?.p95 ?? "-"} ms max ${rec.worstPerRepWarm?.max ?? "-"} ms${rec.repEffects ? `; acts with a verified effect ${rec.repsWithEffect} of ${rec.reps}` : "; per-rep effect not checkable"}`,
      );
  }


  /* ── the first device selection after load, one fresh browser per trial (see FIRST_SELECTION) ── */
  if (selected(FIRST_SELECTION.id)) {
    const anchorOf = new Map(J2_HITS.map((h) => [h.id, h]));
    const trials = [];
    for (const target of FIRST_SELECTION.targets) {
      const anchor = anchorOf.get(target.id) ?? null;
      for (let k = 0; k < target.trials; k++) {
        const trial = { target: target.id, trial: k, observed: false, effect: false, why: null };
        trials.push(trial);
        if (anchor === null) {
          trial.why = `no canvas point was found that selects ${target.id}`;
          continue;
        }
        const fresh = await chromium.launch(LAUNCH);
        try {
          const ctx = await fresh.newContext(CONTEXT);
          await ctx.addInitScript(EXPOSE_SCENE);
          await ctx.addInitScript(INSTRUMENT);
          const page = await ctx.newPage();
          const nav = await gotoWithRetry(page, `${APP}${FIRST_SELECTION.url}`);
          if (!nav.ok) {
            trial.why = `transport: ${nav.error ?? nav.firstError}`;
            continue;
          }
          await FIRST_SELECTION.beforeClick(page);
          trial.presenting = await ensurePresenting(ctx, page).catch((e) => ({ ok: false, error: String(e).slice(0, 120) }));
          if (!trial.presenting.ok) {
            trial.why = "window not presenting — harness environment, not the app";
            continue;
          }
          await checkWindow(ctx, page);
          if (environment === null) environment = await page.evaluate(RENDERER_PROBE).catch(() => null);
          await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 300)))));
          const start = await page.evaluate(() => {
            window.__ev.length = 0;
            window.__long.length = 0;
            window.__loaf.length = 0;
            return performance.now();
          });
          await FIRST_SELECTION.act(page, anchor);
          await page.waitForTimeout(160);
          /* The effect is read AFTER the timing window opened and closed on its own: the aimed device
             must be the one the application says is selected. */
          trial.effect = await page
            .waitForFunction((id) => (location.search.match(/[?&]d=([^&]*)/) || [])[1] === id, target.id, { timeout: 3000 })
            .then(() => true)
            .catch(() => false);
          if (!trial.effect) trial.why = `the click aimed at ${target.id} selected ${await page.evaluate(() => (location.search.match(/[?&]d=([^&]*)/) || [])[1] ?? null).catch(() => "?") ?? "nothing"}`;
          await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 300)))));
          const data = await page.evaluate(() => ({ ev: window.__ev, long: window.__long, loaf: window.__loaf, loafSupported: window.__loafSupported === true }));
          const interactions = data.ev.filter((e) => e.interactionId > 0 && e.startTime >= start - 1);
          trial.observed = interactions.length > 0;
          trial.worstMs = interactions.length ? Number(Math.max(...interactions.map((e) => e.duration)).toFixed(1)) : null;
          trial.eventHistogram = interactions.reduce((h, e) => ((h[e.name] = (h[e.name] ?? 0) + 1), h), {});
          trial.onPath = onPathLongTasks(
            data.long.map((l) => ({ ...l, duration: Number(l.duration.toFixed(1)), startTime: Number(l.startTime.toFixed(1)) })),
            interactions,
          ).filter((x) => x.overlapsInteraction);
          const loaf = data.loafSupported ? worstLoafOnPath(data.loaf, interactions) : null;
          trial.worstLoafOnPathMs = data.loafSupported ? (loaf === null ? 0 : Number(loaf.duration.toFixed(1))) : null;
          trial.worstLoafScripts = loaf === null ? [] : loaf.scripts;
          trial.presentation = { rafMedianMs: trial.presenting.rafMedianMs ?? null };
        } catch (e) {
          trial.why = `trial threw: ${String(e).slice(0, 160)}`;
        } finally {
          await hostLoadMeter.close(fresh);
        }
        const onPathMs = (trial.onPath ?? []).map((x) => x.durationMs);
        console.log(
          `  first selection ${target.id} #${k + 1}: ${trial.observed ? `worst interaction ${trial.worstMs} ms, on-path tasks >50 ms ${onPathMs.length ? onPathMs.join("/") : "none"}, worst LoAF on the path ${trial.worstLoafOnPathMs ?? "n/a"} ms` : "NOT OBSERVED"}${trial.effect ? "" : ` [${trial.why}]`}`,
        );
      }
    }
    const planned = trials.length;
    const good = trials.filter((t) => t.observed && t.effect);
    const perTrialWorst = good.map((t) => t.worstMs);
    const onPath = good.flatMap((t) => t.onPath ?? []);
    const rec = {
      id: FIRST_SELECTION.id,
      firstSelection: true,
      reps: planned,
      repsWithASample: good.length,
      measured: good.length >= Math.min(MIN_REPS_WITH_SAMPLE, planned) && planned > 0,
      firstInteractionConsumedBeforeLoop: null,
      trials,
      perTarget: Object.fromEntries(
        FIRST_SELECTION.targets.map((t) => {
          const ts = good.filter((x) => x.target === t.id);
          const loafs = ts.map((x) => x.worstLoafOnPathMs).filter((x) => typeof x === "number");
          return [
            t.id,
            {
              planned: t.trials,
              measured: ts.length,
              trialsWithOnPathTaskOver50: ts.filter((x) => (x.onPath ?? []).length > 0).length,
              worstOnPathTaskMs: Math.max(0, ...ts.flatMap((x) => (x.onPath ?? []).map((o) => o.durationMs))),
              trialsWithLoafOnPathOver50: loafs.filter((x) => x > 50).length,
              worstLoafOnPathMs: loafs.length ? Math.max(...loafs) : null,
              worstInteractionMs: ts.length ? Math.max(...ts.map((x) => x.worstMs)) : null,
            },
          ];
        }),
      ),
      worstPerRep: { p50: pct(perTrialWorst, 50), p75: pct(perTrialWorst, 75), p95: pct(perTrialWorst, 95), max: perTrialWorst.length ? Math.max(...perTrialWorst) : null, n: perTrialWorst.length },
      longTasksOnInteractionPath: onPath,
      longTasksOver50OnPath: onPath.length,
      onPathByPhase: { "input-delay": 0, "in-handler": 0, "post-handler-pre-present": 0 },
      /* The slowest cadence any trial started from: the end-of-run gate reads it like a journey's. */
      presenting: { ok: true, rafMedianMs: Math.max(0, ...trials.map((t) => t.presenting?.rafMedianMs ?? 0)) || null },
      reason: null,
    };
    for (const x of onPath) if (x.phase) rec.onPathByPhase[x.phase] += 1;
    if (!rec.measured) rec.reason = `only ${good.length} of ${planned} fresh-browser trials both produced an Event Timing entry and selected the aimed device (need ${Math.min(MIN_REPS_WITH_SAMPLE, planned)})`;
    const within = (rec.worstPerRep.p95 ?? 1e9) <= 200;
    rec.verdict = !rec.measured ? "NOT MEASURED" : LANE === "evidence" ? (within ? "PASS" : "FAIL") : within ? "FLOOR-PASS" : "FLOOR-FAIL";
    rec.e3Verdict = onPath.length > 0 ? "E3-FAIL" : !rec.measured ? "NOT MEASURED" : "E3-PASS";
    rec.e3Why =
      onPath.length === 0
        ? `no task over 50 ms overlapped the first selection in ${good.length} fresh-browser trial(s)`
        : `${onPath.length} task(s) over 50 ms overlapped the first selection; worst ${Math.max(...onPath.map((x) => x.durationMs))} ms`;
    rec.longTasks = { maxMs: Math.max(0, ...onPath.map((x) => x.durationMs)) };
    results.push(rec);
    console.log(
      `${rec.verdict.padEnd(12)} ${rec.e3Verdict.padEnd(9)} ${rec.id.padEnd(22)} FIRST selection after load, one fresh browser per trial: worst interaction p95=${rec.worstPerRep.p95 ?? "-"}ms max=${rec.worstPerRep.max ?? "-"}ms over ${good.length}/${planned} trials${rec.reason ? "  [" + rec.reason + "]" : ""}`,
    );
    for (const [id, t] of Object.entries(rec.perTarget))
      console.log(
        `             ${" ".repeat(22)} ${id}: on-path task >50 ms in ${t.trialsWithOnPathTaskOver50} of ${t.measured} (worst ${t.worstOnPathTaskMs || "none"}); worst LoAF overlapping the interaction ${t.worstLoafOnPathMs ?? "n/a"} ms, over 50 ms in ${t.trialsWithLoafOnPathOver50} of ${t.measured}`,
      );
  }

  /* Every close in this file goes through the meter (host-env.mjs :: closeMeasured). */
  await hostLoadMeter.close(browser);

  const softwareRasteriser = /swiftshader|llvmpipe|software|microsoft basic render/i.test(
    environment?.renderer ?? "",
  );
  /* Acceptance evidence requires ALL of: the release bundle, a headed browser, and a renderer that is
     not a software rasteriser. Any one of them missing and these are floor numbers, whatever port
     they came from — which is why this is computed from what was OBSERVED rather than from the lane
     that was requested. */
  const hostLoad = hostLoadMeter.finish();
  const hostBusyGross = hostBusySince(hostCpuAtStart);
  /* The figure every gate below reads: busy core-time NOT spent by this harness. */
  const hostBusy = gatedBusy(hostLoad) ?? hostBusyGross;
  /* PRESENTATION CADENCE across the run: a window presenting below 50 Hz (a power governor, a remote
     session) is presenting, but it hid E3 violations on this host (the 30 Hz runs were E3-clean, the
     60 Hz runs were not), so such a run is neither acceptance evidence nor a quiet run. */
  const cadences = results.map((r) => r.presenting?.rafMedianMs).filter((x) => typeof x === "number");
  const slowestCadenceMs = cadences.length ? Math.max(...cadences) : null;
  const presentationBelowFullRate = HEADED && (slowestCadenceMs === null || slowestCadenceMs > FULL_RATE_MAX_RAF_MS);
  const hostPowerAtEnd = hostPower();
  const hostPowerThrottled = Boolean(hostPowerAtStart.throttled || hostPowerAtEnd.throttled);
  const hostQuiet = hostBusy !== null && hostBusy <= MAX_HOST_BUSY_FRACTION && !hostPowerThrottled && !presentationBelowFullRate;
  /* A headed window that is not inside the screen is not a measurement environment (see planWindow). */
  const windowFits = !HEADED || windowFitsOf(windowPlan, windowCheck);
  const acceptanceEvidence =
    LANE === "evidence" && server.devServer === false && !softwareRasteriser && hostQuiet && freshness.fresh && windowFits;

  const out = {
    measurementClass: "LABORATORY — scripted actor, single machine, no CPU/network emulation (host power and cadence recorded in hostPower / presentation). NOT field INP.",
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
          freshness.fresh ? null : `build freshness: ${freshness.why}.`,
          windowFits ? null : `the headed window is not inside the screen's work area (plan ${JSON.stringify(windowPlan)}, window ${JSON.stringify(windowCheck)}).`,
          hostPowerThrottled
            ? `host on battery or Energy Saver (start ${JSON.stringify(hostPowerAtStart)}, end ${JSON.stringify(hostPowerAtEnd)}); measured 2026-09-22: rAF at a 33.4 ms median and windows that stopped presenting under it.`
            : null,
          presentationBelowFullRate
            ? `the window presented below 50 Hz (slowest journey rAF median ${slowestCadenceMs ?? "unknown"} ms, bar <= ${FULL_RATE_MAX_RAF_MS} ms); a capped cadence changes the E3 picture, not only the numbers.`
            : null,
          hostBusy !== null && hostBusy <= MAX_HOST_BUSY_FRACTION
            ? null
            : `host was ${hostBusy === null ? "of unknown busyness" : Math.round(hostBusy * 100) + "% busy"} across the run excluding this harness (bar ${MAX_HOST_BUSY_FRACTION * 100}%); these numbers are about the machine as much as the build.`,
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
    hostPower: { atStart: hostPowerAtStart, atEnd: hostPowerAtEnd, throttled: hostPowerThrottled },
    window: { screen: screenProbe, plan: windowPlan, check: windowCheck, fits: windowFits },
    hostQuiescence: {
      busyFractionOfRun: hostBusy,
      basis: harnessBasis(hostLoad),
      harnessMethod: hostLoad.method,
      harnessCpuMs: hostLoad.harnessCpuMs,
      harnessJobError: hostLoad.jobError,
      grossBusyFraction: hostLoad.gross ?? hostBusyGross,
      harnessFraction: hostLoad.harness,
      idleBaselineBeforeLaunch: hostIdleBaseline,
      maxForAcceptance: MAX_HOST_BUSY_FRACTION,
      cores: cpus().length,
    },
    presentation: { slowestJourneyRafMedianMs: slowestCadenceMs, fullRateMaxRafMs: FULL_RATE_MAX_RAF_MS, belowFullRate: presentationBelowFullRate },
    buildFreshness: freshness,
    /* Where J2's anchors came from, and every reason discovery found fewer (see discoverJ2Anchors). */
    j2AnchorDiscovery: anchorDiscovery,
    minRepsWithSample: MIN_REPS_WITH_SAMPLE,
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
      /* PASS only when EVERY journey was measured clean: an under-sampled journey used to be
         silently absent from this roll-up, so "PASS" could mean "the journeys we saw were clean". */
      verdict: results.some((r) => r.e3Verdict === "E3-FAIL")
        ? "FAIL"
        : results.length > 0 && results.every((r) => r.e3Verdict === "E3-PASS")
          ? "PASS"
          : "NOT MEASURED",
      offenders: results
        .filter((r) => r.e3Verdict === "E3-FAIL")
        /* worstMs is the worst ON-PATH task. It used to be the journey's worst task of any kind, so
           the printed "J1 ... worst 8153ms" was an off-path stall reported as the E3 offender. */
        .map((r) => ({
          id: r.id,
          onPath: r.longTasksOver50OnPath,
          worstMs: Math.max(0, ...(r.longTasksOnInteractionPath ?? []).filter((x) => x.overlapsInteraction).map((x) => x.durationMs)),
          worstAnyTaskMs: r.longTasks?.maxMs ?? null,
          /* WHOSE (see INSTRUMENT): per invoker+source, the worst on-path script, and how many on-path
             frames had no script over 50 ms (style/layout/paint cost). */
          culprits: (() => {
            const onPath = (r.longTasksOnInteractionPath ?? []).filter((x) => x.overlapsInteraction && x.attribution?.available);
            const by = {};
            let renderOnly = 0;
            for (const x of onPath) {
              if (x.attribution.renderOnly) renderOnly += 1;
              for (const s of x.attribution.scripts ?? []) {
                const k = `${s.invoker} @ ${s.sourceURL || "?"}`;
                const cur = by[k] ?? { maxMs: 0, forcedLayoutMaxMs: 0, n: 0 };
                cur.maxMs = Math.max(cur.maxMs, s.durationMs);
                cur.forcedLayoutMaxMs = Math.max(cur.forcedLayoutMaxMs, s.forcedStyleAndLayoutMs);
                cur.n += 1;
                by[k] = cur;
              }
            }
            const scripts = Object.entries(by)
              .map(([k, v]) => ({ script: k, ...v }))
              .sort((a, b) => b.maxMs - a.maxMs)
              .slice(0, 4);
            return { attributed: onPath.length, renderOnlyFrames: renderOnly, scripts };
          })(),
          why: r.e3Why,
        })),
    },
  };
  /* E3 ACROSS RUNS (review finding, 2026-09-21). The per-run E3 verdict flapped for one build: J1
     went ON-PATH 0 -> 16 and J2 20 -> 0 between consecutive runs, so a single run's E3-PASS is a
     sample, not evidence. Every run appends its per-journey E3 verdict to a history keyed by the
     SERVED build (sha256 of the served index.html, which names the content-hashed chunks), and E3 is
     reported STABLE only when at least E3_MIN_RUNS runs of this exact build were all clean — the
     same repeated-run rule the E4 and E5 sweeps already apply. */
  const E3_MIN_RUNS = Number(process.env.ATLAS_E3_MIN_RUNS || 3);
  let servedBuild = null;
  try {
    const res = await fetch(APP.replace(/\/$/, "") + "/");
    servedBuild = res.ok ? createHash("sha256").update(await res.text()).digest("hex").slice(0, 16) : null;
  } catch {
    servedBuild = null;
  }
  /* HISTORY STORAGE (review finding, 2026-09-21). The history used to be ONE JSON file rewritten by
     read-modify-write, while several agents ran this harness at once: two runs that read it before
     either wrote lost one run, and nothing said so. Each run now writes its OWN record, atomically
     (write to a temp name, then rename), into `reports/inp-e3-history/`; the verdict reads the
     directory. The legacy single file is still read so older runs are not silently forgotten, but it
     is never written again. */
  const historyDir = resolve(HERE, "reports", "inp-e3-history");
  const legacyHistoryPath = resolve(HERE, "reports", "inp-e3-history.json");
  mkdirSync(historyDir, { recursive: true });
  if (servedBuild !== null) {
    const record = {
      build: servedBuild,
      at: new Date().toISOString(),
      lane: LANE,
      hostBusy,
      hostBusyBasis: hostLoad.excess !== null ? "excess" : "gross",
      hostPowerThrottled,
      presentationBelowFullRate,
      journeys: Object.fromEntries(results.map((r) => [r.id, { e3: r.e3Verdict, onPath: r.longTasksOver50OnPath ?? null, byPhase: r.onPathByPhase ?? null }])),
    };
    const name = `${record.at.replace(/[:.]/g, "-")}-${process.pid}.json`;
    const tmp = resolve(historyDir, `.${name}.tmp`);
    writeFileSync(tmp, JSON.stringify(record, null, 1));
    renameSync(tmp, resolve(historyDir, name));
  }
  let history = [];
  try {
    history = existsSync(legacyHistoryPath) ? JSON.parse(readFileSync(legacyHistoryPath, "utf8")) : [];
  } catch {
    history = [];
  }
  for (const f of readdirSync(historyDir)) {
    if (!f.endsWith(".json") || f.startsWith(".")) continue;
    try {
      history.push(JSON.parse(readFileSync(resolve(historyDir, f), "utf8")));
    } catch {
      /* A record another run is mid-way through cannot exist (rename is atomic); an unreadable one is
         skipped rather than allowed to abort the verdict. */
    }
  }
  /* QUIESCENCE (review finding, 2026-09-21). The across-runs verdict used to pool every run of the
     build regardless of how busy the host was, so a STABLE FAIL or STABLE PASS could be decided
     entirely by contended runs — or by another agent's contended run — and it printed with no
     qualifier. Only runs on a quiet host (hostBusy <= MAX_HOST_BUSY_FRACTION) count toward the
     verdict now. Busy runs are still counted and printed, separately, so a reader can see the
     laboratory picture; they just cannot decide the evidence. */
  const sameBuildAll = history.filter((h) => h.build === servedBuild && h.lane === LANE);
  /* A quiet run is also one on mains power, presenting at full rate. A record from before the power and
     cadence fields existed cannot claim either and does not count. */
  const isQuietRun = (h) =>
    typeof h.hostBusy === "number" &&
    h.hostBusy <= MAX_HOST_BUSY_FRACTION &&
    h.hostPowerThrottled === false &&
    h.presentationBelowFullRate === false;
  const sameBuild = sameBuildAll.filter(isQuietRun);
  const busyRuns = sameBuildAll.length - sameBuild.length;
  /* NOT MEASURED runs are counted apart, never as violations — see e3StableVerdict. */
  const verdictOf = (runs, id) => e3StableVerdict(runs, id, E3_MIN_RUNS);
  out.e3.acrossRuns = {
    build: servedBuild,
    minRuns: E3_MIN_RUNS,
    runs: sameBuild.length,
    busyRunsExcluded: busyRuns,
    maxHostBusyForEvidence: MAX_HOST_BUSY_FRACTION,
    perJourney: Object.fromEntries(results.map((r) => [r.id, verdictOf(sameBuild, r.id)])),
    /* Laboratory only: every run of this build, busy or quiet. Never the verdict. */
    allRunsLaboratory: Object.fromEntries(results.map((r) => [r.id, verdictOf(sameBuildAll, r.id)])),
  };
  out.e3.stableVerdict = Object.values(out.e3.acrossRuns.perJourney).some((j) => j.stable === "STABLE FAIL" || j.stable === "UNSTABLE")
    ? "FAIL"
    : Object.values(out.e3.acrossRuns.perJourney).every((j) => j.stable === "STABLE PASS")
      ? "PASS"
      : "INSUFFICIENT RUNS";
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
  for (const o of out.e3.offenders) {
    const c = o.culprits;
    if (!c || c.attributed === 0) {
      console.log(`  ${o.id}: no Long Animation Frame attribution available`);
      continue;
    }
    console.log(
      `  ${o.id}: ${c.attributed} attributed on-path frame(s), ${c.renderOnlyFrames} style/layout/paint-only; ` +
        (c.scripts.length
          ? c.scripts.map((s) => `${s.script} max ${s.maxMs}ms${s.forcedLayoutMaxMs ? ` (forced layout ${s.forcedLayoutMaxMs}ms)` : ""}`).join(", ")
          : "no script over 5 ms"),
    );
  }
  console.log(
    `E3 across runs of build ${out.e3.acrossRuns.build ?? "unknown"} (${out.e3.acrossRuns.runs} run(s), need ${E3_MIN_RUNS}): ${out.e3.stableVerdict} — ` +
      Object.entries(out.e3.acrossRuns.perJourney).map(([id, j]) => `${id} ${j.stable} (${j.clean}/${j.measured} measured runs clean${j.notMeasured ? `, ${j.notMeasured} NOT MEASURED` : ""})`).join("; ") +
      `\n  Counted: quiet-host runs only (host <= ${MAX_HOST_BUSY_FRACTION * 100}% busy); ${busyRuns} busy run(s) of this build excluded; a NOT MEASURED run is neither clean nor a violation.` +
      `\n  LABORATORY, NOT ACCEPTANCE EVIDENCE — all ${sameBuildAll.length} run(s) incl. busy: ` +
      Object.entries(out.e3.acrossRuns.allRunsLaboratory).map(([id, j]) => `${id} ${j.stable} (${j.clean}/${j.measured}${j.notMeasured ? `, ${j.notMeasured} NM` : ""})`).join("; ") +
      "\n  A single run's E3-PASS is a sample; only the across-runs verdict over quiet runs is E3 evidence.",
  );
  console.log(
    `lane=${LANE}  url=${APP}  devServer=${server.devServer}  headed=${HEADED}\n` +
      `renderer=${JSON.stringify(environment?.renderer ?? null)}  qualityTier=${environment?.quality ?? "unknown"}`,
  );
  console.log(
    acceptanceEvidence
      ? "ACCEPTANCE EVIDENCE: release build, hardware renderer, quiet host."
      : `NOT ACCEPTANCE EVIDENCE — do not quote these against the 200 ms bar. ${out.acceptanceEvidenceWhy}`,
  );
  console.log(`build: ${freshness.fresh ? "fresh" : "NOT FRESH"} — ${freshness.why}`);
  console.log(`host: ${hostBusy === null ? "unknown" : Math.round(hostBusy * 100) + "%"} busy across the run excluding this harness (gross ${hostLoad.gross === null ? "?" : Math.round(hostLoad.gross * 100) + "%"}, harness ${hostLoad.harness === null ? "?" : Math.round(hostLoad.harness * 100) + "%"} read from its ${hostLoad.method ?? "(unreadable)"}${hostLoad.jobError ? ` [job: ${hostLoad.jobError}]` : ""}, idle baseline before launch ${hostIdleBaseline === null ? "?" : Math.round(hostIdleBaseline * 100) + "%"}) over ${cpus().length} cores (acceptance bar ${MAX_HOST_BUSY_FRACTION * 100}%)`);
  console.log(`presentation: slowest journey rAF median ${slowestCadenceMs ?? "unknown"} ms${presentationBelowFullRate ? ` — BELOW 50 Hz: not acceptance evidence` : ""}`);
  console.log(`power: ${describePower(hostPowerAtStart)}${hostPowerThrottled ? " — THROTTLED: not acceptance evidence" : ""}`);
  console.log(`presentation cadence, median rAF ms at journey start/end: ${results.map((r) => `${r.id.split("-")[0]} ${r.presenting?.rafMedianMs ?? "-"}/${r.presentation?.rafIntervalMedianMs ?? "-"}`).join(", ")} (16.7 = 60 Hz, 33.3 = 30 Hz throttled)`);
  console.log(out.measurementClass);
  /* A journey we could not measure is not a pass, and a journey that violated E3 is not a pass
     either — the exit code carries BOTH axes now. It used to carry only the INP verdicts, which is
     what let a run print twelve on-path long tasks over 50 ms and exit 0. */
  process.exit(
    out.summary.fail + out.summary.notMeasured + out.summary.transportFailures + out.summary.e3Fail > 0 ? 1 : 0,
  );
}

if (IS_MAIN) await main();
