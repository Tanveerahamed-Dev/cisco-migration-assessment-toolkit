/**
 * dataset.unrecognised-values.test.tsx — a value the snapshot supplies for a CLOSED vocabulary (a finding's
 * severity, a device's health band, a node's kind) or for a routing table's KEY (a finding's category) that the
 * vocabulary or table does not name is shown as what it is — unrecognised — END TO END: never a crash, never an
 * inherited member of a constant table, never a healthy or neutral state that hides it.
 *
 * WHY (2026-09-30 refuter, round 3). The compiler passed `category`, `band`, `severity` and `kind` through unchecked
 * and the application used them as KEYS into constant tables: a category "constructor" made the evidence pane throw
 * (`families.flatMap is not a function`), a band "constructor" drew the device in `function Object()` ink (the 3-D
 * lookup fell to its magenta default), ANY severity outside the five crashed the pane ("Element type is invalid" —
 * the type claimed a closed union the compiler never enforced), and a kind "constructor" rendered a function as a
 * legend row's name. The owners now: `core/own.ts` (every table read by a runtime key), the vocabularies in
 * `core/types.ts` (`Unrecognised`, `recognisedSeverity`, `recognisedBand`, `recognisedKind`), and the compiler's
 * closed-vocabulary reader (`term`, tools/lib/compile-model.mjs).
 *
 * THE FIXTURE is the tracked sample with ONE finding, ONE device and that device's cable-map node changed — chosen
 * by role, never by name: the first punch-list row that names a device which has both a health score and a
 * cable-map node. Its severity and category, the device's band and the node's kind are each set to the same value,
 * for every reserved name a table lookup can be handed and for one ordinary unknown word ("Bogus"). Each variant is
 * compiled by the one compiler and installed as an opened file in a module graph of its own.
 */
import { act, createElement, type ReactElement } from "react";
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

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);

/* ── the subjects, chosen by role from the sample ─────────────────────────────────────────────── */
const SOURCE_TEXT = readFileSync(SAMPLE_SNAPSHOT, "utf8");
const parse = (): Obj => JSON.parse(SOURCE_TEXT) as Obj;
const ORIGINAL = parse();
const rows = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : []);
const healthRows = rows(ORIGINAL.health_scores);
const nodeRows = rows(isObj(ORIGINAL.cable_map) ? ORIGINAL.cable_map.nodes : undefined);
const hasHealth = (h: string): boolean => healthRows.some((r) => r.switch === h && typeof r.band === "string");
const hasNode = (h: string): boolean => nodeRows.some((r) => r.host === h && typeof r.kind === "string");
const FINDING_INDEX = rows(ORIGINAL.punchlist).findIndex(
  (p) => typeof p.category === "string" && Array.isArray(p.devices) && p.devices.some((h) => typeof h === "string" && hasHealth(h) && hasNode(h)),
);
const FINDING_ROW = rows(ORIGINAL.punchlist)[FINDING_INDEX];
const DEVICE = ((FINDING_ROW?.devices as unknown[] | undefined) ?? []).find((h): h is string => typeof h === "string" && hasHealth(h) && hasNode(h)) ?? "";
/** The compiled id of punchlist[i] (tools/lib/compile-model.mjs: `F` + the 1-based index, three digits). */
const FINDING_ID = `F${String(FINDING_INDEX + 1).padStart(3, "0")}`;

/** Every value a lookup keyed by it could be handed: the reserved names, and an ordinary word no table holds. */
const VALUES = ["constructor", "toString", "__proto__", "Bogus"] as const;
type Value = (typeof VALUES)[number];

/** The sample with the subject finding's severity and category, the device's band and its node's kind set to `value`. */
function variant(value: Value): string {
  const snap = parse();
  const finding = rows(snap.punchlist)[FINDING_INDEX]!;
  finding.severity = value;
  finding.category = value;
  for (const h of rows(snap.health_scores)) if (h.switch === DEVICE) h.band = value;
  for (const n of rows(isObj(snap.cable_map) ? snap.cable_map.nodes : undefined)) if (n.host === DEVICE) n.kind = value;
  return JSON.stringify(snap, null, 2);
}

