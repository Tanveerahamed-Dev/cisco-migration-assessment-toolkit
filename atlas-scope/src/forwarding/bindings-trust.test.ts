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
import { fabric, resolveCite } from "../core/data";
import { need } from "./test-subjects";

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

  it("the refusal sentence cites what the mismatch was read from, not the ACL table (2026-09-28 verifier, D7)", async () => {
    const sha = REAL.meta.sourceSha256;
    const other = `${sha[0] === "0" ? "1" : "0"}${sha.slice(1)}`;
    const b = await loadWith({ ...REAL, meta: { ...REAL.meta, sourceSha256: other } });
    const sentences = b.bindingCoverageSentences();
    expect(sentences.length).toBeGreaterThan(0);
    for (const line of sentences) {
      // The two digests that disagree, each named, and the record of this build's own binding.
      expect(line).toContain(other.slice(0, 8));
      expect(line).toContain(fabric.meta.sourceSha256.slice(0, 8));
      expect(line).toContain("(meta.sourceSha256)");
      expect(resolveCite("meta.sourceSha256")).toBe(fabric.meta.sourceSha256);
    }
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

/* D7 (2026-09-28 verifier). A host that holds collected ACLs but for which the binding projection carries no
   interface record: the sentence says "no interface record was collected for it", and that absence must cite
   what it was read from — the snapshot's collection-coverage record, which counts the hosts with interface
   records — not the ACL table (which proves nothing about interfaces). No ACL host on the reference sample
   lacks interface records, so the branch runs here, on the real sidecar with ONE host's records removed. */
describe("an ACL host with no interface record: the absence cites the coverage record it was read from", () => {
  const aclHost = (): string | undefined =>
    Object.keys(fabric.acls)
      .sort()
      .find((h) => Object.keys(fabric.acls[h] ?? {}).length > 0 && (REAL.hosts[h]?.length ?? 0) > 0);

  it("the sentence for that host cites the coverage record and names the host's own ACL table separately", async (ctx) => {
    const h = need(ctx, aclHost(), "host holding collected ACLs and interface records");
    const hosts = Object.fromEntries(Object.entries(REAL.hosts).filter(([k]) => k !== h));
    const b = await loadWith({ ...REAL, hosts });
    expect(b.BINDINGS_TRUSTED).toBe(true);
    const line = b.bindingCoverageSentences().find((s) => s.startsWith(`${h}:`));
    expect(line, `a sentence for ${h}`).toBeDefined();
    expect(line).toMatch(/no interface record was collected for it/);
    const absence = line!.slice(0, line!.indexOf(", so"));
    // The absence clause cites the coverage record (a real record's cite), not acls.<host>.
    expect(absence).toContain(`(${fabric.coverage.cite}`);
    expect(absence).not.toContain(`acls.${h}`);
    expect(absence).toContain(`${fabric.coverage.hostsWithInterfaces} hosts`);
    // The ACLs the fallback applies to are still cited by their own table.
    expect(line).toContain(`(acls.${h})`);
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
    /* The LOADED sidecar, unmocked. `vi.importActual` resolves through the runner's dataset override, so on the
       rename or golden-snapshot leg this is that dataset's document, paired with that dataset's fabric. Reading
       the tracked file from disk paired the sample's sidecar with another fleet's fabric, and the positive
       control then failed on every other dataset (2026-09-28 verifier legs). The partition check above stays a
       walk of the SOURCE TREE: which sidecars exist is a property of the code, not of the data. */
    const loaded = async (): Promise<{ meta: Record<string, unknown> }> =>
      structuredClone(((await vi.importActual(specOf(c.json))) as { default: { meta: Record<string, unknown> } }).default);
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
      const real = await loaded();
      expect(real.meta.sourceSha256).toBe(fabric.meta.sourceSha256);
      expect((await load(real))[c.flag]).toBe(true);
    });

    for (const [why, rewrite] of rewrites)
      it(`${c.json}: the same sourceSha256 that ${why} is refused`, async () => {
        const real = await loaded();
        expect(real.meta.sourceSha256).toBe(fabric.meta.sourceSha256);
        expect((await load({ ...real, meta: rewrite(real.meta) }))[c.flag]).toBe(false);
      });
  }
});
