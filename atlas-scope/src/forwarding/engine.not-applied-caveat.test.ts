/**
 * engine.not-applied-caveat.test.ts — the caveat about an ACL that was NOT applied describes lines
 * that can actually match the flow, for every protocol the engine accepts.
 *
 * The defect (2026-09-23 acceptance report, adjacent to B5): `notAppliedCaveat` chose the lines it
 * describes by ADDRESS only, so a udp or icmp flow from 10.0.10.0/24 was told that core1's
 * INET_RETURN "matches this flow at acls.core1.INET_RETURN[1]" — `permit tcp 10.0.10.0 0.0.0.255
 * any eq 443 time-range …`, a TCP-only line whose protocol excludes the flow. The report measured
 * it in 50 of 3,968 traces.
 *
 * The check below is independent of the caveat's branches: every line the caveat cites with a
 * matching verb is looked up by its citation and re-matched against the flow with the engine's own
 * matcher (`matchTri`). "matches" must mean the matcher says yes; "could match" must mean it does
 * not say no. The sweep is over `FLOW_PROTOCOLS` — the engine's own protocol set, not a list typed
 * here — and over the suggested flows plus flows synthesised from every observed SVI subnet.
 *
 * Measured with the fix removed (address-only candidate lines, verb always "matches"): this sweep's
 * 3,269 traces carried 78 protocol-excluded "matches" citations (the report's own generator, 3,968
 * traces, counted 50 traces), and every case below went red; with the fix, 0. The sweep also audits
 * the other sentences that say a cited line could match a flow — an applied list's undecidable
 * line, a not-applied list's undecidable-line evidence, and a suggested flow's rationale — so the
 * rule is held for the class of sentence, not the one parenthetical that was caught.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import type { AclLine, Flow } from "../core/types";
import { FLOW_PROTOCOLS, formatIpv4, hostAddressIn, parseInterfaceAddress, parseIpv4, protocolCarriesPorts } from "./ip";
import { evaluateAcls, matchTri, suggestedFlows, traceFlow, type Tri } from "./engine";

/** The line a citation names, or undefined when the citation does not resolve. */
function lineAt(cite: string): AclLine | undefined {
  const m = /^acls\.([^.]+)\.([^[]+)\[(\d+)\]$/.exec(cite);
  if (m === null) return undefined;
  return fabric.acls[m[1]!]?.[m[2]!]?.[Number(m[3])];
}

/** Addresses the sweep uses: three hosts inside every observed SVI subnet, plus two off-fabric. */
function sweepAddresses(): string[] {
  const out = new Set<string>();
  for (const r of fabric.l3) {
    if (r.sviIp === null) continue;
    const a = parseInterfaceAddress(r.sviIp);
    if (a === null) continue;
    for (const off of [7, 10, 50]) {
      const h = hostAddressIn(a.prefix, off);
      if (h !== null) out.add(formatIpv4(h));
    }
  }
  out.add("8.8.8.8");
  out.add("198.51.100.7");
  return [...out].sort();
}

/** Ports per protocol, drawn from the ports the collected ACL lines themselves name. */
function sweepPorts(): number[] {
  const ports = new Set<number>([3389]);
  for (const named of Object.values(fabric.acls))
    for (const lines of Object.values(named))
      for (const l of lines) {
        if (l.dport === null) continue;
        if (typeof l.dport.val === "number") ports.add(l.dport.val);
      }
  return [...ports].sort((a, b) => a - b);
}

function sweepFlows(): Flow[] {
  const flows: Flow[] = suggestedFlows().map((s) => s.flow);
  const addrs = sweepAddresses();
  const ports = sweepPorts();
  for (const s of addrs)
    for (const d of addrs) {
      if (s === d) continue;
      for (const protocol of FLOW_PROTOCOLS) {
        for (const dstPort of protocolCarriesPorts(protocol) ? ports : [null]) flows.push({ srcIp: s, dstIp: d, protocol, dstPort, srcPort: null });
      }
    }
  return flows;
}

interface Violation {
  flow: string;
  cite: string;
  verb: string;
  tri: Tri;
}

/**
 * Every sentence in these texts that says a CITED line matches, or could match, this flow —
 * re-derived from the line and the flow. The forms, all of which the engine emits:
 *   "<LIST> (<verb> this flow at <cite>…"                       not-applied list, one line named
 *   "<LIST> (<verb> this flow only through catch-all lines)"    not-applied list, catch-alls only
 *   "(<cite>) "<raw>" could match this flow but …"              an applied list's undecidable line
 *   "<cite> ("<raw>") could match this flow and …"              a suggested flow's rationale
 * Returns the violations and how many citations were checked.
 */
function audit(flow: Flow, caveats: readonly string[]): { violations: Violation[]; checked: number; excludedByProtocol: number } {
  const src = parseIpv4(flow.srcIp)!;
  const dst = parseIpv4(flow.dstIp)!;
  const violations: Violation[] = [];
  let checked = 0;
  let excludedByProtocol = 0;
  const text = caveats.join("\n");
  const cited = [
    ...[...text.matchAll(/\b(matches|could match) this flow at (acls\.[^\s,;)]+)/g)].map((m) => ({ verb: m[1]!, cite: m[2]! })),
    ...[...text.matchAll(/\((acls\.[^\s)]+)\) "[^"]*" (could match) this flow\b/g)].map((m) => ({ verb: m[2]!, cite: m[1]! })),
    ...[...text.matchAll(/(?:^|\s)(acls\.[^\s(]+) \("[^"]*"\) (could match) this flow\b/g)].map((m) => ({ verb: m[2]!, cite: m[1]! })),
  ];
  for (const { verb, cite } of cited) {
    const line = lineAt(cite);
    expect(line, `unresolvable citation ${cite}`).toBeDefined();
    const tri = matchTri(line!, flow, src, dst);
    checked += 1;
    const ok = verb === "matches" ? tri === "yes" : tri !== "no";
    if (!ok) {
      violations.push({ flow: JSON.stringify(flow), cite, verb, tri });
      if (tri === "no" && line!.proto !== null && line!.proto.toLowerCase() !== "ip" && line!.proto.toLowerCase() !== flow.protocol) excludedByProtocol += 1;
    }
  }
  for (const m of text.matchAll(/(\w+) \((matches|could match) this flow only through catch-all lines\)/g)) {
    const [, name, verb] = m;
    // The host whose "also defines" sentence carries this parenthetical: the nearest one before it.
    const host = [...text.slice(0, m.index).matchAll(/(\S+) also defines/g)].pop()?.[1];
    const lines = host === undefined ? [] : (fabric.acls[host]?.[name!] ?? []);
    const tris = lines.map((l) => matchTri(l, flow, src, dst));
    checked += 1;
    const ok = verb === "matches" ? tris.includes("yes") : tris.some((t) => t !== "no");
    if (!ok) violations.push({ flow: JSON.stringify(flow), cite: `${host}.${name}`, verb: `${verb!} (catch-all)`, tri: tris.includes("maybe") ? "maybe" : "no" });
  }
  return { violations, checked, excludedByProtocol };
}

describe("the not-applied-ACL caveat never says a line matches a flow its protocol or port excludes", () => {
  const flows = sweepFlows();

  it("over every suggested and synthesised flow, for every protocol the engine accepts (traces)", () => {
    const violations: Violation[] = [];
    let checked = 0;
    let protocolViolations = 0;
    const perProtocol = new Map<string, number>();
    for (const f of flows) {
      const t = traceFlow(f);
      const r = audit(f, t.caveats);
      violations.push(...r.violations);
      // Hop evidence says it too ("… could match this flow and cannot be evaluated"), citing the line separately.
      for (const e of t.hops.flatMap((h) => h.evidence)) {
        if (!/\bcould match this flow\b/.test(e.label)) continue;
        const line = lineAt(e.cite);
        if (line === undefined) continue;
        const tri = matchTri(line, f, parseIpv4(f.srcIp)!, parseIpv4(f.dstIp)!);
        r.checked += 1;
        if (tri === "no") violations.push({ flow: JSON.stringify(f), cite: e.cite, verb: "could match (evidence)", tri });
      }
      checked += r.checked;
      protocolViolations += r.excludedByProtocol;
      if (r.checked > 0) perProtocol.set(f.protocol, (perProtocol.get(f.protocol) ?? 0) + 1);
    }
    // Non-vacuity: the sweep reaches the caveat, and for more than the one protocol that was right by luck.
    expect(checked, `${flows.length} traces`).toBeGreaterThan(0);
    // Every protocol the engine accepts reaches a match citation, so a caveat right for one protocol only cannot hide.
    expect([...perProtocol.keys()].sort(), `protocols whose traces carry a match citation: ${JSON.stringify([...perProtocol])}`).toEqual(
      [...FLOW_PROTOCOLS].sort(),
    );
    expect(protocolViolations, `${flows.length} traces; protocol-excluded "matches" citations`).toBe(0);
    expect(violations.slice(0, 5), `${violations.length} violations over ${flows.length} traces`).toEqual([]);
  });

  it("at the fallback seam too (core1 with no binding consulted), where every list is contested", () => {
    const violations: Violation[] = [];
    let checked = 0;
    const perProtocol = new Map<string, number>();
    for (const f of flows) {
      const r = audit(f, evaluateAcls("core1", f, parseIpv4(f.srcIp)!, parseIpv4(f.dstIp)!).caveats);
      violations.push(...r.violations);
      checked += r.checked;
      if (r.checked > 0) perProtocol.set(f.protocol, (perProtocol.get(f.protocol) ?? 0) + 1);
    }
    expect(checked).toBeGreaterThan(0);
    // Every protocol reaches the seam, so a caveat that is right for tcp only cannot hide here.
    expect([...perProtocol.keys()].sort()).toEqual([...FLOW_PROTOCOLS].sort());
    expect(violations.slice(0, 5), `${violations.length} violations over ${flows.length} fallback evaluations`).toEqual([]);
  });

  it("the suggested flows' rationales say a line could match only where the matcher does not exclude it", () => {
    const violations: Violation[] = [];
    let checked = 0;
    for (const s of suggestedFlows()) {
      const r = audit(s.flow, [s.rationale]);
      violations.push(...r.violations);
      checked += r.checked;
    }
    // Non-vacuity: at least one suggestion names an undecidable line as able to match its flow.
    expect(checked).toBeGreaterThan(0);
    expect(violations).toEqual([]);
  });

  it("the headline udp case: INET_RETURN's tcp-only line is not cited to a udp flow", () => {
    const f: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "udp", dstPort: 53, srcPort: null };
    const joined = evaluateAcls("core1", f, parseIpv4(f.srcIp)!, parseIpv4(f.dstIp)!).caveats.join(" ");
    expect(joined).toMatch(/INET_RETURN \(/);
    expect(joined).not.toMatch(/(matches|could match) this flow at acls\.core1\.INET_RETURN\[[01]\]/);
    // The tcp flow on the port that line names still gets the specific citation (engine.test.ts pins it too).
    const t: Flow = { ...f, protocol: "tcp", dstPort: 443 };
    expect(evaluateAcls("core1", t, parseIpv4(t.srcIp)!, parseIpv4(t.dstIp)!).caveats.join(" ")).toMatch(
      /INET_RETURN \(matches this flow at acls\.core1\.INET_RETURN\[1\]/,
    );
  });

  it("an ip flow (spanning protocols) is told a tcp-only line COULD match it, never that it matches", () => {
    const f: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "ip", dstPort: null, srcPort: null };
    const joined = evaluateAcls("core1", f, parseIpv4(f.srcIp)!, parseIpv4(f.dstIp)!).caveats.join(" ");
    expect(joined).toMatch(/INET_RETURN \(could match this flow at acls\.core1\.INET_RETURN\[1\]/);
  });

  it("a discarded list none of whose lines can match is said to fall to its implicit deny, naming the exclusion", () => {
    /* No list in this snapshot lacks a trailing `deny ip any any`, so the branch is reached by
       handing the engine a real line on its own: INET_RETURN[1], verbatim, as the only line of the
       list. Nothing is fabricated; the list is shortened. */
    const f: Flow = { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "udp", dstPort: 53, srcPort: null };
    const core1 = fabric.acls["core1"]!;
    const named = { PROTECT_SERVERS: core1["PROTECT_SERVERS"]!, INET_RETURN: [core1["INET_RETURN"]![1]!] };
    const joined = evaluateAcls("core1", f, parseIpv4(f.srcIp)!, parseIpv4(f.dstIp)!, named).caveats.join(" ");
    expect(joined).toContain(
      "INET_RETURN (names this flow's addresses but no line of it can match this flow — at acls.core1.INET_RETURN[1] its protocol (tcp) cannot match a udp flow — so, were it applied, this flow would fall to the list's implicit deny)",
    );
    expect(joined).not.toMatch(/(matches|could match) this flow at acls\.core1\.INET_RETURN/);
  });
});
