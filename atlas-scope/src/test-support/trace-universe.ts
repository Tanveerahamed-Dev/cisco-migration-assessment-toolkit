/**
 * trace-universe.ts — the flows a panels test draws its subjects from, DERIVED from the loaded fabric.
 *
 * TEST SUPPORT ONLY (imported by `*.test.tsx` files in this directory, never by the product).
 *
 * Why it exists (phase 3, 2026-09-28). The panels tests named their subjects by the sample's host names
 * and addresses ("tcp 10.0.40.50 -> 10.0.30.10:443 stops at dist1, which has NO RIB"). Regenerating the
 * sample gave dist1 a RIB, and 35 tests went red at once — not because a surface lied, but because the
 * PROPERTY each test was about had moved to another flow. A test that names its subject by the property it
 * needs ("a decided delivery over two hops", "a hop on a host whose table is shown incomplete") finds that
 * subject on whatever snapshot is loaded, and fails loudly — through the caller's own precondition — only
 * when the snapshot really has no such subject. Sample-specific literals belong in `describeGolden` blocks
 * (src/test-support/golden-sample.ts), never here.
 *
 * The universe is: every suggested flow, plus every ordered pair of addresses the snapshot's SVI records
 * name (the interface address, the FHRP virtual address, and an ordinary host address inside each
 * subnet) together with two addresses no collection holds (a documentation address and a public
 * resolver), over a small set of services. That is the same space `PathTrace.claim-cites.test.tsx`
 * swept before this module owned it.
 *
 * Plus the ROUTED destinations (2026-09-28 verifier V1): for every route an ordinary host address can be
 * forwarded by (`exercisableRoutes`) that no SVI-universe address already is, one such address. The SVI subnets alone are a hand-picked stand-in for
 * "where a packet can go": the engine's golden fleet routes 10.0.0.0/16 off-SVI, and its only decided
 * denial is a flow to such a destination, so an SVI-only universe reported "this snapshot has no decided
 * denial" for a snapshot that has one. The route table is the forwarding denominator, so the destinations
 * are derived from it. The pairs that involve a routed address are APPENDED after the SVI pairs, so the
 * order - and therefore every "first trace with the property" - of the SVI universe is unchanged.
 */
import { expect, type TestContext } from "vitest";
import { fabric } from "../core/data";
import { own } from "../core/own";
import { isGoldenSample } from "./golden-sample";
import type { Flow, RouteEntry, Trace } from "../core/types";
import { suggestedFlows, traceFlow } from "../forwarding/engine";
import { formatIpv4, hostAddressIn, parseInterfaceAddress, parseIpv4, parsePrefix, rankPrefixMatches, type Ipv4, type Prefix } from "../forwarding/ip";

/** Addresses outside every collected subnet: RFC 5737 documentation space, and a public resolver. */
export const OUTSIDE_ADDRESSES: readonly string[] = ["198.51.100.7", "8.8.8.8"];

/** The services the grid poses. The ports are the ones the engine's own presets and intents use. */
export const UNIVERSE_SERVICES: readonly (readonly [Flow["protocol"], number | null])[] = [
  ["tcp", 443],
  ["tcp", 3389],
  ["tcp", 22],
  ["udp", 53],
  ["icmp", null],
];

export const flowOf = (srcIp: string, dstIp: string, protocol: Flow["protocol"], dstPort: number | null): Flow => ({
  srcIp,
  dstIp,
  protocol,
  dstPort,
  srcPort: null,
});

/** A plain HOST address inside each SVI subnet the snapshot records — never a device's own address. */
export function subnetHostAddresses(): { host: string; vlan: number | null; ip: string; cite: string; fhrpRole: string | null }[] {
  const owned = deviceOwnedAddresses();
  const out: { host: string; vlan: number | null; ip: string; cite: string; fhrpRole: string | null }[] = [];
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    if (a === null || r.host === null) continue;
    for (const offset of [50, 60, 70]) {
      const ip = hostAddressIn(a.prefix, offset);
      if (ip === null) continue;
      const text = formatIpv4(ip);
      if (owned.has(text)) continue;
      out.push({ host: r.host, vlan: r.vlan, ip: text, cite: r.cite, fhrpRole: r.fhrpRole });
      break;
    }
  }
  return out;
}