/* ── one module graph per variant ─────────────────────────────────────────────────────────────── */
async function loadGraph(set: CompiledDataset) {
  vi.resetModules();
  (await import("./dataset/slot")).installDataset(asOpenedFile(set, "snapshot.json"));
  return {
    set,
    data: await import("./data"),
    store: await import("./store"),
    band: await import("./band-qualification"),
    devicePane: await import("../panels/DevicePane"),
    evidencePane: await import("../panels/EvidencePane"),
    primitives: await import("../ui/primitives"),
    legend: await import("../fabric3d/FabricLegend"),
  };
}
type Graph = Awaited<ReturnType<typeof loadGraph>>;
const graphs = new Map<Value, Graph>();

beforeAll(async () => {
  for (const value of VALUES) graphs.set(value, await loadGraph(compileBytes(new TextEncoder().encode(variant(value)), "snapshot.json")));
}, 240_000);
afterAll(() => {
  vi.resetModules();
});

/* ── rendering ────────────────────────────────────────────────────────────────────────────────── */
/** Every text node, one per line, with the <wbr> break opportunities dropped and the text they split rejoined. */
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
/** Render `element` after `select`; the text, or `THREW <message>` — a throw is an answer here, never a skip. */
function render(g: Graph, select: () => void, element: () => ReactElement): { text: string; html: string } {
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
    return { text: textOf(container), html: container.innerHTML };
  } catch (e) {
    return { text: `THREW ${e instanceof Error ? e.message : String(e)}`, html: "" };
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
/** How a surface names an unrecognised value: the vocabulary, then the producer's text, quoted exactly. */
const unrecognised = (what: "severity" | "band" | "kind", value: string): string => `unrecognised ${what} ${JSON.stringify(value)}`;

describe("the fixture", () => {
  it("chooses a finding, a scored device and its cable-map node by role", () => {
    expect(FINDING_INDEX, "no punch-list row names a device with a health score and a cable-map node").toBeGreaterThanOrEqual(0);
    expect(DEVICE).not.toBe("");
    for (const value of VALUES) expect(SOURCE_TEXT.includes(`"${value}"`), `${value} already occurs in the sample`).toBe(false);
  });

  for (const value of VALUES) {
    it(`${value}: the compiler carries each value verbatim — never coerced to a member, never dropped`, () => {
      const g = graphs.get(value)!;
      const f = g.set.fabric.findings.find((x) => x.id === FINDING_ID);
      const d = g.set.fabric.devices.find((x) => x.host === DEVICE);
      expect(f?.severity).toBe(value);
      expect(f?.category).toBe(value);
      expect(d?.band).toBe(value);
      expect(d?.kind).toBe(value);
    });
  }
});

describe("every surface states an unrecognised value as unrecognised, and none throws", () => {
  for (const value of VALUES) {
    describe(value, () => {
      it("panels/EvidencePane: the finding's severity is unrecognised and its category is not routed", () => {
        const g = graphs.get(value)!;
        const { text } = render(
          g,
          () => {
            g.store.useInvestigation.getState().selectFinding(FINDING_ID);
          },
          () => createElement(g.evidencePane.EvidencePane, { onOpenCite: () => {}, onShowConfig: () => {} }),
        );
        expect(text).not.toMatch(/^THREW /);
        expect(text).toContain(unrecognised("severity", value));
        expect(text).toContain(`category ${JSON.stringify(value)} is not one Atlas Scope routes to an evidence family`);
        expect(text).not.toMatch(/function |\[object /);
      });

      for (const tab of ["summary", "findings"] as const) {
        it(`panels/DevicePane ${tab}: ${tab === "summary" ? "the band and the kind are" : "the finding's severity is"} unrecognised`, () => {
          const g = graphs.get(value)!;
          const { text } = render(
            g,
            () => {
              g.store.useInvestigation.getState().selectDevice(DEVICE);
              g.store.useInvestigation.getState().setEvidenceTab(tab);
            },
            () => createElement(g.devicePane.DevicePane, {}),
          );
          expect(text).not.toMatch(/^THREW /);
          for (const what of tab === "summary" ? (["band", "kind"] as const) : (["severity"] as const)) expect(text).toContain(unrecognised(what, value));
          expect(text).not.toMatch(/function |\[object /);
        });
      }

      it("ui/primitives SeverityBadge, full and compact: names the value as unrecognised", () => {
        const g = graphs.get(value)!;
        const f = g.data.findingById.get(FINDING_ID)!;
        for (const compact of [false, true]) {
          const { text, html } = render(g, () => {}, () => createElement(g.primitives.SeverityBadge, { severity: f.severity, compact }));
          expect(text).not.toMatch(/^THREW /);
          expect(text, `compact=${compact}`).toContain(unrecognised("severity", value));
          expect(html).toContain('data-severity="unrecognised"');
        }
      });

      it("core/band-qualification: the band is indeterminate — never favourable, never a band colour, never a function", () => {
        const g = graphs.get(value)!;
        const d = g.data.deviceById.get(DEVICE)!;
        const p = g.band.presentBand(d);
        expect(typeof p.colorToken).toBe("string");
        expect(p.colorToken).toBe(g.band.NO_BAND_TOKEN);
        expect(p.tone).toBe("neutral");
        expect(p.label).toBe(unrecognised("band", value));
        expect(p.legendKey).toBe("unrecognised");
        expect(g.band.bandCandidates(d)).toBeNull();
        expect(g.band.bandHealthy(d)).toBe("unknown");
        expect(g.band.bandKey(d)).toBeNull();
        expect(g.band.isFavourableBand(value)).toBe(false);
      });

      it("fabric3d/FabricLegend: the kind row and the band row name the value as unrecognised", () => {
        const g = graphs.get(value)!;
        /* The legend is closed by default; its own stored preference opens it (FabricLegend.tsx readStored). */
        window.localStorage.setItem("atlas-scope.fabric-legend.open", "1");
        const { text } = render(g, () => {}, () => createElement(g.legend.FabricLegend, { id: "lg", devices: g.data.fabric.devices, links: g.data.fabric.links }));
        expect(text).not.toMatch(/^THREW /);
        expect(text).toContain(unrecognised("kind", value));
        expect(text).toContain(unrecognised("band", value));
        expect(text).not.toMatch(/function |\[object /);
      });
    });
  }
});

describe("the compile boundary: a closed-vocabulary value that is not text", () => {
  /** The sample with the subject finding's severity, the device's band and its node's kind set to `value` (any JSON). */
  const withValue = (value: unknown): Uint8Array => {
    const snap = parse();
    rows(snap.punchlist)[FINDING_INDEX]!.severity = value;
    for (const h of rows(snap.health_scores)) if (h.switch === DEVICE) h.band = value;
    for (const n of rows(isObj(snap.cable_map) ? snap.cable_map.nodes : undefined)) if (n.host === DEVICE) n.kind = value;
    return new TextEncoder().encode(JSON.stringify(snap));
  };

  it("a number or a boolean is carried as its TEXT (so it reads as unrecognised), never as a number a string reader throws on", () => {
    for (const value of [3, true]) {
      const set = compileBytes(withValue(value), "snapshot.json");
      const f = set.fabric.findings.find((x) => x.id === FINDING_ID);
      const d = set.fabric.devices.find((x) => x.host === DEVICE);
      expect([f?.severity, d?.band, d?.kind], String(value)).toEqual([String(value), String(value), String(value)]);
    }
  });

  it("an object or a list is refused with a coded reason and its path, never stringified to [object Object]", () => {
    for (const value of [{ level: "High" }, ["High"]]) {
      let code: unknown = null;
      let path: unknown = null;
      try {
        compileBytes(withValue(value), "snapshot.json");
      } catch (e) {
        code = (e as { code?: unknown }).code;
        path = (e as { path?: unknown }).path;
      }
      expect(code, JSON.stringify(value)).toBe("E_NON_PRIMITIVE");
      expect(path).toMatch(/^(punchlist\[\d+\]\.severity|health_scores\[switch=.+\]\.band|cable_map\.nodes\[host=.+\]\.kind)$/);
    }
  });
});
