// @vitest-environment node
/**
 * compile-evidence-records.test.ts — the records the engine's evidence pointers name are projected into the
 * model: bounded, deduplicated, keyed by pointer, and nothing the engine did not point at.
 *
 * WHY (phase 3, A1). Every punch-list row of the regenerated sample carries `evidence_basis` and
 * `evidence_refs` (RFC 6901 pointers, contracts/engine-contract.v1.json). The compiler RESOLVED each pointer
 * and then kept only the pointer: the record it names — a security check, a dossier row, a configuration
 * line — was not in the model, so no surface could render what the engine points at. The projection
 * (tools/lib/compile-model.mjs `compileEvidenceRecords`) carries each named record once, under its pointer.
 *
 * WHAT THIS PINS, for the tracked sample AND for planted cases:
 *   - the projection's pointer set EQUALS the set of pointers the findings carry — no record the engine did
 *     not name, none it named missing, each once, sorted;
 *   - each record is the pointed value itself: its members in the engine's order, each text a prefix of the
 *     member's whole text, `chars` the whole length — so a cut is stated, never silent;
 *   - the caps hold per field, per record and in total, and are stated in `evidenceProjection` together with
 *     what they cost; a record past the total budget is `withheld`, never dropped;
 *   - a sibling of a pointed record (another check in the same list) never reaches the model;
 *   - `cite` in the compiled model means a snapshot path: the producer's human label is `label`, so no
 *     free text is indexed as a citation.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { bindSource, lfNormalise } from "../../tools/source-binding.mjs";
import { compileAll, compileEvidenceRecords, EVIDENCE_PROJECTION_CAPS, resolvePointer, type CompiledSet } from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import type { EvidenceRecord, Fabric } from "./types";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPO = resolve(PKG, "..");
const SAMPLE_REL = "webapp/sample_data/sample_fleet.snapshot.json";
const SAMPLE_BYTES = lfNormalise(readFileSync(resolve(REPO, SAMPLE_REL)));
const SAMPLE = JSON.parse(new TextDecoder().decode(SAMPLE_BYTES)) as Record<string, any>;

function compileSnap(snap: Record<string, unknown>): CompiledSet {
  const bytes = new TextEncoder().encode(JSON.stringify(snap));
  const v = assertValidSnapshot(bytes);
  return compileAll(v.snap, bindSource(bytes, { source: "case.json", sourceOrigin: "external-file" }), { schemaAssumed: v.schemaAssumed });
}
const sampleSet = (): CompiledSet => {
  const v = assertValidSnapshot(SAMPLE_BYTES);
  return compileAll(v.snap, bindSource(SAMPLE_BYTES, { source: SAMPLE_REL, sourceOrigin: "repository-file" }), { schemaAssumed: v.schemaAssumed });
};

/**
 * The order the total budget is spent in: the engine's own priority. Findings by `priority` (then punch-list
 * order), each finding's pointers in the engine's order; a pointer's place is its FIRST naming there.
 */
function budgetOrder(findings: readonly { priority?: number | null; evidenceRefs?: readonly { ref: string }[] | null }[]): Map<string, number> {
  const order = findings.map((f, i) => ({ f, i })).sort((a, b) => (a.f.priority ?? Infinity) - (b.f.priority ?? Infinity) || a.i - b.i);
  const rank = new Map<string, number>();
  for (const { f } of order) for (const r of f.evidenceRefs ?? []) if (!rank.has(r.ref)) rank.set(r.ref, rank.size);
  return rank;
}
const written = (recs: readonly EvidenceRecord[]): number => recs.reduce((a, r) => a + JSON.stringify(r).length, 0);

const typeOf = (v: unknown): string => (v === null ? "null" : Array.isArray(v) ? "array" : typeof v);
const cap = EVIDENCE_PROJECTION_CAPS;

