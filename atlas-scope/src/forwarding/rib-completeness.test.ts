/**
 * rib-completeness.test.ts — WHICH routing-protocol evidence can make a collected table read as
 * complete, and which can only leave it unknown.
 *
 * The old rule demanded that every protocol the snapshot names (the keys of `routing_neighbors`,
 * which the producer ALWAYS writes as {ospf, eigrp, bgp}) be `assessed` on every hop. `assessed`
 * needs a parsed neighbor, so the rule in effect demanded that every router run all three
 * protocols: a named set standing in for "the protocols this host runs". A switch that runs only
 * OSPF could never have a complete table, however carefully it was collected.
 *
 * The rule now reads the engine's own receipt (`cisco_toolkit/analyze.py`
 * compute_protocol_assessability): a family contributes no learned routes on a host ONLY when its
 * state is `captured_empty` — "a recognized command capture was empty", the neighbor table was
 * collected and holds nothing. Every other non-assessed state stays a reason the table is not known
 * to be complete, and names the assessability row that says so:
 *   - `captured_no_record` — output was captured but nothing parsed (possibly a parser gap), NOT empty;
 *   - `partial`, `capture_error`, `not_collected`, `analysis_unavailable`, a missing row, and any
 *     state this code has never seen.
 * An empty neighbor table beside routes of that family in the table is a contradiction between two
 * captures, and is named, not resolved in the table's favour.
 *
 * The adjacency rule (an adjacency exchanging routes while the table holds no route of its family)
 * is kept, and now covers the producer's actual encodings of "exchanging": OSPF `FULL/…`, EIGRP
 * `up <uptime>` (every listed EIGRP neighbor), and BGP's numeric State/PfxRcd — a number IS the
 * Established state, carrying the received-prefix count (the old /^(full|established)/ test never
 * matched a BGP peer from `show ip bgp summary`). A route's family is read from the engine's
 * route-source vocabulary, which sub-types a family as `<family>-<subtype>` (`ospf-ext2`,
 * `eigrp-external`), so an O E2 route is an OSPF route.
 *
 * The routing-completeness record is mocked with synthetic hosts ADDED to the real compiled file
 * (same source binding), so the real module is exercised through its public API.
 */
import { describe, expect, it, vi } from "vitest";

import realEvidence from "./rib-evidence.json";
import { fabric, routesOf } from "../core/data";

