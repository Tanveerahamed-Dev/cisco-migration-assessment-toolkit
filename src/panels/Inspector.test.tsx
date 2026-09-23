/**
 * Inspector.test.tsx — the behaviour a visual review cannot see.
 *
 * Everything asserted here is a claim the Inspector makes about evidence, and each one is checked
 * against the REAL compiled snapshot rather than a fixture shaped to agree with the component:
 *
 *   - a citation that resolves is shown, and one that does not is shouted about;
 *   - a null in a record reaches the not-observed treatment rather than an empty cell;
 *   - the coverage lists are the actual members, recomputed from the arrays, not copied counts;
 *   - opening the panel does not disturb the investigation behind it.
 *
 * The only fabricated inputs are the two things the real data cannot supply: a deliberately broken
 * citation (the failure path has to be executed to be a failure path) and an oversized array (the
 * chunking guard never fires on a document this small, and an unexercised guard is not a guard).
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { aclUndecidability } from "../core/acl-coverage";
import * as claims from "../core/claims";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import {
  Inspector,
  citeBearers,
  citationCandidates,
  aclLineVerdict,
  resolveCitation,
  setInspectorCite,
  openInspector,
} from "./Inspector";
import { JsonView, ancestorsOf, searchDocument } from "./JsonView";

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

const writeText = vi.fn((_text: string) => Promise.resolve());

beforeEach(() => {
  writeText.mockClear();
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
    writable: true,
  });
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().setInspectorOpen(false);
  });
  setInspectorCite(null);
});

const key = (el: Element, k: string, init: KeyboardEventInit = {}): void => {
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, ...init }));
  });
};
const click = (el: Element): void => {
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
};
const text = (el: Element | null): string => el?.textContent ?? "";
const panel = (c: HTMLElement, id: string): HTMLElement | null =>
  c.querySelector<HTMLElement>(`#inspector-panel-${id}`);
const tabFor = (c: HTMLElement, id: string): HTMLElement => {
  const el = c.querySelector<HTMLElement>(`#inspector-tab-${id}`);
  if (!el) throw new Error(`no tab ${id}`);
  return el;
};

/* Real citations taken from the shipped data, not invented. */
const FIRST_FINDING = fabric.findings[0]!;
const MODEL_CITE = fabric.routes["core1"]![0]!.cite; // resolves by path: routes.core1[0]

describe("citation resolution has two honest layers", () => {
  it("resolves a citation that names a path inside the compiled model", () => {
    const r = resolveCitation(MODEL_CITE);
    expect(r.kind).toBe("model");
    expect(r.modelPath).toBe(MODEL_CITE);
    expect(r.record).toBeDefined();
  });

  it("resolves a source-snapshot citation to the compiled record that carries it", () => {
    /* The finding's cite points into the SOURCE snapshot (`punchlist[0]`), which this build does
       not bundle. Reporting that as broken would be a false alarm on 628 of 652 citations. */
    const r = resolveCitation(FIRST_FINDING.cite);
    expect(r.kind).toBe("bearer");
    expect(r.modelPath).toBe("findings[0]");
    expect((r.record as { id: string }).id).toBe(FIRST_FINDING.id);
  });

  it("reports a citation that names nothing at all as unresolved", () => {
    const r = resolveCitation("no_such_collection[9].nowhere");
    expect(r.kind).toBe("unresolved");
    expect(r.record).toBeUndefined();
    expect(r.modelPath).toBeNull();
  });

  it("lets the reader step between every record that answers one citation", () => {
    /* Five citations in the shipped data are carried by two records each: the ACL line and the ACL
       finding about it. Both are real answers and the reader chooses; a switcher that ignored the
       choice would be a control that does nothing. */
    const shared = [...citeBearers().entries()].find(([c, paths]) => paths.length > 1 && c !== "");
    expect(
      shared,
      "the real data must contain a citation carried by more than one record",
    ).toBeTruthy();
    const [cite] = shared!;
    const candidates = citationCandidates(cite);
    expect(candidates.length).toBeGreaterThan(1);
    expect(resolveCitation(cite, 0).modelPath).toBe(candidates[0]);
    expect(resolveCitation(cite, 1).modelPath).toBe(candidates[1]);
    expect(resolveCitation(cite, 0).record).not.toBe(resolveCitation(cite, 1).record);
    // Out-of-range clamps to the last candidate rather than falling off into "unresolved".
    expect(resolveCitation(cite, 99).modelPath).toBe(candidates[candidates.length - 1]);
  });

  it("indexes every citation in the compiled model, so no claim is silently unauditable", () => {
    const index = citeBearers();
    const cites = new Set<string>();
    const walk = (v: unknown): void => {
      if (Array.isArray(v)) {
        v.forEach(walk);
        return;
      }
      if (typeof v !== "object" || v === null) return;
      const rec = v as Record<string, unknown>;
      if (typeof rec["cite"] === "string") cites.add(rec["cite"]);
      for (const k of Object.keys(rec)) walk(rec[k]);
    };
    walk(fabric as unknown);
    /* The sidecar documents the forwarding engine reads (every src/forwarding/*.json that binds the
       snapshot bytes) are citation bearers too — the engine's evidence cites them (critic B6). */
    for (const doc of Object.values(import.meta.glob("../forwarding/*.json", { eager: true, import: "default" }))) {
      if (typeof (doc as { meta?: { sourceSha256?: unknown } }).meta?.sourceSha256 === "string") walk(doc);
    }
    expect(cites.size).toBeGreaterThan(100);
    const missing = [...cites].filter((c) => resolveCitation(c).kind === "unresolved");
    expect(missing, `citations no record in this build can answer:\n${missing.join("\n")}`).toEqual(
      [],
    );
    expect(index.size).toBe(cites.size);
  });
});

