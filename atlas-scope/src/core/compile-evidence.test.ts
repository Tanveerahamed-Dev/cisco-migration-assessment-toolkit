// @vitest-environment node
/**
 * compile-evidence.test.ts — the punch-list's producer fields are compiled, never dropped, and every
 * evidence pointer a finding carries RESOLVES inside the snapshot it was compiled from.
 *
 * WHAT WAS WRONG. `PUNCHLIST_FIELDS` left out `severity_basis` and `evidence_confidence` "because this
 * snapshot carries neither" — and the engine writes both on every Multicast/Media row
 * (cisco_toolkit/analyze.py `add()`, with a non-empty "NOT published" fallback), so every real fleet
 * with such a finding stopped the build. The engine is also gaining a per-finding evidence contract
 * (`evidence_basis`, `evidence_refs`, `evidence_refs_total`; cluster E1). A pointer the compiler copies
 * without resolving is a citation of a record that may not exist — the compiled model would then CITE
 * evidence its own source does not hold. So: every pointer is resolved at compile time, and one that
 * does not resolve, or that breaks the contract in any way, is a coded build failure.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { bindSource } from "../../tools/source-binding.mjs";
import {
  CompileError,
  compileAll,
  EVIDENCE_BASES as COMPILER_BASES,
  EVIDENCE_REF_KINDS as COMPILER_KINDS,
  EVIDENCE_REF_ROLES as COMPILER_ROLES,
  resolvePointer,
} from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import { EVIDENCE_BASES, EVIDENCE_REF_KINDS, EVIDENCE_REF_ROLES, type Finding } from "./types";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const GOLDEN = readFileSync(resolve(REPO, "tests", "golden", "snapshot.json"), "utf8");
/**
 * The base every case extends: the golden (a real producer output) with the evidence contract removed
 * from every punch-list row, so each case states the ONLY contract it carries. Using the golden as
 * published made every case here depend on the engine lane's refs — which point into sections the golden
 * harness strips (verifier S1-V1) — so a case about `severity_basis` failed on a device_dossiers pointer.
 */
const golden = (): Record<string, any> => {
  const s = JSON.parse(GOLDEN) as Record<string, any>;
  s.punchlist = (s.punchlist as Record<string, unknown>[]).map((row) =>
    Object.fromEntries(Object.entries(row).filter(([k]) => k !== "evidence_basis" && k !== "evidence_refs" && k !== "evidence_refs_total")),
  );
  return s;
};

/** Compile a snapshot object through the real path: bytes -> validate -> bind -> compile. */
function compile(snap: Record<string, unknown>) {
  const bytes = new TextEncoder().encode(JSON.stringify(snap));
  const v = assertValidSnapshot(bytes);
  return compileAll(v.snap, bindSource(bytes, { source: "case.json", sourceOrigin: "external-file" }), { schemaAssumed: v.schemaAssumed });
}
function codeOf(snap: Record<string, unknown>): string {
  try {
    compile(snap);
    return "OK";
  } catch (e) {
    if (e instanceof CompileError) return e.code;
    throw e;
  }
}

/** The golden snapshot with its first punch-list row extended by `extra`. */
function withRow(extra: Record<string, unknown>): Record<string, any> {
  const s = golden();
  s.punchlist[0] = { ...s.punchlist[0], ...extra };
  return s;
}

const IFACE = "/interfaces/core1/Gi1~10~11"; // interfaces.core1["Gi1/0/1"], RFC 6901-escaped
const ref = (over: Record<string, unknown> = {}) => ({ kind: "interface", host: "core1", ref: IFACE, role: "subject", cite: "core1 Gi1/0/1", ...over });

