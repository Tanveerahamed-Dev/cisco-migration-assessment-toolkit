/**
 * blast.test.ts — the topology engine tested against the REAL compiled snapshot.
 *
 * Every expectation below was derived by reading `src/data/fabric.json` directly (cable_map.cables,
 * link_centrality, failure_impact, endpoint_identity), NOT by running the implementation and
 * writing down what it said. Each block states the derivation, because a test whose expected value
 * came out of the code under test proves only that the code is self-consistent.
 */
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { describeGolden } from "../test-support/golden-sample";
import type { Link } from "../core/types";
import { findPortDisputes } from "./port-claims";
import {
  articulationPoints,
  bridges,
  buildAdjacency,
  buildAdjacencyFrom,
  failureImpact,
  kCore,
  linkBetweenness,
  linkFailureImpact,
  pathsBetween,
  reachableSet,
  resolvePathLimit,
} from "./blast";

const ALL_NODES = () => buildAdjacency({ transit: "all-nodes" });

/* ── TWO TIERS (src/test-support/golden-sample.ts; phase 3) ──
 * The blocks marked `describeGolden` pin answers derived by hand from the tracked reference sample (host and
 * cable names, counts, derivations in their comments): they run only on that sample and are skipped BY NAME on
 * any other dataset (the rename and golden-snapshot legs). Everything else here is an invariant over whatever
 * fabric is loaded, its subjects resolved by PROPERTY below, never by name. */
const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
const G0 = buildAdjacency();
/** The articulation point whose loss strands the most hosts (on the sample: core1); a transit node if none. */
const CUT: string =
  [...articulationPoints().points.map((p) => p.host)].sort(
    (a, b) => failureImpact(b).newlyStranded.length - failureImpact(a).newlyStranded.length || cmpStr(a, b),
  )[0] ?? G0.nodes[0]!;
/** A transit node that is not a cut vertex (on the sample: an access leaf). */
const LEAF: string = G0.nodes.find((n) => !articulationPoints().points.some((p) => p.host === n)) ?? G0.nodes[0]!;
/** A device the collector never reached, or a name the fabric does not hold. */
const UNCOLLECTED: string = fabric.devices.find((d) => !d.collected)?.host ?? "no-uncollected-device";
/** A cable the projection calls a bridge, and one outside the default projection (unknown status), if any. */
const BRIDGE: string = bridges().bridges[0]?.linkId ?? fabric.links[0]!.id;
const UNCERTAIN: string = G0.uncertainLinkIds[0] ?? fabric.links[fabric.links.length - 1]!.id;
/** Two hosts joined by a carrying cable, so a path between them exists on any fabric that has one. */
const PAIR: readonly [string, string] = [G0.edges[0]!.a, G0.edges[0]!.b];

/** The 17 links `link_centrality` marks is_bridge:true, read straight out of the snapshot. */
const ENGINE_BRIDGES = fabric.links.filter((l) => l.isBridge === true).map((l) => l.id).sort();

describeGolden("link status classes in the real snapshot", () => {
  /* Derivation: histogram of cable_map.cables[].op_status — 42 "up", 2 "unknown" (L34 core2↔
     AP-floor3-01, L35 core2↔wan-edge-rtr1.lab), 0 "down". The observed-down path therefore cannot
     be exercised by the snapshot as collected; it is exercised below on a graph built from the REAL
     link records with one status field changed, which is stated there. */
  it("separates carrying, observed-down and unknown-status links", () => {
    const g = buildAdjacency();
    expect(g.downLinkIds).toEqual([]);
    expect(g.uncertainLinkIds).toEqual(["L34", "L35"]);
    expect(fabric.links.filter((l) => l.opStatus === "up")).toHaveLength(42);
    expect(fabric.links.filter((l) => l.opStatus === "down")).toHaveLength(0);
  });

  it("never treats an unknown status as up in the default projection", () => {
    const g = buildAdjacency();
    expect(g.edges.map((e) => e.linkId)).not.toContain("L34");
    expect(g.excluded.find((x) => x.linkId === "L34")?.reason).toBe("unknown-status");
  });
});

describeGolden("articulationPoints", () => {
  /* Derivation (default = collected-only projection, unknown links excluded):
     every accessN is single-homed to exactly one core — access1/2/4/6/8/10/12/14/16 to core1
     (cables L18–L25 + L7), access3/5/7/9/11/13/15/17 to core2 (L28–L31, L33, L36–L38) — so each
     core is a cut vertex for its own nine/eight leaves. dist1, dist2, podacc1, podacc2 sit in the
     4-cycle L39/L40/L41/L42/L43, so removing any one of them leaves the rest joined; core1↔core2
     (L27) plus core1↔dist1 (L26) and core2↔dist2 (L32) close the spine loop. Expected: exactly
     core1 and core2. */
  it("finds exactly the two cores on the collected-only graph", () => {
    expect(articulationPoints().points.map((p) => p.host)).toEqual(["core1", "core2"]);
  });

  /* Derivation: the snapshot also carries AP-floor1, a device with collected:false that appears as
     the far end of 17 one-end-confirmed cables (L0–L6, L8–L17), one from every access switch. If
     that node is allowed to forward, every access switch has a second path and the graph becomes
     2-connected: no cut vertices at all. That inversion is the point of the two projections. */
  it("finds none once the uncollected AP pseudo-hub is allowed to forward", () => {
    expect(articulationPoints(ALL_NODES()).points).toEqual([]);
  });

  it("reports the removal consequence for each point it names", () => {
    const core1 = articulationPoints().points.find((p) => p.host === "core1");
    expect(core1?.componentsAfterRemoval).toBe(10);
    expect(core1?.separatedHosts).toEqual([
      "access1", "access10", "access12", "access14", "access16",
      "access2", "access4", "access6", "access8",
    ]);
  });
});

describeGolden("bridges and the cross-check against link_centrality", () => {
  it("agrees with every engine is_bridge verdict on the collected-only graph", () => {
    const r = bridges();
    expect(r.bridges.map((b) => b.linkId).sort()).toEqual(ENGINE_BRIDGES);
    expect(ENGINE_BRIDGES).toHaveLength(17);
    expect(r.engineComparison.disagreed).toEqual([]);
    expect(r.engineComparison.agreed).toHaveLength(25);
  });

  /* A single named bridge from the snapshot: L18 is core1(Gi1/0/24)↔access1(Gi0/1), is_bridge:true,
     pairs_cut 22, rank 5. */
  it("agrees on the named bridge L18", () => {
    const row = bridges().engineComparison.rows.find((r) => r.linkId === "L18");
    expect(row).toMatchObject({ ours: true, engine: true, agreement: "agree", cite: "cable_map.cables[18]" });
  });

  it("treats a missing centrality record as silence, not as non-bridgehood", () => {
    const r = bridges();
    // 44 cables, 25 carry a link_centrality row (coverage.linksWithCentrality) → 19 are silent.
    expect(r.engineComparison.linksWithoutEngineRecord).toHaveLength(19);
    expect(r.engineComparison.linksWithoutEngineRecord).toContain("L0");
    expect(r.engineComparison.rows.every((row) => row.engine !== false || row.agreement !== "engine-silent")).toBe(true);
  });

  it("surfaces the projection disagreement instead of papering over it", () => {
    const r = bridges(ALL_NODES());
    expect(r.bridges).toEqual([]);
    expect(r.engineComparison.disagreed).toHaveLength(17);
    for (const row of r.engineComparison.disagreed) {
      expect(row.engine).toBe(true);
      expect(row.ours).toBe(false);
    }
    expect(r.engineComparison.note.length).toBeGreaterThan(0);
  });
});

