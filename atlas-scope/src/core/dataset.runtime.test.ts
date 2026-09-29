// @vitest-environment node
/**
 * dataset.runtime.test.ts — the runtime paths into the one door: an AssessHub snapshot fetched from the
 * guarded /api, and a snapshot file the reader opens. Each is exercised with the SAME code the worker
 * runs (dataset/compile-request.ts) and with WebCrypto where a secure context has it — Node's
 * `crypto.subtle` here — so what is proved is the browser path, not a Node stand-in.
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { compileAll, serialiseCompiled } from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import { bindSource } from "../../tools/source-binding.mjs";
import type { CompileFn } from "./dataset/compile-client";
import { runCompileRequest } from "./dataset/compile-request";
import { sha1Hex } from "./dataset/hashes";
import { HUB_DIGEST_FORM, loadFromAssessHub, snapshotIdFromPath } from "./dataset/hub";
import { openSnapshotFile, restoreOpenedDataset, returnToSample } from "./dataset/opened";
import { memoryStore, STORED_RECORD_VERSION } from "./dataset/store";
import { GOLDEN_SNAPSHOT, SAMPLE_SNAPSHOT } from "./dataset/testing";

const subtle = globalThis.crypto.subtle;
const inProcess: CompileFn = (req) => runCompileRequest(req, subtle);
const noWebCrypto: CompileFn = (req) => runCompileRequest(req, null);
const buf = (b: Uint8Array): ArrayBuffer => b.slice().buffer;
const sha256 = (b: Uint8Array): string => createHash("sha256").update(b).digest("hex");

/** The golden snapshot in AssessHub's STORE form: compact JSON, exactly what /raw returns. */
const goldenStore = new TextEncoder().encode(JSON.stringify(JSON.parse(readFileSync(GOLDEN_SNAPSHOT, "utf8"))));
const sampleFile = new Uint8Array(readFileSync(SAMPLE_SNAPSHOT));

function hubResponse(body: Uint8Array, headers: Record<string, string>, status = 200): Response {
  return new Response(body.slice(), { status, headers: { "content-type": "application/json", ...headers } });
}
const goodHeaders = (body: Uint8Array): Record<string, string> => ({
  "x-snapshot-sha256": sha256(body),
  "x-snapshot-bytes": String(body.length),
  "x-snapshot-digest-form": HUB_DIGEST_FORM,
});

describe("the compile the worker runs is the one compiler, byte for byte", () => {
  it("an opened file compiles to exactly what the Node CLI path writes for the same bytes and label", async () => {
    const out = await inProcess({ bytes: buf(sampleFile), label: { source: "sample_fleet.snapshot.json", sourceOrigin: "external-file" }, expect: null });
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const { snap, schemaAssumed } = assertValidSnapshot(sampleFile);
    const node = compileAll(snap, bindSource(sampleFile, { source: "sample_fleet.snapshot.json", sourceOrigin: "external-file" }), { schemaAssumed });
    expect(serialiseCompiled(out.set)).toEqual(serialiseCompiled(node));
    expect(out.verification).toBe("computed");
  });

  it("the SHA-1 used where WebCrypto is absent is SHA-1 (every padding boundary)", () => {
    for (const n of [0, 1, 55, 56, 63, 64, 65, 119, 120, 1000, 4097]) {
      const b = new Uint8Array(n).map((_, i) => (i * 131 + 7) & 0xff);
      expect(sha1Hex(b), `length ${n}`).toBe(createHash("sha1").update(b).digest("hex"));
    }
  });

  it("an opened file outside a secure context is refused, never bound without a computed digest", async () => {
    const out = await noWebCrypto({ bytes: buf(sampleFile), label: { source: "x.json", sourceOrigin: "external-file" }, expect: null });
    expect(out.ok ? "ok" : out.errors.map((e) => e.code)).toEqual(["E_NO_WEBCRYPTO"]);
  });
});

