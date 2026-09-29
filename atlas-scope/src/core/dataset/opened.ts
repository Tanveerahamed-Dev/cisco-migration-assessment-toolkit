/**
 * dataset/opened.ts — "Open a snapshot" in the standalone build, and the way back to the sample.
 *
 *   open:    File -> bytes -> worker (validate + the one compiler) -> IndexedDB -> marker -> reload.
 *   boot:    marker present -> read IndexedDB -> check the record -> install it (dataset/slot.ts) before
 *            the application loads. A record the check refuses is removed, and the reader is TOLD the
 *            snapshot could not be restored — the page never shows the sample as if it were their file.
 *   return:  clear IndexedDB and the marker -> reload -> the bundled sample.
 *
 * The file never leaves the browser: it is read, compiled and stored locally, and nothing is uploaded.
 */
import type { CompileFn } from "./compile-client";
import { clearOpenedMarker, setOpenedMarker } from "./marker";
import { incoherence } from "./slot";
import { STORED_RECORD_VERSION, type DatasetStore, type StoredDataset } from "./store";
import type { DatasetIssue, DatasetNotice, InstalledDataset } from "./types";

/** The largest file this reader opens (bytes). The validator's own ceiling is far higher; a browser tab is not. */
export const MAX_OPEN_BYTES = 64 * 1024 * 1024;

export interface OpenDeps {
  compile: CompileFn;
  store: DatasetStore;
  compilerId: string;
  reload: () => void;
  setMarker?: () => boolean;
}

export type OpenResult = { ok: true } | { ok: false; errors: DatasetIssue[] };

type FileLike = Pick<File, "name" | "size" | "arrayBuffer">;

/** Open `file`: compile it, keep it, and reload into it. Resolves with the refusal when it cannot be shown. */
export async function openSnapshotFile(file: FileLike, deps: OpenDeps): Promise<OpenResult> {
  const fail = (code: string, message: string): OpenResult => ({ ok: false, errors: [{ code, message }] });
  if (file.size > MAX_OPEN_BYTES) {
    return fail("E_TOO_LARGE", `${file.name} is ${file.size} bytes; this reader opens snapshots up to ${MAX_OPEN_BYTES} bytes.`);
  }
  let bytes: ArrayBuffer;
  try {
    bytes = await file.arrayBuffer();
  } catch (e) {
    return fail("E_FILE_READ", `${file.name} could not be read (${e instanceof Error ? e.message : String(e)}).`);
  }
  const keep = bytes.slice(0);
  const outcome = await deps.compile({ bytes, label: { source: file.name, sourceOrigin: "external-file" }, expect: null });
  if (!outcome.ok) return { ok: false, errors: outcome.errors };
  const record: StoredDataset = {
    version: STORED_RECORD_VERSION,
    compilerId: deps.compilerId,
    set: outcome.set,
    origin: {
      kind: "opened-file",
      fileName: file.name,
      fileBytes: keep.byteLength,
      warnings: outcome.warnings,
    },
    bytes: keep,
  };
  try {
    await deps.store.put(record);
  } catch (e) {
    return fail(
      "E_STORE_UNAVAILABLE",
      `the compiled snapshot could not be kept in this browser's storage (${e instanceof Error ? e.message : String(e)}), so it cannot be shown after the reload. Allow site storage for this page, or free some space, and open it again.`,
    );
  }
  if (!(deps.setMarker ?? setOpenedMarker)()) {
    await deps.store.clear().catch(() => undefined);
    return fail("E_STORE_UNAVAILABLE", "this browser blocks site storage for this page, so an opened snapshot cannot survive the reload that shows it.");
  }
  deps.reload();
  return { ok: true };
}

export interface RestoreDeps {
  compile: CompileFn;
  store: DatasetStore;
  compilerId: string;
  clearMarker?: () => void;
}

export type RestoreResult = { ok: true; dataset: InstalledDataset; recompiled: boolean } | { ok: false; notice: DatasetNotice };

/**
 * The opened dataset kept in `store`, checked; recompiled from its bytes when another compiler build
 * produced it. On any refusal the record and marker are removed (so the next load is the plain sample)
 * and the notice says what happened.
 */
export async function restoreOpenedDataset(deps: RestoreDeps): Promise<RestoreResult> {
  const forget = async (code: string, why: string): Promise<RestoreResult> => {
    await deps.store.clear().catch(() => undefined);
    (deps.clearMarker ?? clearOpenedMarker)();
    return {
      ok: false,
      notice: { code, message: `The snapshot you opened earlier could not be restored: ${why}. This is the bundled sample fleet, not your file — open it again to see it.` },
    };
  };
  let rec: unknown;
  try {
    rec = await deps.store.get();
  } catch (e) {
    return forget("E_STORE_UNAVAILABLE", `this browser's storage could not be read (${e instanceof Error ? e.message : String(e)})`);
  }
  const r = rec as Partial<StoredDataset> | undefined | null;
  if (r === undefined || r === null || typeof r !== "object") return forget("E_STORE_EMPTY", "nothing was kept in this browser's storage (it may have been cleared)");
  if (r.version !== STORED_RECORD_VERSION) return forget("E_STORE_VERSION", "it was kept in a format this build does not read");
  const origin = r.origin;
  if (!origin || origin.kind !== "opened-file" || typeof origin.fileName !== "string" || !(r.bytes instanceof ArrayBuffer)) {
    return forget("E_STORE_CORRUPT", "the kept record is incomplete");
  }
  if (r.compilerId === deps.compilerId && r.set !== undefined) {
    const candidate: InstalledDataset = { set: r.set, origin };
    const why = incoherence(candidate);
    if (why === null) return { ok: true, dataset: candidate, recompiled: false };
  }
  /* Another compiler build (or an incoherent set): compile the kept bytes again with THIS one. */
  const outcome = await deps.compile({ bytes: r.bytes.slice(0), label: { source: origin.fileName, sourceOrigin: "external-file" }, expect: null });
  if (!outcome.ok) return forget(outcome.errors[0]?.code ?? "E_COMPILE", `this build's compiler refuses it — ${outcome.errors[0]?.message ?? "no reason given"}`);
  const refreshed: InstalledDataset = { set: outcome.set, origin: { ...origin, warnings: outcome.warnings } };
  await deps.store.put({ version: STORED_RECORD_VERSION, compilerId: deps.compilerId, set: outcome.set, origin: refreshed.origin as StoredDataset["origin"], bytes: r.bytes }).catch(() => undefined);
  return { ok: true, dataset: refreshed, recompiled: true };
}

/** Forget the opened snapshot and reload into the bundled sample. */
export async function returnToSample(deps: { store: DatasetStore; reload: () => void; clearMarker?: () => void }): Promise<void> {
  (deps.clearMarker ?? clearOpenedMarker)();
  await deps.store.clear().catch(() => undefined);
  deps.reload();
}
