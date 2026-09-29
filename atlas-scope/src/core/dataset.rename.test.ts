// @vitest-environment node
/**
 * dataset.rename.test.ts — review/rename-snapshot.mjs writes a DETERMINISTIC, ISOMORPHIC rename of the
 * sample, which is what makes the rename leg (`ATLAS_DATASET_DIR=<its compile> npx vitest run`) a test of
 * the suite rather than of the rename:
 *
 *   - the same input gives the same bytes;
 *   - it is one-to-one and complete: every host the snapshot names is renamed, no old host name survives
 *     as a token anywhere, and the reverse mapping restores the original exactly;
 *   - compiled with the one compiler, the renamed fleet is the SAME network: the same numbers of devices,
 *     links and findings, and every compiled record maps back to one of the original's.
 *   - its new names sort in the reverse order of the old ones (so an order assumption is exposed too).
 *
 * The harness is imported through a runtime specifier: review/*.mjs is outside the type-checked programs
 * (tsconfig.scripts.json says why), and its module shape is declared here instead.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";
import type { Fabric } from "./types";
import { compileBytes, PKG, SAMPLE_SNAPSHOT } from "./dataset/testing";

interface RenameModule {
  hostsOf(snap: Record<string, unknown>): string[];
  renameSnapshot(snap: Record<string, unknown>): { snapshot: Record<string, unknown>; mapping: Record<string, string> };
  serialiseRenamed(snap: Record<string, unknown>): string;
}

let mod: RenameModule;
const original = JSON.parse(readFileSync(SAMPLE_SNAPSHOT, "utf8")) as Record<string, unknown>;
beforeAll(async () => {
  const spec = pathToFileURL(resolve(PKG, "review", "rename-snapshot.mjs")).href;
  mod = (await import(/* @vite-ignore */ spec)) as RenameModule;
});

const escape = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const tokenRe = (names: string[]): RegExp =>
  new RegExp(`(?<![A-Za-z0-9_])(?:${[...names].sort((a, b) => b.length - a.length).map(escape).join("|")})(?![A-Za-z0-9_])`, "g");

describe("the rename is deterministic and one-to-one", () => {
  it("the same input gives the same bytes", () => {
    const a = mod.serialiseRenamed(mod.renameSnapshot(original).snapshot);
    const b = mod.serialiseRenamed(mod.renameSnapshot(structuredClone(original)).snapshot);
    expect(a).toBe(b);
    expect(a.endsWith("}\n")).toBe(true);
  });

  it("renames every host the snapshot names, leaves none behind, and reverses exactly", () => {
    const { snapshot, mapping } = mod.renameSnapshot(original);
    const hosts = mod.hostsOf(original);
    expect(hosts.length).toBeGreaterThan(10);
    expect(Object.keys(mapping).sort()).toEqual([...hosts].sort());
    expect(new Set(Object.values(mapping)).size, "one-to-one").toBe(hosts.length);
    const renamedText = JSON.stringify(snapshot);
    expect(renamedText.match(tokenRe(hosts)) ?? [], "no original host name survives as a token").toEqual([]);
    const inverse = Object.fromEntries(Object.entries(mapping).map(([k, v]) => [v, k]));
    const restored = renamedText.replace(tokenRe(Object.keys(inverse)), (m) => inverse[m] ?? m);
    expect(restored).toBe(JSON.stringify(original));
  });

  it("the new names sort in the reverse order of the old ones", () => {
    const { mapping } = mod.renameSnapshot(original);
    const old = Object.keys(mapping).sort();
    const renamed = old.map((h) => mapping[h]!);
    expect(renamed).toEqual([...renamed].sort().reverse());
  });

  it("refuses a rename onto a name the snapshot already uses", () => {
    const hosts = mod.hostsOf(original);
    const clash = structuredClone(original);
    (clash as { note?: string }).note = `see rn-${String(hosts.length).padStart(String(hosts.length).length, "0")}`;
    expect(() => mod.renameSnapshot(clash)).toThrow(/already occurs/);
  });
});

describe("compiled, the renamed fleet is the same network", () => {
  let before: Fabric;
  let after: Fabric;
  let mapping: Record<string, string>;
  beforeAll(() => {
    const r = mod.renameSnapshot(original);
    mapping = r.mapping;
    before = compileBytes(new Uint8Array(readFileSync(SAMPLE_SNAPSHOT)), "sample_fleet.snapshot.json").fabric;
    after = compileBytes(new TextEncoder().encode(mod.serialiseRenamed(r.snapshot)), "sample_fleet.renamed.snapshot.json").fabric;
  });

  it("has the same numbers of devices, links, findings and cross-layer records", () => {
    expect([after.devices.length, after.links.length, after.findings.length, after.crossLayer.length]).toEqual([
      before.devices.length,
      before.links.length,
      before.findings.length,
      before.crossLayer.length,
    ]);
    expect(after.devices.length).toBeGreaterThan(0);
  });

  it("every compiled device, link and finding is an original one under the new names", () => {
    const rename = (v: unknown): string => JSON.stringify(v).replace(tokenRe(Object.keys(mapping)), (m) => mapping[m] ?? m);
    const canon = (xs: readonly unknown[]): string[] => xs.map((x) => JSON.stringify(x)).sort();
    for (const k of ["devices", "links", "findings", "crossLayer"] as const) {
      expect(canon(after[k]), k).toEqual(before[k].map((x) => rename(x)).sort());
    }
  });
});
