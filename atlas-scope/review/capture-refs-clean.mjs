/**
 * capture-refs-clean.mjs — the ONE owner of the C1 reference set: clean, task-matched frames of the
 * reference products' WORKING surfaces, with provenance, and a self-check that refuses a frame
 * that still carries a tour, promo banner or modal.
 *
 *   node review/capture-refs-clean.mjs            offline self-check of what is on disk (default)
 *   node review/capture-refs-clean.mjs --fetch    capture/refresh the set over the network, then self-check
 *
 * WHY THIS FILE EXISTS (discovery c1-references, 2026-09-26). The previous reference set rested on
 * two capture bugs, not on the products being uncapturable: `capture-deep.mjs` looked for a
 * `<button>` "Next" while Storylane's tour controls are `<div class="PlayerButton_root__…">`, so no
 * tour ever advanced and "step3" and "step6" were byte-identical; and neither script could close
 * Grafana's promo banner (its dismiss control is labelled "Close alert", not "Close"). Four of six
 * pairings showed a tour modal, and six pairings used three distinct reference images. A verdict
 * over a wrapped reference judges the WRAPPER.
 *
 * HOW THE FRAMES ARE MADE — and what each one is:
 *   - Forward, demo jdhoywyw5voi: Storylane stores each recorded screen as a page file (a saved copy
 *     of Forward's DOM with its CSS inlined). The tour is a SEPARATE layer drawn by the player, not
 *     part of those files. The page list comes from the demo HTML's server-rendered data (a plain
 *     GET: no player, no script, no analytics), and each chosen page is rendered offline with
 *     JavaScript disabled at its recorded viewport; a recorded <canvas> whose pixels were stored as a
 *     data: image is replaced by that image. THESE ARE STORYLANE RECORDINGS OF FORWARD, NOT THE LIVE
 *     PRODUCT — every manifest row says so.
 *   - Forward, demo ts9nkc4osn4z: the demo's pages are stored screenshots (PNG); the chosen one is
 *     downloaded as is.
 *   - IP Fabric: the documentation's unannotated product screenshots (the guided demo and trial
 *     are gated on an email + consent form, which this harness never fills).
 *   - Grafana: play.grafana.org rendered live, with the promo banner's dismissal and the undocked
 *     menu PRE-SEEDED in localStorage (no click needed), plus one deliberately UNDISMISSED control
 *     frame that the self-check must flag — proof the marker check fires on the real banner.
 *   - Linear: NOT OBTAINABLE without an account — recorded as such, never substituted.
 *
 * WHAT THE SELF-CHECK PROVES (default mode, offline). Each item fails closed:
 *   1. Positive controls first: the phrase matcher, the duplicate-reference check, and the OCR text
 *      layer (a synthetic Storylane-style tour card is rendered, OCR'd and must be flagged) each
 *      trip on a known-bad input. A check whose failure path never ran is not a check.
 *   2. The manifest exists (absence of a reference set is UNPROVEN, never "clean").
 *   3. Every frame exists and its sha256 still matches the manifest.
 *   4. NO TOUR/BANNER MARKER, judged on two independent layers: the DOM census recorded at capture
 *      (overlay roles — dialog / alertdialog / alert / aria-modal — and Storylane's player-layer
 *      component classes) where the frame was rendered from a DOM, and the OCR text of the PIXELS
 *      for EVERY frame, raster or not. A frame with no DOM layer is not thereby clean: the pixel
 *      layer applies to all of them.
 *   5. The frame shows the working surface it claims (its `expect` phrases are in its pixels).
 *   6. No two frames are byte-identical, and no two blind pairings share a byte-identical reference
 *      unless the pairing declares it (`sharesReferenceWith`). Nor may two pairings present a
 *      near-identical reference SCREEN (thumbnail correlation >= SIMILAR_SCREEN) unless a pairing
 *      declares it with its reason (`similarScreenWith`) — byte identity is only the narrow case.
 *   7. Every pairing's reference is in the set.
 *   8. Control frames ARE flagged (a detector that passes its control is broken).
 *   9. Every frame whose identity marks were not measured in its DOM (identityRects) declares its identity slots — logo glyph, workspace chip, user menu — as
 *      geometry measured on that frame, or an empty list with a reason; blind-pair.mjs masks them.
 *
 * Output lives under review/shots/refs-clean/, which .gitignore excludes (review/shots/): vendor
 * demo and documentation imagery is NEVER tracked and never goes into anything published.
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
export const REFS_DIR = resolve(HERE, "shots", "refs-clean");
export const MANIFEST = resolve(REFS_DIR, "manifest.json");
const WORK = resolve(HERE, "shots", "refs-clean", "_work");
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36";
const STORYLANE_NOTE = "Storylane recording of Forward Enterprise, not the live product.";

export const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");
/** Paths written into manifests are repository-relative: an absolute path would carry the host's
    home directory, which is a client-privacy marker in this repository. */
export const rel = (p) => relative(resolve(HERE, ".."), p).split("\\").join("/");
export const fromRel = (p) => resolve(HERE, "..", p);

/* ── The marker vocabulary ────────────────────────────────────────────────────────────────────
   The CLASS is "the frame shows something wrapped around the product": a guided-tour layer, a
   promo/sign-up banner, or a modal. It is judged structurally where a DOM exists (roles and the
   tour player's component classes — not a list of the modals seen so far) and by phrase on the
   pixels everywhere. The phrases are the calls to action such wrappers exist to make; a product's
   own working surface does not say "sign up" or "in this demo". */
export const TOUR_BANNER_PHRASES = [
  "storylane",
  "made with storylane",
  "in this demo",
  "this demo",
  "guided tour",
  "take the tour",
  "start tour",
  "start demo",
  "book a demo",
  "request a demo",
  "get a demo",
  "click on",
  "create free account",
  "create a free account",
  "free account",
  "sign up",
  "free trial",
  "start free trial",
  "try for free",
];
/** Storylane's player layer is built from CSS-module components named `<Component>_<part>__<hash>`;
    every tour component is a `Widget*`, `PlayerButton*` or `FloatingFrameControls*`. */
export const TOUR_LAYER_CLASS = /(?:^|\s)(?:Widget[A-Z]\w*|PlayerButton|FloatingFrameControls)_\w+/;
/** Overlay roles: anything that sits ON the product rather than being part of it. */
export const OVERLAY_ROLES = '[role="dialog"],[role="alertdialog"],[role="alert"],[aria-modal="true"]';

/* ── Fuzzy phrase matching over OCR text ──────────────────────────────────────────────────────
   OCR is noisy ("FORW7RD", "Forward Al"), so a phrase matches a run of whole words whose joined
   letters are within floor(len/7) edits of the phrase's joined letters. Whole words only, so
   "forward" never matches inside "l3_forwarding". */
