import type { CampaignAdjacentComparison, CampaignTrendResponse, CompareResponse } from "./api";

/* ---- what a downloaded receipt file holds: bound evidence, never a display-only reading ----

   AssessHub returns display-only readings BESIDE the documents it binds: today the engine owner's live
   `impacts_view` beside each trend pair and each execution receipt (webapp/backend/engine.py, W50). They are never
   stored, never hashed and never part of receipt verification, so no exported file may carry them. Both JSON
   exports go through this one module:

     comparisonExportDocument  the complete comparison (the document a receipt binds), exactly as received, minus
                               any display-only field;
     trendReceiptsExportDocument  the campaign trend, built from an explicit allowlist of the trend's own fields, with
                               each adjacent pair built from an explicit allowlist of its bound fields (its identity and
                               its complete comparison). A field the server adds later is left out until it is
                               classified here, so a new display-only reading cannot leak into the file by default.

   The type-level checks below fail the type-check when a typed field of a pair or of the trend is neither exported
   nor listed as display-only, but they see only the hand-written api.ts types: the route itself returns an untyped
   dict. webapp/tests/test_receipt_export_allowlist.py therefore reads these three arrays as source text and requires
   them to EQUAL the keys the real trend route returns for a real two-snapshot campaign, so a key the engine adds or
   drops fails there until it is classified here. src/receiptExport.test.tsx reads the files the two buttons write. */

/** Display-only readings AssessHub serves beside bound documents. Never written to an exported file. */
export const DISPLAY_ONLY_FIELDS = ["impacts_view"] as const;

/** The bound fields of one adjacent trend pair: its identity and its complete server-owned comparison. */
export const TREND_PAIR_EXPORT_FIELDS = [
  "schema", "index", "from", "to", "before_snapshot_id", "after_snapshot_id", "before_label", "after_label",
  "comparison",
] as const satisfies ReadonlyArray<keyof CampaignAdjacentComparison>;

/** The campaign trend's own fields (cisco_toolkit/html.py compute_campaign_trend, webapp/backend/engine.py
 *  campaign_trend). `adjacent_comparisons` is exported pair by pair through TREND_PAIR_EXPORT_FIELDS. */
export const TREND_EXPORT_FIELDS = [
  "verdict", "verdict_note", "trajectory", "timeline", "steps", "not_comparable", "integrity", "provenance",
  "schema_compat", "protocol_adjacencies", "current_baseline", "adjacent_comparisons", "adjacent_comparison_status",
] as const satisfies ReadonlyArray<keyof CampaignTrendResponse>;

type Unclassified<T, Listed> = Exclude<keyof T, Listed>;
/** Every typed pair field is either exported or display-only: a new one fails the type-check until classified. */
export const PAIR_FIELDS_CLASSIFIED: [Unclassified<CampaignAdjacentComparison,
  (typeof TREND_PAIR_EXPORT_FIELDS)[number] | (typeof DISPLAY_ONLY_FIELDS)[number]>] extends [never] ? true : never = true;
/** Every typed trend field is exported: a new one fails the type-check until classified. */
export const TREND_FIELDS_CLASSIFIED: [Unclassified<CampaignTrendResponse,
  (typeof TREND_EXPORT_FIELDS)[number]>] extends [never] ? true : never = true;

const DISPLAY_ONLY: ReadonlySet<string> = new Set<string>(DISPLAY_ONLY_FIELDS);
const TREND_FIELDS: ReadonlySet<string> = new Set<string>(TREND_EXPORT_FIELDS);
const PAIR_FIELDS: ReadonlySet<string> = new Set<string>(TREND_PAIR_EXPORT_FIELDS);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** The keys of `value` that `keep` admits, in the order the server sent them. */
function picked(value: Record<string, unknown>, keep: (key: string) => boolean,
  map: (key: string, item: unknown) => unknown = (_key, item) => item): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value)) if (keep(key)) out[key] = map(key, value[key]);
  return out;
}

/** The complete comparison, as received, without any display-only field. A comparison never carries one today
 *  (the server puts them beside it); the rule holds here too so the export cannot depend on that. */
export function comparisonExportDocument(value: CompareResponse): CompareResponse {
  return isRecord(value) ? picked(value, (key) => !DISPLAY_ONLY.has(key)) as unknown as CompareResponse : value;
}

/** One adjacent trend pair: its allowlisted bound fields only. */
export function trendPairExportDocument(pair: CampaignAdjacentComparison): unknown {
  if (!isRecord(pair)) return pair;
  return picked(pair, (key) => PAIR_FIELDS.has(key),
    (key, item) => key === "comparison" ? comparisonExportDocument(item as CompareResponse) : item);
}

/** The campaign trend: its allowlisted fields, every adjacent pair through trendPairExportDocument. */
export function trendReceiptsExportDocument(value: CampaignTrendResponse): Record<string, unknown> {
  if (!isRecord(value)) return {};
  return picked(value, (key) => TREND_FIELDS.has(key), (key, item) => key === "adjacent_comparisons" && Array.isArray(item)
    ? item.map((pair) => trendPairExportDocument(pair as CampaignAdjacentComparison)) : item);
}

/** The exact text a download writes. */
export function exportJsonText(document: unknown): string {
  return JSON.stringify(document, null, 2);
}

/** Save one export document as a JSON file: a blob URL where the browser offers one, otherwise a data URL. */
export function downloadJsonDocument(document: unknown, filename: string): void {
  const text = exportJsonText(document);
  const makeUrl = typeof URL.createObjectURL === "function";
  const href = makeUrl
    ? URL.createObjectURL(new Blob([text], { type: "application/json;charset=utf-8" }))
    : `data:application/json;charset=utf-8,${encodeURIComponent(text)}`;
  const anchor = window.document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.style.display = "none";
  window.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  if (makeUrl) URL.revokeObjectURL(href);
}
