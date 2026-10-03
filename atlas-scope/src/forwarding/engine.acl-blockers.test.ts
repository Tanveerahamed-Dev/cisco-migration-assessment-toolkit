/**
 * engine.acl-blockers.test.ts — an indeterminate ACL result names EVERY earlier line that could fire
 * first, each with its true reason (acceptance B5).
 *
 * Re-grade, 2026-10-03, on the real PROTECT_SERVERS list: an `ip` flow 10.0.10.50 -> 10.0.30.20 was
 * indeterminate, but the trace named line 1 (`permit tcp … eq 443`) as "cannot be evaluated" although
 * `lineEvaluability` calls it evaluable, and never named line 3 (`permit icmp … echo-reply`), the
 * unevaluable line that really blocks evaluation. The deny line read "an earlier unevaluable line may
 * fire first" without saying which, and said so too for a portless tcp flow where no unevaluable line
 * can match at all. `runLists` kept only the first undecidable line and gave every undecidable line the
 * "cannot be evaluated" reason, whether the MODEL could not read it or the FLOW left a field open.
 *
 * The first-pass oracle agreed with that by construction: it took "the first line that is unevaluable
 * or a maybe", which is the engine's own rule. The oracle here reads `lineEvaluability` and `matchTri`
 * per line, on its own, and asks the question the criterion asks: which lines above the match could
 * fire, and is each one named with the right kind of reason.
 */
import { describe, expect, it } from "vitest";

import { fabric } from "../core/data";
import { own } from "../core/own";
import type { AclLine, Flow, HopEvidence } from "../core/types";
import { GOLDEN_FORWARDING as G } from "../test-support/golden-expectations";
import { describeGolden, isGoldenSample } from "../test-support/golden-sample";
import { OUTSIDE_ADDRESSES, subnetHostAddresses } from "../test-support/trace-universe";
import { aclLineName } from "./acl-line";
import { evaluateAcls, evaluateListsInOrder, lineEvaluability, matchTri, traceFlow } from "./engine";
import { formatIpv4, parseIpv4, type Ipv4 } from "./ip";

const PS = G.core1Acls.protectServers;
const IR = G.core1Acls.inetReturn;
const HOST = G.core1Acls.host;
const BF = PS.blockerFlows;

const ip = (text: string): Ipv4 => {
  const v = parseIpv4(text);
  expect(v, `${text} parses`).not.toBeNull();
  return v!;
};

/** Every collected ACL line, by citation. */
const LINE_BY_CITE = new Map<string, AclLine>();
for (const host of Object.keys(fabric.acls).sort()) {
  const lists = own(fabric.acls, host) ?? {};
  for (const name of Object.keys(lists).sort()) for (const l of own(lists, name) ?? []) LINE_BY_CITE.set(l.cite, l);
}

