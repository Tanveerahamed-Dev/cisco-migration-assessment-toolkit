/**
 * measure-scale.mjs — LABORATORY wall-clock of the 3-D fabric's LAYOUT at fleet scale, in a real browser.
 *
 * WHAT IT GATES (owner decision, phase 3.5, 2026-09-29). The layout budgets for the SCALE requirement are
 * ≤ 300 ms at 300 devices and ≤ 2 s at 1 000, stated as LABORATORY figures. The unit suite cannot pin them:
 * vitest.config.ts forbids wall-clock assertions, so src/fabric3d/scale.test.ts pins the layout's COUNTED
 * work instead. This instrument measures the milliseconds, in the running application, and turns them into
 * an exit code — gated, like the E harnesses (measure-fps, measure-inp, audit-e5-*), on ./host-env.mjs's
 * answer to "was this machine in a state where a timing figure means anything?".
 *
 * WHAT IS TIMED, AND FROM WHERE. Nothing here re-implements or re-times the layout. The stage
 * (src/fabric3d/Fabric3D.tsx :: useSlicedLayout) leaves user-timing measures on the page's performance
 * timeline, taken by the browser between named marks (the stage reads no clock itself): ONE
 * LAYOUT_MEASURE ("atlas:layout") per layout run, from its creation to its last slice, whose `detail`
 * carries the run number, the fabric's device and link counts, the counted work and the slice count; and
 * one LAYOUT_SLICE_MEASURE ("atlas:layout-slice") per slice, naming its run. From them this harness
 * derives `computeMs` — the slice durations summed: main-thread time spent INSIDE the layout, its own
 * cost, the figure the budget is about; `elapsedMs` — the run measure's duration: compute plus every
 * yield, i.e. how long the reader waited for the fabric; and `maxSliceMs` — the longest the layout held
 * the main thread at once. A run whose slice measures do not number exactly its slice count is NOT
 * MEASURED. That contract is pinned in src/fabric3d/scale.test.ts, so a renamed measure fails the unit
 * suite rather than making this harness time nothing.
 *
 * THE FLEETS are review/synth-fleet.mjs's campus-shaped synthetic fleets (seed 1) — synthetic from the first
 * byte, engine-shaped — opened through the app's OWN "Open a snapshot file…" control (the header's snapshot
 * provenance popover), exactly as a reader opens a snapshot. Each run is a FRESH browser context, so no run
 * reuses a layout, a dataset kept in storage, or a warm cache the previous run left.
 *
 * THE VERDICT. Per size: every run must produce the measure for the fleet that was opened (its device and
 * link counts equal the app's own compiler's output for those bytes, compiled here in Node) with outcome
 * "done"; the MEDIAN `computeMs` across runs must be within that size's budget. A run whose layout FAILED
 * (the stage's error boundary replaced the fabric) is a FAIL — a failure is never a fast layout. A run that
 * produced no measure, or a measure for another fabric, is NOT MEASURED — never a pass.
 *
 * ACCEPTANCE EVIDENCE is a stronger claim than PASS and is refused unless the host was quiet (busy ≤ 25 %
 * excluding this harness), on AC power without Energy Saver, the headed window was inside the screen and
 * presenting at full rate, and the served build is this checkout's fresh dist/ (build-freshness.mjs). A PASS
 * on a busy host describes the machine as much as the build, and the report says so in a field.
 *
 * Usage (release build — the evidence lane):
 *     npm run build && npm run preview                     # serves dist/ on :4181
 *     node review/measure-scale.mjs [--runs 5] [--sizes 300,1000]
 *     ATLAS_URL=http://localhost:4180 node review/measure-scale.mjs   # a dev server: StrictMode, NOT evidence
 *     ATLAS_HEADLESS=1 node review/measure-scale.mjs                 # headless: NOT acceptance evidence
 *
 * Exit code: 0 = every size's median within its budget; 1 = a median over its budget, or a layout that
 * failed in the browser; 2 = NOT MEASURED (no measure, the wrong fabric measured, the app unreachable) or
 * refused arguments (refused before any browser launches). The receipt is written to
 * review/reports/scale.json (gitignored) and its sha256 printed on the last line.
 */
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { cpus } from "node:os";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { bindSourceWith, compileFabric } from "../tools/lib/compile-model.mjs";
import { validateSnapshot } from "../tools/lib/validate-snapshot.mjs";
import { checkBuildFreshness } from "./build-freshness.mjs";
import {
  FULL_RATE_MAX_RAF_MS,
  createLoadMeter,
  describePower,
  ensurePresenting,
  gatedBusy,
  harnessBasis,
  headedWindow,
  hostPower,
  idleBaseline,
  presentationState,
  rafCadence,
  windowBoundsCheck,
  windowFitsOf,
} from "./host-env.mjs";
import { synthFleetBytes } from "./synth-fleet.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, "..");

