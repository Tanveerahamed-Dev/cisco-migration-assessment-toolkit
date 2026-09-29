/**
 * blind-pair.mjs — build the C1 blind comparison sheets, and validate the verdicts recorded
 * against them under a rule written down BEFORE any critic runs.
 *
 *   node review/blind-pair.mjs                      self-tests, build the sheets, validate verdicts
 *   node review/blind-pair.mjs --selftest           the pure self-tests only
 *   node review/blind-pair.mjs --validate           validate blind/verdicts.jsonl against blind/KEY.json
 *   node review/blind-pair.mjs --validate --verdicts <file.jsonl>
 *
 * WHAT CHANGED AND WHY (discovery c1-references, 2026-09-26). The previous sheets were not blind
 * enough to mean anything, and the file claimed more than it did:
 *   - the A/B side was one bit of a hash of the pair id, so every "-craft" sheet put the reference
 *     on the left — a pattern, not blinding;
 *   - the header said both panels were scaled "to the same height"; the CSS scaled them to equal
 *     WIDTH, so the panels had different heights (measured 659 vs 534 px for 16:9 vs 2560x1168);
 *   - the "craft" crop was 4 % of the panel WIDTH, which left "Forward AI" and our own wordmark in;
 *   - one question asked which read as "a professional instrument rather than a demo", priming
 *     the critic to look for the demo;
 *   - the KEY had no verdict, critic, recognition or reason fields, and six pairings used three
 *     distinct reference images (two pairs of byte-identical references).
 *
 * WHAT A SHEET IS NOW:
 *   - ONE pairing per C1 dimension (composition, information density, typographic craft, colour
 *     discipline, network visualisation), each matched BY TASK to a clean reference frame owned by
 *     capture-refs-clean.mjs, and each asking ONE neutral question about ONE dimension.
 *   - SYMMETRIC: both panels are the same CSS-pixel rectangle of their frame, rendered at the SAME
 *     device pixel ratio (the lower of the two captures'), so they are identical in pixel size and
 *     in text scale. Our theme is chosen to match the reference's MEASURED theme.
 *   - MASKED ON BOTH PANELS: every wordmark / product / vendor / user / workspace string found in
 *     either panel's PIXELS (OCR, read at the higher of the two capture DPRs), plus the reference's
 *     logo slots (DOM-measured, or declared on its TARGET for a raster frame), becomes a neutral grey rectangle,
 *     and the UNION of those rectangles is painted at the same place on both panels. The masked
 *     panels are then OCR'd again: a sheet on which any identity string is still legible is NOT
 *     emitted (it is reported as blocked, which leaves its pairing UNPROVEN).
 *   - SIDE DRAWN FRESH PER CRITIC: each pairing gets both side variants, and every critic slot in
 *     the KEY draws its side from crypto.randomInt at build time (drawSlots). A sheet's file name is
 *     derived from its bytes, so neither the name nor the order reveals the side, and a rebuild with
 *     byte-identical sheets keeps the same files and the same KEY.
 *
 * VERIFIER ROUND 1 (2026-09-28) closed: our side is task-matched too (`oursRequires`, D1); one verdict
 * per critic per pairing, and an invalid loss still blocks (RULE v2, D2); raster references mask
 * their declared logo slots, chips mask whole, our dataset row is masked, and identity is read at the
 * higher capture DPR (D3); the slot draw is testable (D4); the crop is written into the rule and the
 * critic's instructions, and each pairing records what the crop cut (D5); near-identical reference
 * SCREENS must be declared (capture-refs-clean.mjs, D6); content-named sheets, an append-only receipt
 * and unparseable lines reported as invalid (D8).
 *   - RECOGNITION IS MEASURED, NOT ASSUMED: blinding cannot be perfect (a 3-D render, a familiar
 *     layout, a logo glyph the OCR cannot read). Each critic answers a recognition question first;
 *     a verdict from a critic who recognised either product is excluded and reported separately.
 *
 * The KEY (blind/KEY.json) maps sheets back to sources and is NEVER given to a critic; the critic
 * manifest (blind/sheets.json) carries only slot, sheet file, and the neutral questions. Verdicts
 * are appended, one JSON object per line, to blind/verdicts.jsonl by the critic-panel step (this
 * script never runs critics). Outputs live under review/blind/, which .gitignore excludes: they
 * contain third-party imagery and are never tracked or published.
 */
