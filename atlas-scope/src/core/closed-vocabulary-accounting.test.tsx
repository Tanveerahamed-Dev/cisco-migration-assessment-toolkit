/**
 * closed-vocabulary-accounting.test.tsx — every grouping, tally and ordering over a CLOSED vocabulary (a finding's
 * severity, a device's health band, a device's kind) places and counts EVERY record, and says what each one is.
 *
 * WHY (2026-10-01 refuter, on e092ebbe — which made those vocabularies `known | Unrecognised`). With every finding
 * naming one host given the severity "Bogus", the priority queue grouped by severity showed 128 of 146 findings:
 * `buildGroups` (core/query.ts) kept only the keys SEVERITY_ORDER lists, although its own comment said rows are
 * "never dropped". The device pane's Findings tab printed the tally `C0 H0 M0 L0 I0` above a list of those
 * findings — an all-zero readout over a non-empty list, the false-health class. The same pass found the engine's own
 * not-measured band ("Insufficient Data", cisco_toolkit/analyze.py `compute_health_scores`) shown as an unrecognised
 * band, an ABSENT severity compiled to "Info" (tools/lib/compile-model.mjs), and an unrecognised severity ranked 98 —
 * after Info, i.e. as the least severe finding there is.
 *
 * THE RULES PINNED HERE. A grouping over a closed vocabulary places every record: a member in its member's group, a
 * value the vocabulary does not name in a group of its own labelled as unrecognised, an absent value in the
 * Not-observed group. A tally over one sums to the records it counts. The engine's not-measured band is a stated
 * absence of a measurement — indeterminate, never scored, never healthy, never a band colour. An absent severity is
 * NOT STATED — never Info. And a severity that is not a point on the graded scale (unrecognised, or not stated) is
 * never ranked as the least severe: it sorts after every graded finding in BOTH directions, as a null sinks.
 *
 * THE FIXTURES are the tracked sample, compiled as a renamed external file ("snapshot.json"), with one device chosen
 * by role (as dataset.unrecognised-values.test.tsx chooses it: the first punch-list row that names a device with
 * both a health score and a cable-map node) and every punch-list and cross-layer record naming it changed:
 *   - "bogus":        their severity "Bogus"; the device's band and its node's kind "Bogus".
 *   - "absent":       their severity absent — cycling a missing key, null, "", "-", "N/A" and "[NOT OBSERVED]".
 *   - "not-measured": the device's band "Insufficient Data", the engine's own not-measured band (records unchanged).
 * Each variant is compiled by the one compiler and installed as an opened file in a module graph of its own.
 */
import { act, createElement, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readFileSync } from "node:fs";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { CompiledDataset } from "./dataset/types";
import { asOpenedFile, compileBytes, SAMPLE_SNAPSHOT } from "../test-support/dataset/testing";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);

/* ── the subject, chosen by role from the sample ──────────────────────────────────────────────── */
const SOURCE_TEXT = readFileSync(SAMPLE_SNAPSHOT, "utf8");
const parse = (): Obj => JSON.parse(SOURCE_TEXT) as Obj;
const ORIGINAL = parse();
const rows = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : []);
const healthRows = rows(ORIGINAL.health_scores);
const nodeRows = rows(isObj(ORIGINAL.cable_map) ? ORIGINAL.cable_map.nodes : undefined);
const hasHealth = (h: string): boolean => healthRows.some((r) => r.switch === h && typeof r.band === "string");
const hasNode = (h: string): boolean => nodeRows.some((r) => r.host === h && typeof r.kind === "string");
const FIRST = rows(ORIGINAL.punchlist).find(
  (p) => typeof p.category === "string" && Array.isArray(p.devices) && p.devices.some((h) => typeof h === "string" && hasHealth(h) && hasNode(h)),
);
const DEVICE = ((FIRST?.devices as unknown[] | undefined) ?? []).find((h): h is string => typeof h === "string" && hasHealth(h) && hasNode(h)) ?? "";
const names = (list: unknown): boolean => Array.isArray(list) && list.includes(DEVICE);
/** How many punch-list / cross-layer records name the subject device. */
const N_FINDINGS = rows(ORIGINAL.punchlist).filter((p) => names(p.devices)).length;
const N_CROSS = rows(ORIGINAL.cross_layer).filter((c) => names(c.hosts)).length;
/** The compiled id of punchlist[i] (tools/lib/compile-model.mjs: `F` + the 1-based index, three digits). */
const findingId = (i: number): string => `F${String(i + 1).padStart(3, "0")}`;
const SUBJECT_IDS = new Set(rows(ORIGINAL.punchlist).flatMap((p, i) => (names(p.devices) ? [findingId(i)] : [])));

