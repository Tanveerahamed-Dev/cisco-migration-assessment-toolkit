/**
 * dataset/store.ts — where an opened snapshot waits for the reload that shows it: IndexedDB (a compiled
 * reference-size model is ~1 MB and its source ~3 MB, far beyond what sessionStorage holds).
 *
 * One record, one key. It keeps the compiled set AND the source bytes, stamped with the identity of the
 * compiler that produced the set (`__ATLAS_COMPILER_ID__`, vite.config.ts): a set compiled by an older
 * build of the compiler is never shown as this build's — it is recompiled from the bytes instead.
 */
import type { CompiledDataset, InstalledDataset } from "./types";

export const STORED_RECORD_VERSION = 1;

export interface StoredDataset {
  version: number;
  compilerId: string;
  set: CompiledDataset;
  origin: Extract<InstalledDataset["origin"], { kind: "opened-file" }>;
  bytes: ArrayBuffer;
}

export interface DatasetStore {
  get(): Promise<unknown>;
  put(record: StoredDataset): Promise<void>;
  clear(): Promise<void>;
}

const DB = "atlas-scope";
const OBJECTS = "dataset";
const KEY = "opened";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("this browser offers no IndexedDB here (a private window, or storage blocked for this site)"));
      return;
    }
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(OBJECTS)) req.result.createObjectStore(OBJECTS);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB could not be opened"));
    req.onblocked = () => reject(new Error("IndexedDB is held open by another Atlas Scope tab; close it and retry"));
  });
}

function run<T>(mode: IDBTransactionMode, body: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(OBJECTS, mode);
        const req = body(tx.objectStore(OBJECTS));
        tx.oncomplete = () => {
          db.close();
          resolve(req.result);
        };
        tx.onerror = () => {
          db.close();
          reject(tx.error ?? req.error ?? new Error("IndexedDB transaction failed"));
        };
        tx.onabort = () => {
          db.close();
          reject(tx.error ?? new Error("IndexedDB transaction aborted (storage full?)"));
        };
      }),
  );
}

/** The browser's IndexedDB. */
export const indexedDbStore: DatasetStore = {
  get: () => run("readonly", (s) => s.get(KEY)),
  put: (record) => run("readwrite", (s) => s.put(record, KEY)).then(() => undefined),
  clear: () => run("readwrite", (s) => s.delete(KEY)).then(() => undefined),
};

/** An in-memory store with the same contract (tests, and nowhere else). */
export function memoryStore(): DatasetStore & { record: unknown } {
  const m = {
    record: undefined as unknown,
    get: async () => structuredClone(m.record),
    put: async (r: StoredDataset) => {
      m.record = structuredClone(r);
    },
    clear: async () => {
      m.record = undefined;
    },
  };
  return m;
}
