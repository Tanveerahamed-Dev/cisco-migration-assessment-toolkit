/**
 * DevicePane.cite.test.tsx — every figure the device and link panes show resolves to the record
 * that carries it (acceptance B6).
 *
 * THE DEFECT (2026-09-23 acceptance report, B6 overturned). `?l=L7` showed "Cutting it partitions
 * yes / Betweenness 22.0000 / Pairs cut 22 / Centrality rank 4" with no citation control at all. The
 * values came from the snapshot's `link_centrality[i]`, which the compiler read and never cited; the
 * pane's only reference was a plain-text "Source record cable_map.cables[7]" — a record that holds
 * none of those fields — and `link_centrality` did not occur in the compiled model. The first-pass
 * sample could only reach claims that already carried a citation, so the gap was invisible to it.
 *
 * THE CLASS. The refuter named the Identity rows (Model, Serial, Software) as the obvious next
 * suspect. So the guard below is not about those rows or about centrality: it renders EVERY device
 * and EVERY link, on every tab that carries key/value rows or record grids, walks the rendered rows —
 * no list of labels — and requires each to carry a citation control that the Inspector resolves, or
 * to declare itself a computation of this application (`data-derived`, with the basis stated).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fabric, resolveCite } from "../core/data";
import { useInvestigation, type EvidenceTab } from "../core/store";
import type { Device } from "../core/types";
import { DevicePane } from "./DevicePane";
import { resolveCitation } from "./Inspector";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}
function unmountAll(): void {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
}

beforeEach(() => {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().setEvidenceTab("summary");
  });
});
afterEach(unmountAll);

const squash = (s: string | null | undefined): string => (s ?? "").replace(/\s+/g, " ").trim();

/* The SOURCE snapshot the compiler read (`meta.source`, relative to the repository root, the
   package's parent). A citation is a path into THIS document; resolving it here is the only way to
   check that the record a citation names actually holds the field the row shows. */
const SOURCE = JSON.parse(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", fabric.meta.source), "utf8"),
) as unknown;

/** Resolve a citation path in the source snapshot — the same grammar `resolveCite` reads. */
function sourceRecord(path: string): unknown {
  let cur: unknown = SOURCE;
  for (const part of path.split(/[.[]/).map((p) => p.replace(/]$/, "")).filter(Boolean)) {
    if (cur === null || typeof cur !== "object") return undefined;
    const kv = /^([A-Za-z_]\w*)=(.*)$/.exec(part);
    if (kv && Array.isArray(cur)) {
      cur = (cur as Record<string, unknown>[]).find((r) => String(r[kv[1]!]) === kv[2]);
    } else if (Array.isArray(cur)) {
      cur = Number.isInteger(Number(part)) ? cur[Number(part)] : undefined;
    } else {
      cur = (cur as Record<string, unknown>)[part];
    }
  }
  return cur;
}

/** The citation paths every cite control inside `el` opens — read from the accessible name. */
const citesIn = (el: Element): string[] =>
  [...el.querySelectorAll(".ui-cite")].map((b) => (b.getAttribute("aria-label") ?? "").replace(/^Open source record /, ""));

function showLink(id: string, tab: EvidenceTab): HTMLElement {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().selectLink(id);
    useInvestigation.getState().setEvidenceTab(tab);
  });
  return mount(<DevicePane />);
}
function showDevice(id: string, tab: EvidenceTab): HTMLElement {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().selectDevice(id);
    useInvestigation.getState().setEvidenceTab(tab);
  });
  return mount(<DevicePane />);
}

const sectionTitled = (c: HTMLElement, re: RegExp): HTMLElement | undefined =>
  [...c.querySelectorAll<HTMLElement>(".dp-sec")].find((s) => re.test(squash(s.querySelector(".dp-sec__title")?.textContent)));

/* ── the reported instance: link centrality ─────────────────────────────── */

