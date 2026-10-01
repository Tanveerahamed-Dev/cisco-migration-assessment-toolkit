/**
 * dataset/bundled.ts — the dataset a STANDALONE build carries: the four compiled documents of the
 * tracked engine sample, imported statically so the sample is on screen at first paint with no fetch
 * and no spinner (acceptance E budgets).
 *
 * This is the ONE module that may import a compiled document (src/core/dataset.test.ts enforces it,
 * derived from the compiler's own OUTPUTS). Everything else reads `core/dataset.ts`.
 *
 * In an AssessHub build (`vite build --mode hub`) vite.config.ts resolves this module to
 * `./bundled.none.ts` instead, so NO compiled dataset is in that output at all: AssessHub serves /scope
 * outside its API guard, and a compiled model there would be readable by any page on the web.
 */
import fabric from "../../data/fabric.json";
import aclBindings from "../../forwarding/acl-bindings.json";
import ribEvidence from "../../forwarding/rib-evidence.json";
import producerEmission from "../../panels/producer-emission.json";
import type { CompiledDataset } from "./types";

export const BUNDLED: CompiledDataset | null = {
  fabric: fabric as unknown as CompiledDataset["fabric"],
  aclBindings: aclBindings as unknown as CompiledDataset["aclBindings"],
  ribEvidence: ribEvidence as unknown as CompiledDataset["ribEvidence"],
  producerEmission: producerEmission as unknown as CompiledDataset["producerEmission"],
};
