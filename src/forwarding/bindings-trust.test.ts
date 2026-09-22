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
});
