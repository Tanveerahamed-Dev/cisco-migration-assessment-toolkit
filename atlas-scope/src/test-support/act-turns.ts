/**
 * act-turns.ts — the one way a test opens an ASYNC `act()` scope, and the reader the act-scope
 * canary in `src/test-setup.ts` uses.
 *
 * WHY (acceptance F2, the load cascade). On a run at 85-100 % host CPU, one 37 s timeout in
 * `self-removing-focus.test.tsx` was followed by 277 failures reading "the seeded flow had not been
 * traced after 50 flush turns". The cause was not the wait. It was React's process-global act()
 * scope:
 *
 *   1. Vitest does not stop a test that times out. It rejects the test's promise and aborts the
 *      test context's `signal`; the body keeps running. Nothing read that signal, so the abandoned
 *      body was still parked inside `await act(async () => …)` when the next case opened its own.
 *   2. React 19's act() keeps a module-level depth. A scope pops by restoring the depth it saw when
 *      it OPENED (react.development.js `popActScope`), and it flushes its queue only when that depth
 *      was 0. Two async scopes that close out of order (A opens, B opens, A closes, B closes) leave
 *      the depth stuck at 1: no act() is ever outermost again, the queue is never flushed, and React
 *      commits nothing for the rest of the file. Every later case then fails with a message about
 *      itself, never about the leak.
 *
 * WHAT THIS MODULE GUARANTEES, for every async scope opened through it:
 *   - CHECKPOINTS. Before a scope opens and after it closes, the calling test's own `signal` is
 *     read; if Vitest abandoned that test, the continuation throws `AbandonedTestError` instead of
 *     opening another scope in a later test. "The calling test" is carried by an AsyncLocalStorage
 *     chain that `src/test-setup.ts` enters around every test (`runInTestChain`), so an abandoned
 *     body checks ITS signal, not whichever test happens to be running when it wakes up.
 *   - SETTLING. Every scope opened here, and every promise handed to `track()`, is awaited by
 *     `settleActTurns()` — which `src/test-setup.ts` runs after each test, before the canary. A
 *     timed-out case therefore costs exactly one red: the scope it was parked in closes (one turn),
 *     its continuation hits the checkpoint and stops, and the next case starts with a clean depth.
 *
 * WHAT IT CANNOT DO, stated rather than implied. An abandoned body that is parked in an await this
 * module does not see (a bare timer, a fetch) is not waited for; it is stopped at its NEXT call
 * here, which is why `src/core/source-hygiene.test.ts` requires every act() in `src/` whose scope
 * can be asynchronous to go through this module. It decides that with the TypeScript checker, not
 * with syntax: React's act() is allowed raw only as a direct call with one inline, non-async callback
 * every value of which is PROVED not to be a thenable (React's act() takes its asynchronous path
 * exactly when the callback returns one) — a primitive by its syntax, a non-void primitive by its
 * type, or a `void` from a function whose own body is proved the same way or from a member a library
 * declares with `void` WRITTEN as its return type (not a type parameter it passes a callee's return
 * through, as `fn.call(…)`, `Reflect.apply` and `Object.freeze` do). A `void` type alone proves nothing: TypeScript lets a Promise-returning function stand
 * wherever `() => void` is expected, so `act(() => fn())` through such a value is reported and the fix
 * is a block, `act(() => { fn(); })`. Also reported: an async, Promise-returning, `any`/`unknown`-
 * returning or passed-by-name callback; React's act used as a value (stored, re-exported, `.call`ed)
 * or reached without its name (a computed key on, or an escape of, a value that carries it); and a
 * Promise-returning look-alike of a library member. An act the checker cannot resolve counts as
 * React's. What that scan does not see — a thenable wearing a non-void primitive type through `any`
 * or an assertion written elsewhere, or a library's implementation replaced where no type describes
 * it (a `vi.mock` factory, `Object.assign`) — is the canary's to catch. A scope whose callback never
 * resolves cannot be settled; the after-each hook then times out and says so.
 *
 * The containment and the canary are proved by a planted child Vitest run in
 * `src/core/scripts-typecheck.test.ts` (one abandoned case costs one red; the same planted file with
 * raw act() cascades; an un-awaited act() scope is named by the canary).
 */
import { AsyncLocalStorage } from "node:async_hooks";
import * as React from "react";

/* ── the test chain ── */

interface Chain {
  signal: AbortSignal;
  test: string;
}

const chains = new AsyncLocalStorage<Chain>();

/** Run one test (its hooks and its body) inside its own chain. Called by `src/test-setup.ts` only. */
export function runInTestChain<T>(signal: AbortSignal, test: string, run: () => T): T {
  return chains.run({ signal, test }, run);
}

/** Thrown into a continuation whose test Vitest has already abandoned. */
export class AbandonedTestError extends Error {
  override name = "AbandonedTestError";
}