const fx = vi.hoisted(() => {
  const row = (protocol: string, state: string | null, i: number) => ({
    protocol,
    state,
    reason: `synthetic ${state}`,
    cite: `protocol_assessability.rows[${9000 + i}]`,
  });
  /** An adjacency as the compiler publishes it: the producer's record plus the neighbor's link
   *  address and the interface it formed on (`null` where the record carries none — EIGRP/BGP records
   *  name the neighbor BY its address, BGP records name no interface). Defaults put the neighbor on
   *  Gi1/0/1 at its own address, the link every fixture table below holds as connected 10.9.0.0/24. */
  const adj = (
    protocol: string,
    neighbor: string,
    state: string,
    host: string,
    i: number,
    link: { address?: string | null; interface?: string | null } = {},
  ) => ({
    protocol,
    neighbor,
    state,
    cite: `routing_neighbors.${host}.${protocol}[${i}]`,
    address: link.address === undefined ? neighbor : link.address,
    interface: link.interface === undefined ? "Gi1/0/1" : link.interface,
  });
  const route = (host: string, source: string, i: number, over: { prefix?: string; outIntf?: string | null } = {}) => ({
    prefix: over.prefix ?? `10.9.${i}.0/24`,
    source,
    nextHop: source === "connected" ? null : "10.9.0.254",
    outIntf: over.outIntf === undefined ? "Gi1/0/1" : over.outIntf,
    adminDistance: null,
    cite: `routes.${host}[${i}]`,
  });
  const hosts: Record<string, { protocols: unknown[]; adjacencies: unknown[]; overlay: unknown[] }> = {
    // Runs OSPF only; EIGRP/BGP neighbor tables captured and empty. The shape of dist1 after E2.
    "t-ospf-only": {
      protocols: [row("OSPF", "assessed", 0), row("BGP", "captured_empty", 1), row("EIGRP", "captured_empty", 2)],
      adjacencies: [adj("ospf", "10.9.0.1", "FULL/  -", "t-ospf-only", 0)],
      overlay: [],
    },
    // Output present but nothing parsed: NOT evidence of absence.
    "t-no-record": {
      protocols: [row("OSPF", "assessed", 3), row("BGP", "captured_no_record", 4), row("EIGRP", "captured_empty", 5)],
      adjacencies: [adj("ospf", "10.9.0.1", "FULL/DR", "t-no-record", 0)],
      overlay: [],
    },
    // Every other state, including one no code has seen.
    "t-states": {
      protocols: [row("OSPF", "partial", 6), row("BGP", "capture_error", 7), row("EIGRP", "analysis_unavailable", 8)],
      adjacencies: [],
      overlay: [],
    },
    "t-future": {
      protocols: [row("OSPF", "assessed", 9), row("BGP", "captured_nothing_new", 10), row("EIGRP", null, 11)],
      adjacencies: [],
      overlay: [],
    },
    // An empty EIGRP neighbor table beside EIGRP routes in the table: the captures disagree.
    "t-contradict": {
      protocols: [row("OSPF", "captured_empty", 12), row("BGP", "captured_empty", 13), row("EIGRP", "captured_empty", 14)],
      adjacencies: [],
      overlay: [],
    },
    // BGP's Established encoding is the received-prefix count; EIGRP neighbors are listed only when up.
    "t-bgp-eigrp": {
      protocols: [row("OSPF", "captured_empty", 15), row("BGP", "assessed", 16), row("EIGRP", "assessed", 17)],
      adjacencies: [
        // BGP records name the peer BY its address and name no interface.
        adj("bgp", "203.0.113.1", "3", "t-bgp-eigrp", 0, { address: null, interface: null }),
        adj("bgp", "203.0.113.2", "0", "t-bgp-eigrp", 1, { address: null, interface: null }),
        adj("bgp", "203.0.113.3", "Idle", "t-bgp-eigrp", 2, { address: null, interface: null }),
        adj("eigrp", "10.9.1.1", "up 01:02:03", "t-bgp-eigrp", 0, { address: null }),
      ],
      overlay: [],
    },
    // Every family accounted for, but a FULL adjacency whose routes the table does not hold.
    "t-full-no-route": {
      protocols: [row("OSPF", "assessed", 20), row("BGP", "captured_empty", 21), row("EIGRP", "captured_empty", 22)],
      adjacencies: [adj("ospf", "10.9.0.2", "FULL/DR", "t-full-no-route", 0)],
      overlay: [],
    },
    // One protocol row missing entirely.
    "t-missing-row": {
      protocols: [row("OSPF", "assessed", 18), row("BGP", "captured_empty", 19)],
      adjacencies: [],
      overlay: [],
    },
    // THE B1 SHAPE ON THE REGENERATED FLEET (verifier E2-V1): every family accounted for, the table
    // holds OSPF routes (learned over another adjacency), yet one FULL adjacency runs over a link the
    // table does not hold — core1's FULL/DR neighbour 10.0.99.2 on Po1 with no connected route there.
    "t-link-missing": {
      protocols: [row("OSPF", "assessed", 30), row("BGP", "captured_empty", 31), row("EIGRP", "captured_empty", 32)],
      adjacencies: [
        adj("ospf", "10.9.0.1", "FULL/  -", "t-link-missing", 0),
        adj("ospf", "10.9.99.2", "FULL/DR", "t-link-missing", 1, { interface: "Po1" }),
        // Stuck below 2-WAY: no session exists, so no link is implied by it (a stated boundary).
        adj("ospf", "10.9.40.9", "EXSTART/DROTHER", "t-link-missing", 2, { interface: "Vlan40" }),
      ],
      overlay: [],
    },
    // A connected route covers the neighbour's address, but on ANOTHER interface: not the adjacency's link.
    "t-link-wrong-intf": {
      protocols: [row("OSPF", "assessed", 33), row("BGP", "captured_empty", 34), row("EIGRP", "captured_empty", 35)],
      adjacencies: [adj("ospf", "10.9.0.1", "FULL/BDR", "t-link-wrong-intf", 0, { interface: "Gi1/0/2" })],
      overlay: [],
    },
    // The link is held under the long interface name; the neighbour record uses the short one. The
    // OSPF neighbour ID is a router ID, not the link address: the address field is what is covered.
    "t-link-abbrev": {
      protocols: [row("OSPF", "assessed", 36), row("BGP", "captured_empty", 37), row("EIGRP", "captured_empty", 38)],
      adjacencies: [adj("ospf", "10.255.0.9", "FULL/DR", "t-link-abbrev", 0, { address: "10.9.0.9", interface: "Po1" })],
      overlay: [],
    },
    // 2-WAY is a session over a shared segment even though it exchanges no routes: the link is implied.
    "t-2way": {
      protocols: [row("OSPF", "assessed", 39), row("BGP", "captured_empty", 40), row("EIGRP", "captured_empty", 41)],
      adjacencies: [
        adj("ospf", "10.9.0.1", "FULL/DR", "t-2way", 0),
        adj("ospf", "10.9.50.7", "2WAY/DROTHER", "t-2way", 1, { interface: "Vlan50" }),
      ],
      overlay: [],
    },
    // An Established BGP peer (0 prefixes: no BGP route is expected) that no route in the table reaches.
    "t-bgp-unreachable": {
      protocols: [row("OSPF", "captured_empty", 42), row("BGP", "assessed", 43), row("EIGRP", "captured_empty", 44)],
      adjacencies: [adj("bgp", "203.0.113.9", "0", "t-bgp-unreachable", 0, { address: null, interface: null })],
      overlay: [],
    },
    // The same peer, reached by a route the table holds.
    "t-bgp-reached": {
      protocols: [row("OSPF", "captured_empty", 45), row("BGP", "assessed", 46), row("EIGRP", "captured_empty", 47)],
      adjacencies: [adj("bgp", "203.0.113.9", "0", "t-bgp-reached", 0, { address: null, interface: null })],
      overlay: [],
    },
    // An adjacency record compiled WITHOUT the link fields (the compiler before it publishes them):
    // whether the link is held cannot be read, so the table is never shown complete on it.
    "t-no-link-fields": {
      protocols: [row("OSPF", "assessed", 48), row("BGP", "captured_empty", 49), row("EIGRP", "captured_empty", 50)],
      adjacencies: [{ protocol: "ospf", neighbor: "10.9.0.1", state: "FULL/DR", cite: "routing_neighbors.t-no-link-fields.ospf[0]" }],
      overlay: [],
    },
  };
  const routes: Record<string, unknown[]> = {
    "t-ospf-only": [route("t-ospf-only", "connected", 0), route("t-ospf-only", "ospf", 1), route("t-ospf-only", "ospf-ext2", 2)],
    "t-no-record": [route("t-no-record", "connected", 0), route("t-no-record", "ospf", 1)],
    // Only sub-typed OSPF routes (beside the link): still OSPF routes for the adjacency rule.
    "t-interarea": [route("t-interarea", "connected", 0), route("t-interarea", "ospf-interarea", 1)],
    "t-contradict": [route("t-contradict", "connected", 0), route("t-contradict", "eigrp-external", 1)],
    "t-bgp-eigrp": [route("t-bgp-eigrp", "connected", 0), route("t-bgp-eigrp", "static", 1, { prefix: "0.0.0.0/0", outIntf: null })],
    "t-full-no-route": [route("t-full-no-route", "connected", 0), route("t-full-no-route", "static", 1)],
    "t-link-missing": [
      route("t-link-missing", "connected", 0),
      route("t-link-missing", "ospf", 1),
      route("t-link-missing", "static", 2, { prefix: "10.9.0.0/16", outIntf: null }),
    ],
    "t-link-wrong-intf": [route("t-link-wrong-intf", "connected", 0), route("t-link-wrong-intf", "ospf", 1)],
    "t-link-abbrev": [route("t-link-abbrev", "connected", 0, { outIntf: "Port-channel1" }), route("t-link-abbrev", "ospf", 1)],
    "t-2way": [route("t-2way", "connected", 0), route("t-2way", "ospf", 1)],
    "t-bgp-unreachable": [route("t-bgp-unreachable", "connected", 0)],
    "t-bgp-reached": [route("t-bgp-reached", "connected", 0), route("t-bgp-reached", "static", 1, { prefix: "203.0.113.8/30", outIntf: null })],
    "t-no-link-fields": [route("t-no-link-fields", "connected", 0), route("t-no-link-fields", "ospf", 1)],
  };
  hosts["t-interarea"] = {
    protocols: [
      { protocol: "OSPF", state: "assessed", reason: "synthetic", cite: "protocol_assessability.rows[9100]" },
      { protocol: "BGP", state: "captured_empty", reason: "synthetic", cite: "protocol_assessability.rows[9101]" },
      { protocol: "EIGRP", state: "captured_empty", reason: "synthetic", cite: "protocol_assessability.rows[9102]" },
    ],
    adjacencies: [
      { protocol: "ospf", neighbor: "10.9.0.9", state: "FULL/BDR", cite: "routing_neighbors.t-interarea.ospf[0]", address: "10.9.0.9", interface: "Gi1/0/1" },
    ],
    overlay: [],
  };
  return { hosts, routes };
});

