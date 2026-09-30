/**
 * dataset.reserved-names.test.tsx — a host the snapshot names "toString", "constructor" or "__proto__" is read
 * like any other host, by every consumer of the compiled documents, END TO END.
 *
 * WHY (2026-09-30 refuter, after c199e0f9 made the COMPILER safe for such names). The compiled documents are
 * plain objects keyed by names the snapshot supplies, and the application indexed them with `dict[name]`: a name
 * the dictionary does not hold answered from the prototype chain. On a dataset whose hosts were named so,
 * `producerFieldNotEmitted` threw (`(deviceAbsent[host] ?? []).includes is not a function`), `routesOf` handed
 * back a function and `ribIncompleteness` threw, the coverage bar counted a host with no interface table as
 * collected, and the device pane showed "0" ACL lines for a host whose ACLs were never collected — absence
 * rendered as presence. The one owner of such reads is `src/core/own.ts`; `own-read.guard.test.ts` keeps it so.
 *
 * THE FIXTURE is the tracked sample, renamed (never a hand-made shape): three of its own hosts, chosen by ROLE so
 * that each reserved name is looked up where a dictionary holds NO entry for it — the path that reads an
 * inherited member:
 *   - the first two inventoried hosts with an interface table, a scored health record (so producer-emission
 *     has no `deviceAbsent` entry for them) and no routes, ACLs or object groups -> "toString", "__proto__";
 *   - the LAST topology-only node by code unit (no interfaces, no routing evidence, no health record) ->
 *     "constructor", which then keeps its place in every list of uncollected hosts sorted by name.
 * The ORIGINAL sample and the renamed one are each compiled with the one compiler and installed as an opened
 * file in a module graph of their own (the way `dataset.example-query.test.ts` installs one). The renamed
 * fleet is the same network under other names, so every consumer must answer for a renamed host exactly what
 * it answers for the original host — renamed.
 */
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readFileSync } from "node:fs";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { CompiledDataset } from "./dataset/types";
import { asOpenedFile, compileBytes, SAMPLE_SNAPSHOT } from "../test-support/dataset/testing";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const byCodeUnit = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
const escape = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/* ── the roles, read from the sample ──────────────────────────────────────────────────────────── */
const SOURCE_TEXT = readFileSync(SAMPLE_SNAPSHOT, "utf8");
const ORIGINAL = JSON.parse(SOURCE_TEXT) as Record<string, unknown>;
const inSection = (section: string, host: string): boolean => {
  const s = ORIGINAL[section];
  return isObj(s) && Object.hasOwn(s, host);
};
const inventory = isObj(ORIGINAL.devices) ? Object.keys(ORIGINAL.devices) : [];
const scoredWithDeductions = new Set(
  (Array.isArray(ORIGINAL.health_scores) ? ORIGINAL.health_scores : [])
    .filter((h: unknown) => isObj(h) && Object.hasOwn(h, "deductions"))
    .map((h: unknown) => (h as { switch: unknown }).switch)
    .filter((h): h is string => typeof h === "string"),
);
const [PLAIN_A, PLAIN_B] = inventory
  .filter(
    (h) =>
      inSection("interfaces", h) &&
      !inSection("routes", h) &&
      !inSection("acls", h) &&
      !inSection("object_groups", h) &&
      scoredWithDeductions.has(h),
  )
  .sort(byCodeUnit) as [string, string];
const cableNodes = isObj(ORIGINAL.cable_map) && Array.isArray(ORIGINAL.cable_map.nodes) ? ORIGINAL.cable_map.nodes : [];
const TOPOLOGY_ONLY = cableNodes
  .map((n: unknown) => (isObj(n) ? n.host : undefined))
  .filter((h): h is string => typeof h === "string" && !inventory.includes(h))
  .sort(byCodeUnit)
  .at(-1) as string;

