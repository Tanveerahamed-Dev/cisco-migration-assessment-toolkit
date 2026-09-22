/**
 * rib-completeness.ts — is a collected routing table COMPLETE enough to decide "no route"?
 *
 * A "dropped — no route" outcome is a claim about an ABSENCE: nothing in the table matches. That
 * claim is only as strong as the table's completeness, and the table cannot testify to its own
 * completeness — four connected routes look the same whether they are everything or a sliver. The
 * snapshot does testify, in two places this module reads (compiled by
 * `tools/compile-rib-evidence.mjs` into `rib-evidence.json`, sha-bound to the same bytes):
 *
 *  - `protocol_assessability.rows`: a routing-protocol family (the producer's own routing
 *    vocabulary — the keys of its `routing_neighbors` records) whose state on this host is anything
 *    but `assessed` was not collected, or only partly, so what it installs is unknown;
 *  - control-plane evidence the table does not reflect: an established overlay peer reporting
 *    received prefixes, or an established/FULL adjacency, where the table holds no route of that
 *    protocol at all.
 *
 * Every reason is derived from those records — never from a list of host names. When the sidecar
 * was compiled from other bytes, or names no routing vocabulary at all, completeness is UNKNOWN and
 * every table reads as incomplete: an unreadable completeness record can never make a table look
 * whole. (2026-09-21 critic, B1 blocker: core2's four-route table decided 60 "no counterexample"
 * drops while the snapshot recorded OSPF/BGP/EIGRP not_collected and a 240-prefix EVPN peer.)
 */
import evidenceJson from "./rib-evidence.json";
import { fabric, routesOf } from "../core/data";
import type { Cite } from "../core/types";

interface ProtocolRow {
  protocol: string;
  state: string | null;
  reason: string | null;
  cite: Cite;
}
interface Adjacency {
  protocol: string;
  neighbor: string | null;
  state: string | null;
  cite: Cite;
}
interface OverlayPeer {
  kind: string;
  neighbor: string | null;
  state: string | null;
  prefixes: number | null;
  cite: Cite;
}
interface HostEvidence {
  protocols: ProtocolRow[];
  adjacencies: Adjacency[];
  overlay: OverlayPeer[];
}
interface EvidenceFile {
  meta: { source: string; sourceSha256: string; sourceBytes: number; routingProtocols: string[]; routingProtocolsFrom: string };
  hosts: Record<string, HostEvidence>;
}

const FILE = evidenceJson as unknown as EvidenceFile;

/** The sidecar is evidence only about the bytes it was compiled from. */
export const RIB_EVIDENCE_TRUSTED = FILE.meta.sourceSha256 === fabric.meta.sourceSha256;

/** One reason a collected table cannot be read as complete, with the record that says so. */
export interface RibIncompleteness {
  label: string;
  cite: Cite;
}

/** An adjacency / session state that means routes are being exchanged. */
const EXCHANGING = /^(full|established)\b/i;

const CACHE = new Map<string, RibIncompleteness[]>();

/**
 * Why `host`'s collected routing table is not complete. Empty means the snapshot's own
 * routing-protocol receipts cover this table and nothing observed contradicts it — NOT that the
 * table is proven complete (the families' own boundaries still apply). A host with no collected
 * table is not asked here: it is unmodelled, which is a stronger statement.
 */
export function ribIncompleteness(host: string): RibIncompleteness[] {
  const hit = CACHE.get(host);
  if (hit !== undefined) return hit;
  const out: RibIncompleteness[] = [];
  if (!RIB_EVIDENCE_TRUSTED) {
    out.push({
      label: `the routing-completeness record was compiled from different snapshot bytes (${FILE.meta.sourceSha256.slice(0, 8)}) than this build's data, so whether ${host}'s table is complete is unknown`,
      cite: `routes.${host}`,
    });
    CACHE.set(host, out);
    return out;
  }
  const vocab = FILE.meta.routingProtocols;
  if (vocab.length === 0) {
    out.push({
      label: `the snapshot names no routing-protocol families (no ${FILE.meta.routingProtocolsFrom} keys), so whether ${host}'s table is complete is unknown`,
      cite: `routes.${host}`,
    });
    CACHE.set(host, out);
    return out;
  }
  const ev = FILE.hosts[host];
  const sources = new Set(routesOf(host).map((r) => (r.source ?? "").toLowerCase()));
  for (const proto of vocab) {
    const row = ev?.protocols.find((p) => p.protocol.toLowerCase() === proto);
    if (row === undefined) {
      out.push({ label: `no ${proto.toUpperCase()} collection receipt exists for ${host}`, cite: "protocol_assessability" });
    } else if (row.state !== "assessed") {
      out.push({
        label: `${row.protocol} is ${(row.state ?? "unrecorded").replace(/_/g, " ")} on ${host}`,
        cite: row.cite,
      });
    }
  }
  for (const a of ev?.adjacencies ?? []) {
    if (a.state === null || !EXCHANGING.test(a.state) || sources.has(a.protocol)) continue;
    out.push({
      label: `an ${a.protocol.toUpperCase()} adjacency with ${a.neighbor ?? "an unrecorded neighbour"} is ${a.state}, yet the table holds no ${a.protocol.toUpperCase()} route`,
      cite: a.cite,
    });
  }
  for (const p of ev?.overlay ?? []) {
    if (p.state === null || !EXCHANGING.test(p.state) || p.prefixes === null || p.prefixes <= 0 || sources.has("bgp")) continue;
    out.push({
      label: `an established ${p.kind.toUpperCase()} peer ${p.neighbor ?? "(unrecorded)"} reports ${p.prefixes} received prefixes, none of which the table holds`,
      cite: p.cite,
    });
  }
  CACHE.set(host, out);
  return out;
}

/** One sentence naming why `host`'s table is incomplete, or null when nothing says it is. */
export function ribIncompletenessSentence(host: string): string | null {
  const r = ribIncompleteness(host);
  if (r.length === 0) return null;
  return `${host}'s collected routing table is itself incomplete — ${r.map((x) => x.label).join("; ")}`;
}

/**
 * The hosts whose collected table the snapshot shows to be incomplete, in coverage order. A count of
 * collected RIBs ("RIBs 2/26") without this reads as two whole tables; on this snapshot both are
 * partial (2026-09-22 critic, B7). Every surface that counts RIBs reads it here.
 */
export function ribHostsShownIncomplete(): string[] {
  return fabric.coverage.routableHosts.filter((h) => ribIncompleteness(h).length > 0);
}

/** "(both shown incomplete)", "(1 of 3 shown incomplete)", or "" when none is. */
export function ribCountQualifier(): string {
  const all = fabric.coverage.routableHosts.length;
  const partial = ribHostsShownIncomplete().length;
  if (partial === 0) return "";
  if (partial === all) return all === 1 ? "(shown incomplete)" : all === 2 ? "(both shown incomplete)" : `(all ${all} shown incomplete)`;
  return `(${partial} of ${all} shown incomplete)`;
}
