/**
 * capture.mjs — deterministic screenshot harness for the visual-review loop.
 *
 * Four jobs:
 *   1. `node review/capture.mjs app`    — capture Atlas Scope in a fixed set of investigation states.
 *   2. `node review/capture.mjs refs`   — capture the quality-bar reference products.
 *   3. `node review/capture.mjs reduced`— the `prefers-reduced-motion` evidence (acceptance D7).
 *   4. `node review/capture.mjs twice`  — capture, re-capture, byte-compare (acceptance F6).
 *
 * Determinism matters more than convenience here: a critic comparing two runs must be looking at a
 * difference we made, not at a layout that reshuffled. So: fixed viewport, fixed deviceScaleFactor,
 * animations disabled at capture time, web fonts awaited, and the app's own layout seeded.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHOTS = resolve(HERE, "shots");
const APP = process.env.ATLAS_URL || "http://localhost:4180";

/**
 * The investigation states a reviewer must see. Each is a URL the store can rehydrate from, using
 * the grammar in src/core/store.ts :: encodeInvestigation.
 *
 * Every parameter below was verified against the real compiled data, not assumed:
 *   - `core1` is a real inventoried host and the one host whose ACLs we hold.
 *   - `F001` is a real Critical finding ("CR-01: End-of-support keystone") on core1.
 *   - tcp/3389 to 10.0.30.10 is genuinely DENIED by acls.core1.PROTECT_SERVERS[3]; tcp/443 on the
 *     same pair is DELIVERED. An earlier version of this file used 443 for the "blocked" state,
 *     which would have shown a critic a successful trace under a screenshot named "blocked".
 */
const APP_STATES = [
  { id: "01-fabric-overview", q: "", note: "First paint: the whole fabric, nothing selected." },
  { id: "02-device-selected", q: "d=core1&s=fabric", note: "A device selected — evidence pane populated." },
  { id: "03-finding-drill", q: "s=findings&sev=CH", note: "Priority queue filtered to Critical+High." },
  { id: "04-finding-evidence", q: "s=findings&f=F001&d=core1&tab=raw", note: "Finding to its configuration evidence." },
  { id: "05-path-trace", q: "s=path", note: "Path trace surface, before a flow is run." },
  {
    id: "06-path-blocked",
    q: "s=path&flow=10.0.10.50>10.0.30.10>tcp>3389&hop=0",
    note: "A genuinely denied flow: the blocking-hop answer, naming PROTECT_SERVERS line 3.",
  },
  {
    id: "08-path-indeterminate",
    q: "s=path&flow=10.0.40.50>10.0.30.10>tcp>443&hop=0",
    note: "A flow reaching dist1, which has no collected RIB — the honest 'I cannot tell you' state.",
  },
  { id: "07-evidence-raw", q: "s=evidence&d=core1&tab=raw", note: "Raw inspectable evidence, Grafana-style." },
];

const VIEWPORTS = [
  { id: "1920", width: 1920, height: 1080 },
  { id: "1440", width: 1440, height: 900 },
];

const THEMES = ["dark", "light"];

