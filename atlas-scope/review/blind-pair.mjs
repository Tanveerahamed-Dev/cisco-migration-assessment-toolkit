/**
 * blind-pair.mjs — build the C1 blind comparison sheets, and validate the verdicts recorded
 * against them under a rule written down BEFORE any critic runs.
 *
 *   node review/blind-pair.mjs                      self-tests, build the sheets, validate verdicts
 *   ATLAS_URL=http://localhost:<port> node review/blind-pair.mjs --capture-ours
 *                                                   first capture OUR states (capture.mjs app, into the
 *                                                   private root blind/_ours) and measure our identity
 *                                                   geometry from that served build, then build as above
 *   node review/blind-pair.mjs --selftest           the self-tests only
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
 *
 * PHASE 3.5 (owner decisions, 2026-09-29):
 *   - TASK-MATCHED THROUGH ONE DEFINITION: a pairing names a kind from TASK_KINDS; its reference TARGET
 *     must declare that kind and OUR frame must meet the kind's specification. The typographic pairing
 *     had set a device's raw record against a path hop's decision table; it now uses a traced flow at
 *     its deciding hop.
 *   - RULE v3: a critic (normalised id) counts at most once per pairing and dimension; a critic who
 *     recognised a product on ANY line for the pairing is excluded wholesale; an invalid verdict never
 *     counts; any loss — counted, invalid, unattributable or a later re-ask — keeps the pairing
 *     UNPROVEN. VALIDATOR_CASES is the table that proves each.
 *   - OUR IDENTITY IS MASKED BY ITS DOM GEOMETRY (identityCensus), not by what OCR happens to read,
 *     and the geometry is checked against the frame's pixels before a sheet is built.
 *   - RECOGNITION IS MEASURED, NOT ASSUMED: blinding cannot be perfect (a 3-D render, a familiar
 *     layout, a logo glyph the OCR cannot read). Each critic answers a recognition question first;
 *     a verdict from a critic who recognised either product is excluded and reported separately.
 *
 * W5 REPAIR (O70, verifier round 2) — RULE v5, each hole closed by class with VALIDATOR_CASES rows:
 *   - R2-1: a pick is read from EVERY pick-bearing shape (any perDimension key, a non-object
 *     perDimension, any field outside the closed schema); an answer the validator cannot read is a
 *     possible loss, and one filed outside the sheet's dimension never counts as a win;
 *   - R2-2: lines bind to sheets through ONE tolerant resolver (sha, name, path, unique 8+ hex prefix,
 *     case, invisibles, space); "stale" only for a sheet an earlier KEY lists; anything else is
 *     UNBOUND and blocks C1, and is an uncounted possible loss of the pairing its frames name;
 *   - R2-3 / R2-7: recognition is read from what a verdict SAYS (identityMasked + REFERENCES.md's
 *     products); it drops a WIN but never erases a LOSS (RULE v6, below);
 *   - R2-4: derivedRecordProblems() is the pure record-vs-files check, pinned on real captures;
 *   - R2-5: the reference must show its TARGET's taskState (its result) inside the crop;
 *   - D5: --capture-ours asks capture.mjs for every paired reference's viewport, and a sheet uses our
 *     frame at that viewport when it exists (no crop).
 *
 * W5 REPAIR, round 2 (verifier QG-V1..V5) — RULE v6:
 *   - QG-V1 / requirement 3: no recognition erases a loss. v5 set a critic's loss aside when its first
 *     line said recognized:true with a recognizedAs naming anything in the vocabulary, and the
 *     vocabulary holds ordinary identity strings ("Sign in", "Forward"): "a Sign in form" erased a loss;
 *   - QG-V2: the leaves of a schema field whose TYPE the schema rejects (faults as an object,
 *     recognized: "B", reasons: "B") and a reason or fault that is nothing but a pick are read as
 *     possible picks, never "no answer";
 *   - QG-V5: an unbound line is also tied to every pairing whose dimension it files under;
 *   - QG-V4: the CLI's evaluate options come from one tested helper (cliEvaluateOptions), and
 *     `--selftest` FAILS when the R2-4 real-data check cannot run.
 *
 * The KEY (blind/KEY.json) maps sheets back to sources and is NEVER given to a critic; the critic
 * manifest (blind/sheets.json) carries only slot, sheet file, and the neutral questions. Verdicts
 * are appended, one JSON object per line, to blind/verdicts.jsonl by the critic-panel step (this
 * script never runs critics). Outputs live under review/blind/, which .gitignore excludes: they
 * contain third-party imagery and are never tracked or published.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { createHash, randomInt } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { awaitPaletteWarm } from "./palette-warm.mjs";

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
/* Our frames live in a PRIVATE capture root (blind/_ours), written by `--capture-ours` through
   capture.mjs (its render checks and index), not the shared review/shots/app that other review runs
   rewrite: the 2026-09-28 KEY's frames were re-captured under it by another run within twenty minutes. */
const OURS_SHOTS = process.env.ATLAS_SHOTS ? resolve(process.env.ATLAS_SHOTS) : resolve(HERE, "blind", "_ours");

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

/** THE TASK VOCABULARY — the one definition of what a task state IS, used on BOTH sides of a pairing
    (phase 3.5, owner: "pairings genuinely matched by task"). A pairing names a kind; the reference
    TARGET it uses must declare the same `taskKind` (capture-refs-clean.mjs, whose self-check also
    proves the reference shows it: its `expect` phrases are in its pixels), and OUR frame must meet the
    kind's `ours` specification, checked against our capture record and the OCR of our frame before a
    sheet is built. A pairing therefore cannot carry a hand-written requirement of its own that drifts
    from what its reference shows — the verifier found exactly that twice: the path surface before any
    trace against a traced-path reference (round 1, D1), and a device's raw record against a path
    hop's decision table (phase 3.5). A state that does not show the task is BLOCKED, not judged.
    `ours`:
      query   — regular expressions the captured URL must match (the investigation state; the grammar
                is src/core/store.ts :: encodeInvestigation);
      expect  — phrases that must be legible in our frame's pixels (as a TARGET's `expect`);
      minHops — the least hop count the header's Path badge must show (a drawn multi-hop trace; the
                badge is `Header.tsx :: hdr-surface__count`, the current trace's `hops.length`);
      open    — disclosures (their class, e.g. `hop__evidence`) the capture must record as OPEN
                (`capture.dom.open`, read from the page at shoot time: `.ui-disclosure[data-open=true]`);
      rows    — a row class of which at least one row must be recorded on screen (`capture.dom.rows`,
                clipped by its scroll containers) INSIDE the crop the critic sees.
    Every check is made inside the crop the critic sees, never on the whole frame (verifier V5).
    `ours: null` means no state of ours has been specified for that task yet: such a kind is unpairable.
    Each spec must name what only the TASK's surface shows — URL parameters alone name a state that may
    not be the visible one (`tab=raw` on the findings surface leaves the Finding tab showing: verifier V1). */
/* `ref` (O70 R2-5): the REFERENCE side's proof. `contrast` names the kinds that cannot show the task (a
   network at rest, a query form before its result). The reference TARGET declares `taskState` — text
   only the task's RESULT shows — which capture-refs-clean.mjs proves is content, not chrome (absent from
   every frame of the product whose kind is a contrast kind), and which must be legible INSIDE the crop
   the critic sees (refRequirementProblems). Chrome labels ("Query history", "Physical topology") hold
   whatever the screen shows, so they never prove the task. */
export const TASK_KINDS = {
  "path-blocked": {
    ref: { contrast: ["network-at-rest", "path-query-form"] },
    says: "a path question answered: the traffic is blocked or dropped, with the hop and rule that stop it",
    ours: { query: ["[?&]s=path", "[?&]flow="], expect: ["denies this flow"] },
  },
  "path-hop-decision": {
    ref: { contrast: ["network-at-rest", "path-query-form"] },
    says: "the evidence behind a path result: one hop's forwarding/filtering decision and the data it rests on",
    /* The decision AND the evidence it rests on, on screen: the evidence list opened with a row visible,
       not only its collapsed label (verifier V4). No URL state encodes an open disclosure, so this state
       is a DERIVED capture (DERIVED_STATES). */
    ours: { query: ["[?&]s=path", "[?&]flow=", "[?&]hop=\\d"], expect: ["evidence consulted at this hop"], open: ["hop__evidence"], rows: "hop__ev" },
  },
  "finding-list": {
    ref: { contrast: ["network-at-rest", "path-query-form"] },
    says: "a dense working list of findings / vulnerable devices, filtered by severity",
    ours: { query: ["[?&]s=findings", "[?&]sev="], expect: ["severity critical"] },
  },
  "result-data-inspection": {
    ref: { contrast: ["network-at-rest", "path-query-form"] },
    says: "inspecting the raw data behind one result",
    /* The raw record must be the VISIBLE surface: the evidence surface on its Raw tab, whose own
       sentence is legible (src/panels/DevicePane.tsx raw tab). The finding surface with tab=raw shows
       the Finding tab (verifier V1). */
    ours: { query: ["[?&]s=evidence", "[?&]tab=raw"], expect: ["this is the compiled record this pane renders from"] },
  },
  "path-drawn": {
    ref: { contrast: ["network-at-rest", "path-query-form"] },
    says: "the network drawn with a traced multi-hop path highlighted on it",
    ours: { query: ["[?&]s=path", "[?&]flow="], expect: ["trace a flow"], minHops: 2 },
  },
  "path-result-device": { says: "path search results with one device's details open", ours: null },
  "network-at-rest": { says: "the network map or graph at rest, nothing traced", ours: null },
  "path-query-form": { says: "the whole application on its path query form", ours: null },
};

/** One pairing per dimension, each naming a task kind (above). Our theme follows the reference's
    measured theme. The network-visualisation pairing compares our 3-D render with a 2-D topology
    because no reference product has a 3-D render — stated as such, pending the owner's decision to
    keep it in C1 or move it to C5. `similarScreenWith` declares — with the reason — that this
    pairing's reference is the same KIND of screen as another pairing's (capture-refs-clean.mjs
    measures that and refuses it undeclared). Two pairings may use one state of ours (only reference
    reuse is policed); their themes, and so their frames, may differ. */
export const PAIRINGS = [
  {
    id: "c1-composition",
    dimension: "composition",
    ours: "06-path-blocked",
    ref: "forward-path-dropped",
    task: "path-blocked",
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
    task: "finding-list",
  },
  {
    id: "c1-typographic-craft",
    dimension: "typographic-craft",
    /* Not 07-evidence-raw: that is ONE DEVICE's compiled record, while the reference is a traced path's
       per-hop decision table (phase 3.5). A traced flow at its deciding hop, with the evidence consulted
       at that hop OPENED (06 alone shows only the collapsed label: verifier V4) — a derived capture. */
    ours: "06b-path-hop-evidence",
    ref: "ipfabric-path-detail",
    task: "path-hop-decision",
  },
  {
    id: "c1-colour-discipline",
    dimension: "colour-discipline",
    /* Not 04-finding-evidence: its URL carries tab=raw but its visible surface is the Finding tab (a
       finding summary), against Grafana Explore's query data (verifier V1). 07 shows the raw record. */
    ours: "07-evidence-raw",
    ref: "grafana-explore",
    task: "result-data-inspection",
  },
  {
    id: "c1-network-visualisation",
    dimension: "network-visualisation",
    /* 08, not 05 (the path surface before any flow is run) and not 06 (a single-hop trace: its own
       capture note says no path geometry between devices is drawn). 08's trace is multi-hop and drawn. */
    ours: "08-path-indeterminate",
    ref: "forward-topology-path",
    task: "path-drawn",
    similarScreenWith: { "c1-composition": "See c1-composition." },
    note: "3-D render judged against a 2-D topology as 'network visualisation' (no reference has a 3-D render); owner decision pending: keep in C1 or move to C5.",
  },
];

/** OUR states that no URL can encode (an opened disclosure), captured by this script (`--capture-ours`)
    FROM a capture.mjs state: the same URL, theme, viewport and DPR, the same settle, tier and
    convergence gates and the palette pre-warm wait, then the interaction, then the shot. The record
    carries the DOM facts the task kinds check (`dom.open`, `dom.rows`) and the sha of the base frame
    it was derived from; a derived frame whose base capture has since been replaced is refused.
      from   — the capture.mjs state (review/capture.mjs APP_STATES id) it starts from;
      open   — disclosure selectors whose trigger is clicked open;
      reveal — a row class scrolled into view (the nearest scroll container moves, nothing else). */
export const DERIVED_STATES = [
  {
    id: "06b-path-hop-evidence",
    from: "06-path-blocked",
    open: [".hop__evidence"],
    reveal: "hop__ev",
    note: "The blocked flow at its deciding hop, with the evidence consulted at that hop opened and its first row in view.",
  },
];

/** Pairings whose reference TARGET does not declare the pairing's task kind, or whose kind is not in
    the vocabulary or has no specification of our side. Empty = every pairing is task-matched by
    declaration (the pixels are then checked on both sides). */
export function taskKindProblems(pairings, targets) {
  const out = [];
  for (const p of pairings) {
    const kind = TASK_KINDS[p.task];
    if (!kind) out.push(`${p.id}: task kind ${JSON.stringify(p.task)} is not in TASK_KINDS`);
    else if (!kind.ours) out.push(`${p.id}: task kind ${p.task} specifies no state of ours`);
    const t = targets.find((x) => x.id === p.ref);
    if (!t) out.push(`${p.id}: reference ${p.ref} is not a TARGET`);
    else if (t.taskKind !== p.task) out.push(`${p.id}: reference ${p.ref} shows task ${JSON.stringify(t.taskKind)}, not ${JSON.stringify(p.task)}`);
  }
  return out;
}

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

/** The OCR of a frame restricted to a CSS-px rectangle (the crop the critic sees): only words whose
    centre lies inside survive, and the text is rebuilt from them. A frame read without word geometry
    cannot be restricted, so it yields no text (fail closed, never the whole frame's text). */
export function ocrWithin(ocr, rect, dpr) {
  if (!ocr?.ok) return ocr;
  const inside = (w) => {
    const cx = (w.x + w.w / 2) / dpr;
    const cy = (w.y + w.h / 2) / dpr;
    return cx >= rect.x && cx <= rect.x + rect.w && cy >= rect.y && cy <= rect.y + rect.h;
  };
  const lines = (ocr.lines ?? []).map((l) => ({ ...l, words: (l.words ?? []).filter(inside) })).filter((l) => l.words.length);
  return { ...ocr, lines, text: lines.map((l) => l.words.map((w) => w.text).join(" ")).join("\n") };
}
const intersects = (r, c) => r.x < c.x + c.w && r.x + r.w > c.x && r.y < c.y + c.h && r.y + r.h > c.y;

/** What is missing for OUR frame to show the pairing's task (its kind's `ours` specification), judged
    inside `crop` (CSS px of our frame: what the critic sees; the whole frame when null). Empty = it shows it. */
/** What is missing for the REFERENCE frame to show the pairing's task inside `crop` (CSS px of the
    reference: what the critic sees): its TARGET's `taskState` phrases (O70 R2-5). Empty = it shows it. */
