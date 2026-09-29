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
 * The skeleton is now `stageSkeleton(devices, tiers)`: groups labelled by the reconciled tier
 * (fabric3d/tier-groups.ts, the reading the layout publishes) or "tier not observed", one extra group for devices
 * no tier group lists, the count = every device record.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../fabric3d/Fabric3D", () => ({ default: () => <div data-testid="fabric-mounted" />, Fabric3D: () => <div /> }));

import { fabric } from "../core/data";
import type { Device } from "../core/types";
import { describeGolden } from "../test-support/golden-sample";
import { reconcileTierGroups } from "../fabric3d/tier-groups";
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

describe("stageSkeleton", () => {
  it("labels a group by its members' recorded tier, never by its array index", () => {
    const ds = [d("ap", 0), d("sw1", 1), d("sw2", 1)];
    const s = stageSkeleton(ds, [["ap"], ["sw1", "sw2"]]);
    expect(s.groups.map((g) => g.label)).toEqual(["tier 0 · 1", "tier 1 · 2"]);
  });

  it("a group whose members record no tier (or tie) reads 'tier not observed'", () => {
    const ds = [d("a", null), d("b", 2), d("c", 3)];
    const s = stageSkeleton(ds, [["a"], ["b", "c"]]);
    expect(s.groups.map((g) => g.label)).toEqual(["tier not observed · 1", "tier not observed · 2"]);
  });

  it("a device no tier group lists is drawn in its own 'tier not observed' group and counted", () => {
    const ds = [d("a", 0), d("orphan", null), d("orphan2", 4)];
    const s = stageSkeleton(ds, [["a"]]);
    expect(s.placed).toBe(3);
    expect(s.groups.map((g) => [g.label, g.ids])).toEqual([
      ["tier 0 · 1", ["a"]],
      ["tier not observed · 2", ["orphan", "orphan2"]],
    ]);
  });

  it("a cable-map host with no device record is not drawn (the layout does not place it) and not counted", () => {
    const s = stageSkeleton([d("a", 0)], [["a", "cable-only"]]);
    expect(s.placed).toBe(1);
    expect(s.groups.flatMap((g) => g.ids)).toEqual(["a"]);
  });

  it("on the loaded fabric: every device drawn exactly once, labels from the reconciler", () => {
    const s = stageSkeleton(fabric.devices, fabric.tiers);
    expect(s.placed).toBe(fabric.devices.length);
    const drawn = s.groups.flatMap((g) => g.ids);
    expect(drawn.slice().sort()).toEqual(fabric.devices.map((x) => x.id).sort());
    const readings = reconcileTierGroups(fabric.devices, fabric.tiers);
    for (const g of s.groups.filter((x) => x.index !== null)) {
      const t = readings[g.index!]!.tier;
      expect(g.label.startsWith(t === null ? "tier not observed · " : `tier ${t} · `), g.label).toBe(true);
    }
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
