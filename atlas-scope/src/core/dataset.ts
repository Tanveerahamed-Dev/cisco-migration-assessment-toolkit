/**
 * dataset.ts — THE ONE DOOR through which the four compiled documents enter the application.
 *
 * The four documents are the one compiler's output (tools/lib/compile-model.mjs `compileAll`) for one
 * snapshot: the fabric model and its three sidecars (ACL bindings, RIB evidence, producer emission).
 * Every module that renders evidence reads them from here — `core/data.ts` (the fabric and its
 * indexes), `forwarding/bindings.ts`, `forwarding/rib-completeness.ts` and `panels/producer-emission.ts`.
 *
 * Which set that is, is decided ONCE, when this module is first evaluated:
 *
 *   - a RUNTIME dataset, when one was installed before the application loaded (`dataset/slot.ts`):
 *     an AssessHub snapshot fetched from the guarded /api (the hub build, `npm run build:hub`), or a
 *     snapshot file the reader opened in the standalone build (compiled in a worker, kept in IndexedDB,
 *     restored on the reload that follows);
 *   - otherwise the BUNDLED sample (`dataset/bundled.ts`, static imports — no fetch, no spinner). The
 *     hub build carries no bundled dataset at all, so there it is a refusal, never a quiet fallback.
 *
 * Deciding at load (rather than making the documents a swappable store) keeps every consumer's
 * synchronous, module-level indexes exactly as they were: 31 modules read `core/data` and none of them
 * changes. The cost is that a different dataset means a reload, which is what opening a file does.
 */
import { BUNDLED } from "./dataset/bundled";
import { selectActiveDataset } from "./dataset/select";
import { takeInstalledDataset } from "./dataset/slot";
import { withoutPrototypes } from "./own";
import type { CompiledDataset, DatasetNotice, DatasetOrigin } from "./dataset/types";

export type { CompiledDataset, DatasetIssue, DatasetNotice, DatasetOrigin } from "./dataset/types";

const { installed, notices } = takeInstalledDataset();

const selected: { set: CompiledDataset; origin: DatasetOrigin } = selectActiveDataset(installed, BUNDLED);
/* Every name-keyed dictionary of the ONE set this page shows loses its prototype here, before any module reads it —
   the bundled sample and a runtime-opened snapshot alike — so no read shape can answer a snapshot name from
   Object.prototype (core/own.ts, THE STRUCTURAL GUARANTEE). */
const active: { set: CompiledDataset; origin: DatasetOrigin } = { set: withoutPrototypes(selected.set), origin: selected.origin };

/** The four compiled documents of the one dataset this page shows. */
export const dataset: CompiledDataset = active.set;
/** The compiled fabric model (read through `core/data.ts`, which builds the indexes). */
export const fabricDocument: CompiledDataset["fabric"] = active.set.fabric;
/** The ACL-binding sidecar (`forwarding/bindings.ts`). */
export const aclBindings: CompiledDataset["aclBindings"] = active.set.aclBindings;
/** The RIB-evidence sidecar (`forwarding/rib-completeness.ts`). */
export const ribEvidence: CompiledDataset["ribEvidence"] = active.set.ribEvidence;
/** The producer-emission sidecar (`panels/producer-emission.ts`). */
export const producerEmission: CompiledDataset["producerEmission"] = active.set.producerEmission;
/**
 * The four documents keyed by the file name the compiler writes each to (tools/lib/compile-model.mjs
 * OUTPUTS[].file) — for a reader that iterates the set by document rather than naming one (e.g. every
 * sidecar a citation may point into). src/core/dataset.test.ts pins the keys to OUTPUTS.
 */
export const documentsByFile: Readonly<Record<string, unknown>> = Object.freeze({
  "fabric.json": active.set.fabric,
  "acl-bindings.json": active.set.aclBindings,
  "rib-evidence.json": active.set.ribEvidence,
  "producer-emission.json": active.set.producerEmission,
});
/** Where this dataset came from — what the dataset banner names. */
export const datasetOrigin: DatasetOrigin = active.origin;
/** Things the reader must be told that are not the dataset itself (e.g. an opened file that could not be restored). */
export const datasetNotices: readonly DatasetNotice[] = notices;
/** True when the page shows the sample this build carries, rather than a snapshot fetched or opened at run time. */
export const isBundledSample: boolean = active.origin.kind === "bundled-sample";
