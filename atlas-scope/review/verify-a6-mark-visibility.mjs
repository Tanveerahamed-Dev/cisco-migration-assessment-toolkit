/**
 * Hosted A6 mark-visibility witness over a fresh standalone production build.
 *
 * After npm run build, build-freshness --stamp and playwright install chromium:
 *   node review/verify-a6-mark-visibility.mjs --expected-commit <checkout SHA> --output <fresh external dir>
 *
 * Geometry/paint-order observations are independent of data-covered/data-clipped. The expected
 * stranded universe comes from the real DevicePane/LinkPane's canonical Newly stranded row,
 * not from the labels' marking flags or the HUD's own counts. Marks, counts and reader actions
 * are observed across camera movement and subject transitions, including pending reports.
 *
 * A6's recorded acceptance FAIL is not changed. No reference-laptop timing/frame proof, A3
 * fallback endorsement, network/fleet qualification or review approval follows from this file.
 */
import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, constants, existsSync, fstatSync, lstatSync, mkdirSync, openSync, readSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";
import { checkBuildFreshness } from "./build-freshness.mjs";
import { awaitPaletteWarm } from "./palette-warm.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = realpathSync(resolve(PKG, ".."));
const MAX_INPUT = 16 * 1024 * 1024;
const WAIT = 30000;
const ORIGIN = "http://127.0.0.1:4189";
const VIEWPORTS = [{ width: 390, height: 844 }, { width: 768, height: 1024 }, { width: 1440, height: 900 }];
const TARGETS = ["core1", "core2", "L18", "L33"];
const PIXEL_CONTROLS = ["dist1", "dist2"];
const THEME = ["light", "dark"];
const check = (ok, why, diagnostic) => {
  if (!ok) {
    const error = new Error(why);
    if (diagnostic !== undefined) error.a6Diagnostic = diagnostic;
    throw error;
  }
};
const sha = (raw) => createHash("sha256").update(raw).digest("hex");
const inside = (parent, child) => {
  const path = relative(parent, child);
  return path === "" || (!isAbsolute(path) && path !== ".." && !path.startsWith(`..${sep}`));
};
const gitBytes = (...args) => {
  const result = spawnSync("git", args, { cwd: REPO, timeout: WAIT, maxBuffer: MAX_INPUT });
  check(result.status === 0, `git ${args[0]} failed`);
  return result.stdout;
};
const git = (...args) => gitBytes(...args).toString("utf8").trim();
function canonical(path) {
  check(isAbsolute(path), "custody path must be absolute");
  let existing = resolve(path);
  const tail = [];
  while (!existsSync(existing)) {
    check(existing !== dirname(existing), "custody path lacks an existing parent");
    tail.unshift(basename(existing)); existing = dirname(existing);
  }
  return resolve(realpathSync(existing), ...tail);
}
function external(path) {
  const roots = gitBytes("worktree", "list", "--porcelain", "-z").toString("utf8").split("\0")
    .filter((part) => part.startsWith("worktree ")).map((part) => canonical(part.slice(9)));
  const common = canonical(git("rev-parse", "--path-format=absolute", "--git-common-dir"));
  check(roots.length > 0, "no managed worktree roots");
  const actual = canonical(path);
  for (const root of [...roots, REPO, common]) check(!inside(root, actual) && !inside(actual, root), "evidence overlaps source or common Git");
  return actual;
}
const stable = (a, b) => ["dev", "ino", "mode", "nlink", "size", "mtimeNs", "ctimeNs"]
  .every((key) => typeof a[key] === "bigint" && a[key] === b[key]);
function ordinary(path, maximum = MAX_INPUT) {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(fd, { bigint: true });
    check(before.isFile() && before.nlink === 1n && before.size <= BigInt(maximum) && canonical(path) === resolve(path), "nonordinary/aliased/oversized input");
    const chunk = Buffer.alloc(65536); const parts = []; let bytes = 0;
    while (bytes <= maximum) {
      const n = readSync(fd, chunk, 0, Math.min(chunk.length, maximum + 1 - bytes), null);
      if (n === 0) break;
      parts.push(Buffer.from(chunk.subarray(0, n))); bytes += n;
    }
    const after = fstatSync(fd, { bigint: true }); const named = lstatSync(path, { bigint: true });
    check(bytes <= maximum && bytes === Number(before.size) && named.isFile() && !named.isSymbolicLink()
      && stable(before, after) && stable(before, named) && canonical(path) === resolve(path), "source identity changed while reading");
    return Buffer.concat(parts, bytes);
  } finally { closeSync(fd); }
}
function materialSet() {
  const selected = ["atlas-scope", "webapp/sample_data/sample_fleet.snapshot.json", ".github/workflows/atlas-scope-ci.yml", ".github/scripts/scope_compile_handoff.py"];
  const inventory = (index) => {
    const rows = index ? gitBytes("ls-files", "--stage", "-z", "--", ...selected) : gitBytes("ls-tree", "-r", "-z", "HEAD", "--", ...selected);
    const result = {};
    for (const row of rows.toString("utf8").split("\0").filter(Boolean)) {
      const tab = row.indexOf("\t"); const [mode, second, third] = row.slice(0, tab).split(" "); const path = row.slice(tab + 1);
      const blob = index ? second : third; const kind = index ? third : second;
      check(tab > 0 && ["100644", "100755"].includes(mode) && kind === (index ? "0" : "blob") && /^[0-9a-f]{40}$/.test(blob), "unsupported source Git entry");
      check(!Object.hasOwn(result, path) && !isAbsolute(path) && !path.includes("\\") && !path.split("/").some((p) => ["", ".", ".."].includes(p)), "unsafe/duplicate source path");
      result[path] = { gitMode: mode, gitBlob: blob };
    }
    return Object.fromEntries(Object.entries(result).sort(([a], [b]) => a.localeCompare(b)));
  };
  const head = inventory(false); check(JSON.stringify(head) === JSON.stringify(inventory(true)), "source index differs from HEAD");
  check(gitBytes("ls-files", "-v", "-z", "--", ...selected).toString("utf8").split("\0").filter(Boolean).every((row) => row.startsWith("H ")), "source index hides changes");
  check(Object.hasOwn(head, "atlas-scope/review/verify-a6-mark-visibility.mjs"), "harness is not committed");
  return Object.fromEntries(Object.entries(head).map(([path, record]) => {
    const bytes = ordinary(join(REPO, path)); check(bytes.equals(gitBytes("cat-file", "blob", `HEAD:${path}`)), "source differs from immutable Git blob");
    return [path, { ...record, bytes: bytes.length, sha256: sha(bytes) }];
  }));
}
function option(name) {
  const at = process.argv.indexOf(name); check(at > 0 && process.argv[at + 1], `required ${name}`); return process.argv[at + 1];
}
check(process.env.GITHUB_ACTIONS === "true" && process.env.RUNNER_ENVIRONMENT === "github-hosted" && process.platform === "linux", "GITHUB-ONLY hosted Linux browser harness");
const expectedCommit = option("--expected-commit"); check(/^[0-9a-f]{40}$/.test(expectedCommit), "full expected commit required");
const outputArg = option("--output"); check(isAbsolute(outputArg) && !existsSync(outputArg) && existsSync(dirname(outputArg)), "fresh external output with existing parent required");
const output = external(outputArg); check(!existsSync(output), "resolved output already exists"); mkdirSync(output, { mode: 0o700 });
const report = {
  schema: "atlas-scope.a6-mark-visibility-browser/1", status: "FAIL", expectedCommit,
  acceptanceGrade: "FAIL_RETAINED_UNTIL_SEPARATE_REGRADE", acceptanceGradeChanged: false, qualification: false,
  source: null, cases: [], observations: [], failures: [], optionalCoverage: [],
  counters: { subjects: 0, canvasSelections: 0, enter: 0, zoom: 0, orbit: 0, home: 0, readyReports: 0, transitionFrames: 0, geometryChecks: 0, keyboardReveal: 0, glyphChecks: 0 },
  canvasPixelCriterion: { status: "UNVERIFIED", method: "raw WebGL default-framebuffer RGBA, separate from DOM screenshots", comparisons: [] },
  limits: ["Finite repair witness; not reference-laptop/frame-time qualification, A3 fallback approval, fleet proof or a formal review.",
    "B3 capture and existing complete A5/B5/C6/F4 unit/contracts remain separate hosted gates; no old receipt transfers.",
    "Pointer-inert labels temporarily receive pointer-events:auto during measurement, then restore exactly, solely to query actual browser paint order without moving/resizing/relabeling them."],
};
const save = () => writeFileSync(join(output, "a6-mark-visibility.json"), `${JSON.stringify(report, null, 2)}\n`);
const failures = (error, where) => {
  report.failures.push({ where, error: String(error), ...(error?.a6Diagnostic === undefined ? {} : { diagnostic: error.a6Diagnostic }) });
  save();
};
save();

