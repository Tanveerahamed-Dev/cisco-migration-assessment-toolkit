#!/usr/bin/env node
/* Verification harness for fabric.html.
 *
 *   node docs/prototypes/fabric/verify.mjs        # exits 0 on pass, 1 on failure
 *
 * Needs a playwright with a downloaded chromium. It looks in the two places this
 * repo already keeps one (.ds-sync/ from the design-sync skill, and
 * webapp/frontend/) and tells you what to install if neither is present, rather
 * than dying on a bare import.
 *
 * WHY THIS EXISTS. The engine makes claims that are easy to assert and hard to
 * believe — "two draw calls", "bundling is free", "absence is drawn louder than
 * health". Every one of them was WRONG at some point during development, and in
 * each case the thing that caught it was a measurement, not a re-read:
 *   - a "worst case 0.337 ms" that was really a frame painting 0.00% of the buffer;
 *   - a bench that reported mode:"gpu", draws:2 while the GL context was dead and
 *     the SVG path had silently run instead;
 *   - not-observed devices rendering 2.8-3.5x QUIETER than healthy ones, which is
 *     the exact failure this visualization exists to prevent.
 * So this file is the gate. If it does not run, the claims are unverified.
 *
 * NOTE ON TIMING. Under SwiftShader (software rasteriser) the correctness results
 * are valid but the frame times are NOT hardware figures. Perf assertions here are
 * deliberately loose; treat the numbers as smoke, not as a benchmark.
 */
import { createRequire } from "node:module";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join, extname } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..", "..", "..");

function findPlaywrightCandidates() {
  const candidates = [];
  for (const base of [join(REPO, "webapp", "frontend"), join(REPO, ".ds-sync"), REPO]) {
    const p = join(base, "node_modules", "playwright", "index.mjs");
    if (existsSync(p)) candidates.push({ base, url:pathToFileURL(p).href });
  }
  return candidates;
}
const pwCandidates = findPlaywrightCandidates();
if (!pwCandidates.length) {
  console.error(
    "playwright not found. Install one with a chromium, e.g.:\n" +
    "  npm i --prefix .ds-sync playwright && node .ds-sync/node_modules/playwright/cli.js install chromium");
  process.exit(2);
}

/* Different local Playwright packages may expect different Chromium revisions.
   Importing a package is not proof that its browser exists, so try every candidate
   until one actually launches instead of letting a stale .ds-sync install mask the
   project-local package. */
const launchErrors = [];
let browser = null;
for (const candidate of pwCandidates) {
  try {
    const { chromium } = await import(candidate.url);
    browser = await chromium.launch({
      args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
    });
    break;
  } catch (error) {
    launchErrors.push(`${candidate.base}: ${error instanceof Error ? error.message : String(error)}`);
  }
}
if (!browser) {
  console.error("No installed Playwright candidate could launch Chromium:\n" + launchErrors.join("\n\n"));
  process.exit(2);
}

/* Serve this directory on an ephemeral port — no fixed port to collide with. */
const MIME = { ".html": "text/html; charset=utf-8", ".mjs": "text/javascript", ".js": "text/javascript" };
const server = createServer(async (req, res) => {
  const f = decodeURIComponent(req.url.split("?")[0]);
  try {
    const buf = await readFile(join(HERE, f === "/" ? "fabric.html" : f));
    res.writeHead(200, { "Content-Type": MIME[extname(f)] || "text/plain" });
    res.end(buf);
  } catch { res.writeHead(404); res.end("not found"); }
});
await new Promise(r => server.listen(0, "127.0.0.1", r));
const URL_ = `http://127.0.0.1:${server.address().port}/fabric.html`;

const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const pageErrors = [];
page.on("pageerror", e => pageErrors.push(String(e)));
page.on("console", m => { if (m.type() === "error") pageErrors.push("console: " + m.text()); });
await page.goto(URL_, { waitUntil: "load" });
await page.waitForFunction(() => !!window.__fabric, null, { timeout: 30000 });

const checks = [];
const check = (name, pass, detail) => { checks.push({ name, pass, detail }); };

/* Copy is a correctness surface too: an exact count in the solved graph is neither
   an upper nor a lower bound on a partially collected real network. Keep both the
   README explanation and the inspector copy explicit about scope and uncertainty. */
