/**
 * collection-coverage.b7.test.tsx — the collected-host figure follows the ENGINE's collection authority (acceptance B7).
 *
 * WHAT WAS WRONG (2026-10 re-grade refuter, B7 overturned). The compiler set `collected: d ? true : …`, so every host
 * with a `devices` record counted as collected — and the engine writes that record for every INVENTORIED host,
 * including one whose capture folder is empty. The engine's own authority is `collection_completeness`
 * (cisco_toolkit/analyze.py `compute_collection_completeness`: complete / partial / not collected), whose
 * `summary.complete` is the canonical `n_collected` (cisco_toolkit/ssot.py CANONICAL_FACTS). With an empty-capture host
 * and a show-version-only host the status bar read "25/28 collected", its tooltip "25 of 28 devices answered the
 * collector", and the coverage disclosure listed the dead host under "Collector reached the device", where the engine
 * says 23 complete, 1 partial, 1 not collected. Absence rendered as health.
 *
 * THE FIXTURE IS THE ENGINE'S. tools/fixtures/engine-collection-completeness.json is produced by the real pipeline
 * (webapp/sample_data/build_sample.py, run with its own argv over the sample collection plus `deadsw`, an empty
 * capture folder, and `partsw`, show version only; see the generator's docstring). This file patches those rows,
 * verbatim, into the tracked sample and compiles it with the one compiler, so every other record is the real sample.
 * Each variant is installed as an opened file in a module graph of its own — the in-app upload path.
 *
 * THE RULES PINNED HERE. The headline figure equals the engine's canonical complete count; a partial host is
 * disclosed as partial (answered, incomplete) and never folded into the complete count; a not-collected host is never
 * shown as having answered; and a snapshot that carries no usable `collection_completeness` states that the basis is
 * not stated instead of counting device records as collection.
 */
import { act, createElement, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { CompiledDataset } from "../core/dataset/types";
import { validateSnapshot } from "../../tools/lib/validate-snapshot.mjs";
import { asOpenedFile, compileBytes, PKG, SAMPLE_SNAPSHOT } from "../test-support/dataset/testing";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type Obj = Record<string, unknown>;

interface EngineFixture {
  added: Record<string, string>;
  collection_completeness: { summary: { inventory: number; complete: number; partial: number; not_collected: number }; devices: Obj[] };
  n_collected: number;
  devices: Record<string, Obj>;
  cable_map_nodes: Obj[];
  health_scores: Obj[];
}
const FIXTURE = JSON.parse(readFileSync(resolve(PKG, "tools", "fixtures", "engine-collection-completeness.json"), "utf8")) as EngineFixture;
const SUMMARY = FIXTURE.collection_completeness.summary;
const blindSpot = (status: string): string[] =>
  FIXTURE.collection_completeness.devices.filter((d) => d.status === status).map((d) => String(d.host));
const PARTIAL = blindSpot("partial");
const NOT_COLLECTED = blindSpot("not collected");
const missingOf = (host: string): string[] =>
  (FIXTURE.collection_completeness.devices.find((d) => d.host === host)?.missing as string[] | undefined) ?? [];

const SOURCE_TEXT = readFileSync(SAMPLE_SNAPSHOT, "utf8");
const parse = (): Obj => JSON.parse(SOURCE_TEXT) as Obj;

type Variant = "engine" | "absent" | "malformed";
const VARIANTS: readonly Variant[] = ["engine", "absent", "malformed"];

/** The tracked sample with the engine's rows for the two added hosts patched in, verbatim. */
function variantSnapshot(variant: Variant): Obj {
  const snap = parse();
  const devices = snap.devices as Obj;
  for (const [h, rec] of Object.entries(FIXTURE.devices)) devices[h] = structuredClone(rec);
  (((snap.cable_map as Obj).nodes) as Obj[]).push(...structuredClone(FIXTURE.cable_map_nodes));
  (snap.health_scores as Obj[]).push(...structuredClone(FIXTURE.health_scores));
  if (variant === "engine") snap.collection_completeness = structuredClone(FIXTURE.collection_completeness);
  else if (variant === "absent") delete snap.collection_completeness;
  else snap.collection_completeness = { summary: "23 complete", devices: {} };
  return snap;
}
const bytesOf = (snap: Obj): Uint8Array => new TextEncoder().encode(JSON.stringify(snap, null, 2));

async function loadGraph(set: CompiledDataset) {
  vi.resetModules();
  (await import("../core/dataset/slot")).installDataset(asOpenedFile(set, "snapshot.json"));
  return {
    set,
    data: await import("../core/data"),
    store: await import("../core/store"),
    claims: await import("../core/claims"),
    statusBar: await import("./StatusBar"),
    coverage: await import("./CoverageBar"),
    primitives: await import("../ui/primitives"),
    devicePane: await import("../panels/DevicePane"),
  };
}
type Graph = Awaited<ReturnType<typeof loadGraph>>;
const graphs = new Map<Variant, Graph>();
const G = (v: Variant): Graph => graphs.get(v)!;

beforeAll(async () => {
  for (const v of VARIANTS) graphs.set(v, await loadGraph(compileBytes(bytesOf(variantSnapshot(v)), "snapshot.json")));
}, 300_000);
afterAll(() => {
  vi.resetModules();
});

function render<R>(g: Graph, select: () => void, element: () => ReactElement, read: (c: HTMLElement) => R): R {
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
    return read(container);
  } finally {
    const r = root;
    if (r !== undefined) act(() => r.unmount());
    container.remove();
  }
}