/** This executes only in the hosted browser: actual boxes/paint order, not report flags as oracle. */
function observeScene() {
  const text = (node) => (node?.textContent ?? "").replace(/\s+/g, " ").trim();
  const rect = (element) => { const r = element.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; };
  const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  const stage = document.querySelector(".fabric3d"); const canvas = stage?.querySelector("canvas");
  if (!stage || !canvas) return { error: "actual fabric stage/canvas absent" };
  const sr = rect(stage); const cr = rect(canvas); const all = [...stage.querySelectorAll(".fabric3d-label[data-device]")];
  const drawn = (el) => { const cs = getComputedStyle(el); const r = rect(el); return r.w > 0 && r.h > 0 && cs.visibility === "visible" && cs.display !== "none" && Number(cs.opacity) > 0; };
  const controls = [...stage.querySelectorAll(".fabric3d__hud > *, [data-label-keepout]:not(.fabric3d__hud), .fabric3d__pointers button:not([hidden])")]
    .filter((node) => { const cs = getComputedStyle(node); const r = rect(node); return r.w >= 2 && r.h >= 2 && cs.visibility === "visible" && cs.display !== "none"; });
  const marked = all.map((el) => {
    const box = rect(el); const shown = drawn(el);
    const whole = box.x >= sr.x - 0.5 && box.y >= sr.y - 0.5 && box.x + box.w <= sr.x + sr.w + 0.5 && box.y + box.h <= sr.y + sr.h + 0.5;
    // Document viewport containment has zero CSS-pixel tolerance: interior hits cannot prove an absent edge.
    const viewportWhole = box.x >= 0 && box.y >= 0 && box.x + box.w <= innerWidth && box.y + box.h <= innerHeight;
    return { el, id: el.getAttribute("data-device"), host: text(el.querySelector(".fabric3d-label__name")), box, shown, whole, viewportWhole,
      strandedCuePainted: Boolean(el.querySelector(".fabric3d-label__stranded") && drawn(el.querySelector(".fabric3d-label__stranded"))),
      cutCuePainted: Boolean(el.querySelector(".fabric3d-label__alarm--cut") && drawn(el.querySelector(".fabric3d-label__alarm--cut"))),
      cutClaim: el.getAttribute("data-cut"), strandedClaim: el.getAttribute("data-stranded"), diagnosticCoveredFlag: el.getAttribute("data-covered"),
      diagnosticClippedFlag: el.getAttribute("data-clipped"), expectedProbes: 0, skippedProbes: [], hits: [], occluders: [] };
  });
  const old = all.map((el) => ({ el, value: el.style.getPropertyValue("pointer-events"), priority: el.style.getPropertyPriority("pointer-events") }));
  try {
    for (const el of all) el.style.setProperty("pointer-events", "auto");
    for (const row of marked) {
      if (!row.shown || !row.whole) continue;
      const tests = [];
      for (const x of [0.15, 0.5, 0.85]) for (const y of [0.2, 0.5, 0.8]) tests.push({ x: row.box.x + row.box.w * x, y: row.box.y + row.box.h * y });
      for (const other of [...marked.filter((r) => r.shown && r.el !== row.el).map((r) => ({ element: r.el, box: r.box })), ...controls.map((element) => ({ element, box: rect(element) }))]) {
        if (!overlap(row.box, other.box)) continue;
        const left = Math.max(row.box.x, other.box.x), right = Math.min(row.box.x + row.box.w, other.box.x + other.box.w);
        const top = Math.max(row.box.y, other.box.y), bottom = Math.min(row.box.y + row.box.h, other.box.y + other.box.h);
        tests.push({ x: (left + right) / 2, y: (top + bottom) / 2 });
      }
      row.expectedProbes = tests.length;
      for (const point of tests) {
        if (point.x < 0 || point.y < 0 || point.x >= innerWidth || point.y >= innerHeight) {
          row.skippedProbes.push({ ...point, reason: "outside-document-viewport" });
          continue;
        }
        const hit = document.elementFromPoint(point.x, point.y);
        const own = hit !== null && row.el.contains(hit);
        row.hits.push({ ...point, own, topTag: hit?.tagName ?? null, topClass: typeof hit?.className === "string" ? hit.className : null });
        if (!own && hit && hit !== canvas) row.occluders.push(hit.closest(".fabric3d-label")?.getAttribute("data-device")
          ?? (hit.closest(".fabric3d__hud") ? "painted-hud" : stage.contains(hit) ? "stage-layer" : "outside-stage-overlay"));
      }
      if (row.hits.length > 0 && row.hits.every((hit) => !hit.own) && row.occluders.length === 0) row.occluders.push("paint-order-not-visible");
    }
  } finally {
    for (const { el, value, priority } of old) { if (value) el.style.setProperty("pointer-events", value, priority); else el.style.removeProperty("pointer-events"); }
  }
  for (const row of marked) {
    const completeProbes = row.expectedProbes > 0 && row.skippedProbes.length === 0 && row.hits.length === row.expectedProbes;
    row.category = !row.shown || !row.whole || !row.viewportWhole ? "out-of-view" : row.occluders.length > 0 ? "covered"
      : completeProbes && row.hits.every((hit) => hit.own) ? "shown" : "paint-unavailable";
    row.hitCoverage = row.expectedProbes === 0 ? "not-measured" : completeProbes ? "complete" : "partial";
    delete row.el;
  }
  // Read the separate canonical pane, stripping its computed-by annotation, not HUD/mark flags.
  const canonicalRows = [...document.querySelectorAll(".dp-kv__row")].filter((r) => text(r.querySelector("dt")) === "Newly stranded");
  let universe = null;
  if (canonicalRows.length === 1) {
    const copy = canonicalRows[0].querySelector("dd")?.cloneNode(true);
    copy?.querySelectorAll(".visually-hidden, button").forEach((n) => n.remove());
    const value = text(copy);
    universe = value === "none" ? [] : copy?.querySelector(".dp-mono") ? value.split(", ") : null;
  }
  const wanted = new Set(universe ?? []);
  const selectedDevice = new URL(location.href).searchParams.get("d");
  for (const row of marked) if (!wanted.has(row.host) && row.id !== selectedDevice) {
    row.hitSummary = { count: row.hits.length, own: row.hits.filter((hit) => hit.own).length };
    delete row.hits; // Non-subject boxes still remain as independent occlusion inputs.
  }
  const hud = stage.querySelector("[data-stranded-total]");
  const state = hud?.getAttribute("data-mark-report") ?? stage.getAttribute("data-mark-report");
  const attr = (name) => hud?.hasAttribute(name) ? hud.getAttribute(name) : null;
  const categoryNames = (label) => {
    const match = new RegExp(`(?: · |^)\\d+ ${label}: ([^·]+)`).exec(text(hud));
    return match ? match[1].trim().split(", ") : [];
  };
  const glyph = window.__atlasScene?.terminalGlyphScreenBox?.() ?? null;
  const glyphBox = glyph === null ? null : { host: glyph.host, x: cr.x + glyph.x0, y: cr.y + glyph.y0, w: glyph.x1 - glyph.x0, h: glyph.y1 - glyph.y0 };
  return { stage: sr, canvas: cr, documentScroll: { x: scrollX, y: scrollY }, labels: marked, universe,
    hud: hud ? { text: text(hud), title: hud.getAttribute("title"), state, total: attr("data-stranded-total"), shown: attr("data-stranded-shown"),
      outOfView: attr("data-stranded-out-of-view"), unseen: attr("data-stranded-unseen"), covered: attr("data-stranded-covered"),
      cut: attr("data-cut-mark"), outNames: categoryNames("out of view"), coveredNames: categoryNames("covered") } : null,
    reportState: state, glyph: glyphBox, sceneConverged: window.__atlasScene?.stats?.().converged === true,
    reportBinding: [stage, stage.querySelector(".fabric3d__labels")].map((node) => node ? {
      className: node.className, state: node.getAttribute("data-mark-report"), subject: node.getAttribute("data-mark-report-subject"),
      scope: node.getAttribute("data-mark-report-scope"), epoch: node.getAttribute("data-mark-report-epoch"),
    } : null),
    controls: controls.map((node) => ({ text: text(node), rect: rect(node), pointerEvents: getComputedStyle(node).pointerEvents })),
    url: location.href, canonicalRows: canonicalRows.length };
}
function assertObservation(observation, target, phase) {
  check(!observation.error, `${phase}: ${observation.error}`);
  check(observation.stage.w > 0 && observation.stage.h > 0, `${phase}: unmeasured actual stage`);
  if (observation.universe === null) {
    check(!observation.hud || !/all \d+ marked/.test(observation.hud.text), `${phase}: unreadable canonical radius cannot certify all marked`);
    return;
  }
  const wanted = observation.universe;
  const rows = wanted.map((host) => observation.labels.find((r) => r.host === host));
  check(rows.every(Boolean), `${phase}: canonical stranded host missing from label denominator`);
  const category = (row, cue) => !row[cue] ? "out-of-view" : row.category;
  const buckets = Object.fromEntries(["shown", "out-of-view", "covered"].map((key) => [key, rows.filter((r) => category(r, "strandedCuePainted") === key).map((r) => r.host).sort()]));
  const hud = observation.hud;
  const diagnostic = { phase, target, claimed: hud, actualBuckets: buckets, universe: wanted,
    stage: observation.stage, canvas: observation.canvas, documentScroll: observation.documentScroll,
    reportBinding: observation.reportBinding, controls: observation.controls.slice(0, 32),
    labels: rows.filter(Boolean).slice(0, 64).map((row) => ({ id: row.id, host: row.host, box: row.box,
      shown: row.shown, stageWhole: row.whole, viewportWhole: row.viewportWhole, category: row.category,
      strandedCuePainted: row.strandedCuePainted, coveredFlagDiagnostic: row.diagnosticCoveredFlag,
      clippedFlagDiagnostic: row.diagnosticClippedFlag, occluders: row.occluders, hitCoverage: row.hitCoverage,
      hitCount: row.hits?.length ?? row.hitSummary?.count ?? 0,
      ownHitCount: row.hits?.filter((hit) => hit.own).length ?? row.hitSummary?.own ?? 0 })),
    labelsOmitted: Math.max(0, rows.filter(Boolean).length - 64) };
  if (wanted.length === 0 && !hud) return; // genuine NO_BLAST, not fabricated cut-only coverage
  check(hud, `${phase}: actual positive radius has no reporting HUD`);
  if (hud.state === "pending" || hud.state === "unmeasured") {
    check(!/all \d+ marked/.test(hud.text) && hud.cut !== "shown", `${phase}: pending/unmeasured report certifies marks`);
    return;
  }
  check(hud.state === "ready", `${phase}: report does not state ready/pending/unmeasured`);
  report.counters.readyReports += 1;
  check(rows.every((row) => row.category !== "paint-unavailable"), `${phase}: ready stranded marks have unavailable/partial actual paint coverage; legibility not verified`);
  check(Number(hud.total) === wanted.length && Number(hud.shown) === buckets.shown.length
    && Number(hud.outOfView) === buckets["out-of-view"].length && Number(hud.covered) === buckets.covered.length,
  `${phase}: HUD counts disagree with actual rendered geometry/paint order`, diagnostic);
  check(JSON.stringify([...hud.outNames].sort()) === JSON.stringify(buckets["out-of-view"])
    && JSON.stringify([...hud.coveredNames].sort()) === JSON.stringify(buckets.covered), `${phase}: HUD host lists disagree with actual marks`, diagnostic);
  const cut = !target.startsWith("L") && wanted.length > 0 ? observation.labels.find((r) => r.host === target) : null;
  if (cut) {
    check(cut.category !== "paint-unavailable", `${phase}: cut mark paint coverage is unavailable/partial`);
    check(hud.cut === category(cut, "cutCuePainted"), `${phase}: cut mark state disagrees with actual cue/box/paint order`);
  }
  if (observation.glyph) {
    const g = observation.glyph;
    for (const label of observation.labels.filter((r) => r.shown && r.whole)) {
      const b = label.box;
      check(!(b.x < g.x + g.w && b.x + b.w > g.x && b.y < g.y + g.h && b.y + b.h > g.y), `${phase}: label covers the actual renderer terminal glyph box`);
    }
    report.counters.glyphChecks += 1;
  }
  report.counters.geometryChecks += rows.length + Number(Boolean(cut));
}
async function observations(page, target, name, frames = 12) {
  const values = await page.evaluate(async (count) => {
    const out = [];
    for (let i = 0; i < count; i += 1) { await new Promise((done) => requestAnimationFrame(done)); out.push(window.__a6ObserveScene()); }
    return out;
  }, frames);
  for (const [index, value] of values.entries()) {
    report.observations.push({ name, index, ...value });
    try { assertObservation(value, target, `${name} frame ${index}`); } catch (error) { failures(error, name); }
  }
  report.counters.transitionFrames += values.length;
  save();
  return values.at(-1);
}
async function settle(page) {
  await page.waitForFunction(() => window.__atlasScene?.stats?.().converged === true, null, { timeout: WAIT });
  // Every fresh navigation/theme context reaches this before gestures or captures; later settles reuse the terminal phase.
  await awaitPaletteWarm(page);
}
async function select(page, id) {
  if (id.startsWith("L")) {
    const row = await linkInFabricList(page, id);
    await row.click();
    await page.waitForFunction((target) => new URL(location.href).searchParams.get("l") === target, id, { timeout: WAIT });
    await closeFabricList(page);
    return;
  }
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Command palette", exact: true });
  await expect(dialog).toBeVisible();
  const input = dialog.getByRole("combobox", { name: "Search commands, devices, findings and paths", exact: true });
  await input.fill(id);
  const results = dialog.getByRole("listbox", { name: "Results", exact: true });
  const options = results.getByRole("option"); await expect(options.first()).toBeVisible();
  const at = await options.evaluateAll((nodes, target) => nodes.findIndex((node) => {
    const text = node.querySelector(".palette__row-label")?.textContent?.trim() ?? "";
    return text === target || text.startsWith(`${target} `) || text.startsWith(`${target}\u00a0`);
  }), id);
  check(at >= 0, `real palette has no named ${id} option`); await options.nth(at).click();
  await page.waitForFunction((target) => new URL(location.href).searchParams.get(target.startsWith("L") ? "l" : "d") === target, id, { timeout: WAIT });
}
async function linkInFabricList(page, id) {
  const stage = page.locator(".fabric3d");
  const toggle = stage.getByRole("button", { name: "Fabric list", exact: true });
  if (await toggle.getAttribute("aria-pressed") !== "true") await toggle.click();
  const panel = stage.getByTestId("fabric3d-tree");
  await expect(panel).toHaveAttribute("data-hidden", "false");
  const tree = panel.getByRole("tree", { name: "Fabric list", exact: true });
  await expect(tree).toBeVisible();
  const row = tree.locator('[role="treeitem"][data-kind="link"][data-target="' + id + '"]').first();
  if (await row.count() === 0) {
    for (const kind of ["tier", "device"]) {
      const parents = tree.locator('[role="treeitem"][data-kind="' + kind + '"]');
      const count = await parents.count();
      for (let i = 0; i < count; i += 1) {
        const parent = parents.nth(i);
        if (await parent.getAttribute("aria-expanded") !== "false") continue;
        await parent.focus(); await page.keyboard.press("ArrowRight");
        await expect(parent).toHaveAttribute("aria-expanded", "true");
      }
    }
  }
  await expect(row).toBeVisible();
  check(await row.getAttribute("aria-disabled") !== "true", `real Fabric list link ${id} is disabled`);
  return row;
}
async function closeFabricList(page) {
  const panel = page.locator(".fabric3d").getByTestId("fabric3d-tree");
  if (await panel.getAttribute("data-hidden") !== "false") return;
  await panel.getByRole("button", { name: "Hide", exact: true }).click();
  await expect(panel).toHaveAttribute("data-hidden", "true");
}
async function viewportState(page) {
  return page.evaluate(() => {
    const canvas = document.querySelector(".fabric3d canvas"), stage = document.querySelector(".fabric3d");
    if (!canvas || !stage) return null;
    const box = (el) => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };
    const r = canvas.getBoundingClientRect(); const ports = [];
    for (let node = canvas.parentElement; node; node = node.parentElement) {
      ports.push({ id: node.id, tag: node.tagName, className: node.className, left: node.scrollLeft, top: node.scrollTop });
    }
    const visibleWidth = Math.max(0, Math.min(innerWidth, r.right) - Math.max(0, r.left));
    const visibleHeight = Math.max(0, Math.min(innerHeight, r.bottom) - Math.max(0, r.top));
    const query = document.querySelector("#query-bar");
    const querybar = query ? { rect: box(query), text: (query.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 2048),
      hasEmptySentence: Boolean(query.querySelector(".qbar__empty")), hasTokens: Boolean(query.querySelector(".qbar__tokens")) } : null;
    const app = document.querySelector(".app"), body = document.querySelector(".app__body"), dock = document.querySelector("#inspector");
    return { canvas: box(canvas), stage: box(stage), onScreenPixels: visibleWidth * visibleHeight, ports, querybar,
      layout: { app: app ? box(app) : null, appRows: app ? getComputedStyle(app).gridTemplateRows : null,
        body: body ? box(body) : null, inspector: dock ? { rect: box(dock), display: getComputedStyle(dock).display } : null },
      activeElement: { tag: document.activeElement?.tagName ?? null, id: document.activeElement?.id ?? null },
      url: location.href,
      document: { left: document.scrollingElement?.scrollLeft ?? 0, top: document.scrollingElement?.scrollTop ?? 0 } };
  });
}
async function observableCamera(page) {
  return page.evaluate(() => {
    const canvas = document.querySelector(".fabric3d canvas"), scene = window.__atlasScene;
    if (!canvas || !scene || typeof scene.project !== "function") return null;
    const r = canvas.getBoundingClientRect();
    return { width: r.width, height: r.height,
      anchors: ["core1", "core2", "dist1", "dist2", "access4", "access10"].map((id) => ({ id, point: scene.project(id) })) };
  });
}
function cameraChange(before, after) {
  check(before && after && before.width > 0 && before.height > 0 && after.width > 0 && after.height > 0, "observable camera unavailable");
  let paired = 0, maximumDriftCssPx = 0, visibilityChanges = 0;
  for (const [index, row] of before.anchors.entries()) {
    const next = after.anchors[index]; check(next?.id === row.id, "camera probe denominator changed");
    if (!row.point || !next.point) { if (Boolean(row.point) !== Boolean(next.point)) visibilityChanges += 1; continue; }
    paired += 1;
    if (row.point.visible !== next.point.visible) visibilityChanges += 1;
    maximumDriftCssPx = Math.max(maximumDriftCssPx, Math.hypot(next.point.x - row.point.x, next.point.y - row.point.y));
  }
  check(paired > 0, "camera probe has no paired observable anchor");
  return { paired, maximumDriftCssPx, visibilityChanges,
    changed: maximumDriftCssPx > 0.5 || visibilityChanges > 0,
    sizeUnchanged: Math.abs(before.width - after.width) <= 0.5 && Math.abs(before.height - after.height) <= 0.5 };
}
function assertCanvasNotScrolled(before, after, name) {
  check(before && after && before.onScreenPixels > 0 && after.onScreenPixels > 0, `${name}: canvas was moved off screen`);
  check(before.document.left === after.document.left && before.document.top === after.document.top, `${name}: document scrollport moved`);
  check(before.ports.length === after.ports.length && before.ports.every((port, index) => {
    const next = after.ports[index]; return port.id === next.id && port.tag === next.tag
      && port.left === next.left && port.top === next.top;
  }), `${name}: outer canvas-carrying scrollport moved`);
  check(Math.abs(after.canvas.x - before.canvas.x) <= 1 && Math.abs(after.canvas.y - before.canvas.y) <= 1,
    `${name}: canvas on-screen origin moved despite unchanged document scroll`, { criterion: "canvas-origin", before, after });
}
async function canvasSelect(page, id) {
  // Clear before locating chassis geometry, so a changed selection cannot make the points stale.
  await page.locator(".fabric3d canvas").evaluate((node) => node.focus({ preventScroll: true })); await page.keyboard.press("Escape");
  await page.waitForFunction(() => {
    const selected = new URL(location.href).searchParams;
    return !selected.has("d") && !selected.has("l");
  }, null, { timeout: WAIT });
  await settle(page);
  const points = await page.evaluate((target) => {
    const canvas = document.querySelector(".fabric3d canvas"), scene = window.__atlasScene, b = scene?.chassisScreenBox?.(target);
    if (!canvas || !b || typeof scene.pick !== "function") return { points: [], candidates: [] };
    const r = canvas.getBoundingClientRect(); const out = [], candidates = [];
    for (const x of [0.5, 0.3, 0.7]) for (const y of [0.65, 0.5, 0.8]) {
      const point = { x: r.left + b.x0 + (b.x1 - b.x0) * x, y: r.top + b.y0 + (b.y1 - b.y0) * y };
      const top = document.elementFromPoint(point.x, point.y);
      const pick = top === canvas ? scene.pick(point.x, point.y) : null;
      const genuine = top === canvas && pick?.kind === "device" && pick.id === target;
      candidates.push({ ...point, hitTag: top?.tagName ?? null, hitClass: typeof top?.className === "string" ? top.className : null, pick, genuine });
      if (genuine) out.push(point);
    }
    return { points: out, candidates };
  }, id);
  check(points.points.length > 0, `mandatory ${id} canvas selection has no actual hit-testable chassis point`, { target: id, candidates: points.candidates });
  const before = await viewportState(page);
  const point = points.points[0];
  report.observations.push({ name: `canvas-selection-${id}-before`, before, selectedPoint: point, candidates: points.candidates }); save();
  // One actual click, then the product's deferred cross-surface/URL commit.
  // A protocol roundtrip immediately after pointerup is not that commit.
  await page.mouse.click(point.x, point.y);
  try {
    await page.waitForFunction((target) => new URL(location.href).searchParams.get("d") === target, id, { timeout: WAIT });
  } catch (error) {
    let after = null, captureError = null;
    try { after = await viewportState(page); } catch (diagnosticError) { captureError = String(diagnosticError); }
    error.a6Diagnostic = { criterion: "deferred-canvas-selection", target: id, point, before, after, captureError };
    throw error;
  }
  const after = await viewportState(page);
  assertCanvasNotScrolled(before, after, `canvas selection of ${id}`);
  report.counters.canvasSelections += 1;
  return { before, after, selectedPoint: point, hitTestablePoints: points.points.length };
}
async function enter(page, target) {
  const canvas = page.locator(".fabric3d canvas");
  if (!target.startsWith("L")) { await canvas.evaluate((node) => node.focus({ preventScroll: true })); await page.keyboard.press("Enter"); return "canvas Enter"; }
  // Canvas Enter frames devices. Links use their real Fabric-list Enter route, not a fake device pin.
  const tree = await linkInFabricList(page, target);
  await expect(tree).toBeVisible(); await tree.focus(); await page.keyboard.press("Enter");
  await page.waitForFunction((id) => new URL(location.href).searchParams.get("l") === id, target, { timeout: WAIT });
  await closeFabricList(page);
  return "Fabric-list link Enter (actual selection route; current product does not frame links on Enter)";
}
async function ensureFabric(page) {
  const show = page.getByRole("button", { name: "Show the 3-D fabric", exact: true });
  if (await show.count()) await show.click();
  await expect(page.locator(".fabric3d canvas")).toBeVisible();
  await page.locator(".fabric3d canvas").scrollIntoViewIfNeeded();
  await settle(page);
}
async function keyboardReveal(page, name) {
  const grid = page.locator("#rail-queue .ag__grid");
  await expect(grid).toBeAttached();
  const entry = grid.locator('[tabindex="0"]').first();
  await expect(entry).toBeAttached(); await entry.focus();
  // Ctrl+Home selects the logical header (ARIA1); End selects the last body row.
  // A roving stop
  // left near the end by selection is not a declared positive scroll challenge.
  await page.keyboard.press("Control+Home");
  await page.waitForFunction(() => {
    const active = document.activeElement, g = document.querySelector("#rail-queue .ag__grid");
    const header = active?.closest('[role="columnheader"]'), row = header?.closest('[role="row"]');
    return Boolean(active && g?.contains(active) && header && row?.classList.contains("ag__row--head")
      && row.getAttribute("aria-rowindex") === "1");
  }, null, { timeout: WAIT });
  const state = () => grid.evaluate((g) => {
    const active = document.activeElement, cell = active?.closest('[role="gridcell"],[role="rowheader"],[role="columnheader"]');
    const r = active?.getBoundingClientRect(); const ports = [];
    for (let node = g; node; node = node.parentElement) {
      const cs = getComputedStyle(node), b = node.getBoundingClientRect();
      ports.push({ id: node.id, tag: node.tagName, className: node.className, left: node.scrollLeft, top: node.scrollTop,
        overflowY: cs.overflowY, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight,
        rect: { x: b.x, y: b.y, w: b.width, h: b.height } });
    }
    return { own: g.scrollTop, doc: scrollY, ports, rowCount: Number(g.getAttribute("aria-rowcount")),
      rowIndex: Number(active?.closest('[role="row"]')?.getAttribute("aria-rowindex")),
      colIndex: Number(cell?.getAttribute("aria-colindex")), cellRole: cell?.getAttribute("role") ?? null,
      headerRow: Boolean(cell?.closest('[role="row"]')?.classList.contains("ag__row--head")), inGrid: Boolean(active && g.contains(active)),
      top: r?.top, bottom: r?.bottom, activeText: active?.textContent?.slice(0, 512), viewport: innerHeight };
  });
  const before = await state();
  check(before.inGrid && before.rowIndex === 1 && before.cellRole === "columnheader" && before.headerRow && before.rowCount > 1,
    `${name}: mandatory keyboard Home header start premise failed`, before);
  await page.keyboard.press("Control+End");
  await page.waitForFunction((lastRow) => {
    const active = document.activeElement, grid = document.querySelector("#rail-queue .ag__grid");
    if (!active || !grid?.contains(active)) return false;
    const cell = active.closest('[role="gridcell"],[role="rowheader"]');
    const row = cell?.closest('[role="row"]');
    const r = active.getBoundingClientRect();
    return Boolean(cell && row && Number(row.getAttribute("aria-rowindex")) === lastRow
      && r.top >= 0 && r.bottom <= innerHeight);
  }, before.rowCount, { timeout: WAIT });
  const after = await state();
  check(after.inGrid && after.top >= 0 && after.bottom <= after.viewport, `${name}: keyboard focus did not reveal a whole cell`);
  check(after.rowCount === before.rowCount && after.rowIndex === after.rowCount,
    `${name}: actual Control+End did not reach the predeclared last row`, { before, after });
  check(before.ports.length === after.ports.length && before.ports.every((port, i) => {
    const next = after.ports[i]; return port.id === next.id && port.tag === next.tag && port.className === next.className;
  }), `${name}: keyboard scrollport denominator changed`, { before, after });
  check(after.doc !== before.doc || after.ports.some((port, i) => port.top !== before.ports[i].top || port.left !== before.ports[i].left),
    `${name}: mandatory keyboard reveal did not exercise a scroll`, { before, after });
  report.counters.keyboardReveal += 1;
  report.observations.push({ name: `${name}-keyboard-positive`, before, after }); save();
}
// Raw raster attempt is explicitly optional: a cleared default buffer is not a canvas measurement.
async function rawCanvasSingle(page, name) {
  const observed = await page.evaluate(async () => {
    const c = document.querySelector(".fabric3d canvas"); if (!c) return null;
    for (let i = 0; i < 30; i += 1) {
      await new Promise((done) => requestAnimationFrame(done));
      const gl = c.getContext("webgl2"); if (!gl || gl.getParameter(gl.FRAMEBUFFER_BINDING) !== null) return null;
      const w = c.width, h = c.height; if (!(w > 0 && h > 0 && w * h <= 4_000_000)) return null;
      const bytes = new Uint8Array(w * h * 4); gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
      let variable = false;
      for (let k = 4; k < bytes.length; k += 4) if (bytes[k] !== bytes[0] || bytes[k + 1] !== bytes[1] || bytes[k + 2] !== bytes[2]) { variable = true; break; }
      if (!variable || !window.__atlasScene?.stats?.().converged || gl.getError() !== gl.NO_ERROR) continue;
      const anchors = ["core1", "core2", "dist1", "dist2", "access4", "access10"].map((id) => ({ id, point: window.__atlasScene?.project?.(id) ?? null }));
      const rect = c.getBoundingClientRect();
      let text = ""; for (let k = 0; k < bytes.length; k += 32768) text += String.fromCharCode(...bytes.subarray(k, k + 32768));
      return { w, h, base64: btoa(text), anchors, canvasRect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
        quality: window.__atlasScene?.stats?.().quality ?? null, method: "readPixels RGBA from actual default WebGL framebuffer" };
    }
    return null;
  });
  if (observed === null) { report.optionalCoverage.push(`${name}: valid stable raw canvas framebuffer unavailable; pixel criterion unverified`); return null; }
  const raw = Buffer.from(observed.base64, "base64"); check(raw.length === observed.w * observed.h * 4, "raster length mismatch");
  const file = `${name}.rgba.deflate`; writeFileSync(join(output, file), deflateSync(raw), { flag: "wx", mode: 0o600 });
  return { w: observed.w, h: observed.h, raw, file, sha256: sha(raw), method: observed.method,
    anchors: observed.anchors, canvasRect: observed.canvasRect, quality: observed.quality };
}
function sameObservablePose(a, b) {
  if (!a || !b || a.w !== b.w || a.h !== b.h || a.quality !== b.quality) return false;
  if (["x", "y", "w", "h"].some((key) => Math.abs(a.canvasRect[key] - b.canvasRect[key]) > 0.5)) return false;
  return a.anchors.length === 6 && a.anchors.every((anchor, index) => {
    const other = b.anchors[index];
    return anchor.id === other.id && anchor.point && other.point && anchor.point.visible === other.point.visible
      && Math.abs(anchor.point.x - other.point.x) <= 0.5 && Math.abs(anchor.point.y - other.point.y) <= 0.5;
  });
}
async function rawCanvas(page, name) {
  const first = await rawCanvasSingle(page, `${name}-repeat1`);
  const second = await rawCanvasSingle(page, `${name}-repeat2`);
  if (!sameObservablePose(first, second)) {
    report.optionalCoverage.push(`${name}: repeated raw captures lack a fixed observable pose/tier/size; pixel criterion unverified`); return null;
  }
  const repeatDifference = difference(first, second);
  if (repeatDifference.fraction > 0.001) {
    report.optionalCoverage.push(`${name}: repeated raw captures exceed declared 0.1% stability tolerance; pixel criterion unverified`); return null;
  }
  report.observations.push({ name: `${name}-raster-stability`, first: { file: first.file, sha256: first.sha256 },
    second: { file: second.file, sha256: second.sha256 }, anchors: second.anchors, canvasRect: second.canvasRect,
    quality: second.quality, repeatDifference, maximumChangedFraction: 0.001, maximumAnchorDriftCssPx: 0.5 });
  return second;
}
const difference = (a, b) => {
  check(a.w === b.w && a.h === b.h, "pixel-control canvas dimensions changed"); let changed = 0;
  for (let i = 0; i < a.raw.length; i += 4) if (Math.max(Math.abs(a.raw[i] - b.raw[i]), Math.abs(a.raw[i + 1] - b.raw[i + 1]), Math.abs(a.raw[i + 2] - b.raw[i + 2])) > 12) changed += 1;
  return { changedPixels: changed, pixels: a.w * a.h, fraction: changed / (a.w * a.h), thresholdPerChannel: 12 };
};