describeGolden("failureImpact", () => {
  /* Derivation from endpoint_identity counts per host: access1,2,3,4,5,6,13,14,15,16,17 have 3
     endpoints each; access7,8,9,10,11,12 have 2; core1 has 1; podacc1/podacc2 have 2 each.
     Removing core1 on the collected-only graph separates its nine leaves
     (3+3+3+3+2+2+2+3+3 = 24 endpoints) and takes core1's own 1 with it → 25.
     Removing the leaf access1 separates nobody → only its own 3. */
  it("strands far more endpoints on a core than on a leaf", () => {
    const core = failureImpact("core1");
    const leaf = failureImpact("access1");
    expect(core.strandedEndpoints.total).toBe(25);
    expect(leaf.strandedEndpoints.total).toBe(3);
    expect(core.strandedEndpoints.total!).toBeGreaterThan(leaf.strandedEndpoints.total!);
    expect(core.newlyStranded).toHaveLength(9);
    expect(leaf.newlyStranded).toEqual([]);
    expect(core.isArticulationPoint).toBe(true);
    expect(core.severedLinks.map((l) => l.linkId)).toContain("L18");
    expect(core.severedLinks.every((l) => l.cite.startsWith("cable_map.cables["))).toBe(true);
  });

  it("reports the counter-projection where the answer inverts", () => {
    const core = failureImpact("core1");
    const alt = core.alternateProjections.find((a) => a.options.transit === "all-nodes");
    expect(alt?.differs).toBe(true);
    expect(alt?.strandedEndpointTotal).toBe(1);
    // and the inverted measurement is really what the other projection yields
    expect(failureImpact("core1", ALL_NODES()).strandedEndpoints.total).toBe(1);
    expect(failureImpact("access1", ALL_NODES()).strandedEndpoints.total).toBe(3);
  });

  it("does not blame a pre-existing partition on the failure under test", () => {
    const r = failureImpact("access1", ALL_NODES());
    // AP-floor3-01 and wan-edge-rtr1.lab hang off unknown-status cables only: they are already
    // outside the connected fabric before anything fails.
    expect(r.alreadyDisconnected).toEqual(["AP-floor3-01", "wan-edge-rtr1.lab"]);
    expect(r.newlyStranded).toEqual([]);
  });

  it("refuses to reason about the internals of a host that was never collected", () => {
    const r = failureImpact("AP-floor1");
    expect(r.presence).toBe("attached-non-transit");
    expect(r.collected).toBe(false);
    expect(r.certainty).toBe("not-determinable");
    expect(r.reasoningLimit).not.toBeNull();
    expect(r.strandedEndpoints.determinable).toBe(false);
    expect(r.strandedEndpoints.total).toBeNull();
  });

  it("says a host is absent rather than unaffected", () => {
    const r = failureImpact("no-such-switch");
    expect(r.presence).toBe("absent-from-topology");
    expect(r.certainty).toBe("not-determinable");
    expect(r.strandedEndpoints.total).toBeNull();
    expect(r.caveats.join(" ")).toMatch(/not present/i);
  });

  it("carries the engine's own failure_impact record alongside ours", () => {
    const r = failureImpact("core1");
    expect(r.engine.record?.cite).toBe("failure_impact[host=core1]");
    expect(r.engine.basis).toBe("different-measure");
    const leaf = failureImpact("access1");
    // The engine calls a leaf switch a 3-VLAN hard partition (42 endpoints); topology says its
    // removal separates nobody. Qualitative disagreement, surfaced not smoothed.
    expect(leaf.engine.qualitative).toBe("engine-impact-only");
  });
});

describeGolden("linkFailureImpact", () => {
  it("strands the leaf behind a bridge link", () => {
    const r = linkFailureImpact("L18");
    expect(r.presence).toBe("carrying");
    expect(r.newlyStranded).toEqual(["access1"]);
    expect(r.strandedEndpoints.total).toBe(3);
    expect(r.isBridge).toBe(true);
    expect(r.engine.agreement).toBe("agree");
  });

  it("finds no partition behind the core port-channel and says so with its granularity caveat", () => {
    const r = linkFailureImpact("L27");
    expect(r.newlyStranded).toEqual([]);
    expect(r.isBridge).toBe(false);
    expect(r.assumptions.some((a) => a.id === "port-channel-granularity")).toBe(true);
  });

  it("does not report an unknown-status link as harmless", () => {
    const r = linkFailureImpact("L34");
    expect(r.presence).toBe("not-carrying-unknown-status");
    expect(r.certainty).not.toBe("observed");
    expect(r.strandedEndpoints.determinable).toBe(false);
    expect(r.caveats.join(" ")).toMatch(/unknown/i);
  });
});

describeGolden("observed-down links", () => {
  /* No cable in this snapshot is observed down, so this exercises the exclusion on a graph built
     from the REAL link records with exactly one field changed: L18 (core1↔access1) flipped to
     "down". Everything else — ports, confirmation, centrality — is the real record. */
  const downed: Link[] = fabric.links.map((l) => (l.id === "L18" ? { ...l, opStatus: "down" } : l));

  it("drops a down link from connectivity and names the reason", () => {
    const g = buildAdjacencyFrom(downed, fabric.devices);
    expect(g.downLinkIds).toEqual(["L18"]);
    expect(g.edges.map((e) => e.linkId)).not.toContain("L18");
    expect(g.excluded.find((x) => x.linkId === "L18")?.reason).toBe("observed-down");
    expect(reachableSet("access1", g).hosts).toEqual(["access1"]);
    expect(reachableSet("core1", g).hosts).not.toContain("access1");
  });

  it("leaves the rest of the fabric exactly as it was", () => {
    const g = buildAdjacencyFrom(downed, fabric.devices);
    // access1 is already isolated, so core1's removal separates one fewer host than before.
    expect(failureImpact("core1", g).newlyStranded).toHaveLength(8);
    expect(failureImpact("core1", g).alreadyDisconnected).toEqual(["access1"]);
    expect(bridges(g).bridges.map((b) => b.linkId)).not.toContain("L18");
  });
});

describeGolden("reachableSet", () => {
  it("returns the whole collected fabric from any of its members", () => {
    const r = reachableSet("core1");
    expect(r.hosts).toHaveLength(23);
    expect(r.hosts).toContain("podacc2");
    expect(r.present).toBe(true);
  });

  it("names what is reachable only if the unknown-status cables carry", () => {
    const r = reachableSet("core2");
    expect(r.attachedOnlyViaUncertainLinks).toEqual(["AP-floor3-01", "wan-edge-rtr1.lab"]);
    expect(r.certainty).toBe("uncertain");
  });
});

describeGolden("pathsBetween (topology adjacency, not forwarding)", () => {
  it("finds the spine path between two access switches on different cores", () => {
    const r = pathsBetween("access1", "access3", 5);
    expect(r.paths).toHaveLength(1);
    expect(r.paths[0]?.hosts).toEqual(["access1", "core1", "core2", "access3"]);
    expect(r.paths[0]?.linkIds).toEqual(["L18", "L27", "L33"]);
    expect(r.totalShortestPaths).toBe(1);
    expect(r.claim).toMatch(/adjacency/i);
    expect(r.claim).toMatch(/not.*forwarding/i);
  });

  it("enumerates both equal-cost pod paths in a deterministic order", () => {
    const r = pathsBetween("podacc1", "podacc2", 5);
    expect(r.paths.map((p) => p.hosts)).toEqual([
      ["podacc1", "dist1", "podacc2"],
      ["podacc1", "dist2", "podacc2"],
    ]);
  });

  it("truncates honestly rather than implying it showed everything", () => {
    const r = pathsBetween("core1", "AP-floor1", 3, ALL_NODES());
    expect(r.paths).toHaveLength(3);
    expect(r.totalShortestPaths).toBe(9);
    expect(r.truncated).toBe(true);
  });

  it("does not present an unreachable pair as a settled answer when an unknown link is in play", () => {
    const r = pathsBetween("access1", "wan-edge-rtr1.lab", 5, ALL_NODES());
    expect(r.paths).toEqual([]);
    expect(r.certainty).not.toBe("observed");
    expect(r.caveats.join(" ")).toMatch(/unknown/i);
  });
});

