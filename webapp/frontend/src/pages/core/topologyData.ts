import { loadProjectionPage, requireProjectionPage, type Schemas, type ViewDocument } from "../../projection";
import { TOPOLOGY_LISTS, TOPOLOGY_STYLE_SCHEMA, EMBED_MAX_ROWS, EMBED_MAX_PAGES, canonicalProjectionJson, type SelectionTarget } from "../../projectionEmbed";

// Feature-private transport assembly and geometry only. Hostnames, status and risk never
// participate in joins or visual classifications: the engine supplies those facts and styles.
export type TopologyDocument = ViewDocument<"topology">;
export type TopologyPayload = TopologyDocument["payload"];
export { TOPOLOGY_LISTS };
export type TopologyListName = typeof TOPOLOGY_LISTS[number];
export type TopologyRows = { [K in TopologyListName]: ReadonlyArray<TopologyPayload[K]["page"]["items"][number]> };
export type TopologyRow = TopologyRows[TopologyListName][number];
export type RowRef = Schemas["UiProjection1_RowRef"];
export type TopologyTarget = SelectionTarget;
export type TopologyNode = TopologyRows["nodes"][number];
export type TopologyLegend = TopologyPayload["legend"];

export const ASSEMBLY_ROW_LIMIT = EMBED_MAX_ROWS;
export const ASSEMBLY_PAGE_LIMIT = EMBED_MAX_PAGES;
export const DRAW_NODE_LIMIT = 500;
export const DRAW_LINK_LIMIT = 1_000;

export class TopologyCapacityError extends Error {}

function ownedJson<T>(value: T): T {
  const copy: T = JSON.parse(canonicalProjectionJson(value));
  const freeze = (item: unknown): void => {
    if (item !== null && typeof item === "object") {
      for (const child of Object.values(item)) freeze(child);
      Object.freeze(item);
    }
  };
  freeze(copy);
  return copy;
}

function requireUniqueRows(items: readonly RowRef[], prior = new Set<string>()): Set<string> {
  const seen = new Set(prior);
  for (const row of items) {
    const key = rowKey(row);
    if (seen.has(key)) throw new Error("A topology page repeats a source row identity. Reload the view.");
    seen.add(key);
  }
  return seen;
}

export function initialTopologyRows(document: TopologyDocument): TopologyRows {
  const legend = document.payload.legend;
  const tokens = new Set(legend.entries.map((entry) => entry.token));
  if (legend.schema !== TOPOLOGY_STYLE_SCHEMA || tokens.size !== legend.entries.length || !tokens.has(legend.fallback.token)) {
    throw new Error("The engine topology legend is unavailable or ambiguous.");
  }
  for (const name of TOPOLOGY_LISTS) {
    const page = document.payload[name].page;
    requireProjectionPage(page);
    if (page.offset !== 0 || document.payload[name].pointer !== `/${name}`) {
      throw new Error("Topology lists do not begin at the expected source page.");
    }
    requireUniqueRows(page.items);
  }
  return ownedJson({ nodes: document.payload.nodes.page.items, cables: document.payload.cables.page.items,
    structural_links: document.payload.structural_links.page.items, failure_impact: document.payload.failure_impact.page.items,
    source_addresses: document.payload.source_addresses.page.items });
}

export async function assembleTopology(document: TopologyDocument, signal: AbortSignal,
  progress: (rows: TopologyRows) => void): Promise<TopologyRows> {
  // Freeze an owned request baseline so neither a callback nor a source alias can change
  // the identity/context against which later pages are compared.
  const baseline = ownedJson(document);
  let rows = initialTopologyRows(baseline);
  let budget = ASSEMBLY_ROW_LIMIT;
  for (const name of TOPOLOGY_LISTS) {
    if (baseline.payload[name].page.total > budget) {
      throw new TopologyCapacityError(`The interactive map is limited to ${ASSEMBLY_ROW_LIMIT.toLocaleString()} projected rows. The evidence lists remain paged.`);
    }
    budget -= baseline.payload[name].page.total;
  }
  let pages = 0;
  for (const name of TOPOLOGY_LISTS) {
    const source = baseline.payload[name];
    let page = source.page;
    let seen = requireUniqueRows(rows[name]);
    while (page.has_more) {
      if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
      if (++pages > ASSEMBLY_PAGE_LIMIT) throw new TopologyCapacityError("Topology page assembly reached its request limit.");
      const next = await loadProjectionPage(baseline, source, page.offset + page.returned, undefined, signal);
      if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
      seen = requireUniqueRows(next.page.items, seen);
      // The guarded request retains the same view/pointer and therefore the same row type.
      // Only the new page's row graph is cloned; accumulated rows stay immutable and shared.
      rows = Object.freeze({ ...rows, [name]: Object.freeze([...rows[name], ...ownedJson(next.page.items)]) });
      page = next.page;
      progress({ ...rows });
    }
  }
  return rows;
}

export function rowKey(row: RowRef): string { return JSON.stringify([row.index, row.pointer]); }
export function targetKey(target: TopologyTarget): string { return `${target.list}:${rowKey(target.row)}`; }
export function hasTarget(rows: TopologyRows, target: TopologyTarget): boolean {
  return rows[target.list].some((row) => row.index === target.row.index && row.pointer === target.row.pointer);
}

export function diagramPositions(nodes: readonly TopologyNode[]): Map<string, { x: number; y: number }> {
  return new Map(nodes.map((node, index) => {
    if (nodes.length > 40) {
      const columns = Math.ceil(Math.sqrt(nodes.length * 1.6));
      const rowCount = Math.ceil(nodes.length / columns);
      return [rowKey(node), { x: 50 + (index % columns + .5) * 900 / columns,
        y: 45 + (Math.floor(index / columns) + .5) * 510 / rowCount }];
    }
    const angle = index * Math.PI * 2 / Math.max(1, nodes.length) - Math.PI / 2;
    return [rowKey(node), { x: 500 + (nodes.length === 1 ? 0 : 370 * Math.cos(angle)),
      y: 300 + (nodes.length === 1 ? 0 : 210 * Math.sin(angle)) }];
  }));
}

export function exactEndpoint(refs: { readonly state: string; readonly items: readonly RowRef[] },
  nodes: readonly TopologyNode[]): TopologyNode | undefined {
  if (refs.state !== "published" || refs.items.length !== 1) return undefined;
  const ref = refs.items[0];
  const matches = nodes.filter((node) => node.index === ref.index && node.pointer === ref.pointer);
  return matches.length === 1 ? matches[0] : undefined;
}

export function topologyStyle(fact: TopologyNode["style"], legend: TopologyLegend) {
  const value = fact.state === "published" ? fact.value : legend.fallback;
  const entry = legend.entries.find((item) => item.token === value.token);
  if (!entry) throw new Error("The engine style is absent from its legend.");
  return { value, entry };
}