export function refRequirementProblems(target, ocrWhole, crop, dpr) {
  const phrases = Array.isArray(target?.taskState) ? target.taskState.filter((x) => typeof x === "string" && x.trim()) : [];
  if (!phrases.length) return [`reference ${target?.id ?? "?"} declares no taskState, so only chrome labels would say it shows the task`];
  const ocr = crop ? ocrWithin(ocrWhole, crop, dpr ?? 1) : ocrWhole;
  if (!ocr?.ok) return [`the reference's pixels could not be read (${ocr?.error ?? "no OCR"})`];
  return phrases.filter((ph) => !findPhraseIn(ocr.text, ph)).map((ph) => `"${ph}" (the task's result) is not legible in the reference${crop ? " inside the crop" : ""}`);
}
export function oursRequirementProblems(p, ours, ocrWhole, crop = null) {
  const req = TASK_KINDS[p.task]?.ours ?? {};
  const out = [];
  if (!(req.expect ?? []).length) out.push(`the pairing's task kind ${JSON.stringify(p.task)} does not specify what our state must show`);
  const url = ours?.capture?.url ?? "";
  for (const q of req.query ?? []) if (!new RegExp(q).test(url)) out.push(`our captured state ${JSON.stringify(url.replace(/^https?:\/\/[^/]+/, ""))} does not match ${q}`);
  const dom = ours?.capture?.dom ?? null;
  for (const c of req.open ?? []) if (!(dom?.open ?? []).includes(c)) out.push(`the "${c}" disclosure is not recorded as open in our capture${dom ? "" : " (the capture recorded no DOM state)"}`);
  if (req.rows) {
    const rows = (dom?.rows?.[req.rows] ?? []).filter((r) => r.w >= 1 && r.h >= 8);
    const shown = crop ? rows.filter((r) => intersects(r, crop)) : rows;
    if (!shown.length) out.push(`no "${req.rows}" row is recorded on screen${crop ? " inside the crop" : ""} (${rows.length} on screen in the whole frame)`);
  }
  const ocr = crop ? ocrWithin(ocrWhole, crop, ours?.dpr ?? 1) : ocrWhole;
  if (!ocr?.ok) {
    out.push(`our frame's pixels could not be read (${ocr?.error ?? "no OCR"})`);
    return out;
  }
  for (const e of req.expect ?? []) if (!findPhraseIn(ocr.text, e)) out.push(`"${e}" is not legible in our frame${crop ? " inside the crop" : ""}`);
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
export const RULE = `C1 blind-verdict rule v6 (pre-registered; changing it changes ruleSha, recorded in every KEY).
SHEETS. A verdict line's sheet reference (its sheetSha) is resolved against the CURRENT sheets through one resolver, tolerant of form: the full sha, the sheet's file name (with or without a path or ".png"), or a unique prefix of at least 8 hex characters of the sha, after Unicode form, invisible (default-ignorable) characters, case and surrounding space are normalised. A line so resolved BELONGS to that sheet's pairing P. A line whose reference resolves only to a sheet an EARLIER build's KEY lists (blind/_superseded/*/KEY.json) is STALE: an earlier build's pixels; it never counts and uses up nothing. Any other line is UNBOUND and keeps C1 UNPROVEN (as an unparseable line does); it also BELONGS, with its side UNKNOWN, to every pairing it can be tied to — the one pairing whose frames its oursSha and refSha name, and every pairing whose dimension it files an answer under (key normalised as below) — so it is an invalid verdict there whose A or B is a possible loss, and it is that critic's first line there. An unbound line is never read as stale.
A CRITIC is its criticId with Unicode form, invisible characters, case and spacing normalised ("k1", " K1 " and "k1" with a zero-width space are one critic); the result must be plain ASCII letters, digits, '.', '_' or '-'. A line without such an id is UNATTRIBUTABLE: it never counts.
A PICK is read from EVERY pick-bearing shape on the line, because each sheet asks exactly one question: every value in perDimension under any key, a perDimension that is not an object (a bare string is read as a pick), every leaf (objects and arrays recursed) of a field outside the verdict schema or of a schema field whose type is wrong (a shape the validator cannot interpret may hold a pick), and every reason or fault that is nothing but "A", "B" or "tie". Each value is normalised as a critic id is: "A"/"a", "B"/" b " or "tie" (mapped to ours/reference through the sheet's recorded side); a value that is not A, B or tie — or any value that is not a string — is UNREADABLE and is treated as a possible loss, never as a win. Values that disagree are unreadable when any of them may pick the reference. An answer not filed under the key P.dimension (case, Unicode form, invisible characters and separators normalised) makes the verdict invalid, but its value is still read: a win filed elsewhere never counts; a loss filed elsewhere is still a loss. A line with no value at all is no answer.
ONE VERDICT PER CRITIC PER PAIRING AND DIMENSION: the FIRST line from a critic that belongs to P is that critic's verdict for P, whatever its outcome (counted, recognised or invalid). Every later line from that critic for P is a DUPLICATE and never counts, so neither a recognition nor an invalid verdict can be re-asked away.
RECOGNITION DROPS A WIN BUT NEVER ERASES A LOSS. A line discloses recognition when it says recognized === true, or when its recognizedAs, reasons, faults or any field outside the schema NAME a product or identity string: any string in the KEY's identityMasked or any reference product REFERENCES.md lists, matched as whole words (joined or possessive forms included), whatever recognized says. A critic who discloses recognition on ANY line for P, first or later, is excluded from counting for P and reported; every loss on its record STANDS. A line that says recognized === true with an empty recognizedAs is invalid, and so is recognized === false with a non-empty recognizedAs.
A critic's verdict for P COUNTS only if ALL hold:
  1. it has every field {sheetSha, oursSha, refSha, commit, criticId, criticModel, recognized, recognizedAs, perDimension, reasons, faults} with the right type (reasons and faults arrays of strings), and no other field;
  2. its sheet reference resolves to one of P's current sheets, and oursSha, refSha and commit equal P's KEY values;
  3. the critic is attributable and has disclosed no recognition, on any line;
  4. its pick is A, B or tie after normalisation, filed under P.dimension;
  5. reasons holds at least one non-empty string, and faults is an array.
A LOSS IS NEVER IGNORED: any line of P that picks the reference, or whose pick is unreadable — a counted verdict, an invalid verdict (an UNCOUNTED LOSS: absence of reasons is not a win), an unattributable line (recognising or not), a line bound to P only by its frames, a later duplicate, or any line of a critic who disclosed recognition — keeps P UNPROVEN. No loss is set aside.
P is PASS iff at least 2 counted verdicts from distinct critics exist AND there is no loss.
Otherwise P is UNPROVEN. A loss keeps P UNPROVEN for that build: verdicts are append-only (a receipt of the validated prefix refuses an edited or truncated file), so a loss cannot be re-run away; its reasons become work items, and only a new build (new sheets) starts a new count.
When either panel of a sheet is a CROP of a larger screen, both are the same size and cut at the same place: content cut by a panel edge is an artefact of the crop, not a fault of the design, and such faults are not work items.
An unparseable verdict line, or an unbound one, cannot be attributed and keeps C1 UNPROVEN until it is resolved by appending, never by editing. A recognition vocabulary that cannot be read keeps C1 UNPROVEN.
C1 is PASS iff every pairing is PASS; otherwise UNPROVEN. Linear is out of scope (not obtainable without an account).`;
export const CRITIC_INSTRUCTIONS =
  "You are shown sheets of two interface screenshots, A and B. Answer the recognition question FIRST, then the question for the sheet. " +
  "Both panels are same-size crops of larger screens, cut at the same place: text or controls cut off at a panel edge are an artefact of the crop, so do not count them as faults. " +
  "Grey rectangles are neutral masks, placed identically on both panels; ignore them. List every specific, actionable fault you see in EITHER panel.";
export const RULE_SHA = sha256(Buffer.from(RULE));

/** The reference products REFERENCES.md names — the Product column of its reference-set table — read
    from that file, not restated here: with the KEY's identityMasked they are the vocabulary a verdict
    is screened against for recognition (R2-3). Empty when the file or its table cannot be read, which
    the validator reports rather than reading as "nothing to recognise". */
export function referenceProductsFrom(md) {
  const lines = String(md).split(/\r?\n/);
  const at = lines.findIndex((l) => /^##\s+The C1 reference set\b/.test(l));
  if (at < 0) return [];
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.replace(/[`*]/g, "").trim());
  let i = lines.findIndex((l, j) => j > at && /^\s*\|/.test(l));
  if (i < 0) return [];
  const col = cells(lines[i]).findIndex((c) => /^product$/i.test(c));
  if (col < 0) return [];
  const out = [];
  for (i += 1; i < lines.length && /^\s*\|/.test(lines[i]); i++) {
    const c = cells(lines[i])[col] ?? "";
    if (c && !/^:?-+:?$/.test(c)) out.push(c);
  }
  return [...new Set(out)];
}
export const REFERENCES_MD = resolve(HERE, "REFERENCES.md");
export const REFERENCE_PRODUCTS = (() => {
  try {
    return referenceProductsFrom(readFileSync(REFERENCES_MD, "utf8"));
  } catch {
    return [];
  }
})();

/** Two sheets named as a real build names them (sheet-<first 16 hex of its sha>.png), for the rows
    that bind a line by name, prefix, case or spacing (R2-2). */
export const HEX_SHEETS = ["78c6277c8c1ab709" + "0".repeat(48), "9909f156910f9e33" + "0".repeat(48)];
/** The keys the validator rows run against, by name (`row.key`; the default is "default"). */
export function validatorKeys() {
  const sheetA = { sheetName: "s1.png", sheetSha: "SA", A: "ours", B: "reference" };
  const sheetB = { sheetName: "s2.png", sheetSha: "SB", A: "reference", B: "ours" };
  const pairing = (dimension, sheets) => ({ id: "p", dimension, ours: { sha256: "O" }, ref: { sha256: "R" }, sheets });
  const identityMasked = ["Forward", "Forward AI", "Grafana", "IPFabric", "Atlas Scope"];
  return {
    default: { commit: "C", identityMasked, pairings: [pairing("composition", [sheetA, sheetB])] },
    colour: { commit: "C", identityMasked, pairings: [pairing("colour-discipline", [sheetA, sheetB])] },
    hex: { commit: "C", identityMasked, pairings: [pairing("composition", HEX_SHEETS.map((s, i) => ({ sheetName: `sheet-${s.slice(0, 16)}.png`, sheetSha: s, A: i ? "reference" : "ours", B: i ? "ours" : "reference" })))] },
    bare: { commit: "C", identityMasked: [], pairings: [pairing("composition", [sheetA, sheetB])] },
    /* identityMasked as the real KEY's holds it: ordinary words and chips beside the product names. */
    signin: { commit: "C", identityMasked: [...identityMasked, "Sign in", "Demo Network", "demoguy"], pairings: [pairing("composition", [sheetA, sheetB])] },
  };
}

/** The validator's cases, as a table: each row is a verdict sequence on one pairing (sheet SA puts
    ours in A, sheet SB puts the reference in A; a row object overrides a valid, unrecognising,
    reasoned verdict from critic k1 on SA picking A) and the outcome RULE demands, with the exact set
    of critics counted. `selfTest` runs every row; a row is never deleted to get green. */
export const VALIDATOR_CASES = [
  { name: "the empty set is UNPROVEN", verdicts: [], want: { status: "UNPROVEN", counted: [] } },
  { name: "two distinct critics picking ours or a tie PASS", verdicts: [{}, { criticId: "k2", perDimension: { composition: "tie" } }], want: { status: "PASS", counted: ["k1", "k2"] } },
  { name: "one critic twice counts once", verdicts: [{}, {}], want: { status: "UNPROVEN", counted: ["k1"] } },
  { name: "a critic id differing only in case or spacing is the same critic", verdicts: [{}, { criticId: " K1 " }], want: { status: "UNPROVEN", counted: ["k1"] } },
  { name: "both side variants from one critic count once", verdicts: [{}, { sheetSha: "SB", perDimension: { composition: "B" } }], want: { status: "UNPROVEN", counted: ["k1"] } },
  {
    name: "recognised, then resubmitted as unrecognised: never counted",
    verdicts: [{ recognized: true, recognizedAs: "Forward in B" }, { sheetSha: "SB", perDimension: { composition: "B" } }, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k2"] },
  },
  {
    name: "counted, then the same critic discloses recognition: excluded",
    verdicts: [{}, { recognized: true, recognizedAs: "Grafana in B" }, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k2"] },
  },
  {
    name: "an invalid loss (no reasons) re-asked into a win stays a loss",
    verdicts: [{ perDimension: { composition: "B" }, reasons: [] }, {}, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "an invalid loss (another build) re-asked into a win stays a loss",
    verdicts: [{ perDimension: { composition: "B" }, commit: "OLD" }, {}, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  { name: "a win re-asked into a loss: the loss stands", verdicts: [{}, { perDimension: { composition: "B" } }, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  {
    name: "an invalid verdict with no pick, resubmitted valid: that critic is never counted",
    verdicts: [{ perDimension: {} }, {}, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "PASS", counted: ["k2", "k3"] },
  },
  { name: "an invalid verdict (no model) is never counted", verdicts: [{ criticModel: "" }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k2"] } },
  {
    /* (W5 round 2, requirement 3 "recognition drops a WIN but never erases a LOSS": this row expected
       PASS under the earlier D2 reading, which set a first-line recogniser aside loss included.) */
    name: "a recognising critic is never counted, and its pick of the reference is still a loss (requirement 3)",
    verdicts: [{ recognized: true, recognizedAs: "Forward in B", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  { name: "an unattributable line picking the reference is still a loss", verdicts: [{ criticId: "", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }], want: { status: "UNPROVEN", counted: ["k2", "k3"] } },
  { name: "a counted loss keeps UNPROVEN even with two wins", verdicts: [{}, { criticId: "k2" }, { criticId: "k3", perDimension: { composition: "B" } }], want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] } },
  /* (W5, R2-2: "stale" now means a sheet an earlier build's KEY lists, so the row names that KEY; a
     sheet no KEY lists is the row "a line on a sheet NO KEY lists" below.) */
  { name: "a line on a stale sheet does not use up the critic's verdict", superseded: ["OLD"], verdicts: [{ sheetSha: "OLD" }, {}, { criticId: "k2" }], want: { status: "PASS", counted: ["k1", "k2"], overall: "PASS" } },
  /* ── phase 3.5 repair (verifier V2, V3, V6, V7): a re-ask, a spelling, an id variant or an
     unattributable recognition can never erase a loss. ── */
  {
    name: "a counted loss, then the same critic discloses recognition: the loss stands (V2)",
    verdicts: [{ perDimension: { composition: "B" } }, { recognized: true, recognizedAs: "Forward in B" }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "an invalid loss (no reasons), then recognition: the loss stands (V2)",
    verdicts: [{ perDimension: { composition: "B" }, reasons: [] }, { recognized: true, recognizedAs: "Grafana in B" }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "a win, then a re-ask that recognises AND picks the reference: the loss stands (V2)",
    verdicts: [{}, { recognized: true, recognizedAs: "Forward in B", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    /* (requirement 3: expected PASS under the earlier D2 reading) */
    name: "recognised on the FIRST line, then a loss on a re-ask: never counted, and the loss stands (requirement 3)",
    verdicts: [{ recognized: true, recognizedAs: "Forward in B" }, { perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  { name: "a loss spelled lowercase 'b' is a loss (V3)", verdicts: [{ perDimension: { composition: "b" } }, { criticId: "k2" }, { criticId: "k3" }], want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] } },
  { name: "a loss spelled ' B ' is a loss (V3)", verdicts: [{ perDimension: { composition: " B " } }, { criticId: "k2" }, { criticId: "k3" }], want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] } },
  { name: "a lowercase 'a' on an ours-left sheet is a win", verdicts: [{ perDimension: { composition: "a" } }, { criticId: "k2" }], want: { status: "PASS", counted: ["k1", "k2"] } },
  {
    name: "an unreadable pick ('reference') fails closed: an uncounted loss (V3)",
    verdicts: [{ perDimension: { composition: "reference" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  { name: "an unreadable pick ('panel A') fails closed too (V3)", verdicts: [{ perDimension: { composition: "panel A" } }, { criticId: "k2" }, { criticId: "k3" }], want: { status: "UNPROVEN", counted: ["k2", "k3"] } },
  { name: "a zero-width character does not make a second critic (V6)", verdicts: [{}, { criticId: "k1​" }], want: { status: "UNPROVEN", counted: ["k1"] } },
  { name: "an invisible character inside an otherwise valid id leaves that id (k2) attributable (V6)", verdicts: [{}, { criticId: "k2​", sheetSha: "SB", perDimension: { composition: "tie" } }], want: { status: "PASS", counted: ["k1", "k2"] } },
  { name: "a homoglyph id (Cyrillic) is unattributable, never a second critic (V6)", verdicts: [{}, { criticId: "к1" }], want: { status: "UNPROVEN", counted: ["k1"] } },
  {
    name: "a homoglyph id's loss is still a loss (V6)",
    verdicts: [{ criticId: "к1", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "an unattributable line that recognises and picks the reference is still a loss (V7)",
    verdicts: [{ criticId: "", recognized: true, recognizedAs: "Forward in B", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  /* ── W5 repair (O70, verifier round 2): a loss can vanish through the KEY it is filed under (R2-1),
     the SHEET reference it names (R2-2), a product named outside the `recognized` flag (R2-3), or an
     empty recognition (R2-7). Each row below was red on the file that verifier reviewed. `superseded`
     lists the sheets of an earlier build's KEY (the only sheets a line may be "stale" on); `overall`
     is C1's overall result for that verdict set. ── */
  {
    name: "a loss filed under 'color-discipline' (US spelling) on a colour sheet is a loss (R2-1)",
    key: "colour",
    verdicts: [{ criticId: "k3", perDimension: { "color-discipline": "B" } }, { perDimension: { "colour-discipline": "A" } }, { criticId: "k2", perDimension: { "colour-discipline": "A" } }],
    want: { status: "UNPROVEN", counted: ["k1", "k2"] },
  },
  {
    name: "a loss filed under 'Colour-Discipline' (case variant) is a counted loss (R2-1)",
    key: "colour",
    verdicts: [{ criticId: "k3", perDimension: { "Colour-Discipline": "B" } }, { perDimension: { "colour-discipline": "A" } }, { criticId: "k2", perDimension: { "colour-discipline": "A" } }],
    want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] },
  },
  {
    name: "a bare-string perDimension 'B' is a loss, never 'no answer' (R2-1)",
    verdicts: [{ criticId: "k3", perDimension: "B" }, {}, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k1", "k2"] },
  },
  { name: "a perDimension array holding 'B' is a possible loss (R2-1)", verdicts: [{ criticId: "k3", perDimension: ["B"] }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  {
    name: "a win under the dimension with a 'B' under another key on the same line is a possible loss (R2-1)",
    verdicts: [{ criticId: "k3", perDimension: { composition: "A", "information-density": "B" } }, {}, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k1", "k2"] },
  },
  {
    name: "a pick in a field outside the verdict schema is read: 'B' there is a loss (R2-1)",
    verdicts: [{ criticId: "k3", perDimension: {}, pick: "B" }, {}, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k1", "k2"] },
  },
  {
    name: "a win filed under another dimension's key is never counted (R2-1)",
    verdicts: [{ perDimension: { "information-density": "A" } }, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k2"] },
  },
  {
    name: "a loss bound by the sheet NAME, then a re-ask win on the exact sha: the loss stands (R2-2)",
    key: "hex",
    verdicts: [{ sheetSha: "sheet-78c6277c8c1ab709.png", perDimension: { composition: "B" } }, { sheetSha: HEX_SHEETS[0] }, { criticId: "k2", sheetSha: HEX_SHEETS[0] }, { criticId: "k3", sheetSha: HEX_SHEETS[0] }],
    want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] },
  },
  {
    name: "a loss bound by a 16-hex sha prefix is a loss (R2-2)",
    key: "hex",
    verdicts: [{ sheetSha: "78c6277c8c1ab709", perDimension: { composition: "B" } }, { criticId: "k2", sheetSha: HEX_SHEETS[0] }, { criticId: "k3", sheetSha: HEX_SHEETS[0] }],
    want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] },
  },
  {
    name: "a loss bound by an UPPERCASED sha is a loss (R2-2)",
    key: "hex",
    verdicts: [{ sheetSha: HEX_SHEETS[0].toUpperCase(), perDimension: { composition: "B" } }, { sheetSha: HEX_SHEETS[0] }, { criticId: "k2", sheetSha: HEX_SHEETS[0] }, { criticId: "k3", sheetSha: HEX_SHEETS[0] }],
    want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] },
  },
  {
    name: "a loss whose sha carries a trailing space is a loss (R2-2)",
    key: "hex",
    verdicts: [{ sheetSha: `${HEX_SHEETS[0]} `, perDimension: { composition: "B" } }, { criticId: "k2", sheetSha: HEX_SHEETS[0] }, { criticId: "k3", sheetSha: HEX_SHEETS[0] }],
    want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] },
  },
  {
    name: "a loss naming the sheet by its path is a loss (R2-2)",
    key: "hex",
    verdicts: [{ sheetSha: "review/blind/sheet-78c6277c8c1ab709.png", perDimension: { composition: "B" } }, { criticId: "k2", sheetSha: HEX_SHEETS[0] }, { criticId: "k3", sheetSha: HEX_SHEETS[0] }],
    want: { status: "UNPROVEN", counted: ["k1", "k2", "k3"] },
  },
  {
    name: "a loss naming no current sheet but this pairing's frames is an uncounted loss here, and its re-ask never counts (R2-2)",
    key: "hex",
    verdicts: [{ sheetSha: "s9.png", perDimension: { composition: "B" } }, { sheetSha: HEX_SHEETS[0] }, { criticId: "k2", sheetSha: HEX_SHEETS[0] }, { criticId: "k3", sheetSha: HEX_SHEETS[0] }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"], overall: "UNPROVEN" },
  },
  {
    /* (W5 round 2, QG-V5: this row expected the pairing PASS with k1's re-ask counted as its first
       verdict — the dimension key the line files its answer under names the pairing.) */
    name: "a line bound to no sheet whose frames name no pairing is bound by the dimension it files under: its loss stands, its re-ask never counts, C1 is blocked (R2-2, QG-V5)",
    key: "hex",
    verdicts: [{ sheetSha: "s9.png", oursSha: "X", refSha: "Y", perDimension: { composition: "B" } }, { sheetSha: HEX_SHEETS[0] }, { criticId: "k2", sheetSha: HEX_SHEETS[0] }, { criticId: "k3", sheetSha: HEX_SHEETS[0] }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"], overall: "UNPROVEN" },
  },
  {
    name: "the dimension key binds an unbound line tolerantly (case, separators): its loss stands (QG-V5)",
    key: "colour",
    verdicts: [{ sheetSha: "zz", oursSha: "X", refSha: "Y", perDimension: { "Colour_Discipline": "A" } }, { perDimension: { "colour-discipline": "A" } }, { criticId: "k2", perDimension: { "colour-discipline": "A" } }],
    want: { status: "UNPROVEN", counted: ["k2"], overall: "UNPROVEN" },
  },
  {
    name: "a line tied to no sheet, no frames and no dimension still blocks C1 overall, like an unparseable line (R2-2)",
    key: "hex",
    verdicts: [{ sheetSha: "s9.png", oursSha: "X", refSha: "Y", perDimension: "B" }, { sheetSha: HEX_SHEETS[0] }, { criticId: "k2", sheetSha: HEX_SHEETS[0] }],
    want: { status: "PASS", counted: ["k1", "k2"], overall: "UNPROVEN" },
  },
  {
    name: "a line on a sheet an earlier KEY lists is stale: it never counts, uses up nothing and blocks nothing (R2-2)",
    superseded: ["OLDSHEET"],
    verdicts: [{ sheetSha: "OLDSHEET", perDimension: { composition: "B" } }, {}, { criticId: "k2" }],
    want: { status: "PASS", counted: ["k1", "k2"], overall: "PASS" },
  },
  {
    name: "a line on a sheet NO KEY lists is not 'stale': it is bound to its pairing by its frames and its loss stands (R2-2)",
    verdicts: [{ sheetSha: "OLDSHEET", perDimension: { composition: "B" } }, {}, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"], overall: "UNPROVEN" },
  },
  {
    name: "recognizedAs naming a product under recognized:false is recognition: the win is dropped (R2-3)",
    verdicts: [{ recognized: false, recognizedAs: "Grafana Explore in B" }, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k2"] },
  },
  {
    name: "reasons naming a product are recognition: the win is dropped (R2-3)",
    verdicts: [{ reasons: ["B is Grafana Explore; its colours are muted"] }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "PASS", counted: ["k2", "k3"] },
  },
  {
    name: "reasons naming a product never erase that critic's loss (R2-3)",
    verdicts: [{ reasons: ["B is Grafana Explore and reads better"], perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "faults naming a product are recognition too (R2-3)",
    verdicts: [{ faults: ["the Forward AI entry in B is cramped"] }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "PASS", counted: ["k2", "k3"] },
  },
  {
    name: "a product named in a LATER line drops the first line's win (R2-3)",
    verdicts: [{}, { reasons: ["on reflection A is Atlas Scope"] }, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k2"] },
  },
  {
    name: "a reference product REFERENCES.md names is recognition even when the KEY's identity list lacks it (R2-3)",
    key: "bare",
    verdicts: [{ reasons: ["B looks like IP Fabric's path lookup"] }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "PASS", counted: ["k2", "k3"] },
  },
  {
    name: "a product name joined up ('IPFabric') or possessive ('Grafana's') is still named (R2-3)",
    verdicts: [{ reasons: ["IPFabric-style table"] }, { criticId: "k2", reasons: ["Grafana's palette"] }, { criticId: "k3" }, { criticId: "k4" }],
    want: { status: "PASS", counted: ["k3", "k4"] },
  },
  {
    name: "a brand word inside another word ('forwarding') is not a product name (R2-3)",
    verdicts: [{ reasons: ["the forwarding table is legible"] }, { criticId: "k2" }],
    want: { status: "PASS", counted: ["k1", "k2"] },
  },
  {
    name: "recognized:true with an empty recognizedAs on the first line does not erase that critic's loss (R2-7)",
    verdicts: [{ recognized: true, recognizedAs: "", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "recognized:true with an invisible-only recognizedAs does not exclude its critic wholesale (R2-7)",
    verdicts: [{ recognized: true, recognizedAs: " ​ ", perDimension: { composition: "B" } }, { perDimension: { composition: "A" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "recognized:true naming nothing either product is known by ('nothing') does not erase a loss (R2-7 class)",
    verdicts: [{ recognized: true, recognizedAs: "nothing in particular", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "recognized:true with an empty recognizedAs is never counted, even as a win (R2-7)",
    verdicts: [{ recognized: true, recognizedAs: "" }, {}, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k2"] },
  },
  /* ── W5 round 2 (verifier QG-V1..V5). QG-V1 / requirement 3: recognition drops a WIN but never
     erases a LOSS — not through a vocabulary word that names no product ("Sign in", "forward-thinking"
     on a KEY whose identityMasked holds them, as the real KEY's does), and not through a valid named
     recognition either. ── */
  {
    name: "recognized:true 'a Sign in form' (an identity string, not a product) never erases the loss (QG-V1)",
    key: "signin",
    verdicts: [{ recognized: true, recognizedAs: "a Sign in form", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "recognized:true 'B looks forward-thinking' never erases the loss (QG-V1)",
    key: "signin",
    verdicts: [{ recognized: true, recognizedAs: "B looks forward-thinking", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "a valid named recognition ('Forward Enterprise in B') on the first line never erases its loss (requirement 3)",
    verdicts: [{ recognized: true, recognizedAs: "Forward Enterprise in B", perDimension: { composition: "B" } }, { criticId: "k2" }, { criticId: "k3" }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "a first-line recogniser's LATER loss stands too (requirement 3)",
    verdicts: [{ recognized: true, recognizedAs: "Grafana in B" }, { criticId: "k2" }, { criticId: "k3" }, { sheetSha: "SB", perDimension: { composition: "A" } }],
    want: { status: "UNPROVEN", counted: ["k2", "k3"] },
  },
  {
    name: "a recognition naming only an identity string still drops the win (QG-V1)",
    key: "signin",
    verdicts: [{ recognized: true, recognizedAs: "a Sign in form" }, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k2"] },
  },
  /* QG-V2 (R2-1 by class): a pick held in a MALFORMED schema field is read as a possible pick, never
     "no answer" — every leaf of a field whose type the schema rejects (recursing into objects and
     arrays), and a reason or fault that is nothing but a pick. */
  { name: "faults as an object keyed by the dimension holding 'B' is a loss (QG-V2)", verdicts: [{ criticId: "k3", perDimension: {}, faults: { composition: "B" } }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  { name: "recognized: 'B' (not a boolean) is a possible loss (QG-V2)", verdicts: [{ criticId: "k3", perDimension: {}, recognized: "B" }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  { name: "reasons: 'B' (not an array) is a possible loss (QG-V2)", verdicts: [{ criticId: "k3", perDimension: {}, reasons: "B" }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  { name: "a non-string reason holding 'B' is a possible loss (QG-V2)", verdicts: [{ criticId: "k3", perDimension: {}, reasons: ["clear", { composition: "B" }] }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  { name: "a fault object holding 'B' is a possible loss (QG-V2)", verdicts: [{ criticId: "k3", perDimension: {}, faults: [{ panel: "B" }] }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  { name: "recognizedAs as an object holding 'B' is a possible loss (QG-V2)", verdicts: [{ criticId: "k3", perDimension: {}, recognizedAs: { composition: "B" } }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  { name: "an identifier field holding an object with 'B' is a possible loss (QG-V2)", verdicts: [{ criticId: "k3", perDimension: {}, criticModel: { pick: "B" } }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  { name: "a reason that is nothing but 'B' is a pick, so a possible loss (QG-V2)", verdicts: [{ criticId: "k3", perDimension: {}, reasons: ["B"] }, {}, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k1", "k2"] } },
  {
    name: "a malformed field is read leaf by leaf: an 'A' there is no loss (but never a counted win) (QG-V2)",
    verdicts: [{ criticId: "k3", perDimension: {}, faults: { composition: "A" } }, {}, { criticId: "k2" }],
    want: { status: "PASS", counted: ["k1", "k2"] },
  },
  { name: "a reason that is not a string (null) makes the verdict invalid: never counted (QG-V2 typed schema)", verdicts: [{ reasons: ["clear", null] }, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k2"] } },
  { name: "a fault that is not a string (null) makes the verdict invalid: never counted (QG-V2 typed schema)", verdicts: [{ faults: [null] }, { criticId: "k2" }], want: { status: "UNPROVEN", counted: ["k2"] } },
  { name: "a well-formed reason beside a malformed one is not read as a pick: no loss, never counted (QG-V2 precision)", verdicts: [{ criticId: "k3", reasons: ["clear", null] }, {}, { criticId: "k2" }], want: { status: "PASS", counted: ["k1", "k2"] } },
  /* QG-V4: the recognized:false + recognizedAs shape rule, pinned where the vocabulary cannot catch it. */
  {
    name: "recognized:false with a recognizedAs naming something outside the vocabulary ('Kibana') is invalid: never counted (QG-V4)",
    verdicts: [{ recognized: false, recognizedAs: "Kibana in B" }, { criticId: "k2" }],
    want: { status: "UNPROVEN", counted: ["k2"] },
  },
];
export const VERDICT_FIELDS = ["sheetSha", "oursSha", "refSha", "commit", "criticId", "criticModel", "recognized", "recognizedAs", "perDimension", "reasons", "faults"];

/* Default-ignorable code points (zero-width space/joiners, BOM, soft hyphen, variation selectors…):
   invisible, so they never make a new critic or a new answer. */
const stripInvisible = (s) => s.normalize("NFKC").replace(/\p{Default_Ignorable_Code_Point}/gu, "");
const nonBlank = (s) => typeof s === "string" && stripInvisible(s).trim() !== "";

export function verdictShapeProblems(v) {
  const p = [];
  if (!v || typeof v !== "object" || Array.isArray(v)) return ["not an object"];
  for (const f of VERDICT_FIELDS) if (!(f in v)) p.push(`missing ${f}`);
  for (const f of ["sheetSha", "oursSha", "refSha", "commit", "criticId", "criticModel"]) if (f in v && (typeof v[f] !== "string" || !v[f])) p.push(`${f} must be a non-empty string`);
  if ("recognized" in v && typeof v.recognized !== "boolean") p.push("recognized must be a boolean");
  if ("recognizedAs" in v && v.recognizedAs !== null && typeof v.recognizedAs !== "string") p.push("recognizedAs must be a string or null");
  /* A recognition must name what it recognised, and a non-recognition must name nothing: either
     mismatch is an inconsistent verdict (R2-7, R2-3). Blank-by-invisibles is blank. */
  if (v.recognized === true && !nonBlank(v.recognizedAs)) p.push("recognized without recognizedAs (a recognition that names nothing)");
  if (v.recognized === false && nonBlank(v.recognizedAs)) p.push("recognized is false but recognizedAs names something");
  if ("perDimension" in v && (typeof v.perDimension !== "object" || v.perDimension === null || Array.isArray(v.perDimension))) p.push("perDimension must be an object");
  if ("reasons" in v && (!Array.isArray(v.reasons) || !v.reasons.some((r) => typeof r === "string" && r.trim()))) p.push("reasons must hold at least one non-empty string");
  if ("faults" in v && !Array.isArray(v.faults)) p.push("faults must be an array");
  /* Each reason and each fault is a string: a non-string element is a shape the validator cannot
     interpret (its leaves are read as possible picks, QG-V2). */
  for (const f of ["reasons", "faults"]) if (Array.isArray(v[f]) && v[f].some((r) => typeof r !== "string")) p.push(`every element of ${f} must be a string`);
  /* The schema is CLOSED: a field outside it is a shape the validator cannot interpret, so the line
     never counts (and pickValues reads its value as a possible pick: R2-1). */
  const extra = Object.keys(v).filter((k) => !VERDICT_FIELDS.includes(k));
  if (extra.length) p.push(`fields outside the verdict schema: ${extra.map((k) => JSON.stringify(k)).join(", ")}`);
  return p;
}

/** A critic's identity for the one-verdict rule: case, spacing, Unicode form and invisible characters
    do not make a new critic ("k1", " K1 " and "k1<ZWSP>" are one critic). The id must then be plain
    ASCII (letters, digits, '.', '_', '-'), so a homoglyph ("к1", Cyrillic) is not a second critic: a
    line whose id is not of that form is UNATTRIBUTABLE (null) — never counted, and its loss still
    blocks (verifier V6). */
export const CRITIC_ID_FORM = /^[a-z0-9][a-z0-9._-]*$/;
export const criticKey = (id) => {
  if (typeof id !== "string") return null;
  const k = stripInvisible(id).trim().toLowerCase().replace(/\s+/g, "-");
  return CRITIC_ID_FORM.test(k) ? k : null;
};
/** ONE value's pick, in the critic's A/B terms mapped through the sheet's side: "ours" | "reference" |
    "tie"; null when the value is absent; "unreadable" when it is not A, B or tie after case, spacing
    and Unicode normalisation ("b" and " B " are B; "reference", "panel A", an object or an array are
    unreadable), and also when it is A or B on a line whose side is UNKNOWN (`sideA` null: a line bound
    to its pairing only by its frames, R2-2). An unreadable value is never read as a win: it fails
    closed as a possible loss (verifier V3). */
export function pickOf(raw, sideA) {
  if (raw === undefined || raw === null) return null;
  if (typeof raw !== "string") return "unreadable";
  const s = stripInvisible(raw).trim().toLowerCase();
  if (s === "tie") return "tie";
  if (s !== "a" && s !== "b") return "unreadable";
  if (sideA !== "ours" && sideA !== "reference") return "unreadable";
  if (s === "a") return sideA;
  return sideA === "ours" ? "reference" : "ours";
}
const isLoss = (pick) => pick === "reference" || pick === "unreadable";
/* A key's form for "is this answer filed under the sheet's dimension": case, Unicode form, invisible
   characters and separators do not matter ("Colour-Discipline", "colour_discipline"). No spelling is
   aliased: "color-discipline" is ANOTHER key, so its win never counts and its loss still blocks. */
const keyForm = (k) => stripInvisible(String(k)).toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
const carries = (x) =>
  !(x === undefined || x === null || (typeof x === "string" && !nonBlank(x)) || (Array.isArray(x) && !x.length) || (typeof x === "object" && !Array.isArray(x) && !Object.keys(x).length));

/** The TYPE each schema field other than perDimension must have (verdictShapeProblems checks the same
    types, plus the consistency rules). A value of the wrong type is a shape the validator cannot
    interpret, so it may hold a pick (QG-V2). */
const FIELD_TYPE_OK = {
  sheetSha: (x) => typeof x === "string",
  oursSha: (x) => typeof x === "string",
  refSha: (x) => typeof x === "string",
  commit: (x) => typeof x === "string",
  criticId: (x) => typeof x === "string",
  criticModel: (x) => typeof x === "string",
  recognized: (x) => typeof x === "boolean",
  recognizedAs: (x) => x === null || typeof x === "string",
  reasons: (x) => Array.isArray(x) && x.every((r) => typeof r === "string"),
  faults: (x) => Array.isArray(x) && x.every((r) => typeof r === "string"),
};
/** Every carrying LEAF of a value (objects and arrays recursed; a leaf past a depth of 16 is the
    remaining value itself), each with where it was found. */
function leavesOf(x, where, depth = 0, out = []) {
  if (!carries(x)) return out;
  if (typeof x === "object" && depth < 16) {
    for (const [k, y] of Array.isArray(x) ? x.entries() : Object.entries(x)) leavesOf(y, `${where}${Array.isArray(x) ? `[${k}]` : `.${k}`}`, depth + 1, out);
    return out;
  }
  out.push({ where, raw: x });
  return out;
}
/** A string that normalises to nothing but a pick token ("B", " b ", "tie"). */
const isPickToken = (x) => typeof x === "string" && ["a", "b", "tie"].includes(stripInvisible(x).trim().toLowerCase());
/** EVERY pick-bearing value on a line (R2-1, closed by class in W5 round 2: QG-V2). Each sheet asks
    exactly one question, so any answer on the line answers it:
    - every value in perDimension under ANY key (`filed` = under the sheet's dimension), and a
      perDimension that is not an object (a bare "B" is an answer, not "no answer");
    - every carrying LEAF of a field outside the verdict schema, and of a SCHEMA field whose type the
      schema rejects (faults as an object keyed by the dimension, recognized: "B", reasons: "B", a
      non-string reason or fault): a shape the validator cannot interpret may hold a pick, so it is
      read, leaf by leaf, and a leaf that is not A, B or tie is unreadable — a possible loss;
    - a reason or fault that is nothing but a pick token (reasons: ["B"]): a pick written in the wrong
      place is still a pick.
    None of these is ever `filed`, so none counts as a win. */
export function pickValues(v, dimension) {
  const out = [];
  const pd = v?.perDimension;
  if (pd !== undefined && pd !== null) {
    if (typeof pd === "object" && !Array.isArray(pd)) for (const [k, raw] of Object.entries(pd)) out.push({ where: `perDimension[${JSON.stringify(k)}]`, raw, filed: keyForm(k) === keyForm(dimension) });
    else out.push({ where: "perDimension itself", raw: pd, filed: false });
  }
  for (const k of Object.keys(v ?? {})) {
    if (k === "perDimension") continue;
    const typed = FIELD_TYPE_OK[k];
    const list = (k === "reasons" || k === "faults") && Array.isArray(v[k]);
    if (list) {
      /* In a reasons or faults ARRAY only the non-string elements are the uninterpretable shape; its
         string elements are reasons, read as picks only when they are nothing but a pick. */
      v[k].forEach((r, i) => {
        if (typeof r !== "string") for (const leaf of leavesOf(r, `field ${JSON.stringify(k)}[${i}]`)) out.push({ ...leaf, filed: false });
        else if (isPickToken(r)) out.push({ where: `${k}[${i}]`, raw: r, filed: false });
      });
    } else if (!typed || !typed(v[k])) for (const leaf of leavesOf(v[k], `field ${JSON.stringify(k)}`)) out.push({ ...leaf, filed: false });
  }
  return out;
}
/** The line's pick for a pairing's dimension, read from every pick-bearing value: { pick, problem }.
    pick: null (no value at all), "ours" | "reference" | "tie" (one agreed answer), "unreadable" (a
    possible loss: an unreadable value, or values that disagree where one may pick the reference), or
    "conflicting" (ours and tie both given: no loss, but no single answer). `problem` is set whenever
    the line's answer cannot be counted as it stands — including a readable answer filed outside
    perDimension[dimension], which never counts as a win but is still read as a loss. */
export function linePick(v, dimension, sideA) {
  const vals = pickValues(v, dimension)
    .map((x) => ({ ...x, pick: pickOf(x.raw, sideA) }))
    .filter((x) => x.pick !== null);
  if (!vals.length) return { pick: null, problem: `no answer: perDimension["${dimension}"] must be A, B or tie` };
  const picks = new Set(vals.map((x) => x.pick));
  const pick = picks.size === 1 ? vals[0].pick : picks.has("reference") || picks.has("unreadable") ? "unreadable" : "conflicting";
  const shown = (xs) => xs.map((x) => `${x.where} = ${JSON.stringify(x.raw)?.slice(0, 40)}`).join(", ");
  const problems = [];
  const foreign = vals.filter((x) => !x.filed);
  if (foreign.length) problems.push(`an answer filed outside perDimension["${dimension}"] (${shown(foreign)}): a win filed elsewhere never counts; a loss filed elsewhere is still a loss`);
  if (pick === "unreadable") problems.push(`the answer (${shown(vals)}) is not one A, B or tie${sideA === "ours" || sideA === "reference" ? "" : " on a sheet whose side is known"} (an unreadable pick is never read as a win)`);
  if (pick === "conflicting") problems.push(`the line gives more than one answer (${shown(vals)})`);
  return { pick, problem: problems.length ? problems.join("; ") : null };
}

/* ── Binding a line to a sheet (R2-2): ONE resolver, tolerant of form, for current and earlier sheets ── */
const refForm = (s) =>
  typeof s === "string"
    ? stripInvisible(s)
        .trim()
        .toLowerCase()
        .replace(/^.*[\\/]/, "")
        .replace(/\.png$/, "")
        .replace(/^sheet-/, "")
    : "";
/** Resolve a line's sheet reference against sheet entries ({sheetSha, sheetName, …}): the full sha, the
    sheet's file name (with or without a path or ".png"), or a unique hex prefix of at least 8
    characters, after Unicode form, invisible characters, case and surrounding space are normalised.
    { status: "bound", entry, by } | { status: "ambiguous" } | { status: "none" }. */
export function resolveSheet(ref, entries) {
  const r = refForm(ref);
  if (!r) return { status: "none" };
  const exact = entries.filter((s) => refForm(s.sheetSha) === r || (s.sheetName && refForm(s.sheetName) === r));
  if (exact.length === 1) return { status: "bound", entry: exact[0], by: ref === exact[0].sheetSha ? "exact" : "tolerant" };
  if (exact.length > 1) return { status: "ambiguous" };
  if (/^[0-9a-f]{8,}$/.test(r)) {
    const pre = entries.filter((s) => refForm(s.sheetSha).startsWith(r));
    if (pre.length === 1) return { status: "bound", entry: pre[0], by: "prefix" };
    if (pre.length > 1) return { status: "ambiguous" };
  }
  return { status: "none" };
}
/** The sheets every earlier build's KEY lists (blind/_superseded/<stamp>/KEY.json): the only sheets a
    line may be STALE on. */
export function supersededSheets(dir = resolve(OUT, "_superseded")) {
  const out = [];
  if (!existsSync(dir)) return out;
  for (const d of readdirSync(dir)) {
    try {
      const k = JSON.parse(readFileSync(resolve(dir, d, "KEY.json"), "utf8"));
      for (const p of k.pairings ?? []) for (const s of p.sheets ?? []) if (typeof s.sheetSha === "string") out.push({ sheetSha: s.sheetSha, sheetName: s.sheetName ?? null, from: d });
    } catch {
      /* a stamp directory without a readable KEY lists no sheets: its lines are unbound, never stale */
    }
  }
  return out;
}

/* ── Recognition from what a verdict SAYS, not only its flag (R2-3) ── */
const wordsOf = (s) =>
  stripInvisible(String(s))
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
/** The recognition vocabulary: every identity string the KEY masked (identityMasked: the reference
    products' names, vendors, users and workspaces, and ours) and every reference product REFERENCES.md
    lists (REFERENCE_PRODUCTS, passed in as `referenceProducts`, or the KEY's copy). */
export function recognitionVocabulary(key, opts = {}) {
  const products = opts.referenceProducts ?? key?.referenceProducts ?? [];
  return [...new Set([...(Array.isArray(key?.identityMasked) ? key.identityMasked : []), ...products].filter((s) => typeof s === "string" && wordsOf(s).length))];
}
/** The vocabulary entries a text NAMES, as whole words: an entry matches a run of whole words whose
    letters, joined, are exactly the entry's ("IPFabric" and "IP Fabric" are one name; "Grafana's" names
    Grafana; "forwarding" does not name Forward). */
export function namedIn(text, vocab) {
  const t = wordsOf(text);
  const hits = [];
  for (const ph of vocab) {
    const joined = wordsOf(ph).join("");
    if (!joined) continue;
    let hit = false;
    for (let i = 0; i < t.length && !hit; i++) {
      let acc = "";
      for (let k = i; k < t.length && acc.length < joined.length; k++) {
        acc += t[k];
        if (acc === joined) hit = true;
      }
    }
    if (hit) hits.push(ph);
  }
  return hits;
}
const textOf = (x) => (typeof x === "string" ? x : x === undefined || x === null ? "" : JSON.stringify(x));
/** The vocabulary a line names in anything a critic wrote: recognizedAs, every reason, every fault and
    every field outside the schema. */
export function namesOnLine(v, vocab) {
  const parts = [
    textOf(v?.recognizedAs),
    ...(Array.isArray(v?.reasons) ? v.reasons.map(textOf) : [textOf(v?.reasons)]),
    ...(Array.isArray(v?.faults) ? v.faults.map(textOf) : [textOf(v?.faults)]),
    ...Object.keys(v ?? {})
      .filter((k) => !VERDICT_FIELDS.includes(k))
      .map((k) => textOf(v[k])),
  ];
  return [...new Set(parts.flatMap((p) => namedIn(p, vocab)))];
}

/** Evaluate verdicts against a KEY under RULE. Pure: no I/O. `opts.superseded` lists the sheets of
    earlier builds' KEYs (supersededSheets()); `opts.referenceProducts` the products REFERENCES.md
    lists (REFERENCE_PRODUCTS). */
export function evaluate(key, verdicts, opts = {}) {
  const out = [];
  const current = key.pairings.flatMap((p) => (p.sheets ?? []).map((s) => ({ sheetSha: s.sheetSha, sheetName: s.sheetName, pairing: p, sheet: s })));
  const superseded = (opts.superseded ?? []).map((s) => (typeof s === "string" ? { sheetSha: s } : s)).filter((s) => s && typeof s.sheetSha === "string");
  const vocab = recognitionVocabulary(key, opts);
  const isLine = (v) => Boolean(v) && typeof v === "object" && !Array.isArray(v) && !("unparseable" in v);
  const unparseable = verdicts.filter((v) => !isLine(v)).length;
  const shaForm = (s) => (typeof s === "string" ? stripInvisible(s).trim().toLowerCase() : null);
  let stale = 0;
  const unbound = [];
  /* Every line is bound through ONE resolver (R2-2): to a current sheet (its pairing, its side), or to
     an earlier build's sheet (STALE), or it is UNBOUND — which blocks C1 — and it also belongs, with its
     side unknown, to EVERY pairing it can be tied to: the one pairing its frame shas name, and every
     pairing whose dimension it files an answer under (one pairing per dimension, so the key names the
     pairing; QG-V5). There it is an invalid verdict whose A or B is a possible loss, and it uses up that
     critic's first line, so a re-ask never counts. */
  const bound = verdicts.map((v, i) => {
    if (!isLine(v)) return null;
    const r = resolveSheet(v.sheetSha, current);
    if (r.status === "bound") return { pairings: [r.entry.pairing], sheet: r.entry.sheet, by: r.by, why: null };
    if (r.status === "none" && resolveSheet(v.sheetSha, superseded).status === "bound") {
      stale++;
      return null;
    }
    const ref = JSON.stringify(String(v.sheetSha ?? "").slice(0, 80));
    const why = r.status === "ambiguous" ? `its sheet reference ${ref} matches more than one current sheet` : `its sheet reference ${ref} names no current sheet and no sheet an earlier build's KEY lists`;
    const byFrames = key.pairings.filter((p) => shaForm(v.oursSha) && shaForm(v.oursSha) === shaForm(p.ours?.sha256) && shaForm(v.refSha) === shaForm(p.ref?.sha256));
    const filedKeys = v.perDimension && typeof v.perDimension === "object" && !Array.isArray(v.perDimension) ? Object.keys(v.perDimension).map(keyForm) : [];
    const byDimension = key.pairings.filter((p) => filedKeys.includes(keyForm(p.dimension)));
    const tied = [...new Set([...(byFrames.length === 1 ? byFrames : []), ...byDimension])];
    unbound.push({ line: i + 1, criticId: typeof v.criticId === "string" ? v.criticId.slice(0, 40) : null, why, pairing: tied.length ? tied.map((p) => p.id).join(", ") : null });
    return tied.length ? { pairings: tied, sheet: null, by: byFrames.length === 1 ? "frames" : "dimension", why } : null;
  });
  for (const p of key.pairings) {
    const res = { id: p.id, dimension: p.dimension, status: "UNPROVEN", counted: [], recognized: [], invalid: [], duplicates: [], uncountedLosses: [], laterLosses: [], why: "" };
    if (p.blocked) {
      res.why = `no sheet was emitted: ${p.blocked}`;
      out.push(res);
      continue;
    }
    /* RULE v6. The lines that belong to P, each attributed to a NORMALISED critic id (null =
       unattributable), read to a pick from every pick-bearing shape, and screened for any product it
       names. */
    const lines = [];
    verdicts.forEach((v, i) => {
      const b = bound[i];
      if (!b || !b.pairings.includes(p)) return;
      lines.push({ v, b, ...linePick(v, p.dimension, b.sheet?.A ?? null), cid: criticKey(v.criticId), named: namesOnLine(v, vocab) });
    });
    const discloses = (l) => l.v.recognized === true || l.named.length > 0;
    const disclosure = (l) => [...(l.v.recognized === true ? [`recognized: ${JSON.stringify(l.v.recognizedAs ?? null)}`] : []), ...(l.named.length ? [`names ${l.named.map((n) => JSON.stringify(n)).join(", ")}`] : [])].join("; ");
    const unboundProblem = (l) => (l.b.sheet ? [] : [`${l.b.why}: bound to this pairing only by its frame shas or the dimension it files under, so its side is unknown`]);
    /* RECOGNITION DROPS A WIN BUT NEVER ERASES A LOSS (requirement 3, W5 round 2). Any disclosure — the
       flag, on any line (first or later), or a product or identity string NAMED in recognizedAs, reasons,
       faults or an extra field whatever the flag says (R2-3) — excludes the critic from COUNTING, and
       every loss on its record stands. There is no longer a "valid first-line recognition" that sets a
       loss aside: that exception was decided against a vocabulary holding ordinary words ("Sign in",
       "Forward"), so a critic writing recognizedAs "a Sign in form" erased its own loss (QG-V1). */
    const disclosedBy = new Map();
    for (const l of lines) if (l.cid !== null && discloses(l) && !disclosedBy.has(l.cid)) disclosedBy.set(l.cid, l);
    const seen = new Set();
    for (const l of lines) {
      const { v, pick, problem: pickProblem, cid } = l;
      /* An unattributable line cannot be tied to a critic, so neither the one-verdict rule nor a
         recognition exclusion can apply to it: it never counts, and if it may pick the reference it is
         a loss (verifier V7). */
      if (cid === null) {
        const problems = [
          ...new Set([
            "unattributable: no critic id of the form " + CRITIC_ID_FORM,
            ...(discloses(l) ? [`discloses recognition (${disclosure(l)}), but cannot be tied to a critic to exclude`] : []),
            ...verdictShapeProblems(v),
            ...unboundProblem(l),
            ...(pickProblem ? [pickProblem] : []),
          ]),
        ];
        res.invalid.push({ criticId: null, rawCriticId: typeof v.criticId === "string" ? v.criticId.slice(0, 40) : null, problems });
        if (isLoss(pick)) res.uncountedLosses.push({ criticId: null, problems });
        continue;
      }
      const first = !seen.has(cid);
      seen.add(cid);
      /* A critic's FIRST line is its only verdict for P; a later line never counts, but a later line
         that may pick the reference is still a loss (a win cannot be re-asked away into a loss's
         absence, nor a loss into a win). */
      if (!first) {
        res.duplicates.push(cid);
        if (isLoss(pick)) res.laterLosses.push({ criticId: cid });
        continue;
      }
      const problems = [...verdictShapeProblems(v), ...unboundProblem(l)];
      if (v.oursSha !== p.ours?.sha256) problems.push("oursSha differs from the KEY");
      if (v.refSha !== p.ref?.sha256) problems.push("refSha differs from the KEY");
      if (v.commit !== key.commit) problems.push("commit differs from the KEY");
      if (pickProblem) problems.push(pickProblem);
      const d = disclosedBy.get(cid);
      if (d) res.recognized.push({ criticId: cid, criticModel: v.criticModel ?? null, recognizedAs: d.v.recognizedAs ?? null, named: d.named, disclosed: `${d === l ? "its first line" : "a later line"} (${disclosure(d)})` });
      if (problems.length) {
        res.invalid.push({ criticId: cid, problems: [...new Set(problems)] });
        if (isLoss(pick)) res.uncountedLosses.push({ criticId: cid, problems: [...new Set(problems)] });
        continue;
      }
      if (d) {
        if (isLoss(pick)) res.uncountedLosses.push({ criticId: cid, problems: ["a loss from a critic who disclosed recognition: recognition never erases a loss"] });
        continue;
      }
      res.counted.push({ criticId: cid, criticModel: v.criticModel, pick, boundBy: l.b.by, reasons: v.reasons, faults: v.faults });
    }
    const losses = res.counted.filter((c) => c.pick === "reference");
    if (losses.length) res.why = `${losses.length} counted verdict(s) pick the reference — work items: ${losses.flatMap((l) => l.reasons).slice(0, 3).join(" | ")}`;
    else if (res.uncountedLosses.length) res.why = `${res.uncountedLosses.length} uncounted verdict(s) may pick the reference (invalid, unattributable, unbound or recognising: a loss is never ignored)`;
    else if (res.laterLosses.length) res.why = `${res.laterLosses.length} later line(s) from critics already heard pick the reference (a loss is never ignored)`;
    else if (res.counted.length >= 2) {
      res.status = "PASS";
      res.why = `${res.counted.length} counted verdicts, none picks the reference`;
    } else res.why = `${res.counted.length} counted verdict(s); the rule needs 2 unrecognising critics`;
    out.push(res);
  }
  const overall = !unparseable && !unbound.length && vocab.length > 0 && out.length === key.pairings.length && out.every((r) => r.status === "PASS") ? "PASS" : "UNPROVEN";
  return { overall, pairings: out, stale, unparseable, unbound: unbound.length, unboundLines: unbound, recognitionVocabulary: vocab.length };
}

export function printEvaluation(ev) {
  console.log(`C1 verdicts under the pre-registered rule (ruleSha ${RULE_SHA.slice(0, 12)}):`);
  for (const r of ev.pairings) {
    console.log(`  ${r.status.padEnd(8)} ${r.id} [${r.dimension}] — ${r.why}`);
    if (r.recognized.length) console.log(`           excluded (recognised): ${r.recognized.map((x) => `${x.criticId} saw "${x.recognizedAs ?? ""}"${x.named?.length ? ` / named ${x.named.join(", ")}` : ""} (${x.disclosed})`).join("; ")}`);
    if (r.invalid.length) console.log(`           invalid: ${r.invalid.map((x) => `${x.criticId ?? "?"}: ${x.problems.join(", ")}`).join("; ")}`);
    if (r.uncountedLosses?.length) console.log(`           uncounted losses (not counted, but may pick the reference): ${r.uncountedLosses.map((x) => x.criticId ?? "?").join(", ")}`);
    if (r.laterLosses?.length) console.log(`           later lines picking the reference (a loss is never ignored): ${r.laterLosses.map((x) => x.criticId ?? "?").join(", ")}`);
    if (r.duplicates.length) console.log(`           later lines from a critic already heard for this pairing (never count): ${r.duplicates.join(", ")}`);
  }
  if (ev.stale) console.log(`  (${ev.stale} verdict(s) are against sheets an earlier build's KEY lists: stale, not counted)`);
  if (ev.unbound) console.log(`  INVALID: ${ev.unbound} verdict line(s) name no current or earlier sheet — C1 cannot be PASS while they stand: ${ev.unboundLines.map((u) => `line ${u.line}${u.pairing ? ` (tied to ${u.pairing} by its frames or its dimension)` : " (tied to no pairing)"}: ${u.why}`).join("; ")}`);
  if (ev.unparseable) console.log(`  INVALID: ${ev.unparseable} verdict line(s) are unparseable and cannot be attributed — C1 cannot be PASS while they stand`);
  if (!ev.recognitionVocabulary) console.log("  INVALID: no recognition vocabulary (the KEY's identityMasked and REFERENCES.md's products are both empty) — recognition cannot be screened, so C1 cannot be PASS");
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
/** The padding every mask gets (capture-refs-clean.mjs reproduces a sheet's masks with it). */
export const MASK_PAD = PAD;
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

/* ── OUR identity, by DOM geometry (phase 3.5) ────────────────────────────────────────────────
   OCR cannot be the proof that our identity is masked: on the 1x IP Fabric sheet it read neither
   "collect_parse_snapshot/1" nor the 8-hex snapshot tag, so no mask was painted AND the post-mask leak check
   (the same OCR) passed, while a person could read both. The fix is the class, not a longer phrase
   list: OUR frame is our own page, so its identity marks are measured in its DOM — every visible
   element whose text holds an identity string, widened to the compact block it sits in (the brand
   <p> with its glyph, the whole two-line snapshot button), or only the phrase's own box when it sits
   in prose. Those rectangles are masked on BOTH panels, and the measurement is checked against the
   pixels: an OCR identity hit on our frame outside every measured rectangle means the geometry does
   not describe this frame (or missed a mark), and the pairing is BLOCKED. */
export const IDENTITY_BLOCK_MAX = { h: 64, wFrac: 0.34 };
/** Runs in the page. Rectangles (CSS px, viewport coordinates) of every visible identity mark. */
export function identityCensus({ identity, maxH, maxWFrac }) {
  /* Whole words only, so a brand word never matches inside a product word ("forward" in "forwarding"). */
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const needles = identity.map((s) => String(s).toLowerCase()).filter((s) => s.length >= 3);
  const reOf = (s) => new RegExp(`(?<![a-z0-9])${esc(s)}(?![a-z0-9])`, "g");
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return false;
    for (let a = el; a; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) < 0.05) return false;
    }
    return true;
  };
  const compact = (r) => r.height <= maxH && r.width <= innerWidth * maxWFrac;
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = (n.textContent || "").toLowerCase();
    const which = needles.filter((s) => reOf(s).test(text));
    const el = n.parentElement;
    if (!which.length || !vis(el)) continue;
    if (compact(el.getBoundingClientRect())) {
      let best = el;
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        const ar = a.getBoundingClientRect();
        /* A box-less wrapper (display: contents — our header's popover trigger) has a 0x0 rect: it is
           passed through, never taken as the block (the first measurement masked nothing that way). */
        if (ar.width === 0 && ar.height === 0) continue;
        if (!compact(ar)) break;
        best = a;
      }
      const r = best.getBoundingClientRect();
      out.push({ x: r.x, y: r.y, w: r.width, h: r.height, why: `identity block (${which.join(", ")})` });
    } else {
      for (const s of which)
        for (const m of text.matchAll(reOf(s))) {
          const range = document.createRange();
          range.setStart(n, m.index);
          range.setEnd(n, m.index + s.length);
          for (const r of range.getClientRects()) out.push({ x: r.x, y: r.y, w: r.width, h: r.height, why: `identity phrase in prose (${s})` });
        }
    }
  }
  return out.filter((r) => r.w >= 1 && r.h >= 1).map((r) => ({ ...r, x: Math.round(r.x * 10) / 10, y: Math.round(r.y * 10) / 10, w: Math.round(r.w * 10) / 10, h: Math.round(r.h * 10) / 10 }));
}
/** The measurement's own identity — the census AND the procedure that decides when the page is
    measured (a settled page, repair round): a cached measurement made by another version of either is
    re-measured. (Function declarations are hoisted, so their sources are readable here.) */
