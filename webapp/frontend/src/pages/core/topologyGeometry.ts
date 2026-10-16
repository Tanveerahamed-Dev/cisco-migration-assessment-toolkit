import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, type SimulationNodeDatum } from "d3-force";
import { DRAW_LINK_LIMIT, DRAW_NODE_LIMIT, exactEndpoint, rowKey, type TopologyNode, type TopologyRows } from "./topologyData";

export const CHASSIS_WIDTH = 176;
export const CHASSIS_HEIGHT = 64;
export interface MapPoint { x: number; y: number }
export type MapLink = TopologyRows["cables"][number] | TopologyRows["structural_links"][number];
type Side = "left" | "right" | "top" | "bottom";
interface LayoutNode extends SimulationNodeDatum { id: string }

export function displayedNodes(nodes: readonly TopologyNode[], collectedOnly: boolean) {
  return nodes.filter((node) => !collectedOnly || node.collected.state === "published" && node.collected.value === true).slice(0, DRAW_NODE_LIMIT);
}

function joinedRows(nodes: readonly TopologyNode[], links: readonly MapLink[]) {
  return links.slice(0, DRAW_LINK_LIMIT).flatMap((row) => {
    const a = exactEndpoint(row.a_nodes, nodes), b = exactEndpoint(row.b_nodes, nodes);
    return a && b ? [{ row, aKey: rowKey(a), bKey: rowKey(b) }] : [];
  });
}

/** d3 owns only disposable coordinates. Projection rows and references are never simulation data.
 *  Forces represent screen geometry, not tier, health, reachability or physical location. */
export function forceTopologyLayout(nodes: readonly TopologyNode[], links: readonly MapLink[]) {
  const limited = nodes.slice(0, DRAW_NODE_LIMIT);
  const copies: LayoutNode[] = limited.map((node) => ({ id: rowKey(node) }));
  const edges = joinedRows(limited, links).map(({ aKey, bKey }) => ({ source: aKey, target: bKey }));
  if (!copies.length) return { positions: new Map<string, MapPoint>(), width: 1000, height: 600 };
  const simulation = forceSimulation(copies).stop()
    .force("links", forceLink<LayoutNode, typeof edges[number]>(edges).id((node) => node.id).distance(260).strength(.3))
    .force("charge", forceManyBody<LayoutNode>().strength(-750))
    .force("collision", forceCollide<LayoutNode>(118).iterations(2))
    .force("center", forceCenter(0, 0));
  // Bounded synchronous layout: no timer or application-state update survives this function.
  simulation.tick(120);
  simulation.stop();
  const minX = Math.min(...copies.map((node) => node.x!)), maxX = Math.max(...copies.map((node) => node.x!));
  const minY = Math.min(...copies.map((node) => node.y!)), maxY = Math.max(...copies.map((node) => node.y!));
  const width = Math.max(1000, maxX - minX + 320), height = Math.max(600, maxY - minY + 240);
  const offsetX = (width - (maxX - minX)) / 2 - minX, offsetY = (height - (maxY - minY)) / 2 - minY;
  return { positions: new Map(copies.map((node) => [node.id, { x: node.x! + offsetX, y: node.y! + offsetY }])), width, height };
}

function facing(a: MapPoint, b: MapPoint): Side {
  return Math.abs(b.x - a.x) >= Math.abs(b.y - a.y)
    ? b.x >= a.x ? "right" : "left" : b.y >= a.y ? "bottom" : "top";
}
function anchor(center: MapPoint, side: Side, slot: number, total: number): MapPoint {
  const fraction = (slot + 1) / (total + 1);
  return side === "left" || side === "right"
    ? { x: center.x + (side === "left" ? -1 : 1) * CHASSIS_WIDTH / 2,
      y: center.y - CHASSIS_HEIGHT / 2 + fraction * CHASSIS_HEIGHT }
    : { x: center.x - CHASSIS_WIDTH / 2 + fraction * CHASSIS_WIDTH,
      y: center.y + (side === "top" ? -1 : 1) * CHASSIS_HEIGHT / 2 };
}

export function cableCurve(a: MapPoint, b: MapPoint, horizontal: boolean): string {
  if (horizontal) {
    const middle = (a.x + b.x) / 2;
    return `M${a.x},${a.y} C${middle},${a.y} ${middle},${b.y} ${b.x},${b.y}`;
  }
  const middle = (a.y + b.y) / 2;
  return `M${a.x},${a.y} C${a.x},${middle} ${b.x},${middle} ${b.x},${b.y}`;
}

export function chassisLinks(nodes: readonly TopologyNode[], links: readonly MapLink[], positions: ReadonlyMap<string, MapPoint>) {
  const joined = joinedRows(nodes, links).flatMap((link) => {
    const a = positions.get(link.aKey), b = positions.get(link.bKey);
    if (!a || !b) return [];
    const self = link.aKey === link.bKey;
    const aSide = facing(a, b), bSide = self ? "top" as const : facing(b, a);
    return [{ ...link, a, b, self, aSide, bSide, aSlot: `${link.aKey}:${aSide}`, bSlot: `${link.bKey}:${bSide}` }];
  });
  const counts = new Map<string, number>();
  for (const link of joined) for (const key of [link.aSlot, link.bSlot]) counts.set(key, (counts.get(key) ?? 0) + 1);
  const slots = new Map<string, number>();
  return joined.map((link) => {
    const nextAnchor = (key: string, point: MapPoint, side: Side) => {
      const slot = slots.get(key) ?? 0;
      slots.set(key, slot + 1);
      return anchor(point, side, slot, counts.get(key)!);
    };
    const a = nextAnchor(link.aSlot, link.a, link.aSide), b = nextAnchor(link.bSlot, link.b, link.bSide);
    const path = link.self ? `M${a.x},${a.y} C${a.x + 90},${a.y} ${b.x},${b.y - 90} ${b.x},${b.y}`
      : cableCurve(a, b, link.aSide === "left" || link.aSide === "right");
    return { row: link.row, a, b, aSide: link.aSide, bSide: link.bSide, path };
  });
}

export function publishedPortLabels(row: MapLink): { a: string; b: string } | null {
  // Structural graph rows are host-pair relationships, never asserted physical cable ends.
  if (!("members" in row) || row.ends.state !== "published") return null;
  return { a: row.ends.value.a_port, b: row.ends.value.b_port };
}

export function matchesLoadedNode(node: TopologyNode, query: string): boolean {
  return !!query.trim() && node.host.state === "published"
    && node.host.value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}