let server, browser, before;
      try {
  check(git("rev-parse", "HEAD") === expectedCommit && process.env.GITHUB_SHA === expectedCommit && git("status", "--porcelain") === "", "source/context must be exact and clean");
  before = materialSet();
  const model = JSON.parse(ordinary(join(PKG, "src/data/fabric.json")).toString("utf8"));
  report.source = { commit: expectedCommit, tree: git("rev-parse", "HEAD^{tree}"), materials: before,
    harnessSha256: sha(ordinary(fileURLToPath(import.meta.url))), githubHeadRef: process.env.GITHUB_HEAD_REF ?? "", runId: process.env.GITHUB_RUN_ID,
    attempt: process.env.GITHUB_RUN_ATTEMPT, nodeVersion: process.version, runnerEnvironment: process.env.RUNNER_ENVIRONMENT,
    sampleBinding: model.meta, playwrightVersion: JSON.parse(ordinary(join(PKG, "node_modules/@playwright/test/package.json")).toString("utf8")).version };
  const html = ordinary(join(PKG, "dist/index.html")).toString("utf8");
  check(!/<link[^>]*modulepreload[^>]*three-/i.test(html), "F4: renderer chunk must not be preloaded by initial HTML");
  let occupied = false; try { await fetch(ORIGIN, { signal: AbortSignal.timeout(1000) }); occupied = true; } catch { /* required absent owned preview */ }
  check(!occupied, "preview port already occupied");
  server = spawn(process.execPath, [join(PKG, "node_modules/vite/bin/vite.js"), "preview", "--host", "127.0.0.1", "--port", "4189", "--strictPort"], { cwd: PKG, stdio: ["ignore", "pipe", "pipe"] });
  let log = ""; for (const stream of [server.stdout, server.stderr]) stream.on("data", (raw) => { log += raw.toString(); writeFileSync(join(output, "preview.log"), log); });
  const deadline = Date.now() + WAIT;
  while (true) {
    check(server.exitCode === null && Date.now() < deadline, "owned preview failed to start");
    try { const res = await fetch(ORIGIN, { signal: AbortSignal.timeout(1000) }); if (res.ok) break; } catch { /* bounded startup */ }
    await new Promise((done) => setTimeout(done, 100));
  }
  report.buildFreshness = await checkBuildFreshness(ORIGIN);
  check(report.buildFreshness.fresh && report.buildFreshness.servesLocalDist && !report.buildFreshness.devServer, "fresh production bundle required");
  browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] }); report.source.chromiumVersion = browser.version();
  for (const viewport of VIEWPORTS) for (const theme of THEME) {
    const prefix = `${viewport.width}x${viewport.height}-${theme}`;
    const ctx = await browser.newContext({ viewport, colorScheme: theme, deviceScaleFactor: 1 });
    const errors = [], forbidden = [], requests = [];
    try {
      await ctx.route("**/*", (route) => {
        const u = new URL(route.request().url());
        if (u.origin === ORIGIN || ["blob:", "data:"].includes(u.protocol)) return route.continue();
        forbidden.push(u.href); return route.abort("blockedbyclient");
      });
      await ctx.addInitScript((choice) => { try { localStorage.setItem("atlas-scope.theme", choice); } catch { /* opaque pre-navigation context */ } window.__atlasExposeScene = true; }, theme);
      const page = await ctx.newPage(); page.setDefaultTimeout(WAIT);
      page.on("pageerror", (error) => errors.push(String(error))); page.on("request", (r) => requests.push(r.url()));
      await page.goto(`${ORIGIN}/?__atlasScene=1`, { waitUntil: "load" }); await expect(page.locator("#rail-queue .ag__grid")).toBeAttached();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      if (viewport.width < 768) check(!requests.some((url) => /\/three-[^/]+\.js/.test(url)), `${prefix}: F4 renderer fetched before explicit phone toggle`);
      await page.evaluate(`window.__a6ObserveScene = ${observeScene.toString()}`);
      await ensureFabric(page);
      for (const target of TARGETS) {
        const name = `${prefix}-${target}`;
        const current = { name, target, viewport, theme, status: "FAIL", gestures: [], failures: [] }; report.cases.push(current);
        try {
          if (!target.startsWith("L")) {
            await page.locator(".fabric3d canvas").evaluate((node) => node.focus({ preventScroll: true })); await page.keyboard.press("Home"); await settle(page);
            current.canvasSelection = await canvasSelect(page, target);
          } else await select(page, target);
          await observations(page, target, `${name}-selection-transition`);
          await settle(page); const baseline = await page.evaluate(observeScene); assertObservation(baseline, target, name);
          check(baseline.canonicalRows === 1, `${name}: separate canonical pane did not identify its radius`);
          if (!target.startsWith("L")) check(baseline.universe?.length > 0, `${name}: mandatory device articulation control has no readable positive radius`);
          if (baseline.universe?.length > 0) check(baseline.reportState === "ready", `${name}: settled positive radius never obtained a fresh ready report`);
          report.counters.subjects += 1;
          await page.locator(".fabric3d canvas").evaluate((node) => node.focus({ preventScroll: true }));
          await page.keyboard.press("Home"); await settle(page);
          const homeBaseline = await observableCamera(page);
          for (const action of ["enter", "zoom", "orbit", "home"]) {
            const canvas = page.locator(".fabric3d canvas"); await canvas.evaluate((node) => node.focus({ preventScroll: true }));
            const scrollBefore = await viewportState(page);
            const poseBefore = await observableCamera(page);
            let route = "canvas key";
            if (action === "enter") route = await enter(page, target);
            else await page.keyboard.press(action === "zoom" ? "+" : action === "orbit" ? "Shift+ArrowLeft" : "Home");
            await observations(page, target, `${name}-${action}-transition`);
            await settle(page); const state = await page.evaluate(observeScene); assertObservation(state, target, `${name}-${action}`);
            if (state.universe?.length > 0) check(state.reportState === "ready", `${name}-${action}: settled positive report remains pending/unmeasured`);
            const scrollAfter = await viewportState(page);
            const poseAfter = await observableCamera(page);
            const effect = cameraChange(poseBefore, poseAfter);
            if (action === "zoom" || action === "orbit" || (action === "enter" && !target.startsWith("L"))) {
              check(effect.sizeUnchanged && effect.changed, `${name}-${action}: dispatched key had no verified camera effect`);
            }
            const returned = action === "home" ? cameraChange(homeBaseline, poseAfter) : null;
            if (returned) check(returned.sizeUnchanged && !returned.changed, `${name}: Home failed to restore the predeclared overview pose`);
            if (action !== "enter" || !target.startsWith("L")) assertCanvasNotScrolled(scrollBefore, scrollAfter, `${name}-${action}`);
            report.counters[action] += 1; current.gestures.push({ action, route, scrollBefore, scrollAfter, poseBefore, poseAfter, effect, homeBaseline, returned, observation: state });
            await page.screenshot({ path: join(output, `${name}-${action}.png`), fullPage: false }); save();
          }
          current.status = "PASS";
        } catch (error) {
          current.failures.push(String(error)); failures(error, name);
          try { await page.screenshot({ path: join(output, `${name}-failure.png`), fullPage: false }); } catch { /* failure retained without unavailable pixels */ }
        }
      }
      // Predeclared non-articulation controls. No dynamic cherry-picking of a convenient pixel comparison.
      await page.locator(".fabric3d canvas").evaluate((node) => node.focus({ preventScroll: true })); await page.keyboard.press("Escape"); await page.keyboard.press("Home"); await settle(page);
      const base = await rawCanvas(page, `${prefix}-pixel-baseline`); const probes = {};
      for (const target of ["core1", ...PIXEL_CONTROLS]) {
        await select(page, target); await page.locator(".fabric3d canvas").evaluate((node) => node.focus({ preventScroll: true })); await page.keyboard.press("Home"); await settle(page);
        const oracle = await page.evaluate(observeScene);
        check(oracle.universe !== null && (target === "core1" ? oracle.universe.length > 0 : oracle.universe.length === 0), `${prefix}: predeclared pixel articulation/control premise failed`);
        probes[target] = await rawCanvas(page, `${prefix}-pixel-${target}`);
        if (target !== "core1") {
          check(!oracle.hud || !/all \d+ marked/.test(oracle.hud.text), `${prefix}: genuine zero-impact control fabricated a cut/stranded report`);
          report.observations.push({ name: `${prefix}-zero-impact-${target}`, ...oracle });
        }
      }
      if (probes.core1 && PIXEL_CONTROLS.every((target) => probes[target])
        && PIXEL_CONTROLS.every((target) => sameObservablePose(probes.core1, probes[target]))) {
        const articulationPairs = PIXEL_CONTROLS.map((target) => ({ left: "core1", right: target, ...difference(probes.core1, probes[target]) }));
        const nonArticulationPair = { left: "dist1", right: "dist2", ...difference(probes.dist1, probes.dist2) };
        const relation = articulationPairs.every((pair) => pair.fraction > nonArticulationPair.fraction);
        report.canvasPixelCriterion.comparisons.push({ prefix, articulationPairs, nonArticulationPair, articulationExceedsControls: relation,
          clearedBaselineDiagnostic: base && sameObservablePose(base, probes.core1) ? difference(base, probes.core1) : null,
          criterionOwner: "atlas-scope/docs/acceptance.md:A6",
          interpretation: "Both articulation/non-articulation pairs must exceed the non-articulation/non-articulation pair on the same observable pose. Raw canvas only; no acceptance promotion." });
        if (!relation) {
          report.canvasPixelCriterion.status = "PIXEL_RELATION_REFUTED";
          failures(new Error(`${prefix}: measured articulation/non-articulation canvas difference did not exceed dist1/dist2`), "canvas-pixel-criterion");
        }
      } else report.optionalCoverage.push(`${prefix}: raw pixel controls lacked a stable identical drawing-buffer size; criterion unverified`);
      await keyboardReveal(page, prefix);
      check(errors.length === 0 && forbidden.length === 0, `${prefix}: page errors or forbidden external requests`);
      report.observations.push({ name: `${prefix}-browser`, pageErrors: errors, forbiddenRequests: forbidden });
    } catch (error) { failures(error, prefix); } finally { await ctx.close(); save(); }
  }
  check(report.counters.subjects === 24 && report.counters.canvasSelections === 12 && ["enter", "zoom", "orbit", "home"].every((key) => report.counters[key] === 24)
    && report.counters.readyReports > 0 && report.counters.geometryChecks > 0 && report.counters.keyboardReveal === 6, "mandatory browser case/gesture/report controls incomplete");
  const comparisons = report.canvasPixelCriterion.comparisons;
  report.canvasPixelCriterion.status = comparisons.some((r) => !r.articulationExceedsControls) ? "PIXEL_RELATION_REFUTED"
    : comparisons.length === 6 ? "BOUNDED_PIXEL_RELATION_OBSERVED" : "UNVERIFIED";
  report.optionalCoverage.push("Cut-only app state is not fabricated: independent product unit cut-only/mutation controls remain required when the real current dataset yields no such UI state.");
  report.optionalCoverage.push("A5 terminal glyph checks run only when an actual trace glyph exists. Existing A5/B5/C6 and B3 hosted controls remain separately required; this harness does not claim those unexecuted trace branches.");
  check(git("rev-parse", "HEAD") === expectedCommit && git("status", "--porcelain") === "" && JSON.stringify(materialSet()) === JSON.stringify(before), "source changed during hosted witness");
  report.source.materialsStableAfter = true;
  report.status = report.failures.length === 0 ? "BOUNDED_A6_REPAIR_WITNESS_PASS" : "FAIL";
} catch (error) { failures(error, "harness"); } finally {
  if (browser) await browser.close();
  if (server && server.exitCode === null) {
    server.kill("SIGTERM"); await Promise.race([new Promise((done) => server.once("close", done)), new Promise((done) => setTimeout(done, 3000))]);
    if (server.exitCode === null && server.signalCode === null) server.kill("SIGKILL");
  }
  report.finishedAt = new Date().toISOString(); save();
  try {
    const names = readdirSync(output).sort();
    check(names.length <= 180 && names.every((name) => /^(?:a6-mark-visibility\.json|preview\.log|(?:390x844|768x1024|1440x900)-(?:light|dark)-[A-Za-z0-9_-]+\.(?:png|rgba\.deflate))$/.test(name)), "unexpected/oversized evidence inventory");
    let total = 0;
    const members = {};
    for (const name of names) {
      const raw = ordinary(join(output, name), 32 * 1024 * 1024); total += raw.length;
      check(total <= 64 * 1024 * 1024, "evidence exceeds closed transfer bound");
      members[name] = { bytes: raw.length, sha256: sha(raw) };
    }
    writeFileSync(join(output, "a6-output-manifest.json"), `${JSON.stringify({ schema: "atlas-scope.a6-output/1", expectedCommit, members,
      totalBytes: total, releaseAuthority: false, selfApproval: false }, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  } catch (error) {
    failures(error, "evidence-inventory"); report.status = "FAIL"; save();
  }
}
console.log(JSON.stringify({ status: report.status, counters: report.counters, pixelCriterion: report.canvasPixelCriterion.status, failures: report.failures }));
process.exitCode = report.status === "BOUNDED_A6_REPAIR_WITNESS_PASS" ? 0 : 1;
