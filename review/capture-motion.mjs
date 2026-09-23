/**
 * capture-motion.mjs — frame-dense MOTION evidence for acceptance C5.
 *
 *     npm run build && npm run preview          # the release build on :4181 (see capture.mjs)
 *     node review/capture-motion.mjs            # all four legs: {dark,light} x {high,low} @ 1440x900
 *     node review/capture-motion.mjs --no-png   # analyse only, skip writing every frame to disk
 *
 * WHY THIS EXISTS. C5's static checklist passes at high and low, but four of its items are properties
 * of MOTION and were never captured frame by frame: z-fighting on coplanar surfaces while the camera
 * moves, LOD / effect / label popping, the ambient-occlusion drop and restore around a camera stop at
 * the high tier, and the quality-tier cross-fade (TIER_FADE_MS, under C6's 300 ms). A screenshot taken every ~250 ms cannot see
 * a one-frame pop (the tier-fade comment in scene.ts records exactly that mistake), so this harness
 * captures EVERY animation frame the scene renders and judges the sequence numerically.
 *
 * HOW A FRAME IS CAPTURED (and the two harness-side interventions it needs, stated):
 *
 *   1. `preserveDrawingBuffer: true` is forced on every WebGL context the page creates (init script).
 *      The default framebuffer is otherwise undefined after presentation, so the drawn frame could
 *      not be copied reliably. It changes buffer retention, not what is drawn: the renderer clears
 *      every frame itself (the composer's passes autoClear) — so pixels are the product's own.
 *   2. `requestAnimationFrame` is wrapped by a pump that runs the page's callbacks in registration
 *      order, exactly as the browser would, and THEN one harness hook. So the hook always runs after
 *      the scene's render for that frame, and the scene state it reads (`stats()`, `project()`) is
 *      the state that produced the pixels it copies. Without this, the hook's order relative to the
 *      scene's callback depends on who re-registered first.
 *
 *   The hook copies the WebGL canvas into a GPU-backed 2-D canvas (a GPU→GPU blit, cheap enough to
 *   keep the loop at display rate — the recorded rAF intervals prove it per sequence), composites the
 *   scene's own tier-fade overlay on top at the opacity the page reports for that frame (so the
 *   cross-fade is judged as SEEN, not as rendered underneath), and records per-frame metadata: the
 *   projected screen position of every device anchor (the camera-change signal), the quality tier,
 *   whether occlusion was suspended for that render, which DOM labels are visible, the hovered
 *   device, and the fade overlay's opacity. After each recorded sequence the frames are read back to
 *   Node as raw RGBA, written as PNG and analysed.
 *
 *   DOM labels are NOT in the canvas: their popping is judged from the per-frame visibility log.
 *
 * Reuses capture.mjs's GPU_ARGS, its server identification and its scene-handle opt-in (copied, not
 * imported: importing capture.mjs runs its CLI). Exit code: 0 only when every check PASSES; 3 on any
 * FAIL; 4 when a check could not be established (UNPROVEN) and nothing failed.
 */
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { crc32, deflateSync } from "node:zlib";
import { checkBuildFreshness } from "./build-freshness.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
/* Executed (`node review/capture-motion.mjs`), not imported: see `main` at the bottom. */
const IS_MAIN = typeof process.argv[1] === "string" && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
const OUT = resolve(HERE, "shots", "motion");
const APP = process.env.ATLAS_URL || "http://localhost:4181";
const WRITE_PNG = !process.argv.includes("--no-png");
const VIEWPORT = { width: 1440, height: 900 };
/* deviceScaleFactor 1: the canvas is then 760x790 at 1440x900 and a full-resolution frame can be
   copied on every rAF without the copy itself costing frames. The DPR the scene renders at is
   recorded in the report. */
const DSF = 1;
const THEMES = ["dark", "light"];
const TIERS = ["high", "low"];

/* ── copied from capture.mjs (see its comments for the reasoning) ─────────────────────────────── */
const GPU_ARGS = ["--use-gl=angle", "--disable-gpu-rasterization", "--ignore-gpu-blocklist"];

async function serverIdentity(url = APP) {
  try {
    const res = await fetch(url + "/");
    const html = await res.text();
    const mode = !res.ok ? "unknown" : html.includes("/@vite/client") ? "dev" : "build";
    return { url, mode };
  } catch (e) {
    return { url, mode: "unknown", error: String(e).slice(0, 200) };
  }
}

/* The tier cross-fade's duration and the eases' settle times are READ FROM THE SOURCE that owns
   them, not copied: a copy here is how the harness kept judging a 300 ms fade against "300 ms"
   after the question became "under 300 ms" (acceptance C6). */
const SRC_DIR = resolve(HERE, "..", "src");
function constFrom(file, name) {
  const text = readFileSync(resolve(SRC_DIR, file), "utf8");
  const m = new RegExp(`const\\s+${name}\\s*=\\s*(\\d+(?:\\.\\d+)?)\\s*;`).exec(text);
  if (!m) throw new Error(`capture-motion: ${name} not found in src/${file} — the harness cannot state its bar`);
  return Number(m[1]);
}
const TIER_FADE_MS = constFrom("fabric3d/scene.ts", "TIER_FADE_MS");
const RECEDE_MS = constFrom("fabric3d/emphasis.ts", "RECEDE_MS");
/** Acceptance C6: every animation except a deliberate camera move ends under this. */
const C6_BAR_MS = 300;
const FRAME_60_MS = 1000 / 60;

/* ── THRESHOLDS — each one stated, and why ─────────────────────────────────────────────────────
 *
 * Luma is Rec.709 over 8-bit sRGB values (0-255). "Still" means the camera did not change between
 * two frames: no device anchor moved by more than STILL_PX.
 */
