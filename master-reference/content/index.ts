import atlasCore from "./atlas-core.json";
import capabilityCatalog from "./capability-catalog.json";
import deliveryGovernance from "./delivery-governance.json";
import openHorizonRegister from "./open-horizon-register.json";

export type AtlasState =
  | "current"
  | "partial"
  | "missing"
  | "gated"
  | "excluded"
  | "unknown";

export { atlasCore, capabilityCatalog, deliveryGovernance, openHorizonRegister };

export const capabilityEntries = capabilityCatalog.domains.flatMap((domain) =>
  domain.entries.map((entry) => ({ ...entry, domain_ref: domain.id })),
);

export const capabilityById = new Map(
  capabilityEntries.map((entry) => [entry.id, entry]),
);

export const gapById = new Map(
  deliveryGovernance.gaps.map((gap) => [gap.id, gap]),
);

export const ownerById = new Map(
  atlasCore.owners.map((owner) => [owner.id, owner]),
);

export const horizonById = new Map(
  openHorizonRegister.signals.map((entry) => [entry.id, entry]),
);

export function capabilitiesForGap(gapId: string) {
  return capabilityEntries.filter((entry) =>
    "gap_refs" in entry && entry.gap_refs?.includes(gapId),
  );
}

export function capabilitiesForDomain(domainRef: string) {
  return capabilityEntries.filter((entry) => entry.domain_ref === domainRef);
}

export function stateCounts() {
  return capabilityEntries.reduce<Record<AtlasState, number>>(
    (counts, entry) => {
      counts[entry.state as AtlasState] += 1;
      return counts;
    },
    { current: 0, partial: 0, missing: 0, gated: 0, excluded: 0, unknown: 0 },
  );
}