describeGolden("load-bearing measures", () => {
  /* Derivation: peel degree-1 first — all 17 access switches are leaves on the collected-only
     graph, so coreness 1. What is left (core1, core2, dist1, dist2, podacc1, podacc2) has minimum
     degree 2 and survives as the 2-core; nothing has three independent neighbours inside it, so
     the max core is 2. */
  it("puts the spine in the 2-core and every access leaf in the 1-core", () => {
    const r = kCore();
    expect(r.maxCore).toBe(2);
    expect(r.shells.find((s) => s.k === 2)?.hosts).toEqual([
      "core1", "core2", "dist1", "dist2", "podacc1", "podacc2",
    ]);
    expect(r.coreness.filter((c) => c.k === 1)).toHaveLength(17);
    expect(r.notScored.map((n) => n.host)).toEqual(["AP-floor1", "AP-floor3-01", "wan-edge-rtr1.lab"]);
  });

  it("reports engine betweenness only where the engine supplied it", () => {
    const r = linkBetweenness();
    expect(r.supplied).toHaveLength(25);
    expect(r.missing).toHaveLength(19);
    expect(r.supplied.find((s) => s.linkId === "L27")?.betweenness).toBe(99.5);
    expect(r.note).toMatch(/not.*zero|absence/i);
  });
});

describe("honesty invariants", () => {
  const results = [
    buildAdjacency(),
    articulationPoints(),
    bridges(),
    failureImpact(CUT),
    failureImpact(UNCOLLECTED),
    failureImpact("no-such-switch"),
    linkFailureImpact(BRIDGE),
    linkFailureImpact(UNCERTAIN),
    kCore(),
    linkBetweenness(),
    reachableSet(CUT),
    pathsBetween(PAIR[0], PAIR[1], 5),
  ];

  it("gives every result a non-empty assumption list", () => {
    for (const r of results) {
      expect(r.assumptions.length).toBeGreaterThan(0);
      for (const a of r.assumptions) expect(a.statement.length).toBeGreaterThan(0);
    }
  });

  it("states the collection limit and the status policy in every assumption list", () => {
    for (const r of results) {
      const ids = r.assumptions.map((a) => a.id);
      expect(ids).toContain("link-status-policy");
      expect(ids).toContain("topology-not-forwarding");
    }
  });

  it("backs each assumption with at least one citation into the snapshot", () => {
    for (const a of buildAdjacency().assumptions) expect(a.cites.length).toBeGreaterThan(0);
  });
});

describe("Hopcroft–Tarjan against brute force", () => {
  /* The expectations above pin the answer on this snapshot; this pins the ALGORITHM. Brute force —
     delete a node (or an edge) and recount components — is obviously correct and obviously too slow
     to ship, so it is the right oracle. Run over both projections and over 44 perturbed graphs (each
     real cable downed in turn), which reaches structures the snapshot itself does not contain. */
  const bruteComponents = (g: ReturnType<typeof buildAdjacency>, skipNode?: string, skipLink?: string): number => {
    const seen = new Set<string>();
    let n = 0;
    for (const start of g.nodes) {
      if (start === skipNode || seen.has(start)) continue;
      n += 1;
      const stack = [start];
      seen.add(start);
      while (stack.length > 0) {
        const cur = stack.pop() as string;
        for (const e of g.adjacency.get(cur) ?? []) {
          if (e.host === skipNode || e.linkId === skipLink || seen.has(e.host)) continue;
          seen.add(e.host);
          stack.push(e.host);
        }
      }
    }
    return n;
  };

  const check = (g: ReturnType<typeof buildAdjacency>, label: string): void => {
    const base = bruteComponents(g);
    const expectedAps = g.nodes
      .filter((n) => {
        const isolated = (g.adjacency.get(n) ?? []).length === 0;
        return bruteComponents(g, n) > (isolated ? base - 1 : base);
      })
      .sort();
    const expectedBridges = g.edges
      .filter((e) => bruteComponents(g, undefined, e.linkId) > base)
      .map((e) => e.linkId)
      .sort();
    expect(articulationPoints(g).points.map((p) => p.host), `articulation ${label}`).toEqual(expectedAps);
    expect(bridges(g).bridges.map((b) => b.linkId).sort(), `bridges ${label}`).toEqual(expectedBridges);
  };

  it("matches brute force on both projections of the real graph", () => {
    check(buildAdjacency(), "collected-only");
    check(ALL_NODES(), "all-nodes");
  });

  it("matches brute force on every single-cable-down perturbation of the real graph", () => {
    expect(fabric.links.length, "precondition: there are cables to perturb").toBeGreaterThan(0);
    for (const target of fabric.links) {
      const links: Link[] = fabric.links.map((l) => (l.id === target.id ? { ...l, opStatus: "down" } : l));
      check(buildAdjacencyFrom(links, fabric.devices), `collected-only minus ${target.id}`);
      check(buildAdjacencyFrom(links, fabric.devices, { transit: "all-nodes" }), `all-nodes minus ${target.id}`);
    }
  });
});

/** Every object reachable from the compiled snapshot — the engine's INPUT, owned by core/data.ts. */
function reachableObjects(root: unknown, out = new Set<unknown>()): Set<unknown> {
  if (root === null || typeof root !== "object" || out.has(root)) return out;
  out.add(root);
  for (const c of Array.isArray(root) ? root : Object.values(root)) reachableObjects(c, out);
  return out;
}

/**
 * Snapshot records a result carries BY REFERENCE are not poisoned. Measured 2026-09-22:
 * `failureImpact(h).engine.record` IS the compiled `failure_impact` record from `fabric`, not a copy,
 * and `fabric` is not frozen — so writing through a result mutates the snapshot for every later
 * caller in the process (reported for the owner of blast.ts / core/data.ts; not fixed here). Poisoning
 * it would also corrupt the shared snapshot for the rest of this file. This check is about what the
 * ANALYSIS computes and memoises; input records are out of its scope, and are named as such.
 */
const SNAPSHOT_OBJECTS = reachableObjects(fabric);

/**
 * Write a sentinel into every array, Set, Map and plain object reachable from `v`. A frozen
 * container refuses the write, which is itself the protection being tested, so a refusal is skipped.
 */
function deepPoison(v: unknown, seen = new Set<unknown>()): void {
  if (v === null || typeof v !== "object" || seen.has(v) || SNAPSHOT_OBJECTS.has(v)) return;
  seen.add(v);
  const children = v instanceof Map ? [...v.values()] : v instanceof Set ? [...v] : Array.isArray(v) ? [...v] : Object.values(v);
  for (const c of children) deepPoison(c, seen);
  try {
    if (Array.isArray(v)) v.push("__poison__");
    else if (v instanceof Set) v.add("__poison__");
    else if (v instanceof Map) v.set("__poison__", "__poison__");
    else (v as Record<string, unknown>)["__poison__"] = true;
  } catch {
    /* frozen: the result cannot be written through, which is what this check wants */
  }
}

