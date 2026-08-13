import capabilityJson from "../../content/capability-catalog.json";
import coreJson from "../../content/atlas-core.json";
import deliveryJson from "../../content/delivery-governance.json";
import horizonJson from "../../content/open-horizon-register.json";
import { buildCapabilityCatalogViewModel } from "./capabilityLineage";
import { buildCoreOutcomeViewModel } from "./coreOutcomeLineage";
import { buildHorizonGapsViewModel } from "./horizonLineage";
import type {
  Capability,
  CapabilityCatalog,
  CapabilityState,
  DeliveryGovernance,
} from "./types";

export const coreOutcomeViewModel = buildCoreOutcomeViewModel(coreJson, {
  gap_ids: deliveryJson.gaps.map((gap) => gap.id),
});
export const core = coreOutcomeViewModel.core;
export const capabilityCatalogViewModel = buildCapabilityCatalogViewModel(capabilityJson, {
  domain_ids: core.domain_registry.map((domain) => domain.id),
  owner_ids: core.owners.map((owner) => owner.id),
  gap_ids: deliveryJson.gaps.map((gap) => gap.id),
  traffic_plane_ids: core.traffic_model.planes.map((plane) => plane.id),
});
export const capabilityCatalog: CapabilityCatalog = capabilityCatalogViewModel.catalog;
export const deliveryGovernance = deliveryJson as unknown as DeliveryGovernance;
export const horizonGapsViewModel = buildHorizonGapsViewModel(horizonJson);
export const horizon = horizonGapsViewModel.horizon;

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