/** Reference products. `wait` gives JS apps time to settle; `note` tells the critic what it is. */
const REFS = [
  { id: "forward-getting-started", url: "https://www.forwardnetworks.com/getting-started/", wait: 6000 },
  { id: "forward-demo-a", url: "https://app.storylane.io/demo/ts9nkc4osn4z?embed=inline", wait: 12000 },
  { id: "forward-demo-b", url: "https://app.storylane.io/demo/jdhoywyw5voi?embed=inline", wait: 12000 },
  { id: "ipfabric-network-viewer", url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/diagrams/network_viewer/", wait: 6000 },
  { id: "ipfabric-path-lookup", url: "https://docs.ipfabric.io/latest/IP_Fabric_GUI/diagrams/how_to_use_path-lookup/", wait: 6000 },
  { id: "linear-custom-views", url: "https://linear.app/docs/custom-views", wait: 6000 },
  { id: "linear-display-options", url: "https://linear.app/docs/display-options", wait: 6000 },
  { id: "grafana-play", url: "https://play.grafana.org/", wait: 14000 },
  { id: "grafana-explore-inspector", url: "https://grafana.com/docs/grafana/latest/explore/explore-inspector/", wait: 6000 },
  { id: "batfish-fwd-validation", url: "https://batfish.readthedocs.io/en/latest/notebooks/linked/introduction-to-forwarding-change-validation.html", wait: 6000 },
  { id: "apg-data-grid", url: "https://www.w3.org/WAI/ARIA/apg/patterns/grid/examples/data-grids/", wait: 4000 },
];

const FREEZE_CSS = `
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    caret-color: transparent !important;
  }
`;

async function shoot(page, file, { fullPage = false } = {}) {
  mkdirSync(dirname(file), { recursive: true });
  await page.screenshot({ path: file, fullPage, animations: "disabled", scale: "device" });
  return file;
}

/**
 * Decide whether a captured state is worth showing a critic.
 *
 * A blank or half-rendered frame costs a whole review round: three critics spend their effort
 * describing an accident rather than the design, and their fault lists are then worthless. So each
 * capture is checked for actual content before it is admitted, and anything that fails is reported
 * LOUDLY rather than written into index.json as if it were our work.
 */
async function verifyRendered(page, state) {
  return page.evaluate((st) => {
    const problems = [];
    const root = document.getElementById("root");
    if (!root) problems.push("no #root");
    const text = (document.body.innerText || "").trim();
    if (text.length < 120) problems.push(`only ${text.length} chars of visible text`);
    if (/error|failed to fetch|cannot read|undefined is not/i.test(text.slice(0, 600)))
      problems.push("an error message is on screen");
    // A surface that should show the fabric must actually have a canvas with pixels behind it.
    if (st.id.includes("fabric") || st.id.includes("device")) {
      const c = document.querySelector("canvas");
      if (!c) problems.push("no <canvas> on a fabric surface");
      else if (c.width < 200 || c.height < 200) problems.push(`canvas is ${c.width}x${c.height}`);
    }
    // A path state must have produced a verdict, not an empty form.
    if (st.id.includes("path-blocked") || st.id.includes("path-indeterminate")) {
      if (!/denied|indeterminate|dropped|delivered|out of scope/i.test(text))
        problems.push("no forwarding verdict rendered");
    }
    return problems;
  }, state);
}

/**
 * Launch flags that get us a REAL GPU rather than SwiftShader.
 *
 * This matters more than it looks. The 3-D subsystem probes the renderer and picks a quality tier
 * from what it finds; on SwiftShader it correctly selects `low`, which switches off bloom and SSAO.
 * Capturing with default flags therefore photographs a deliberately degraded render — and the blind
 * comparison would then be judging our low tier against another product's full one, which is not a
 * comparison at all. `--use-gl=angle` routes through the platform GPU (D3D11 on this host).
 */
const GPU_ARGS = ["--use-gl=angle", "--enable-gpu-rasterization", "--ignore-gpu-blocklist"];

async function captureApp(outRoot = resolve(SHOTS, "app")) {
  const browser = await chromium.launch({ args: GPU_ARGS });
  const written = [];
  const failures = [];
  for (const theme of THEMES) {
    for (const vp of VIEWPORTS) {
      const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: 2,
        colorScheme: theme,
        reducedMotion: "no-preference",
      });
      const page = await ctx.newPage();
      const consoleErrors = [];
      page.on("console", (m) => {
        if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
      });
      page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 200)));

      for (const st of APP_STATES) {
        const url = `${APP}/${st.q ? "?" + st.q : ""}`;

        /* PREPARE, with a bounded retry on a navigation that happened UNDER us.
         *
         * Against `npm run dev`, Vite's HMR client reloads the page whenever any module it is
         * serving changes. If that lands between `goto` and `addStyleTag`, Playwright throws
         * "Execution context was destroyed" and the whole run dies — which is what happened on the
         * second of the two F6 runs while other agents were editing the tree.
         *
         * A retry, not a swallow. It re-navigates from scratch (so the state is set up cleanly
         * rather than half-applied), it is bounded, and the attempt count is RECORDED on the frame
         * so a reviewer can see that a capture needed three goes. Exhausting the retries is a
         * recorded problem, not a silent pass. Note this makes the harness survive a live-reload;
         * it does not make a capture taken DURING active editing authoritative — F6's measurement
         * belongs on a tree nobody is writing to. */
        let attempts = 0;
        let prepareError = null;
        for (; attempts < 3; attempts++) {
          try {
            consoleErrors.length = 0;
            await page.goto(url, { waitUntil: "networkidle" });
            await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
            await page.addStyleTag({ content: FREEZE_CSS });
            await page.evaluate(() => document.fonts?.ready);

            /* Wait for the renderer to say it has CONVERGED rather than guessing with a timeout.
               The 3-D subsystem exposes `converged` in its stats precisely so a screenshot can be
               taken at a defined moment; a fixed sleep produces a different frame on a different
               machine and silently breaks the byte-identical-capture requirement. Falls back to a
               bounded wait when the hook is absent, so this still works on the non-3-D surfaces. */
            await page
              .waitForFunction(() => window.__atlasScene?.stats?.().converged === true, null, { timeout: 8000 })
              .catch(() => page.waitForTimeout(2200));
            prepareError = null;
            break;
          } catch (e) {
            prepareError = String(e).slice(0, 200);
          }
        }

        const problems = await verifyRendered(page, st).catch((e) => [`verify failed: ${String(e).slice(0, 160)}`]);
        if (prepareError !== null) problems.push(`could not prepare the page in 3 attempts: ${prepareError}`);
        if (attempts > 0) problems.push(`the page reloaded under the harness; captured on attempt ${attempts + 1}`);
        if (consoleErrors.length) problems.push(`console: ${consoleErrors.slice(0, 3).join(" | ")}`);

        /* Record WHICH quality tier and renderer produced each frame. A reviewer comparing two
           captures has to be able to tell a design change from a tier change, and a capture that
           silently ran on a software renderer would otherwise look like a design regression. */
        const render = await page.evaluate(() => {
          const s = window.__atlasScene?.stats?.();
          const c = document.createElement("canvas").getContext("webgl2");
          const dbg = c?.getExtension("WEBGL_debug_renderer_info");
          return {
            quality: s?.quality ?? null,
            drawCalls: s?.drawCalls ?? null,
            converged: s?.converged ?? null,
            renderer: c && dbg ? String(c.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) : null,
          };
        });
        if (render.quality !== null && render.quality !== "high") {
          problems.push(`rendered at quality tier "${render.quality}" (${render.renderer ?? "unknown GPU"})`);
        }

        const file = resolve(outRoot, theme, vp.id, `${st.id}.png`);
        await shoot(page, file);
        const rec = { ...st, theme, viewport: vp.id, file, url, render, attempts: attempts + 1, problems };
        written.push(rec);
        if (problems.length) {
          failures.push(`${theme}/${vp.id}/${st.id}: ${problems.join("; ")}`);
          console.log(`  BAD  ${theme}/${vp.id}/${st.id} — ${problems.join("; ")}`);
        }
      }
      await ctx.close();
    }
  }
  await browser.close();
  mkdirSync(outRoot, { recursive: true });
  writeFileSync(resolve(outRoot, "index.json"), JSON.stringify(written, null, 1));
  console.log(`captured ${written.length} app frames -> ${outRoot}`);
  if (failures.length) {
    console.log(`\n${failures.length} of ${written.length} frames did NOT render properly:`);
    for (const f of failures) console.log(`  ${f}`);
    // Non-zero so a review round cannot start on broken captures without someone noticing.
    process.exitCode = 3;
  }
  return { written, failures };
}

