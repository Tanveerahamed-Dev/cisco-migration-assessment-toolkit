/**
 * bindings-trust.test.ts — the sidecar's fail-closed guard, EXECUTED.
 *
 * `bindings.ts` refuses the whole of `acl-bindings.json` when its `meta.sourceSha256` differs from
 * `fabric.json`'s: every binding becomes `unknown` ("compiled from different snapshot bytes"), never
 * `bound` and never `none`. Until this file, no test ever reached that branch — the only data the
 * suite loaded was the matching pair, so `BINDINGS_TRUSTED` was always true and the refusal path was
 * a gate whose failure side had never run.
 *
 * Here the real sidecar is loaded, its digest is changed by one character (everything else
 * byte-for-byte the shipped content), and the module is re-imported against it. The positive
 * control runs first on the real file, so a refusal below cannot be explained by an empty file.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import real from "./acl-bindings.json";
import { fabric } from "../core/data";

type Sidecar = { meta: { sourceSha256: string }; hosts: Record<string, { port: string }[]> };
const REAL = real as unknown as Sidecar;

async function loadWith(sidecar: Sidecar): Promise<typeof import("./bindings")> {
  vi.resetModules();
  vi.doMock("./acl-bindings.json", () => ({ default: sidecar }));
  return import("./bindings");
}

/** Every (host, port, direction) the sidecar holds — the whole denominator, not a sample. */
const EVERY = Object.entries(REAL.hosts).flatMap(([host, recs]) =>
  recs.flatMap((r) => (["in", "out"] as const).map((dir) => ({ host, port: r.port, dir }))),
);

afterEach(() => {
  vi.doUnmock("./acl-bindings.json");
  vi.resetModules();
});

describe("acl-bindings.json is refused when it was compiled from other bytes", () => {
  it("positive control: the shipped pair agrees, and the sidecar holds observed bindings", async () => {
    const b = await loadWith(REAL);
    expect(REAL.meta.sourceSha256).toBe(fabric.meta.sourceSha256);
    expect(b.BINDINGS_TRUSTED).toBe(true);
    expect(EVERY.length).toBeGreaterThan(0);
    const kinds = EVERY.map((e) => b.bindingAt(e.host, e.port, e.dir).kind);
    expect(kinds).toContain("bound");
    expect(kinds).toContain("none");
  });

  it("a sidecar with a different sourceSha256 turns EVERY binding into unknown, with the reason", async () => {
    const sha = REAL.meta.sourceSha256;
    const other = `${sha[0] === "0" ? "1" : "0"}${sha.slice(1)}`;
    const stale: Sidecar = { ...REAL, meta: { ...REAL.meta, sourceSha256: other } };
    const b = await loadWith(stale);

    expect(b.BINDINGS_TRUSTED).toBe(false);
    const leaked = EVERY.map((e) => ({ ...e, s: b.bindingAt(e.host, e.port, e.dir) })).filter((e) => e.s.kind !== "unknown");
    expect(leaked.map((e) => `${e.host} ${e.port} ${e.dir}: ${e.s.kind}`)).toEqual([]);
    for (const e of EVERY) {
      const s = b.bindingAt(e.host, e.port, e.dir);
      expect(s.kind === "unknown" && s.reason).toMatch(/compiled from different snapshot bytes/);
      // Absence evidence, never topology: the reader is told the binding was not observed.
      expect(b.bindingEvidence(s).kind).toBe("absence");
    }
    // The coverage prose says so for every ACL-holding host rather than listing stale bindings.
    const sentences = b.bindingCoverageSentences();
    expect(sentences.length).toBeGreaterThan(0);
    for (const line of sentences) expect(line).toMatch(/are not read in this build/);
  });

  /* O15. A digest names bytes only together with the FORM it was taken over (tools/source-binding.mjs:
     LF-normalised). A sidecar whose digest string matches but that states another form — or states
     none, as every sidecar did before the canonical form existed — is a claim about different bytes
     that merely prints the same hex, and must be refused like any other mismatch. The same holds for
     a byte length that disagrees: the digest and the length are one binding, not two alternatives. */
  it.each([
    ["states a different digest form", (m: Record<string, unknown>) => ({ ...m, sourceDigestForm: "raw-working-tree" })],
    ["states no digest form at all", (m: Record<string, unknown>) => Object.fromEntries(Object.entries(m).filter(([k]) => k !== "sourceDigestForm"))],
    ["states a different byte length", (m: Record<string, unknown>) => ({ ...m, sourceBytes: Number(m.sourceBytes) + 1 })],
  ])("a sidecar with the same sourceSha256 that %s is refused", async (_why, rewrite) => {
    expect((REAL.meta as Record<string, unknown>).sourceDigestForm, "the shipped sidecar states its form").toBe(fabric.meta.sourceDigestForm);
    const b = await loadWith({ ...REAL, meta: rewrite(REAL.meta as Record<string, unknown>) as Sidecar["meta"] });
    expect(b.BINDINGS_TRUSTED).toBe(false);
    const kinds = new Set(EVERY.map((e) => b.bindingAt(e.host, e.port, e.dir).kind));
    expect([...kinds]).toEqual(["unknown"]);
  });
});

