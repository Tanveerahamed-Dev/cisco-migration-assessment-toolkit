/** Hosted-only synthetic measurement controls; these are not actual browser evidence. */
import assert from "node:assert/strict";
import { resolve } from "node:path";
import test from "node:test";
import { CASES, beyondWindowFailures, caseEvidenceFailures, completeVerdict, exactArguments, frameFailures, normalWindow, pageDestination, pageFailures, retentionFailures, rootTsconfigFamily } from "./verify-grid-focus-baseline.mjs";

if (process.env.GITHUB_ACTIONS !== "true" || process.env.RUNNER_ENVIRONMENT !== "github-hosted") throw new Error("pure probe controls run only on GitHub-hosted runners");

const box = (top = 0, height = 32) => ({ x: 0, y: top, width: 600, height, top, bottom: top + height, left: 0, right: 600 });
const identity = (row) => {
  const base = { tag: "DIV", role: row === 1 ? "columnheader" : "gridcell", label: "synthetic measured cell", row, col: 1,
    dataCol: "sev", findingId: row > 2 ? "F001" : "", group: row === 2 ? "a" : "" };
  return { ...base, identity: JSON.stringify(base), rowKind: row === 1 ? "header" : row === 2 ? "group" : "data" };
};
const queryIdentity = () => {
  const base = { tag: "INPUT", role: "combobox", label: "Filter findings", row: null, col: null, dataCol: null, findingId: "", group: "" };
  return { ...base, rowKind: null, identity: JSON.stringify(base) };
};
function measured(row = 3, { scroll = 0, origin = row, query = false, count = 400, entered = !query } = {}) {
  const start = Math.max(0, Math.min(count, Math.floor(scroll / 32) - 8));
  const end = Math.max(start, Math.min(count, Math.ceil((scroll + 320) / 32) + 8));
  const indices = new Set(Array.from({ length: end - start }, (_, i) => start + i + 2));
  if (origin >= 2 && origin <= count + 1) indices.add(origin);
  const rows = [...indices].sort((a, b) => a - b).map((index) => ({ index, kind: index === 2 ? "group" : "data", findingId: "F001", group: index === 2 ? "a" : "", box: box((index - 2) * 32 - scroll + 20) }));
  const stop = identity(query ? origin : row);
  const events = [{ sequence: 1, at: 1, inGrid: false, query: true }];
  if (entered) events.push({ sequence: 2, at: 2, inGrid: true, query: false });
  if (entered && query) events.push({ sequence: 3, at: 3, inGrid: false, query: true });
  return { missingGrid: false, logicalRows: count + 1, logicalBodyRows: count, rowsComplete: true, mountedBodyRows: rows.length, rows,
    density: "compact", grouping: "host", busy: null,
    grid: { box: box(0, 340), scrollTop: scroll, scrollLeft: 0, clientHeight: 320, scrollHeight: Math.max(340, count * 32) },
    header: box(0, 20), viewport: { width: 1440, height: 900, x: 0, y: 0 },
    ancestors: [{ box: box(0, 340), scrollTop: scroll, scrollLeft: 0 }], spacers: [box(20, start * 32), box(20, (count - end) * 32)],
    pageGeometry: { top: 20, bottom: 340, dataRowHeight: rows.some((r) => r.kind === "data") ? 32 : null, fallbackUsed: false, clipped: { top: 20, bottom: 340 }, edgeProbes: [] },
    focusHistory: { installed: true, overflow: false, events }, tabstops: [stop],
    active: { inGrid: !query, query, tag: query ? "INPUT" : "DIV", description: query ? queryIdentity() : identity(row) },
    target: query ? null : { connected: true, isActive: row === origin, identity: identity(origin).identity, tabIndex: row === origin ? 0 : -1,
      soleStopMatchesTarget: row === origin, box: { top: 20, bottom: 52, height: 32 } }, emptyResult: null, query: "" };
}

test("closed arguments accept one exact source and absolute output only", () => {
  const source = "a".repeat(40), output = resolve("synthetic-probe-output");
  assert.deepEqual(exactArguments(["--expected-commit", source, "--output", output]), { expectedCommit: source, output });
  for (const args of [[], ["--expected-commit", "main", "--output", output], ["--expected-commit", source, "--output", "relative"],
    ["--expected-commit", source, "--output", output, "--ignore-failure"], ["--output", output, "--expected-commit", source]]) assert.throws(() => exactArguments(args));
});

