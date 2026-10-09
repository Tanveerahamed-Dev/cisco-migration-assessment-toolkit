import { webcrypto } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EMBED_PROTOCOL, PROJECTION_SCHEMA, TOPOLOGY_STYLE_SCHEMA, canonicalProjectionJson,
  parseEmbedMessage, projectionContextDigest, projectionEmbedUrl, sameProjectionIdentity, sameSelection,
  type EmbedMessage, type ProjectionEngine, type ProjectionIdentity,
} from "./projectionEmbed";

// Synthetic protocol fixtures; no snapshot or assessment facts are claimed by these messages.
const nonce = "1".repeat(32);
const digest = `sha256:${"2".repeat(64)}`;
const identity: ProjectionIdentity = { snapshot_id: 7, sha256: `sha256:${"3".repeat(64)}`, bytes: 123, digest_form: "assesshub-store-blob" };
const base = { protocol: EMBED_PROTOCOL, nonce };
const bound = { ...base, identity, context_digest: digest };
const versions = { projection_schema: PROJECTION_SCHEMA, style_schema: TOPOLOGY_STYLE_SCHEMA };
const target = { list: "nodes", row: { index: 0, pointer: "/cable_map/nodes/0" } } as const;
const text = { state: "published", value: "synthetic", subject: null, basis: "synthetic", refs: [] } as const;
const engine: ProjectionEngine = { code_schema_version: "synthetic", collected_at: text, generated_at: text,
  script_version: text, snapshot_schema: text, snapshot_schema_supported: true,
  snapshot_sha256: { ...text, value: `sha256:${"3".repeat(64)}` }, snapshot_bytes: { ...text, value: 123 },
  snapshot_digest_form: "exact-parsed-bytes" };

afterEach(() => vi.unstubAllGlobals());

describe("closed Scope coordination", () => {
  const messages: EmbedMessage[] = [
    { ...base, ...versions, type: "ready", snapshot_id: 7 },
    { ...bound, ...versions, type: "init" }, { ...bound, type: "bound" },
    { ...bound, type: "select", target }, { ...bound, type: "select", target: null },
    { ...bound, type: "query", request_id: "request-1", query: { src_ip: "not an IP", dst_ip: "2001:db8::1" } },
    { ...bound, type: "query", request_id: "request-2", query: null },
    { ...bound, type: "query_applied", request_id: "request-2" },
    { ...bound, type: "refused", code: "WEBGL_UNAVAILABLE", request_id: null },
    { ...base, identity: null, context_digest: null, type: "refused", code: "UNSUPPORTED_CONTRACT", request_id: null },
  ];
  for (const message of messages) {
    it(`accepts the complete ${message.type} envelope ${"request_id" in message ? message.request_id : ""}`, () => {
      expect(parseEmbedMessage(message)).toEqual(message);
      expect(parseEmbedMessage({ ...message, extra: true })).toBeNull();
    });
  }

  it("rejects every omitted field and unknown version, nonce or identity", () => {
    for (const message of messages) {
      for (const key of Object.keys(message)) {
        const omitted = { ...message } as Record<string, unknown>;
        delete omitted[key];
        expect(parseEmbedMessage(omitted)).toBeNull();
      }
      expect(parseEmbedMessage({ ...message, protocol: "atlas.ui_projection_embed/2" })).toBeNull();
      expect(parseEmbedMessage({ ...message, nonce: nonce + "\n" })).toBeNull();
    }
    for (const altered of [{ ...identity, bytes: -1 }, { ...identity, bytes: 2 ** 53 }, { ...identity, sha256: identity.sha256 + "\n" },
      { ...identity, snapshot_id: 1.1 }, { ...identity, digest_form: "raw-file" }, { ...identity, extra: true }]) {
      expect(parseEmbedMessage({ ...bound, identity: altered, type: "bound" })).toBeNull();
    }
    expect(parseEmbedMessage({ ...bound, type: "bound", context_digest: digest + "\n" })).toBeNull();
    expect(parseEmbedMessage({ ...bound, ...versions, type: "init", style_schema: "unknown" })).toBeNull();
  });

  it("owns accepted nested values and never evaluates accessors", () => {
    const input = { ...bound, identity: { ...identity }, type: "select", target: { ...target, row: { ...target.row } } };
    const accepted = parseEmbedMessage(input);
    input.identity.bytes = 999;
    input.target.row.pointer = "/replacement";
    expect(accepted).toEqual({ ...bound, type: "select", target });
    const getter = vi.fn(() => EMBED_PROTOCOL);
    expect(parseEmbedMessage({ ...bound, type: "bound", get protocol() { return getter(); } })).toBeNull();
    expect(getter).not.toHaveBeenCalled();
    expect(parseEmbedMessage(new Date())).toBeNull();
  });

  it("refuses mixed unbound contexts, invented selectors, row keys, and command fields", () => {
    expect(parseEmbedMessage({ ...bound, identity: null, type: "refused", code: "HTTP_REFUSED", request_id: null })).toBeNull();
    expect(parseEmbedMessage({ ...bound, type: "select", target: { ...target, list: "devices" } })).toBeNull();
    expect(parseEmbedMessage({ ...bound, type: "select", target: { ...target, row: { ...target.row, extra: 1 } } })).toBeNull();
    expect(parseEmbedMessage({ ...bound, type: "select", target: { ...target, row: { index: -1, pointer: "bad" } } })).toBeNull();
    expect(parseEmbedMessage({ ...bound, type: "query", request_id: "request-1", query: { src_ip: "a", dst_ip: "b", max_hops: 2 } })).toBeNull();
    expect(parseEmbedMessage({ ...bound, type: "query", request_id: "x".repeat(65), query: null })).toBeNull();
    expect(parseEmbedMessage({ ...bound, type: "query", request_id: "q1", query: { src_ip: "a".repeat(129), dst_ip: "b" } })).toBeNull();
  });

  it("rejects every JavaScript line terminator even at the exact nonce length", () => {
    for (const terminator of ["\n", "\r", "\u2028", "\u2029"]) {
      expect(parseEmbedMessage({ ...bound, type: "bound", nonce: nonce.slice(0, -1) + terminator })).toBeNull();
      expect(parseEmbedMessage({ ...bound, type: "query", request_id: `q1${terminator}`, query: null })).toBeNull();
      expect(projectionEmbedUrl("/scope/snapshots/7/?engine_projection=1", 7, nonce.slice(0, -1) + terminator, "http://localhost:8000")).toBeNull();
    }
  });

  it("compares all identity fields and full row identities", () => {
    expect(sameProjectionIdentity(identity, { ...identity })).toBe(true);
    for (const change of [{ snapshot_id: 8 }, { sha256: digest }, { bytes: 124 }]) {
      expect(sameProjectionIdentity(identity, { ...identity, ...change })).toBe(false);
    }
    expect(sameSelection(target, { ...target, row: { ...target.row } })).toBe(true);
    expect(sameSelection(target, { ...target, row: { ...target.row, index: 1 } })).toBe(false);
    expect(sameSelection(target, { ...target, list: "cables" })).toBe(false);
    expect(sameSelection(target, null)).toBe(false);
    expect(sameSelection(null, null)).toBe(true);
  });
});

