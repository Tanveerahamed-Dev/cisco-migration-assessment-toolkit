/**
 * surfaces.stage-pending.test.tsx — the loading skeleton numbers tiers as the fabric does, counts every device,
 * and says which sample its warm-up figure was measured on (disc-app-sample-assumptions #4 and #7).
 *
 * THE DEFECTS.
 *   - Each `fabric.tiers` group was labelled `tier ${i + 1}` — its array index, which layout.ts itself calls an
 *     artifact of serialisation. The same AP was announced as "Tier 0" by the fabric and "tier 1" here.
 *   - "Drawing the 3-D fabric: N devices" counted only devices listed in `fabric.tiers`; the layout places a
 *     device with no tier group too (in a bucket labelled "tier not observed"), so N under-counted it.
 *   - "up to about a second" was measured over cold loads of ONE sample and stated as if true of any snapshot.
 *
 * The skeleton is now `stageSkeleton(devices, tiers)`: one group per tier the LAYOUT places devices at (each
 * device's own record tier, else its cable-map group's reconciled tier — fabric3d/tier-groups.ts `placedTiers`),
 * "tier not observed" only for a device with neither (the layout's synthetic plane), the count = every device
 * record. Every case is held equal to `computeLayout(...).nodes[].observedTier`, never to a hand-written reading.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../fabric3d/Fabric3D", () => ({ default: () => <div data-testid="fabric-mounted" />, Fabric3D: () => <div /> }));

import { fabric } from "../core/data";
import type { Device } from "../core/types";
import { describeGolden } from "../test-support/golden-sample";
import { computeLayout } from "../fabric3d/layout";
import { Stage, stageSkeleton, WARMUP_MEASURED_ON } from "./surfaces";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {
  document.body.innerHTML = "";
});

const d = (host: string, tier: number | null): Device => ({ ...fabric.devices[0]!, id: host, host, tier });

/** What the layout itself does with each device: the tier it places it at (`observedTier`, null = the synthetic
 *  "tier not observed" plane) — the skeleton must say the same thing about every device. */
function layoutTiers(ds: readonly Device[], tiers: readonly (readonly string[])[]): Map<string, number | null> {
  const ids = new Set(ds.map((x) => x.id));
  const links = fabric.links.filter((l) => ids.has(l.a) && ids.has(l.b));
  return new Map(computeLayout({ devices: ds, links, tiers }).nodes.map((n) => [n.id, n.observedTier]));
}

/** The skeleton's own per-device reading, AS THE READER SEES IT: the tier its group's label announces. */
function skeletonTiers(s: ReturnType<typeof stageSkeleton>): Map<string, number | null> {
  const out = new Map<string, number | null>();
  for (const g of s.groups) {
    const m = /^tier (?:(\d+)|not observed) · \d+$/.exec(g.label);
    expect(m, `an unreadable label: ${g.label}`).not.toBeNull();
    for (const id of g.ids) {
      expect(out.has(id), `${id} drawn twice`).toBe(false);
      out.set(id, m![1] === undefined ? null : Number(m![1]));
    }
  }
  return out;
}

/** The skeleton agrees with the layout on every device, labels each group from its tier, and counts both. */
function expectAgreesWithLayout(ds: readonly Device[], tiers: readonly (readonly string[])[]): ReturnType<typeof stageSkeleton> {
  const s = stageSkeleton(ds, tiers);
  const placed = layoutTiers(ds, tiers);
  expect(skeletonTiers(s)).toEqual(placed);
  expect(s.placed).toBe(ds.length);
  for (const g of s.groups) expect(g.label).toBe(`${g.tier === null ? "tier not observed" : `tier ${g.tier}`} · ${g.ids.length}`);
  // One group per tier the layout places at, ascending, "tier not observed" (the layout's synthetic plane) last.
  const want = [...new Set(placed.values())].sort((a, b) => (a === null ? 1 : b === null ? -1 : a - b));
  expect(s.groups.map((g) => g.tier)).toEqual(want);
  expect(s.observedTiers).toBe(want.filter((t) => t !== null).length);
  return s;
}

