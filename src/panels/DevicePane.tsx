/**
 * DevicePane.tsx — everything the snapshot holds about the selected device or link.
 *
 * This is the third step of acceptance A1 (priority -> device -> finding -> configuration
 * evidence) and the surface that has to survive the hardest reading: it is where a reader decides
 * what is known about a box. So the organising rule here is narrower than "show the record":
 *
 *   A field we never collected and a field we measured as zero must not be able to render the
 *   same pixels. `orNotObserved` is the only route to the screen for any nullable field, and the
 *   two joins on this surface (interface x physical-health, our blast radius x the snapshot's own
 *   failure_impact) are OUTER joins whose one-sided rows are labelled, never dropped.
 *
 * Nothing here recomputes a verdict the engine already published. Where our analysis and the
 * snapshot's disagree, both numbers are rendered next to each other with T9 — reconciling them
 * would invent a fact at exactly the point where the two sources of truth diverge.
 */
import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import {
  crossLayerByHost,
  fabric,
  findingsByHost,
  hasRib,
  interfacesOf,
  l3ByHost,
  linkById,
  linksByHost,
  physicalByHost,
  protocolsByHost,
  endpointsByHost,
  deviceById,
  routesOf,
  severityRank,
} from "../core/data";
import { presentBand, unassessedScoringDomains } from "../core/band-qualification";
import { aclUndecidability } from "../core/acl-coverage";
import { ribIncompleteness } from "../forwarding/rib-completeness";
import { placeholderZero } from "../core/placeholders";
import { T9_disagreement } from "../core/claims";
import { RouteFieldValue } from "./HopList";
import { failureImpact, linkFailureImpact } from "../analysis/blast";
import { cableCountPhrase, disputeSentence, disputesOf, hostCableAccount } from "../analysis/port-claims";
import { useInvestigation, type EvidenceTab } from "../core/store";
import type {
  AclLine,
  Cite,
  Device,
  InterfaceRecord,
  Link,
  PhysicalHealth,
  Severity,
} from "../core/types";
import { SEVERITY_ORDER } from "../core/types";

/**
 * Fields `tools/compile-snapshot.mjs` emits that `PhysicalHealth` in `core/types.ts` does not yet
 * declare. `late_collisions` is present in every source row and was silently dropped; the engine's
 * own "[NOT OBSERVED] — no counters for this port" prose was nulled by `val()` before a reader
 * could see the reason. Both are now compiled, and read here through a narrow local widening
 * because `core/types.ts` is owned by another workstream in this session — lift them into
 * `PhysicalHealth` the next time that file is touched.
 */
type PhysExtra = { lateCollisions?: number | null; riskUnobserved?: string | null };
const physExtra = (p: PhysicalHealth | null | undefined): PhysExtra => (p ?? {}) as PhysExtra;

/** True when the row carries at least one MEASUREMENT a risk grade could rest on: an observed port
 *  status, or any observed error/drop counter. */
export function physHasMeasurement(p: PhysicalHealth): boolean {
  const status = typeof p.status === "string" && p.status.trim() !== "" && p.status.trim().toLowerCase() !== "unknown";
  const counters = [p.inputErrors, p.crcErrors, p.outputErrors, p.outputDrops, physExtra(p).lateCollisions ?? null];
  return status || counters.some((n) => typeof n === "number" && Number.isFinite(n));
}

/**
 * Why a physical-health row's risk and severity are NOT a result, or null when they are.
 *
 * Two routes to "not assessed", one predicate. The producer's own "[NOT OBSERVED] … L1 error rate
 * NOT assessed" marker, where it wrote one; and — whatever the producer's risk string says — a row
 * with no observed status and no observed counter. The guard used to key only on the marker, so 19
 * rows on core1/core2 with every measurement empty rendered the producer's default "ok" and an
 * "Info" grade as a healthy port (2026-09-22 critic, B1 blocker): a verdict over zero observations.
 * Keyed on the measurement fields themselves, not on a list of ports or on the marker's presence.
 */
export function physUnassessedReason(p: PhysicalHealth | null | undefined): string | null {
  if (p == null) return null;
  const marker = physExtra(p).riskUnobserved;
  if (!p.risk && typeof marker === "string" && marker.trim() !== "") return marker;
  if (physHasMeasurement(p)) return null;
  const stamped = [p.risk ? `risk "${p.risk}"` : null, p.severity ? `severity "${p.severity}"` : null].filter(Boolean).join(" and ");
  return (
    "no port status and no error or drop counter was observed for this port, so its L1 error rate was not assessed" +
    (stamped === "" ? "." : ` — the producer stamped ${stamped} over no measurements, which is not a result.`)
  );
}
import {
  Band,
  Chip,
  Cite as CiteButton,
  Empty,
  LiveRegion,
  Meter,
  NotObserved,
  SeverityBadge,
  StateDot,
  Tabs,
  TabPanel,
  orNotObserved,
  type TabItem,
} from "../ui/primitives";
import { IconNotObserved } from "../ui/icons";
import "./DevicePane.css";

/* ══ the citation channel ══════════════════════════════════════════════════
   Opening the Inspector at an exact path belongs to the Inspector, not to this pane. The prop is
   the real integration point; the fallback exists so that a Cite affordance is never inert while
   the surfaces are still being wired together. An affordance that silently does nothing is worse
   than one that is absent, because a reader concludes the evidence is unreachable rather than
   that the app is unfinished. */

/** Dispatched on `window` when no `onOpenCite` was supplied. The Inspector may subscribe to it. */
export const OPEN_CITE_EVENT = "atlas:open-cite";

export function useOpenCite(handler?: (cite: Cite) => void): (cite: Cite) => void {
  const setInspectorOpen = useInvestigation((s) => s.setInspectorOpen);
  return useCallback(
    (cite: Cite) => {
      if (handler) {
        handler(cite);
        return;
      }
      setInspectorOpen(true);
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(OPEN_CITE_EVENT, { detail: { cite } }));
      }
    },
    [handler, setInspectorOpen],
  );
}

/* ══ small shared helpers ══════════════════════════════════════════════════ */

const cx = (...parts: (string | false | null | undefined)[]): string => parts.filter(Boolean).join(" ");

const SEVERITY_SET = new Set<string>(SEVERITY_ORDER);

/** The model types several severity fields as a bare string. Anything off the enum is not a severity. */
export const asSeverity = (s: string | null | undefined): Severity | null =>
  typeof s === "string" && SEVERITY_SET.has(s) ? (s as Severity) : null;

/**
 * The severity of a row whose producer ALSO says the row was not assessed.
 *
 * The collector grades every physical_health row — including the 73 whose risk reads "[NOT
 * OBSERVED] - no 'show interfaces' counters … L1 error rate NOT assessed" — as "Info", the same
 * chip a port assessed as clean earns. Rendered through, that grade sat beside "risk flag: not
 * observed" and read as a mild result (2026-09-21 critic, B1). A grade is only shown for a row that
 * was assessed; a row carrying the producer's own unassessed marker renders "not graded", with the
 * producer's reason, whatever grade it was stamped with. Keyed on the unobserved-risk field the
 * compiler emits, not on a list of ports or the literal grade. Applied to physical rows, where the
 * marker says the row's ONE assessment (the L1 error rate) was not made; an L3 row's marker names
 * only object tracking, so its grade is left as stamped.
 */
function GradedSeverity({ severity, unassessed }: { severity: string | null | undefined; unassessed: string | null | undefined }): ReactElement {
  if (typeof unassessed === "string" && unassessed.trim() !== "") {
    return (
      <span className="ui-notobs ui-notobs--compact" data-unobserved="true" data-ungraded="" title={unassessed}>
        <IconNotObserved className="ui-notobs__glyph" />
        <span className="visually-hidden">severity: </span>
        <span className="ui-notobs__text">not graded</span>
        <span className="visually-hidden">{` — not assessed. Reason: ${unassessed}${severity ? ` The producer stamped "${severity}", which is not a result for a row it did not assess.` : ""}`}</span>
      </span>
    );
  }
  const sev = asSeverity(severity);
  return sev ? <SeverityBadge severity={sev} compact /> : <NotObserved what="severity" compact />;
}

/** `interfacesOf`/`physicalByHost` flatten "no records" and "host never collected" into an empty
 *  array. The difference decides whether an empty table means zero or means unknown, so the
 *  presence of the host KEY is read directly rather than the length of what it returns. */
const hasInterfaceRecords = (host: string): boolean =>
  Object.prototype.hasOwnProperty.call(fabric.interfaces, host);

const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

/* The band-qualification rule and `unassessedScoringDomains` live in ONE owner every band surface
   reads (core/band-qualification.ts); re-exported here for the callers that import it from the pane. */
export { unassessedScoringDomains };

/* ══ key/value rows ════════════════════════════════════════════════════════ */

export interface KvRow {
  k: string;
  v: ReactNode;
  /** The record(s) the value was read from. Several when the row reads several records. */
  cite?: Cite | readonly Cite[];
  /**
   * Set instead of `cite` when the value is a computation of THIS application, not a field of any
   * record: the basis, in words, rendered on the row as `data-derived` and read aloud with it.
   */
  derived?: string;
  /** Renders the value across the full width under its key — for prose and long strings. */
  wide?: boolean;
}

/**
 * A row of the Device pane: it MUST say where its value comes from — a citation to the record that
 * carries it, or the basis of this application's own computation (acceptance B6). `KvRow` keeps both
 * optional for the surfaces outside this pane; every row this pane renders is typed as this.
 */
export type EvidenceRow = Omit<KvRow, "cite" | "derived"> &
  ({ cite: Cite | readonly Cite[]; derived?: undefined } | { derived: string; cite?: undefined });

const citesOf = (c: Cite | readonly Cite[] | undefined): Cite[] =>
  c === undefined ? [] : [...new Set(typeof c === "string" ? [c] : c)];