/* ── F6: two runs produce byte-identical captures ─────────────────────────────────────────────
 *
 * WHY THIS EXISTS. Acceptance F6 reads "No `Math.random()` or `Date.now()` in rendered output
 * paths; two runs produce byte-identical captures", and its stated evidence is "capture twice,
 * compare hashes". Nothing in this repository did that. The half that WAS gated —
 * `src/core/determinism.test.ts` — is a syntactic scan of `src/`, and it was green while the
 * property was false: two consecutive `capture.mjs app` runs on 2026-09-21 differed in 23 of 32
 * frames, because `scene.ts`'s frame rate reached the status bar as a rAF callback PARAMETER,
 * which is not a call and so was invisible to it. A criterion whose evidence is a measurement
 * nobody performs is not a criterion; it is a sentence.
 *
 * So this mode performs it. Capture, re-capture into a second directory, hash every PNG, and exit
 * non-zero on any difference — naming the files, so the next person starts from the fault rather
 * than from the discovery that there is one.
 *
 * It is deliberately a WHOLE-FRAME comparison of the real product in a real browser. The unit
 * suite can prove that the status line draws no digit; only this can prove that the picture is the
 * same picture. Neither is a substitute for the other, and both are cited by F6. */

function sha256(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

/** Every PNG under `root`, keyed by its path relative to `root` in POSIX form. */
function pngs(root, dir = root, out = new Map()) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) pngs(root, p, out);
    else if (p.endsWith(".png")) out.set(relative(root, p).split("\\").join("/"), p);
  }
  return out;
}