/**
 * Run twice, with the FIRST result deliberately corrupted in between. The old form,
 * `expect(f()).toEqual(f())`, compared a pure function's output with itself and could not fail: two
 * calls sharing one memoised object are equal to each other however that object has been damaged.
 * The failure a repeated run can actually exhibit here is exactly that — `buildAdjacency` and the
 * alternate-graph projections are memoised and handed to every surface — so the second run is
 * compared against a CLONE taken before the corruption. Returns the clone for a non-empty check.
 */
function repeatable<T>(label: string, run: () => T): T {
  const first = run();
  const before = structuredClone(first);
  deepPoison(first);
  expect(run(), `${label}: the second run reflects damage done to the first run's result`).toEqual(before);
  return before;
}

describe("determinism", () => {
  it("returns deeply equal results on repeated runs", () => {
    /* Each result is also required to be non-empty — a determinism check over empty results passes
       for any implementation (acceptance report 2026-09-22, F2: this test compared outputs with
       themselves). */
    expect(repeatable("articulationPoints", () => articulationPoints()).points.length).toBeGreaterThan(0);
    expect(repeatable("bridges", () => bridges()).bridges.length).toBeGreaterThan(0);
    const fi = repeatable(`failureImpact(${CUT})`, () => failureImpact(CUT));
    expect(JSON.stringify(fi).length, "precondition: failureImpact(CUT) carries a result").toBeGreaterThan(50);
    const lfi = repeatable(`linkFailureImpact(${BRIDGE})`, () => linkFailureImpact(BRIDGE));
    expect(JSON.stringify(lfi).length, "precondition: linkFailureImpact(BRIDGE) carries a result").toBeGreaterThan(50);
    expect(repeatable("pathsBetween", () => pathsBetween(PAIR[0], PAIR[1], 5)).paths.length).toBeGreaterThan(0);
    const kc = repeatable("kCore", () => kCore());
    expect(JSON.stringify(kc).length, "precondition: kCore carries a result").toBeGreaterThan(50);
    const rs = repeatable(`reachableSet(${CUT})`, () => reachableSet(CUT));
    expect(JSON.stringify(rs).length, "precondition: reachableSet(CUT) carries a result").toBeGreaterThan(50);
  });

  it("the repeat check can fail: it catches a memo that hands every caller the same object", () => {
    /* Guard the guard. A deliberately aliasing memo — the defect class `repeatable` targets — must
       fail it, while the old self-comparison form passes the same function. */
    let memo: { items: string[] } | null = null;
    const aliasing = (): { items: string[] } => (memo ??= { items: ["a", "b"] });
    expect(aliasing()).toEqual(aliasing()); // the old form: cannot tell
    expect(() => repeatable("aliasing memo", aliasing)).toThrow(/reflects damage/);
  });

  it("is independent of the graph instance it was handed", () => {
    const a = failureImpact(CUT, buildAdjacency());
    const b = failureImpact(CUT, buildAdjacencyFrom(fabric.links, fabric.devices));
    expect(a).toEqual(b);
  });
});

/* ── regressions ─────────────────────────────────────────────────────────────
   Each block below pins a defect an adversarial review reproduced against the REAL records. The
   perturbations change nothing but `op_status` on cables that exist in the snapshot — the technique
   the observed-down block above already uses — because that is the only way to reach an
   already-partitioned brownfield shape from this fabric, and every defect here needed one. */

const withDown = (...ids: string[]): Link[] =>
  fabric.links.map((l) => (ids.includes(l.id) ? { ...l, opStatus: "down" } : l));

type Graph = ReturnType<typeof buildAdjacency>;

/** Reachability by explicit walk — the obviously-correct oracle, written without the module's helpers. */
const walk = (g: Graph, from: string, skipNode?: string, skipLink?: string): Set<string> => {
  const seen = new Set<string>([from]);
  const stack = [from];
  while (stack.length > 0) {
    const cur = stack.pop() as string;
    for (const e of g.adjacency.get(cur) ?? []) {
      if (e.host === skipNode || e.linkId === skipLink || seen.has(e.host)) continue;
      seen.add(e.host);
      stack.push(e.host);
    }
  }
  return seen;
};

/**
 * The contract, restated independently: the blast radius of removing an element is the members of
 * THAT ELEMENT'S OWN component which no longer reach the largest piece that component survives as.
 * Hosts that never shared a component with it lose nothing and are not in it.
 */
const oracle = (g: Graph, home: readonly string[], skipNode?: string, skipLink?: string): string[] => {
  const rest = home.filter((n) => n !== skipNode).sort();
  const pieces: string[][] = [];
  const done = new Set<string>();
  for (const n of rest) {
    if (done.has(n)) continue;
    const piece = [...walk(g, n, skipNode, skipLink)].sort();
    for (const m of piece) done.add(m);
    pieces.push(piece);
  }
  pieces.sort((x, y) => y.length - x.length || ((x[0] ?? "") < (y[0] ?? "") ? -1 : (x[0] ?? "") > (y[0] ?? "") ? 1 : 0));
  const largest = new Set(pieces[0] ?? []);
  return rest.filter((n) => !largest.has(n));
};

const oracleHost = (g: Graph, host: string): string[] => oracle(g, [...walk(g, host)], host, undefined);
const oracleLink = (g: Graph, linkId: string): string[] => {
  const e = g.edges.find((x) => x.linkId === linkId);
  return e === undefined ? [] : oracle(g, [...walk(g, e.a)], undefined, linkId);
};

