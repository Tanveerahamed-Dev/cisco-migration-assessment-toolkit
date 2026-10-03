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
import { beforeAll, describe, expect, it, vi } from "vitest";

import { bindSource } from "../../tools/source-binding.mjs";
import * as model from "../../tools/lib/compile-model.mjs";
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
/** The engine contract AS A FILE (cisco_toolkit/analyze.py engine_contract_projection generates it). */
const CONTRACT_PATH = resolve(REPO, "atlas-scope", "contracts", "engine-contract.v1.json");
const contractFile = (): Record<string, any> => JSON.parse(readFileSync(CONTRACT_PATH, "utf8")) as Record<string, any>;
const sorted = (xs: readonly string[]): string[] => [...xs].sort();
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
/**
 * A producer ref as the COMPILED finding carries it: every field kept, the producer's human `cite` under
 * `label` (in the model `cite` means a snapshot path — src/core/compile-evidence-records.test.ts pins the
 * class: no compiled `cite` holds free text).
 */
const compiled = (r: Record<string, unknown>) => ({ kind: r.kind, host: r.host, ref: r.ref, role: r.role, label: r.cite });
const ref = (over: Record<string, unknown> = {}) => ({ kind: "interface", host: "core1", ref: IFACE, role: "subject", cite: "core1 Gi1/0/1", ...over });
/** Exactly EVIDENCE_REFS_CAP distinct, resolvable, null-hosted row refs (every punch row, then every health score …). */
const cappedRefs = (): Record<string, unknown>[] => {
  const s = golden();
  const pointers = [
    ...(s.punchlist as unknown[]).map((_, i) => `/punchlist/${i}`),
    ...(s.health_scores as unknown[]).map((_, i) => `/health_scores/${i}`),
    ...Object.keys(s.devices as object).map((h) => `/devices/${h.replace(/~/g, "~0").replace(/\//g, "~1")}`),
    ...(s.cross_layer as unknown[]).map((_, i) => `/cross_layer/${i}`),
    ...((s.cable_map?.cables ?? []) as unknown[]).map((_, i) => `/cable_map/cables/${i}`),
    ...Object.entries(s.interfaces as Record<string, object>).flatMap(([h, ports]) => Object.keys(ports).map((p) => `/interfaces/${h}/${p.replace(/~/g, "~0").replace(/\//g, "~1")}`)),
  ];
  expect(pointers.length, "the golden holds enough distinct records for a capped list").toBeGreaterThanOrEqual(model.EVIDENCE_REFS_CAP);
  return pointers.slice(0, model.EVIDENCE_REFS_CAP).map((p) => ({ kind: "analysis_row", host: null, ref: p, role: "derived_from", cite: p }));
};

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
  it("compiles basis and refs, keeping each ref's fields", () => {
    const refs = [ref(), ref({ kind: "analysis_row", host: null, ref: "/health_scores/0", role: "derived_from", cite: "health score" })];
    const set = compile(withRow({ evidence_basis: "record", evidence_refs: refs }));
    const f = set.fabric.findings[0] as Finding;
    expect(f.evidenceBasis).toBe("record");
    expect(f.evidenceRefs).toEqual(refs.map(compiled));
    expect(f.evidenceRefsTotal).toBeNull();
  });

  it("compiles a CAPPED list with its uncapped total (the only form a total is written in)", () => {
    /* The earlier control here carried a total of 5 on a 2-ref list — which the engine never writes
       (tests/test_punchlist_evidence_refs.py: a total only when the list was capped). Moved, not dropped: the
       compile of a total is proven on the form the contract allows. */
    const refs = cappedRefs();
    const set = compile(withRow({ evidence_basis: "row", evidence_refs: refs, evidence_refs_total: refs.length + 6 }));
    const f = set.fabric.findings[0] as Finding;
    expect(f.evidenceRefs).toHaveLength(model.EVIDENCE_REFS_CAP);
    expect(f.evidenceRefsTotal).toBe(model.EVIDENCE_REFS_CAP + 6);
  });

  it("an absence basis with witness refs compiles", () => {
    const refs = [ref({ kind: "absence_witness", role: "witness", ref: "/security/core1", cite: "core1 security record" })];
    const s = withRow({ evidence_basis: "absence", evidence_refs: refs });
    expect(Object.hasOwn(s, "security")).toBe(true);
    expect(codeOf(s)).toBe("OK");
  });

  it("the compiler's vocabularies are exactly the ones the types declare", () => {
    expect(sorted(COMPILER_KINDS)).toEqual(sorted(EVIDENCE_REF_KINDS));
    expect(sorted(COMPILER_ROLES)).toEqual(sorted(EVIDENCE_REF_ROLES));
    expect(sorted(COMPILER_BASES)).toEqual(sorted(EVIDENCE_BASES));
  });
});

