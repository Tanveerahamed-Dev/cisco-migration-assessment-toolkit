/**
 * dataset/select.ts — which dataset the page shows, decided once: the one installed at run time, else
 * the build's bundled sample, else a refusal. Pure, so the refusal (an AssessHub build, which carries no
 * bundled dataset, reached with nothing installed) is tested without mocking a module.
 */
import type { CompiledDataset, DatasetOrigin, InstalledDataset } from "./types";

export function selectActiveDataset(
  installed: InstalledDataset | null,
  bundled: CompiledDataset | null,
): { set: CompiledDataset; origin: DatasetOrigin } {
  if (installed !== null) return installed;
  if (bundled !== null) return { set: bundled, origin: { kind: "bundled-sample" } };
  throw new Error(
    "E_NO_DATASET: this build carries no bundled dataset (an AssessHub build) and none was installed before the " +
      "application loaded. Atlas Scope shows nothing rather than an unnamed dataset.",
  );
}