describe("AssessHub mode: /scope/snapshots/{id}/ -> /api/snapshots/{id}/raw -> verified compile", () => {
  it("reads the snapshot id from the path under the build's base, and nothing else", () => {
    expect(snapshotIdFromPath("/scope/snapshots/12/", "/scope/")).toBe("12");
    expect(snapshotIdFromPath("/scope/snapshots/12", "/scope/")).toBe("12");
    expect(snapshotIdFromPath("/scope/snapshots/-3/", "/scope/")).toBe("-3");
    for (const bad of ["/scope/", "/scope/snapshots/", "/scope/snapshots/1/2/", "/scope/snapshots/..%2f1/", "/scope/snapshots/a%2Fb/", "/other/snapshots/1/", "/scope/snapshots/%E0%A4%A/"]) {
      expect(snapshotIdFromPath(bad, "/scope/"), bad).toBeNull();
    }
  });

  it("fetches same-origin with no cache, verifies the digest in a secure context, and binds in the store form", async () => {
    const calls: { url: string; init: RequestInit | undefined }[] = [];
    const r = await loadFromAssessHub({
      pathname: "/scope/snapshots/7/",
      base: "/scope/",
      secure: true,
      compile: inProcess,
      fetch: (async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        return hubResponse(goldenStore, goodHeaders(goldenStore));
      }) as typeof fetch,
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe("/api/snapshots/7/raw");
    expect(calls[0]!.init).toMatchObject({ credentials: "same-origin", cache: "no-store" });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const meta = r.dataset.set.fabric.meta;
    expect(meta.source).toBe("assesshub:snapshot/7");
    expect(meta.sourceOrigin).toBe("assesshub-store");
    expect(meta.sourceDigestForm).toBe("assesshub-store-blob");
    /* The displayed binding IS the store's binding (the server's X-Snapshot-Sha256). */
    expect(meta.sourceSha256).toBe(sha256(goldenStore));
    expect(meta.sourceBytes).toBe(goldenStore.length);
    expect(r.dataset.origin).toMatchObject({ kind: "assesshub", snapshotId: "7", verification: "verified-in-browser", attestedSha256: sha256(goldenStore) });
    expect(r.dataset.set.fabric.devices.length).toBe(7);
  });

  it("outside a secure context it says server-attested, never verified, and still checks the length", async () => {
    const r = await loadFromAssessHub({
      pathname: "/scope/snapshots/7/",
      base: "/scope/",
      secure: false,
      compile: noWebCrypto,
      fetch: (async () => hubResponse(goldenStore, goodHeaders(goldenStore))) as unknown as typeof fetch,
    });
    expect(r.ok && r.dataset.origin).toMatchObject({ verification: "server-attested" });
    if (!r.ok) return;
    /* The binding's sha256 is the server's statement; the Git blob id is computed (it has no header). */
    expect(r.dataset.set.fabric.meta.sourceSha256).toBe(sha256(goldenStore));
    const blob = new Uint8Array([...new TextEncoder().encode(`blob ${goldenStore.length}\0`), ...goldenStore]);
    expect(r.dataset.set.fabric.meta.sourceGitBlob).toBe(createHash("sha1").update(blob).digest("hex"));
  });

  const refusals: [string, string, () => Response | Promise<Response>, boolean?][] = [
    ["a digest that is not the bytes'", "E_HUB_DIGEST_MISMATCH", () => hubResponse(goldenStore, { ...goodHeaders(goldenStore), "x-snapshot-sha256": "0".repeat(64) })],
    ["a byte count that is not the body's", "E_HUB_BYTES_MISMATCH", () => hubResponse(goldenStore, { ...goodHeaders(goldenStore), "x-snapshot-bytes": String(goldenStore.length + 1) })],
    ["a byte count that is not the body's, outside a secure context", "E_HUB_BYTES_MISMATCH", () => hubResponse(goldenStore, { ...goodHeaders(goldenStore), "x-snapshot-bytes": "5" }), false],
    ["no binding headers", "E_HUB_HEADERS", () => hubResponse(goldenStore, {})],
    ["an upper-case digest header", "E_HUB_HEADERS", () => hubResponse(goldenStore, { ...goodHeaders(goldenStore), "x-snapshot-sha256": sha256(goldenStore).toUpperCase() })],
    ["another digest form", "E_HUB_DIGEST_FORM", () => hubResponse(goldenStore, { ...goodHeaders(goldenStore), "x-snapshot-digest-form": "lf-normalised" })],
    ["a 404", "E_HUB_HTTP", () => hubResponse(new Uint8Array(), {}, 404)],
    ["a 403 (cross-site or foreign host)", "E_HUB_HTTP", () => hubResponse(new Uint8Array(), {}, 403)],
    ["a network failure", "E_HUB_FETCH", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a body with a byte-order mark", "E_BOM", () => {
      const b = new Uint8Array([0xef, 0xbb, 0xbf, ...goldenStore]);
      return hubResponse(b, goodHeaders(b));
    }],
    ["a JSON body that is not a snapshot", "E_NOT_A_SNAPSHOT", () => {
      const b = new TextEncoder().encode('{"hello":"world"}');
      return hubResponse(b, goodHeaders(b));
    }],
  ];
  for (const [what, code, respond, secure = true] of refusals) {
    it(`refuses ${what} with ${code} and a plain-language message`, async () => {
      const r = await loadFromAssessHub({
        pathname: "/scope/snapshots/7/",
        base: "/scope/",
        secure,
        compile: secure ? inProcess : noWebCrypto,
        fetch: (async () => respond()) as unknown as typeof fetch,
      });
      expect(r.ok).toBe(false);
      if (r.ok) return;
      expect(r.errors[0]!.code).toBe(code);
      expect(r.errors[0]!.message.length).toBeGreaterThan(30);
      expect(r.snapshotId).toBe("7");
    });
  }

  it("a page not opened at /scope/snapshots/{id}/ fetches nothing", async () => {
    let fetched = false;
    const r = await loadFromAssessHub({
      pathname: "/scope/",
      base: "/scope/",
      secure: true,
      compile: inProcess,
      fetch: (async () => {
        fetched = true;
        return hubResponse(goldenStore, goodHeaders(goldenStore));
      }) as unknown as typeof fetch,
    });
    expect(r.ok ? "ok" : r.errors[0]!.code).toBe("E_HUB_NO_SNAPSHOT_ID");
    expect(fetched).toBe(false);
  });
});