describe("ONE contract: every vocabulary and rule the compiler enforces is the engine contract's (R3 / X6)", () => {
  /* Before: EVIDENCE_REF_KINDS / ROLES / BASES were hand-copied from cisco_toolkit/analyze.py, and the only
     engine-app binding was the golden compile, which exercises only the kinds the golden emits (never acl_line or
     route). Now the compiler READS atlas-scope/contracts/engine-contract.v1.json, which the engine generates. */
  it("the contract file exists and is the engine's (schema and owner)", () => {
    const c = contractFile();
    expect(c.schema).toBe("atlas-engine-contract/1");
    expect(c.owner).toBe("cisco_toolkit/analyze.py");
  });

  it("the compiler's accepted vocabularies EQUAL the contract's — kinds, record kinds, roles, bases, cap, protocol states", () => {
    const pe = contractFile().punch_evidence as Record<string, any>;
    expect(sorted(model.EVIDENCE_REF_KINDS)).toEqual(sorted(pe.kinds as string[]));
    expect(sorted(model.EVIDENCE_RECORD_KINDS)).toEqual(sorted(pe.record_kinds as string[]));
    expect(sorted(model.EVIDENCE_REF_ROLES)).toEqual(sorted(pe.roles as string[]));
    expect(sorted(model.EVIDENCE_BASES)).toEqual(sorted(pe.bases as string[]));
    expect(model.EVIDENCE_REFS_CAP).toBe(pe.cap);
    expect(sorted(model.PROTOCOL_ASSESSABILITY_STATES)).toEqual(sorted(contractFile().protocol_assessability_states as string[]));
  });

  it("…and so do the types the UI is checked against", () => {
    const pe = contractFile().punch_evidence as Record<string, any>;
    expect(sorted(EVIDENCE_REF_KINDS)).toEqual(sorted(pe.kinds as string[]));
    expect(sorted(EVIDENCE_REF_ROLES)).toEqual(sorted(pe.roles as string[]));
    expect(sorted(EVIDENCE_BASES)).toEqual(sorted(pe.bases as string[]));
  });

  it("a cheap text tripwire (NOT the guard): no frozen literal list of evidence kinds or roles, no state literal, in compile-model.mjs", () => {
    /* Verifier R3-V5a: this catches one SPELLING of a hand copy only (Object.freeze([...])); a Set, a plain array
       or a switch passes it. The guard for the class is the behavioural block below ("the compile path reads the
       contract…"), which compiles against a PERTURBED contract. This stays as an early, specific signal. */
    /* `readCollectionCompleteness` reads the engine's `collection_completeness.summary.not_collected` COUNT — a field
       name of another engine block (acceptance B7), not a protocol-assessability state value — so its body is the
       one span this spelling check does not read. Everything else in the file still is. */
    const whole = readFileSync(resolve(REPO, "atlas-scope", "tools", "lib", "compile-model.mjs"), "utf8");
    const span = /\nexport function readCollectionCompleteness\(cc\) \{\n[\s\S]*?\n\}\n/.exec(whole);
    expect(span, "the collection-completeness reader is where this exclusion says it is").not.toBeNull();
    expect(span![0].match(/"not_collected"/g)?.length, "it reads the summary key once, as a key").toBe(1);
    const text = whole.replace(span![0], "\n");
    // A frozen literal list of kinds or roles is the hand copy this cluster deleted; any such list is a new one.
    expect(text).not.toMatch(/Object\.freeze\(\[\s*"(interface|acl_line|route|config_text|device_fact|analysis_row|adjacency|absence_witness)"/);
    expect(text).not.toMatch(/Object\.freeze\(\[\s*"(subject|derived_from|witness)"/);
    expect(text).not.toMatch(/"not_collected"|"captured_empty"|"analysis_unavailable"/);
  });

  it("every rule the contract states is enforced: the rule set the compiler knows equals the contract's", () => {
    const pe = contractFile().punch_evidence as Record<string, unknown>;
    const ruleKeys = Object.keys(pe).filter((k) => typeof pe[k] === "boolean").sort();
    expect(ruleKeys.length, "the contract states rules (not vacuous)").toBeGreaterThan(0);
    expect(Object.keys(model.ENGINE_CONTRACT.punchEvidence.rules).sort()).toEqual(ruleKeys);
    for (const k of ruleKeys) expect(model.ENGINE_CONTRACT.punchEvidence.rules[k], k).toBe(pe[k]);
  });

  it.each([
    ["an unknown punch_evidence rule (an engine rule the compiler would not enforce)", (c: Record<string, any>) => void (c.punch_evidence.refs_must_be_sorted = true)],
    ["a rule that is not a boolean", (c: Record<string, any>) => void (c.punch_evidence.row_requires_ref = "yes")],
    ["a missing rule", (c: Record<string, any>) => void delete c.punch_evidence.host_must_be_row_device_or_null],
    ["a record kind that is not a kind", (c: Record<string, any>) => void c.punch_evidence.record_kinds.push("vibe")],
    ["an unknown schema", (c: Record<string, any>) => void (c.schema = "atlas-engine-contract/2")],
    ["an empty state list", (c: Record<string, any>) => void (c.protocol_assessability_states = [])],
    ["an unknown top-level key", (c: Record<string, any>) => void (c.extra = 1)],
  ])("a malformed contract is refused, never defaulted: %s", (_why, bend) => {
    const good = contractFile();
    expect(() => model.readEngineContract(good), "positive control: the real contract reads").not.toThrow();
    const bad = structuredClone(good);
    bend(bad);
    let code = "OK";
    try {
      model.readEngineContract(bad);
    } catch (e) {
      code = e instanceof CompileError ? e.code : String(e);
    }
    expect(code).toBe("E_ENGINE_CONTRACT");
  });
});

describe("every contract rule is enforced at compile time, with a code (S1-R2V-6)", () => {
  /* Measured by the verifier: the real engine on-disk output compiled with exit 0 while the engine's own check
     failed on it ("ref /cross_layer/0 claims host core1 but ..."), because the compiler checked only
     `total >= refs.length`. Each case below breaks exactly ONE rule on an otherwise valid row. */
  const rowRef = (over: Record<string, unknown> = {}) => ref({ kind: "analysis_row", host: null, ref: "/health_scores/0", role: "derived_from", cite: "health score", ...over });
  const cases: [string, Record<string, unknown>, string][] = [
    ["refs with no basis (basis required)", { evidence_refs: [ref()] }, "E_EVIDENCE_CONTRACT"],
    ["a basis with no refs list", { evidence_basis: "row" }, "E_EVIDENCE_CONTRACT"],
    ["a ref about a host the row does not name", { devices: ["core1"], evidence_basis: "record", evidence_refs: [ref({ host: "core2", ref: "/interfaces/core2" })] }, "E_EVIDENCE_CONTRACT"],
    ["basis record with no record-kind ref", { evidence_basis: "record", evidence_refs: [rowRef()] }, "E_EVIDENCE_CONTRACT"],
    ["basis absence carrying a record kind", { evidence_basis: "absence", evidence_refs: [ref()] }, "E_EVIDENCE_CONTRACT"],
    ["basis row with no ref at all", { evidence_basis: "row", evidence_refs: [] }, "E_EVIDENCE_CONTRACT"],
    ["a total equal to the number of refs (not capped)", { evidence_basis: "record", evidence_refs: [ref()], evidence_refs_total: 1 }, "E_EVIDENCE_CONTRACT"],
    ["a total above an UNCAPPED list", { evidence_basis: "record", evidence_refs: [ref(), rowRef()], evidence_refs_total: 5 }, "E_EVIDENCE_CONTRACT"],
  ];
  it.each(cases)("%s → %s", (_why, extra, code) => {
    expect(codeOf(withRow({ devices: ["core1"], ...extra }))).toBe(code);
  });

  it("a list ONE longer than the cap, with no total, is refused by the cap rule itself (R3-V3)", () => {
    /* The case below also carries evidence_refs_total, so the total rule refuses it first with the same code —
       removing the cap check left every test green (verifier R3-V3). Here nothing but the length is wrong: a
       row basis, distinct resolvable refs, and no total. The message must be the CAP's. */
    const refs = [...cappedRefs(), rowRef({ ref: "/security/core1", cite: "one past the cap" })];
    expect(new Set(refs.map((r) => r.ref)).size, "every ref is distinct (no other rule applies)").toBe(refs.length);
    expect(refs).toHaveLength(model.EVIDENCE_REFS_CAP + 1);
    let err: unknown;
    try {
      compile(withRow({ devices: ["core1"], evidence_basis: "row", evidence_refs: refs }));
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(CompileError);
    expect((err as CompileError).code).toBe("E_EVIDENCE_CONTRACT");
    expect((err as CompileError).message).toContain(`caps a row at ${model.EVIDENCE_REFS_CAP}`);
    expect((err as CompileError).path).toBe("punchlist[0].evidence_refs");
    // Control: exactly the cap, same shape, compiles.
    expect(codeOf(withRow({ devices: ["core1"], evidence_basis: "row", evidence_refs: refs.slice(0, model.EVIDENCE_REFS_CAP) }))).toBe("OK");
  });

  it("a list longer than the cap is refused; the capped list with a larger total compiles (control)", () => {
    const refs = cappedRefs();
    expect(codeOf(withRow({ evidence_basis: "row", evidence_refs: [...refs, rowRef({ ref: "/health_scores/1" })], evidence_refs_total: refs.length + 7 }))).toBe("E_EVIDENCE_CONTRACT");
    expect(codeOf(withRow({ evidence_basis: "row", evidence_refs: refs, evidence_refs_total: refs.length + 7 }))).toBe("OK");
    expect(codeOf(withRow({ evidence_basis: "row", evidence_refs: refs, evidence_refs_total: refs.length }))).toBe("E_EVIDENCE_CONTRACT");
  });

  it.each([
    ["a record basis backed by a record ref", { evidence_basis: "record", evidence_refs: [ref(), rowRef()] }],
    ["an absence basis with witnesses only", { evidence_basis: "absence", evidence_refs: [ref({ kind: "absence_witness", role: "witness", ref: "/security/core1", cite: "core1 security record" })] }],
    ["an absence basis with NO ref (nothing to witness is allowed; a row basis is not)", { evidence_basis: "absence", evidence_refs: [] }],
    ["a row basis with its row", { evidence_basis: "row", evidence_refs: [rowRef()] }],
    ["a null-hosted ref on a row that names devices", { evidence_basis: "record", evidence_refs: [ref({ host: null })] }],
  ])("control: %s compiles", (_why, extra) => {
    expect(codeOf(withRow({ devices: ["core1"], ...extra }))).toBe("OK");
  });
});

describe("the compile PATH accepts every kind the contract names — not only the ones the golden emits (R3-V5b)", () => {
  /* The vocabulary-equality test compares exports READ from the contract, so it cannot fail while they are wired
     to it; the golden never emits acl_line or route. Each contract kind is compiled here through the real path:
     a record kind under a "record" basis (it must back it), any other kind under a "row" basis. */
  const kinds = (contractFile().punch_evidence as { kinds: string[] }).kinds;
  const recordKinds = (contractFile().punch_evidence as { record_kinds: string[] }).record_kinds;
  it("the contract names kinds the golden never emits (so this block covers more than the golden does)", () => {
    const emitted = new Set(
      (JSON.parse(GOLDEN) as { punchlist: { evidence_refs?: { kind: string }[] }[] }).punchlist.flatMap((r) => (r.evidence_refs ?? []).map((x) => x.kind)),
    );
    expect(kinds.filter((k) => !emitted.has(k)).length).toBeGreaterThan(0);
  });
  it.each(kinds)("a ref of kind %s compiles, and reaches the finding with that kind", (kind) => {
    const isRecord = recordKinds.includes(kind);
    const r = ref({ kind, host: "core1", role: kind === "absence_witness" ? "witness" : "subject" });
    const f = compile(withRow({ devices: ["core1"], evidence_basis: isRecord ? "record" : "row", evidence_refs: [r] })).fabric.findings[0] as Finding;
    expect(f.evidenceBasis).toBe(isRecord ? "record" : "row");
    expect(f.evidenceRefs).toEqual([compiled(r)]);
  });
  it.each((contractFile().punch_evidence as { roles: string[] }).roles)("a ref of role %s compiles", (role) => {
    expect(codeOf(withRow({ devices: ["core1"], evidence_basis: "record", evidence_refs: [ref({ role })] }))).toBe("OK");
  });
});

describe("the compile path reads the contract, and holds no copy of it anywhere (R3-V5a)", () => {
  /* THE CLASS GUARD. A hand-kept copy of a vocabulary — in any spelling: a frozen list, a Set, a switch, an
     inline comparison — would keep accepting the OLD names. So the compiler is loaded against a PERTURBED
     contract (every kind, record kind, role and protocol state renamed, the cap lowered) and must then accept
     exactly the renamed vocabulary and refuse the real one. Only a compile path that reads every vocabulary
     and the cap from the contract passes both halves. */
  const CONTRACT_MODULE = "../../contracts/engine-contract.v1.json";
  const rename = (xs: string[], p: string): string[] => xs.map((x) => `${p}${x}`);
  const perturbed = (): Record<string, any> => {
    const c = contractFile();
    c.punch_evidence.kinds = rename(c.punch_evidence.kinds as string[], "k_");
    c.punch_evidence.record_kinds = rename(c.punch_evidence.record_kinds as string[], "k_");
    c.punch_evidence.roles = rename(c.punch_evidence.roles as string[], "r_");
    c.punch_evidence.cap = 3;
    c.protocol_assessability_states = rename(c.protocol_assessability_states as string[], "s_");
    return c;
  };
  type Loaded = {
    model: typeof import("../../tools/lib/compile-model.mjs");
    compile: (snap: Record<string, unknown>) => ReturnType<typeof compileAll>;
    code: (snap: Record<string, unknown>) => string;
  };
  async function load(contract: Record<string, any>): Promise<Loaded> {
    vi.resetModules();
    vi.doMock(CONTRACT_MODULE, () => ({ default: contract }));
    try {
      const m = await import("../../tools/lib/compile-model.mjs");
      const binding = await import("../../tools/source-binding.mjs");
      const validate = await import("../../tools/lib/validate-snapshot.mjs");
      const compileWith = (snap: Record<string, unknown>) => {
        const bytes = new TextEncoder().encode(JSON.stringify(snap));
        const v = validate.assertValidSnapshot(bytes);
        return m.compileAll(v.snap, binding.bindSource(bytes, { source: "case.json", sourceOrigin: "external-file" }), { schemaAssumed: v.schemaAssumed });
      };
      const code = (snap: Record<string, unknown>): string => {
        try {
          compileWith(snap);
          return "OK";
        } catch (e) {
          if (e instanceof m.CompileError) return e.code;
          throw e;
        }
      };
      return { model: m, compile: compileWith, code };
    } finally {
      vi.doUnmock(CONTRACT_MODULE);
      vi.resetModules();
    }
  }
  /** The golden with every protocol state renamed the way the perturbed contract names them. */
  const renamedStates = (s: Record<string, any>): Record<string, any> => {
    for (const r of s.protocol_assessability.rows as { state?: unknown }[]) if (typeof r.state === "string") r.state = `s_${r.state}`;
    return s;
  };

  it("positive control: the real contract, loaded the same way, accepts the real vocabulary", async () => {
    const real = await load(contractFile());
    expect(real.code(withRow({ devices: ["core1"], evidence_basis: "record", evidence_refs: [ref()] }))).toBe("OK");
    expect(real.model.EVIDENCE_REFS_CAP).toBe(contractFile().punch_evidence.cap);
  });

  /* ONE record per test (vitest.config.ts: a large unit of work is split, not given a bigger limit — as one test
     this timed out at 30 s under host contention). The perturbed compiler is loaded ONCE, the golden parsed once. */
  const P = { loaded: null as Loaded | null, base: null as Record<string, any> | null };
  beforeAll(async () => {
    P.loaded = await load(perturbed());
    P.base = renamedStates(withRow({ devices: ["core1"] }));
  });
  const p = (): Loaded => P.loaded!;
  const row = (extra: Record<string, unknown>): Record<string, any> => {
    const s = structuredClone(P.base!);
    s.punchlist[0] = { ...s.punchlist[0], ...extra };
    return s;
  };
  const pe = contractFile().punch_evidence as { kinds: string[]; record_kinds: string[]; roles: string[] };

  it("the perturbed contract was really loaded, and its base (renamed states, no evidence) compiles", () => {
    expect(p().model.EVIDENCE_REF_KINDS).toEqual(rename(pe.kinds, "k_"));
    expect(p().model.EVIDENCE_REFS_CAP).toBe(3);
    expect(p().code(row({}))).toBe("OK");
  });
  it.each(rename(pe.kinds, "k_"))("the RENAMED kind %s compiles (a record kind under a record basis)", (kind) => {
    const isRecord = rename(pe.record_kinds, "k_").includes(kind);
    expect(p().code(row({ evidence_basis: isRecord ? "record" : "row", evidence_refs: [ref({ kind, role: "r_subject" })] }))).toBe("OK");
  });
  it.each(rename(pe.roles, "r_"))("the RENAMED role %s compiles", (role) => {
    expect(p().code(row({ evidence_basis: "record", evidence_refs: [ref({ kind: "k_interface", role })] }))).toBe("OK");
  });
  it.each(pe.kinds)("the REAL kind %s is refused: no copy of the real kinds survives anywhere in the path", (kind) => {
    expect(p().code(row({ evidence_basis: "row", evidence_refs: [ref({ kind, role: "r_subject" })] }))).toBe("E_EVIDENCE_CONTRACT");
  });
  it.each(pe.roles)("the REAL role %s is refused", (role) => {
    expect(p().code(row({ evidence_basis: "record", evidence_refs: [ref({ kind: "k_interface", role })] }))).toBe("E_EVIDENCE_CONTRACT");
  });
  it("the record-kind rule follows the renamed record kinds: a renamed NON-record kind cannot back a record basis", () => {
    expect(p().code(row({ evidence_basis: "record", evidence_refs: [ref({ kind: "k_analysis_row", host: null, ref: "/health_scores/0", role: "r_derived_from" })] }))).toBe("E_EVIDENCE_CONTRACT");
  });
  it("the cap is the contract's (3), not 64", () => {
    const refs = [0, 1, 2, 3].map((i) => ref({ kind: "k_analysis_row", host: null, ref: `/punchlist/${i}`, role: "r_derived_from", cite: `p${i}` }));
    expect(p().code(row({ evidence_basis: "row", evidence_refs: refs.slice(0, 3) }))).toBe("OK");
    expect(p().code(row({ evidence_basis: "row", evidence_refs: refs }))).toBe("E_EVIDENCE_CONTRACT");
  });
  it("protocol states are the contract's: a REAL state is refused under the renamed ones", () => {
    const s = row({});
    (s.protocol_assessability.rows as { state: unknown }[])[0]!.state = (contractFile().protocol_assessability_states as string[])[0];
    expect(p().code(s)).toBe("E_PROTOCOL_STATE");
  });

  it("the module registry is restored afterwards: the real contract is what the rest of this file compiles against", () => {
    expect(model.EVIDENCE_REF_KINDS).toContain("interface");
    expect(codeOf(withRow({ devices: ["core1"], evidence_basis: "record", evidence_refs: [ref()] }))).toBe("OK");
  });
});

describe("protocol_assessability states pass through, validated against the contract", () => {
  const withState = (state: unknown): Record<string, any> => {
    const s = golden();
    s.protocol_assessability.rows[0].state = state;
    return s;
  };
  it("every state the contract names compiles — the engine's newer ones (e.g. not_running) included", () => {
    for (const st of model.PROTOCOL_ASSESSABILITY_STATES) expect(codeOf(withState(st)), st).toBe("OK");
    expect(model.PROTOCOL_ASSESSABILITY_STATES, "the engine's no-process state is in the contract").toContain("not_running");
  });
  it("a state the contract does not name is refused (E_PROTOCOL_STATE), not passed through as an unknown string", () => {
    expect(codeOf(withState("probably_fine"))).toBe("E_PROTOCOL_STATE");
    expect(codeOf(withState(7))).toBe("E_PROTOCOL_STATE");
  });
  it("the state reaches the compiled RIB evidence verbatim for a routing row", () => {
    const s = golden();
    const i = (s.protocol_assessability.rows as Record<string, unknown>[]).findIndex((r) => ["ospf", "bgp", "eigrp", "isis"].includes(String(r.protocol).toLowerCase()));
    expect(i, "the golden carries a routing-protocol assessability row").toBeGreaterThanOrEqual(0);
    s.protocol_assessability.rows[i].state = "not_running";
    s.routing_neighbors = { ...(s.routing_neighbors ?? {}), [s.protocol_assessability.rows[i].switch]: { [String(s.protocol_assessability.rows[i].protocol).toLowerCase()]: [] } };
    const rib = compile(s).ribEvidence as { hosts: Record<string, { protocols: { protocol: string; state: string | null }[] }> };
    const row = rib.hosts[s.protocol_assessability.rows[i].switch]?.protocols.find((p) => p.protocol === s.protocol_assessability.rows[i].protocol);
    expect(row?.state).toBe("not_running");
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
    /* Every case states a valid basis unless it is the case's subject, so each fails ONLY for the reason it
       names — never for the separate "basis required" rule, which shares the code E_EVIDENCE_CONTRACT. */
    expect(codeOf(withRow({ evidence_basis: "record", ...extra }))).toBe(code);
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
      const s = withRow({ evidence_basis: "row", evidence_refs: [ref({ kind: "analysis_row", host: null, ref: "/health_scores/0/score", role: "derived_from", cite: "score" })] });
      s.health_scores[0].score = score;
      return s;
    };
    expect(codeOf(at(3))).toBe("OK");
    expect(codeOf(at(null))).toBe("E_EVIDENCE_REF_UNRESOLVED");
  });

  it("a ref into a whole section the file does not carry says so, in plain language", () => {
    /* The pipeline golden used to be the case in point (its harness stripped device_dossiers while its refs
       cited it). It now keeps the section, so the case is BUILT: the section is removed here explicitly, and
       the row is otherwise valid (a row basis), so the only thing wrong is the missing section. The refusal
       must name the missing SECTION, not only the missing member. */
    let err: CompileError | undefined;
    const s = withRow({ evidence_basis: "row", evidence_refs: [ref({ kind: "analysis_row", host: null, ref: "/device_dossiers/per_device/0", role: "derived_from" })] });
    delete s.device_dossiers;
    try {
      compile(s);
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
