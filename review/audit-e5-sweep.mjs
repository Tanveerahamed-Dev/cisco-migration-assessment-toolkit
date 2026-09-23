/**
 * audit-e5-sweep.mjs — E5's actual evidence column: "a list of anything over 200 ms".
 *
 * The five declared journeys are not that list. E5 asks about the whole product, so this sweep
 * drives the interactions the journeys do NOT cover and reports every long animation frame, using
 * the Long Animation Frames API so each one is attributed to the script that caused it.
 *
 * WHAT "NOT COVERED" MEANS (decided 2026-09-23, docs/acceptance.md "E3's scope"). A declared journey
 * is exactly what `review/measure-inp.mjs` times — J1 includes the first finding selection after
 * load, J4 is swap + submit, J5 is the palette's open and close. An action here therefore never
 * times an input a journey's act performs: where it needs that input to reach its own state (the
 * palette open before running a command, a grid click before arrowing through it) the input is its
 * `setup`, which runs BEFORE the measured window opens. `src/core/journey-scope.test.ts` records the
 * inputs of both harnesses' acts and fails if they share one — derived from the two files, not from
 * a list of names — and requires the "outside the journeys" enumeration in docs/acceptance.md to be
 * exactly this file's action names. Until 2026-09-23 this sweep re-timed J4's swap + submit and J1's
 * first selection, and acceptance.md listed them as outside the journeys while also saying the
 * first selection was inside J1.
 *
 * Each action is run from a settled state, with the LoAF buffer cleared immediately before, so a
 * frame attributed to an action really did happen during it.
 *
 * It is REPLICATED and it has a VERDICT AND AN EXIT CODE — see REPLICATION and THE GATE below. It
 * had neither: it ran each action once and exited 0 while printing its own summary line saying
 * seven of sixteen actions had crossed the bar.
 *
 *     node review/audit-e5-sweep.mjs            # 3 repetitions
 *     ATLAS_SWEEP_REPS=5 node review/audit-e5-sweep.mjs
 *
 * Imported (by src/core/journey-scope.test.ts), it is a module of action definitions and pure
 * helpers; everything that launches a browser, reads the host or writes a report runs in `main`,
 * and `main` runs only when this file is EXECUTED.
 */
import { writeFileSync } from "node:fs";
import os from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { checkBuildFreshness } from "./build-freshness.mjs";
import { VISIBLE_AFFORDANCE_JS, affordancePaintedAt } from "./working-affordance.mjs";
import { createLoadMeter, describePower, ensurePresenting, gatedBusy, headedWindow, hostPower, idleBaseline, presentationState, rafCadence, windowBoundsCheck, windowFitsOf } from "./host-env.mjs";

const IS_MAIN = typeof process.argv[1] === "string" && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

export const BAR_MS = 200;
/** Where every repetition starts. */
export const SWEEP_START = "/?s=findings";

const INIT = `
  window.__atlasExposeScene = true;
  window.__loaf = [];
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__loaf.push({
      startTime: +e.startTime.toFixed(1), duration: +e.duration.toFixed(1),
      blockingDuration: +(e.blockingDuration ?? 0).toFixed(1),
      /* Every reported script's time, not only the top two below: what classifies the frame. */
      scriptMs: +(e.scripts||[]).reduce((a, s) => a + s.duration, 0).toFixed(1),
      renderMs: e.renderStart > 0 ? +(e.startTime + e.duration - e.renderStart).toFixed(1) : 0,
      scripts: (e.scripts||[]).map((s)=>({dur:+s.duration.toFixed(1), invoker:s.invoker, src:(s.sourceURL||'').slice(-34)})).sort((a,b)=>b.dur-a.dur).slice(0,2),
    }); }).observe({ type: 'long-animation-frame', buffered: true });
  } catch (e) { window.__loafError = String(e); }
  /* AFFORDANCE TIMELINE (repair 2026-09-21). E5 is two halves — "budgeted separately" AND
     "communicated, not hidden behind a frozen UI" — and this sweep only ever tested the first.
     So the page records when a WORKING affordance (the same selector audit-e5-coldload.mjs uses)
     appeared and disappeared, whether it offered a Cancel/Stop control, and a stamp for every
     animation frame, so an over-bar frame can be judged: was an affordance on screen AND painted
     (at least one frame produced after it appeared) before the long frame began? */
  window.__raf = [];
  /* Scoped to affordances that NAME the slow work — see working-affordance.mjs. */
  ${VISIBLE_AFFORDANCE_JS}
  /* The on-screen timeline itself is kept by the shared predicate, stamped with the browser's own
     rendering-step times (window.__affTimeline) — see working-affordance.mjs. */
  const rafLoop = (t) => { window.__raf.push(+t.toFixed(1)); if (window.__raf.length > 4000) window.__raf.splice(0, 2000); requestAnimationFrame(rafLoop); };
  requestAnimationFrame(rafLoop);
`;