export const CENSUS_SHA = sha256(Buffer.from([identityCensus, measureOursIdentity, awaitSettledPage, derivedSettle].map((f) => f.toString()).join("\n"))).slice(0, 16);
/** OCR identity hits (CSS px) whose centre lies in no DOM rectangle (grown by `tol`). */
export function identityOutsideDom(hits, rects, tol = 6) {
  return hits.filter((b) => {
    const cx = b.x + b.w / 2;
    const cy = b.y + b.h / 2;
    return !rects.some((r) => cx >= r.x - tol && cx <= r.x + r.w + tol && cy >= r.y - tol && cy <= r.y + r.h + tol);
  });
}
/** DOM identity rectangles as masks in crop coordinates (padded like every other mask). */
export const oursIdentityMasks = (rects, origin) => rects.map((r) => ({ x: r.x - origin.x - PAD, y: r.y - origin.y - PAD, w: r.w + 2 * PAD, h: r.h + 2 * PAD, why: r.why ?? "our identity (DOM)" }));
/** The geometric masks a sheet starts from, in crop coordinates: the reference's identity slots and
    OUR DOM-measured identity marks. OCR boxes are added on top of these, never instead of them. */
export const initialMasks = (refSlots, oursRects, crop) => [
  ...refSlots.map((r) => ({ x: r.x - crop.refOrigin.x - PAD, y: r.y - crop.refOrigin.y - PAD, w: r.w + 2 * PAD, h: r.h + 2 * PAD, why: r.why })),
  ...oursIdentityMasks(oursRects, crop.oursOrigin),
];
/** Why our frame's identity geometry cannot be used (a BLOCK reason), or null: unmeasured, or it does
    not describe the frame's pixels (an identity string OCR reads outside every measured rectangle). */