import { execFileSync } from "node:child_process";
import { createHash, randomInt } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from "node:fs";
import { basename, dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
export const OUT = resolve(HERE, "blind");
const WORK = resolve(OUT, "_work");
/* capture-refs-clean.mjs imports PAIRINGS from this file for its self-check, so this file must not
   import it statically: a static cycle deadlocks that script's top-level await. It is loaded lazily. */
let REFS_LIB = null;
const refsLib = async () => (PHRASE_LIB = REFS_LIB ??= await import("./capture-refs-clean.mjs"));
const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");
const rel = (p) => relative(ROOT, p).split("\\").join("/");
const fromRel = (p) => resolve(ROOT, p);
const OURS_SHOTS = process.env.ATLAS_SHOTS ? resolve(process.env.ATLAS_SHOTS) : resolve(HERE, "shots");

/* ── The C1 dimensions and the pairings ───────────────────────────────────────────────────── */
export const C1_DIMENSIONS = ["composition", "information-density", "typographic-craft", "colour-discipline", "network-visualisation"];

const ASK = (what) =>
  `Both images, A and B, show a network tool with work on screen. Judge ${what} Say which is better, A or B, or that it is a genuine tie, and give specific, visible reasons.`;
export const QUESTIONS = {
  composition: ASK("OVERALL COMPOSITION only: how the screen is divided, what draws the eye first, and how quickly the main result and its supporting detail can be located."),
  "information-density": ASK("INFORMATION DENSITY only: how much useful information is visible per unit of screen, and whether it stays readable and uncluttered."),
  "typographic-craft": ASK("TYPOGRAPHIC CRAFT only: type sizes and weights, hierarchy, alignment, spacing rhythm and legibility."),
  "colour-discipline": ASK("COLOUR DISCIPLINE only: whether colour carries meaning (state, severity, selection) rather than decoration, and whether contrast is sufficient."),
  "network-visualisation": ASK(
    "the NETWORK VISUALISATION only: how legibly the drawing shows the devices, the links between them and their state. The two drawings may use different techniques; judge how well each one shows the network, not the technique.",
  ),
};
export const RECOGNITION_QUESTION =
  "Before judging: do you recognise the product, vendor or brand of either A or B? Answer yes or no. If yes, name what you recognise and which panel it is in.";

/** One pairing per dimension, each matched by TASK — on BOTH sides. The reference side's match is
    proved by capture-refs-clean.mjs (each TARGET's `expect` must be in its pixels); OUR side's match is
    proved here by `oursRequires`, checked against our capture record and the OCR of our frame before
    a sheet is built, so a state that does not show the task (e.g. the path surface before any flow is
    traced, paired with a reference that shows a traced path — verifier round 1, D1) is BLOCKED, not
    judged. `oursRequires`:
      query   — regular expressions the captured URL must match (the investigation state);
      expect  — phrases that must be legible in our frame's pixels (as a TARGET's `expect`);
      minHops — the least hop count the header's Path badge must show (a drawn multi-hop trace; the
                badge is `Header.tsx :: hdr-surface__count`, the current trace's `hops.length`).
    Our theme follows the reference's measured theme. The network-visualisation pairing compares our
    3-D render with a 2-D topology because no reference product has a 3-D render — stated as such,
    pending the owner's decision to keep it in C1 or move it to C5.
    `similarScreenWith` declares — with the reason — that this pairing's reference is the same KIND of
    screen as another pairing's (capture-refs-clean.mjs measures that and refuses it undeclared). */
export const PAIRINGS = [
  {
    id: "c1-composition",
    dimension: "composition",
    ours: "06-path-blocked",
    ref: "forward-path-dropped",
    task: "path question answered: the traffic is blocked, with the hop that blocks it",
    oursRequires: { query: ["[?&]flow="], expect: ["denies this flow"] },
    similarScreenWith: {
      "c1-network-visualisation":
        "Both references are Forward's path-search result screen (different recorded paths), because both of our states are our path surface too: composition is judged on the whole screen, network visualisation on the drawing.",
    },
  },
  {
    id: "c1-information-density",
    dimension: "information-density",
    ours: "03-finding-drill",
    ref: "forward-vulnerability-table",
    task: "a dense working list of findings / vulnerable devices",
    oursRequires: { query: ["[?&]s=findings", "[?&]sev="], expect: ["severity critical"] },
  },
  {
    id: "c1-typographic-craft",
    dimension: "typographic-craft",
    ours: "07-evidence-raw",
    ref: "ipfabric-path-detail",
    task: "the evidence behind a result: per-hop decision, raw data",
    oursRequires: { query: ["[?&]tab=raw", "[?&]d="], expect: ["routing"] },
  },
  {
    id: "c1-colour-discipline",
    dimension: "colour-discipline",
    ours: "04-finding-evidence",
    ref: "grafana-explore",
    task: "inspecting the data behind a result",
    oursRequires: { query: ["[?&]f=", "[?&]tab=raw"], expect: ["finding"] },
  },
  {
    id: "c1-network-visualisation",
    dimension: "network-visualisation",
    /* 08, not 05 (the path surface before any flow is run) and not 06 (a single-hop trace: its own
       capture note says no path geometry between devices is drawn). 08's trace is multi-hop and drawn. */
    ours: "08-path-indeterminate",
    ref: "forward-topology-path",
    task: "the network drawn with a traced path highlighted on it",
    oursRequires: { query: ["[?&]flow="], expect: ["blocked"], minHops: 2 },
    similarScreenWith: { "c1-composition": "See c1-composition." },
    note: "3-D render judged against a 2-D topology as 'network visualisation' (no reference has a 3-D render); owner decision pending: keep in C1 or move to C5.",
  },
];

/** The hop count the header's Path badge shows, read from our frame's OCR words: a number word just
    right of a "Path" word in the header row. null when it is not legible (never read as zero hops). */
export function hopBadge(ocr, dpr) {
  if (!ocr?.ok) return null;
  const words = (ocr.lines ?? []).flatMap((l) => l.words ?? []).map((w) => ({ ...w, x: w.x / dpr, y: w.y / dpr, w: w.w / dpr, h: w.h / dpr }));
  for (const p of words.filter((w) => /^path$/i.test(w.text) && w.y < 60)) {
    const n = words.find((w) => /^\d{1,3}$/.test(w.text) && Math.abs(w.y - p.y) < 8 && w.x > p.x + p.w - 2 && w.x < p.x + p.w + 40);
    if (n) return Number(n.text);
  }
  return null;
}

/** What is missing for OUR frame to show the pairing's task. Empty = it shows it. */
export function oursRequirementProblems(p, ours, ocr) {
  const req = p.oursRequires ?? {};
  const out = [];
  if (!(req.expect ?? []).length) out.push("the pairing does not declare what our state must show");
  const url = ours?.capture?.url ?? "";
  for (const q of req.query ?? []) if (!new RegExp(q).test(url)) out.push(`our captured state ${JSON.stringify(url.replace(/^https?:\/\/[^/]+/, ""))} does not match ${q}`);
  if (!ocr?.ok) {
    out.push(`our frame's pixels could not be read (${ocr?.error ?? "no OCR"})`);
    return out;
  }
  for (const e of req.expect ?? []) if (!findPhraseIn(ocr.text, e)) out.push(`"${e}" is not legible in our frame`);
  if (req.minHops) {
    const hops = hopBadge(ocr, ours.dpr ?? 1);
    if (hops === null || hops < req.minHops) out.push(`the trace shown has ${hops === null ? "no legible" : hops} hop(s); the task needs a drawn trace of at least ${req.minHops}`);
  }
  return out;
}
/* Phrase matching without importing capture-refs-clean.mjs at load (see refsLib): the same rule — a
   run of whole words within floor(len/7) edits — is used via the lazily loaded library when present. */
let PHRASE_LIB = null;
const findPhraseIn = (text, phrase) => {
  if (PHRASE_LIB) return PHRASE_LIB.phrasesIn(text, [phrase]).length > 0;
  const n = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  return ` ${n(text)} `.includes(` ${n(phrase)} `);
};

/* ── The pre-registered rule ─────────────────────────────────────────────────────────────── */
export const RULE = `C1 blind-verdict rule v2 (pre-registered; changing it changes ruleSha, recorded in every KEY).
A verdict line BELONGS to pairing P when its sheetSha is one of P's CURRENT sheets (a line on any other sheet is STALE: an earlier build's pixels; it never counts).
ONE VERDICT PER CRITIC PER PAIRING: the FIRST line that belongs to P and carries a criticId is that critic's verdict for P, whatever its outcome (counted, recognised or invalid). Every later line from that criticId for P is a DUPLICATE and never counts, so neither a recognition nor an invalid loss can be re-asked away.
A critic's verdict for P COUNTS only if ALL hold:
  1. it has every field {sheetSha, oursSha, refSha, commit, criticId, criticModel, recognized, recognizedAs, perDimension, reasons, faults} with the right type;
  2. oursSha, refSha and commit equal P's KEY values;
  3. recognized === false (a critic who recognised either product is EXCLUDED and reported separately with recognizedAs);
  4. perDimension[P.dimension] is "A", "B" or "tie" (mapped to ours/reference through the sheet's recorded side);
  5. reasons holds at least one non-empty string, and faults is an array.
P is PASS iff at least 2 counted verdicts from distinct critics exist AND no unrecognising verdict of P picks the reference — counted or not: an invalid verdict that picks the reference is an UNCOUNTED LOSS and keeps P UNPROVEN just as a counted loss does (absence of reasons is not a win).
Otherwise P is UNPROVEN. A loss keeps P UNPROVEN for that build: verdicts are append-only (a receipt of the validated prefix refuses an edited or truncated file), so a loss cannot be re-run away; its reasons become work items, and only a new build (new sheets) starts a new count.
Both panels of a sheet are same-size CROPS of larger screens, cut at the same place: content cut by a panel edge is an artefact of the crop, not a fault of the design, and such faults are not work items.
An unparseable verdict line cannot be attributed and keeps C1 UNPROVEN until it is resolved by appending, never by editing.
C1 is PASS iff every pairing is PASS; otherwise UNPROVEN. Linear is out of scope (not obtainable without an account).`;
export const CRITIC_INSTRUCTIONS =
  "You are shown sheets of two interface screenshots, A and B. Answer the recognition question FIRST, then the question for the sheet. " +
  "Both panels are same-size crops of larger screens, cut at the same place: text or controls cut off at a panel edge are an artefact of the crop, so do not count them as faults. " +
  "Grey rectangles are neutral masks, placed identically on both panels; ignore them. List every specific, actionable fault you see in EITHER panel.";
export const RULE_SHA = sha256(Buffer.from(RULE));
export const VERDICT_FIELDS = ["sheetSha", "oursSha", "refSha", "commit", "criticId", "criticModel", "recognized", "recognizedAs", "perDimension", "reasons", "faults"];

export function verdictShapeProblems(v) {
  const p = [];
  if (!v || typeof v !== "object") return ["not an object"];
  for (const f of VERDICT_FIELDS) if (!(f in v)) p.push(`missing ${f}`);
  for (const f of ["sheetSha", "oursSha", "refSha", "commit", "criticId", "criticModel"]) if (f in v && (typeof v[f] !== "string" || !v[f])) p.push(`${f} must be a non-empty string`);
  if ("recognized" in v && typeof v.recognized !== "boolean") p.push("recognized must be a boolean");
  if ("recognizedAs" in v && v.recognizedAs !== null && typeof v.recognizedAs !== "string") p.push("recognizedAs must be a string or null");
  if (v.recognized === true && !v.recognizedAs) p.push("recognized without recognizedAs");
  if ("perDimension" in v && (typeof v.perDimension !== "object" || v.perDimension === null)) p.push("perDimension must be an object");
  if ("reasons" in v && (!Array.isArray(v.reasons) || !v.reasons.some((r) => typeof r === "string" && r.trim()))) p.push("reasons must hold at least one non-empty string");
  if ("faults" in v && !Array.isArray(v.faults)) p.push("faults must be an array");
  return p;
}

/** Evaluate verdicts against a KEY under RULE. Pure: no I/O. */
export function evaluate(key, verdicts) {
  const out = [];
  const bySheet = new Map();
  for (const p of key.pairings) for (const s of p.sheets ?? []) bySheet.set(s.sheetSha, { pairing: p, sheet: s });
  const allCurrent = new Set(bySheet.keys());
  const unparseable = verdicts.filter((v) => !v || typeof v !== "object" || "unparseable" in v).length;
  const stale = verdicts.filter((v) => v && typeof v === "object" && !("unparseable" in v) && !allCurrent.has(v.sheetSha)).length;
  for (const p of key.pairings) {
    const res = { id: p.id, dimension: p.dimension, status: "UNPROVEN", counted: [], recognized: [], invalid: [], duplicates: [], uncountedLosses: [], why: "" };
    if (p.blocked) {
      res.why = `no sheet was emitted: ${p.blocked}`;
      out.push(res);
      continue;
    }
    /* RULE v2: the first line per criticId that belongs to P is that critic's ONLY verdict for P. */
    const seen = new Set();
    for (const v of verdicts) {
      const hit = v && typeof v === "object" && bySheet.get(v.sheetSha);
      if (!hit || hit.pairing !== p) continue;
      const cid = typeof v.criticId === "string" && v.criticId ? v.criticId : null;
      if (cid !== null) {
        if (seen.has(cid)) {
          res.duplicates.push(cid);
          continue;
        }
        seen.add(cid);
      }
      if (v.recognized === true) {
        res.recognized.push({ criticId: cid, criticModel: v.criticModel ?? null, recognizedAs: v.recognizedAs ?? null });
        continue;
      }
      const side = hit.sheet.A === "ours" ? { A: "ours", B: "reference" } : { A: "reference", B: "ours" };
      const raw = v.perDimension && typeof v.perDimension === "object" ? v.perDimension[p.dimension] : undefined;
      const pick = raw === "tie" ? "tie" : side[raw] ?? null;
      const problems = [...verdictShapeProblems(v)];
      if (v.oursSha !== p.ours?.sha256) problems.push("oursSha differs from the KEY");
      if (v.refSha !== p.ref?.sha256) problems.push("refSha differs from the KEY");
      if (v.commit !== key.commit) problems.push("commit differs from the KEY");
      if (pick === null) problems.push(`perDimension["${p.dimension}"] must be A, B or tie`);
      if (problems.length) {
        res.invalid.push({ criticId: cid, problems: [...new Set(problems)] });
        if (pick === "reference") res.uncountedLosses.push({ criticId: cid, problems: [...new Set(problems)] });
        continue;
      }
      res.counted.push({ criticId: cid, criticModel: v.criticModel, pick, reasons: v.reasons, faults: v.faults });
    }
    const losses = res.counted.filter((c) => c.pick === "reference");
    if (losses.length) res.why = `${losses.length} counted verdict(s) pick the reference — work items: ${losses.flatMap((l) => l.reasons).slice(0, 3).join(" | ")}`;
    else if (res.uncountedLosses.length) res.why = `${res.uncountedLosses.length} invalid verdict(s) pick the reference (uncounted losses keep the pairing UNPROVEN)`;
    else if (res.counted.length >= 2) {
      res.status = "PASS";
      res.why = `${res.counted.length} counted verdicts, none picks the reference`;
    } else res.why = `${res.counted.length} counted verdict(s); the rule needs 2 unrecognising critics`;
    out.push(res);
  }
  const overall = !unparseable && out.length === key.pairings.length && out.every((r) => r.status === "PASS") ? "PASS" : "UNPROVEN";
  return { overall, pairings: out, stale, unparseable };
}

export function printEvaluation(ev) {
  console.log(`C1 verdicts under the pre-registered rule (ruleSha ${RULE_SHA.slice(0, 12)}):`);
  for (const r of ev.pairings) {
    console.log(`  ${r.status.padEnd(8)} ${r.id} [${r.dimension}] — ${r.why}`);
    if (r.recognized.length) console.log(`           excluded (recognised): ${r.recognized.map((x) => `${x.criticId} saw "${x.recognizedAs}"`).join("; ")}`);
    if (r.invalid.length) console.log(`           invalid: ${r.invalid.map((x) => `${x.criticId ?? "?"}: ${x.problems.join(", ")}`).join("; ")}`);
    if (r.uncountedLosses?.length) console.log(`           uncounted losses (invalid, but pick the reference): ${r.uncountedLosses.map((x) => x.criticId ?? "?").join(", ")}`);
    if (r.duplicates.length) console.log(`           later lines from a critic already heard for this pairing (never count): ${r.duplicates.join(", ")}`);
  }
  if (ev.stale) console.log(`  (${ev.stale} verdict(s) are against sheets of an earlier build: stale, not counted)`);
  if (ev.unparseable) console.log(`  INVALID: ${ev.unparseable} verdict line(s) are unparseable and cannot be attributed — C1 cannot be PASS while they stand`);
  console.log(`C1 overall: ${ev.overall}`);
}

/* ── Geometry ───────────────────────────────────────────────────────────────────────────── */
/** The common CSS rectangle and the sheet DPR for a pairing. */
export function cropFor(p, oursFrame, refFrame) {
  const oo = p.oursOrigin ?? { x: 0, y: 0 };
  const ro = p.refOrigin ?? { x: 0, y: 0 };
  const w = Math.floor(Math.min(oursFrame.css.w - oo.x, refFrame.css.w - ro.x, p.size?.w ?? Infinity));
  const h = Math.floor(Math.min(oursFrame.css.h - oo.y, refFrame.css.h - ro.y, p.size?.h ?? Infinity));
  return { w, h, oursOrigin: oo, refOrigin: ro, dpr: Math.min(oursFrame.dpr, refFrame.dpr) };
}

const MASK_FILL = "#808080";
const PAD = 4;
/** Word boxes (device px of a panel screenshot) of every identity phrase, as CSS-px rectangles. */
export function identityBoxes(ocr, phrases, dpr, { tokens, findPhrase }) {
  const boxes = [];
  if (!ocr?.ok) return boxes;
  for (const line of ocr.lines ?? []) {
    const words = line.words ?? [];
    const toks = [];
    const owner = [];
    words.forEach((w, i) => {
      for (const t of tokens(w.text)) {
        toks.push(t);
        owner.push(i);
      }
    });
    for (const ph of phrases) {
      for (const [a, b] of findPhrase(toks, ph)) {
        /* A short line holding an identity string is a name chip (workspace, user, file): mask the
           whole line, so "Demo Network (default)" does not leave "(default)" behind. */
        /* On a longer line, the mask still covers the whole CHIP when the match sits in one: the
           maximal run of words around the match separated by no more than an inter-word space (0.6
           of the text height). A run of at most 4 words is a chip ("Demo Network (default)", so
           "(default)" goes too); a longer run is prose, and only the matched words are masked
           (verifier round 1, D3). */
        let ws;
        if (words.length <= 4) ws = words;
        else {
          const idx = [...new Set(owner.slice(a, b))].sort((x, y) => x - y);
          let lo = idx[0];
          let hi = idx[idx.length - 1];
          const th = 0.6 * Math.max(...idx.map((i) => words[i].h));
          while (hi + 1 < words.length && words[hi + 1].x - (words[hi].x + words[hi].w) <= th) hi++;
          while (lo - 1 >= 0 && words[lo].x - (words[lo - 1].x + words[lo - 1].w) <= th) lo--;
          ws = hi - lo + 1 <= 4 ? words.slice(lo, hi + 1) : idx.map((i) => words[i]);
        }
        const x0 = Math.min(...ws.map((w) => w.x));
        const y0 = Math.min(...ws.map((w) => w.y));
        const x1 = Math.max(...ws.map((w) => w.x + w.w));
        const y1 = Math.max(...ws.map((w) => w.y + w.h));
        const h = (y1 - y0) / dpr;
        /* A wordmark sits beside its glyph: widen leftwards by 2.5 line heights. */
        boxes.push({ x: x0 / dpr - PAD - 2.5 * h, y: y0 / dpr - PAD, w: (x1 - x0) / dpr + 2 * PAD + 2.5 * h, h: h + 2 * PAD, why: ph });
      }
    }
  }
  return boxes;
}

const panelHtml = (frame, origin, crop, masks) => {
  const src = `data:image/png;base64,${readFileSync(fromRel(frame.file)).toString("base64")}`;
  const m = masks.map((r) => `<div style="position:absolute;left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;background:${MASK_FILL}"></div>`).join("");
  return `<div class="panel" style="position:relative;overflow:hidden;width:${crop.w}px;height:${crop.h}px;background:#000"><img src="${src}" style="position:absolute;left:${-origin.x}px;top:${-origin.y}px;width:${frame.css.w}px;height:${frame.css.h}px;max-width:none">${m}</div>`;
};
const PANEL_PAGE = (inner) => `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#16181c}</style></head><body>${inner}</body></html>`;
const SHEET_PAGE = (left, right) => `<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;background:#16181c;font:600 15px/1 ui-monospace,Consolas,monospace;color:#e8ecf2}
  .sheet{display:flex;gap:18px;padding:18px;width:max-content}
  .cell{display:flex;flex-direction:column;gap:8px}
  .tag{background:#23262c;border:1px solid #30343c;border-radius:4px;padding:7px 12px;width:max-content;letter-spacing:.08em}
  .frame{border:1px solid #30343c}
</style></head><body><div class="sheet">
<div class="cell"><div class="tag">A</div><div class="frame">${left}</div></div>
<div class="cell"><div class="tag">B</div><div class="frame">${right}</div></div>
</div></body></html>`;

/* ── Inputs ──────────────────────────────────────────────────────────────────────────────── */
/** Our identity strings: the product name (index.html <title>) and every field the header's snapshot
    identity renders (src/app/Header.tsx :: SnapshotIdentity — file name, schema, sha8), read from the
    same compiled data the header reads (src/data/fabric.json meta), so the dataset row is masked as
    Forward's workspace chip is (verifier round 1, D3). The collection date is not identity (Forward's
    snapshot time is not masked either). */
function oursIdentity() {
  const title = /<title>([^<]+)<\/title>/.exec(readFileSync(resolve(ROOT, "index.html"), "utf8"))?.[1];
  const src = /SOURCE_REL\s*=\s*"([^"]+)"/.exec(readFileSync(resolve(ROOT, "tools", "source-binding.mjs"), "utf8"))?.[1];
  let meta = null;
  try {
    meta = JSON.parse(readFileSync(resolve(ROOT, "src", "data", "fabric.json"), "utf8")).meta ?? null;
  } catch {
    meta = null;
  }
  if (!title || !src || !meta?.source || !meta?.schema || !meta?.sourceSha256)
    throw new Error("cannot read our own identity (index.html <title>, tools/source-binding.mjs SOURCE_REL, src/data/fabric.json meta source/schema/sourceSha256)");
  return [...new Set([title, basename(src), basename(meta.source), meta.schema, meta.sourceSha256.slice(0, 8)])];
}
function oursFrame(state, theme) {
  const file = resolve(OURS_SHOTS, "app", theme, "1920", `${state}.png`);
  if (!existsSync(file)) return null;
  const buf = readFileSync(file);
  const w = buf.readUInt32BE(16);
  const h = buf.readUInt32BE(20);
  const dpr = w / 1920;
  let capture = null;
  try {
    const idx = JSON.parse(readFileSync(resolve(OURS_SHOTS, "app", "index.json"), "utf8"));
    const e = idx.find((x) => x.id === state && x.theme === theme && String(x.viewport) === "1920");
    if (e) capture = { url: e.url, server: e.server, problems: e.problems ?? [], render: e.render ? { quality: e.render.quality, converged: e.render.converged } : null };
  } catch {
    capture = null;
  }
  return { id: `${theme}/1920/${state}`, file: rel(file), sha256: sha256(buf), css: { w: 1920, h: Math.round(h / dpr) }, dpr, theme, capture };
}
function gitState() {
  const git = (...a) => execFileSync("git", ["-C", ROOT, ...a], { encoding: "utf8" }).trim();
  try {
    return { commit: git("rev-parse", "HEAD"), dirty: git("status", "--porcelain", "--", ".").length > 0 };
  } catch {
    return { commit: "unknown", dirty: true };
  }
}

