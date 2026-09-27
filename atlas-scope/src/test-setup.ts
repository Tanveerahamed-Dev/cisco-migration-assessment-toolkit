/**
 * test-setup.ts — every test the runner executes must make at least one assertion AT RUN TIME.
 *
 * WHY (independent refuter, wave 3, acceptance F2). `src/core/source-hygiene.test.ts` already scans
 * the source for a test whose body contains no `expect(` — and three tests with a textual `expect`
 * still made ZERO assertions when run (`motion-inventory.test.ts`, `compiler-fidelity.test.ts`,
 * `engine.test.ts`), because every `expect` sat inside a loop or branch the real data never
 * entered: `for (const k of keyframes) expect(...)` over an empty list passes having proved nothing.
 * A per-test probe of `expect.getState().assertionCalls` found them; ~25 of 161 candidates had been
 * checked by hand. A source scan cannot see which branch runs. The runner can, so the class is
 * closed here, once, for every test, instead of in a list of the ones someone happened to read.
 *
 * THE RULE. After each test, `assertionCalls` must be at least 1. A test whose body legitimately has
 * nothing to compare still has an assertion to make — the absence of a throw is
 * `expect(() => f()).not.toThrow()` — so there is no silent way out. The one explicit opt-out is
 * Vitest's own `expect.assertions(0)`, which Vitest itself then ENFORCES (the test fails if it makes
 * any assertion at all); each use is announced on stderr by name, and the guard's own test (in
 * `src/core/scripts-typecheck.test.ts`, with the other runner gates) requires every use in `src/`
 * to carry an `assertion-guard:` justification comment on the line above it.
 *
 * WHAT IT DOES NOT DO. It counts assertions; it cannot judge them. `expect(true).toBe(true)` passes.
 * A test that already FAILED is left to its own error rather than given a second one.
 *
 * Installed through `setupFiles` in vitest.config.ts. The guard proves it is installed: it sets a
 * global marker that the guard's own test reads, and that test also runs a planted zero-assertion
 * test through a child Vitest with the real config and requires it to FAIL, naming the test.
 *
 * ── THE ACT-SCOPE CANARY (acceptance F2, the load cascade) ─────────────────────────────────────
 *
 * WHY. On a run at 85-100 % host CPU one 37 s timeout was followed by 277 failures that each blamed
 * themselves ("the seeded flow had not been traced after 50 flush turns"). Vitest does not stop a
 * timed-out body; the abandoned body's async act() scope closed out of order with the next case's,
 * React's process-global act depth stuck at 1, and nothing committed for the rest of the file. The
 * leak was a class — any async act() scope that outlives its test — so it is closed here, for every
 * test, rather than in the one file where it was seen:
 *
 *   - every test (hooks and body) runs inside its own chain (`runInTestChain`), so the helper in
 *     `src/test-support/act-turns.ts` can stop an abandoned body at its next act() instead of letting
 *     it open a scope inside a later test;
 *   - after each test, every scope the helper opened and every chain a test `track()`ed is settled
 *     before anything else looks at React;
 *   - then the canary reads React's act queue. Left open, it fails the test that left it, with a
 *     message naming the cause instead of the symptom a later test would report. It fails CLOSED:
 *     this file refuses to load if the React internals it reads are missing or no longer behave as
 *     the canary assumes (proved against the running React below, before any test).
 *
 * WHAT IT DOES NOT DO. It does not make a wall-clock verdict load-proof: a case can still exceed the
 * hang detector on a saturated host. What it guarantees is that such a timeout is ONE red that names
 * itself. Proved by the planted child runs in `src/core/scripts-typecheck.test.ts`.
 */
import { afterEach, aroundEach, expect } from "vitest";

import { assertActScopeObservable, openActScope, runInTestChain, settleActTurns } from "./test-support/act-turns";

/* Read by the guard's own test to prove this file ran in the worker executing it. */
(globalThis as Record<symbol, unknown>)[Symbol.for("atlas-scope.assertion-guard.installed")] = true;

/* The message prefix the planted-test proof looks for. */
const ASSERTION_GUARD_PREFIX = "[assertion guard]";

afterEach((ctx) => {
  const task = ctx.task;
  const state = expect.getState();
  // A test that already failed has its own error; do not bury it under a second one.
  if (task.result?.state === "fail" || (task.result?.errors?.length ?? 0) > 0) return;
  if (state.assertionCalls > 0) return;

  const names: string[] = [];
  for (let s: { name: string; suite?: unknown } | undefined = task; s !== undefined; s = s.suite as typeof s) {
    if (s.name !== "") names.unshift(s.name);
  }
  const where = `${task.file?.name ?? "<unknown file>"} > ${names.join(" > ")}`;

  if (state.expectedAssertionsNumber === 0) {
    // The explicit, Vitest-enforced opt-out. Loud, never silent.
    process.stderr.write(`${ASSERTION_GUARD_PREFIX} opted out with expect.assertions(0): ${where}\n`);
    return;
  }
  throw new Error(
    `${ASSERTION_GUARD_PREFIX} ${where} made ZERO assertions when it ran. Every expect() it contains ` +
      `sits in a loop or branch this run never entered, so it passed having proved nothing. Pin the ` +
      `precondition (a non-empty input, an exact count, the element's presence) with an expect(); ` +
      `if the assertion really is "this does not throw", write expect(() => …).not.toThrow().`,
  );
});

/* ── the act-scope canary ── */

/* The reader is proved against the running React before any test relies on it (fails closed). */
await assertActScopeObservable();

const ACT_SCOPE_GUARD_PREFIX = "[act-scope guard]";

aroundEach(async (runTest, ctx) => {
  await runInTestChain(ctx.signal, ctx.task.name, runTest);
});

/* Registered after the assertion guard, so it runs BEFORE it (after-each hooks run in reverse), and
   after every after-each hook a test file registers: nothing the file's own clean-up does can reopen
   a scope once this has checked. */
afterEach(async () => {
  await settleActTurns();
  const leak = openActScope();
  if (leak !== null) throw new Error(`${ACT_SCOPE_GUARD_PREFIX} ${leak}`);
});
