import { afterEach, describe, expect, it, vi } from "vitest";
import { common, topologyFixture, topologyNodeFixture } from "../../test/projectionFixtures";
import { assembleTopology, exactEndpoint, initialTopologyRows, rowKey, topologyStyle, TopologyCapacityError } from "./topologyData";

describe("Topology custody and geometry", () => {
  afterEach(() => vi.restoreAllMocks());
  it("assembles only same-source pages, preserving the original row references", async () => {
    const document = topologyFixture();
    document.payload.nodes.page = { ...document.payload.nodes.page, limit: 2, total: 3, has_more: true };
    const last = topologyNodeFixture(11, "synthetic-last");
    const list = { ...document.payload.nodes, page: { offset: 2, limit: 2, returned: 1, total: 3, has_more: false, items: [last] } };
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...common(1, "topology"), list })));
    const progress = vi.fn();
    const rows = await assembleTopology(document as never, new AbortController().signal, progress);
    expect(rows.nodes.map((row) => row.index)).toEqual([0, 1, 11]);
    expect(rows.nodes[2].pointer).toBe("/cable_map/nodes/11");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(String(fetcher.mock.calls[0][0])).toContain("/ui-projection/topology/lists?pointer=%2Fnodes&offset=2&limit=2");
    expect(progress).toHaveBeenCalledTimes(1);
  });
  it("rejects authority/context drift without publishing the mismatched rows", async () => {
    const document = topologyFixture();
    document.payload.nodes.page = { ...document.payload.nodes.page, limit: 2, total: 3, has_more: true };
    const last = topologyNodeFixture(2, "must-not-publish");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...common(1, "topology"), identity: { ...document.identity, bytes: 999 },
      list: { ...document.payload.nodes, page: { offset: 2, limit: 2, total: 3, returned: 1, has_more: false, items: [last] } } })));
    const progress = vi.fn();
    await expect(assembleTopology(document as never, new AbortController().signal, progress)).rejects.toThrow(/identity/);
    expect(progress).not.toHaveBeenCalled();
  });
  it("refuses over-budget complete assembly while retaining a clearly separate initial page", async () => {
    const document = topologyFixture();
    document.payload.nodes.page = { ...document.payload.nodes.page, limit: 2, total: 20_001, has_more: true };
    expect(initialTopologyRows(document as never).nodes).toHaveLength(2);
    const fetcher = vi.spyOn(globalThis, "fetch");
    await expect(assembleTopology(document as never, new AbortController().signal, vi.fn())).rejects.toBeInstanceOf(TopologyCapacityError);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("joins only one published exact pointer/index, never a hostname or ambiguous candidate", () => {
    const nodes = initialTopologyRows(topologyFixture() as never).nodes;
    const ref = { index: nodes[0].index, pointer: nodes[0].pointer };
    expect(exactEndpoint({ state: "published", items: [ref] }, nodes)).toBe(nodes[0]);
    for (const refs of [{ state: "unverified", items: [ref] }, { state: "published", items: [ref, ref] },
      { state: "published", items: [{ ...ref, index: 9 }] }]) expect(exactEndpoint(refs, nodes)).toBeUndefined();
    expect(exactEndpoint({ state: "published", items: [ref] }, [nodes[0], nodes[0]])).toBeUndefined();
    expect(rowKey({ index: 1, pointer: "/same" })).not.toBe(rowKey({ index: 2, pointer: "/same" }));
  });
  it("renders the supplied style and legend, without deriving them from kind/role/status", () => {
    const document = topologyFixture();
    const rows = initialTopologyRows(document as never);
    const style = topologyStyle(rows.nodes[0].style, document.payload.legend as never);
    expect(rows.nodes[0].kind.value).toBe("router");
    expect(style.value.glyph).toBe("device");
    expect(style.entry.tone).toBe("info");
    expect(topologyStyle(rows.nodes[1].style, document.payload.legend as never).entry.stroke).toBe("dotted");
  });
  it("refuses an ambiguous legend rather than selecting one repeated token", () => {
    const document = topologyFixture();
    document.payload.legend.entries.push(document.payload.legend.entries[0]);
    expect(() => initialTopologyRows(document as never)).toThrow(/legend/);
  });
  it("owns immutable row graphs independently of the original response", () => {
    const document = topologyFixture();
    const rows = initialTopologyRows(document as never);
    expect(rows.nodes[0]).not.toBe(document.payload.nodes.page.items[0]);
    expect(Object.isFrozen(rows.nodes)).toBe(true);
    expect(Object.isFrozen(rows.nodes[0].host)).toBe(true);
    document.payload.nodes.page.items[0].host.value = "mutated original";
    expect(rows.nodes[0].host.value).toBe("synthetic-edge-a");
  });
  it("isolates progress containers and refuses mutation of shared immutable row arrays", async () => {
    const document = topologyFixture();
    document.payload.nodes.page = { ...document.payload.nodes.page, limit: 2, total: 3, has_more: true };
    const last = topologyNodeFixture(11, "synthetic-last");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...common(1, "topology"),
      list: { ...document.payload.nodes, page: { offset: 2, limit: 2, returned: 1, total: 3, has_more: false, items: [last] } } })));
    const rows = await assembleTopology(document as never, new AbortController().signal, (progress) => {
      expect(() => { (progress.nodes as unknown as unknown[]).length = 0; }).toThrow();
      progress.nodes = [];
      document.payload.nodes.page.items[0].host.value = "mutated during progress";
    });
    expect(rows.nodes.map((row) => row.index)).toEqual([0, 1, 11]);
    expect(rows.nodes[0].host.value).toBe("synthetic-edge-a");
    expect(Object.isFrozen(rows.nodes[2])).toBe(true);
  });
  it("rejects duplicate tuple identities across pages even when cardinality metadata is consistent", async () => {
    const document = topologyFixture();
    document.payload.nodes.page = { ...document.payload.nodes.page, limit: 2, total: 3, has_more: true };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...common(1, "topology"),
      list: { ...document.payload.nodes, page: { offset: 2, limit: 2, returned: 1, total: 3, has_more: false, items: [document.payload.nodes.page.items[0]] } } })));
    const progress = vi.fn();
    await expect(assembleTopology(document as never, new AbortController().signal, progress)).rejects.toThrow(/repeats a source row identity/);
    expect(progress).not.toHaveBeenCalled();
  });
  it("retains distinct address observations sharing a source pointer", () => {
    const document = topologyFixture();
    const first = document.payload.source_addresses.page.items[0];
    document.payload.source_addresses.page.items.push({ ...first, index: 1 });
    document.payload.source_addresses.page.total = 2;
    document.payload.source_addresses.page.returned = 2;
    expect(initialTopologyRows(document as never).source_addresses).toHaveLength(2);
  });
});
