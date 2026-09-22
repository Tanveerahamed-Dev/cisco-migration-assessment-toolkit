/**
 * compile-acl-bindings.mjs — the interface ACL bindings (`ip access-group`) the snapshot carries,
 * compiled for the forwarding engine.
 *
 * Why this is a SEPARATE file from compile-snapshot.mjs: that compiler is the shared bridge for
 * the whole UI model and is owned elsewhere; the only consumer of these fields is the forwarding
 * engine, so its projection lives next to it (src/forwarding/acl-bindings.json). It is bound to the
 * same source bytes as fabric.json by sha256 — the engine refuses the whole file (every binding
 * becomes "not observed") when the two were compiled from different snapshots, so a stale sidecar
 * can never be read as evidence about a newer snapshot.
 *
 * Doctrine is the same as the main compiler: every field is READ, never defaulted. The snapshot
 * records a binding as `acl_in` / `acl_out`, the producer's gate projection as
 * `forwarding_gate_candidates`, and a candidate whose ACL name the producer could not project as
 * `forwarding_gate_unmodeled: candidate_projection_incomplete`. A port whose running configuration
 * was not observed carries `runConfigObserved: false` — which the engine reads as "binding unknown",
 * never as "no ACL here".
 *
 * Run: node tools/compile-acl-bindings.mjs
 */
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readSource } from "./source-binding.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../src/forwarding/acl-bindings.json");

/* The source and the bytes that bind it: tools/source-binding.mjs owns the rule (LF-normalised). */
const { snap, binding } = readSource(HERE);

const NOT_OBSERVED = /^\s*\[NOT OBSERVED\]/i;
/** @param {unknown} v @returns {string | null} */
const val = (v) => {
  if (v === undefined || v === null) return null;
  if (typeof v !== "string") return null;
  const t = v.trim();
  if (t === "" || t === "-" || t === "N/A" || NOT_OBSERVED.test(t)) return null;
  return t;
};
/** @param {unknown} v @returns {string[]} */
const list = (v) => (val(v) ?? "").split(",").map((s) => s.trim()).filter((s) => s !== "");
/** @param {unknown} v @returns {Record<string, any>} */
const obj = (v) => (v !== null && typeof v === "object" && !Array.isArray(v) ? v : {});

/**
 * The record shape `src/forwarding/bindings.ts :: BindingRecord` reads.
 * @typedef {{ port: string; vlan: string | null; switchportMode: string | null; aclIn: string | null;
 *   aclOut: string | null; gateCandidates: string[]; gateUnmodeled: string[]; runConfigObserved: boolean;
 *   cite: string }} BindingRecord
 */
/** @type {Record<string, BindingRecord[]>} */
const hosts = {};
for (const [host, ports] of Object.entries(obj(snap.interfaces)).sort(([a], [b]) => a.localeCompare(b))) {
  hosts[host] = Object.entries(obj(ports)).map(([port, p]) => ({
    port,
    vlan: val(p.vlan),
    switchportMode: val(p.switchport_mode),
    aclIn: val(p.acl_in),
    aclOut: val(p.acl_out),
    gateCandidates: list(p.forwarding_gate_candidates),
    gateUnmodeled: list(p.forwarding_gate_unmodeled),
    runConfigObserved: p.run_config_observed === true,
    cite: `interfaces.${host}.${port}`,
  }));
}

const out = {
  meta: { ...binding },
  hosts,
};
writeFileSync(OUT, JSON.stringify(out, null, 1) + "\n");
const bound = Object.values(hosts).flat().filter((r) => r.aclIn !== null || r.aclOut !== null).length;
console.log(`acl-bindings: ${Object.keys(hosts).length} hosts, ${bound} bound interface(s), sha ${binding.sourceSha256.slice(0, 8)} (${binding.sourceDigestForm})`);