const RENAME = new Map<string, string>([
  [PLAIN_A, "toString"],
  [PLAIN_B, "__proto__"],
  [TOPOLOGY_ONLY, "constructor"],
]);
const HOSTS = [...RENAME]; // [original, renamed]
const TOKEN = new RegExp(
  `(?<![A-Za-z0-9_])(?:${[...RENAME.keys()].sort((a, b) => b.length - a.length || byCodeUnit(a, b)).map(escape).join("|")})(?![A-Za-z0-9_])`,
  "g",
);
const renameText = (text: string): string => text.replace(TOKEN, (m) => RENAME.get(m) ?? m);
/** Names a lookup keyed by a snapshot name can be handed that no dictionary here holds. */
const RESERVED = ["toString", "constructor", "__proto__", "valueOf", "hasOwnProperty"];

/* ── an answer, made comparable ───────────────────────────────────────────────────────────────── */
/** What a consumer returned, or the error it threw; a function or Object.prototype is named, never serialised away. */
function answer(fn: () => unknown): string {
  let v: unknown;
  try {
    v = fn();
  } catch (e) {
    return `THREW ${e instanceof Error ? e.message : String(e)}`;
  }
  return JSON.stringify(v, (_k, x: unknown) =>
    typeof x === "function" ? `<a function: ${(x as { name?: string }).name ?? ""}>` : x === Object.prototype ? "<Object.prototype>" : x,
  ) ?? "undefined";
}
/**
 * The original's text as the renamed dataset must show it: renamed, and with the source digests the original's
 * bytes have replaced by the renamed bytes' (a digest a pane prints is the only thing the rename may change
 * besides the names).
 */
function asRenamed(text: string): string {
  const pairs = (["sourceSha256", "sourceGitBlob"] as const).map((k) => [O.data.fabric.meta[k], R.data.fabric.meta[k]] as const);
  return renameText(text).replace(/[0-9a-f]{7,}/g, (hex) => {
    const pair = pairs.find(([was]) => was.startsWith(hex));
    return pair === undefined ? hex : pair[1].slice(0, hex.length);
  });
}
/** The original graph's answer for the original host, written as the renamed graph must answer it. */
const renamedAnswer = (fn: () => unknown): string => asRenamed(answer(fn));

/* ── two module graphs: the original sample, and the renamed one ──────────────────────────────── */
async function loadGraph(set: CompiledDataset) {
  vi.resetModules();
  (await import("./dataset/slot")).installDataset(asOpenedFile(set, "snapshot.json"));
  return {
    data: await import("./data"),
    emission: await import("../panels/producer-emission"),
    rib: await import("../forwarding/rib-completeness"),
    engine: await import("../forwarding/engine"),
    coverage: await import("../app/CoverageBar"),
    store: await import("./store"),
    devicePane: await import("../panels/DevicePane"),
    evidencePane: await import("../panels/EvidencePane"),
  };
}
type Graph = Awaited<ReturnType<typeof loadGraph>>;
let O: Graph;
let R: Graph;
let renamedSet: CompiledDataset;

beforeAll(async () => {
  const originalSet = compileBytes(new TextEncoder().encode(SOURCE_TEXT), "snapshot.json");
  renamedSet = compileBytes(new TextEncoder().encode(renameText(SOURCE_TEXT)), "snapshot.json");
  O = await loadGraph(originalSet);
  R = await loadGraph(renamedSet);
}, 120_000);
afterAll(() => {
  vi.resetModules();
});

/* ── rendering a pane in one graph ────────────────────────────────────────────────────────────── */
/**
 * Every text node, one per line, so a host name is always a whole token (textContent glues words together).
 * The <wbr> break opportunities an identifier gets after each separator (ui/primitives.tsx) are dropped and
 * the text they split rejoined first: they split "__proto__" where they never split "access10".
 */