/** Every address a device owns on an SVI: its interface address and any FHRP virtual address. */
export function deviceOwnedAddresses(): Set<string> {
  const out = new Set<string>();
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    if (a !== null) out.add(formatIpv4(a.ip));
    if (r.vip !== null && parseIpv4(r.vip) !== null) out.add(r.vip);
  }
  return out;
}

/**
 * Candidate ordinary-host addresses inside a prefix: the SVI helper's offsets first, then a spread over the
 * whole prefix (the first and last 256 hosts and 256 evenly spaced ones), so a prefix whose low end is
 * covered by longer prefixes still yields a candidate its OWN route is chosen for.
 */
export function candidateHostsIn(p: Prefix): Ipv4[] {
  const size = 2 ** (32 - p.bits);
  const offsets = new Set<number>([50, 60, 70]);
  for (let o = 1; o <= Math.min(256, size - 2); o++) offsets.add(o);
  const step = Math.max(1, Math.floor(size / 256));
  for (let o = 0; o < size; o += step) offsets.add(o);
  for (let o = Math.max(1, size - 257); o < size - 1; o++) offsets.add(o);
  const out: Ipv4[] = [];
  for (const o of offsets) {
    const ip = hostAddressIn(p, o);
    if (ip !== null) out.push(ip);
  }
  return out;
}

/** Every address the snapshot shows a device owning: SVI and FHRP addresses, and every /32 a table records. */
export function ownedAddressesWithHostRoutes(): Set<string> {
  const owned = deviceOwnedAddresses();
  for (const rs of Object.values(fabric.routes))
    for (const r of rs) {
      const p = parsePrefix(r.prefix);
      if (p !== null && p.bits === 32) owned.add(formatIpv4(p.base));
    }
  return owned;
}

/** The route entry a host's table chooses for an address (longest match; the table's own order breaks ties). */
export const longestMatchOn = (host: string, ip: Ipv4): RouteEntry | undefined =>
  rankPrefixMatches(own(fabric.routes, host) ?? [], ip, (r) => r.prefix)[0]?.item;

/**
 * Every route entry an ordinary host address can be forwarded BY: a prefix of 1..31 bits on any host's table
 * for which some non-device address inside it is longest-matched to that very entry. The default route is
 * excluded (the outside addresses stand for it) and so is a /32 (a device's own address, not a destination
 * host). This is the forwarding denominator the universe's destinations must cover.
 */
export function exercisableRoutes(): { host: string; route: RouteEntry; witness: string }[] {
  const owned = ownedAddressesWithHostRoutes();
  const out: { host: string; route: RouteEntry; witness: string }[] = [];
  for (const host of Object.keys(fabric.routes).sort())
    for (const r of own(fabric.routes, host) ?? []) {
      const p = parsePrefix(r.prefix);
      if (p === null || p.bits === 0 || p.bits === 32) continue;
      const witness = candidateHostsIn(p).find((ip) => !owned.has(formatIpv4(ip)) && longestMatchOn(host, ip) === r);
      if (witness !== undefined) out.push({ host, route: r, witness: formatIpv4(witness) });
    }
  return out;
}

/** The addresses of the SVI universe: outside addresses, suggested-flow endpoints, device SVI/FHRP addresses, SVI hosts. */
function sviUniverseAddresses(): Set<string> {
  const addrs = new Set<string>(OUTSIDE_ADDRESSES);
  for (const s of suggestedFlows()) {
    addrs.add(s.flow.srcIp);
    addrs.add(s.flow.dstIp);
  }
  for (const a of deviceOwnedAddresses()) addrs.add(a);
  for (const h of subnetHostAddresses()) addrs.add(h.ip);
  return addrs;
}

/**
 * The ROUTED destinations: for every exercisable route that no SVI-universe address is already forwarded by,
 * one ordinary host address that is (its witness). On a snapshot whose every route is reached through an SVI
 * subnet this is empty and the universe is exactly the SVI universe.
 */
