/**
 * host-env.mjs — the ONE owner of "was this machine in a state where a timing figure means
 * anything?" for every E2-E5 instrument (measure-inp, measure-fps, audit-e5-coldload,
 * audit-e5-sweep).
 *
 * WHY ONE MODULE (perf audit, 2026-09-22). The power probe and the presentation check were added to
 * measure-inp.mjs alone, and the three sibling instruments kept printing "unthrottled" figures taken
 * on battery with Windows Energy Saver ON — the state that capped the browser at 30 Hz, stopped it
 * presenting altogether, produced the "1016.8 ms STALL" in measure-fps, and HID E3 violations (the
 * 30 Hz runs were E3-clean, the 60 Hz runs were not). A guard copied into one of four instruments is
 * a guard for that instrument, not for the class; every instrument now imports these.
 *
 * Three questions, each answered from the OS or the page, never assumed:
 *   1. POWER — on AC, Energy Saver off? (`hostPower`)
 *   2. PRESENTATION — is the headed window presenting, and at what cadence? (`rafCadence`,
 *      `presentationState`). visibilityState stays "visible" while a window is minimised or the
 *      display is off; only rAF cadence reveals it.
 *   3. CONTENTION — how busy was the machine EXCLUDING the harness's own browser? (`hostLoad`).
 *      The old figure counted the headed Chromium and its GPU process as "busy", and on the
 *      reference host the idle baseline alone is 15-33 % (a security-virtualisation process holds
 *      about one core), so a 25 % bar on the gross figure was unattainable and could not separate
 *      contention from measurement load. The gate now reads the EXCESS: busy core-time minus the
 *      harness's own CPU (Node + the launched browsers and all their children, INCLUDING the ones
 *      that have exited — read from a Windows job object since wave 5; see 3a). The gross figure
 *      and a pre-run idle baseline are recorded beside it.
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, renameSync } from "node:fs";
import { cpus, tmpdir } from "node:os";
import { join } from "node:path";

/* ── 1. power ────────────────────────────────────────────────────────────────────────────────── */

/**
 * Power source and Energy Saver, from the Windows Runtime PowerManager. `throttled` is true on
 * battery or with Energy Saver ON. Unknown (non-Windows, probe failed) is recorded as unknown.
 * EnergySaverStatus is "Disabled" on AC (the saver cannot engage), "Off" or "On" on battery.
 */
export const hostPower = () => {
  if (process.platform !== "win32") return { known: false, why: `platform ${process.platform}` };
  try {
    const ps =
      "[Windows.System.Power.PowerManager,Windows.System.Power,ContentType=WindowsRuntime] | Out-Null; " +
      "$m=[Windows.System.Power.PowerManager]; " +
      "Write-Output ('' + $m::EnergySaverStatus + '|' + $m::PowerSupplyStatus + '|' + $m::RemainingChargePercent)";
    const r = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", ps], { encoding: "utf8", timeout: 15000 });
    const [saver, supply, pct] = String(r.stdout || "").trim().split("|");
    if (!saver || !supply) return { known: false, why: `probe returned ${JSON.stringify(String(r.stdout || r.stderr || "").slice(0, 80))}` };
    return { known: true, energySaver: saver, powerSupply: supply, chargePercent: Number(pct), throttled: saver === "On" || supply === "NotPresent" };
  } catch (e) {
    return { known: false, why: String(e).slice(0, 80) };
  }
};

export const describePower = (p) =>
  p.known ? `saver=${p.energySaver} supply=${p.powerSupply} charge=${p.chargePercent}%` : `unknown (${p.why})`;

/* ── 2. presentation ─────────────────────────────────────────────────────────────────────────── */

/** "Not presenting": no frames, or a median rAF interval over this (measured signature ~1000 ms). */
export const PRESENTING_MAX_RAF_MS = 100;
/**
 * A presenting window whose median rAF interval is over this is presenting BELOW 50 Hz — a power
 * governor (measured 33.4 ms under Energy Saver) or a slow display. It IS presenting, but no figure
 * taken there can be read against a 55 fps bar, and E3's long-task picture changes shape under it.
 */
export const FULL_RATE_MAX_RAF_MS = 20;

