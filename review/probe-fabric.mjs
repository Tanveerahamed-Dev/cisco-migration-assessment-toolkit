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