/** The status bar's collected control: its text and its tooltip, and the disclosure it opens (portalled to body). */
function statusBar(g: Graph): { bar: string; figure: string; tooltip: string; disclosure: string; states: Record<string, string> } {
  return render(
    g,
    () => undefined,
    () => createElement(g.statusBar.StatusBar, {}),
    (c) => {
      const group = c.querySelector('[aria-label="Collection coverage"]');
      const button = group?.querySelector("button.sb__cov") as HTMLButtonElement | null;
      const figure = button?.textContent ?? "";
      const tooltip = button?.title ?? "";
      act(() => button?.click());
      const panel = document.body.querySelector('[role="dialog"][aria-label="Collection coverage"]');
      const disclosure = panel?.textContent ?? "";
      const states = Object.fromEntries(
        [...(panel?.querySelectorAll("[data-collection]") ?? [])].map((e) => [e.getAttribute("data-collection") ?? "", e.textContent ?? ""]),
      );
      act(() => button?.click());
      return { bar: c.textContent ?? "", figure, tooltip, disclosure, states };
    },
  );
}

const total = (g: Graph): number => g.data.fabric.devices.length;
const inventoried = (g: Graph): string[] => g.data.fabric.devices.filter((d) => d.inventoried).map((d) => d.host);

describe("the fixture is the engine's own answer", () => {
  it("the engine reported one partial and one not-collected host, and its canonical n_collected is summary.complete", () => {
    expect(Object.keys(FIXTURE.added).sort()).toEqual(["deadsw", "partsw"]);
    expect(SUMMARY.partial).toBe(1);
    expect(SUMMARY.not_collected).toBe(1);
    expect(FIXTURE.n_collected).toBe(SUMMARY.complete);
    expect(NOT_COLLECTED).toEqual(["deadsw"]);
    expect(PARTIAL).toEqual(["partsw"]);
    // The engine wrote a device record for BOTH, which is exactly why record presence is not collection.
    expect(Object.keys(FIXTURE.devices).sort()).toEqual(["deadsw", "partsw"]);
  });
  it("the tracked sample alone has no partial and no not-collected host, so only the fixture exercises those paths", () => {
    const cc = parse().collection_completeness as { summary: Obj; devices: unknown[] };
    expect(cc.summary.partial).toBe(0);
    expect(cc.summary.not_collected).toBe(0);
    expect(cc.devices).toEqual([]);
  });
});