test("root tsconfig family uses actual Git tree selection and preserves complete identity changes", () => {
  // Actual hosted Git route: unsupported ls-tree glob magic must fail this positive control.
  const baseline = rootTsconfigFamily("a97fdfc93fb1bb0c30b2a4b51fa81d2d75fa3aa7");
  assert.deepEqual(Object.keys(baseline), ["atlas-scope/tsconfig.config.json", "atlas-scope/tsconfig.json", "atlas-scope/tsconfig.scripts.json"]);
  assert.deepEqual(rootTsconfigFamily("HEAD"), baseline);
  const select = (tree) => rootTsconfigFamily("synthetic-ref", (ref, paths) => {
    assert.equal(ref, "synthetic-ref"); assert.deepEqual(paths, ["atlas-scope"]); return tree;
  });
  assert.deepEqual(select({ ...baseline, "atlas-scope/src/tsconfig.fixture.json": { mode: "100644", blob: "0".repeat(40) } }), baseline);
  const added = { ...baseline, "atlas-scope/tsconfig.new.json": { mode: "100644", blob: "1".repeat(40) } };
  const removed = { ...baseline }; delete removed["atlas-scope/tsconfig.scripts.json"];
  const changed = { ...baseline, "atlas-scope/tsconfig.json": { ...baseline["atlas-scope/tsconfig.json"], blob: "2".repeat(40) } };
  const mode = { ...baseline, "atlas-scope/tsconfig.json": { ...baseline["atlas-scope/tsconfig.json"], mode: "100755" } };
  for (const tree of [added, removed, changed, mode]) assert.notDeepEqual(select(tree), baseline);
});

test("semantic frame completeness refuses absent state, scroll, identity and history", () => {
  assert.deepEqual(frameFailures(measured(), true), []);
  for (const change of [(s) => { delete s.grid.scrollTop; }, (s) => { s.grid.clientHeight = NaN; }, (s) => { delete s.target.identity; },
    (s) => { delete s.active; }, (s) => { delete s.focusHistory; }, (s) => { s.focusHistory.overflow = true; },
    (s) => { s.logicalBodyRows++; }, (s) => { s.rows.push(s.rows[0]); }, (s) => { delete s.rows[0].box; }]) {
    const state = measured(); change(state); assert.notDeepEqual(frameFailures(state, true), []);
  }
  assert.notDeepEqual(frameFailures(null, true), []);
});

test("original-node continuity refuses a wrong sole tabstop and another logical copy", () => {
  const before = measured(), after = measured(3, { scroll: 960, origin: 3 });
  assert.deepEqual(retentionFailures(before, after), []);
  for (const change of [(s) => { s.target.connected = false; }, (s) => { s.target.isActive = false; },
    (s) => { s.target.identity = "row4/col1/F001"; }, (s) => { s.target.tabIndex = -1; },
    (s) => { s.target.soleStopMatchesTarget = false; }, (s) => { s.tabstops = [identity(4)]; }, (s) => { s.tabstops = []; }]) {
    const value = structuredClone(after); change(value); assert.notDeepEqual(retentionFailures(before, value), []);
  }
});

test("more than a viewport is not enough when the original row is still in overscan", () => {
  const before = measured(20), stillInside = measured(20, { scroll: 352, origin: 20 });
  assert.ok(stillInside.grid.scrollTop > before.grid.scrollTop + before.grid.clientHeight);
  assert.deepEqual(normalWindow(stillInside), { start: 3, end: 29, rowEstimatePx: 32, overscan: 8, count: 400 });
  assert.ok(beyondWindowFailures(before, stillInside, 20).includes("original logical row is still inside normal overscan interval"));
  const excludedButRetained = measured(20, { scroll: 1280, origin: 20 });
  assert.equal(excludedButRetained.target.connected, true);
  assert.deepEqual(beyondWindowFailures(before, excludedButRetained, 20), []);
  const missingNormal = structuredClone(excludedButRetained); missingNormal.rows.pop(); missingNormal.mountedBodyRows--;
  assert.notDeepEqual(beyondWindowFailures(before, missingNormal, 20), []);
});

test("measured PageDown target refuses ArrowDown substitution and respects the last row", () => {
  const before = measured(4, { origin: 3 });
  assert.equal(pageDestination(before).step, 9);
  assert.equal(pageDestination(before).row, 13);
  assert.deepEqual(pageFailures(before, measured(13, { origin: 3 })), []);
  assert.notDeepEqual(pageFailures(before, measured(5, { origin: 3 })), []);
  const clipped = measured(4); clipped.pageGeometry.bottom = 180;
  assert.equal(pageDestination(clipped).step, 4);
  assert.equal(pageDestination(measured(398)).row, 401);
  const unmeasured = measured(4); unmeasured.pageGeometry.dataRowHeight = 0;
  assert.throws(() => pageDestination(unmeasured));
});

