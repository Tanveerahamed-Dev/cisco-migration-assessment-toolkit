/**
 * engine.no-counterexample.counterfactual.test.ts — the multi-hop-denial preset's B8 clause, EXECUTED on
 * its rejecting side: a decided multi-hop denial for which the counterexample search finds nothing is NOT
 * offered.
 *
 * Why a counterfactual (2026-09-28 verifier, D4). On the reference sample the first decided multi-hop
 * denial the preset search meets happens to have a counterexample, so replacing the clause
 * `counterexample(t.flow, t).found` with `true` left every suggestion test green: a guard tested only where
 * it is inert. Here the search is starved of candidates AT THE BLOCKING HOST, which is exactly what the
 * clause reads, and nothing else:
 *
 *   The counterexample search varies a refusal two ways, both read from the blocking host H (engine.ts
 *   `counterexample`): (a) the protocol/port of every evaluable PERMIT line of H's ACLs, and (b) the
 *   destination to a host inside every CONNECTED prefix of H's table. The fixture removes exactly those
 *   inputs — every permit line of H's ACLs, and every connected route of H except the one holding the
 *   denied destination (whose variation is the refused flow itself) — so no candidate is left to find.
 *
 * H and the denied flow are resolved by PROPERTY in a first pass over the real compiled document (the
 * blocking host of the multi-hop-denial preset the engine offers there); the engine is then re-imported
 * against the counterfactual document (vi.doMock + vi.resetModules). Removing connected routes can change
 * what H's routing-completeness receipt says about its sessions, so in BOTH passes the completeness producer
 * is answered "complete" (the same counterfactual engine.counterfactual.test.ts uses): the question here is
 * the preset's acceptance rule, not H's table. Vitest isolates modules per file.
 *
 * Mutation-checked 2026-09-28: with the clause replaced by `return true` this file fails ("… expected false
 * to be true" — an offered multi-hop denial with no counterexample); engine.suggestions.test.ts stays green.
 */
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { Flow } from "../core/types";
import { need } from "./test-subjects";

interface AclLineShape {
  action: string | null;
  cite: string;
}
interface RouteRow {
  prefix: string;
  source: string | null;
  cite: string;
}
interface FabricShape {
  routes: Record<string, RouteRow[]>;
  acls: Record<string, Record<string, AclLineShape[]>>;
}

const cf = vi.hoisted(() => ({
  plan: null as { host: string; dstIp: string } | null,
  removed: [] as string[],
}));

vi.mock("./rib-completeness", async (orig) => {
  const actual = await orig<typeof import("./rib-completeness")>();
  return { ...actual, ribIncompleteness: () => [], ribIncompletenessSentence: () => null };
});

/** The counterfactual document: the real one with the plan's inputs removed (installed with vi.doMock in pass 2). */
async function counterfactualDocument(): Promise<{ default: FabricShape }> {
  const real = ((await vi.importActual("../data/fabric.json")) as { default: FabricShape }).default;
  const c = structuredClone(real);
  const plan = cf.plan!;
  const toInt = (ip: string): number => ip.split(".").reduce((n, o) => ((n << 8) | Number(o)) >>> 0, 0);
  const contains = (prefix: string, ip: string): boolean => {
    const [net, len] = prefix.split("/");
    const bits = Number(len);
    return bits === 0 || toInt(ip) >>> (32 - bits) === toInt(net!) >>> (32 - bits);
  };
  cf.removed = [];
  for (const [name, lines] of Object.entries(c.acls[plan.host] ?? {})) {
    cf.removed.push(...lines.filter((l) => (l.action ?? "").toLowerCase() === "permit").map((l) => l.cite));
    c.acls[plan.host]![name] = lines.filter((l) => (l.action ?? "").toLowerCase() !== "permit");
  }
  const rs = c.routes[plan.host] ?? [];
  cf.removed.push(...rs.filter((r) => r.source === "connected" && !contains(r.prefix, plan.dstIp)).map((r) => r.cite));
  c.routes[plan.host] = rs.filter((r) => r.source !== "connected" || contains(r.prefix, plan.dstIp));
  return { default: c };
}