describeGolden("regression: a blast radius is measured inside the failed element's own component", () => {
  /* L26 (core1↔dist1) and L27 (core1↔core2) are real cables. With both down the projection is in
     two pieces: core1 plus its nine single-homed leaves, and everything else — the larger one.
     access1 is single-homed to core1 by L18 alone, so its removal can strand nobody. Measured
     against the GLOBALLY largest surviving component instead of its own, every peer in core1's
     smaller piece read as newly cut off: a pre-existing partition billed to access1. */
  const partitioned = (): Graph => buildAdjacencyFrom(withDown("L26", "L27"), fabric.devices);

  it("does not bill a pre-existing partition to a single-homed leaf", () => {
    const r = failureImpact("access1", partitioned());
    expect(r.newlyStranded).toEqual([]);
    expect(r.isArticulationPoint).toBe(false);
    expect(r.strandedEndpoints.total).toBe(3); // access1's own three endpoint records, nothing else
    expect(r.claim).toContain("cuts 0 host(s)");
  });

  it("keeps failureImpact and articulationPoints telling one story about the same graph", () => {
    const g = partitioned();
    const aps = articulationPoints(g).points.map((p) => p.host);
    const disagreements = g.nodes.filter((h) => (failureImpact(h, g).newlyStranded.length > 0) !== aps.includes(h));
    expect(disagreements).toEqual([]);
  });

  it("calls a cable a cut edge only when lowlink does, on a graph already in pieces", () => {
    /* With L26 and L32 down the pod (dist1, dist2, podacc1, podacc2) is its own component and its
       five cables form a cycle: none of them cuts anything. Each was reported as a bridge stranding
       all four members — and published as a fabricated "disagree" against the engine's is_bridge. */
    const g = buildAdjacencyFrom(withDown("L26", "L32"), fabric.devices);
    const cut = new Set(bridges(g).bridges.map((b) => b.linkId));
    /* A cable on a disputed port (./port-claims.ts) has its verdict WITHHELD (isBridge null,
       not-determinable) rather than wrong; it is checked as withheld, and the rest against lowlink. */
    const disputed = new Set(findPortDisputes(g.source.links).flatMap((d) => d.claims.map((c) => c.linkId)));
    const withheld = g.edges.filter((e) => disputed.has(e.linkId));
    expect(withheld.length).toBeGreaterThan(0);
    for (const e of withheld) {
      const r = linkFailureImpact(e.linkId, g);
      expect(r.isBridge, e.linkId).toBeNull();
      expect(r.certainty, e.linkId).toBe("not-determinable");
    }
    const wrong = g.edges.filter((e) => !disputed.has(e.linkId) && linkFailureImpact(e.linkId, g).isBridge !== cut.has(e.linkId));
    expect(wrong.map((e) => e.linkId)).toEqual([]);
    for (const id of ["L39", "L40", "L41", "L42", "L43"]) {
      const r = linkFailureImpact(id, g);
      expect(r.isBridge, id).toBe(false);
      expect(r.newlyStranded, id).toEqual([]);
      expect(r.engine.agreement, id).toBe("agree"); // engine says is_bridge:false and so do we
    }
  });

  it("matches the oracle for every host and every cable on all 946 two-cable perturbations", () => {
    /* The single-cable sweep above never produces a graph whose non-largest component holds two or
       more nodes, so it cannot reach this defect. Two-cable perturbations do. Mismatches are
       collected and asserted once: 60k individual expect() calls cost more than the sweep. */
    const ids = fabric.links.map((l) => l.id);
    const mismatches: string[] = [];
    let pairs = 0;
    let withheldLinks = 0;
    let comparedLinks = 0;
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        const label = `${ids[i]}+${ids[j]}`;
        const g = buildAdjacencyFrom(withDown(ids[i] as string, ids[j] as string), fabric.devices);
        pairs += 1;
        for (const host of g.nodes) {
          const got = failureImpact(host, g).newlyStranded;
          const want = oracleHost(g, host);
          if (got.join(",") !== want.join(",")) mismatches.push(`${label} host ${host}: ${got} vs ${want}`);
        }
        const disputed = new Set(findPortDisputes(g.source.links).flatMap((d) => d.claims.map((c) => c.linkId)));
        for (const e of g.edges) {
          const r = linkFailureImpact(e.linkId, g);
          /* A cable on a disputed port has no radius to compare: it is withheld as not-determinable
             (./port-claims.ts). Counted, so the skip cannot silently swallow the sweep. */
          if (disputed.has(e.linkId)) {
            withheldLinks += 1;
            if (r.certainty !== "not-determinable" || r.newlyStranded.length > 0) mismatches.push(`${label} link ${e.linkId}: disputed but not withheld`);
            continue;
          }
          const got = r.newlyStranded;
          const want = oracleLink(g, e.linkId);
          if (got.join(",") !== want.join(",")) mismatches.push(`${label} link ${e.linkId}: ${got} vs ${want}`);
          comparedLinks += 1;
        }
      }
    }
    expect(pairs).toBe(946);
    expect(withheldLinks).toBeGreaterThan(0);
    expect(comparedLinks).toBeGreaterThan(withheldLinks);
    expect(mismatches.slice(0, 5)).toEqual([]);
    expect(mismatches).toHaveLength(0);
  }, 600_000);
});

describeGolden("regression: a cut vertex separates only what its removal separates", () => {
  /* With L26, L39, L40, L42 and L43 down, podacc1 and podacc2 hold no carrying cable at all —
     g.isolatedNodes names them in the same object. They were credited to core1, core2 AND dist2 as
     hosts each one separates, inflating three different SPOF verdicts with the same dead hosts. */
  const preIsolated = (): Graph => buildAdjacencyFrom(withDown("L26", "L39", "L40", "L42", "L43"), fabric.devices);

  it("never credits an already-isolated host to a cut vertex", () => {
    const g = preIsolated();
    expect(g.isolatedNodes).toEqual(["podacc1", "podacc2"]);
    const r = articulationPoints(g);
    expect(r.points.length).toBeGreaterThan(0);
    for (const p of r.points) {
      for (const iso of g.isolatedNodes) expect(p.separatedHosts, `${p.host} separates ${iso}`).not.toContain(iso);
    }
  });

  it("agrees host-for-host with failureImpact on the same graph", () => {
    const g = preIsolated();
    for (const p of articulationPoints(g).points) {
      expect(p.separatedHosts, p.host).toEqual(failureImpact(p.host, g).newlyStranded);
    }
  });
});

describeGolden("regression: a cut vertex's endpoint count keeps its coverage honesty", () => {
  /* endpoint_identity holds no record for AP-floor1, AP-floor3-01, core2, dist1, dist2 or
     wan-edge-rtr1.lab. Down core2's eight leaf cables plus L27 and L41 and the fabric becomes
     core1—dist1—podacc{1,2}—dist2—core2: dist2 is then a cut vertex whose entire blast radius is
     core2, a host with no endpoint records at all. Reporting 0 there is absence read as health. */
  const thinned = (): Graph =>
    buildAdjacencyFrom(
      withDown("L27", "L28", "L29", "L30", "L31", "L33", "L36", "L37", "L38", "L41"),
      fabric.devices,
    );

  it("declines a bare number when nothing behind the cut has an endpoint record", () => {
    const p = articulationPoints(thinned()).points.find((x) => x.host === "dist2");
    expect(p?.separatedHosts).toEqual(["core2"]);
    expect(p?.hostsWithoutEndpointRecords).toEqual(["core2"]);
    expect(p?.endpointsBehind).toBeNull();
  });

  it("names the unrecorded hosts behind a cut it does count", () => {
    const r = articulationPoints(thinned());
    const p = r.points.find((x) => x.host === "dist1");
    expect(p?.separatedHosts).toEqual(["core2", "dist2", "podacc1", "podacc2"]);
    expect(p?.endpointsBehind).toBe(4); // podacc1 + podacc2, two records each
    expect(p?.hostsWithoutEndpointRecords).toEqual(["core2", "dist2"]);
    expect(r.caveats.join(" ")).toMatch(/core2/);
    expect(r.caveats.join(" ")).toMatch(/not zero|unknown/i);
  });

  it("says the same thing in the claim as in the caveats", () => {
    const g = thinned();
    const r = failureImpact("dist2", g);
    expect(r.newlyStranded).toEqual(["core2"]);
    expect(r.claim).toMatch(/unknown number of endpoints/i);
    expect(r.claim).not.toMatch(/at least 0/);
  });

  it("publishes the same refusal on every surface that carries a bare endpoint number", () => {
    /* The renderable number is `floorTotal`, and it declines wherever the arithmetic sum would be a
       0 nobody measured. `total` keeps the sum, next to the list that qualifies it. */
    const g = thinned();
    const link = linkFailureImpact("L32", g); // core2's last uplink: cutting it strands core2 alone
    expect(link.newlyStranded).toEqual(["core2"]);
    expect(link.strandedEndpoints.total).toBe(0);
    expect(link.strandedEndpoints.floorTotal).toBeNull();
    expect(link.strandedEndpoints.hostsWithoutEndpointRecords).toEqual(["core2"]);
    expect(link.claim).toMatch(/unknown number of endpoints/i);
    // and a real count still reads as a floor, not as a refusal
    const counted = linkFailureImpact("L18");
    expect(counted.strandedEndpoints.floorTotal).toBe(3);
    expect(counted.claim).toContain("at least 3 observed endpoint(s)");
  });
});