/* ── Build ───────────────────────────────────────────────────────────────────────────────── */
export async function buildSheets({ slotsPerPairing = 4 } = {}) {
  const lib = await refsLib();
  const { MANIFEST, TOUR_BANNER_PHRASES, ocrImages } = lib;
  if (!existsSync(MANIFEST)) throw new Error(`no reference set (${rel(MANIFEST)}); run node review/capture-refs-clean.mjs --fetch`);
  const man = JSON.parse(readFileSync(MANIFEST, "utf8"));
  /* Identity strings come from the reference owner's CODE (TARGETS) as well as the captured manifest,
     so adding one there re-masks sheets without a re-fetch. */
  const refIdentity = [...new Set([...lib.TARGETS.flatMap((t) => t.identity ?? []), ...man.frames.flatMap((f) => f.identity ?? [])])];
  const identity = [...new Set([...refIdentity, ...oursIdentity()])];
  const leakPhrases = [...identity, ...TOUR_BANNER_PHRASES];
  mkdirSync(WORK, { recursive: true });
  const git = gitState();
  const browser = await chromium.launch();
  const pairings = [];
  const shoot = async (html, dpr, w, h, file) => {
    const ctx = await browser.newContext({ viewport: { width: Math.ceil(w), height: Math.ceil(h) }, deviceScaleFactor: dpr });
    const page = await ctx.newPage();
    await page.setContent(html, { waitUntil: "load" });
    await page.evaluate(() => Promise.all([...document.images].map((i) => i.decode())));
    const buf = await page.locator(".panel, .sheet").first().screenshot({ animations: "disabled", scale: "device" });
    await ctx.close();
    writeFileSync(file, buf);
    return buf;
  };
  try {
    for (const p of PAIRINGS) {
      const ref = man.frames.find((f) => f.id === p.ref);
      const entry = { id: p.id, dimension: p.dimension, task: p.task, question: QUESTIONS[p.dimension], note: p.note ?? null, sheets: [], slots: [] };
      pairings.push(entry);
      if (!ref || !existsSync(fromRel(ref.file))) {
        entry.blocked = `reference ${p.ref} is not in the set`;
        continue;
      }
      if (sha256(readFileSync(fromRel(ref.file))) !== ref.sha256) {
        entry.blocked = `reference ${p.ref} changed since capture`;
        continue;
      }
      const ours = oursFrame(p.ours, ref.theme);
      if (!ours) {
        entry.blocked = `our capture ${ref.theme}/1920/${p.ours} is missing`;
        continue;
      }
      const crop = cropFor(p, ours, ref);
      entry.ours = ours;
      /* Our frame is only comparable if its capture says it rendered properly. A missing capture
         record is not "rendered properly" — it is unknown — and a frame the capture harness flagged
         would have the critic judge the defect rather than the design. */
      if (!ours.capture) {
        entry.blocked = `our capture ${ours.id} has no record in the capture index, so whether it rendered properly is unknown`;
        continue;
      }
      if (ours.capture.problems.length) {
        entry.blocked = `our capture ${ours.id} did not render properly: ${ours.capture.problems.map((x) => String(x).slice(0, 140)).join("; ")}`;
        continue;
      }
      /* Our frame must show the pairing's TASK, as the reference's must (D1). */
      const oursOcr = ocrImages([fromRel(ours.file)]).get(resolve(fromRel(ours.file)));
      const unmet = oursRequirementProblems(p, ours, oursOcr);
      if (unmet.length) {
        entry.blocked = `our state ${ours.id} does not show the pairing's task (${p.task}): ${unmet.join("; ")}`;
        continue;
      }
      entry.ref = { id: ref.id, product: ref.product, file: ref.file, sha256: ref.sha256, css: ref.css, dpr: ref.dpr, theme: ref.theme, provenance: ref.provenance };
      entry.crop = crop;
      /* What each panel loses to the common crop, in CSS px: a fault the critic reports at a cut edge
         is a crop artefact (RULE v2), and this is where a reader of the faults can see which edges
         were cut (verifier round 1, D5). */
      entry.truncation = {
        ours: { right: ours.css.w - crop.oursOrigin.x - crop.w, bottom: ours.css.h - crop.oursOrigin.y - crop.h },
        reference: { right: ref.css.w - crop.refOrigin.x - crop.w, bottom: ref.css.h - crop.refOrigin.y - crop.h },
      };
      /* Masks: the reference's identity slots — DOM-measured where a DOM existed, otherwise the
         geometry its TARGET declares for a raster frame (capture-refs-clean.mjs requires every raster
         frame to declare it, empty or not) — then OCR identity boxes on both panels, unioned and
         painted on BOTH; iterate until the masked pixels read clean (max 3 passes). */
      const declared = lib.TARGETS.find((t) => t.id === ref.id)?.identitySlots ?? [];
      const slots = [...(ref.census?.logoRects ?? []).map((r) => ({ ...r, why: "DOM logo slot" })), ...declared.map((r) => ({ ...r, why: r.why ?? "declared identity slot" }))];
      let masks = slots.map((r) => ({ x: r.x - crop.refOrigin.x - PAD, y: r.y - crop.refOrigin.y - PAD, w: r.w + 2 * PAD, h: r.h + 2 * PAD, why: r.why }));
      let leaks = [];
      /* Identity is READ at the higher of the two capture DPRs, not the sheet's: text a critic can
         still read at a 1x sheet may be too small for OCR at 1x (our snapshot row on the IP Fabric
         sheet, verifier round 1, D3). Masks are CSS px, so the sheet at its own DPR gets the same masks. */
      const ocrDpr = Math.max(crop.dpr, ours.dpr, ref.dpr);
      entry.maskReadAtDpr = ocrDpr;
      for (let pass = 0; pass < 3; pass++) {
        const fo = resolve(WORK, `${p.id}.ours.p${pass}.png`);
        const fr = resolve(WORK, `${p.id}.ref.p${pass}.png`);
        await shoot(PANEL_PAGE(panelHtml(ours, crop.oursOrigin, crop, masks)), ocrDpr, crop.w, crop.h, fo);
        await shoot(PANEL_PAGE(panelHtml(ref, crop.refOrigin, crop, masks)), ocrDpr, crop.w, crop.h, fr);
        const ocr = ocrImages([fo, fr]);
        const oo = ocr.get(resolve(fo));
        const or = ocr.get(resolve(fr));
        if (!oo?.ok || !or?.ok) {
          leaks = [`OCR unavailable: ${oo?.error ?? or?.error}`];
          break;
        }
        const found = [...identityBoxes(oo, leakPhrases, ocrDpr, lib), ...identityBoxes(or, leakPhrases, ocrDpr, lib)];
        leaks = found.map((b) => b.why);
        if (!found.length) break;
        masks = [...masks, ...found];
      }
      entry.masks = masks.map((m) => ({ x: Math.round(m.x), y: Math.round(m.y), w: Math.round(m.w), h: Math.round(m.h), why: m.why }));
      if (leaks.length) {
        entry.blocked = `identity still legible after masking: ${[...new Set(leaks)].join(", ")}`;
        continue;
      }
      /* Both side variants; each is checked for equal panel geometry before it is kept. */
      for (const oursLeft of [true, false]) {
        const L = oursLeft ? panelHtml(ours, crop.oursOrigin, crop, masks) : panelHtml(ref, crop.refOrigin, crop, masks);
        const R = oursLeft ? panelHtml(ref, crop.refOrigin, crop, masks) : panelHtml(ours, crop.oursOrigin, crop, masks);
        const ctx = await browser.newContext({ viewport: { width: 2 * crop.w + 80, height: crop.h + 120 }, deviceScaleFactor: crop.dpr });
        const page = await ctx.newPage();
        await page.setContent(SHEET_PAGE(L, R), { waitUntil: "load" });
        await page.evaluate(() => Promise.all([...document.images].map((i) => i.decode())));
        const geo = await page.$$eval(".panel", (ps) => ps.map((e) => ({ w: e.getBoundingClientRect().width, h: e.getBoundingClientRect().height })));
        const buf = await page.locator(".sheet").screenshot({ animations: "disabled", scale: "device" });
        await ctx.close();
        if (geo.length !== 2 || geo[0].w !== geo[1].w || geo[0].h !== geo[1].h) {
          entry.blocked = `panels differ in size: ${JSON.stringify(geo)}`;
          break;
        }
        const name = sheetNameFor(buf);
        writeFileSync(resolve(OUT, name), buf);
        entry.sheets.push({ sheetName: name, sheetSha: sha256(buf), A: oursLeft ? "ours" : "reference", B: oursLeft ? "reference" : "ours", panelCss: geo[0] });
      }
      if (entry.blocked) continue;
      entry.slots = drawSlots(p.id, entry.sheets, slotsPerPairing);
      console.log(`  sheet ${p.id}: ${crop.w}x${crop.h} css @${Math.round(crop.dpr * 100) / 100}x vs ${ref.id}, ${entry.masks.length} mask(s), slots ${entry.slots.map((s) => (s.A === "ours" ? "L" : "R")).join("")}`);
    }
  } finally {
    await browser.close();
  }
  const key = {
    schema: "atlas-scope/blind-key/2",
    builtAt: new Date().toISOString(),
    commit: git.commit,
    dirtyTree: git.dirty,
    rule: RULE,
    ruleSha: RULE_SHA,
    dimensions: C1_DIMENSIONS,
    identityMasked: identity,
    verdictSchema: {
      file: "blind/verdicts.jsonl (append-only, one JSON object per line)",
      fields: VERDICT_FIELDS,
      perDimension: "{ <dimension>: 'A' | 'B' | 'tie' } in the critic's own A/B terms; mapped through the sheet's side",
      recognizedAs: "string naming what was recognised, or null",
    },
    unobtainable: man.unobtainable ?? [],
    pairings,
  };
  const critic = {
    instructions: CRITIC_INSTRUCTIONS,
    recognitionQuestion: RECOGNITION_QUESTION,
    slots: pairings.flatMap((p) => p.slots.map((s) => ({ slot: s.slot, sheet: s.sheetName, question: p.question }))),
  };
  return { key, critic };
}