type Engine = typeof import("./engine");
let real: { flow: Flow; host: string } | undefined;
let cfEngine: Engine | undefined;
let realFabric: FabricShape;
let cfFabric: FabricShape;

beforeAll(async () => {
  /* Pass 1: the real data (no plan). The real engine's own preset names the flow and its blocking host. */
  const e1: Engine = await import("./engine");
  realFabric = ((await import("../data/fabric.json")) as unknown as { default: FabricShape }).default;
  const s = e1.suggestedFlows().find((f) => f.id === "multi-hop-denial");
  if (s !== undefined) {
    const b = e1.blockingHop(e1.traceFlow(s.flow));
    if (b !== null) real = { flow: s.flow, host: b.hop.host };
  }
  if (real === undefined) return;
  /* Pass 2: the same modules, re-imported against the counterfactual document. */
  cf.plan = { host: real.host, dstIp: real.flow.dstIp };
  vi.doMock("../data/fabric.json", counterfactualDocument);
  vi.resetModules();
  cfEngine = await import("./engine");
  cfFabric = ((await import("../data/fabric.json")) as unknown as { default: FabricShape }).default;
}, 120_000);

const SUBJECT = "decided multi-hop denial preset on the real data";

describe("the fixture changes only the counterexample search's inputs at the blocking host", () => {
  it("removes H's permit lines and H's connected routes that do not hold the denied destination, and nothing else", (ctx) => {
    const r = need(ctx, real, SUBJECT);
    expect(cf.removed.length, "the fixture removed something").toBeGreaterThan(0);
    const restored = structuredClone(cfFabric);
    const removed = new Set(cf.removed);
    // Put back exactly the removed records, in their real positions, and the documents are identical.
    for (const [name, lines] of Object.entries(realFabric.acls[r.host] ?? {})) {
      for (const l of lines) if (!removed.has(l.cite)) expect(restored.acls[r.host]![name]!.some((x) => x.cite === l.cite)).toBe(true);
      restored.acls[r.host]![name] = lines;
    }
    restored.routes[r.host] = realFabric.routes[r.host]!;
    expect(JSON.stringify(restored)).toBe(JSON.stringify(realFabric));
    for (const c of cf.removed) expect(/^(acls|routes)\./.test(c) && c.includes(`.${r.host}`), c).toBe(true);
  });
});

describe("a decided multi-hop denial with no counterexample is not offered (B8)", () => {
  it("precondition: in the counterfactual the same flow is still a decided multi-hop ACL denial at H, and the search finds nothing", (ctx) => {
    const r = need(ctx, real, SUBJECT);
    const e = cfEngine!;
    const t = e.traceFlow(r.flow);
    expect(t.outcome).toBe("denied");
    expect(t.hops.length).toBeGreaterThanOrEqual(2);
    expect(e.isDecidedRefusal(t)).toBe(true);
    const b = e.blockingHop(t);
    expect(b?.hop.host).toBe(r.host);
    expect(b?.evidence.kind).toBe("acl");
    expect(b?.evidence.raw ?? null).not.toBeNull();
    const cx = e.counterexample(t.flow, t);
    expect(cx.found).toBe(false);
  });

  it("the preset search rejects it: no offered multi-hop denial lacks a counterexample, and that flow is not offered", (ctx) => {
    const r = need(ctx, real, SUBJECT);
    const e = cfEngine!;
    const offered = e.suggestedFlows().filter((f) => f.id === "multi-hop-denial");
    for (const p of offered) {
      const t = e.traceFlow(p.flow);
      expect(e.counterexample(t.flow, t).found, JSON.stringify(p.flow)).toBe(true);
    }
    expect(offered.map((p) => JSON.stringify(p.flow))).not.toContain(JSON.stringify(r.flow));
  });
});