export function oursGeometryProblem(geo, oursOcr, ourId, ours, lib) {
  if (!geo?.rects?.length) return `our identity geometry for ${ours.id} is unmeasured (${geo?.error ?? "no measurement"}); run node review/blind-pair.mjs --capture-ours with the build served`;
  if (!oursOcr?.ok) return `our frame ${ours.id} could not be read to check its identity geometry (${oursOcr?.error ?? "no OCR"})`;
  const stray = identityOutsideDom(identityHits(oursOcr, ourId, ours.dpr ?? 1, lib), geo.rects);
  if (stray.length) return `our DOM identity geometry does not describe ${ours.id}'s pixels: identity legible outside every measured rectangle (${stray.map((s) => `"${s.why}" at ${Math.round(s.x)},${Math.round(s.y)}`).join("; ")})`;
  return null;
}
/** Tight OCR word boxes (CSS px) of every identity phrase — no chip or glyph widening. */
export function identityHits(ocr, phrases, dpr, { tokens, findPhrase }) {
  const out = [];
  if (!ocr?.ok) return out;
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
    for (const ph of phrases)
      for (const [a, b] of findPhrase(toks, ph)) {
        const ws = [...new Set(owner.slice(a, b))].map((i) => words[i]);
        const x0 = Math.min(...ws.map((w) => w.x));
        const y0 = Math.min(...ws.map((w) => w.y));
        out.push({ x: x0 / dpr, y: y0 / dpr, w: (Math.max(...ws.map((w) => w.x + w.w)) - x0) / dpr, h: (Math.max(...ws.map((w) => w.y + w.h)) - y0) / dpr, why: ph });
      }
  }
  return out;
}
const IDENTITY_CONTROL_PAGE = `<!doctype html><html><head><style>body{margin:0;font:14px system-ui}header{display:flex;align-items:center;gap:16px;height:56px;padding:0 12px;border-bottom:1px solid #ccc}
.brand{display:flex;gap:8px;align-items:center;margin:0}.snap{display:flex;flex-direction:column;border:0;background:none;text-align:left}.l2{font-size:12px}</style></head><body>
<header><p class="brand"><span class="mark"><svg width="18" height="18"><circle cx="9" cy="9" r="6"/></svg></span><span>Scope Product</span></p>
<span class="pop" style="display:contents"><button class="snap"><span class="l1"><span>fleet.snapshot.json</span></span><span class="l2"><span>schema/1</span> · <code>ab12cd34</code> · collected 2026-01-01</span></button></span>
<input style="width:900px" placeholder="search"></header>
<main style="padding:12px"><p style="width:1400px">Everything below is read from the snapshot at data/fleet.snapshot.json. A long sentence of prose that is not an identity block at all.</p>
<div style="display:none">fleet.snapshot.json hidden</div><p><span>l3_forwarding</span> table, <code>forwarding</code> decisions</p></main></body></html>`;
/** Positive control for identityCensus on a synthetic page with the shape of our header. */
export async function identityCensusControl() {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1920, height: 400 } });
    await page.setContent(IDENTITY_CONTROL_PAGE);
    const rects = await page.evaluate(identityCensus, { identity: ["Scope Product", "fleet.snapshot.json", "schema/1", "ab12cd34", "Forward"], maxH: IDENTITY_BLOCK_MAX.h, maxWFrac: IDENTITY_BLOCK_MAX.wFrac });
    const geo = await page.evaluate(() => {
      const b = (s) => {
        const r = document.querySelector(s).getBoundingClientRect();
        return { x: r.x, y: r.y, w: r.width, h: r.height };
      };
      return { brand: b(".brand"), mark: b(".mark"), snap: b(".snap"), l2: b(".l2") };
    });
    const covers = (outer, inner) => outer.x <= inner.x + 0.5 && outer.y <= inner.y + 0.5 && outer.x + outer.w >= inner.x + inner.w - 0.5 && outer.y + outer.h >= inner.y + inner.h - 0.5;
    const glyph = rects.some((r) => covers(r, geo.mark) && covers(r, geo.brand));
    const block = rects.some((r) => covers(r, geo.snap) && covers(r, geo.l2));
    const prose = rects.filter((r) => /prose/.test(r.why));
    const proseOk = prose.length === 1 && prose[0].w < 300;
    const noHidden = rects.every((r) => r.y < 380);
    const wholeWords = rects.every((r) => !/forward/i.test(r.why));
    return { ok: glyph && block && proseOk && noHidden && wholeWords, glyph, block, proseOk, noHidden, wholeWords, n: rects.length };
  } finally {
    await browser.close();
  }
}