describe("stageSkeleton", () => {
  it("labels a group by its members' recorded tier, never by its array index", () => {
    const ds = [d("ap", 0), d("sw1", 1), d("sw2", 1)];
    const s = expectAgreesWithLayout(ds, [["ap"], ["sw1", "sw2"]]);
    expect(s.groups.map((g) => g.label)).toEqual(["tier 0 · 1", "tier 1 · 2"]);
  });

  /* P3C-V2-1 (verifier, phase 3): the skeleton put every device of a no-consensus group, and every device no group
     lists, under "tier not observed" whatever that device's OWN record said, while the layout places each at its
     recorded tier (`d.tier ?? the reconciled cable-map tier`). Only a device with neither is "not observed". */
  it("a tie group's members are drawn at their OWN recorded tiers, as the layout places them", () => {
    const ds = [d("a", null), d("b", 2), d("c", 3)];
    const s = expectAgreesWithLayout(ds, [["a"], ["b", "c"]]);
    expect(s.groups.map((g) => g.label)).toEqual(["tier 2 · 1", "tier 3 · 1", "tier not observed · 1"]);
  });

  it("a device no tier group lists is drawn at its recorded tier; only one with no tier at all reads 'tier not observed'", () => {
    const ds = [d("a", 0), d("orphan", null), d("orphan2", 4)];
    const s = expectAgreesWithLayout(ds, [["a"]]);
    expect(s.groups.map((g) => [g.label, g.ids])).toEqual([
      ["tier 0 · 1", ["a"]],
      ["tier 4 · 1", ["orphan2"]],
      ["tier not observed · 1", ["orphan"]],
    ]);
  });

  it("a member with no record tier takes its group's reconciled tier; a dissenter keeps its own (the layout's rule)", () => {
    const ds = [d("x", 1), d("y", 1), d("z", 2), d("w", null), d("lone", null)];
    const s = expectAgreesWithLayout(ds, [["x", "y", "z", "w"], ["lone"]]);
    expect(s.groups.map((g) => [g.label, g.ids])).toEqual([
      ["tier 1 · 3", ["x", "y", "w"]],
      ["tier 2 · 1", ["z"]],
      ["tier not observed · 1", ["lone"]],
    ]);
  });

  it("a device listed by host (id differs), and one listed twice, read as the layout reads them", () => {
    const byHost = { ...d("h1", null), id: "dev-h1" };
    const ds = [d("p", 3), byHost, d("q", 5), d("twice", null)];
    expectAgreesWithLayout(ds, [["p", "h1", "twice"], ["q", "twice"]]);
  });

  it("a cable-map host with no device record is not drawn (the layout does not place it) and not counted", () => {
    const s = expectAgreesWithLayout([d("a", 0)], [["a", "cable-only"]]);
    expect(s.groups.flatMap((g) => g.ids)).toEqual(["a"]);
  });

  /* QC-R1-1 (verifier, phase 3.5): two records sharing a host. The layout reads devices in (order, id) order and
     lets the FIRST record carrying a host vouch for it; walking the caller's array order instead chose the other
     record, changed the group's reading, and announced "tier not observed" for devices the layout places at tier 2.
     `fabric.devices` is not in the layout's order (the compiled `order` is per tier), so this is reachable. */
  it("two records sharing a host: the record the LAYOUT reads first (order, then id) vouches for it, not array order", () => {
    const o = (id: string, host: string, tier: number | null, order: number): Device => ({ ...fabric.devices[0]!, id, host, tier, order });
    let s = expectAgreesWithLayout([o("a", "h", null, 2), o("b", "h", 2, 1), o("c", "c", null, 3)], [["h", "c"]]);
    expect(s.groups.map((g) => [g.label, g.ids])).toEqual([["tier 2 · 3", ["a", "b", "c"]]]);
    s = expectAgreesWithLayout([o("a", "h", 1, 2), o("b", "h", 2, 1), o("c", "c", null, 3)], [["h", "c"]]);
    expect(s.groups.map((g) => [g.label, g.ids])).toEqual([["tier 1 · 1", ["a"]], ["tier 2 · 2", ["b", "c"]]]);
    // Equal order: the id decides ("aa" before "zz" whatever the array says).
    expectAgreesWithLayout([o("zz", "h", null, 0), o("aa", "h", 3, 0), o("c", "c", null, 0)], [["h", "c"]]);
  });

  /* The class, not the instance: any divergence between the skeleton's reading and the layout's, over fleets with
     shared hosts, id/host spellings, per-tier `order`s, null tiers and arbitrary partitions (seeded, deterministic). */
  it("agrees with the layout on 300 seeded fleets with shared hosts, shuffled array order and per-tier orders", () => {
    let seed = 0x9e3779b9;
    const rnd = (n: number): number => {
      seed = (Math.imul(seed ^ (seed >>> 15), 0x2c1b3c6d) + 0x6d2b79f5) >>> 0;
      return seed % n;
    };
    let sharedHostCases = 0;
    for (let k = 0; k < 300; k++) {
      const n = 2 + rnd(7);
      const hosts = ["h0", "h1", "h2", "h3", "h4"].slice(0, 1 + rnd(5));
      const ds: Device[] = [];
      for (let i = 0; i < n; i++) {
        const host = rnd(3) === 0 ? `d${i}` : hosts[rnd(hosts.length)]!;
        const tier = rnd(3) === 0 ? null : rnd(4);
        ds.push({ ...fabric.devices[0]!, id: `d${i}`, host, tier, order: rnd(3) });
      }
      if (new Set(ds.map((x) => x.host)).size < ds.length) sharedHostCases++;
      const names = [...new Set([...ds.map((x) => x.host), ...ds.map((x) => x.id), "ghost"])];
      const tiers: string[][] = Array.from({ length: rnd(4) }, () => names.filter(() => rnd(3) === 0));
      expectAgreesWithLayout(ds, tiers);
    }
    // The generator actually exercises the shared-host case it exists for.
    expect(sharedHostCases).toBeGreaterThan(100);
  });

  it("on the loaded fabric: every device drawn exactly once, at the tier the layout places it", () => {
    expectAgreesWithLayout(fabric.devices, fabric.tiers);
  });

  it("on the loaded fabric with the cable map reversed and with no cable map: still the layout's reading", () => {
    expectAgreesWithLayout(fabric.devices, [...fabric.tiers].reverse());
    expectAgreesWithLayout(fabric.devices, []);
    // ...and with every record tier withheld, so the cable map alone decides (a group's null-tier members included).
    expectAgreesWithLayout(fabric.devices.map((x, i) => (i % 3 === 0 ? { ...x, tier: null } : x)), fabric.tiers);
  });
});

