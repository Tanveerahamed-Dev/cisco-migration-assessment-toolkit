/**
 * DevicePane.test.tsx — the behaviour of the device and evidence panes that a visual review
 * cannot see.
 *
 * Every test here runs against the REAL compiled snapshot (`src/data/fabric.json`), never a
 * hand-shaped fixture. A fabricated device in the shape the pane expects would agree with the
 * pane's own assumptions, and the defects worth catching on this surface are exactly the ones
 * where the real data does something the author did not picture: three devices with no score at
 * all, a physical-health row for a port that has no interface record, seventeen devices whose
 * role is null.
 *
 * No testing-library: React's own `act` over a real `createRoot` in jsdom, matching
 * `src/ui/primitives.test.tsx`.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fabric, interfacesOf, physicalByHost } from "../core/data";
import { useInvestigation } from "../core/store";
import { describeGolden } from "../test-support/golden-sample";
import { need } from "../test-support/trace-universe";
import { DevicePane, joinPorts, parseDeduction } from "./DevicePane";
import { EvidencePane, blocksFor, configEvidenceFor } from "./EvidencePane";

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

/* The store is a module singleton shared by every surface, so a test that leaves a selection
   behind changes what the NEXT test renders — and it would still pass, for the wrong reason.
   `reset()` deliberately does not clear `evidenceTab` (it is view state, not selection), so the
   tab is cleared here as well: without it a test that opened the ports tab silently decided which
   panel the next test was reading. */
beforeEach(() => {
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.getState().setEvidenceTab("summary");
  });
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

const panel = (c: HTMLElement, id: string): HTMLElement => {
  const el = c.querySelector<HTMLElement>(`#dp-panel-${id}`);
  if (!el) throw new Error(`panel ${id} is not in the DOM`);
  return el;
};

const key = (el: Element, k: string, opts: KeyboardEventInit = {}): void => {
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, ...opts }));
  });
};

/* ══ the data this file depends on, asserted rather than assumed ═══════════ */


/**
 * The densest host in the loaded snapshot — the one with the most port rows (interface records joined
 * with physical-health rows), ties broken by name — and its device id. These tests named core1 ("the
 * densest host in this snapshot"); reading it by that property keeps them true on any snapshot where
 * the property holds (phase 3 rename leg). The reference sample's answer is pinned in the golden block.
 */
const denseHost = (): string => {
  const hosts = [...new Set(fabric.devices.map((d) => d.host))].sort();
  let best: { host: string; n: number } | null = null;
  for (const h of hosts) {
    const n = joinPorts(h).length;
    if (best === null || n > best.n) best = { host: h, n };
  }
  expect(best, "precondition: the snapshot has devices").not.toBeNull();
  return best!.host;
};
const idOf = (host: string): string => {
  const d = fabric.devices.find((x) => x.host === host);
  expect(d, `precondition: ${host} is in the inventory`).toBeDefined();
  return d!.id;
};

describeGolden("the reference sample's densest host", () => {
  it("is core1", () => {
    expect(denseHost()).toBe("core1");
  });
});

describe("the real snapshot still has the shape these tests probe", () => {
  it("carries at least one device that was never collected, and it has no score", () => {
    const uncollected = fabric.devices.filter((d) => !d.collected);
    expect(uncollected.length).toBeGreaterThan(0);
    for (const d of uncollected) expect(d.score).toBeNull();
  });

  it("carries a host whose ACLs were collected and one whose were not", () => {
    expect(Object.keys(fabric.acls).length).toBeGreaterThan(0);
    expect(Object.keys(fabric.acls).length).toBeLessThan(fabric.devices.length);
  });
});

/* ══ absence is never health (acceptance B1) ═══════════════════════════════ */

