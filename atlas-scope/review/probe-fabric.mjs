/**
 * probe-fabric.mjs — is the 3-D fabric actually rendering, in the browser the review harness uses?
 *
 * A clean Playwright context, so nothing here is a stale HMR module or a cumulative console buffer.
 * It answers three questions the critique loop depends on and that a screenshot alone cannot:
 *   1. does a WebGL2 context exist at all in this environment;
 *   2. did the scene reach `converged`, which is the signal capture.mjs waits on;
 *   3. is the canvas drawing anything, or is it a uniform field of background colour.
 *
 * (3) matters because a blank canvas photographs identically to a working one that happens to be
 * looking at empty space, and handing a critic a blank frame burns a whole review round.
 */
import { chromium } from "@playwright/test";
import { awaitPaletteWarm } from "./palette-warm.mjs";

/*
 * --hairline: acceptance C5 item 8 ("1px hairline links"), as a detector rather than a look.
 *
 * `node review/probe-fabric.mjs --hairline` (ATLAS_URL = the app root, default :4180; ATLAS_TIERS,
 * default "high,low"; ATLAS_VIEWPORT, default "1440x900") photographs the canvas at DSF 2 in both
 * themes with the label layer and the HUD hidden, and looks for the defect's exact shape: a run of
 * ONE device pixel of ink with the stage's own ground on both sides, continuing (shifting at most a
 * pixel per step, gaps of up to 3 allowed, so a DASHED sliver counts) for at least 24 rows or
 * columns. The ground is the most common luma of a 32 px tile, and only tiles whose mode is within
 * 24 of the whole canvas's mode count as ground — so the dark seam where two lit cable tubes abut
 * (ink on both sides) is not a stroke, and neither is anything inside a chassis.
 * MEASURED (2026-09-24, overview, 1440x900, dark/light x high/low): the pre-fix tree held 3 such
 * chains in every leg, one of them 185 rows through (806, 400) — the grader's hairline; the fixed
 * tree holds 0. Exit 1 when any chain is found.
 */