/** A sheet's file name, derived from its bytes: a rebuild whose sheets are byte-identical keeps the
    same names, so a critic panel working from an earlier sheets.json does not lose its files
    (verifier round 1, D8). The name reveals nothing without the KEY: both side variants of a pairing
    have names of the same form. */
export const sheetNameFor = (buf) => `sheet-${sha256(buf).slice(0, 16)}.png`;

/** Critic slots for a pairing: each slot draws ITS OWN side variant with `rng(2)` (crypto.randomInt
    by default) and records the side it drew. The RNG is injectable so the self-test can prove the
    draw uses both sheets rather than one (verifier round 1, D4). */
export function drawSlots(pairingId, sheets, n, rng = randomInt) {
  if (sheets.length !== 2) throw new Error(`pairing ${pairingId}: expected two side variants, got ${sheets.length}`);
  return Array.from({ length: n }, (_, s) => {
    const sheet = sheets[rng(2)];
    return { slot: `${pairingId}#${s + 1}`, sheetName: sheet.sheetName, sheetSha: sheet.sheetSha, A: sheet.A };
  });
}

/** The parts of a KEY that decide what a verdict binds to. Two builds with the same substance are the
    same build for the critic panel: the KEY (and its slots) is kept rather than re-drawn. */
export function keySubstance(key) {
  return JSON.stringify({
    ruleSha: key.ruleSha,
    commit: key.commit,
    pairings: key.pairings.map((p) => ({ id: p.id, blocked: p.blocked ?? null, ours: p.ours?.sha256 ?? null, ref: p.ref?.sha256 ?? null, masks: p.masks ?? null, sheets: (p.sheets ?? []).map((x) => [x.sheetSha, x.A]) })),
  });
}