describe("the Data tab shows the record behind a claim", () => {
  it("renders the resolved record as key/value rows", () => {
    const c = mount(<Inspector cite={FIRST_FINDING.cite} forceOpen />);
    const body = text(panel(c, "data"));
    expect(body).toContain("severity");
    expect(body).toContain(FIRST_FINDING.title);
    expect(body).toContain("findings[0]");
  });

  it("renders a null field through the not-observed treatment, never as a blank cell", () => {
    /* F001 carries `wave: null`. A blank cell there would read as "no wave needed"; the record
       actually says nobody recorded one. */
    expect(FIRST_FINDING.wave).toBeNull();
    const c = mount(<Inspector cite={FIRST_FINDING.cite} forceOpen />);
    const rows = [...(panel(c, "data")?.querySelectorAll(".insp-kv__row") ?? [])];
    const waveRow = rows.find((r) => text(r.querySelector(".insp-kv__key")) === "wave");
    expect(waveRow, "the null field must still be listed, not omitted").toBeTruthy();
    expect(waveRow!.querySelector('[data-unobserved="true"]')).toBeTruthy();
    expect(text(waveRow!)).toContain("not observed");
  });

  it("renders a STRUCTURAL null as not applicable, not as not observed (B1)", () => {
    /* `deny ip any any` rendered "sport: not observed", and a connected route "nextHop: not
       observed" — nothing is missing in either; the record's shape says the field cannot apply. */
    const rowsOf = (cite: string): Element[] => {
      const c = mount(<Inspector cite={cite} forceOpen />);
      return [...(panel(c, "data")?.querySelectorAll(".insp-kv__row") ?? [])];
    };
    const pick = (rows: Element[], key: string): Element => {
      const row = rows.find((r) => text(r.querySelector(".insp-kv__key")) === key);
      expect(row, key).toBeTruthy();
      return row!;
    };
    const acl = rowsOf("acls.core1.PROTECT_SERVERS[3]");
    for (const key of ["sport", "dport", "icmpType"]) {
      const row = pick(acl, key);
      expect(row.querySelector('[data-unobserved="true"]'), key).toBeNull();
      expect(row.querySelector('[data-not-applicable="true"]'), key).toBeTruthy();
    }
  });

  it("renders a connected route's missing next hop as not applicable (B1)", () => {
    const rowsOf = (cite: string): Element[] => {
      const c = mount(<Inspector cite={cite} forceOpen />);
      return [...(panel(c, "data")?.querySelectorAll(".insp-kv__row") ?? [])];
    };
    const pick = (rows: Element[], key: string): Element => {
      const row = rows.find((r) => text(r.querySelector(".insp-kv__key")) === key);
      expect(row, key).toBeTruthy();
      return row!;
    };
    const connected = fabric.routes["core1"]!.findIndex((r) => r.source === "connected" && r.nextHop === null);
    expect(connected).toBeGreaterThanOrEqual(0);
    const nh = pick(rowsOf(`routes.core1[${connected}]`), "nextHop");
    expect(text(nh)).toContain("a connected route has no next hop");
    expect(nh.querySelector('[data-unobserved="true"]')).toBeNull();
  });

  it("keeps a null that MAY be missing as not observed — a port operator on the line, an ICMP line", () => {
    const { notApplicableReason } = claims;
    expect(notApplicableReason({ action: "permit", raw: "permit tcp any any eq 443", proto: "tcp", unevaluable: false, dport: null }, "dport")).toBeNull();
    expect(notApplicableReason({ action: "permit", raw: "permit icmp any any", proto: "icmp", unevaluable: false, icmpType: null }, "icmpType")).toBeNull();
    expect(notApplicableReason({ action: "permit", raw: "permit tcp any any", proto: "tcp", unevaluable: true, dport: null }, "dport")).toBeNull();
    expect(notApplicableReason({ prefix: "0.0.0.0/0", source: "static", nextHop: null }, "nextHop")).toBeNull();
    expect(notApplicableReason({ action: "permit", raw: null, proto: "ip", unevaluable: false, sport: null }, "sport")).toBeNull();
    // A source-port operator (before the destination) keeps a null sport an absence.
    expect(notApplicableReason({ action: "permit", raw: "permit udp any eq 53 any", proto: "udp", unevaluable: false, sport: null }, "sport")).toBeNull();
    // A port list this grammar refuses is not read as "no constraint".
    expect(notApplicableReason({ action: "permit", raw: "permit tcp any any eq 80 443", proto: "tcp", unevaluable: false, sport: null }, "sport")).toBeNull();
  });

  it("reads a port operator by POSITION: a destination 'eq' says nothing about the source port (2026-09-22 auditor, B1)", () => {
    const { notApplicableReason } = claims;
    const line = fabric.acls["core1"]!["PROTECT_SERVERS"]![0]!;
    expect(line.raw).toBe("permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 443");
    expect(line.sport).toBeNull();
    expect(notApplicableReason(line, "sport")).toMatch(/no source-port constraint/);
    expect(notApplicableReason({ action: "permit", raw: "permit tcp any eq 1024 any", proto: "tcp", unevaluable: false, dport: null }, "dport")).toMatch(/no destination-port constraint/);
    // And in the rendered Inspector the row is not-applicable, not "not observed".
    const c = mount(<Inspector cite={line.cite} forceOpen />);
    const row = [...(panel(c, "data")?.querySelectorAll(".insp-kv__row") ?? [])].find((r) => text(r.querySelector(".insp-kv__key")) === "sport");
    expect(row).toBeTruthy();
    expect(row!.querySelector('[data-unobserved="true"]')).toBeNull();
    expect(row!.querySelector('[data-not-applicable="true"]')).toBeTruthy();
  });

  /* AMENDED 2026-09-23, with evidence. This used to pin the reading "0 — a connected route's
     administrative distance by definition". The acceptance report (B1, "allows no inference
     exemption") rejected exactly that wording: the record carries no number, and the value slot put
     the digit 0 in it. The doctrine this test guards is unchanged — a structural null is NOT "not
     observed" — and is still asserted below; only the words in the value slot changed, to "not
     recorded", with the platform convention stated as the reason. */
  it("renders a connected route's missing administrative distance as not recorded — never as 0, and not as not observed", () => {
    const { notApplicableReason } = claims;
    const i = fabric.routes["core1"]!.findIndex((r) => r.source === "connected" && r.adminDistance === null);
    expect(i, "precondition: a connected route with no AD in the record").toBeGreaterThanOrEqual(0);
    expect(notApplicableReason(fabric.routes["core1"]![i], "adminDistance")).toMatch(/^not recorded — .*a connected route's administrative distance is zero by platform convention/);
    expect(notApplicableReason(fabric.routes["core1"]![i], "adminDistance")).not.toMatch(/^0\b/);
    expect(notApplicableReason({ prefix: "0.0.0.0/0", source: "static", adminDistance: null }, "adminDistance")).toBeNull();
    const c = mount(<Inspector cite={`routes.core1[${i}]`} forceOpen />);
    const row = [...(panel(c, "data")?.querySelectorAll(".insp-kv__row") ?? [])].find((r) => text(r.querySelector(".insp-kv__key")) === "adminDistance");
    expect(row!.querySelector('[data-unobserved="true"]')).toBeNull();
  });

  it("distinguishes an empty array from an unobserved one", () => {
    const c = mount(<Inspector cite={FIRST_FINDING.cite} forceOpen />);
    const rows = [...(panel(c, "data")?.querySelectorAll(".insp-kv__row") ?? [])];
    const devicesRow = rows.find((r) => text(r.querySelector(".insp-kv__key")) === "devices");
    expect(text(devicesRow!)).toContain(FIRST_FINDING.devices[0]!);
    expect(devicesRow!.querySelector('[data-unobserved="true"]')).toBeNull();
  });

  it("copies exactly the record it displayed", () => {
    const c = mount(<Inspector cite={FIRST_FINDING.cite} forceOpen />);
    const btn = [...c.querySelectorAll("button")].find((b) => text(b).includes("Copy record"));
    click(btn!);
    expect(writeText).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(writeText.mock.calls[0]![0]) as { id: string };
    expect(sent.id).toBe(FIRST_FINDING.id);
  });
});

describe("a broken evidence chain is loud", () => {
  it("renders an alert naming the citation, and shows no record", () => {
    const c = mount(<Inspector cite="no_such_collection[9].nowhere" forceOpen />);
    const alert = c.querySelector('[role="alert"]');
    expect(alert, "an unresolvable citation must announce itself").toBeTruthy();
    expect(text(alert)).toContain("Broken evidence chain");
    expect(text(alert)).toContain("no_such_collection[9].nowhere");
    expect(text(panel(c, "data"))).toContain("There is no record to show");
  });

  it("renders no alert for a citation that does resolve — the warning is not decoration", () => {
    const c = mount(<Inspector cite={FIRST_FINDING.cite} forceOpen />);
    expect(c.querySelector('[role="alert"]')).toBeNull();
  });
});

describe("the Provenance tab answers 'where exactly did this come from'", () => {
  it("shows the source file, its digest and byte length, read from the model", () => {
    const c = mount(<Inspector cite={FIRST_FINDING.cite} forceOpen />);
    const body = text(panel(c, "provenance"));
    expect(body).toContain(fabric.meta.source);
    expect(body).toContain(fabric.meta.sourceSha256);
    expect(body).toContain(fabric.meta.sourceBytes.toLocaleString("en-GB"));
    expect(body).toContain(fabric.meta.schema!);
    expect(body).toContain(fabric.meta.collectedAt!);
    expect(body).toContain(fabric.meta.scriptVersion!);
    expect(body).toContain("tools/compile-snapshot.mjs");
    expect(body).toContain(FIRST_FINDING.cite);
  });

  /* O15: the digest and the byte count are taken over the LF-normalised form (tools/source-binding.mjs),
     not over the raw bytes of a Windows (CRLF) checkout, which are longer. A page that says "those
     exact bytes" without naming the form sends a reader to hash the wrong file. */
  it("names the byte form its digest and byte count are taken over", () => {
    expect(fabric.meta.sourceDigestForm).toBe("lf-normalised");
    const c = mount(<Inspector cite={FIRST_FINDING.cite} forceOpen />);
    const p = panel(c, "provenance")!;
    const labels = [...p.querySelectorAll("dt")].map((d) => d.textContent ?? "");
    expect(labels).toContain("Source sha256 (LF-normalised)");
    expect(labels).toContain("Source bytes (LF-normalised)");
    const body = text(p);
    expect(body).toContain("LF-normalised form");
    expect(body).toContain("git cat-file blob HEAD:");
    expect(body).toContain("a CRLF copy on disk is longer than that count");
    expect(body).toContain("Recompile from a file whose LF-normalised form has that digest");
  });

  it("says which layer answered the citation rather than implying the source was read", () => {
    const c = mount(<Inspector cite={FIRST_FINDING.cite} forceOpen />);
    expect(text(panel(c, "provenance"))).toContain("the compiled record carrying it");
  });
});

describe("the Coverage tab is the coverage-honesty guarantee, inspectable", () => {
  it("lists every host with no collected RIB, and the count matches the list", () => {
    const c = mount(<Inspector forceOpen />);
    const body = panel(c, "coverage")!;
    const section = [...body.querySelectorAll(".insp-gap")].find((s) =>
      text(s.querySelector(".insp-gap__title")).includes("no collected RIB"),
    );
    expect(section).toBeTruthy();
    const expected = fabric.devices.filter((d) => !(d.host in fabric.routes)).map((d) => d.host);
    const items = [...section!.querySelectorAll(".insp-gap__item")].map((li) => text(li));
    expect(items.sort()).toEqual([...expected].sort());
    expect(text(section!.querySelector(".insp-gap__count"))).toBe(
      `${expected.length} of ${fabric.devices.length}`,
    );
  });

  it("lists the links whose centrality was never computed", () => {
    const c = mount(<Inspector forceOpen />);
    const body = panel(c, "coverage")!;
    const section = [...body.querySelectorAll(".insp-gap")].find((s) =>
      text(s.querySelector(".insp-gap__title")).includes("no centrality"),
    );
    const uncounted = fabric.links.filter((l) => l.isBridge === null);
    expect(uncounted.length).toBeGreaterThan(0);
    expect(section!.querySelectorAll(".insp-gap__item")).toHaveLength(uncounted.length);
    expect(text(section!)).toContain(uncounted[0]!.id);
  });

  /**
   * Widened from "every line the PRODUCER flagged" to "every line ANY of the three analyses
   * cannot decide". The old form passed while the tab named exactly one line — `core1 MGMT_IN[0]`,
   * which this engine resolves and decides — and silently omitted the three lines the engine
   * actually refuses. See `src/core/acl-coverage.ts`.
   */
  it("names every ACL line that cannot be decided, by any of the three analyses", () => {
    const c = mount(<Inspector forceOpen />);
    const body = text(panel(c, "coverage"));
    const u = aclUndecidability();
    expect(u.count).toBeGreaterThan(0);
    for (const m of u.members) expect(body, `${m.label} is undecidable but unnamed`).toContain(m.label);
    expect(u.engineRefused.length).toBeGreaterThan(0);
  });

  it("reconciles the snapshot's own counters against the arrays and reports agreement per row", () => {
    const c = mount(<Inspector forceOpen />);
    const table = panel(c, "coverage")!.querySelector(".insp-table")!;
    const rows = [...table.querySelectorAll("tbody tr")];
    expect(rows.length).toBeGreaterThan(8);
    const byLabel = new Map(rows.map((r) => [text(r.querySelector("th")), r]));
    const ribRow = byLabel.get("hostsWithRoutes")!;
    const cells = [...ribRow.querySelectorAll("td")].map((td) => text(td));
    expect(cells[0]).toBe(String(fabric.coverage.hostsWithRoutes));
    expect(cells[1]).toBe(String(Object.keys(fabric.routes).length));
    // Whatever the data says, the verdict is a WORD, never a colour alone. It is the LAST cell:
    // a "what this can catch" column sits between the derived figure and the verdict.
    const verdict = cells[cells.length - 1]!;
    expect(verdict.startsWith("agrees") || verdict.startsWith("DISAGREES")).toBe(true);
  });

  /**
   * THE DEFECT this pins. The reconciliation headline read "0 of 11 disagree" above prose claiming
   * the snapshot ships its own coverage counters and that each is independently recomputed. Both
   * halves were false: the snapshot ships none of them — `tools/compile-snapshot.mjs` computes
   * every "Stated" value — and nine of the eleven rows recomputed with the byte-identical
   * expression the compiler used. It was a green zero no data could have turned red, presented as
   * a cross-verification.
   */
  it("does not present a self-check as an independent cross-verification", () => {
    const c = mount(<Inspector forceOpen />);
    const section = panel(c, "coverage")!.querySelector(".insp-gap--recon")!;
    const said = text(section);

    /* The false provenance claim must be gone. */
    expect(said).not.toContain("The snapshot ships its own coverage counters");

    const rows = [...section.querySelectorAll("tbody tr")];
    const kinds = rows.map((r) => r.getAttribute("data-kind"));
    expect(kinds.every((k) => k !== null), "every row must declare what it can catch").toBe(true);
    expect(kinds).toContain("self-check");
    expect(
      kinds.filter((k) => k === "independent").length,
      "a reconciliation with no independent comparison is not a reconciliation",
    ).toBeGreaterThan(0);

    /* The headline counts only the comparisons capable of disagreeing about the model. */
    const independent = kinds.filter((k) => k === "independent").length;
    expect(said).toContain(`of ${independent} independent comparisons`);

    /* And on this snapshot those comparisons DO disagree — the success path of this check has
       actually executed, which is the whole point. */
    const disagreeing = rows.filter(
      (r) => r.getAttribute("data-kind") === "independent" && r.getAttribute("data-disagree") === "true",
    );
    expect(
      disagreeing.length,
      "the independent rows all agree, so this check has still never failed — verify the comparison is real",
    ).toBeGreaterThan(0);
  });

  it("an empty gap category says so in words rather than rendering nothing", () => {
    /* A category with no members is a positive statement about this snapshot. Rendering it as an
       absent section would make the tab look shorter the better the coverage got — and identical
       to a section that failed to render. */
    const c = mount(<Inspector forceOpen />);
    const sections = [...panel(c, "coverage")!.querySelectorAll(".insp-gap:not(.insp-gap--recon)")];
    expect(sections.length).toBeGreaterThan(5);
    for (const s of sections) {
      const items = s.querySelectorAll(".insp-gap__item").length;
      const none = s.querySelector(".insp-gap__none");
      expect(items > 0 || none !== null).toBe(true);
    }
  });

  it("the compiled coverage record's aclLinesUnevaluable is labelled as the parser's flag, beside the union", () => {
    /* Review item 13 (2026-09-22): the compiled coverage record read `aclLinesUnevaluable 1` while the
       status bar said 6 of 12 lines cannot be decided. The field is the collector's parser flag
       only (core/acl-coverage.ts); read bare, it understates the undecidable surface sixfold. */
    const u = aclUndecidability();
    expect(u.count, "this test needs the flag and the union to differ").not.toBe(fabric.coverage.aclLinesUnevaluable);
    const c = mount(<Inspector cite="coverage" forceOpen />);
    const data = panel(c, "data")!;
    const row = [...data.querySelectorAll(".insp-kv__row")].find((r) => text(r.querySelector("dt")) === "aclLinesUnevaluable");
    expect(row, "the coverage record renders its aclLinesUnevaluable field").toBeTruthy();
    const said = text(row!.querySelector("dd"));
    expect(said).toContain(String(fabric.coverage.aclLinesUnevaluable));
    expect(said).toContain("parser");
    expect(said).toContain(`${u.count} of ${u.total}`);
  });

  it("the JSON tab annotates the same field the same way — the whole fabric.json is shown there too", () => {
    /* The Data tab's note did not reach the JSON tab, which renders all of fabric.json: there the
       counter still read bare, `aclLinesUnevaluable: 1`, beside a status bar saying 6 of 12. */
    const u = aclUndecidability();
    const c = mount(<Inspector cite="coverage" forceOpen />);
    const json = panel(c, "json")!;
    const coverageRow = json.querySelector<HTMLElement>('[data-node-id="coverage"]');
    expect(coverageRow, "the JSON tab renders the coverage record").toBeTruthy();
    if (coverageRow!.getAttribute("aria-expanded") !== "true") act(() => coverageRow!.click());
    const row = json.querySelector('[data-node-id="coverage.aclLinesUnevaluable"]');
    expect(row, "the JSON tab renders coverage.aclLinesUnevaluable").toBeTruthy();
    const note = text(row!.querySelector(".jsonview__note"));
    expect(note).toContain("parser flag only");
    expect(note).toContain("aclUndecidability()");
    expect(note).toContain(`${u.count} of ${u.total}`);
  });
});

describe("JsonView per-path annotations", () => {
  it("draws a note on exactly the annotated row, and on no other", () => {
    const c = mount(
      <JsonView value={{ a: { b: 1, c: 2 } }} rootLabel="doc.json" label="doc" citedPath="a.b" annotations={{ "a.b": "only here" }} />,
    );
    const notes = [...c.querySelectorAll(".jsonview__note")];
    expect(notes.map((n) => n.closest("[data-node-id]")?.getAttribute("data-node-id"))).toEqual(["a.b"]);
    expect(text(notes[0]!)).toBe("only here");
  });
});

describe("the panel is a dock, not a detour", () => {
  it("opening it preserves the investigation", () => {
    act(() => {
      useInvestigation.getState().selectDevice("core1");
      useInvestigation.getState().selectFinding(FIRST_FINDING.id);
    });
    const before = useInvestigation.getState();
    const snapshot = {
      deviceId: before.deviceId,
      findingId: before.findingId,
      query: before.query,
      surface: before.surface,
      flow: before.flow,
    };
    mount(<Inspector />);
    act(() => openInspector(FIRST_FINDING.cite));
    const after = useInvestigation.getState();
    expect(after.deviceId).toBe(snapshot.deviceId);
    expect(after.findingId).toBe(snapshot.findingId);
    expect(after.query).toBe(snapshot.query);
    expect(after.surface).toBe(snapshot.surface);
    expect(after.flow).toBe(snapshot.flow);
    expect(after.inspectorOpen).toBe(true);
  });

  it("falls back to the current selection when opened with no citation of its own", () => {
    act(() => useInvestigation.getState().selectFinding(FIRST_FINDING.id));
    const c = mount(<Inspector forceOpen />);
    expect(text(c.querySelector(".inspector__head"))).toContain(FIRST_FINDING.cite);
  });

  it("says so plainly when there is nothing to inspect, instead of rendering an empty table", () => {
    const c = mount(<Inspector forceOpen />);
    expect(text(c.querySelector(".inspector__head"))).toContain("Nothing is selected");
    expect(text(panel(c, "data"))).toContain("No citation is active");
  });

  it("implements the APG tabs contract", () => {
    const c = mount(<Inspector cite={MODEL_CITE} forceOpen />);
    const list = c.querySelector('[role="tablist"]')!;
    expect(list.getAttribute("aria-label")).toBeTruthy();
    const data = tabFor(c, "data");
    expect(data.getAttribute("aria-selected")).toBe("true");
    expect(data.getAttribute("aria-controls")).toBe("inspector-panel-data");
    expect(data.tabIndex).toBe(0);
    expect(tabFor(c, "json").tabIndex).toBe(-1);
    key(data, "ArrowRight");
    expect(tabFor(c, "provenance").getAttribute("aria-selected")).toBe("true");
    expect(panel(c, "data")!.hidden).toBe(true);
    key(tabFor(c, "provenance"), "End");
    expect(tabFor(c, "json").getAttribute("aria-selected")).toBe("true");
  });

  it("offers a keyboard route to every drag on the resize divider (WCAG 2.5.7)", () => {
    const c = mount(<Inspector cite={MODEL_CITE} forceOpen />);
    const sep = c.querySelector<HTMLElement>('[role="separator"]')!;
    expect(sep.tabIndex).toBe(0);
    const start = Number(sep.getAttribute("aria-valuenow"));
    key(sep, "ArrowUp");
    expect(Number(sep.getAttribute("aria-valuenow"))).toBeGreaterThan(start);
    key(sep, "Home");
    expect(sep.getAttribute("aria-valuenow")).toBe(sep.getAttribute("aria-valuemin"));
    key(sep, "End");
    expect(sep.getAttribute("aria-valuenow")).toBe(sep.getAttribute("aria-valuemax"));
  });
});

/* Acceptance D3: closing the dock gives focus back through the ONE focus-return owner. MEASURED on
   the preview build before this was routed (review/audit-d3-focus.mjs): every Inspector close path
   landed on <body> — an Inspector opened with `i` has no `openInspector` capture, and one whose
   invoker unmounted focused nothing. */
describe("closing the Inspector never drops focus to <body> (D3)", () => {
  const extras: HTMLElement[] = [];
  afterEach(() => {
    for (const el of extras.splice(0)) el.remove();
  });
  const addButton = (label: string): HTMLButtonElement => {
    const b = document.createElement("button");
    b.textContent = label;
    document.body.appendChild(b);
    extras.push(b);
    return b;
  };
  const setOpen = (v: boolean): void => {
    act(() => useInvestigation.getState().setInspectorOpen(v));
  };

  it("returns to the element focused when it opened, even when opened without openInspector (the `i` path)", () => {
    const c = mount(<Inspector cite={MODEL_CITE} />);
    const invoker = addButton("invoker");
    invoker.focus();
    setOpen(true);
    expect(c.querySelector('[role="tablist"]')!.contains(document.activeElement)).toBe(true);
    setOpen(false);
    expect(document.activeElement).toBe(invoker);
  });

  it("falls back to the stage when the invoker unmounted while the dock was open", () => {
    const stage = document.createElement("div");
    stage.id = "stage";
    stage.tabIndex = -1;
    document.body.appendChild(stage);
    extras.push(stage);
    mount(<Inspector />);
    const invoker = addButton("invoker");
    invoker.focus();
    act(() => openInspector(MODEL_CITE));
    invoker.remove();
    setOpen(false);
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(stage);
  });

  it("does not steal focus back when the reader closed it by moving focus elsewhere", () => {
    mount(<Inspector />);
    const invoker = addButton("invoker");
    const elsewhere = addButton("elsewhere");
    invoker.focus();
    act(() => openInspector(MODEL_CITE));
    elsewhere.focus();
    setOpen(false);
    expect(document.activeElement).toBe(elsewhere);
  });
});

/* ══ the JSON tree ═══════════════════════════════════════════════════════════ */

describe("JsonView is a real tree over the real document", () => {
  const treeRows = (c: HTMLElement): HTMLElement[] => [
    ...c.querySelectorAll<HTMLElement>('[role="treeitem"]'),
  ];
  const rowFor = (c: HTMLElement, id: string): HTMLElement => {
    const el = treeRows(c).find((r) => r.dataset["nodeId"] === id);
    if (!el) throw new Error(`no row ${id}`);
    return el;
  };

  it("finds the ancestors of a path by walking the document, not by splitting the string", () => {
    expect(ancestorsOf(fabric as unknown, "findings[0].title")).toEqual([
      "",
      "findings",
      "findings[0]",
    ]);
    expect(ancestorsOf(fabric as unknown, "findings[0].nope")).toBeNull();
  });

  it("pre-expands and marks the cited path", () => {
    const c = mount(
      <JsonView
        value={fabric as unknown}
        rootLabel="fabric.json"
        label="doc"
        citedPath="findings[0].title"
      />,
    );
    const cited = rowFor(c, "findings[0].title");
    expect(cited.dataset["cited"]).toBe("true");
    expect(text(cited)).toContain("cited here");
    expect(text(cited)).toContain(FIRST_FINDING.title);
    expect(rowFor(c, "findings").getAttribute("aria-expanded")).toBe("true");
  });

  it("carries the ARIA a flat tree needs to convey its shape", () => {
    const c = mount(
      <JsonView
        value={fabric as unknown}
        rootLabel="fabric.json"
        label="doc"
        citedPath="findings[0]"
      />,
    );
    const row = rowFor(c, "findings[0]");
    expect(row.getAttribute("aria-level")).toBe("3");
    expect(row.getAttribute("aria-posinset")).toBe("1");
    expect(row.getAttribute("aria-setsize")).toBe(String(fabric.findings.length));
    expect(c.querySelector('[role="tree"]')!.getAttribute("aria-label")).toBe("doc");
  });

  it("navigates with the APG treeview keys", () => {
    const c = mount(<JsonView value={fabric as unknown} rootLabel="fabric.json" label="doc" />);
    const root = rowFor(c, "");
    expect(root.tabIndex).toBe(0);
    key(root, "ArrowDown");
    expect(rowFor(c, "meta").tabIndex).toBe(0);
    // Right on a collapsed container expands it; right again steps into the first child.
    key(rowFor(c, "meta"), "ArrowRight");
    expect(rowFor(c, "meta").getAttribute("aria-expanded")).toBe("true");
    key(rowFor(c, "meta"), "ArrowRight");
    expect(rowFor(c, "meta.source").tabIndex).toBe(0);
    // Left from a leaf goes to the parent; left again collapses it.
    key(rowFor(c, "meta.source"), "ArrowLeft");
    expect(rowFor(c, "meta").tabIndex).toBe(0);
    key(rowFor(c, "meta"), "ArrowLeft");
    expect(rowFor(c, "meta").getAttribute("aria-expanded")).toBe("false");
    key(rowFor(c, "meta"), "End");
    expect(treeRows(c)[treeRows(c).length - 1]!.tabIndex).toBe(0);
  });

  it("renders a null leaf through the not-observed treatment", () => {
    const c = mount(
      <JsonView
        value={fabric as unknown}
        rootLabel="fabric.json"
        label="doc"
        citedPath="findings[0].wave"
      />,
    );
    const row = rowFor(c, "findings[0].wave");
    expect(row.querySelector('[data-unobserved="true"]')).toBeTruthy();
    expect(text(row)).toContain("not observed");
  });

  it("renders an empty array as an empty array, not as an absence", () => {
    const c = mount(<JsonView value={{ seen: [], missing: null }} rootLabel="doc" label="doc" />);
    key(rowFor(c, ""), "ArrowRight"); // root starts expanded; this is a no-op guard against regressions
    expect(text(rowFor(c, "seen"))).toContain("empty array");
    expect(rowFor(c, "seen").querySelector('[data-unobserved="true"]')).toBeNull();
    expect(rowFor(c, "missing").querySelector('[data-unobserved="true"]')).toBeTruthy();
  });

  it("searches keys and values across the whole document and reports the true total", () => {
    const res = searchDocument(fabric as unknown, "core1");
    expect(res.total).toBeGreaterThan(10);
    expect(res.hits.length).toBeLessThanOrEqual(res.total);
    expect(searchDocument(fabric as unknown, "zzz-no-such-token").total).toBe(0);
  });

  it("reveals a search match by expanding its ancestors", () => {
    const c = mount(<JsonView value={fabric as unknown} rootLabel="fabric.json" label="doc" />);
    const input = c.querySelector<HTMLInputElement>("input")!;
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, FIRST_FINDING.title);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const next = [...c.querySelectorAll("button")].find((b) => text(b) === "Next match")!;
    expect((next as HTMLButtonElement).disabled).toBe(false);
    click(next);
    const current = c.querySelector<HTMLElement>('[data-current-match="true"]');
    expect(current, "activating a match must reveal it").toBeTruthy();
    expect(current!.dataset["nodeId"]).toContain("findings[0]");
  });

  it("says plainly when a search matches nothing", () => {
    const c = mount(<JsonView value={fabric as unknown} rootLabel="fabric.json" label="doc" />);
    const input = c.querySelector<HTMLInputElement>("input")!;
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, "zzz-no-such-token");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(text(c.querySelector(".jsonview__hitcount"))).toContain(
      "No node in this document matches",
    );
  });

  it("copies the focused node's path with the c key", () => {
    const c = mount(
      <JsonView
        value={fabric as unknown}
        rootLabel="fabric.json"
        label="doc"
        citedPath="meta.schema"
      />,
    );
    key(rowFor(c, "meta.schema"), "c");
    expect(writeText).toHaveBeenCalledWith("meta.schema");
  });

  it("chunks an oversized array and states the remainder rather than truncating silently", () => {
    /* No array in the shipped document is this large, so this branch would otherwise never run.
       A guard whose success path was never executed is not a guard. */
    const big = { big: Array.from({ length: 500 }, (_, i) => `row-${i}`) };
    const c = mount(<JsonView value={big} rootLabel="doc" label="doc" />);
    click(rowFor(c, "big"));
    const more = c.querySelector(".jsonview__row--more")!;
    expect(text(more)).toContain("300 more of 500 not rendered");
    expect(c.querySelectorAll('[role="treeitem"]').length).toBeLessThan(250);
    click(more);
    expect(text(c.querySelector(".jsonview__row--more"))).toContain("100 more of 500");
  });
});