/** Median of 12 rAF intervals in the page, or null when fewer frames arrived within `timeoutMs`. */
export const rafCadence = (page, timeoutMs = 4000) =>
  page.evaluate(
    (t) =>
      new Promise((resolve) => {
        const ts = [];
        const tick = (x) => {
          ts.push(x);
          if (ts.length < 13) requestAnimationFrame(tick);
          else {
            const d = ts.slice(1).map((v, k) => v - ts[k]).sort((p, q) => p - q);
            resolve(Number(d[6].toFixed(1)));
          }
        };
        requestAnimationFrame(tick);
        setTimeout(() => resolve(null), t);
      }),
    timeoutMs,
  );

/** Classify a measured cadence. */
export const presentationState = (rafMedianMs) =>
  rafMedianMs === null || !(rafMedianMs < PRESENTING_MAX_RAF_MS)
    ? { presenting: false, fullRate: false, rafMedianMs, hz: null }
    : { presenting: true, fullRate: rafMedianMs <= FULL_RATE_MAX_RAF_MS, rafMedianMs, hz: Number((1000 / rafMedianMs).toFixed(1)) };

/** Chromium flags that stop the harness's own window being throttled when occluded. */
export const NO_OCCLUSION_ARGS = [
  "--disable-backgrounding-occluded-windows",
  "--disable-renderer-backgrounding",
  "--disable-features=CalculateNativeWinOcclusion",
];

/* ── 2b. window geometry (acceptance report item 15, 2026-09-23) ────────────────────────────────
 *
 * Every headed instrument used to launch at a fixed `--window-size=1940,1180` for a 1920x1080
 * viewport. On the reference host the screen is 1920x1200 physical at 150 % scaling — a 1280x752 DIP
 * work area — so the window was half again the size of the screen and most of it, the canvas
 * included, was off-screen. An off-screen window region is not a measurement environment. The
 * viewport stays the render target the criteria are written about (1920x1080 CSS px at DSF 1); the
 * WINDOW is sized to hold it and placed inside the screen's work area. When the work area cannot
 * hold it at the display's own scale, the browser is started with a smaller device scale factor
 * (`--force-device-scale-factor`), which changes the browser's DIP-to-pixel ratio and nothing about
 * the page: the page is emulated at DSF 1, so the canvas draws the same buffer either way. This was
 * measure-inp's alone; it is here so every headed instrument uses it (src/core/headed-window.test.ts
 * holds the class). */

/**
 * The launch plan that puts a window holding `viewport` inside the screen's work area.
 * `screen` is in DIP at the display's native scale: availWidth/availHeight/availLeft/availTop, the
 * native devicePixelRatio `dpr`, and the browser chrome's insets `insetW`/`insetH` (outer - inner).
 */
export function planWindow(screen, viewport = { width: 1920, height: 1080 }) {
  const needW = Math.ceil(viewport.width + screen.insetW);
  const needH = Math.ceil(viewport.height + screen.insetH);
  const physW = screen.availWidth * screen.dpr;
  const physH = screen.availHeight * screen.dpr;
  /* Floored to a thousandth so the window rounds INSIDE the work area, never one pixel over it. */
  const scale = Math.floor(Math.min(screen.dpr, physW / needW, physH / needH) * 1000) / 1000;
  const forced = scale !== screen.dpr;
  const areaAtScale = {
    left: Math.round(((screen.availLeft ?? 0) * screen.dpr) / scale),
    top: Math.round(((screen.availTop ?? 0) * screen.dpr) / scale),
    width: Math.floor(physW / scale),
    height: Math.floor(physH / scale),
  };
  const window = { left: areaAtScale.left, top: areaAtScale.top, width: needW, height: needH };
  return {
    scale,
    forced,
    window,
    workAreaAtScale: areaAtScale,
    fits: scale > 0 && needW <= areaAtScale.width && needH <= areaAtScale.height,
    args: [
      ...(forced ? [`--force-device-scale-factor=${scale}`] : []),
      `--window-position=${window.left},${window.top}`,
      `--window-size=${window.width},${window.height}`,
    ],
  };
}

