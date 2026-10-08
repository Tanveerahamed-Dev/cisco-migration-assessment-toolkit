/** W26: actual compact/Device-grouped PriorityQueue focus witness on the exact current hosted source. */
import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, constants, existsSync, fstatSync, lstatSync, mkdirSync, openSync, readFileSync, readSync, realpathSync, writeFileSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { checkBuildFreshness } from "./build-freshness.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = realpathSync(resolve(PKG, ".."));
const SELF = "atlas-scope/review/verify-grid-focus.mjs";
const PORT = 4189, ORIGIN = `http://127.0.0.1:${PORT}`, WAIT_MS = 30000;
const MAX_BYTES = 16 * 1024 * 1024;
const SHARED = ["webapp/frontend/src/projectionEmbed.ts", "webapp/frontend/src/generated/openapi.ts", "webapp/frontend/src/test/projectionFixtures.ts"];
const sha = (raw) => createHash("sha256").update(raw).digest("hex");
const check = (ok, message) => { if (!ok) throw new Error(message); };
export const CASES = Object.freeze(["data-wheel", "group-wheel", "never-entered-query", "left-grid-query", "header-wheel", "tab-reentry", "filter-transitions", "repeated-copies"]);
const PHASES = Object.freeze({
  "data-wheel": ["setup", "focused", "after-wheel", "after-arrow", "after-page"],
  "group-wheel": ["setup", "focused", "after-wheel", "after-arrow", "after-page"],
  "never-entered-query": ["setup", "query-focused", "after-wheel"],
  "left-grid-query": ["setup", "entered", "query-focused", "after-wheel"],
  "header-wheel": ["setup", "focused", "after-wheel"],
  "tab-reentry": ["setup", "entered", "query-focused", "after-wheel", "reentered"],
  "filter-transitions": ["setup", "shrink", "empty", "recovery"],
  "repeated-copies": ["setup", "copies", "first-copy", "second-copy"],
});

export function exactArguments(args) {
  check(args.length === 4 && args[0] === "--expected-commit" && /^[0-9a-f]{40}$/.test(args[1])
    && args[2] === "--output" && isAbsolute(args[3]), "exact --expected-commit SHA --output ABSOLUTE arguments required");
  return { expectedCommit: args[1], output: args[3] };
}
export function retentionFailures(before, after) {
  const failures = [];
  if (before?.active?.inGrid !== true || before.target?.connected !== true || before.target?.isActive !== true) failures.push("original focus premise missing");
  if (after?.target?.connected !== true) failures.push("original focused DOM node was detached");
  if (after?.target?.isActive !== true || after?.active?.inGrid !== true) failures.push("original node no longer owns grid focus");
  if (typeof before?.target?.identity !== "string" || after?.target?.identity !== before.target.identity) failures.push("logical row/column/control identity changed");
  if (after?.tabstops?.length !== 1) failures.push("grid must retain exactly one tabstop");
  if (after?.target?.tabIndex !== 0 || after?.target?.soleStopMatchesTarget !== true
    || after?.tabstops?.[0]?.identity !== after?.target?.identity) failures.push("sole tabstop is not the retained focused control");
  return failures;
}
const finite = (n) => typeof n === "number" && Number.isFinite(n);
const rect = (r) => r && ["x", "y", "width", "height", "top", "bottom", "left", "right"].every((k) => finite(r[k])) && r.width >= 0 && r.height >= 0;
const identityValid = (value, grid = true) => value && typeof value.tag === "string" && value.tag.length > 0
  && (value.role === null || typeof value.role === "string") && typeof value.label === "string"
  && (value.dataCol === null || typeof value.dataCol === "string") && typeof value.findingId === "string" && typeof value.group === "string"
  && (grid ? Number.isInteger(value.row) && value.row >= 1 && Number.isInteger(value.col) && value.col >= 1
    && ["data", "group", "header"].includes(value.rowKind) : value.row === null && value.col === null && value.rowKind === null)
  && value.identity === JSON.stringify({ tag: value.tag, role: value.role, label: value.label, row: value.row, col: value.col,
    dataCol: value.dataCol, findingId: value.findingId, group: value.group });
