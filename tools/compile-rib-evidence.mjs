/**
 * compile-rib-evidence.mjs — the evidence that says whether a collected routing table is COMPLETE,
 * compiled for the forwarding engine.
 *
 * Why this exists: the engine decides "dropped — no route" from `routes.<host>` alone. A table that
 * holds four connected/local routes looks exactly like a table that holds everything, unless the
 * reader also knows that the routing protocols which populate it were never collected, or that the
 * control plane reports prefixes the table does not hold. The snapshot records both —
 * `protocol_assessability.rows` (per host, per protocol family: assessed / partial / not_collected)
 * and `overlay.<host>.evpn_neighbors` / `routing_neighbors.<host>` (adjacencies and received-prefix
 * counts) — and neither was projected anywhere, so core2's partial table was read as complete and a
 * no-route drop there was banded REFUTED (2026-09-21 critic, B1 blocker).
 *
 * Why a SEPARATE file from compile-snapshot.mjs: that compiler is the shared bridge for the whole UI
 * model and is owned elsewhere; the only consumer of these fields is the forwarding engine (see
 * compile-acl-bindings.mjs for the same arrangement). It is bound to the same source bytes by
 * sha256 and the engine refuses the whole file when the two differ — a refused file makes every
 * collected table INCOMPLETE, never complete.
 *
 * Which protocol families populate a routing table is not a list written here: it is the set of
 * protocol keys the producer itself uses in `routing_neighbors` records (ospf / eigrp / bgp in this
 * snapshot), matched case-insensitively against the assessability families. If the snapshot names
 * no such keys the set is empty, and the engine reads that as "completeness unknown", not "complete".
 *
 * Doctrine as the other compilers: every field is READ, never defaulted.
 *
 * Run: node tools/compile-rib-evidence.mjs
 */
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readSource } from "./source-binding.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../src/forwarding/rib-evidence.json");

/* The source and the bytes that bind it: tools/source-binding.mjs owns the rule (LF-normalised). */
const { snap, binding } = readSource(HERE);

/** @param {unknown} v @returns {Record<string, any>} */
const obj = (v) => (v !== null && typeof v === "object" && !Array.isArray(v) ? v : {});
/** @param {unknown} v @returns {any[]} */
const arr = (v) => (Array.isArray(v) ? v : []);
/** @param {unknown} v @returns {string | null} */
const str = (v) => (typeof v === "string" && v.trim() !== "" ? v.trim() : null);
/** @param {unknown} v @returns {number | null} */
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/* The producer's own routing-protocol vocabulary: every key it uses inside a routing_neighbors host
   record. Sorted so the output is byte-stable. */
const neighbours = obj(snap.routing_neighbors);
const routingProtocols = [
  ...new Set(Object.values(neighbours).flatMap((rec) => Object.keys(obj(rec)).map((k) => k.toLowerCase()))),
].sort();

/**
 * @typedef {{ protocol: string; state: string | null; reason: string | null; cite: string }} ProtocolRow
 * @typedef {{ protocol: string; neighbor: string | null; state: string | null; cite: string }} Adjacency
 * @typedef {{ kind: string; neighbor: string | null; state: string | null; prefixes: number | null; cite: string }} OverlayPeer
 * @typedef {{ protocols: ProtocolRow[]; adjacencies: Adjacency[]; overlay: OverlayPeer[] }} HostEvidence
 */
/** @type {Record<string, HostEvidence>} */
const hosts = {};
/** @param {string} h @returns {HostEvidence} */
const at = (h) => (hosts[h] ??= { protocols: [], adjacencies: [], overlay: [] });

arr(obj(snap.protocol_assessability).rows).forEach((r, i) => {
  const host = str(obj(r).switch);
  const protocol = str(obj(r).protocol);
  if (host === null || protocol === null) return;
  if (!routingProtocols.includes(protocol.toLowerCase())) return;
  at(host).protocols.push({
    protocol,
    state: str(r.state),
    reason: str(r.reason),
    cite: `protocol_assessability.rows[${i}]`,
  });
});

for (const [host, rec] of Object.entries(neighbours)) {
  for (const [protocol, list] of Object.entries(obj(rec))) {
    arr(list).forEach((n, i) => {
      at(host).adjacencies.push({
        protocol: protocol.toLowerCase(),
        neighbor: str(obj(n).neighbor),
        state: str(obj(n).state),
        cite: `routing_neighbors.${host}.${protocol}[${i}]`,
      });
    });
  }
}

for (const [host, rec] of Object.entries(obj(snap.overlay))) {
  arr(obj(rec).evpn_neighbors).forEach((n, i) => {
    at(host).overlay.push({
      kind: "evpn",
      neighbor: str(obj(n).neighbor),
      state: str(obj(n).state),
      prefixes: num(obj(n).prefixes),
      cite: `overlay.${host}.evpn_neighbors[${i}]`,
    });
  });
}

const sorted = Object.fromEntries(Object.entries(hosts).sort(([a], [b]) => a.localeCompare(b)));
const out = {
  meta: {
    ...binding,
    routingProtocols,
    routingProtocolsFrom: "routing_neighbors",
  },
  hosts: sorted,
};
writeFileSync(OUT, JSON.stringify(out, null, 1) + "\n");
console.log(
  `rib-evidence: ${Object.keys(sorted).length} hosts, routing protocols [${routingProtocols.join(", ")}], sha ${binding.sourceSha256.slice(0, 8)} (${binding.sourceDigestForm})`,
);