const readmeCopy = (await readFile(join(HERE, "README.md"), "utf8")).toLowerCase();
const htmlCopy = (await readFile(join(HERE, "fabric.html"), "utf8")).toLowerCase();
const scoped = text => text.includes("resolved topology") &&
                       text.includes("may be smaller") && text.includes("or larger") &&
                       text.includes("deterministic reference anchor") &&
                       text.includes("[reference anchor]") && text.includes("[outside baseline]");
const unsafe = text => text.includes("stated as an upper bound") ||
                       text.includes("strands &le;") || text.includes("every count is stated as a bound");
check("coverage copy scopes counts and both directions of uncertainty",
      scoped(readmeCopy) && scoped(htmlCopy) && !unsafe(readmeCopy) && !unsafe(htmlCopy),
      JSON.stringify({ readmeScoped:scoped(readmeCopy), htmlScoped:scoped(htmlCopy),
                       readmeUnsafe:unsafe(readmeCopy), htmlUnsafe:unsafe(htmlCopy) }));

const env = await page.evaluate(() => window.__fabric.stats());
check("WebGL2 context available", env.glReady, JSON.stringify(env));

if (env.glReady) {
  /* 1. beta = 0 must reproduce straight lines EXACTLY. Holten Eq.1 places the
        interior control points at the Greville abscissae i/3 of the chord, and
        Bezier curves have linear precision — so this is an exact identity, not a
        tolerance. It is the only reason the bundling maths can be trusted. */
  const oracle = await page.evaluate(() => {
    const fb = window.__fabric; fb.set(3000, 85);
    const bez = (p0,p1,p2,p3,t) => { const u=1-t; return u*u*u*p0+3*u*u*t*p1+3*u*t*t*p2+t*t*t*p3; };
    let nan = 0, off = 0, worst = 0, n = 0, intra = 0, intraOk = 0;
    const st = fb.stats();
    for (let e = 0; e < st.m; e++) {
      const c = fb.ctrlAt(e);
      if (![c.c1x,c.c1y,c.c2x,c.c2y].every(Number.isFinite)) { nan++; continue; }
      if (e % 7) continue;
      const s = fb.segAt(e); n++;
      const L1x=s.ax+(s.bx-s.ax)/3, L1y=s.ay+(s.by-s.ay)/3;
      const L2x=s.ax+2*(s.bx-s.ax)/3, L2y=s.ay+2*(s.by-s.ay)/3;
      for (const t of [0.13,0.25,0.5,0.77,0.91]) {
        const d = Math.hypot(bez(s.ax,L1x,L2x,s.bx,t) - (s.ax+(s.bx-s.ax)*t),
                             bez(s.ay,L1y,L2y,s.by,t) - (s.ay+(s.by-s.ay)*t));
        if (d > worst) worst = d;
        if (d > 1e-6) off++;
      }
    }
    for (let e = 0; e < st.m && intra < 300; e++) {
      const s = fb.segAt(e); if (s.ay !== s.by) continue; intra++;
      const c = fb.ctrlAt(e);
      if (Math.abs(c.c1x-(s.ax+(s.bx-s.ax)/3)) < 1e-4 && Math.abs(c.c1y-s.ay) < 1e-4) intraOk++;
    }
    return { nan, sampled:n, off, worst, intra, intraOk };
  });
  check("bundling: no NaN control points", oracle.nan === 0, `nan=${oracle.nan}`);
  check("bundling: beta=0 is exactly the chord (linear precision)",
        oracle.off === 0, `${oracle.sampled} edges x5 t, offChord=${oracle.off}, worst=${oracle.worst.toExponential(2)}`);
  check("bundling: intra-lane edges stay straight",
        oracle.intra === 0 || oracle.intraOk === oracle.intra, `${oracle.intraOk}/${oracle.intra}`);

  /* 2. For every ASSESSABLE device, stranding others is equivalent to being an
        articulation point. The reference anchor and nodes outside its baseline are
        deliberately excluded: neither has a counterfactual count in this model. */
  const cross = await page.evaluate(() => {
    const fb = window.__fabric; fb.set(700, 84);
    let arts = 0, str = 0, viol = 0, skipped = 0;
    for (let i = 0; i < 700; i++) {
      const r = fb.strandOf(i), a = fb.isArt(i);
      if (r.status !== "assessed") { skipped++; continue; }
      const s = r.count;
      if (a) arts++;
      if (s > 0) { str++; if (!a) viol++; }
    }
    return { arts, str, viol, skipped };
  });
  check("counterfactual agrees with articulation points",
        cross.viol === 0 && cross.arts === cross.str,
        `assessedArts=${cross.arts} stranders=${cross.str} skipped=${cross.skipped} violations=${cross.viol}`);

  /* Rendered semantics, not source substrings. The actual fleet anchor, an anchor
        on a cycle (so "all nodes stranded" would be visibly absurd), and a node in
        a disconnected component must each land in their explicit #insp branch. */
  const realAnchor = await page.evaluate(() => {
    const fb = window.__fabric; fb.set(700, 84);
    const anchor = fb.anchor(); fb.select(anchor);
    const box = document.querySelector("#insp");
    return { anchor, result:fb.strandOf(anchor), text:box.innerText,
             hero:box.querySelector(".hero")?.textContent || null,
             named:box.querySelector("code")?.textContent || null };
  });
  check("rendered inspector marks the real reference anchor unassessable",
        realAnchor.result.status === "reference-anchor" && realAnchor.result.count === null &&
        realAnchor.text.includes("[REFERENCE ANCHOR]") && realAnchor.text.includes("UNASSESSABLE") &&
        realAnchor.named === realAnchor.hero && !realAnchor.text.includes("strands (resolved)"),
        JSON.stringify(realAnchor));

  const cycleAnchor = await page.evaluate(() => window.__fabric.verifyFailureFixture({
    ids:["CYCLE-ANCHOR", "CYCLE-B", "CYCLE-C"],
    edges:[[0,1], [1,2], [2,0]], selected:0,
  }));
  check("rendered inspector does not strand a cycle tautologically when its anchor is selected",
        cycleAnchor.anchor === cycleAnchor.selected && !cycleAnchor.anchorIsArt &&
        cycleAnchor.status === "reference-anchor" && cycleAnchor.count === null &&
        cycleAnchor.text.includes("[REFERENCE ANCHOR]") && cycleAnchor.text.includes("unassessable") &&
        !cycleAnchor.text.includes("strands (resolved)"), JSON.stringify(cycleAnchor));

  const outside = await page.evaluate(() => window.__fabric.verifyFailureFixture({
    ids:["BASE-ANCHOR", "BASE-B", "BASE-C", "ISLAND-A", "ISLAND-B"],
    edges:[[0,1], [1,2], [2,0], [3,4]], selected:3,
  }));
  check("rendered inspector marks a disconnected selection outside baseline, not zero",
        outside.anchor !== outside.selected && !outside.selectedInBaseline &&
        outside.status === "outside-baseline" && outside.count === null &&
        outside.text.includes("[OUTSIDE BASELINE]") && outside.text.includes("unassessable") &&
        outside.text.includes("cannot be reported as a zero-impact result") &&
        !outside.text.includes("strands no others"), JSON.stringify(outside));

  /* 3. Picking must never miss a device that is inside the requested radius. */
  const pick = await page.evaluate(() => {
    const fb = window.__fabric; fb.set(3000, 85);
    const st = fb.stats(); let wrong = 0, tested = 0;
    for (const k of [0.04, 0.15, 0.307, 1.0]) {
      fb.cam().k = k;
      const radius = Math.max(22, 26 / k);
      for (let t = 0; t < 300; t++) {
        const i = (t * 7919) % st.n, p = fb.nodePos(i);
        const wx = p.x + ((t % 5) - 2), wy = p.y + ((t % 3) - 1);
        const got = fb.pickAt(wx, wy, radius); tested++;
        if (got === -1) { wrong++; continue; }
        const q = fb.nodePos(got);
        if (Math.hypot(q.x-wx, q.y-wy) > Math.hypot(p.x-wx, p.y-wy) + 1e-3) wrong++;
      }
    }
    return { tested, wrong };
  });
  check("picking is exact across the zoom range", pick.wrong === 0, `${pick.wrong} wrong of ${pick.tested}`);

  /* 4. Absence must not be quieter than health, on EITHER ground. */
  const loud = await page.evaluate(async () => {
    const fb = window.__fabric;
    const measure = () => {
      fb.set(300, 55);
      const st = fb.stats(); let h = -1, n = -1;
      for (let i = 0; i < st.n; i++) {
        const k = fb.evidence(i);
        if (h < 0 && k === "healthy") h = i;
        if (n < 0 && k === "not-observed") n = i;
        if (h >= 0 && n >= 0) break;
      }
      const bg = fb.bgRgb(), d = c => Math.hypot(c[0]-bg[0], c[1]-bg[1], c[2]-bg[2]);
      const probe = i => { fb.bench({ iters:1, w:900, h:600, keepView:true, centreOn:fb.nodePos(i), zoom:9 });
                           return fb.readCentre(40, 20); };
      return { healthy: d(probe(h)), notObserved: d(probe(n)) };
    };
    const out = {};
    for (const theme of ["dark", "light"]) {
      document.documentElement.setAttribute("data-theme", theme);
      await new Promise(r => setTimeout(r, 80));
      const m = measure(); out[theme] = +(m.notObserved / Math.max(1, m.healthy)).toFixed(2);
    }
    return out;
  });
  check("absence is at least as loud as health (dark)", loud.dark >= 0.98, `ratio=${loud.dark}`);
  check("absence is at least as loud as health (light)", loud.light >= 0.98, `ratio=${loud.light}`);

  /* 5. A frame that painted nothing must never be reported as a timing. */
  const honesty = await page.evaluate(() => {
    const fb = window.__fabric; fb.set(2000, 84);
    fb.bench({ iters:2, w:1200, h:800, keepView:true }); fb.fitView(); fb.cam().k *= 40;  // off-screen
    const blank = fb.bench({ iters:5, w:1200, h:800 });
    fb.setMode("dom");
    const svg = fb.bench({ iters:3, w:1200, h:800 });
    fb.setMode("gpu");
    return { blankPainted: blank.paintedPct, blankNote: blank.note || null,
             svgSubstrate: svg.substrate, svgDraws: svg.draws, svgElements: svg.svgElements };
  });
  check("bench flags a frame that painted nothing",
        honesty.blankPainted !== 0 || !!honesty.blankNote, JSON.stringify(honesty));
  check("SVG substrate never claims GPU draw calls",
        honesty.svgSubstrate === "svg" && honesty.svgDraws === null,
        `substrate=${honesty.svgSubstrate} draws=${honesty.svgDraws} elements=${honesty.svgElements}`);

  /* 6. Context loss must restore AND must not leave a second render loop running. */
  const ctx = await page.evaluate(async () => {
    const fb = window.__fabric; fb.set(1500, 84);
    const tick = () => new Promise(r => requestAnimationFrame(() => r()));
    const rate = async () => { const a = fb.frameRuns(); for (let i=0;i<15;i++) await tick();
                               return +((fb.frameRuns()-a)/15).toFixed(2); };
    const before = await rate();
    const ev = await fb.loseAndRestore();
    await fb.loseAndRestore(); await fb.loseAndRestore();
    const after = await rate();
    fb.bench({ iters:2, w:900, h:600, keepView:true }); fb.fitView();
    const post = fb.bench({ iters:8, w:900, h:600 });
    return { ok: ev.ok, before, after, painted: post.paintedPct, substrate: post.substrate };
  });
  check("context restores and redraws", ctx.ok && ctx.substrate === "gpu" && ctx.painted > 5,
        `painted=${ctx.painted}% substrate=${ctx.substrate}`);
  check("render loop does not fork across restores", ctx.after <= ctx.before * 1.25 + 0.05,
        `framesPerTick ${ctx.before} -> ${ctx.after} after 3 losses`);

  /* 7. Same fleet, same picture — engineers compare snapshots. */
  const det = await page.evaluate(() => {
    const fb = window.__fabric; fb.set(1500, 80); const a = fb.layoutSig();
    fb.set(900, 70); fb.set(1500, 80); return { a, b: fb.layoutSig() };
  });
  check("layout is deterministic", det.a === det.b, `${det.a} vs ${det.b}`);
}

check("no page or console errors", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));

await browser.close();
await new Promise(r => server.close(r));

const failed = checks.filter(c => !c.pass);
for (const c of checks) console.log(`${c.pass ? "PASS" : "FAIL"}  ${c.name}${c.detail ? "  — " + c.detail : ""}`);
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`);
process.exit(failed.length ? 1 : 0);