export const norm = (s) =>
  String(s)
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
export const tokens = (s) => (norm(s) ? norm(s).split(" ") : []);
export function lev(a, b) {
  if (a === b) return 0;
  const m = a.length;
  const n = b.length;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[n];
}
const tolerance = (joined) => Math.floor(joined.length / 7);
/** Every occurrence of `phrase` in the token list, as [start, endExclusive] token ranges. */
export function findPhrase(toks, phrase) {
  const p = tokens(phrase);
  if (!p.length) return [];
  const target = p.join("");
  const tol = tolerance(target);
  const out = [];
  for (let i = 0; i < toks.length; i++) {
    for (let k = Math.max(1, p.length - 1); k <= p.length + 1 && i + k <= toks.length; k++) {
      const cand = toks.slice(i, i + k).join("");
      if (Math.abs(cand.length - target.length) > tol) continue;
      if (lev(cand, target) <= tol) {
        out.push([i, i + k]);
        break;
      }
    }
  }
  return out;
}
export const phrasesIn = (text, phrases) => {
  const toks = tokens(text);
  return phrases.filter((ph) => findPhrase(toks, ph).length > 0);
};

/* ── OCR: Windows.Media.Ocr through PowerShell, the host's own engine, no network ────────────
   Returns, per file, { ok, text, lines: [{ text, words: [{ text, x, y, w, h }] }] } in the
   image's DEVICE pixels. Fails closed: an unavailable engine is reported, never read as "no text". */
const OCR_PS = (paths) => `
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation\`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(); $task.Result }
$eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$paths = ConvertFrom-Json '${JSON.stringify(paths).replace(/'/g, "''")}'
foreach ($p in $paths) {
  try {
    if ($null -eq $eng) { throw 'no OCR engine for the user profile languages' }
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    foreach ($l in $res.Lines) {
      $words = @()
      foreach ($w in $l.Words) { $r = $w.BoundingRect; $words += @{ text = $w.Text; x = $r.X; y = $r.Y; w = $r.Width; h = $r.Height } }
      $lines += @{ text = $l.Text; words = $words }
    }
    $stream.Dispose()
    $o = @{ path = $p; ok = $true; text = $res.Text; lines = $lines }
  } catch { $o = @{ path = $p; ok = $false; error = ($_.Exception.Message) } }
  # One JSON document per LINE per image: PS 5.1 ConvertTo-Json caps one document at 2 MB.
  [Console]::Out.WriteLine((ConvertTo-Json -InputObject $o -Depth 8 -Compress))
}
`;
export function ocrImages(files) {
  const results = new Map();
  if (process.platform !== "win32") {
    for (const f of files) results.set(f, { ok: false, error: "OCR text layer needs Windows.Media.Ocr (Windows host)" });
    return results;
  }
  for (let i = 0; i < files.length; i += 12) {
    const batch = files.slice(i, i + 12).map((f) => resolve(f));
    const enc = Buffer.from(OCR_PS(batch), "utf16le").toString("base64");
    const r = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc], {
      encoding: "utf8",
      maxBuffer: 256 * 1024 * 1024,
      timeout: 300000,
    });
    const arr = [];
    for (const ln of String(r.stdout || "").split(String.fromCharCode(10))) {
      if (!ln.trim().startsWith("{")) continue;
      try {
        /* PS 5.1's ConvertTo-Json leaves control characters (OCR emits e.g. U+0007) unescaped,
           which JSON.parse rejects: they carry no text, so they become spaces. */
        arr.push(JSON.parse(ln.replace(/[\u0000-\u001f]/g, " ")));
      } catch {
        /* a truncated line is a missing result, reported below */
      }
    }
    for (const f of batch) {
      const hit = arr.find((x) => resolve(x.path) === f);
      const errs = [...String(r.stderr || "").matchAll(/<S S="Error">([^<]*)<\/S>/g)].map((x) => x[1].replace(/_x000D__x000A_/g, " ")).join("");
      results.set(
        f,
        hit ?? { ok: false, error: `OCR produced no result (exit ${r.status}, ${String(r.stdout || "").length} stdout bytes): ${(errs || String(r.stderr || "")).slice(0, 300)}` },
      );
    }
  }
  for (const v of results.values()) if (v.ok) v.lines = (v.lines ?? []).map((l) => ({ ...l, words: Array.isArray(l.words) ? l.words : l.words ? [l.words] : [] }));
  return results;
}

/* ── The targets ──────────────────────────────────────────────────────────────────────────────
   `taskKind` names the working task the frame shows from the ONE task vocabulary
   (blind-pair.mjs :: TASK_KINDS), which also specifies what OUR state must show for that task, so a
   pairing is matched by task on both sides through one definition (the self-check refuses a pairing
   whose reference declares another kind); `task` describes this frame's instance of it. `identity` is
   the text that names the product, vendor, user or workspace in that frame: blind-pair.mjs masks
   it on BOTH panels and then re-reads the pixels to prove it is gone. `expect` is text the working
   surface must show, so a blank or wrong page cannot pass as a reference. */
const FORWARD_IDENTITY = ["Forward", "Forward AI", "Forward Networks", "Forward Enterprise", "Forward Documentation", "demoguy", "Demo Network", "fwd.app"];
/* The recorded Forward header of demo jdhoywyw5voi is the same on every page (measured on all four
   rendered pages, 2026-09-29): the wordmark is a DOM logo slot (census.logoRects), but the workspace
   chip and the user menu are text in boxes that OCR masks word by word, leaving the chip's box and
   caret. Their geometry is declared here, measured on the frames, in CSS px (phase 3.5, owner: masks
   cover every identity mark). A later --fetch also records identity marks structurally (identityRects). */
