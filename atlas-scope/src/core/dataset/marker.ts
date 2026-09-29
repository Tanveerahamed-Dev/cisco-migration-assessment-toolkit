/**
 * dataset/marker.ts — the one synchronous hint the boot entry reads: "the reader opened a snapshot
 * file; restore it before the application loads". It is a localStorage flag, not the dataset (that
 * lives in IndexedDB, dataset/store.ts), so a cold load of the sample pays one localStorage read and
 * never opens a database. Every access is guarded: storage can be blocked, full or absent, and then the
 * page shows the bundled sample — and says so only if a restore was actually attempted.
 */
export const OPENED_MARKER_KEY = "atlas-scope.dataset";
export const OPENED_MARKER_VALUE = "opened-file";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const storage = (): StorageLike | null => {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
};

export function hasOpenedMarker(s: StorageLike | null = storage()): boolean {
  try {
    return s?.getItem(OPENED_MARKER_KEY) === OPENED_MARKER_VALUE;
  } catch {
    return false;
  }
}

/** Returns false when the marker could not be written (the caller must then not claim the file will reopen). */
export function setOpenedMarker(s: StorageLike | null = storage()): boolean {
  try {
    if (s === null) return false;
    s.setItem(OPENED_MARKER_KEY, OPENED_MARKER_VALUE);
    return s.getItem(OPENED_MARKER_KEY) === OPENED_MARKER_VALUE;
  } catch {
    return false;
  }
}

export function clearOpenedMarker(s: StorageLike | null = storage()): void {
  try {
    s?.removeItem(OPENED_MARKER_KEY);
  } catch {
    /* nothing to clear */
  }
}