const SCORED_BANDS = ["Excellent", "Good", "Fair", "Poor", "Critical"];
/** The five spellings of "no severity" the compiler reads as unobserved, plus a key that is simply missing. */
const ABSENT_FORMS: readonly unknown[] = [undefined, null, "", "-", "N/A", "[NOT OBSERVED] no grade published"];

type Variant = "bogus" | "absent" | "not-measured";
const VARIANTS: readonly Variant[] = ["bogus", "absent", "not-measured"];

function variantSnapshot(variant: Variant): Obj {
  const snap = parse();
  let k = 0;
  const setSeverity = (r: Obj): void => {
    if (variant === "bogus") r.severity = "Bogus";
    else if (variant === "absent") {
      const form = ABSENT_FORMS[k++ % ABSENT_FORMS.length];
      if (form === undefined) delete r.severity;
      else r.severity = form;
    }
  };
  if (variant !== "not-measured") {
    for (const p of rows(snap.punchlist)) if (names(p.devices)) setSeverity(p);
    for (const c of rows(snap.cross_layer)) if (names(c.hosts)) setSeverity(c);
  }
  if (variant === "bogus") {
    for (const h of rows(snap.health_scores)) if (h.switch === DEVICE) h.band = "Bogus";
    for (const n of rows(isObj(snap.cable_map) ? snap.cable_map.nodes : undefined)) if (n.host === DEVICE) n.kind = "Bogus";
  }
  if (variant === "not-measured") for (const h of rows(snap.health_scores)) if (h.switch === DEVICE) h.band = "Insufficient Data";
  return snap;
}

/* ── one module graph per variant ─────────────────────────────────────────────────────────────── */
async function loadGraph(set: CompiledDataset, source: Obj) {
  vi.resetModules();
  (await import("./dataset/slot")).installDataset(asOpenedFile(set, "snapshot.json"));
  return {
    set,
    source,
    types: await import("./types"),
    data: await import("./data"),
    query: await import("./query"),
    store: await import("./store"),
    band: await import("./band-qualification"),
    coverage: await import("../app/CoverageBar"),
    devicePane: await import("../panels/DevicePane"),
    evidencePane: await import("../panels/EvidencePane"),
    queue: await import("../panels/PriorityQueue"),
    primitives: await import("../ui/primitives"),
    legend: await import("../fabric3d/FabricLegend"),
  };
}
type Graph = Awaited<ReturnType<typeof loadGraph>>;
const graphs = new Map<Variant, Graph>();
const G = (v: Variant): Graph => graphs.get(v)!;

