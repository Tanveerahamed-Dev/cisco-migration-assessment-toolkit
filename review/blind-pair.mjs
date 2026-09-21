/**
 * blind-pair.mjs — build genuinely blind side-by-side comparison sheets.
 *
 * The user's bar is: a harsh critic, shown our interface and a reference interface WITHOUT knowing
 * which is which, says which is the better professional tool. For that verdict to mean anything the
 * blinding has to be real:
 *
 *   - No filenames, product names, logos or captions reach the critic; only "A" and "B".
 *   - Side assignment is derived from a hash of the pair id, so it is reproducible for us but not
 *     guessable from a pattern by the critic (it is not "ours is always left").
 *   - The key mapping A/B back to source lives in a SEPARATE file the critic is never given.
 *   - Both panels are scaled to the same height on the same neutral ground, so neither wins on
 *     size or on a background that flatters it.
 *
 * Composition is done by rendering an HTML sheet in Playwright — no image library needed, and it
 * gives exact control over the neutral framing.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { basename, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "blind");

/** Deterministic but non-obvious: the low bit of a sha256 over the pair id decides the side. */
const oursOnLeft = (pairId) => (createHash("sha256").update(pairId).digest()[0] & 1) === 0;

const dataUri = (file) => `data:image/png;base64,${readFileSync(file).toString("base64")}`;

/**
 * `maskTopPct` crops the same proportion off the top of BOTH panels.
 *
 * Why it exists: a reference product carries its own logo in its header, so a critic can recognise
 * the brand and then reason from reputation instead of from what is on screen — which is exactly
 * the bias blinding is supposed to remove. Cropping the branding band off both panels equally
 * restores a genuine craft comparison of the WORKING surface, which is the part being judged.
 * It is applied symmetrically so neither panel gains or loses area.
 */
const SHEET = (leftUri, rightUri, maskTopPct = 0) => `<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;background:#16181c;font:400 13px/1.4 -apple-system,Segoe UI,system-ui,sans-serif;color:#c8ccd4}
  .sheet{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:18px}
  .cell{display:flex;flex-direction:column;gap:8px;min-width:0}
  .tag{font:600 15px/1 ui-monospace,Consolas,monospace;letter-spacing:.08em;color:#e8ecf2;
       background:#23262c;border:1px solid #30343c;border-radius:4px;padding:7px 12px;width:max-content}
  .frame{background:#0e1013;border:1px solid #30343c;border-radius:6px;overflow:hidden;
         display:flex;align-items:flex-start;justify-content:center}
  .clip{overflow:hidden;width:100%}
  .clip img{margin-top:-${maskTopPct}%}
  img{display:block;width:100%;height:auto}
</style></head><body>
<div class="sheet">
  <div class="cell"><div class="tag">A</div><div class="frame"><div class="clip"><img src="${leftUri}"></div></div></div>
  <div class="cell"><div class="tag">B</div><div class="frame"><div class="clip"><img src="${rightUri}"></div></div></div>
</div>
</body></html>`;

/**
 * pairs: [{ id, ours, reference, question }]
 *   ours / reference are absolute PNG paths.
 */
export async function buildSheets(pairs, outDir = OUT) {
  mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 2400, height: 1000 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const key = [];
  const sheets = [];

  for (const p of pairs) {
    if (!existsSync(p.ours) || !existsSync(p.reference)) {
      key.push({ id: p.id, skipped: true, reason: `missing: ${!existsSync(p.ours) ? p.ours : p.reference}` });
      continue;
    }
    const left = oursOnLeft(p.id);
    const html = SHEET(
      dataUri(left ? p.ours : p.reference),
      dataUri(left ? p.reference : p.ours),
      p.maskTopPct ?? 0,
    );
    await page.setContent(html, { waitUntil: "load" });
    await page.waitForTimeout(300);
    /* The filename must not leak which product is in the sheet. A critic handed
       "p1-topology-vs-forward.png" is not blind — it can infer that one panel is Forward and
       reason from brand rather than from what it sees. So the sheet is named by an opaque digest
       and the human-readable id lives only in the key, which critics never receive. */
    const opaque = createHash("sha256").update(`sheet:${p.id}`).digest("hex").slice(0, 12);
    const file = resolve(outDir, `sheet-${opaque}.png`);
    await page.screenshot({ path: file, fullPage: true });
    key.push({
      id: p.id,
      sheetName: `sheet-${opaque}.png`,
      A: left ? "ours" : "reference",
      B: left ? "reference" : "ours",
      ours: basename(p.ours),
      reference: basename(p.reference),
      question: p.question ?? null,
      sheet: file,
    });
    sheets.push({ sheet: file, question: p.question ?? null });
    console.log(`  sheet ${p.id} -> sheet-${opaque}.png  (A=${left ? "ours" : "ref"})`);
  }

  await browser.close();
  // The KEY is written separately and must never be handed to a critic.
  writeFileSync(resolve(outDir, "KEY.json"), JSON.stringify(key, null, 1));
  // The MANIFEST is what a critic may see: sheet paths and questions, no identities.
  writeFileSync(resolve(outDir, "sheets.json"), JSON.stringify(sheets, null, 1));
  console.log(`built ${sheets.length}/${pairs.length} blind sheets in ${outDir}`);
  return { key, sheets };
}