vi.mock("./rib-evidence.json", async (importOriginal) => {
  const real = (await importOriginal()) as { default: { meta: unknown; hosts: Record<string, unknown> } };
  return { default: { ...real.default, hosts: { ...real.default.hosts, ...fx.hosts } } };
});
vi.mock("../core/data", async (importOriginal) => {
  const real = await importOriginal<typeof import("../core/data")>();
  return { ...real, routesOf: (h: string) => (fx.routes[h] as ReturnType<typeof real.routesOf> | undefined) ?? real.routesOf(h) };
});

const mod = await import("./rib-completeness");
const { ribIncompleteness, RIB_EVIDENCE_TRUSTED } = mod;

const cites = (h: string) => ribIncompleteness(h).map((r) => r.cite);
const labels = (h: string) => ribIncompleteness(h).map((r) => r.label).join(" | ");

describe("a family contributes no routes ONLY when its neighbor table was captured and is empty", () => {
  it("precondition: the synthetic hosts sit on the real compiled record's binding", () => {
    expect(RIB_EVIDENCE_TRUSTED).toBe(true);
  });

  it("an OSPF-only host with EIGRP/BGP captured empty and its OSPF routes present is not shown incomplete", () => {
    expect(ribIncompleteness("t-ospf-only")).toEqual([]);
  });

  it("the basis for that says why each family does not make the table incomplete, citing its assessability row", () => {
    const basis = mod.ribCompletenessBasis("t-ospf-only");
    expect(basis.map((b) => [b.protocol, b.cite])).toEqual([
      ["BGP", "protocol_assessability.rows[9001]"],
      ["EIGRP", "protocol_assessability.rows[9002]"],
      ["OSPF", "protocol_assessability.rows[9000]"],
    ]);
    const eigrp = basis.find((b) => b.protocol === "EIGRP")!;
    expect(eigrp.label).toMatch(/EIGRP neighbor table was captured on t-ospf-only and is empty/);
    expect(eigrp.label).toMatch(/no EIGRP-learned route/);
    expect(basis.find((b) => b.protocol === "OSPF")!.label).toMatch(/OSPF is assessed on t-ospf-only/);
  });

  it("output captured but nothing parsed (captured_no_record) stays a reason, citing its row — it is not 'empty'", () => {
    expect(cites("t-no-record")).toEqual(["protocol_assessability.rows[9004]"]);
    expect(labels("t-no-record")).toMatch(/BGP output was captured on t-no-record but no neighbor state was parsed from it/);
    expect(mod.ribCompletenessBasis("t-no-record").map((b) => b.protocol)).toEqual(["EIGRP", "OSPF"]);
  });

  it("partial / capture_error / analysis_unavailable each stay a reason citing their own row", () => {
    // Reasons follow the snapshot's own (sorted) routing vocabulary: bgp, eigrp, ospf.
    expect(cites("t-states")).toEqual([
      "protocol_assessability.rows[9007]",
      "protocol_assessability.rows[9008]",
      "protocol_assessability.rows[9006]",
    ]);
    expect(labels("t-states")).toMatch(/OSPF is only partly collected on t-states/);
    expect(labels("t-states")).toMatch(/BGP capture on t-states returned an error/);
    expect(labels("t-states")).toMatch(/protocol analysis was unavailable/);
    expect(mod.ribCompletenessBasis("t-states")).toEqual([]);
  });

  it("an unrecorded or never-seen state is unknown, never empty", () => {
    expect(cites("t-future")).toEqual(["protocol_assessability.rows[9010]", "protocol_assessability.rows[9011]"]);
    expect(labels("t-future")).toMatch(/BGP is captured nothing new on t-future/);
    expect(labels("t-future")).toMatch(/EIGRP is unrecorded on t-future/);
  });

  it("a missing receipt row is still a reason", () => {
    expect(labels("t-missing-row")).toMatch(/no EIGRP collection receipt exists for t-missing-row/);
    expect(cites("t-missing-row")).toEqual(["protocol_assessability"]);
  });

  it("an empty neighbor table beside routes of that family is a contradiction, named with the row and the route", () => {
    const r = ribIncompleteness("t-contradict");
    expect(r.map((x) => x.cite)).toEqual(["protocol_assessability.rows[9014]"]);
    expect(r[0]!.label).toMatch(/EIGRP neighbor table was captured on t-contradict and is empty, yet the table holds an EIGRP route \(routes\.t-contradict\[1\]\)/);
    expect(mod.ribCompletenessBasis("t-contradict").map((b) => b.protocol)).toEqual(["BGP", "OSPF"]);
  });
});

