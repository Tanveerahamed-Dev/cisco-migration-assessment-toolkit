import capabilityJson from "../../content/capability-catalog.json";
import coreJson from "../../content/atlas-core.json";
import deliveryJson from "../../content/delivery-governance.json";
import horizonJson from "../../content/open-horizon-register.json";
import type {
  Capability,
  CapabilityCatalog,
  CapabilityState,
  CoreModel,
  DeliveryGovernance,
  HorizonModel,
} from "./types";

export const core = coreJson as unknown as CoreModel;
export const capabilityCatalog = capabilityJson as unknown as CapabilityCatalog;
export const deliveryGovernance = deliveryJson as unknown as DeliveryGovernance;
export const horizon = horizonJson as unknown as HorizonModel;

export const capabilities = capabilityCatalog.domains.flatMap((domain) =>
  domain.entries.map((entry) => ({ ...entry, domain_id: domain.id })),
);

export const capabilityCounts = capabilities.reduce<Record<CapabilityState, number>>(
  (counts, entry) => {
    counts[entry.state] += 1;
    return counts;
  },
  { current: 0, partial: 0, missing: 0, gated: 0, excluded: 0, unknown: 0 },
);

export const ownerById = new Map(core.owners.map((owner) => [owner.id, owner]));
export const gapById = new Map(deliveryGovernance.gaps.map((gap) => [gap.id, gap]));
export const capabilityById = new Map<string, Capability>(
  capabilities.map((capability) => [capability.id, capability]),
);

export function titleForDomain(id: string): string {
  return core.domain_registry.find((domain) => domain.id === id)?.title ?? id;
}

export function shortId(id: string): string {
  return id.replace(/^(cap|gap|owner|invariant|lab|decision|opportunity)\./, "");
}