/** Does the window the OS gave (CDP `Browser.getWindowBounds`, DIP) lie inside the planned work area? */
export function windowInside(bounds, plan) {
  if (!bounds || !plan) return false;
  const a = plan.workAreaAtScale;
  return bounds.left >= a.left && bounds.top >= a.top && bounds.left + bounds.width <= a.left + a.width && bounds.top + bounds.height <= a.top + a.height;
}

/**
 * Read the screen from a throwaway headed browser at the display's own scale (no viewport emulation,
 * so outer - inner is the browser chrome) and plan the window for `viewport`. Returns
 * `{ screen, plan, args, line }`: `args` are the launch arguments (the plan's, plus the occlusion
 * flags); `plan` is null when the probe failed, in which case the window is launched with only a
 * position hint and NO size of its own (Chromium's default, which is inside the screen), and every
 * verdict built on `windowFits` withholds acceptance evidence rather than guessing.
 * `meter` is the run's load meter when one is running: the probe browser is harness load too, and it
 * is closed through the meter (closeMeasured).
 */
export async function headedWindow(chromium, viewport = { width: 1920, height: 1080 }, meter = null) {
  let screen;
  const probe = await chromium.launch({ headless: false, args: [...NO_OCCLUSION_ARGS] });
  try {
    const pctx = await probe.newContext({ viewport: null });
    const ppage = await pctx.newPage();
    await ppage.goto("about:blank");
    await ppage.waitForTimeout(300);
    screen = await ppage.evaluate(() => ({
      availWidth: window.screen.availWidth,
      availHeight: window.screen.availHeight,
      availLeft: window.screen.availLeft ?? 0,
      availTop: window.screen.availTop ?? 0,
      dpr: window.devicePixelRatio,
      insetW: window.outerWidth - window.innerWidth,
      insetH: window.outerHeight - window.innerHeight,
    }));
  } catch (e) {
    screen = { error: String(e).slice(0, 160) };
  } finally {
    /* Through the run's load meter when there is one (see closeMeasured). */
    await closeMeasured(meter, probe).catch(() => {});
  }
  const plan = screen && !screen.error ? planWindow(screen, viewport) : null;
  const line = plan
    ? `window: screen work area ${screen.availWidth}x${screen.availHeight} DIP at DPR ${screen.dpr}, chrome ${screen.insetW}x${screen.insetH}; ` +
      `window ${plan.window.width}x${plan.window.height} at scale ${plan.scale}${plan.forced ? " (forced)" : ""}, plan fits: ${plan.fits}`
    : `window: the screen could not be read (${screen?.error ?? "no probe"}); launched at the browser's default size — NOT acceptance evidence`;
  return { screen, plan, args: [...(plan ? plan.args : ["--window-position=0,0"]), ...NO_OCCLUSION_ARGS], line };
}

/**
 * The window the OS actually gave `page`, checked against `plan`. `{ checked, bounds, inside }`, or
 * `{ checked, error, inside: false }` — a window that could not be read is not known to be inside.
 */
export async function windowBoundsCheck(ctx, page, plan) {
  try {
    const cdp = await ctx.newCDPSession(page);
    const { windowId } = await cdp.send("Browser.getWindowForTarget");
    const { bounds } = await cdp.send("Browser.getWindowBounds", { windowId });
    return { checked: true, bounds, plan, inside: windowInside(bounds, plan) };
  } catch (e) {
    return { checked: true, error: String(e).slice(0, 160), plan, inside: false };
  }
}

/** The one rule: a headed window is a measurement environment only when its plan fits AND the OS put it inside. */
export const windowFitsOf = (plan, check) => plan !== null && plan.fits === true && check?.inside === true;

/**
 * Measure the cadence; if the window is not presenting, restore it and bring it to front once and
 * measure again. Returns the presentationState of the final reading plus `restored`.
 */
export async function ensurePresenting(ctx, page) {
  const first = presentationState(await rafCadence(page).catch(() => null));
  if (first.presenting) return { ...first, restored: false };
  try {
    const cdp = await ctx.newCDPSession(page);
    const { windowId } = await cdp.send("Browser.getWindowForTarget");
    await cdp.send("Browser.setWindowBounds", { windowId, bounds: { windowState: "normal" } });
  } catch {
    /* not every context exposes the window; bringToFront below is the fallback */
  }
  await page.bringToFront().catch(() => {});
  await page.waitForTimeout(800);
  const second = presentationState(await rafCadence(page).catch(() => null));
  return { ...second, restored: true, firstRafMedianMs: first.rafMedianMs };
}