/* The DOM identity geometry of our frames, measured once per frame (keyed by the frame's sha256) while
   the server that produced it is up, and cached beside the frames. */
const geometryFile = () => resolve(OURS_SHOTS, "identity-geometry.json");
function readGeometryCache() {
  try {
    return JSON.parse(readFileSync(geometryFile(), "utf8"));
  } catch {
    return {};
  }
}
/** Measure our identity rectangles for each frame by loading its captured URL at its captured
    viewport and theme. Returns { [frameSha]: { url, rects } | { url, error } }. */
export async function measureOursIdentity(frames, identity) {
  const out = {};
  const browser = await chromium.launch();
  try {
    for (const f of frames) {
      const url = f.capture?.url;
      if (!url) {
        out[f.sha256] = { url: null, error: "no captured URL" };
        continue;
      }
      const ctx = await browser.newContext({ viewport: { width: f.css.w, height: f.css.h }, deviceScaleFactor: 1, colorScheme: f.theme });
      try {
        await ctx.addInitScript(() => {
          window.__atlasExposeScene = true;
        });
        const page = await ctx.newPage();
        await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
        await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), f.theme);
        await page.evaluate(() => document.fonts?.ready);
        /* The SETTLED page the frame was shot in (capture.mjs's own gate), never a moment of the load:
           a fixed wait measured a page still booting (repair round, dark/06). */
        const unsettled = [];
        await awaitSettledPage(page, unsettled, "before measuring");
        if (!unsettled.length) await awaitPaletteWarm(page).catch((e) => unsettled.push(String(e).slice(0, 120)));
        if (unsettled.length) {
          out[f.sha256] = { url, census: CENSUS_SHA, error: `the page did not reach the settled state its frame was shot in: ${unsettled.join("; ").slice(0, 200)}` };
          continue;
        }
        const rects = await page.evaluate(identityCensus, { identity, maxH: IDENTITY_BLOCK_MAX.h, maxWFrac: IDENTITY_BLOCK_MAX.wFrac });
        out[f.sha256] = rects.length ? { url, census: CENSUS_SHA, rects, measuredAt: new Date().toISOString() } : { url, census: CENSUS_SHA, error: "no identity mark found in the page's DOM" };
      } catch (e) {
        out[f.sha256] = { url, error: `could not load our page to measure it: ${String(e).slice(0, 140)}` };
      } finally {
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }
  return out;
}

/* ── Derived captures of OUR states (DERIVED_STATES) ──────────────────────────────────────────
   The gates are capture.mjs's own (review/capture.mjs :: readSettle, awaitSettledOnScreen, the tier
   and convergence checks), restated here because that file exports nothing; they are the gates a
   derived frame must pass, and the record lists which were run. capture.mjs's text-fidelity, overflow
   and scroll-edge audits ran on the BASE frame (its record must be clean) and are not repeated. */
const DERIVED_GPU_ARGS = ["--use-gl=angle", "--disable-gpu-rasterization", "--ignore-gpu-blocklist"];
const DERIVED_FREEZE_CSS = "*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;transition-duration:0s!important;transition-delay:0s!important;caret-color:transparent!important}";
const derivedRoot = () => resolve(OURS_SHOTS, "derived");
function derivedSettle() {
  const scene = window.__atlasScene;
  const stats = scene?.stats?.();
  const word = document.querySelector(".sb__converged")?.textContent ?? null;
  const warm = document.querySelector(".stage-warmup");
  const warmVisible = warm !== null && warm.getClientRects().length > 0;
  return {
    handle: Boolean(scene),
    converged: stats?.converged ?? null,
    quality: stats?.quality ?? null,
    frameRateBelowBar: stats ? stats.frameRateBelowBar === true : null,
    framesTimed: stats?.framesTimed ?? null,
    statusWord: word,
    warmupVisible: warmVisible,
    belowBarWords: [...document.querySelectorAll(".sb__reduced")].some((n) => /below frame-rate bar/.test(n.textContent ?? "")),
    ok: Boolean(scene) && stats?.converged === true && word === "settled" && !warmVisible,
  };
}
/** Poll the page until it is settled on screen (derivedSettle), bounded as capture.mjs bounds it: a
    120 s hard cap, or 15 s with no new frame while not converged. A failure is pushed onto `problems`. */