const FORWARD_RECORDED_HEADER_SLOTS = [
  { x: 206, y: 5, w: 214, h: 38, why: "workspace chip 'Demo Network (default)' with its caret (measured on the frame)" },
  { x: 1770, y: 8, w: 102, h: 32, why: "user menu 'demoguy' with its avatar glyph (measured on the frame)" },
];
export const TARGETS = [
  {
    id: "forward-path-dropped",
    taskKind: "path-blocked",
    product: "Forward Enterprise",
    kind: "storylane-page",
    demo: "jdhoywyw5voi",
    pageFile: "anbgag3v",
    task: "path search result: a flow dropped by an ACL on a firewall, with hop list, topology and MTU check",
    expect: ["dropped", "path mtu"],
    identity: FORWARD_IDENTITY,
    identitySlots: FORWARD_RECORDED_HEADER_SLOTS,
    identitySlotsCheckedOn: "82e931784f0dee8b",
  },
  {
    id: "forward-topology-home",
    taskKind: "network-at-rest",
    product: "Forward Enterprise",
    kind: "storylane-page",
    demo: "jdhoywyw5voi",
    pageFile: "i9onifgy",
    task: "search home: the site map at rest with the quick path search panel",
    expect: ["quick path search"],
    identity: FORWARD_IDENTITY,
    identitySlots: FORWARD_RECORDED_HEADER_SLOTS,
    identitySlotsCheckedOn: "093cadcfc970a162",
  },
  {
    id: "forward-topology-path",
    taskKind: "path-drawn",
    product: "Forward Enterprise",
    kind: "storylane-page",
    demo: "jdhoywyw5voi",
    pageFile: "uajafk3c",
    task: "a data-centre physical topology drawn with a traced path highlighted on it",
    expect: ["physical topology"],
    identity: FORWARD_IDENTITY,
    identitySlots: FORWARD_RECORDED_HEADER_SLOTS,
    identitySlotsCheckedOn: "c1391863cbc6104a",
  },
  {
    id: "forward-path-device-details",
    taskKind: "path-result-device",
    product: "Forward Enterprise",
    kind: "storylane-page",
    demo: "jdhoywyw5voi",
    pageFile: "bfqctsok",
    task: "path search results with one device's details pane open",
    expect: ["paths"],
    identity: FORWARD_IDENTITY,
    identitySlots: FORWARD_RECORDED_HEADER_SLOTS,
    identitySlotsCheckedOn: "df303b258f1ce9f1",
  },
  {
    id: "forward-vulnerability-table",
    taskKind: "finding-list",
    product: "Forward Enterprise",
    kind: "storylane-image",
    demo: "ts9nkc4osn4z",
    /* Pinned by page id: several pages share the vulnerability URL (a CVE detail drawer among them),
       and the first URL match was that drawer, not the table. The expectation below proves which. */
    pageId: "ed47c1fb",
    /* The demo's stored screenshots are 2560 device px wide; its recorded VIDEO pages declare the
       viewport as 1920 wide, so the capture DPR is 2560/1920. Read from the demo data at fetch. */
    task: "a dense working table: devices by vulnerability, with key metrics above",
    expect: ["total devices analyzed", "key metrics"],
    identity: FORWARD_IDENTITY,
    /* A raster frame has no DOM to measure its logo slot from, so its identity slots are DECLARED —
       geometry measured on this frame, in its CSS px — and the self-check requires every raster frame
       to declare them (an empty list must say why). OCR cannot read a logo glyph (verifier round 1, D3). */
    identitySlots: [
      { x: 10, y: 5, w: 52, h: 36, why: "Forward logo glyph (measured on the stored screenshot)" },
      { x: 79, y: 7, w: 208, h: 34, why: "workspace chip 'Demo Network (default)' with its caret (measured on the stored screenshot)" },
      { x: 1770, y: 10, w: 100, h: 32, why: "user menu 'demoguy' with its avatar glyph (measured on the stored screenshot)" },
    ],
    identitySlotsCheckedOn: "2da15affda65c9a8",
  },
  {
    id: "ipfabric-path-detail",
    taskKind: "path-hop-decision",
    product: "IP Fabric",
    kind: "docs-image",
    url: "https://docs.ipfabric.io/latest/images/diagrams/diagrams_pathlookup-path-detail.webp",
    dpr: 1,
    task: "path lookup detail: path topology, per-hop decision table and packet diff (evidence behind a path result)",
    expect: ["decision table", "path inspector"],
    identity: ["IP Fabric", "IPFabric", "ipfabric"],
    identitySlots: [],
    identitySlotsNote: "No logo, product name or user area in this frame: it opens at the Network Viewer rail, below the application header (checked on the frame).",
    identitySlotsCheckedOn: "19aab68e7ad71283",
  },
  {
    id: "ipfabric-path-lookup-app",
    taskKind: "path-query-form",
    product: "IP Fabric",
    kind: "docs-image",
    url: "https://docs.ipfabric.io/latest/images/diagrams/diagrams_pathlookup-src-dst-aim-suggestions.webp",
    dpr: 2,
    task: "the whole application on its path lookup surface",
    expect: ["path"],
    identity: ["IP Fabric", "IPFabric", "ipfabric"],
    identitySlots: [
      { x: 12, y: 10, w: 26, h: 28, why: "IP Fabric logo glyph (measured on the frame)" },
      { x: 1484, y: 10, w: 32, h: 30, why: "user avatar (measured on the frame)" },
    ],
    identitySlotsCheckedOn: "e16ba01d18d28ded",
  },
  {
    id: "grafana-explore",
    taskKind: "result-data-inspection",
    product: "Grafana",
    kind: "live",
    url: "https://play.grafana.org/explore",
    task: "inspecting query results and the underlying data (Explore)",
    expect: ["query inspector", "query history"],
    identity: ["Grafana", "Powered by Grafana", "Grafana Labs", "Grafana Cloud", "play.grafana.org", "Sign in"],
    identitySlots: [],
    identitySlotsNote:
      "The logo is a DOM logo slot (census.logoRects); signed out, so there is no workspace or user chip ('Sign in' and the '-- Grafana --' data source name are text, masked by OCR) (checked on the frame).",
    control: true,
    identitySlotsCheckedOn: "e58f13456db913e6",
  },
  {
    id: "grafana-node-graph-kiosk",
    taskKind: "network-at-rest",
    product: "Grafana",
    kind: "live",
    url: "https://play.grafana.org/d/bdodfbi3d57uoe/node-graph-panel?kiosk",
    task: "a network-relevant dashboard (node graph) in kiosk mode",
    expect: ["node graph panel"],
    identity: ["Grafana", "Powered by Grafana", "Grafana Labs", "Grafana Cloud", "play.grafana.org", "Sign in"],
    identitySlots: [{ x: 1745, y: 1050, w: 165, h: 28, why: "'Powered by Grafana' footer with its logo glyph (measured on the frame)" }],
    identitySlotsCheckedOn: "fbbbfc19645849bf",
  },
];
export const UNOBTAINABLE = [
  {
    product: "Linear",
    reason:
      "No full working view is obtainable without an account: there is no public workspace, and the documentation figures (e.g. custom-views, source asset 2494x1021) are zoomed crops of part of a window on a marketing gradient, not a working screen. Linear is out of scope for C1 unless the owner supplies a capture of their own signed-in workspace.",
  },
];

/* ── DOM census (runs in the page) ───────────────────────────────────────────────────────── */
function domCensus({ overlayRoles, tourClass, identity }) {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    if (r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && Number(cs.opacity) > 0.05;
  };
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
  };
  const tourRe = new RegExp(tourClass);
  const overlays = [...document.querySelectorAll(overlayRoles)].filter(visible).map((el) => ({
    role: el.getAttribute("role") || (el.getAttribute("aria-modal") ? "aria-modal" : ""),
    text: (el.innerText || "").replace(/\s+/g, " ").slice(0, 160),
    ...box(el),
  }));
  const tourLayer = [...document.querySelectorAll("[class]")]
    .filter((el) => tourRe.test(String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className)) && visible(el))
    .map((el) => ({ cls: String(el.className).slice(0, 80), ...box(el) }));
  const ids = identity.map((s) => s.toLowerCase());
  const logos = [...document.querySelectorAll('a[href="/"], a[href="./"], img, svg')]
    .filter(visible)
    .filter((el) => {
      if (el.tagName === "A") return el.getBoundingClientRect().top < 160;
      const name = `${el.getAttribute("alt") || ""} ${el.getAttribute("aria-label") || ""} ${el.getAttribute("title") || ""} ${el.querySelector?.("title")?.textContent || ""}`.toLowerCase();
      return ids.some((t) => name.includes(t));
    })
    .map(box);
  const closeControls = [...document.querySelectorAll("[aria-label]")]
    .filter(visible)
    .map((el) => el.getAttribute("aria-label"))
    .filter((l) => /^close/i.test(l));
  return {
    closeControls,
    text: (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 20000),
    overlays,
    tourLayer,
    logoRects: logos,
    luminance: null,
  };
}
/** Identity marks measured in the page's DOM with the same census that measures OUR identity
    (blind-pair.mjs :: identityCensus): every visible element holding an identity string, widened to its
    compact block (a chip, a user menu), so a mask covers the mark rather than the words OCR read. */