/** Append-only receipt for blind/verdicts.jsonl: the length and sha256 of the bytes last validated.
    A later file must START with exactly those bytes. This is a tripwire, not a lock: it catches an
    edited, truncated or deleted verdict file between validations. */
export const receiptFor = (buf) => ({ bytes: buf ? buf.length : 0, sha256: sha256(buf ?? Buffer.alloc(0)) });
export function appendOnlyProblem(receipt, buf) {
  if (!receipt || !receipt.bytes) return null;
  if (!buf) return `the verdict file is gone, but ${receipt.bytes} byte(s) of verdicts were validated before`;
  if (buf.length < receipt.bytes) return `the verdict file shrank from ${receipt.bytes} to ${buf.length} byte(s)`;
  if (sha256(buf.subarray(0, receipt.bytes)) !== receipt.sha256) return "the verdict file's first " + receipt.bytes + " byte(s) changed since they were validated (edited, not appended)";
  return null;
}

/** Move sheets that the new KEY does not list out of the live directory (never delete them). */
function retireOrphans(key) {
  if (!existsSync(OUT)) return [];
  const live = new Set(key.pairings.flatMap((p) => p.sheets.map((s) => s.sheetName)));
  const orphans = readdirSync(OUT).filter((f) => /^sheet-.*\.png$/.test(f) && !live.has(f));
  if (!orphans.length) return [];
  const dest = resolve(OUT, "_superseded", new Date().toISOString().replace(/[:.]/g, "-"));
  mkdirSync(dest, { recursive: true });
  for (const f of orphans) renameSync(resolve(OUT, f), resolve(dest, f));
  for (const f of ["KEY.json", "sheets.json"]) if (existsSync(resolve(OUT, f))) renameSync(resolve(OUT, f), resolve(dest, f));
  return orphans;
}
export function orphanSheets(key) {
  const live = new Set(key.pairings.flatMap((p) => p.sheets.map((s) => s.sheetName)));
  const onDisk = existsSync(OUT) ? readdirSync(OUT).filter((f) => /^sheet-.*\.png$/.test(f)) : [];
  return { orphans: onDisk.filter((f) => !live.has(f)), missing: [...live].filter((f) => !onDisk.includes(f)) };
}