describe("the rendered skeleton", () => {
  function render(): HTMLElement {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(<Stage fabricVisible={false} />));
    return host;
  }

  it("draws the skeleton's labels and one node per device, and the sentence counts every device", () => {
    const host = render();
    const s = stageSkeleton(fabric.devices, fabric.tiers);
    expect([...host.querySelectorAll(".stage-skeleton__label")].map((e) => e.textContent)).toEqual(s.groups.map((g) => g.label));
    expect(host.querySelectorAll(".stage-skeleton__node")).toHaveLength(fabric.devices.length);
    const text = host.querySelector(".stage-pending__text")?.textContent ?? "";
    expect(text).toContain(`Drawing the 3-D fabric: ${fabric.devices.length} devices`);
    // The observed-tier count is the layout's own: the distinct tiers it places devices at.
    const n = new Set([...layoutTiers(fabric.devices, fabric.tiers).values()].filter((t) => t !== null)).size;
    expect(text).toContain(`across ${n} observed ${n === 1 ? "tier" : "tiers"}`);
  });

  it("names the sample digest the warm-up figure was measured on, and whether that is this snapshot", () => {
    const host = render();
    const text = host.querySelector(".stage-pending__text")?.textContent ?? "";
    expect(text).toContain("up to about a second");
    expect(text).toContain(`measured over cold loads of the reference sample ${WARMUP_MEASURED_ON}`);
    const same = fabric.meta.sourceSha256.startsWith(WARMUP_MEASURED_ON);
    if (same) expect(text).toContain("this snapshot");
    else expect(text).toContain(`not of this snapshot (${fabric.meta.sourceSha256.slice(0, 8)})`);
  });
});

describeGolden("the skeleton on the reference sample", () => {
  it("reads tier 0 to 4 in the fabric's own numbering (the AP the fabric calls Tier 0 is tier 0 here)", () => {
    expect(stageSkeleton(fabric.devices, fabric.tiers).groups.map((g) => g.label)).toEqual([
      "tier 0 · 1",
      "tier 1 · 17",
      "tier 2 · 2",
      "tier 3 · 4",
      "tier 4 · 2",
    ]);
    // The warm-up figure predates the phase-3 regeneration, so on this sample the sentence says it is not ours.
    expect(fabric.meta.sourceSha256.startsWith(WARMUP_MEASURED_ON)).toBe(false);
  });
});