/**
 * Stop here if the test this code belongs to was abandoned (timed out, or its hook did). Outside a
 * test (collection, beforeAll) there is no chain and nothing to check.
 */
export function checkpoint(): void {
  const c = chains.getStore();
  if (c === undefined || !c.signal.aborted) return;
  const why = c.signal.reason instanceof Error ? c.signal.reason.message : String(c.signal.reason);
  throw new AbandonedTestError(
    `[act-turns] "${c.test}" was abandoned by the runner (${why}); its continuation stops here instead of ` +
      `opening another act() scope inside a later test.`,
  );
}

/* ── the scopes ── */

/** Async act() scopes opened here and not yet closed. */
const open = new Set<Promise<void>>();
/** Whole chains a test asked to have waited for (`track`), as never-rejecting promises. */
const tracked = new Set<Promise<void>>();

/**
 * `await act(async () => …)`, with a checkpoint on each side and the scope registered so the
 * after-each settle waits for it. Use this, never a raw async act(), anywhere in `src/`.
 */
export async function actAsync(fn: () => unknown): Promise<void> {
  checkpoint();
  const scope = (async (): Promise<void> => {
    await React.act(async () => {
      await fn();
    });
  })();
  open.add(scope);
  try {
    await scope;
  } finally {
    open.delete(scope);
  }
  checkpoint();
}

/** `rounds` act turns, each letting `ms` of timers run: the "let the scheduler and effects land" wait. */
export async function flushTurns(ms = 10, rounds = 1): Promise<void> {
  for (let i = 0; i < rounds; i += 1) {
    await actAsync(() => new Promise<void>((r) => setTimeout(r, ms)));
  }
}

/**
 * Register a whole chain (a case's drive, say) so the after-each settle waits until it has fully
 * stopped — including the synchronous work after its last await. Returns the promise unchanged.
 */
export function track<T>(p: Promise<T>): Promise<T> {
  const settled = p.then(
    () => undefined,
    () => undefined,
  );
  tracked.add(settled);
  void settled.then(() => tracked.delete(settled));
  return p;
}

/**
 * Wait until no scope opened here is open and no tracked chain is running. Bounded by one turn of
 * whatever is in flight: an abandoned continuation stops at its next checkpoint.
 */
export async function settleActTurns(): Promise<void> {
  while (open.size + tracked.size > 0) {
    await Promise.allSettled([...open, ...tracked]);
  }
}

/* ── the reader the act-scope canary uses ── */

/**
 * React's shared internals, pinned to the react version in package.json. The canary must fail
 * CLOSED if they move: a React upgrade that renames or drops `actQueue` would otherwise disarm it
 * silently — a gate whose success path is never executed.
 */
const INTERNALS_KEY = "__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE";

function internals(): { actQueue: unknown } {
  const value = (React as unknown as Record<string, unknown>)[INTERNALS_KEY];
  if (value === null || typeof value !== "object" || !("actQueue" in value)) {
    throw new Error(
      `[act-scope guard] React ${React.version} no longer exposes ${INTERNALS_KEY}.actQueue, which the act-scope ` +
        `canary reads. Re-derive the canary against this React's act() before trusting any test run.`,
    );
  }
  return value as { actQueue: unknown };
}

/**
 * Proves the reader against the running React before any test relies on it: an open async scope
 * must be visible as a non-null queue, and the queue must be released once the scope closes.
 */
export async function assertActScopeObservable(): Promise<void> {
  const box = internals();
  if (box.actQueue !== null) throw new Error("[act-scope guard] React's act() queue was already open before any test ran.");
  let seenOpen = false;
  await React.act(async () => {
    seenOpen = box.actQueue !== null;
  });
  if (!seenOpen || box.actQueue !== null) {
    throw new Error(
      `[act-scope guard] React ${React.version}'s act() no longer behaves as the canary assumes ` +
        `(open scope visible: ${seenOpen}; released after close: ${box.actQueue === null}).`,
    );
  }
}

/**
 * Null when no act() scope is left open; otherwise what is wrong. An act() whose callback THREW
 * leaves the queue allocated at depth 0 (react.development.js pops the scope without releasing it);
 * one empty synchronous act() at depth 0 flushes and releases it, so that residue is cleared rather
 * than reported. At depth 1 or more — a scope still open, or a depth corrupted by two scopes that
 * closed out of order — the probe cannot release it, and that is the leak.
 */
export function openActScope(): string | null {
  const box = internals();
  if (box.actQueue === null) return null;
  React.act(() => {});
  if (box.actQueue === null) return null;
  return (
    "React's act() queue is still open after this test ended: an act() scope was left open, or two async " +
    "scopes closed out of order and left React's act depth stuck. Every later render in this file will be " +
    "queued and never committed. Open async scopes through src/test-support/act-turns.ts and await them."
  );
}
