/**
 * compile-producer-emission.mjs — which producer fields the collector ACTUALLY EMITTED, for the
 * compiled fields that `compile-snapshot.mjs` fills in when the source key is absent.
 *
 * Why this exists: the shared compiler turns an absent source key into a value — `unevaluable:
 * l.unevaluable === true` gives `false`, `strs(l.unmodeled_qualifiers)` gives `[]`, `established:
 * l.established === true` gives `false`, and `strs(h?.deductions)` gives `[]` for a device that has
 * no health_scores record at all. The Inspector then presented those manufactured values as producer
 * testimony ("unevaluable false — the collector's own flag"; "deductions [ ] empty — 0 items") for
 * fields the collector never emitted (2026-09-22 critic, B6 major / B1 minor). That compiler is the
 * shared bridge and owned elsewhere, so — as compile-rib-evidence.mjs and compile-acl-bindings.mjs do
 * — this sidecar is bound to the same source bytes by sha256, and a consumer that finds the two
 * differing must treat every such field as "whether the collector emitted it is unknown", never as
 * emitted.
 *
 * The map from compiled field to source key lives HERE, beside the source reading. It names the
 * defaulting sites found in compile-snapshot.mjs on 2026-09-22 (ACL lines: unevaluable,
 * unmodeled_qualifiers, established; devices: the health_scores record). It is a bounded list, not a
 * proof that no other compiled field is defaulted: `src/panels/producer-emission.test.ts` re-reads
 * the source and checks each LISTED field on every record, and a new defaulting site in the shared
 * compiler must be added here.
 *
 * Run: node tools/compile-producer-emission.mjs
 */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "../../webapp/sample_data/sample_fleet.snapshot.json");
const OUT = resolve(HERE, "../src/panels/producer-emission.json");

const raw = readFileSync(SRC);
const snap = JSON.parse(raw.toString("utf8"));
const sha256 = createHash("sha256").update(raw).digest("hex");

/** @param {unknown} v @returns {Record<string, any>} */
const obj = (v) => (v !== null && typeof v === "object" && !Array.isArray(v) ? v : {});
/** @param {unknown} v @returns {any[]} */
const arr = (v) => (Array.isArray(v) ? v : []);

/** compiled field -> the source key whose absence the compiler turns into a value. */
const ACL_LINE_FIELDS = { unevaluable: "unevaluable", unmodeledQualifiers: "unmodeled_qualifiers", established: "established" };
/** compiled device field -> the source record (health_scores) whose absence becomes a value. */
const DEVICE_HEALTH_FIELDS = { deductions: "deductions" };

/** @type {Record<string, string[]>} cite -> compiled fields whose source key was NOT emitted */
const aclLineAbsent = {};
for (const [host, lists] of Object.entries(obj(snap.acls))) {
  for (const [name, lines] of Object.entries(obj(lists))) {
    arr(lines).forEach((l, i) => {
      const rec = obj(l);
      const missing = Object.entries(ACL_LINE_FIELDS)
        .filter(([, key]) => !Object.prototype.hasOwnProperty.call(rec, key))
        .map(([field]) => field)
        .sort();
      if (missing.length > 0) aclLineAbsent[`acls.${host}.${name}[${i}]`] = missing;
    });
  }
}

/** @type {Record<string, string[]>} host -> compiled device fields whose source was NOT emitted */
const deviceAbsent = {};
const health = new Map();
for (const h of arr(snap.health_scores)) if (typeof obj(h).switch === "string") health.set(h.switch, obj(h));
const hosts = new Set([
  ...Object.keys(obj(snap.devices)),
  ...arr(obj(snap.cable_map).nodes).map((n) => obj(n).host).filter((h) => typeof h === "string"),
]);
for (const host of [...hosts].sort()) {
  const h = health.get(host);
  const missing = Object.entries(DEVICE_HEALTH_FIELDS)
    .filter(([, key]) => h === undefined || !Object.prototype.hasOwnProperty.call(h, key))
    .map(([field]) => field)
    .sort();
  if (missing.length > 0) deviceAbsent[host] = missing;
}

/** @param {Record<string, string[]>} o */
const sortObj = (o) => Object.fromEntries(Object.entries(o).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
const out = {
  meta: {
    source: "webapp/sample_data/sample_fleet.snapshot.json",
    sourceSha256: sha256,
    sourceBytes: raw.length,
    aclLineFields: ACL_LINE_FIELDS,
    deviceHealthFields: DEVICE_HEALTH_FIELDS,
  },
  aclLineAbsent: sortObj(aclLineAbsent),
  deviceAbsent: sortObj(deviceAbsent),
};
writeFileSync(OUT, JSON.stringify(out, null, 1) + "\n");
console.log(`producer-emission: ${Object.keys(aclLineAbsent).length} ACL line(s), ${Object.keys(deviceAbsent).length} device(s) with defaulted fields -> ${OUT}`);