describe("standalone: open a snapshot file -> IndexedDB -> reload -> restore; and back to the sample", () => {
  const golden = new Uint8Array(readFileSync(GOLDEN_SNAPSHOT));
  const file = (bytes: Uint8Array, name = "snapshot.json") => ({ name, size: bytes.length, arrayBuffer: async () => buf(bytes) });

  it("compiles, keeps the set with its bytes, sets the marker, reloads — and the reload restores it", async () => {
    const store = memoryStore();
    let reloads = 0;
    let marker = false;
    const r = await openSnapshotFile(file(golden), { compile: inProcess, store, compilerId: "c1", reload: () => (reloads += 1), setMarker: () => (marker = true) });
    expect(r).toEqual({ ok: true });
    expect(reloads).toBe(1);
    expect(marker).toBe(true);
    const back = await restoreOpenedDataset({ compile: inProcess, store, compilerId: "c1", clearMarker: () => (marker = false) });
    expect(back.ok).toBe(true);
    if (!back.ok) return;
    expect(back.recompiled).toBe(false);
    expect(back.dataset.origin).toMatchObject({ kind: "opened-file", fileName: "snapshot.json", fileBytes: golden.length });
    expect(back.dataset.set.fabric.meta).toMatchObject({ source: "snapshot.json", sourceOrigin: "external-file", sourceDigestForm: "lf-normalised" });
    expect(marker).toBe(true);
  });

  it("a set compiled by another compiler build is recompiled from the kept bytes, never shown as this build's", async () => {
    const store = memoryStore();
    await openSnapshotFile(file(golden), { compile: inProcess, store, compilerId: "old", reload: () => undefined, setMarker: () => true });
    const stale = store.record as { set: { fabric: { devices: unknown[] } } };
    stale.set.fabric.devices = [];
    const back = await restoreOpenedDataset({ compile: inProcess, store, compilerId: "new", clearMarker: () => undefined });
    expect(back.ok && back.recompiled).toBe(true);
    if (!back.ok) return;
    expect(back.dataset.set.fabric.devices.length).toBe(7);
    expect((store.record as { compilerId: string }).compilerId).toBe("new");
  });

  const broken: [string, (r: Record<string, unknown>) => unknown, string][] = [
    ["nothing kept", () => undefined, "E_STORE_EMPTY"],
    ["another record format", (r) => ({ ...r, version: STORED_RECORD_VERSION + 1 }), "E_STORE_VERSION"],
    ["no kept bytes", (r) => ({ ...r, bytes: null }), "E_STORE_CORRUPT"],
    ["an incoherent set whose bytes no longer compile", (r) => {
      const set = structuredClone(r.set) as { aclBindings: { meta: { sourceSha256: string } } };
      set.aclBindings.meta.sourceSha256 = "x";
      return { ...r, set, bytes: buf(new TextEncoder().encode("{}")) };
    }, "E_NOT_A_SNAPSHOT"],
  ];
  for (const [what, corrupt, code] of broken) {
    it(`${what}: the record and marker are removed, and the reader is TOLD the sample is not their file (${code})`, async () => {
      const store = memoryStore();
      await openSnapshotFile(file(golden), { compile: inProcess, store, compilerId: "c1", reload: () => undefined, setMarker: () => true });
      store.record = corrupt(store.record as Record<string, unknown>);
      let cleared = false;
      const back = await restoreOpenedDataset({ compile: inProcess, store, compilerId: "c1", clearMarker: () => (cleared = true) });
      expect(back.ok).toBe(false);
      if (back.ok) return;
      expect(back.notice.code).toBe(code);
      expect(back.notice.message).toMatch(/bundled sample fleet, not your file/);
      expect(cleared).toBe(true);
      expect(store.record).toBeUndefined();
    });
  }

  it("an invalid file is refused with its validator code; nothing is kept and nothing reloads", async () => {
    const store = memoryStore();
    let reloads = 0;
    const bom = new Uint8Array([0xef, 0xbb, 0xbf, ...golden]);
    const r = await openSnapshotFile(file(bom), { compile: inProcess, store, compilerId: "c1", reload: () => (reloads += 1), setMarker: () => true });
    expect(r.ok ? "ok" : r.errors[0]!.code).toBe("E_BOM");
    expect(store.record).toBeUndefined();
    expect(reloads).toBe(0);
  });

  it("storage that cannot keep the set is a refusal before any reload", async () => {
    const store = { ...memoryStore(), put: async () => Promise.reject(new Error("QuotaExceededError")) };
    let reloads = 0;
    const r = await openSnapshotFile(file(golden), { compile: inProcess, store, compilerId: "c1", reload: () => (reloads += 1), setMarker: () => true });
    expect(r.ok ? "ok" : r.errors[0]!.code).toBe("E_STORE_UNAVAILABLE");
    expect(reloads).toBe(0);
  });

  it("a blocked marker is a refusal too, and the kept set is dropped", async () => {
    const store = memoryStore();
    const r = await openSnapshotFile(file(golden), { compile: inProcess, store, compilerId: "c1", reload: () => undefined, setMarker: () => false });
    expect(r.ok ? "ok" : r.errors[0]!.code).toBe("E_STORE_UNAVAILABLE");
    expect(store.record).toBeUndefined();
  });

  it("return to sample clears the marker and the kept set, then reloads", async () => {
    const store = memoryStore();
    await openSnapshotFile(file(golden), { compile: inProcess, store, compilerId: "c1", reload: () => undefined, setMarker: () => true });
    let cleared = false;
    let reloads = 0;
    await returnToSample({ store, reload: () => (reloads += 1), clearMarker: () => (cleared = true) });
    expect([cleared, reloads, store.record]).toEqual([true, 1, undefined]);
  });
});
