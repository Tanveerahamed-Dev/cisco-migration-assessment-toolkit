/**
 * golden-expectations.ts — the ONE place the forwarding tests read what the tracked reference sample
 * contains (the golden tier; see ../test-support/golden-sample.ts).
 *
 * Every value here was MEASURED on the sample at `GOLDEN_SHA` (webapp/sample_data/sample_fleet.snapshot.json,
 * regenerated for phase 3: core1<->dist1 routed transit on Gi1/0/40 <-> Gi1/0/3, dist1/dist2 RIBs, OSPF
 * adjacencies and not_running BGP evidence). The blocks that read them run through `describeGolden`, so on
 * any other dataset they are skipped BY NAME, and importing the golden tier THROWS when the tracked sample
 * changed without these being re-derived — a stale number here can never pass silently.
 *
 * Only data lives here: flows, host / list / interface names, citations, configuration text and counts.
 * The assertions stay in the tests, next to the invariant each golden pin sits beside. A golden block that
 * needs a sample fact reads it from here — a host name inside a sentence it matches included — so
 * re-deriving the tier for a regenerated sample is an edit to this file, not a hunt through the suite
 * (2026-09-28 verifier, D3). Every value is read by some test: `golden-expectations.test.ts` fails on a
 * top-level key no forwarding test names.
 *
 * Sections are keyed by SUBJECT (a list, a flow, a host role), not by test file, because several files pin
 * the same fact (the headline pair, the bound PROTECT_SERVERS list) and one fact has one owner.
 */
import type { Flow } from "../core/types";

const tcp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "tcp", dstPort, srcPort: null });
const udp = (srcIp: string, dstIp: string, dstPort: number): Flow => ({ srcIp, dstIp, protocol: "udp", dstPort, srcPort: null });
const icmp = (srcIp: string, dstIp: string): Flow => ({ srcIp, dstIp, protocol: "icmp", dstPort: null, srcPort: null });
const ipAny = (srcIp: string, dstIp: string): Flow => ({ srcIp, dstIp, protocol: "ip", dstPort: null, srcPort: null });

/* ── the sample's hosts, by role ───────────────────────────────────────────────────────────────── */

/** core1: the routed core holding the four named lists; the headline pair's gateway on Vlan10/Vlan30. */
const CORE1 = "core1";
/** core2: the HSRP peer holding a collected RIB and NO collected ACLs. */
const CORE2 = "core2";

/* ── the headline pair: a host on core1's Vlan10 to a server on core1's Vlan30 ─────────────────── */
const HEADLINE_SRC = "10.0.10.50";
const HEADLINE_DST = "10.0.30.10";