/* The determinism gate that used to live here — "neither panel file reads a clock or a random
   source" — has moved to src/core/determinism.test.ts and been rewritten. It was scoped to a
   two-name array in a tree of 50+ source files, it matched the two literal strings `Math.random`
   and `Date.now` rather than the class of clock and randomness sources, and its liveness proof
   exercised a second, differently-written visitor instead of the guard itself. It reported green
   over a `performance.now()` delta that was being rendered into the live region on every trace.
   A whole-tree rule cannot live in one panel's test file; that is how it stayed scoped to two. */

describe("Inspector — the stylesheet", () => {
  it("spends no literal colour, type size or duration", () => {
    const css = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "Inspector.css"),
      "utf8",
    );
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/font-size:\s*\d/);
    expect(css).not.toMatch(/(transition|animation)[^;]*\b\d+m?s\b/);
  });
});

describe("an ACL line record carries this model's evaluability, not only the collector's flag", () => {
  /* REGRESSION: acls.core1.INET_RETURN[1] (`… time-range BUSINESS_HOURS`) showed `unevaluable: false`
     and an empty qualifier list, reading as "evaluable", while the status bar and every trace
     listed it as undecidable. */
  it("marks a line the collector flagged false as undecidable to this model, with the reason", () => {
    const r = resolveCitation("acls.core1.INET_RETURN[1]");
    expect((r.record as { unevaluable: boolean }).unevaluable).toBe(false);
    const v = aclLineVerdict(r.modelPath, r.record);
    expect(v).not.toBeNull();
    expect(v!.evaluable).toBe(false);
    expect(v!.reason).toMatch(/time-range/);
  });

  it("returns null for a record that is not an ACL line", () => {
    const r = resolveCitation("routes.core1[0]");
    expect(aclLineVerdict(r.modelPath, r.record)).toBeNull();
  });
});