describeGolden("regression: reachability from a host whose own cabling was never observed", () => {
  /* AP-floor3-01's only cable is L34 (core2↔AP-floor3-01, op_status "unknown"). Asked from core2
     the module says "uncertain" and names it; asked from AP-floor3-01 it said "observed: 0
     reachable, 23 unreachable" — the identical unobserved evidence, rendered as a definite answer.
     pathsBetween on the same pair has always returned not-determinable. */
  it("refuses to answer rather than reporting nothing reachable", () => {
    for (const host of ["AP-floor3-01", "wan-edge-rtr1.lab"]) {
      const r = reachableSet(host);
      expect(r.certainty, host).toBe("not-determinable");
      expect(r.unreachable, host).toEqual([]);
      expect(r.hosts, host).toEqual([]);
    }
    expect(reachableSet("AP-floor3-01").caveats.join(" ")).toContain("L34");
    expect(reachableSet("wan-edge-rtr1.lab").caveats.join(" ")).toContain("L35");
    expect(reachableSet("AP-floor3-01").uncertainLinksInScope).toEqual(["L34"]);
  });

  it("gives the same verdict as pathsBetween about the same cable", () => {
    expect(pathsBetween("core2", "AP-floor3-01").certainty).toBe("not-determinable");
    expect(reachableSet("AP-floor3-01").certainty).toBe("not-determinable");
  });

  it("still answers observed when the subject's own cables were observed down", () => {
    /* A down cable is evidence; an unobserved one is not. access1 isolated by a down L18 really can
       reach nobody, and that answer is observed — this is the line the fix must not blur. */
    const g = buildAdjacencyFrom(withDown("L18"), fabric.devices);
    const r = reachableSet("access1", g);
    expect(r.hosts).toEqual(["access1"]);
    expect(r.certainty).toBe("observed");
  });
});

/* An invariant (it sweeps every device and link of whatever fabric is loaded); it was filed under the golden tier in
   phase 3 and is moved back out (P3C-V2-3). */
describe("regression: projection prose quotes the quantity that actually moved", () => {
  /* `differs` is true when EITHER the stranded set or the component count changed, but the sentence
     interpolated only the stranded count — so a component-only difference printed "0 host(s)
     stranded instead of 0", and the endpoint caveat printed "3 endpoint(s) instead of 3". */
  const offenders = (lines: readonly string[]): string[] =>
    lines.filter((line) => {
      const m = /(\d+)[^.]*?instead of (\d+)/.exec(line);
      return m !== null && m[1] === m[2];
    });

  it("never states a difference by printing the same number twice", () => {
    const bad: string[] = [];
    for (const d of fabric.devices) {
      const r = failureImpact(d.id);
      bad.push(...offenders([...r.alternateProjections.flatMap((a) => [a.note, ...a.differences]), ...r.caveats]));
    }
    for (const l of fabric.links) {
      const r = linkFailureImpact(l.id);
      bad.push(...offenders([...r.alternateProjections.flatMap((a) => [a.note, ...a.differences]), ...r.caveats]));
    }
    expect(bad).toEqual([]);
  });

  it("keeps `differs` and the stated differences in step", () => {
    for (const d of fabric.devices) {
      for (const a of failureImpact(d.id).alternateProjections) {
        expect(a.differs, `${d.id} ${a.options.transit}/${a.options.unknownStatus}`).toBe(a.differences.length > 0);
      }
    }
  });
});

/* An invariant over any fabric: the host whose adjacency is checked is CUT (resolved by property above), not a typed
   name (P3C-V2-3). */
describe("regression: the shared graph is evidence a renderer cannot edit", () => {
  it("freezes what this module builds, mutators included", () => {
    const g = buildAdjacency();
    expect(Object.isFrozen(g)).toBe(true);
    expect(Object.isFrozen(g.edges[0])).toBe(true);
    if (g.excluded.length > 0) expect(Object.isFrozen(g.excluded[0])).toBe(true);
    if (g.attachedNonTransit.length > 0) expect(Object.isFrozen(g.attachedNonTransit[0])).toBe(true);
    expect(Object.isFrozen(g.assumptions[0])).toBe(true);
    expect(Object.isFrozen(g.options)).toBe(true);
    expect(g.adjacency.get(CUT)?.length ?? 0, "precondition: CUT has adjacency to freeze").toBeGreaterThan(0);
    expect(Object.isFrozen(g.adjacency.get(CUT))).toBe(true);
    expect(Object.isFrozen((g.adjacency.get(CUT) ?? [])[0])).toBe(true);
  });

  it("has no way to inject a host into the memoised singleton", () => {
    const g = buildAdjacency();
    const asMap = g.adjacency as unknown as { set?: unknown };
    expect(asMap.set).toBeUndefined();
    expect(buildAdjacency().adjacency.has("ghost")).toBe(false);
    expect(failureImpact("ghost").presence).toBe("absent-from-topology");
  });
});

describe("regression: the path-enumeration ceiling is a ceiling", () => {
  /* Math.max(1, Math.min(Math.trunc(NaN), 64)) is NaN, so `paths.length >= cap` was never true and
     enumeration ran unbounded while `truncated` reported false. The snapshot's largest minimum-hop
     path count between any pair is 17, so the ceiling itself is unreachable through pathsBetween —
     it is pinned here directly, where it can actually execute. */
  it("clamps every request, including the ones that are not numbers", () => {
    expect(resolvePathLimit(1000)).toEqual({ requested: 1000, applied: 64, ceiling: 64, usable: true });
    expect(resolvePathLimit(Number.POSITIVE_INFINITY).applied).toBe(64);
    expect(resolvePathLimit(Number.NaN)).toEqual({ requested: null, applied: 64, ceiling: 64, usable: false });
    expect(resolvePathLimit(0)).toEqual({ requested: 0, applied: 1, ceiling: 64, usable: true });
    expect(resolvePathLimit(-3).applied).toBe(1);
    expect(resolvePathLimit(3.9)).toEqual({ requested: 3, applied: 3, ceiling: 64, usable: true });
  });

  it("reports the limit it actually applied, and says so when the request was unusable", () => {
    // Any pair (PAIR is joined by a carrying cable, so a path exists on any fabric that has one).
    const r = pathsBetween(PAIR[0], PAIR[1], Number.NaN, ALL_NODES());
    expect(r.pathLimit).toEqual({ requested: null, applied: 64, ceiling: 64, usable: false });
    expect(r.paths.length).toBeLessThanOrEqual(64);
    expect(r.caveats.join(" ")).toMatch(/limit/i);
    const ok = pathsBetween(PAIR[0], PAIR[1], 3, ALL_NODES());
    expect(ok.pathLimit).toEqual({ requested: 3, applied: 3, ceiling: 64, usable: true });
    expect(ok.paths.length).toBeLessThanOrEqual(3);
  });
});

describeGolden("regression: the path-enumeration ceiling on the reference sample", () => {
  it("core1 to AP-floor1 has more than three minimum-hop paths, so a limit of 3 truncates and says so", () => {
    const r = pathsBetween("core1", "AP-floor1", Number.NaN, ALL_NODES());
    expect(r.pathLimit).toEqual({ requested: null, applied: 64, ceiling: 64, usable: false });
    const ok = pathsBetween("core1", "AP-floor1", 3, ALL_NODES());
    expect(ok.pathLimit).toEqual({ requested: 3, applied: 3, ceiling: 64, usable: true });
    expect(ok.truncated).toBe(true);
  });
});

/* ══ a refusal message may not name an innocent device ═════════════════════ */