describe("a device we never reached", () => {
  const host = fabric.devices.find((d) => !d.collected)?.host ?? "";

  it("says so at the top of the pane, not in a footnote", () => {
    act(() => { useInvestigation.getState().selectDevice(host); });
    const c = mount(<DevicePane />);
    const banner = panel(c, "summary").querySelector(".dp-banner--uncollected");
    expect(banner).not.toBeNull();
    expect(banner?.textContent ?? "").toContain("never reached");
    // First element of the panel: a reader must meet it before any field it qualifies.
    expect(panel(c, "summary").firstElementChild?.firstElementChild).toBe(banner);
  });

  it("renders every absent field as the words 'not observed', never blank and never zero", () => {
    act(() => { useInvestigation.getState().selectDevice(host); });
    const c = mount(<DevicePane />);
    const p = panel(c, "summary");
    const values = [...p.querySelectorAll<HTMLElement>(".dp-kv__v")];
    expect(values.length).toBeGreaterThan(8);
    for (const v of values) expect((v.textContent ?? "").trim()).not.toBe("");
    expect((p.textContent ?? "").match(/not observed/g)?.length ?? 0).toBeGreaterThanOrEqual(8);
  });

  it("does not render a missing health band as a passing grade", () => {
    act(() => { useInvestigation.getState().selectDevice(host); });
    const c = mount(<DevicePane />);
    const text = panel(c, "summary").textContent ?? "";
    expect(text).not.toMatch(/\b(Excellent|Good|Fair)\b/);
    expect(c.querySelector(".ui-band")).toBeNull();
  });

  it("reports an unknown port inventory rather than an empty one", () => {
    act(() => {
      useInvestigation.getState().selectDevice(host);
      useInvestigation.getState().setEvidenceTab("ports");
    });
    const c = mount(<DevicePane />);
    const text = panel(c, "ports").textContent ?? "";
    expect(text).toContain("not observed");
    expect(text).toMatch(/unknown rather than empty/);
  });
});

/* ══ the interface x physical-health outer join ════════════════════════════ */

describe("joinPorts", () => {
  it("keeps every port from both sides for every collected host", () => {
    for (const host of Object.keys(fabric.interfaces)) {
      const rows = joinPorts(host);
      const ports = new Set(rows.map((r) => r.port));
      for (const i of interfacesOf(host)) expect(ports.has(i.port)).toBe(true);
      for (const p of physicalByHost.get(host) ?? []) {
        if (p.port !== null) expect(ports.has(p.port)).toBe(true);
      }
    }
  });

  it("marks a one-sided row instead of dropping it", () => {
    // The densest host has physical-health rows for only some ports.
    const host = denseHost();
    const rows = joinPorts(host);
    const oneSided = rows.filter((r) => r.intf === null || r.phys === null);
    expect(oneSided.length).toBeGreaterThan(0);
    act(() => {
      useInvestigation.getState().selectDevice(idOf(host));
      useInvestigation.getState().setEvidenceTab("ports");
    });
    const c = mount(<DevicePane />);
    const p = panel(c, "ports");
    // Every one-sided row carries the absence mark in its own "Records" cell.
    expect(p.querySelectorAll('[data-unobserved="true"]').length).toBeGreaterThanOrEqual(oneSided.length);
  });
});

/* ══ the score and the deductions that produced it ═════════════════════════ */

describe("health deductions", () => {
  it("parses the engine's own point notation", () => {
    expect(parseDeduction("CL-01 Critical (-18)")).toEqual({
      raw: "CL-01 Critical (-18)",
      label: "CL-01 Critical",
      points: 18,
      crossLayerId: "CL-01",
    });
    expect(parseDeduction("no-ntp low (-1)").points).toBe(1);
    // A deduction with no point value keeps its text and reports the points as absent.
    expect(parseDeduction("something unpriced")).toEqual({
      raw: "something unpriced",
      label: "something unpriced",
      points: null,
      crossLayerId: null,
    });
  });

  it("states the residual between the itemised deductions and the published score", () => {
    const host = denseHost();
    const d = fabric.devices.find((x) => x.host === host);
    expect(d).toBeDefined();
    act(() => { useInvestigation.getState().selectDevice(idOf(host)); });
    const c = mount(<DevicePane />);
    const arith = panel(c, "summary").querySelector(".dp-arith")?.textContent ?? "";
    const sum = (d?.deductions ?? []).reduce(
      (a, s) => a + (parseDeduction(s).points ?? 0),
      0,
    );
    expect(arith).toContain(String(sum));
    // The gap is named, not reconciled away.
    expect(arith).toContain("shown rather than reconciled");
  });
});

/* ══ blast radius: ours and theirs, side by side ═══════════════════════════ */