/** The members a projected record carries, as [key, member] in order. */
const membersOf = (rec: EvidenceRecord): [string, unknown][] =>
  Array.isArray(rec.value) ? rec.value.map((x, i) => [String(i), x]) : rec.value !== null && typeof rec.value === "object" ? Object.entries(rec.value) : [];

/**
 * Check one projected record against the value its pointer names in `snap` — the invariant, independent of
 * which snapshot: every member carried is the engine's member at the same position — a scalar exactly, a text
 * a prefix of the engine's whole text with its whole length stated when shorter — and nothing else is carried.
 */
function checkAgainstSource(rec: EvidenceRecord, snap: unknown): void {
  const hit = resolvePointer(snap, rec.pointer);
  expect(hit.ok, rec.pointer).toBe(true);
  if (!hit.ok) return;
  const v = hit.value;
  expect(rec.cite, "a record's citation is its pointer").toBe(rec.pointer);
  expect(rec.type, rec.pointer).toBe(typeOf(v));
  expect(rec.jsonChars, rec.pointer).toBe(JSON.stringify(v).length);
  if (rec.withheld) {
    expect(rec.value, rec.pointer).toBeNull();
    expect(rec.nested, rec.pointer).toEqual([]);
    expect(rec.cut, rec.pointer).toEqual({});
    return;
  }
  const checkText = (where: string, key: string, whole: string, carried: unknown, limit: number): void => {
    expect(typeof carried, where).toBe("string");
    const t = carried as string;
    expect(whole.startsWith(t), `${where}: the text is a prefix of the engine's`).toBe(true);
    expect(t.length, where).toBeLessThanOrEqual(limit);
    if (whole.length <= limit) expect(t, `${where}: an uncut text is whole`).toBe(whole);
    if (t.length < whole.length) expect(rec.cut[key], `${where}: a cut states the whole length`).toBe(whole.length);
    else expect(Object.hasOwn(rec.cut, key), `${where}: an uncut text is not listed as cut`).toBe(false);
  };
  if (v !== null && typeof v === "object") {
    const entries: [string, unknown][] = Array.isArray(v) ? v.map((x, i) => [String(i), x]) : Object.entries(v as Record<string, unknown>);
    expect(rec.fieldsTotal, rec.pointer).toBe(entries.length);
    expect(Array.isArray(rec.value), rec.pointer).toBe(Array.isArray(v));
    const carried = membersOf(rec);
    expect(carried.length, rec.pointer).toBeLessThanOrEqual(cap.recordFields);
    carried.forEach(([key, x], i) => {
      const [srcKey, srcVal] = entries[i]!;
      const where = `${rec.pointer} member ${key}`;
      expect(key, where).toBe(srcKey);
      const isNested = srcVal !== null && typeof srcVal === "object";
      expect(rec.nested.includes(key), `${where}: named nested exactly when the engine's member is an object or list`).toBe(isNested);
      if (isNested) checkText(where, key, JSON.stringify(srcVal), x, cap.fieldTextChars);
      else if (typeof srcVal === "string") checkText(where, key, srcVal, x, cap.fieldTextChars);
      else expect(x, where).toBe(srcVal);
    });
    for (const k of [...rec.nested, ...Object.keys(rec.cut)]) expect(carried.some(([key]) => key === k), `${rec.pointer}: ${k} is carried`).toBe(true);
  } else {
    expect(rec.fieldsTotal, rec.pointer).toBe(0);
    expect(rec.nested, rec.pointer).toEqual([]);
    if (typeof v === "string") checkText(rec.pointer, "", v, rec.value, cap.scalarTextChars);
    else expect(rec.value, rec.pointer).toBe(v);
  }
  expect(JSON.stringify(rec).length, `${rec.pointer}: within the per-record cap`).toBeLessThanOrEqual(cap.recordChars);
}