describe("the adjacency rule covers every producer encoding of 'exchanging routes'", () => {
  it("a BGP peer whose State/PfxRcd is a positive count is Established and exchanging; 0 received and Idle are not", () => {
    const r = ribIncompleteness("t-bgp-eigrp");
    const bgp = r.filter((x) => x.cite.startsWith("routing_neighbors.t-bgp-eigrp.bgp"));
    expect(bgp.map((x) => x.cite)).toEqual(["routing_neighbors.t-bgp-eigrp.bgp[0]"]);
    expect(bgp[0]!.label).toMatch(/a BGP adjacency with 203\.0\.113\.1 is Established \(3 prefixes received\), yet the table holds no BGP route/);
  });

  it("a listed EIGRP neighbor is up, so a table with no EIGRP route beside it is incomplete", () => {
    expect(cites("t-bgp-eigrp")).toContain("routing_neighbors.t-bgp-eigrp.eigrp[0]");
    expect(labels("t-bgp-eigrp")).toMatch(/an EIGRP adjacency with 10\.9\.1\.1 is up 01:02:03, yet the table holds no EIGRP route/);
  });

  it("an OSPF adjacency is satisfied by a sub-typed OSPF route (ospf-interarea is an OSPF route)", () => {
    expect(ribIncompleteness("t-interarea")).toEqual([]);
  });

  it("a FULL OSPF adjacency with no OSPF route in the table is still a reason, even when every family is accounted for (kept rule)", () => {
    expect(cites("t-full-no-route")).toEqual(["routing_neighbors.t-full-no-route.ospf[0]"]);
    expect(labels("t-full-no-route")).toBe("an OSPF adjacency with 10.9.0.2 is FULL/DR, yet the table holds no OSPF route");
  });
});