/** The owner's LABORATORY budgets, milliseconds of layout compute, by fleet size. */
const BUDGET_MS = { 300: 300, 1000: 2000 };
/** The measures the stage leaves: src/fabric3d/Fabric3D.tsx :: LAYOUT_MEASURE and LAYOUT_SLICE_MEASURE. */
const LAYOUT_MEASURE = "atlas:layout";
const LAYOUT_SLICE_MEASURE = "atlas:layout-slice";
/** Above this much host CPU across the run (excluding this harness), the figure is not acceptance evidence. */
const MAX_HOST_BUSY_FRACTION = 0.25;
/** How long one opened fleet may take to produce its measure before the run is NOT MEASURED. */
const RUN_TIMEOUT_MS = 180_000;

/* ── arguments, judged before anything launches ───────────────────────────── */

function parseArgs(argv) {
  const o = { runs: 5, sizes: Object.keys(BUDGET_MS).map(Number) };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const v = () => {
      const x = argv[i + 1];
      if (x === undefined) throw new Error(`measure-scale: ${a} needs a value`);
      i += 1;
      return x;
    };
    if (a === "--runs") o.runs = Number(v());
    else if (a === "--sizes") o.sizes = v().split(",").map((s) => Number(s.trim()));
    else throw new Error(`measure-scale: unknown argument ${a}`);
  }
  if (!(Number.isSafeInteger(o.runs) && o.runs >= 1)) throw new Error(`measure-scale: --runs must be a whole number of at least 1, got ${o.runs}`);
  if (o.sizes.length === 0 || o.sizes.some((n) => BUDGET_MS[n] === undefined)) {
    throw new Error(`measure-scale: --sizes must name sizes with a stated budget (${Object.keys(BUDGET_MS).join(", ")}), got ${o.sizes.join(",")}`);
  }
  return o;
}

let args;
try {
  args = parseArgs(process.argv.slice(2));
} catch (e) {
  console.error(String(e instanceof Error ? e.message : e));
  process.exit(2);
}

const APP = (process.env.ATLAS_URL || "http://localhost:4181").replace(/\/$/, "");
const PAGE_URL = `${APP}/?s=fabric`;
const HEADED = process.env.ATLAS_HEADLESS !== "1";

const median = (xs) => {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return Number((s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2).toFixed(2));
};

/* ── the fleets, and what the app's own compiler makes of them ─────────────── */

const hashes = {
  sha256Hex: (b) => createHash("sha256").update(b).digest("hex"),
  sha1Hex: (b) => createHash("sha1").update(b).digest("hex"),
};
const fleets = args.sizes.map((n) => {
  const bytes = synthFleetBytes({ devices: n, seed: 1 });
  const name = `synth-fleet-${n}-s1.snapshot.json`;
  const v = validateSnapshot(bytes);
  if (!v.ok || v.snap === null) {
    console.error(`measure-scale: the app's validator refused ${name}: ${JSON.stringify(v.errors).slice(0, 300)}`);
    process.exit(2);
  }
  const f = compileFabric(v.snap, bindSourceWith(bytes, { source: name, sourceOrigin: "external-file" }, hashes));
  return { n, name, bytes: Buffer.from(bytes), sha256: hashes.sha256Hex(bytes), devices: f.devices.length, links: f.links.length };
});

