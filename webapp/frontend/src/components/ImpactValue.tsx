import { useId, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import type { ImpactEntry } from "../api";

/* ---- engine failure-impact values: one renderer for the whole class (W47 / F8) ----

   The backend reads failure impact from the engine-owned projection (webapp/backend/summary.py::impact_view, W27),
   so a failure-impact or keystone value reaches the SPA in one of four states. Every surface that shows one (the
   dashboard keystones, a cutover wave's worst-case blast radius, the snapshot "Failure impact" tab, and the
   failure-impact rows of the core topology and the core device page, which share one projection row builder,
   ui_projection._topology_impact) classifies it here and renders it with <ImpactValue>, so the states cannot drift
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
   a value: a count that is not a finite number is unavailable, never read as a number.

   Every state but measured carries a reason, and the reason is never hover-only. By default the value is a toggletip:
   a non-submitting <button> whose accessible name is its state text and whose accessible description is its reason
   (aria-describedby). The reason is shown in place while the button has keyboard focus, or after it is activated (a
   click, a tap, Enter or Space; Escape or leaving it hides it again). It carries no `title`, so the reason is never
   read twice and never replaces the state text as the name. A caller that makes the reason reachable itself asks for
   `reasonShown`: the core pages' FactView (a visible reason line), a disclosure that shows its reason beside the value,
   and the snapshot "Failure impact" tab, whose rows each carry one disclosure listing their qualified cells' reasons
   (one tab stop per row, not one per cell). Such a value is a plain span, never a tab stop, and keeps its `title` for a
   pointer user's hover.

   The constants below are hand copies of their Python owners. webapp/tests/test_impact_surfaces.py reads this file and
   requires each to equal its owner exactly, in order, so a renamed, added or reordered engine field fails a test
   instead of being silently dropped here. */

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

/** How a witness that is the snapshot ROOT pointer reads. RFC 6901's whole-document pointer is the empty string, which
 *  would otherwise render as an empty pointer ("the record at "). The engine cites the root as a bound's witness when
 *  no nearer record was collected to cite (the pending W35 engine change, PR #626), so it is worded as what it is. */
export const IMPACT_ROOT_WITNESS = "the snapshot as a whole (no nearer record was collected)";

/** How one cited witness pointer reads beside the failure-impact row it bounds: the snapshot as a whole (the root
 *  pointer ""), the row's own record, one of the row's own cells, or another record, always with its pointer. A bound
 *  whose witness is the row itself (a row-level bound) therefore reads as the row's own record, never as "a bound cited
 *  by another record". */
function witnessText(pointer: string, rowPointer: string | undefined): string {
  if (pointer === "") return IMPACT_ROOT_WITNESS;
  if (rowPointer && pointer === rowPointer) return `this row's own record (${pointer})`;
  if (rowPointer && pointer.startsWith(`${rowPointer}/`)) {
    return `this row's ${pointer.slice(rowPointer.length + 1).split("/").join(" ")} cell (${pointer})`;
  }
  return `the record at ${pointer}`;
}

/** The projection's own mark of a published lower bound on one failure-impact row cell: a published measure that
 *  cites a witness ref (ui_projection._topology_impact passes every bound's witnesses to each measure, and no other
 *  path puts a witness on a published failure-impact measure; summary._impact_bounds reads the same mark). Returns
 *  why, naming each cited witness relative to the row (pass the row's `pointer` so a witness on the row itself, or on
 *  one of its cells, says so), or ``undefined`` when the cell is not a published lower bound. Only for rows of the
 *  failure-impact list: a witness ref on another projection fact means something else.
 *
 *  The projection publishes no reason text on a published cell, so this names the evidence rather than paraphrasing
 *  it. It deliberately does not borrow a withheld sibling cell's reason: _topology_impact cites the bound's witnesses on
 *  every measure whatever its state, so a measure withheld for another cause (a missing key, a mistyped value) cites
 *  them too, and its reason would not explain this bound. */
export function projectionImpactBound(field: string, fact: unknown, rowPointer?: string): string | undefined {
  if (!IMPACT_MEASURES.includes(field) || !fact || typeof fact !== "object") return undefined;
  const { state, refs } = fact as { state?: unknown; refs?: unknown };
  if (state !== "published" || !Array.isArray(refs)) return undefined;
  const cited: string[] = [];
  for (const ref of refs) {
    const { role, pointer } = (ref && typeof ref === "object" ? ref : {}) as { role?: unknown; pointer?: unknown };
    if (role === "witness" && typeof pointer === "string" && !cited.includes(pointer)) cited.push(pointer);
  }
  if (!cited.length) return undefined;
  const named = cited.map((pointer) => witnessText(pointer, rowPointer || undefined));
  return `the engine publishes this value only as a minimum, citing ${named.join("; ")} as what bounds it`;
}

/** What a lower bound says, for its tooltip, its focus-revealed reason and its visible reason line. */
export function impactBoundText(value: number | string, why: string): string {
  const said = why.trim().replace(/\.+$/, "");
  return `At least ${value}: ${LOWER_BOUND_LEAD}${said ? `. Why: ${said}` : ""}.`;
}

/** The reason a qualified state carries, as one sentence: what its toggletip is described by, and what a row's
 *  disclosure lists for it. Empty for a measured value, which needs none. */
export function impactReasonText(state: ImpactValueState): string {
  switch (state.kind) {
    case "measured":
      return "";
    case "lower_bound":
      return impactBoundText(state.value, state.why);
    default:
      return state.why;
  }
}

/** The state text a value shows in place of a bare value: "≥ N", NOT ASSESSED or "unavailable" (a measured value is
 *  itself). A row's disclosure names each listed cell by it. */
export function impactStateText(state: ImpactValueState): string {
  switch (state.kind) {
    case "measured":
      return String(state.value);
    case "lower_bound":
      return `${IMPACT_BOUND_MARK} ${state.value}`;
    case "not_assessed":
      return IMPACT_NOT_ASSESSED;
    default:
      return "unavailable";
  }
}

/** A value with a reason that is never hover-only. By default it is a toggletip: a non-submitting button, reset to look
 *  like the text it replaces, whose name is its state text (`face`) and whose description is its reason. The reason is
 *  visually hidden until the button has keyboard focus or has been activated, and is then shown in place. A click or
 *  tap also focuses the button (Safari does not focus a clicked button), so Escape and leaving it behave the same for
 *  every input. It has no `title`: with a description present, a title would read the reason twice or stand in for
 *  the state text as the name. With `reasonShown`, the caller makes the reason reachable itself, so the value is a
 *  plain span that is neither a tab stop nor described twice, and its `title` stays for a pointer user's hover. */
function Explained({ kind, className, face, why, reasonShown }: {
  kind: string; className: string; face: ReactNode; why: string; reasonShown: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  if (reasonShown) return <span className={className} data-impact={kind} title={why}>{face}</span>;
  const toggle = (event: MouseEvent<HTMLButtonElement>) => {
    event.currentTarget.focus();
    setOpen((was) => !was);
  };
  const dismiss = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Escape") setOpen(false);
  };
  return (
    <span className="impact-explained">
      <button type="button" className={`impact-toggletip ${className}`} data-impact={kind}
        data-open={open ? "true" : undefined} aria-describedby={id}
        onClick={toggle} onKeyDown={dismiss} onBlur={() => setOpen(false)}>
        {face}
      </button>
      <span id={id} className="impact-why">{why}</span>
    </span>
  );
}

/** One failure-impact value in its state. `format` renders a published value (a severity as its chip); a lower bound
 *  keeps the ≥ mark in front of it. Text, never colour alone, carries the state: "≥", NOT ASSESSED, "unavailable". */
export function ImpactValue({ state, format, reasonShown = false }: {
  state: ImpactValueState; format?: (value: number | string) => ReactNode; reasonShown?: boolean;
}) {
  const show = (value: number | string): ReactNode => (format ? format(value) : String(value));
  switch (state.kind) {
    case "measured":
      return <span data-impact="measured">{show(state.value)}</span>;
    case "lower_bound": {
      const face = (
        <>
          <span aria-hidden="true">
            {format ? <>{IMPACT_BOUND_MARK} {format(state.value)}</> : `${IMPACT_BOUND_MARK} ${state.value}`}
          </span>
          <span className="sr-only">{`At least ${state.value}`}</span>
        </>
      );
      return <Explained kind="lower_bound" className="impact-bound" face={face} why={impactReasonText(state)}
        reasonShown={reasonShown} />;
    }
    case "not_assessed":
      return <Explained kind="not_assessed" className="impact-na" face={IMPACT_NOT_ASSESSED} why={state.why}
        reasonShown={reasonShown} />;
    default:
      return <Explained kind="unavailable" className="impact-unavailable" face="unavailable" why={state.why}
        reasonShown={reasonShown} />;
  }
}

/** A heading tag for a figure that is only a lower bound as a whole (a wave's worst case that may be larger). Its
 *  reason is reachable the same way as a value's. */
export function ImpactLowerBoundTag({ why }: { why: string }) {
  return <Explained kind="lower_bound_tag" className="impact-tag" face="lower bound" why={why} reasonShown={false} />;
}
