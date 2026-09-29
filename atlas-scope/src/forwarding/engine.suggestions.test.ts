/**
 * engine.suggestions.test.ts — the suggested flows offer a DECIDED multi-hop delivery, a DECIDED multi-hop
 * denial that names its blocking line, and a counterexample search that finds one (A2 / B8) — derived from
 * the loaded data, never typed in.
 *
 * Two tiers (../test-support/golden-sample.ts):
 *  - INVARIANTS, over whatever fabric is loaded: each multi-hop preset IS what it poses (hop count, decided,
 *    the blocking line's host / list / line / literal text, a counterexample found and itself decided), and
 *    its absence is honest: an independent sweep over the same observed subnets and ACL-named services finds
 *    no such trace the engine failed to offer. The rationale's citations name real records, and its route
 *    claim is re-read from the RIB.
 *  - GOLDEN, on the tracked sample only: which flows those are, read from ./golden-expectations.ts.
 */
import { describe, expect, it } from "vitest";
import { bandOfTrace, claimBadge, isDecidedOutcome } from "../core/claims";
import { aclsOf, fabric, resolveCite, routesOf } from "../core/data";
import type { Flow, Trace } from "../core/types";
import { describeGolden } from "../test-support/golden-sample";
import { GOLDEN_FORWARDING as G } from "./golden-expectations";
import { formatIpv4, hostAddressIn, parseInterfaceAddress, parseIpv4, parsePrefix, prefixContains } from "./ip";
import {
  blockingHop,
  counterexample,
  isDecidedRefusal,
  isDefiniteDelivery,
  isDefiniteOnModelledPath,
  lineEvaluability,
  MULTIHOP_PRESET_CANDIDATE_CAP,
  suggestedFlows,
  traceFlow,
  type SuggestedFlow,
} from "./engine";

const presets = suggestedFlows();
const preset = (id: string): SuggestedFlow | undefined => presets.find((s) => s.id === id);

/** Every address a collected device owns — an SVI address, an FHRP virtual address, a RIB `local` /32. */
function ownedBy(): Map<string, Set<string>> {
  const m = new Map<string, Set<string>>();
  const add = (ip: string, host: string): void => {
    const s = m.get(ip) ?? new Set<string>();
    s.add(host);
    m.set(ip, s);
  };
  for (const r of fabric.l3) {
    if (r.host === null) continue;
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    if (a !== null) add(formatIpv4(a.ip), r.host);
    if (r.vip !== null) add(r.vip, r.host);
  }
  for (const [host, rs] of Object.entries(fabric.routes))
    for (const r of rs) if (r.source === "local" && r.prefix.endsWith("/32")) add(r.prefix.slice(0, -3), host);
  return m;
}
const OWNERS = ownedBy();

/** Every `cite` a compiled record carries (endpoint and l3 cites are source-snapshot paths resolveCite does not walk). */
const RECORD_CITES: ReadonlySet<string> = (() => {
  const out = new Set<string>();
  const walk = (v: unknown): void => {
    if (Array.isArray(v)) for (const x of v) walk(x);
    else if (v !== null && typeof v === "object") {
      const c = (v as Record<string, unknown>)["cite"];
      if (typeof c === "string") out.add(c);
      for (const x of Object.values(v)) walk(x);
    }
  };
  walk(fabric);
  return out;
})();
const citeNamesARecord = (c: string): boolean => resolveCite(c) !== undefined || RECORD_CITES.has(c);

