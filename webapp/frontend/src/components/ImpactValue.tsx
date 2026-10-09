import type { ReactNode } from "react";
import type { ImpactEntry } from "../api";

/* ---- engine failure-impact values: one renderer for the whole class (W47 / F8) ----

   The backend reads failure impact from the engine-owned projection (webapp/backend/summary.py::impact_view, W27),
   so a failure-impact or keystone value reaches the SPA in one of four states. Every surface that shows one (the
   dashboard keystones, a cutover wave's worst-case blast radius, the snapshot "Failure impact" tab, and the core
   topology's failure-impact rows) classifies it here and renders it with <ImpactValue>, so the states cannot drift
   apart from one screen to the next:

     measured      a published value, shown as itself. A published 0 stays 0.
     lower_bound   a published value the engine marks as only a minimum: summary.impact_entry's `lower_bound`, the
                   tab's "≥ N — …" cell (summary.IMPACT_BOUND_MARK), or a witness ref on a published failure-impact
                   measure (the projection's own mark, which summary._impact_bounds reads). It shows as "≥ N" with a
                   dashed underline, and its tooltip and screen-reader text say it is a minimum, not a measurement.
     not_assessed  a cell the engine holds, or a blast radius it could not rank: summary.IMPACT_NOT_ASSESSED, or a
                   withheld tab cell carrying the projection's reason. It shows as the neutral, hatched NOT ASSESSED
                   tag: never 0, never a blank that reads as healthy, and never a colour of health.
     unavailable   a value the backend nulls because the engine withholds it (summary.impact_entry's None). It shows
                   as "unavailable", which is distinct from 0.

   Classification only reads what the backend owner already decided. It never re-derives a bound, and it never coerces
   a value: a count that is not a finite number is unavailable, never read as a number. */

/** summary.IMPACT_NOT_ASSESSED (cutover.GATE_NOT_ASSESSED): the severity of an entry that ranks nothing. */
export const IMPACT_NOT_ASSESSED = "NOT ASSESSED";
/** summary.IMPACT_BOUND_MARK: how the tab marks a published lower bound in place of its bare value. */
export const IMPACT_BOUND_MARK = "≥";
/** analyze.compute_failure_impact's bands (ui_projection.IMPACT_SEVERITIES), worst first. */
export const IMPACT_SEVERITIES: readonly string[] = ["High", "Medium", "Low", "Info"];
/** The cells that measure the simulated blast radius (ui_projection._IMPACT_MEASURES, summary.IMPACT_MEASURES): the
 *  only cells a published lower bound sits on. */
export const IMPACT_MEASURES: readonly string[] = ["severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp"];
/** The tab's columns, in the producer's field order (summary.IMPACT_FIELDS). */
export const IMPACT_FIELDS: readonly string[] = [
  "host", "severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp", "off_scan_gw_vlans", "detail",
];
/** The tab columns that carry a value. The host and detail columns are text, shown as they are. */
const IMPACT_VALUE_FIELDS: readonly string[] = [...IMPACT_MEASURES, "off_scan_gw_vlans"];

/** summary._R_BOUND_LEAD, without its colon. */
const LOWER_BOUND_LEAD = "a lower bound, not an exact measurement";
export const IMPACT_UNAVAILABLE_WHY =
  "Withheld by the engine: no value was published here, so it is unavailable. It is not a measured 0.";
export const IMPACT_NOT_ASSESSED_WHY =
  "Not assessed: the engine publishes no blast radius it could rank here, so there is no measurement. It is not a 0 "
  + "and not a clean result.";
const IMPACT_BOUND_DEFAULT_WHY = "the engine publishes this value only as a lower bound";

export type ImpactValueState =
  | { kind: "measured"; value: number | string }
  | { kind: "lower_bound"; value: number | string; why: string }
  | { kind: "not_assessed"; why: string }
  | { kind: "unavailable"; why: string };

const UNAVAILABLE: ImpactValueState = { kind: "unavailable", why: IMPACT_UNAVAILABLE_WHY };
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

/** True for the entry the backend writes when it ranks nothing (summary._keystones' disclosure, a wave's worst case
 *  that no switch could rank). */
export function isImpactNotAssessed(entry: Partial<ImpactEntry> | null | undefined): boolean {
  return !!entry && typeof entry === "object" && entry.severity === IMPACT_NOT_ASSESSED;
}

/** One count of a keystone or a worst-case blast radius (summary.impact_entry). */
export function impactEntryValue(entry: Partial<ImpactEntry> | null | undefined,
  field: "stranded" | "vlans_impacted"): ImpactValueState {
  if (!entry || typeof entry !== "object") return UNAVAILABLE;
  if (isImpactNotAssessed(entry)) return { kind: "not_assessed", why: text(entry.detail) || IMPACT_NOT_ASSESSED_WHY };
  const value: unknown = entry[field];
  if (!isCount(value)) return UNAVAILABLE;
  if (entry.lower_bound === true) return { kind: "lower_bound", value, why: impactBoundReasons(entry.lower_bound_reasons) };
  return { kind: "measured", value };
}

