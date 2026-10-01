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
 * WHICH NAME EXERCISES WHICH SITE. Plain assignment `o[name] = v` misbehaves ONLY for "__proto__" (the one
 * Object.prototype member with a setter); every other reserved name, assigned, simply becomes an own member. So
 * each converted assignment site is caught only by a fixture that puts "__proto__" where THAT site writes it:
 *   - the host dictionaries (routes, acls, object groups, interfaces, ACL bindings, rib evidence) — an inventoried
 *     host present in the most name-keyed sections (fixture "hosts");
 *   - the inner ACL and object-group dictionaries — an ACL NAME and an object-group NAME (fixture "hosts");
 *   - producer-emission `deviceAbsent`, written only for a host with NO health_scores record — a topology-only
 *     node, which the sample never scores (fixture "unscored host"). The sample scores every inventoried host, so
 *     no single fixture can hold both "__proto__" roles.
 * `aclLineAbsent` is keyed by `acls.<host>.<name>[<i>]`, which can never equal "__proto__" (nor any
 * Object.prototype member name: none starts "acls."), so a plain object there is behaviourally identical on every
 * input; its Map is defence in depth. That premise — the key shape — is what is pinned for it below.
 * The read `devices[name]` misbehaves for any inherited name, and is exercised by a topology-only node named
 * "toString" (fixture "hosts") and one named "__proto__" (fixture "unscored host").
 *
 * THE FIXTURES are the tracked sample, renamed — never a hand-made shape. The renamed names are chosen by ROLE and
 * replaced wherever they occur as a whole token (review/rename-snapshot.mjs's rule). A renamed snapshot is the
 * same network under other names, so every compiled document must be the original one under the same rename —
 * except for what orders BY name (the device list and the coverage host lists, compared as sets here) and the
 * evidence projection's character budgets, which measure name lengths (its records are compared by pointer).
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

/* ── the roles, read from the sample ──────────────────────────────────────────────────────────── */
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
const topologyOnly = cableNodes
  .map((n: unknown) => (isObj(n) ? n.host : undefined))
  .filter((h): h is string => typeof h === "string" && !inventory.includes(h))
  .sort(byCodeUnit);
const TOPOLOGY_ONLY = topologyOnly[0] as string;
const scored = new Set(
  (Array.isArray(ORIGINAL.health_scores) ? ORIGINAL.health_scores : [])
    .map((h: unknown) => (isObj(h) ? h.switch : undefined))
    .filter((h): h is string => typeof h === "string"),
);
/** A host the snapshot never scores: the only kind producer-emission writes a `deviceAbsent` entry for. */
const UNSCORED = topologyOnly.find((h) => !scored.has(h)) as string;
/** The name-keyed inner dictionaries: host -> name -> record. */
const innerNames = (section: string): string[] => {
  const s = ORIGINAL[section];
  return isObj(s) ? Object.values(s).flatMap((named) => (isObj(named) ? Object.keys(named) : [])) : [];
};
const hostsDefining = (section: string, name: string): number => innerNames(section).filter((n) => n === name).length;
/** The ACL name defined on the most hosts (so the inner dictionary is exercised on more than one host). */
const ACL_NAME = [...new Set(innerNames("acls"))].sort((a, b) => hostsDefining("acls", b) - hostsDefining("acls", a) || byCodeUnit(a, b))[0] as string;
const GROUP_NAME = [...new Set(innerNames("object_groups"))].sort(byCodeUnit)[0] as string;

/* ── a fixture: the sample under one role-chosen rename ───────────────────────────────────────── */
interface Fixture {
  label: string;
  rename: Map<string, string>;
  /** Own reserved-name members the compiled dictionaries must hold between them (so the check is not vacuous). */
  minReserved: number;
}
const FIXTURES: Fixture[] = [
  {
    label: "hosts",
    rename: new Map([
      [RICHEST, "__proto__"],
      [NEXT, "constructor"],
      [TOPOLOGY_ONLY, "toString"],
      /* A different namespace from the hosts', so sharing the host's "__proto__" merges nothing. */
      [ACL_NAME, "__proto__"],
      [GROUP_NAME, "__proto__"],
    ]),
    minReserved: 12,
  },
  { label: "unscored host", rename: new Map([[UNSCORED, "__proto__"]]), minReserved: 1 },
];

function prepare(text: string, name: string): { snap: Record<string, unknown>; binding: ReturnType<typeof bindSource>; schemaAssumed: string | null } {
  const bytes = new TextEncoder().encode(text);
  const v = assertValidSnapshot(bytes);
  return { snap: v.snap, binding: bindSource(bytes, { source: name, sourceOrigin: "external-file" }), schemaAssumed: v.schemaAssumed };
}
const original = prepare(SOURCE_TEXT, "sample.snapshot.json");

/* ── comparing a document with the original under the rename ──────────────────────────────────── */
type Doc = Record<string, any>;
/** A `meta` without the source binding (the two snapshots are different bytes, so their digests differ). */
const unbound = (meta: Doc): Doc => Object.fromEntries(Object.entries(meta).filter(([k]) => !(BINDING_KEYS as readonly string[]).includes(k)));
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

for (const fx of FIXTURES) {
  /* A name is replaced where it stands as a whole token, longest name first (review/rename-snapshot.mjs). */
  const TOKEN = new RegExp(
    `(?<![A-Za-z0-9_])(?:${[...fx.rename.keys()].sort((a, b) => b.length - a.length || byCodeUnit(a, b)).map(escape).join("|")})(?![A-Za-z0-9_])`,
    "g",
  );
  const renameText = (text: string): string => text.replace(TOKEN, (m) => fx.rename.get(m) ?? m);
  const renamedTo = (k: string): string => fx.rename.get(k) ?? k;
  const RENAMED_TEXT = renameText(SOURCE_TEXT);
  const renamed = prepare(RENAMED_TEXT, "reserved-names.snapshot.json");
  /** The document as written, parsed; the ORIGINAL's written text first renamed exactly as the snapshot was. */
  const written = (doc: unknown, rename: boolean): Doc => JSON.parse(rename ? renameText(JSON.stringify(doc)) : JSON.stringify(doc)) as Doc;

  describe(`a snapshot name is data, whatever it spells — fixture "${fx.label}"`, () => {
    it("the fixture is the sample with its role-chosen names renamed to reserved names", () => {
      expect(inventory.length, "the sample has no device inventory").toBeGreaterThan(2);
      expect(reach(RICHEST), `${RICHEST} is in too few name-keyed sections to exercise them`).toBeGreaterThanOrEqual(4);
      expect(reach(NEXT), `${NEXT} is in too few name-keyed sections to exercise them`).toBeGreaterThanOrEqual(3);
      expect(TOPOLOGY_ONLY, "the sample has no topology-only node").toBeTypeOf("string");
      expect(UNSCORED, "the sample has no host without a health_scores record").toBeTypeOf("string");
      expect(ACL_NAME, "the sample defines no ACL").toBeTypeOf("string");
      expect(GROUP_NAME, "the sample defines no object group").toBeTypeOf("string");
      for (const name of new Set(fx.rename.values())) expect(SOURCE_TEXT.includes(name), `${name} already occurs in the sample`).toBe(false);
      for (const old of fx.rename.keys()) {
        expect(new RegExp(`(?<![A-Za-z0-9_])${escape(old)}(?![A-Za-z0-9_])`).test(RENAMED_TEXT), `${old} survives the rename`).toBe(false);
      }
      for (const name of fx.rename.values()) expect(RENAMED_TEXT.includes(`"${name}"`), `${name} is not in the renamed snapshot`).toBe(true);
      /* The parsed snapshot holds each reserved host name as an ORDINARY member (JSON.parse defines members). */
      for (const [old, name] of fx.rename) {
        if (inventory.includes(old)) expect(Object.hasOwn(renamed.snap.devices as object, name), name).toBe(true);
      }
    });

    it("the whole set compiles and serialises, and neither Object.prototype nor Object gains a property", () => {
      const protoBefore = Object.getOwnPropertyNames(Object.prototype).sort();
      const objectBefore = Object.getOwnPropertyNames(Object).sort();
      let set: CompiledSet | undefined;
      expect(() => {
        set = compileAll(renamed.snap, renamed.binding, { schemaAssumed: renamed.schemaAssumed });
      }).not.toThrow();
      const texts = serialiseCompiled(set as CompiledSet);
      expect(Object.values(texts).some((t) => t.includes('"__proto__":')), "no document writes a __proto__ member").toBe(true);
      expect(Object.getOwnPropertyNames(Object.prototype).sort()).toEqual(protoBefore);
      expect(Object.getOwnPropertyNames(Object).sort()).toEqual(objectBefore);
      expect(({} as Doc).protocols).toBeUndefined();
    });

    it("every name-keyed dictionary, outer and inner, keeps Object.prototype as its prototype and holds each renamed name as an own member", () => {
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
      /* The inner dictionaries: every host's ACLs and object groups, keyed by ACL / group NAME. */
      for (const [section, now, before] of [
        ["fabric.acls", set.fabric.acls, was.fabric.acls],
        ["fabric.objectGroups", set.fabric.objectGroups, was.fabric.objectGroups],
      ] as [string, Doc, Doc][]) {
        for (const host of Object.keys(before)) {
          const key = renamedTo(host);
          expect(Object.hasOwn(now, key), `${section}: ${key} (was ${host})`).toBe(true);
          dictionaries.push([`${section}.${key}`, now[key] as Doc, before[host] as Doc]);
        }
      }
      let reserved = 0;
      for (const [label, dict, before] of dictionaries) {
        expect(Object.getPrototypeOf(dict), `${label}'s prototype was replaced`).toBe(Object.prototype);
        expect(Object.keys(dict).sort(byCodeUnit), `${label}'s members are not the original's under the rename`).toEqual(
          Object.keys(before).map(renamedTo).sort(byCodeUnit),
        );
        for (const [old, name] of fx.rename) {
          if (Object.hasOwn(before, old)) {
            expect(Object.hasOwn(dict, name), `${label}: ${name} (was ${old})`).toBe(true);
            reserved += 1;
          }
        }
      }
      expect(reserved, "too few dictionaries carry a reserved name: the check is (nearly) vacuous").toBeGreaterThanOrEqual(fx.minReserved);
    });

    it("a renamed topology-only node is not read as inventoried", () => {
      const fabric = compileFabric(renamed.snap, renamed.binding, { schemaAssumed: renamed.schemaAssumed });
      const nodes = [...fx.rename].filter(([old]) => topologyOnly.includes(old));
      expect(nodes.length, "this fixture renames no topology-only node").toBeGreaterThan(0);
      for (const [, name] of nodes) {
        const node = fabric.devices.find((d) => d.host === name);
        expect(node, `the renamed topology-only node ${name} is missing`).toBeDefined();
        expect(node?.inventoried).toBe(false);
        expect(node?.platform).toBeNull();
        expect(node?.cite).toBe(`cable_map.nodes[host=${name}]`);
      }
    });

    it("aclLineAbsent's keys are all `acls.<host>.<name>[<i>]` — the shape that keeps a plain object there safe", () => {
      const keys = Object.keys(compileProducerEmission(renamed.snap, renamed.binding).aclLineAbsent);
      expect(keys.length).toBeGreaterThan(0);
      for (const k of keys) expect(k).toMatch(/^acls\..+\[\d+\]$/);
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
}