if (process.argv.includes("--hairline")) {
  const app = (process.env.ATLAS_URL || "http://localhost:4180").replace(/\/$/, "");
  const tiers = (process.env.ATLAS_TIERS || "high,low").split(",");
  const [vw, vh] = (process.env.ATLAS_VIEWPORT || "1440x900").split("x").map(Number);
  const hb = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  let found = 0;
  for (const theme of ["dark", "light"]) {
    for (const tier of tiers) {
      const ctx = await hb.newContext({ viewport: { width: vw ?? 1440, height: vh ?? 900 }, deviceScaleFactor: 2, colorScheme: theme });
      const page = await ctx.newPage();
      await page.goto(`${app}/?__atlasScene=1`, { waitUntil: "networkidle", timeout: 120000 });
      await page.waitForFunction(() => window.__atlasScene?.stats?.().converged === true, null, { timeout: 60000 });
      await awaitPaletteWarm(page);
      await page.evaluate((t) => window.__atlasScene?.setQuality?.(t), tier);
      await page.waitForTimeout(4000);
      await page.waitForFunction(() => window.__atlasScene?.stats?.().converged === true, null, { timeout: 60000 });
      await page.addStyleTag({ content: ".fabric3d__labels,.fabric3d__hud{visibility:hidden!important}" });
      await page.waitForTimeout(1200);
      const clip = await page.evaluate(() => {
        const r = document.querySelector(".fabric3d canvas")?.getBoundingClientRect();
        return r ? { x: r.x, y: r.y, width: r.width, height: r.height } : null;
      });
      if (clip === null) throw new Error("no fabric canvas on the page");
      const png = await page.screenshot({ clip, scale: "device", timeout: 180000 });
      const chains = await page.evaluate(async (b64) => {
        const img = new Image();
        img.src = "data:image/png;base64," + b64;
        await img.decode();
        const w = img.naturalWidth;
        const h = img.naturalHeight;
        const off = document.createElement("canvas");
        off.width = w;
        off.height = h;
        const g = off.getContext("2d");
        if (!g) return [];
        g.drawImage(img, 0, 0);
        const d = g.getImageData(0, 0, w, h).data;
        const L = new Uint8Array(w * h);
        for (let i = 0; i < w * h; i += 1) L[i] = (d[i * 4] * 299 + d[i * 4 + 1] * 587 + d[i * 4 + 2] * 114) / 1000;
        const mode = (x0, y0, x1, y1) => {
          const hist = new Uint32Array(256);
          for (let y = y0; y < y1; y += 1) for (let x = x0; x < x1; x += 1) hist[L[y * w + x]] += 1;
          let best = 0;
          for (let v = 1; v < 256; v += 1) if (hist[v] > hist[best]) best = v;
          return best;
        };
        const T = 32;
        const G = mode(0, 0, w, h);
        const tw = Math.ceil(w / T);
        const tiles = [];
        for (let ty = 0; ty < h; ty += T) for (let tx = 0; tx < w; tx += T) {
          const m = mode(tx, ty, Math.min(w, tx + T), Math.min(h, ty + T));
          tiles.push(Math.abs(m - G) <= 24 ? m : -999);
        }
        const ground = (x, y) => tiles[Math.floor(y / T) * tw + Math.floor(x / T)];
        const TH = 18;
        const isoH = (x, y) => {
          if (x < 1 || x >= w - 1) return false;
          const l = L[y * w + x - 1], c = L[y * w + x], r = L[y * w + x + 1], gd = ground(x, y);
          return Math.abs(c - l) > TH && Math.abs(c - r) > TH && Math.abs(l - gd) <= 10 && Math.abs(r - gd) <= 10;
        };
        const isoV = (x, y) => {
          if (y < 1 || y >= h - 1) return false;
          const l = L[(y - 1) * w + x], c = L[y * w + x], r = L[(y + 1) * w + x], gd = ground(x, y);
          return Math.abs(c - l) > TH && Math.abs(c - r) > TH && Math.abs(l - gd) <= 10 && Math.abs(r - gd) <= 10;
        };
        const out = [];
        const walk = (major, minor, iso, name) => {
          const hits = new Set();
          for (let a = 0; a < major; a += 1) for (let b = 0; b < minor; b += 1) if (iso(a, b)) hits.add(a * 65536 + b);
          const seen = new Set();
          for (const k of [...hits].sort((p, q) => p - q)) {
            if (seen.has(k)) continue;
            let a = Math.floor(k / 65536), b = k % 65536, n = 0, gaps = 0;
            const start = [a, b];
            while (a < major && gaps <= 3) {
              let f = -1;
              for (const db of [0, -1, 1]) if (hits.has(a * 65536 + b + db)) { f = b + db; break; }
              if (f >= 0) { seen.add(a * 65536 + f); b = f; n += 1; gaps = 0; } else gaps += 1;
              a += 1;
            }
            if (n >= 24) out.push({ axis: name, length: n, at: start });
          }
        };
        walk(h, w, (y, x) => isoH(x, y), "vertical (y, x)");
        walk(w, h, (x, y) => isoV(x, y), "horizontal (x, y)");
        return out;
      }, png.toString("base64"));
      const tierNow = await page.evaluate(() => window.__atlasScene?.stats?.().quality ?? "unknown");
      console.log(`${theme}/${tier} (in force: ${tierNow}): ${chains.length} one-device-pixel chain(s)`);
      for (const c of chains.slice(0, 8)) console.log(`  ${c.axis} starting ${c.at.join(", ")}: ${c.length} steps`);
      found += chains.length;
      await ctx.close();
    }
  }
  await hb.close();
  console.log(found === 0 ? "VERDICT: no sub-2 px hairline on the fabric" : `VERDICT: ${found} hairline chain(s) found`);
  process.exit(found === 0 ? 0 : 1);
}

