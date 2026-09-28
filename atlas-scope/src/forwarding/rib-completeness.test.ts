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
 * compute_protocol_assessability): a family contributes no learned routes on a host ONLY on positive
 * evidence — `captured_empty` (the neighbor table was collected and holds nothing) or `not_running`
 * (the capture is the platform's no-process banner, e.g. IOS `% BGP not active`), each honoured only
 * while the engine's generated contract (`contracts/engine-contract.v1.json`) declares it. Every
 * other state the engine declares — read from that contract, not listed here — stays a reason the
 * table is not known to be complete, and names the assessability row that says so:
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
 * A route learned by a protocol with NO receipt at all (IS-IS, RIP, LISP, NHRP, mobile, ODR, or any
 * code the parser passes through unmapped) makes the table incomplete; the sources the engine's route
 * parser can emit are read from its own source text (cisco_toolkit/parse.py), so a new route code is
 * exercised here the day it is added (2026-09-27 verifier, E2R2-V1). A BGP peer the table reaches only
 * by its default route is not reached (E2R2-V2), and the real-data sweep recomputes, for every
 * uncited session, that its link IS held (E2R2-V6).
 *
 * The routing-completeness record is mocked with synthetic hosts ADDED to the real compiled file
 * (same source binding), so the real module is exercised through its public API.
 */
import { readFileSync } from "node:fs";

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
    // The 0-prefix peer 203.0.113.2 is reached by a route the table holds, so this host pins only what
    // "exchanging" means. (It used to be reached by a static DEFAULT, which the link rule no longer
    // accepts as evidence of a path -- that case is t-bgp-default-only.)
    "t-bgp-eigrp": [route("t-bgp-eigrp", "connected", 0), route("t-bgp-eigrp", "static", 1, { prefix: "203.0.113.0/24", outIntf: null })],
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
  // The dist-switch shape on the substrate fleet: OSPF runs, EIGRP's neighbor table is captured empty, and
  // BGP's capture is IOS's no-process banner, which the engine reads as its own `not_running` state.
  hosts["t-not-running"] = {
    protocols: [row("OSPF", "assessed", 60), row("BGP", "not_running", 61), row("EIGRP", "captured_empty", 62)],
    adjacencies: [adj("ospf", "10.9.0.1", "FULL/  -", "t-not-running", 0)],
    overlay: [],
  };
  routes["t-not-running"] = [route("t-not-running", "connected", 0), route("t-not-running", "ospf-ext2", 1)];
  // "No BGP process" beside a BGP route in the table: the captures disagree.
  hosts["t-not-running-contradict"] = {
    protocols: [row("OSPF", "captured_empty", 63), row("BGP", "not_running", 64), row("EIGRP", "captured_empty", 65)],
    adjacencies: [],
    overlay: [],
  };
  routes["t-not-running-contradict"] = [route("t-not-running-contradict", "connected", 0), route("t-not-running-contradict", "bgp", 1)];
  // Every other state the engine names stays unknown -- never positive evidence of absence.
  hosts["t-unknown-states"] = {
    protocols: [row("OSPF", "not_collected", 66), row("BGP", "captured_no_record", 67), row("EIGRP", "capture_error", 68)],
    adjacencies: [],
    overlay: [],
  };
  routes["t-unknown-states"] = [route("t-unknown-states", "connected", 0)];
  // An Established BGP peer (no interface recorded) that only the DEFAULT route covers: the default covers
  // every address, so it is no evidence of a path to this peer (2026-09-27 verifier, E2R2-V2).
  hosts["t-bgp-default-only"] = {
    protocols: [row("OSPF", "captured_empty", 69), row("BGP", "assessed", 70), row("EIGRP", "captured_empty", 71)],
    adjacencies: [adj("bgp", "203.0.113.9", "0", "t-bgp-default-only", 0, { address: null, interface: null })],
    overlay: [],
  };
  routes["t-bgp-default-only"] = [
    route("t-bgp-default-only", "connected", 0),
    route("t-bgp-default-only", "static", 1, { prefix: "0.0.0.0/0", outIntf: null }),
  ];
  // A learned route whose source the engine recorded as NOTHING: compiled as null, or as the empty string
  // the NX-OS source mapper returns for an empty via token (cisco_toolkit/parse.py _nxos_route_source
  // passes its normalised token through, and `str(None or "").strip().lower()` is ""). Every receipted
  // family is accounted for, so the unrecorded source is the only thing asked (2026-09-28 verifier, R2V-2).
  for (const [name, source] of [["t-src-unrecorded-null", null], ["t-src-unrecorded-empty", ""]] as const) {
    hosts[name] = {
      protocols: [row("OSPF", "captured_empty", 93), row("BGP", "captured_empty", 94), row("EIGRP", "captured_empty", 95)],
      adjacencies: [],
      overlay: [],
    };
    routes[name] = [route(name, "connected", 0), { ...route(name, "ospf", 1, { prefix: "10.60.0.0/16" }), source }];
  }

  /** Every route source the engine's route-code parser can emit, read from its own source text
   *  (cisco_toolkit/parse.py): the IOS/IOS-XE `code_map` values and the NX-OS `_nxos_route_source`
   *  names. Both parsers ALSO pass an unmapped code through as-is (`primary.lower()`, `return t`), so
   *  the emitted vocabulary is open -- which is why the rule reads the complement, never this list. */
  const engineRouteSources = (parseSrc: string): string[] => {
    const codeMap = /code_map = \{([\s\S]*?)\}/.exec(parseSrc)?.[1] ?? "";
    const iosValues = [...codeMap.matchAll(/'[^']+'\s*:\s*'([^']+)'/g)].map((m) => m[1]!);
    const nxos = /def _nxos_route_source[\s\S]*?for name in \(([^)]*)\)/.exec(parseSrc)?.[1] ?? "";
    const nxosValues = [...nxos.matchAll(/"([^"]+)"/g)].map((m) => m[1]!);
    return [...new Set([...iosValues, ...nxosValues, "connected"])].sort();
  };
  /** One synthetic host per source the parser can emit, plus two it passes through unmapped: `o` (ODR,
   *  which the parser's own comment names) and a token no parser version has ever produced. Every
   *  receipted family on these hosts is accounted for, so the route itself is the only thing asked. */
  const oovHosts = (sources: string[]) => {
    const h: Record<string, unknown> = {};
    const r: Record<string, unknown[]> = {};
    for (const source of [...sources, "o", "zz-future"]) {
      const name = `t-src-${source}`;
      h[name] = {
        protocols: [row("OSPF", "captured_empty", 80), row("BGP", "captured_empty", 81), row("EIGRP", "captured_empty", 82)],
        adjacencies: [],
        overlay: [],
      };
      r[name] = [route(name, "connected", 0), route(name, source, 1, { prefix: "10.50.0.0/16" })];
    }
    return { h, r };
  };
  /** One synthetic host per state the ENGINE declares (read from the generated contract): BGP in that
   *  state, OSPF/EIGRP captured empty, a connected-only table -- so the state itself is all that is asked. */
  const engineStateHosts = (states: unknown) => {
    const h: Record<string, unknown> = {};
    for (const s of Array.isArray(states) ? states : []) {
      if (typeof s !== "string") continue;
      h[`t-engine-state-${s}`] = {
        protocols: [row("OSPF", "captured_empty", 91), row("BGP", s, 90), row("EIGRP", "captured_empty", 92)],
        adjacencies: [],
        overlay: [],
      };
    }
    return h;
  };
  const PARSE_PY = `${import.meta.dirname}/../../../cisco_toolkit/parse.py`;
  return { hosts, routes, engineRouteSources, oovHosts, engineStateHosts, PARSE_PY };
});

