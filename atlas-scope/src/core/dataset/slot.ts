/**
 * dataset/slot.ts — the hand-off between the boot entry and the application: where a runtime dataset
 * (an AssessHub snapshot, or a file the reader opened) is installed BEFORE the application loads.
 *
 * It is deliberately tiny and imports nothing at runtime: `src/main.tsx` (the entry chunk, acceptance
 * E5/F4) reaches it, so anything here is paid on every cold load.
 *
 * THE ORDER IS THE CONTRACT. Every surface reads module-level indexes that `core/data.ts` builds once,
 * at import. So a dataset must be installed before `core/dataset.ts` is first evaluated; installing one
 * after would leave the application rendering the dataset it already read while claiming another. The
 * first read therefore SEALS the slot, and a later install throws instead of being silently ignored.
 */
import type { DatasetNotice, InstalledDataset } from "./types";

let installed: InstalledDataset | null = null;
let sealed = false;
const notices: DatasetNotice[] = [];

/**
 * Install `dataset` as the one the application will read. Throws when the application has already read
 * its dataset (the install would be invisible), or when one is already installed (two sources for one
 * page). The set is checked for coherence here, the one choke point every runtime source passes through.
 */
export function installDataset(dataset: InstalledDataset): void {
  if (sealed) {
    throw new Error(
      "E_DATASET_SEALED: a dataset was installed after the application had already read one. The application builds its " +
        "indexes once, at load, so this install would not be shown; install before importing the application.",
    );
  }
  if (installed !== null) throw new Error("E_DATASET_TWICE: a dataset is already installed for this page; one page shows one dataset.");
  const why = incoherence(dataset);
  if (why !== null) throw new Error(`E_DATASET_INCOHERENT: the installed set is refused — ${why}`);
  installed = dataset;
}

/** Record something the reader must be told (shown by the dataset banner). Allowed until the first read. */
export function noteDatasetNotice(notice: DatasetNotice): void {
  if (sealed) throw new Error("E_DATASET_SEALED: a notice was recorded after the application read its dataset; it would never be shown.");
  notices.push(notice);
}

/** The application's one read. Seals the slot. */
export function takeInstalledDataset(): { installed: InstalledDataset | null; notices: readonly DatasetNotice[] } {
  sealed = true;
  return { installed, notices: [...notices] };
}

const BINDING_KEYS = ["source", "sourceOrigin", "sourceDigestForm", "sourceSha256", "sourceBytes", "sourceExactSha256", "sourceGitBlob"] as const;
const DOCUMENTS = ["fabric", "aclBindings", "ribEvidence", "producerEmission"] as const;

/**
 * Why `dataset` cannot be one compile of one snapshot, or null. The four documents must all be present
 * and all bound to the same source (every binding key equal): a mixed set would render ACL bindings or
 * routing completeness from other bytes than the fabric. This restates the rule of `sameSourceBinding`
 * (core/types.ts) without importing it, because this module is in the entry chunk; the mapping is pinned
 * by src/core/dataset.test.ts against SOURCE_BINDING_KEYS.
 */
export function incoherence(dataset: InstalledDataset): string | null {
  const set = dataset.set as unknown as Record<string, { meta?: Record<string, unknown> } | undefined> | null;
  if (set === null || typeof set !== "object") return "it is not a compiled set";
  const fabricMeta = set.fabric?.meta;
  if (fabricMeta === undefined || fabricMeta === null || typeof fabricMeta !== "object") return "the fabric document carries no binding";
  for (const doc of DOCUMENTS) {
    const meta = set[doc]?.meta;
    if (meta === undefined || meta === null || typeof meta !== "object") return `the ${doc} document is missing or carries no binding`;
    for (const k of BINDING_KEYS) {
      if (meta[k] === undefined || meta[k] !== fabricMeta[k]) return `the ${doc} document is bound to other bytes than the fabric (${k} differs)`;
    }
  }
  return null;
}

/** Test seam: forget everything. Only a test that re-imports the application after it may call this. */
export function resetDatasetSlotForTests(): void {
  installed = null;
  sealed = false;
  notices.length = 0;
}

export const SLOT_BINDING_KEYS: readonly string[] = BINDING_KEYS;
