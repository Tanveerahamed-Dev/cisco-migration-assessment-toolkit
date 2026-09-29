/* tier-groups.ts — how one cable-map tier group is numbered: from what its members are RECORDED at, or not at all.
 *
 * The cable map is a PARTITION: it says which devices share a tier, never which number that tier has, and its array
 * index is an artifact of serialisation. A group's number is therefore taken from its own members' device records
 * (every member agrees -> that tier; a strict plurality -> that tier, dissenters reported by the layout; a tie or no
 * member with a recorded tier -> null, "tier not observed").
 *
 * This module is dependency-free (no three.js, no layout engine) so the loading skeleton in app/surfaces.tsx can
 * label its groups by the reconciled tier while the renderer chunk is still in flight, instead of numbering them
 * by array index ("tier 1" for a group whose members are recorded at tier 0). `layout.ts` computes the same
 * reading for its diagnostics (`cableMapGroups`); `tier-groups.test.ts` pins that the two agree on the loaded fabric
 * and on synthetic partitions, so they cannot drift while both exist.
 */
export type TierGroupBasis = "device-consensus" | "device-majority" | "no-consensus" | "no-member-tier";

export interface TierGroupReading {
  index: number;
  members: number;
  /** The tier this group vouches for; null = the evidence does not support a number. */
  tier: number | null;
  basis: TierGroupBasis;
  /** Distinct tiers found on the members' own device records, sorted. */
  memberTiers: number[];
}

export interface TierRecord {
  id: string;
  host: string;
  tier: number | null;
  /** The compiled draw order. It decides which of two records sharing a host vouches for that host (QC-R1-1). */
  order: number;
}

/**
 * The devices in the order the layout reads them: `order`, then id (layout.ts step 1). Everything here that is
 * first-wins — which record vouches for a host, which group a host takes its tier from — is resolved in THIS order,
 * never the caller's array order: `fabric.devices` is not in it (the compiled `order` restarts per tier), and when two
 * records share a host, walking the array let the other record vouch, changing the group's reading and announcing
 * "tier not observed" for devices the layout places at an observed tier (QC-R1-1).
 */
export function inLayoutOrder<T extends TierRecord>(devices: readonly T[]): T[] {
  return [...devices].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
}

export function reconcileTierGroups(unordered: readonly TierRecord[], tiers: readonly (readonly string[])[]): TierGroupReading[] {
  const devices = inLayoutOrder(unordered);
  const recordTierOfHost = new Map<string, number | null>();
  for (const d of devices) {
    recordTierOfHost.set(d.id, d.tier);
    if (!recordTierOfHost.has(d.host)) recordTierOfHost.set(d.host, d.tier);
  }
  return tiers.map((hosts, index) => {
    const counts = new Map<number, number>();
    for (const h of hosts) {
      const t = recordTierOfHost.get(h);
      if (t !== undefined && t !== null) counts.set(t, (counts.get(t) ?? 0) + 1);
    }
    const memberTiers = [...counts.keys()].sort((a, b) => a - b);
    const members = hosts.length;
    if (memberTiers.length === 0) return { index, members, tier: null, basis: "no-member-tier", memberTiers };
    if (memberTiers.length === 1) return { index, members, tier: memberTiers[0] as number, basis: "device-consensus", memberTiers };
    const ranked = [...counts].sort((a, b) => b[1] - a[1] || a[0] - b[0]);
    const top = ranked[0] as [number, number];
    const runnerUp = ranked[1] as [number, number];
    return top[1] > runnerUp[1]
      ? { index, members, tier: top[0], basis: "device-majority", memberTiers }
      : { index, members, tier: null, basis: "no-consensus", memberTiers };
  });
}

/**
 * The tier the layout places each device at: its OWN record tier, else the reconciled tier of the first cable-map
 * group that lists it (by host, then by id) and vouches for a number, else null — "tier not observed", the layout's
 * synthetic plane. This is layout.ts's `observedTierOf` rule (`d.tier ?? fromCable`), stated once here so the
 * loading skeleton can draw each device where the layout will: a group's reading is not its members' tier (a
 * dissenter keeps its own record, a member of a tie group keeps its own, a device no group lists keeps its own),
 * and labelling every member by the group's reading announced "tier not observed" for devices whose tier WAS
 * observed (P3C-V2-1). Which record vouches for a host two records share is resolved in the layout's own device
 * order (`inLayoutOrder`), never the caller's array order (QC-R1-1). surfaces.stage-pending.test.tsx holds this equal
 * to `computeLayout(...).nodes[].observedTier`, on hand-built cases and on 300 seeded fleets with shared hosts.
 */
export function placedTiers(devices: readonly TierRecord[], tiers: readonly (readonly string[])[]): Map<string, number | null> {
  const readings = reconcileTierGroups(devices, tiers);
  const cableTier = new Map<string, number>();
  readings.forEach((g) => {
    if (g.tier === null) return;
    for (const h of tiers[g.index] ?? []) if (!cableTier.has(h)) cableTier.set(h, g.tier);
  });
  return new Map(devices.map((d) => [d.id, d.tier ?? cableTier.get(d.host) ?? cableTier.get(d.id) ?? null]));
}
