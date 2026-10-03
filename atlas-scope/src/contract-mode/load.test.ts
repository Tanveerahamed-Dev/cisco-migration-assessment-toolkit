import { webcrypto } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import { topologyNodeFixture } from "../../../webapp/frontend/src/test/projectionFixtures";
import { loadCompleteTopology, loadContractPath } from "./load";
import { completeFixture, rawPath, rawTopology } from "../test-support/projection-contract-fixtures";

const response = (value: unknown): Response => ({ ok: true, json: async () => value }) as Response;
const deps = (fetcher: typeof fetch, controller = new AbortController()) => ({ fetch: fetcher, signal: controller.signal, subtle: webcrypto.subtle });

describe("guarded engine-only Scope loading", () => {
  it("reads only the topology contract with same-origin credentials and complete page bounds", async () => {
    const expected = await completeFixture();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(rawTopology()));
    const result = await loadCompleteTopology(expected.document.identity, expected.contextDigest, deps(fetcher));
    expect(result.rows.nodes).toHaveLength(2);
    expect(result.contextDigest).toBe(expected.contextDigest);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/snapshots/7/ui-projection/topology?limit=200", expect.objectContaining({ credentials: "same-origin", cache: "no-store" }));
  });

  it("assembles every page without changing source row identities", async () => {
    const expected = await completeFixture(), first = rawTopology();
    const nodes = Array.from({ length: 201 }, (_, index) => topologyNodeFixture(index, `synthetic-node-${index}`));
    first.payload.nodes.page = { offset: 0, limit: 200, returned: 200, total: 201, has_more: true, items: nodes.slice(0, 200) };
    const { payload: _payload, ...common } = first;
    const page = { ...common, list: { ...first.payload.nodes, page: { offset: 200, limit: 200, returned: 1, total: 201, has_more: false, items: nodes.slice(200) } } };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response(first)).mockResolvedValueOnce(response(page));
    const result = await loadCompleteTopology(expected.document.identity, expected.contextDigest, deps(fetcher));
    expect(result.rows.nodes).toHaveLength(201);
    expect(result.rows.nodes[200]?.pointer).toBe("/cable_map/nodes/200");
    expect(fetcher.mock.calls.map(([url]) => String(url))).toEqual([
      "/api/snapshots/7/ui-projection/topology?limit=200",
      "/api/snapshots/7/ui-projection/topology/lists?pointer=%2Fnodes&offset=200&limit=200",
    ]);
  });

  it("refuses identity, version, context, census and duplicate-row changes", async () => {
    const expected = await completeFixture();
    const mutations = [
      (value: ReturnType<typeof rawTopology>) => { value.identity.bytes++; },
      (value: ReturnType<typeof rawTopology>) => { value.projection_schema = "unknown"; },
      (value: ReturnType<typeof rawTopology>) => { value.engine.code_schema_version = "changed"; },
      (value: ReturnType<typeof rawTopology>) => { value.payload.nodes.page.total++; },
      (value: ReturnType<typeof rawTopology>) => { value.payload.nodes.page.has_more = true; },
      (value: ReturnType<typeof rawTopology>) => { value.payload.nodes.page.items[1] = value.payload.nodes.page.items[0]!; },
      (value: ReturnType<typeof rawTopology>) => { value.payload.nodes.page.total = 20_001; value.payload.nodes.page.has_more = true; },
    ];
    for (const mutate of mutations) {
      const input = rawTopology(); mutate(input);
      const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(input));
      await expect(loadCompleteTopology(expected.document.identity, expected.contextDigest, deps(fetcher))).rejects.toThrow();
      expect(fetcher).toHaveBeenCalledTimes(1);
    }
  });

  it("refuses mismatched subsequent page metadata and source qualification", async () => {
    const expected = await completeFixture();
    for (const mode of ["identity", "engine", "limitations", "offset", "source_list", "duplicate"] as const) {
      const first = rawTopology();
      const nodes = Array.from({ length: 201 }, (_, index) => topologyNodeFixture(index));
      first.payload.nodes.page = { offset: 0, limit: 200, returned: 200, total: 201, has_more: true, items: nodes.slice(0, 200) };
      const { payload: _payload, ...common } = structuredClone(first);
      const page = { ...common, list: { ...structuredClone(first.payload.nodes), page: { offset: 200, limit: 200, returned: 1, total: 201, has_more: false, items: nodes.slice(200) } } };
      if (mode === "identity") page.identity.bytes++;
      if (mode === "engine") page.engine.code_schema_version = "changed";
      if (mode === "limitations") Object.assign(page, { limitations: [{ different: true }] });
      if (mode === "offset") page.list.page.offset = 0;
      if (mode === "source_list") page.list.source_list.basis = "changed";
      if (mode === "duplicate") page.list.page.items = [nodes[0]!];
      const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response(first)).mockResolvedValueOnce(response(page));
      await expect(loadCompleteTopology(expected.document.identity, expected.contextDigest, deps(fetcher))).rejects.toThrow();
    }
  });

  it("honours cancellation even when a fetch mock ignores the signal", async () => {
    const expected = await completeFixture(), controller = new AbortController();
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => { controller.abort(); return response(rawTopology()); });
    await expect(loadCompleteTopology(expected.document.identity, expected.contextDigest, deps(fetcher, controller))).rejects.toMatchObject({ name: "AbortError" });
  });

  it("binds a complete path to query, identity, engine, limitations and legend without raw reads", async () => {
    const model = await completeFixture(), query = { src_ip: "192.0.2.10", dst_ip: "198.51.100.10" };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(rawPath()));
    const result = await loadContractPath(model, query, deps(fetcher));
    expect(result.payload.result.state).toBe("published");
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/snapshots/7/ui-projection/topology/path?src_ip=192.0.2.10&dst_ip=198.51.100.10");
    for (const mode of ["identity", "query", "hops", "mtu", "disclose", "engine", "legend"] as const) {
      const bad = rawPath();
      if (mode === "identity") bad.identity.bytes++;
      if (mode === "query") bad.payload.query.dst_ip = "192.0.2.99";
      if (mode === "hops") bad.payload.query.max_hops = 2;
      if (mode === "mtu") Object.assign(bad.payload.query, { required_mtu: 1500 });
      if (mode === "disclose") bad.payload.query.disclose = false;
      if (mode === "engine") bad.engine.code_schema_version = "changed";
      if (mode === "legend") bad.payload.legend.entries[0]!.meaning = "changed";
      await expect(loadContractPath(model, query, deps(vi.fn<typeof fetch>().mockResolvedValue(response(bad))))).rejects.toThrow();
    }
  });
});
