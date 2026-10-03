/** Positions and declared joins only: this module never matches hosts or computes a path. */
import type { ProjectionRowRef, SelectionTarget } from "../../../webapp/frontend/src/projectionEmbed";
import { ContractRefusal } from "./errors";
import type { CompleteTopology, Legend, PathDocument, RowRefs, Style, StyleFact, TopologyNode } from "./types";

export const SCENE_NODE_LIMIT = 500;
export const SCENE_LINK_LIMIT = 1_000;
export type Position = Readonly<{ x: number; y: number; z: number }>;
export type PositionedNode = Readonly<{ row: TopologyNode; position: Position }>;
export type NodeGeometry = ReadonlyMap<string, PositionedNode>;

export function rowKey(row: ProjectionRowRef): string { return JSON.stringify([row.index, row.pointer]); }
export function hasSelection(model: CompleteTopology, target: SelectionTarget | null): boolean {
  return target === null || model.rows[target.list].some((row) => row.index === target.row.index && row.pointer === target.row.pointer);
}

/** A neutral grid follows projection order. Height/position make no role, tier or health claim. */
export function placeNodes(model: CompleteTopology): NodeGeometry {
  if (model.rows.nodes.length > SCENE_NODE_LIMIT || model.rows.cables.length + model.rows.structural_links.length > SCENE_LINK_LIMIT) {
    throw new ContractRefusal("RENDER_CAPACITY");
  }
  const result = new Map<string, PositionedNode>();
  const columns = Math.max(1, Math.ceil(Math.sqrt(model.rows.nodes.length)));
  const rows = Math.ceil(model.rows.nodes.length / columns);
  model.rows.nodes.forEach((row, ordinal) => {
    const key = rowKey(row);
    if (result.has(key)) throw new ContractRefusal("CONTEXT_MISMATCH");
    result.set(key, { row, position: { x: (ordinal % columns - (columns - 1) / 2) * 32,
      y: 0, z: (Math.floor(ordinal / columns) - (rows - 1) / 2) * 30 } });
  });
  return result;
}

/** A candidate list is not permission to choose an arbitrary matching endpoint. */
export function uniquePosition(refs: RowRefs, nodes: NodeGeometry): PositionedNode | null {
  return refs.state === "published" && refs.items.length === 1 ? nodes.get(rowKey(refs.items[0]!)) ?? null : null;
}

export function suppliedStyle(fact: StyleFact, legend: Legend): Style {
  return fact.state === "published" ? fact.value : legend.fallback;
}

/** An unresolved hop leaves a gap. Never bridge it, or map a raw FIB hostname to a device. */
export function pathPositions(path: PathDocument, nodes: NodeGeometry): readonly (PositionedNode | null)[] {
  if (path.payload.result.state !== "published") return [];
  const result: (PositionedNode | null)[] = Array(path.payload.result.value.hops.length).fill(null);
  if (path.payload.hop_evidence.state !== "published") return result;
  const seen = new Set<number>();
  for (const hop of path.payload.hop_evidence.items) {
    if (!Number.isSafeInteger(hop.hop_index) || hop.hop_index < 0 || hop.hop_index >= result.length || seen.has(hop.hop_index)) {
      throw new ContractRefusal("CONTEXT_MISMATCH");
    }
    seen.add(hop.hop_index);
    result[hop.hop_index] = uniquePosition(hop.node_rows, nodes);
  }
  return result;
}