async function awaitSettledPage(page, problems, label) {
  const t0 = Date.now();
  let last = null;
  let lastAdvance = Date.now();
  for (;;) {
    const st = await page.evaluate(derivedSettle).catch(() => null);
    if (st?.ok) return st;
    if (st?.framesTimed !== last) {
      last = st?.framesTimed ?? null;
      lastAdvance = Date.now();
    }
    if (Date.now() - t0 > 120000 || (last !== null && st?.converged !== true && Date.now() - lastAdvance > 15000)) {
      problems.push(`${label}: not settled on screen (${JSON.stringify(st)})`);
      return st;
    }
    await page.waitForTimeout(100);
  }
}
/** Runs in the page: which disclosures are open (their non-generic classes), and the on-screen rects
    (CSS px, clipped by every scrolling/clipping ancestor and the viewport) of rows of the given classes. */
export function derivedDomFacts({ rowClasses }) {
  const open = [...document.querySelectorAll('.ui-disclosure[data-open="true"]')].flatMap((el) => [...el.classList].filter((c) => c !== "ui-disclosure"));
  const clip = (el) => {
    let r = el.getBoundingClientRect();
    let box = { x0: r.left, y0: r.top, x1: r.right, y1: r.bottom };
    for (let a = el.parentElement; a; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.display === "none" || cs.visibility === "hidden") return null;
      if (/(hidden|auto|scroll|clip)/.test(cs.overflowX + cs.overflowY)) {
        const ar = a.getBoundingClientRect();
        box = { x0: Math.max(box.x0, ar.left), y0: Math.max(box.y0, ar.top), x1: Math.min(box.x1, ar.right), y1: Math.min(box.y1, ar.bottom) };
      }
    }
    box = { x0: Math.max(box.x0, 0), y0: Math.max(box.y0, 0), x1: Math.min(box.x1, innerWidth), y1: Math.min(box.y1, innerHeight) };
    return box.x1 - box.x0 >= 1 && box.y1 - box.y0 >= 1 ? { x: box.x0, y: box.y0, w: box.x1 - box.x0, h: box.y1 - box.y0 } : null;
  };
  const rows = {};
  for (const c of rowClasses) rows[c] = [...document.getElementsByClassName(c)].map(clip).filter(Boolean);
  return { open: [...new Set(open)], rows };
}
/** Capture every DERIVED_STATES state in every theme and viewport its base was captured in (D5: the
    reference's own viewport as well as 1920x1080). Returns the records. */
export async function captureDerived() {
  const idx = JSON.parse(readFileSync(resolve(OURS_SHOTS, "app", "index.json"), "utf8"));
  const records = [];
  const browser = await chromium.launch({ args: DERIVED_GPU_ARGS });
  try {
    for (const d of DERIVED_STATES) {
      for (const base of idx.filter((e) => e.id === d.from && viewportCss(e.viewport))) {
        const problems = [];
        const theme = base.theme;
        const vp = String(base.viewport);
        const css = viewportCss(vp);
        const file = resolve(derivedRoot(), theme, vp, `${d.id}.png`);
        const baseFile = resolve(OURS_SHOTS, "app", theme, vp, `${d.from}.png`);
        const rec = { id: d.id, from: d.from, theme, viewport: vp, url: base.url, server: base.server ?? null, file: rel(file), baseSha: existsSync(baseFile) ? sha256(readFileSync(baseFile)) : null, gates: ["base record clean", "settled on screen", "tier high", "converged", "palette pre-warm terminal", "no frame-rate-bar words", "no console errors", "opened", "still settled after the shot"], problems };
        records.push(rec);
        if ((base.problems ?? []).length || !rec.baseSha) {
          problems.push(`the base capture ${theme}/${vp}/${d.from} is ${rec.baseSha ? "not clean" : "missing"}: nothing was derived`);
          continue;
        }
        const ctx = await browser.newContext({ viewport: { width: css.w, height: css.h }, deviceScaleFactor: 2, colorScheme: theme, reducedMotion: "no-preference" });
        await ctx.addInitScript(() => {
          window.__atlasExposeScene = true;
        });
        const page = await ctx.newPage();
        const consoleErrors = [];
        page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text().slice(0, 200)));
        page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 200)));
        try {
          await page.goto(base.url, { waitUntil: "networkidle", timeout: 60000 });
          await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
          await page.addStyleTag({ content: DERIVED_FREEZE_CSS });
          await page.evaluate(() => document.fonts?.ready);
          const settled = (label) => awaitSettledPage(page, problems, label);
          await settled("before opening");
          rec.paletteWarm = await awaitPaletteWarm(page).catch((e) => {
            problems.push(String(e).slice(0, 160));
            return null;
          });
          for (const sel of d.open) {
            const trig = page.locator(`${sel} > .ui-disclosure__trigger`).first();
            if (!(await trig.count())) {
              problems.push(`no "${sel}" disclosure on the page`);
              continue;
            }
            if ((await trig.getAttribute("aria-expanded")) !== "true") await trig.click();
            if ((await trig.getAttribute("aria-expanded")) !== "true") problems.push(`"${sel}" did not open`);
          }
          if (d.reveal) await page.locator(`.${d.reveal}`).first().scrollIntoViewIfNeeded({ timeout: 5000 }).catch((e) => problems.push(`could not reveal .${d.reveal}: ${String(e).slice(0, 120)}`));
          /* No focus ring from the click in the photograph: the state, not the interaction. */
          await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
          await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
          const st = await settled("after opening");
          if (st?.quality !== "high") problems.push(`rendered at quality tier ${JSON.stringify(st?.quality ?? null)}`);
          if (st?.converged !== true) problems.push(`scene not converged at shoot time (converged=${st?.converged ?? null})`);
          if (st?.frameRateBelowBar !== false || st?.belowBarWords !== false) problems.push(`frame-rate bar at shoot time: flag ${st?.frameRateBelowBar ?? null}, words drawn ${st?.belowBarWords ?? null}`);
          rec.render = st ? { quality: st.quality, converged: st.converged } : null;
          rec.dom = await page.evaluate(derivedDomFacts, { rowClasses: d.reveal ? [d.reveal] : [] });
          mkdirSync(dirname(file), { recursive: true });
          await page.screenshot({ path: file, animations: "disabled", scale: "device" });
          const after = await page.evaluate(derivedSettle).catch(() => null);
          if (!after?.ok) problems.push(`left the settled state during the shot (${JSON.stringify(after)})`);
          if (consoleErrors.length) problems.push(`console: ${consoleErrors.slice(0, 3).join(" | ")}`);
          rec.frameSha = sha256(readFileSync(file));
        } catch (e) {
          problems.push(`could not capture: ${String(e).slice(0, 200)}`);
        } finally {
          await ctx.close();
        }
      }
    }
  } finally {
    await browser.close();
  }
  mkdirSync(derivedRoot(), { recursive: true });
  writeFileSync(resolve(derivedRoot(), "index.json"), JSON.stringify(records, null, 1));
  return records;
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
/** The viewport id capture.mjs files a frame under: "1920" for its canonical 1920x1080, "WxH" for any
    other size (capture.mjs ATLAS_VIEWPORTS, D5). */
export const viewportId = (css) => (css && css.w === 1920 && css.h === 1080 ? "1920" : `${css?.w}x${css?.h}`);
export const viewportCss = (id) => {
  if (String(id) === "1920") return { w: 1920, h: 1080 };
  const m = /^(\d+)x(\d+)$/.exec(String(id));
  return m ? { w: Number(m[1]), h: Number(m[2]) } : null;
};
/** What --capture-ours asks capture.mjs for (D5): the states the pairings use (a derived state is
    captured from its base) and the viewports: 1920x1080 plus every paired reference's CSS size. */
export function oursCapturePlan(pairings, refFrames) {
  const states = [...new Set(pairings.map((p) => DERIVED_STATES.find((d) => d.id === p.ours)?.from ?? p.ours))];
  const sizes = pairings.map((p) => refFrames.find((f) => f.id === p.ref)?.css).filter((c) => c && Number.isInteger(c.w) && Number.isInteger(c.h));
  const viewports = [...new Set(["1920x1080", ...sizes.map((c) => `${c.w}x${c.h}`)])];
  return { states: states.join(","), viewports: viewports.join(",") };
}
/** OUR frame of a state, preferring the capture made at the reference's own CSS viewport (`want`) so the
    panel is the whole screen rather than a crop (D5), and falling back to the canonical 1920x1080
    capture (then cropped, with the truncation recorded in the KEY). */
function oursFrame(state, theme, want = null, root = OURS_SHOTS) {
  const ids = [...new Set([...(want ? [viewportId(want)] : []), "1920"])];
  for (const vp of ids) {
    const f = oursFrameAt(state, theme, vp, root);
    if (f) return f;
  }
  return null;
}
function oursFrameAt(state, theme, vp, root) {
  const derived = DERIVED_STATES.find((d) => d.id === state);
  if (derived) return derivedFrame(derived, theme, vp, root);
  const css = viewportCss(vp);
  const file = resolve(root, "app", theme, vp, `${state}.png`);
  if (!css || !existsSync(file)) return null;
  const buf = readFileSync(file);
  const dpr = buf.readUInt32BE(16) / css.w;
  let capture = null;
  try {
    const idx = JSON.parse(readFileSync(resolve(root, "app", "index.json"), "utf8"));
    const e = idx.find((x) => x.id === state && x.theme === theme && String(x.viewport) === vp);
    if (e) capture = { url: e.url, server: e.server, problems: e.problems ?? [], render: e.render ? { quality: e.render.quality, converged: e.render.converged } : null };
  } catch {
    capture = null;
  }
  return { id: `${theme}/${vp}/${state}`, viewport: vp, file: rel(file), sha256: sha256(buf), css: { w: css.w, h: Math.round(buf.readUInt32BE(20) / dpr) }, dpr, theme, capture };
}
/** The problems of a derived capture record against the files it describes (pure, R2-4): the record's
    own problems, plus a frame whose bytes are not the ones recorded, and a base capture that has been
    replaced (other bytes) or removed since the frame was derived from it. A record that names no frame
    sha or no base sha is unbound, and refused. */
export function derivedRecordProblems(r, { frameSha, baseSha, from }) {
  const problems = [...(r?.problems ?? [])];
  if (!r?.frameSha || r.frameSha !== frameSha) problems.push(r?.frameSha ? "the derived frame's bytes differ from its capture record" : "the derived capture record names no frame sha, so its frame is unbound");
  if (!r?.baseSha) problems.push(`the derived capture record names no base capture of ${from}, so it is unbound`);
  else if (!baseSha || baseSha !== r.baseSha) problems.push(`derived from a base capture of ${from} that has since been ${baseSha ? "replaced" : "removed"} (run --capture-ours)`);
  return problems;
}
/** A derived frame (DERIVED_STATES) with its capture record; its problems include every mismatch
    between the record and the files (derivedRecordProblems). */