describe("the projection of the tracked sample (invariants over every pointer)", () => {
  const set = sampleSet();
  const fabric = set.fabric as Fabric;
  const records = fabric.evidenceRecords ?? [];
  const pointers = [...new Set(fabric.findings.flatMap((f) => (f.evidenceRefs ?? []).map((r) => r.ref)))];

  it("the sample carries the evidence contract at all (the rest is not vacuous)", () => {
    expect(pointers.length).toBeGreaterThan(0);
    expect(fabric.evidenceRecords, "the compiler emits the projection").toBeDefined();
    expect(fabric.evidenceProjection).toBeDefined();
  });

  it("carries exactly one record per distinct pointer the findings carry — none unnamed, none missing — sorted", () => {
    expect(records.map((r) => r.pointer)).toEqual([...pointers].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)));
  });

  it("every record is the value its pointer names in the source, cut only where stated", () => {
    expect(records.length, "precondition: records to check").toBe(pointers.length);
    for (const r of records) checkAgainstSource(r, SAMPLE);
  });

  it("states its caps and what they cost, and the cost is within them", () => {
    const p = fabric.evidenceProjection!;
    expect(p.fieldTextChars).toBe(EVIDENCE_PROJECTION_CAPS.fieldTextChars);
    expect(p.scalarTextChars).toBe(EVIDENCE_PROJECTION_CAPS.scalarTextChars);
    expect(p.recordFields).toBe(EVIDENCE_PROJECTION_CAPS.recordFields);
    expect(p.recordChars).toBe(EVIDENCE_PROJECTION_CAPS.recordChars);
    expect(p.totalChars).toBe(EVIDENCE_PROJECTION_CAPS.totalChars);
    expect(p.records).toBe(records.length);
    const projected = records.filter((r) => !r.withheld).reduce((a, r) => a + JSON.stringify(r).length, 0);
    expect(p.projectedChars).toBe(projected);
    expect(projected).toBeLessThanOrEqual(p.totalChars);
    expect(p.recordsWithheld).toBe(records.filter((r) => r.withheld).length);
    expect(p.fieldsOmitted).toBe(records.filter((r) => !r.withheld).reduce((a, r) => a + (r.fieldsTotal - membersOf(r).length), 0));
    expect(p.textsCut).toBe(records.reduce((a, r) => a + Object.keys(r.cut).length, 0));
    /* The total bounds EVERYTHING the projection writes, the withheld records' pointer-only stubs included
       (verifier P3A1-V1-4: stubs were outside every budget, so the output grew past the cap with the
       pointer count). */
    expect(p.writtenChars, "every record as written, stubs included").toBe(written(records));
    expect(p.withheldChars).toBe(written(records.filter((r) => r.withheld)));
    expect(p.writtenChars).toBeLessThanOrEqual(p.totalChars);
  });

  it("every evidence ref carries the producer's label as `label`, and no compiled `cite` holds free text", () => {
    fabric.findings.forEach((f, i) => {
      (f.evidenceRefs ?? []).forEach((r, k) => {
        const src = SAMPLE.punchlist[i].evidence_refs[k] as Record<string, unknown>;
        expect(r, `${f.id} ref ${k}`).toEqual({ kind: src.kind, host: src.host, ref: src.ref, role: src.role, label: src.cite });
      });
    });
    /* THE CLASS: every string under a `cite` key anywhere in the compiled model is a path — a dotted/indexed
       snapshot path, an RFC 6901 pointer, or the one " / "-joined coverage citation — never prose. Free text
       under `cite` is indexed as a citation bearer by the Inspector, and nothing can recognise it as one. */
    const PATHLIKE = /^(?:\/\S*|[A-Za-z_][\w-]*(?:\.[^\s.[\]]+|\[[^\]]+\])*(?:\s\/\s[A-Za-z_][\w-]*)*)$/;
    const bad: string[] = [];
    const walk = (v: unknown, at: string): void => {
      if (Array.isArray(v)) return v.forEach((x, i) => walk(x, `${at}[${i}]`));
      if (v === null || typeof v !== "object") return;
      for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
        if (k === "cite" && typeof x === "string" && !PATHLIKE.test(x)) bad.push(`${at}.cite = ${JSON.stringify(x).slice(0, 80)}`);
        walk(x, `${at}.${k}`);
      }
    };
    walk(fabric, "fabric");
    expect(bad.slice(0, 10)).toEqual([]);
  });
});