const URL_ = process.env.ATLAS_URL || "http://localhost:4180/fabric-preview.html";

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text().slice(0, 200));
});
page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));

await page.goto(URL_, { waitUntil: "networkidle", timeout: 45000 });

const caps = await page.evaluate(() => {
  const c = document.createElement("canvas");
  const gl = c.getContext("webgl2");
  if (!gl) return { webgl2: false };
  const dbg = gl.getExtension("WEBGL_debug_renderer_info");
  return { webgl2: true, renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "unknown" };
});
console.log("webgl2:", caps.webgl2, caps.renderer ? `(${caps.renderer})` : "");

const converged = await page
  .waitForFunction(() => window.__atlasScene?.stats?.().converged === true, null, { timeout: 20000 })
  .then(() => true)
  .catch(() => false);
/* The palette's pre-warm draws once after convergence (review/palette-warm.mjs): say where it stands. */
console.log(
  "palette pre-warm:",
  converged ? await awaitPaletteWarm(page).catch((e) => `NOT terminal: ${e instanceof Error ? e.message : String(e)}`) : "not waited (the scene never converged)",
);

const stats = await page.evaluate(() => {
  const s = window.__atlasScene?.stats?.();
  return s ? { fps: s.fps, frameMs: s.frameMs, drawCalls: s.drawCalls, triangles: s.triangles, quality: s.quality, converged: s.converged } : null;
});

/*
 * Did it actually DRAW? Measured from a real screenshot, not from the canvas.
 *
 * The obvious approach — `drawImage(canvas, …)` then `getImageData` — is wrong and wrong silently.
 * A WebGL context created with the default `preserveDrawingBuffer: false` discards its drawing
 * buffer once the frame is composited, so any later read returns empty. This probe originally did
 * exactly that and reported "the canvas is NOT drawing a scene" about a fabric that was rendering
 * perfectly. A blank-frame detector that cries blank on a good frame is worse than none: it would
 * have sent the critique loop chasing a renderer bug that did not exist.
 *
 * Screenshotting composites the page the same way a user sees it, then the PNG is decoded back
 * inside the browser — the one place that can decode it without adding a dependency.
 */
const shot = await page.screenshot({ type: "png" });
const pixels = await page.evaluate(async (b64) => {
  const img = new Image();
  img.src = "data:image/png;base64," + b64;
  await img.decode();
  const off = document.createElement("canvas");
  off.width = Math.min(600, img.naturalWidth);
  off.height = Math.min(400, img.naturalHeight);
  const g = off.getContext("2d");
  if (!g) return { ok: false, why: "no 2d context" };
  g.drawImage(img, 0, 0, off.width, off.height);
  const data = g.getImageData(0, 0, off.width, off.height).data;
  const seen = new Set();
  let nonBlack = 0;
  for (let i = 0; i < data.length; i += 4) {
    // Quantise to 5 bits per channel: distinguishes real shading from compression noise.
    const key = (data[i] >> 3) * 4096 + (data[i + 1] >> 3) * 64 + (data[i + 2] >> 3);
    seen.add(key);
    if (data[i] + data[i + 1] + data[i + 2] > 24) nonBlack++;
  }
  return {
    ok: true,
    w: img.naturalWidth,
    h: img.naturalHeight,
    distinctColours: seen.size,
    nonBlackFraction: Number((nonBlack / (data.length / 4)).toFixed(3)),
  };
}, shot.toString("base64"));

console.log("converged:", converged);
console.log("stats:", JSON.stringify(stats));
console.log("pixels:", JSON.stringify(pixels));
if (errors.length) {
  console.log(`console errors (${errors.length}):`);
  for (const e of errors.slice(0, 6)) console.log("  " + e);
} else {
  console.log("console errors: none");
}

const drew = pixels.ok && pixels.distinctColours > 50;
console.log(drew ? "VERDICT: the fabric is rendering" : "VERDICT: the canvas is NOT drawing a scene");
await browser.close();
process.exit(drew && errors.length === 0 ? 0 : 1);