const PHASES = {
  "data-wheel": ["setup", "focused", "after-wheel", "after-arrow", "after-page"],
  "group-wheel": ["setup", "focused", "after-wheel", "after-arrow", "after-page"],
  "never-entered-query": ["setup", "query-focused", "after-wheel"],
  "left-grid-query": ["setup", "entered", "query-focused", "after-wheel"],
  "header-wheel": ["setup", "focused", "after-wheel"],
  "tab-reentry": ["setup", "entered", "query-focused", "after-wheel", "reentered"],
  "filter-transitions": ["setup", "shrink", "empty", "recovery"],
  "repeated-copies": ["setup", "copies", "first-copy", "second-copy"],
};
function passing() {
  return Object.entries(PHASES).map(([id, phases]) => {
    const origin = id === "header-wheel" ? 1 : id === "group-wheel" ? 2 : 3;
    const outside = ["never-entered-query", "left-grid-query", "tab-reentry"].includes(id);
    const focus = measured(origin), wheel = measured(origin, { scroll: 960, origin, query: outside, entered: id !== "never-entered-query" });
    const arrow = measured(origin + 1, { origin }), paged = measured(origin + 10, { origin });
    const query = measured(origin, { query: true, entered: id !== "never-entered-query" });
    const shrink = measured(3, { count: 6, query: true });
    const empty = measured(1, { count: 0, origin: 1, query: true }); empty.emptyResult = "No findings match this scope";
    const copies = measured(3, { count: 6, query: true });
    const first = measured(3, { count: 6 }), second = measured(5, { count: 6 });
    const reentered = measured(3);
    const states = { setup: query, focused: focus, entered: focus, "query-focused": query, "after-wheel": wheel,
      "after-arrow": arrow, "after-page": paged, shrink, empty, recovery: query, copies, "first-copy": first, "second-copy": second, reentered };
    states.final = id === "header-wheel" ? wheel : ["data-wheel", "group-wheel"].includes(id) ? paged
      : id === "tab-reentry" ? reentered : id === "repeated-copies" ? second : query;
    const observations = [...phases, "final"].map((phase) => ({ phase, status: "COMPLETE", errors: [], state: structuredClone(states[phase]),
      afterImageState: structuredClone(states[phase]), image: { file: `${id}-${phase}.png`, bytes: 10, sha256: "a".repeat(64) } }));
    return { id, status: "PASS", failures: [], observations, pageErrors: [], forbiddenRequests: [], wheelSamples: [{ state: wheel }], pageInput: arrow };
  });
}
test("complete synthetic frames support one bounded positive census; missing and late negatives cannot pass", () => {
  assert.deepEqual(CASES, Object.keys(PHASES));
  for (const item of passing()) assert.deepEqual(caseEvidenceFailures(item), [], item.id);
  assert.equal(completeVerdict(passing(), []), "PASS");
  const changes = [
    (items) => { items.pop(); }, (items) => { items[1].id = items[0].id; },
    (items) => { items[0].status = "FAIL"; }, (items) => { items[0].status = "SKIP"; },
    (items) => { items[0].failures.push("expected negative is still failure"); },
    (items) => { items[6].observations[1].status = "INCOMPLETE"; items[6].observations[1].errors.push("shrink action failed; later empty and recovery retained"); },
    (items) => { delete items[0].observations[0].state; },
    (items) => { items[6].observations = items[6].observations.filter((row) => row.phase !== "empty"); },
    (items) => { items[2].observations[0].image = null; },
    (items) => { items[2].observations[0].image.file = "other.png"; },
    (items) => { items[0].pageErrors.push("late page error"); },
    (items) => { items[0].forbiddenRequests.push({ url: "https://example.invalid/" }); },
    (items) => { items[4].observations.at(-1).afterImageState.target.connected = false; },
    (items) => { items[2].observations.at(-1).afterImageState.focusHistory.events.push({ sequence: 2, at: 2, inGrid: true, query: false }); },
    (items) => { items[2].observations[0].state.focusHistory.events.push({ sequence: 2, at: 2, inGrid: true, query: false }); },
    (items) => { items[0].observations.at(-1).afterImageState.active.description = identity(4); },
  ];
  for (const change of changes) { const items = passing(); change(items); assert.equal(completeVerdict(items, []), "FAIL"); }
  assert.equal(completeVerdict(passing(), ["source/output/cleanup failure"]), "FAIL");
});

test("filtered controls remain meaningful without the unrelated high-row virtualization premise", () => {
  const items = passing();
  for (const index of [6, 7]) {
    const item = items[index];
    for (const row of item.observations) if ((["setup", "recovery", "final"].includes(row.phase) && index === 6) || (row.phase === "setup" && index === 7)) {
      row.state = measured(3, { count: 20, query: true }); row.afterImageState = structuredClone(row.state);
    }
    assert.deepEqual(caseEvidenceFailures(item), [], item.id);
  }
  const invalidHighCase = items[2];
  invalidHighCase.observations[0].state = measured(3, { count: 20, query: true });
  invalidHighCase.observations[0].afterImageState = structuredClone(invalidHighCase.observations[0].state);
  assert.ok(caseEvidenceFailures(invalidHighCase).includes("high-row virtualization premise missing"));
});