export function frameFailures(state, targetRequired = false) {
  const errors = [];
  if (!state || state.missingGrid !== false || !Number.isInteger(state.logicalRows) || state.logicalRows < 1
    || state.logicalBodyRows !== state.logicalRows - 1 || state.rowsComplete !== true || !Array.isArray(state.rows)
    || state.rows.length !== state.mountedBodyRows || state.rows.length > state.logicalBodyRows
    || new Set(state.rows.map((row) => row.index)).size !== state.rows.length
    || state.rows.some((row) => !Number.isInteger(row.index) || row.index < 2 || row.index > state.logicalRows || !["data", "group"].includes(row.kind) || !rect(row.box))) errors.push("missing or incoherent logical/mounted row census");
  if (!state?.grid || !rect(state.grid.box) || !finite(state.grid.scrollTop) || state.grid.scrollTop < 0 || !finite(state.grid.scrollLeft)
    || !finite(state.grid.clientHeight) || state.grid.clientHeight <= 0 || !finite(state.grid.scrollHeight) || state.grid.scrollHeight < state.grid.clientHeight
    || !rect(state.header) || !state.viewport || !["width", "height", "x", "y"].every((k) => finite(state.viewport[k]))
    || state.viewport.width <= 0 || state.viewport.height <= 0 || !Array.isArray(state.ancestors) || state.ancestors.length === 0
    || state.ancestors.some((a) => !rect(a.box) || !finite(a.scrollTop) || !finite(a.scrollLeft))
    || !Array.isArray(state.spacers) || state.spacers.some((s) => !rect(s))) errors.push("missing finite geometry/scroll evidence");
  if (!state?.active || typeof state.active.inGrid !== "boolean" || typeof state.active.query !== "boolean" || !Array.isArray(state.tabstops)
    || state.tabstops.some((s) => !identityValid(s))) errors.push("missing focus/tabstop identity census");
  if (!identityValid(state?.active?.description, state?.active?.inGrid === true)
    || (state?.active?.inGrid && state.active.description.row > state.logicalRows)) errors.push("invalid active control identity");
  if (!state?.focusHistory || state.focusHistory.installed !== true || !Array.isArray(state.focusHistory.events) || state.focusHistory.overflow !== false
    || state.focusHistory.events.some((e, index) => e.sequence !== index + 1 || typeof e.inGrid !== "boolean" || typeof e.query !== "boolean" || !finite(e.at))) errors.push("missing/incomplete passive focus history");
  if (targetRequired && (!state?.target || typeof state.target.connected !== "boolean" || typeof state.target.isActive !== "boolean"
    || typeof state.target.identity !== "string" || !state.target.identity || !Number.isInteger(state.target.tabIndex)
    || typeof state.target.soleStopMatchesTarget !== "boolean")) errors.push("missing original-node evidence");
  const p = state?.pageGeometry, firstData = state?.rows?.find((row) => row.kind === "data");
  if (!p || !finite(p.top) || !finite(p.bottom) || typeof p.fallbackUsed !== "boolean" || !p.clipped
    || !finite(p.clipped.top) || !finite(p.clipped.bottom) || !Array.isArray(p.edgeProbes)
    || p.dataRowHeight !== (firstData?.box?.height ?? null)) errors.push("missing/incoherent measured page geometry");
  return errors;
}
export function normalWindow(state) {
  check(frameFailures(state).length === 0, "normal window needs a complete measured frame");
  const count = state.logicalBodyRows, start = Math.max(0, Math.min(count, Math.floor(state.grid.scrollTop / 32) - 8));
  return { start, end: Math.max(start, Math.min(count, Math.ceil((state.grid.scrollTop + state.grid.clientHeight) / 32) + 8)),
    rowEstimatePx: 32, overscan: 8, count };
}
export function beyondWindowFailures(before, after, originRow) {
  if (frameFailures(before).length || frameFailures(after).length || !Number.isInteger(originRow)) return ["window exclusion lacks complete evidence"];
  const normal = normalWindow(after), originalBodyIndex = originRow - 2;
  const failures = [];
  if (!(after.grid.scrollTop > before.grid.scrollTop) || normal.start === 0) failures.push("wheel did not move the normal body window");
  if (originRow !== 1 && originalBodyIndex >= normal.start && originalBodyIndex < normal.end) failures.push("original logical row is still inside normal overscan interval");
  const mounted = new Set(after.rows.map((row) => row.index));
  if (normal.end <= normal.start || Array.from({ length: normal.end - normal.start }, (_, i) => i + normal.start + 2).some((i) => !mounted.has(i))) failures.push("mounted rows do not corroborate normal interval");
  if (!after.spacers.some((s) => s.height > 0) || after.mountedBodyRows >= after.logicalBodyRows) failures.push("normal interval has no actual windowing/spacer evidence");
  return failures;
}
export function pageDestination(before) {
  check(frameFailures(before).length === 0 && before.active.inGrid, "PageDown requires a complete active grid frame");
  const p = before.pageGeometry;
  check(p && finite(p.top) && finite(p.bottom) && finite(p.dataRowHeight) && p.dataRowHeight >= 1 && p.bottom > p.top,
    "PageDown requires measured clipped band and data-row height");
  const step = Math.max(1, Math.floor((p.bottom - p.top) / p.dataRowHeight) - 1);
  return { from: before.active.description.row, step, row: Math.min(before.logicalRows, before.active.description.row + step), geometry: p };
}
export function pageFailures(before, after) {
  try {
    const destination = pageDestination(before);
    return frameFailures(after).length === 0 && after.active.inGrid && after.active.description.row === destination.row
      && after.tabstops.length === 1 && after.tabstops[0].identity === after.active.description.identity ? [] : ["PageDown differs from the measured page destination"];
  } catch (error) { return [String(error)]; }
}
export function caseEvidenceFailures(item) {
  const errors = [];
  if (!Array.isArray(item.pageErrors) || item.pageErrors.length || !Array.isArray(item.forbiddenRequests) || item.forbiddenRequests.length) errors.push("retained browser error or forbidden request");
  for (const row of item.observations ?? []) {
    if (row.errors?.length || row.status !== "COMPLETE") errors.push(`${row.phase}: incomplete capture`);
    const requiredTarget = ["data-wheel", "group-wheel", "header-wheel"].includes(item.id) && row.phase !== "setup";
    errors.push(...frameFailures(row.state, requiredTarget).map((e) => `${row.phase}: ${e}`));
    errors.push(...frameFailures(row.afterImageState, requiredTarget).map((e) => `${row.phase} after image: ${e}`));
  }
  const at = (phase) => item.observations?.find((row) => row.phase === phase)?.afterImageState;
  const final = at("final"), focus = at("focused"), after = at("after-wheel"), initial = at("setup");
  if (initial?.density !== "compact" || initial?.grouping !== "host") errors.push("compact Device-grouping premise missing");
  if (CASES.indexOf(item.id) < 6 && !(initial?.logicalBodyRows > 200 && initial.mountedBodyRows < initial.logicalBodyRows && initial.spacers?.some((s) => s.height > 0))) errors.push("high-row virtualization premise missing");
  if (CASES.indexOf(item.id) < 6) {
    const original = focus ?? at("query-focused");
    errors.push(...beyondWindowFailures(original, after, focus?.active?.description?.row ?? original?.tabstops?.[0]?.row));
    if (!Array.isArray(item.wheelSamples) || item.wheelSamples.length === 0) errors.push("missing wheel sample history");
    else for (const [index, sample] of item.wheelSamples.entries()) {
      errors.push(...frameFailures(sample.state, Boolean(focus)));
      if (index > 0 && !(sample.state?.grid?.scrollTop >= item.wheelSamples[index - 1].state?.grid?.scrollTop)) errors.push("retained wheel snapback sample");
      if (focus) errors.push(...retentionFailures(focus, sample.state));
      else if (!sample.state?.active?.query) errors.push("retained outside-focus loss");
    }
    if (after?.tabstops?.length !== 1) errors.push("missing unique wheel tabstop");
  }
  if (["data-wheel", "group-wheel", "header-wheel"].includes(item.id)) {
    errors.push(...retentionFailures(focus, after));
    errors.push(...retentionFailures(focus, item.observations?.find((row) => row.phase === "after-wheel")?.state));
    if (item.id === "header-wheel") errors.push(...retentionFailures(focus, final));
    else {
      const arrow = at("after-arrow"), paged = at("after-page");
      if (!arrow?.active?.inGrid || arrow.active.description?.row !== focus?.active?.description?.row + 1) errors.push("ArrowDown did not preserve logical continuation");
      errors.push(...pageFailures(item.pageInput, paged));
      if (!final?.active?.inGrid || final.tabstops?.length !== 1 || final.tabstops[0].identity !== final.active.description?.identity
        || final.active.description?.identity !== paged?.active?.description?.identity) errors.push("final key focus/tabstop contradiction");
    }
  }
  if (["never-entered-query", "left-grid-query", "filter-transitions"].includes(item.id) && final?.active?.query !== true) errors.push("final outside query focus was lost");
  if (item.id === "never-entered-query" && (!final?.focusHistory || final.focusHistory.events.some((e) => e.inGrid) || !final.focusHistory.events.some((e) => e.query))) errors.push("never-entered premise lacks complete passive query-focus history");
  if (item.id === "never-entered-query" && item.observations?.some((row) => [row.state, row.afterImageState].some((state) => state?.focusHistory?.events?.some((e) => e.inGrid)))) errors.push("an earlier captured grid entry contradicts never-entered status");
  if (item.id === "tab-reentry" && (!final?.active?.inGrid || final.tabstops?.[0]?.identity !== final.active.description?.identity
    || final.active.description?.identity !== at("reentered")?.active?.description?.identity)) errors.push("final reentry identity contradiction");
  if (item.id === "filter-transitions" && !(at("shrink")?.logicalBodyRows < initial?.logicalBodyRows
    && at("shrink")?.rows?.some((r) => r.kind === "data") && at("empty")?.rows?.every((r) => r.kind !== "data")
    && at("empty")?.emptyResult?.includes("No findings match") && at("recovery")?.logicalRows === initial?.logicalRows
    && final?.logicalRows === initial?.logicalRows && final?.tabstops?.length === 1)) errors.push("filter subphase measurement mismatch");
  if (item.id === "repeated-copies" && !(at("copies")?.logicalBodyRows <= 200 && at("copies")?.mountedBodyRows === at("copies")?.logicalBodyRows
    && at("first-copy")?.active?.inGrid && at("second-copy")?.active?.inGrid && at("first-copy")?.active?.description?.row !== at("second-copy")?.active?.description?.row
    && final?.active?.description?.identity === at("second-copy")?.active?.description?.identity)) errors.push("filtered repeated-copy phase mismatch");
  const finalBeforeImage = item.observations?.find((row) => row.phase === "final")?.state;
  if (item.id === "header-wheel") errors.push(...retentionFailures(focus, finalBeforeImage));
  else if (finalBeforeImage?.active?.inGrid !== final?.active?.inGrid || finalBeforeImage?.active?.query !== final?.active?.query
    || finalBeforeImage?.active?.description?.identity !== final?.active?.description?.identity) errors.push("focus changed during the final captured observation");
  return errors;
}
export function completeVerdict(cases, globalFailures) {
  return globalFailures.length === 0 && cases.length === CASES.length && cases.every((item, index) =>
    item.id === CASES[index] && item.status === "PASS" && item.failures.length === 0
    && new Set(item.observations.map((row) => row.phase)).size === item.observations.length
    && item.observations.every((row) => [...PHASES[item.id], "final"].includes(row.phase))
    && caseEvidenceFailures(item).length === 0
    && [...PHASES[item.id], "final"].every((phase) => item.observations.some((row) => row.phase === phase && row.image
      && row.image.file === `${item.id}-${phase}.png` && Number.isInteger(row.image.bytes) && row.image.bytes > 0
      && /^[0-9a-f]{64}$/.test(row.image.sha256)))) ? "PASS" : "FAIL";
}
const inside = (parent, child) => {
  const value = relative(parent, child);
  return value === "" || (!isAbsolute(value) && value !== ".." && !value.startsWith(`..${sep}`));
};
const gitBytes = (...args) => {
  const result = spawnSync("git", ["--no-optional-locks", ...args], { cwd: REPO, timeout: WAIT_MS, maxBuffer: MAX_BYTES });
  check(result.status === 0, `Git ${args[0]} read failed`);
  return result.stdout;
};
const git = (...args) => gitBytes(...args).toString("utf8").trim();
function canonical(input) {
  check(isAbsolute(input), "absolute output path required");
  let parent = resolve(input);
  const tail = [];
  while (!existsSync(parent)) { tail.unshift(basename(parent)); parent = dirname(parent); }
  return resolve(realpathSync(parent), ...tail);
}
function ordinary(path) {
  check(typeof constants.O_NOFOLLOW === "number" && typeof constants.O_NONBLOCK === "number", "Linux descriptor flags required");
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(fd, { bigint: true });
    check(before.isFile() && before.nlink === 1n && before.size <= BigInt(MAX_BYTES) && canonical(path) === resolve(path), "nonordinary or oversized source file");
    const parts = [], chunk = Buffer.alloc(64 * 1024); let total = 0;
    while (total <= MAX_BYTES) {
      const count = readSync(fd, chunk, 0, Math.min(chunk.length, MAX_BYTES + 1 - total), null);
      if (count === 0) break;
      parts.push(Buffer.from(chunk.subarray(0, count))); total += count;
    }
    check(total <= MAX_BYTES, "source exceeded descriptor read bound");
    const bytes = Buffer.concat(parts, total);
    const after = fstatSync(fd, { bigint: true }), named = lstatSync(path, { bigint: true });
    check(named.isFile() && ["dev", "ino", "mode", "nlink", "size", "mtimeNs", "ctimeNs"].every((k) => before[k] === after[k] && before[k] === named[k])
      && bytes.length === Number(before.size), "source file changed during read");
    return bytes;
  } finally { closeSync(fd); }
}
function entries(ref, paths, index = false) {
  const rows = gitBytes(...(index ? ["ls-files", "--stage", "-z"] : ["ls-tree", "-r", "-z", ref]), "--", ...paths).toString("utf8").split("\0").filter(Boolean);
  const found = {};
  for (const row of rows) {
    const tab = row.indexOf("\t"), header = row.slice(0, tab).split(" "), path = row.slice(tab + 1);
    const [mode, second, third] = header, blob = index ? second : third;
    check(tab > 0 && header.length === 3 && ["100644", "100755"].includes(mode) && (index ? third === "0" : second === "blob")
      && /^[0-9a-f]{40}$/.test(blob) && !isAbsolute(path) && !path.includes("\\") && !path.split("/").some((v) => ["", ".", ".."].includes(v))
      && !Object.hasOwn(found, path), "invalid source mode/path/blob/census");
    found[path] = { mode, blob };
  }
  return Object.fromEntries(Object.entries(found).sort(([a], [b]) => a.localeCompare(b)));
}
export function rootTsconfigFamily(ref, readTree = entries) {
  return Object.fromEntries(Object.entries(readTree(ref, ["atlas-scope"]))
    .filter(([path]) => /^atlas-scope\/tsconfig[^/]*\.json$/.test(path)));
}
function source(expectedCommit) {
  check(git("rev-parse", "HEAD") === expectedCommit && process.env.GITHUB_SHA === expectedCommit, "checkout and declared hosted commit differ");
  check(/^[0-9]+$/.test(process.env.GITHUB_RUN_ID ?? "") && /^[1-9][0-9]*$/.test(process.env.GITHUB_RUN_ATTEMPT ?? "")
    && typeof process.env.GITHUB_JOB === "string" && process.env.GITHUB_JOB.length > 0, "hosted run/attempt/job identity required");
  check(git("status", "--porcelain") === "", "selected source checkout is dirty");
  const paths = ["atlas-scope", ...SHARED, "webapp/sample_data/sample_fleet.snapshot.json", ".github/workflows/atlas-scope-ci.yml", ".github/scripts/scope_compile_handoff.py"];
  const head = entries(expectedCommit, paths);
  check(Object.hasOwn(head, SELF) && Object.keys(head).length > 0 && JSON.stringify(head) === JSON.stringify(entries("HEAD", paths, true)), "tracked source/index closure differs");
  const flags = gitBytes("ls-files", "-v", "-z", "--", ...paths).toString("utf8").split("\0").filter(Boolean);
  check(flags.length === Object.keys(head).length && flags.every((row) => row.startsWith("H ")), "hidden or unsupported source index flags");
  const materials = {};
  for (const [path, identity] of Object.entries(head)) {
    const bytes = ordinary(join(REPO, path)), committed = gitBytes("cat-file", "blob", `${expectedCommit}:${path}`);
    check(bytes.equals(committed), "worktree source differs from its committed blob");
    materials[path] = { ...identity, bytes: bytes.length, sha256: sha(bytes) };
  }
  const configurationFamily = rootTsconfigFamily(expectedCommit);
  const indexFamily = rootTsconfigFamily(expectedCommit, (ref, selected) => entries(ref, selected, true));
  check(["tsconfig.json", "tsconfig.config.json", "tsconfig.scripts.json"].every((name) => Object.hasOwn(configurationFamily, `atlas-scope/${name}`))
    && JSON.stringify(configurationFamily) === JSON.stringify(indexFamily), "current configuration family/index closure differs");
  check(git("rev-parse", "HEAD") === expectedCommit && git("status", "--porcelain") === "", "source changed during current-source binding");
  return { commit: expectedCommit, tree: git("rev-parse", `${expectedCommit}^{tree}`), configurationFamily, currentSourceOnly: true,
    actualProbeSourceIsHistoricalReplay: false, githubSha: process.env.GITHUB_SHA, prHead: process.env.PR_HEAD_SHA ?? null,
    runId: process.env.GITHUB_RUN_ID, attempt: process.env.GITHUB_RUN_ATTEMPT, job: process.env.GITHUB_JOB,
    event: process.env.GITHUB_EVENT_NAME, githubRef: process.env.GITHUB_REF, runner: process.env.RUNNER_ENVIRONMENT,
    node: process.version, materials };
}