function textOf(live: Element): string {
  const el = live.cloneNode(true) as Element;
  for (const w of [...el.querySelectorAll("wbr")]) w.remove();
  el.normalize();
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const out: string[] = [];
  for (let n = walker.nextNode(); n !== null; n = walker.nextNode()) {
    const t = (n.textContent ?? "").trim();
    if (t !== "") out.push(t);
  }
  return out.join("\n");
}
function renderText(g: Graph, select: () => void, element: () => ReturnType<typeof createElement>): string {
  let root: Root | undefined;
  const container = document.createElement("div");
  document.body.appendChild(container);
  try {
    act(() => {
      g.store.useInvestigation.getState().reset();
      select();
    });
    root = createRoot(container);
    const r = root;
    act(() => {
      r.render(element());
    });
    return textOf(container);
  } catch (e) {
    return `THREW ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    const r = root;
    if (r !== undefined) {
      act(() => {
        r.unmount();
      });
    }
    container.remove();
  }
}
const deviceOf = (g: Graph, host: string) => g.data.fabric.devices.find((d) => d.host === host);

describe("the fixture: the sample with three of its own hosts renamed to reserved names", () => {
  it("chooses its hosts by role, and each reserved name is a host the renamed dataset holds", () => {
    expect(PLAIN_A, "the sample has no plain access host").toBeTypeOf("string");
    expect(PLAIN_B, "the sample has no second plain access host").toBeTypeOf("string");
    expect(TOPOLOGY_ONLY, "the sample has no topology-only node").toBeTypeOf("string");
    for (const name of RENAME.values()) expect(SOURCE_TEXT.includes(`"${name}"`), `${name} already occurs in the sample`).toBe(false);
    expect(R.data.fabric.meta.source).toBe("snapshot.json");
    for (const [old, name] of HOSTS) {
      expect(deviceOf(O, old), old).toBeDefined();
      expect(deviceOf(R, name), name).toBeDefined();
    }
    /* The absent path is the one exercised: no routes, ACLs or object groups for any of them; no interface table,
       routing evidence or health record for the topology-only node; no deviceAbsent entry for the scored ones. */
    for (const [, name] of HOSTS) {
      expect(Object.hasOwn(renamedSet.fabric.routes, name), name).toBe(false);
      expect(Object.hasOwn(renamedSet.fabric.acls, name), name).toBe(false);
      expect(Object.hasOwn(renamedSet.fabric.objectGroups, name), name).toBe(false);
    }
    expect(Object.hasOwn(renamedSet.fabric.interfaces, "constructor")).toBe(false);
    expect(Object.hasOwn(renamedSet.ribEvidence.hosts, "constructor")).toBe(false);
    expect(Object.hasOwn(renamedSet.producerEmission.deviceAbsent, "toString")).toBe(false);
    expect(Object.hasOwn(renamedSet.producerEmission.deviceAbsent, "__proto__")).toBe(false);
  });
});

describe("every consumer answers for a renamed host what it answers for the original host", () => {
  for (const [old, name] of [...RENAME]) {
    describe(`${name} (was ${old})`, () => {
      it("producer-emission: whether the health record's deductions were emitted", () => {
        expect(answer(() => R.emission.producerFieldNotEmitted(null, deviceOf(R, name), "deductions"))).toBe(
          renamedAnswer(() => O.emission.producerFieldNotEmitted(null, deviceOf(O, old), "deductions")),
        );
      });

      it("core/data: routesOf, interfacesOf, aclsOf, hasRib", () => {
        for (const [label, of] of [
          ["routesOf", (g: Graph, h: string) => g.data.routesOf(h)],
          ["interfacesOf", (g: Graph, h: string) => g.data.interfacesOf(h)],
          ["aclsOf", (g: Graph, h: string) => g.data.aclsOf(h)],
          ["hasRib", (g: Graph, h: string) => g.data.hasRib(h)],
        ] as const) {
          expect(answer(() => of(R, name)), label).toBe(renamedAnswer(() => of(O, old)));
        }
      });

      it("forwarding/rib-completeness: ribIncompleteness, ribCompletenessBasis, ribIncompletenessSentence", () => {
        expect(answer(() => R.rib.ribIncompleteness(name))).toBe(renamedAnswer(() => O.rib.ribIncompleteness(old)));
        expect(answer(() => R.rib.ribCompletenessBasis(name))).toBe(renamedAnswer(() => O.rib.ribCompletenessBasis(old)));
        expect(answer(() => R.rib.ribIncompletenessSentence(name))).toBe(renamedAnswer(() => O.rib.ribIncompletenessSentence(old)));
      });

      for (const tab of ["summary", "ports", "routing", "acl", "findings", "raw"] as const) {
        it(`panels/DevicePane renders its ${tab} tab as it renders the original's`, () => {
          const shown = (g: Graph, host: string): string =>
            renderText(
              g,
              () => {
                g.store.useInvestigation.getState().selectDevice(host);
                g.store.useInvestigation.getState().setEvidenceTab(tab);
              },
              () => createElement(g.devicePane.DevicePane, {}),
            );
          const now = shown(R, name);
          expect(now).not.toMatch(/^THREW /);
          expect(now).toBe(asRenamed(shown(O, old)));
        });
      }
    });
  }

  it("app/CoverageBar: every row's observed count and denominator", () => {
    expect(answer(() => R.coverage.coverageRows())).toBe(renamedAnswer(() => O.coverage.coverageRows()));
  });

  for (const [old, name] of [...RENAME].filter(([o]) => o !== TOPOLOGY_ONLY)) {
    it(`panels/EvidencePane renders the first finding naming ${name} (was ${old}) as it renders the original's`, () => {
      const finding = O.data.fabric.findings.filter((f) => f.devices.includes(old)).sort((a, b) => byCodeUnit(a.id, b.id))[0];
      expect(finding, `no finding names ${old}`).toBeDefined();
      const id = finding?.id ?? "";
      const shown = (g: Graph): string =>
        renderText(
          g,
          () => {
            g.store.useInvestigation.getState().selectFinding(id);
          },
          () => createElement(g.evidencePane.EvidencePane, { onOpenCite: () => {}, onShowConfig: () => {} }),
        );
      const now = shown(R);
      expect(now).not.toMatch(/^THREW /);
      expect(now).toBe(asRenamed(shown(O)));
      const f = R.data.findingById.get(id);
      expect(answer(() => (f ? R.evidencePane.configEvidenceFor(f) : null))).toBe(
        renamedAnswer(() => O.evidencePane.configEvidenceFor(O.data.findingById.get(id)!)),
      );
      expect(answer(() => (f ? R.evidencePane.nearestConfigFor(f) : null))).toBe(
        renamedAnswer(() => O.evidencePane.nearestConfigFor(O.data.findingById.get(id)!)),
      );
    });
  }
});