describe("same-hub capability URL", () => {
  const origin = "http://localhost:8000";
  const href = "/scope/snapshots/7/?engine_projection=1";
  it("normalizes the current same-origin capability and adds only the mount nonce", () => {
    expect(projectionEmbedUrl(href, 7, nonce, origin)).toBe(`${origin}${href}&projection_nonce=${nonce}`);
    expect(projectionEmbedUrl(origin + href, 7, nonce, origin)).toBe(`${origin}${href}&projection_nonce=${nonce}`);
  });
  it("refuses origin, credentials, path, fragment, duplicate, stale and extra-param escapes", () => {
    for (const altered of ["https://elsewhere.invalid" + href, "http://localhost:8001" + href,
      "http://user@localhost:8000" + href, href.replace("/7/", "/8/"), href + "#fragment", href + "&extra=1",
      href + "&engine_projection=1", href + `&projection_nonce=${nonce}`, href.replace("=1", "=2"), "javascript:void(0)",
      href.replace("/7/", "/%37/"), href.replace("engine_projection", "wrong")]) {
      expect(projectionEmbedUrl(altered, 7, nonce, origin)).toBeNull();
    }
    expect(projectionEmbedUrl(href, 7, "bad", origin)).toBeNull();
    expect(projectionEmbedUrl(href, 7, nonce, "null")).toBeNull();
  });
});

describe("independently fetched context comparison", () => {
  it("sorts object keys but retains arrays, JSON types and shared values", () => {
    expect(canonicalProjectionJson({ b: [2, 1], a: true })).toBe('{"a":true,"b":[2,1]}');
    expect(canonicalProjectionJson({ a: true, b: [1, 2] })).not.toBe(canonicalProjectionJson({ b: [2, 1], a: true }));
    const shared = { value: "\u{1f600}" };
    expect(canonicalProjectionJson([shared, shared])).toBe('[{"value":"😀"},{"value":"😀"}]');
  });
  it("refuses non-JSON, cycles, holes, array extras and hidden object fields", () => {
    const cycle: unknown[] = []; cycle.push(cycle);
    const extra = Object.assign([1], { extra: 2 });
    const hidden = Object.defineProperty({}, "hidden", { value: 1, enumerable: false });
    for (const value of [NaN, Infinity, undefined, new Date(), new Set(), cycle, Array(1), extra, hidden, { x: undefined }]) {
      expect(() => canonicalProjectionJson(value)).toThrow();
    }
  });
  it("produces the same SHA256 only for the same canonical context", async () => {
    const original = await projectionContextDigest(engine, [], webcrypto.subtle);
    const reordered = Object.fromEntries(Object.entries(engine).reverse()) as ProjectionEngine;
    expect(await projectionContextDigest(reordered, [], webcrypto.subtle)).toBe(original);
    expect(await projectionContextDigest({ ...engine, code_schema_version: "different" }, [], webcrypto.subtle)).not.toBe(original);
    // G41: the engine block names its source bytes, so a context from other bytes never shares this digest.
    expect(await projectionContextDigest({ ...engine, snapshot_sha256: { ...text, value: `sha256:${"4".repeat(64)}` } },
      [], webcrypto.subtle)).not.toBe(original);
    expect(await projectionContextDigest({ ...engine, snapshot_bytes: { ...text, value: 124 } }, [], webcrypto.subtle)).not.toBe(original);
    expect(original).toMatch(/^sha256:[0-9a-f]{64}$/);
  });
  it("refuses missing browser crypto rather than inventing a comparison digest", async () => {
    vi.stubGlobal("crypto", undefined);
    await expect(projectionContextDigest(engine, [])).rejects.toThrow("verification is unavailable");
  });
});
