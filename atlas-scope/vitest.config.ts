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
 *   - `testTimeout` at 30 s, meant as a HANG detector. This header used to justify it as "far above
 *     any measured test (slowest solo: 2 266 ms)". That premise was false (acceptance report F2,
 *     2026-09-23): on a GREEN full run two EvidencePane tests took 13.5 s and 15.7 s, and on a loaded
 *     one they hit 30 s while not hung. Measured 2026-09-23, full `npx vitest run` with the host 84-86 %
 *     busy (other agents' suites and a concurrent `review/mutation-check.mjs`): 42 of 2 041 tests took
 *     over 10 s, and several tests left on this default read 30-74 s. No quiet-host (solo) figure has
 *     been re-taken since, so this file quotes none. What holds instead is a RULE, not a number:
 *     a unit test asserts no wall-clock time (a count of the work replaces it — see the "per-keystroke
 *     work" block in `CommandPalette.test.tsx` and the primitive-operation budget in `layout.test.ts`,
 *     which replaced the last wall-clock median, O26), and a test whose unit of work is large is
 *     split one record per test (the EvidencePane per-finding tests; since 2026-09-24 also the
 *     per-flow cases of `HopList.decider-header.test.tsx` and the per-file cases of
 *     `determinism.test.ts`) rather than given a bigger limit. Expensive setup is shared and its
 *     repetition COUNTED, not timed: `tracked-sources.test.ts` builds the compilers' program once,
 *     `determinism.test.ts` parses each file once, `composite-tabstop.test.tsx` pins the presses its
 *     keyboard walk makes. Raising
 *     this number to make a loaded run green would only move the flake. The suite asserts
 *     CORRECTNESS; the latency budget is measured against the running application by
 *     `review/measure-inp.mjs` and `review/audit-e5-sweep.mjs`, which label themselves LABORATORY and
 *     gate acceptance on a quiet host.
 *   - `maxWorkers` capped below the core count, so the suite does not oversubscribe the machine it
 *     is measuring on. It cannot stop OTHER processes doing so: on the loaded run above, four test
 *     files never started because Vitest's fixed 60 s worker-start timeout expired
 *     ("[vitest-pool]: Failed to start forks worker"), which is the host, not the tests. Tests that
 *     carry their own explicit timeout at the call site (`blast.test.ts`'s 946 two-cable
 *     perturbations among them — 600 s there, and it took 319 s on that loaded run) are unaffected by
 *     this default; each such override is its owner's to justify.
 *
 * It merges the app config rather than replacing it: vitest loads `vitest.config.ts` INSTEAD of
 * `vite.config.ts` when both exist, and the React plugin, the module resolution and the chunking
 * rules all have to survive that. The `test` block below is the only thing that overrides.
 */
import { cpus } from "node:os";
import { fileURLToPath } from "node:url";
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
      /* Only a ceiling. `minWorkers: 1` stood here and did nothing: Vitest 4 removed the option, so
         it was silently ignored (TS2769 once this file was type-checked by tsconfig.config.json). */
      maxWorkers: WORKERS,
      /* Every test must make at least one assertion WHEN IT RUNS — see src/test-setup.ts. A source
         scan cannot see an expect() inside a loop over an empty list; the runner can. Absolute, so
         the guard's own proof (src/core/scripts-typecheck.test.ts) can run THIS config over a
         planted test in another root and still get this file. */
      setupFiles: [fileURLToPath(new URL("./src/test-setup.ts", import.meta.url))],
      /* No `retry`. A test that passes on the second attempt is a test whose result is noise, and
         hiding that is the defect this file was written to remove, not a workaround for it. */
      retry: 0,
    },
  }),
);
