/**
 * dataset/boot.ts — install the page's runtime dataset before the application loads. Imported
 * DYNAMICALLY by src/main.tsx, and only when there is one to install (every AssessHub load; a standalone
 * load whose reader opened a file), so a cold load of the bundled sample never fetches this chunk.
 */
import { compileInWorker, type CompileFn } from "./compile-client";
import { loadFromAssessHub } from "./hub";
import { restoreOpenedDataset } from "./opened";
import { installDataset, noteDatasetNotice } from "./slot";
import { indexedDbStore, type DatasetStore } from "./store";
import type { DatasetIssue } from "./types";

/** Why the page cannot show its dataset. main.tsx renders it in place of the application. */
export class DatasetBootError extends Error {
  constructor(
    readonly title: string,
    readonly issues: DatasetIssue[],
  ) {
    super(`${title}: ${issues.map((i) => `[${i.code}] ${i.message}`).join(" ")}`);
    this.name = "DatasetBootError";
  }
}

export interface BootEnv {
  target: "hub" | "standalone";
  pathname: string;
  base: string;
  secure: boolean;
  fetch: typeof fetch;
  compile?: CompileFn;
  store?: DatasetStore;
  compilerId: string;
  onProgress?: (message: string) => void;
}

/**
 * Hub: fetch + verify + compile + install, or throw DatasetBootError (nothing else is shown).
 * Standalone: restore the opened file + install; when it cannot be restored the SAMPLE is shown, with a
 * notice saying so — the page is still useful, and it says whose data it is.
 */
export async function prepareDataset(env: BootEnv): Promise<void> {
  const compile = env.compile ?? compileInWorker;
  if (env.target === "hub") {
    const r = await loadFromAssessHub({ pathname: env.pathname, base: env.base, fetch: env.fetch, secure: env.secure, compile, ...(env.onProgress ? { onProgress: env.onProgress } : {}) });
    if (!r.ok) throw new DatasetBootError(r.snapshotId === null ? "Atlas Scope has no snapshot to open" : `Atlas Scope could not open AssessHub snapshot ${r.snapshotId}`, r.errors);
    installDataset(r.dataset);
    return;
  }
  env.onProgress?.("Loading Atlas Scope — restoring the snapshot you opened.");
  const r = await restoreOpenedDataset({ compile, store: env.store ?? indexedDbStore, compilerId: env.compilerId });
  if (r.ok) installDataset(r.dataset);
  else noteDatasetNotice(r.notice);
}