export const GOLDEN_FORWARDING = {
  /** fabric.coverage on the sample. */
  routableHosts: ["core1", "core2", "dist1", "dist2"],
  aclHosts: ["core1", "dist1", "dist2"],
  deviceCount: 26,

  /** The sample's hosts by the role the golden blocks use them in. */
  sampleHosts: { core1: CORE1, core2: CORE2 },

  /** The suggestion list, in the engine's order. */
  presetIds: ["permitted", "denied", "unevaluable", "multi-hop-delivery", "multi-hop-denial", "out-of-scope"],

  /** The decided multi-hop delivery the engine derives from the dist1 -> core1 routed edge. */
  multiHopDelivery: {
    flow: tcp("10.0.40.50", "10.0.10.50", 22),
    hops: [
      { host: "dist1", verdict: "forwarded", decidedBy: "routes.dist1[1]", nextHop: "10.0.140.1", nextHost: "core1" },
      { host: "core1", verdict: "delivered", decidedBy: "routes.core1[2]", nextHop: null, nextHost: null },
    ],
    /** "none is bound to the interfaces this flow enters (X) or leaves (Y)", once per ACL host on the path. */
    unboundAtEachHost: [
      { enters: "Vlan40", leaves: "Gi1/0/3" },
      { enters: "Gi1/0/40", leaves: "Vlan10" },
    ],
  },

  /** The decided multi-hop denial, its blocking line, and the counterexample the search finds (B8). */
  multiHopDenial: {
    flow: tcp("10.0.40.50", "10.0.30.10", 22),
    blockingHost: "core1",
    blockingCite: "acls.core1.PROTECT_SERVERS[3]",
    blockingRaw: "deny ip any any",
    blockingLine: "line 4 of 4",
    boundOn: "applied outbound on core1 Vlan30 (interfaces.core1.Vlan30)",
    counterexample: tcp("10.0.40.50", "10.0.20.10", 22),
    counterexampleDecidedBy: "routes.core1[4]",
  },

  /**
   * A denial whose deciding LINE depends on the ingress (acceptance A3, 2026-10 refuter overturn). Entering at
   * the HSRP Active core2 it is denied by PROTECT_SERVERS, bound outbound on core1 Vlan30; entering at the
   * Standby core1 it is denied first by VOICE_FILTER, bound inbound on core1 Vlan20. Same outcome, different line.
   */
  ingressDependentDenial: {
    flow: tcp("10.0.20.50", "10.0.30.10", 22),
    chosen: CORE2,
    alternate: CORE1,
    blockingHost: CORE1,
    chosenCite: "acls.core1.PROTECT_SERVERS[3]",
    alternateCite: "acls.core1.VOICE_FILTER[2]",
  },

  /** The same denial on the port the critic used (acceptance report, R2): also decided, also answered. */
  multiHopDenialRdp: tcp("10.0.40.50", "10.0.30.10", 3389),

  /** The old sample's dist1 stop, now a decided two-hop denial on tcp/443: dist1 forwards, core1 denies. */
  twoHopDenial443: {
    flow: tcp("10.0.40.50", "10.0.30.10", 443),
    hops: [
      ["dist1", "forwarded", "routes.dist1[3]"],
      ["core1", "denied", "acls.core1.PROTECT_SERVERS[3]"],
    ] as [string, string, string][],
  },

  /** The single-hop headline pair from core1's own Vlan10, and what the new data makes of it. */
  headline: {
    src: HEADLINE_SRC,
    dst: HEADLINE_DST,
    permit: tcp(HEADLINE_SRC, HEADLINE_DST, 443),
    deny: tcp(HEADLINE_SRC, HEADLINE_DST, 3389),
    /** The same pair on the ports the not-applied sweep reads. */
    ssh: tcp(HEADLINE_SRC, HEADLINE_DST, 22),
    dns: udp(HEADLINE_SRC, HEADLINE_DST, 53),
    tcp53: tcp(HEADLINE_SRC, HEADLINE_DST, 53),
    icmp: icmp(HEADLINE_SRC, HEADLINE_DST),
    ip: ipAny(HEADLINE_SRC, HEADLINE_DST),
    /** The ingress-side gaps the headline pair carries on this sample (no rib-partial: core1's table is complete). */
    gapKinds: ["ingress-alternate", "ingress-port-unobserved"],
    /** The counterexample the search offers for the headline denial on this sample. */
    counterexample: tcp(HEADLINE_SRC, HEADLINE_DST, 22),
    /** Where the pair enters and leaves core1, and core1's HSRP peer the ingress caveat names. */
    ingressIntf: "Vlan10",
    egressIntf: "Vlan30",
    alternate: CORE2,
    alternateRole: "HSRP Standby",
  },

  /** core1's lists, lines and bindings the golden blocks read by name. */
  core1Acls: {
    host: CORE1,
    /** The list bound OUTBOUND on Vlan30, and its lines. */
    protectServers: {
      name: "PROTECT_SERVERS",
      bindingCite: "interfaces.core1.Vlan30",
      bindingRaw: "acl_out: PROTECT_SERVERS",
      permit443Cite: "acls.core1.PROTECT_SERVERS[0]",
      permit443Raw: "permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 443",
      permit443Index: 0,
      echoReplyCite: "acls.core1.PROTECT_SERVERS[2]",
      denyAllCite: "acls.core1.PROTECT_SERVERS[3]",
      denyAllIndex: 3,
    },
    /** A list bound on none of core1's interfaces: `permit tcp any any established`, then a time-ranged line. */
    inetReturn: {
      name: "INET_RETURN",
      establishedCite: "acls.core1.INET_RETURN[0]",
      timeRangedCite: "acls.core1.INET_RETURN[1]",
      timeRange: "BUSINESS_HOURS",
    },
    /** The list whose object-group the compiler carries — the producer's one justified override. */
    mgmtIn: {
      name: "MGMT_IN",
      group: "MGMT_HOSTS",
      lineCite: "acls.core1.MGMT_IN[0]",
      /** The producer marked it unevaluable; the engine resolves the group — the only such override. */
      overrides: ["core1.MGMT_IN[0]"],
      /** A source inside a group member, one outside, one in neither member, toward the headline server. */
      inGroupSrc: "10.0.40.7",
      outOfGroupSrc: HEADLINE_SRC,
      neitherMemberSrc: "203.0.113.9",
    },
    /** The list bound INBOUND on Vlan20; its deny line decides the core2-crossing denial by specificity. */
    voiceFilter: { name: "VOICE_FILTER", denyCite: "acls.core1.VOICE_FILTER[2]" },
    /** The lists core1 defines beside PROTECT_SERVERS, in the order the not-applied caveat names them. */
    otherLists: ["INET_RETURN", "MGMT_IN", "VOICE_FILTER"],
    /** The not-applied lists the flow meets only through `… any any` lines. */
    catchAllLists: ["MGMT_IN", "VOICE_FILTER"],
    /** "core1: 2 interface ACL bindings were observed …", and the one port with an unnamed access-group. */
    observedBindings: 2,
    unnamedAccessGroupPort: "Gi1/0/5",
    unnamedAccessGroupCite: "interfaces.core1.Gi1/0/5",
    /** core1's default and summary routes: next hops no collected host owns (honest dead ends). */
    deadEndPrefixes: ["0.0.0.0/0", "10.0.0.0/16"],
    /** The connected Vlan10 route, and the default route resolved through it. */
    connectedVlan10: { cite: "routes.core1[2]", prefix: "10.0.10.0/24" },
    defaultRoute: { cite: "routes.core1[0]", nextHop: "10.0.10.254", egress: "Vlan10" },
  },

  /** A flow leaving core1 by Vlan10, whose access port carries an unnamed outbound access-group (unknown binding). */
  unknownBinding: {
    flow: tcp("10.0.30.50", "10.0.10.77", 443),
    decidedByCite: "acls.core1.INET_RETURN[0]",
    outIntf: "Vlan10",
    /** The routes it beat. */
    alternatives: ["10.0.0.0/16", "0.0.0.0/0"],
    /** A delivery into Vlan10 is held back by the same unnamed access-group. */
    vlan10Delivery: udp("10.0.30.50", "10.0.10.10", 53),
  },

  /** engine.test.ts "never a definite permit" sweep (6 sources x 4 destinations x 5 services), and its counts. */
  neverADefinitePermitSweep: {
    srcs: ["10.0.10.50", "10.0.10.77", "10.0.10.1", "10.0.20.50", "10.0.30.1", "10.0.40.50"],
    dsts: ["10.0.10.10", "10.0.20.10", "10.0.30.10", "10.0.30.1"],
  },
  neverADefinitePermit: { caveated: 2, definite: 5, heldBackByAbsence: 0 },

  /** Deliveries and refusals the golden blocks trace by shape. */
  flows: {
    /** Delivered at core2 on a connected route; core2's missing ACLs keep it from being definite. */
    core2Delivery: tcp("10.0.20.10", "10.0.10.10", 443),
    /** The flow that used to drop at core2: now core2 forwards and core1 denies (VOICE_FILTER, by specificity). */
    viaCore2: { flow: tcp("10.0.20.50", "198.51.100.7", 443), hops: ["core2:forwarded", "core1:denied"] },
    viaDist1: { flow: tcp("10.0.40.50", "10.0.30.10", 443), hops: ["dist1:forwarded", "core1:denied"] },
    /** Delivered at core1 out Vlan20: Vlan10 in and Vlan20 out observed with no access-group. */
    localDelivery: { flow: tcp(HEADLINE_SRC, "10.0.20.10", 22), enters: "Vlan10", leaves: "Vlan20" },
    /** core1's own Vlan30 address as a source: router-originated. */
    routerOwnSource: { flow: tcp("10.0.30.1", "10.0.20.10", 22), owner: CORE1 },
    /** icmp to an off-fabric address, denied by the list the specificity rule chose at core1. */
    heuristicIcmp: icmp(HEADLINE_SRC, "8.8.8.8"),
    /** An internet-bound tcp flow behind `permit tcp any any established`. */
    establishedInternet: tcp(HEADLINE_SRC, "203.0.113.9", 443),
    /** The flow core2 used to drop, off-fabric; its caveats name core2's missing ACLs. */
    core2Internet: tcp("10.0.20.50", "203.0.113.9", 443),
    /** 0.0.0.0/0 via 10.0.10.254 from core1. */
    viaDefault: tcp(HEADLINE_SRC, "8.8.8.8", 443),
  },

  /** Destinations for the "no source in a device's own address set is decided" sweep, and the SCOPED sweep. */
  ownedSourceSweepDsts: ["10.0.10.50", "10.0.20.50", "10.0.30.10", "10.0.40.50", "8.8.8.8"],
  scopedIngressSweep: {
    srcs: ["10.0.10.50", "10.0.10.77", "10.0.20.50", "10.0.30.50", "10.0.40.50", "10.0.10.1", "10.0.20.1", "10.0.30.1"],
    dsts: ["10.0.10.10", "10.0.20.10", "10.0.30.10", "8.8.8.8", "10.0.40.10"],
  },

  /** The core2 uniqueness pin: a core2 host toward two addresses, on three ports. */
  core2Uniqueness: { src: "10.0.20.10", dsts: ["10.0.10.10", "10.0.20.10"] },

  /** VLAN 20's HSRP group: core2 Active, core1 Standby; its virtual address, a host in it, and a doubly-owned address. */
  fhrpVlan20: {
    vlan: 20,
    active: CORE2,
    standby: CORE1,
    vipFlow: tcp("10.0.20.1", HEADLINE_DST, 443),
    hostFlow: tcp("10.0.20.50", HEADLINE_DST, 443),
    /** core1's Vlan10 address, which is also a `local` /32 in its RIB: two records, one host. */
    ownedTwiceFlow: tcp("10.0.10.2", HEADLINE_DST, 443),
    ownedTwiceHost: CORE1,
  },

  /** core1's Vlan30 subnet's own addresses, and Vlan10's, as destinations and sources. */
  subnetAddresses: {
    nonHostDsts: ["10.0.30.0", "10.0.30.255"],
    nonHostSrcs: ["10.0.10.0", "10.0.10.255"],
  },

  /** engine.test.ts's depth-ratchet flow space (19 addresses x 19 x 9 services = 3,249 traces). */
  depthRatchet: {
    /** Addresses added to the derived set (a server, a dist host, an off-fabric address, core1's two next hops). */
    seedAddresses: ["10.0.30.10", "10.0.41.50", "198.51.100.7", "10.0.10.254", "10.0.30.254"],
    addresses: 19,
    traces: 3249,
    histogram: { 0: 2574, 1: 343, 2: 332 } as Record<number, number>,
    resolvedNextHops: 332,
    definiteDeliveries: 9,
    decidedOutcomes: 23,
    refusals: 70,
    counterexamplesFound: 26,
  },

  /** ip.test.ts: l3 rows, and rows carrying both an SVI address and the engine's primarySubnet. */
  l3PrimarySubnet: { rows: 9, compared: 9 },

  /** engine.off-subnet.test.ts: traces in its sweep (14 sources x destinations x services). */
  offSubnetTraces: 504,

  /** router-destined.test.ts: the address the defect was found on (core1's own Vlan30 address). */
  routerDestined: {
    ownedAtLeast: 5,
    address: "10.0.30.1",
    owner: CORE1,
    rdp: tcp(HEADLINE_SRC, "10.0.30.1", 3389),
    ssh: tcp(HEADLINE_SRC, "10.0.30.1", 22),
  },

  /** claim-honesty.test.ts subjects. */
  claimHonesty: {
    /** udp to a Vlan10 host whose attachment port was never observed: an absence decides it. */
    absenceDelivery: udp("10.0.30.10", "10.0.10.7", 53),
    /** Delivered at core2, which holds no collected ACLs. */
    noAclDelivery: tcp("10.0.20.50", HEADLINE_SRC, 443),
    /** core1's Vlan30 address as a source. */
    routerOriginated: tcp("10.0.30.1", "10.0.20.10", 443),
    /** The sweep's addresses. */
    sweepAddresses: ["10.0.10.7", "10.0.10.50", "10.0.20.10", "10.0.20.50", "10.0.30.10", "10.0.30.20", "8.8.8.8", "192.168.1.1"],
    /** Two hosts of one subnet (Vlan30) and the list that must not decide them; and Vlan10's pair. */
    sameSubnet: { flow: tcp("10.0.30.10", "10.0.30.20", 443), subnet: "10.0.30.0/24", list: "PROTECT_SERVERS" },
    sameSubnetVlan10: { src: HEADLINE_SRC, dst: "10.0.10.7", list: "INET_RETURN" },
    crossSubnet: tcp("10.0.30.10", "10.0.20.10", 443),
  },

  /** engine.counterfactual.test.ts subjects (complete-table counterfactual). */
  counterfactual: {
    /** A Vlan30 source (single gateway, no FHRP alternate): SCOPED once its ports are observed. */
    scoped: tcp("10.0.30.5", HEADLINE_SRC, 443),
    neverADefinitePermitSweep: {
      srcs: ["10.0.10.50", "10.0.10.77", "10.0.10.5", "10.0.20.50", "10.0.30.5", "10.0.40.50"],
      dsts: ["10.0.10.10", "10.0.20.10", "10.0.30.10", "10.0.40.10"],
    },
    citationSweepAddresses: ["10.0.10.50", "10.0.20.10", "10.0.30.10", "10.0.30.50", "10.0.40.5", "10.0.99.10", "203.0.113.9"],
  },

  /** rib-partial-route.test.ts: the critic's flow toward core1's OSPF neighbour's router ID. */
  ribPartialRoute: {
    host: CORE1,
    neighborRouterId: "10.0.99.2",
    /** open-issues O65: the session's L3 home since phase 2.75 (not a retired transit VLAN 900). */
    sessionInterface: "Vlan10",
    criticFlow: tcp("10.0.30.50", "10.0.99.2", 443),
    criticOutcome: "denied",
  },
} as const;
