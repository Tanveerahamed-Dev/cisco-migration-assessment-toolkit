/**
 * Pure capability-matrix selection contract.
 *
 * CapabilityExplorer and the content ratchet import the same functions. This
 * keeps filtering and URL state executable without a browser and prevents the
 * catalog from claiming UI behavior that exists only in prose.
 */

export const CAPABILITY_STATES = Object.freeze([
  "current",
  "partial",
  "missing",
  "gated",
  "excluded",
  "unknown",
]);

export function flattenCapabilityEntries(catalog) {
  if (!catalog || !Array.isArray(catalog.domains)) return [];
  return catalog.domains.flatMap((item) =>
    Array.isArray(item.entries)
      ? item.entries.map((entry) => ({ ...entry, domain: item.id }))
      : [],
  );
}

export function filterCapabilityEntries(
  entries,
  { domain = "all", state = "all", query = "" } = {},
) {
  const needle = String(query).trim().toLowerCase();
  return entries.filter((entry) => {
    if (domain !== "all" && entry.domain !== domain) return false;
    if (state !== "all" && entry.state !== state) return false;
    if (!needle) return true;
    return [entry.id, entry.title, entry.current_scope, entry.domain]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });
}

export function capabilitySelectionUrl({ domain = "all", state = "all", query = "" } = {}) {
  const params = new URLSearchParams();
  if (domain !== "all") params.set("domain", domain);
  if (state !== "all") params.set("state", state);
  if (String(query).trim()) params.set("q", String(query).trim());
  return params.size ? `/capabilities?${params}` : "/capabilities";
}