export function Kv({
  rows,
  onOpenCite,
  className,
}: {
  rows: readonly KvRow[];
  onOpenCite: (cite: Cite) => void;
  className?: string;
}): ReactElement {
  return (
    <dl className={cx("dp-kv", className)}>
      {rows.map((r) => (
        <div key={r.k} className={cx("dp-kv__row", r.wide && "dp-kv__row--wide")} data-derived={r.derived}>
          <dt className="dp-kv__k">{r.k}</dt>
          <dd className="dp-kv__v">
            {r.v}
            {citesOf(r.cite).map((c) => (
              <CiteButton key={c} cite={c} onOpen={onOpenCite} className="dp-kv__cite" />
            ))}
            {r.derived !== undefined && r.cite === undefined ? (
              <span className="visually-hidden">{` — computed by this application: ${r.derived}`}</span>
            ) : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** `Kv` for this pane: every row states its evidence, and the type refuses one that does not. */
function EvidenceKv({ rows, onOpenCite }: { rows: readonly EvidenceRow[]; onOpenCite: (cite: Cite) => void }): ReactElement {
  return <Kv rows={rows} onOpenCite={onOpenCite} />;
}

/**
 * The evidence for one field of a device record: the source record the compiler READ it from
 * (`Device.fieldCites`). A null field with no such record is an absence, visible on the device's own
 * record, so that record is cited. A non-null value no source record carries is the compiler's own
 * default, and says so instead of borrowing a citation that does not hold it.
 */
function deviceFieldEvidence(device: Device, field: keyof Device): { cite: Cite } | { derived: string } {
  const c = device.fieldCites?.[field];
  if (c !== undefined) return { cite: c };
  const v = device[field];
  if (v === null || v === undefined) return { cite: device.cite };
  return { derived: `the compiler's default for ${String(field)} — no source record carries it for ${device.host}` };
}

/** The basis stated on every row of our own blast-radius computation. */
const OUR_BLAST_BASIS =
  "our blast-radius analysis over the compiled cable map (analysis/blast.ts); a computation, not a field of any source record";

export function Section({
  title,
  note,
  children,
  actions,
}: {
  title: string;
  note?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}): ReactElement {
  return (
    <section className="dp-sec">
      <div className="dp-sec__head">
        <h3 className="dp-sec__title">{title}</h3>
        {actions ? <div className="dp-sec__actions">{actions}</div> : null}
      </div>
      {note ? <p className="dp-sec__note">{note}</p> : null}
      {children}
    </section>
  );
}

/* ══ the record grid (APG data grid) ═══════════════════════════════════════
   The queue's grid belongs to another surface; this one displays records and deliberately does
   NOT implement row selection, so it also does not advertise `aria-multiselectable` or
   `aria-selected`. Announcing a selection model that does not exist is the same class of defect
   as announcing a row position that is not the logical one.

   Arrow keys CLAMP. Wrapping is layout-grid behaviour and it destroys the positional model an
   engineer builds while scanning a table of ports. */

export interface GridColumn<T> {
  id: string;
  header: string;
  /** A CSS grid track, e.g. "7rem" or "minmax(9rem, 1fr)". */
  width: string;
  align?: "start" | "end";
  render: (row: T) => ReactNode;
  /** Plain text for the cell's `title`, where `render` produces a glyph or a wrapped node. */
  text?: (row: T) => string;
  /** Exactly one column should set this: it becomes the row's `rowheader` and sticks on scroll. */
  rowHeader?: boolean;
}

const clamp = (n: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, n));

/** Anything the browser would put in the sequential focus order by default, or that says it wants
 *  to be there. The cells themselves (`data-r`) are the grid's own roving stops and are skipped. */
const FOCUSABLE =
  'a[href], area[href], button, input, select, textarea, iframe, summary, audio[controls], video[controls], [contenteditable]:not([contenteditable="false"]), [tabindex]';

/** Take every interactive descendant of a cell out of the tab sequence (see RecordGrid). */
function retireInnerStops(grid: HTMLElement): void {
  for (const el of grid.querySelectorAll<HTMLElement>(FOCUSABLE)) {
    if (el.hasAttribute("data-r") || el.tabIndex === -1) continue;
    el.tabIndex = -1;
  }
}

export function RecordGrid<T>({
  id,
  label,
  columns,
  rows,
  rowKey,
  describedBy,
}: {
  id: string;
  label: string;
  columns: readonly GridColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T, i: number) => string;
  describedBy?: string;
}): ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<[number, number]>([0, 0]);

  /* Derived rather than corrected in an effect: the row count changes whenever the selection
     changes, and an effect would leave one render frame pointing a roving tabindex at a cell that
     no longer exists — which drops the grid out of the tab order entirely. */
  const r = clamp(pos[0], 0, rows.length);
  const c = clamp(pos[1], 0, Math.max(0, columns.length - 1));

  const goto = useCallback((nr: number, nc: number) => {
    const next: [number, number] = [clamp(nr, 0, rows.length), clamp(nc, 0, Math.max(0, columns.length - 1))];
    setPos(next);
    ref.current
      ?.querySelector<HTMLElement>(`[data-r="${next[0]}"][data-c="${next[1]}"]`)
      ?.focus();
  }, [rows.length, columns.length]);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    const target = e.target as HTMLElement;
    const cell = target.closest<HTMLElement>('[role="gridcell"],[role="rowheader"],[role="columnheader"]');
    if (!cell) return;
    const inControl = target !== cell;

    if (inControl) {
      // F2/Escape leave cell-content mode and hand navigation back to the grid (APG).
      if (e.key === "Escape" || e.key === "F2") {
        e.preventDefault();
        cell.focus();
      }
      return;
    }

    switch (e.key) {
      case "ArrowRight": e.preventDefault(); goto(r, c + 1); break;
      case "ArrowLeft": e.preventDefault(); goto(r, c - 1); break;
      case "ArrowDown": e.preventDefault(); goto(r + 1, c); break;
      case "ArrowUp": e.preventDefault(); goto(r - 1, c); break;
      case "Home":
        e.preventDefault();
        if (e.ctrlKey || e.metaKey) goto(0, 0);
        else goto(r, 0);
        break;
      case "End":
        e.preventDefault();
        if (e.ctrlKey || e.metaKey) goto(rows.length, columns.length - 1);
        else goto(r, columns.length - 1);
        break;
      case "PageDown": e.preventDefault(); goto(r + 5, c); break;
      case "PageUp": e.preventDefault(); goto(r - 5, c); break;
      case "Enter":
      case "F2": {
        const inner = cell.querySelector<HTMLElement>("button:not([disabled]),a[href],input,select");
        if (inner) {
          e.preventDefault();
          inner.focus();
        }
        break;
      }
      default: break;
    }
  };

  /* ONE tab stop, whatever the cells render (APG grid; acceptance D1). A column's `render` is free to
     produce a control — a cite button, a port's interface/physical links — and a control is in the
     tab sequence by default. MEASURED (W6 gate, 2026-09-25, core1): "Ports on core1" held 31 stops,
     "Endpoints on core1" 2 and "Routing table for core1" 9. Every interactive descendant of a cell
     is taken out of the sequence here, structurally (any focusable element, not a list of
     components), and stays reachable from its cell with Enter/F2 (see onKeyDown), which focuses it
     programmatically. Re-applied after every commit of this grid and on any DOM change inside it,
     because a cell's own component can mount a control in a render the grid never sees. */
  useLayoutEffect(() => {
    if (ref.current) retireInnerStops(ref.current);
  });
  useLayoutEffect(() => {
    const g = ref.current;
    if (!g || typeof MutationObserver === "undefined") return;
    const mo = new MutationObserver(() => retireInnerStops(g));
    mo.observe(g, { childList: true, subtree: true, attributes: true, attributeFilter: ["tabindex", "href", "disabled", "contenteditable"] });
    return () => mo.disconnect();
  }, []);

  const cols = columns.map((col) => col.width).join(" ");
  const style = { "--rg-cols": cols } as CSSProperties;

  return (
    <div className="rg__scroll">
      <div
        ref={ref}
        role="grid"
        id={id}
        aria-label={label}
        aria-describedby={describedBy}
        aria-rowcount={rows.length + 1}
        aria-colcount={columns.length}
        className="rg"
        style={style}
        onKeyDown={onKeyDown}
      >
        <div role="row" aria-rowindex={1} className="rg__row rg__row--head">
          {columns.map((col, ci) => (
            <span
              key={col.id}
              role="columnheader"
              aria-colindex={ci + 1}
              data-r={0}
              data-c={ci}
              data-align={col.align ?? "start"}
              data-sticky={col.rowHeader ? "true" : undefined}
              tabIndex={r === 0 && c === ci ? 0 : -1}
              className="rg__cell rg__cell--head"
            >
              {col.header}
            </span>
          ))}
        </div>
        {rows.map((row, ri) => (
          <div key={rowKey(row, ri)} role="row" aria-rowindex={ri + 2} className="rg__row">
            {columns.map((col, ci) => {
              const title = col.text?.(row);
              return (
                <span
                  key={col.id}
                  role={col.rowHeader ? "rowheader" : "gridcell"}
                  aria-colindex={ci + 1}
                  data-r={ri + 1}
                  data-c={ci}
                  data-align={col.align ?? "start"}
                  data-sticky={col.rowHeader ? "true" : undefined}
                  tabIndex={r === ri + 1 && c === ci ? 0 : -1}
                  title={title}
                  className="rg__cell"
                >
                  {col.render(row)}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ══ device: identity ══════════════════════════════════════════════════════ */

function UncollectedBanner({ device, onOpenCite }: { device: Device; onOpenCite: (c: Cite) => void }): ReactElement | null {
  if (device.collected) {
    return device.inventoried ? null : (
      <div className="dp-banner dp-banner--partial" role="note">
        <p className="dp-banner__title">Reached, but not inventoried</p>
        <p className="dp-banner__text">
          The collector reached {device.host} but no inventory record (model, serial, software)
          was produced for it. Those fields below are absences, not empty boxes.
        </p>
        <CiteButton cite={device.cite} onOpen={onOpenCite} />
      </div>
    );
  }
  return (
    <div className="dp-banner dp-banner--uncollected" role="note">
      <p className="dp-banner__title">Not assessed — this device was never reached</p>
      <p className="dp-banner__text">
        {device.host} is present only because a neighbour&rsquo;s cable map names it. Nothing below
        is a measurement of its state: we hold no interfaces, no routing table, no configuration
        and no score for it. Its absence from a list on this pane means we did not look, not that
        there is nothing there.
      </p>
      <CiteButton cite={device.cite} onOpen={onOpenCite} />
    </div>
  );
}

/**
 * A number that is identical on EVERY inventoried device in the fleet is a producer placeholder,
 * not a measurement — and "Power supplies 0" on a WS-C3850-24T that has a serial and a software
 * version is plainly not a count. The snapshot is upstream of us, so the honest move is the one
 * this pane already makes for the health score: show the number the source carries AND the
 * reconciliation, rather than suppressing it or laundering it into a fact.
 *
 * Computed from `fabric.devices`, never hardcoded (SSOT Law 1): the note disappears by itself the
 * day the collector starts reporting real counts.
 */
/* STRUCTURAL, not a named list (2026-09-22 critic, B1). The detector used to run over power
   supplies and modules only, so data_quality — 1 on all 23 inventoried devices — printed as a
   clean top score beside fields the same pane calls not observed. It now runs over EVERY numeric
   field the producer carries; `order` is excluded because it is this app's own layout index, not a
   producer measurement. A field joins the map only when every inventoried device reports the same
   number, so the map empties itself the day the collector reports real per-device values. */
const NOT_PRODUCER_FIELDS: ReadonlySet<string> = new Set(["order"]);
const INVENTORIED_DEVICES = fabric.devices.filter((d) => d.inventoried);
const INVENTORIED = INVENTORIED_DEVICES.length;
export const FLEET_CONSTANTS: ReadonlyMap<string, number> = (() => {
  const out = new Map<string, number>();
  if (INVENTORIED < 2) return out;
  const keys = new Set<string>();
  for (const d of INVENTORIED_DEVICES) for (const k of Object.keys(d)) keys.add(k);
  for (const k of keys) {
    if (NOT_PRODUCER_FIELDS.has(k)) continue;
    const vals = INVENTORIED_DEVICES.map((d) => (d as unknown as Record<string, unknown>)[k]);
    if (!vals.every((v) => typeof v === "number" && Number.isFinite(v))) continue;
    if (new Set(vals).size === 1) out.set(k, vals[0] as number);
  }
  return out;
})();
const fleetConstant = (deviceField: keyof Device): number | null => FLEET_CONSTANTS.get(deviceField) ?? null;
const PSU_CONSTANT = fleetConstant("powerSupplies");
const MODULES_CONSTANT = fleetConstant("modules");

function FleetConstant({ n, constant, field, what, device, deviceField }: { n: number; constant: number | null; field: string; what: string; device?: Device; deviceField?: string }): ReactElement {
  /* A zero every inventoried device reports is a likely ABSENCE, and is rendered through the
     not-observed path — the same owner (core/placeholders.ts) the Inspector's field table reads. It
     used to print the digit 0 first and qualify it after, which still displays a measurement. */
  const ph = device !== undefined && deviceField !== undefined ? placeholderZero(device, deviceField) : null;
  if (ph !== null) return <NotObserved what={what} why={`${ph.reason} (${field})`} />;
  if (constant === null || n !== constant) return <>{String(n)}</>;
  return (
    <>
      {String(n)}{" "}
      <span className="dp-quiet">
        — the snapshot reports {String(constant)} {what} for all {INVENTORIED} inventoried devices
        {constant === 0 ? ", so this field is very likely uncollected rather than counted" : ", so it does not distinguish one device from another here"} (
        <span className="dp-mono">{field}</span>)
      </span>
    </>
  );
}

/**
 * The producer's `data_quality` with its scale and meaning (engine: analyze.py compute_data_quality):
 * the FRACTION, 0 to 1, of the essential show-command set whose output file was present and
 * non-empty. It measures capture presence, not what was parsed from it, so a 1 here sits beside
 * software version or uptime shown as not observed without contradicting them — and must never be
 * read as "this device's record is complete" (2026-09-22 critic, B1).
 */
function DataQuality({ n }: { n: number }): ReactElement {
  return (
    <>
      {String(n)}{" "}
      <span className="dp-quiet">
        on a 0–1 scale (<span className="dp-mono">data_quality</span>): the share of the producer&rsquo;s essential
        show commands whose output was captured. It measures capture presence, not parse yield, so it does not
        vouch for any field shown as not observed on this device
        {fleetConstant("dataQuality") === n
          ? `. All ${INVENTORIED} inventoried devices report ${n}, so it does not distinguish one device from another here.`
          : "."}
      </span>
    </>
  );
}

function IdentitySection({ device, onOpenCite }: { device: Device; onOpenCite: (c: Cite) => void }): ReactElement {
  const links = linksByHost.get(device.host) ?? [];
  const ev = (field: keyof Device): { cite: Cite } | { derived: string } => deviceFieldEvidence(device, field);
  const rows: EvidenceRow[] = [
    { k: "Host", v: <span className="dp-mono">{device.host}</span>, ...ev("host") },
    { k: "Kind", v: device.kind, ...ev("kind") },
    {
      k: "Role",
      v: orNotObserved(device.role, (s) => s, {
        what: "role",
        why: "the engine assigned no role to this device",
        compact: true,
      }),
      ...ev("role"),
    },
    {
      k: "Tier",
      v: orNotObserved(device.tier, (t) => `${t} — ${describeTier(t)}`, { what: "tier", compact: true }),
      ...ev("tier"),
    },
    { k: "State", v: <StateDot state={device.opStatus} showLabel />, ...ev("opStatus") },
    {
      k: "Platform",
      v: orNotObserved(device.platform, (s) => s, { what: "platform", compact: true }),
      ...ev("platform"),
    },
    { k: "Model", v: orNotObserved(device.model, (s) => <span className="dp-mono">{s}</span>, { what: "model", compact: true }), ...ev("model") },
    { k: "Serial", v: orNotObserved(device.serial, (s) => <span className="dp-mono">{s}</span>, { what: "serial", compact: true }), ...ev("serial") },
    { k: "Software", v: orNotObserved(device.swVersion, (s) => <span className="dp-mono">{s}</span>, { what: "software version", compact: true }), ...ev("swVersion") },
    { k: "Uptime", v: orNotObserved(device.uptime, (s) => s, { what: "uptime", compact: true }), ...ev("uptime") },
    {
      k: "Power supplies",
      v: orNotObserved(device.powerSupplies, (n) => <FleetConstant n={n} constant={PSU_CONSTANT} field="num_power_supplies" what="power supplies" device={device} deviceField="powerSupplies" />, {
        what: "power supplies",
        compact: true,
      }),
      ...ev("powerSupplies"),
    },
    {
      k: "Modules",
      v: orNotObserved(device.modules, (n) => <FleetConstant n={n} constant={MODULES_CONSTANT} field="num_modules" what="modules" device={device} deviceField="modules" />, {
        what: "modules",
        compact: true,
      }),
      ...ev("modules"),
    },
    {
      k: "Badges",
      ...ev("badges"),
      v:
        device.badges.length > 0 ? (
          <span className="dp-chips">
            {device.badges.map((b) => (
              <Chip key={b} mono>{b}</Chip>
            ))}
          </span>
        ) : device.collected ? (
          <span className="dp-quiet">none recorded</span>
        ) : (
          <NotObserved what="badges" why="the device was never reached" compact />
        ),
    },
    /* Routed through the same one-port-one-cable detector the link pane uses: AP-floor1 appears on
       17 cable records whose shared port Gi0 lets at most one of them be real. */
    {
      k: "Cables",
      v: cableCountPhrase(hostCableAccount(device.host, links)),
      derived: `counted by this application over the ${plural(links.length, "cable_map.cables record")} naming ${device.host}, with each disputed port counted once (analysis/port-claims.ts)`,
    },
  ];
  return (
    <Section title="Identity" note={<>Source record <CiteButton cite={device.cite} onOpen={onOpenCite} /></>}>
      <EvidenceKv rows={rows} onOpenCite={onOpenCite} />
    </Section>
  );
}

/** Tier membership is published by the engine as an ordered list; this names the tier, nothing more. */
function describeTier(t: number): string {
  const members = fabric.tiers[t];
  if (!members) return "tier not present in the published tier list";
  return `${plural(members.length, "device")} at this level`;
}

/* ══ device: health and its deductions ═════════════════════════════════════ */

const DEDUCTION_RE = /^(.*?)\s*\(-(\d+(?:\.\d+)?)\)\s*$/;
const CL_REF_RE = /^(CL-\d+)\b/;

interface ParsedDeduction {
  raw: string;
  label: string;
  points: number | null;
  crossLayerId: string | null;
}

export function parseDeduction(raw: string): ParsedDeduction {
  const m = DEDUCTION_RE.exec(raw);
  const label = m?.[1] ?? raw;
  const pts = m?.[2];
  return {
    raw,
    label,
    points: pts === undefined ? null : Number(pts),
    crossLayerId: CL_REF_RE.exec(label)?.[1] ?? null,
  };
}

function HealthSection({ device, onOpenCite }: { device: Device; onOpenCite: (c: Cite) => void }): ReactElement {
  const parsed = useMemo(() => device.deductions.map(parseDeduction), [device.deductions]);
  const priced = parsed.filter((d) => d.points !== null);
  const sum = priced.reduce((a, d) => a + (d.points ?? 0), 0);
  const maxPts = priced.reduce((a, d) => Math.max(a, d.points ?? 0), 0);
  const unpriced = parsed.length - priced.length;

  /* A score is a sum of deductions, and a domain that was never assessed on this device could not
     deduct. So a high band on a device whose protocols, routing table or ACLs were never collected
     partly measures the ABSENCE of evidence: podacc1 read "90 Excellent" in the healthy tone beside
     "Its routing and switching protocols were not assessed here" (2026-09-22 auditor, B1). The
     unassessed domains are named next to the band, read from the same per-host coverage owners the
     sections below use, and a favourable band is drawn in the neutral tone while any of them is
     unassessed — an unfavourable band is left as is, because its deductions were observed. */
  const presentation = presentBand(device);
  const { unassessed, qualified, tone } = presentation;

  return (
    <Section title="Health">
      {/* Score is a row of this grid, not a widget parked above it. The band pill rides the value's
          own baseline: it is the same measurement stated as a band, so putting it under a separate
          right-aligned caption invented a second column that nothing else in the pane uses. */}
      <EvidenceKv
        rows={[
          {
            k: "Score",
            ...deviceFieldEvidence(device, "score"),
            v: (
              <>
                <Meter label="Health score" value={device.score} max={100} tone={tone} />
                {/* The band's own citation names the record the band was READ from (health_scores),
                    not the inventory record, which holds no band and no score (B6). */}
                <Band band={presentation} cite={device.fieldCites?.band ?? device.cite} onOpenCite={onOpenCite} {...(qualified ? { className: "dp-band--partial" } : {})} />
                {unassessed.length > 0 ? (
                  <span className="dp-score-gap" data-score-unassessed={unassessed.length}>
                    {`score does not reflect: ${unassessed.join(", ")} — never assessed on ${device.host}, so nothing there could deduct`}
                  </span>
                ) : null}
              </>
            ),
          },
          {
            k: "Criticality",
            v: orNotObserved(device.criticality, (n) => <FleetConstant n={n} constant={fleetConstant("criticality")} field="criticality" what="criticality" />, {
              what: "criticality",
              compact: true,
            }),
            ...deviceFieldEvidence(device, "criticality"),
          },
          {
            k: "Data quality",
            v: orNotObserved(device.dataQuality, (n) => <DataQuality n={n} />, { what: "data quality", compact: true }),
            ...deviceFieldEvidence(device, "dataQuality"),
          },
        ]}
        onOpenCite={onOpenCite}
      />

      <h4 className="dp-sub">Deductions that produced this score</h4>
      {parsed.length === 0 ? (
        device.collected ? (
          <Empty
            title="No deductions recorded"
            reason={`The snapshot lists no scoring deductions for ${device.host}. A score with no itemisation cannot be read back to its inputs.`}
          />
        ) : (
          <NotObserved
            what="deductions"
            why="the device was never reached, so it was never scored"
            cite={device.cite}
            onOpenCite={onOpenCite}
          />
        )
      ) : (
        <>
          <ol className="dp-deduct">
            {parsed.map((d) => (
              <li key={d.raw} className="dp-deduct__row">
                <span className="dp-deduct__label">
                  {d.crossLayerId ? (
                    <>
                      <span className="dp-mono">{d.crossLayerId}</span>
                      {d.label.slice(d.crossLayerId.length)}
                    </>
                  ) : (
                    d.label
                  )}
                </span>
                <span className="dp-deduct__bar" aria-hidden="true">
                  <span
                    className="dp-deduct__fill"
                    style={{ inlineSize: maxPts > 0 ? `${((d.points ?? 0) / maxPts) * 100}%` : "0%" }}
                  />
                </span>
                <span className="dp-deduct__pts">
                  {d.points === null ? (
                    <NotObserved what="deduction points" compact />
                  ) : (
                    <>&minus;{d.points}</>
                  )}
                </span>
              </li>
            ))}
          </ol>
          <p className="dp-arith">
            {priced.length === parsed.length
              ? `All ${parsed.length} deductions carry a point value; they total ${sum}.`
              : `${priced.length} of ${parsed.length} deductions carry a point value; those total ${sum}. ${plural(unpriced, "deduction")} carries none.`}{" "}
            {device.score === null ? (
              <>The published score is not observed, so the itemisation cannot be checked against it.</>
            ) : (
              <>
                The published score is {device.score} of 100, and 100 &minus; {sum} ={" "}
                {100 - sum}. The snapshot does not carry the arithmetic that produced the score —
                it carries a separate <span className="dp-mono">criticality</span> weighting of{" "}
                {device.criticality === null ? "not observed" : device.criticality} whose
                application is not stated. The {Math.abs(100 - sum - device.score)}-point
                difference is shown rather than reconciled.
              </>
            )}
          </p>
        </>
      )}
    </Section>
  );
}

/* ══ device: failure impact — ours next to theirs ══════════════════════════ */

function ImpactSection({ device, onOpenCite }: { device: Device; onOpenCite: (c: Cite) => void }): ReactElement {
  const ours = useMemo(() => failureImpact(device.host), [device.host]);
  const theirs = device.impact;
  const eps = ours.strandedEndpoints;

  /* The snapshot's FHRP / backup counts, checked against this device's OWN L3 records. core2's
     failure_impact read "FHRP covered 0 / Backed up 0" while its Routing tab showed it HSRP Standby
     on VLAN 10 and Active on VLAN 20 — a zero the pane's own evidence contradicts, drawn as a
     measurement (2026-09-21 critic, B1). The source value is still shown verbatim; the
     contradiction is stated beside it, the way the score arithmetic is. */
  const impactChecks = useMemo(() => {
    const l3 = l3ByHost.get(device.host) ?? [];
    const withFhrp = l3.filter((r) => r.fhrp !== null);
    const fhrpVlans = [...new Set(withFhrp.map((r) => (r.vlan === null ? "(unnumbered)" : String(r.vlan))))];
    /* A backup gateway is another host holding the same virtual address — read from the L3 records
       themselves, never from a role word. */
    const peered = l3.filter((r) => r.vip !== null && fabric.l3.some((o) => o.host !== device.host && o.vip === r.vip));
    const peeredVlans = [...new Set(peered.map((r) => (r.vlan === null ? "(unnumbered)" : String(r.vlan))))];
    const out: { field: string; theirs: number; ours: number; detail: string; cites: Cite[] }[] = [];
    if (theirs !== null && theirs.fhrp !== null && fhrpVlans.length > theirs.fhrp) {
      out.push({
        field: "failure_impact.fhrp",
        theirs: theirs.fhrp,
        ours: fhrpVlans.length,
        detail: `this device's own L3 records carry an FHRP group on VLAN ${fhrpVlans.join(", ")} (${withFhrp.map((r) => `${r.fhrp}${r.fhrpRole === null ? "" : ` ${r.fhrpRole}`}`).join(", ")})`,
        cites: withFhrp.map((r) => r.cite),
      });
    }
    if (theirs !== null && theirs.backup !== null && peeredVlans.length > theirs.backup) {
      out.push({
        field: "failure_impact.backup",
        theirs: theirs.backup,
        ours: peeredVlans.length,
        detail: `another collected host holds the same virtual gateway address on VLAN ${peeredVlans.join(", ")}`,
        cites: peered.map((r) => r.cite),
      });
    }
    return out;
  }, [device.host, theirs]);

  const ourStranded = ours.certainty === "not-determinable" ? null : ours.newlyStranded.length;
  const ourSummary =
    ourStranded === null
      ? "not determinable"
      : `${plural(ourStranded, "host")} stranded, ${
          eps.floorTotal === null
            ? "an unknown number of endpoints"
            : `at least ${plural(eps.floorTotal, "endpoint")}`
        }`;
  const theirSummary =
    theirs === null
      ? "no failure_impact record"
      : `${theirs.stranded === null ? "not observed" : plural(theirs.stranded, "endpoint")} across ${
          theirs.vlans === null ? "not observed" : plural(theirs.vlans, "VLAN")
        }`;

  /* "Disagree" is reserved for a qualitative conflict between two OBSERVED answers (one says
     partition, the other says none). An absent side is not an answer: it used to be counted here,
     so for a topology-only device — no failure_impact record AND a radius that is not determinable —
     the card read "The two measures disagree" over two columns that both said "not observed"
     (critic B1, 2026-09-21). A missing measure is stated as missing, on whichever side it is. */
  const q = ours.engine.qualitative;
  const oursAbsent = ours.certainty === "not-determinable" || q === "ours-not-determined";
  const theirsAbsent = q === "engine-silent";
  const disagrees = q === "engine-impact-only" || q === "ours-impact-only";
  const compareHead = disagrees
    ? "The two measures disagree"
    : oursAbsent && theirsAbsent
      ? "Neither measure exists for this device"
      : theirsAbsent
        ? "Only our measure exists — the snapshot carries none to compare"
        : oursAbsent
          ? "Only the snapshot's measure exists — ours could not be computed"
          : "How the two measures compare";

  return (
    <Section
      title="Failure impact"
      note="Two independent answers to the same question, from different measures. Both are rendered; neither is suppressed."
    >
      <div className="dp-cmp">
        <div className="dp-cmp__col">
          <h4 className="dp-cmp__head">The snapshot&rsquo;s own failure_impact</h4>
          {theirs === null ? (
            <NotObserved
              what="failure impact"
              why={`the snapshot carries no failure_impact record for ${device.host}`}
              cite={device.cite}
              onOpenCite={onOpenCite}
            />
          ) : (
            <EvidenceKv
              rows={[
                {
                  k: "Severity",
                  v:
                    asSeverity(theirs.severity) !== null ? (
                      <SeverityBadge severity={asSeverity(theirs.severity) as Severity} />
                    ) : (
                      orNotObserved(theirs.severity, (s) => s, { what: "impact severity", compact: true })
                    ),
                  cite: theirs.cite,
                },
                { k: "Endpoints stranded", v: orNotObserved(theirs.stranded, (n) => n.toLocaleString("en-GB"), { what: "stranded endpoints", compact: true }), cite: theirs.cite },
                { k: "VLANs", v: orNotObserved(theirs.vlans, (n) => String(n), { what: "VLAN count", compact: true }), cite: theirs.cite },
                { k: "Hard partitions", v: orNotObserved(theirs.hard, (n) => String(n), { what: "hard partitions", compact: true }), cite: theirs.cite },
                { k: "Backed up", v: orNotObserved(theirs.backup, (n) => String(n), { what: "backed-up VLANs", compact: true }), cite: theirs.cite },
                { k: "FHRP covered", v: orNotObserved(theirs.fhrp, (n) => String(n), { what: "FHRP-covered VLANs", compact: true }), cite: theirs.cite },
                { k: "Detail", v: orNotObserved(theirs.detail, (s) => s, { what: "impact detail", compact: true }), wide: true, cite: theirs.cite },
              ]}
              onOpenCite={onOpenCite}
            />
          )}
          {impactChecks.map((c) => (
            <div key={c.field} className="dp-disagree dp-disagree--live" data-impact-check={c.field}>
              <p className="dp-disagree__head">{`${c.field} is contradicted by this device's own records`}</p>
              <p className="dp-disagree__body">
                {`The snapshot's ${c.field} says ${c.theirs}; ${c.detail} — at least ${c.ours}. Both are shown; neither is suppressed, so the count above is not read as a measurement of zero.`}
              </p>
              <p className="dp-disagree__body">
                {c.cites.map((cite) => (
                  <CiteButton key={cite} cite={cite} onOpen={onOpenCite} />
                ))}
              </p>
            </div>
          ))}
        </div>

        <div className="dp-cmp__col">
          <h4 className="dp-cmp__head">Our computed blast radius</h4>
          <EvidenceKv
            rows={[
              { k: "Presence", v: ours.presence, derived: OUR_BLAST_BASIS },
              { k: "Certainty", v: <span data-certainty={ours.certainty} className="dp-certainty">{ours.certainty}</span>, derived: OUR_BLAST_BASIS },
              {
                k: "Articulation point",
                derived: OUR_BLAST_BASIS,
                v: ours.certainty === "not-determinable"
                  ? <NotObserved what="articulation point" why={ours.reasoningLimit ?? "the radius could not be computed"} compact />
                  : ours.isArticulationPoint ? "yes — removing it partitions the graph" : "no",
              },
              {
                k: "Components",
                derived: OUR_BLAST_BASIS,
                /* "1 before → 1 after" is a measured no-impact result. It may not be shown for a
                   subject that was never in the connectivity graph: the two numbers are then
                   equal because nothing was computed, not because nothing would break. The
                   sibling rows on this very card already guard on exactly this. */
                v: ours.certainty === "not-determinable"
                  ? <NotObserved what="component count" why={ours.reasoningLimit ?? ours.presence} compact />
                  : `${ours.componentsBefore} before → ${ours.componentsAfter} after`,
              },
              {
                k: "Newly stranded",
                derived: OUR_BLAST_BASIS,
                v: ourStranded === null || ours.certainty === "not-determinable"
                  ? <NotObserved what="stranded hosts" why={ours.reasoningLimit ?? ours.presence} compact />
                  : ours.newlyStranded.length === 0
                    ? "none"
                    : <span className="dp-mono dp-wrap">{ours.newlyStranded.join(", ")}</span>,
              },
              {
                k: "Endpoints behind the cut",
                derived: `${OUR_BLAST_BASIS}, floored by the endpoint_identity records behind the cut`,
                v: orNotObserved(eps.floorTotal, (n) => `at least ${n.toLocaleString("en-GB")}`, {
                  what: "endpoints behind the cut",
                  why: eps.note,
                  compact: true,
                }),
              },
              {
                k: "Severed cables",
                derived: OUR_BLAST_BASIS,
                /* The same port-dispute ceiling as the Cables row: 17 severed RECORDS on a port
                   that terminates one cable is not 17 severed cables. */
                v: (() => {
                  const ids = new Set(ours.severedLinks.map((s) => s.linkId));
                  const acct = hostCableAccount(device.host, fabric.links.filter((l) => ids.has(l.id)));
                  return acct.disputedLinkIds.length === 0 ? String(acct.records) : cableCountPhrase(acct);
                })(),
              },
            ]}
            onOpenCite={onOpenCite}
          />
        </div>
      </div>

      <p className="dp-claim">{ours.claim}</p>

      <div className={cx("dp-disagree", disagrees && "dp-disagree--live")}>
        <p className="dp-disagree__head">
          {compareHead}
        </p>
        <p className="dp-disagree__body">{ours.engine.note}</p>
        {disagrees ? (
          <p className="dp-disagree__t9">
            {T9_disagreement(
              device.host,
              ourSummary,
              "failure_impact",
              theirSummary,
              theirs?.cite ?? device.cite,
            )}
          </p>
        ) : null}
      </div>

      {ours.caveats.length > 0 ? (
        <>
          <h4 className="dp-sub">Caveats on our number</h4>
          <ul className="dp-caveats">
            {ours.caveats.map((cv) => (
              <li key={cv}>{cv}</li>
            ))}
          </ul>
        </>
      ) : null}

      {ours.assumptions.length > 0 ? (
        <>
          <h4 className="dp-sub">Assumptions it rests on</h4>
          <ul className="dp-caveats">
            {ours.assumptions.map((a) => (
              <li key={a.id}>
                {a.statement}
                {a.cites.slice(0, 2).map((ct) => (
                  <CiteButton key={ct} cite={ct} onOpen={onOpenCite} />
                ))}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {ours.alternateProjections.filter((p) => p.differs).map((p) => (
        <p key={`${p.options.transit}-${p.options.unknownStatus}`} className="dp-altproj">
          <span className="dp-altproj__k">
            Under transit “{p.options.transit}” / unknown-status “{p.options.unknownStatus}”
          </span>
          {p.note}
        </p>
      ))}
    </Section>
  );
}

/* ══ device: protocols ═════════════════════════════════════════════════════ */

function ProtocolSection({ device, onOpenCite }: { device: Device; onOpenCite: (c: Cite) => void }): ReactElement {
  const rows = protocolsByHost.get(device.host) ?? [];
  if (rows.length === 0) {
    return (
      <Section title="Protocol health">
        {device.collected ? (
          <Empty
            title="No protocol records"
            reason={`The collection produced no protocol_health row for ${device.host}. Its routing and switching protocols were not assessed here.`}
          />
        ) : (
          <NotObserved what="protocol health" why="the device was never reached" compact />
        )}
      </Section>
    );
  }
  return (
    <Section title="Protocol health">
      <ul className="dp-list">
        {rows.map((p) => {
          const sev = asSeverity(p.severity);
          return (
            <li key={p.cite} className="dp-list__row">
              <span className="dp-list__lead">
                {sev ? <SeverityBadge severity={sev} compact /> : <NotObserved what="severity" compact />}
                <span className="dp-mono">{orNotObserved(p.protocol, (s) => s, { what: "protocol", compact: true })}</span>
              </span>
              <span className="dp-list__main">
                {orNotObserved(p.summary, (s) => s, { what: "summary", compact: true })}
                {p.detail === null ? null : <span className="dp-quiet"> {p.detail}</span>}
              </span>
              <CiteButton cite={p.cite} onOpen={onOpenCite} />
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

/* ══ device: ports — the interface x physical-health OUTER join ════════════ */

interface PortRow {
  port: string;
  intf: InterfaceRecord | null;
  phys: PhysicalHealth | null;
}

export function joinPorts(host: string): PortRow[] {
  const intf = interfacesOf(host);
  const phys = physicalByHost.get(host) ?? [];
  const byPort = new Map<string, PortRow>();
  for (const i of intf) byPort.set(i.port, { port: i.port, intf: i, phys: null });
  for (const p of phys) {
    if (p.port === null) continue;
    const row = byPort.get(p.port);
    if (row) row.phys = p;
    // A physical-health row with no interface record is kept, not dropped: the port exists in the
    // collection and hiding it would make the interface list read as the complete port inventory.
    else byPort.set(p.port, { port: p.port, intf: null, phys: p });
  }
  return [...byPort.values()].sort((a, b) => a.port.localeCompare(b.port, "en", { numeric: true }));
}

/**
 * The reason a configuration-derived field is empty. "Not in the collected configuration" is an
 * observed NEGATIVE, and only true where that configuration was collected: for a port whose running
 * configuration was never collected (`runConfigObserved: false`) the same sentence turned a missing
 * record into a claim about it, on 19 core1/core2 ports (2026-09-22 critic, B1).
 */
function configAbsenceReason(intf: InterfaceRecord, observedNegative: string, field: string): string {
  return intf.runConfigObserved === true
    ? observedNegative
    : `the running configuration for this port was not collected, so its ${field} is unknown — not absent`;
}

/**
 * A configuration-derived field, rendered by what was actually observed.
 *
 * Three states, not two. A value renders as itself. An empty value over a COLLECTED running
 * configuration is an observed NEGATIVE ("none — not in a channel group"), so it renders as an
 * observed value: marking it "not observed" put presence in the absence marker's clothes and diluted
 * the one mark this product depends on (critic B1, access13 Gi0/1). Only an empty value over a
 * configuration that was never collected is "not observed", with the reason.
 */
function configField(
  intf: InterfaceRecord,
  value: string | null | undefined,
  render: (v: string) => ReactNode,
  o: { what: string; field: string; observedNegative: string },
): ReactNode {
  if (typeof value === "string" && value.trim() !== "") return render(value);
  if (intf.runConfigObserved === true) {
    return (
      <span className="dp-quiet" data-observed-negative="true" title={`${o.observedNegative} (collected configuration)`}>
        {`none — ${o.observedNegative}`}
      </span>
    );
  }
  return <NotObserved what={o.what} why={configAbsenceReason(intf, o.observedNegative, o.field)} compact />;
}

const num = (n: number | null | undefined, what: string): ReactNode =>
  orNotObserved(n, (v) => v.toLocaleString("en-GB"), { what, compact: true });

type PortField = "status" | "speed" | "duplex";

/**
 * A field BOTH port records carry, read from both.
 *
 * These columns used to render `intf?.x ?? phys?.x`: whenever the interface record existed its value
 * won and the physical-health row was never looked at. On 73 ports the two disagree on duplex
 * (interface "Full", physical-health "unknown") — on hosts that carry an open duplex-mismatch
 * finding — and the table printed a clean "Full". The coalesce was the defect, so it is replaced
 * for every field the two records share rather than for the one column that was caught: agreement
 * (or one side only) renders one value; disagreement renders both, each labelled with its source.
 */
/* Same value in two spellings is agreement, not a disagreement: the interface record writes speed
   as "1000" and the physical-health row as "1000Mb/s". Only the unit suffix is normalised. */
const sameValue = (a: string, b: string): boolean => {
  const norm = (v: string): string => v.trim().toLowerCase().replace(/\s*(mb\/s|mbps)$/, "");
  return norm(a) === norm(b);
};

function portFieldText(r: PortRow, field: PortField): string {
  const a = r.intf?.[field] ?? null;
  const b = r.phys?.[field] ?? null;
  if (a !== null && b !== null && !sameValue(a, b)) {
    return `records disagree: interface ${a}, physical-health ${b}`;
  }
  return String(a ?? b ?? "not observed");
}

function portField(r: PortRow, field: PortField): ReactNode {
  const a = r.intf?.[field] ?? null;
  const b = r.phys?.[field] ?? null;
  if (a !== null && b !== null && !sameValue(a, b)) {
    return (
      <span className="dp-split" title={portFieldText(r, field)} data-disagree="true">
        <span className="dp-split__mark" aria-hidden="true">≠</span>
        <span className="dp-split__v">{a}</span>
        <span className="dp-split__src">intf</span>
        <span className="dp-split__v">{b}</span>
        <span className="dp-split__src">phys</span>
        <span className="visually-hidden">{` — ${portFieldText(r, field)}`}</span>
      </span>
    );
  }
  return orNotObserved(a ?? b, (v) => v, { what: field, compact: true });
}

function PortsPanel({ device, onOpenCite }: { device: Device; onOpenCite: (c: Cite) => void }): ReactElement {
  const rows = useMemo(() => joinPorts(device.host), [device.host]);
  const known = hasInterfaceRecords(device.host);
  const noteId = `dp-ports-note-${device.host}`;

  if (!known && rows.length === 0) {
    return (
      <div className="dp-panel">
        <NotObserved
          what="interfaces"
          why={`no interface or physical-health record exists for ${device.host}; the collector never reached it, so its port inventory is unknown rather than empty`}
          cite={device.cite}
          onOpenCite={onOpenCite}
        />
      </div>
    );
  }

  const bothSides = rows.filter((r) => r.intf !== null && r.phys !== null).length;
  const intfOnly = rows.filter((r) => r.phys === null).length;
  const physOnly = rows.filter((r) => r.intf === null).length;

  const columns: GridColumn<PortRow>[] = [
    {
      id: "port",
      header: "Port",
      width: "7.5rem",
      rowHeader: true,
      text: (r) => r.port,
      render: (r) => <span className="dp-mono">{r.port}</span>,
    },
    {
      id: "records",
      header: "Records",
      width: "5.5rem",
      text: (r) => (r.intf && r.phys ? "interface + physical" : r.intf ? "interface only" : "physical only"),
      render: (r) =>
        r.intf && r.phys ? (
          <span className="dp-quiet">both</span>
        ) : r.intf ? (
          <NotObserved what="physical-health row" why="no physical_health record for this port" compact />
        ) : (
          <NotObserved what="interface record" why="no interface record for this port" compact />
        ),
    },
    {
      id: "status",
      header: "Status",
      width: "6.5rem",
      text: (r) => portFieldText(r, "status"),
      render: (r) => portField(r, "status"),
    },
    {
      id: "speed",
      header: "Speed",
      width: "5.5rem",
      align: "end",
      text: (r) => portFieldText(r, "speed"),
      render: (r) => portField(r, "speed"),
    },
    {
      id: "duplex",
      header: "Duplex",
      width: "5rem",
      text: (r) => portFieldText(r, "duplex"),
      render: (r) => portField(r, "duplex"),
    },
    {
      id: "media",
      header: "Media",
      width: "6.5rem",
      render: (r) => orNotObserved(r.phys?.media ?? r.intf?.linkType, (s) => s, { what: "media", compact: true }),
    },
    { id: "inerr", header: "In err", width: "4.5rem", align: "end", render: (r) => num(r.phys?.inputErrors, "input errors") },
    { id: "crc", header: "CRC", width: "4.5rem", align: "end", render: (r) => num(r.phys?.crcErrors, "CRC errors") },
    { id: "outerr", header: "Out err", width: "4.5rem", align: "end", render: (r) => num(r.phys?.outputErrors, "output errors") },
    /* Carried in every source row and previously dropped by the compiler, which made a counter the
       collector DID read look like one it never took. */
    { id: "latecoll", header: "Late coll", width: "5rem", align: "end", render: (r) => num(physExtra(r.phys).lateCollisions ?? null, "late collisions") },
    { id: "drops", header: "Drops", width: "4.5rem", align: "end", render: (r) => num(r.phys?.outputDrops, "output drops") },
    {
      id: "poe",
      header: "PoE",
      width: "5rem",
      render: (r) => orNotObserved(r.phys?.poe, (s) => s, { what: "PoE", compact: true }),
    },
    {
      id: "risk",
      header: "Risk",
      width: "8rem",
      text: (r) => (physUnassessedReason(r.phys) !== null ? "not assessed" : (r.phys?.risk ?? "not observed")),
      /* The engine's own "[NOT OBSERVED] - no 'show interfaces' counters for this port; L1 error
         rate NOT assessed" reaches the reader as the REASON, instead of being nulled to a bare
         "not observed" that says nothing about why. A risk string over a row with no measurement at
         all is withheld the same way (`physUnassessedReason`). */
      render: (r) => {
        const unassessed = physUnassessedReason(r.phys);
        return unassessed !== null
          ? <NotObserved what="risk flag" why={unassessed} compact />
          : orNotObserved(r.phys?.risk, (s) => s, { what: "risk flag", compact: true });
      },
    },
    {
      id: "sev",
      header: "Sev",
      width: "6rem", // wide enough for "not graded" (an unassessed row) without clipping
      render: (r) => <GradedSeverity severity={r.phys?.severity} unassessed={physUnassessedReason(r.phys)} />,
    },
    {
      id: "pc",
      header: "Channel",
      width: "6rem",
      render: (r) =>
        r.intf === null
          ? <NotObserved what="port-channel membership" why="no interface record for this port" compact />
          : configField(r.intf, r.intf.portChannel, (s) => <span className="dp-mono">{s}</span>, {
              what: "port-channel membership",
              field: "channel-group membership",
              observedNegative: "not in a channel group",
            }),
    },
    {
      id: "desc",
      header: "Description",
      width: "minmax(11rem, 1fr)",
      text: (r) =>
        r.intf?.description ?? (r.intf?.runConfigObserved === true ? "none — no description configured" : "not observed"),
      render: (r) =>
        r.intf === null
          ? <NotObserved what="description" why="no interface record for this port" compact />
          : configField(r.intf, r.intf.description, (s) => s, {
              what: "description",
              field: "description",
              observedNegative: "no description configured",
            }),
    },
    {
      id: "cite",
      header: "Evidence",
      width: "11rem",
      render: (r) => (
        <span className="rg__cites">
          {r.intf ? <CiteButton cite={r.intf.cite} onOpen={onOpenCite} label="intf" /> : null}
          {r.phys ? <CiteButton cite={r.phys.cite} onOpen={onOpenCite} label="phys" /> : null}
        </span>
      ),
    },
  ];

  return (
    <div className="dp-panel">
      <p id={noteId} className="dp-sec__note">
        {plural(rows.length, "port")} — an outer join of {plural(interfacesOf(device.host).length, "interface record")} and{" "}
        {plural((physicalByHost.get(device.host) ?? []).length, "physical-health row")}. {bothSides} carry both;{" "}
        {intfOnly} have no physical-health row and {physOnly} have no interface record. A one-sided
        row is marked on the row, not removed from the table.
      </p>
      <RecordGrid
        id={`dp-ports-${device.host}`}
        label={`Ports on ${device.host}`}
        describedBy={noteId}
        columns={columns}
        rows={rows}
        rowKey={(r) => r.port}
      />
      <EndpointsBlock host={device.host} onOpenCite={onOpenCite} />
    </div>
  );
}

function EndpointsBlock({ host, onOpenCite }: { host: string; onOpenCite: (c: Cite) => void }): ReactElement {
  const eps = endpointsByHost.get(host) ?? [];
  const columns: GridColumn<(typeof eps)[number]>[] = [
    { id: "port", header: "Port", width: "6.5rem", rowHeader: true, text: (e) => e.port ?? "not observed", render: (e) => orNotObserved(e.port, (s) => <span className="dp-mono">{s}</span>, { what: "port", compact: true }) },
    { id: "vlan", header: "VLAN", width: "4.5rem", align: "end", render: (e) => orNotObserved(e.vlan, (s) => s, { what: "VLAN", compact: true }) },
    { id: "ip", header: "IP", width: "8.5rem", render: (e) => orNotObserved(e.ip, (s) => <span className="dp-mono">{s}</span>, { what: "IP address", compact: true }) },
    { id: "mac", header: "MAC", width: "9.5rem", render: (e) => orNotObserved(e.mac, (s) => <span className="dp-mono">{s}</span>, { what: "MAC address", compact: true }) },
    { id: "macs", header: "MACs", width: "4.5rem", align: "end", render: (e) => num(e.macCount, "MAC count") },
    { id: "vendor", header: "Vendor", width: "7rem", render: (e) => orNotObserved(e.vendor, (s) => s, { what: "vendor", compact: true }) },
    { id: "class", header: "Class", width: "8rem", render: (e) => orNotObserved(e.endpointClass, (s) => s, { what: "endpoint class", compact: true }) },
    { id: "conf", header: "Confidence", width: "7.5rem", render: (e) => orNotObserved(e.confidence, (s) => s, { what: "confidence", compact: true }) },
    { id: "ev", header: "Basis", width: "minmax(9rem, 1fr)", text: (e) => e.evidence ?? "not observed", render: (e) => orNotObserved(e.evidence, (s) => s, { what: "evidence", compact: true }) },
    { id: "cite", header: "Evidence", width: "9rem", render: (e) => <CiteButton cite={e.cite} onOpen={onOpenCite} /> },
  ];
  return (
    <Section
      title="Endpoints observed behind this device"
      note="A floor, not an inventory: these are the endpoint_identity records the collection produced. A port with no record is not a port with nothing on it."
    >
      {eps.length === 0 ? (
        <Empty
          title="No endpoint records"
          reason={`The collection produced no endpoint_identity row for ${host}. What is attached to it is unknown in size, not zero.`}
        />
      ) : (
        <RecordGrid
          id={`dp-eps-${host}`}
          label={`Endpoints on ${host}`}
          columns={columns}
          rows={eps}
          rowKey={(e, i) => `${e.cite}-${i}`}
        />
      )}
    </Section>
  );
}

/* ══ device: routing ═══════════════════════════════════════════════════════ */

function RoutingPanel({ device, onOpenCite }: { device: Device; onOpenCite: (c: Cite) => void }): ReactElement {
  const l3 = l3ByHost.get(device.host) ?? [];
  const routes = routesOf(device.host);
  const rib = hasRib(device.host);
  const cov = fabric.coverage;
  /* A collected table cannot testify to its own completeness: four connected routes look the same
     whether they are everything or a sliver. The snapshot does testify (./rib-completeness.ts), and
     this tab used to say "on those entries and on nothing else" over core2's four routes while the
     snapshot recorded OSPF/BGP/EIGRP not collected and a 240-prefix EVPN peer (2026-09-22 critic, B7). */
  const partial = rib ? ribIncompleteness(device.host) : [];

  return (
    <div className="dp-panel">
      <p className={cx("dp-scope", !rib && "dp-scope--absent", partial.length > 0 && "dp-scope--partial")}>
        {rib ? (
          partial.length > 0 ? (
            <>
              A routing table was collected for {device.host}: {plural(routes.length, "entry", "entries")}. The
              snapshot shows that table to be <strong>incomplete</strong>, so these entries are not all of{" "}
              {device.host}'s routing: forwarding claims about this host that rest on them are not decided
              where a route the table does not hold could change the answer.
            </>
          ) : (
            <>
              A routing table was collected for {device.host}: {plural(routes.length, "entry", "entries")}.
              Forwarding claims about this host rest on those entries. Nothing in the snapshot shows the table
              to be incomplete; that is not proof that it is complete.
            </>
          )
        ) : (
          <>
            No routing table was collected for {device.host}. {cov.hostsWithRoutes} of{" "}
            {fabric.devices.length} hosts have one ({cov.routableHosts.join(", ")}). Nothing on
            this tab states how this device forwards — a hop through it is <em>unmodelled</em>, which
            is neither a delivery nor a drop.
          </>
        )}
      </p>
      {partial.length > 0 ? (
        <ul className="dp-rib-partial" aria-label={`Why ${device.host}'s routing table is incomplete`}>
          {partial.map((r) => (
            <li key={`${r.label}|${r.cite}`}>
              {r.label} <CiteButton cite={r.cite} onOpen={onOpenCite} />
            </li>
          ))}
        </ul>
      ) : null}

      <Section title="L3 interfaces and first-hop redundancy">
        {l3.length === 0 ? (
          device.collected ? (
            <Empty
              title="No L3 interface records"
              reason={`The collection produced no l3_forwarding row for ${device.host}. Whether it carries an SVI at all was not established here.`}
            />
          ) : (
            <NotObserved what="L3 interfaces" why="the device was never reached" compact />
          )
        ) : (
          l3.map((r) => (
            <div key={r.cite} className="dp-l3">
              <div className="dp-l3__head">
                <span className="dp-mono dp-l3__vlan">
                  VLAN {orNotObserved(r.vlan, (v) => String(v), { what: "VLAN id", compact: true })}
                </span>
                {/* Not routed through GradedSeverity: an L3 row's unobserved marker says only that
                    object TRACKING was not assessed ("no 'show track' evidence"), not that the row
                    was — so its grade may still rest on assessed fields. */}
                <GradedSeverity severity={r.severity} unassessed={null} />
                <CiteButton cite={r.cite} onOpen={onOpenCite} />
              </div>
              <EvidenceKv
                rows={[
                  { k: "SVI address", v: orNotObserved(r.sviIp, (s) => <span className="dp-mono">{s}</span>, { what: "SVI address", compact: true }), cite: r.cite },
                  { k: "Primary subnet", v: orNotObserved(r.primarySubnet, (s) => <span className="dp-mono">{s}</span>, { what: "primary subnet", compact: true }), cite: r.cite },
                  { k: "Secondary", v: orNotObserved(r.secondary, (s) => <span className="dp-mono">{s}</span>, { what: "secondary address", compact: true }), cite: r.cite },
                  { k: "FHRP", v: orNotObserved(r.fhrp, (s) => s, { what: "FHRP protocol", compact: true }), cite: r.cite },
                  { k: "FHRP role", v: orNotObserved(r.fhrpRole, (s) => s, { what: "FHRP role", compact: true }), cite: r.cite },
                  { k: "Virtual IP", v: orNotObserved(r.vip, (s) => <span className="dp-mono">{s}</span>, { what: "virtual IP", compact: true }), cite: r.cite },
                  { k: "Routing source", v: orNotObserved(r.routingSource, (s) => s, { what: "routing source", compact: true }), cite: r.cite },
                  { k: "Next hop", v: orNotObserved(r.nextHop, (s) => <span className="dp-mono">{s}</span>, { what: "next hop", compact: true }), cite: r.cite },
                  {
                    k: "Tracking",
                    cite: r.cite,
                    /* The engine writes its OWN absence prose into `trackingUnobserved`. It is the
                       reason the field is empty, and a generic placeholder would delete it. */
                    v: orNotObserved(r.tracking ?? r.trackingUnobserved, (s) => s, {
                      what: "object tracking",
                      compact: true,
                    }),
                    wide: true,
                  },
                  {
                    k: "Risk",
                    cite: r.cite,
                    v: orNotObserved(r.risk ?? r.riskUnobserved, (s) => s, { what: "risk", compact: true }),
                    wide: true,
                  },
                ]}
                onOpenCite={onOpenCite}
              />
            </div>
          ))
        )}
      </Section>

      <Section title="Routing table">
        {!rib ? (
          <NotObserved
            what="routing table"
            why={`no RIB was collected for ${device.host}; ${cov.hostsWithRoutes} of ${fabric.devices.length} hosts have one`}
            cite={fabric.coverage.cite}
            onOpenCite={onOpenCite}
          />
        ) : routes.length === 0 ? (
          <Empty
            title="The collected routing table is empty"
            reason={`A RIB was collected for ${device.host} and it contains no entries. That is an observation, not an absence of one.`}
          />
        ) : (
          <RecordGrid
            id={`dp-routes-${device.host}`}
            label={`Routing table for ${device.host}`}
            columns={[
              { id: "prefix", header: "Prefix", width: "10rem", rowHeader: true, text: (r) => r.prefix, render: (r) => <span className="dp-mono">{r.prefix}</span> },
              { id: "src", header: "Source", width: "6.5rem", render: (r) => orNotObserved(r.source, (s) => s, { what: "route source", compact: true }) },
              /* Both route fields render their ONE owner's reading (claims.ts routeFieldReading), through
                 the renderer the Path panel and the Inspector use. The AD column used to print the
                 field raw, so a connected route's null AD read "not observed" here and something else
                 there (acceptance B1, failed twice for this class). */
              { id: "ad", header: "AD", width: "4rem", align: "end", render: (r) => <RouteFieldValue route={r} field="adminDistance" compact classes={{ notApplicable: "dp-quiet" }} /> },
              { id: "nh", header: "Next hop", width: "9rem", render: (r) => <RouteFieldValue route={r} field="nextHop" classes={{ notApplicable: "dp-quiet", value: "dp-mono" }} /> },
              { id: "out", header: "Out", width: "8rem", render: (r) => orNotObserved(r.outIntf, (s) => <span className="dp-mono">{s}</span>, { what: "egress interface", compact: true }) },
              { id: "cite", header: "Evidence", width: "minmax(10rem, 1fr)", render: (r) => <CiteButton cite={r.cite} onOpen={onOpenCite} /> },
            ]}
            rows={routes}
            rowKey={(r, i) => `${r.prefix}-${i}`}
          />
        )}
      </Section>
    </div>
  );
}

/* ══ device: ACL ═══════════════════════════════════════════════════════════ */

function AclPanel({ device, onOpenCite }: { device: Device; onOpenCite: (c: Cite) => void }): ReactElement {
  const named = fabric.acls[device.host];
  const findings = fabric.aclFindings.filter((f) => f.host === device.host);
  const cov = fabric.coverage;
  /* The union of the three undecidability sets, not the producer's flag alone — see
     core/acl-coverage.ts. Stating the flag here put "1 of 12 could not be modelled" directly
     above a list of five INDETERMINATE verdicts. */
  const undecidable = aclUndecidability();

  if (!named) {
    return (
      <div className="dp-panel">
        <NotObserved
          what="access lists"
          why={`no ACL was collected for ${device.host}. ACL evaluation is modelled on ${cov.hostsWithAcls} of ${fabric.devices.length} hosts (${cov.aclHosts.join(", ")}); a policy decision on this host cannot be evaluated at all`}
          cite={cov.cite}
          onOpenCite={onOpenCite}
        />
      </div>
    );
  }

  const entries = Object.entries(named);
  return (
    <div className="dp-panel">
      <p className="dp-scope">
        {plural(entries.length, "access list")} collected on {device.host}.{" "}
        {undecidable.count} of {undecidable.total} ACL lines in this snapshot cannot be decided
        {undecidable.count === 0
          ? ""
          : ` (${undecidable.members.map((m) => m.label).join(", ")})`}
        ; a definite result that steps over one of those is an overclaim. That figure is the union
        of the {undecidable.bySource.engine} line(s) this model refuses to evaluate, the{" "}
        {undecidable.bySource.producer} the collector&rsquo;s parser could not model, and the{" "}
        {undecidable.bySource.snapshot} the snapshot&rsquo;s own reachability analysis returned
        indeterminate — sets that overlap only partly, so no one of them is the denominator.
      </p>
      {entries.map(([name, lines]) => (
        <Section key={name} title={name} note={`${plural(lines.length, "line")} as parsed by the collector`}>
          <AclLines lines={lines} onOpenCite={onOpenCite} />
        </Section>
      ))}
      <Section title="What the engine concluded about these lines">
        {findings.length === 0 ? (
          <Empty
            title="No ACL findings"
            reason={`The engine published no acl finding for ${device.host}. That is the absence of a published conclusion, not a conclusion that the policy is sound.`}
          />
        ) : (
          <ul className="dp-list">
            {findings.map((f) => (
              <li key={f.cite} className="dp-list__row">
                <span className="dp-list__lead">
                  <span className="dp-mono">
                    {orNotObserved(f.acl, (s) => s, { what: "ACL name", compact: true })}
                    {f.lineIndex === null ? null : ` [${f.lineIndex}]`}
                  </span>
                  <span className="dp-verdict" data-verdict={f.verdict ?? "unknown"}>
                    {orNotObserved(f.verdict, (s) => s, { what: "verdict", compact: true })}
                  </span>
                </span>
                <span className="dp-list__main">
                  {orNotObserved(f.detail, (s) => s, { what: "detail", compact: true })}
                  {f.raw === null ? null : <code className="dp-raw">{f.raw}</code>}
                </span>
                <CiteButton cite={f.cite} onOpen={onOpenCite} />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

export function AclLines({
  lines,
  highlightIndex,
  onOpenCite,
}: {
  lines: readonly AclLine[];
  highlightIndex?: number | null;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  /* Every line ANY source cannot decide is flagged inline — the engine's own evaluability, the
     producer's flag, and the snapshot's reachability analysis — from the one owner of that union
     (`aclUndecidability`). Only the producer's flag used to be drawn here, so the lines this model
     refuses (an `established`, a time-range, an icmp qualifier) read as evaluable in the list and
     were named undecidable only in a separate section further down (2026-09-21 critic, B5). */
  const undecidable = useMemo(() => new Map(aclUndecidability().members.map((m) => [m.cite, m] as const)), []);
  return (
    <ol className="dp-acl">
      {lines.map((l) => {
        const member = undecidable.get(l.cite);
        const blockers = [
          l.established ? "established (stateful)" : null,
          l.icmpType === null ? null : `icmp-type ${l.icmpType}`,
          l.timeRange === null ? null : `time-range ${l.timeRange}`,
          ...l.unmodeledQualifiers,
        ].filter((x): x is string => x !== null);
        return (
          <li
            key={l.cite}
            className={cx("dp-acl__line", (l.unevaluable || member !== undefined) && "dp-acl__line--unevaluable")}
            data-match={highlightIndex === l.index ? "true" : undefined}
            data-undecidable={member === undefined ? undefined : member.sources.join(" ")}
          >
            <span className="dp-acl__idx">{l.index}</span>
            <span className="dp-acl__text">
              {orNotObserved(l.raw, (s) => <code className="dp-raw">{s}</code>, {
                what: "configuration line",
                why: "the collector kept the parsed fields for this line but not its literal text",
                compact: true,
              })}
              {l.unevaluable ? (
                <span className="dp-acl__flag">
                  the producer could not model this line
                  {blockers.length > 0 ? `: ${blockers.join(", ")}` : ""}
                </span>
              ) : null}
              {member !== undefined && member.sources.some((s) => s !== "producer") ? (
                <span className="dp-acl__flag">
                  {`cannot be decided in general — ${member.sources
                    .map((s, i) => (s === "producer" ? null : member.reasons[i]))
                    .filter((x): x is string => typeof x === "string" && x !== "")
                    .join("; ")}`}
                </span>
              ) : null}
            </span>
            <CiteButton cite={l.cite} onOpen={onOpenCite} />
          </li>
        );
      })}
    </ol>
  );
}

/* ══ device: findings ══════════════════════════════════════════════════════ */

function FindingsPanel({ hosts, onOpenCite }: { hosts: readonly string[]; onOpenCite: (c: Cite) => void }): ReactElement {
  const selectFinding = useInvestigation((s) => s.selectFinding);
  const findingId = useInvestigation((s) => s.findingId);

  const findings = useMemo(() => {
    const seen = new Map<string, (typeof fabric.findings)[number]>();
    for (const h of hosts) for (const f of findingsByHost.get(h) ?? []) seen.set(f.id, f);
    return [...seen.values()].sort(
      (a, b) => severityRank(a.severity) - severityRank(b.severity) || (a.priority ?? 1e9) - (b.priority ?? 1e9) || a.id.localeCompare(b.id),
    );
  }, [hosts]);

  const cross = useMemo(() => {
    const seen = new Map<string, (typeof fabric.crossLayer)[number]>();
    for (const h of hosts) for (const c of crossLayerByHost.get(h) ?? []) seen.set(c.id, c);
    return [...seen.values()].sort((a, b) => severityRank(a.severity) - severityRank(b.severity) || a.id.localeCompare(b.id));
  }, [hosts]);

  const counts = SEVERITY_ORDER.map((s) => ({ s, n: findings.filter((f) => f.severity === s).length }));
  /* "C 0 H 0 M 0 L 0 I 0" is a positive statement about a search, and it may only be made where a
     search was possible. On a host the collection never visited it is a clean all-zero readout on
     a device nobody looked at — the false-health class this pane exists to refuse. */
  /* The scope is SPLIT, never merged: a cable with one uncollected end used to pass a
     `hosts.some(collected)` guard and print an assessed-looking tally "across 2 hosts" whose second
     half was silence (critic B1, 20 cables). The tally is stated over the collected hosts by name,
     and each never-collected host is named separately as contributing no search. A host this
     snapshot has no device record for is not evidence of collection either. */
  const collectedHosts = hosts.filter((h) => deviceById.get(h)?.collected === true);
  const uncollectedHosts = hosts.filter((h) => deviceById.get(h)?.collected !== true);
  const searchable = collectedHosts.length > 0;
  const partial = searchable && uncollectedHosts.length > 0;
  const uncollectedSentence =
    uncollectedHosts.length === 0
      ? ""
      : ` ${uncollectedHosts.join(", ")} ${uncollectedHosts.length === 1 ? "was" : "were"} never collected; ${uncollectedHosts.length === 1 ? "it contributes" : "they contribute"} no search, so ${uncollectedHosts.length === 1 ? "its" : "their"} share of this tally is not observed.`;

  return (
    <div className="dp-panel">
      {/* Every severity renders, including the ones at zero: "Info 0" is a positive statement
          about this host's findings, and hiding it turns that statement into silence. */}
      {searchable ? (
        <>
          <ul className="dp-sevcounts" aria-label={`Severity tally over ${collectedHosts.join(", ")}`}>
            {counts.map(({ s, n }) => (
              <li key={s} className="dp-sevcounts__item">
                <SeverityBadge severity={s} compact />
                <span className="dp-sevcounts__n">{n}</span>
              </li>
            ))}
          </ul>
          {partial ? (
            <NotObserved
              what={`finding counts for ${uncollectedHosts.join(", ")}`}
              why={`the tally above searched ${collectedHosts.join(", ")} only.${uncollectedSentence}`}
            />
          ) : null}
        </>
      ) : (
        <NotObserved
          what="finding counts"
          why={`${hosts.join(", ")} ${hosts.length === 1 ? "was" : "were"} never collected, so a severity tally here would count an empty search rather than an assessed device`}
        />
      )}

      <Section
        title="Findings that name this selection"
        note={
          searchable
            ? hosts.length === 1
              ? `${plural(findings.length, "finding")} across ${plural(hosts.length, "host")}.`
              : `${plural(findings.length, "finding")} across ${plural(collectedHosts.length, "collected host")} (${collectedHosts.join(", ")}).${uncollectedSentence}`
            : `${plural(hosts.length, "host")}, none of them collected: this is the size of the search, not a finding count.`
        }
      >
        {findings.length === 0 ? (
          <Empty
            title="No finding names this host"
            reason="No punchlist entry lists this host among its devices. That is the absence of a published finding, not an assessment that nothing is wrong."
          />
        ) : (
          <ul className="dp-list dp-list--findings">
            {findings.map((f) => (
              <li key={f.id} className="dp-list__row" data-selected={f.id === findingId ? "true" : undefined}>
                <span className="dp-list__lead">
                  <SeverityBadge severity={f.severity} compact />
                  <span className="dp-mono">{f.id}</span>
                </span>
                <button type="button" className="dp-linkbtn dp-list__main" onClick={() => selectFinding(f.id)}>
                  {f.title}
                  <span className="dp-quiet"> · {orNotObserved(f.category, (s) => s, { what: "category", compact: true })}</span>
                </button>
                <CiteButton cite={f.cite} onOpen={onOpenCite} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Cross-layer findings"
        note="A cross-layer finding is one whose cause spans more than one layer at once; the layers it composes are named on each row."
      >
        {cross.length === 0 ? (
          <Empty
            title="No cross-layer finding names this host"
            reason="No cross_layer entry lists this host. The engine composed no multi-layer risk here; it did not conclude that none exists."
          />
        ) : (
          <ul className="dp-list">
            {cross.map((c) => (
              <li key={c.id} className="dp-list__row">
                <span className="dp-list__lead">
                  <SeverityBadge severity={c.severity} compact />
                  <span className="dp-mono">{c.id}</span>
                </span>
                <span className="dp-list__main">
                  {c.title}
                  <span className="dp-layers">
                    {c.layers === null ? (
                      <NotObserved what="layer composition" compact />
                    ) : (
                      c.layers.split("+").map((layer) => (
                        <span key={layer} className="dp-layer">{layer}</span>
                      ))
                    )}
                  </span>
                </span>
                <CiteButton cite={c.cite} onOpen={onOpenCite} />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

/* ══ device: raw ═══════════════════════════════════════════════════════════ */

function RawPanel({ record, cite, onOpenCite }: { record: unknown; cite: Cite; onOpenCite: (c: Cite) => void }): ReactElement {
  const text = useMemo(() => JSON.stringify(record, null, 2), [record]);
  return (
    <div className="dp-panel">
      <p className="dp-sec__note">
        This is the <strong>compiled</strong> record this pane renders from. The record in the
        source snapshot is at <span className="dp-mono">{cite}</span> — open it to check the
        compilation itself rather than its output.
      </p>
      <p className="dp-sec__note">
        <CiteButton cite={cite} onOpen={onOpenCite} label={`open ${cite} in the inspector`} />
      </p>
      <pre className="dp-json" tabIndex={0} aria-label="Compiled record, JSON">
        {text}
      </pre>
    </div>
  );
}

/* ══ link view ═════════════════════════════════════════════════════════════ */

function LinkSummary({ link, onOpenCite }: { link: Link; onOpenCite: (c: Cite) => void }): ReactElement {
  const ours = useMemo(() => linkFailureImpact(link.id), [link.id]);
  const selectDevice = useInvestigation((s) => s.selectDevice);
  const eps = ours.strandedEndpoints;
  /* A port this cable names that the cable map also places on another cable. Shown beside the
     cable's own evidence, not only as a blast-radius caveat: the adjacency itself is contradicted. */
  const disputes = disputesOf(link.id);

  return (
    <div className="dp-panel">
      <Section title="Cable" note={<>Source record <span className="dp-mono">{link.cite}</span></>}>
        <div className="dp-linkends">
          <button type="button" className="dp-linkbtn dp-linkend" onClick={() => selectDevice(link.a)}>
            <span className="dp-mono dp-linkend__host">{link.a}</span>
            <span className="dp-mono dp-quiet">
              {orNotObserved(link.aPort, (s) => s, { what: "port on the A end", compact: true })}
            </span>
          </button>
          <span className="dp-linkends__joint" aria-hidden="true" />
          <button type="button" className="dp-linkbtn dp-linkend" onClick={() => selectDevice(link.b)}>
            <span className="dp-mono dp-linkend__host">{link.b}</span>
            <span className="dp-mono dp-quiet">
              {orNotObserved(link.bPort, (s) => s, { what: "port on the B end", compact: true })}
            </span>
          </button>
        </div>
        <EvidenceKv
          rows={[
            { k: "State", v: <StateDot state={link.opStatus} showLabel />, cite: link.cite },
            { k: "Speed", v: orNotObserved(link.speedMbps, (n) => `${n.toLocaleString("en-GB")} Mbps`, { what: "speed", compact: true }), cite: link.cite },
            {
              k: "Port channel",
              cite: link.cite,
              v: link.isPortChannel
                ? <span className="dp-mono dp-wrap">{link.members.length > 0 ? link.members.join(", ") : "members not observed"}</span>
                : "no — a single cable",
            },
            {
              k: "How confirmed",
              cite: link.cite,
              v: orNotObserved(link.confirmation, (s) => s, {
                what: "adjacency confirmation",
                why: "the engine did not record how this adjacency was confirmed",
                compact: true,
              }),
              wide: true,
            },
            {
              k: "Port conflict",
              derived: "compared by this application against every cable_map.cables record for a port placed on two cables (analysis/port-claims.ts)",
              v:
                disputes.length === 0
                  ? "none — no port this cable names is on another cable in the map"
                  : (
                      <span className="dp-wrap" data-disputed="true">
                        <strong>disputed</strong>
                        {disputes.map((d) => ` ${disputeSentence(link.id, d)}`).join("")}
                      </span>
                    ),
              wide: true,
            },
          ]}
          onOpenCite={onOpenCite}
        />
      </Section>

      <Section
        title="Centrality — the snapshot's own measure"
        note={`Centrality was computed for ${fabric.coverage.linksWithCentrality} of ${fabric.links.length} links in this snapshot. A link without it is unmeasured, not unimportant.`}
      >
        {/* Each figure cites the link_centrality row it was READ from (compiled under that path, so the
            Inspector opens the very record that carries it). The cable record `link.cite` holds none
            of these, so it is cited only where no centrality row exists — the record whose lack of one
            is the absence (acceptance B6). */}
        <EvidenceKv
          rows={[
            {
              k: "Cutting it partitions",
              v: orNotObserved(link.isBridge, (b) => (b ? "yes" : "no"), {
                what: "bridge status",
                why: "link centrality was not computed for this cable",
                compact: true,
              }),
              cite: link.centralityCite ?? link.cite,
            },
            { k: "Betweenness", v: orNotObserved(link.betweenness, (n) => n.toFixed(4), { what: "betweenness", compact: true }), cite: link.centralityCite ?? link.cite },
            { k: "Pairs cut", v: num(link.pairsCut, "pairs cut"), cite: link.centralityCite ?? link.cite },
            { k: "Centrality rank", v: num(link.centralityRank, "centrality rank"), cite: link.centralityCite ?? link.cite },
          ]}
          onOpenCite={onOpenCite}
        />
      </Section>

      <Section title="Our computed blast radius" note="Computed from the cable map, independently of the snapshot's own centrality pass.">
        <EvidenceKv
          rows={[
            { k: "Presence", v: ours.presence, derived: OUR_BLAST_BASIS },
            { k: "Certainty", v: <span className="dp-certainty" data-certainty={ours.certainty}>{ours.certainty}</span>, derived: OUR_BLAST_BASIS },
            {
              k: "Cutting it partitions",
              derived: OUR_BLAST_BASIS,
              v: orNotObserved(ours.isBridge, (b) => (b ? "yes" : "no"), {
                what: "bridge status",
                /* A carrying cable with no verdict was withheld for its own reason (a disputed port);
                   "not carrying" would be false there. */
                why:
                  ours.presence === "carrying"
                    ? (eps.note ?? "no verdict was computed for this cable")
                    : "this cable is not carrying traffic in the projection, so we decline to call it a non-bridge",
                compact: true,
              }),
            },
            {
              k: "Components",
              derived: OUR_BLAST_BASIS,
              /* Measured 2026-09-21: 19 of 44 links are excluded from the projection and returned
                 `componentsBefore === componentsAfter === 1` — rendered here as a clean
                 "1 before → 1 after" directly above prose saying no blast radius was computed for
                 this cable. An unmodelled cable must not read as a measured no-impact result. */
              v: ours.certainty === "not-determinable"
                ? <NotObserved what="component count" why={eps.note ?? ours.presence} compact />
                : `${ours.componentsBefore} before → ${ours.componentsAfter} after`,
            },
            {
              k: "Newly stranded",
              derived: OUR_BLAST_BASIS,
              v: ours.certainty === "not-determinable"
                ? <NotObserved what="stranded hosts" why={eps.note ?? ours.presence} compact />
                : ours.newlyStranded.length === 0
                  ? "none"
                  : <span className="dp-mono dp-wrap">{ours.newlyStranded.join(", ")}</span>,
            },
            {
              k: "Endpoints behind the cut",
              derived: `${OUR_BLAST_BASIS}, floored by the endpoint_identity records behind the cut`,
              v: orNotObserved(eps.floorTotal, (n) => `at least ${n.toLocaleString("en-GB")}`, {
                what: "endpoints behind the cut",
                why: eps.note,
                compact: true,
              }),
            },
          ]}
          onOpenCite={onOpenCite}
        />
        <p className="dp-claim">{ours.claim}</p>
        <div className={cx("dp-disagree", ours.engine.agreement === "disagree" && "dp-disagree--live")}>
          <p className="dp-disagree__head">
            {ours.engine.agreement === "agree"
              ? "Our answer and the snapshot's agree"
              : ours.engine.agreement === "disagree"
                ? "The two measures disagree"
                : /* "engine-silent" also covers OUR side being undetermined; name the absent side(s). */
                  ours.engine.isBridge === null && ours.isBridge === null
                  ? "Neither measure exists for this cable"
                  : ours.engine.isBridge === null
                    ? "The snapshot published no centrality for this cable"
                    : "Only the snapshot's measure exists — ours could not be computed"}
          </p>
          {ours.engine.agreement === "disagree" ? (
            <p className="dp-disagree__t9">
              {T9_disagreement(
                link.id,
                ours.isBridge === null ? "not determinable" : ours.isBridge ? "cutting it partitions the graph" : "cutting it does not partition the graph",
                "link_centrality.is_bridge",
                ours.engine.isBridge === null ? "not observed" : ours.engine.isBridge ? "partitions" : "does not partition",
                ours.engine.cite ?? link.cite,
              )}
            </p>
          ) : null}
        </div>
        {ours.caveats.length > 0 ? (
          <ul className="dp-caveats">
            {ours.caveats.map((cv) => (
              <li key={cv}>{cv}</li>
            ))}
          </ul>
        ) : null}
      </Section>
    </div>
  );
}

/* ══ the pane ══════════════════════════════════════════════════════════════ */

export interface DevicePaneProps {
  /** Opens the Inspector at an exact citation path. See `useOpenCite` for the fallback. */
  onOpenCite?: (cite: Cite) => void;
  className?: string;
}

interface TabSpec {
  item: TabItem;
  render: () => ReactNode;
  /**
   * Set when the snapshot holds NOTHING behind this tab. The panel renders this sentence in
   * place of the tab's own content, so the panel is never blank.
   *
   * A11Y AUDIT FIX, 2026-09-21 (D1 and D4). These tabs used to carry the native disabled
   * attribute. That removed them from the tab order AND from the tablist's own roving cycle, so
   * "no ACL collected" — the only statement of that coverage gap anywhere on this surface — was
   * unreachable by keyboard or screen reader; and the :disabled dimming made it the
   * lowest-contrast text in the whole product (measured 2.18:1 light, 3.30:1 dark). Neither was
   * the intended meaning. A tab with an explanation behind it is a WORKING tab — which is
   * exactly how the sibling routing tab ("no RIB collected") already behaved. So there is no
   * disabled state here any more: reaching the tab is how a reader reaches the reason.
   */
  absentReason?: string;
}

export function DevicePane({ onOpenCite, className }: DevicePaneProps): ReactElement {
  const deviceId = useInvestigation((s) => s.deviceId);
  const linkId = useInvestigation((s) => s.linkId);
  const tab = useInvestigation((s) => s.evidenceTab);
  const setEvidenceTab = useInvestigation((s) => s.setEvidenceTab);
  const openCite = useOpenCite(onOpenCite);

  const link = linkId === null ? null : (linkById.get(linkId) ?? null);
  const device = deviceId === null ? null : (deviceById.get(deviceId) ?? null);
  /* A link selection is strictly narrower than the device it belongs to, and the store clears the
     link whenever a device is chosen — so a live `linkId` is always the more recent intent. */
  const subject = link !== null ? ("link" as const) : device !== null ? ("device" as const) : null;

  const tabs: TabSpec[] = useMemo(() => {
    if (subject === "link" && link) {
      const hosts = [link.a, link.b];
      return [
        { item: { id: "summary", label: "Cable" }, render: () => <LinkSummary link={link} onOpenCite={openCite} /> },
        {
          item: { id: "ports", label: "Ends", count: 2 },
          render: () => <LinkEnds link={link} onOpenCite={openCite} />,
        },
        {
          item: { id: "routing", label: <TabWhy label="Routing" why="a cable carries no routing record" /> },
          render: () => null,
          absentReason: "A cable has no routing table of its own. Select one of its end devices to read a RIB.",
        },
        {
          item: { id: "acl", label: <TabWhy label="ACL" why="a cable carries no policy" /> },
          render: () => null,
          absentReason: "Access lists are held per device, not per cable. Select an end device.",
        },
        {
          item: { id: "findings", label: "Findings", count: countFindings(hosts) },
          render: () => <FindingsPanel hosts={hosts} onOpenCite={openCite} />,
        },
        { item: { id: "raw", label: "Raw" }, render: () => <RawPanel record={link} cite={link.cite} onOpenCite={openCite} /> },
      ];
    }
    if (subject === "device" && device) {
      const collected = device.collected;
      const ports = joinPorts(device.host);
      const acls = fabric.acls[device.host];
      const aclLines = acls ? Object.values(acls).reduce((a, ls) => a + ls.length, 0) : null;
      return [
        {
          item: { id: "summary", label: "Summary" },
          render: () => (
            <div className="dp-panel">
              <UncollectedBanner device={device} onOpenCite={openCite} />
              <IdentitySection device={device} onOpenCite={openCite} />
              <HealthSection device={device} onOpenCite={openCite} />
              <ImpactSection device={device} onOpenCite={openCite} />
              <ProtocolSection device={device} onOpenCite={openCite} />
            </div>
          ),
        },
        {
          item: { id: "ports", label: "Ports", count: collected ? ports.length : null },
          render: () => <PortsPanel device={device} onOpenCite={openCite} />,
        },
        {
          item: {
            id: "routing",
            label: !hasRib(device.host) ? (
              <TabWhy label="Routing" why="no RIB collected" />
            ) : ribIncompleteness(device.host).length > 0 ? (
              /* The count beside it is the table's size; the table is shown incomplete, and a bare
                 "4" reads as the whole of core2's routing (2026-09-22 critic, B7). */
              <TabWhy label="Routing" why="incomplete" />
            ) : (
              "Routing"
            ),
            /* A badge is a COUNT of things observed, so it may only be shown where something was
               looked for. `collected` is too coarse: access1 is collected, holds no RIB and no
               l3_forwarding row, and rendered a bare "0" next to a sibling ACL badge that
               correctly read "not observed" for the identical kind of absence. A device with no
               routing evidence has no routing count.

               `undefined`, not `null`: the LABEL beside it already says "no RIB collected", and a
               second "not observed" chip saying the same thing in the same 3 cm of tab strip is
               what pushed the whole strip into horizontal overflow. One statement of an absence
               is honesty; two is noise that costs the reader a tab they can no longer see. */
            /* The count beside "Routing" is the size of the ROUTING TABLE — the RIB entries the tab
               lists. It used to be the number of L3 SVIs (core1 read "3" over an 8-entry RIB), a
               different quantity under the one label a reader takes as the table size. */
            count: collected && hasRib(device.host) ? routesOf(device.host).length : undefined,
          },
          render: () => <RoutingPanel device={device} onOpenCite={openCite} />,
        },
        {
          item: {
            id: "acl",
            label: acls ? "ACL" : <TabWhy label="ACL" why="no ACL collected" />,
            // See the routing tab: the label carries the absence, so the count stays silent.
            count: acls ? (aclLines ?? undefined) : undefined,
          },
          render: () => <AclPanel device={device} onOpenCite={openCite} />,
          absentReason: acls
            ? undefined
            : `No access list was collected for ${device.host}. ACL evaluation in this snapshot is modelled on ${fabric.coverage.aclHosts.join(", ")} only, so a policy question about this host cannot be evaluated at all.`,
        },
        {
          item: {
            id: "findings",
            label: collected ? "Findings" : <TabWhy label="Findings" why="this device was never collected" />,
            /* "0 findings" on a device nobody assessed is the false-health class: it reads as a
               clean bill of health when it is an empty search of an empty evidence set. */
            count: collected ? countFindings([device.host]) : undefined,
          },
          render: () => <FindingsPanel hosts={[device.host]} onOpenCite={openCite} />,
        },
        { item: { id: "raw", label: "Raw" }, render: () => <RawPanel record={device} cite={device.cite} onOpenCite={openCite} /> },
      ];
    }
    return [];
  }, [subject, device, link, openCite]);

  const heading =
    subject === "link" && link
      ? `${link.a} ↔ ${link.b}`
      : subject === "device" && device
        ? device.host
        : "Nothing selected";

  const announce =
    subject === null
      ? "No device or cable selected"
      : `${heading}, ${tab} tab`;

  if (subject === null || tabs.length === 0) {
    return (
      <section className={cx("dp", className)} aria-label="Device evidence">
        <header className="dp__head">
          <h2 className="dp__title">Device</h2>
        </header>
        <div className="dp__body scroll-scrim">
          <Empty
            title="Nothing is selected"
            reason="Select a device or a cable — in the fabric, in the priority queue, or from a finding's evidence chain — and everything the snapshot holds about it appears here."
          />
        </div>
        <LiveRegion message={announce} />
      </section>
    );
  }

  const active = tabs.find((t) => t.item.id === tab) ?? tabs[0];

  return (
    <section className={cx("dp", className)} aria-label="Device evidence">
      <header className="dp__head">
        <h2 className="dp__title">
          <span className="dp-mono">{heading}</span>
        </h2>
        <p className="dp__sub">
          {subject === "device" && device ? (
            <>
              {device.kind} ·{" "}
              {orNotObserved(device.role, (s) => s, { what: "role", compact: true })} ·{" "}
              {device.collected ? "assessed" : "topology only"}
            </>
          ) : (
            <>cable · {plural(link?.members.length ?? 0, "member")}</>
          )}
        </p>
      </header>

      <Tabs
        id="dp"
        label="Device evidence"
        items={tabs.map((t) => t.item)}
        value={active?.item.id ?? "summary"}
        onChange={(id) => setEvidenceTab(id as EvidenceTab)}
        className="dp__tabs"
      />

      <div className="dp__body scroll-scrim">
        {tabs.map((t) => {
          /* Only the ACTIVE panel's content is built. The panel elements all stay mounted so
             `aria-controls` always resolves, but rendering six panels of dense grids on every
             selection change put ~140 ms of React work on the interaction path — measured, by
             this file's own test timing out. The inactive panels hold no DOM, so switching tabs
             costs one panel, not six. */
          const isActive = t.item.id === active?.item.id;
          return (
            <TabPanel key={t.item.id} id="dp" tabId={t.item.id} active={isActive}>
              {!isActive ? null : t.absentReason ? (
                /* A tab with nothing behind it explains itself rather than rendering an empty
                   panel — an empty panel reads as "nothing here" when it means "we never
                   looked". Reachable by pointer, by keyboard (the tab is in the roving
                   cycle) and from a shared URL. */
                <div className="dp-panel">
                  <NotObserved what={t.item.id} why={t.absentReason} />
                </div>
              ) : (
                t.render()
              )}
            </TabPanel>
          );
        })}
      </div>

      <LiveRegion message={announce} />
    </section>
  );
}

function TabWhy({ label, why }: { label: string; why: string }): ReactElement {
  return (
    <span className="dp-tabwhy">
      {label}
      <span className="dp-tabwhy__why">{why}</span>
    </span>
  );
}

function countFindings(hosts: readonly string[]): number {
  const seen = new Set<string>();
  for (const h of hosts) for (const f of findingsByHost.get(h) ?? []) seen.add(f.id);
  return seen.size;
}

/** The port records a joined row was read from: the interface record, the physical-health row, or both. */
const portCites = (r: PortRow): Cite[] => [r.intf?.cite, r.phys?.cite].filter((c): c is Cite => c !== undefined);

function LinkEnds({ link, onOpenCite }: { link: Link; onOpenCite: (c: Cite) => void }): ReactElement {
  const ends: { host: string; port: string | null }[] = [
    { host: link.a, port: link.aPort },
    { host: link.b, port: link.bPort },
  ];
  return (
    <div className="dp-panel">
      {ends.map((e) => {
        const row = e.port === null ? undefined : joinPorts(e.host).find((r) => r.port === e.port);
        return (
          <Section key={e.host} title={`${e.host} end`}>
            {e.port === null ? (
              <NotObserved
                what="port on this end"
                why="the cable map names the device but not the port it lands on"
                cite={link.cite}
                onOpenCite={onOpenCite}
              />
            ) : row === undefined ? (
              <NotObserved
                what="interface record"
                why={`the cable map names ${e.host} ${e.port}, but no interface or physical-health record was collected for that port`}
                cite={link.cite}
                onOpenCite={onOpenCite}
              />
            ) : (
              <EvidenceKv
                rows={[
                  /* Every row cites the port record(s) it READ: both where the value is joined from
                     the interface and physical-health records, the physical-health row alone for its
                     counters — and, where a record is missing, the one that exists, whose lack of the
                     field is the absence shown (acceptance B6). */
                  { k: "Port", v: <span className="dp-mono">{row.port}</span>, cite: portCites(row) },
                  { k: "Status", v: portField(row, "status"), cite: portCites(row) },
                  { k: "Speed", v: portField(row, "speed"), cite: portCites(row) },
                  { k: "Duplex", v: portField(row, "duplex"), cite: portCites(row) },
                  { k: "Media", v: orNotObserved(row.phys?.media ?? row.intf?.linkType, (s) => s, { what: "media", compact: true }), cite: portCites(row) },
                  { k: "CRC errors", v: num(row.phys?.crcErrors, "CRC errors"), cite: row.phys?.cite ?? portCites(row) },
                  { k: "Input errors", v: num(row.phys?.inputErrors, "input errors"), cite: row.phys?.cite ?? portCites(row) },
                  { k: "Output drops", v: num(row.phys?.outputDrops, "output drops"), cite: row.phys?.cite ?? portCites(row) },
                  {
                    k: "Description",
                    v: row.intf === null
                      ? <NotObserved what="description" why="no interface record for this port" compact />
                      : orNotObserved(row.intf.description, (s) => s, { what: "description", compact: true }),
                    wide: true,
                    cite: row.intf?.cite ?? portCites(row),
                  },
                ]}
                onOpenCite={onOpenCite}
              />
            )}
          </Section>
        );
      })}
    </div>
  );
}

export default DevicePane;