/* ── WHICH LONG FRAMES ARE THE APPLICATION'S ──────────────────────────────────────────────────────
 *
 * HARNESS FIX (acceptance report, E harness item 12d, 2026-09-23). The sweep counted every Long
 * Animation Frame as the application's, and its ~1,000 ms rows with 0 ms blocking are the signature
 * of a window that is NOT PRESENTING: the frame stays open because nothing is being drawn to screen,
 * not because the main thread is working. measure-inp.mjs already separates that (a journey on a
 * window that is not presenting is NOT MEASURED, harness environment); this sweep did not, so a
 * throttled or occluded window read as an over-bar application frame.
 *
 * A frame is the MAIN THREAD's when it carried blocking time (a task over 50 ms, render included) or
 * when reported scripts account for at least half of it. Otherwise — no blocking and most of the
 * frame spent in no reported script — it has the window-not-presenting signature. Such a frame over
 * the bar is neither a pass nor a fail: the repetition it happened in is NOT MEASURED, with the
 * frame named. Limit, stated: LoAF reports only scripts over 5 ms, so a frame made of many
 * sub-5 ms scripts with no task over 50 ms would also read as not presenting — and would therefore
 * make the repetition NOT MEASURED, never a pass.
 */
/** @param {{ duration: number, blockingDuration: number, scriptMs?: number }} f */
export const frameKind = (f) =>
  f.blockingDuration > 0 || (f.scriptMs ?? 0) >= f.duration / 2 ? "main-thread" : "not-presenting";

/** Split one action's frames into the application's and the not-presenting ones, against the bar. */
export function judgeFrames(loaf, bar = BAR_MS) {
  const main = loaf.filter((e) => frameKind(e) === "main-thread");
  const stalls = loaf.filter((e) => frameKind(e) === "not-presenting");
  const worstOf = (xs) => (xs.length ? xs.reduce((a, b) => (b.duration > a.duration ? b : a)) : null);
  const worstMain = worstOf(main);
  const worstStall = worstOf(stalls);
  return {
    main,
    stalls,
    worstMain,
    worstStall,
    mainOverBar: main.filter((e) => e.duration > bar),
    stallsOverBar: stalls.filter((e) => e.duration > bar),
    /** Why this repetition is not a measurement of the application, or null. */
    notPresenting:
      worstStall !== null && worstStall.duration > bar
        ? `window-not-presenting signature: a ${worstStall.duration} ms frame with ${worstStall.blockingDuration} ms blocking and ${worstStall.scriptMs ?? 0} ms of reported script — harness environment, not the app`
        : null,
  };
}

/* ── the actions, each with the effect that proves it ran ─────────────────────────────────────────
 *
 * EVERY ACTION PROVES IT HAPPENED (review finding, 2026-09-21). An actuation that throws was already
 * NOT MEASURED, but one that ran and did NOTHING was indistinguishable from a fast one: the palette
 * action typed "blast", for which no command exists, pressed Enter on nothing and reported 0 ms in
 * every repetition; `focusDevice` was called through optional chaining and would have no-op'd
 * silently without the scene handle. So each action carries an effect check, as the measure-inp
 * journeys do: `before` snapshots whatever the effect is judged against (optional), `verify` returns
 * null when the effect is on the page and a reason when it is not, and a missing effect is recorded
 * as an error — NOT MEASURED — never as a 0 ms pass.
 *
 * `setup` (optional) runs BEFORE the LoAF buffer is cleared: the inputs that reach the action's
 * state and that a declared journey already times. Every function takes (page, env), env = { app }. */
const param = (page, k) => page.evaluate((key) => new URL(location.href).searchParams.get(key), k);
const themeChecked = (page, i) =>
  page.evaluate((n) => document.querySelectorAll(".thm__opt")[n]?.getAttribute("aria-checked") === "true", i);
/** The focused grid row's logical index, and the grid's total — both from the grid's own ARIA. */
const focusedRow = (page) =>
  page.evaluate(() => {
    const row = document.activeElement?.closest?.('[role="row"]');
    const grid = document.activeElement?.closest?.('[role="grid"], [role="treegrid"]');
    return {
      index: row ? Number(row.getAttribute("aria-rowindex")) : null,
      count: grid ? Number(grid.getAttribute("aria-rowcount")) : null,
    };
  });
const dataRows = (page) => page.evaluate(() => document.querySelectorAll(".ag__row--data").length);
const legendOpen = (page) => page.evaluate(() => document.querySelector('[data-testid="fabric3d-legend"]') !== null);
const paletteOpen = (page) =>
  page.evaluate(() => document.querySelector(".palette__input") !== null && document.activeElement?.classList?.contains("palette__input") === true);
/* The scene handle is REQUIRED, never optional-chained: without it the camera actions do nothing
   and would otherwise be timed as 0 ms. `converged` false right after the call is the handle's own
   statement that the camera started moving. */
