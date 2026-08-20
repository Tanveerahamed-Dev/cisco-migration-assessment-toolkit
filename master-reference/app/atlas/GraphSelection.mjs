/**
 * Pure, executable community-selection boundary for GraphExplorer.
 *
 * Every non-ready result deliberately carries empty records. This prevents a
 * rejected, null, invalid, or mismatched request from inheriting the previous
 * community's nodes or edges while the URL names a different partition.
 */

function abstained(requestedCommunity, reason, message) {
  return {
    state: "abstained",
    requestedCommunity,
    loadedCommunity: null,
    nodes: [],
    edges: [],
    reason,
    message,
  };
}

export function beginCommunitySelection(requestedCommunity, availableCommunities) {
  const requested = String(requestedCommunity);
  const available = new Set([...availableCommunities].map(String));
  if (!available.has(requested)) {
    return abstained(
      requested,
      "invalid_selection",
      `Community ${requested} is not in the exact-source graph denominator. No substitute partition was loaded.`,
    );
  }
  return {
    state: "loading",
    requestedCommunity: requested,
    loadedCommunity: null,
    nodes: [],
    edges: [],
    reason: null,
    message: `Loading community ${requested} from its bound projection shards.`,
  };
}

export function resolveCommunitySelection(requestedCommunity, payload) {
  const requested = String(requestedCommunity);
  if (payload === null || payload === undefined) {
    return abstained(
      requested,
      "null_payload",
      `Community ${requested} has no bound projection payload. Previous graph records were cleared.`,
    );
  }
  if (
    typeof payload !== "object" ||
    Array.isArray(payload) ||
    String(payload.community) !== requested ||
    !Array.isArray(payload.nodes) ||
    !Array.isArray(payload.edges)
  ) {
    return abstained(
      requested,
      "mismatched_or_invalid_payload",
      `Community ${requested} returned an invalid or differently bound payload. No graph records were retained.`,
    );
  }
  return {
    state: "ready",
    requestedCommunity: requested,
    loadedCommunity: requested,
    nodes: [...payload.nodes],
    edges: [...payload.edges],
    reason: null,
    message: `Community ${requested} is bound to the selected projection payload.`,
  };
}

export function rejectCommunitySelection(requestedCommunity) {
  const requested = String(requestedCommunity);
  return abstained(
    requested,
    "load_rejected",
    `Community ${requested} could not be loaded or verified. Previous graph records were cleared.`,
  );
}