/* ── the host, before anything launches (host-env.mjs) ─────────────────────── */

const hostPowerAtStart = hostPower();
const hostIdleBaseline = await idleBaseline(3000);
const hostLoadMeter = createLoadMeter();
hostLoadMeter.start();

/* Long tasks, and the scene handle for the canvas size, from the first byte of every page. */
const INSTRUMENT = `
  window.__atlasLongTasks = [];
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) window.__atlasLongTasks.push([e.startTime, e.duration]);
    }).observe({ type: "longtask", buffered: true });
  } catch (e) { /* no longtask support: reported as null below */ }
`;

const headedPlan = HEADED ? await headedWindow(chromium, { width: 1920, height: 1080 }, hostLoadMeter) : null;
if (headedPlan) console.log(headedPlan.line);
const browser = await chromium.launch(HEADED ? { headless: false, args: headedPlan.args } : {});

const newRunPage = async () => {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, reducedMotion: "no-preference" });
  await ctx.addInitScript(INSTRUMENT);
  const page = await ctx.newPage();
  return { ctx, page };
};

/** The text of the error boundary that replaced a surface whose title starts with `prefix`, or null. */
const surfaceError = (page, prefix) =>
  page.evaluate(
    (p) => [...document.querySelectorAll(".surface-error")].find((e) => (e.querySelector(".surface-error__title")?.textContent ?? "").startsWith(p))?.textContent ?? null,
    prefix,
  );
/** Titles of every OTHER surface an error boundary replaced: reported, since a fleet can break a panel too. */
const otherSurfaceErrors = (page) =>
  page.evaluate(() =>
    [...document.querySelectorAll(".surface-error__title")].map((e) => e.textContent ?? "").filter((t) => !t.startsWith("The 3-D fabric")),
  );

/** Measures on the page so far, as plain data. */
const readMeasures = (page, name = LAYOUT_MEASURE) =>
  page.evaluate((n) => performance.getEntriesByName(n).map((e) => ({ start: e.startTime, duration: e.duration, detail: e.detail ?? null })), name);

/* The window check and the presentation check, once, on a first page. */
const first = await newRunPage();
const windowCheck = HEADED ? await windowBoundsCheck(first.ctx, first.page, headedPlan.plan) : { checked: false, skipped: "headless" };
const windowFits = !HEADED || windowFitsOf(headedPlan.plan, windowCheck);
let reachable = true;
let unreachableWhy = null;
try {
  await first.page.goto(PAGE_URL, { waitUntil: "load", timeout: 30_000 });
  await first.page.waitForSelector('.fabric3d[data-layout="ready"]', { timeout: 60_000 });
} catch (e) {
  reachable = false;
  unreachableWhy = String(e instanceof Error ? e.message : e).split("\n")[0].slice(0, 200);
}
const presentationBefore = !reachable
  ? { presenting: false, fullRate: false, rafMedianMs: null, skipped: "unreachable" }
  : HEADED
    ? await ensurePresenting(first.ctx, first.page)
    : { presenting: true, fullRate: true, rafMedianMs: null, skipped: "headless" };
await hostLoadMeter.close(first.ctx);

/* ── the runs ──────────────────────────────────────────────────────────────── */