export function readVerdicts(file) {
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf8")
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((l) => {
      try {
        return JSON.parse(l);
      } catch {
        return { unparseable: l.slice(0, 80) };
      }
    });
}

/* ── Self-tests (pure; each case would fail on the pre-2026-09-28 file) ─────────────────── */
export function selfTest() {
  let fails = 0;
  const t = (name, ok, detail = "") => {
    console.log(`${ok ? "  ok  " : "  FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
    if (!ok) fails++;
  };
  // pairings
  t("one pairing per C1 dimension", C1_DIMENSIONS.every((d) => PAIRINGS.filter((p) => p.dimension === d).length === 1) && PAIRINGS.length === C1_DIMENSIONS.length);
  t("no two pairings name the same reference frame", new Set(PAIRINGS.map((p) => p.ref)).size === PAIRINGS.length);
  const neutral = Object.values(QUESTIONS).every((q) => !/\bdemo\b|professional instrument|reference|ours|forward|grafana|fabric|linear|atlas/i.test(q));
  t("questions are neutral: no product, side or 'demo' priming", neutral);
  // geometry
  const c = cropFor({}, { css: { w: 1920, h: 1080 }, dpr: 2 }, { css: { w: 1692, h: 943 }, dpr: 1 });
  t("crop is one CSS rectangle at the lower DPR", c.w === 1692 && c.h === 943 && c.dpr === 1, JSON.stringify(c));
  // side draw
  const draws = new Set(Array.from({ length: 64 }, () => randomInt(2)));
  t("side is drawn per slot, not derived from the pairing id", draws.size === 2);
  // validator
  const sheetA = { sheetName: "s1.png", sheetSha: "SA", A: "ours", B: "reference" };
  const sheetB = { sheetName: "s2.png", sheetSha: "SB", A: "reference", B: "ours" };
  const key = { commit: "C", pairings: [{ id: "p", dimension: "composition", ours: { sha256: "O" }, ref: { sha256: "R" }, sheets: [sheetA, sheetB] }] };
  const v = (o) => ({ sheetSha: "SA", oursSha: "O", refSha: "R", commit: "C", criticId: "k1", criticModel: "m", recognized: false, recognizedAs: null, perDimension: { composition: "A" }, reasons: ["clear hop list"], faults: [], ...o });
  t("empty verdict set -> UNPROVEN", evaluate(key, []).pairings[0].status === "UNPROVEN" && evaluate(key, []).overall === "UNPROVEN");
  t("one counted verdict -> UNPROVEN", evaluate(key, [v()]).pairings[0].status === "UNPROVEN");
  t("two distinct unrecognising critics for ours/tie -> PASS", evaluate(key, [v(), v({ criticId: "k2", sheetSha: "SB", perDimension: { composition: "tie" } })]).pairings[0].status === "PASS");
  t("the side mapping is applied (B on a reference-left sheet is ours)", evaluate(key, [v({ sheetSha: "SB", perDimension: { composition: "B" } })]).pairings[0].counted[0].pick === "ours");
  t("a recognising critic is excluded and reported", (() => {
    const r = evaluate(key, [v(), v({ criticId: "k2", recognized: true, recognizedAs: "Forward in A" })]).pairings[0];
    return r.status === "UNPROVEN" && r.recognized.length === 1;
  })());
  t("the same critic twice counts once", evaluate(key, [v(), v()]).pairings[0].status === "UNPROVEN");
  t("a counted loss keeps the pairing UNPROVEN even with two wins", evaluate(key, [v(), v({ criticId: "k2" }), v({ criticId: "k3", perDimension: { composition: "B" } })]).pairings[0].status === "UNPROVEN");
  t("a verdict with no reasons is invalid", evaluate(key, [v({ reasons: [] }), v({ criticId: "k2", reasons: [" "] })]).pairings[0].invalid.length === 2);
  t("a verdict bound to another build does not count", evaluate(key, [v({ commit: "OLD" }), v({ criticId: "k2", oursSha: "X" })]).pairings[0].counted.length === 0);
  t("a verdict on an unknown sheet is stale", evaluate(key, [v({ sheetSha: "ZZ" })]).stale === 1);
  t("a blocked pairing is UNPROVEN whatever the verdicts", evaluate({ ...key, pairings: [{ ...key.pairings[0], blocked: "leak" }] }, [v(), v({ criticId: "k2" })]).pairings[0].status === "UNPROVEN");
  const omit = (o, k) => Object.fromEntries(Object.entries(o).filter(([x]) => x !== k));
  t("every verdict field is required", VERDICT_FIELDS.every((f) => verdictShapeProblems(omit(v(), f)).length > 0));
  /* ── verifier round 1 (2026-09-28): each case below was red on the file it reviewed ── */
  const safe = (f) => {
    try {
      return f();
    } catch (e) {
      return `threw: ${String(e).slice(0, 90)}`;
    }
  };
  // D2: a critic's FIRST verdict for a pairing is its only one, whatever that verdict's outcome.
  t("a critic who recognised a product cannot be counted by resubmitting unrecognised (D2)", safe(() => {
    const r = evaluate(key, [v({ recognized: true, recognizedAs: "Forward in B" }), v({ sheetSha: "SB", perDimension: { composition: "B" } }), v({ criticId: "k2" })]).pairings[0];
    return r.status === "UNPROVEN" && r.counted.length === 1 && r.duplicates.includes("k1");
  }) === true);
  t("an unreasoned loss cannot be re-asked into a win (D2)", safe(() => {
    const r = evaluate(key, [v({ perDimension: { composition: "B" }, reasons: [] }), v(), v({ criticId: "k2" })]).pairings[0];
    return r.status === "UNPROVEN" && r.counted.length === 1;
  }) === true);
  t("an invalid verdict that picks the reference still keeps the pairing UNPROVEN (D2)", safe(() => {
    const r = evaluate(key, [v({ perDimension: { composition: "B" }, reasons: [] }), v({ criticId: "k2" }), v({ criticId: "k3" })]).pairings[0];
    return r.status === "UNPROVEN" && r.uncountedLosses.length === 1;
  }) === true);
  t("an unparseable verdict line is invalid and keeps C1 UNPROVEN, not 'stale' (D8)", safe(() => {
    const ev = evaluate(key, [{ unparseable: "{oops" }]);
    return ev.stale === 0 && ev.unparseable === 1 && ev.overall === "UNPROVEN";
  }) === true);
  // D4: the slot side is drawn per slot from the sheets, with an injectable RNG.
  t("slots draw from BOTH sheets and record each slot's own side (D4)", safe(() => {
    const seq = [0, 1, 1, 0];
    const slots = drawSlots("p", [sheetA, sheetB], 4, () => seq.shift());
    const real = drawSlots("p", [sheetA, sheetB], 64);
    return (
      slots.map((s) => s.sheetSha).join() === "SA,SB,SB,SA" &&
      slots.every((s) => s.A === (s.sheetSha === "SA" ? "ours" : "reference")) &&
      new Set(real.map((s) => s.sheetSha)).size === 2
    );
  }) === true);
  // D1: a pairing names what OUR state must show, and a state that does not show it is refused.
  t("every pairing declares what our state must show (D1)", PAIRINGS.every((p) => (p.oursRequires?.expect ?? []).length > 0));
  t("a traced-path pairing refuses a state with no multi-hop trace (D1)", safe(() => {
    const p = PAIRINGS.find((x) => x.dimension === "network-visualisation");
    const line = (text, x, y) => ({ text, words: [{ text, x, y, w: 60, h: 20 }] });
    const ocrOf = (...ls) => ({ ok: true, text: ls.map((l) => l.text).join(" "), lines: ls });
    /* Each requirement is tested ALONE: every other one is met in each case. */
    const shown = (p.oursRequires.expect ?? []).map((e) => line(e, 900, 900));
    const traced = "http://h/?s=path&flow=a>b>tcp>1";
    const pre = oursRequirementProblems(p, { capture: { url: "http://h/?s=path" }, dpr: 2 }, ocrOf(line("Path", 2530, 40), line("2", 2596, 40), ...shown));
    const one = oursRequirementProblems(p, { capture: { url: traced }, dpr: 2 }, ocrOf(line("Path", 2530, 40), line("1", 2596, 40), ...shown));
    const blank = oursRequirementProblems(p, { capture: { url: traced }, dpr: 2 }, ocrOf(line("Path", 2530, 40), line("2", 2596, 40)));
    const two = oursRequirementProblems(p, { capture: { url: traced }, dpr: 2 }, ocrOf(line("Path", 2530, 40), line("2", 2596, 40), ...shown));
    return pre.length === 1 && one.length === 1 && blank.length === 1 && two.length === 0;
  }) === true);
  // D3: an identity chip is masked whole, not word by word.
  t("a workspace chip is masked through its trailing words (D3)", safe(() => {
    const ocr = { ok: true, lines: [{ words: [{ text: "Demo", x: 120, y: 24, w: 55, h: 16 }, { text: "Network", x: 183, y: 23, w: 77, h: 17 }, { text: "(default)", x: 267, y: 23, w: 79, h: 22 }, { text: ".", x: 357, y: 29, w: 11, h: 7 }, { text: "2026-02-03", x: 456, y: 24, w: 107, h: 16 }, { text: "18:51", x: 575, y: 24, w: 40, h: 16 }] }] };
    const [b] = identityBoxes(ocr, ["Demo Network"], 4 / 3, { tokens: (s) => s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean), findPhrase: (toks, ph) => (toks.join(" ").includes(ph.toLowerCase()) ? [[0, 2]] : []) });
    return !!b && b.x + b.w >= (267 + 79) / (4 / 3) && b.x + b.w < 456 / (4 / 3);
  }) === true);
  t("a phrase inside prose masks only the phrase, not the sentence (D3)", safe(() => {
    const ws = "Learn more in the Forward Documentation today".split(" ").map((text, i) => ({ text, x: i * 60, y: 10, w: 52, h: 16 }));
    const toks = (s) => s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
    const [b] = identityBoxes({ ok: true, lines: [{ words: ws }] }, ["Forward Documentation"], 1, { tokens: toks, findPhrase: (tk) => [[4, 6]] });
    return !!b && b.x > 180 && b.x + b.w < 360 + 52 + 20;
  }) === true);
  // D5: the critic is told that panels are crops, so a cut edge is not recorded as a design fault.
  t("the protocol states the crop, in the rule and in the critic's instructions (D5)", /crop/i.test(RULE) && /crop/i.test(CRITIC_INSTRUCTIONS ?? ""));
  // D8: a sheet's name is derived from its bytes, so a rebuild with identical sheets keeps them in place.
  t("sheet names are derived from the sheet's bytes (D8)", safe(() => sheetNameFor(Buffer.from("x")) === sheetNameFor(Buffer.from("x")) && sheetNameFor(Buffer.from("x")) !== sheetNameFor(Buffer.from("y"))) === true);
  t("an edited or truncated verdict file is refused (append-only receipt) (D8)", safe(() => {
    const r = receiptFor(Buffer.from('{"a":1}\n'));
    return appendOnlyProblem(r, Buffer.from('{"a":1}\n{"b":2}\n')) === null && appendOnlyProblem(r, Buffer.from('{"a":2}\n')) !== null && appendOnlyProblem(r, null) !== null && appendOnlyProblem(null, null) === null;
  }) === true);
  return fails;
}

/* ── CLI ─────────────────────────────────────────────────────────────────────────────────── */
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const args = process.argv.slice(2);
  const vi = args.indexOf("--verdicts");
  const verdictsFile = vi >= 0 ? resolve(args[vi + 1]) : resolve(OUT, "verdicts.jsonl");
  const receiptFile = resolve(OUT, "verdicts.receipt.json");
  console.log("self-tests:");
  const tf = selfTest();
  if (tf) {
    console.log(`SELF-TESTS FAILED (${tf}); nothing built`);
    process.exit(1);
  }
  if (args.includes("--selftest")) process.exit(0);
  let key;
  const keyFile = resolve(OUT, "KEY.json");
  if (args.includes("--validate")) {
    if (!existsSync(keyFile)) {
      console.log("no KEY.json: nothing to validate against — C1 UNPROVEN");
      process.exit(2);
    }
    key = JSON.parse(readFileSync(keyFile, "utf8"));
    if (key.ruleSha !== RULE_SHA) {
      console.log(`KEY was built under a different rule (${String(key.ruleSha).slice(0, 12)} != ${RULE_SHA.slice(0, 12)}): rebuild the sheets`);
      process.exit(2);
    }
  } else {
    console.log("building sheets:");
    const built = await buildSheets();
    key = built.key;
    mkdirSync(OUT, { recursive: true });
    const prior = existsSync(keyFile) ? (() => { try { return JSON.parse(readFileSync(keyFile, "utf8")); } catch { return null; } })() : null;
    if (prior && keySubstance(prior) === keySubstance(key) && orphanSheets(prior).orphans.length === 0 && orphanSheets(prior).missing.length === 0) {
      /* Same rule, commit, frames, masks and sheet bytes: the same build. Keep its KEY and slots, so a
         critic panel already working from its sheets.json is not disturbed (verifier round 1, D8). */
      key = prior;
      console.log(`  unchanged since ${prior.builtAt}: KEY.json and sheets.json kept (same rule, commit, frames, masks and sheet bytes)`);
    } else {
      const retired = retireOrphans(key);
      if (retired.length) console.log(`  moved ${retired.length} sheet(s) of an earlier build to blind/_superseded/`);
      const { orphans, missing } = orphanSheets(key);
      if (orphans.length || missing.length) {
        console.log(`REFUSED: blind/ holds orphan sheets (${orphans.join(", ")}) or lacks listed ones (${missing.join(", ")}); KEY not written`);
        process.exit(1);
      }
      writeFileSync(keyFile, JSON.stringify(key, null, 1));
      writeFileSync(resolve(OUT, "sheets.json"), JSON.stringify(built.critic, null, 1));
    }
    const n = key.pairings.reduce((a, p) => a + p.sheets.length, 0);
    const blocked = key.pairings.filter((p) => p.blocked);
    console.log(`built ${n} sheet(s) for ${key.pairings.length - blocked.length}/${key.pairings.length} pairings at ${key.commit.slice(0, 8)}${key.dirtyTree ? " (working tree dirty)" : ""}`);
    for (const b of blocked) console.log(`  BLOCKED ${b.id}: ${b.blocked}`);
  }
  /* The append-only tripwire: the verdict bytes validated last time must still be the file's prefix. */
  const vbuf = existsSync(verdictsFile) ? readFileSync(verdictsFile) : null;
  let receipt = null;
  try {
    receipt = existsSync(receiptFile) && verdictsFile === resolve(OUT, "verdicts.jsonl") ? JSON.parse(readFileSync(receiptFile, "utf8")) : null;
  } catch {
    receipt = { bytes: 1, sha256: "unreadable receipt" };
  }
  const tamper = appendOnlyProblem(receipt, vbuf);
  const verdicts = readVerdicts(verdictsFile);
  console.log(`verdicts: ${verdicts.length} in ${rel(verdictsFile)}${vbuf ? "" : " (no file — the empty set)"}`);
  const ev = evaluate(key, verdicts);
  if (tamper) {
    ev.overall = "UNPROVEN";
    console.log(`REFUSED: the verdict file is not append-only — ${tamper}. C1 cannot be PASS on an edited verdict record.`);
  } else if (vbuf && verdictsFile === resolve(OUT, "verdicts.jsonl")) writeFileSync(receiptFile, JSON.stringify(receiptFor(vbuf)));
  printEvaluation(ev);
  process.exit(tamper ? 1 : key.pairings.some((p) => p.blocked) ? 2 : 0);
}