vi.mock("./rib-evidence.json", async (importOriginal) => {
  const real = (await importOriginal()) as { default: { meta: unknown; hosts: Record<string, unknown> } };
  const { readFileSync } = await import("node:fs");
  const oov = fx.oovHosts(fx.engineRouteSources(readFileSync(fx.PARSE_PY, "utf8")));
  const contract = (await import("../../contracts/engine-contract.v1.json")).default as { protocol_assessability_states?: unknown };
  const states = fx.engineStateHosts(contract.protocol_assessability_states);
  return { default: { ...real.default, hosts: { ...real.default.hosts, ...fx.hosts, ...oov.h, ...states } } };
});
vi.mock("../core/data", async (importOriginal) => {
  const real = await importOriginal<typeof import("../core/data")>();
  const { readFileSync } = await import("node:fs");
  const oov = fx.oovHosts(fx.engineRouteSources(readFileSync(fx.PARSE_PY, "utf8")));
  const all: Record<string, unknown[]> = { ...fx.routes, ...oov.r };
  return { ...real, routesOf: (h: string) => (all[h] as ReturnType<typeof real.routesOf> | undefined) ?? real.routesOf(h) };
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

  it("a BGP peer that only the DEFAULT route covers is not reached: the default covers every address (E2R2-V2)", () => {
    expect(cites("t-bgp-default-only")).toEqual(["routing_neighbors.t-bgp-default-only.bgp[0]"]);
    expect(labels("t-bgp-default-only")).toBe(
      "a BGP adjacency with 203.0.113.9 is Established (0 prefixes received), yet no route in the table other than the default (routes.t-bgp-default-only[1]) covers 203.0.113.9 — a default covers every address, so it is no evidence of a path to this peer",
    );
    // The same 0-prefix peer covered by a non-default route is reached (t-bgp-eigrp's 203.0.113.2).
    expect(cites("t-bgp-eigrp")).not.toContain("routing_neighbors.t-bgp-eigrp.bgp[1]");
  });

  it("an adjacency record compiled without its link fields leaves the table's completeness UNKNOWN, never complete", () => {
    expect(cites("t-no-link-fields")).toEqual(["routing_neighbors.t-no-link-fields.ospf[0]"]);
    expect(labels("t-no-link-fields")).toMatch(/does not carry the neighbour's address and interface/);
    expect(mod.ribCompletenessBasis("t-no-link-fields").map((b) => b.protocol)).toEqual(["BGP", "EIGRP"]);
  });
});

describe("positive evidence of absence is ONLY what the engine says it is: a captured-empty neighbor table, or no process running", () => {
  it("the absence states are exactly captured_empty and not_running, and both are states the ENGINE declares", () => {
    expect([...mod.RIB_ABSENCE_STATES].sort()).toEqual(["captured_empty", "not_running"]);
    for (const s of mod.RIB_ABSENCE_STATES) expect(mod.ENGINE_ASSESSABILITY_STATES.has(s), s).toBe(true);
    // The vocabulary is the engine's, read from the generated contract -- and it is the real one.
    expect(mod.ENGINE_ASSESSABILITY_STATES.has("assessed")).toBe(true);
    expect(mod.ENGINE_ASSESSABILITY_STATES.size).toBeGreaterThanOrEqual(8);
  });

  it("an engine state the contract stops declaring stops vouching (fail closed), and a malformed contract declares nothing", () => {
    expect(mod.engineAssessabilityStates({ protocol_assessability_states: ["assessed", "captured_empty"] })).toEqual(
      new Set(["assessed", "captured_empty"]),
    );
    expect(mod.engineAssessabilityStates({ protocol_assessability_states: "captured_empty" }).size).toBe(0);
    expect(mod.engineAssessabilityStates(null).size).toBe(0);
  });

  it("EVERY state the engine declares, other than assessed and the two absence states, is a reason citing its row", () => {
    const others = [...mod.ENGINE_ASSESSABILITY_STATES].filter((s) => s !== "assessed" && !mod.RIB_ABSENCE_STATES.has(s));
    expect(others.length).toBeGreaterThanOrEqual(5);
    for (const s of others) {
      const host = `t-engine-state-${s}`;
      expect(cites(host), s).toEqual(["protocol_assessability.rows[9090]"]);
      expect(mod.ribCompletenessBasis(host).map((b) => b.protocol), s).toEqual(["EIGRP", "OSPF"]);
    }
  });

  it("a host whose BGP capture is the no-process banner (not_running) is not shown incomplete by BGP", () => {
    expect(ribIncompleteness("t-not-running")).toEqual([]);
    const basis = mod.ribCompletenessBasis("t-not-running");
    expect(basis.map((b) => [b.protocol, b.cite])).toEqual([
      ["BGP", "protocol_assessability.rows[9061]"],
      ["EIGRP", "protocol_assessability.rows[9062]"],
      ["OSPF", "protocol_assessability.rows[9060]"],
    ]);
    expect(basis[0]!.label).toMatch(/no BGP process is running on t-not-running/);
    expect(basis[0]!.label).toMatch(/no BGP-learned route is missing from the table/);
  });

  it("'no process' beside a route of that family is a contradiction, named with the row and the route", () => {
    const r = ribIncompleteness("t-not-running-contradict");
    expect(r.map((x) => x.cite)).toEqual(["protocol_assessability.rows[9064]"]);
    expect(r[0]!.label).toMatch(
      /no BGP process is running on t-not-running-contradict \(its capture is the platform's no-process banner\), yet the table holds a BGP route \(routes\.t-not-running-contradict\[1\]\)/,
    );
    expect(mod.ribCompletenessBasis("t-not-running-contradict").map((b) => b.protocol)).toEqual(["EIGRP", "OSPF"]);
  });

  it("not_collected, captured_no_record and capture_error stay unknown: reasons citing their rows, never a basis", () => {
    expect(cites("t-unknown-states")).toEqual([
      "protocol_assessability.rows[9067]",
      "protocol_assessability.rows[9068]",
      "protocol_assessability.rows[9066]",
    ]);
    expect(mod.ribCompletenessBasis("t-unknown-states")).toEqual([]);
  });
});

describe("a table holding routes of a protocol with no collection receipt is never complete (E2R2-V1, the whole class)", () => {
  const sources = fx.engineRouteSources(readFileSync(fx.PARSE_PY, "utf8"));
  const vocab = (realEvidence as unknown as { meta: { routingProtocols: string[] } }).meta.routingProtocols;
  const family = (s: string) => s.split("-")[0]!;

  it("precondition: the parser's vocabulary was read, and it emits protocols outside the receipted families", () => {
    for (const s of ["isis", "rip", "lisp", "nhrp", "mobile", "connected", "local", "static", "ospf-ext2", "eigrp-external"]) {
      expect(sources).toContain(s);
    }
    expect(vocab.length).toBeGreaterThan(0);
  });

  it("every route source the engine can emit outside the receipted families (and the unmapped pass-through) makes the table incomplete, naming the source", () => {
    let unreceipted = 0;
    for (const source of [...sources, "o", "zz-future"]) {
      const host = `t-src-${source}`;
      const r = ribIncompleteness(host);
      if (["connected", "local", "static"].includes(source) || vocab.includes(family(source))) continue;
      unreceipted += 1;
      expect(r.map((x) => x.cite), source).toEqual([`routes.${host}[1]`]);
      expect(r[0]!.label, source).toContain(`"${source}"`);
      expect(r[0]!.label, source).toMatch(/no collection receipt/);
    }
    // isis, rip, lisp, nhrp, mobile, candidate-default, o, zz-future at the time of writing.
    expect(unreceipted).toBeGreaterThanOrEqual(8);
  });

  it("the basis still vouches only for the receipted families -- the unreceipted protocol is never listed as accounted for", () => {
    const basis = mod.ribCompletenessBasis("t-src-isis");
    expect(basis.map((b) => b.protocol)).toEqual(["BGP", "EIGRP", "OSPF"]);
    expect(ribIncompleteness("t-src-isis").length).toBe(1);
  });

  it("connected, local and static routes need no protocol receipt: they are the table's own evidence", () => {
    for (const s of ["connected", "local", "static"]) expect(ribIncompleteness(`t-src-${s}`), s).toEqual([]);
  });

  it("a receipted family's sub-types are that family, not an unknown protocol", () => {
    // ospf-ext2 on a host whose OSPF neighbor table is captured empty: the captures disagree (OSPF's own
    // rule), never "no receipt".
    const r = ribIncompleteness("t-src-ospf-ext2");
    expect(r.map((x) => x.cite)).toEqual(["protocol_assessability.rows[9080]"]);
    expect(r[0]!.label).not.toMatch(/no collection receipt/);
  });
});

describe("a learned route whose source the engine recorded as nothing is an unknown protocol, never a known one (R2V-2)", () => {
  it("precondition: the engine's NX-OS source mapper can emit the empty source (it passes its normalised token through)", () => {
    const src = readFileSync(fx.PARSE_PY, "utf8");
    const body = /def _nxos_route_source\(token: str\) -> str:\n([\s\S]*?)\n\n\n/.exec(src)?.[1] ?? "";
    expect(body).toMatch(/^ {4}t = str\(token or ""\)\.strip\(\)\.lower\(\)$/m);
    expect(body).toMatch(/\n {4}return t$/);
  });

  it("a null or empty source is a reason citing the route, naming it as an unrecorded source", () => {
    for (const host of ["t-src-unrecorded-null", "t-src-unrecorded-empty"]) {
      const r = ribIncompleteness(host);
      expect(r.map((x) => x.cite), host).toEqual([`routes.${host}[1]`]);
      expect(r[0]!.label, host).toMatch(/the table holds a route whose source is an unrecorded source \(routes\.t-src-unrecorded-\w+\[1\]\), a protocol with no collection receipt/);
    }
  });

  it("an unrecorded source could be ANY family, so the basis vouches for none", () => {
    for (const host of ["t-src-unrecorded-null", "t-src-unrecorded-empty"]) {
      expect(mod.ribCompletenessBasis(host), host).toEqual([]);
    }
  });
});

describe("the contract filter is live: an absence state the engine retires or renames stops vouching, through RIB_ABSENCE_STATES itself (R2V-1)", () => {
  const CONTRACT = "../../contracts/engine-contract.v1.json";
  // Each absence state, and a synthetic host whose completeness rests on it.
  for (const [state, host, cite] of [
    ["not_running", "t-not-running", "protocol_assessability.rows[9061]"],
    ["captured_empty", "t-ospf-only", "protocol_assessability.rows[9001]"],
  ] as const) {
    it(`with ${state} renamed in the engine contract, the module no longer counts it, and ${host} is shown incomplete citing that row`, async () => {
      const real = (await import("../../contracts/engine-contract.v1.json")).default as { protocol_assessability_states: string[] };
      const renamed = real.protocol_assessability_states.map((s) => (s === state ? `${state}_renamed` : s));
      expect(renamed).not.toContain(state);
      // Before: the host's completeness rests on that state.
      expect(ribIncompleteness(host)).toEqual([]);
      vi.resetModules();
      vi.doMock(CONTRACT, () => ({ default: { ...real, protocol_assessability_states: renamed } }));
      try {
        const retired = await import("./rib-completeness");
        expect(retired.ENGINE_ASSESSABILITY_STATES.has(state)).toBe(false);
        expect(retired.RIB_ABSENCE_STATES.has(state)).toBe(false);
        expect([...retired.RIB_ABSENCE_STATES]).toEqual([...mod.RIB_ABSENCE_STATES].filter((s) => s !== state));
        expect(retired.ribIncompleteness(host).map((r) => r.cite)).toContain(cite);
        expect(retired.ribCompletenessBasis(host).map((b) => b.cite)).not.toContain(cite);
      } finally {
        vi.doUnmock(CONTRACT);
        vi.resetModules();
      }
    });
  }
});

describe("over every host in the compiled record (the committed snapshot's plus the synthetic ones)", () => {
  const ev = realEvidence as unknown as { hosts: Record<string, { protocols: { protocol: string; state: string | null; cite: string }[] }> };
  const hosts = Object.keys(ev.hosts);

  it("precondition: the record holds every routable host of the committed snapshot", () => {
    expect(fabric.coverage.routableHosts.length).toBeGreaterThan(0);
    for (const h of fabric.coverage.routableHosts) expect(hosts).toContain(h);
  });

  it("every protocol row that is neither assessed nor an absence state is a reason carrying that row's cite", () => {
    let rows = 0;
    for (const h of hosts) {
      const got = new Set(cites(h));
      for (const p of ev.hosts[h]?.protocols ?? []) {
        if (p.state === "assessed" || (p.state !== null && mod.RIB_ABSENCE_STATES.has(p.state))) continue;
        rows += 1;
        expect(got.has(p.cite), `${h} ${p.protocol} ${p.state}`).toBe(true);
      }
    }
    expect(rows, "the committed snapshot must exercise at least one non-assessed row").toBeGreaterThan(0);
  });

  it("every adjacency in a session state is cited as a reason unless the table holds its link (the whole class, every host)", () => {
    const adjEv = realEvidence as unknown as {
      hosts: Record<string, { adjacencies: { neighbor: string | null; state: string | null; cite: string; address?: string | null; interface?: string | null }[] }>;
    };
    const UP = /^(full|2way|established|up)\b|^\d+$/i;
    /** An independent restatement of "the table holds the link" (2026-09-27 verifier, E2R2-V6: the sweep
     *  asserted only that an uncited session CARRIES link fields, never that its link is HELD). */
    const toInt = (ip: string) => ip.split(".").reduce((n, o) => n * 256 + Number(o), 0);
    const inPrefix = (prefix: string, ip: string) => {
      const [net, len] = prefix.split("/");
      const bits = Number(len);
      if (bits === 0) return true;
      const size = 2 ** (32 - bits);
      return Math.floor(toInt(ip) / size) === Math.floor(toInt(net!) / size);
    };
    const intfKey = (s: string) => {
      const m = /^([a-z-]+)\s*(\S+)$/i.exec(s.trim());
      return m === null ? s.toLowerCase() : `${m[1]!.slice(0, 2).toLowerCase()}${m[2]!.toLowerCase()}`;
    };
    let sessions = 0;
    let uncited = 0;
    for (const h of hosts) {
      const rs = routesOf(h);
      if (rs.length === 0) continue;
      const got = new Set(cites(h));
      for (const a of adjEv.hosts[h]?.adjacencies ?? []) {
        if (a.state === null || !UP.test(a.state.trim())) continue;
        sessions += 1;
        if (got.has(a.cite)) continue;
        uncited += 1;
        // Not cited: then the record must carry the link fields AND the table must hold that link.
        expect("address" in a && "interface" in a, `${a.cite} is uncited but carries no link fields`).toBe(true);
        const addr = a.address ?? a.neighbor;
        expect(addr, `${a.cite} names no address`).not.toBeNull();
        const held =
          a.interface !== null && a.interface !== undefined
            ? rs.some((r) => r.source === "connected" && r.outIntf !== null && intfKey(r.outIntf) === intfKey(a.interface!) && inPrefix(r.prefix, addr!))
            : rs.some((r) => !r.prefix.endsWith("/0") && inPrefix(r.prefix, addr!));
        expect(held, `${a.cite}: uncited, yet ${h}'s table does not hold its link`).toBe(true);
      }
    }
    expect(sessions, "the record must exercise at least one session").toBeGreaterThan(0);
    expect(uncited, "the sweep must reach at least one uncited session (the held-link branch)").toBeGreaterThan(0);
  });

  it("the held-link sweep reaches REAL hosts' sessions, read from the compiled file on disk -- no synthetic host counts (R2V-3)", () => {
    /* The sweep above iterates the MOCKED record, whose synthetic hosts alone satisfied its `uncited > 0`
       precondition (2026-09-28 verifier, R2V-3). This one reads the compiled record from disk, so only hosts
       the engine's snapshot names are asked, and each session is judged against the real compiled table. */
    const disk = JSON.parse(readFileSync(`${import.meta.dirname}/rib-evidence.json`, "utf8")) as {
      hosts: Record<string, { adjacencies: { neighbor: string | null; state: string | null; cite: string; address?: string | null; interface?: string | null }[] }>;
    };
    const real = Object.keys(disk.hosts);
    expect(real.some((h) => h.startsWith("t-"))).toBe(false);
    const UP = /^(full|2way|established|up)\b|^\d+$/i;
    const toInt = (ip: string) => ip.split(".").reduce((n, o) => n * 256 + Number(o), 0);
    const inPrefix = (prefix: string, ip: string) => {
      const [net, len] = prefix.split("/");
      const size = 2 ** (32 - Number(len));
      return Math.floor(toInt(ip) / size) === Math.floor(toInt(net!) / size);
    };
    const intfKey = (s: string) => {
      const m = /^([a-z-]+)\s*(\S+)$/i.exec(s.trim());
      return m === null ? s.toLowerCase() : `${m[1]!.slice(0, 2).toLowerCase()}${m[2]!.toLowerCase()}`;
    };
    const up: { host: string; cite: string; held: boolean; viaInterface: boolean }[] = [];
    for (const h of real) {
      const rs = routesOf(h);
      if (rs.length === 0) continue;
      for (const a of disk.hosts[h]!.adjacencies) {
        if (a.state === null || !UP.test(a.state.trim())) continue;
        const addr = a.address ?? a.neighbor;
        const viaInterface = a.interface !== null && a.interface !== undefined;
        const held =
          addr !== null &&
          (viaInterface
            ? rs.some((r) => r.source === "connected" && r.outIntf !== null && intfKey(r.outIntf) === intfKey(a.interface!) && inPrefix(r.prefix, addr))
            : rs.some((r) => !r.prefix.endsWith("/0") && inPrefix(r.prefix, addr)));
        up.push({ host: h, cite: a.cite, held, viaInterface });
      }
    }
    expect(up.length, "the compiled snapshot must hold at least one real up session").toBeGreaterThan(0);
    const uncited = up.filter((s) => !cites(s.host).includes(s.cite));
    // Whatever the fleet: an uncited real session is one whose link its table holds (never the reverse).
    for (const s of uncited) expect(s.held, `${s.cite}: uncited, yet its link is not held`).toBe(true);
    /* RATCHET. The tracked fleet these files were compiled from predates the forwarding substrate: its one
       real up session -- core1's FULL/DR neighbour on the L2 trunk Po1 -- runs over a link core1's table does
       not hold, so it is cited and NO real session reaches the held-link branch there. The exemption is
       bound to the ABSENCE of the whole substrate and to that exact reason, never to a typed digest (a
       literal copy of the snapshot digest is a cache nothing invalidates: src/core/provenance.test.ts).
       "Predates the substrate" is read from the engine's own demo builder: every host its substrate gives a
       whole routing table (`<var>["show ip route"] = (` on a `<var> = cols["<host>"][1]`) must be a real
       host of the compiled fleet holding NO routes. A fleet carrying any part of the substrate (the
       regenerated one carries the inter-core session on Vlan10, the dist1 transit and the dist pair's OSPF)
       must bring real sessions into the held-link branch, both with and without a recorded interface.
       Phase 3 (fleet regeneration) deletes this exemption. */
    const build = readFileSync(`${import.meta.dirname}/../../../webapp/sample_data/build_sample.py`, "utf8");
    const substrate = /\ndef _add_forwarding_substrate\(cols: dict\) -> dict:\n([\s\S]*?)\n\n\n/.exec(build)?.[1] ?? "";
    const hostOf = new Map([...substrate.matchAll(/^ {4}(\w+) = cols\["([^"]+)"\]\[1\]$/gm)].map((m) => [m[1]!, m[2]!]));
    const tabled = [...substrate.matchAll(/^ {4}(\w+)\["show ip route"\] = \($/gm)].map((m) => hostOf.get(m[1]!));
    expect(tabled.length, "the builder's substrate gives at least one host a whole routing table").toBeGreaterThan(0);
    for (const h of tabled) {
      expect(h, "every substrate-tabled variable resolves to a builder host").toBeDefined();
      expect(real, `${h}: a substrate-tabled host is a real host of the compiled fleet`).toContain(h);
    }
    const predatesSubstrate = tabled.every((h) => routesOf(h!).length === 0);
    if (predatesSubstrate) {
      expect(uncited).toEqual([]);
      // ...and the exemption's reason, recomputed: not one real up session's link is held there.
      for (const s of up) expect(s.held, s.cite).toBe(false);
    } else {
      expect(uncited.filter((s) => s.viaInterface).length, "a real session over a recorded interface in the held-link branch").toBeGreaterThan(0);
      expect(uncited.filter((s) => !s.viaInterface).length, "a real session with no recorded interface in the held-link branch").toBeGreaterThan(0);
    }
  });

  it("an absence-state row (captured_empty / not_running) is cited as a reason exactly when the table holds routes of its family", () => {
    let rows = 0;
    for (const h of hosts) {
      const got = new Set(cites(h));
      for (const p of ev.hosts[h]?.protocols ?? []) {
        if (p.state === null || !mod.RIB_ABSENCE_STATES.has(p.state)) continue;
        rows += 1;
        const fam = p.protocol.toLowerCase();
        const hasFamilyRoute = routesOf(h).some((r) => r.source === fam || (r.source ?? "").startsWith(`${fam}-`));
        expect(got.has(p.cite), `${h} ${p.protocol}`).toBe(hasFamilyRoute);
      }
    }
    expect(rows).toBeGreaterThan(0);
  });
});