const perSize = [];
let presentationAfter = presentationBefore;
for (const f of reachable ? fleets : []) {
  const runs = [];
  for (let r = 1; r <= args.runs; r += 1) {
    const { ctx, page } = await newRunPage();
    const run = { run: r, verdict: "NOT MEASURED", why: null, detail: null, longTasksDuringLayout: null, canvasCss: null, otherSurfaceErrors: [] };
    try {
      await page.goto(PAGE_URL, { waitUntil: "load", timeout: 30_000 });
      /* The reference sample first: the stage is mounted and laid out before the fleet is opened. */
      await page.waitForSelector('.fabric3d[data-layout="ready"]', { timeout: 60_000 });
      /* Opening a snapshot may replace the document (the dataset is kept, then the page is rebuilt from
         it: observed, the sample's measure is gone from the timeline afterwards), so the fleet's measure
         is recognised by WHAT it measured — the compiled device and link counts — never by a count of
         entries that a new document resets. */
      await page.locator(".hdr-snap").first().click();
      await page.locator('input[type="file"]').first().setInputFiles({ name: f.name, mimeType: "application/json", buffer: f.bytes });
      /* A new measure, the stage's error boundary, or the open control's refusal — whichever comes first. */
      await page.waitForFunction(
        ([name, devices, links]) =>
          performance.getEntriesByName(name).some((e) => e.detail && e.detail.devices === devices && e.detail.links === links) ||
          [...document.querySelectorAll(".surface-error__title")].some((e) => (e.textContent ?? "").startsWith("The 3-D fabric")) ||
          document.querySelector("[data-open-refused]") !== null,
        [LAYOUT_MEASURE, f.devices, f.links],
        { timeout: RUN_TIMEOUT_MS, polling: 100 },
      );
      const refused = await page.evaluate(() => document.querySelector("[data-open-refused]")?.textContent ?? null);
      const failed = await surfaceError(page, "The 3-D fabric");
      run.otherSurfaceErrors = await otherSurfaceErrors(page);
      const fresh = await readMeasures(page);
      const m = fresh.find((x) => x.detail && x.detail.devices === f.devices && x.detail.links === f.links) ?? null;
      if (refused !== null) run.why = `the app refused the snapshot: ${refused.slice(0, 200)}`;
      else if (m === null && failed !== null) {
        run.verdict = "FAIL";
        run.why = `the fabric's error boundary replaced the stage: ${failed.slice(0, 240)}`;
      } else if (m === null) {
        run.why = `no ${LAYOUT_MEASURE} measure for ${f.devices} devices / ${f.links} links; saw ${JSON.stringify(fresh.map((x) => x.detail && [x.detail.devices, x.detail.links]))}`;
      } else {
        const sliceMs = (await readMeasures(page, LAYOUT_SLICE_MEASURE)).filter((x) => x.detail && x.detail.run === m.detail.run).map((x) => x.duration);
        run.detail = {
          ...m.detail,
          computeMs: Number(sliceMs.reduce((a, b) => a + b, 0).toFixed(2)),
          maxSliceMs: sliceMs.length ? Number(Math.max(...sliceMs).toFixed(2)) : null,
          elapsedMs: Number(m.duration.toFixed(2)),
          sliceMeasures: sliceMs.length,
        };
        const lo = m.start;
        const hi = m.start + m.duration;
        const tasks = await page.evaluate(() => window.__atlasLongTasks ?? null);
        run.longTasksDuringLayout = tasks === null ? null : tasks.filter(([s, d]) => s < hi && s + d > lo).map(([s, d]) => ({ at: Number((s - lo).toFixed(1)), ms: Number(d.toFixed(1)) }));
        run.canvasCss = await page.evaluate(() => {
          const c = document.querySelector(".fabric3d canvas");
          return c ? { w: c.clientWidth, h: c.clientHeight } : null;
        });
        if (sliceMs.length !== m.detail.slices) {
          run.detail = null;
          run.why = `the run reported ${m.detail.slices} slices but ${sliceMs.length} slice measures were found; its compute time cannot be summed`;
        } else if (m.detail.outcome !== "done") {
          run.verdict = "FAIL";
          run.why = `the layout failed in the browser after ${m.detail.work} units (${m.detail.slices} slices)`;
        } else {
          run.verdict = "MEASURED";
          run.why = `computeMs ${run.detail.computeMs}, elapsedMs ${run.detail.elapsedMs}, ${m.detail.slices} slices, longest slice ${run.detail.maxSliceMs} ms`;
        }
      }
    } catch (e) {
      run.why = `the run did not complete: ${String(e instanceof Error ? e.message : e).split("\n")[0].slice(0, 200)}`;
    }
    if (r === args.runs && f === fleets[fleets.length - 1] && HEADED) {
      presentationAfter = presentationState(await rafCadence(page, 5000).catch(() => null));
    }
    /* Through the meter: see closeMeasured in host-env.mjs. */
    await hostLoadMeter.close(ctx);
    console.log(`  ${f.n} devices, run ${r}/${args.runs}: ${run.verdict} — ${run.why}`);
    runs.push(run);
  }
  const measured = runs.filter((x) => x.verdict === "MEASURED");
  const failedRuns = runs.filter((x) => x.verdict === "FAIL");
  const computeMedian = median(measured.map((x) => x.detail.computeMs));
  const verdict =
    failedRuns.length > 0
      ? "FAIL"
      : measured.length < runs.length
        ? "NOT MEASURED"
        : computeMedian !== null && computeMedian <= BUDGET_MS[f.n]
          ? "PASS"
          : "FAIL";
  perSize.push({
    devices: f.n,
    fleet: { name: f.name, sha256: f.sha256, compiledDevices: f.devices, compiledLinks: f.links },
    budgetMs: BUDGET_MS[f.n],
    verdict,
    runs: runs.length,
    measuredRuns: measured.length,
    computeMsMedian: computeMedian,
    computeMs: measured.map((x) => x.detail.computeMs),
    elapsedMsMedian: median(measured.map((x) => x.detail.elapsedMs)),
    maxSliceMs: measured.length ? Math.max(...measured.map((x) => x.detail.maxSliceMs)) : null,
    slices: measured.length ? measured[0].detail.slices : null,
    work: measured.length ? measured[0].detail.work : null,
    longestLongTaskDuringLayoutMs: measured.some((x) => x.longTasksDuringLayout === null)
      ? null
      : Math.max(0, ...measured.flatMap((x) => x.longTasksDuringLayout.map((t) => t.ms))),
    canvasCss: measured.length ? measured[0].canvasCss : null,
    perRun: runs,
  });
}
await hostLoadMeter.close(browser);

