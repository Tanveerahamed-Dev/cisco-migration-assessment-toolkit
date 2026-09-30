// @vitest-environment node
/**
 * compile-reserved-names.test.ts — a name the snapshot supplies is DATA, whatever it spells.
 *
 * WHY (CodeQL js/remote-property-injection, 2026-09-30). The compiler builds dictionaries keyed by names the
 * snapshot supplies — hosts, ACLs, object groups, ports — and a snapshot is untrusted input (a file a user opens,
 * or one AssessHub serves). While those dictionaries were plain objects written through `dict[name] = …`, a host
 * named "__proto__" REPLACED a dictionary's prototype, so the host vanished from routes, ACLs, object groups,
 * interfaces and ACL bindings with no error; through `dict[name] ??= …` it (and "constructor") was handed
 * Object.prototype / the Object function, and the rib-evidence compile crashed. And the lookup `devices[name]`
 * answered a topology-only node named "toString" from Object.prototype, so it compiled as an inventoried switch.
 * The rule the compiler now follows is written at `own` in tools/lib/compile-model.mjs (THE DICTIONARY RULE).
 *
 * THE FIXTURE is the tracked sample, renamed — never a hand-made shape. Three of its own hosts, chosen by ROLE
 * (the inventoried host present in the most name-keyed sections, the next such host, and the first topology-only
 * node), are renamed wherever they occur as a whole token (review/rename-snapshot.mjs's rule) to "__proto__",
 * "constructor" and "toString". The renamed snapshot is the same network under other names, so every compiled
 * document must be the original one under the same rename — except for what orders BY name (the device list and
 * the coverage host lists, compared as sets here) and the evidence projection's character budgets, which measure
 * name lengths (its records are compared by pointer).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { bindSource, lfNormalise } from "../../tools/source-binding.mjs";
import {
  BINDING_KEYS,
  compileAclBindings,
  compileAll,
  compileFabric,
  compileProducerEmission,
  compileRibEvidence,
  serialiseCompiled,
  type CompiledSet,
} from "../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../tools/lib/validate-snapshot.mjs";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SAMPLE_REL = "webapp/sample_data/sample_fleet.snapshot.json";
const SOURCE_TEXT = new TextDecoder().decode(lfNormalise(readFileSync(resolve(PKG, "..", SAMPLE_REL))));

const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const byCodeUnit = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
const escape = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/* ── the fixture: three of the sample's own hosts, chosen by role ─────────────────────────────── */
const ORIGINAL = JSON.parse(SOURCE_TEXT) as Record<string, unknown>;
/** The sections keyed by host name. */
const NAME_KEYED = ["routes", "acls", "object_groups", "interfaces", "routing_neighbors", "overlay"] as const;
const inventory = isObj(ORIGINAL.devices) ? Object.keys(ORIGINAL.devices) : [];
const reach = (h: string): number =>
  NAME_KEYED.filter((s) => {
    const section = ORIGINAL[s];
    return isObj(section) && Object.hasOwn(section, h);
  }).length;
const [RICHEST, NEXT] = [...inventory].sort((a, b) => reach(b) - reach(a) || byCodeUnit(a, b)) as [string, string];
const cableNodes = isObj(ORIGINAL.cable_map) && Array.isArray(ORIGINAL.cable_map.nodes) ? ORIGINAL.cable_map.nodes : [];
const TOPOLOGY_ONLY = cableNodes
  .map((n: unknown) => (isObj(n) ? n.host : undefined))
  .filter((h): h is string => typeof h === "string" && !inventory.includes(h))
  .sort(byCodeUnit)[0] as string;

const RENAME = new Map<string, string>([
  [RICHEST, "__proto__"],
  [NEXT, "constructor"],
  [TOPOLOGY_ONLY, "toString"],
]);
/* A host is replaced where it stands as a whole token, longest name first (review/rename-snapshot.mjs). */
const TOKEN = new RegExp(
  `(?<![A-Za-z0-9_])(?:${[...RENAME.keys()].sort((a, b) => b.length - a.length || byCodeUnit(a, b)).map(escape).join("|")})(?![A-Za-z0-9_])`,
  "g",
);
const renameText = (text: string): string => text.replace(TOKEN, (m) => RENAME.get(m) ?? m);
const RENAMED_TEXT = renameText(SOURCE_TEXT);