/* ── 3. contention, net of the harness ───────────────────────────────────────────────────────── */

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

/* ── 3a. the harness as a Windows JOB OBJECT (acceptance E2/E3, wave 5) ────────────────────────
 *
 * THE DEFECT THIS REPLACES. The harness used to be read as a process TREE (3b below) at start(), at
 * each sample() and at finish(). A process that is not alive at a read is not in the tree, so every
 * CPU millisecond a child spent after the last read before it exited was LOST — and a lost harness
 * millisecond is not dropped, it is moved: excess = gross - harness, so it was booked as other load on
 * the machine, the figure the 25 % gate reads. The contract "sample() BEFORE each browser.close()" was
 * a rule every caller had to remember, and measure-inp sampled once while closing a scout browser, 21
 * fresh first-selection browsers and a context per journey unsampled: its reports said "harness 0-1 %"
 * where an independent sidecar measured Playwright Chromium at 7.2-9.3 % of the host. Renderer and
 * utility processes that Chromium itself retires mid-run were lost the same way, with no close to hang
 * a sample on at all.
 *
 * THE FIX, for the class rather than the call sites. At start() the harness process is placed in a
 * fresh job object. Every process it creates from then on — the browsers, their GPU, renderer and
 * utility children, anything they spawn — is created inside that job (Chromium's own sandbox jobs nest
 * under it), and the job's basic accounting (TotalUserTime + TotalKernelTime) is kept for processes
 * that have EXITED as well as those still running. The harness figure is the job's growth from
 * start() to finish(); no call site can lose a child.
 *
 * The mechanics, each measured on the reference host (2026-09-24):
 *   - the job is created, the Node process assigned and the start reading taken by a PowerShell that
 *     Node spawns BEFORE it joins, so that helper is not itself in the job; it duplicates the job
 *     handle into the Node process, so the job's name stays openable until Node exits;
 *   - the finish reading is taken by a PowerShell that IS in the job (Node's child); it reads its own
 *     CPU time immediately before the query and the meter subtracts it, and it runs AFTER the run's
 *     closing CPU-counter read, so its cost is in neither the gross nor the harness window;
 *   - the helper type is compiled once into a DLL cached under the OS temp directory, and loaded by
 *     path afterwards: compiling in the finish probe would start csc.exe inside the job;
 *   - a process in a job cannot leave it, and nothing else is changed: no limit is set on the job.
 * Where any step fails (not Windows, a policy that refuses nesting) the meter says so (`method:
 * "tree"`, `jobError`) and falls back to the tree, whose rule closeMeasured below enforces. */