const sceneMoves = (page, call) =>
  page.evaluate((what) => {
    const s = window.__atlasScene;
    if (!s || typeof s.stats !== "function") return "no scene handle (window.__atlasScene) — the action cannot run";
    if (what.kind === "focus") {
      const id = document.querySelector(".fabric3d-label[data-device]")?.dataset.device ?? null;
      if (id === null) return "no device label on the fabric to focus";
      if (typeof s.focusDevice !== "function") return "scene handle has no focusDevice";
      s.focusDevice(id);
    } else {
      if (typeof s.resetCamera !== "function") return "scene handle has no resetCamera";
      s.resetCamera();
    }
    return s.stats().converged === false ? null : "the scene stayed converged — the camera did not move";
  }, call);
/** Open the palette OUTSIDE the measured window (J5 times the open) and prove it opened. */
const openPaletteUntimed = async (page) => {
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(250);
  if (!(await paletteOpen(page))) throw new Error("setup: Ctrl+K did not open the command palette");
};

/** @type {{ name: string, setup?: Function, fn: Function, verify: Function, before: Function }[]} */
export const ACTIONS = [];
const ACT = (name, { setup, fn, verify, before = async () => null }) => {
  if (typeof verify !== "function") throw new Error(`sweep action "${name}" has no effect check`);
  ACTIONS.push({ name, setup, fn, verify, before });
};

/* AUDIT FIX: the theme control is a radio group of `.thm__opt` buttons (src/app/ThemeToggle.tsx),
   not one button inside an element whose class contains "theme". The original selector matched
   nothing, the action never happened, and it was reported as 0 ms — a measurement of nothing. */
ACT("theme toggle (-> second option)", {
  fn: async (page) => page.locator(".thm__opt").nth(1).click({ timeout: 4000 }),
  verify: async (page) => ((await themeChecked(page, 1)) ? null : "second theme option is not checked"),
});
ACT("theme toggle (-> first option)", {
  fn: async (page) => page.locator(".thm__opt").nth(0).click({ timeout: 4000 }),
  verify: async (page) => ((await themeChecked(page, 0)) ? null : "first theme option is not checked"),
});
/* The first finding selection after page load used to be timed here. It is J1's rep 0
   (measure-inp.mjs spends no selection before J1's loop), so it is a journey act and not this
   sweep's to time. */
/* AUDIT FIX: there is no "Inspect" button. The inspector is opened by the `view.inspector`
   command ("Toggle the inspector", src/app/commands.ts), so the palette is the way in. Opening the
   palette and typing the command's name are setup; the measured act is Enter RUNNING the command,
   which is where the 62-144 ms `BODY.onkeydown` frames were attributed. */
ACT("open the Inspector (raw source record): run the command", {
  setup: async (page) => {
    await openPaletteUntimed(page);
    await page.keyboard.type("inspector");
    /* The timed Enter runs the ACTIVE row: it must be the inspector command before the window opens. */
    const ready = await page
      .waitForFunction(() => /inspector/i.test(document.querySelector('.palette [role="option"][aria-selected="true"]')?.textContent ?? ""), null, { timeout: 4000 })
      .then(() => true)
      .catch(() => false);
    if (!ready) throw new Error("setup: typing 'inspector' did not make the inspector command the active row");
  },
  fn: async (page) => page.keyboard.press("Enter"),
  verify: async (page, before) => {
    const now = await page.evaluate(() => document.querySelector(".app__stage--with-inspector") !== null);
    return now !== before ? null : "the inspector did not toggle";
  },
  before: async (page) => page.evaluate(() => document.querySelector(".app__stage--with-inspector") !== null),
});
ACT("surface switch findings -> fabric", {
  fn: async (page) => {
    await page.keyboard.press("g");
    await page.keyboard.press("f");
  },
  verify: async (page) => {
    const s = await param(page, "s");
    return s === null || s === "fabric" ? null : `surface is still ${s}`;
  },
});
/* The click that puts focus in the grid SELECTS a finding — J1's act — so it is setup. */
ACT("keyboard grid: 40 x ArrowDown", {
  setup: async (page) => {
    await page.locator(".ag__row--data").first().locator('[role="gridcell"]').first().click();
    await page.waitForTimeout(400);
  },
  fn: async (page) => {
    for (let i = 0; i < 40; i++) await page.keyboard.press("ArrowDown");
  },
  verify: async (page) => {
    const r = await focusedRow(page);
    return r.index !== null && r.index > 40 ? null : `focus is on row ${r.index}, not 40 rows down`;
  },
});
ACT("keyboard grid: Ctrl+End (jump to last row)", {
  fn: async (page) => page.keyboard.press("Control+End"),
  verify: async (page) => {
    const r = await focusedRow(page);
    return r.index !== null && r.index === r.count ? null : `focus is on row ${r.index} of ${r.count}`;
  },
});
/* Typing into the query bar is J3 / J3b's act, so the filter this action clears is typed in setup.
   What is measured is clearing it in ONE edit (Playwright `fill("")`: select-all + delete), which
   no journey performs — J3b erases by Backspace, one character at a time. */