describe("B6: every link centrality figure cites the link_centrality record that carries it", () => {
  const withCentrality = fabric.links.filter(
    (l) => l.betweenness !== null || l.isBridge !== null || l.pairsCut !== null || l.centralityRank !== null,
  );

  it("rests on the links the snapshot measured (25 in this snapshot, read from the model)", () => {
    expect(withCentrality.length).toBe(fabric.coverage.linksWithCentrality);
    expect(withCentrality.length).toBeGreaterThan(0);
  });

  it("each of the four rows has a cite control, and resolveCite(cite) returns a record carrying that link's values", () => {
    let checked = 0;
    for (const link of withCentrality) {
      const c = showLink(link.id, "summary");
      const sec = sectionTitled(c, /^Centrality/);
      expect(sec, `${link.id}: no centrality section`).toBeDefined();
      const rows = [...sec!.querySelectorAll(".dp-kv__row")];
      expect(rows.length, `${link.id}: the four centrality rows`).toBe(4);
      for (const row of rows) {
        const k = squash(row.querySelector(".dp-kv__k")?.textContent);
        const cites = citesIn(row);
        expect(cites.length, `${link.id} "${k}" has no cite control`).toBeGreaterThan(0);
        for (const cite of cites) {
          const rec = resolveCite(cite) as Record<string, unknown> | undefined;
          expect(rec, `${link.id} "${k}" cites ${cite}, which resolveCite cannot resolve`).toBeDefined();
          // The record the citation names carries every figure the section shows, with the same value.
          expect(rec!["betweenness"], `${cite}.betweenness`).toBe(link.betweenness);
          expect(rec!["isBridge"], `${cite}.isBridge`).toBe(link.isBridge);
          expect(rec!["pairsCut"], `${cite}.pairsCut`).toBe(link.pairsCut);
          expect(rec!["rank"], `${cite}.rank`).toBe(link.centralityRank);
          // …and it is THIS link's row, not merely some centrality row with equal numbers.
          expect(new Set([`${rec!["aHost"]}|${rec!["aPort"]}`, `${rec!["bHost"]}|${rec!["bPort"]}`])).toEqual(
            new Set([`${link.a}|${link.aPort}`, `${link.b}|${link.bPort}`]),
          );
          // The Inspector resolves it as a MODEL path: the record itself, not a projection of it.
          expect(resolveCitation(cite).kind, `${cite} in the Inspector`).toBe("model");
          checked += 1;
        }
      }
      unmountAll();
    }
    expect(checked).toBeGreaterThanOrEqual(withCentrality.length * 4);
  });
});

/* ── the rows the refuter named: identity and health ───────────────────── */

describe("B6: identity and health rows cite a record that carries the value they show", () => {
  /* The compiled field each row shows, and the key the SOURCE record holds it under. Resolving the
     citation in the compiled model alone cannot discriminate here: every device citation is borne by
     the same compiled device record, so a row citing the inventory record for a health score would
     still "resolve". The citation is therefore also resolved in the source snapshot the compiler
     read, and that source record must hold the field. */
  const FIELD_OF: Record<string, [keyof Device, string[]]> = {
    Model: ["model", ["model"]],
    Serial: ["serial", ["serial_number", "chassis_serial"]],
    Software: ["swVersion", ["sw_version"]],
    Role: ["role", ["role"]],
    Tier: ["tier", ["tier"]],
    Criticality: ["criticality", ["criticality"]],
    "Data quality": ["dataQuality", ["data_quality"]],
    Score: ["score", ["score"]],
  };
  const inventoried = fabric.devices.filter((d) => d.inventoried);

  /* One inventoried device per case (acceptance F2, W6 gate 2026-09-25); each case's count of the
     citations it checked is kept, so the floor below sums them rather than re-rendering. */
  const checkedOn = new Map<string, number>();
  const checkDevice = (d: Device): number => {
    const known = checkedOn.get(d.id);
    if (known !== undefined) return known;
    let checked = 0;
    {
      const c = showDevice(d.id, "summary");
      for (const row of c.querySelectorAll(".dp-kv__row")) {
        const k = squash(row.querySelector(".dp-kv__k")?.textContent);
        const spec = FIELD_OF[k];
        if (spec === undefined) continue;
        const [field, sourceKeys] = spec;
        const cites = citesIn(row);
        expect(cites.length, `${d.id} "${k}" has no cite control`).toBeGreaterThan(0);
        for (const cite of cites) {
          const r = resolveCitation(cite);
          expect(r.kind, `${d.id} "${k}" cites ${cite}`).not.toBe("unresolved");
          expect((r.record as Record<string, unknown>)[field], `${d.id} "${k}" via ${cite}`).toEqual(d[field]);
          const src = sourceRecord(cite);
          expect(src, `${d.id} "${k}" cites ${cite}, which names no record in the source snapshot`).toBeDefined();
          if (d[field] !== null) {
            expect(
              sourceKeys.some((sk) => Object.prototype.hasOwnProperty.call(src, sk)),
              `${d.id} "${k}" cites ${cite}, whose source record holds none of ${sourceKeys.join(", ")}`,
            ).toBe(true);
          }
          checked += 1;
        }
      }
      unmountAll();
    }
    checkedOn.set(d.id, checked);
    return checked;
  };

  it("there is more than one inventoried device", () => {
    expect(inventoried.length).toBeGreaterThan(1);
  });
  for (const d of inventoried) {
    it(`${d.id}: the named rows cite the SOURCE record that holds the field`, () => {
      checkDevice(d);
    });
  }
  it("the named rows were checked on every inventoried device (more than five citations each, on average)", () => {
    const checked = inventoried.reduce((n, d) => n + checkDevice(d), 0);
    expect(checked).toBeGreaterThan(inventoried.length * 5);
  });

  it("each link centrality citation names a source record holding betweenness, is_bridge, pairs_cut and rank", () => {
    let links = 0;
    for (const l of fabric.links) {
      if (l.betweenness === null) continue;
      links += 1;
      const c = showLink(l.id, "summary");
      const sec = sectionTitled(c, /^Centrality/)!;
      const cites = new Set(citesIn(sec));
      expect(cites.size, `${l.id}: the centrality section cites nothing`).toBeGreaterThan(0);
      for (const cite of cites) {
        const src = sourceRecord(cite) as Record<string, unknown> | undefined;
        expect(src, `${l.id}: ${cite} names nothing in the source`).toBeDefined();
        expect(src!["betweenness"]).toBe(l.betweenness);
        expect(src!["is_bridge"]).toBe(l.isBridge);
        expect(src!["pairs_cut"]).toBe(l.pairsCut);
        expect(src!["rank"]).toBe(l.centralityRank);
      }
      unmountAll();
    }
    expect(links).toBe(fabric.coverage.linksWithCentrality);
  });

  it("a health figure cites the health_scores record, not the inventory record that holds no score", () => {
    const d = inventoried.find((x) => x.score !== null)!;
    const c = showDevice(d.id, "summary");
    const row = [...c.querySelectorAll(".dp-kv__row")].find((r) => squash(r.querySelector(".dp-kv__k")?.textContent) === "Criticality")!;
    expect(citesIn(row)).toEqual([`health_scores[switch=${d.host}]`]);
  });
});

