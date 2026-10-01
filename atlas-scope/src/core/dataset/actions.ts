/**
 * dataset/actions.ts — the side effects the dataset controls perform (compile in a worker, keep in
 * IndexedDB, reload the page), gathered in one object so a test can replace them without a browser.
 * The application never reassigns them.
 */
import { compileInWorker, type CompileFn } from "./compile-client";
import { indexedDbStore, type DatasetStore } from "./store";

export const datasetActions: { compile: CompileFn; store: DatasetStore; reload: () => void; compilerId: string } = {
  compile: compileInWorker,
  store: indexedDbStore,
  reload: () => window.location.reload(),
  compilerId: __ATLAS_COMPILER_ID__,
};