beforeAll(async () => {
  for (const v of VARIANTS) {
    const snap = variantSnapshot(v);
    graphs.set(v, await loadGraph(compileBytes(new TextEncoder().encode(JSON.stringify(snap, null, 2)), "snapshot.json"), snap));
  }
}, 300_000);
afterAll(() => {
  vi.resetModules();
});
beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* a preference store is not evidence */
  }
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
/** Render `element` after `select`, hand the live container to `read`, then unmount. A throw is an answer, never a skip. */
function render<R>(g: Graph, select: () => void, element: () => ReactElement, read: (c: HTMLElement) => R): R | string {
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
const unrecognised = (what: "severity" | "band" | "kind", value: string): string => `unrecognised ${what} ${JSON.stringify(value)}`;
const placed = (groups: readonly { items: readonly unknown[] }[]): number => groups.reduce((a, x) => a + x.items.length, 0);

describe("the fixture", () => {
  it("chooses a device by role that findings and cross-layer records name, on a sample that holds none of the values", () => {
    expect(DEVICE).not.toBe("");
    expect(N_FINDINGS).toBeGreaterThan(0);
    expect(N_CROSS).toBeGreaterThan(0);
    for (const s of ['"Bogus"', '"Insufficient Data"']) expect(SOURCE_TEXT.includes(s), `${s} already occurs in the sample`).toBe(false);
  });
});

/* ══ 1. a grouping over a closed vocabulary places every record ═════════════════════════════════ */

describe("grouping over a closed vocabulary places every record", () => {
  it("core/query groupBy severity: every finding is placed; the unrecognised ones form their own labelled group, after every graded group", () => {
    const g = G("bogus");
    const groups = g.query.groupBy(g.data.fabric.findings, "severity");
    expect(placed(groups)).toBe(g.data.fabric.findings.length);
    const u = groups.find((x) => x.label === unrecognised("severity", "Bogus"));
    expect(u?.items.length).toBe(N_FINDINGS);
    expect(new Set(u?.items.map((f) => f.id))).toEqual(SUBJECT_IDS);
    const at = groups.indexOf(u!);
    for (const [i, x] of groups.entries()) if (g.types.recognisedSeverity(x.key)) expect(i, x.label).toBeLessThan(at);
  });

  it("core/query groupBy severity: an absent severity lands in the Not-observed group, never in Info", () => {
    const g = G("absent");
    const groups = g.query.groupBy(g.data.fabric.findings, "severity");
    expect(placed(groups)).toBe(g.data.fabric.findings.length);
    const none = groups.find((x) => x.key === g.query.UNOBSERVED_GROUP);
    expect(new Set(none?.items.map((f) => f.id))).toEqual(SUBJECT_IDS);
    expect(groups.find((x) => x.key === "Info")?.items.some((f) => SUBJECT_IDS.has(f.id)) ?? false).toBe(false);
  });

  it("core/query groupDevicesBy band and kind: every device is placed; the unrecognised value is labelled as such", () => {
    const g = G("bogus");
    const devices = g.data.fabric.devices;
    const bands = g.query.groupDevicesBy(devices, "band");
    expect(placed(bands)).toBe(devices.length);
    expect(bands.find((x) => x.label === unrecognised("band", "Bogus"))?.items.map((d) => d.host)).toEqual([DEVICE]);
    expect(bands.find((x) => x.key === g.query.UNOBSERVED_GROUP)?.items.some((d) => d.host === DEVICE) ?? false).toBe(false);
    const kinds = g.query.groupDevicesBy(devices, "kind");
    expect(placed(kinds)).toBe(devices.length);
    expect(kinds.find((x) => x.label === unrecognised("kind", "Bogus"))?.items.map((d) => d.host)).toEqual([DEVICE]);
    expect(kinds.some((x) => x.label === "Bogus")).toBe(false);
  });

  it("core/query band groupings: the engine's not-measured band is its own group, never 'Not observed' and never unrecognised", () => {
    const g = G("not-measured");
    const devices = g.data.fabric.devices;
    const bands = g.query.groupDevicesBy(devices, "band");
    expect(placed(bands)).toBe(devices.length);
    const nm = bands.find((x) => x.items.some((d) => d.host === DEVICE));
    expect(nm?.label).toMatch(/not measured/i);
    expect(nm?.label).toContain("Insufficient Data");
    expect(nm?.observed).toBe(true);
    expect(bands.some((x) => x.label.startsWith("unrecognised"))).toBe(false);
    const byFinding = g.query.groupBy(g.data.fabric.findings, "band");
    const nmf = byFinding.find((x) => x.label === nm?.label);
    expect(new Set(nmf?.items.map((f) => f.id))).toEqual(SUBJECT_IDS);
  });

  for (const corpus of ["findings", "cross-layer"] as const) {
    it(`panels/PriorityQueue ${corpus}, grouped by severity: every row renders, under a header naming the unrecognised value and its count`, () => {
      const g = G("bogus");
      window.localStorage.setItem("atlas-scope.queue.corpus", corpus);
      const total = corpus === "findings" ? g.data.fabric.findings.length : g.data.fabric.crossLayer.length;
      const n = corpus === "findings" ? N_FINDINGS : N_CROSS;
      const got = render(
        g,
        () => {},
        () => createElement(g.queue.PriorityQueue, { debounceMs: 0 }),
        (c) => ({
          rows: c.querySelectorAll(".ag__row--data").length,
          headers: [...c.querySelectorAll<HTMLElement>(".ag__row--group")].map((r) => textOf(r)),
        }),
      );
      expect(typeof got, String(got)).toBe("object");
      const { rows: shown, headers } = got as { rows: number; headers: string[] };
      expect(shown).toBe(total);
      const h = headers.find((x) => x.includes(unrecognised("severity", "Bogus")));
      expect(h, headers.join(" | ")).toBeDefined();
      expect(h).toContain(String(n));
    });
  }

  it("panels/PriorityQueue: a finding that states no severity renders under the Not-observed header", () => {
    const g = G("absent");
    const got = render(
      g,
      () => {},
      () => createElement(g.queue.PriorityQueue, { debounceMs: 0 }),
      (c) => ({
        rows: c.querySelectorAll(".ag__row--data").length,
        headers: [...c.querySelectorAll<HTMLElement>(".ag__row--group")].map((r) => textOf(r)),
      }),
    );
    const { rows: shown, headers } = got as { rows: number; headers: string[] };
    expect(shown).toBe(g.data.fabric.findings.length);
    expect(headers.find((x) => x.startsWith("Not observed"))).toContain(String(N_FINDINGS));
  });
});

/* ══ 2. every tally over a closed vocabulary sums to what it counts ═════════════════════════════ */

/** The device pane's Findings tab for the subject: the tally's slots, their sum, and the number of listed findings. */
function findingsTab(g: Graph): { text: string; sum: number; listed: number } | string {
  return render(
    g,
    () => {
      g.store.useInvestigation.getState().selectDevice(DEVICE);
      g.store.useInvestigation.getState().setEvidenceTab("findings");
    },
    () => createElement(g.devicePane.DevicePane, {}),
    (c) => {
      const tally = c.querySelector<HTMLElement>(".dp-sevcounts");
      const ns = [...c.querySelectorAll<HTMLElement>(".dp-sevcounts__n")].map((x) => Number(x.textContent));
      return {
        text: tally === null ? "" : textOf(tally),
        sum: ns.reduce((a, x) => a + x, 0),
        listed: c.querySelectorAll(".dp-list--findings > li").length,
      };
    },
  );
}

describe("every tally over a closed vocabulary sums to what it counts", () => {
  it("panels/DevicePane Findings tab: the severity tally counts the unrecognised findings it lists — never an all-zero readout", () => {
    const got = findingsTab(G("bogus"));
    expect(typeof got, String(got)).toBe("object");
    const { text, sum, listed } = got as Exclude<typeof got, string>;
    expect(listed).toBe(N_FINDINGS);
    expect(sum).toBe(listed);
    expect(text).toContain(unrecognised("severity", "Bogus"));
  });

  it("panels/DevicePane Findings tab: the severity tally counts the findings that state no severity", () => {
    const got = findingsTab(G("absent"));
    const { text, sum, listed } = got as Exclude<typeof got, string>;
    expect(listed).toBe(N_FINDINGS);
    expect(sum).toBe(listed);
    expect(text).toContain("severity not stated");
  });

  for (const v of ["bogus", "absent"] as const) {
    it(`core/data tallySeverities (${v}): graded + unrecognised + not stated = every finding`, () => {
      const g = G(v);
      const t = g.data.tallySeverities(g.data.fabric.findings);
      const sum = t.graded.reduce((a, x) => a + x.n, 0) + t.unrecognised.reduce((a, x) => a + x.n, 0) + t.notStated;
      expect(sum).toBe(g.data.fabric.findings.length);
      expect(t.total).toBe(g.data.fabric.findings.length);
      expect(t.graded.map((x) => x.severity)).toEqual([...g.types.SEVERITY_ORDER]);
      if (v === "bogus") expect(t.unrecognised).toEqual([{ value: "Bogus", n: N_FINDINGS }]);
      else expect(t.notStated).toBe(N_FINDINGS);
    });
  }

  for (const v of ["bogus", "not-measured"] as const) {
    it(`fabric3d/FabricLegend (${v}): the band rows and the kind rows each count every device exactly once`, () => {
      const g = G(v);
      window.localStorage.setItem("atlas-scope.fabric-legend.open", "1");
      const got = render(
        g,
        () => {},
        () => createElement(g.legend.FabricLegend, { id: "lg", devices: g.data.fabric.devices, links: g.data.fabric.links }),
        (c) =>
          [...c.querySelectorAll<HTMLElement>(".fabric3d-legend__group")].map((grp) => ({
            heading: grp.querySelector(".fabric3d-legend__legend")?.textContent ?? "",
            rows: [...grp.querySelectorAll<HTMLElement>(".fabric3d-legend__row")].map((r) => ({
              text: textOf(r),
              n: Number(r.querySelector(".fabric3d-legend__count")?.textContent ?? "NaN"),
            })),
          })),
      );
      expect(Array.isArray(got), String(got)).toBe(true);
      const groups = got as { heading: string; rows: { text: string; n: number }[] }[];
      const devices = g.data.fabric.devices.length;
      const band = groups.find((x) => x.heading.includes("health band"))!;
      const kind = groups.find((x) => x.heading.includes("device kind"))!;
      expect(band.rows.reduce((a, r) => a + r.n, 0)).toBe(devices);
      expect(kind.rows.reduce((a, r) => a + r.n, 0)).toBe(devices);
      if (v === "not-measured") {
        const nm = band.rows.find((r) => /not measured/i.test(r.text));
        expect(nm?.n, band.rows.map((r) => r.text).join(" | ")).toBe(1);
        expect(band.rows.some((r) => r.text.includes("unrecognised"))).toBe(false);
      }
    });
  }

  it("app/CoverageBar: the band row counts as scored only devices the engine placed in one of its five bands", () => {
    const g = G("not-measured");
    const row = g.coverage.coverageRows().find((r) => r.id === "band")!;
    /* The oracle is the SOURCE: compiled devices whose health row states one of the five scored bands. */
    const scored = new Set(rows(g.source.health_scores).filter((h) => SCORED_BANDS.includes(String(h.band))).map((h) => String(h.switch)));
    expect(row.observed).toBe(g.data.fabric.devices.filter((d) => scored.has(d.host)).length);
    expect(row.observed + row.absent + row.notApplicable).toBe(row.total);
  });
});

/* ══ 3. the engine's not-measured band ═════════════════════════════════════════════════════════ */

describe("the engine's not-measured band ('Insufficient Data') is not measured — never unrecognised, never scored, never healthy", () => {
  it("core/band-qualification: indeterminate, never a band colour, never favourable, never a candidate band", () => {
    const g = G("not-measured");
    const d = g.data.deviceById.get(DEVICE)!;
    const p = g.band.presentBand(d);
    expect(p.label).toMatch(/not measured/i);
    expect(p.short).toMatch(/not measured/i);
    expect(p.short).toContain("Insufficient Data");
    expect(`${p.label} ${p.short} ${p.sentence}`).not.toMatch(/unrecognised/i);
    expect(p.unrecognised).toBeNull();
    expect(p.legendKey).toBe("not-measured");
    expect(p.tone).toBe("neutral");
    expect(p.colorToken).toBe(g.band.NO_BAND_TOKEN);
    expect(p.letter).toBe("?");
    expect(g.band.bandCandidates(d)).toBeNull();
    expect(g.band.bandHealthy(d)).toBe("unknown");
    expect(g.band.bandDegraded(d)).toBe("unknown");
    expect(g.band.bandKey(d)).toBeNull();
    expect(g.band.bandRank(d)).toBeNull();
    expect(g.band.isFavourableBand("Insufficient Data")).toBe(false);
    expect(g.band.bandScored(d)).toBe(false);
  });

  it("the score the engine published beside it is never counted as a measurement", () => {
    const g = G("not-measured");
    const d = g.data.deviceById.get(DEVICE)!;
    expect(d.score, "precondition: the engine publishes a number beside the not-measured band").not.toBeNull();
    expect(g.band.measuredScore(d)).toBeNull();
    const withScore = g.query.applyToDevices(g.data.fabric.devices, g.query.parseQuery("has:score")).items.map((x) => x.host);
    expect(withScore).not.toContain(DEVICE);
    for (const direction of ["asc", "desc"] as const) {
      const order = g.query.sortDevicesBy(g.data.fabric.devices, [{ field: "score", direction }]).map((x) => x.host);
      const unscored = g.data.fabric.devices.filter((x) => g.band.measuredScore(x) === null).length;
      expect(order.indexOf(DEVICE), direction).toBeGreaterThanOrEqual(order.length - unscored);
    }
  });

  it("panels/DevicePane summary: the band reads not measured, quoting the engine, and the score is not shown as a measurement", () => {
    const g = G("not-measured");
    const got = render(
      g,
      () => {
        g.store.useInvestigation.getState().selectDevice(DEVICE);
        g.store.useInvestigation.getState().setEvidenceTab("summary");
      },
      () => createElement(g.devicePane.DevicePane, {}),
      (c) => ({ text: textOf(c), meter: c.querySelector('.ui-meter[data-unobserved="true"]') !== null }),
    );
    expect(typeof got, String(got)).toBe("object");
    const { text, meter } = got as { text: string; meter: boolean };
    expect(text).toMatch(/not measured/i);
    expect(text).toContain("Insufficient Data");
    expect(text).not.toContain(unrecognised("band", "Insufficient Data"));
    expect(meter, "the health-score meter must not draw the engine's number as a measurement").toBe(true);
  });
});

/* ══ 4. an absent severity is not stated — never Info ══════════════════════════════════════════ */

describe("an absent severity is NOT STATED — never compiled to, drawn as, or counted as Info", () => {
  it("tools/lib/compile-model: every absent spelling compiles to null, a stated severity verbatim", () => {
    const g = G("absent");
    for (const [i, p] of rows(g.source.punchlist).entries()) {
      const f = g.set.fabric.findings[i]!;
      if (names(p.devices)) expect(f.severity, `punchlist[${i}] ${JSON.stringify(p.severity)}`).toBeNull();
      else expect(f.severity).toBe(p.severity);
    }
    for (const [i, c] of rows(g.source.cross_layer).entries()) {
      const x = g.set.fabric.crossLayer[i]!;
      if (names(c.hosts)) expect(x.severity, `cross_layer[${i}] ${JSON.stringify(c.severity)}`).toBeNull();
      else expect(x.severity).toBe(c.severity);
    }
  });

  it("ui/primitives SeverityBadge, full and compact: says 'severity not stated', never Info", () => {
    const g = G("absent");
    for (const compact of [false, true]) {
      const got = render(
        g,
        () => {},
        () => createElement(g.primitives.SeverityBadge, { severity: null, compact }),
        (c) => ({ text: textOf(c), html: c.innerHTML }),
      );
      const { text, html } = got as { text: string; html: string };
      expect(text, `compact=${compact}`).toContain("severity not stated");
      expect(text).not.toMatch(/\bInfo\b|^I$/m);
      expect(html).toContain('data-severity="not-stated"');
    }
  });

  it("panels/EvidencePane: a selected finding that states no severity says so, and does not throw", () => {
    const g = G("absent");
    const id = [...SUBJECT_IDS][0]!;
    const got = render(
      g,
      () => {
        g.store.useInvestigation.getState().selectFinding(id);
      },
      () => createElement(g.evidencePane.EvidencePane, { onOpenCite: () => {}, onShowConfig: () => {} }),
      (c) => textOf(c),
    );
    expect(got).not.toMatch(/^THREW /);
    expect(got).toContain("severity not stated");
  });
});

/* ══ 5. ordering: a severity off the graded scale is never ranked as the least severe ═══════════ */

describe("ordering: an unrecognised or unstated severity sorts after every graded one, in both directions", () => {
  it("core/data severityRank: Critical < High < Medium < Low < Info < unrecognised < not stated", () => {
    const g = G("bogus");
    const ranks = [...g.types.SEVERITY_ORDER, "Bogus", null].map((s) => g.data.severityRank(s));
    expect([...ranks].sort((a, b) => a - b)).toEqual(ranks);
    expect(new Set(ranks).size).toBe(ranks.length);
    expect(g.data.severityRank("Bogus")).toBe(g.data.UNRECOGNISED_SEVERITY_RANK);
    expect(g.data.severityRank(null)).toBe(g.data.NOT_STATED_SEVERITY_RANK);
  });

  for (const v of ["bogus", "absent"] as const) {
    it(`core/query sortBy severity (${v}): the off-scale findings come last whether the order is ascending or descending`, () => {
      const g = G(v);
      for (const direction of ["asc", "desc"] as const) {
        const order = g.query.sortBy(g.data.fabric.findings, [{ field: "severity", direction }]).map((f) => f.id);
        expect(new Set(order.slice(-N_FINDINGS)), direction).toEqual(SUBJECT_IDS);
      }
      const ranked = [...g.data.fabric.findings].sort(g.data.bySeverityThenRank).map((f) => f.id);
      expect(new Set(ranked.slice(-N_FINDINGS))).toEqual(SUBJECT_IDS);
    });
  }
});