async function identityRectsIn(page, identity) {
  const { identityCensus, IDENTITY_BLOCK_MAX } = await import("./blind-pair.mjs");
  return page.evaluate(identityCensus, { identity, maxH: IDENTITY_BLOCK_MAX.h, maxWFrac: IDENTITY_BLOCK_MAX.wFrac });
}
const CENSUS = (identity) => `(${domCensus.toString()})(${JSON.stringify({ overlayRoles: OVERLAY_ROLES, tourClass: TOUR_LAYER_CLASS.source, identity })})`;

/** Mean luminance of a PNG, measured in the browser: the frame's THEME is measured, not declared. */
async function measureTheme(page, file) {
  const uri = `data:image/png;base64,${readFileSync(file).toString("base64")}`;
  return page.evaluate(async (src) => {
    const img = new Image();
    img.src = src;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = 192;
    c.height = Math.max(1, Math.round((192 * img.naturalHeight) / img.naturalWidth));
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0, c.width, c.height);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let s = 0;
    for (let i = 0; i < d.length; i += 4) s += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
    const mean = s / (d.length / 4) / 255;
    return { meanLuminance: Math.round(mean * 1000) / 1000, theme: mean < 0.45 ? "dark" : "light" };
  }, uri);
}

/* ── Storylane page renderer (offline, JavaScript disabled) ──────────────────────────────── */
const VOID = new Set(["AREA", "BASE", "BR", "COL", "EMBED", "HR", "IMG", "INPUT", "LINK", "META", "SOURCE", "TRACK", "WBR"]);
const escText = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escAttr = (s) => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
function serialise(n, parentTag) {
  if (!n) return "";
  if (n.nodeType === 3) return parentTag === "STYLE" ? n.textContent || "" : escText(n.textContent || "");
  if (n.nodeType !== 1) return "";
  if (n.tagName === "SCRIPT") return "";
  const attrs = n.attributes || {};
  if (n.tagName === "CANVAS") {
    /* The recorder stores a canvas's pixels as a data: background image on the element, which a
       JavaScript-disabled render paints at 0x0. Replace it with the image it recorded. */
    const st = attrs.style || "";
    const m = st.match(/url\("(data:image\/(?:png|jpeg|webp);base64,[^"]+)"\)/);
    if (!m) return "";
    const keep = st
      .split(";")
      .filter((p) => /^\s*(width|height|transform|position|left|top|right|bottom|opacity|z-index)\s*:/.test(p))
      .join(";");
    return `<img src="${m[1]}" style="display:block;${escAttr(keep)}" class="${escAttr(attrs.class || "")}">`;
  }
  const tag = n.isSvg ? n.tagName : n.tagName.toLowerCase();
  const a = Object.entries(attrs)
    .filter(([k]) => !/^on/i.test(k))
    .map(([k, v]) => ` ${k}="${escAttr(v)}"`)
    .join("");
  if (VOID.has(n.tagName)) return `<${tag}${a}>`;
  return `<${tag}${a}>${(n.childNodes || []).map((c) => serialise(c, n.tagName)).join("")}</${tag}>`;
}

async function fetchOk(url, as = "text") {
  const r = await fetch(url, { headers: { "user-agent": UA } });
  if (!r.ok) throw new Error(`GET ${url} -> ${r.status}`);
  return as === "buffer" ? Buffer.from(await r.arrayBuffer()) : r.text();
}
const demoCache = new Map();
/** The demo's page list, from the server-rendered data of a plain GET (no player, no analytics). */
async function storylaneProject(demo) {
  if (demoCache.has(demo)) return demoCache.get(demo);
  const html = await fetchOk(`https://app.storylane.io/demo/${demo}`);
  const m = html.match(/<script id="__NEXT_DATA__" type="application\/json">([\s\S]*?)<\/script>/);
  if (!m) throw new Error(`demo ${demo}: no server-rendered page data`);
  const data = JSON.parse(JSON.parse(m[1]).props.pageProps.ssResponseDataStr);
  const project = Object.values(data.data.entities.projects)[0];
  demoCache.set(demo, project);
  return project;
}

async function captureStorylanePage(browser, t) {
  const project = await storylaneProject(t.demo);
  const pg = project.pages.find((p) => String(p.file_url || "").split("/").pop().startsWith(t.pageFile));
  if (!pg) throw new Error(`demo ${t.demo}: no page file starting ${t.pageFile}`);
  const body = await fetchOk(pg.file_url);
  const json = JSON.parse(body);
  const w = Math.round(pg.dimensions.width);
  const h = Math.round(pg.dimensions.height);
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, javaScriptEnabled: false, userAgent: UA });
  const page = await ctx.newPage();
  await page.setContent(`<!DOCTYPE html>${serialise(json[1])}`, { waitUntil: "load", timeout: 90000 });
  await page.waitForTimeout(1500);
  const buf = await page.screenshot({ animations: "disabled", scale: "device" });
  /* The census needs script; the page's own script is gone, this one is ours. */
  const cctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1, javaScriptEnabled: true });
  const cpage = await cctx.newPage();
  await cpage.setContent(`<!DOCTYPE html>${serialise(json[1])}`, { waitUntil: "load", timeout: 90000 });
  const census = await cpage.evaluate(CENSUS(t.identity));
  census.identityRects = await identityRectsIn(cpage, t.identity);
  await cctx.close();
  await ctx.close();
  return {
    buf,
    css: { w, h },
    dpr: 2,
    census,
    source: { url: pg.file_url, pageId: pg.id, recordedUrl: pg.url, demo: `https://app.storylane.io/demo/${t.demo}`, sha256: sha256(Buffer.from(body)) },
    provenance: STORYLANE_NOTE,
  };
}

async function captureStorylaneImage(t) {
  const project = await storylaneProject(t.demo);
  const pg = project.pages.find((p) => p.kind === "image" && String(p.id).startsWith(t.pageId));
  if (!pg) throw new Error(`demo ${t.demo}: no image page with id ${t.pageId}…`);
  const video = project.pages.find((p) => p.kind === "video" && p.dimensions?.width);
  if (!video) throw new Error(`demo ${t.demo}: no video page declares the recorded viewport, so the stored screenshot's DPR is unknown`);
  const buf = await fetchOk(pg.file_url, "buffer");
  const dpr = pg.dimensions.width / video.dimensions.width;
  return {
    buf,
    css: { w: Math.round(pg.dimensions.width / dpr), h: Math.round(pg.dimensions.height / dpr) },
    dpr,
    census: null,
    source: { url: pg.file_url, pageId: pg.id, recordedUrl: pg.url, demo: `https://app.storylane.io/demo/${t.demo}`, sha256: sha256(buf), dprFrom: `stored ${pg.dimensions.width}px / recorded viewport ${video.dimensions.width}px (video page)` },
    provenance: STORYLANE_NOTE + " A stored page screenshot; the tour is drawn by the player over it and is not in these pixels.",
  };
}