export const T = {
  /* EXACTLY zero. The first draft used 0.02 px, reasoning that no pixel can change for a smaller
     move; the first run refuted it: OrbitControls' damping tail keeps moving the camera by 0.01 ->
     0.0001 px per frame for ~1 s after a release, and those frames still changed hundreds of pixels
     by up to 160/255. So "still" means the camera did not change AT ALL (every projected anchor equal
     at full float precision), and sub-pixel tail frames are judged as motion (z-fighting/shimmer). */
  STILL_PX: 0,
  /* SEQUENCE DENSITY. The task requires at least 30 frames per second of motion; a sequence whose
     median frame interval is above 33.4 ms, or where more than 10 % of intervals exceed 50 ms (a
     dropped-frame gap long enough to hide a one-frame pop), is not dense evidence -> UNPROVEN. */
  MAX_MEDIAN_DT_MS: 33.4,
  MAX_GAP_MS: 50,
  MAX_GAP_SHARE: 0.1,
  /* STILL-FRAME POP. With the camera still, no emphasis animating and no fade, the scene is
     deterministic (acceptance F6: two captures are byte-identical), so two consecutive frames must
     be the same picture. 4/255 tolerates 8-bit rounding in the copy; 60 px (~0.01 % of the canvas,
     an 8x8 blob) is the smallest area we treat as a visible event. Anything above = a pop/flicker. */
  POP_DELTA: 4,
  POP_MAX_PIXELS: 60,
  /* Frames after a hover change are excluded from the still-frame pop check (the hover rim / recede
     easing is a designed transition: finite eases in emphasis.ts, the longest RECEDE_MS, whose end
     state is on screen within one frame of it) and counted separately. Read from the source, plus
     four frames of slack for a host that drops frames. */
  HOVER_SETTLE_MS: Math.ceil(RECEDE_MS + 5 * FRAME_60_MS),
  /* MOTION SPIKE. During motion every frame changes; a pop shows as ONE frame whose change is far
     above its neighbours' at the same camera speed. Frame change is normalised by the camera change
     (mean luma delta per px of anchor motion); a frame > 3x the median of its +-4 neighbours AND
     at least 1.0/255 mean luma change above that median is a spike. 3x is a stated bar, not a fitted
     one: each sequence reports the observed 99th percentile and maximum of this ratio
     (spikeRatioP99 / spikeRatioMax) so the margin between smooth motion and the bar is visible. The
     1.0/255 floor stops a near-still tail frame (mean change ~0.01) from reading as a spike. */
  SPIKE_RATIO: 3,
  SPIKE_MIN_EXCESS: 1.0,
  /* THE REFERENCE RATE HAS A FLOOR (acceptance report 2026-09-23, item 15). The reference is the
     median rate of the moving neighbours, and that median can be exactly 0: damping-tail frames move
     the anchors by 0.0001-0.01 px and change no pixel (in the 2026-09-22 run, 20-30 % of the moving
     frames of every orbit sequence). Divided by 0, every frame with any change became an infinite
     spike — the "Infinityx" FAIL at light/high dolly frame 59 — so the item could fail on ordinary
     motion. A neighbourhood that changed (almost) nothing says nothing about how much a frame at
     THIS camera speed should change, so the reference is floored at a rate that ordinary motion
     does not exceed a SPIKE_RATIO multiple of: across all 24 motion sequences of that run (2941
     moving frames) the largest change rate a smooth frame produced was 4.53 levels per px of anchor
     motion (p99 3.81), and 3 x 1.6 = 4.8 is above it. So a frame is a spike only when it changes
     more than SPIKE_RATIO times max(neighbour median, 1.6) levels per px, AND by SPIKE_MIN_EXCESS
     over its neighbours — a real pop among near-still frames still fails (src/fabric3d/
     render-c5-repairs.test.ts, known-answer cases both ways). Stated cost: where the neighbours'
     median is below 1.6 (dolly sequences run at ~0.7) the bar rises from 3x their rate to 4.8
     levels/px; the printed ratio is taken against the floored reference, so it stays finite. */
  SPIKE_NORM_FLOOR: 1.6,
  /* Z-FIGHTING. On frames where the camera moves slowly (every anchor moved <= SLOW_PX this frame
     AND last frame), real geometry cannot make a pixel go up-down-up: at <= 0.25 px/frame an edge,
     a 2 px cable or a periodic pattern of period >= 3 px (dashes, lid louvers) needs >= 6 frames per
     half-cycle, and its per-frame steps are small. (The first draft gated at 1.5 px/frame; the first
     run showed dashed cables and louvers alternating legitimately at that speed.) A pixel whose luma reverses
     direction (both steps >= FLIP_DELTA) FLIP_MIN_REVERSALS times within FLIP_WINDOW consecutive
     frame steps is flip-flopping. Isolated single pixels are anti-aliasing sparkle on sub-pixel
     edges (judged elsewhere in C5); z-fighting is a PATCH on a coplanar overlap, so the check fails
     on any 4-connected cluster of >= ZF_CLUSTER flip-flopping pixels (a 4x4 patch), or when
     flip-flopping pixels exceed ZF_MAX_SHARE of the canvas in total.
     The two rules are REPORTED as two items (2026-09-22), with unchanged thresholds and the same
     exit code, because they measure different things and the name was hiding which one failed. A
     per-cluster raycast at the recorded camera pose (scratch probe, recorded in open-issues) found
     no cluster ray that crossed two surfaces within 0.02 units — the clusters were a sub-pixel strip
     of the faceplate frame and cable joints — and the SHARE rule is carried, after both were fixed,
     by isolated single-pixel edge sparkle along cables (~60 %) and chassis edges (~30 %), which is
     aliasing, not a depth tie. A failing share is therefore printed as what it is.
     ATTRIBUTED (repair wave 2c, 2026-09-23): the sparkle is made by the SMAA stage, not by the
     scene. This harness, run unchanged on the dev build with ONLY SMAAEffect's blend weights cleared
     in-page after its weights pass, measured 7-65 flip px in all 8 orbit sequences (bar: 120 px of
     the 760x790 canvas) and 0 clusters >= ZF_CLUSTER, every item PASS, exit 0 — against 300-732 px
     with SMAA on. SMAA's per-frame edge/pattern decisions on 1-3 px features (analytically
     anti-aliased cables, state-ring curbs, faceplate strips) toggle as the damped orbit creeps. The
     intermittent 16x1 row on a near-horizontal cable (1 of 48 sequences) did not appear in that run
     and has the shape of SMAA's orthogonal long-edge blend, but one clean run of an intermittent
     cluster is not proof of its cause. The lever
     is src/fabric3d/postfx.ts (SMAA configuration / temporal stability), not geometry. */
  SLOW_PX: 0.25,
  FLIP_DELTA: 12,
  FLIP_MIN_REVERSALS: 3,
  FLIP_WINDOW: 6,
  ZF_CLUSTER: 16,
  ZF_MAX_SHARE: 0.0002,
  /* LABEL BLINK. Labels are shown/hidden, never faded (FabricLabels.tsx). A visibility run of
     <= LABEL_BLINK_FRAMES (5 frames ~ 83 ms at 60 Hz) between two opposite states is a blink: under
     ~100 ms a brief appearance registers as a flash rather than as a change of state. */
  LABEL_BLINK_FRAMES: 5,
  /* AO RESTORE (high tier). The scene suspends SSAO while the camera moves and restores it after it
     has held still for MOTION_HOLD_MS = 140 ms (scene.ts). Checks:
       - the drop must not happen on a still frame (it would be a pop with nothing to mask it);
       - the restore must happen, within AO_RESTORE_MAX_MS of the camera's last change (140 ms plus
         a generous 360 ms for a slow host) — a settled frame without AO is the wrong final frame;
       - the restore JUMP must stay under the visible-pop bar. The precedent is the C5 audit's own
         call on the tier swap: 3.61 % of the canvas changed in one frame was "a pop". The bar here is
         an order of magnitude stricter: FAIL when more than AO_MAX_SHARE (0.5 %) of the canvas
         changes by >= 8/255 in the restore frame, or more than AO_MAX_STRONG_SHARE (0.05 %) by
         >= 32/255 (a hard dark crease appearing at once). */
  AO_RESTORE_MAX_MS: 500,
  /* The DROP is masked only by a real move: when the camera moved less than half a pixel in the drop
     frame, the frame's geometry change is sub-pixel and its change is the effect itself, so the drop
     is judged by the same pop bar as the restore. */
  AO_MASK_PX: 0.5,
  AO_DELTA: 8,
  AO_MAX_SHARE: 0.005,
  AO_STRONG_DELTA: 32,
  AO_MAX_STRONG_SHARE: 0.0005,
  /* TIER CROSS-FADE. scene.ts: TIER_FADE_MS (read above), ease-in-out, started once the new tier's
     frames are ordinary. The measured fade (the frame before the overlay's opacity leaves 1 to the
     frame it is gone or <= 0.005) must be at least TIER_FADE_MS - 50 ms (the tail below 0.005 of an
     ease-in-out, plus a frame of start slop) and UNDER the C6 bar of 300 ms. The upper bound used
     to be 400 ms around a 300 ms fade, so a fade AT the ceiling passed here while the grading
     measured 299.9-300.1 ms and failed C6 on it. No single frame may carry more than
     FADE_MAX_STEP (0.25) of opacity — an ease-in-out over 18 frames peaks near 0.09/frame, so 0.25
     allows a dropped frame; the critic's "cut" was 0.92 -> 0.50 (0.42) and 0.94 -> 0.056. The
     composited picture must agree: no frame may carry more than FADE_MAX_PIXEL_SHARE (40 %) of the
     total pixel change from the old tier's picture to the new one. */
  FADE_MIN_MS: TIER_FADE_MS - 50,
  /* exclusive: a fade that lasts 300 ms is not under 300 ms */
  FADE_MAX_MS: C6_BAR_MS,
  FADE_MAX_STEP: 0.25,
  FADE_MAX_PIXEL_SHARE: 0.4,
  FADE_MIN_VISIBLE_DELTA: 0.1,
};

