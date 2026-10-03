import { afterEach, describe, expect, it, vi } from "vitest";
import { loadPathProjection, loadProjection, loadProjectionPage, requireProjectionPage, sameIdentity } from "./projection";
import { pathFixture, topologyFixture } from "./test/projectionFixtures";

const identity = { snapshot_id: 4, sha256: `sha256:${"a".repeat(64)}`, bytes: 42, digest_form: "assesshub-store-blob" as const };
const common = { identity, schema: "ui_projection_transport/1", projection_schema: "ui_projection/1", view: "device", engine: {}, limitations: [] };
const source = { pointer: "/findings", source_list: { state: "not_collected", reason: "Partial", subject: null, refs: [], basis: "engine" }, page: { offset: 0, limit: 25, total: 2, returned: 2, has_more: false, items: [{ index: 8, pointer: "/punchlist/8" }, { index: 12, pointer: "/punchlist/12" }] } };
describe("Projection transport custody", () => {
  afterEach(() => vi.restoreAllMocks());
  it("encodes the exact host and only calls the projection API", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...common, payload: { host: " a/b~& " } })));
    await loadProjection(4, "device", " a/b~& ");
    const url = String(fetcher.mock.calls[0][0]);
    expect(new URL(url, "http://localhost").searchParams.get("host")).toBe(" a/b~& ");
    expect(url).toContain("/ui-projection/device?");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("rejects a different snapshot, host or contract", async () => {
    for (const data of [
      { ...common, identity: { ...identity, snapshot_id: 5 }, payload: { host: "a" } },
      { ...common, payload: { host: "b" } },
      { ...common, schema: "future", payload: { host: "a" } },
    ]) {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(data)));
      await expect(loadProjection(4, "device", "a")).rejects.toThrow();
    }
  });
  it("does not join pages from a replaced source", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...common, identity: { ...identity, sha256: `sha256:${"b".repeat(64)}` }, list: source })));
    // Deliberately partial transport doubles: this test attacks identity before reading owner rows.
    await expect(loadProjectionPage({ ...common, payload: { host: "a" } } as never, source as never, 0, "a")).rejects.toThrow(/identity/);
  });
  it("treats byte count and digest form as part of identity", () => {
    expect(sameIdentity(identity, { ...identity, bytes: 43 })).toBe(false);
    expect(sameIdentity(identity, { ...identity })).toBe(true);
  });
  it.each(["\n", "\r", "\u2028", "\u2029"])("rejects a digest with a trailing line terminator %j", async (suffix) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...common,
      identity: { ...identity, sha256: identity.sha256 + suffix }, payload: { host: "a" } })));
    await expect(loadProjection(4, "device", "a")).rejects.toThrow(/identify/);
  });
  it("rejects coercible digest arrays rather than regex-converting them to strings", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...common,
      identity: { ...identity, sha256: [identity.sha256] }, payload: { host: "a" } })));
    await expect(loadProjection(4, "device", "a")).rejects.toThrow(/identify/);
  });
  it("rejects a different exact device context before fetching even when snapshot and list match", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    await expect(loadProjectionPage({ ...common, payload: { host: "access1" } } as never, source as never, 25, "access2"))
      .rejects.toThrow(/device/);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(["engine", "limitations"])("rejects changed %s context before returning rows", async (key) => {
    const data = { ...common, list: source, [key]: { changed: true } };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(data)));
    await expect(loadProjectionPage({ ...common, payload: { host: "a" } } as never, source as never, 0, "a"))
      .rejects.toThrow(/context/);
  });
  it("requests only the path projection and preserves exact accepted address text", async () => {
    const src = " 192.0.2.10 ", dst = "198.51.100.10&x=1";
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(pathFixture(1, src, dst))));
    await loadPathProjection(topologyFixture() as never, src, dst);
    const url = new URL(String(fetcher.mock.calls[0][0]), "http://localhost");
    expect(url.pathname).toBe("/api/snapshots/1/ui-projection/topology/path");
    expect([...url.searchParams]).toEqual([["src_ip", src], ["dst_ip", dst]]);
  });
  it.each(["identity", "engine", "limitations", "query", "view"])("refuses path %s drift", async (change) => {
    const path = pathFixture();
    const changed = change === "identity" ? { ...path, identity: { ...path.identity, bytes: 43 } }
      : change === "engine" ? { ...path, engine: { ...path.engine, code_schema_version: "changed" } }
      : change === "limitations" ? { ...path, limitations: [{ id: "changed" }] }
      : change === "view" ? { ...path, view: "topology" }
      : { ...path, payload: { ...path.payload, query: { ...path.payload.query, disclose: false } } };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(changed)));
    await expect(loadPathProjection(topologyFixture() as never, "192.0.2.10", "198.51.100.10")).rejects.toThrow();
  });
  it.each([
    { offset: -1 }, { returned: 0 }, { has_more: true }, { total: 3 }, { limit: 201 }, { total: Infinity },
  ])("refuses inconsistent paging metadata %j", (change) => {
    expect(() => requireProjectionPage({ ...source.page, ...change } as never)).toThrow(/incomplete|inconsistent/);
  });
});
