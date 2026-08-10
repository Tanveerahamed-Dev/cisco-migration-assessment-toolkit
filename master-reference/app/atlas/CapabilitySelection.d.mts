export type CapabilityFilterable = {
  id: string;
  title: string;
  current_scope: string;
  state: string;
};

export type CapabilityRow<T extends CapabilityFilterable = CapabilityFilterable> = T & {
  domain: string;
};

export type CapabilitySelection = {
  domain?: string;
  state?: string;
  query?: string;
};

export const CAPABILITY_STATES: readonly [
  "current",
  "partial",
  "missing",
  "gated",
  "excluded",
  "unknown",
];

export function flattenCapabilityEntries<T extends CapabilityFilterable>(catalog: {
  domains: Array<{ id: string; entries: T[] }>;
}): Array<CapabilityRow<T>>;

export function filterCapabilityEntries<T extends CapabilityFilterable>(
  entries: Array<CapabilityRow<T>>,
  selection?: CapabilitySelection,
): Array<CapabilityRow<T>>;

export function capabilitySelectionUrl(selection?: CapabilitySelection): string;