/** The entry's `lower_bound_reasons` as one clause (summary.impact_bound_reason joins them the same way). */
export function impactBoundReasons(reasons: unknown): string {
  const said = Array.isArray(reasons) ? reasons.filter((r): r is string => typeof r === "string" && !!r.trim()) : [];
  return said.length ? said.join("; ") : IMPACT_BOUND_DEFAULT_WHY;
}

const BOUND_CELL = /^≥\s*(.+?)(?:\s+—\s+([\s\S]*))?$/;
const BOUND_LEAD_PREFIX = new RegExp(`^${LOWER_BOUND_LEAD}:\\s*`);

/** A tab cell that opens with summary.IMPACT_BOUND_MARK: ``≥ value — a lower bound, not an exact measurement: why``
 *  (summary.impact_bound_cell). ``null`` for any other cell. */
export function parseImpactBound(cell: string): ImpactValueState | null {
  const said = BOUND_CELL.exec(cell.trim());
  if (!said) return null;
  const raw = said[1].trim();
  const value = /^-?\d+(?:\.\d+)?$/.test(raw) ? Number(raw) : raw;
  const why = (said[2] ?? "").trim().replace(BOUND_LEAD_PREFIX, "");
  return { kind: "lower_bound", value, why: why || IMPACT_BOUND_DEFAULT_WHY };
}

/** One cell of the snapshot "Failure impact" tab (summary.failure_impact_table) in a value column; ``null`` for the
 *  host and detail columns, which are text. A string in a count column, or a severity outside the engine's bands, is
 *  the projection's reason for withholding the cell, so it is not assessed. */
export function impactTableCell(field: string, value: unknown): ImpactValueState | null {
  if (!IMPACT_VALUE_FIELDS.includes(field)) return null;
  if (typeof value === "string") {
    const bound = parseImpactBound(value);
    if (bound) return bound;
    if (field === "severity" && IMPACT_SEVERITIES.includes(value)) return { kind: "measured", value };
    return { kind: "not_assessed", why: value.trim() || IMPACT_NOT_ASSESSED_WHY };
  }
  if (field !== "severity" && isCount(value)) return { kind: "measured", value };
  return UNAVAILABLE;
}

/** The projection's own mark of a published lower bound on one failure-impact row cell: a published measure that
 *  cites a witness ref (ui_projection._topology_impact passes every bound's witnesses to each measure, and no other
 *  path puts a witness on a published failure-impact measure; summary._impact_bounds reads the same mark). Returns
 *  why, naming the cited pointers, or ``undefined`` when the cell is not a published lower bound. Only for rows of the
 *  failure-impact list: a witness ref on another projection fact means something else. */
export function projectionImpactBound(field: string, fact: unknown): string | undefined {
  if (!IMPACT_MEASURES.includes(field) || !fact || typeof fact !== "object") return undefined;
  const { state, refs } = fact as { state?: unknown; refs?: unknown };
  if (state !== "published" || !Array.isArray(refs)) return undefined;
  const cited: string[] = [];
  for (const ref of refs) {
    const { role, pointer } = (ref && typeof ref === "object" ? ref : {}) as { role?: unknown; pointer?: unknown };
    if (role === "witness" && typeof pointer === "string" && !cited.includes(pointer)) cited.push(pointer);
  }
  return cited.length ? `the engine cites ${cited.join(", ")} as a bound on this row` : undefined;
}

/** What a lower bound says, for its tooltip and its screen-reader text. */
export function impactBoundText(value: number | string, why: string): string {
  return `At least ${value}: ${LOWER_BOUND_LEAD}${why ? ` (${why})` : ""}.`;
}

/** One failure-impact value in its state. `format` renders a published value (a severity as its chip); a lower bound
 *  keeps the ≥ mark in front of it. */
export function ImpactValue({ state, format }: {
  state: ImpactValueState; format?: (value: number | string) => ReactNode;
}) {
  const show = (value: number | string): ReactNode => (format ? format(value) : String(value));
  switch (state.kind) {
    case "measured":
      return <span data-impact="measured">{show(state.value)}</span>;
    case "lower_bound": {
      const said = impactBoundText(state.value, state.why);
      return (
        <span className="impact-bound" data-impact="lower_bound" title={said}>
          <span aria-hidden="true">
            {format ? <>{IMPACT_BOUND_MARK} {format(state.value)}</> : `${IMPACT_BOUND_MARK} ${state.value}`}
          </span>
          <span className="sr-only">{said}</span>
        </span>
      );
    }
    case "not_assessed":
      return (
        <span className="impact-na" data-impact="not_assessed" title={state.why}>
          {IMPACT_NOT_ASSESSED}<span className="sr-only">: {state.why}</span>
        </span>
      );
    default:
      return (
        <span className="impact-unavailable" data-impact="unavailable" title={state.why}>
          unavailable<span className="sr-only">: {state.why}</span>
        </span>
      );
  }
}

/** A heading tag for a figure that is only a lower bound as a whole (a wave's worst case that may be larger). */
export function ImpactLowerBoundTag({ why }: { why: string }) {
  return (
    <span className="impact-tag" data-impact="lower_bound_tag" title={why}>
      lower bound<span className="sr-only">: {why}</span>
    </span>
  );
}