async function captureDocsImage(browser, t) {
  const src = await fetchOk(t.url, "buffer");
  /* WebP -> PNG, pixel for pixel: the image at DPR 1, screenshotted at its natural size. */
  const ctx = await browser.newContext({ viewport: { width: 800, height: 600 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await page.setContent(`<body style="margin:0"><img id="i" style="display:block" src="data:image/webp;base64,${src.toString("base64")}"></body>`);
  const nat = await page.$eval("#i", async (i) => (await i.decode(), { w: i.naturalWidth, h: i.naturalHeight }));
  await page.setViewportSize({ width: nat.w, height: nat.h });
  const buf = await (await page.$("#i")).screenshot();
  await ctx.close();
  return {
    buf,
    css: { w: Math.round(nat.w / t.dpr), h: Math.round(nat.h / t.dpr) },
    dpr: t.dpr,
    census: null,
    source: { url: t.url, sha256: sha256(src) },
    provenance: "IP Fabric documentation screenshot of the product (unannotated). Its capture DPR is not published; declared from its text size.",
  };
}

const GRAFANA_SEED = {
  "grafana.grafana-setupguide-app.banners.play-cta-explore-signup": "false",
  "grafana.navigation.docked": "false",
};
async function captureLive(browser, t, { seed = true } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2, colorScheme: "dark", userAgent: UA });
  if (seed)
    await ctx.addInitScript((kv) => {
      try {
        for (const [k, v] of Object.entries(kv)) localStorage.setItem(k, v);
      } catch {}
    }, GRAFANA_SEED);
  const page = await ctx.newPage();
  await page.goto(t.url, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(14000);
  await page.mouse.move(1919, 1079);
  await page.waitForTimeout(800);
  const census = await page.evaluate(CENSUS(t.identity));
  census.identityRects = await identityRectsIn(page, t.identity);
  const buf = await page.screenshot({ animations: "disabled", scale: "device" });
  await ctx.close();
  return {
    buf,
    css: { w: 1920, h: 1080 },
    dpr: 2,
    census,
    source: { url: t.url, seededLocalStorage: seed ? GRAFANA_SEED : null },
    provenance: seed ? "play.grafana.org, rendered live; promo banner dismissed and menu undocked by pre-seeded localStorage." : "CONTROL: rendered live with NOTHING dismissed. It must be flagged.",
  };
}

async function fetchAll(only) {
  mkdirSync(REFS_DIR, { recursive: true });
  /* One read, no exists-check first (CodeQL js/file-system-race): no manifest yet is the empty set; one that is
     there but will not parse still stops the run, as before. */
  let prior;
  try {
    prior = JSON.parse(readFileSync(MANIFEST, "utf8"));
  } catch (e) {
    if (e?.code !== "ENOENT") throw e;
    prior = { frames: [], controls: [] };
  }
  const frames = new Map(prior.frames.map((f) => [f.id, f]));
  const controls = new Map((prior.controls ?? []).map((f) => [f.id, f]));
  const browser = await chromium.launch();
  const failures = [];
  const themePage = await (await browser.newContext()).newPage();
  const record = async (t, r, id = t.id) => {
    const file = resolve(REFS_DIR, `${id}.png`);
    writeFileSync(file, r.buf);
    const theme = await measureTheme(themePage, file);
    return {
      id,
      product: t.product,
      kind: t.kind,
      task: t.task,
      expect: t.expect,
      identity: t.identity,
      file: rel(file),
      sha256: sha256(r.buf),
      css: r.css,
      dpr: r.dpr,
      ...theme,
      source: r.source,
      provenance: r.provenance,
      census: r.census,
      capturedAt: new Date().toISOString(),
    };
  };
  for (const t of TARGETS) {
    if (only && t.id !== only) continue;
    try {
      const r =
        t.kind === "storylane-page"
          ? await captureStorylanePage(browser, t)
          : t.kind === "storylane-image"
            ? await captureStorylaneImage(t)
            : t.kind === "docs-image"
              ? await captureDocsImage(browser, t)
              : await captureLive(browser, t);
      frames.set(t.id, await record(t, r));
      console.log(`  ok   ${t.id}`);
      if (t.control) {
        const c = await captureLive(browser, t, { seed: false });
        controls.set(`${t.id}.control-undismissed`, { ...(await record(t, c, `${t.id}.control-undismissed`)), mustBeFlagged: true });
        console.log(`  ok   ${t.id}.control-undismissed (control)`);
      }
    } catch (e) {
      failures.push({ id: t.id, error: String(e).slice(0, 300) });
      console.log(`  FAIL ${t.id}: ${String(e).slice(0, 200)}`);
    }
  }
  await browser.close();
  const manifest = {
    schema: "atlas-scope/refs-clean/1",
    note: "Third-party product imagery for INTERNAL blind comparison only. Untracked (review/shots/ is gitignored); never publish.",
    frames: TARGETS.map((t) => frames.get(t.id)).filter(Boolean),
    controls: [...controls.values()],
    unobtainable: UNOBTAINABLE,
    lastFetch: { at: new Date().toISOString(), failures },
  };
  writeFileSync(MANIFEST, JSON.stringify(manifest, null, 1));
  return failures;
}

/* ── Checks ──────────────────────────────────────────────────────────────────────────────── */

/** Markers on the DOM layer of one frame (null census = no DOM layer, NOT clean). */
export function domMarkers(census) {
  if (!census) return null;
  const found = [];
  for (const o of census.overlays ?? []) found.push(`overlay role=${o.role} "${o.text.slice(0, 60)}"`);
  for (const c of census.tourLayer ?? []) found.push(`tour-layer class ${c.cls}`);
  for (const p of phrasesIn(census.text ?? "", TOUR_BANNER_PHRASES)) found.push(`DOM text "${p}"`);
  return found;
}

/** Pairings sharing a byte-identical reference without declaring it. `shaOf(refId)` -> sha. */
export function sharedReferenceViolations(pairings, shaOf) {
  const bySha = new Map();
  for (const p of pairings) {
    const s = shaOf(p.ref);
    if (!s) continue;
    if (!bySha.has(s)) bySha.set(s, []);
    bySha.get(s).push(p);
  }
  const out = [];
  for (const [s, ps] of bySha) {
    if (ps.length < 2) continue;
    for (const p of ps) {
      const others = ps.filter((q) => q !== p).map((q) => q.id);
      const declared = new Set(p.sharesReferenceWith ?? []);
      const undeclared = others.filter((o) => !declared.has(o));
      if (undeclared.length) out.push(`${p.id} shares reference ${s.slice(0, 12)} with ${undeclared.join(", ")} (undeclared)`);
    }
  }
  return out;
}

/** Frames whose bytes are identical (the step3 == step6 class). */
export function duplicateFrames(frames) {
  const by = new Map();
  for (const f of frames) {
    if (!by.has(f.sha256)) by.set(f.sha256, []);
    by.get(f.sha256).push(f.id);
  }
  return [...by.values()].filter((ids) => ids.length > 1).map((ids) => `byte-identical frames: ${ids.join(" = ")}`);
}

/* ── Near-identical SCREENS, not only identical bytes ─────────────────────────────────────────
   Byte identity is the narrow case. Two pairings whose references are the same kind of screen (the
   same product view with a different highlighted path) present a critic with one reference twice, so
   the check is perceptual: the Pearson correlation of 48x27 luminance thumbnails. Calibrated on the
   2026-09-28 set: the two Forward path-result recordings correlate at 0.92; every other pair of
   frames at 0.77 or below (verifier round 1, D6). A pairing may DECLARE a similar screen, with its
   reason, in `similarScreenWith`; an undeclared one fails. */
export const SIMILAR_SCREEN = 0.85;
export function screenCorrelation(a, b) {
  if (!a || !b || a.length !== b.length || !a.length) return null;
  const z = (v) => {
    const m = v.reduce((s, x) => s + x, 0) / v.length;
    const sd = Math.sqrt(v.reduce((s, x) => s + (x - m) ** 2, 0) / v.length) || 1;
    return v.map((x) => (x - m) / sd);
  };
  const A = z(a);
  const B = z(b);
  return A.reduce((s, x, i) => s + x * B[i], 0) / A.length;
}
export function similarScreenViolations(pairings, thumbOf, threshold = SIMILAR_SCREEN) {
  const out = [];
  for (let i = 0; i < pairings.length; i++)
    for (let j = i + 1; j < pairings.length; j++) {
      const p = pairings[i];
      const q = pairings[j];
      if (p.ref === q.ref) continue; /* the same frame: the byte-identity check owns that case */
      const c = screenCorrelation(thumbOf(p.ref), thumbOf(q.ref));
      if (c === null || c < threshold) continue;
      const why = String(p.similarScreenWith?.[q.id] ?? q.similarScreenWith?.[p.id] ?? "").trim();
      if (!why) out.push(`${p.id} and ${q.id}: their references ${p.ref} and ${q.ref} are the same kind of screen (correlation ${c.toFixed(2)} >= ${threshold}) and neither pairing declares it`);
    }
  return out;
}
/** 48x27 luminance thumbnails of PNG files, computed in a browser page. */
async function thumbnails(page, files) {
  const out = new Map();
  for (const f of files) {
    const uri = `data:image/png;base64,${readFileSync(f).toString("base64")}`;
    out.set(
      f,
      await page.evaluate(async (src) => {
        const img = new Image();
        img.src = src;
        await img.decode();
        const c = document.createElement("canvas");
        c.width = 48;
        c.height = 27;
        const g = c.getContext("2d");
        g.drawImage(img, 0, 0, 48, 27);
        const d = g.getImageData(0, 0, 48, 27).data;
        const v = [];
        for (let k = 0; k < d.length; k += 4) v.push((0.2126 * d[k] + 0.7152 * d[k + 1] + 0.0722 * d[k + 2]) / 255);
        return v;
      }, uri),
    );
  }
  return out;
}

/** Declared identity slots (and a declared "no slots" note) are geometry measured on ONE frame, so each
    TARGET names that frame by its sha256 prefix (identitySlotsCheckedOn, at least 12 hex). A frame
    that relies on them (no DOM-measured identityRects) whose bytes are not that frame — a re-fetch, a
    changed recording — is refused until they are re-measured on it (verifier V8). */
export function staleIdentitySlots(frames, targets) {
  const out = [];
  for (const f of frames) {
    if (Array.isArray(f.census?.identityRects)) continue;
    const t = targets.find((x) => x.id === f.id);
    if (!t || !Array.isArray(t.identitySlots)) continue;
    const on = typeof t.identitySlotsCheckedOn === "string" && /^[0-9a-f]{12,64}$/.test(t.identitySlotsCheckedOn) ? t.identitySlotsCheckedOn : null;
    if (!on) out.push(`${f.id}: declares identity slots without the frame they were measured on`);
    else if (!String(f.sha256 ?? "").startsWith(on)) out.push(`${f.id}: slots measured on ${on}, frame is ${String(f.sha256 ?? "?").slice(0, 16)}`);
  }
  return out;
}

/** Every frame whose identity marks were not MEASURED in its DOM (a raster frame, or a DOM census from
    before identityRects existed, which located only logo slots) must DECLARE its identity slots — an
    empty list with a reason. OCR alone never stands for "covered". */
export function undeclaredIdentitySlots(frames, targets) {
  return frames
    .filter((f) => !Array.isArray(f.census?.identityRects))
    .map((f) => ({ f, t: targets.find((t) => t.id === f.id) }))
    .filter(({ t }) => !t || !Array.isArray(t.identitySlots) || (t.identitySlots.length === 0 && !String(t.identitySlotsNote ?? "").trim()))
    .map(({ f }) => f.id);
}

async function positiveControls() {
  const out = [];
  const ok = (name, pass, detail = "") => out.push({ name, pass, detail });
  // 1. phrase matcher on OCR-like noise
  ok("matcher: flags 'Made with Storylane' in OCR noise", phrasesIn("Next  Made wlth Storylane ©", TOUR_BANNER_PHRASES).includes("made with storylane"));
  ok("matcher: flags a sign-up banner", phrasesIn("Create free acc0unt to save your queries", TOUR_BANNER_PHRASES).length > 0);
  ok("matcher: does not flag a product word containing a brand word", findPhrase(tokens("l3_forwarding[3] forwarding table"), "forward").length === 0);
  ok("matcher: finds an OCR-mangled wordmark", findPhrase(tokens("FORW7RD Forward Al Network Maps"), "forward").length > 0);
  // 2. duplicate-reference checks
  const dupPairs = [
    { id: "a", ref: "x" },
    { id: "b", ref: "y" },
  ];
  const sameSha = (id) => ({ x: "s1", y: "s1" })[id];
  ok("shared-reference check: flags two pairings on one byte-identical frame", sharedReferenceViolations(dupPairs, sameSha).length === 2);
  ok(
    "shared-reference check: a declared share passes",
    sharedReferenceViolations(
      [
        { id: "a", ref: "x", sharesReferenceWith: ["b"] },
        { id: "b", ref: "y", sharesReferenceWith: ["a"] },
      ],
      sameSha,
    ).length === 0,
  );
  ok("duplicate-frame check: flags byte-identical frames", duplicateFrames([{ id: "s3", sha256: "e" }, { id: "s6", sha256: "e" }]).length === 1);
  const th = { x: [0, 1, 0, 1, 0.5, 0.2], y: [0.1, 0.9, 0.1, 0.9, 0.5, 0.25], z: [1, 0, 0.3, 0.2, 0.9, 0] };
  const simPairs = [
    { id: "a", ref: "x" },
    { id: "b", ref: "y" },
    { id: "c", ref: "z" },
  ];
  ok("similar-screen check: flags two pairings on near-identical screens, and only them", similarScreenViolations(simPairs, (id) => th[id]).length === 1);
  ok(
    "similar-screen check: a declared similar screen, with a reason, passes",
    similarScreenViolations([{ ...simPairs[0], similarScreenWith: { b: "judged on different dimensions" } }, simPairs[1], simPairs[2]], (id) => th[id]).length === 0,
  );
  ok("identity-slot check: a raster frame without declared slots is flagged", undeclaredIdentitySlots([{ id: "r", census: null }, { id: "d", census: { identityRects: [] } }], [{ id: "r" }, { id: "d" }]).join() === "r");
  /* phase 3.5: a DOM census that measured only logo slots does not locate a workspace chip or a user
     menu, so a DOM frame without measured identity marks must declare them too. */
  ok("identity-slot check: a DOM frame with no measured identity marks and no declared slots is flagged", undeclaredIdentitySlots([{ id: "d", census: { logoRects: [{ x: 1, y: 1, w: 9, h: 9 }] } }], [{ id: "d" }]).join() === "d");
  ok("identity-slot binding: slots measured on another frame, or on no named frame, are flagged; on this frame they pass", (() => {
    const tg = [{ id: "r", identitySlots: [{ x: 1, y: 1, w: 9, h: 9 }], identitySlotsCheckedOn: "aaaaaaaaaaaa" }];
    return staleIdentitySlots([{ id: "r", sha256: "aaaaaaaaaaaa77" }], tg).length === 0 && staleIdentitySlots([{ id: "r", sha256: "bbbbbbbbbbbb77" }], tg).length === 1 && staleIdentitySlots([{ id: "r", sha256: "aaaaaaaaaaaa77" }], [{ id: "r", identitySlots: [] }]).length === 1 && staleIdentitySlots([{ id: "r", sha256: "x", census: { identityRects: [] } }], [{ id: "r", identitySlots: [] }]).length === 0;
  })());
  // 3. the DOM layer flags an overlay role and the tour layer's classes
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
    await page.setContent(
      `<main style="height:800px;background:#fff">product</main><div class="WidgetManagerHtml_root__a1"><div role="dialog" style="position:fixed;left:400px;top:250px;width:420px;height:220px;background:#fff;border:2px solid #9939eb;font:600 28px system-ui;padding:24px">End-to-End Path Search Demo<p style="font:400 22px system-ui">In this demo we are going to investigate a path.</p><div class="PlayerButton_root__KQ0uR" style="background:#e97438;color:#fff;width:120px;padding:8px">Next</div></div></div><div style="position:fixed;right:8px;bottom:8px;font:500 22px system-ui">Made with Storylane</div>`,
    );
    /* The perceptual measure on rendered pixels: one layout with the highlight moved must read as the
       same screen; a different layout must not. */
    mkdirSync(WORK, { recursive: true });
    const rows = (n, h, a, b) => Array.from({ length: n }, (_, i) => `<div style="height:${h}px;background:${i % 2 ? a : b}"></div>`).join("");
    const boxes = [60, 380, 700].flatMap((x) => [80, 360].map((y) => `<div style="position:absolute;left:${x}px;top:${y}px;width:240px;height:200px;border:3px solid #6b7280;background:#2a2e36"></div>`)).join("");
    const layout = (hl) =>
      `<body style="margin:0;background:#1b1d22"><div style="height:48px;background:#3a3f4b"></div><div style="display:flex"><div style="width:300px">${rows(14, 50, "#23262c", "#30343c")}</div><div style="flex:1;position:relative;height:700px">${boxes}<div style="position:absolute;left:${hl}px;top:300px;width:160px;height:4px;background:#e97438"></div></div></div></body>`;
    const other = `<body style="margin:0;background:#f5f6f8"><div style="height:90px;background:#1f4b7a"></div>${Array.from({ length: 14 }, (_, i) => `<div style="height:40px;border-bottom:1px solid #cdd3da;background:${i % 2 ? "#fff" : "#eef1f4"}"></div>`).join("")}</body>`;
    const shots = [];
    for (const [n, html] of [["same-1", layout(120)], ["same-2", layout(360)], ["other", other]]) {
      await page.setContent(html);
      const f = resolve(WORK, `control-screen-${n}.png`);
      await page.screenshot({ path: f });
      shots.push(f);
    }
    const tn = await thumbnails(page, shots);
    const cSame = screenCorrelation(tn.get(shots[0]), tn.get(shots[1]));
    const cOther = screenCorrelation(tn.get(shots[0]), tn.get(shots[2]));
    ok(
      "screen correlation: one layout with its highlight moved is the same screen; another layout is not",
      cSame >= SIMILAR_SCREEN && cOther < SIMILAR_SCREEN,
      `same ${cSame?.toFixed(2)}, other ${cOther?.toFixed(2)}`,
    );
    await page.setContent(
      `<main style="height:800px;background:#fff">product</main><div class="WidgetManagerHtml_root__a1"><div role="dialog" style="position:fixed;left:400px;top:250px;width:420px;height:220px;background:#fff;border:2px solid #9939eb;font:600 28px system-ui;padding:24px">End-to-End Path Search Demo<p style="font:400 22px system-ui">In this demo we are going to investigate a path.</p><div class="PlayerButton_root__KQ0uR" style="background:#e97438;color:#fff;width:120px;padding:8px">Next</div></div></div><div style="position:fixed;right:8px;bottom:8px;font:500 22px system-ui">Made with Storylane</div>`,
    );
    const census = await page.evaluate(CENSUS([]));
    const dm = domMarkers(census);
    const idr = await identityRectsIn(page, ["Storylane"]);
    ok("DOM layer: measures an identity mark's geometry at capture (identityRects)", idr.length === 1 && idr[0].x > 900 && idr[0].y > 700 && idr[0].w < 400, JSON.stringify(idr));
    ok("DOM layer: flags an overlay dialog and the tour-layer classes", dm.some((m) => m.startsWith("overlay")) && dm.some((m) => m.startsWith("tour-layer")), dm.join("; "));
    mkdirSync(WORK, { recursive: true });
    const f = resolve(WORK, "control-synthetic-tour.png");
    await page.screenshot({ path: f });
    const ocr = ocrImages([f]).get(resolve(f));
    const hits = ocr?.ok ? phrasesIn(ocr.text, TOUR_BANNER_PHRASES) : [];
    ok("OCR layer: available on this host", !!ocr?.ok, ocr?.ok ? "" : ocr?.error);
    ok("OCR layer: flags a synthetic Storylane tour card from its PIXELS", hits.length > 0, hits.join(", "));
  } finally {
    await browser.close();
  }
  return out;
}

export async function selfCheck({ pairings } = {}) {
  let failed = 0;
  const line = (ok, msg) => {
    console.log(`${ok ? "  ok  " : "  FAIL"} ${msg}`);
    if (!ok) failed++;
  };
  console.log("positive controls (each must trip on a known-bad input):");
  for (const c of await positiveControls()) line(c.pass, `${c.name}${c.detail ? ` — ${c.detail}` : ""}`);

  console.log("reference set:");
  if (!existsSync(MANIFEST)) {
    line(false, `no reference set at ${rel(MANIFEST)} — UNPROVEN, not clean. Run: node review/capture-refs-clean.mjs --fetch`);
    return failed;
  }
  const man = JSON.parse(readFileSync(MANIFEST, "utf8"));
  const frames = man.frames ?? [];
  const controls = man.controls ?? [];
  const missingTargets = TARGETS.filter((t) => !frames.some((f) => f.id === t.id)).map((t) => t.id);
  line(missingTargets.length === 0, `every target captured${missingTargets.length ? ` — missing: ${missingTargets.join(", ")}` : ` (${frames.length})`}`);
  for (const u of man.unobtainable ?? []) console.log(`  n/a   ${u.product}: not obtainable — ${u.reason.split(".")[0]}.`);

  const all = [...frames, ...controls];
  const present = all.filter((f) => existsSync(fromRel(f.file)));
  for (const f of all) {
    if (!existsSync(fromRel(f.file))) line(false, `${f.id}: file missing (${f.file})`);
    else {
      const s = sha256(readFileSync(fromRel(f.file)));
      if (s !== f.sha256) line(false, `${f.id}: sha256 changed since capture (${s.slice(0, 12)} != ${f.sha256.slice(0, 12)})`);
    }
  }
  const ocr = ocrImages(present.map((f) => fromRel(f.file)));
  for (const f of present) {
    const o = ocr.get(resolve(fromRel(f.file)));
    const dom = domMarkers(f.census);
    const px = o?.ok ? phrasesIn(o.text, TOUR_BANNER_PHRASES).map((p) => `pixel text "${p}"`) : null;
    const markers = [...(dom ?? []), ...(px ?? [])];
    const layers = `${dom === null ? "no DOM layer (raster source)" : "DOM"} + ${px === null ? `OCR UNAVAILABLE (${o?.error ?? "?"})` : "OCR"}`;
    if (f.mustBeFlagged) {
      /* A control only proves something if the wrapper was actually served to this session. */
      const established = (f.census?.closeControls ?? []).some((l) => /close alert/i.test(l));
      if (!established) {
        console.log(`  info  control ${f.id}: the promo banner was not served to this capture session (no "Close alert" control in its DOM), so this control proves nothing; real-banner detection rests on the synthetic control above`);
        continue;
      }
      line(markers.length > 0, `control ${f.id}: ${markers.length ? `flagged as it must be — ${markers.slice(0, 3).join("; ")}` : "NOT flagged — the marker check is blind to the real banner"}`);
      continue;
    }
    if (px === null) {
      line(false, `${f.id}: pixel layer unavailable, so the frame is UNPROVEN clean (${layers})`);
      continue;
    }
    line(markers.length === 0, `${f.id}: ${markers.length ? `CARRIES tour/banner markers — ${markers.join("; ")}` : "no tour/banner marker"} [${layers}; ${f.css.w}x${f.css.h} css @${Math.round(f.dpr * 100) / 100}x, ${f.theme}]`);
    /* The expectation is the CODE's (TARGETS), so tightening it re-judges frames already on disk. */
    const expect = TARGETS.find((t) => t.id === f.id)?.expect ?? f.expect ?? [];
    const missing = expect.filter((e) => !phrasesIn(o.text, [e]).length);
    line(expect.length > 0, `${f.id}: declares what working surface it must show${expect.length ? "" : " — no expectation: a blank or wrong page would pass"}`);
    line(missing.length === 0, `${f.id}: shows its working surface${missing.length ? ` — expected text not in the pixels: ${missing.join(", ")}` : ` (${expect.join(", ")})`}`);
  }
  for (const d of duplicateFrames(frames)) line(false, d);
  if (!duplicateFrames(frames).length) line(true, `no two reference frames are byte-identical (${frames.length} frames, ${new Set(frames.map((f) => f.sha256)).size} distinct)`);

  const bp = await import("./blind-pair.mjs");
  let ps = pairings;
  if (!ps) ps = bp.PAIRINGS;
  /* Task matching (phase 3.5): every TARGET names a kind from the one vocabulary, and every pairing's
     reference declares the pairing's kind. A detector that passes its known-bad input is broken. */
  const badKinds = TARGETS.filter((t) => !Object.hasOwn(bp.TASK_KINDS, t.taskKind)).map((t) => `${t.id} (${JSON.stringify(t.taskKind)})`);
  line(badKinds.length === 0, `every reference target names a task kind from the vocabulary${badKinds.length ? ` — not: ${badKinds.join(", ")}` : ` (${TARGETS.length})`}`);
  const control = bp.taskKindProblems([{ id: "control", task: "path-hop-decision", ref: "forward-vulnerability-table" }], TARGETS);
  line(control.length === 1, `task-match check: flags a pairing whose reference shows another task (control) — ${control.join("; ") || "NOT flagged"}`);
  const mismatched = bp.taskKindProblems(ps, TARGETS);
  for (const m of mismatched) line(false, `pairing not matched by task: ${m}`);
  if (!mismatched.length) line(true, `every pairing's reference shows the pairing's task kind (${ps.map((p) => `${p.id}: ${p.task}`).join(", ")})`);
  const shaOf = (id) => frames.find((f) => f.id === id)?.sha256;
  const unknown = ps.filter((p) => !shaOf(p.ref)).map((p) => `${p.id} -> ${p.ref}`);
  line(unknown.length === 0, `every pairing's reference is in the set${unknown.length ? ` — missing: ${unknown.join(", ")}` : ` (${ps.length} pairings)`}`);
  const shared = sharedReferenceViolations(ps, shaOf);
  for (const s of shared) line(false, s);
  if (!shared.length) line(true, `no two pairings share a byte-identical reference (${ps.length} pairings, ${new Set(ps.map((p) => shaOf(p.ref))).size} distinct references)`);

  /* Near-identical SCREENS across pairings (D6), measured on the frames on disk. */
  const refFrames = [...new Set(ps.map((p) => p.ref))].map((id) => frames.find((f) => f.id === id)).filter((f) => f && existsSync(fromRel(f.file)));
  const browser = await chromium.launch();
  let tn;
  try {
    tn = await thumbnails(await browser.newPage(), refFrames.map((f) => fromRel(f.file)));
  } finally {
    await browser.close();
  }
  const thumbOf = (id) => {
    const f = frames.find((x) => x.id === id);
    return f ? tn.get(fromRel(f.file)) : null;
  };
  const similar = similarScreenViolations(ps, thumbOf);
  for (const s of similar) line(false, s);
  const declaredSimilar = [];
  for (let i = 0; i < ps.length; i++)
    for (let j = i + 1; j < ps.length; j++) {
      const c = screenCorrelation(thumbOf(ps[i].ref), thumbOf(ps[j].ref));
      if (c !== null && c >= SIMILAR_SCREEN && ps[i].ref !== ps[j].ref) declaredSimilar.push(`${ps[i].id} ~ ${ps[j].id} (${c.toFixed(2)})`);
    }
  if (!similar.length)
    line(true, `no two pairings present an UNDECLARED near-identical reference screen (threshold ${SIMILAR_SCREEN}${declaredSimilar.length ? `; declared: ${declaredSimilar.join(", ")}` : ""})`);

  /* Raster frames carry no DOM logo slot: their identity slots must be declared (D3). */
  const undeclared = undeclaredIdentitySlots(frames, TARGETS);
  line(undeclared.length === 0, `every frame without measured identity marks declares its identity slots${undeclared.length ? ` — undeclared: ${undeclared.join(", ")}` : ""}`);
  const stale = staleIdentitySlots(frames, TARGETS);
  line(stale.length === 0, `every declared identity slot was measured on the frame on disk${stale.length ? ` — stale: ${stale.join("; ")}` : ` (${frames.filter((f) => !Array.isArray(f.census?.identityRects)).length} frame(s))`}`);
  return failed;
}

/* ── CLI ─────────────────────────────────────────────────────────────────────────────────── */
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const args = process.argv.slice(2);
  if (args.includes("--fetch")) {
    const oi = args.indexOf("--only");
    const failures = await fetchAll(oi >= 0 ? args[oi + 1] : null);
    if (failures.length) console.log(`fetch: ${failures.length} target(s) failed — the set is incomplete`);
  }
  const failed = await selfCheck();
  console.log(failed ? `SELF-CHECK FAILED: ${failed} problem(s)` : "SELF-CHECK PASSED: every reference frame is clean, distinct and shows its working surface");
  process.exit(failed ? 1 : 0);
}
