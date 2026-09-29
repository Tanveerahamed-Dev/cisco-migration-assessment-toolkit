/**
 * dataset/bundled.none.ts — what `./bundled.ts` resolves to in an AssessHub build (vite.config.ts,
 * mode "hub"): no dataset at all. The page must install the snapshot it fetched from the guarded /api
 * before the application loads; if it did not, `core/dataset.ts` refuses to start rather than show
 * anything (there is nothing it could honestly show).
 */
import type { CompiledDataset } from "./types";

export const BUNDLED: CompiledDataset | null = null;