describe("failure impact", () => {
  it("renders the snapshot's own number and ours without picking a winner", () => {
    act(() => { useInvestigation.getState().selectDevice(idOf(denseHost())); });
    const c = mount(<DevicePane />);
    const heads = [...panel(c, "summary").querySelectorAll(".dp-cmp__head")].map((h) => h.textContent);
    expect(heads).toHaveLength(2);
    expect(heads.join(" ")).toContain("failure_impact");
    expect(heads.join(" ")).toContain("blast radius");
  });

  // ImpactSection is unconditional on the summary panel, so "every device with an impact
  // comparison" is every device. One device per case (acceptance F2, W6 gate 2026-09-25: the loop
  // over every device was one unit of work), each mounted, read and unmounted: the pane's element
  // ids are fixed, and 26 live copies would make an id lookup ambiguous.
  it("has more than one device to compare", () => {
    expect(fabric.devices.length).toBeGreaterThan(1);
  });
  for (const d of fabric.devices) {
    it(`${d.host}: renders the impact comparison, with a disagreement block`, () => {
      act(() => { useInvestigation.getState().selectDevice(d.id); });
      const c = mount(<DevicePane />);
      const summary = panel(c, "summary");
      expect(summary.querySelectorAll(".dp-cmp__head").length, `${d.host}: every device renders the impact comparison`).toBeGreaterThan(0);
      const block = summary.querySelector(".dp-disagree");
      expect(block, `${d.host}: comparison without a disagreement block`).not.toBeNull();
      expect(block!.querySelector(".dp-disagree__head")?.textContent?.trim(), d.host).toBeTruthy();
    });
  }
});

/* ══ tabs: a tab with no evidence behind it is REACHABLE and explains itself ══
   The coverage sentence ("no ACL collected") lives on that tab and nowhere else on this surface,
   so anything that takes the tab out of the keyboard cycle deletes the fact for a keyboard or
   screen-reader user. It used to: the tab carried the native `disabled` attribute, which removed
   it from the tab order AND from the tablist's roving cycle. */

describe("evidence tabs", () => {
  it("keeps the ACL tab reachable on a host with no ACLs and puts the reason on the tab", () => {
    const host = fabric.devices.find((d) => d.collected && !fabric.acls[d.host])?.host ?? "";
    expect(host).not.toBe("");
    act(() => { useInvestigation.getState().selectDevice(host); });
    const c = mount(<DevicePane />);
    const tab = c.querySelector<HTMLButtonElement>("#dp-tab-acl");
    expect(tab).not.toBeNull();
    // Neither disabled nor aria-disabled: activating it renders the reason, so it WORKS.
    expect(tab?.disabled).toBe(false);
    expect(tab?.getAttribute("aria-disabled")).toBeNull();
    expect(tab?.textContent ?? "").toContain("no ACL collected");
  });

  it("includes the evidence-absent tab in the tablist's arrow-key cycle", () => {
    const host = fabric.devices.find((d) => d.collected && !fabric.acls[d.host])?.host ?? "";
    act(() => {
      useInvestigation.getState().selectDevice(host);
      useInvestigation.getState().setEvidenceTab("ports");
    });
    const c = mount(<DevicePane />);
    const list = c.querySelector<HTMLElement>('[role="tablist"]');
    expect(list).not.toBeNull();
    const ids = [...(list?.querySelectorAll<HTMLElement>('[role="tab"]') ?? [])].map((t) => t.id);
    const seen = new Set<string>();
    let from = c.querySelector<HTMLElement>("#dp-tab-ports");
    from?.focus();
    for (let i = 0; i < ids.length + 2; i++) {
      act(() => {
        (document.activeElement ?? from)?.dispatchEvent(
          new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
        );
      });
      seen.add(document.activeElement?.id ?? "");
    }
    expect(seen.has("dp-tab-acl")).toBe(true);
  });

  it("renders the reason in the panel when a shared link lands on an evidence-absent tab", () => {
    const host = fabric.devices.find((d) => d.collected && !fabric.acls[d.host])?.host ?? "";
    act(() => {
      useInvestigation.getState().selectDevice(host);
      useInvestigation.getState().setEvidenceTab("acl");
    });
    const c = mount(<DevicePane />);
    const p = panel(c, "acl");
    expect(p.textContent ?? "").toContain("not observed");
    expect(p.textContent ?? "").toContain("cannot be evaluated at all");
  });

  it("keeps the routing tab reachable on a host with no RIB, and says why", () => {
    const host = fabric.devices.find((d) => d.collected && !fabric.routes[d.host])?.host ?? "";
    act(() => {
      useInvestigation.getState().selectDevice(host);
      useInvestigation.getState().setEvidenceTab("routing");
    });
    const c = mount(<DevicePane />);
    const text = panel(c, "routing").textContent ?? "";
    expect(text).toContain("No routing table was collected");
    expect(text).toContain("unmodelled");
  });
});

/* ══ the APG data-grid contract ════════════════════════════════════════════ */

