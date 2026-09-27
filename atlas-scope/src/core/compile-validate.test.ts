// @vitest-environment node
/**
 * compile-validate.test.ts — a file that is not a supported snapshot is REFUSED with a coded,
 * plain-language reason; it is never compiled into an empty or partial network.
 *
 * WHAT WAS WRONG (measured 2026-09-26 against the four compilers as they shipped, discovery report
 * "compiler-any-snapshot" §3): a byte-order mark and a NaN number crashed every compiler with a raw
 * `SyntaxError: Unexpected token`; `{}`, `[]` and a devices.json inventory compiled with exit 0 into an
 * EMPTY model carrying a sha — an empty file rendered as an empty, healthy-looking network; duplicate
 * keys were accepted last-one-wins (the engine refuses them, protocol_assurance.py
 * `reject_duplicate_json_keys`); `collect_parse_snapshot/2` compiled silently; and every real fleet
 * with a Multicast/Media finding stopped the build with an uncoded Error.
 *
 * Every case below is built from a REAL producer's output (the repository's golden snapshot, or the
 * repository's own devices.example.json), altered in exactly one way, so the refusal is attributable
 * to that one alteration. The table is the class the brief names; each row asserts the exact code.
 *
 * THE BASE (verifier S1-V1). The golden is used with the per-finding evidence contract (evidence_basis,
 * evidence_refs, evidence_refs_total) removed from every punch-list row — the shape every producer before
 * that contract wrote, which the compiler reads as "not emitted". The golden AS PUBLISHED is a stripped
 * derivative (tests/test_pipeline_golden.py pops device_dossiers and other date-relative sections, into
 * which the engine's refs legitimately point), so it does not resolve its own pointers; when the engine
 * lane regenerated it, every positive control here turned red for a reason unrelated to the case. The
 * golden as published is compiled once, explicitly, in compile-all.test.ts (R6); the evidence contract's
 * own cases live in compile-evidence.test.ts.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { bindSource } from "../../tools/source-binding.mjs";
import { CompileError, compileAll, serialiseCompiled } from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot, validateSnapshot, DEFAULT_MAX_SNAPSHOT_BYTES } from "../../tools/lib/validate-snapshot.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPO = resolve(PKG, "..");
const GOLDEN_BYTES = (() => {
  const s = JSON.parse(readFileSync(resolve(REPO, "tests", "golden", "snapshot.json"), "utf8")) as { punchlist: Record<string, unknown>[] };
  s.punchlist = s.punchlist.map((row) =>
    Object.fromEntries(Object.entries(row).filter(([k]) => k !== "evidence_basis" && k !== "evidence_refs" && k !== "evidence_refs_total")),
  );
  return Buffer.from(JSON.stringify(s, null, 2), "utf8");
})();
const GOLDEN_TEXT = GOLDEN_BYTES.toString("utf8");
const golden = (): Record<string, any> => JSON.parse(GOLDEN_TEXT) as Record<string, any>;
const enc = (s: string): Uint8Array => new TextEncoder().encode(s);
const json = (v: unknown): Uint8Array => enc(JSON.stringify(v, null, 1));

/** Replace the FIRST occurrence of `find` in the golden text; fail loudly if it is not there. */
const goldenWith = (find: string, replace: string): Uint8Array => {
  const at = GOLDEN_TEXT.indexOf(find);
  expect(at, `the golden snapshot must contain ${JSON.stringify(find)}`).toBeGreaterThan(0);
  return enc(GOLDEN_TEXT.slice(0, at) + replace + GOLDEN_TEXT.slice(at + find.length));
};

/** Validate, bind and compile — the whole path a caller takes. Returns the first coded failure. */
function codeOf(bytes: Uint8Array, opts: { allowLegacy?: boolean; maxBytes?: number } = {}): string {
  try {
    const { snap, schemaAssumed } = assertValidSnapshot(bytes, opts);
    compileAll(snap, bindSource(bytes, { source: "case.json", sourceOrigin: "external-file" }), { schemaAssumed });
    return "OK";
  } catch (e) {
    if (e instanceof CompileError) return e.code;
    throw e; // an UNCODED failure is itself the defect this file exists to refuse
  }
}

