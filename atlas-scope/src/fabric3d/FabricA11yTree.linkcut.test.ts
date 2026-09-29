/**
 * FabricA11yTree.linkcut.test.ts — A6: the non-canvas channels never state the snapshot's bridge flag as fact
 * where our own computation (the one the Inspector shows) cannot decide or disagrees.
 *
 * MEASURED (audit, real canvas click on L7): the live region said "Cutting this link partitions
 * the fabric." while the Inspector said L7's radius is not determinable (L7 shares core1 Gi1/0/40
 * with L26). The rule is checked across EVERY link, not the one that was caught.
 */
import { describe, expect, it } from "vitest";
import { describeGolden } from "../test-support/golden-sample";
import { linkFailureImpact } from "../analysis/blast";
import { fabric } from "../core/data";
import { linkCutMeta, linkCutSentence } from "./FabricA11yTree";

/** Every (host, port) a link record names, and how many links name it: two links on one port is a dispute. */
const portUse = new Map<string, number>();
for (const l of fabric.links) {
  for (const [h, p] of [[l.a, l.aPort], [l.b, l.bPort]] as const) if (p !== null && p !== "") portUse.set(`${h}|${p}`, (portUse.get(`${h}|${p}`) ?? 0) + 1);
}
const disputed = (l: (typeof fabric.links)[number]): boolean =>
  [[l.a, l.aPort], [l.b, l.bPort]].some(([h, p]) => p !== null && p !== "" && (portUse.get(`${h}|${p}`) ?? 0) > 1);
/** Links the snapshot calls a bridge whose own port another link also claims (the sample's L7). */
const DISPUTED_BRIDGES = fabric.links.filter((l) => l.isBridge === true && disputed(l));

describe("link-cut wording follows the computed radius and its certainty", () => {
  /* RE-EXPRESSED 2026-09-29 (P3C-V2-3): the audited link used to be the only subject (typed L7), which exists only in
     the sample. The class is a cable the snapshot calls a bridge while its port is DISPUTED — another link claims
     the same port on the same host (read here straight off the link records) — so our computation cannot decide
     its radius. L7 (sharing core1 Gi1/0/40 with L26) is pinned by name in the golden block below. */
  it.runIf(DISPUTED_BRIDGES.length > 0)(
    DISPUTED_BRIDGES.length > 0
      ? "a disputed cable the snapshot calls a bridge names the conflict"
      : "a disputed cable the snapshot calls a bridge names the conflict [skipped: the loaded dataset has no such link]",
    () => {
      for (const l of DISPUTED_BRIDGES) {
        const s = linkCutSentence(l);
        expect(s, l.id).toContain("The snapshot says cutting this link partitions the fabric.");
        expect(s, l.id).toContain("cannot decide");
        expect(s, l.id).toContain("disputed");
        expect(linkCutMeta(l).unobserved, l.id).toBe(true);
      }
    },
  );

  it("no link's sentence asserts a partition our computation did not establish", () => {
    for (const l of fabric.links) {
      const r = linkFailureImpact(l.id);
      const s = linkCutSentence(l);
      const decided = r.certainty !== "not-determinable" && r.isBridge !== null;
      if (!decided) {
        expect(s, l.id).toContain("cannot decide");
        expect(linkCutMeta(l).text, l.id).not.toBe("cut partitions fabric");
      }
      // The bare, unattributed claim is never made.
      expect(s.startsWith("Cutting this link"), l.id).toBe(false);
      if (l.isBridge !== null && decided && l.isBridge !== r.isBridge) expect(s, l.id).toContain("disagrees");
    }
  });
});

describeGolden("link-cut wording on the reference sample", () => {
  it("L7 (sharing core1 Gi1/0/40 with L26, and called a bridge by the snapshot) is among the disputed bridges", () => {
    expect(DISPUTED_BRIDGES.map((l) => l.id)).toContain("L7");
    const l7 = fabric.links.find((l) => l.id === "L7")!;
    expect(linkCutSentence(l7)).toContain("disputed");
  });
});