const JOB_ACCOUNTING_CS = `
using System;
using System.Runtime.InteropServices;
public static class AtlasHarnessJob {
  [StructLayout(LayoutKind.Sequential)]
  public struct BASIC { public long TotalUserTime; public long TotalKernelTime; public long ThisPeriodTotalUserTime; public long ThisPeriodTotalKernelTime; public uint TotalPageFaultCount; public uint TotalProcesses; public uint ActiveProcesses; public uint TotalTerminatedProcesses; }
  [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] static extern IntPtr CreateJobObjectW(IntPtr attrs, string name);
  [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] static extern IntPtr OpenJobObjectW(uint access, bool inherit, string name);
  [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
  [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
  [DllImport("kernel32.dll", SetLastError = true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr proc);
  [DllImport("kernel32.dll", SetLastError = true)] static extern bool DuplicateHandle(IntPtr srcProc, IntPtr src, IntPtr dstProc, out IntPtr dst, uint access, bool inherit, uint options);
  [DllImport("kernel32.dll", SetLastError = true)] static extern bool QueryInformationJobObject(IntPtr job, int cls, out BASIC info, int len, IntPtr ret);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  static string Row(BASIC b) { return "ok|" + (b.TotalUserTime + b.TotalKernelTime) + "|" + b.TotalProcesses + "|" + b.ActiveProcesses; }
  static string Err(string step) { return "err|" + step + "|" + Marshal.GetLastWin32Error(); }
  public static string Adopt(int pid, string name) {
    IntPtr job = CreateJobObjectW(IntPtr.Zero, name);
    if (job == IntPtr.Zero) return Err("create");
    IntPtr proc = OpenProcess(0x0001 | 0x0100 | 0x0040 | 0x0400, false, pid);
    if (proc == IntPtr.Zero) return Err("open-process");
    if (!AssignProcessToJobObject(job, proc)) return Err("assign");
    IntPtr kept;
    if (!DuplicateHandle(GetCurrentProcess(), job, proc, out kept, 0, false, 2)) return Err("keep-handle");
    BASIC b;
    if (!QueryInformationJobObject(job, 1, out b, Marshal.SizeOf(typeof(BASIC)), IntPtr.Zero)) return Err("query");
    return Row(b);
  }
  public static string Query(string name) {
    IntPtr job = OpenJobObjectW(0x0004, false, name);
    if (job == IntPtr.Zero) return Err("open-job");
    BASIC b;
    bool ok = QueryInformationJobObject(job, 1, out b, Marshal.SizeOf(typeof(BASIC)), IntPtr.Zero);
    CloseHandle(job);
    return ok ? Row(b) : Err("query");
  }
}
`;
const JOB_DLL = join(tmpdir(), `atlas-harness-job-${createHash("sha256").update(JOB_ACCOUNTING_CS).digest("hex").slice(0, 16)}.dll`);

const powershell = (script, timeout = 60000) => {
  const r = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], { encoding: "utf8", timeout, windowsHide: true });
  return { out: String(r.stdout || "").trim(), err: String(r.stderr || r.error || "").trim().slice(0, 200) };
};
const parseRow = (s) => {
  const [tag, a, b, c] = String(s).split("|");
  if (tag !== "ok") return { error: `${a ?? "no output"} (win32 error ${b ?? "?"})` };
  return { cpuMs: Number(a) / 1e4, processes: Number(b), active: Number(c) };
};

/**
 * Put THIS process in a new job object and read the job's accounting. Returns `{ name, cpuMs, dll }`
 * or `{ error }`. Must be called before the harness spawns anything it means to count.
 */
const adoptIntoJob = () => {
  if (process.platform !== "win32") return { error: `platform ${process.platform}` };
  try {
    const name = `AtlasScopeHarness-${process.pid}-${Date.now()}`;
    let dll = JOB_DLL;
    let compile = "";
    if (!existsSync(JOB_DLL)) {
      /* Compiled to a private path, then moved into place, so two harnesses starting together
         cannot load a half-written DLL. */
      dll = JOB_DLL.replace(/\.dll$/, `.${process.pid}.dll`);
      const b64 = Buffer.from(JOB_ACCOUNTING_CS, "utf16le").toString("base64");
      compile = `$cs=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('${b64}')); Add-Type -TypeDefinition $cs -OutputAssembly '${dll}' -OutputType Library; `;
    }
    const r = powershell(`${compile}Add-Type -Path '${dll}'; [AtlasHarnessJob]::Adopt(${process.pid}, '${name}')`);
    if (dll !== JOB_DLL) {
      try {
        renameSync(dll, JOB_DLL);
        dll = JOB_DLL;
      } catch {
        /* another harness put it there first, or it is locked: keep using the private copy */
      }
    }
    const row = parseRow(r.out.split(/\r?\n/).pop());
    return row.error ? { error: `${row.error}${r.err ? `; ${r.err}` : ""}` } : { name, dll, cpuMs: row.cpuMs };
  } catch (e) {
    return { error: String(e).slice(0, 160) };
  }
};

/**
 * The job's accounting now, net of the reading process's own CPU (that PowerShell is a child of this
 * process, so it is in the job). `{ cpuMs }` or `{ error }`.
 */
