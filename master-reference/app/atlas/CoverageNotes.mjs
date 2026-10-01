/**
 * Pure, executable coverage notes for the Source Explorer proof cards.
 *
 * Line, symbol and test records exist only for full-depth files; a file the
 * compiler censuses at identity depth contributes none of them. Every card
 * whose total is drawn from those record groups therefore names the deferral
 * instead of presenting a bare total as whole-repository coverage, and says
 * "unproven" when the census depth was not reported at all.
 */

const COVERAGE_CARDS = Object.freeze({
  lines: Object.freeze({
    unreported: "Census depth not reported — line coverage unproven",
    full: () => "Exact denominator from completeness ledger",
    deferred: (censusDepth) =>
      `Full-depth files only · ${censusDepth.identity_depth_nonblank_lines_deferred.toLocaleString("en-US")} lines in ${censusDepth.identity_depth_files.toLocaleString("en-US")} identity-only files deferred`,
  }),
  symbols: Object.freeze({
    unreported: "Census depth not reported — symbol coverage unproven",
    full: (recordCounts) => `${declaredTests(recordCounts)} declared tests`,
    deferred: (censusDepth, recordCounts) =>
      `Full-depth files only · symbols and tests of ${censusDepth.identity_depth_files.toLocaleString("en-US")} identity-only files deferred · ${declaredTests(recordCounts)} declared tests`,
  }),
});

function declaredTests(recordCounts) {
  const tests = recordCounts?.tests;
  return Number.isSafeInteger(tests) ? tests.toLocaleString("en-US") : "—";
}

export function proofCardCoverageNote(card, censusDepth, recordCounts) {
  const notes = Object.hasOwn(COVERAGE_CARDS, card) ? COVERAGE_CARDS[card] : undefined;
  if (!notes) throw new Error(`unknown coverage card: ${String(card)}`);
  if (censusDepth === undefined || censusDepth === null) return notes.unreported;
  return censusDepth.identity_depth_files > 0 ? notes.deferred(censusDepth, recordCounts) : notes.full(recordCounts);
}