describe("every session a host holds implies the link it runs over — checked per adjacency, not per family (E2-V1)", () => {
  it("a FULL adjacency over a link the table does not hold makes the table incomplete even when the table holds routes of its family", () => {
    // Per-family, "the table holds an OSPF route" answered yes (routes.t-link-missing[1], learned over
    // the OTHER adjacency) and the B1 contradiction on Po1 vanished; the static /16 summary covering
    // the neighbour is not the link either.
    const r = ribIncompleteness("t-link-missing");
    expect(r.map((x) => x.cite)).toEqual(["routing_neighbors.t-link-missing.ospf[1]"]);
    expect(r[0]!.label).toBe(
      "an OSPF adjacency with 10.9.99.2 is FULL/DR, yet the table holds no connected route on Po1 covering its address 10.9.99.2 — the link that adjacency runs over, and whatever it teaches, are missing from the table",
    );
  });

  it("the basis never lists a family whose own adjacency is what makes the table incomplete (E2-V3)", () => {
    expect(mod.ribCompletenessBasis("t-link-missing").map((b) => b.protocol)).toEqual(["BGP", "EIGRP"]);
    expect(mod.ribCompletenessBasis("t-full-no-route").map((b) => b.protocol)).toEqual(["BGP", "EIGRP"]);
    expect(mod.ribCompletenessBasis("t-bgp-eigrp").map((b) => b.protocol)).toEqual(["OSPF"]);
  });

  it("a connected route covering the neighbour on a DIFFERENT interface is not the adjacency's link", () => {
    expect(cites("t-link-wrong-intf")).toEqual(["routing_neighbors.t-link-wrong-intf.ospf[0]"]);
    expect(labels("t-link-wrong-intf")).toMatch(/no connected route on Gi1\/0\/2 covering its address 10\.9\.0\.1/);
  });

  it("the link is found under either spelling of the interface, and is tested against the link address, not the OSPF router ID", () => {
    expect(ribIncompleteness("t-link-abbrev")).toEqual([]);
    expect(mod.ribCompletenessBasis("t-link-abbrev").map((b) => b.protocol)).toEqual(["BGP", "EIGRP", "OSPF"]);
  });

  it("a 2-WAY session implies its link too; an adjacency stuck below 2-WAY implies none (boundary)", () => {
    expect(cites("t-2way")).toEqual(["routing_neighbors.t-2way.ospf[1]"]);
    expect(labels("t-2way")).toMatch(/is 2WAY\/DROTHER, yet the table holds no connected route on Vlan50 covering its address 10\.9\.50\.7/);
    expect(cites("t-link-missing")).not.toContain("routing_neighbors.t-link-missing.ospf[2]");
  });

  it("an Established BGP peer with no recorded interface must at least be reachable by a route the table holds", () => {
    expect(cites("t-bgp-unreachable")).toEqual(["routing_neighbors.t-bgp-unreachable.bgp[0]"]);
    expect(labels("t-bgp-unreachable")).toBe(
      "a BGP adjacency with 203.0.113.9 is Established (0 prefixes received), yet no route in the table covers 203.0.113.9 — the session could not be up over the table as collected",
    );
    expect(ribIncompleteness("t-bgp-reached")).toEqual([]);
  });

  it("an adjacency record compiled without its link fields leaves the table's completeness UNKNOWN, never complete", () => {
    expect(cites("t-no-link-fields")).toEqual(["routing_neighbors.t-no-link-fields.ospf[0]"]);
    expect(labels("t-no-link-fields")).toMatch(/does not carry the neighbour's address and interface/);
    expect(mod.ribCompletenessBasis("t-no-link-fields").map((b) => b.protocol)).toEqual(["BGP", "EIGRP"]);
  });
});

describe("over every host in the compiled record (the committed snapshot's plus the synthetic ones)", () => {
  const ev = realEvidence as unknown as { hosts: Record<string, { protocols: { protocol: string; state: string | null; cite: string }[] }> };
  const hosts = Object.keys(ev.hosts);

  it("precondition: the record holds every routable host of the committed snapshot", () => {
    expect(fabric.coverage.routableHosts.length).toBeGreaterThan(0);
    for (const h of fabric.coverage.routableHosts) expect(hosts).toContain(h);
  });

  it("every non-assessed, non-empty protocol row on a routable host is a reason carrying that row's cite", () => {
    let rows = 0;
    for (const h of hosts) {
      const got = new Set(cites(h));
      for (const p of ev.hosts[h]?.protocols ?? []) {
        if (p.state === "assessed" || p.state === "captured_empty") continue;
        rows += 1;
        expect(got.has(p.cite), `${h} ${p.protocol} ${p.state}`).toBe(true);
      }
    }
    expect(rows, "the committed snapshot must exercise at least one non-assessed row").toBeGreaterThan(0);
  });

  it("every adjacency in a session state is cited as a reason unless the table holds its link (the whole class, every host)", () => {
    const adjEv = realEvidence as unknown as {
      hosts: Record<string, { adjacencies: { state: string | null; cite: string; address?: string | null; interface?: string | null }[] }>;
    };
    const UP = /^(full|2way|established|up)\b|^\d+$/i;
    let sessions = 0;
    for (const h of hosts) {
      if (routesOf(h).length === 0) continue;
      const got = new Set(cites(h));
      for (const a of adjEv.hosts[h]?.adjacencies ?? []) {
        if (a.state === null || !UP.test(a.state.trim())) continue;
        sessions += 1;
        if (got.has(a.cite)) continue;
        // Not cited: then the record must carry the link fields and the table must hold that link.
        expect("address" in a && "interface" in a, `${a.cite} is uncited but carries no link fields`).toBe(true);
      }
    }
    expect(sessions, "the record must exercise at least one session").toBeGreaterThan(0);
  });

  it("a captured_empty row is cited as a reason exactly when the table holds routes of its family", () => {
    let rows = 0;
    for (const h of hosts) {
      const got = new Set(cites(h));
      for (const p of ev.hosts[h]?.protocols ?? []) {
        if (p.state !== "captured_empty") continue;
        rows += 1;
        const fam = p.protocol.toLowerCase();
        const hasFamilyRoute = routesOf(h).some((r) => r.source === fam || (r.source ?? "").startsWith(`${fam}-`));
        expect(got.has(p.cite), `${h} ${p.protocol}`).toBe(hasFamilyRoute);
      }
    }
    expect(rows).toBeGreaterThan(0);
  });
});