describe("a name a dictionary does not hold reads as absent, never as an inherited member", () => {
  it("forwarding/engine resolveObjectGroup: a group only when the host's own table defines that name", () => {
    const groups = renamedSet.fabric.objectGroups;
    const groupNames = [...new Set(Object.values(groups).flatMap((g) => Object.keys(g)))];
    expect(groupNames.length, "the sample defines no object group").toBeGreaterThan(0);
    const hosts = [...new Set([...R.data.fabric.devices.map((d) => d.host), ...Object.keys(groups)])];
    const wrong: string[] = [];
    for (const host of hosts) {
      for (const group of [...groupNames, ...RESERVED]) {
        const table = Object.hasOwn(groups, host) ? groups[host] : undefined;
        const expected = table !== undefined && Object.hasOwn(table, group) ? table[group] : null;
        const got = answer(() => R.engine.resolveObjectGroup(host, group));
        if (got !== answer(() => expected)) wrong.push(`${host} / ${group}: ${got}`);
      }
    }
    expect(wrong).toEqual([]);
  });

  it("core/data severityRank: a severity no rank is defined for sorts after every known one", () => {
    for (const s of RESERVED) expect(answer(() => R.data.severityRank(s)), s).toBe("98");
  });

  it("core/data resolveCite: a path through a name no dictionary holds does not resolve", () => {
    for (const s of RESERVED) {
      expect(answer(() => R.data.resolveCite(`routes.${s}`)), `routes.${s}`).toBe("undefined");
      expect(answer(() => R.data.resolveCite(`acls.${s}`)), `acls.${s}`).toBe("undefined");
    }
  });
});