export function routedHostAddresses(): { host: string; prefix: string; ip: string; cite: string }[] {
  const base = [...sviUniverseAddresses()].flatMap((a) => {
    const ip = parseIpv4(a);
    return ip === null ? [] : [ip];
  });
  const out: { host: string; prefix: string; ip: string; cite: string }[] = [];
  const chosen = new Set<string>();
  for (const { host, route, witness } of exercisableRoutes()) {
    const covered = [...base, ...[...chosen].map((c) => parseIpv4(c)!)].some((ip) => longestMatchOn(host, ip) === route);
    if (covered) continue;
    chosen.add(witness);
    out.push({ host, prefix: route.prefix, ip: witness, cite: route.cite });
  }
  return out;
}

let flowsCache: Flow[] | null = null;
/** Every flow of the universe: suggested flows first, then the SVI pairs, then the routed pairs; stable. */
export function universeFlows(): Flow[] {
  if (flowsCache !== null) return flowsCache;
  const addrs = sviUniverseAddresses();
  const out: Flow[] = suggestedFlows().map((s) => s.flow);
  const seen = new Set(out.map((f) => JSON.stringify(f)));
  const pairs = (srcs: readonly string[], dsts: readonly string[]): void => {
    for (const src of srcs)
      for (const dst of dsts)
        for (const [protocol, dstPort] of UNIVERSE_SERVICES) {
          if (src === dst) continue;
          const f = flowOf(src, dst, protocol, dstPort);
          const k = JSON.stringify(f);
          if (seen.has(k)) continue;
          seen.add(k);
          out.push(f);
        }
  };
  const svi = [...addrs].sort();
  pairs(svi, svi);
  const routed = routedHostAddresses()
    .map((r) => r.ip)
    .filter((ip) => !addrs.has(ip))
    .sort();
  const all = [...new Set([...svi, ...routed])].sort();
  pairs(all, routed);
  pairs(routed, all);
  flowsCache = out;
  return out;
}

let tracesCache: Trace[] | null = null;
/** Every flow of the universe, traced by the real engine once per test file. */
export function universeTraces(): Trace[] {
  if (tracesCache === null) tracesCache = universeFlows().map(traceFlow);
  return tracesCache;
}

/**
 * The first trace of the universe with the property, or undefined. The CALLER asserts it is defined, with
 * a message naming the property, so an absent subject fails as "this snapshot has no X" — never silently.
 */
export function firstTrace(property: (t: Trace) => boolean): Trace | undefined {
  return universeTraces().find(property);
}

/** Every trace of the universe with the property. */
export function tracesWhere(property: (t: Trace) => boolean): Trace[] {
  return universeTraces().filter(property);
}

/** `?s=path&flow=…&hop=…` for a flow, in the form `decodeInvestigation` reads. */
export const pathSearch = (f: Flow, hop = 0): string => `?s=path&flow=${f.srcIp}>${f.dstIp}>${f.protocol}>${f.dstPort ?? ""}&hop=${hop}`;

/** A short label for a flow, for assertion messages. */
export const flowLabel = (f: Flow): string => `${f.protocol} ${f.srcIp} -> ${f.dstIp}:${f.dstPort ?? "*"}`;

/**
 * The subject a test needs, or — only on a snapshot that is NOT the tracked reference sample — a skip
 * that names what the snapshot lacks. On the reference sample an absent subject is a failure, never a
 * skip: the golden tier's rule (src/test-support/golden-sample.ts), applied to the property a test needs.
 * The skip is preceded by the assertion that licenses it, so it is never a silent pass.
 */
export function need<T>(ctx: TestContext, subject: T | undefined | null, what: string): T {
  if (subject === undefined || subject === null) {
    expect(isGoldenSample(), `precondition: the reference sample has ${what}`).toBe(false);
    ctx.skip(`not applicable to this snapshot: it has no ${what}`);
  }
  return subject as T;
}

/** A list, or undefined when it is empty — for `need`, whose subject is a whole class of traces. */
export const nonEmpty = <T>(xs: readonly T[]): readonly T[] | undefined => (xs.length > 0 ? xs : undefined);
