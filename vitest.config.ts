/**
 * vitest.config.ts — the test runner's policy, separate from the app's build config.
 *
 * WHY THIS FILE EXISTS. `npx vitest run` was red roughly half the time on this machine and green
 * the rest, from at least four different tests, none of which had regressed. No `testTimeout` was
 * configured, so the runner used its 5 000 ms default while 23 test files ran in parallel on a
 * 14-core box and several individual tests legitimately take 1.5–2.3 s in isolation. Measured:
 * `claim-lint.test.ts > scans every source file` takes 395 ms alone and timed out at 5 000 ms in a
 * full run; `PriorityQueue.test.tsx > ranks by severity` and `CommandPalette.test.tsx > opens over
 * an index that already exists` each did the same on other runs — 3 reds in 6 runs.
 *
 * A gate whose verdict depends on what else the host was doing is not a gate. It cannot tell a
 * regression from contention, and the remedy it teaches is "re-run until green", which is how a
 * real red gets waved through. The fix is not a bigger number on one test: it is to stop the
 * runner's defaults from deciding the verdict.
 *
 *   - `testTimeout` far above any measured test (slowest solo: 2 266 ms) so a timeout means a hang,
 *     not a busy scheduler. The suite asserts CORRECTNESS; the latency budget that actually matters
 *     is measured against the running application by `review/measure-inp.mjs`, which labels itself
 *     LABORATORY, and by the median-over-repeats tripwires inside `engine.test.ts`.
 *   - `maxWorkers` capped below the core count, so the suite does not oversubscribe the machine it
 *     is measuring on. The one deliberately long test (`blast.test.ts`, 946 two-cable
 *     perturbations, ~22 s) carries its own explicit timeout at the call site and is unaffected.
 *
 * It merges the app config rather than replacing it: vitest loads `vitest.config.ts` INSTEAD of
 * `vite.config.ts` when both exist, and the React plugin, the module resolution and the chunking
 * rules all have to survive that. The `test` block below is the only thing that overrides.
 */
import { cpus } from "node:os";
import { configDefaults, defineConfig, mergeConfig } from "vitest/config";

/* Extension included deliberately: Vite's native config loader warns about a bare specifier here
   and will reject it once that loader becomes the default. */
import viteConfig from "./vite.config.ts";

/* Half the reported cores, floored at 2: enough parallelism to keep the suite quick, far enough
   below saturation that one heavy file does not starve the rest into a timeout. */
const WORKERS = Math.max(2, Math.floor(cpus().length / 2));

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: true,
      include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
      /* Scratch is not suite. Review and audit agents write probe tests under `src/` — measured
         2026-09-21: `src/__audit_tmp/probe.test.ts` and later `src/__probe/probe.test.ts`, each
         picked up by `vitest run` and each writing to an env-named path. The class is the leading
         underscore on ANY path segment (the same convention `.gitignore :: review/_*` keys on),
         not a list of the two names seen so far; no authored module under `src/` uses one, and
         `source-hygiene.test.ts` asserts that stays true so this exclusion can never hide a real
         test. Vitest's own defaults are kept: an `exclude` given here REPLACES them. */
      exclude: [...configDefaults.exclude, "src/**/_*/**", "src/**/_*"],
      testTimeout: 30_000,
      hookTimeout: 30_000,
      maxWorkers: WORKERS,
      minWorkers: 1,
      /* No `retry`. A test that passes on the second attempt is a test whose result is noise, and
         hiding that is the defect this file was written to remove, not a workaround for it. */
      retry: 0,
    },
  }),
);