/* ── in-page instrumentation (init script; self-contained) ─────────────────────────────────── */
function instrument() {
  window.__atlasExposeScene = true;

  const getContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, attrs) {
    if (typeof type === "string" && type.startsWith("webgl")) attrs = { ...(attrs || {}), preserveDrawingBuffer: true };
    return getContext.call(this, type, attrs);
  };

  const nativeRAF = window.requestAnimationFrame.bind(window);
  let queue = new Map();
  let nextId = 1;
  let scheduled = false;
  const M = {
    recording: false,
    /* false = metadata only (no pixel copy): the control that separates a product stall from one the
       copy itself could cause. */
    copy: true,
    pool: [],
    frames: [],
    ids: null,
    label: null,
    hookErrors: 0,
  };
  window.__motion = M;

  function hook(ts) {
    if (!M.recording) return;
    const h0 = performance.now();
    try {
      const scene = window.__atlasScene;
      const c = document.querySelector(".fabric3d canvas, canvas");
      if (!scene || !c) return;
      const i = M.frames.length;
      let g = null;
      let buf = null;
      if (M.copy) {
        buf = M.pool[i];
        if (!buf || buf.width !== c.width || buf.height !== c.height) {
          buf = new OffscreenCanvas(c.width, c.height);
          M.pool[i] = buf;
        }
        g = buf.getContext("2d");
        g.globalAlpha = 1;
        g.clearRect(0, 0, buf.width, buf.height);
        g.drawImage(c, 0, 0);
      }
      const fadeEl = c.parentElement?.querySelector(".fabric3d__tier-fade") ?? null;
      let fade = null;
      if (fadeEl) {
        const op = Number(getComputedStyle(fadeEl).opacity);
        fade = { opacity: op, transition: fadeEl.style.transition || "" };
        if (g) {
          g.globalAlpha = op;
          g.drawImage(fadeEl, 0, 0, buf.width, buf.height);
          g.globalAlpha = 1;
        }
      }
      const s = scene.stats();
      const cam = [];
      for (const id of M.ids) {
        const p = scene.project(id);
        cam.push(p ? p.x : NaN, p ? p.y : NaN); /* full float precision: see STILL_PX */
      }
      let vis = "";
      let hover = null;
      for (const id of M.ids) {
        const el = document.querySelector(`.fabric3d-label[data-device="${CSS.escape(id)}"]`);
        vis += el && el.getAttribute("data-visible") !== "false" && el.getClientRects().length > 0 ? "1" : "0";
        if (el && el.getAttribute("data-state") === "hover") hover = id;
      }
      M.frames.push({
        i,
        ts,
        quality: s.quality,
        converged: s.converged,
        aoSuspended: (s.qualityReasons || []).some((r) => /ambient occlusion is suspended/.test(r)),
        framesTimed: s.framesTimed,
        sceneFrameMs: s.frameMs,
        hookMs: Math.round((performance.now() - h0) * 100) / 100,
        labelsShown: s.labelsShown,
        cam,
        vis,
        hover,
        fade,
        w: c.width,
        h: c.height,
      });
    } catch (e) {
      M.hookErrors += 1;
      M.lastHookError = String(e).slice(0, 200);
    }
  }

  function pump(ts) {
    scheduled = false;
    const q = queue;
    queue = new Map();
    for (const cb of q.values()) {
      try {
        cb(ts);
      } catch (e) {
        setTimeout(() => {
          throw e;
        });
      }
    }
    hook(ts);
    if (queue.size > 0 || M.recording) ensure();
  }
  function ensure() {
    if (!scheduled) {
      scheduled = true;
      nativeRAF(pump);
    }
  }
  window.requestAnimationFrame = (cb) => {
    const id = nextId++;
    queue.set(id, cb);
    ensure();
    return id;
  };
  window.cancelAnimationFrame = (id) => {
    queue.delete(id);
  };

  M.start = (label, ids) => {
    M.frames = [];
    M.ids = ids;
    M.label = label;
    M.recording = true;
    ensure();
  };
  M.stop = () => {
    M.recording = false;
    return M.frames.map((f) => ({ ...f }));
  };
  /** Raw RGBA of frame k as base64 (FileReader is native and fast for megabytes). */
  M.read = (k) =>
    new Promise((res, rej) => {
      const buf = M.pool[k];
      const f = M.frames[k];
      const data = buf.getContext("2d").getImageData(0, 0, f.w, f.h).data;
      const r = new FileReader();
      r.onload = () => res(String(r.result).slice(String(r.result).indexOf(",") + 1));
      r.onerror = () => rej(r.error);
      r.readAsDataURL(new Blob([data]));
    });
  M.release = () => {
    M.pool = [];
    M.frames = [];
  };
}

/* The settle condition from capture.mjs (readSettle), trimmed to what this harness needs. */
function readSettle() {
  const scene = window.__atlasScene;
  const stats = scene?.stats?.();
  const word = document.querySelector(".sb__converged")?.textContent ?? null;
  const warm = document.querySelector(".stage-warmup");
  const warmVisible = warm !== null && warm.getClientRects().length > 0;
  return {
    handle: Boolean(scene),
    converged: stats?.converged ?? null,
    quality: stats?.quality ?? null,
    ok: Boolean(scene) && stats?.converged === true && word === "settled" && !warmVisible,
  };
}

async function awaitSettled(page, capMs = 60000) {
  const t0 = Date.now();
  for (;;) {
    const st = await page.evaluate(readSettle).catch(() => null);
    if (st?.ok) return st;
    if (Date.now() - t0 > capMs) throw new Error(`not settled within ${capMs} ms: ${JSON.stringify(st)}`);
    await page.waitForTimeout(100);
  }
}

