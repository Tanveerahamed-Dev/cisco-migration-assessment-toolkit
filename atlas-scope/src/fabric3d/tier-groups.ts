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
}

export function reconcileTierGroups(devices: readonly TierRecord[], tiers: readonly (readonly string[])[]): TierGroupReading[] {
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