/* O15, FOR THE CLASS. A rule copied into one of the sidecar consumers is not a rule for the class:
   every compiled sidecar that binds itself to the snapshot's source bytes must be refused on ANY
   binding-field mismatch — digest, form, byte length, source — not only on a different digest.
   The denominator is structural: every JSON module under src/ (the snapshot itself excepted) whose
   `meta` carries a `sourceSha256` is a sidecar, and the partition check fails if one appears that
   this table does not exercise. */
describe("every source-bound sidecar consumer fails closed on any binding mismatch", () => {
  const SRC = resolve(__dirname, "..");
  const CONSUMERS: { json: string; mod: string; flag: string }[] = [
    { json: "forwarding/acl-bindings.json", mod: "./bindings", flag: "BINDINGS_TRUSTED" },
    { json: "forwarding/rib-evidence.json", mod: "./rib-completeness", flag: "RIB_EVIDENCE_TRUSTED" },
    { json: "panels/producer-emission.json", mod: "../panels/producer-emission", flag: "PRODUCER_EMISSION_TRUSTED" },
  ];
  const specOf = (json: string): string => `../${json}`.replace("../forwarding/", "./");

  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((n) => {
      const p = join(dir, n);
      return statSync(p).isDirectory() ? walk(p) : p.endsWith(".json") ? [p] : [];
    });

  it("the table covers every source-bound sidecar under src/", () => {
    const found = walk(SRC)
      .map((p) => relative(SRC, p).split(sep).join("/"))
      .filter((rel) => rel !== "data/fabric.json")
      .filter((rel) => {
        const doc = JSON.parse(readFileSync(join(SRC, rel), "utf8")) as { meta?: Record<string, unknown> };
        return doc !== null && typeof doc === "object" && typeof doc.meta?.sourceSha256 === "string";
      })
      .sort();
    expect(found).toEqual(CONSUMERS.map((c) => c.json).sort());
  });

  const rewrites: [string, (m: Record<string, unknown>) => Record<string, unknown>][] = [
    ["states a different digest form", (m) => ({ ...m, sourceDigestForm: "raw-working-tree" })],
    ["states no digest form at all", (m) => Object.fromEntries(Object.entries(m).filter(([k]) => k !== "sourceDigestForm"))],
    ["states a different byte length", (m) => ({ ...m, sourceBytes: Number(m.sourceBytes) + 1 })],
    ["names a different source file", (m) => ({ ...m, source: `${String(m.source)}.other` })],
  ];

  for (const c of CONSUMERS) {
    const real = JSON.parse(readFileSync(join(SRC, c.json), "utf8")) as { meta: Record<string, unknown> };
    const load = async (doc: unknown): Promise<Record<string, unknown>> => {
      vi.resetModules();
      vi.doMock(specOf(c.json), () => ({ default: doc }));
      try {
        return (await import(/* @vite-ignore */ c.mod)) as Record<string, unknown>;
      } finally {
        vi.doUnmock(specOf(c.json));
      }
    };

    it(`${c.json}: positive control — the shipped pair is trusted`, async () => {
      expect((await load(real))[c.flag]).toBe(true);
    });

    for (const [why, rewrite] of rewrites)
      it(`${c.json}: the same sourceSha256 that ${why} is refused`, async () => {
        expect(real.meta.sourceSha256).toBe(fabric.meta.sourceSha256);
        expect((await load({ ...real, meta: rewrite(real.meta) }))[c.flag]).toBe(false);
      });
  }
});