/* ── PNG writer (no decoder/encoder dependency in this package) ───────────────────────────────── */
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td) >>> 0);
  return Buffer.concat([len, td, crc]);
}
function encodePng(w, h, rgba, channels = 4) {
  const stride = w * channels;
  const raw = Buffer.alloc((stride + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (stride + 1)] = 0;
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8;
  ihdr[9] = channels === 4 ? 6 : 2;
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 3 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const luma = (rgba, n) => {
  const L = new Uint8Array(n);
  for (let p = 0, q = 0; p < n; p++, q += 4) L[p] = (rgba[q] * 0.2126 + rgba[q + 1] * 0.7152 + rgba[q + 2] * 0.0722 + 0.5) | 0;
  return L;
};

/* ── the recorded sequences, per leg ──────────────────────────────────────────────────────────── */
const sleep = (page, ms) => page.waitForTimeout(ms);

async function focusCanvas(page) {
  await page.evaluate(() => document.querySelector(".fabric3d canvas, canvas")?.focus());
}

/** Each entry: { id, run(page, box) } — the motion is scripted in real time around the recorder. */
const SEQUENCES = [
  {
    id: "orbit-drag",
    what: "pointer-drag orbit through the canvas (the gesture a reader makes), release, pointer off canvas, then hold still",
    async run(page, box) {
      await sleep(page, 450);
      const y = box.y + box.height * 0.82;
      const x0 = box.x + box.width * 0.2;
      await page.mouse.move(x0, y);
      await page.mouse.down();
      for (let k = 1; k <= 90; k++) {
        await page.mouse.move(x0 + k * 4, y - k * 0.4);
        await sleep(page, 16);
      }
      await page.mouse.up();
      await page.mouse.move(5, VIEWPORT.height - 5);
      /* 3 s, not 1.5: the first full run measured the damping tail still moving the camera
         (0.0005 px/frame) 1.5 s after release, so the stop and the AO restore fell outside the window. */
      await sleep(page, 3000);
    },
  },
  {
    id: "orbit-keys-slow",
    what: "Shift+Arrow keyboard orbit (15 deg steps with OrbitControls damping; no pointer over the canvas, so no hover), then hold still — the damping tail is the slow-motion window for z-fighting",
    async run(page) {
      await focusCanvas(page);
      await sleep(page, 450);
      for (let k = 0; k < 3; k++) {
        await page.keyboard.press("Shift+ArrowLeft");
        await sleep(page, 380);
      }
      await sleep(page, 2500);
    },
  },
  {
    id: "dolly-in",
    what: "keyboard '+' dolly-in (a wheel notch each), five notches 180 ms apart, then hold still",
    async run(page) {
      await focusCanvas(page);
      await sleep(page, 450);
      for (let k = 0; k < 5; k++) {
        await page.keyboard.press("+");
        await sleep(page, 180);
      }
      await sleep(page, 1400);
    },
  },
  {
    id: "dolly-out",
    what: "keyboard '-' dolly-out, five notches 180 ms apart, then hold still",
    async run(page) {
      await focusCanvas(page);
      await sleep(page, 450);
      for (let k = 0; k < 5; k++) {
        await page.keyboard.press("-");
        await sleep(page, 180);
      }
      await sleep(page, 1400);
    },
  },
  {
    id: "focus-fly",
    what: "focusDevice('core1') eased fly-to (the product's focus affordance), then the camera stops and holds",
    async run(page) {
      await sleep(page, 450);
      await page.evaluate(() => window.__atlasScene.focusDevice("core1"));
      await sleep(page, 2600);
    },
  },
  {
    id: "reset-fly",
    what: "resetCamera() eased fly back to the whole fabric, then the camera stops and holds",
    async run(page) {
      await sleep(page, 450);
      await page.evaluate(() => window.__atlasScene.resetCamera());
      await sleep(page, 2600);
    },
  },
];

const FADE_REPEATS = Number(process.env.ATLAS_FADE_REPEATS || 3);
const FADE_SEQUENCES = [
  {
    id: "tier-fade-high-to-low",
    to: "low",
    async run(page) {
      await sleep(page, 300);
      await page.evaluate(() => window.__atlasScene.setQuality("low"));
      await sleep(page, 2200);
    },
  },
  {
    id: "tier-fade-low-to-high",
    to: "high",
    async run(page) {
      await sleep(page, 300);
      await page.evaluate(() => window.__atlasScene.setQuality("high"));
      await sleep(page, 2800);
    },
  },
];

/* ── recording ────────────────────────────────────────────────────────────────────────────────── */
async function record(page, ids, seqId, run, box, dir, { copy = true, keepRgba = false } = {}) {
  await page.evaluate((c) => (window.__motion.copy = c), copy);
  await page.evaluate(({ l, ids }) => window.__motion.start(l, ids), { l: seqId, ids });
  await run(page, box);
  const meta = await page.evaluate(() => window.__motion.stop());
  const hookErrors = await page.evaluate(() => ({ n: window.__motion.hookErrors, last: window.__motion.lastHookError ?? null }));
  const frames = [];
  const rgbaFrames = [];
  if (WRITE_PNG && copy) mkdirSync(dir, { recursive: true });
  for (let k = 0; copy && k < meta.length; k += 6) {
    const batch = await page.evaluate(
      async ({ a, b }) => {
        const out = [];
        for (let j = a; j < b; j++) out.push(await window.__motion.read(j));
        return out;
      },
      { a: k, b: Math.min(meta.length, k + 6) },
    );
    batch.forEach((b64, j) => {
      const f = meta[k + j];
      const rgba = Buffer.from(b64, "base64");
      frames.push(luma(rgba, f.w * f.h));
      if (keepRgba) rgbaFrames.push(rgba);
      if (WRITE_PNG) writeFileSync(resolve(dir, `${String(k + j).padStart(4, "0")}.png`), encodePng(f.w, f.h, rgba));
    });
  }
  await page.evaluate(() => window.__motion.release());
  return { meta, frames, rgbaFrames, hookErrors };
}

/* ── analysis ─────────────────────────────────────────────────────────────────────────────────── */
export const median = (a) => {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const r2 = (x) => (x === null || x === undefined || Number.isNaN(x) ? null : Math.round(x * 100) / 100);

export function camDeltaSeries(meta) {
  const d = [0];
  for (let t = 1; t < meta.length; t++) {
    let m = 0;
    const a = meta[t - 1].cam;
    const b = meta[t].cam;
    for (let k = 0; k < a.length; k++) {
      const u = a[k];
      const v = b[k];
      if (Number.isNaN(u) !== Number.isNaN(v)) m = Math.max(m, 999);
      else if (!Number.isNaN(u)) m = Math.max(m, Math.abs(u - v));
    }
    d.push(m);
  }
  return d;
}

export function frameDiff(A, B, delta) {
  let sum = 0;
  let over = 0;
  let strong = 0;
  let max = 0;
  for (let p = 0; p < A.length; p++) {
    const d = Math.abs(A[p] - B[p]);
    sum += d;
    if (d >= delta) over++;
    if (d >= T.AO_STRONG_DELTA) strong++;
    if (d > max) max = d;
  }
  return { mean: sum / A.length, over, strong, max };
}

function diffBBox(A, B, w, delta) {
  let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
  for (let p = 0; p < A.length; p++) {
    if (Math.abs(A[p] - B[p]) >= delta) {
      const x = p % w, y = (p / w) | 0;
      if (x < x0) x0 = x;
      if (y < y0) y0 = y;
      if (x > x1) x1 = x;
      if (y > y1) y1 = y;
    }
  }
  return x1 < 0 ? null : { x0, y0, x1, y1 };
}

function density(meta) {
  const dts = [];
  for (let t = 1; t < meta.length; t++) dts.push(meta[t].ts - meta[t - 1].ts);
  const med = median(dts);
  const gaps = dts.filter((d) => d > T.MAX_GAP_MS).length;
  const renderedEvery = meta.slice(1).every((f, i) => f.framesTimed === meta[i].framesTimed + 1);
  const ok = meta.length >= 30 && med !== null && med <= T.MAX_MEDIAN_DT_MS && gaps / Math.max(1, dts.length) <= T.MAX_GAP_SHARE;
  return {
    frames: meta.length,
    durationMs: r2(meta.length ? meta[meta.length - 1].ts - meta[0].ts : 0),
    medianDtMs: r2(med),
    maxDtMs: r2(dts.length ? Math.max(...dts) : null),
    gapsOver50ms: gaps,
    fps: r2(med ? 1000 / med : null),
    oneSceneFramePerCapture: renderedEvery,
    ok,
  };
}

export function analyseMotion(seq, meta, L, w, h, tier) {
  const n = w * h;
  const cd = camDeltaSeries(meta);
  const diffs = [null];
  for (let t = 1; t < L.length; t++) diffs.push(frameDiff(L[t - 1], L[t], T.POP_DELTA));

  /* Hover-change exclusion windows. */
  const hoverChangedAt = [];
  for (let t = 1; t < meta.length; t++) if (meta[t].hover !== meta[t - 1].hover) hoverChangedAt.push(meta[t].ts);
  const nearHover = (ts) => hoverChangedAt.some((h0) => ts >= h0 - 20 && ts - h0 <= T.HOVER_SETTLE_MS);

  /* 1. Still-frame pops. */
  const stillPops = [];
  let stillPairs = 0;
  let hoverExcluded = 0;
  let aoRestoreFrames = [];
  for (let t = 1; t < meta.length; t++) {
    if (cd[t] > T.STILL_PX) continue;
    const aoEdge = meta[t - 1].aoSuspended !== meta[t].aoSuspended;
    if (aoEdge) {
      aoRestoreFrames.push(t);
      continue;
    }
    if (meta[t].fade || meta[t - 1].fade) continue;
    if (nearHover(meta[t].ts)) {
      hoverExcluded++;
      continue;
    }
    stillPairs++;
    if (diffs[t].over > T.POP_MAX_PIXELS) {
      stillPops.push({ frame: t, pixelsOver: diffs[t].over, maxDelta: diffs[t].max, mean: r2(diffs[t].mean), bbox: diffBBox(L[t - 1], L[t], w, T.POP_DELTA) });
    }
  }

  /* 2. Motion spikes. */
  const norm = diffs.map((d, t) => (t === 0 || cd[t] <= T.STILL_PX ? null : d.mean / Math.max(cd[t], 0.05)));
  const spikes = [];
  const ratios = [];
  for (let t = 1; t < meta.length; t++) {
    if (norm[t] === null) continue;
    const nb = [];
    for (let k = t - 4; k <= t + 4; k++) if (k !== t && k > 0 && k < meta.length && norm[k] !== null) nb.push(norm[k]);
    if (nb.length < 4) continue;
    /* The reference rate, floored (T.SPIKE_NORM_FLOOR): a neighbourhood that changed nothing is not
       a rate this frame can be compared with. */
    const nbRate = median(nb);
    const m = Math.max(nbRate, T.SPIKE_NORM_FLOOR);
    const nbMean = [];
    for (let k = t - 4; k <= t + 4; k++) if (k !== t && k > 0 && k < meta.length && diffs[k] && cd[k] > T.STILL_PX) nbMean.push(diffs[k].mean);
    const excess = diffs[t].mean - median(nbMean);
    ratios.push(norm[t] / m);
    const aoEdge = meta[t - 1].aoSuspended !== meta[t].aoSuspended;
    if (norm[t] > T.SPIKE_RATIO * m && excess >= T.SPIKE_MIN_EXCESS) {
      spikes.push({ frame: t, ratio: r2(norm[t] / m), rate: r2(norm[t]), neighbourRate: r2(nbRate), meanDiff: r2(diffs[t].mean), neighbourMedian: r2(median(nbMean)), camPx: r2(cd[t]), aoEdge, hoverNear: nearHover(meta[t].ts) });
    }
  }

  /* 3. Z-fighting flip-flop on slow frames. */
  const flipCount = new Uint8Array(n);
  const lastFlagFrame = new Int16Array(n).fill(-1);
  let slowSteps = 0;
  {
    const win = [];
    for (let t = 2; t < L.length; t++) {
      const slow = cd[t] > T.STILL_PX && cd[t - 1] > T.STILL_PX && cd[t] <= T.SLOW_PX && cd[t - 1] <= T.SLOW_PX;
      let rev = null;
      if (slow) {
        slowSteps++;
        rev = new Uint8Array(n);
        const A = L[t - 2], B = L[t - 1], C = L[t];
        for (let p = 0; p < n; p++) {
          const d1 = B[p] - A[p];
          const d2 = C[p] - B[p];
          if ((d1 >= T.FLIP_DELTA && d2 <= -T.FLIP_DELTA) || (d1 <= -T.FLIP_DELTA && d2 >= T.FLIP_DELTA)) rev[p] = 1;
        }
      }
      win.push(rev);
      if (win.length > T.FLIP_WINDOW) win.shift();
      if (rev) {
        for (let p = 0; p < n; p++) {
          if (!rev[p]) continue;
          let c = 0;
          for (const r of win) if (r && r[p]) c++;
          if (c >= T.FLIP_MIN_REVERSALS) {
            flipCount[p] = 1;
            lastFlagFrame[p] = t;
          }
        }
      }
    }
  }
  let flipPixels = 0;
  for (let p = 0; p < n; p++) flipPixels += flipCount[p];
  const clusters = clustersOf(flipCount, w, h)
    .filter((c) => c.size >= T.ZF_CLUSTER)
    .map((c) => {
      /* the frame at which this cluster was last seen flip-flopping, for the evidence strip */
      let f = -1;
      for (let y = c.bbox.y0; y <= c.bbox.y1; y++) for (let x = c.bbox.x0; x <= c.bbox.x1; x++) f = Math.max(f, lastFlagFrame[y * w + x]);
      return { ...c, lastFlipFrame: f, camPxThen: f >= 0 ? Number(cd[f].toPrecision(3)) : null };
    });

  /* 4. Label blinks. */
  const blinks = [];
  if (meta.length) {
    const k = meta[0].vis.length;
    for (let j = 0; j < k; j++) {
      let runStart = 0;
      for (let t = 1; t <= meta.length; t++) {
        if (t < meta.length && meta[t].vis[j] === meta[t - 1].vis[j]) continue;
        const runLen = t - runStart;
        if (runStart > 0 && t < meta.length && runLen <= T.LABEL_BLINK_FRAMES) {
          blinks.push({ device: null, idx: j, state: meta[runStart].vis[j] === "1" ? "shown" : "hidden", fromFrame: runStart, frames: runLen });
        }
        runStart = t;
      }
    }
  }
  let labelToggles = 0;
  let maxDropsPerFrame = 0;
  for (let t = 1; t < meta.length; t++) {
    let drops = 0;
    for (let j = 0; j < meta[t].vis.length; j++) {
      if (meta[t].vis[j] !== meta[t - 1].vis[j]) labelToggles++;
      if (meta[t - 1].vis[j] === "1" && meta[t].vis[j] === "0") drops++;
    }
    maxDropsPerFrame = Math.max(maxDropsPerFrame, drops);
  }

  /* 5. AO drop / restore (only meaningful where the chain has SSAO: the high tier). */
  const ao = [];
  for (let t = 1; t < meta.length; t++) {
    if (!meta[t - 1].aoSuspended && meta[t].aoSuspended) {
      const d = frameDiff(L[t - 1], L[t], T.AO_DELTA);
      ao.push({
        kind: "drop",
        frame: t,
        cameraMovedThisFrame: cd[t] > T.STILL_PX,
        camPx: Number(cd[t].toPrecision(3)),
        maskedByMotion: cd[t] >= T.AO_MASK_PX,
        jump: { meanLuma: r2(d.mean), maxDelta: d.max, shareOver8: Number((d.over / n).toFixed(5)), shareOver32: Number((d.strong / n).toFixed(5)), bbox: diffBBox(L[t - 1], L[t], w, T.AO_DELTA) },
      });
    }
    if (meta[t - 1].aoSuspended && !meta[t].aoSuspended) {
      let lastMove = t - 1;
      while (lastMove > 0 && cd[lastMove] <= T.STILL_PX) lastMove--;
      const d = frameDiff(L[t - 1], L[t], T.AO_DELTA);
      let after = null;
      if (t + 1 < L.length) after = frameDiff(L[t], L[t + 1], T.POP_DELTA);
      ao.push({
        kind: "restore",
        frame: t,
        lastCameraChangeFrame: lastMove,
        stillFramesBeforeRestore: t - lastMove - 1,
        msAfterLastCameraChange: r2(meta[t].ts - meta[lastMove].ts),
        cameraMovedThisFrame: cd[t] > T.STILL_PX,
        jump: {
          meanLuma: r2(d.mean),
          maxDelta: d.max,
          shareOver8: Number((d.over / n).toFixed(5)),
          shareOver32: Number((d.strong / n).toFixed(5)),
          bbox: diffBBox(L[t - 1], L[t], w, T.AO_DELTA),
        },
        nextFrameChangePixels: after ? after.over : null,
      });
    }
  }
  const suspendedAtEnd = meta.length ? meta[meta.length - 1].aoSuspended : null;
  let lastMoveOverall = -1;
  for (let t = 1; t < meta.length; t++) if (cd[t] > T.STILL_PX) lastMoveOverall = t;

  return {
    sequence: seq.id,
    tier,
    what: seq.what,
    density: density(meta),
    tiersSeen: [...new Set(meta.map((f) => f.quality))],
    cameraFramesMoving: cd.filter((x) => x > T.STILL_PX).length,
    maxCamPxPerFrame: r2(Math.max(...cd)),
    stillPairsJudged: stillPairs,
    stillPairsExcludedForHover: hoverExcluded,
    hoverChanges: hoverChangedAt.length,
    stillPops,
    motionSpikes: spikes,
    /* The observed spread of the spike statistic, so the margin under SPIKE_RATIO is visible. */
    spikeRatioP99: r2(ratios.length ? [...ratios].sort((x, y) => x - y)[Math.floor(ratios.length * 0.99)] : null),
    spikeRatioMax: r2(ratios.length ? Math.max(...ratios) : null),
    zfight: { slowStepsJudged: slowSteps, flipPixels, flipShare: Number((flipPixels / n).toFixed(6)), clusters: clusters.slice(0, 10), clusterCount: clusters.length, flipClasses: flipPixels > 0 ? classifyFlipPixels(flipCount, lastFlagFrame, L, w, h) : null },
    labels: { toggles: labelToggles, maxDropsInOneFrame: maxDropsPerFrame, blinks },
    ao,
    aoSuspendedAtEnd: suspendedAtEnd,
    lastCameraChangeFrame: lastMoveOverall,
    msStillAtEnd: meta.length && lastMoveOverall >= 0 ? r2(meta[meta.length - 1].ts - meta[lastMoveOverall].ts) : null,
    _flipMap: flipCount,
    _diffs: diffs.map((d) => (d ? { mean: r2(d.mean), over: d.over, max: d.max } : null)),
    _cd: cd.map((x) => Number(x.toPrecision(3))),
  };
}

/**
 * WHAT KIND OF PIXEL is flip-flopping — a DIAGNOSTIC, never a verdict (repair wave 3, 2026-09-23).
 *
 * Each class of flipping pixel has a different remedy (a thin stroke wants a width floor or its own
 * anti-aliasing, a silhouette wants stable edge anti-aliasing, a highlight wants specular
 * anti-aliasing, a flat-region flip is shading noise), so the count alone could not say what to fix.
 * Every flagged pixel is classified on the luma frame in which it was LAST flagged (the camera then
 * moved <= SLOW_PX per frame, so the neighbourhood is the one that flipped), by the shape of the
 * image around it along the four principal directions, with CONTRAST (12 levels, FLIP_DELTA) as the
 * only threshold:
 *   thin-stroke  a ridge or valley at most 3 px wide: both samples 3 px away on one line lie on the
 *                same side of the pixel's +-1 extremum by >= CONTRAST (a cable, a curb, a strip).
 *   silhouette   a step: the samples 3 px away on some line differ from each other by >= 2 x
 *                CONTRAST, and it is not a stroke (a chassis outline, a deck edge).
 *   highlight    a local peak at least 2 x CONTRAST above the median of its 5x5 neighbourhood that is
 *                not a stroke or a step (a specular glint, an LED).
 *   flat         the 5x5 neighbourhood spans < CONTRAST: shading noise (AO, dither, lighting).
 *   other        none of the above (textures, the port grille, mixed neighbourhoods).
 */
export function classifyFlipPixels(flipMap, lastFlagFrame, L, w, h, contrast = T.FLIP_DELTA) {
  const out = { "thin-stroke": 0, silhouette: 0, highlight: 0, flat: 0, other: 0 };
  const dirs = [[1, 0], [0, 1], [1, 1], [1, -1]];
  for (let p = 0; p < flipMap.length; p++) {
    if (!flipMap[p]) continue;
    const t = lastFlagFrame[p];
    const F = L[t] ?? L[L.length - 1];
    const x = p % w;
    const y = (p / w) | 0;
    if (x < 3 || y < 3 || x >= w - 3 || y >= h - 3) {
      out.other++;
      continue;
    }
    const at = (dx, dy) => F[(y + dy) * w + (x + dx)];
    let lo = 255;
    let hi = 0;
    const win = [];
    for (let dy = -2; dy <= 2; dy++)
      for (let dx = -2; dx <= 2; dx++) {
        const v = at(dx, dy);
        win.push(v);
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    if (hi - lo < contrast) {
      out.flat++;
      continue;
    }
    let stroke = false;
    let step = false;
    for (const [dx, dy] of dirs) {
      const a = at(-3 * dx, -3 * dy);
      const b = at(3 * dx, 3 * dy);
      const ridgeMax = Math.max(at(-dx, -dy), at(0, 0), at(dx, dy));
      const ridgeMin = Math.min(at(-dx, -dy), at(0, 0), at(dx, dy));
      if ((ridgeMax - a >= contrast && ridgeMax - b >= contrast) || (a - ridgeMin >= contrast && b - ridgeMin >= contrast)) stroke = true;
      if (Math.abs(a - b) >= 2 * contrast) step = true;
    }
    if (stroke) {
      out["thin-stroke"]++;
      continue;
    }
    if (step) {
      out.silhouette++;
      continue;
    }
    win.sort((m, n) => m - n);
    if (at(0, 0) - win[12] >= 2 * contrast || hi - win[12] >= 2 * contrast) out.highlight++;
    else out.other++;
  }
  return out;
}

export function clustersOf(mask, w, h) {
  const seen = new Uint8Array(mask.length);
  const out = [];
  const stack = [];
  for (let p = 0; p < mask.length; p++) {
    if (!mask[p] || seen[p]) continue;
    let size = 0, x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
    stack.push(p);
    seen[p] = 1;
    while (stack.length) {
      const q = stack.pop();
      size++;
      const x = q % w, y = (q / w) | 0;
      if (x < x0) x0 = x;
      if (y < y0) y0 = y;
      if (x > x1) x1 = x;
      if (y > y1) y1 = y;
      for (const r of [x > 0 ? q - 1 : -1, x < w - 1 ? q + 1 : -1, y > 0 ? q - w : -1, y < h - 1 ? q + w : -1]) {
        if (r >= 0 && mask[r] && !seen[r]) {
          seen[r] = 1;
          stack.push(r);
        }
      }
    }
    out.push({ size, bbox: { x0, y0, x1, y1 } });
  }
  return out.sort((a, b) => b.size - a.size);
}

function analyseFade(seq, meta, L, w, h) {
  const n = w * h;
  const firstPresent = meta.findIndex((f) => f.fade);
  if (firstPresent < 0) return { sequence: seq.id, established: false, why: "the tier-fade overlay never appeared", density: density(meta) };
  let start = -1;
  for (let t = firstPresent; t < meta.length; t++) {
    if (meta[t].fade && meta[t].fade.opacity < 0.995) {
      start = t;
      break;
    }
  }
  let end = -1;
  for (let t = Math.max(start, firstPresent); t < meta.length && start >= 0; t++) {
    if (!meta[t].fade || meta[t].fade.opacity <= 0.005) {
      end = t;
      break;
    }
  }
  const trace = meta.slice(Math.max(0, firstPresent - 1), end >= 0 ? end + 2 : meta.length).map((f) => ({
    frame: f.i,
    t: r2(f.ts - meta[firstPresent].ts),
    opacity: f.fade ? r2(f.fade.opacity) : null,
    quality: f.quality,
  }));
  if (start < 0 || end < 0) return { sequence: seq.id, established: false, why: `fade ${start < 0 ? "never started" : "never finished"} in the recorded window`, trace, density: density(meta) };
  let maxStep = 0;
  let maxStepFrame = -1;
  const op = (t) => (meta[t].fade ? meta[t].fade.opacity : 0);
  for (let t = start; t <= end; t++) {
    const s = Math.abs(op(t - 1) - op(t));
    if (s > maxStep) {
      maxStep = s;
      maxStepFrame = t;
    }
  }
  /* Composited pixel progress: total change from the last full-overlay frame to the first frame
     without it, and the largest one-frame share of that. */
  const hasPixels = L.length === meta.length;
  const total = hasPixels ? frameDiff(L[start - 1], L[end], 8).mean : 0;
  /* Below FADE_MIN_VISIBLE_DELTA mean luma the two tiers' pictures are the same picture (light theme:
     0.02/255 measured), and a one-frame "share" of a near-zero total is rounding noise, not a cut. */
  const judgeComposite = hasPixels && total >= T.FADE_MIN_VISIBLE_DELTA;
  let maxShare = hasPixels ? 0 : null;
  let maxShareFrame = -1;
  for (let t = start; hasPixels && t <= end; t++) {
    const s = total > 0 ? frameDiff(L[t - 1], L[t], 8).mean / total : 0;
    if (s > maxShare) {
      maxShare = s;
      maxShareFrame = t;
    }
  }
  return {
    sequence: seq.id,
    established: true,
    density: density(meta),
    overlayAppearedFrame: firstPresent,
    holdMs: r2(meta[start].ts - meta[firstPresent].ts),
    fadeStartFrame: start,
    fadeEndFrame: end,
    fadeMs: r2(meta[end].ts - meta[start - 1].ts),
    framesInFade: end - start + 1,
    maxOpacityStep: r2(maxStep),
    maxOpacityStepFrame: maxStepFrame,
    compositeTotalMeanDelta: hasPixels ? r2(total) : null,
    compositeJudged: judgeComposite,
    compositeMaxOneFrameShare: r2(maxShare),
    compositeMaxShareFrame: maxShareFrame,
    tierAfter: meta[meta.length - 1].quality,
    trace,
  };
}

/* ── evidence images for the worst frames ─────────────────────────────────────────────────────── */
function writeHeat(file, A, B, w, h, gain = 8) {
  const rgb = Buffer.alloc(w * h * 3);
  for (let p = 0; p < w * h; p++) {
    const d = Math.min(255, Math.abs(A[p] - B[p]) * gain);
    rgb[p * 3] = d;
    rgb[p * 3 + 1] = d >> 1;
    rgb[p * 3 + 2] = 0;
  }
  writeFileSync(file, encodePng(w, h, rgb, 3));
}
/** Crop `bbox` (+pad) out of each listed RGBA frame, magnify by `scale` (nearest), lay them side by side. */
function writeStrip(file, rgbaFrames, list, bbox, w, h, pad = 12, scale = 6) {
  const x0 = Math.max(0, bbox.x0 - pad), y0 = Math.max(0, bbox.y0 - pad);
  const x1 = Math.min(w - 1, bbox.x1 + pad), y1 = Math.min(h - 1, bbox.y1 + pad);
  const cw = x1 - x0 + 1, ch = y1 - y0 + 1, gap = 4;
  const frames = list.filter((t) => t >= 0 && t < rgbaFrames.length);
  const W = frames.length * (cw * scale + gap), H = ch * scale;
  const out = Buffer.alloc(W * H * 3, 128);
  frames.forEach((t, k) => {
    const src = rgbaFrames[t];
    const ox = k * (cw * scale + gap);
    for (let y = 0; y < H; y++) {
      const sy = y0 + ((y / scale) | 0);
      for (let x = 0; x < cw * scale; x++) {
        const sx = x0 + ((x / scale) | 0);
        const q = (sy * w + sx) * 4, o = (y * W + ox + x) * 3;
        out[o] = src[q]; out[o + 1] = src[q + 1]; out[o + 2] = src[q + 2];
      }
    }
  });
  writeFileSync(file, encodePng(W, H, out, 3));
}
function writeMask(file, mask, w, h, base) {
  const rgb = Buffer.alloc(w * h * 3);
  for (let p = 0; p < w * h; p++) {
    const v = base ? base[p] >> 2 : 0;
    rgb[p * 3] = mask[p] ? 255 : v;
    rgb[p * 3 + 1] = mask[p] ? 0 : v;
    rgb[p * 3 + 2] = mask[p] ? 255 : v;
  }
  writeFileSync(file, encodePng(w, h, rgb, 3));
}

/* ── main ─────────────────────────────────────────────────────────────────────────────────────────
   Runs only when this file is EXECUTED. Imported (src/fabric3d/render-c5-repairs.test.ts), it is a
   module of thresholds and pure analysis functions, so the rules a verdict depends on can be pinned
   by a known-answer test rather than trusted. */
async function main() {
  const { chromium } = await import("@playwright/test");
  const server = await serverIdentity();
  const freshness = await checkBuildFreshness(APP);
  console.log(`server: ${server.url} (${server.mode}); build fresh: ${freshness.fresh} — ${freshness.why}`);
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({ args: GPU_ARGS });
  const legs = [];
  for (const theme of THEMES) {
    for (const tier of TIERS) {
      /* ATLAS_MOTION_LEGS=dark/high,light/low restricts a run while iterating; a restricted run can
         never PASS (the verdicts below require all four legs). */
      if (process.env.ATLAS_MOTION_LEGS && !process.env.ATLAS_MOTION_LEGS.split(",").includes(`${theme}/${tier}`)) continue;
      const leg = { theme, tier, problems: [], sequences: [], fades: [] };
      legs.push(leg);
      const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: DSF, colorScheme: theme, reducedMotion: "no-preference" });
      await ctx.addInitScript(instrument);
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
      page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 200)));
      await page.goto(`${APP}/`, { waitUntil: "networkidle" });
      await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
      await page.mouse.move(5, VIEWPORT.height - 5);
      await awaitSettled(page);
      const env = await page.evaluate(() => {
        const c = document.querySelector(".fabric3d canvas, canvas");
        const gl = document.createElement("canvas").getContext("webgl2");
        const dbg = gl?.getExtension("WEBGL_debug_renderer_info");
        return {
          quality: window.__atlasScene.stats().quality,
          renderer: gl && dbg ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) : null,
          canvas: { w: c.width, h: c.height, cssW: c.clientWidth, cssH: c.clientHeight },
          dpr: window.devicePixelRatio,
          ids: [...document.querySelectorAll(".fabric3d-label[data-device]")].map((e) => e.dataset.device),
        };
      });
      leg.env = env;
      if (env.quality !== "high") leg.problems.push(`auto-selected tier was "${env.quality}", not high — the high tier is not established on this host`);
      if (tier === "low") {
        await page.evaluate(() => window.__atlasScene.setQuality("low"));
        await awaitSettled(page);
      }
      const box = await page.locator(".fabric3d canvas, canvas").first().boundingBox();
      const ids = env.ids;
      console.log(`leg ${theme}/${tier}: tier ${await page.evaluate(() => window.__atlasScene.stats().quality)}, canvas ${env.canvas.w}x${env.canvas.h}, ${ids.length} anchors, ${env.renderer}`);

      for (const seq of SEQUENCES) {
        await awaitSettled(page);
        const dir = resolve(OUT, theme, tier, seq.id);
        const { meta, frames, rgbaFrames, hookErrors } = await record(page, ids, seq.id, seq.run, box, dir, { keepRgba: true });
        const w = meta[0]?.w, h = meta[0]?.h;
        const a = analyseMotion(seq, meta, frames, w, h, tier);
        a.hookErrors = hookErrors;
        a.dir = dir;
        a.labelIds = ids;
        for (const b of a.labels.blinks) b.device = ids[b.idx];
        /* evidence images */
        const ev = resolve(OUT, "_evidence", theme, tier, seq.id);
        mkdirSync(ev, { recursive: true });
        for (const [k, c] of a.zfight.clusters.slice(0, 3).entries()) {
          const t = c.lastFlipFrame;
          writeStrip(resolve(ev, `flipflop-cluster${k + 1}-frames${t - 5}-${t}.png`), rgbaFrames, [t - 5, t - 4, t - 3, t - 2, t - 1, t], c.bbox, w, h);
        }
        for (const [k, sp] of a.stillPops.slice(0, 2).entries()) if (sp.bbox) writeStrip(resolve(ev, `still-pop${k + 1}-frames${sp.frame - 1}-${sp.frame}.png`), rgbaFrames, [sp.frame - 1, sp.frame], sp.bbox, w, h, 12, 2);
        for (const e of a.ao) if (e.jump?.bbox) writeStrip(resolve(ev, `ao-${e.kind}-frames${e.frame - 1}-${e.frame}.png`), rgbaFrames, [e.frame - 1, e.frame], e.jump.bbox, w, h, 8, 2);
        if (a.zfight.flipPixels > 0) writeMask(resolve(ev, "flipflop-map.png"), a._flipMap, w, h, frames[frames.length - 1]);
        const worstStill = [...a.stillPops].sort((x, y) => y.pixelsOver - x.pixelsOver)[0];
        if (worstStill) writeHeat(resolve(ev, `still-pop-${worstStill.frame}-heat.png`), frames[worstStill.frame - 1], frames[worstStill.frame], w, h);
        for (const r of a.ao) writeHeat(resolve(ev, `ao-${r.kind}-${r.frame}-heat.png`), frames[r.frame - 1], frames[r.frame], w, h);
        for (const s of a.motionSpikes.slice(0, 3)) writeHeat(resolve(ev, `spike-${s.frame}-heat.png`), frames[s.frame - 1], frames[s.frame], w, h, 4);
        writeFileSync(resolve(ev, "series.json"), JSON.stringify({ camPx: a._cd, diff: a._diffs, meta: meta.map(({ cam, ...m }) => m) }));
        delete a._flipMap;
        delete a._diffs;
        delete a._cd;
        leg.sequences.push(a);
        console.log(
          `  ${seq.id}: ${a.density.frames} frames @ ${a.density.fps} fps (max dt ${a.density.maxDtMs} ms), moving ${a.cameraFramesMoving}, ` +
            `still pops ${a.stillPops.length}/${a.stillPairsJudged}, spikes ${a.motionSpikes.length}, flip px ${a.zfight.flipPixels}${a.zfight.flipClasses ? " " + JSON.stringify(a.zfight.flipClasses) : ""} (clusters>=${T.ZF_CLUSTER}: ${a.zfight.clusterCount}), ` +
            `label blinks ${a.labels.blinks.length}, ao ${JSON.stringify(a.ao.map((x) => x.kind + "@" + x.frame + (x.jump ? ` ${x.msAfterLastCameraChange}ms ${x.jump.shareOver8}` : "")))}`,
        );
      }

      if (tier === "high") {
        /* REPLICATED, and with a CONTROL. A single fade is one sample of a timing property, and the first
           runs disagreed (one high->low fade ran 300 ms in 18 frames, the next was cut by a 517 ms stall).
           Each direction is therefore recorded FADE_REPEATS times with the pixel copy ON (composite
           evidence) and FADE_REPEATS times with it OFF (opacity trace only): a stall that appears with
           the copy off is the product's, not the harness's. */
        for (let rep = 0; rep < FADE_REPEATS; rep++) for (const copy of [true, false]) for (const seq of FADE_SEQUENCES) {
          await awaitSettled(page);
          const tag = `${seq.id}-r${rep + 1}-${copy ? "copy" : "nocopy"}`;
          const dir = resolve(OUT, theme, "fade", tag);
          const { meta, frames } = await record(page, ids, seq.id, seq.run, box, dir, { copy });
          const f = analyseFade(seq, meta, frames, meta[0].w, meta[0].h);
          f.dir = copy ? dir : null;
          f.copy = copy;
          f.rep = rep + 1;
          f.tag = tag;
          f.worstSceneFrameMs = r2(Math.max(...meta.map((m) => m.sceneFrameMs ?? 0)));
          f.maxHookMs = r2(Math.max(...meta.map((m) => m.hookMs ?? 0)));
          leg.fades.push(f);
          console.log(`  ${tag}: max dt ${f.density.maxDtMs} ms, worst scene frame ${f.worstSceneFrameMs} ms, hook <= ${f.maxHookMs} ms; ${f.established ? `hold ${f.holdMs} ms, fade ${f.fadeMs} ms over ${f.framesInFade} frames, max opacity step ${f.maxOpacityStep} @${f.maxOpacityStepFrame}, max composite share ${f.compositeMaxOneFrameShare}` : "NOT ESTABLISHED: " + f.why}`);
        }
      }
      leg.pageErrors = errors.slice(0, 5);
      await ctx.close();
    }
  }
  await browser.close();

  /* ── verdicts per C5 motion item ──────────────────────────────────────────────────────────────── */
  const all = legs.flatMap((l) => l.sequences.map((s) => ({ leg: `${l.theme}/${l.tier}`, ...s })));
  const dense = all.filter((s) => s.density.ok);
  const notDense = all.filter((s) => !s.density.ok).map((s) => `${s.leg}/${s.sequence} (${s.density.fps} fps, ${s.density.gapsOver50ms} gaps)`);
  const legProblems = legs.flatMap((l) => l.problems.map((p) => `${l.theme}/${l.tier}: ${p}`));

  function verdict(fails, established, why) {
    return { verdict: fails.length ? "FAIL" : established ? "PASS" : "UNPROVEN", fails, why };
  }

  const zf = all.flatMap((s) =>
    s.zfight.clusterCount > 0 ? [`${s.leg}/${s.sequence}: ${s.zfight.clusterCount} flip-flop clusters >= ${T.ZF_CLUSTER} px (largest ${s.zfight.clusters[0]?.size ?? 0} px at ${JSON.stringify(s.zfight.clusters[0]?.bbox ?? null)}), ${s.zfight.flipPixels} flip px (${s.zfight.flipShare})`] : [],
  );
  const sparkle = all.flatMap((s) =>
    s.zfight.flipShare > T.ZF_MAX_SHARE ? [`${s.leg}/${s.sequence}: ${s.zfight.flipPixels} flip-flopping px, ${s.zfight.flipShare} of the canvas (bar ${T.ZF_MAX_SHARE}); ${s.zfight.clusterCount} clusters >= ${T.ZF_CLUSTER} px`] : [],
  );
  const zfSlowSteps = dense.reduce((a, s) => a + s.zfight.slowStepsJudged, 0);
  const popFails = [
    ...all.flatMap((s) => s.stillPops.map((p) => `${s.leg}/${s.sequence} still frame ${p.frame}: ${p.pixelsOver} px changed >= ${T.POP_DELTA}/255 (max ${p.maxDelta}) with the camera still, bbox ${JSON.stringify(p.bbox)}`)),
    ...all.flatMap((s) => s.motionSpikes.map((p) => `${s.leg}/${s.sequence} motion frame ${p.frame}: change ${p.ratio}x its neighbours at the same camera speed (mean ${p.meanDiff} vs ${p.neighbourMedian}, cam ${p.camPx} px${p.aoEdge ? ", AO edge" : ""}${p.hoverNear ? ", hover change nearby" : ""})`)),
    ...all.flatMap((s) => s.labels.blinks.map((b) => `${s.leg}/${s.sequence} label ${b.device} ${b.state} for only ${b.frames} frame(s) from frame ${b.fromFrame}`)),
  ];
  const popStill = dense.reduce((a, s) => a + s.stillPairsJudged, 0);
  const aoFails = [];
  const aoUnjudged = [];
  let aoRestores = 0;
  for (const s of all.filter((x) => x.tier === "high")) {
    for (const e of s.ao) {
      if (e.kind === "drop" && !e.maskedByMotion && (e.jump.shareOver8 > T.AO_MAX_SHARE || e.jump.shareOver32 > T.AO_MAX_STRONG_SHARE))
        aoFails.push(`${s.leg}/${s.sequence}: AO drop frame ${e.frame} (camera moved ${e.camPx} px: not masked) jumps ${e.jump.shareOver8} of the canvas >= ${T.AO_DELTA}/255 and ${e.jump.shareOver32} >= ${T.AO_STRONG_DELTA}/255`);
      if (e.kind === "restore") {
        aoRestores++;
        if (e.msAfterLastCameraChange > T.AO_RESTORE_MAX_MS) aoFails.push(`${s.leg}/${s.sequence}: AO restored ${e.msAfterLastCameraChange} ms after the camera stopped (> ${T.AO_RESTORE_MAX_MS})`);
        if (e.jump.shareOver8 > T.AO_MAX_SHARE || e.jump.shareOver32 > T.AO_MAX_STRONG_SHARE)
          aoFails.push(`${s.leg}/${s.sequence}: AO restore frame ${e.frame} jumps ${e.jump.shareOver8} of the canvas >= ${T.AO_DELTA}/255 and ${e.jump.shareOver32} >= ${T.AO_STRONG_DELTA}/255 (bars ${T.AO_MAX_SHARE} / ${T.AO_MAX_STRONG_SHARE})`);
      }
    }
    /* Ending suspended is a FAIL only when the camera had been still for longer than the restore bar
       before the recording ended; otherwise the window was too short to judge (recorded, not passed). */
    if (s.aoSuspendedAtEnd) {
      if (s.msStillAtEnd !== null && s.msStillAtEnd > T.AO_RESTORE_MAX_MS) aoFails.push(`${s.leg}/${s.sequence}: camera still for ${s.msStillAtEnd} ms at the end and AO never restored`);
      else aoUnjudged.push(`${s.leg}/${s.sequence}: recording ended ${s.msStillAtEnd} ms after the last camera change, AO still suspended`);
    }
  }
  const fadeFails = [];
  let fadesEstablished = 0;
  for (const l of legs) {
    for (const f of l.fades) {
      if (!f.established) continue;
      fadesEstablished++;
      if (f.fadeMs < T.FADE_MIN_MS || f.fadeMs >= T.FADE_MAX_MS) fadeFails.push(`${l.theme}/${f.tag}: fade lasted ${f.fadeMs} ms (bar: at least ${T.FADE_MIN_MS}, under ${T.FADE_MAX_MS})`);
      if (f.maxOpacityStep > T.FADE_MAX_STEP) fadeFails.push(`${l.theme}/${f.tag}: opacity fell ${f.maxOpacityStep} in one frame (frame ${f.maxOpacityStepFrame}; bar ${T.FADE_MAX_STEP})`);
      if (f.compositeJudged && f.compositeMaxOneFrameShare > T.FADE_MAX_PIXEL_SHARE) fadeFails.push(`${l.theme}/${f.tag}: one frame carried ${f.compositeMaxOneFrameShare} of the composited change (frame ${f.compositeMaxShareFrame}; bar ${T.FADE_MAX_PIXEL_SHARE})`);
    }
  }
  const fadeNotEst = legs.flatMap((l) => l.fades.filter((f) => !f.established).map((f) => `${l.theme}/${f.tag}: ${f.why}`));

  const items = {
    "z-fighting (flip-flop PATCHES >= ZF_CLUSTER px during camera moves)": verdict(zf, zfSlowSteps >= 60 && notDense.length === 0 && legProblems.length === 0, `${zfSlowSteps} slow-motion frame steps judged across dense sequences`),
    "edge sparkle (total flip-flopping share <= ZF_MAX_SHARE during camera moves)": verdict(sparkle, zfSlowSteps >= 60 && notDense.length === 0 && legProblems.length === 0, `same ${zfSlowSteps} slow-motion frame steps`),
    "LOD / effect / label popping": verdict(popFails, popStill >= 100 && notDense.length === 0 && legProblems.length === 0, `${popStill} still frame pairs + every motion frame + per-frame label visibility judged`),
    "AO drop and restore at camera stop (high tier)": verdict(aoFails, aoRestores >= 4 && aoUnjudged.length === 0 && notDense.length === 0 && legProblems.length === 0, `${aoRestores} restores observed at the high tier${aoUnjudged.length ? "; not judged: " + aoUnjudged.join("; ") : ""}`),
    [`${TIER_FADE_MS} ms quality-tier cross-fade (under ${C6_BAR_MS} ms)`]: verdict(fadeFails, fadesEstablished === THEMES.length * 2 * 2 * FADE_REPEATS && fadeNotEst.length === 0, `${fadesEstablished} of ${THEMES.length * 2 * 2 * FADE_REPEATS} fades (2 themes x 2 directions x ${FADE_REPEATS} repeats x copy on/off) established${fadeNotEst.length ? "; " + fadeNotEst.join("; ") : ""}`),
  };

  const report = {
    generatedAt: new Date().toISOString(),
    server,
    freshness,
    viewport: VIEWPORT,
    deviceScaleFactor: DSF,
    thresholds: T,
    notDense,
    legProblems,
    items,
    legs,
  };
  writeFileSync(resolve(OUT, "report.json"), JSON.stringify(report, null, 1));
  console.log("\nC5 motion items:");
  for (const [k, v] of Object.entries(items)) {
    console.log(`  ${v.verdict.padEnd(8)} ${k} — ${v.why}`);
    for (const f of v.fails.slice(0, 12)) console.log(`           ${f}`);
    if (v.fails.length > 12) console.log(`           ... ${v.fails.length - 12} more in report.json`);
  }
  if (notDense.length) console.log(`  sequences below the density bar: ${notDense.join("; ")}`);
  if (legProblems.length) console.log(`  leg problems: ${legProblems.join("; ")}`);
  if (!freshness.fresh || server.mode !== "build") console.log(`  WARNING: not evidence of what ships (server ${server.mode}, fresh ${freshness.fresh}).`);
  console.log(`report: ${resolve(OUT, "report.json")}`);
  const verdicts = Object.values(items).map((v) => v.verdict);
  process.exitCode = verdicts.includes("FAIL") ? 3 : verdicts.includes("UNPROVEN") || !freshness.fresh ? 4 : 0;
}

if (IS_MAIN) await main();