describe("every input class the brief names gets its exact code", () => {
  const nanScore = (): Uint8Array => goldenWith('"score": 3,', '"score": NaN,');
  const cases: [string, () => Uint8Array, string, { allowLegacy?: boolean }?][] = [
    ["the golden snapshot itself (positive control)", () => GOLDEN_BYTES, "OK"],
    ["a UTF-8 byte-order mark", () => new Uint8Array([0xef, 0xbb, 0xbf, ...GOLDEN_BYTES]), "E_BOM"],
    ["a UTF-16 byte-order mark", () => new Uint8Array([0xff, 0xfe, 0x7b, 0x00, 0x7d, 0x00]), "E_BOM"],
    ["bytes that are not UTF-8", () => new Uint8Array([0x7b, 0x22, 0x61, 0x22, 0x3a, 0x22, 0xc3, 0x28, 0x22, 0x7d]), "E_NOT_UTF8"],
    ["a NaN number (Python json.dump's default)", nanScore, "E_NOT_JSON"],
    ["an Infinity number", () => goldenWith('"score": 3,', '"score": Infinity,'), "E_NOT_JSON"],
    ["a -Infinity number", () => goldenWith('"score": 3,', '"score": -Infinity,'), "E_NOT_JSON"],
    ["a truncated file", () => GOLDEN_BYTES.subarray(0, Math.floor(GOLDEN_BYTES.byteLength / 2)), "E_NOT_JSON"],
    ["an empty file", () => new Uint8Array(0), "E_NOT_JSON"],
    ["a duplicate top-level key", () => enc('{"devices":{"a":{}},"devices":{"b":{}}}'), "E_DUPLICATE_KEY"],
    ["a duplicate key nested in a real record", () => goldenWith('"score": 3,', '"score": 3, "score": 4,'), "E_DUPLICATE_KEY"],
    ["a duplicate key spelled with an escape", () => enc('{"schema":"collect_parse_snapshot/1","a":1,"\\u0061":2}'), "E_DUPLICATE_KEY"],
    ["an empty object", () => enc("{}"), "E_NOT_A_SNAPSHOT"],
    ["an array root", () => enc("[]"), "E_ROOT_NOT_OBJECT"],
    ["a scalar root", () => enc("42"), "E_ROOT_NOT_OBJECT"],
    ["the repository's devices.json inventory", () => readFileSync(resolve(REPO, "devices.example.json")), "E_ROOT_NOT_OBJECT"],
    ["an inventory wrapped in an object", () => json({ devices: JSON.parse(readFileSync(resolve(REPO, "devices.example.json"), "utf8")) }), "E_NOT_A_SNAPSHOT"],
    ["another engine document (a traffic-assurance set)", () => json({ schema: "traffic_assurance_set/1", flows: [] }), "E_NOT_A_SNAPSHOT"],
    ["a non-string schema tag", () => json({ ...golden(), schema: 1 }), "E_NOT_A_SNAPSHOT"],
    ["collect_parse_snapshot/2", () => goldenWith('"schema": "collect_parse_snapshot/1"', '"schema": "collect_parse_snapshot/2"'), "E_SCHEMA_UNSUPPORTED"],
    ["a legacy snapshot with no schema key", () => json(Object.fromEntries(Object.entries(golden()).filter(([k]) => k !== "schema"))), "E_SCHEMA_UNSUPPORTED"],
    [
      "a legacy snapshot with no schema key, --allow-legacy",
      () => json(Object.fromEntries(Object.entries(golden()).filter(([k]) => k !== "schema"))),
      "OK",
      { allowLegacy: true },
    ],
    [
      "a section the compilers read, at an unknown section schema",
      () => goldenWith('"schema": "protocol_assessability/1"', '"schema": "protocol_assessability/2"'),
      "E_SECTION_SCHEMA",
    ],
    [
      "a Multicast/Media row carrying severity_basis and evidence_confidence (the engine always writes both)",
      () => {
        const s = golden();
        s.punchlist.push({
          ...s.punchlist[0],
          category: "Multicast/Media",
          severity_basis: "severity basis NOT published by this snapshot — check the finding's own detail for what it rests on",
          evidence_confidence: "evidence confidence NOT published by this snapshot",
        });
        return json(s);
      },
      "OK",
    ],
    ["a punch-list key no compiler knows", () => json({ ...golden(), punchlist: [{ ...golden().punchlist[0], shiny_new_field: 1 }] }), "E_UNKNOWN_PRODUCER_FIELD"],
    [
      "object-shaped health deductions",
      () => {
        const s = golden();
        s.health_scores[0].deductions = [{ reason: "x", points: -8 }];
        return json(s);
      },
      "E_NON_PRIMITIVE",
    ],
    ["a snapshot with no device at all", () => json({ schema: "collect_parse_snapshot/1", devices: {}, cable_map: { nodes: [], cables: [] }, punchlist: [] }), "E_EMPTY_FABRIC"],
    /* The shape class: a record where the engine writes an object is null / a scalar. Each of these
       used to escape as a raw TypeError from whichever reader met it first. */
    ["a null punch-list row", () => json({ ...golden(), punchlist: [null] }), "E_SNAPSHOT_SHAPE"],
    ["a null cable-map node", () => json({ ...golden(), cable_map: { ...golden().cable_map, nodes: [null] } }), "E_SNAPSHOT_SHAPE"],
  ];

  it.each(cases)("%s → %s", (_why, make, code, opts) => {
    expect(codeOf(make(), opts ?? {})).toBe(code);
  });

  it("refuses a file above the size cap before it parses anything", () => {
    expect(DEFAULT_MAX_SNAPSHOT_BYTES).toBeGreaterThan(GOLDEN_BYTES.byteLength);
    expect(codeOf(GOLDEN_BYTES, { maxBytes: 1024 })).toBe("E_TOO_LARGE");
  });
});