/**
 * THE DEFECT. The refusal for a link excluded as non-transit printed BOTH endpoints inside a
 * parenthetical that reads as the list of never-collected ends:
 *
 *   "L0 is up but at least one end (access1, AP-floor1) was never collected, …"
 *
 * `access1` has `collected: true`, eighteen findings, health band Poor and four physical-health
 * rows. Only `AP-floor1` was never collected. The message interpolated `excluded?.a` and
 * `excluded?.b` — the cable's two ends — rather than the uncollected ones, on EVERY non-transit
 * link. The same optional chaining would have rendered the literal string "undefined" had the
 * branch been reached with no exclusion record.
 *
 * Asserted over the whole class, not over L0: for every link the projection excludes as
 * non-transit, every host the message names as never-collected must actually be uncollected.
 */
/* Hoisted (QC-R1-4) so the golden block at the foot of this file can state that the sample has such links. */
const nonTransitGraph = buildAdjacency();
const nonTransit = nonTransitGraph.excluded.filter((x) => x.reason === "non-transit-endpoint");
describe("the non-transit refusal names only the ends that were never collected", () => {
  const graph = nonTransitGraph;
  const collectedOf = new Map(graph.source.devices.map((d) => [d.id, d.collected]));

  /* The class sweep runs on any fabric; that the sample HAS such links (so the sweep is not empty there) is pinned
     in the golden block at the foot of this file, and a fabric with none says so by name. */
  it.runIf(nonTransit.length > 0)(
    nonTransit.length > 0 ? "has such links to speak about" : "has such links to speak about [skipped: the loaded dataset excludes no link as non-transit]",
    () => {
      expect(nonTransit.length).toBeGreaterThan(0);
    },
  );

  it.each(nonTransit.map((x) => x.linkId))(
    "%s does not call a collected device uncollected",
    (linkId) => {
      const r = linkFailureImpact(linkId, graph);
      const why = r.strandedEndpoints.note;
      const uncollected = [
        graph.excluded.find((x) => x.linkId === linkId)!.a,
        graph.excluded.find((x) => x.linkId === linkId)!.b,
      ].filter((h) => collectedOf.get(h) !== true);

      expect(why).not.toContain("undefined");
      expect(why).toMatch(/never collected/);
      for (const h of uncollected) expect(why, `${h} was never collected but is not named`).toContain(h);
      for (const [host, isCollected] of collectedOf) {
        if (!isCollected) continue;
        /* A collected device may legitimately appear elsewhere in a sentence, but not inside the
           clause that says what was never collected. The clause is what is checked. */
        const clause = /never collected[^.]*/.exec(why)?.[0] ?? "";
        const before = why.slice(0, why.indexOf("never collected"));
        expect(
          `${before} ${clause}`.includes(host),
          `${linkId}: "${why}" names ${host} as never collected, but it was collected`,
        ).toBe(false);
      }
    },
  );
});

/* ── invariants over any compiled fabric (phase 3), the property-level counterparts of the golden blocks ── */
describe("blast invariants on the loaded fabric", () => {
  it("the subjects above were resolved from the data, not named", () => {
    expect(G0.nodes).toContain(CUT);
    expect(G0.nodes).toContain(LEAF);
    expect(fabric.links.map((l) => l.id)).toContain(BRIDGE);
  });

  it("the engine comparison accounts for every cable once, and never reads silence as a verdict", () => {
    const r = bridges();
    const silent = fabric.links.filter((l) => l.isBridge === null).map((l) => l.id).sort();
    expect([...r.engineComparison.linksWithoutEngineRecord].sort()).toEqual(silent);
    expect(r.engineComparison.rows.every((row) => row.engine !== false || row.agreement !== "engine-silent")).toBe(true);
    // every bridge the ENGINE names is one ours names too, or a disagreement is surfaced for it
    const ours = new Set(r.bridges.map((b) => b.linkId));
    const disputed = new Set(r.engineComparison.disagreed.map((d) => d.linkId));
    const engineBridges = fabric.links.filter((l) => l.isBridge === true).map((l) => l.id);
    expect(engineBridges.filter((id) => !ours.has(id) && !disputed.has(id))).toEqual([]);
  });

  it("each articulation point's separated hosts are exactly what failureImpact strands, all real nodes", () => {
    const aps = articulationPoints().points;
    for (const p of aps) {
      expect(p.separatedHosts, p.host).toEqual(failureImpact(p.host).newlyStranded);
      expect(p.separatedHosts.filter((h) => !G0.nodes.includes(h)), p.host).toEqual([]);
    }
    expect(aps.every((p) => p.componentsAfterRemoval >= 2)).toBe(true);
  });

  it("a non-cut transit node strands nobody else", () => {
    expect(failureImpact(LEAF).newlyStranded).toEqual([]);
  });

  it("kCore scores every transit node and names every attached non-transit node as unscored, never as 0", () => {
    const r = kCore();
    expect(r.coreness.map((c) => c.host).sort()).toEqual([...G0.nodes].sort());
    expect(r.notScored.map((n) => n.host).sort()).toEqual(G0.attachedNonTransit.map((a) => a.host).sort());
    expect(r.maxCore).toBe(Math.max(0, ...r.coreness.map((c) => c.k)));
  });

  it("reachableSet from a node holds every node its own component walks to", () => {
    const seen = new Set<string>([CUT]);
    const stack = [CUT];
    while (stack.length > 0) for (const e of G0.adjacency.get(stack.pop()!) ?? []) if (!seen.has(e.host)) (seen.add(e.host), stack.push(e.host));
    expect([...seen].filter((h) => !reachableSet(CUT).hosts.includes(h))).toEqual([]);
  });
});

/* ── the golden regressions above, as PROPERTIES of any fabric (P3C-V2-3, phase 3.5) ──
 * The regression blocks pin each defect on the sample's own cables (L26 and L27 down, the five pod cables, ...),
 * so they run only there. What each stood for holds on any fabric, and is checked here on perturbations CHOSEN BY
 * PROPERTY: every pair of the cables incident to the widest cut vertex (CUT) downed together — which, wherever CUT
 * has two or more cables, leaves the fabric already in pieces, the brownfield shape every one of those defects
 * needed. The oracles are the independent walks above. */
/* The preconditions below are hoisted to module scope (QC-R1-4) so the golden block can state that each holds on
   the reference sample; otherwise a sample change that falsified one would turn its test into a silent named skip. */
const cutCables = fabric.links
  .filter((l) => l.a === CUT || l.b === CUT)
  .map((l) => l.id)
  .sort(cmpStr);
const PERTURBED = cutCables.flatMap((x, i) =>
  cutCables.slice(i + 1).map((y) => ({ label: `${x}+${y}`, g: buildAdjacencyFrom(withDown(x, y), fabric.devices) })),
);
/** Whether some perturbation leaves a component other than the largest with two or more nodes: the shape the
 *  own-component defect needed (a single-cable sweep never produces one). */
const piecesOf = (g: Graph): string[][] => {
  const done = new Set<string>();
  const out: string[][] = [];
  for (const n of g.nodes) {
    if (done.has(n)) continue;
    const piece = [...walk(g, n)];
    for (const m of piece) done.add(m);
    out.push(piece);
  }
  return out.sort((x, y) => y.length - x.length);
};
const REACHES = PERTURBED.some(({ g }) => piecesOf(g).slice(1).some((p) => p.length >= 2));
const needs = (ok: boolean, title: string, why: string): [boolean, string] => [ok, ok ? title : `${title} [skipped: ${why}]`];