describe("the record grid keyboard contract", () => {
  const openPorts = (): HTMLElement => {
    act(() => {
      useInvestigation.getState().selectDevice(idOf(denseHost()));
      useInvestigation.getState().setEvidenceTab("ports");
    });
    const c = mount(<DevicePane />);
    const grid = panel(c, "ports").querySelector<HTMLElement>('[role="grid"]');
    if (!grid) throw new Error("no grid rendered");
    return grid;
  };

  const roving = (grid: HTMLElement): HTMLElement | null =>
    grid.querySelector<HTMLElement>('[tabindex="0"]');

  it("is one tab stop: exactly one cell carries tabindex=0", () => {
    const grid = openPorts();
    expect(grid.querySelectorAll('[tabindex="0"]')).toHaveLength(1);
  });

  it("declares the LOGICAL row and column counts", () => {
    const grid = openPorts();
    const rows = joinPorts(denseHost()).length;
    expect(grid.getAttribute("aria-rowcount")).toBe(String(rows + 1));
    expect(Number(grid.getAttribute("aria-colcount"))).toBeGreaterThan(5);
    const first = grid.querySelector('[role="row"]:nth-child(2)');
    expect(first?.getAttribute("aria-rowindex")).toBe("2");
  });

  it("clamps at the edges instead of wrapping", () => {
    const grid = openPorts();
    const start = roving(grid);
    expect(start?.dataset.r).toBe("0");
    expect(start?.dataset.c).toBe("0");
    key(start!, "ArrowLeft");
    expect(roving(grid)?.dataset.c).toBe("0");
    key(roving(grid)!, "ArrowUp");
    expect(roving(grid)?.dataset.r).toBe("0");
    key(roving(grid)!, "ArrowRight");
    expect(roving(grid)?.dataset.c).toBe("1");
  });

  it("moves five rows on Page Down and clamps at the last row", () => {
    const grid = openPorts();
    const rows = joinPorts(denseHost()).length;
    key(roving(grid)!, "PageDown");
    expect(roving(grid)?.dataset.r).toBe("5");
    // Enough Page Downs to overshoot the last row by a clear margin, and no more: each one is a
    // full re-render of the pane, and 40 of them made this test the slowest thing in the suite.
    const overshoot = Math.ceil(rows / 5) + 2;
    for (let i = 0; i < overshoot; i += 1) key(roving(grid)!, "PageDown");
    expect(roving(grid)?.dataset.r).toBe(String(rows));
  });

  it("honours Ctrl+End and Ctrl+Home", () => {
    const grid = openPorts();
    const rows = joinPorts(denseHost()).length;
    const cols = Number(grid.getAttribute("aria-colcount"));
    key(roving(grid)!, "End", { ctrlKey: true });
    expect(roving(grid)?.dataset.r).toBe(String(rows));
    expect(roving(grid)?.dataset.c).toBe(String(cols - 1));
    key(roving(grid)!, "Home", { ctrlKey: true });
    expect(roving(grid)?.dataset.r).toBe("0");
    expect(roving(grid)?.dataset.c).toBe("0");
  });

  it("uses real grid roles, with one rowheader per row", () => {
    const grid = openPorts();
    const bodyRows = [...grid.querySelectorAll('[role="row"]')].slice(1);
    expect(bodyRows.length).toBeGreaterThan(0);
    for (const row of bodyRows) {
      expect(row.querySelectorAll('[role="rowheader"]')).toHaveLength(1);
    }
  });
});

/* ══ the evidence chain ════════════════════════════════════════════════════ */