describe("severity_basis and evidence_confidence are compiled, not a build failure", () => {
  it("carries both onto the finding, verbatim", () => {
    const basis = "observed querier state";
    const conf = "evidence confidence NOT published by this snapshot";
    const set = compile(withRow({ severity_basis: basis, evidence_confidence: conf }));
    const f = set.fabric.findings[0] as Finding;
    expect(f.severityBasis).toBe(basis);
    expect(f.evidenceConfidence).toBe(conf);
  });

  it("an absent key compiles to null (not emitted), never to an empty string", () => {
    const f = compile(golden()).fabric.findings[0] as Finding;
    expect(f.severityBasis).toBeNull();
    expect(f.evidenceConfidence).toBeNull();
    expect(f.evidenceBasis).toBeNull();
    expect(f.evidenceRefs).toBeNull();
    expect(f.evidenceRefsTotal).toBeNull();
  });

  it.each([["N/A"], ["-"], [""], ["  [NOT OBSERVED] querier  "]])(
    "a PRESENT producer string %j is kept verbatim — emitted is never read as not-emitted (S1-V10)",
    (s) => {
      /* Before: both fields went through val(), which maps "", "-", "N/A" and [NOT OBSERVED] to null — and
         null is defined (types.ts Finding) as "the producer did not emit the key". A disclosure the producer
         DID write must not be rendered as one it did not. */
      const f = compile(withRow({ severity_basis: s, evidence_confidence: s })).fabric.findings[0] as Finding;
      expect(f.severityBasis).toBe(s);
      expect(f.evidenceConfidence).toBe(s);
    },
  );

  it("a non-string basis is a coded failure, not a stringified object", () => {
    expect(codeOf(withRow({ severity_basis: { why: "x" } }))).toBe("E_PRODUCER_FIELD_TYPE");
  });
});

describe("the evidence contract is compiled when it is honoured", () => {
  it("compiles basis, refs and total, keeping each ref's fields", () => {
    const refs = [ref(), ref({ kind: "analysis_row", host: null, ref: "/health_scores/0", role: "derived_from", cite: "health score" })];
    const set = compile(withRow({ evidence_basis: "record", evidence_refs: refs, evidence_refs_total: 5 }));
    const f = set.fabric.findings[0] as Finding;
    expect(f.evidenceBasis).toBe("record");
    expect(f.evidenceRefs).toEqual(refs);
    expect(f.evidenceRefsTotal).toBe(5);
  });

  it("an absence basis with witness refs compiles", () => {
    const refs = [ref({ kind: "absence_witness", role: "witness", ref: "/security/core1", cite: "core1 security record" })];
    const s = withRow({ evidence_basis: "absence", evidence_refs: refs });
    expect(Object.hasOwn(s, "security")).toBe(true);
    expect(codeOf(s)).toBe("OK");
  });

  it("the compiler's vocabularies are exactly the ones the types declare", () => {
    expect([...COMPILER_KINDS]).toEqual([...EVIDENCE_REF_KINDS]);
    expect([...COMPILER_ROLES]).toEqual([...EVIDENCE_REF_ROLES]);
    expect([...COMPILER_BASES]).toEqual([...EVIDENCE_BASES]);
  });
});

