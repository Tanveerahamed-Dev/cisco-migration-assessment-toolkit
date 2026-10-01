/* golden-sample.ts — the ONE place a test may bind itself to what the tracked reference sample contains.
 *
 * The suite has two tiers.
 *   - INVARIANT tests hold for ANY compiled fabric. The rename leg (an isomorphic rename of the sample) and the
 *     golden-snapshot leg (the engine's 7-device golden) run them against other datasets; a failure there is a
 *     hard-coded assumption about one snapshot.
 *   - GOLDEN tests pin numbers, names and geometry that are true only of the tracked engine sample
 *     (webapp/sample_data/sample_fleet.snapshot.json at GOLDEN_SHA). They run only when the loaded dataset IS that
 *     sample, and they read their expectations from here or from one golden module per area — never scattered
 *     literals.
 *
 * FAIL CLOSED (the "gate whose success path never executed" shape): if the loaded fabric names the tracked sample
 * as its source but its digest is not GOLDEN_SHA, importing this module THROWS. The sample was regenerated and every
 * golden expectation must be re-derived — a silent skip on the reference snapshot would turn the whole golden tier
 * into a gate that never runs. A skip is legal only for a dataset that is NOT the tracked sample, and then
 * describeGolden names every skipped block so the rename/golden legs report exactly what did not run.
 */
import { describe } from "vitest";
import { fabric } from "../core/data";

export const SAMPLE_SOURCE = "webapp/sample_data/sample_fleet.snapshot.json";
/** sourceSha256 (LF-normalised) of the tracked sample the golden tier was derived from. */
export const GOLDEN_SHA = "3934281bb44cb7a1154c00d088c7c7805c569823ae8fc4099c1eba7adeee1e54";

export const isGoldenSample = (): boolean => fabric.meta.sourceSha256 === GOLDEN_SHA;

if (fabric.meta.source === SAMPLE_SOURCE && fabric.meta.sourceSha256 !== GOLDEN_SHA) {
  throw new Error(
    `golden-sample: the tracked sample changed (compiled sourceSha256 ${fabric.meta.sourceSha256}, golden tier derived ` +
      `from ${GOLDEN_SHA}). Re-derive every golden expectation from the regenerated data and update GOLDEN_SHA; ` +
      `never skip the golden tier on the reference snapshot.`,
  );
}

/** A describe block that runs only on the tracked reference sample; on any other dataset it is skipped BY NAME. */
export function describeGolden(name: string, fn: () => void): void {
  if (isGoldenSample()) describe(`[golden] ${name}`, fn);
  else describe.skip(`[golden tier: not the reference sample] ${name}`, fn);
}
