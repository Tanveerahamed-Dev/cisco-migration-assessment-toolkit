/**
 * claims.no-rib.counterfactual.test.ts — the badge invariant over REAL engine traces that touch a host with no RIB.
 *
 * WHY A COUNTERFACTUAL (QC-R1-3, verifier of phase 3.5). claims.test.ts swept the engine's traces for one that touched
 * a host without a collected routing table and required each to be badged INDETERMINATE. On the reference sample no
 * trace reaches such a host (every SVI gateway holds a RIB — pinned in claims.test.ts's golden block), and the rename
 * and engine-golden legs are the same in that respect, so the sweep was a named skip on every leg the program runs:
 * a gate whose success path never executed. The rule itself is pinned there on a hand-built trace; THIS file makes
 * the engine-level invariant execute.
 *
 * The one counterfactual: the collected RIB (and ACLs) of ONE host, chosen by PROPERTY — the observed-Active SVI
 * gateway holding a collected RIB with the fewest collected ACL lines, ties by name (the rule
 * src/forwarding/engine.no-rib.counterfactual.test.ts uses) — withdrawn, with the coverage lists kept consistent.
 * Every other record is the real compiled evidence, and the traces come from the real engine. A dataset with no such
 * gateway skips BY NAME; the golden tier states the sample has one. Vitest isolates modules per file.
 */
import { describe, expect, it, vi } from "vitest";

interface FabricShape {
  routes: Record<string, unknown[]>;
  acls: Record<string, Record<string, unknown[]>>;
  l3: { host: string | null; sviIp: string | null; fhrpRole: string | null }[];
  coverage: { routableHosts: string[]; aclHosts: string[]; hostsWithRoutes: number; hostsWithAcls: number };
}

const cf = vi.hoisted(() => ({ host: null as string | null }));

vi.mock("../data/fabric.json", async () => {
  const real = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  const c = structuredClone(real);
  const lines = (h: string): number => Object.values(c.acls[h] ?? {}).reduce((n, ls) => n + ls.length, 0);
  const hosts = [
    ...new Set(
      c.l3.filter((r) => r.host !== null && (r.fhrpRole ?? "").toLowerCase() === "active" && c.routes[r.host] !== undefined).map((r) => r.host!),
    ),
  ];
  hosts.sort((a, b) => lines(a) - lines(b) || (a < b ? -1 : a > b ? 1 : 0));
  const x = hosts[0];
  if (x === undefined) return { default: c };
  cf.host = x;
  delete c.routes[x];
  delete c.acls[x];
  c.coverage.routableHosts = c.coverage.routableHosts.filter((h) => h !== x);
  c.coverage.aclHosts = c.coverage.aclHosts.filter((h) => h !== x);
  c.coverage.hostsWithRoutes = c.coverage.routableHosts.length;
  c.coverage.hostsWithAcls = c.coverage.aclHosts.length;
  return { default: c };
});

import { bandOfTrace, claimBadge } from "./claims";
import { fabric, hasRib } from "./data";
import type { Flow } from "./types";
import { describeGolden } from "../test-support/golden-sample";
import { formatIpv4, hostAddressIn, parseInterfaceAddress } from "../forwarding/ip";
import { suggestedFlows, traceFlow } from "../forwarding/engine";

const HAS_SUBJECT = cf.host !== null;

/** Every suggested flow, plus one from each of the withdrawn host's Active SVI subnets toward every other SVI subnet. */
function sweep(x: string): Flow[] {
  const flows: Flow[] = suggestedFlows().map((s) => s.flow);
  const prefixes = fabric.l3
    .map((r) => ({ host: r.host, active: (r.fhrpRole ?? "").toLowerCase() === "active", a: r.sviIp === null ? null : parseInterfaceAddress(r.sviIp) }))
    .filter((r) => r.a !== null);
  for (const own of prefixes.filter((r) => r.host === x && r.active)) {
    const src = hostAddressIn(own.a!.prefix, 50);
    if (src === null) continue;
    for (const other of prefixes) {
      if (formatIpv4(other.a!.prefix.base) === formatIpv4(own.a!.prefix.base)) continue;
      const dst = hostAddressIn(other.a!.prefix, 10);
      if (dst !== null) flows.push({ srcIp: formatIpv4(src), dstIp: formatIpv4(dst), protocol: "tcp", dstPort: 443, srcPort: null });
    }
  }
  return flows;
}

describe("real engine traces over a fleet where one gateway's RIB was not collected", () => {
  it.runIf(HAS_SUBJECT)(
    HAS_SUBJECT
      ? "the fixture withdrew exactly that host's RIB and ACLs, and the coverage says so"
      : "the fixture withdrew exactly that host's RIB and ACLs [skipped: no observed-Active SVI gateway holds a collected RIB here]",
    () => {
      expect(hasRib(cf.host!)).toBe(false);
      expect(fabric.coverage.routableHosts).not.toContain(cf.host);
      expect(fabric.coverage.aclHosts).not.toContain(cf.host);
    },
  );

  it.runIf(HAS_SUBJECT)(
    HAS_SUBJECT
      ? "every real trace that touched a host with no RIB is badged INDETERMINATE and banded UNDETERMINED (moved from claims.test.ts)"
      : "every real trace that touched a host with no RIB is badged INDETERMINATE [skipped: no observed-Active SVI gateway holds a collected RIB here]",
    () => {
      const traces = sweep(cf.host!).map((f) => traceFlow(f));
      const touched = traces.filter((t) => t.unmodelledHosts.length > 0);
      // Non-vacuity: the counterfactual exists so that this list is not empty.
      expect(touched.length, "traces whose path crosses the withdrawn host").toBeGreaterThan(0);
      expect(touched.some((t) => t.unmodelledHosts.includes(cf.host!))).toBe(true);
      expect(touched.filter((t) => claimBadge(t) !== "INDETERMINATE").map((t) => `${t.flow.srcIp}->${t.flow.dstIp} ${claimBadge(t)}`)).toEqual([]);
      expect(touched.filter((t) => bandOfTrace(t) !== "UNDETERMINED").map((t) => `${t.flow.srcIp}->${t.flow.dstIp}`)).toEqual([]);
      // Control: the same sweep also holds traces that touched no such host, and the rule did not flatten them all.
      expect(traces.some((t) => t.unmodelledHosts.length === 0 && claimBadge(t) !== "INDETERMINATE")).toBe(true);
    },
  );
});

describeGolden("the no-RIB counterfactual on the reference sample", () => {
  it("has a subject, so neither test above is skipped here", () => {
    expect(HAS_SUBJECT).toBe(true);
    expect(cf.host).not.toBeNull();
  });
});