function prepare(text: string, name: string): { snap: Record<string, unknown>; binding: ReturnType<typeof bindSource>; schemaAssumed: string | null } {
  const bytes = new TextEncoder().encode(text);
  const v = assertValidSnapshot(bytes);
  return { snap: v.snap, binding: bindSource(bytes, { source: name, sourceOrigin: "external-file" }), schemaAssumed: v.schemaAssumed };
}
const original = prepare(SOURCE_TEXT, "sample.snapshot.json");
const renamed = prepare(RENAMED_TEXT, "reserved-names.snapshot.json");

/* ── comparing a document with the original under the rename ──────────────────────────────────── */
type Doc = Record<string, any>;
/** A `meta` without the source binding (the two snapshots are different bytes, so their digests differ). */
const unbound = (meta: Doc): Doc => Object.fromEntries(Object.entries(meta).filter(([k]) => !(BINDING_KEYS as readonly string[]).includes(k)));
/** The document as written, parsed; the ORIGINAL's written text first renamed exactly as the snapshot was. */
const written = (doc: unknown, rename: boolean): Doc => JSON.parse(rename ? renameText(JSON.stringify(doc)) : JSON.stringify(doc)) as Doc;
/** What a rename may change in the fabric: its order by name, and the evidence projection's name-length budgets. */
function canonFabric(f: Doc): Doc {
  const { meta, devices, coverage, evidenceRecords, evidenceProjection: _budgets, ...rest } = f;
  return {
    ...rest,
    meta: unbound(meta),
    devices: [...devices].sort((a: Doc, b: Doc) => byCodeUnit(a.id, b.id)),
    coverage: { ...coverage, routableHosts: [...coverage.routableHosts].sort(byCodeUnit), aclHosts: [...coverage.aclHosts].sort(byCodeUnit) },
    evidencePointers: (evidenceRecords as Doc[]).map((r) => r.pointer as string).sort(byCodeUnit),
  };
}
const canonSidecar = (d: Doc): Doc => ({ ...d, meta: unbound(d.meta) });