/* ── the class: every rendered value row, every device, every link ─────── */

describe("B6 class guard: no value row in the device or link pane lacks a resolvable citation", () => {
  const DEVICE_TABS: EvidenceTab[] = ["summary", "ports", "routing"];
  const LINK_TABS: EvidenceTab[] = ["summary", "ports"];

  function audit(c: HTMLElement, where: string, out: { rows: number; cited: number; derived: number; grid: number; problems: string[] }): void {
    for (const row of c.querySelectorAll<HTMLElement>(".dp-kv__row")) {
      const k = squash(row.querySelector(".dp-kv__k")?.textContent);
      const cites = citesIn(row);
      const derived = row.getAttribute("data-derived");
      out.rows += 1;
      if (cites.length === 0) {
        if (derived !== null && derived.trim().length > 10) out.derived += 1;
        else out.problems.push(`${where}: row "${k}" has no citation and declares no derivation`);
      } else {
        out.cited += 1;
      }
      for (const cite of cites) {
        if (resolveCitation(cite).kind === "unresolved") out.problems.push(`${where}: row "${k}" cites ${cite}, which resolves to nothing`);
      }
    }
    for (const grid of c.querySelectorAll<HTMLElement>('[role="grid"].rg')) {
      const rows = [...grid.querySelectorAll('[role="row"]')].slice(1);
      for (const [i, row] of rows.entries()) {
        out.grid += 1;
        const cites = citesIn(row);
        if (cites.length === 0) out.problems.push(`${where}: ${grid.getAttribute("aria-label")} row ${i + 1} has no citation`);
        for (const cite of cites) {
          if (resolveCitation(cite).kind === "unresolved") out.problems.push(`${where}: ${grid.getAttribute("aria-label")} row ${i + 1} cites ${cite}, which resolves to nothing`);
        }
      }
    }
  }

  /* ONE CASE PER DEVICE AND PER LINK (acceptance F2, W6 gate 2026-09-25). The walk was one test over
     every device and every link, every tab — 1.7 s on a quiet host, 40-43 s for this file on a
     saturated clone, under a 240 s limit of its own. Each record is now audited in a case of its own
     and its audit is kept, so the floor below (the walk met the rows it is about) sums the same
     audits instead of repeating them; a record a filtered run did not reach is audited there. */
  type Audit = { rows: number; cited: number; derived: number; grid: number; problems: string[] };
  const audits = new Map<string, Audit>();
  const auditOf = (kind: "device" | "link", id: string): Audit => {
    const key = `${kind} ${id}`;
    let out = audits.get(key);
    if (out === undefined) {
      out = { rows: 0, cited: 0, derived: 0, grid: 0, problems: [] };
      for (const tab of kind === "device" ? DEVICE_TABS : LINK_TABS) {
        audit(kind === "device" ? showDevice(id, tab) : showLink(id, tab), `${key} / ${tab}`, out);
        unmountAll();
      }
      audits.set(key, out);
    }
    return out;
  };
  const records = [...fabric.devices.map((d) => ["device", d.id] as const), ...fabric.links.map((l) => ["link", l.id] as const)];

  for (const [kind, id] of records) {
    it(`${kind} ${id}: every row it renders is cited or declares its derivation`, () => {
      const out = auditOf(kind, id);
      expect(out.problems.slice(0, 40), `${out.problems.length} uncited rows`).toEqual([]);
    });
  }

  it("the walk met the rows it is about — an empty walk is not a pass", () => {
    const total = records.map(([kind, id]) => auditOf(kind, id)).reduce(
      (a, o) => ({ rows: a.rows + o.rows, cited: a.cited + o.cited, derived: a.derived + o.derived, grid: a.grid + o.grid }),
      { rows: 0, cited: 0, derived: 0, grid: 0 },
    );
    expect(total.rows).toBeGreaterThan(500);
    expect(total.grid).toBeGreaterThan(100);
    expect(total.cited).toBeGreaterThan(total.derived);
  });
});