ACT("query: clear a 17-character filter in one edit (back to 146 rows)", {
  setup: async (page) => {
    const q = page.locator(".hdr-query__input").first();
    await q.click();
    for (const ch of "severity:Critical") await q.press(ch === ":" ? "Shift+Semicolon" : ch);
    const v = await q.inputValue();
    if (v !== "severity:Critical") throw new Error(`setup: the query reads ${JSON.stringify(v)}`);
    /* The filter is debounced and chunked: wait for it to LAND, not for a guessed interval — on a
       loaded host a 600 ms sleep let `before` read the unfiltered grid, and the filter's own commit
       then fell inside the measured window (headless smoke, 2026-09-23). */
    const landed = await page
      .waitForFunction(() => document.querySelectorAll(".ag__row--data").length < 100, null, { timeout: 8000 })
      .then(() => true)
      .catch(() => false);
    if (!landed) throw new Error("setup: the typed filter never narrowed the grid");
    await page.waitForTimeout(300);
  },
  fn: async (page) => page.locator(".hdr-query__input").first().fill(""),
  verify: async (page, before) => {
    const n = await dataRows(page);
    return n > before ? null : `the grid did not restore (${before} -> ${n} rows)`;
  },
  before: dataRows,
});
/* AUDIT FIX: this typed "blast" — no palette command matches it, so Enter ran nothing and the
   action reported 0 ms in every repetition. It now runs a command that exists and whose effect is
   on the page: "Toggle the fabric legend" (commands.ts view.legend). The palette's open is J5's act,
   so it is setup; typing the command's name and running it are measured. */
