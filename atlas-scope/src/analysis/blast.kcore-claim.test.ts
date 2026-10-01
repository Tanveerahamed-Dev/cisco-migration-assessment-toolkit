/**
 * blast.kcore-claim.test.ts — the k-core claim states what THIS graph's shells are (disc-app-sample-assumptions #3).
 *
 * The claim used to say, on every input, "the N host(s) in the highest shell are the mutually redundant spine;
 * shell 1 and 0 hosts hang off it" — true only because the reference sample's maximum coreness is 2. On a
 * loop-free tree (maximum coreness 1) it called the whole fleet a mutually redundant spine, where no host has a
 * redundant path at all. The claim now branches on maxCore (<= 1 means no redundant core) and names the shells
 * below the highest from the data.
 *
 * The graphs here are synthetic adjacency over made-up host names, built on the real projection's options and
 * assumptions, so kCore is exercised on shapes the sample does not contain.
 */
import { describe, expect, it } from "vitest";
import { buildAdjacency, kCore, type AdjacencyEntry, type TopologyGraph } from "./blast";

/** A carrying-adjacency graph over the given undirected edges (the real projection's options and assumptions). */
function graphOf(edges: readonly (readonly [string, string])[], isolated: readonly string[] = []): TopologyGraph {
  const real = buildAdjacency();
  const adjacency = new Map<string, AdjacencyEntry[]>();
  const nodes = new Set<string>(isolated);
  edges.forEach(([a, b], i) => {
    nodes.add(a).add(b);
    const linkId = `S${i}`;
    adjacency.set(a, [...(adjacency.get(a) ?? []), { host: b, linkId }]);
    adjacency.set(b, [...(adjacency.get(b) ?? []), { host: a, linkId }]);
  });
  const sorted = [...nodes].sort();
  for (const n of sorted) if (!adjacency.has(n)) adjacency.set(n, []);
  return { ...real, nodes: sorted, adjacency, attachedNonTransit: [], uncertainLinkIds: [], isolatedNodes: [...isolated] };
}

const star = graphOf([
  ["hub", "a"],
  ["hub", "b"],
  ["hub", "c"],
  ["c", "d"],
]);
/** K4 (maximum coreness 3) with a two-host tail (coreness 1). */
const k4tail = graphOf([
  ["n1", "n2"],
  ["n1", "n3"],
  ["n1", "n4"],
  ["n2", "n3"],
  ["n2", "n4"],
  ["n3", "n4"],
  ["n4", "t1"],
  ["t1", "t2"],
]);

describe("kCore claim is branched on the graph's own maximum coreness", () => {
  it("a loop-free tree (maxCore 1) has no redundant core, and the claim says so", () => {
    const r = kCore(star);
    expect(r.maxCore).toBe(1);
    expect(r.claim).toMatch(/no host has redundant adjacency/);
    expect(r.claim).not.toMatch(/mutually redundant/);
    expect(r.claim).not.toMatch(/spine/);
    expect(r.claim).toContain("maximum coreness 1");
    expect(r.claim).toContain("every carrying link is a bridge");
  });

  it("K4 plus a tail (maxCore 3) names the highest shell and every lower shell from the data", () => {
    const r = kCore(k4tail);
    expect(r.maxCore).toBe(3);
    expect(r.shells.map((s) => [s.k, s.hosts.length])).toEqual([
      [3, 4],
      [1, 2],
    ]);
    expect(r.claim).toContain("the 4 hosts in the highest shell (k = 3) each keep at least 3 carrying links inside it");
    expect(r.claim).toContain("the lower shells hang off it: k = 1 (2 hosts)");
    // The old literal named shells this graph does not have.
    expect(r.claim).not.toMatch(/shell 1 and 0/);
    expect(r.claim).not.toMatch(/k = 2|k = 0/);
  });

  /* P3C-V2-4 (verifier, phase 3): coreness is peeled over LINKS — the adjacency holds one entry per carrying link,
     parallel links included — so two hosts joined by two parallel cables reach k = 2 while each has ONE neighbour.
     The claim said "at least k neighbours", which the computation does not measure. It now says what it counts. */
  it("counts carrying links, not neighbours: two hosts on two parallel cables are a 2-shell of one neighbour each", () => {
    const r = kCore(
      graphOf([
        ["pa", "pb"],
        ["pa", "pb"],
        ["pb", "pc"],
      ]),
    );
    expect(r.maxCore).toBe(2);
    expect(r.shells.map((x) => [x.k, [...x.hosts].sort()])).toEqual([
      [2, ["pa", "pb"]],
      [1, ["pc"]],
    ]);
    expect(r.claim).toContain("the 2 hosts in the highest shell (k = 2) each keep at least 2 carrying links inside it");
    expect(r.claim).not.toMatch(/neighbour/);
  });

  it("a graph with no carrying link at all (maxCore 0) names no core", () => {
    const r = kCore(graphOf([], ["lonely1", "lonely2"]));
    expect(r.maxCore).toBe(0);
    expect(r.claim).toMatch(/no carrying adjacency/);
    expect(r.claim).not.toMatch(/redundant (spine|core)\b(?! )/);
    expect(r.claim).not.toMatch(/highest shell/);
  });

  it("on the loaded fabric the claim agrees with its own shells (invariant)", () => {
    const r = kCore();
    const top = r.shells[0];
    if (r.maxCore <= 1) {
      expect(r.claim).toMatch(/no host has redundant adjacency|no carrying adjacency/);
    } else {
      expect(top?.k).toBe(r.maxCore);
      const n = top!.hosts.length;
      expect(r.claim).toContain(`the ${n} host${n === 1 ? "" : "s"} in the highest shell (k = ${r.maxCore})`);
      for (const s of r.shells.slice(1)) expect(r.claim).toContain(`k = ${s.k} (${s.hosts.length} host${s.hosts.length === 1 ? "" : "s"})`);
    }
  });
});
