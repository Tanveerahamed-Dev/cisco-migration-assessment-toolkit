import type {
  CurrentBaselineBlocker,
  ExecCheck,
  ValidationCheck,
} from "./api";

/** Rows that can be projected in a current-baseline evidence panel. API ownership stays with api.ts. */
export type BaselinePresentationRow = CurrentBaselineBlocker | ValidationCheck | ExecCheck;

export function baselinePresentationKey(row: BaselinePresentationRow): string {
  return [row.device, row.wave, row.category, row.check, row.source_key, row.expect]
    .map((part) => String(part || "").trim())
    .join("\u0000");
}

/** Current producers own this classification explicitly; presentation code must not recreate it. */
export function isProducerDeclaredBaselineBlocker(row: BaselinePresentationRow): boolean {
  return row.baseline_blocker === true;
}

/**
 * Compatibility-only hint for records written before `baseline_blocker` was frozen.
 *
 * Callers may render these rows neutrally so evidence is not hidden. They must never use this hint
 * to derive a gate, blocker count, execution outcome, or disabled operator action.
 */
export function isLegacyBaselinePresentationCandidate(row: BaselinePresentationRow): boolean {
  if (typeof row.baseline_blocker === "boolean") return false;
  const state = String(row.baseline_state || row.evidence_state || "").trim().toLowerCase();
  if (["degraded", "review", "not_verified"].includes(state)) return true;
  const expected = String(row.expect || "").trim();
  return /^PRE-CUTOVER (?:DEGRADED|REVIEW) — BLOCKER:/i.test(expected)
    || /^[A-Z0-9][A-Z0-9 _/-]* BASELINE NOT VERIFIED(?:\s+—\s+BLOCKER)?(?::|\b)/i.test(expected);
}