const readJob = (job) => {
  try {
    const r = powershell(
      `Add-Type -Path '${job.dll}'; $self=[Diagnostics.Process]::GetCurrentProcess().TotalProcessorTime.Ticks; ` +
        `$row=[AtlasHarnessJob]::Query('${job.name}'); Write-Output ($row + '|' + $self)`,
    );
    const line = r.out.split(/\r?\n/).pop() ?? "";
    const row = parseRow(line);
    if (row.error) return { error: `${row.error}${r.err ? `; ${r.err}` : ""}` };
    const selfMs = Number(line.split("|")[4]) / 1e4;
    return { cpuMs: row.cpuMs - (Number.isFinite(selfMs) ? selfMs : 0), processes: row.processes };
  } catch (e) {
    return { error: String(e).slice(0, 160) };
  }
};

/* ── 3b. the harness as a process TREE — the fallback where no job can be created ──────────────── */

/**
 * CPU milliseconds consumed so far by the process tree rooted at `rootPid` (Windows only: CIM
 * Win32_Process, KernelModeTime + UserModeTime in 100 ns units). Map pid -> ms. null when unknown.
 * A process that has exited is not in the tree: see 3a for why this is only the fallback.
 */
const treeCpuMs = (rootPid) => {
  if (process.platform !== "win32" || !rootPid) return null;
  try {
    const ps =
      /* Filtered to the image names a Playwright harness can spawn: an unfiltered Win32_Process
         query took ~17 s on a contended host (measured 2026-09-22) and hit the timeout, leaving the
         harness unmeasured. The probe's own PowerShell is therefore NOT counted as harness, which
         errs toward a HIGHER excess figure — the conservative direction for a quiescence gate. */
      "Get-CimInstance Win32_Process -Filter \"Name='node.exe' OR Name='chrome.exe' OR Name='chrome-headless-shell.exe' OR Name='msedge.exe'\" " +
      "-Property ProcessId,ParentProcessId,KernelModeTime,UserModeTime | " +
      "ForEach-Object { '' + $_.ProcessId + ',' + $_.ParentProcessId + ',' + ($_.KernelModeTime + $_.UserModeTime) }";
    const r = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", ps], { encoding: "utf8", timeout: 45000 });
    const rows = String(r.stdout || "")
      .split(/\r?\n/)
      .map((l) => l.trim().split(","))
      .filter((x) => x.length === 3)
      .map(([p, pp, t]) => ({ pid: Number(p), ppid: Number(pp), ms: Number(t) / 1e4 }));
    if (rows.length === 0) return null;
    const kids = new Map();
    for (const x of rows) kids.set(x.ppid, [...(kids.get(x.ppid) ?? []), x]);
    const out = new Map();
    const root = rows.find((x) => x.pid === rootPid);
    if (!root) return null;
    const stack = [root];
    while (stack.length) {
      const x = stack.pop();
      if (out.has(x.pid)) continue;
      out.set(x.pid, x.ms);
      for (const k of kids.get(x.pid) ?? []) if (k.pid !== x.pid) stack.push(k);
    }
    return out;
  } catch {
    return null;
  }
};

/** Gross busy fraction of all cores over a quiet `ms` window, taken BEFORE any browser launches. */
export async function idleBaseline(ms = 3000) {
  const a = cpuTicks();
  await new Promise((r) => setTimeout(r, ms));
  const b = cpuTicks();
  if (!a || !b || b.total - a.total <= 0) return null;
  return Number((1 - (b.idle - a.idle) / (b.total - a.total)).toFixed(3));
}

/**
 * THE close for every Playwright browser, context or page a metered harness opens: sample the meter,
 * then close. Under the job (3a) the sample costs nothing and changes nothing — an exited process's CPU
 * is kept by the job. Under the tree fallback (3b) it is the only way that CPU is counted, because a
 * child that exits takes its counters out of the tree. `meter` may be null only where no run is being
 * metered (a unit test's fake browser). src/core/host-load-meter.test.ts holds every metered harness in
 * review/ to this: no `.close(` except through its meter, and this is the one bare close.
 */
export async function closeMeasured(meter, target) {
  if (meter) meter.sample();
  await target.close();
}