describe("a snapshot name is data, whatever it spells", () => {
  it("the fixture is the sample with three of its own hosts renamed to reserved names, reaching every name-keyed section", () => {
    expect(inventory.length, "the sample has no device inventory").toBeGreaterThan(2);
    expect(reach(RICHEST), `${RICHEST} is in too few name-keyed sections to exercise them`).toBeGreaterThanOrEqual(4);
    expect(reach(NEXT), `${NEXT} is in too few name-keyed sections to exercise them`).toBeGreaterThanOrEqual(3);
    expect(TOPOLOGY_ONLY, "the sample has no topology-only node").toBeTypeOf("string");
    for (const name of RENAME.values()) expect(SOURCE_TEXT.includes(name), `${name} already occurs in the sample`).toBe(false);
    for (const old of RENAME.keys()) {
      expect(new RegExp(`(?<![A-Za-z0-9_])${escape(old)}(?![A-Za-z0-9_])`).test(RENAMED_TEXT), `${old} survives the rename`).toBe(false);
    }
    for (const name of RENAME.values()) expect(RENAMED_TEXT.includes(`"${name}"`), `${name} is not in the renamed snapshot`).toBe(true);
    /* The parsed snapshot holds each reserved name as an ORDINARY member (JSON.parse defines members). */
    expect(Object.hasOwn(renamed.snap.devices as object, "__proto__")).toBe(true);
    expect(Object.hasOwn(renamed.snap.devices as object, "constructor")).toBe(true);
  });

  it("the whole set compiles and serialises, and neither Object.prototype nor Object gains a property", () => {
    const protoBefore = Object.getOwnPropertyNames(Object.prototype).sort();
    const objectBefore = Object.getOwnPropertyNames(Object).sort();
    let set: CompiledSet | undefined;
    expect(() => {
      set = compileAll(renamed.snap, renamed.binding, { schemaAssumed: renamed.schemaAssumed });
    }).not.toThrow();
    const texts = serialiseCompiled(set as CompiledSet);
    expect(texts.fabric).toContain('"__proto__":');
    expect(Object.getOwnPropertyNames(Object.prototype).sort()).toEqual(protoBefore);
    expect(Object.getOwnPropertyNames(Object).sort()).toEqual(objectBefore);
    expect(({} as Doc).protocols).toBeUndefined();
  });

  it("every name-keyed dictionary keeps Object.prototype as its prototype and holds each renamed host as an own member", () => {
    const set = compileAll(renamed.snap, renamed.binding, { schemaAssumed: renamed.schemaAssumed });
    const was = compileAll(original.snap, original.binding, { schemaAssumed: original.schemaAssumed });
    const dictionaries: [string, Doc, Doc][] = [
      ["fabric.routes", set.fabric.routes, was.fabric.routes],
      ["fabric.acls", set.fabric.acls, was.fabric.acls],
      ["fabric.objectGroups", set.fabric.objectGroups, was.fabric.objectGroups],
      ["fabric.interfaces", set.fabric.interfaces, was.fabric.interfaces],
      ["aclBindings.hosts", set.aclBindings.hosts, was.aclBindings.hosts],
      ["ribEvidence.hosts", set.ribEvidence.hosts, was.ribEvidence.hosts],
      ["producerEmission.deviceAbsent", set.producerEmission.deviceAbsent, was.producerEmission.deviceAbsent],
    ];
    let reserved = 0;
    for (const [label, dict, before] of dictionaries) {
      expect(Object.getPrototypeOf(dict), `${label}'s prototype was replaced`).toBe(Object.prototype);
      for (const [old, name] of RENAME) {
        expect(Object.hasOwn(dict, name), `${label}: ${name} (was ${old})`).toBe(Object.hasOwn(before, old));
        if (Object.hasOwn(dict, name)) reserved += 1;
      }
    }
    expect(reserved, "no dictionary carries a reserved name: the check is vacuous").toBeGreaterThanOrEqual(8);
  });

  it("a topology-only node named toString is not read as inventoried", () => {
    const fabric = compileFabric(renamed.snap, renamed.binding, { schemaAssumed: renamed.schemaAssumed });
    const node = fabric.devices.find((d) => d.host === "toString");
    expect(node, "the renamed topology-only node is missing").toBeDefined();
    expect(node?.inventoried).toBe(false);
    expect(node?.platform).toBeNull();
    expect(node?.cite).toBe("cable_map.nodes[host=toString]");
  });

  it("fabric.json is the original under the same rename", () => {
    const now = written(compileFabric(renamed.snap, renamed.binding, { schemaAssumed: renamed.schemaAssumed }), false);
    const was = written(compileFabric(original.snap, original.binding, { schemaAssumed: original.schemaAssumed }), true);
    expect(canonFabric(now)).toEqual(canonFabric(was));
  });

  it("acl-bindings.json is the original under the same rename", () => {
    expect(canonSidecar(written(compileAclBindings(renamed.snap, renamed.binding), false))).toEqual(
      canonSidecar(written(compileAclBindings(original.snap, original.binding), true)),
    );
  });

  it("rib-evidence.json is the original under the same rename", () => {
    expect(canonSidecar(written(compileRibEvidence(renamed.snap, renamed.binding), false))).toEqual(
      canonSidecar(written(compileRibEvidence(original.snap, original.binding), true)),
    );
  });

  it("producer-emission.json is the original under the same rename", () => {
    expect(canonSidecar(written(compileProducerEmission(renamed.snap, renamed.binding), false))).toEqual(
      canonSidecar(written(compileProducerEmission(original.snap, original.binding), true)),
    );
  });
});
