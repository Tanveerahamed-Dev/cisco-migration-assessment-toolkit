/**
 * tier-groups.test.ts — the skeleton's tier reading and the layout's cannot drift.
 *
 * `reconcileTierGroups` (tier-groups.ts) is what the loading skeleton labels its groups by; `computeLayout`
 * publishes the same reading as `diagnostics.cableMapGroups`. Until the layout calls this module itself, both
 * exist, so this test holds them equal on the loaded fabric and on synthetic partitions covering every basis.
 */
import { describe, expect, it } from "vitest";
import fabricJson from "../data/fabric.json";
import type { Device, Link } from "../core/types";
import { computeLayout } from "./layout";
import { reconcileTierGroups } from "./tier-groups";

const devices = fabricJson.devices as Device[];
const links = fabricJson.links as Link[];

const layoutGroups = (ds: readonly Device[], tiers: readonly (readonly string[])[]) =>
  computeLayout({ devices: ds, links: links.filter((l) => ds.some((d) => d.id === l.a) && ds.some((d) => d.id === l.b)), tiers }).diagnostics.cableMapGroups;

describe("reconcileTierGroups agrees with the layout's own reconciliation", () => {
  it("on the loaded fabric", () => {
    expect(reconcileTierGroups(devices, fabricJson.tiers)).toEqual(layoutGroups(devices, fabricJson.tiers));
  });

  it("on synthetic partitions covering consensus, majority, tie and no member tier", () => {
    const d = (host: string, tier: number | null): Device => ({ ...devices[0]!, id: host, host, tier });
    const ds = [d("a", 0), d("b", 0), d("c", 1), d("e", 1), d("f", 2), d("g", 2), d("h", null), d("i", null), d("j", 3)];
    const tiers = [["a", "b"], ["c", "e", "f"], ["g", "j"], ["h", "i"], ["ghost-with-no-record"]];
    const mine = reconcileTierGroups(ds, tiers);
    expect(mine.map((g) => g.basis)).toEqual(["device-consensus", "device-majority", "no-consensus", "no-member-tier", "no-member-tier"]);
    expect(mine.map((g) => g.tier)).toEqual([0, 1, null, null, null]);
    expect(mine).toEqual(layoutGroups(ds, tiers));
  });
});