describe("the compiled hosts carry the engine's collection state (the in-app compile path)", () => {
  it("every inventoried host is complete, partial or not collected exactly as the engine says; topology-only hosts are none of them", () => {
    const g = G("engine");
    const by = new Map(g.data.fabric.devices.map((d) => [d.host, d]));
    expect(by.get("deadsw")?.collection).toBe("not collected");
    expect(by.get("deadsw")?.collected, "a host the engine says was not collected never counts as having answered").toBe(false);
    expect(by.get("partsw")?.collection).toBe("partial");
    expect(by.get("partsw")?.collected, "a partial host answered the collector").toBe(true);
    const complete = g.data.fabric.devices.filter((d) => d.collection === "complete").map((d) => d.host);
    expect(complete.length).toBe(SUMMARY.complete);
    expect(complete.length).toBe(FIXTURE.n_collected);
    for (const d of g.data.fabric.devices) {
      if (!d.inventoried) expect(d.collection, d.host).toBe("topology only");
      if (d.collection === "complete") expect(d.collected, d.host).toBe(true);
    }
    expect(inventoried(g).length).toBe(SUMMARY.inventory);
  });
  it("each state cites the record it was read from, and the citation resolves inside the model", () => {
    const g = G("engine");
    const dead = g.data.fabric.devices.find((d) => d.host === "deadsw")!;
    expect(dead.fieldCites.collection).toBe("collection_completeness.devices[host=deadsw]");
    expect(g.data.resolveCite(dead.fieldCites.collection!)).toMatchObject({ host: "deadsw", status: "not collected" });
    const complete = g.data.fabric.devices.find((d) => d.collection === "complete")!;
    expect(g.data.resolveCite(complete.fieldCites.collection!)).toMatchObject({ complete: SUMMARY.complete });
  });
});

describe("the permanent line and its disclosure state the engine's count", () => {
  it("the status bar's collected figure is the canonical complete count, qualified by the partial and not-collected hosts", () => {
    const g = G("engine");
    const s = statusBar(g);
    expect(s.figure).toContain(`${SUMMARY.complete}/${total(g)} collected`);
    expect(s.figure).toContain(`${SUMMARY.partial} partial`);
    expect(s.figure).toContain(`${SUMMARY.not_collected} not collected`);
    // the refuter's reading: record presence counted both added hosts
    expect(s.bar).not.toContain(`${SUMMARY.complete + 2}/${total(g)} collected`);
  });
  it("the tooltip names the partial host as answered but incomplete, and the not-collected host as never answering", () => {
    const g = G("engine");
    const { tooltip } = statusBar(g);
    expect(tooltip).toContain(`${SUMMARY.complete} of ${total(g)} devices`);
    expect(tooltip).not.toContain(`${SUMMARY.complete + 2} of ${total(g)} devices answered`);
    expect(tooltip).toMatch(/partsw[^.]*partial|partial[^.]*partsw/);
    for (const m of missingOf("partsw")) expect(tooltip).toContain(m);
    expect(tooltip).toMatch(/deadsw[^.]*not collected|not collected[^.]*deadsw/);
    expect(tooltip).toContain("collection-completeness report");
  });
  it("the coverage disclosure counts only complete hosts as observed, and discloses the partial and the dead host by name", () => {
    const g = G("engine");
    const rows = g.coverage.coverageRows();
    const first = rows[0]!;
    expect(first.observed).toBe(SUMMARY.complete);
    expect(first.stated).toBe(SUMMARY.complete);
    expect(first.statedField).toBe("collection_completeness.summary.complete");
    expect(first.observed + first.absent + first.notApplicable).toBe(first.total);
    const { disclosure, states } = statusBar(g);
    expect(states.partial).toContain("partsw");
    expect(states.partial).toContain("answered the collector, but incompletely");
    for (const m of missingOf("partsw")) expect(states.partial).toContain(m);
    expect(states["not collected"]).toContain("deadsw");
    expect(states["not collected"]).not.toContain("answered");
    expect(states.complete).toContain(`${SUMMARY.complete} complete`);
    for (const host of [...PARTIAL, ...NOT_COLLECTED]) expect(states.complete ?? "").not.toContain(host);
    expect(disclosure).not.toContain("DISAGREEMENT");
    expect(disclosure).not.toContain("Collector reached the device");
  });
  it("the overlay coverage statement (the owner's T8 line) carries the same figure", () => {
    const g = G("engine");
    expect(g.claims.T8_coverageLine()).toContain(`${SUMMARY.complete}/${total(g)} collected`);
    expect(g.primitives.coverageFigures().join(" · ")).toContain(`${SUMMARY.complete}/${total(g)} collected`);
  });
  it("the device pane says the dead host returned nothing usable, and the partial host what it is missing", () => {
    const g = G("engine");
    const pane = (host: string): string =>
      render(
        g,
        () => g.store.useInvestigation.getState().selectDevice(host),
        () => createElement(g.devicePane.DevicePane, {}),
        (c) => c.textContent ?? "",
      );
    const dead = pane("deadsw");
    expect(dead).not.toContain("present only because a neighbour");
    expect(dead).toContain("not collected");
    const part = pane("partsw");
    expect(part).toContain("partial");
    for (const m of missingOf("partsw")) expect(part).toContain(m);
  });
});