/* ── CLI: build the standard pairing set ───────────────────────────────────── */

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const APP = (name) => resolve(HERE, "shots/app/dark/1920", `${name}.png`);
  const REF = (name) => resolve(HERE, "shots/refs", `${name}.png`);
  const DEEP = (name) => resolve(HERE, "shots/refs-deep", `${name}.png`);

  /* Each pairing asks one focused question. A critic asked "which is better" in the abstract gives
     a useless answer; asked "which reads faster as a working instrument" it gives an actionable one.

     Reference selection is deliberate and was checked by eye. Only FULL-PRODUCT captures are used:
     the Forward demos and Grafana Explore/dashboard are real applications filling a 1920 viewport.
     The IP Fabric docs figures were tried and rejected — they are annotated instructional crops
     with callout boxes drawn on them, so a critic would be comparing our application against a
     tutorial diagram and would reasonably prefer whichever image was less cluttered. That measures
     nothing. Linear's marketing page was rejected for the same reason: it is mostly headline copy,
     not a working list. Where a comparison is unfair, the verdict is worthless even when it is
     favourable to us. */
  const pairs = [
    {
      id: "p1-fabric-vs-forward-map",
      ours: APP("01-fabric-overview"),
      reference: DEEP("forward-demo-b-step6"),
      question:
        "Both are network-investigation interfaces at rest, showing a topology with investigation controls around it. Which one would a senior network engineer rather work in for an hour, and which reads faster as a professional instrument rather than a demo? Judge composition, information density, typographic craft, colour discipline, and the quality of the network visualisation itself.",
    },
    {
      id: "p2-path-vs-forward-path",
      ours: APP("06-path-blocked"),
      reference: DEEP("forward-demo-b-step6"),
      question:
        "Both show a network path-investigation surface. Which one better answers 'can this traffic get through, and what stopped it?' — judged on how quickly the answer and its supporting evidence are locatable, and on visual craft.",
    },
    {
      id: "p3-dense-list-vs-grafana",
      ours: APP("03-finding-drill"),
      reference: DEEP("grafana-dashboard-dense"),
      question:
        "Both are dense working views packed with real operational data. Which has better typographic craft, spacing rhythm, information density without clutter, and colour discipline (colour used only as signal, never as decoration)?",
    },
    {
      id: "p4-inspector-vs-grafana-explore",
      ours: APP("07-evidence-raw"),
      reference: DEEP("grafana-explore"),
      question:
        "Both let an investigator inspect the raw underlying data alongside a result. Which makes the data more auditable and the tool more trustworthy? Judge layout, hierarchy, density and craft.",
    },
    {
      id: "p5-device-vs-forward-inventory",
      ours: APP("02-device-selected"),
      reference: DEEP("forward-demo-a-step6"),
      question:
        "Both present network context with a specific element selected. Which keeps the investigator better oriented — able to see both the whole and the detail without losing their place — and which looks like the more mature product?",
    },
    {
      id: "p6-indeterminate-vs-forward",
      ours: APP("08-path-indeterminate"),
      reference: DEEP("forward-demo-a-step3"),
      question:
        "Both are analysis surfaces reporting a result. Which communicates the LIMITS of what it knows more clearly and more credibly, and which would you trust more to tell you when it cannot answer your question? Judge how a partial or uncertain result is presented, not just how a confident one looks.",
    },
  ];

  /* A second set with the branding band cropped off both panels. These are the sheets that carry
     the genuinely blind craft verdict; the uncropped set above still shows the full composition. */
  const cropped = pairs.map((p) => ({
    ...p,
    id: `${p.id}-craft`,
    maskTopPct: 4,
    question: `${p.question}\n\nNote: the top band of both interfaces has been cropped so neither can be identified by branding. Judge only the working surface you can see.`,
  }));

  await buildSheets([...pairs, ...cropped]);
}