/* ── the host, after ───────────────────────────────────────────────────────── */

const hostLoad = hostLoadMeter.finish();
const hostBusy = gatedBusy(hostLoad);
const hostPowerAtEnd = hostPower();
const hostPowerThrottled = Boolean(hostPowerAtStart.throttled || hostPowerAtEnd.throttled);
const presentationFault = !HEADED
  ? null
  : !presentationBefore.presenting
    ? `the window was not presenting before measurement (rAF median ${presentationBefore.rafMedianMs ?? "none"} ms)`
    : !presentationAfter.presenting
      ? `the window stopped presenting during the run (rAF median ${presentationAfter.rafMedianMs ?? "none"} ms)`
      : !presentationBefore.fullRate || !presentationAfter.fullRate
        ? `the display presented below 50 Hz (rAF median ${presentationBefore.rafMedianMs}/${presentationAfter.rafMedianMs} ms; bar <= ${FULL_RATE_MAX_RAF_MS} ms)`
        : null;
const freshness = await checkBuildFreshness(APP);

const verdict = !reachable
  ? "NOT MEASURED"
  : perSize.some((s) => s.verdict === "FAIL")
    ? "FAIL"
    : perSize.some((s) => s.verdict === "NOT MEASURED")
      ? "NOT MEASURED"
      : "PASS";
