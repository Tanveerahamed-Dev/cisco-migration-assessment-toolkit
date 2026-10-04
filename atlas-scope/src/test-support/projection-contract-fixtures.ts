/** Synthetic test inputs only. No production entry imports this module. */
import { webcrypto } from "node:crypto";
import { topologyFixture, pathFixture } from "../../../webapp/frontend/src/test/projectionFixtures";
import { projectionContextDigest, TOPOLOGY_LISTS } from "../../../webapp/frontend/src/projectionEmbed";
import type { CompleteTopology, PathDocument, TopologyDocument } from "../contract-mode/types";

export function rawTopology() {
  const value = topologyFixture(7);
  for (const name of TOPOLOGY_LISTS) value.payload[name].page.limit = 200;
  return value;
}
export function rawPath(src = "192.0.2.10", dst = "198.51.100.10") { return pathFixture(7, src, dst); }
export function typedPath(): PathDocument { return rawPath() as unknown as PathDocument; }
export async function completeFixture(): Promise<CompleteTopology> {
  const document = rawTopology() as unknown as TopologyDocument;
  const contextDigest = await projectionContextDigest(document.engine, document.limitations, webcrypto.subtle);
  return { document, contextDigest, rows: { nodes: document.payload.nodes.page.items, cables: document.payload.cables.page.items,
    structural_links: document.payload.structural_links.page.items, failure_impact: document.payload.failure_impact.page.items,
    source_addresses: document.payload.source_addresses.page.items } };
}