describe("the caps, on planted records built from the real sample", () => {
  /* A punch row pointing at ONE record the case plants, so each cap is exercised by a record that exceeds it. */
  const withPlanted = (planted: unknown, extraSiblings = true): { set: CompiledSet; snap: Record<string, any> } => {
    const snap = structuredClone(SAMPLE);
    const host = Object.keys(snap.security)[0]!;
    const list = snap.security[host].findings as unknown[];
    list.push(planted);
    if (extraSiblings) list.push({ id: "SIBLING-NEVER-POINTED-AT", detail: "SIBLING-TEXT-MUST-NOT-REACH-THE-MODEL" });
    const pointer = `/security/${host}/findings/${list.length - (extraSiblings ? 2 : 1)}`;
    snap.punchlist[0] = {
      ...snap.punchlist[0],
      devices: [host],
      evidence_basis: "row",
      evidence_refs: [{ kind: "device_fact", host, ref: pointer, role: "derived_from", cite: "planted" }],
    };
    delete snap.punchlist[0].evidence_refs_total;
    return { set: compileSnap(snap), snap };
  };
  const recordAt = (set: CompiledSet, pointer: string): EvidenceRecord => {
    const r = (set.fabric.evidenceRecords ?? []).find((x) => x.pointer === pointer);
    expect(r, pointer).toBeDefined();
    return r!;
  };

  it("a long text is cut to the field cap, and the cut is stated by its whole length", () => {
    const long = "x".repeat(EVIDENCE_PROJECTION_CAPS.fieldTextChars * 3);
    const { set, snap } = withPlanted({ id: "long", detail: long });
    const p = set.fabric.findings[0]!.evidenceRefs![0]!.ref;
    const rec = recordAt(set, p);
    checkAgainstSource(rec, snap);
    const d = (rec.value as Record<string, unknown>)["detail"] as string;
    expect(d.length).toBe(EVIDENCE_PROJECTION_CAPS.fieldTextChars);
    expect(rec.cut["detail"]).toBe(long.length);
  });

  it("a record with more members than the field cap carries the first ones and states how many it has", () => {
    const wide = Object.fromEntries(Array.from({ length: EVIDENCE_PROJECTION_CAPS.recordFields * 2 }, (_, i) => [`k${i}`, i]));
    const { set, snap } = withPlanted(wide);
    const rec = recordAt(set, set.fabric.findings[0]!.evidenceRefs![0]!.ref);
    checkAgainstSource(rec, snap);
    expect(membersOf(rec).length).toBe(EVIDENCE_PROJECTION_CAPS.recordFields);
    expect(rec.fieldsTotal).toBe(EVIDENCE_PROJECTION_CAPS.recordFields * 2);
  });

  it("a record whose members together exceed the record cap stops at the cap", () => {
    const heavy = Object.fromEntries(Array.from({ length: EVIDENCE_PROJECTION_CAPS.recordFields }, (_, i) => [`k${i}`, "y".repeat(EVIDENCE_PROJECTION_CAPS.fieldTextChars * 2)]));
    const { set, snap } = withPlanted(heavy);
    const rec = recordAt(set, set.fabric.findings[0]!.evidenceRefs![0]!.ref);
    checkAgainstSource(rec, snap);
    expect(membersOf(rec).length).toBeLessThan(EVIDENCE_PROJECTION_CAPS.recordFields);
    expect(membersOf(rec).length, "it still carries what fits").toBeGreaterThan(0);
    expect(JSON.stringify(rec).length).toBeLessThanOrEqual(EVIDENCE_PROJECTION_CAPS.recordChars);
  });

  it("a sibling of the pointed record never reaches the model", () => {
    const { set } = withPlanted({ id: "pointed", detail: "the pointed record" });
    expect(JSON.stringify(set.fabric).includes("SIBLING-TEXT-MUST-NOT-REACH-THE-MODEL")).toBe(false);
    expect(JSON.stringify(set.fabric).includes("the pointed record")).toBe(true);
  });

  it("a pointer two findings share is projected once", () => {
    const snap = structuredClone(SAMPLE);
    const r = snap.punchlist.find((row: Record<string, any>) => (row.evidence_refs ?? []).length > 0);
    const shared = r.evidence_refs[0];
    snap.punchlist[1] = { ...snap.punchlist[1], devices: shared.host === null ? snap.punchlist[1].devices : [shared.host], evidence_basis: "row", evidence_refs: [{ ...shared, kind: "analysis_row" }] };
    delete snap.punchlist[1].evidence_refs_total;
    const set = compileSnap(snap);
    expect((set.fabric.evidenceRecords ?? []).filter((x) => x.pointer === shared.ref)).toHaveLength(1);
  });

  it("records past the TOTAL budget are withheld — carried by pointer, stated, never dropped", () => {
    /* Enough distinct heavy records to exceed the total cap. */
    const snap = structuredClone(SAMPLE);
    const host = Object.keys(snap.security)[0]!;
    const list = snap.security[host].findings as unknown[];
    /* Unpointed fillers so every planted index has three digits: the planted records are then all the same
       size, and which of them are withheld is decided by the budget ORDER alone. */
    while (list.length < 100) list.push({ id: "FILLER-NEVER-POINTED-AT" });
    const per = EVIDENCE_PROJECTION_CAPS.recordChars;
    const n = Math.ceil(EVIDENCE_PROJECTION_CAPS.totalChars / (per / 2)) + 2;
    const start = list.length;
    for (let i = 0; i < n; i += 1) list.push(Object.fromEntries(Array.from({ length: 12 }, (_, k) => [`k${k}`, `${i}-`.padEnd(EVIDENCE_PROJECTION_CAPS.fieldTextChars, "z")])));
    /* Spread over rows so the per-row ref cap (the engine contract's) is honoured. The highest-priority row
       names the HIGHEST indices, so the pointers' sort order disagrees with the engine's priority. */
    const cap = 50;
    for (let i = 0, row = 0; i < n; i += cap, row += 1) {
      snap.punchlist[row] = {
        ...snap.punchlist[row],
        devices: [host],
        evidence_basis: "row",
        evidence_refs: Array.from({ length: Math.min(cap, n - i) }, (_, k) => ({ kind: "device_fact", host, ref: `/security/${host}/findings/${start + n - 1 - (i + k)}`, role: "derived_from", cite: "planted" })),
      };
      delete snap.punchlist[row].evidence_refs_total;
    }
    const set = compileSnap(snap);
    const recs = set.fabric.evidenceRecords ?? [];
    const withheld = recs.filter((r) => r.withheld);
    expect(withheld.length, "some records were past the budget").toBeGreaterThan(0);
    const p = set.fabric.evidenceProjection!;
    expect(p.recordsWithheld).toBe(withheld.length);
    expect(p.projectedChars).toBeLessThanOrEqual(p.totalChars);
    for (const r of recs) checkAgainstSource(r, snap);
    // Every pointer is still there: withheld is stated, not dropped.
    const pointers = new Set(set.fabric.findings.flatMap((f) => (f.evidenceRefs ?? []).map((r) => r.ref)));
    expect(recs.length).toBe(pointers.size);
    // …and what is written, stubs included, stays inside the total.
    expect(p.writtenChars).toBe(written(recs));
    expect(p.writtenChars, "the total bounds the whole projection").toBeLessThanOrEqual(p.totalChars);
    /* The budget is spent in the engine's priority order: every planted record carried comes before every
       planted record withheld (they are all the same size, so the order alone decides). */
    const rank = budgetOrder(set.fabric.findings);
    const planted = recs.filter((r) => r.pointer.startsWith(`/security/${host}/findings/`) && Number(r.pointer.split("/").pop()) >= start);
    expect(planted.length).toBe(n);
    const kept = planted.filter((r) => !r.withheld).map((r) => rank.get(r.pointer)!);
    const cut = planted.filter((r) => r.withheld).map((r) => rank.get(r.pointer)!);
    expect(kept.length > 0 && cut.length > 0, "precondition: some planted records carried, some withheld").toBe(true);
    expect(Math.max(...kept), "no lower-priority record displaced a higher-priority one").toBeLessThan(Math.min(...cut));
  });

  it("when the pointers alone outgrow the total, every record is withheld and the overrun is stated, never hidden", () => {
    /* The pointer-only stubs cannot be dropped (each is a pointer a finding carries), so a total smaller than
       they are is exceeded — by them alone, and that is what the projection says. */
    const three = [{ priority: 1, evidenceRefs: [{ ref: "/punchlist/0" }, { ref: "/punchlist/1" }, { ref: "/punchlist/2" }] }];
    const { records, projection } = compileEvidenceRecords(three, SAMPLE, { ...EVIDENCE_PROJECTION_CAPS, totalChars: 10 });
    expect(records.map((r) => r.withheld)).toEqual([true, true, true]);
    expect(projection.projectedChars).toBe(0);
    expect(projection.totalChars).toBe(10);
    expect(projection.writtenChars).toBe(written(records));
    expect(projection.withheldChars).toBe(projection.writtenChars);
    expect(projection.writtenChars).toBeGreaterThan(projection.totalChars);
    /* With room for exactly one full record plus the other's stub, the ENGINE's first pointer is the one
       carried — though it sorts after the other. */
    const two = [{ priority: 1, evidenceRefs: [{ ref: "/punchlist/2" }, { ref: "/punchlist/0" }] }];
    const roomy = compileEvidenceRecords(two, SAMPLE, { ...EVIDENCE_PROJECTION_CAPS, totalChars: 1e9 });
    const bare = compileEvidenceRecords(two, SAMPLE, { ...EVIDENCE_PROJECTION_CAPS, totalChars: 0 });
    const size = (set: { records: EvidenceRecord[] }, p: string): number => JSON.stringify(set.records.find((r) => r.pointer === p)).length;
    const tight = compileEvidenceRecords(two, SAMPLE, { ...EVIDENCE_PROJECTION_CAPS, totalChars: size(roomy, "/punchlist/2") + size(bare, "/punchlist/0") });
    expect(tight.records.map((r) => r.pointer), "the output stays sorted by pointer").toEqual(["/punchlist/0", "/punchlist/2"]);
    expect(tight.records.find((r) => r.pointer === "/punchlist/2")?.withheld, "the engine's first pointer is carried").toBe(false);
    expect(tight.records.find((r) => r.pointer === "/punchlist/0")?.withheld).toBe(true);
    expect(tight.projection.writtenChars).toBe(tight.projection.totalChars);
  });

  it("a model with no evidence pointer carries an empty projection, stated as such", () => {
    const snap = structuredClone(SAMPLE);
    snap.punchlist = (snap.punchlist as Record<string, unknown>[]).map((row) =>
      Object.fromEntries(Object.entries(row).filter(([k]) => !k.startsWith("evidence_"))),
    );
    const set = compileSnap(snap);
    expect(set.fabric.evidenceRecords).toEqual([]);
    expect(set.fabric.evidenceProjection?.records).toBe(0);
    expect(set.fabric.evidenceProjection?.projectedChars).toBe(0);
  });
});
