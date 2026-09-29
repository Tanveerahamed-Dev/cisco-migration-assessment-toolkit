/**
 * test-subjects.ts — how a forwarding INVARIANT test obtains a subject it resolved by property, and what it
 * does on a fabric that has none.
 *
 * The invariant tier runs on whatever fabric is loaded: the tracked sample, its isomorphic rename, the
 * engine's 7-device golden snapshot, a reader's own snapshot. A property a test needs ("a decided two-hop
 * denial", "a route whose next hop another collected host owns") may simply not exist on a small fleet.
 * Then the test is NOT APPLICABLE and says so BY NAME — never a throw at module scope that takes every
 * other test in the file with it, and never a pass that proved nothing.
 *
 * On the tracked reference sample an absent subject is a FAILURE, never a skip: the golden tier's rule
 * (src/test-support/golden-sample.ts), applied to the property a test needs. The skip is preceded by the
 * assertion that licenses it, so the runner's zero-assertion guard (src/test-setup.ts) sees it.
 *
 * Resolve subjects inside a test or hook (lazily, memoised if they are costly), never at module scope.
 */
import { expect, type TestContext } from "vitest";
import { isGoldenSample } from "../test-support/golden-sample";

/** The subject, or — only on a fabric that is not the reference sample — a named not-applicable skip. */
export function need<T>(ctx: TestContext, subject: T | undefined | null, what: string): T {
  if (subject === undefined || subject === null) {
    expect(isGoldenSample(), `precondition: the reference sample has ${what}`).toBe(false);
    ctx.skip(`not applicable to this fabric: it has no ${what}`);
  }
  return subject as T;
}

/** A count that must be non-zero wherever the data can exercise it: on the reference sample it is required. */
export function needSome(ctx: TestContext, count: number, what: string): number {
  return need(ctx, count > 0 ? count : undefined, what);
}

/** A regular expression matching `text` literally — for a sentence that embeds a name read from data. */
export const literal = (text: string): RegExp => new RegExp(text.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&"));

/** A value computed once, on first use (inside a test or hook), never at module load. */
export function lazy<T>(make: () => T): () => T {
  let done = false;
  let v: T;
  return () => {
    if (!done) {
      v = make();
      done = true;
    }
    return v;
  };
}
