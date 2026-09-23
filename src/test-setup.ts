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
 */
import { afterEach, expect } from "vitest";

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