describe("a snapshot that does not report collection completeness says so, never counting records as collection", () => {
  for (const v of ["absent", "malformed"] as const) {
    it(`${v}: every inventoried host's collection is not stated, and the bar states no collected count`, () => {
      const g = G(v);
      for (const d of g.data.fabric.devices) expect(d.collection, d.host).toBe(d.inventoried ? "not stated" : "topology only");
      const s = statusBar(g);
      expect(s.figure).toContain("collection not stated");
      expect(s.figure).not.toMatch(/\d+\/\d+ collected/);
      expect(s.tooltip).toContain("collection-completeness report");
      expect(g.claims.T8_coverageLine()).not.toMatch(/\d+\/\d+ collected/);
      const first = g.coverage.coverageRows()[0]!;
      expect(first.observed, "no device is counted as completely collected on a basis the snapshot does not state").toBe(0);
    });
    it(`${v}: the validator warns that the section is not usable`, () => {
      const r = validateSnapshot(bytesOf(variantSnapshot(v)));
      expect(r.ok).toBe(true);
      expect(r.warnings.some((w) => w.path === "/collection_completeness")).toBe(true);
    });
  }
});

describe("the block is read whole or not at all (tools/lib/compile-model.mjs readCollectionCompleteness)", () => {
  const cc = (): Obj => structuredClone(FIXTURE.collection_completeness) as unknown as Obj;
  const UNUSABLE: [string, () => unknown][] = [
    ["a list", () => []],
    ["a summary missing a count", () => ({ ...cc(), summary: { inventory: 25, complete: 23, partial: 1 } })],
    ["a negative count", () => ({ ...cc(), summary: { ...(cc().summary as Obj), complete: -1 } })],
    ["a blind spot with a status the engine does not write", () => ({ ...cc(), devices: [{ host: "deadsw", status: "unreachable", missing: [] }] })],
    ["a blind spot with no host", () => ({ ...cc(), devices: [{ status: "partial", missing: [] }] })],
    ["a host listed twice", () => ({ ...cc(), devices: [...(cc().devices as Obj[]), ...(cc().devices as Obj[])] })],
  ];
  for (const [name, value] of UNUSABLE) {
    it(`${name}: every inventoried host is not stated, nothing is compiled as the engine's summary, and the validator says why`, () => {
      const snap = variantSnapshot("engine");
      snap.collection_completeness = value();
      const r = validateSnapshot(bytesOf(snap));
      expect(r.ok).toBe(true);
      const w = r.warnings.find((x) => x.code === "W_COLLECTION_NOT_STATED");
      expect(w?.path).toBe("/collection_completeness");
      const f = compileBytes(bytesOf(snap), "snapshot.json").fabric;
      expect(f.collection_completeness, "absent, never a null a citation would resolve to").toBeUndefined();
      expect(f.coverage.collectionUnstated).toBe(w?.message.split(", so how completely")[0]);
      for (const d of f.devices) expect(d.collection, `${name}: ${d.host}`).toBe(d.inventoried ? "not stated" : "topology only");
    });
  }
});

describe("the fixture is byte-reproducible and records no platform path", () => {
  it("its metadata are POSIX literals, and the file is LF-only with one trailing newline", () => {
    const raw = readFileSync(resolve(PKG, "tools", "fixtures", "engine-collection-completeness.json"), "latin1");
    expect(raw.includes("\r")).toBe(false);
    expect(raw.endsWith("}\n")).toBe(true);
    const doc = JSON.parse(raw) as Obj;
    expect(doc.recordsFrom).toBe("webapp/sample_data/build_sample.py");
    for (const k of ["about", "recordsFrom", "templateHost"]) expect(String(doc[k]).includes("\\"), k).toBe(false);
    const py = readFileSync(resolve(PKG, "tools", "fixtures", "engine-collection-completeness.py"), "utf8");
    expect(py).toMatch(/^SOURCE_REL = "webapp\/sample_data\/build_sample\.py"$/m);
    expect(py).toContain('newline="\\n"');
  });
});