/**
 * A load meter for one run. Playwright launches Chromium as a CHILD of this Node process, so the
 * harness is this process and everything it spawns. `start()` once, BEFORE the harness launches
 * anything it means to count; close every browser/context/page with `meter.close(x)` (closeMeasured);
 * `finish()` at the end.
 *
 * How the harness is read (`method` in the result): "job" — the Windows job object of 3a, which keeps
 * the CPU of processes that have exited; "tree" — the process tree of 3b, sampled at start, at every
 * close and at finish (a pid first seen after start() counts from zero), which loses whatever a child
 * spent after its last sample; null — unreadable on this platform. This module's own tree probes
 * (PowerShell) are not counted as harness, and neither are the job's start and finish probes: the
 * start helper runs outside the job, and the finish probe's own CPU is subtracted and falls after the
 * run's closing counter read. Both err toward a HIGHER excess — the conservative direction.
 *
 * Returned figures (fractions of all core-time over the run):
 *   gross    — every process, the old figure;
 *   harness  — this Node process and everything it spawned, exited or not;
 *   excess   — gross - harness: what the REST of the machine did. The acceptance gate reads this.
 * plus `harnessCpuMs` and `windowCoreMs` (the raw milliseconds behind `harness`), `method`, and
 * `jobError` when a job could not be used. Where the harness cannot be read, excess is null and the
 * gate falls back to gross.
 */
export function createLoadMeter() {
  const cores = cpus().length;
  let t0 = null;
  let base = null;
  let job = null;
  let jobError = null;
  const last = new Map();
  let treeReads = 0;
  const read = () => {
    if (job) return; /* the job keeps every process's CPU; nothing to catch before a close */
    const now = treeCpuMs(process.pid);
    if (!now) return;
    treeReads += 1;
    for (const [pid, ms] of now) last.set(pid, Math.max(last.get(pid) ?? 0, ms));
  };
  const meter = {
    start() {
      /* The job first, and the counters after it: the helper that makes the job (and, on a first run,
         compiles its type) runs before the window opens, so its cost lands in neither figure. */
      const adopted = adoptIntoJob();
      if (adopted.error) jobError = adopted.error;
      else job = adopted;
      t0 = cpuTicks();
      if (!job) {
        base = treeCpuMs(process.pid);
        if (base) treeReads += 1;
      }
    },
    sample: read,
    close: (target) => closeMeasured(meter, target),
    finish() {
      const empty = { gross: null, harness: null, excess: null, cores, harnessMeasured: false, method: null, harnessCpuMs: null, windowCoreMs: null, jobError };
      if (!job) read();
      const t1 = cpuTicks();
      if (!t0 || !t1 || t1.total - t0.total <= 0) return empty;
      const totalMs = t1.total - t0.total; // os.cpus() times are ms, summed over cores
      const gross = 1 - (t1.idle - t0.idle) / totalMs;
      let harnessMs = null;
      let method = null;
      if (job) {
        const end = readJob(job);
        if (end.error) jobError = `finish: ${end.error}`;
        else {
          harnessMs = Math.max(0, end.cpuMs - job.cpuMs);
          method = "job";
        }
      } else if (base !== null && treeReads >= 2) {
        harnessMs = 0;
        for (const [pid, ms] of last) harnessMs += Math.max(0, ms - (base.get(pid) ?? 0));
        method = "tree";
      }
      const harness = harnessMs === null ? null : harnessMs / totalMs;
      return {
        gross: Number(gross.toFixed(3)),
        harness: harness === null ? null : Number(harness.toFixed(3)),
        excess: harness === null ? null : Number(Math.max(0, gross - harness).toFixed(3)),
        cores,
        harnessMeasured: harness !== null,
        method,
        harnessCpuMs: harnessMs === null ? null : Math.round(harnessMs),
        windowCoreMs: Math.round(totalMs),
        jobError,
      };
    },
  };
  return meter;
}

/** What `excess` was taken over, in words, for a report's `hostQuiescence.basis`. */
export const harnessBasis = (load) =>
  load.excess === null
    ? "gross (the harness could not be read on this host)"
    : load.method === "job"
      ? "excess over the harness's job object (every process it spawned, exited or not)"
      : "excess over the harness's process tree (sampled; CPU a child spent after its last sample is lost, and booked as excess)";

/** The busyness the acceptance gate reads: the excess when the harness was measured, else gross. */
export const gatedBusy = (load) => (load.excess !== null ? load.excess : load.gross);