describe("configEvidenceFor", () => {
  /* Found by property (was the sample's "Gi1/0/38" by name; verifier V5, phase 3): a finding whose detail
     quotes one of the snapshot's collected ports as "<host> <port>", ending at a word boundary. The
     sample's own case is pinned in the golden block below. */
  const quotesAPort = (x: (typeof fabric.findings)[number]): boolean => {
    const d = x.detail ?? "";
    return Object.entries(fabric.interfaces).some(([h, recs]) =>
      recs.some((i) => {
        const k = `${h} ${i.port}`;
        const at = d.indexOf(k);
        return at !== -1 && !/[\w/.]/.test(d.charAt(at + k.length));
      }),
    );
  };
  it("resolves a finding that names a port to that port's real interface record", (ctx) => {
    const f = need(ctx, fabric.findings.find(quotesAPort), "finding whose detail quotes a collected port");
    const targets = configEvidenceFor(f);
    const ifaces = targets.filter((t) => t.kind === "interface");
    expect(ifaces.length).toBeGreaterThan(0);
    for (const t of ifaces) {
      // The cite must point at a record that genuinely exists, not at a constructed path.
      expect(interfacesOf(t.host).some((i) => i.cite === t.cite)).toBe(true);
    }
  });

  it("never invents a record: every returned cite resolves to a real collected record", () => {
    for (const f of fabric.findings) {
      for (const t of configEvidenceFor(f)) {
        if (t.kind === "interface") {
          expect(interfacesOf(t.host).some((i) => i.cite === t.cite)).toBe(true);
        } else if (t.kind === "acl") {
          expect(fabric.acls[t.host]).toBeDefined();
          expect(t.lines.length).toBeGreaterThan(0);
        } else {
          expect(t.entries.length).toBeGreaterThan(0);
        }
      }
    }
  });

  /* Pinned to known ids, not to "some finding came back empty": selecting a finding BECAUSE it
     returned nothing and then asserting it exists could only fail if every finding got evidence.
     The census below is the compiled snapshot's own: six findings quote a port in their detail;
     the other 140 name devices but no configuration line. F001 and F003 both name core1 (the host
     with the richest evidence), so returning its records for them would be exactly the guess this
     test forbids. */
  describeGolden("the reference sample's configuration-evidence census", () => {
  it("resolves the sample's Gi1/0/38 finding to that port's interface record", () => {
    const f = fabric.findings.find((x) => /\bGi1\/0\/38\b/.test(x.detail ?? ""));
    expect(f).toBeDefined();
    const ifaces = configEvidenceFor(f!).filter((t) => t.kind === "interface");
    expect(ifaces.length).toBeGreaterThan(0);
    for (const t of ifaces) expect(interfacesOf(t.host).some((i) => i.cite === t.cite)).toBe(true);
  });

  it("returns nothing for a finding that names no configuration, rather than guessing", () => {
    const byId = (id: string) => {
      const f = fabric.findings.find((x) => x.id === id);
      expect(f, `precondition: ${id} is in the snapshot`).toBeDefined();
      return f!;
    };
    for (const id of ["F001", "F003"]) {
      const f = byId(id);
      expect(f.devices, `precondition: ${id} names the host with the richest evidence`).toContain(denseHost());
      expect(configEvidenceFor(f)).toEqual([]);
    }
    const named = fabric.findings.filter((x) => configEvidenceFor(x).length > 0).map((x) => x.id);
    expect(named.sort()).toEqual(["F002", "F136", "F137", "F138", "F139", "F140"]);
  });
  });
});

describe("blocksFor", () => {
  const line = (index: number, match: boolean) => ({
    index,
    text: `line ${index}`,
    match,
    cite: `c${index}`,
    unevaluable: false,
  });

  it("shows everything when nothing matches, so an unsearched record is never truncated", () => {
    const blocks = blocksFor([line(0, false), line(1, false), line(2, false)]);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.lines).toHaveLength(3);
  });

  it("states the exact number of hidden lines rather than eliding silently", () => {
    const lines = Array.from({ length: 20 }, (_, i) => line(i, i === 10));
    const blocks = blocksFor(lines, 2);
    const hidden = blocks.filter((b) => b.kind === "elided").reduce((a, b) => a + b.hidden, 0);
    const shown = blocks.reduce((a, b) => a + b.lines.length, 0);
    expect(shown).toBe(5); // the match plus two either side
    expect(hidden).toBe(15);
    expect(shown + hidden).toBe(20);
  });
});

