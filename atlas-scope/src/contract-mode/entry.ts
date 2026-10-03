import { isEmbedNonce, PROJECTION_NONCE_PARAM } from "../../../webapp/frontend/src/projectionEmbed";

export type ContractLocation = Readonly<{ pathname: string; search: string; hash: string; origin: string }>;
export type ContractMode = Readonly<{ selected: false }> | Readonly<{ selected: true; valid: false }> |
  Readonly<{ selected: true; valid: true; snapshotId: number; nonce: string; origin: string }>;

/** A malformed or unsupported attempted contract URL never falls through to the normal dataset. */
export function readContractMode(location: ContractLocation, mode: string): ContractMode {
  const params = new URLSearchParams(location.search);
  if (!params.has("engine_projection") && !params.has(PROJECTION_NONCE_PARAM)) return { selected: false };
  const invalid = { selected: true, valid: false } as const;
  try {
    const origin = new URL(location.origin);
    const match = /^\/scope\/snapshots\/(-?(?:0|[1-9][0-9]*))\/$/.exec(location.pathname);
    const nonce = params.get(PROJECTION_NONCE_PARAM);
    if (mode !== "hub" || origin.origin !== location.origin || !["http:", "https:"].includes(origin.protocol) ||
      location.hash !== "" || match === null || [...params].length !== 2 || params.getAll("engine_projection").length !== 1 ||
      params.get("engine_projection") !== "1" || params.getAll(PROJECTION_NONCE_PARAM).length !== 1 || !isEmbedNonce(nonce)) return invalid;
    const snapshotId = Number(match[1]);
    if (!Number.isSafeInteger(snapshotId) || String(snapshotId) !== match[1]) return invalid;
    return { selected: true, valid: true, snapshotId, nonce, origin: origin.origin };
  } catch { return invalid; }
}