describe("only a shape failure is blamed on the input (S1-V8)", () => {
  const label = { source: "case.json", sourceOrigin: "external-file" } as const;

  it("a malformed record is E_SNAPSHOT_SHAPE, worded as input OR compiler defect, with the TypeError kept as its cause", () => {
    const bytes = json({ ...golden(), punchlist: [null] });
    let err: unknown;
    try {
      compileAll(assertValidSnapshot(bytes).snap, bindSource(bytes, label), {});
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(CompileError);
    expect((err as CompileError).code).toBe("E_SNAPSHOT_SHAPE");
    expect((err as CompileError).message).toMatch(/compiler has a defect/);
    expect((err as Error & { cause?: unknown }).cause).toBeInstanceOf(TypeError);
  });

  it("any other failure inside the compiler propagates as itself — it is not evidence about the snapshot", () => {
    /* Before: EVERY non-CompileError — a ReferenceError from a compiler bug included — became
       E_SNAPSHOT_SHAPE, "a record in this snapshot is not the shape the engine writes", and the stack was
       dropped. A RangeError is injected here through a getter on a section the compiler reads. */
    const snap = golden();
    Object.defineProperty(snap, "punchlist", {
      get() {
        throw new RangeError("injected compiler-side failure");
      },
    });
    expect(() => compileAll(snap, bindSource(GOLDEN_BYTES, label), {})).toThrow(RangeError);
  });
});

describe("the refusal says what is wrong and where, in plain language", () => {
  it("a NaN names the non-finite number, where it is, and that the engine refuses it too", () => {
    const r = validateSnapshot(goldenWith('"score": 3,', '"score": NaN,'));
    expect(r.ok).toBe(false);
    const e = r.errors[0]!;
    expect(e.code).toBe("E_NOT_JSON");
    expect(e.path).toBe("/health_scores/0/score");
    expect(e.message).toMatch(/non-finite number/i);
    expect(e.message).toMatch(/engine/i);
    expect(e.line).toBeGreaterThan(1);
    expect(e.column).toBeGreaterThan(0);
  });

  it("a syntax error gives a line, a column and a snippet of the text at that point", () => {
    const r = validateSnapshot(enc('{\n "schema": "collect_parse_snapshot/1",\n "devices": {,}\n}'));
    const e = r.errors[0]!;
    expect(e.code).toBe("E_NOT_JSON");
    expect(e.line).toBe(3);
    expect(e.column).toBe(14);
    expect(e.snippet).toContain('"devices": {,}');
  });

  it("a duplicate key names its JSON pointer; JSON.parse alone would have kept the last silently", () => {
    const bytes = enc('{"schema":"collect_parse_snapshot/1","devices":{"a~b/c":{"x":1,"x":2}}}');
    const r = validateSnapshot(bytes);
    expect(r.errors.map((e) => [e.code, e.path])).toEqual([["E_DUPLICATE_KEY", "/devices/a~0b~1c/x"]]);
    // The silent alternative, measured: this is what the compilers used to do.
    expect(JSON.parse(new TextDecoder().decode(bytes)).devices["a~b/c"].x).toBe(2);
  });

  it("a BOM is named as a BOM, not as an 'unexpected token'", () => {
    const e = validateSnapshot(new Uint8Array([0xef, 0xbb, 0xbf, 0x7b, 0x7d])).errors[0]!;
    expect(e.code).toBe("E_BOM");
    expect(e.message).toMatch(/byte-order mark/i);
  });

  it("an unsupported schema names the supported one; a legacy file names --allow-legacy", () => {
    const v2 = validateSnapshot(goldenWith('"schema": "collect_parse_snapshot/1"', '"schema": "collect_parse_snapshot/2"'));
    expect(v2.errors[0]!.message).toContain("collect_parse_snapshot/1");
    const legacy = validateSnapshot(json(Object.fromEntries(Object.entries(golden()).filter(([k]) => k !== "schema"))));
    expect(legacy.errors[0]!.message).toContain("--allow-legacy");
  });

  it("every coded error carries a message a reader can act on (non-empty, no raw 'Unexpected token')", () => {
    const inputs = [enc("{}"), enc("[]"), enc("{"), enc('{"a":NaN}'), new Uint8Array([0xef, 0xbb, 0xbf])];
    for (const b of inputs) {
      const r = validateSnapshot(b);
      expect(r.ok).toBe(false);
      for (const e of r.errors) {
        expect(e.code).toMatch(/^E_[A-Z_]+$/);
        expect(e.message.length).toBeGreaterThan(20);
        expect(e.message).not.toMatch(/Unexpected token/);
      }
    }
  });
});

describe("warnings are shown and never block", () => {
  it("the golden snapshot carries no collected_at/generated_at: warned, still compiled", () => {
    const r = validateSnapshot(GOLDEN_BYTES);
    expect(r.ok).toBe(true);
    const codes = r.warnings.map((w) => w.code);
    expect(codes).toContain("W_COLLECTED_AT_MISSING");
    expect(codes).toContain("W_GENERATED_AT_MISSING");
  });

  it("a legacy file compiled under --allow-legacy stamps the assumed schema into meta", () => {
    const bytes = json(Object.fromEntries(Object.entries(golden()).filter(([k]) => k !== "schema")));
    const { snap, schemaAssumed, warnings } = assertValidSnapshot(bytes, { allowLegacy: true });
    expect(schemaAssumed).toBe("collect_parse_snapshot/1");
    expect(warnings.map((w) => w.code)).toContain("W_SCHEMA_ASSUMED");
    const set = compileAll(snap, bindSource(bytes, { source: "legacy.json", sourceOrigin: "external-file" }), { schemaAssumed });
    expect(set.fabric.meta.schema).toBeNull();
    expect(set.fabric.meta.schemaAssumed).toBe("collect_parse_snapshot/1");
  });

  it("a schema-bearing snapshot assumes nothing", () => {
    const { snap, schemaAssumed } = assertValidSnapshot(GOLDEN_BYTES);
    expect(schemaAssumed).toBeNull();
    const set = compileAll(snap, bindSource(GOLDEN_BYTES, { source: "tests/golden/snapshot.json", sourceOrigin: "repository-file" }), { schemaAssumed });
    expect(set.fabric.meta.schemaAssumed).toBeNull();
  });
});

describe("the engine's on-disk form compiles to the same content", () => {
  /* The engine writes `<output>.snapshot.json` compact (separators=(",",":"), ensure_ascii=False) with
     sparsified interfaces (COLLECT_PARSE_V3_23_0.py `write_json_file(..., sparsify_interfaces(snap), compact=True)`).
     The rule is restated here from cisco_toolkit/html.py `sparsify_interfaces`, and that source line is
     PINNED below, so a change in the producer's rule fails this test instead of leaving it asserting a
     rule the engine no longer applies. */
  const HTML_PY = readFileSync(resolve(REPO, "cisco_toolkit", "html.py"), "utf8");

  it("the producer's sparsify rule is still the one restated here", () => {
    expect(HTML_PY).toContain('if v != "" and not (k == "run_config_observed" and v is False)}');
  });

  it("a sparse, compact copy of the golden compiles to byte-identical content, apart from the binding", () => {
    const dense = golden();
    const sparse = {
      ...dense,
      interfaces: Object.fromEntries(
        Object.entries(dense.interfaces as Record<string, Record<string, Record<string, unknown>>>).map(([h, ports]) => [
          h,
          Object.fromEntries(
            Object.entries(ports).map(([p, rec]) => [p, Object.fromEntries(Object.entries(rec).filter(([k, v]) => v !== "" && !(k === "run_config_observed" && v === false)))]),
          ),
        ]),
      ),
    };
    const compactBytes = enc(JSON.stringify(sparse));
    expect(compactBytes.byteLength).toBeLessThan(GOLDEN_BYTES.byteLength); // the transform did something
    const label = { source: "case.json", sourceOrigin: "external-file" } as const;
    const a = compileAll(assertValidSnapshot(GOLDEN_BYTES).snap, bindSource(GOLDEN_BYTES, label), {});
    const b = compileAll(assertValidSnapshot(compactBytes).snap, bindSource(compactBytes, label), {});
    const strip = (text: string): unknown => {
      const doc = JSON.parse(text) as { meta: Record<string, unknown> };
      return { ...doc, meta: { ...doc.meta, sourceSha256: null, sourceBytes: null, sourceExactSha256: null, sourceGitBlob: null } };
    };
    const sa = serialiseCompiled(a);
    const sb = serialiseCompiled(b);
    for (const k of Object.keys(sa) as (keyof typeof sa)[]) expect(strip(sb[k]), k).toEqual(strip(sa[k]));
  });
});