/** The literal ACL record a citation `acls.<host>.<name>[<i>]` names, read from the compiled model. */
function aclLineAt(cite: string): { host: string; name: string; index: number; count: number; raw: string | null } | null {
  const m = /^acls\.([^.]+)\.([^[]+)\[(\d+)\]$/.exec(cite);
  if (m === null) return null;
  const [, host, name, i] = m;
  const lines = aclsOf(host!)[name!] ?? [];
  const line = lines.find((l) => l.index === Number(i));
  return line === undefined ? null : { host: host!, name: name!, index: line.index, count: lines.length, raw: line.raw };
}

/** Every resolved next hop is an address the data says the NEXT hop's device owns. */
function expectNextHopsOwned(t: Trace, where: string): void {
  for (let i = 0; i < t.hops.length - 1; i += 1) {
    const h = t.hops[i]!;
    expect(h.nextHost, `${where} hop ${i}: a non-terminal hop names the next device`).toBe(t.hops[i + 1]!.host);
    expect(h.nextHop, `${where} hop ${i}: a routed hop names its next-hop address`).not.toBeNull();
    expect(OWNERS.get(h.nextHop!)?.has(h.nextHost!), `${where} hop ${i}: ${h.nextHop} is an address of ${h.nextHost}`).toBe(true);
  }
}

/* ── the independent search: the same question space, asked without the engine's pruning ─────────── */

/** One host address per observed SVI subnet (an observed endpoint first), and every ACL-named service. */
function sweep(): Flow[] {
  const endpoints = [...new Set(fabric.endpoints.map((e) => e.ip).filter((ip): ip is string => ip !== null))].sort();
  const addrs = new Set<string>();
  const prefixes = new Set<string>();
  for (const r of fabric.l3) {
    const a = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    if (a !== null) prefixes.add(`${formatIpv4(a.prefix.base)}/${a.prefix.bits}`);
  }
  for (const rs of Object.values(fabric.routes)) for (const r of rs) if (r.source === "connected") prefixes.add(r.prefix);
  for (const p of prefixes) {
    const pre = parsePrefix(p);
    if (pre === null) continue;
    const seen = endpoints.filter((ip) => prefixContains(pre, parseIpv4(ip)!) && !OWNERS.has(ip));
    for (const ip of seen) addrs.add(ip);
    for (const off of [10, 50]) {
      const h = hostAddressIn(pre, off);
      if (h !== null && !OWNERS.has(formatIpv4(h))) addrs.add(formatIpv4(h));
    }
  }
  const services = new Set<string>();
  for (const named of Object.values(fabric.acls))
    for (const lines of Object.values(named))
      for (const l of lines) {
        const proto = (l.proto ?? "").toLowerCase();
        if ((l.action ?? "").toLowerCase() !== "permit" || !lineEvaluability(l).evaluable || (proto !== "tcp" && proto !== "udp")) continue;
        if (l.dport !== null && l.dport.op.toLowerCase() === "eq" && typeof l.dport.val === "number") services.add(`${proto}/${l.dport.val}`);
      }
  const out: Flow[] = [];
  const list = [...addrs].sort();
  for (const s of list)
    for (const d of list)
      for (const svc of services) {
        if (s === d) continue;
        const [protocol, port] = svc.split("/") as ["tcp" | "udp", string];
        out.push({ srcIp: s, dstIp: d, protocol, dstPort: Number(port), srcPort: null });
      }
  return out;
}

describe("the multi-hop presets are what they pose (invariant: any loaded fabric)", () => {
  it("a 'multi-hop-delivery' preset is a DECIDED delivery over two or more hops, each next hop owned by the next device", () => {
    const s = preset("multi-hop-delivery");
    if (s === undefined) {
      /* Absence is legal only when the data holds no such trace — the completeness test below proves that. */
      expect(presets.map((p) => p.id)).not.toContain("multi-hop-delivery");
      return;
    }
    const t = traceFlow(s.flow);
    expect(s.expectedOutcome).toBe("delivered");
    expect(t.outcome).toBe("delivered");
    expect(t.hops.length, "a multi-hop preset crosses more than one collected routing table").toBeGreaterThanOrEqual(2);
    expect(isDefiniteDelivery(t)).toBe(true);
    expect(isDecidedOutcome(t), "the claims owner agrees it is decided").toBe(true);
    expect(bandOfTrace(t)).toBe("RESOLVED");
    expect(claimBadge(t)).toBe("SCOPED");
    expectNextHopsOwned(t, s.id);
    expect(t.hops.every((h) => h.decidedBy !== null)).toBe(true);
  });

  it("a 'multi-hop-denial' preset is a DECIDED denial over two or more hops naming host, ACL, line and literal text", () => {
    const s = preset("multi-hop-denial");
    if (s === undefined) {
      expect(presets.map((p) => p.id)).not.toContain("multi-hop-denial");
      return;
    }
    const t = traceFlow(s.flow);
    expect(s.expectedOutcome).toBe("denied");
    expect(t.outcome).toBe("denied");
    expect(t.hops.length).toBeGreaterThanOrEqual(2);
    expect(isDecidedRefusal(t)).toBe(true);
    expect(isDecidedOutcome(t), "the claims owner agrees it is decided").toBe(true);
    expect(bandOfTrace(t)).toBe("REFUTED");
    expectNextHopsOwned(t, s.id);
    const b = blockingHop(t);
    expect(b, "the denial names its blocking hop").not.toBeNull();
    expect(b!.hop).toBe(t.hops[t.hops.length - 1]);
    expect(b!.evidence.kind).toBe("acl");
    /* Host, ACL, line and literal text — each read back from the compiled ACL record the citation names. */
    const line = aclLineAt(b!.evidence.cite);
    expect(line, `${b!.evidence.cite} names a collected ACL line`).not.toBeNull();
    expect(line!.host).toBe(b!.hop.host);
    expect(b!.evidence.raw).toBe(line!.raw);
    expect(b!.evidence.raw).not.toBeNull();
    expect(b!.evidence.label).toContain(line!.name);
    expect(b!.evidence.label).toContain(`line ${line!.index + 1} of ${line!.count}`);
    expect(t.claim).toContain(`denied at ${line!.host} by ACL ${line!.name} line ${line!.index + 1} of ${line!.count}`);
    expect(t.claim).toContain(`"${line!.raw}"`);
  });

  it("the denial's counterexample search FINDS one (B8), and what it offers is itself a decided delivery on its path", () => {
    const s = preset("multi-hop-denial");
    if (s === undefined) {
      expect(presets.map((p) => p.id)).not.toContain("multi-hop-denial");
      return;
    }
    const t = traceFlow(s.flow);
    const cx = counterexample(s.flow, t);
    expect(cx.found).toBe(true);
    if (!cx.found) return;
    expect(cx.trace.outcome).toBe("delivered");
    expect(isDefiniteOnModelledPath(cx.trace)).toBe(true);
    expect(traceFlow(cx.flow).outcome).toBe("delivered");
    expect(cx.flow.srcIp, "a counterexample varies the flow, not its source").toBe(s.flow.srcIp);
    expect(JSON.stringify(cx.flow)).not.toBe(JSON.stringify(s.flow));
  });

  it("each multi-hop rationale's route claim is re-read from the RIB, and every citation it prints names a record", () => {
    let checked = 0;
    for (const s of presets.filter((p) => p.id.startsWith("multi-hop-"))) {
      const m = /collected RIB sends (\S+) to next hop (\S+) \((routes\.[^)]+)\), an address of (\S+) \(/.exec(s.rationale);
      expect(m, `${s.id}: ${s.rationale}`).not.toBeNull();
      const [, prefix, nh, cite, next] = m!;
      const route = resolveCite(cite!) as { prefix?: string; nextHop?: string } | undefined;
      expect(route?.prefix, cite).toBe(prefix);
      expect(route?.nextHop, cite).toBe(nh);
      expect(OWNERS.get(nh!)?.has(next!), `${nh} is an address of ${next}`).toBe(true);
      expect(prefixContains(parsePrefix(prefix!)!, parseIpv4(s.flow.dstIp)!), "the destination lies in the route's prefix").toBe(true);
      const gw = traceFlow(s.flow).hops[0]!.host;
      expect(routesOf(gw).some((r) => r.cite === cite), "the route is the FIRST hop's own route").toBe(true);
      for (const c of s.rationale.match(/(?:routes|l3_forwarding|acls)[\w.[\]/-]*\[\d+\]/g) ?? []) expect(citeNamesARecord(c), c).toBe(true);
      checked += 1;
    }
    expect(checked).toBe(presets.filter((p) => p.id.startsWith("multi-hop-")).length);
  });

  it("an absent multi-hop preset is honest: an independent sweep finds no such trace the engine did not offer", () => {
    /* The class, not the instance: a preset is offered iff the data holds one. Swept independently of the
       engine's route-edge pruning, over one host address per observed subnet and every ACL-named service. */
    const flows = sweep();
    expect(flows.length, "the sweep is not empty").toBeGreaterThan(0);
    let delivery: Flow | null = null;
    let denial: Flow | null = null;
    for (const f of flows) {
      if (delivery !== null && denial !== null) break;
      const t = traceFlow(f);
      if (t.hops.length < 2) continue;
      if (delivery === null && t.outcome === "delivered" && isDefiniteDelivery(t)) delivery = f;
      if (denial === null && t.outcome === "denied" && isDecidedRefusal(t)) {
        const b = blockingHop(t);
        if (b !== null && b.evidence.kind === "acl" && b.evidence.raw !== null && counterexample(f, t).found) denial = f;
      }
    }
    expect(preset("multi-hop-delivery") !== undefined, `sweep found ${JSON.stringify(delivery)}`).toBe(delivery !== null);
    expect(preset("multi-hop-denial") !== undefined, `sweep found ${JSON.stringify(denial)}`).toBe(denial !== null);
  });

  it("the preset search is bounded by a count (work, not wall clock)", () => {
    expect(Number.isInteger(MULTIHOP_PRESET_CANDIDATE_CAP)).toBe(true);
    expect(MULTIHOP_PRESET_CANDIDATE_CAP).toBeGreaterThan(0);
  });
});

describe("isDecidedRefusal is the claims owner's refusal rule, restated where claims cannot be imported", () => {
  it("agrees with claims.isDecidedOutcome on every refusal over a sweep, and the sweep reaches both answers", () => {
    let decided = 0;
    let undecided = 0;
    for (const f of [...sweep(), ...presets.map((p) => p.flow)]) {
      const t = traceFlow(f);
      if (t.outcome !== "denied" && t.outcome !== "dropped") {
        expect(isDecidedRefusal(t), JSON.stringify(f)).toBe(false);
        continue;
      }
      expect(isDecidedRefusal(t), JSON.stringify(f)).toBe(isDecidedOutcome(t));
      if (isDecidedOutcome(t)) decided += 1;
      else undecided += 1;
    }
    expect(decided + undecided, "refusals in the sweep").toBeGreaterThan(0);
    expect(undecided, "undecided refusals in the sweep").toBeGreaterThan(0);
  });
});

describe("the no-route preset rests on its own trace (invariant; disc-app-sample-assumptions #2)", () => {
  it("is offered only as a FIRST-hop no-route at the gateway it names, and its premise is that hop's decidedBy", () => {
    const s = preset("no-route");
    if (s === undefined) {
      /* engine.no-route.counterfactual.test.ts runs the offered branch on a table with no default route. */
      expect(presets.map((p) => p.id)).not.toContain("no-route");
      return;
    }
    const t = traceFlow(s.flow);
    expect(t.hops.length).toBe(1);
    expect(t.hops[0]!.verdict).toBe("no-route");
    expect(s.title.startsWith(`${t.hops[0]!.host} `)).toBe(true);
    expect(s.rationale).toContain(t.hops[0]!.decidedBy!.label);
    expect(s.rationale).toContain(t.hops[0]!.decidedBy!.cite);
    expect(routesOf(t.hops[0]!.host).some((r) => r.prefix === "0.0.0.0/0"), "a table with a default route is never said to lack one").toBe(false);
  });
});

describeGolden("the reference sample's presets (golden-expectations.ts)", () => {
  it("offers exactly these presets, in this order", () => {
    expect(presets.map((p) => p.id)).toEqual([...G.presetIds]);
  });

  it("the decided multi-hop delivery is dist1 -> core1 into Vlan10", () => {
    const s = preset("multi-hop-delivery")!;
    expect(s.flow).toEqual(G.multiHopDelivery.flow);
    expect(s.srcProvenance.kind, "10.0.40.50 is derived inside dist1's Vlan40 subnet, and says so").toBe("derived-from-observed-subnet");
    const t = traceFlow(s.flow);
    expect(t.hops.map((h) => ({ host: h.host, verdict: h.verdict, decidedBy: h.decidedBy?.cite, nextHop: h.nextHop, nextHost: h.nextHost }))).toEqual(
      G.multiHopDelivery.hops,
    );
  });

  it("the decided multi-hop denial is PROTECT_SERVERS line 4 of 4 at core1, with the counterexample into Vlan20", () => {
    const s = preset("multi-hop-denial")!;
    expect(s.flow).toEqual(G.multiHopDenial.flow);
    const t = traceFlow(s.flow);
    const b = blockingHop(t)!;
    expect(b.hop.host).toBe(G.multiHopDenial.blockingHost);
    expect(b.evidence.cite).toBe(G.multiHopDenial.blockingCite);
    expect(b.evidence.raw).toBe(G.multiHopDenial.blockingRaw);
    expect(b.evidence.label).toContain(G.multiHopDenial.blockingLine);
    expect(t.claim).toContain(G.multiHopDenial.boundOn);
    const cx = counterexample(s.flow, t);
    expect(cx.found && cx.flow).toEqual(G.multiHopDenial.counterexample);
    expect(cx.found && cx.trace.hops[cx.trace.hops.length - 1]!.decidedBy!.cite).toBe(G.multiHopDenial.counterexampleDecidedBy);
    /* The critic's own port (R2): the same pair on tcp/3389 is decided the same way and answered. */
    const rdp = traceFlow(G.multiHopDenialRdp);
    expect(isDecidedOutcome(rdp)).toBe(true);
    expect(blockingHop(rdp)!.evidence.cite).toBe(G.multiHopDenial.blockingCite);
    expect(counterexample(G.multiHopDenialRdp, rdp).found).toBe(true);
  });

});