async function captureTwice() {
  const root = resolve(SHOTS, "_twice");
  rmSync(root, { recursive: true, force: true });
  const a = resolve(root, "a");
  const b = resolve(root, "b");

  console.log("run 1 of 2");
  const first = await captureApp(a);
  console.log("run 2 of 2");
  const second = await captureApp(b);

  /* A run that did not render is not evidence of determinism either way. Two blank pages hash
     identically, and reporting that as F6 satisfied is the exact failure this repository calls
     "absence rendered as health". */
  if (first.failures.length || second.failures.length) {
    console.log(
      `\nF6 NOT ESTABLISHED: ${first.failures.length + second.failures.length} frame(s) did not ` +
        `render properly, so the comparison below says nothing about determinism.`,
    );
    process.exitCode = 3;
    return;
  }

  const left = pngs(a);
  const right = pngs(b);
  const missing = [...left.keys()].filter((k) => !right.has(k)).concat([...right.keys()].filter((k) => !left.has(k)));
  const differing = [];
  const hashes = {};
  for (const [rel, file] of left) {
    if (!right.has(rel)) continue;
    const h1 = sha256(file);
    const h2 = sha256(right.get(rel));
    hashes[rel] = { run1: h1, run2: h2, identical: h1 === h2 };
    if (h1 !== h2) differing.push(rel);
  }

  writeFileSync(
    resolve(root, "index.json"),
    JSON.stringify({ frames: left.size, differing, missing, hashes }, null, 1),
  );

  // A capture set that is EMPTY compares clean. Say so rather than printing a green line.
  if (left.size === 0) {
    console.log("\nF6 NOT ESTABLISHED: no frames were captured, so nothing was compared.");
    process.exitCode = 3;
    return;
  }
  if (missing.length) {
    console.log(`\nF6 FAILS: ${missing.length} file(s) exist in only one run:\n  ${missing.join("\n  ")}`);
    process.exitCode = 3;
    return;
  }
  if (differing.length) {
    console.log(`\nF6 FAILS: ${differing.length} of ${left.size} frames differ between two runs:`);
    for (const rel of differing) {
      console.log(`  ${rel}\n    run1 ${hashes[rel].run1}\n    run2 ${hashes[rel].run2}`);
    }
    console.log(`\nhashes -> ${resolve(root, "index.json")}`);
    process.exitCode = 3;
    return;
  }
  console.log(`\nF6: ${left.size} of ${left.size} frames byte-identical across two runs.`);
  console.log(`hashes -> ${resolve(root, "index.json")}`);
}

async function captureRefs() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
  });
  const page = await ctx.newPage();
  const written = [];
  for (const r of REFS) {
    try {
      await page.goto(r.url, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.waitForTimeout(r.wait);
      // Dismiss the obvious consent overlays so the capture shows the product, not a banner.
      for (const sel of ['button:has-text("Accept")', 'button:has-text("Got it")', '[aria-label="Close"]']) {
        const el = page.locator(sel).first();
        if (await el.count().catch(() => 0)) await el.click({ timeout: 1500 }).catch(() => {});
      }
      await page.waitForTimeout(1200);
      const file = resolve(SHOTS, "refs", `${r.id}.png`);
      await shoot(page, file);
      written.push({ id: r.id, url: r.url, file, ok: true });
      console.log(`  ok   ${r.id}`);
    } catch (e) {
      // A reference we could not capture must be RECORDED as uncaptured, never quietly skipped —
      // a critic must know it compared against 9 references, not 11.
      written.push({ id: r.id, url: r.url, file: null, ok: false, error: String(e).slice(0, 300) });
      console.log(`  FAIL ${r.id}: ${String(e).slice(0, 120)}`);
    }
  }
  await browser.close();
  mkdirSync(resolve(SHOTS, "refs"), { recursive: true });
  writeFileSync(resolve(SHOTS, "refs", "index.json"), JSON.stringify(written, null, 1));
  const ok = written.filter((w) => w.ok).length;
  console.log(`captured ${ok}/${REFS.length} reference frames -> ${resolve(SHOTS, "refs")}`);
}