async function frame(page, target) {
  const state = await page.evaluate(() => {
    const grid = document.querySelector('[role="grid"][aria-label="Findings, ranked"]');
    if (!(grid instanceof HTMLElement)) return { missingGrid: true };
    const box = (node) => { const r = node?.getBoundingClientRect(); return r ? { x: r.x, y: r.y, width: r.width, height: r.height, top: r.top, bottom: r.bottom, left: r.left, right: r.right } : null; };
    const text = (node) => (node?.textContent ?? "").replace(/\s+/g, " ").trim();
    const identify = (node) => {
      if (!(node instanceof HTMLElement)) return null;
      const cell = node.closest('[role="gridcell"],[role="rowheader"],[role="columnheader"]'), row = cell?.closest('[role="row"]');
      const base = { tag: node.tagName, role: node.getAttribute("role"), label: node.getAttribute("aria-label") ?? text(node),
        row: row ? Number(row.getAttribute("aria-rowindex")) : null, col: cell ? Number(cell.getAttribute("aria-colindex")) : null,
        dataCol: cell?.getAttribute("data-col") ?? null,
        findingId: text(row?.querySelector(".pq-id")), group: text(row?.querySelector(".ag__grouplabel")) };
      return { ...base, identity: JSON.stringify(base), rowKind: !row ? null : row.classList.contains("ag__row--group") ? "group" : row.classList.contains("ag__row--head") ? "header" : "data" };
    };
    const rows = [...grid.querySelectorAll('.ag__body [role="row"]')];
    const allStops = [...grid.querySelectorAll('[tabindex],button,a[href],input,select,textarea')].filter((node) => node instanceof HTMLElement && node.tabIndex === 0);
    const ancestors = [];
    for (let node = grid; node; node = node.parentElement) {
      const css = getComputedStyle(node);
      ancestors.push({ tag: node.tagName, id: node.id, scrollTop: node.scrollTop, scrollLeft: node.scrollLeft,
        clientHeight: node.clientHeight, clientWidth: node.clientWidth, scrollHeight: node.scrollHeight, scrollWidth: node.scrollWidth,
        overflowX: css.overflowX, overflowY: css.overflowY, position: css.position,
        borderTop: css.borderTopWidth, borderBottom: css.borderBottomWidth, box: box(node) });
    }
    const gridBox = box(grid), headerBox = box(grid.querySelector(".ag__head"));
    let top = Math.max(gridBox.top, headerBox?.bottom ?? gridBox.top), bottom = gridBox.bottom;
    const rootOverflow = getComputedStyle(document.documentElement).overflowY;
    for (let node = grid.parentElement; node; node = node.parentElement) {
      if (node === document.documentElement || (node === document.body && ["", "visible"].includes(rootOverflow))) continue;
      const r = box(node);
      if (!["", "visible"].includes(getComputedStyle(node).overflowY) && r.height > 0) { top = Math.max(top, r.top); bottom = Math.min(bottom, r.bottom); }
    }
    top = Math.max(top, 0); bottom = Math.min(bottom, innerHeight);
    const edgeProbes = [], x = Math.min(Math.max((Math.max(gridBox.left, 0) + Math.min(gridBox.right, innerWidth - 1)) / 2, 0), innerWidth - 1);
    const covers = (y) => {
      const rectangles = [];
      for (const node of document.elementsFromPoint(x, y)) {
        if (grid.contains(node) || node.contains(grid)) break;
        rectangles.push(box(node));
      }
      edgeProbes.push({ x, y, covers: rectangles });
      return rectangles;
    };
    for (let i = 0; i < 4 && bottom > top; i++) { const next = Math.min(bottom, ...covers(bottom - 1).filter((r) => r.top > top).map((r) => r.top)); if (next >= bottom) break; bottom = next; }
    for (let i = 0; i < 4 && bottom > top; i++) { const next = Math.max(top, ...covers(top + 1).filter((r) => r.bottom < bottom).map((r) => r.bottom)); if (next <= top) break; top = next; }
    const clipped = { top, bottom }, fallbackUsed = bottom <= top;
    if (fallbackUsed) { top = Math.max(gridBox.top, headerBox?.bottom ?? gridBox.top); bottom = gridBox.bottom; }
    return { missingGrid: false, logicalRows: Number(grid.getAttribute("aria-rowcount")), logicalBodyRows: Number(grid.getAttribute("aria-rowcount")) - 1,
      density: grid.parentElement?.getAttribute("data-density"), grouping: document.querySelector('.pq-controls select')?.value,
      busy: grid.getAttribute("aria-busy"), grid: { box: box(grid), scrollTop: grid.scrollTop, scrollLeft: grid.scrollLeft, clientHeight: grid.clientHeight, scrollHeight: grid.scrollHeight },
      header: box(grid.querySelector(".ag__head")), statusBar: box(document.querySelector("#status-bar")),
      viewport: { width: innerWidth, height: innerHeight, x: scrollX, y: scrollY }, ancestors,
      pageGeometry: { top, bottom, clipped, fallbackUsed, edgeProbes, dataRowHeight: box(grid.querySelector('.ag__row--data'))?.height ?? null },
      focusHistory: window.__w26PassiveFocus ?? null,
      mountedBodyRows: rows.length, rowsComplete: rows.length <= 2000, rows: rows.slice(0, 2000).map((row) => ({ index: Number(row.getAttribute("aria-rowindex")),
        kind: row.classList.contains("ag__row--group") ? "group" : "data", findingId: text(row.querySelector(".pq-id")), group: text(row.querySelector(".ag__grouplabel")),
        box: box(row), borderTop: getComputedStyle(row).borderTopWidth, borderBottom: getComputedStyle(row).borderBottomWidth })),
      spacers: [...grid.querySelectorAll('.ag__body > [role="presentation"]')].map((row) => box(row)),
      tabstops: allStops.map(identify), active: { inGrid: grid.contains(document.activeElement), query: document.activeElement?.matches('.pq-query__input') === true,
        description: identify(document.activeElement), tag: document.activeElement?.tagName ?? null },
      query: document.querySelector('.pq-query__input')?.value ?? null, emptyResult: document.querySelector('.pq-empty')?.textContent ?? null };
  });
  state.target = target ? await target.evaluate((node) => {
    const text = (el) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
    const cell = node.closest('[role="gridcell"],[role="rowheader"],[role="columnheader"]'), row = cell?.closest('[role="row"]');
    const rect = node.getBoundingClientRect();
    const grid = node.closest('[role="grid"]');
    const stops = [...(grid?.querySelectorAll('[tabindex],button,a[href],input,select,textarea') ?? [])].filter((el) => el instanceof HTMLElement && el.tabIndex === 0);
    return { connected: node.isConnected, isActive: document.activeElement === node,
      tabIndex: node.tabIndex, soleStopMatchesTarget: stops.length === 1 && stops[0] === node,
      identity: JSON.stringify({ tag: node.tagName, role: node.getAttribute("role"), label: node.getAttribute("aria-label") ?? text(node),
        row: Number(row?.getAttribute("aria-rowindex")), col: Number(cell?.getAttribute("aria-colindex")), dataCol: cell?.getAttribute("data-col") ?? null,
        findingId: text(row?.querySelector(".pq-id")), group: text(row?.querySelector(".ag__grouplabel")) }),
      box: { top: rect.top, bottom: rect.bottom, height: rect.height } };
  }) : null;
  return state;
}
async function settle(page, target = null, observations = [], persist = () => {}) {
  let prior = null, stable = 0;
  for (let i = 0; i < 60; i++) {
    await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
    const current = await frame(page, target);
    const sample = { at: new Date().toISOString(), state: current };
    observations.push(sample); persist(sample, observations.length - 1);
    const signature = JSON.stringify([current.grid?.scrollTop, current.logicalRows, current.rows?.map((row) => row.index), current.busy]);
    stable = signature === prior && current.busy !== "true" ? stable + 1 : 0;
    if (stable >= 3) return;
    prior = signature;
  }
  throw new Error("grid/scroll did not stabilize within the fixed frame census");
}
async function enterByTab(page, item, persist = () => {}) {
  for (let i = 0; i < 80; i++) {
    await page.keyboard.press("Tab");
    const observation = await frame(page, null);
    const sample = { active: observation.active, scrollTop: observation.grid?.scrollTop, focusHistory: observation.focusHistory };
    item.tabs.push(sample); persist(sample, item.tabs.length - 1);
    if (observation.active?.inGrid === true) return;
  }
  throw new Error("ordinary Tab never reached the grid within 80 destinations");
}
async function setQuery(page, text) {
  const input = page.getByRole("combobox", { name: "Filter findings", exact: true });
  await input.click();
  await input.fill(text);
  await settle(page);
}
async function setup(page) {
  await page.goto(ORIGIN, { waitUntil: "load" });
  await page.locator('.hdr-surface').filter({ has: page.locator('.hdr-surface__label', { hasText: /^Findings$/ }) }).click();
  const queue = page.getByRole("region", { name: "Priority queue", exact: true });
  const group = queue.getByLabel("Group", { exact: true });
  if (!await group.isVisible()) await queue.getByRole("button", { name: "View", exact: true }).click();
  await group.selectOption({ label: "Device" });
  await queue.getByRole("button", { name: "Display", exact: true }).click();
  const toggle = page.getByRole("switch", { name: "Two-line rows", exact: true });
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await page.keyboard.press("Escape");
  await settle(page);
  await expect(page.getByRole("grid", { name: "Findings, ranked", exact: true })).toBeVisible();
}