function derivedFrame(d, theme, vp = "1920", root = OURS_SHOTS) {
  const css = viewportCss(vp);
  const file = resolve(root, "derived", theme, vp, `${d.id}.png`);
  if (!css || !existsSync(file)) return null;
  const buf = readFileSync(file);
  const dpr = buf.readUInt32BE(16) / css.w;
  let capture = null;
  try {
    const r = JSON.parse(readFileSync(resolve(root, "derived", "index.json"), "utf8")).find((x) => x.id === d.id && x.theme === theme && String(x.viewport ?? "1920") === vp);
    if (r) {
      const baseFile = resolve(root, "app", theme, vp, `${d.from}.png`);
      const problems = derivedRecordProblems(r, { frameSha: sha256(buf), baseSha: existsSync(baseFile) ? sha256(readFileSync(baseFile)) : null, from: d.from });
      capture = { url: r.url, server: r.server, problems, render: r.render ?? null, dom: r.dom ?? null, derivedFrom: d.from };
    }
  } catch {
    capture = null;
  }
  return { id: `${theme}/${vp}/${d.id}`, viewport: vp, file: rel(file), sha256: sha256(buf), css: { w: css.w, h: Math.round(buf.readUInt32BE(20) / dpr) }, dpr, theme, capture };
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
  const ourId = oursIdentity();
  const identity = [...new Set([...refIdentity, ...ourId])];
  const geometryCache = readGeometryCache();
  let geometryDirty = false;
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
      const entry = { id: p.id, dimension: p.dimension, task: p.task, taskSays: TASK_KINDS[p.task]?.says ?? null, question: QUESTIONS[p.dimension], note: p.note ?? null, sheets: [], slots: [] };
      pairings.push(entry);
      if (!ref || !existsSync(fromRel(ref.file))) {
        entry.blocked = `reference ${p.ref} is not in the set`;
        continue;
      }
      if (sha256(readFileSync(fromRel(ref.file))) !== ref.sha256) {
        entry.blocked = `reference ${p.ref} changed since capture`;
        continue;
      }
      const ours = oursFrame(p.ours, ref.theme, ref.css);
      if (!ours) {
        entry.blocked = `our capture ${ref.theme}/1920/${p.ours} is missing from ${rel(OURS_SHOTS)} (run node review/blind-pair.mjs --capture-ours with the build served)`;
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
      /* Both sides must show the pairing's TASK, through one definition (D1, phase 3.5): the reference
         declares the kind, and our frame meets the kind's specification. */
      const kindProblems = taskKindProblems([p], lib.TARGETS);
      if (kindProblems.length) {
        entry.blocked = `not matched by task: ${kindProblems.join("; ")}`;
        continue;
      }
      const oursOcr = ocrImages([fromRel(ours.file)]).get(resolve(fromRel(ours.file)));
      /* Judged inside the crop the critic sees (verifier V5). */
      const unmet = oursRequirementProblems(p, ours, oursOcr, { x: crop.oursOrigin.x, y: crop.oursOrigin.y, w: crop.w, h: crop.h });
      if (unmet.length) {
        entry.blocked = `our state ${ours.id} does not show the pairing's task (${p.task}: ${TASK_KINDS[p.task]?.says}): ${unmet.join("; ")}`;
        continue;
      }
      /* ...and so must the REFERENCE, by its task's result inside the crop, not its chrome (O70 R2-5). */
      const refOcr = ocrImages([fromRel(ref.file)]).get(resolve(fromRel(ref.file)));
      const refUnmet = refRequirementProblems(lib.TARGETS.find((x) => x.id === ref.id), refOcr, { x: crop.refOrigin.x, y: crop.refOrigin.y, w: crop.w, h: crop.h }, ref.dpr);
      if (refUnmet.length) {
        entry.blocked = `the reference ${ref.id} does not show the pairing's task (${p.task}) inside the crop: ${refUnmet.join("; ")}`;
        continue;
      }
      /* Our identity marks, by DOM geometry (phase 3.5): measured at capture time (--capture-ours) or,
         failing that, now; unmeasured geometry BLOCKS — OCR alone is not proof that our marks are masked. */
      let geo = geometryCache[ours.sha256];
      if (!geo || geo.error || geo.census !== CENSUS_SHA) {
        geo = (await measureOursIdentity([ours], ourId))[ours.sha256];
        geometryCache[ours.sha256] = geo;
        geometryDirty = true;
      }
      const geoProblem = oursGeometryProblem(geo, oursOcr, ourId, ours, lib);
      if (geoProblem) {
        entry.blocked = geoProblem;
        continue;
      }
      entry.oursIdentityGeometry = { measuredFrom: geo.url?.replace(/^https?:\/\/[^/]+/, "") ?? null, rects: geo.rects.length };
      entry.ref = { id: ref.id, product: ref.product, file: ref.file, sha256: ref.sha256, css: ref.css, dpr: ref.dpr, theme: ref.theme, provenance: ref.provenance };
      entry.crop = crop;
      /* What each panel loses to the common crop, in CSS px: a fault the critic reports at a cut edge
         is a crop artefact (RULE v2), and this is where a reader of the faults can see which edges
         were cut (verifier round 1, D5). */
      entry.truncation = {
        ours: { right: ours.css.w - crop.oursOrigin.x - crop.w, bottom: ours.css.h - crop.oursOrigin.y - crop.h },
        reference: { right: ref.css.w - crop.refOrigin.x - crop.w, bottom: ref.css.h - crop.refOrigin.y - crop.h },
      };
      /* Masks: the reference's identity slots — DOM-measured (logo slots; identity marks once a fetch
         recorded identityRects) and the geometry its TARGET declares (capture-refs-clean.mjs requires
         it of every frame whose identity marks were not measured in its DOM) — plus OUR identity
         blocks measured in our DOM; then OCR identity boxes on both panels as a second net; all
         unioned and painted on BOTH; iterate until the masked pixels read clean (max 3 passes). */
      /* Declared slots are geometry measured on ONE frame: a re-fetched frame with other bytes is not
         the frame they describe (verifier V8). */
      const staleSlots = lib.staleIdentitySlots([ref], lib.TARGETS);
      if (staleSlots.length) {
        entry.blocked = `reference ${ref.id}'s declared identity slots were measured on another frame (${staleSlots.join("; ")}); re-measure them on this frame`;
        continue;
      }
      const declared = lib.TARGETS.find((t) => t.id === ref.id)?.identitySlots ?? [];
      const slots = [
        ...(ref.census?.logoRects ?? []).map((r) => ({ ...r, why: "DOM logo slot" })),
        ...(ref.census?.identityRects ?? []).map((r) => ({ ...r, why: `DOM ${r.why ?? "identity mark"}` })),
        ...declared.map((r) => ({ ...r, why: r.why ?? "declared identity slot" })),
      ];
      let masks = initialMasks(slots, geo.rects, crop);
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
  if (geometryDirty) writeFileSync(geometryFile(), JSON.stringify(geometryCache, null, 1));
  const key = {
    schema: "atlas-scope/blind-key/4",
    oursShots: rel(OURS_SHOTS),
    builtAt: new Date().toISOString(),
    commit: git.commit,
    dirtyTree: git.dirty,
    rule: RULE,
    ruleSha: RULE_SHA,
    dimensions: C1_DIMENSIONS,
    identityMasked: identity,
    /* With identityMasked, the recognition vocabulary (RULE v5+, R2-3): read from REFERENCES.md. */
    referenceProducts: REFERENCE_PRODUCTS,
    verdictSchema: {
      file: "blind/verdicts.jsonl (append-only, one JSON object per line)",
      fields: VERDICT_FIELDS,
      closed: "no other field: a field outside the schema may carry an answer the validator cannot read, so its value is read as a possible pick and the line never counts",
      sheetSha: "the sheet's sha256 as sheets.json gives it (a sheet name or a unique 8+ hex prefix also binds)",
      perDimension: "{ <dimension>: 'A' | 'B' | 'tie' } in the critic's own A/B terms, under the sheet's one dimension; mapped through the sheet's side",
      recognizedAs: "string naming what was recognised when recognized is true; null (or empty) when it is false",
    },
    unobtainable: man.unobtainable ?? [],
    pairings,
  };
  const critic = {
    instructions: CRITIC_INSTRUCTIONS,
    recognitionQuestion: RECOGNITION_QUESTION,
    /* The sheet's sha travels with its name, so the panel can write the exact sheetSha (the resolver
       binds a name too, R2-2). Both are content hashes of the sheet bytes: neither reveals the side. */
    slots: pairings.flatMap((p) => p.slots.map((s) => ({ slot: s.slot, sheet: s.sheetName, sheetSha: s.sheetSha, question: p.question }))),
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

/** R2-4 on REAL data: derivedFrame() run against a scratch copy of every derived capture on disk (its
    record, its frame and its base frame), then with the base replaced by another real frame's bytes,
    with the base removed, and with the frame's bytes changed. { ran:false, why } when no derived
    capture is on disk (reported as NOT RUN, never as passed). */
export function derivedRealDataCheck(root = OURS_SHOTS) {
  let recs;
  try {
    recs = JSON.parse(readFileSync(resolve(root, "derived", "index.json"), "utf8"));
  } catch {
    return { ran: false, why: `no ${rel(resolve(root, "derived", "index.json"))}` };
  }
  const usable = recs.filter((r) => r.frameSha && DERIVED_STATES.some((d) => d.id === r.id) && existsSync(resolve(root, "derived", r.theme, String(r.viewport ?? "1920"), `${r.id}.png`)));
  if (!usable.length) return { ran: false, why: "no derived frame on disk matches its record" };
  const tmp = mkdtempSync(join(tmpdir(), "blind-r24-"));
  const out = { ran: true, ok: true, cases: [] };
  try {
    for (const r of usable) {
      const d = DERIVED_STATES.find((x) => x.id === r.id);
      const vp = String(r.viewport ?? "1920");
      const base = resolve(root, "app", r.theme, vp, `${d.from}.png`);
      const other = readdirSync(resolve(root, "app", r.theme, vp)).find((f) => f.endsWith(".png") && f !== `${d.from}.png`);
      if (!existsSync(base) || !other) {
        out.cases.push({ id: `${r.theme}/${vp}/${r.id}`, skipped: "no base or no other real frame beside it" });
        out.ok = false;
        continue;
      }
      const tBase = resolve(tmp, "app", r.theme, vp, `${d.from}.png`);
      const tFrame = resolve(tmp, "derived", r.theme, vp, `${r.id}.png`);
      mkdirSync(dirname(tBase), { recursive: true });
      mkdirSync(dirname(tFrame), { recursive: true });
      writeFileSync(resolve(tmp, "derived", "index.json"), JSON.stringify([r]));
      const reset = () => {
        writeFileSync(tBase, readFileSync(base));
        writeFileSync(tFrame, readFileSync(resolve(root, "derived", r.theme, vp, `${r.id}.png`)));
      };
      const probs = () => derivedFrame(d, r.theme, vp, tmp)?.capture?.problems ?? ["no frame"];
      reset();
      const clean = probs();
      writeFileSync(tBase, readFileSync(resolve(root, "app", r.theme, vp, other)));
      const replaced = probs();
      rmSync(tBase);
      const removed = probs();
      reset();
      writeFileSync(tFrame, Buffer.concat([readFileSync(tFrame), Buffer.from([0])]));
      const bytes = probs();
      const c = {
        id: `${r.theme}/${vp}/${r.id}`,
        clean: clean.length === (r.problems ?? []).length,
        replaced: replaced.some((x) => /replaced/.test(x)),
        removed: removed.some((x) => /removed/.test(x)),
        bytes: bytes.some((x) => /bytes differ/.test(x)),
      };
      out.cases.push(c);
      if (!(c.clean && c.replaced && c.removed && c.bytes)) out.ok = false;
    }
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
  return out;
}

/** The options the CLI evaluates verdicts under: the sheets every earlier build's KEY in `outDir`
    lists (the only sheets a line may be STALE on) and REFERENCES.md's products. One helper, so the
    self-test pins the wiring the CLI uses (QG-V4). */
export function cliEvaluateOptions(outDir = OUT) {
  return { superseded: supersededSheets(resolve(outDir, "_superseded")), referenceProducts: REFERENCE_PRODUCTS };
}
/** The self-test's options from the CLI arguments: `--selftest` (the gate) REQUIRES the R2-4 real-data
    check to run; the build and `--capture-ours` do not (a first capture must be able to start). */
export const selftestOptions = (args) => ({ requireRealData: args.includes("--selftest") });
/** The R2-4 real-data outcome: "pass" | "fail" | "not-run". Absent real data is "not-run" only when it
    is not required; when it is required it is a "fail" — absence is never a pass (QG-V4). */
export function realDataGate(result, requireRealData) {
  if (result?.ran) return { status: result.ok === true ? "pass" : "fail" };
  return { status: requireRealData ? "fail" : "not-run", why: result?.why ?? "not run" };
}

/* ── Self-tests (pure; each case would fail on the pre-2026-09-28 file) ─────────────────── */
export async function selfTest(opts = {}) {
  let fails = 0;
  const t = (name, ok, detail = "") => {
    console.log(`${ok ? "  ok  " : "  FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
    if (!ok) fails++;
  };
  const safe = (f) => {
    try {
      return f();
    } catch (e) {
      return `threw: ${String(e).slice(0, 90)}`;
    }
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
  /* (W5, R2-2: "stale" is a sheet an earlier build's KEY lists; an unknown sheet is UNBOUND and blocks
     C1 — the old assertion here, "a verdict on an unknown sheet is stale", encoded the defect.) */
  t("a verdict on a sheet an earlier KEY lists is stale; on an unknown sheet it is unbound and blocks C1", safe(() => {
    const st = evaluate(key, [v({ sheetSha: "ZZ" })], { superseded: ["ZZ"] });
    const ub = evaluate(key, [v({ sheetSha: "ZZ" })]);
    return st.stale === 1 && st.unbound === 0 && ub.stale === 0 && ub.unbound === 1 && ub.overall === "UNPROVEN";
  }) === true);
  t("the recognition vocabulary includes every reference product REFERENCES.md lists, and each TARGET's product is one of them", safe(() => REFERENCE_PRODUCTS.length > 0) === true && !!(await import("./capture-refs-clean.mjs").then((m) => m.TARGETS.every((x) => REFERENCE_PRODUCTS.includes(x.product))).catch(() => false)), JSON.stringify(REFERENCE_PRODUCTS));
  t("an unreadable recognition vocabulary keeps C1 UNPROVEN, never 'nothing to recognise'", safe(() => {
    const two = [v(), v({ criticId: "k2" })];
    return evaluate({ ...key, identityMasked: [] }, two, { referenceProducts: [] }).overall === "UNPROVEN" && evaluate({ ...key, identityMasked: ["Forward"] }, two, { referenceProducts: [] }).overall === "PASS";
  }) === true);
  t("a blocked pairing is UNPROVEN whatever the verdicts", evaluate({ ...key, pairings: [{ ...key.pairings[0], blocked: "leak" }] }, [v(), v({ criticId: "k2" })]).pairings[0].status === "UNPROVEN");
  const omit = (o, k) => Object.fromEntries(Object.entries(o).filter(([x]) => x !== k));
  t("every verdict field is required", VERDICT_FIELDS.every((f) => verdictShapeProblems(omit(v(), f)).length > 0));
  /* ── verifier round 1 (2026-09-28): each case below was red on the file it reviewed ── */
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
  /* (phase 3.5: our side's requirement moved from each pairing's `oursRequires` to its task kind's `ours`.) */
  t("every pairing declares what our state must show (D1)", PAIRINGS.every((p) => (TASK_KINDS[p.task]?.ours?.expect ?? []).length > 0));
  t("a traced-path pairing refuses a state with no multi-hop trace (D1)", safe(() => {
    const p = PAIRINGS.find((x) => x.dimension === "network-visualisation");
    const line = (text, x, y) => ({ text, words: [{ text, x, y, w: 60, h: 20 }] });
    const ocrOf = (...ls) => ({ ok: true, text: ls.map((l) => l.text).join(" "), lines: ls });
    /* Each requirement is tested ALONE: every other one is met in each case. */
    const shown = (TASK_KINDS[p.task].ours.expect ?? []).map((e) => line(e, 900, 900));
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
  /* ── phase 3.5 (owner): the KEY validator, table-driven. Each row is a verdict sequence and the
     outcome the RULE demands; `counted` is the exact set of critics counted. ── */
  let cases = null;
  try {
    cases = VALIDATOR_CASES;
  } catch {
    cases = null;
  }
  t("the validator has a table of cases", Array.isArray(cases) && cases.length >= 12);
  const keys = validatorKeys();
  for (const c of Array.isArray(cases) ? cases : []) {
    const got = safe(() => {
      const ev = evaluate(keys[c.key ?? "default"], c.verdicts.map((o) => (o === null ? { unparseable: "{" } : v(o))), { referenceProducts: REFERENCE_PRODUCTS, superseded: c.superseded ?? [] });
      const r = ev.pairings[0];
      return { status: r.status, counted: r.counted.map((x) => x.criticId).sort().join(","), overall: ev.overall };
    });
    const want = { status: c.want.status, counted: [...c.want.counted].sort().join(","), ...(c.want.overall ? { overall: c.want.overall } : {}) };
    t(
      `validator: ${c.name}`,
      typeof got === "object" && got.status === want.status && got.counted === want.counted && (!want.overall || got.overall === want.overall),
      JSON.stringify({ got, want }),
    );
  }
  /* ── phase 3.5 (owner): pairings are matched by TASK on both sides through ONE task definition. ── */
  t("every pairing names a task kind that specifies BOTH sides", safe(() => PAIRINGS.every((p) => TASK_KINDS[p.task]?.ours && TASK_KINDS[p.task]?.says)) === true);
  t("no pairing carries a hand-written our-side requirement (it comes from the task kind)", PAIRINGS.every((p) => !("oursRequires" in p)));
  t("a device's raw record does not show a path hop's decision; a traced flow at a hop does (typographic mismatch)", safe(() => {
    const p = { id: "x", task: "path-hop-decision" };
    const ocr = { ok: true, text: "Trace a flow  Evidence consulted at this hop (6), in evaluation order", lines: [] };
    const device = oursRequirementProblems(p, { capture: { url: "http://h/?s=evidence&d=core1&tab=raw" }, dpr: 2 }, ocr);
    /* (repair V4: the hop's evidence list must also be recorded open with a row on screen; the device
       record is refused before and after that tightening.) */
    const hop = oursRequirementProblems(p, { capture: { url: "http://h/?s=path&flow=a>b>tcp>1&hop=0", dom: { open: ["hop__evidence"], rows: { hop__ev: [{ x: 20, y: 300, w: 300, h: 30 }] } } }, dpr: 2 }, ocr);
    return device.length > 0 && hop.length === 0;
  }) === true);
  const refs = await import("./capture-refs-clean.mjs").catch(() => null);
  t("every pairing's reference TARGET declares the pairing's task kind", !!refs && safe(() => taskKindProblems(PAIRINGS, refs.TARGETS).length === 0) === true, safe(() => taskKindProblems(PAIRINGS, refs?.TARGETS ?? []).join("; ")));
  /* ── W5 (O70 R2-5): the reference's task state is its RESULT, inside the crop the critic sees. ── */
  t("every pairing's reference TARGET declares its task's result (taskState), and every paired kind names contrast kinds (R2-5)", !!refs && safe(() => PAIRINGS.every((p) => (refs.TARGETS.find((x) => x.id === p.ref)?.taskState ?? []).length > 0 && (TASK_KINDS[p.task]?.ref?.contrast ?? []).length > 0)) === true);
  t("the reference's task state is read inside the CROP the critic sees; none declared is refused (R2-5)", safe(() => {
    const target = { id: "r", taskState: ["routes table match"] };
    const at = (x, y) => ({ ok: true, text: "routes table match", lines: [{ text: "routes table match", words: ["routes", "table", "match"].map((w, i) => ({ text: w, x: x + i * 90, y, w: 80, h: 20 })) }] });
    const crop = { x: 0, y: 0, w: 1692, h: 800 };
    const inside = refRequirementProblems(target, at(900, 700), crop, 1);
    const cut = refRequirementProblems(target, at(900, 850), crop, 1);
    const none = refRequirementProblems({ id: "r" }, at(900, 700), crop, 1);
    return inside.length === 0 && cut.length === 1 && none.length === 1;
  }) === true);
  t("a pairing whose reference shows another task is refused",safe(() => taskKindProblems([{ id: "p", task: "path-hop-decision", ref: "r" }], [{ id: "r", taskKind: "finding-list" }]).length === 1) === true);
  /* ── phase 3.5 (owner): OUR identity is masked by its DOM geometry, not by what OCR can read. ── */
  t("our identity geometry: an OCR identity hit outside every DOM rect is reported", safe(() => {
    const rects = [{ x: 90, y: 4, w: 260, h: 40 }];
    return identityOutsideDom([{ x: 100, y: 10, w: 80, h: 14, why: "a" }], rects).length === 0 && identityOutsideDom([{ x: 900, y: 10, w: 80, h: 14, why: "b" }], rects).length === 1 && identityOutsideDom([{ x: 1, y: 1, w: 5, h: 5 }], []).length === 1;
  }) === true);
  t("our identity geometry is painted as masks in crop coordinates", safe(() => {
    const m = oursIdentityMasks([{ x: 90, y: 4, w: 260, h: 40, why: "hdr" }], { x: 0, y: 0 });
    return m.length === 1 && m[0].x <= 90 && m[0].y <= 4 && m[0].x + m[0].w >= 350 && m[0].y + m[0].h >= 44;
  }) === true);
  t("a sheet's masks start from OUR DOM identity geometry as well as the reference's slots", safe(() => {
    const crop = { refOrigin: { x: 0, y: 0 }, oursOrigin: { x: 0, y: 0 } };
    const m = initialMasks([{ x: 10, y: 5, w: 52, h: 36, why: "glyph" }], [{ x: 90, y: 4, w: 260, h: 40, why: "our block" }], crop);
    return m.length === 2 && m.some((r) => r.x <= 90 && r.x + r.w >= 350 && r.y + r.h >= 44) && m.some((r) => r.x <= 10 && r.x + r.w >= 62);
  }) === true);
  t("unmeasured or stale identity geometry blocks the pairing; matching geometry does not", safe(() => {
    const lib = { tokens: (s) => s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean), findPhrase: (toks, ph) => (toks.join(" ").includes(ph.toLowerCase()) ? [[0, toks.length]] : []) };
    const ocr = { ok: true, lines: [{ words: [{ text: "ab12cd34", x: 400, y: 60, w: 120, h: 24 }] }] };
    const ours = { id: "o", dpr: 2 };
    const good = { rects: [{ x: 190, y: 20, w: 90, h: 30 }] };
    const stale = { rects: [{ x: 900, y: 20, w: 90, h: 30 }] };
    return oursGeometryProblem(null, ocr, ["ab12cd34"], ours, lib) !== null && oursGeometryProblem({ error: "down" }, ocr, ["ab12cd34"], ours, lib) !== null && oursGeometryProblem(stale, ocr, ["ab12cd34"], ours, lib) !== null && oursGeometryProblem(good, ocr, ["ab12cd34"], ours, lib) === null;
  }) === true);
  /* ── phase 3.5 repair (verifier V1, V4, V5, V8) ── */
  t("an unattributable recognising line is reported, not dropped without trace (V7)", safe(() => {
    const r = evaluate(key, [v({ criticId: "", recognized: true, recognizedAs: "Forward in B", perDimension: { composition: "A" } })]).pairings[0];
    return r.invalid.length === 1 && /unattributable/.test(r.invalid[0].problems.join(" "));
  }) === true);
  t("a finding's summary is not the raw data behind a result; the raw record is (colour-discipline, V1)", safe(() => {
    const p = { id: "x", task: "result-data-inspection" };
    const finding = { ok: true, text: "Finding Device Critical F001 punchlist[0] CR-01: End-of-support keystone Category Compound risk What the engine said", lines: [] };
    const raw = { ok: true, text: "Summary Ports Routing ACL Findings Raw This is the compiled record this pane renders from. The record in the source snapshot", lines: [] };
    const f04 = oursRequirementProblems(p, { capture: { url: "http://h/?s=findings&f=F001&d=core1&tab=raw" }, dpr: 2 }, finding);
    const f04raw = oursRequirementProblems(p, { capture: { url: "http://h/?s=findings&f=F001&d=core1&tab=raw" }, dpr: 2 }, raw);
    const f07 = oursRequirementProblems(p, { capture: { url: "http://h/?s=evidence&d=core1&tab=raw" }, dpr: 2 }, raw);
    return f04.length > 0 && f04raw.length > 0 && f07.length === 0;
  }) === true);
  t("the colour-discipline pairing uses the raw-evidence state (V1)", PAIRINGS.find((p) => p.dimension === "colour-discipline")?.ours === "07-evidence-raw");
  t("a hop decision needs its evidence list OPEN with a row on screen, not the collapsed label (V4)", safe(() => {
    const p = { id: "x", task: "path-hop-decision" };
    const url = "http://h/?s=path&flow=a>b>tcp>1&hop=0";
    const line = (text, x, y) => ({ text, words: text.split(" ").map((w, i) => ({ text: w, x: x + i * 90, y, w: 80, h: 20 })) });
    const ocr = { ok: true, text: "denies this flow Evidence consulted at this hop (6), in evaluation order", lines: [line("denies this flow", 200, 300), line("Evidence consulted at this hop", 200, 500)] };
    const row = { x: 20, y: 300, w: 300, h: 30 };
    const closed = oursRequirementProblems(p, { capture: { url }, dpr: 2 }, ocr);
    const open = oursRequirementProblems(p, { capture: { url, dom: { open: ["hop__evidence"], rows: { hop__ev: [row] } } }, dpr: 2 }, ocr);
    const openOff = oursRequirementProblems(p, { capture: { url, dom: { open: ["hop__evidence"], rows: { hop__ev: [{ ...row, y: 1200 }] } } }, dpr: 2 }, ocr, { x: 0, y: 0, w: 1692, h: 943 });
    return closed.length > 0 && open.length === 0 && openOff.length > 0;
  }) === true);
  /* ── W5 (O70 R2-4): the derived frame's record is bound to its own bytes AND to its base capture. The
     pure check is pinned on synthetic records; derivedFrame() itself on a scratch copy of the REAL
     derived capture (review/blind/_ours, from --capture-ours): the record as captured is clean, and a
     replaced base, a removed base and changed frame bytes are each refused. ── */
  t("a derived record is refused when its frame bytes changed, its base was replaced, or its base is gone (R2-4)", safe(() => {
    const rec = { frameSha: "F", baseSha: "B", problems: [] };
    const ok = derivedRecordProblems(rec, { frameSha: "F", baseSha: "B", from: "06" });
    const bytes = derivedRecordProblems(rec, { frameSha: "F2", baseSha: "B", from: "06" });
    const replaced = derivedRecordProblems(rec, { frameSha: "F", baseSha: "B2", from: "06" });
    const removed = derivedRecordProblems(rec, { frameSha: "F", baseSha: null, from: "06" });
    const unbound = derivedRecordProblems({ problems: [] }, { frameSha: "F", baseSha: "B", from: "06" });
    return ok.length === 0 && bytes.length === 1 && /bytes/.test(bytes[0]) && replaced.length === 1 && /replaced/.test(replaced[0]) && removed.length === 1 && /removed/.test(removed[0]) && unbound.length === 2;
  }) === true);
  /* ── W5 (O70 D5): our panel is a whole frame when a capture at the reference's viewport exists. ── */
  t("our frame is taken at the reference's own viewport when captured there, and the crop then cuts nothing; else the 1920 frame (D5)", safe(() => {
    const tmp = mkdtempSync(join(tmpdir(), "blind-d5-"));
    try {
      const png = (w, h) => {
        const b = Buffer.alloc(33);
        b.writeUInt32BE(w, 16);
        b.writeUInt32BE(h, 20);
        return b;
      };
      const put = (vp, w, h) => {
        mkdirSync(resolve(tmp, "app", "dark", vp), { recursive: true });
        writeFileSync(resolve(tmp, "app", "dark", vp, "06-path-blocked.png"), png(w, h));
      };
      put("1920", 3840, 2160);
      put("1920x869", 3840, 1738);
      writeFileSync(resolve(tmp, "app", "index.json"), JSON.stringify(["1920", "1920x869"].map((viewport) => ({ id: "06-path-blocked", theme: "dark", viewport, url: "u", problems: [] }))));
      const ref = { css: { w: 1920, h: 869 }, dpr: 2 };
      const at = oursFrame("06-path-blocked", "dark", ref.css, tmp);
      const fallback = oursFrame("06-path-blocked", "dark", { w: 1692, h: 943 }, tmp);
      const crop = cropFor({}, at, ref);
      return at.viewport === "1920x869" && at.css.w === 1920 && at.css.h === 869 && at.dpr === 2 && at.capture?.url === "u" && fallback.viewport === "1920" && fallback.css.h === 1080 && crop.w === 1920 && crop.h === 869;
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  }) === true);
  t("--capture-ours asks for the paired states (a derived state's base) at 1920x1080 and at every paired reference's viewport (D5)", safe(() => {
    const plan = oursCapturePlan(PAIRINGS, PAIRINGS.map((p, i) => ({ id: p.ref, css: i % 2 ? { w: 1920, h: 869 } : { w: 1692, h: 943 } })));
    const states = plan.states.split(",");
    return plan.viewports === "1920x1080,1692x943,1920x869" && states.includes("06-path-blocked") && !states.some((s) => DERIVED_STATES.some((d) => d.id === s)) && PAIRINGS.every((p) => states.includes(DERIVED_STATES.find((d) => d.id === p.ours)?.from ?? p.ours));
  }) === true, JSON.stringify(safe(() => oursCapturePlan(PAIRINGS, []))));
  const cap = await import("./capture.mjs").catch((e) => ({ error: String(e).slice(0, 120) }));
  t("capture.mjs (imported without running) accepts the plan's viewports and states, and files them under the ids oursFrame reads (D5)", safe(() => {
    const plan = oursCapturePlan(PAIRINGS, [{ id: PAIRINGS[0].ref, css: { w: 1920, h: 869 } }, { id: PAIRINGS[2].ref, css: { w: 1692, h: 943 } }]);
    const vps = cap.parseViewports(plan.viewports);
    return vps.problems.length === 0 && vps.viewports.map((v) => v.id).join() === ["1920", "1920x869", "1692x943"].join() && vps.viewports.every((v) => v.id === viewportId({ w: v.width, h: v.height })) && typeof cap.selectStates === "function";
  }) === true, cap.error ?? "");
  const realDerived = derivedRealDataCheck();
  const realGate = realDataGate(realDerived, opts.requireRealData === true);
  if (realGate.status === "not-run") console.log(`  n/a  derivedFrame() real-data check NOT RUN (${realGate.why}): UNPROVEN on this host, not passed; run --capture-ours (--selftest requires it)`);
  else t("derivedFrame() on a scratch copy of the REAL derived capture: clean as captured; replaced base, removed base and changed bytes refused (R2-4)", realGate.status === "pass", realDerived.ran ? JSON.stringify(realDerived).slice(0, 400) : `NOT RUN (${realGate.why}): --selftest requires it; run --capture-ours`);
  /* ── W5 round 2 (QG-V4): the success paths no row pinned. ── */
  t("the CLI's evaluate options name the sheets an earlier build's KEY lists (blind/_superseded) and REFERENCES.md's products (QG-V4)", safe(() => {
    const tmp = mkdtempSync(join(tmpdir(), "blind-cli-"));
    try {
      mkdirSync(resolve(tmp, "_superseded", "20260101T000000Z"), { recursive: true });
      writeFileSync(resolve(tmp, "_superseded", "20260101T000000Z", "KEY.json"), JSON.stringify({ pairings: [{ sheets: [{ sheetSha: "OLDSHEET", sheetName: "sheet-old.png" }] }] }));
      const o = cliEvaluateOptions(tmp);
      const ev = evaluate(validatorKeys().default, [v({ sheetSha: "sheet-old.png", perDimension: { composition: "B" } }), v(), v({ criticId: "k2" })], o);
      return o.referenceProducts === REFERENCE_PRODUCTS && ev.stale === 1 && ev.unbound === 0 && ev.overall === "PASS";
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  }) === true);
  t("`--selftest` requires the R2-4 real-data check to RUN: absent derived captures are a FAIL there, never a pass (QG-V4)", safe(() => {
    const need = selftestOptions(["--selftest"]).requireRealData === true && selftestOptions([]).requireRealData === false && selftestOptions(["--capture-ours"]).requireRealData === false;
    const g = (r, req) => realDataGate(r, req).status;
    return need && g({ ran: false, why: "none" }, true) === "fail" && g({ ran: false, why: "none" }, false) === "not-run" && g({ ran: true, ok: true }, true) === "pass" && g({ ran: true, ok: false }, false) === "fail";
  }) === true);
  t("the typographic pairing uses a state with the hop's evidence list opened (V4)", safe(() => {
    const p = PAIRINGS.find((x) => x.dimension === "typographic-craft");
    const d = DERIVED_STATES.find((s) => s.id === p.ours);
    return !!d && d.open.includes(".hop__evidence");
  }) === true);
  t("our task state is read inside the CROP the critic sees, not the whole frame (V5)", safe(() => {
    const p = { id: "x", task: "path-blocked" };
    const url = "http://h/?s=path&flow=a>b>tcp>1&hop=0";
    const at = (x, y) => ({ ok: true, text: "denies this flow", lines: [{ text: "denies this flow", words: ["denies", "this", "flow"].map((w, i) => ({ text: w, x: x + i * 120, y, w: 100, h: 24 })) }] });
    const inside = oursRequirementProblems(p, { capture: { url }, dpr: 2 }, at(400, 400), { x: 0, y: 0, w: 1692, h: 943 });
    const cutRight = oursRequirementProblems(p, { capture: { url }, dpr: 2 }, at(3500, 400), { x: 0, y: 0, w: 1692, h: 943 });
    const cutBottom = oursRequirementProblems(p, { capture: { url }, dpr: 2 }, at(400, 2000), { x: 0, y: 0, w: 1692, h: 943 });
    return inside.length === 0 && cutRight.length === 1 && cutBottom.length === 1;
  }) === true);
  t("a reference whose declared identity slots were measured on another frame is refused (V8)", !!refs && safe(() => {
    const tg = [{ id: "r", identitySlots: [{ x: 1, y: 1, w: 9, h: 9 }], identitySlotsCheckedOn: "aaaaaaaaaaaa" }];
    return refs.staleIdentitySlots([{ id: "r", sha256: "aaaaaaaaaaaa1234" }], tg).length === 0 && refs.staleIdentitySlots([{ id: "r", sha256: "bbbbbbbbbbbb1234" }], tg).length === 1 && refs.staleIdentitySlots([{ id: "r", sha256: "aaaaaaaaaaaa1234" }], [{ id: "r", identitySlots: [{ x: 1, y: 1, w: 9, h: 9 }] }]).length === 1;
  }) === true);
  /* Repair round: the 2026-09-29 re-capture measured dark/06 while the page was still loading (only a
     "Atlas Scope" loading line, no header), so its geometry described another moment than the frame.
     The measurement must wait for the settled state the frame was shot in. */
  const late = await (async () => {
    const html = `<!doctype html><html><body style="margin:0;font:14px system-ui"><p id="boot" style="width:1400px">Loading Scope Product</p><script>
      setTimeout(() => { document.getElementById("boot").remove();
        document.body.insertAdjacentHTML("afterbegin", '<header style="display:flex;height:48px"><p class="brand" style="margin:0"><span>Scope Product</span></p><button class="snap"><span>fleet.snapshot.json</span></button></header><span class="sb__converged">settled</span>');
        window.__atlasScene = { stats: () => ({ converged: true, quality: "high", framesTimed: 1 }) }; }, 2600);
      document.documentElement.setAttribute("data-palette-warm", "done");</script></body></html>`;
    const r = await measureOursIdentity([{ sha256: "late", capture: { url: `data:text/html,${encodeURIComponent(html)}` }, css: { w: 1920, h: 400 }, theme: "dark" }], ["Scope Product", "fleet.snapshot.json"]);
    const rects = r.late?.rects ?? [];
    return { ok: rects.some((x) => /snapshot/.test(x.why)) && !rects.some((x) => x.w > 1000), n: rects.length, error: r.late?.error ?? null };
  })().catch((e) => ({ ok: false, error: String(e).slice(0, 140) }));
  t("our identity is measured in the SETTLED page the frame was shot in, not mid-load", late.ok === true, JSON.stringify(late));
  const census = await identityCensusControl().catch((e) => ({ error: String(e).slice(0, 120) }));
  t("the DOM identity census covers the WHOLE identity block (both lines, glyph included) and only the phrase inside prose", census.ok === true, JSON.stringify(census).slice(0, 300));
  return fails;
}

/* ── CLI ─────────────────────────────────────────────────────────────────────────────────── */
if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const args = process.argv.slice(2);
  const vi = args.indexOf("--verdicts");
  const verdictsFile = vi >= 0 ? resolve(args[vi + 1]) : resolve(OUT, "verdicts.jsonl");
  const receiptFile = resolve(OUT, "verdicts.receipt.json");
  console.log("self-tests:");
  const tf = await selfTest(selftestOptions(args));
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
    if (args.includes("--capture-ours")) {
      /* Our states, captured by capture.mjs (its render checks and its index) into the private root,
         then our identity geometry measured from the same server while it is up. */
      const url = process.env.ATLAS_URL || "http://localhost:4181";
      /* Only the states the pairings use (a derived state's base), at 1920x1080 AND at every paired
         reference's own CSS viewport, so our panel is a whole frame rather than a crop (D5). */
      const plan = oursCapturePlan(PAIRINGS, await refsLib().then((l) => (existsSync(l.MANIFEST) ? JSON.parse(readFileSync(l.MANIFEST, "utf8")).frames : [])));
      const viewports = process.env.ATLAS_VIEWPORTS || plan.viewports;
      const states = process.env.ATLAS_STATES || plan.states;
      console.log(`capturing our states: capture.mjs app from ${url} into ${rel(OURS_SHOTS)}/app (states ${states}; viewports ${viewports})`);
      const r = spawnSync(process.execPath, [resolve(HERE, "capture.mjs"), "app"], { cwd: ROOT, env: { ...process.env, ATLAS_SHOTS: OURS_SHOTS, ATLAS_URL: url, ATLAS_VIEWPORTS: viewports, ATLAS_STATES: states }, stdio: "inherit" });
      console.log(`capture.mjs app exit ${r.status}${r.status ? " (a frame that did not render properly BLOCKS its pairing below)" : ""}`);
      let idx = [];
      try {
        idx = JSON.parse(readFileSync(resolve(OURS_SHOTS, "app", "index.json"), "utf8"));
      } catch {
        idx = [];
      }
      /* The states no URL encodes, derived from the frames just captured, from the same server. */
      process.env.ATLAS_URL = url;
      const derived = await captureDerived();
      for (const d of derived) console.log(`  derived ${d.theme}/1920/${d.id} (from ${d.from}): ${d.problems.length ? `BAD — ${d.problems.join("; ")}` : `ok, open ${JSON.stringify(d.dom?.open ?? [])}, ${Object.entries(d.dom?.rows ?? {}).map(([k, v]) => `${v.length} ${k} row(s) on screen`).join(", ")}`}`);
      const frames = [
        ...[...new Map(idx.filter((e) => viewportCss(e.viewport)).map((e) => [`${e.theme}/${e.viewport}/${e.id}`, e])).values()].map((e) => oursFrame(e.id, e.theme, viewportCss(e.viewport))),
        ...derived.map((d) => oursFrame(d.id, d.theme, viewportCss(d.viewport))),
      ].filter(Boolean);
      const measured = await measureOursIdentity(frames, oursIdentity());
      writeFileSync(geometryFile(), JSON.stringify({ ...readGeometryCache(), ...measured }, null, 1));
      const bad = Object.values(measured).filter((g) => g.error);
      console.log(`  our identity geometry measured for ${frames.length - bad.length}/${frames.length} frame(s)${bad.length ? ` — ${bad[0].error}` : ""}`);
    }
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
  /* Stale = a sheet an earlier build's KEY lists; the recognition vocabulary adds REFERENCES.md's
     products to the KEY's identityMasked (RULE v5+). */
  const ev = evaluate(key, verdicts, cliEvaluateOptions());
  if (tamper) {
    ev.overall = "UNPROVEN";
    console.log(`REFUSED: the verdict file is not append-only — ${tamper}. C1 cannot be PASS on an edited verdict record.`);
  } else if (vbuf && verdictsFile === resolve(OUT, "verdicts.jsonl")) writeFileSync(receiptFile, JSON.stringify(receiptFor(vbuf)));
  printEvaluation(ev);
  process.exit(tamper ? 1 : key.pairings.some((p) => p.blocked) ? 2 : 0);
}
