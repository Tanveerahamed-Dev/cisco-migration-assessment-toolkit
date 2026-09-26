/**
 * FabricA11yTree.linkcut.test.ts — A6: the non-canvas channels never state the snapshot's bridge flag as fact
 * where our own computation (the one the Inspector shows) cannot decide or disagrees.
 *
 * MEASURED (audit, real canvas click on L7): the live region said "Cutting this link partitions
 * the fabric." while the Inspector said L7's radius is not determinable (L7 shares core1 Gi1/0/40
 * with L26). The rule is checked across EVERY link, not the one that was caught.
 */
import { describe, expect, it } from "vitest";
import { linkFailureImpact } from "../analysis/blast";
import { fabric } from "../core/data";
import { linkCutMeta, linkCutSentence } from "./FabricA11yTree";

describe("link-cut wording follows the computed radius and its certainty", () => {
  it("L7 (a disputed cable the snapshot calls a bridge) names the conflict", () => {
    const l7 = fabric.links.find((l) => l.id === "L7");
    if (!l7) throw new Error("the shipped snapshot has no L7; this test pins the audited case");
    const s = linkCutSentence(l7);
    expect(s).toContain("The snapshot says cutting this link partitions the fabric.");
    expect(s).toContain("cannot decide");
    expect(s).toContain("disputed");
    expect(linkCutMeta(l7).unobserved).toBe(true);
  });

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