describe("EvidencePane", () => {
  const withFinding = (id: string): HTMLElement => {
    act(() => { useInvestigation.getState().selectFinding(id); });
    return mount(<EvidencePane />);
  };

  it("says a finding names no configuration line instead of hiding the affordance", () => {
    const f = fabric.findings.find((x) => configEvidenceFor(x).length === 0);
    expect(f).toBeDefined();
    const c = withFinding(f!.id);
    expect(c.textContent ?? "").toContain("names no configuration line");
  });

  it("renders a navigable control for every device the finding names", () => {
    const f = fabric.findings.find((x) => x.devices.length >= 2);
    expect(f).toBeDefined();
    const c = withFinding(f!.id);
    const buttons = [...c.querySelectorAll<HTMLButtonElement>(".ev-devices .ev-devbtn")];
    expect(buttons).toHaveLength(f!.devices.length);
    act(() => buttons[0]!.click());
    expect(useInvestigation.getState().deviceId).toBe(f!.devices[0]);
  });

  it("shows the layer composition of a cross-layer finding, with the join's own denominator", () => {
    const f = fabric.findings.find((x) => fabric.crossLayer.some((c) => c.title === x.title));
    expect(f).toBeDefined();
    const c = withFinding(f!.id);
    expect(c.querySelectorAll(".ev-layer").length).toBeGreaterThanOrEqual(2);
    expect(c.textContent ?? "").toContain("cross-layer records resolve to a finding this way");
  });

  it("opens the literal ACL text, with the record's own line indices", () => {
    const aclHost = Object.keys(fabric.acls)[0]!;
    const aclName = Object.keys(fabric.acls[aclHost]!)[0]!;
    const f = fabric.findings.find(
      (x) => x.devices.includes(aclHost) && [x.title, x.detail ?? ""].join(" ").includes(aclName),
    );
    // Not every snapshot names an ACL in a punchlist entry. When it does not, the pane must fall
    // back to the nearest record rather than leaving the reader with no route to the policy.
    const target = f ?? fabric.findings.find((x) => x.devices.includes(aclHost))!;
    const c = withFinding(target.id);
    const button = [...c.querySelectorAll<HTMLButtonElement>(".ev-cfgactions button")].find((b) =>
      (b.textContent ?? "").includes(aclName),
    );
    expect(button).toBeDefined();
    act(() => button!.click());
    const gutters = [...c.querySelectorAll(".ev-cfg__gutter")].map((g) => g.textContent);
    const real = fabric.acls[aclHost]![aclName]!.map((l) => String(l.index));
    expect(gutters).toEqual(real);
  });

  it("moves focus into the excerpt and returns it to the control that opened it", () => {
    const aclHost = Object.keys(fabric.acls)[0]!;
    const target = fabric.findings.find((x) => x.devices.includes(aclHost))!;
    const c = withFinding(target.id);
    const buttons = [...c.querySelectorAll<HTMLButtonElement>(".ev-cfgactions button")];
    expect(buttons.length).toBeGreaterThan(1);
    // Deliberately NOT the first button: focus must return to the control actually used.
    const trigger = buttons[1]!;
    act(() => trigger.click());
    expect(document.activeElement).toBe(c.querySelector(".ev-cfg__title"));
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    key(document.activeElement!, "Escape");
    expect(c.querySelector(".ev-cfg")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("offers a way in when nothing is selected, instead of an empty rail", () => {
    const c = mount(<EvidencePane />);
    expect(c.textContent ?? "").toContain("No finding is selected");
    const action = c.querySelector<HTMLButtonElement>(".ui-empty__action button");
    expect(action).not.toBeNull();
    act(() => action!.click());
    expect(useInvestigation.getState().findingId).not.toBeNull();
  });

  it("names a finding id from a stale link as missing rather than rendering a blank pane", () => {
    act(() => { useInvestigation.getState().selectFinding("F-does-not-exist"); });
    const c = mount(<EvidencePane />);
    expect(c.textContent ?? "").toContain("no such record exists in this snapshot");
  });
});

/* ══ two records, one field: disagreement is shown, never coalesced away ═══ */

describe("a port field both records carry and disagree on", () => {
  /* REGRESSION: the Duplex column rendered `intf.duplex ?? phys.duplex`, so on 73 ports where the
     interface record said "Full" and the physical-health row said "unknown" the table printed a
     clean "Full" — on hosts carrying an open duplex-mismatch finding. */
  it("renders both values on a real disagreeing port", () => {
    const hit = fabric.devices
      .flatMap((d) => joinPorts(d.host).map((r) => ({ host: d.host, r })))
      .find(({ r }) => r.intf?.duplex != null && r.phys?.duplex != null && r.intf.duplex.toLowerCase() !== r.phys.duplex.toLowerCase());
    expect(hit, "the snapshot should contain a port whose two records disagree on duplex").toBeDefined();
    const { host, r } = hit!;
    act(() => {
      useInvestigation.getState().selectDevice(host);
      useInvestigation.getState().setEvidenceTab("ports");
    });
    const c = mount(<DevicePane />);
    const split = [...panel(c, "ports").querySelectorAll<HTMLElement>(".dp-split[data-disagree='true']")].find((el) =>
      (el.textContent ?? "").includes(`interface ${r.intf!.duplex}, physical-health ${r.phys!.duplex}`),
    );
    expect(split).toBeDefined();
    expect(split!.textContent).toContain(r.intf!.duplex!);
    expect(split!.textContent).toContain(r.phys!.duplex!);
  });
});