export async function main(args = process.argv.slice(2)) {
  check(process.env.GITHUB_ACTIONS === "true" && process.env.RUNNER_ENVIRONMENT === "github-hosted" && process.platform === "linux", "GitHub-hosted Linux execution only");
  const { expectedCommit, output: requested } = exactArguments(args), output = canonical(requested);
  const protectedRoots = git("worktree", "list", "--porcelain", "-z").split("\0").filter((line) => line.startsWith("worktree ")).map((line) => canonical(line.slice(9)));
  protectedRoots.push(REPO, canonical(git("rev-parse", "--path-format=absolute", "--git-common-dir")));
  check(existsSync(dirname(output)) && !existsSync(output) && protectedRoots.every((root) => !inside(root, output) && !inside(output, root)), "fresh output must be outside all worktrees and common Git data");
  mkdirSync(output, { mode: 0o700 });
  const write = (name, raw) => {
    check(/^[a-z0-9.-]+$/.test(name) && raw.length <= MAX_BYTES, "bounded fixed output member required");
    const fd = openSync(join(output, name), constants.O_CREAT | constants.O_WRONLY | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    try { writeFileSync(fd, raw); } finally { closeSync(fd); }
  };
  const report = { schema: "atlas-scope.grid-focus/1", purpose: "current-source-retention-witness", status: "FAIL", expectedCommit,
    acceptanceRegrade: false, archiveCustody: false, historicalReplay: false, startedAt: new Date().toISOString(), source: null, sourceAfter: null,
    buildFreshness: null, configuredThreshold: 200, sourceRowEstimatePx: 32, cases: CASES.map((id) => ({ id, status: "INCOMPLETE", failures: [], observations: [], tabs: [], pageErrors: [], console: [], forbiddenRequests: [] })), failures: [] };
  let browser, server, before, serverLog = "", reportWritten = false;
  const failure = (item, ok, why) => { if (!ok) item.failures.push(why); };
  const save = (name, value, item = null) => {
    try { write(name, Buffer.from(JSON.stringify(value, null, 2) + "\n")); return true; }
    catch (error) {
      const why = `output ${name}: ${String(error)}`;
      (item?.failures ?? report.failures).push(why);
      try { write(`${name}.refusal.json`, Buffer.from(JSON.stringify({ status: "INCOMPLETE", member: name, reason: why }) + "\n")); }
      catch (refusalError) { report.failures.push(`output refusal record: ${String(refusalError)}`); }
      return false;
    }
  };
  const capture = async (item, phase, page, target = null, action = async () => {}) => {
    const row = { phase, at: new Date().toISOString(), status: "INCOMPLETE", errors: [], state: null, afterImageState: null, image: null };
    item.observations.push(row);
    try { check(page && !page.isClosed(), "page is closed; phase not attempted"); await action(); }
    catch (error) { row.errors.push(`action: ${String(error)}`); }
    const original = typeof target === "function" ? target() : target;
    try { row.state = await frame(page, original); }
    catch (error) { row.errors.push(`frame: ${String(error)}`); }
    try { const raw = await page.screenshot({ fullPage: false }); const name = `${item.id}-${phase}.png`; write(name, raw); row.image = { file: name, bytes: raw.length, sha256: sha(raw) }; }
    catch (error) { row.errors.push(`image: ${String(error)}`); }
    try { row.afterImageState = await frame(page, original); }
    catch (error) { row.errors.push(`after-image frame: ${String(error)}`); }
    const targetRequired = ["data-wheel", "group-wheel", "header-wheel"].includes(item.id) && phase !== "setup";
    row.errors.push(...frameFailures(row.state, targetRequired), ...frameFailures(row.afterImageState, targetRequired));
    item.failures.push(...row.errors.map((why) => `${phase}: ${why}`));
    if (row.errors.length === 0) row.status = "COMPLETE";
    save(`${item.id}-${phase}.json`, row, item);
    return row.afterImageState;
  };
  try {
    before = source(expectedCommit); report.source = before;
    check(save("source-before.json", before), "source-before output was not preserved");
    const fabric = JSON.parse(ordinary(join(PKG, "src/data/fabric.json")));
    const repeated = fabric.findings.find((finding) => Array.isArray(finding.devices) && new Set(finding.devices).size >= 2);
    report.subject = { repeatedFinding: repeated?.id ?? null, groups: repeated ? [...new Set(repeated.devices)].sort() : null, sourceSnapshotSha256: fabric.meta.sourceSha256 };
    let occupied = false;
    try { await fetch(ORIGIN, { signal: AbortSignal.timeout(1000) }); occupied = true; } catch { /* no listener required */ }
    check(!occupied, "preview port already occupied");
    server = spawn(process.execPath, [join(PKG, "node_modules/vite/bin/vite.js"), "preview", "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"], { cwd: PKG, stdio: ["ignore", "pipe", "pipe"] });
    server.on("error", (error) => report.failures.push(`preview: ${String(error)}`));
    for (const stream of [server.stdout, server.stderr]) stream.on("data", (raw) => {
      if (Buffer.byteLength(serverLog) + raw.length <= 2 * 1024 * 1024) serverLog += raw.toString("utf8");
      else if (!report.failures.includes("preview log bound exceeded")) report.failures.push("preview log bound exceeded");
    });
    const until = Date.now() + WAIT_MS; let ready = false;
    while (Date.now() < until) {
      check(server.exitCode === null && server.signalCode === null, "owned preview exited before readiness");
      try { if ((await fetch(ORIGIN, { signal: AbortSignal.timeout(1000) })).ok) { ready = true; break; } } catch { /* bounded owned-server startup */ }
      await new Promise((done) => setTimeout(done, 100));
    }
    check(ready, "owned preview readiness timeout");
    report.buildFreshness = await checkBuildFreshness(ORIGIN);
    check(report.buildFreshness.fresh && report.buildFreshness.servesLocalDist === true && report.buildFreshness.devServer === false, "fresh selected production dist required");
    browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
    report.chromium = browser.version();
    report.playwright = JSON.parse(readFileSync(join(PKG, "node_modules/@playwright/test/package.json"), "utf8")).version;
    for (const item of report.cases) {
      let context, page, target;
      try {
        context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
        await context.route("**/*", (route) => {
          const url = new URL(route.request().url());
          if (url.origin === ORIGIN || ["data:", "blob:"].includes(url.protocol)) return route.continue();
          item.forbiddenRequests.push({ url: url.href, method: route.request().method() }); return route.abort("blockedbyclient");
        });
        page = await context.newPage(); page.setDefaultTimeout(WAIT_MS);
        await page.addInitScript(() => {
          const history = { installed: true, events: [], overflow: false };
          Object.defineProperty(window, "__w26PassiveFocus", { value: history, writable: false, configurable: false });
          document.addEventListener("focusin", (event) => {
            if (history.events.length >= 4096) { history.overflow = true; return; }
            const node = event.target, grid = node instanceof Element ? node.closest('[role="grid"][aria-label="Findings, ranked"]') : null;
            history.events.push({ sequence: history.events.length + 1, at: performance.now(), inGrid: grid !== null,
              query: node instanceof Element && node.matches('.pq-query__input'),
              tag: node instanceof Element ? node.tagName : null, role: node instanceof Element ? node.getAttribute("role") : null });
          }, true);
        });
        page.on("pageerror", (error) => item.pageErrors.push(String(error)));
        page.on("console", (message) => { if (["warning", "error"].includes(message.type())) item.console.push({ type: message.type(), text: message.text() }); });
        const initial = await capture(item, "setup", page, null, () => setup(page));
        check(initial && !initial.missingGrid, "no actual grid is available for later stimuli");
        failure(item, (await page.locator('.sb__sha').getAttribute("title"))?.includes(fabric.meta.sourceSha256), "rendered sample identity differs");
        failure(item, initial.density === "compact" && initial.grouping === "host", "ordinary UI failed to select compact Device grouping");
        if (CASES.indexOf(item.id) < 6) failure(item, initial.logicalBodyRows > 200 && initial.mountedBodyRows < initial.logicalBodyRows
          && initial.spacers.some((spacer) => spacer.height > 0), "actual >200-row virtualization premise missing");
        const query = page.getByRole("combobox", { name: "Filter findings", exact: true });
        const persistTabs = (sample, index) => save(`${item.id}-tab-${String(index).padStart(2, "0")}.json`, sample, item);
        if (["filter-transitions", "repeated-copies"].includes(item.id)) {
          const shrunk = await capture(item, item.id === "filter-transitions" ? "shrink" : "copies", page, null, async () => {
            check(repeated && /^F[0-9]+$/.test(repeated.id), "source sample lacks a real multi-device finding control"); await setQuery(page, repeated.id);
          });
          failure(item, shrunk?.logicalBodyRows < initial.logicalBodyRows && shrunk?.rows?.filter((row) => row.kind === "data").length > 0, "filter must produce a smaller positive result");
          failure(item, shrunk?.active?.query, "filter change stole query focus");
          if (item.id === "filter-transitions") {
            const empty = await capture(item, "empty", page, null, () => setQuery(page, "w26-no-matching-finding-sentinel"));
            failure(item, empty?.rows?.every((row) => row.kind !== "data") && empty?.emptyResult?.includes("No findings match"), "empty filter result was not actually observed");
            failure(item, empty?.active?.query, "empty result stole query focus");
            const recovered = await capture(item, "recovery", page, null, () => setQuery(page, ""));
            failure(item, recovered?.logicalRows === initial.logicalRows && recovered?.active?.query && recovered?.tabstops?.length === 1, "recovery did not restore complete rows/sole entry without stealing focus");
          } else {
            item.filteredBelowThreshold = shrunk?.logicalBodyRows <= 200;
            failure(item, item.filteredBelowThreshold && shrunk?.mountedBodyRows === shrunk?.logicalBodyRows, "repeated-copy positive requires a complete below-threshold DOM census");
            const groups = []; let group = null;
            for (const row of shrunk?.rows ?? []) { if (row.kind === "group") group = row.group; else { failure(item, row.findingId === repeated?.id, "filter retained a different finding"); groups.push(group); } }
            failure(item, JSON.stringify([...groups].sort()) === JSON.stringify(report.subject.groups), "copies do not match distinct source device groups");
            const nextCopy = async (previous) => {
              check(shrunk && shrunk.logicalRows <= 2001, "copy traversal lacks bounded source rows");
              for (let i = 0; i < shrunk.logicalRows + 2; i++) {
                await page.keyboard.press("ArrowDown"); await settle(page); const state = await frame(page, null);
                if (state.active.inGrid && state.active.description?.rowKind === "data" && state.active.description.row !== previous) return;
              }
              throw new Error("keyboard did not reach a distinct actual finding copy");
            };
            const first = await capture(item, "first-copy", page, null, async () => { await enterByTab(page, item, persistTabs); await page.keyboard.press("Control+Home"); await nextCopy(null); });
            const second = await capture(item, "second-copy", page, null, () => nextCopy(first?.active?.description?.row));
            failure(item, first?.active?.inGrid && second?.active?.inGrid && first.active.description.row !== second.active.description.row
              && first.active.description.findingId === repeated?.id && second.active.description.findingId === repeated?.id, "keyboard did not distinguish two logical copies");
          }
        } else {
          const enter = async () => { await query.click(); await enterByTab(page, item, persistTabs); await page.keyboard.press("Control+Home"); };
          const outside = ["never-entered-query", "left-grid-query", "tab-reentry"].includes(item.id);
          if (["left-grid-query", "tab-reentry"].includes(item.id)) await capture(item, "entered", page, null, enter);
          const focused = await capture(item, outside ? "query-focused" : "focused", page, () => target, async () => {
            if (outside) { await query.click(); return; }
            await enter();
            if (["data-wheel", "group-wheel"].includes(item.id)) {
              for (let i = 0; i < 25; i++) {
                await page.keyboard.press("ArrowDown"); await settle(page);
                if ((await frame(page, null)).active.description?.rowKind === (item.id === "data-wheel" ? "data" : "group")) break;
              }
            }
            target = await page.locator(":focus").elementHandle(); // Capture ONCE, before wheel; never re-resolve it afterward.
          });
          failure(item, outside ? focused?.active?.query : focused?.active?.inGrid && target !== null, "intended focus premise missing");
          if (!outside) failure(item, focused?.active?.description?.rowKind === (item.id === "header-wheel" ? "header" : item.id === "data-wheel" ? "data" : "group"), "intended logical row kind not reached");
          item.wheelSamples = [];
          const after = await capture(item, "after-wheel", page, target, async () => {
            check(frameFailures(focused).length === 0, "wheel lacks complete original frame");
            const bounds = focused.grid.box, top = Math.max(bounds.top, focused.header.bottom, 0), bottom = Math.min(bounds.bottom, focused.viewport.height);
            check(bottom - top > 40 && bounds.width > 40, "grid has no real wheel target below its sticky header");
            const point = { x: bounds.x + bounds.width / 2, y: top + (bottom - top) / 2 };
            item.wheelTarget = await page.evaluate(({ x, y }) => {
              const hit = document.elementFromPoint(x, y), grid = document.querySelector('[role="grid"][aria-label="Findings, ranked"]');
              return { x, y, inGrid: grid?.contains(hit) === true, tag: hit?.tagName ?? null, role: hit?.getAttribute("role") ?? null };
            }, point);
            check(item.wheelTarget.inGrid, "wheel point is covered by a non-grid surface");
            await page.mouse.move(point.x, point.y);
            await page.mouse.wheel(0, Math.max(focused.grid.clientHeight * 3, 1600));
            await settle(page, target, item.wheelSamples, (sample, index) => save(`${item.id}-wheel-${String(index).padStart(2, "0")}.json`, sample, item));
          });
          const originRow = outside ? focused?.tabstops?.[0]?.row : focused?.active?.description?.row;
          item.failures.push(...beyondWindowFailures(focused, after, originRow));
          if (frameFailures(after).length === 0) { item.normalWindowAfter = normalWindow(after); save(`${item.id}-normal-window.json`, { originRow, normal: item.normalWindowAfter }, item); }
          failure(item, item.wheelSamples.length > 0 && item.wheelSamples.every((row, index, rows) => index === 0 || row.state.grid?.scrollTop >= rows[index - 1].state.grid?.scrollTop), "positive wheel samples missing or moved backward/snapback");
          failure(item, after?.viewport?.x === focused?.viewport?.x && after?.viewport?.y === focused?.viewport?.y, "wheel escaped the grid to document scrolling");
          failure(item, after?.tabstops?.length === 1, "wheel left no unique grid tabstop, including outside/never-entered focus cases");
          if (outside) failure(item, after?.active?.query && item.wheelSamples.every((row) => row.state.active?.query), "wheel stole outside query focus");
          else item.failures.push(...new Set([...retentionFailures(focused, after), ...item.wheelSamples.flatMap((row) => retentionFailures(focused, row.state))]));
          if (["data-wheel", "group-wheel"].includes(item.id)) {
            const arrow = await capture(item, "after-arrow", page, target, async () => { await page.keyboard.press("ArrowDown"); await settle(page); });
            failure(item, arrow?.active?.inGrid && arrow.active.description.row === focused?.active?.description?.row + 1 && arrow.tabstops.length === 1, "ArrowDown did not advance from the original logical row");
            const paged = await capture(item, "after-page", page, target, async () => {
              try { item.pageInput = await frame(page, target); item.pageExpectation = pageDestination(item.pageInput); }
              catch (error) { item.failures.push(`PageDown premise: ${String(error)}`); }
              save(`${item.id}-page-input.json`, { frame: item.pageInput ?? null, expected: item.pageExpectation ?? null }, item);
              await page.keyboard.press("PageDown"); await settle(page);
            });
            item.failures.push(...pageFailures(item.pageInput, paged));
          } else if (item.id === "tab-reentry") {
            const back = await capture(item, "reentered", page, null, () => enterByTab(page, item, persistTabs));
            failure(item, back?.active?.inGrid && back?.tabstops?.length === 1, "ordinary Tab reentry failed");
          }
        }
        failure(item, item.pageErrors.length === 0 && item.forbiddenRequests.length === 0, "browser error or attempted external request");
        item.status = item.failures.length === 0 ? "PASS" : "FAIL";
      } catch (error) { item.failures.push(String(error)); item.status = "INCOMPLETE"; }
      finally {
        for (const phase of PHASES[item.id]) if (!item.observations.some((row) => row.phase === phase)) {
          await capture(item, phase, page, target, async () => { throw new Error("phase not attempted after the recorded prerequisite/action failure"); });
        }
        await capture(item, "final", page, target);
        try { await context?.close(); } catch (error) { item.failures.push(`context cleanup: ${String(error)}`); }
        item.failures.push(...caseEvidenceFailures(item));
        item.status = item.observations.some((row) => row.status !== "COMPLETE") ? "INCOMPLETE" : item.failures.length ? "FAIL" : "PASS";
        if (!save(`${item.id}.json`, item, item)) item.status = "INCOMPLETE";
      }
    }
  } catch (error) { report.failures.push(String(error)); }
  finally {
    try { await browser?.close(); } catch (error) { report.failures.push(`browser cleanup: ${String(error)}`); }
    if (server && server.exitCode === null && server.signalCode === null) {
      server.kill("SIGTERM"); await Promise.race([new Promise((done) => server.once("exit", done)), new Promise((done) => setTimeout(done, 3000))]);
      if (server.exitCode === null && server.signalCode === null) {
        server.kill("SIGKILL"); report.failures.push("preview required forced termination");
        await Promise.race([new Promise((done) => server.once("exit", done)), new Promise((done) => setTimeout(done, 3000))]);
        if (server.exitCode === null && server.signalCode === null) report.failures.push("preview exit not confirmed after SIGKILL");
      }
    }
    try { report.sourceAfter = source(expectedCommit); check(before && JSON.stringify(before) === JSON.stringify(report.sourceAfter), "closing source changed"); }
    catch (error) { report.failures.push(`closing source: ${String(error)}`); }
    try { write("preview.log", Buffer.from(serverLog)); } catch (error) { report.failures.push(`preview log output: ${String(error)}`); }
    report.status = completeVerdict(report.cases, report.failures); report.finishedAt = new Date().toISOString();
    reportWritten = save("grid-focus.json", report);
    if (!reportWritten) report.status = "FAIL";
  }
  console.log(JSON.stringify({ status: report.status, reportWritten, cases: report.cases.map(({ id, status, failures }) => ({ id, status, failures })), failures: report.failures }));
  return report.status === "PASS" ? 0 : 1;
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) process.exitCode = await main();
