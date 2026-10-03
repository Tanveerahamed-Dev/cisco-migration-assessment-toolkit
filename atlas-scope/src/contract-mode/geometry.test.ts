import { describe, expect, it } from "vitest";
import { hasSelection, pathPositions, placeNodes, suppliedStyle, uniquePosition } from "./geometry";
import { completeFixture, rawPath, typedPath } from "./testing";
import type { PathDocument, RowRefs } from "./types";

describe("contract geometry never becomes a topology or forwarding owner", () => {
  it("positions every supplied node record, including the uncollected peer", async () => {
    const model = await completeFixture(), before = JSON.stringify(model);
    const nodes = placeNodes(model);
    expect(nodes.size).toBe(2);
    expect([...nodes.values()].map((item) => item.row.pointer)).toEqual(model.rows.nodes.map((item) => item.pointer));
    expect([...nodes.values()][1]?.row.collected.value).toBe(false);
    expect(JSON.stringify(model)).toBe(before);
  });
  it("requires published unique engine endpoint joins", async () => {
    const model = await completeFixture(), nodes = placeNodes(model), refs = model.rows.cables[0]!.a_nodes;
    expect(uniquePosition(refs, nodes)?.row.index).toBe(0);
    expect(uniquePosition({ ...refs, items: [...refs.items, ...refs.items] } as RowRefs, nodes)).toBeNull();
    expect(uniquePosition({ ...refs, state: "unverified", reason: "Synthetic ambiguity" } as RowRefs, nodes)).toBeNull();
    expect(uniquePosition({ ...refs, items: [{ index: 99, pointer: "/cable_map/nodes/99" }] } as RowRefs, nodes)).toBeNull();
  });
  it("uses node_rows instead of raw FIB host labels and preserves unresolved gaps", async () => {
    const model = await completeFixture(), nodes = placeNodes(model), raw = rawPath();
    expect(raw.payload.result.value.hops[0]?.host).not.toBe(model.rows.nodes[0]?.host.value);
    expect(pathPositions(typedPath(), nodes)[0]?.row.index).toBe(0);
    raw.payload.result.value.hops.push({ ...raw.payload.result.value.hops[0]! }, { ...raw.payload.result.value.hops[0]! });
    raw.payload.hop_evidence.items.push({ ...raw.payload.hop_evidence.items[0]!, hop_index: 2 });
    const result = pathPositions(raw as unknown as PathDocument, nodes);
    expect(result.map((node) => node?.row.index ?? null)).toEqual([0, null, 0]);
    raw.payload.hop_evidence.items.push({ ...raw.payload.hop_evidence.items[0]! });
    expect(() => pathPositions(raw as unknown as PathDocument, nodes)).toThrow("CONTEXT_MISMATCH");
  });
  it("uses the supplied fallback and refuses hidden rendering truncation", async () => {
    const model = await completeFixture(), fact = model.rows.nodes[0]!.style;
    expect(suppliedStyle(fact, model.document.payload.legend)).toBe(fact.value);
    expect(suppliedStyle({ ...fact, state: "not_collected", value: null, reason: "Synthetic missing style" }, model.document.payload.legend)).toBe(model.document.payload.legend.fallback);
    const excessive = { ...model, rows: { ...model.rows, nodes: Array(501).fill(model.rows.nodes[0]!) } };
    expect(() => placeNodes(excessive)).toThrow("RENDER_CAPACITY");
    expect(hasSelection(model, { list: "nodes", row: { index: 0, pointer: "/cable_map/nodes/0" } })).toBe(true);
    expect(hasSelection(model, { list: "nodes", row: { index: 1, pointer: "/cable_map/nodes/0" } })).toBe(false);
  });
});