describe("the contract fails closed, with a code for each way it can be broken", () => {
  const cases: [string, Record<string, unknown>, string][] = [
    ["an unknown basis", { evidence_basis: "vibes" }, "E_EVIDENCE_CONTRACT"],
    ["a non-string basis", { evidence_basis: 1 }, "E_EVIDENCE_CONTRACT"],
    ["refs that are not a list", { evidence_refs: { a: 1 } }, "E_EVIDENCE_CONTRACT"],
    ["a ref that is not an object", { evidence_refs: ["/interfaces"] }, "E_EVIDENCE_CONTRACT"],
    ["an unknown kind", { evidence_refs: [ref({ kind: "hunch" })] }, "E_EVIDENCE_CONTRACT"],
    ["an unknown role", { evidence_refs: [ref({ role: "vibe" })] }, "E_EVIDENCE_CONTRACT"],
    ["a numeric host", { evidence_refs: [ref({ host: 7 })] }, "E_EVIDENCE_CONTRACT"],
    ["a missing cite", { evidence_refs: [Object.fromEntries(Object.entries(ref()).filter(([k]) => k !== "cite"))] }, "E_EVIDENCE_CONTRACT"],
    ["a missing host key (null must be stated, not implied)", { evidence_refs: [Object.fromEntries(Object.entries(ref()).filter(([k]) => k !== "host"))] }, "E_EVIDENCE_CONTRACT"],
    ["a key the contract does not define", { evidence_refs: [ref({ weight: 1 })] }, "E_UNKNOWN_PRODUCER_FIELD"],
    ["a dotted path instead of a JSON Pointer", { evidence_refs: [ref({ ref: "interfaces.core1.Gi1/0/1" })] }, "E_EVIDENCE_REF_MALFORMED"],
    ["the whole-document pointer", { evidence_refs: [ref({ ref: "" })] }, "E_EVIDENCE_REF_MALFORMED"],
    ["an invalid escape", { evidence_refs: [ref({ ref: "/interfaces/core1/Gi1~20~11" })] }, "E_EVIDENCE_REF_MALFORMED"],
    ["a non-string pointer", { evidence_refs: [ref({ ref: 3 })] }, "E_EVIDENCE_REF_MALFORMED"],
    ["an array index with a leading zero", { evidence_refs: [ref({ ref: "/health_scores/00" })] }, "E_EVIDENCE_REF_UNRESOLVED"],
    ["the past-the-end '-' index", { evidence_refs: [ref({ ref: "/health_scores/-" })] }, "E_EVIDENCE_REF_UNRESOLVED"],
    ["an index past the end", { evidence_refs: [ref({ ref: "/health_scores/999" })] }, "E_EVIDENCE_REF_UNRESOLVED"],
    ["a record the snapshot does not hold", { evidence_refs: [ref({ ref: "/interfaces/core1/Gi9~19~199" })] }, "E_EVIDENCE_REF_UNRESOLVED"],
    ["an unescaped slash (a different path)", { evidence_refs: [ref({ ref: "/interfaces/core1/Gi1/0/1" })] }, "E_EVIDENCE_REF_UNRESOLVED"],
    ["a pointer through a scalar", { evidence_refs: [ref({ ref: "/schema/0" })] }, "E_EVIDENCE_REF_UNRESOLVED"],
    ["an inherited member, not an own one", { evidence_refs: [ref({ ref: "/devices/toString" })] }, "E_EVIDENCE_REF_UNRESOLVED"],
    ["a total below the number of refs", { evidence_refs: [ref(), ref()], evidence_refs_total: 1 }, "E_EVIDENCE_CONTRACT"],
    ["a fractional total", { evidence_refs: [ref()], evidence_refs_total: 1.5 }, "E_EVIDENCE_CONTRACT"],
    ["a total with no refs", { evidence_refs_total: 3 }, "E_EVIDENCE_CONTRACT"],
  ];

  it.each(cases)("%s → %s", (_why, extra, code) => {
    expect(codeOf(withRow(extra))).toBe(code);
  });

  it("the failure names the finding and the pointer", () => {
    let err: CompileError | undefined;
    try {
      compile(withRow({ evidence_refs: [ref({ ref: "/interfaces/core1/nope" })] }));
    } catch (e) {
      err = e as CompileError;
    }
    expect(err?.code).toBe("E_EVIDENCE_REF_UNRESOLVED");
    expect(err?.path).toBe("punchlist[0].evidence_refs[0]");
    expect(err?.message).toContain("/interfaces/core1/nope");
  });

  it("a pointer to a null value is refused; the same pointer to a value compiles (control)", () => {
    /* The engine's own contract (tests/test_punchlist_evidence_refs.py punchlist_evidence_problems): a ref
       resolves to a NON-NULL node. A present key holding null records that nothing was observed there;
       citing it as evidence would render absence as a record. */
    const at = (score: unknown) => {
      const s = withRow({ evidence_refs: [ref({ kind: "analysis_row", host: null, ref: "/health_scores/0/score", role: "derived_from", cite: "score" })] });
      s.health_scores[0].score = score;
      return s;
    };
    expect(codeOf(at(3))).toBe("OK");
    expect(codeOf(at(null))).toBe("E_EVIDENCE_REF_UNRESOLVED");
  });

  it("a ref into a whole section the file does not carry says so, in plain language", () => {
    /* The golden as published is the case in point: its refs cite /device_dossiers/…, a section the golden
       harness strips. The refusal must name the missing SECTION, not only the missing member. */
    let err: CompileError | undefined;
    try {
      compile(withRow({ evidence_refs: [ref({ kind: "analysis_row", host: null, ref: "/device_dossiers/per_device/0", role: "derived_from" })] }));
    } catch (e) {
      err = e as CompileError;
    }
    expect(err?.code).toBe("E_EVIDENCE_REF_UNRESOLVED");
    expect(err?.message).toMatch(/no device_dossiers section/);
    expect(err?.message).toMatch(/removed after the engine wrote it/);
  });
});

describe("resolvePointer is RFC 6901 and nothing looser", () => {
  const doc = { "a/b": { "m~n": [10, 20] }, "": { x: null } };
  it.each([
    ["/a~1b/m~0n/1", 20],
    ["/a~1b/m~0n/0", 10],
    ["//x", null],
  ] as const)("%s resolves", (p, want) => {
    const r = resolvePointer(doc, p);
    expect(r.ok).toBe(true);
    expect(r.ok && r.value).toBe(want);
  });
  it("~01 decodes to '~1', not '/' (the RFC's order of unescaping)", () => {
    expect(resolvePointer({ "~1": 1, "/": 2 }, "/~01")).toEqual({ ok: true, value: 1 });
  });
});