ACT("command palette: type and run 'legend'", {
  setup: openPaletteUntimed,
  fn: async (page) => {
    await page.keyboard.type("legend");
    /* Enter runs the ACTIVE row, so wait until the typed term has produced it rather than for a
       guessed 250 ms — on a loaded host Enter otherwise ran a stale row (headless smoke, 2026-09-23). */
    await page
      .waitForFunction(() => /legend/i.test(document.querySelector('.palette [role="option"][aria-selected="true"]')?.textContent ?? ""), null, { timeout: 4000 })
      .catch(() => null);
    await page.keyboard.press("Enter");
  },
  verify: async (page, before) => ((await legendOpen(page)) !== before ? null : "the legend did not toggle"),
  before: legendOpen,
});
ACT("fabric: focusDevice via scene handle", {
  fn: async (page) => {
    const miss = await sceneMoves(page, { kind: "focus" });
    if (miss) throw new Error(miss);
  },
  verify: async () => null /* proven inside the actuation: it throws unless the camera started moving */,
});
ACT("fabric: resetCamera", {
  fn: async (page) => {
    const miss = await sceneMoves(page, { kind: "reset" });
    if (miss) throw new Error(miss);
  },
  verify: async () => null /* as above */,
});
ACT("path trace: seed a flow by navigation", {
  fn: async (page, env) => {
    await page.goto(`${env.app}/?s=path&flow=10.0.10.50>10.0.20.10>tcp>443`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('#rail-path form.pt-form button[type="submit"]', { timeout: 15000 });
  },
  verify: async (page) => ((await page.locator("#rail-path .pt-result__title").count()) > 0 ? null : "no trace result rendered"),
});
/* "path trace: swap + submit" used to follow here, with the same selectors as measure-inp's J4 act.
   It is J4. It was also the one action the 2026-09-23 run could not actuate, which made the whole
   sweep NOT MEASURED. */
ACT("viewport resize 1920 -> 1280 (drawer rung)", {
  fn: async (page) => page.setViewportSize({ width: 1280, height: 900 }),
  verify: async (page) => ((await page.evaluate(() => window.innerWidth)) === 1280 ? null : "viewport is not 1280 wide"),
});
ACT("viewport resize 1280 -> 1920", {
  fn: async (page) => page.setViewportSize({ width: 1920, height: 1080 }),
  verify: async (page) => ((await page.evaluate(() => window.innerWidth)) === 1920 ? null : "viewport is not 1920 wide"),
});

/* ── the run ─────────────────────────────────────────────────────────────────────────────────── */
async function main() {
  const { chromium } = await import("@playwright/test");
  /* Power, presentation and contention net of the harness — see ./host-env.mjs (perf audit
     2026-09-22). Read before the browser launches so the idle baseline is the machine alone. */
  const hostPowerAtStart = hostPower();
  const hostIdleBaseline = await idleBaseline(3000);
  const hostLoadMeter = createLoadMeter();
  hostLoadMeter.start();

  const APP = process.env.ATLAS_URL || "http://localhost:4181";
  const env = { app: APP };

  /* The headed window is planned inside the screen's work area (acceptance report item 15; host-env.mjs
     owns the plan): an off-screen window region is not a measurement environment. */
  const headedPlan = await headedWindow(chromium, { width: 1920, height: 1080 });
  console.log(headedPlan.line);
  const browser = await chromium.launch({ headless: false, args: headedPlan.args });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, reducedMotion: "no-preference" });
  await ctx.addInitScript(INIT);
  const page = await ctx.newPage();
  const windowCheck = await windowBoundsCheck(ctx, page, headedPlan.plan);
  const windowFits = windowFitsOf(headedPlan.plan, windowCheck);
  await page.goto(`${APP}${SWEEP_START}`, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(6000);
  const presentationBefore = await ensurePresenting(ctx, page);

  const clear = () => page.evaluate(() => { window.__loaf.length = 0; });
  const read = () => page.evaluate(() => window.__loaf.slice());

  /* HOST BUSYNESS (repair 2026-09-21). This sweep's answer moved by more than 2x on host load alone
     (see REPLICATION), and it recorded no host load at all, so a report could not be told apart from
     one taken on a saturated machine. Same method and bar as measure-fps.mjs / measure-inp.mjs:
     os.cpus() tick deltas across the whole run, and a run above HOST_BUSY_PCT is not acceptance
     evidence whatever its verdict. */
  const HOST_BUSY_PCT = 25;
  const cpuTicks = () => os.cpus().reduce((a, c) => {
    const t = c.times;
    a.total += t.user + t.nice + t.sys + t.idle + t.irq;
    a.idle += t.idle;
    return a;
  }, { total: 0, idle: 0 });
  const cpuAtStart = cpuTicks();

  const results = [];
  /* QUALITY TIER ON EVERY ROW (review finding, 2026-09-22, E5 minor). The auto tier steps down during
     a run, and a fabric action measured at "low" is a different, cheaper frame than the same action at
     "high" — but the row carried no tier, so an "ok 0 ms" for focusDevice in repetition 2 could not be
     told apart from a cheap full-quality frame. The tier (with the tail of qualityReasons, which says
     whether the session chose it or stepped down) is read immediately BEFORE and AFTER every action and
     written on the row; a row whose tier moved, or that ran below "high", says so in its console line
     and is counted per action. Recording, not pinning: pinning with setQuality would measure a session
     the product never runs (auto off), and E5 asks about the product as shipped. */
  const readTier = () =>
    page
      .evaluate(() => {
        const s = window.__atlasScene;
        if (!s || typeof s.stats !== "function") return null;
        const st = s.stats();
        return { tier: st.quality ?? null, reasons: Array.isArray(st.qualityReasons) ? st.qualityReasons.slice(-2) : [] };
      })
      .catch(() => null);
  const run = async (a, rep) => {
    let err = null;
    /* Setup is outside the measured window: it runs, and settles, BEFORE the buffer is cleared. */
    if (typeof a.setup === "function") {
      try {
        await a.setup(page, env);
        await page.waitForTimeout(300);
      } catch (e) {
        err = `setup: ${String(e).slice(0, 110)}`;
      }
    }
    await clear();
    const tierBefore = await readTier();
    const t0 = Date.now();
    let pre = null;
    if (err === null) {
      try {
        pre = await a.before(page, env);
      } catch (e) {
        err = `before-state: ${String(e).slice(0, 100)}`;
      }
    }
    try {
      if (err === null) await a.fn(page, env);
    } catch (e) {
      err = String(e).slice(0, 120);
    }
    await page.waitForTimeout(1400);
    if (err === null) {
      /* The effect is polled to a deadline rather than read once after a fixed sleep: an effect that
         lands late (a debounced, chunked filter on a loaded host — headless smoke, 2026-09-23) is
         still the action's effect, and the frames it cost are still inside this window, because the
         frame buffer is read only after the effect is settled. Absent at the deadline = NO EFFECT. */
      const deadline = Date.now() + 5000;
      try {
        let missing = await a.verify(page, pre);
        while (missing && Date.now() < deadline) {
          await page.waitForTimeout(250);
          missing = await a.verify(page, pre);
        }
        if (missing) err = `NO EFFECT: ${missing}`;
      } catch (e) {
        err = `effect check threw: ${String(e).slice(0, 100)}`;
      }
    }
    const loaf = await read();
    const tierAfter = await readTier();
    const timeline = await page.evaluate(() => ({ aff: (window.__affTimeline || []).slice(), paint: window.__affPaint || { fcp: null, elements: {} }, raf: (window.__raf || []).slice() }));
    const frames = judgeFrames(loaf);
    /* A window that stopped presenting mid-action makes the repetition NOT MEASURED (see frameKind). */
    if (err === null && frames.notPresenting !== null) err = `NOT PRESENTING: ${frames.notPresenting}`;
    const worst = frames.worstMain;
    /* For every over-bar frame: was it COMMUNICATED (an affordance on screen and painted before the
       frame began) and CANCELLABLE (that affordance offered a Cancel/Stop control)? A synchronous
       block cannot paint anything once it has started, so the affordance has to precede it. */
    const judged = frames.mainOverBar.map((e) => {
      /* The shared paint rule (working-affordance.mjs) first, then this sweep's own stricter test that
         at least one frame was produced after the affordance appeared and before the long frame. */
      const lastOn = affordancePaintedAt(timeline.aff, timeline.paint, e.startTime);
      const painted = lastOn !== null && timeline.raf.some((t) => t > lastOn.t && t <= e.startTime);
      return { startTime: e.startTime, duration: e.duration, communicated: painted, cancellable: painted && lastOn.cancel, affordance: lastOn?.what ?? null };
    });
    const row = {
      action: a.name,
      rep,
      error: err,
      wallMs: Date.now() - t0,
      /* The application's frames only (main-thread); the not-presenting ones are counted apart. */
      framesOver200ms: frames.mainOverBar.length,
      framesOver50ms: frames.main.filter((e) => e.duration > 50).length,
      worstFrameMs: worst ? worst.duration : 0,
      worstBlockingMs: worst ? worst.blockingDuration : 0,
      worstScripts: worst ? worst.scripts : [],
      notPresentingFrames: frames.stalls.length,
      worstNotPresentingFrameMs: frames.worstStall ? frames.worstStall.duration : 0,
      overBarFrames: judged,
      overBarUncommunicated: judged.filter((j) => !j.communicated).length,
      overBarNotCancellable: judged.filter((j) => !j.cancellable).length,
      /* null when the page had no scene handle at that moment (e.g. mid-navigation). */
      qualityBefore: tierBefore,
      qualityAfter: tierAfter,
      tierChanged: tierBefore !== null && tierAfter !== null && tierBefore.tier !== tierAfter.tier,
    };
    results.push(row);
    const tierNote =
      tierBefore === null || tierAfter === null
        ? " tier=?"
        : row.tierChanged
          ? ` tier=${tierBefore.tier}->${tierAfter.tier} (CHANGED)`
          : ` tier=${tierAfter.tier}`;
    const stallNote = row.notPresentingFrames ? `  not-presenting frames:${row.notPresentingFrames} (worst ${row.worstNotPresentingFrameMs}ms, not counted as the app's)` : "";
    console.log(
      `${(row.worstFrameMs > BAR_MS ? "OVER-200" : row.worstFrameMs > 50 ? "over-50 " : "ok      ")} ${a.name.padEnd(40)} worstLoAF=${row.worstFrameMs}ms (0 = none >50ms) blocking=${row.worstBlockingMs}ms  >200ms:${row.framesOver200ms} >50ms:${row.framesOver50ms}${tierNote}${stallNote}${err ? "  [" + err + "]" : ""}`,
    );
  };

  /* ── REPLICATION ─────────────────────────────────────────────────────────────────────────────
   *
   * Every action above used to be run ONCE, and the committed report was that single pass. An
   * external audit re-ran this sweep twice on the same build and got "7 of 16 actions over 200 ms"
   * at 24.6% host CPU and "3 of 16" at 46.8% — the answer moved by more than a factor of two on
   * host load alone, in opposite directions to the intuition. A one-shot number for a quantity that
   * unstable is not a measurement of the build.
   *
   * So each action is repeated, and the row carries the MEDIAN and the MAX across repetitions plus
   * how many repetitions crossed the bar. An action that crosses in some repetitions and not others
   * is reported as UNSTABLE rather than silently rounded to whichever run was written down last. */
  const REPS = Number(process.env.ATLAS_SWEEP_REPS || 3);

  for (let rep = 1; rep <= REPS; rep++) {
    /* Each repetition starts from the same place. Without this the path-trace action leaves the app
       on another surface and the next repetition measures a different journey under the same name. */
    await page.goto(`${APP}${SWEEP_START}`, { waitUntil: "networkidle", timeout: 30000 });
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(4000);
    console.log(`\n── repetition ${rep} of ${REPS} ──`);
    for (const a of ACTIONS) await run(a, rep);
  }

  /* What was actually measured. A report that does not record the bundle it ran against cannot be
     told apart from a stale one by anything but comparing filenames by eye — which is exactly how
     the previous committed report came to cite a chunk the build no longer ships. */
  const bundle = await page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .filter((r) => /\.(js|css)(\?|$)/.test(r.name))
      .map((r) => ({ url: r.name.split("/").pop(), bytes: r.encodedBodySize }))
      .sort((a, b) => a.url.localeCompare(b.url)),
  );

  const presentationAfter = presentationState(await rafCadence(page, 5000).catch(() => null));
  hostLoadMeter.sample();
  await browser.close();

  const median = (xs) => {
    const s = [...xs].sort((a, b) => a - b);
    return s.length ? Number(s[Math.floor((s.length - 1) / 2)].toFixed(1)) : null;
  };

  const byAction = [...new Set(results.map((r) => r.action))].map((name) => {
    const rows = results.filter((r) => r.action === name);
    const worst = rows.map((r) => r.worstFrameMs);
    const overReps = rows.filter((r) => r.worstFrameMs > BAR_MS).length;
    return {
      action: name,
      reps: rows.length,
      medianWorstFrameMs: median(worst),
      maxWorstFrameMs: Math.max(...worst),
      repsOverBar: overReps,
      stability: overReps === 0 ? "under" : overReps === rows.length ? "over" : "UNSTABLE",
      errors: rows.map((r) => r.error).filter(Boolean),
      notPresentingFrames: rows.reduce((n, r) => n + r.notPresentingFrames, 0),
      worstScripts: rows.reduce((a, b) => (b.worstFrameMs > a.worstFrameMs ? b : a)).worstScripts,
      /* The tier each repetition's figure was taken at, in rep order, so a fast figure at "low" is
         never read as a fast figure at "high". null = no scene handle when it was read. */
      tiersByRep: rows.map((r) =>
        r.qualityAfter === null ? null : r.tierChanged ? `${r.qualityBefore.tier}->${r.qualityAfter.tier}` : r.qualityAfter.tier,
      ),
      repsBelowHigh: rows.filter((r) => r.qualityAfter !== null && (r.qualityAfter.tier !== "high" || r.tierChanged)).length,
    };
  });

  const cpuAtEnd = cpuTicks();
  const hostBusyGrossPct = Math.round(100 * (1 - (cpuAtEnd.idle - cpuAtStart.idle) / Math.max(1, cpuAtEnd.total - cpuAtStart.total)));
  const hostLoad = hostLoadMeter.finish();
  /* The figure the gate reads: busy core-time NOT spent by this harness (gross where unreadable). */
  const hostBusyPct = gatedBusy(hostLoad) === null ? hostBusyGrossPct : Math.round(100 * gatedBusy(hostLoad));
  const hostPowerAtEnd = hostPower();
  const hostPowerThrottled = Boolean(hostPowerAtStart.throttled || hostPowerAtEnd.throttled);
  const presentationFullRate = presentationBefore.fullRate && presentationAfter.fullRate;
  const hostQuiet = hostBusyPct <= HOST_BUSY_PCT && !hostPowerThrottled && presentationFullRate;
  for (const a of byAction) {
    const rows = results.filter((r) => r.action === a.action);
    a.overBarFrames = rows.reduce((n, r) => n + r.overBarFrames.length, 0);
    a.overBarUncommunicated = rows.reduce((n, r) => n + r.overBarUncommunicated, 0);
    a.overBarNotCancellable = rows.reduce((n, r) => n + r.overBarNotCancellable, 0);
  }
  const over = byAction.filter((r) => r.stability === "over");
  const unstable = byAction.filter((r) => r.stability === "UNSTABLE");
  const errored = byAction.filter((r) => r.errors.length > 0);

  /* ── THE GATE ────────────────────────────────────────────────────────────────────────────────
   *
   * This script is cited as E5 evidence and had no verdict and no exit code: it printed its own
   * summary line reading "7 of 16 actions produced an animation frame over 200 ms" and exited 0.
   * It now states a bar and returns it. An action whose actuation ERRORED is NOT MEASURED — a
   * selector that matched nothing used to be reported as 0 ms, which is a measurement of nothing
   * rendered as the best possible result. So is an action whose window stopped presenting over the
   * bar (see frameKind): that frame is the environment's, not a pass and not a fail. */
  const verdict = errored.length > 0 ? "NOT MEASURED" : over.length === 0 && unstable.length === 0 ? "PASS" : "FAIL";
  const why =
    verdict === "NOT MEASURED"
      ? `${errored.length} action(s) could not be measured — not actuated, no effect, or the window was not presenting (${errored.map((e) => `${e.action}: ${e.errors[0]}`).join("; ")}) — an action that was not measured is not a fast one`
      : verdict === "PASS"
        ? `all ${byAction.length} actions stayed under ${BAR_MS} ms in every one of ${REPS} repetitions`
        : `${over.length} action(s) over ${BAR_MS} ms in every repetition, ${unstable.length} unstable across repetitions`;
  /* The communicated half, stated for every action that crossed the bar. It does not soften the
     verdict above (an over-bar action still FAILS the budget); it says whether the reader was told. */
  const frozen = byAction.filter((r) => r.overBarUncommunicated > 0);
  const uncancellable = byAction.filter((r) => r.overBarFrames > 0 && r.overBarNotCancellable > 0);
  /* A stale or foreign build is a measurement of a different program (review finding, E2). */
  const freshness = await checkBuildFreshness(APP);
  /* TIER (perf audit, 2026-09-22): a repetition measured below tier high, or across a tier change, is
     a cheaper frame than the product's own choice on this machine. It still counts AGAINST the bar
     (a cheap frame that is slow is worse), but it cannot count FOR it: a sweep with any such
     repetition is not acceptance evidence. Pinning the tier was rejected above (it measures a session
     the product never runs); discarding the credit is the honest alternative. */
  const belowHighActions = byAction.filter((r) => r.repsBelowHigh > 0);
  const acceptanceEvidence = hostQuiet && verdict !== "NOT MEASURED" && freshness.fresh && belowHighActions.length === 0 && windowFits;

  writeFileSync(
    "review/reports/e5-sweep.json",
    JSON.stringify(
      {
        criterion: "E5",
        measurementClass: "LABORATORY — headed Chromium, release preview, Intel D3D11.",
        verdict,
        why,
        bar: { animationFrameMs: BAR_MS },
        frameClassification:
          "an application (main-thread) frame carried blocking time or was at least half reported script; any other long frame has the window-not-presenting signature, is counted apart, and over the bar makes its repetition NOT MEASURED",
        reps: REPS,
        capturedAt: new Date().toISOString(),
        host: {
          busyPct: hostBusyPct,
          basis: hostLoad.excess !== null ? "excess over the harness's own process tree" : "gross",
          grossBusyPct: hostBusyGrossPct,
          harnessFraction: hostLoad.harness,
          idleBaselineBeforeLaunch: hostIdleBaseline,
          busyBarPct: HOST_BUSY_PCT,
          quiet: hostQuiet,
          cpus: os.cpus().length,
        },
        hostPower: { atStart: hostPowerAtStart, atEnd: hostPowerAtEnd, throttled: hostPowerThrottled },
        presentation: { before: presentationBefore, after: presentationAfter, fullRate: presentationFullRate },
        tierCreditWithheld: belowHighActions.map((r) => r.action),
        window: { screen: headedPlan.screen, plan: headedPlan.plan, check: windowCheck, fits: windowFits },
        acceptanceEvidence,
        buildFreshness: freshness,
        communicated: {
          rule: "an over-bar frame is COMMUNICATED when a working affordance was on screen and at least one frame was produced after it appeared, before the long frame began; CANCELLABLE when that affordance offered a Cancel/Stop control",
          exercised: byAction.some((r) => r.overBarFrames > 0),
          actionsWithUncommunicatedFrames: frozen.map((r) => r.action),
          actionsWithUncancellableFrames: uncancellable.map((r) => r.action),
        },
        /* The artefact this figure describes. Without it a report outlives the build it measured. */
        bundle,
        byAction,
        results,
      },
      null,
      1,
    ),
  );

  console.log(`\n${verdict}  E5 sweep  ${why}`);
  /* Absence is not health: with no over-bar frame, neither property was exercised, and saying
     "every over-bar frame had ..." about an empty set is a vacuous truth printed as a claim. */
  const totalOverBar = byAction.reduce((n, r) => n + r.overBarFrames, 0);
  const NOT_EXERCISED = "no over-bar frames — communication/cancellation not exercised";
  console.log(`communicated: ${totalOverBar === 0 ? NOT_EXERCISED : frozen.length === 0 ? `every one of ${totalOverBar} over-bar frame(s) had a painted working affordance` : `${frozen.length} action(s) froze with NOTHING on screen: ${frozen.map((r) => `${r.action} (${r.overBarUncommunicated} frame(s))`).join("; ")}`}`);
  console.log(`cancellable:  ${totalOverBar === 0 ? NOT_EXERCISED : uncancellable.length === 0 ? `every one of ${totalOverBar} over-bar frame(s) offered Cancel` : `${uncancellable.length} action(s) had over-bar work with no Cancel control: ${uncancellable.map((r) => r.action).join("; ")}`}`);
  const stallTotal = byAction.reduce((n, r) => n + r.notPresentingFrames, 0);
  console.log(`not presenting: ${stallTotal === 0 ? "no long frame had the window-not-presenting signature" : `${stallTotal} long frame(s) had the window-not-presenting signature (no blocking time, mostly no script) and were not counted as the app's`}`);
  console.log(`host: ${hostBusyPct}% busy across the run excluding this harness (gross ${hostBusyGrossPct}%, idle baseline ${hostIdleBaseline === null ? "?" : Math.round(hostIdleBaseline * 100) + "%"}; bar ${HOST_BUSY_PCT}%)${hostBusyPct <= HOST_BUSY_PCT ? "" : " — NOT ACCEPTANCE EVIDENCE, the machine was busy"}`);
  console.log(`power: ${describePower(hostPowerAtStart)}${hostPowerThrottled ? " — THROTTLED: NOT ACCEPTANCE EVIDENCE" : ""}; presentation rAF ${presentationBefore.rafMedianMs ?? "none"}/${presentationAfter.rafMedianMs ?? "none"} ms${presentationFullRate ? "" : " — NOT FULL RATE: NOT ACCEPTANCE EVIDENCE"}`);
  console.log(`build: ${freshness.fresh ? "fresh" : "NOT FRESH — " + freshness.why + " — NOT ACCEPTANCE EVIDENCE"}`);
  console.log(`bundle: ${bundle.map((b) => b.url).join(", ")}`);
  for (const r of [...over, ...unstable]) {
    console.log(`  ${r.stability.padEnd(8)} ${r.action} — median ${r.medianWorstFrameMs}ms, max ${r.maxWorstFrameMs}ms, over in ${r.repsOverBar}/${r.reps} reps, tiers ${JSON.stringify(r.tiersByRep)} ${JSON.stringify(r.worstScripts)}`);
  }
  const belowHigh = byAction.filter((r) => r.repsBelowHigh > 0);
  console.log(
    `tier:   ${belowHigh.length === 0 ? "every row read with a scene handle was measured at tier high" : `${belowHigh.length} action(s) had repetitions measured below tier high or across a tier change (a cheaper frame; under-bar credit withheld, NOT ACCEPTANCE EVIDENCE): ${belowHigh.map((r) => `${r.action} ${JSON.stringify(r.tiersByRep)}`).join("; ")}`}`,
  );
  process.exit(verdict === "PASS" && frozen.length === 0 ? 0 : 1);
}

if (IS_MAIN) await main();