const [ownOk, ownTitle] = needs(
  REACHES,
  "a blast radius is measured inside the failed element's own component, on every two-cable cut around the widest cut vertex",
  "no two-cable cut around the widest cut vertex leaves a second multi-node piece",
);
const [storyOk, storyTitle] = needs(PERTURBED.length > 0, "failureImpact and articulationPoints tell one story on every such graph, and a cut vertex separates only what its removal separates", "the widest cut vertex has fewer than two cables");
/** Hosts every one of whose cables is outside the default projection (unknown status): the sample's AP-floor3-01
 *  and wan-edge-rtr1.lab. */
const uncertainIds = new Set(G0.uncertainLinkIds);
const UNOBSERVED_CABLING = fabric.devices
  .map((d) => d.host)
  .filter((h) => {
    const own = fabric.links.filter((l) => l.a === h || l.b === h);
    return own.length > 0 && own.every((l) => uncertainIds.has(l.id));
  });
const [unobsOk, unobsTitle] = needs(UNOBSERVED_CABLING.length > 0, "reachability from a host whose own cabling was never observed refuses to answer, as pathsBetween does", "no host's cabling is entirely unobserved");
describe("blast regressions as properties of the loaded fabric", () => {
  it.runIf(ownOk)(ownTitle, () => {
    const mismatches: string[] = [];
    let comparedLinks = 0;
    for (const { label, g } of PERTURBED) {
      for (const host of g.nodes) {
        const got = failureImpact(host, g).newlyStranded;
        const want = oracleHost(g, host);
        if (got.join(",") !== want.join(",")) mismatches.push(`${label} host ${host}: ${got} vs ${want}`);
      }
      const disputed = new Set(findPortDisputes(g.source.links).flatMap((d) => d.claims.map((c) => c.linkId)));
      for (const e of g.edges) {
        const r = linkFailureImpact(e.linkId, g);
        if (disputed.has(e.linkId)) {
          if (r.certainty !== "not-determinable" || r.newlyStranded.length > 0) mismatches.push(`${label} link ${e.linkId}: disputed but not withheld`);
          continue;
        }
        comparedLinks += 1;
        const want = oracleLink(g, e.linkId);
        if (r.newlyStranded.join(",") !== want.join(",")) mismatches.push(`${label} link ${e.linkId}: ${r.newlyStranded} vs ${want}`);
      }
    }
    expect(comparedLinks).toBeGreaterThan(0);
    expect(mismatches.slice(0, 5)).toEqual([]);
  }, 600_000);

  it.runIf(storyOk)(storyTitle, () => {
    for (const { label, g } of PERTURBED) {
      const aps = articulationPoints(g).points;
      const names = aps.map((p) => p.host);
      expect(g.nodes.filter((h) => (failureImpact(h, g).newlyStranded.length > 0) !== names.includes(h)), label).toEqual([]);
      for (const p of aps) {
        expect(p.separatedHosts, `${label} ${p.host}`).toEqual(failureImpact(p.host, g).newlyStranded);
        for (const iso of g.isolatedNodes) expect(p.separatedHosts, `${label}: ${p.host} separates ${iso}`).not.toContain(iso);
      }
    }
  });

  it("an endpoint count behind a cut is a floor it measured, or a stated refusal — never a 0 nobody measured", () => {
    const graphs = [{ label: "as collected", g: G0 }, ...PERTURBED];
    let judged = 0;
    for (const { label, g } of graphs) {
      const results = [
        // A failed host's own endpoints go down with it, so its count covers the host itself as well as what it strands.
        ...g.nodes.map((h) => ({ at: `${label} host ${h}`, r: failureImpact(h, g), self: [h] })),
        ...g.edges.map((e) => ({ at: `${label} link ${e.linkId}`, r: linkFailureImpact(e.linkId, g), self: [] as string[] })),
      ];
      for (const { at, r, self } of results) {
        if (r.newlyStranded.length === 0) continue;
        judged += 1;
        expect(r.claim, at).not.toMatch(/at least 0\b/);
        const without = r.strandedEndpoints.hostsWithoutEndpointRecords;
        expect(without.filter((h) => !r.newlyStranded.includes(h) && !self.includes(h)), `${at}: an unrecorded host that is not behind the cut`).toEqual([]);
        if (r.strandedEndpoints.floorTotal === null) expect(r.claim, at).toMatch(/unknown number of endpoints/i);
        else expect(r.claim, at).toContain(`at least ${r.strandedEndpoints.floorTotal}`);
        if (r.strandedEndpoints.total === 0 && without.length > 0) expect(r.strandedEndpoints.floorTotal, at).toBeNull();
      }
    }
    expect(judged, "some cut strands a host, so the rule is exercised").toBeGreaterThan(0);
  });

  it.runIf(unobsOk)(unobsTitle, () => {
    for (const host of UNOBSERVED_CABLING) {
      const r = reachableSet(host);
      expect(r.certainty, host).toBe("not-determinable");
      expect(r.unreachable, host).toEqual([]);
      expect(r.hosts, host).toEqual([]);
      const own = fabric.links.filter((l) => l.a === host || l.b === host);
      for (const l of own) expect(r.caveats.join(" "), host).toContain(l.id);
      const far = own[0]!.a === host ? own[0]!.b : own[0]!.a;
      expect(pathsBetween(far, host).certainty, `${far} -> ${host}`).toBe("not-determinable");
    }
  });

  it("a host whose own cables were observed DOWN reaches nobody, and that answer is observed", () => {
    /* A down cable is evidence; an unobserved one is not. The line the refusal above must not blur. */
    const own = fabric.links.filter((l) => l.a === LEAF || l.b === LEAF).map((l) => l.id);
    expect(own.length, "precondition: LEAF has cables to down").toBeGreaterThan(0);
    const r = reachableSet(LEAF, buildAdjacencyFrom(withDown(...own), fabric.devices));
    expect(r.hosts).toEqual([LEAF]);
    expect(r.certainty).toBe("observed");
  });
});

describeGolden("blast on the reference sample: the resolved subjects and the population", () => {
  it("the property-resolved subjects are the ones the golden blocks name", () => {
    expect(CUT).toBe("core1");
    expect(fabric.links).toHaveLength(44);
    expect(G0.uncertainLinkIds).toEqual(["L34", "L35"]);
  });

  it("every named-skip precondition above holds here, so none of those tests is skipped on the reference sample (QC-R1-4)", () => {
    expect(nonTransit.length).toBeGreaterThan(0);
    expect(REACHES).toBe(true);
    expect(ownOk).toBe(true);
    expect(storyOk).toBe(true);
    expect(unobsOk).toBe(true);
    expect([...UNOBSERVED_CABLING].sort()).toEqual(["AP-floor3-01", "wan-edge-rtr1.lab"]);
  });

  it("the property counterparts reach the audited shapes here: core1's cables, the two unobserved-cabling hosts, non-transit links", () => {
    expect(fabric.links.filter((l) => l.a === "core1" || l.b === "core1").length).toBeGreaterThanOrEqual(2);
    const uncertain = new Set(G0.uncertainLinkIds);
    const unobserved = fabric.devices
      .map((d) => d.host)
      .filter((h) => {
        const own = fabric.links.filter((l) => l.a === h || l.b === h);
        return own.length > 0 && own.every((l) => uncertain.has(l.id));
      });
    expect(unobserved.sort()).toEqual(["AP-floor3-01", "wan-edge-rtr1.lab"]);
    expect(buildAdjacency().excluded.filter((x) => x.reason === "non-transit-endpoint").length).toBeGreaterThan(0);
  });
});