const CITE = /acls\.[^\s()"';,]+\[\d+\]/g;

/* ── the oracle: read per line, independent of the walk under test ─────────────────────────────── */

interface Expected {
  /** Every line above the match (or in the whole list, when nothing matches) that could fire for this flow. */
  earlier: { line: AclLine; evaluable: boolean }[];
  /** The first line that is evaluable and definitely matches, or null. */
  match: AclLine | null;
}

function oracle(lines: readonly AclLine[], f: Flow, s: Ipv4, d: Ipv4): Expected {
  const earlier: Expected["earlier"] = [];
  for (const line of lines) {
    const tri = matchTri(line, f, s, d);
    const evaluable = lineEvaluability(line).evaluable;
    if (evaluable && tri === "yes") return { earlier, match: line };
    if (tri !== "no") earlier.push({ line, evaluable });
  }
  return { earlier, match: null };
}

/** The flow fields an evaluable line tests that this flow leaves open, read from the line's own fields. */
function unspecifiedFields(line: AclLine, f: Flow): string[] {
  const p = (line.proto ?? "").toLowerCase();
  const out: string[] = [];
  if (f.protocol === "ip" && p !== "ip") out.push("protocol");
  if (p === "tcp" || p === "udp") {
    if (line.sport !== null && f.srcPort === null) out.push("source port");
    if (line.dport !== null && f.dstPort === null) out.push("destination port");
  }
  return out;
}

const prefixOf = (host: string, name: string, line: AclLine, total: number): string => `${host} ACL ${name} ${aclLineName(line.index, total)} `;

/**
 * Every clause of `text` that names exactly one ACL line cite and says that line "cannot be evaluated"
 * must cite an unevaluable line. Clauses are split where this engine joins them: "; " and sentence ends.
 */
function falseUnevaluableClaims(text: string): string[] {
  const bad: string[] = [];
  for (const clause of text.split(/;\s+|\.\s+(?=[A-Z])/)) {
    const cites = [...new Set(clause.match(CITE) ?? [])];
    if (cites.length !== 1 || !clause.includes("cannot be evaluated")) continue;
    const line = LINE_BY_CITE.get(cites[0]!);
    if (line !== undefined && lineEvaluability(line).evaluable) bad.push(`${cites[0]} :: ${clause}`);
  }
  return bad;
}

/** An evidence row whose own predicate (the label past its line prefix) says its line cannot be evaluated. */
function rowSaysUnevaluable(e: HopEvidence): boolean {
  return /^\S+ ACL \S+ line \d+ of \d+ cannot be evaluated/.test(e.label);
}

/* ── the walk over every list of the snapshot ───────────────────────────────────────────────────── */

/** A spread of addresses read from the snapshot: SVI hosts, every ACL address and group member, and outside space. */
function sweepAddresses(): string[] {
  const out = new Set<string>([...subnetHostAddresses().map((a) => a.ip), ...OUTSIDE_ADDRESSES]);
  const add = (base: string | null, wild: string | null): void => {
    const b = base === null ? null : parseIpv4(base);
    if (b === null || b === 0) return;
    out.add(formatIpv4(b));
    const w = wild === null ? 0 : parseIpv4(wild);
    // One more address inside the field's space, not its base: a host address the line also covers.
    if (w !== null && w >= 31 && w !== 0xffffffff) out.add(formatIpv4((b + 20) >>> 0));
  };
  for (const line of LINE_BY_CITE.values()) {
    add(line.src?.ip ?? null, line.src?.wild ?? null);
    add(line.dst?.ip ?? null, line.dst?.wild ?? null);
  }
  for (const host of Object.keys(fabric.objectGroups).sort()) {
    const groups = own(fabric.objectGroups, host) ?? {};
    for (const g of Object.keys(groups).sort()) for (const m of own(groups, g)?.members ?? []) add(m.ip, m.wild);
  }
  return [...out].sort();
}

const PROTOCOLS: readonly Flow["protocol"][] = ["ip", "tcp", "udp", "icmp"];

/** The ports a list names (both operands of a range), plus one it names nowhere; and "no port". */
function sweepPorts(lines: readonly AclLine[]): (number | null)[] {
  const ports = new Set<number>([1]);
  for (const l of lines) {
    for (const m of [l.sport, l.dport]) {
      if (m === null) continue;
      if (typeof m.val === "number") ports.add(m.val);
      if (typeof m.val2 === "number") ports.add(m.val2);
    }
  }
  return [null, ...[...ports].sort((a, b) => a - b)];
}

describe("an indeterminate ACL walk names every earlier line that could fire, with its true reason", () => {
  it("holds for every list x protocol x port x source x destination of the loaded snapshot", () => {
    const addrs = sweepAddresses();
    let cases = 0;
    let withEvaluableBlocker = 0;
    let withUnevaluableBlocker = 0;
    let mixed = 0;
    let decidedAfterBlockers = 0;
    const failures: string[] = [];
    const fail = (where: string, what: string): void => {
      if (failures.length < 25) failures.push(`${where}: ${what}`);
    };

    for (const host of Object.keys(fabric.acls).sort()) {
      const lists = own(fabric.acls, host) ?? {};
      for (const name of Object.keys(lists).sort()) {
        const lines = own(lists, name) ?? [];
        const ports = sweepPorts(lines);
        for (const protocol of PROTOCOLS) {
          for (const dstPort of ports) {
            for (const srcIp of addrs) {
              for (const dstIp of addrs) {
                if (srcIp === dstIp) continue;
                const f: Flow = { srcIp, dstIp, protocol, dstPort, srcPort: null };
                const s = ip(srcIp);
                const d = ip(dstIp);
                const where = `${host} ${name} ${protocol} ${srcIp}->${dstIp}:${dstPort ?? "*"}`;
                const want = oracle(lines, f, s, d);
                const run = evaluateListsInOrder(host, f, s, d, { [name]: lines }, [name]);
                cases += 1;
                const ev = want.earlier.filter((e) => e.evaluable).length;
                if (ev > 0) withEvaluableBlocker += 1;
                if (want.earlier.length - ev > 0) withUnevaluableBlocker += 1;
                if (ev > 0 && want.earlier.length - ev > 0) mixed += 1;
                if (want.match !== null && want.earlier.length > 0) decidedAfterBlockers += 1;

                // The result is undecided exactly when some line above the match could fire.
                if ((run.indeterminate !== null) !== (want.earlier.length > 0)) {
                  fail(where, `indeterminate=${run.indeterminate !== null} but ${want.earlier.length} earlier line(s) could fire`);
                }

                // Every row that says "cannot be evaluated" is about an unevaluable line.
                for (const e of run.evidence) {
                  const line = LINE_BY_CITE.get(e.cite);
                  if (line !== undefined && rowSaysUnevaluable(e) && lineEvaluability(line).evaluable) {
                    fail(where, `evaluable ${e.cite} is called "cannot be evaluated": ${e.label}`);
                  }
                }
                // …and so is every clause of every caveat and label that names one line.
                for (const t of [...run.caveats, ...run.evidence.map((e) => e.label)]) {
                  for (const b of falseUnevaluableClaims(t)) fail(where, `false "cannot be evaluated": ${b}`);
                }

                // Every earlier line that could fire is named, with the right kind of reason.
                for (const e of want.earlier) {
                  const row = run.evidence.find((x) => x.cite === e.line.cite);
                  if (row === undefined) {
                    fail(where, `${e.line.cite} could fire first and is not named`);
                    continue;
                  }
                  if (e.evaluable) {
                    if (row.label.includes("cannot be evaluated")) fail(where, `evaluable ${e.line.cite} reads "${row.label}"`);
                    for (const field of unspecifiedFields(e.line, f)) {
                      if (!row.label.includes(field)) fail(where, `${e.line.cite} does not name the unspecified ${field}: "${row.label}"`);
                    }
                  } else if (!rowSaysUnevaluable(row)) {
                    fail(where, `unevaluable ${e.line.cite} reads "${row.label}"`);
                  }
                  if (!run.caveats.some((c) => c.includes(e.line.cite))) fail(where, `no caveat names ${e.line.cite}`);
                }

                // The matching line's "may fire first" appears iff such a line exists, and names each one.
                if (want.match !== null) {
                  const row = run.evidence.find((x) => x.cite === want.match!.cite);
                  if (row === undefined) {
                    fail(where, `the matching line ${want.match.cite} is not named`);
                    continue;
                  }
                  const says = row.label.includes("may fire first");
                  if (says !== want.earlier.length > 0) fail(where, `"may fire first" is ${says} with ${want.earlier.length} earlier line(s): "${row.label}"`);
                  if (want.earlier.length > 0) {
                    const named = new Set(row.label.match(CITE) ?? []);
                    const expected = new Set(want.earlier.map((e) => e.line.cite));
                    if ([...expected].some((c) => !named.has(c)) || [...named].some((c) => !expected.has(c))) {
                      fail(where, `"may fire first" names ${[...named].join(",")} but ${[...expected].join(",")} could fire: "${row.label}"`);
                    }
                    if (want.earlier.every((e) => e.evaluable) && /unevaluable|cannot be evaluated/.test(row.label)) {
                      fail(where, `no earlier line is unevaluable, yet the match reads "${row.label}"`);
                    }
                    if (!row.label.startsWith(`${prefixOf(host, name, want.match, lines.length)}would match, but `)) {
                      fail(where, `the matching line's label lost its shape: "${row.label}"`);
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    expect(failures, failures.join("\n")).toEqual([]);
    expect(cases).toBeGreaterThan(0);
    if (isGoldenSample()) {
      // Non-vacuity on the reference sample: every shape the criterion names was posed.
      expect(withEvaluableBlocker, "flows that leave an evaluable line open").toBeGreaterThan(0);
      expect(withUnevaluableBlocker, "flows an unevaluable line could match").toBeGreaterThan(0);
      expect(mixed, "flows with both kinds above the match").toBeGreaterThan(0);
      expect(decidedAfterBlockers, "a match below lines that could fire first").toBeGreaterThan(0);
    }
  });
});

describe("a trace never calls an evaluable line unevaluable", () => {
  it("over a spread of sources x destinations x {ip,tcp,udp,icmp} x port given / not given", () => {
    const addrs = [...new Set([...subnetHostAddresses().map((a) => a.ip), ...OUTSIDE_ADDRESSES])].sort();
    const services: [Flow["protocol"], number | null][] = [
      ["ip", null],
      ["tcp", null],
      ["tcp", 443],
      ["udp", null],
      ["udp", 53],
      ["icmp", null],
    ];
    const failures: string[] = [];
    let aclHops = 0;
    for (const srcIp of addrs) {
      for (const dstIp of addrs) {
        if (srcIp === dstIp) continue;
        for (const [protocol, dstPort] of services) {
          const t = traceFlow({ srcIp, dstIp, protocol, dstPort, srcPort: null });
          const where = `${protocol} ${srcIp}->${dstIp}:${dstPort ?? "*"}`;
          for (const h of t.hops) {
            for (const e of [...h.evidence, ...(h.decidedBy === null ? [] : [h.decidedBy])]) {
              const line = LINE_BY_CITE.get(e.cite);
              if (line === undefined) continue;
              aclHops += 1;
              if (rowSaysUnevaluable(e) && lineEvaluability(line).evaluable) failures.push(`${where}: ${e.cite} "${e.label}"`);
              for (const b of falseUnevaluableClaims(e.label)) failures.push(`${where}: ${b}`);
            }
          }
          for (const text of [t.claim, ...t.caveats]) for (const b of falseUnevaluableClaims(text)) failures.push(`${where}: ${b}`);
        }
      }
    }
    expect(failures.slice(0, 25), failures.slice(0, 25).join("\n")).toEqual([]);
    expect(aclHops, "the sweep reached ACL evidence").toBeGreaterThan(0);
  });
});

/* ── the refuter's own flows, on the real lists ──────────────────────────────────────────────────── */

describeGolden("B5 counterexamples on core1's real PROTECT_SERVERS and INET_RETURN", () => {
  const lists = own(fabric.acls, HOST) ?? {};
  const ps = own(lists, PS.name) ?? [];
  const ir = own(lists, IR.name) ?? [];
  const walk = (name: string, lines: AclLine[], f: Flow) => evaluateListsInOrder(HOST, f, ip(f.srcIp), ip(f.dstIp), { [name]: lines }, [name]);
  const rowOf = (ev: readonly HopEvidence[], cite: string): HopEvidence => {
    const r = ev.find((e) => e.cite === cite);
    expect(r, `${cite} is named`).toBeDefined();
    return r!;
  };

  it("ip 10.0.10.50 -> 10.0.30.20: names the echo-reply line as unevaluable and lines 1-2 as left open by the flow", () => {
    const f = BF.ipFromVlan10;
    const acl = evaluateAcls(HOST, f, ip(f.srcIp), ip(f.dstIp), { [PS.name]: ps });
    expect(acl.verdict).toBe("indeterminate");
    // The blocker the model cannot read is what the verdict is decided by.
    expect(acl.decidedBy?.cite).toBe(PS.echoReplyCite);
    expect(acl.decidedBy?.label).toMatch(/line 3 of 4 cannot be evaluated/);
    for (const cite of [PS.permit443Cite, PS.permit22Cite]) {
      const row = rowOf(acl.evidence, cite);
      expect(row.label).not.toContain("cannot be evaluated");
      expect(row.label).toContain("protocol");
      expect(row.label).toContain("destination port");
    }
    expect(rowOf(acl.evidence, PS.echoReplyCite).label).toContain("cannot be evaluated");
    const deny = rowOf(acl.evidence, PS.denyAllCite).label;
    expect(deny).toContain("may fire first");
    for (const cite of [PS.permit443Cite, PS.permit22Cite, PS.echoReplyCite]) expect(deny).toContain(cite);
    expect(falseUnevaluableClaims(deny)).toEqual([]);
    expect(acl.caveats.join(" ")).toContain(PS.echoReplyCite);

    // End to end: the trace names the echo-reply line, and never calls line 1 unevaluable.
    const trace = traceFlow(f);
    expect(trace.outcome).toBe("indeterminate");
    expect(JSON.stringify(trace)).toContain(PS.echoReplyCite);
    expect(JSON.stringify(trace)).not.toContain(`${PS.name} line 1 of 4 cannot be evaluated`);
  });

  it("ip 10.0.40.5 -> 10.0.30.20: only the echo-reply line can fire first, and the deny names it", () => {
    const f = BF.ipFromOutside;
    const run = walk(PS.name, ps, f);
    expect(run.indeterminate?.cite).toBe(PS.echoReplyCite);
    expect(rowOf(run.evidence, PS.denyAllCite).label).toBe(
      `${HOST} ACL ${PS.name} line 4 of 4 would match, but an earlier unevaluable line may fire first: line 3 of 4 (${PS.echoReplyCite}) cannot be evaluated`,
    );
    expect(run.evidence.some((e) => e.cite === PS.permit443Cite)).toBe(false);
  });

  it("portless tcp 10.0.10.50 -> 10.0.30.20: the echo-reply line is excluded, so no unevaluable line is claimed", () => {
    const f = BF.portlessTcp;
    expect(matchTri(ps.find((l) => l.cite === PS.echoReplyCite)!, f, ip(f.srcIp), ip(f.dstIp))).toBe("no");
    const run = walk(PS.name, ps, f);
    expect(run.indeterminate?.cite).toBe(PS.permit443Cite);
    expect(run.indeterminate?.label).not.toContain("cannot be evaluated");
    const deny = rowOf(run.evidence, PS.denyAllCite).label;
    expect(deny).toContain("may fire first");
    expect(deny).not.toMatch(/unevaluable|cannot be evaluated/);
    expect(deny).toContain(PS.permit443Cite);
    expect(deny).toContain(PS.permit22Cite);
    expect(deny).toContain("destination port");
    expect(deny).not.toContain(PS.echoReplyCite);
    expect(run.caveats.join(" ")).not.toContain("cannot be evaluated");

    const trace = traceFlow(f);
    expect(trace.outcome).toBe("indeterminate");
    expect(JSON.stringify(trace)).not.toMatch(/PROTECT_SERVERS line [12] of 4 cannot be evaluated/);
  });

  it("INET_RETURN: both unevaluable lines are named above the deny for an ip flow, only the reachable one from 10.0.40.5", () => {
    const deny = (f: Flow): string => {
      const run = walk(IR.name, ir, f);
      const last = ir[ir.length - 1]!;
      return rowOf(run.evidence, last.cite).label;
    };
    const fromVlan10 = deny(BF.ipFromVlan10);
    expect(fromVlan10).toContain("earlier unevaluable lines may fire first");
    expect(fromVlan10).toContain(IR.establishedCite);
    expect(fromVlan10).toContain(IR.timeRangedCite);
    const fromOutside = deny(BF.ipFromOutside);
    expect(fromOutside).toContain("an earlier unevaluable line may fire first");
    expect(fromOutside).toContain(IR.establishedCite);
    expect(fromOutside).not.toContain(IR.timeRangedCite);
    const portless = deny(BF.portlessTcp);
    expect(portless).toContain(IR.establishedCite);
    expect(portless).toContain(IR.timeRangedCite);
  });
});
