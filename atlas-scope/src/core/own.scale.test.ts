/**
 * own.scale.test.ts — `withoutPrototypes` (core/own.ts) strips every name-keyed dictionary of a compiled set of ANY
 * size, and never throws on a large one.
 *
 * WHY (2026-10-01 refuter, on e092ebbe). Its path walker gathered the next step's values with
 * `next.push(...array)` and `next.push(...Object.values(dict))`: a spread passes every element as a separate call
 * argument, and past roughly 130,000 evidence records that exceeds the engine's argument limit — the one install
 * door (core/dataset.ts) then threw `RangeError: Maximum call stack size exceeded` on a large fleet, and the dataset
 * never opened. The walker now appends element by element.
 *
 * The oracle is COUNTED WORK, not time (vitest.config.ts forbids wall-clock assertions): every dictionary the set
 * holds on a name-keyed path is visited and left with no prototype, and the count is exactly the number built.
 */
import { describe, expect, it } from "vitest";
import { withoutPrototypes } from "./own";

/** Past the ~130,000-argument ceiling a spread hit, with margin. */
const RECORDS = 200_000;

describe("withoutPrototypes at scale", () => {
  it(`strips ${RECORDS.toLocaleString("en")} evidence records' value and cut dictionaries, and a ${RECORDS.toLocaleString("en")}-host ACL table, without throwing`, () => {
    const evidenceRecords = Array.from({ length: RECORDS }, (_, i) => ({ value: { [`field${i % 7}`]: i }, cut: { reason: "x" } }));
    const acls = Object.fromEntries(Array.from({ length: RECORDS }, (_, i) => [`host${i}`, { [`ACL_${i % 11}`]: [] }]));
    const set = { fabric: { evidenceRecords, acls } };

    let thrown: unknown = null;
    try {
      withoutPrototypes(set);
    } catch (e) {
      thrown = e;
    }
    expect(thrown === null ? null : String(thrown)).toBeNull();

    let stripped = 0;
    for (const r of evidenceRecords) {
      if (Object.getPrototypeOf(r.value) === null) stripped++;
      if (Object.getPrototypeOf(r.cut) === null) stripped++;
    }
    expect(Object.getPrototypeOf(acls)).toBeNull();
    for (const host of Object.keys(acls)) if (Object.getPrototypeOf(acls[host]) === null) stripped++;
    expect(stripped).toBe(RECORDS * 3);
  });
});