/**
 * `node review/capture.mjs reduced` — the evidence acceptance D7 asks for.
 *
 * The app pass above pins `reducedMotion: "no-preference"` AND injects FREEZE_CSS, so it can never
 * say anything about the preference: it photographs an app whose animations were switched off by
 * the harness rather than by the user's setting. D7 was therefore UNPROVEN, which is a fail — and
 * the half that is easy to break is the WebGL half, a JavaScript boolean no stylesheet dump shows.
 *
 * So this pass forces the media feature through the browser context (the only place it can really
 * be set), takes NO freeze CSS, and MEASURES rather than eyeballs: it asks the live scene to frame
 * a device and samples that device's projection frame by frame. Under `reduce` the camera must land
 * on the first frame; the control run at `no-preference` must take several. Both are printed, and a
 * reduced run that animates exits non-zero.
 */
async function captureReduced() {
  const browser = await chromium.launch({ args: GPU_ARGS });
  const out = [];
  for (const motion of ["reduce", "no-preference"]) {
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
      colorScheme: "dark",
      reducedMotion: motion,
    });
    const page = await ctx.newPage();
    const st = APP_STATES.find((s) => s.id === "06-path-blocked") ?? APP_STATES[0];
    await page.goto(`${APP}/${st.q ? "?" + st.q : ""}`, { waitUntil: "networkidle" });
    await page.evaluate(() => document.fonts?.ready);
    await page
      .waitForFunction(() => window.__atlasScene?.stats?.().converged === true, null, { timeout: 8000 })
      .catch(() => page.waitForTimeout(2200));

    const measured = await page.evaluate(async () => {
      const css = getComputedStyle(document.documentElement);
      const s = window.__atlasScene;
      const series = [];
      if (s) {
        s.resetCamera({ immediate: true });
        await new Promise((r) => requestAnimationFrame(r));
        s.focusDevice("core1");
        for (let i = 0; i < 24; i += 1) {
          await new Promise((r) => requestAnimationFrame(r));
          const p = s.project("core1");
          series.push(p ? `${Math.round(p.x)},${Math.round(p.y)}` : "null");
        }
      }
      return {
        mediaMatches: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        durCamera: css.getPropertyValue("--dur-camera").trim(),
        durMedium: css.getPropertyValue("--dur-medium").trim(),
        // How many DISTINCT camera poses the device was projected through: 1 means it jumped.
        cameraPoses: new Set(series).size,
        sceneHandle: Boolean(s),
      };
    });

    const file = resolve(SHOTS, "reduced-motion", `${motion}.png`);
    await shoot(page, file);
    out.push({ motion, file, ...measured });
    console.log(`  ${motion}: media=${measured.mediaMatches} --dur-camera=${measured.durCamera} cameraPoses=${measured.cameraPoses}`);
    await ctx.close();
  }
  await browser.close();
  mkdirSync(resolve(SHOTS, "reduced-motion"), { recursive: true });
  writeFileSync(resolve(SHOTS, "reduced-motion", "index.json"), JSON.stringify(out, null, 1));

  const reduced = out.find((o) => o.motion === "reduce");
  const control = out.find((o) => o.motion === "no-preference");
  const problems = [];
  if (!reduced?.mediaMatches) problems.push("the reduce context did not report the media feature");
  if (!reduced?.sceneHandle) problems.push("no scene handle: the WebGL half was not exercised at all");
  if ((reduced?.cameraPoses ?? 0) !== 1) problems.push(`camera moved through ${reduced?.cameraPoses} poses under reduce`);
  // Without a control that DOES animate, the check above would pass against a dead renderer.
  if ((control?.cameraPoses ?? 0) < 2) problems.push(`control run did not animate (${control?.cameraPoses} poses) — the measurement proves nothing`);
  if (problems.length) {
    console.log(`\nD7 NOT satisfied:\n  ${problems.join("\n  ")}`);
    process.exitCode = 3;
  } else {
    console.log(`D7: camera lands in one frame under reduce, ${control?.cameraPoses} poses without it.`);
  }
}

const mode = process.argv[2];
if (mode === "app") await captureApp();
else if (mode === "refs") await captureRefs();
else if (mode === "reduced") await captureReduced();
else if (mode === "twice") await captureTwice();
else {
  console.error("usage: node review/capture.mjs app|refs|reduced|twice");
  process.exit(2);
}