/* Acceptance evidence: a PASS taken on a quiet, unthrottled, presenting host, inside the screen, on this
   checkout's fresh release build — never on a dev server (StrictMode lays out twice there). */
const acceptanceEvidence =
  verdict === "PASS" && hostBusy !== null && hostBusy <= MAX_HOST_BUSY_FRACTION && !hostPowerThrottled && presentationFault === null && freshness.fresh && !freshness.devServer && HEADED && windowFits;

const report = {
  criterion: "SCALE / R2 — the 3-D fabric's layout at 300 devices within 300 ms and at 1 000 devices within 2 s (median computeMs).",
  measurementClass:
    "LABORATORY — scripted actor, single machine, real Chromium, the app's own open-a-snapshot path; host power, presentation and net host load recorded. Not a field figure.",
  verdict,
  acceptanceEvidence,
  why: !reachable
    ? `the app at ${PAGE_URL} could not be loaded to a laid-out fabric: ${unreachableWhy}`
    : perSize.map((s) => `${s.devices}: ${s.verdict} — median computeMs ${s.computeMsMedian ?? "-"} against ${s.budgetMs} (elapsed median ${s.elapsedMsMedian ?? "-"} ms, longest slice ${s.maxSliceMs ?? "-"} ms, ${s.measuredRuns}/${s.runs} runs measured)`).join("; "),
  sizes: perSize,
  buildFreshness: freshness,
  window: { screen: headedPlan?.screen ?? null, plan: headedPlan?.plan ?? null, check: windowCheck, fits: windowFits },
  hostPower: { atStart: hostPowerAtStart, atEnd: hostPowerAtEnd, throttled: hostPowerThrottled },
  presentation: { before: presentationBefore, after: presentationAfter, fault: presentationFault },
  hostQuiescence: {
    measured: hostBusy !== null,
    busyFractionOfRun: hostBusy,
    basis: harnessBasis(hostLoad),
    harnessMethod: hostLoad.method,
    harnessCpuMs: hostLoad.harnessCpuMs,
    harnessJobError: hostLoad.jobError,
    grossBusyFraction: hostLoad.gross,
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
  environment: { url: PAGE_URL, headed: HEADED, runsPerSize: args.runs, node: process.version, platform: process.platform, capturedAt: new Date().toISOString() },
  pins: "src/fabric3d/scale.test.ts pins the LAYOUT_MEASURE contract this reads, and the layout's counted work",
};

mkdirSync(resolve(HERE, "reports"), { recursive: true });
const receiptPath = resolve(HERE, "reports", "scale.json");
const receipt = JSON.stringify(report, null, 1);
writeFileSync(receiptPath, receipt);

console.log(`${verdict}  SCALE  ${report.why}`);
console.log(
  `  host: ${hostBusy === null ? "load NOT MEASURED" : `${Math.round(hostBusy * 100)}% busy excluding this harness`} ` +
    `(gross ${hostLoad.gross === null ? "?" : `${Math.round(hostLoad.gross * 100)}%`}, idle baseline ${hostIdleBaseline === null ? "?" : `${Math.round(hostIdleBaseline * 100)}%`}); ` +
    `power ${describePower(hostPowerAtStart)}${hostPowerThrottled ? " THROTTLED" : ""}; presentation ${presentationFault ?? "ok"}; ` +
    `build ${freshness.fresh ? (freshness.devServer ? "dev server" : "fresh") : `NOT FRESH (${freshness.why})`}; ` +
    `window ${windowFits ? "inside the screen" : "NOT inside the screen"} -> acceptanceEvidence=${acceptanceEvidence}`,
);
console.log(report.measurementClass);
console.log(`receipt: ${relative(PKG, receiptPath).replace(/\\/g, "/")} sha256 ${hashes.sha256Hex(receipt)}`);
process.exit(verdict === "PASS" ? 0 : verdict === "FAIL" ? 1 : 2);
