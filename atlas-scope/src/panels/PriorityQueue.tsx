/**
 * PriorityQueue.tsx — the left rail: the ranked, grouped, filtered queue of everything the engine
 * found, and the first surface a user touches.
 *
 * Three positions this file takes, each of which costs something and is worth it:
 *
 *   1. THE TWO CORPORA ARE NOT MERGED. The punchlist carries 146 rows; the cross-layer table
 *      carries 43, and every one of those 43 is also in the punchlist under the `Cross-layer`
 *      category — but only the cross-layer record knows which LAYERS it spans (query.ts documents
 *      why that field cannot be recovered from a punchlist row). Concatenating them would double
 *      every cross-layer finding and inflate the denominator the whole product is judged on. They
 *      are two views of the evidence, switched between and separately counted.
 *   2. EMPTY GROUPS RENDER. `Info · 0` is a positive statement about this snapshot — "zero findings
 *      at this severity in the scope you are looking at". Hiding it converts that statement into
 *      silence, which is the absence-as-health failure in list form. The vocabulary of a grouping
 *      key comes from `valueDomain()`, so the empty buckets are whatever the snapshot's own domain
 *      says they are and never a hardcoded list.
 *   3. A FILTER THAT EXCLUDES ROWS SAYS SO, PER CLAUSE. `applyToFindings` already computes matched
 *      / excluded / undetermined / without-this-clause for every clause and separates a row it
 *      decided AGAINST from one it could not decide. All of that is rendered. A short list with no
 *      explanation is indistinguishable from a small fleet.
 *
 * Determinism: no Math.random, no Date.now on any path that affects what is drawn. The ordering
 * comparators are total orders ending in an identity field, so two runs produce identical rows.
 */
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { flushSync } from "react-dom";
import {
  bySeverityThenRank,
  deviceById,
  fabric,
  findingById,
  linkById,
  severityRank,
} from "../core/data";
import {
  applyToCrossLayer,
  applyToFindings,
  groupBy,
  parseQuery,
  sortBy,
  suggest,
  UNOBSERVED_GROUP,
  valueDomain,
  type Clause,
  type ClauseOutcome,
  type FilterResult,
  type FindingGroupKey,
  type FindingSortField,
  type Group,
  type ParsedQuery,
  type QueryToken,
  type SortSpec,
} from "../core/query";
import { handOffFocus, useReleaseFocusOnHide, useReleaseFocusOnLayoutChange } from "../app/focus-return";
import { bandKey, bandKeyLabel } from "../core/band-qualification";
import { useInvestigation } from "../core/store";
import type { Cite, CrossLayerFinding, Finding } from "../core/types";
import { SEVERITY_ORDER } from "../core/types";
import { IconChevronDown, IconChevronUp, IconCite, IconClose, IconInfo, IconSearch } from "../ui/icons";
import {
  Button,
  Chip,
  Empty,
  IconButton,
  LiveRegion,
  NotObserved,
  Popover,
  Select,
  SeverityBadge,
  Toggle,
  orNotObserved,
} from "../ui/primitives";
import { DataGrid, type GridColumn, type GridNode, type GridSort } from "./DataGrid";
import { deferPastPaint } from "./deferPastPaint";
import "./PriorityQueue.css";
import { own } from "../core/own";

/* One shared empty set, so "nothing is related" is reference-stable and cannot re-render the grid
   on every keystroke. */
const EMPTY_IDS: ReadonlySet<string> = new Set<string>();

/* ── a selection the filter hides (acceptance A4; see `pinned` in the component) ─────────── */

/** A scope clause the store carries, and the store action that takes it off. */
interface ScopePart {
  text: string;
  clear: () => void;
}

/** One part of the effective filter that keeps the selected row out, as the reader sees it. */
interface HidingPart {
  /** The clause or term exactly as it stands in the filter (a chip's clause for a scope chip). */
  text: string;
  /** true = the part decided AGAINST the row; false = it could not decide, so it held the row out. */
  decided: boolean;
  /** A free-text term rather than a key:value clause — only changes how it is worded. */
  isText: boolean;
  /** Where it came from: a range of the typed filter text, or the index of a scope chip. */
  origin: { kind: "text"; start: number; end: number } | { kind: "scope"; index: number };
}

interface PinnedSelection<T> {
  /** The row id the grid addresses (a cross-layer row id in that corpus). */
  id: string;
  item: T;
  /** Empty only if no single part hides it — then the filter as a whole is named. */
  parts: HidingPart[];
  /** How the row is named in sentences. */
  label: string;
  /** The identifier the row itself shows (a finding id, or a cross-layer rule id). */
  short: string;
}

/** The group the pinned row sits under. Not a value any grouping key can produce. */
const OUTSIDE_FILTER_GROUP = "\u0000selected-outside-filter";

const describePart = (p: HidingPart): string => {
  const name = p.isText ? `the text ${p.text}` : p.text;
  return p.decided ? `${name} excludes it` : `${name} could not decide it`;
};

/* ── preferences: furniture, so localStorage and never the URL (design-brief §5.4) ─────────── */

/** One press of "Narrower" / "Wider" in the Display dialog. Coarser than the 8 px Shift+Arrow step
 *  on a header cell: a pointer press is slower than a key repeat. */
const COLUMN_WIDTH_STEP_PX = 16;
const PREF_PREFIX = "atlas-scope.queue.";

const readPref = (key: string): string | null => {
  try {
    return localStorage.getItem(PREF_PREFIX + key);
  } catch {
    /* Blocked storage (private mode, a locked-down profile) loses a preference, never evidence.
       The investigation state that matters lives in the URL, which is why the split exists. */
    return null;
  }
};

const writePref = (key: string, value: string): void => {
  try {
    localStorage.setItem(PREF_PREFIX + key, value);
  } catch {
    /* see readPref */
  }
};

function usePref<T>(key: string, fallback: T, decode: (raw: string) => T | null, encode: (v: T) => string) {
  const [value, setValue] = useState<T>(() => {
    const raw = readPref(key);
    return raw === null ? fallback : (decode(raw) ?? fallback);
  });
  const set = useCallback(
    (next: T) => {
      setValue(next);
      writePref(key, encode(next));
    },
    [key, encode],
  );
  return [value, set] as const;
}

/* ── ordering ───────────────────────────────────────────────────────────────── */

/** Locale-independent: `localeCompare` is not stable across engines and ICU builds. */
const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** Unknown sinks in BOTH directions. It is not the smallest value; it is not a value at all, and a
 *  descending sort that floats unknowns to the top presents them as the extreme case. */
const cmpCell = (a: string | number | null, b: string | number | null, dir: "asc" | "desc"): number => {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  const base = typeof a === "number" && typeof b === "number" ? a - b : cmpStr(String(a), String(b));
  return dir === "asc" ? base : -base;
};

type Ordering = { kind: "ranked" } | { kind: "field"; spec: SortSpec<string> };

const RANKED: Ordering = { kind: "ranked" };

/* ── corpus adapter ─────────────────────────────────────────────────────────── */

type CorpusId = "findings" | "cross-layer";

const CORPORA: readonly { id: CorpusId; label: string }[] = [
  { id: "findings", label: "Findings" },
  { id: "cross-layer", label: "Cross-layer" },
];

interface CorpusSpec<T> {
  id: CorpusId;
  /** Plural noun for sentences: "146 findings match". */
  noun: string;
  rows: readonly T[];
  idOf: (t: T) => string;
  citeOf: (t: T) => Cite;
  /** One pasteable line per row, for the batch copy. Carries the citation, always. */
  lineOf: (t: T) => string;
  columns: readonly GridColumn<T>[];
  groupKeys: readonly { value: string; label: string; vocabulary: () => readonly string[] }[];
  group: (rows: readonly T[], key: string) => Group<T>[];
  sortFieldOf: (columnId: string) => string | null;
  order: (rows: readonly T[], o: Ordering) => T[];
  filter: (rows: readonly T[], parsed: ParsedQuery) => FilterResult<T>;
  /** What the default ordering actually is, stated to the user rather than implied. */
  rankedLabel: string;
}

/** Values a grouping key can take in THIS snapshot, so empty buckets are data-driven. */
const domainValues = (key: string): readonly string[] => (valueDomain(key) ?? []).map((d) => d.value);

/** Grouping keys that name a device or a device attribute: the attribute each one reads. */
const DEVICE_ATTRIBUTE: Readonly<Record<string, (d: (typeof fabric.devices)[number]) => string | null>> = {
  host: (d) => d.host,
  role: (d) => d.role,
  // The band owner's key ("Excellent-partial" for a qualified band), the same key the groups use.
  band: bandKey,
};

/** Was an (empty) bucket of this grouping key actually searched? Always true for keys that do not
 *  name a device. For a device-keyed bucket, true only when at least one COLLECTED device carries
 *  the value: a bucket whose every device was never collected is silence, not a zero. */
export function searchedByCollection(key: string, value: string): boolean {
  const pick = own(DEVICE_ATTRIBUTE, key);
  if (!pick) return true;
  const want = value.toLowerCase();
  return fabric.devices.some((d) => d.collected && (pick(d) ?? "").toLowerCase() === want);
}

/* ── shared cell renderers ──────────────────────────────────────────────────── */

function HostList({ hosts, what }: { hosts: readonly string[]; what: string }): ReactNode {
  if (hosts.length === 0) {
    return <NotObserved what={what} why="this record names no device" compact />;
  }
  const shown = hosts.slice(0, 2);
  const rest = hosts.length - shown.length;
  return (
    <span className="pq-hosts">
      {shown.map((h) => (
        <span key={h} className="pq-host">
          {h}
        </span>
      ))}
      {rest > 0 ? <span className="pq-host pq-host--more">{`+${rest} more`}</span> : null}
      {/* Truncation is visual only: the accessible name carries every host, so a screen-reader
          user is never shown a shorter list than a sighted one. */}
      {rest > 0 ? <span className="visually-hidden">{`, all: ${hosts.join(", ")}`}</span> : null}
    </span>
  );
}

const TextCell = ({ value, className }: { value: string; className: string }): ReactNode => (
  <span className={className}>{value}</span>
);

/**
 * The title, led by the device it is about.
 *
 * 85 of this snapshot's 146 findings share a title with at least one other row, and one title is
 * carried by 17 rows. Ranked by severity they land consecutively, so the loud line of six adjacent
 * rows was the same string truncated at the same character: a ranked list whose visible rows are
 * byte-identical cannot be scanned at all. The device is the differentiator the reader is actually
 * looking for, so it leads — the first characters of the loud line differ per row.
 *
 * It is a PREFIX rather than its own track because a track is sized by the widest row in the whole
 * grid, which would spend that width on every row including the ones that do not need it. The full
 * host list stays in the accessible name, so nothing is hidden from a screen reader.
 */
function TitleCell({ title, hosts }: { title: string; hosts: readonly string[] }): ReactNode {
  const lead = hosts[0];
  const rest = hosts.length - 1;
  return (
    <span className="pq-title">
      {lead === undefined ? (
        /* A record that names no device says so where the device would have been. The leading
           position is now the one the reader looks at first, so leaving it blank here would be the
           same blank-cell-reads-as-zero defect the separate column was built to avoid. */
        <span className="pq-title__host pq-title__host--absent">
          <NotObserved what="devices" why="this record names no device" compact />
        </span>
      ) : (
        <span className="pq-title__host">
          {lead}
          {rest > 0 ? <span className="pq-title__more">{`+${rest}`}</span> : null}
        </span>
      )}
      <span className="pq-title__text">{title}</span>
      {hosts.length > 1 ? (
        <span className="visually-hidden">{`, all devices: ${hosts.join(", ")}`}</span>
      ) : null}
    </span>
  );
}

/* ── the cross-layer -> punchlist bridge ────────────────────────────────────────
   The shared store addresses a selection by `findingId`, so selecting a cross-layer row has to
   name the punchlist row that carries the same record. The join is on (severity, title, detail)
   and is accepted ONLY when it is unique: a one-to-many join would silently re-aim every other
   surface at the wrong evidence, which is worse than offering no link at all. */
const crossLayerBridge: ReadonlyMap<string, string> = (() => {
  const key = (sev: string, title: string, detail: string | null): string =>
    `${sev}\u0000${title}\u0000${detail ?? ""}`;
  const byKey = new Map<string, string[]>();
  for (const f of fabric.findings) {
    const k = key(f.severity, f.title, f.detail);
    const list = byKey.get(k);
    if (list) list.push(f.id);
    else byKey.set(k, [f.id]);
  }
  const out = new Map<string, string>();
  for (const c of fabric.crossLayer) {
    const hit = byKey.get(key(c.severity, c.title, c.detail));
    if (hit && hit.length === 1 && hit[0] !== undefined) out.set(`${c.id}\u0000${c.cite}`, hit[0]);
  }
  return out;
})();

const crossRowId = (c: CrossLayerFinding): string => `${c.id}\u0000${c.cite}`;

/* ── grouping for the cross-layer corpus ────────────────────────────────────────
   query.ts groups Findings; its grouper is not exported and cross-layer records carry different
   fields, so the same three rules are restated here: a row with no observed value for the key
   lands in an explicit Not-observed bucket, a multi-valued key produces multi-membership, and the
   bucket order follows a fixed vocabulary where one exists. */
function groupCross(rows: readonly CrossLayerFinding[], key: string): Group<CrossLayerFinding>[] {
  const keysOf = (c: CrossLayerFinding): string[] | null => {
    if (key === "severity") return [c.severity];
    if (key === "layer") return c.layers === null ? null : [c.layers];
    if (key === "host") return c.hosts.length === 0 ? null : [...c.hosts];
    return ["all"];
  };
  if (key === "none") {
    return [{ key: "all", label: "All cross-layer records", observed: true, items: [...rows] }];
  }
  const buckets = new Map<string, CrossLayerFinding[]>();
  const unobserved: CrossLayerFinding[] = [];
  for (const c of rows) {
    const ks = keysOf(c);
    if (ks === null || ks.length === 0) {
      unobserved.push(c);
      continue;
    }
    for (const k of ks) {
      const list = buckets.get(k);
      if (list) list.push(c);
      else buckets.set(k, [c]);
    }
  }
  const ordered =
    key === "severity"
      ? SEVERITY_ORDER.filter((s) => buckets.has(s)).map(String)
      : [...buckets.keys()].sort((a, b) => (buckets.get(b)?.length ?? 0) - (buckets.get(a)?.length ?? 0) || cmpStr(a, b));
  const groups: Group<CrossLayerFinding>[] = ordered.map((k) => ({
    key: k,
    label: k,
    observed: true,
    items: buckets.get(k) ?? [],
  }));
  if (unobserved.length > 0) {
    groups.push({ key: UNOBSERVED_GROUP, label: "Not observed", observed: false, items: unobserved });
  }
  return groups;
}

/* ── corpora ────────────────────────────────────────────────────────────────── */

const idCell = (v: string): ReactNode => <TextCell value={v} className="pq-id" />;

function buildFindingColumns(onDrill: (f: Finding) => void): GridColumn<Finding>[] {
  return [
    {
      id: "sev",
      header: "Sev",
      headerLabel: "Severity",
      width: "1.5rem",
      sortable: true,
      render: (f) => <SeverityBadge severity={f.severity} compact />,
    },
    {
      id: "id",
      header: "ID",
      headerLabel: "Finding identifier",
      width: "1.75rem",
      rowHeader: true,
      sortable: true,
      render: (f) => idCell(f.id),
    },
    {
      id: "title",
      header: "Finding",
      width: "minmax(0, 1fr)",
      sortable: true,
      render: (f) => <TitleCell title={f.title} hosts={f.devices} />,
    },
    {
      id: "category",
      header: "Category",
      width: "minmax(0, max-content)",
      sortable: true,
      resizable: true,
      minPx: 56,
      maxPx: 220,
      unobservedWhat: "category",
      render: (f) => orNotObserved(f.category, (v) => <TextCell value={v} className="pq-meta" />, { what: "category", compact: true }),
    },
    {
      id: "devices",
      header: "Devices",
      width: "minmax(0, max-content)",
      sortable: true,
      resizable: true,
      minPx: 56,
      maxPx: 260,
      render: (f) => <HostList hosts={f.devices} what="devices" />,
    },
    {
      id: "wave",
      header: "Wave",
      width: "minmax(0, max-content)",
      sortable: true,
      unobservedWhat: "migration wave",
      render: (f) => orNotObserved(f.wave, (v) => <TextCell value={v} className="pq-meta" />, { what: "migration wave", compact: true }),
    },
    {
      id: "priority",
      header: "Pri",
      headerLabel: "Priority",
      width: "2.5rem",
      align: "end",
      sortable: true,
      unobservedWhat: "priority",
      render: (f) => orNotObserved(f.priority, (v) => <TextCell value={String(v)} className="pq-num" />, { what: "priority", compact: true }),
    },
    {
      id: "rank",
      header: "Rank",
      width: "2.5rem",
      align: "end",
      sortable: true,
      unobservedWhat: "rank",
      render: (f) => orNotObserved(f.rank, (v) => <TextCell value={String(v)} className="pq-num" />, { what: "rank", compact: true }),
    },
    {
      id: "drill",
      header: "Evidence",
      width: "1.5rem",
      interactive: true,
      soleControl: true,
      align: "end",
      cellLabel: (f) => `Open the source record for ${f.id} at ${f.cite}`,
      render: (f, cell) => (
        <IconButton
          size="sm"
          label={`Open the source record for ${f.id} at ${f.cite}`}
          icon={<IconCite />}
          tabIndex={cell.tabIndex}
          onClick={(e) => {
            e.stopPropagation();
            onDrill(f);
          }}
        />
      ),
    },
  ];
}

function buildCrossColumns(onDrill: (c: CrossLayerFinding) => void): GridColumn<CrossLayerFinding>[] {
  return [
    {
      id: "sev",
      header: "Sev",
      headerLabel: "Severity",
      width: "1.5rem",
      sortable: true,
      render: (c) => <SeverityBadge severity={c.severity} compact />,
    },
    {
      id: "id",
      header: "ID",
      headerLabel: "Cross-layer rule identifier",
      width: "1.75rem",
      rowHeader: true,
      sortable: true,
      render: (c) => idCell(c.id),
    },
    {
      id: "title",
      header: "Cross-layer record",
      width: "minmax(0, 1fr)",
      sortable: true,
      render: (c) => <TitleCell title={c.title} hosts={c.hosts} />,
    },
    {
      id: "layers",
      header: "Layers",
      width: "minmax(0, max-content)",
      sortable: true,
      resizable: true,
      minPx: 56,
      maxPx: 180,
      unobservedWhat: "layers",
      render: (c) => orNotObserved(c.layers, (v) => <TextCell value={v} className="pq-meta" />, { what: "layers", compact: true }),
    },
    {
      id: "hosts",
      header: "Hosts",
      width: "minmax(0, max-content)",
      sortable: true,
      resizable: true,
      minPx: 56,
      maxPx: 260,
      render: (c) => <HostList hosts={c.hosts} what="hosts" />,
    },
    {
      id: "drill",
      header: "Evidence",
      width: "1.5rem",
      interactive: true,
      soleControl: true,
      align: "end",
      cellLabel: (c) => `Open the source record for ${c.id} at ${c.cite}`,
      render: (c, cell) => (
        <IconButton
          size="sm"
          label={`Open the source record for ${c.id} at ${c.cite}`}
          icon={<IconCite />}
          tabIndex={cell.tabIndex}
          onClick={(e) => {
            e.stopPropagation();
            onDrill(c);
          }}
        />
      ),
    },
  ];
}

const FINDING_SORT_OF: Readonly<Record<string, FindingSortField>> = {
  sev: "severity",
  id: "id",
  title: "title",
  category: "category",
  devices: "devices",
  wave: "wave",
  priority: "priority",
  rank: "rank",
};

const CROSS_SORT_OF: Readonly<Record<string, string>> = {
  sev: "severity",
  id: "id",
  title: "title",
  layers: "layers",
  hosts: "hosts",
};

const crossCell = (c: CrossLayerFinding, field: string): string | number | null => {
  switch (field) {
    case "severity":
      return severityRank(c.severity);
    case "id":
      return c.id;
    case "title":
      return c.title.toLowerCase();
    case "layers":
      return c.layers;
    case "hosts":
      return c.hosts.length === 0 ? null : c.hosts.length;
    default:
      return null;
  }
};

/* ── query-bar helpers ──────────────────────────────────────────────────────── */

/** A value carrying whitespace or a comma has to be quoted, or the parser reads it as two clauses. */
const quoteValue = (v: string): string => (/[\s,"]/.test(v) ? `"${v.replace(/"/g, "")}"` : v);

const splice = (input: string, start: number, end: number, insert: string): string =>
  `${input.slice(0, start)}${insert}${input.slice(end)}`;

/** Ranges the parser flagged as a legal-looking value that matches nothing in this snapshot. */
const unmatchableRanges = (parsed: ParsedQuery): ReadonlySet<number> =>
  new Set(parsed.unmatchableValues.map((u) => u.range.start));

function QueryTokens({ input, parsed }: { input: string; parsed: ParsedQuery }): ReactNode {
  const flagged = unmatchableRanges(parsed);
  const toks = [...parsed.tokens].sort((a, b) => a.start - b.start);
  const out: ReactNode[] = [];
  let pos = 0;
  for (const t of toks) {
    if (t.end <= pos) continue;
    if (t.start > pos) out.push(<span key={`gap-${pos}`}>{input.slice(pos, t.start)}</span>);
    const kind: QueryToken["kind"] = t.kind;
    out.push(
      <span
        key={`tok-${t.start}`}
        className="pq-tok"
        data-kind={kind}
        data-unmatchable={kind === "value" && flagged.has(t.start) ? "yes" : undefined}
      >
        {input.slice(t.start, t.end)}
      </span>,
    );
    pos = t.end;
  }
  if (pos < input.length) out.push(<span key="tail">{input.slice(pos)}</span>);
  return <>{out}</>;
}

/* ── filter accounting ──────────────────────────────────────────────────────── */

const clauseLabel = (c: Clause): string =>
  `${c.negated ? "-" : ""}${c.key}:${c.values.join(",")}`;

function ClauseRow({ outcome, noun }: { outcome: ClauseOutcome; noun: string }): ReactNode {
  const { clause, matched, excluded, undetermined, withoutThisClause, applicability, note } = outcome;
  const problem = applicability === "unrecognised" || applicability === "not-applicable";
  return (
    <li className="pq-clause" data-problem={problem ? "yes" : undefined}>
      <span className="pq-clause__name">{clauseLabel(clause)}</span>
      <span className="pq-clause__nums">
        <span>{`${matched} matched`}</span>
        <span>{`${excluded} excluded`}</span>
        {/* Undetermined is rendered in the unobserved ink and never folded into "excluded": a row
            nobody could decide was not decided against. */}
        <span data-undetermined={undetermined > 0 ? "yes" : undefined}>{`${undetermined} undetermined`}</span>
        <span className="pq-clause__without">{`${withoutThisClause} ${noun} without it`}</span>
      </span>
      {note ? <p className="pq-clause__note">{note}</p> : null}
    </li>
  );
}

/* ── the view-controls fold (O24) ───────────────────────────────────────────── */

/**
 * The queue folds its Group / Order / Display block behind one disclosure when showing it would
 * leave fewer finding rows than this in view at rest. Six is the grid's own floor — its sticky
 * header plus six rows (review/layout-guard.mjs, invariant 2, fails below four).
 */
const MIN_UNFOLDED_ROWS = 6;

/**
 * Does `a` clip the queue's rows into a port of its own? Any ancestor whose overflow is not
 * `visible` — EXCEPT the document's own scroller: the root, or <body> when its `auto`/`scroll`
 * overflow belongs to the viewport (below 768 px the page itself scrolls, shell.css). There every
 * row can be scrolled into view, so the viewport is not the queue's port; counting it made the fold
 * follow page scroll and whatever sat above the queue (the phone Inspector sheet folded the view
 * controls part-way through a session — PriorityQueue.fold-port.test.ts). A fixed frame's
 * `overflow: hidden` body (768 px and up) is a real port and still counts. One predicate for the
 * count, the geometry key and the observers, so the three cannot disagree about what the port is.
 */
function clipsRows(a: Element): boolean {
  const overflowY = getComputedStyle(a).overflowY;
  if (overflowY === "visible") return false;
  const documentScroller = a === document.documentElement || a === document.body || a === document.scrollingElement;
  return !(documentScroller && (overflowY === "auto" || overflowY === "scroll"));
}

/**
 * How many finding rows are in view AT REST with `shrink` px less port — the question the fold
 * asks with `shrink` = 0 while the controls are shown, and = their height while they are folded
 * (unfolding them would push the grid down by exactly that much). The port is the grid's box
 * below its sticky header, cut by every clipping ancestor (the rail that holds the queue and the
 * path panel), in coordinates with each such ancestor's scroll undone, so the answer does not
 * change as the reader scrolls the rail. Rows are counted by their laid-out centres, as a click
 * would find them — NOT as port height over one row's height: rows wrap to two or three lines,
 * and MEASURED at 1440x900 with a trace the first row was 40 px and the next 56, so a height-based
 * estimate read 6 rows where 4 were on screen. Null before layout (jsdom, a hidden rail).
 */
export function restingRowsInView(root: HTMLElement, shrink: number): number | null {
  const grid = root.querySelector<HTMLElement>(".ag__grid");
  const rows = grid?.querySelectorAll<HTMLElement>(".ag__row--data") ?? [];
  if (!grid || rows.length === 0) return null;
  const g = grid.getBoundingClientRect();
  if (!(g.height > 0)) return null;
  /* Undo the scroll of every clipping ancestor: `offset` is added to every viewport y inside them. */
  let offset = 0;
  const clips: number[] = [];
  for (let a = grid.parentElement; a !== null; a = a.parentElement) {
    if (!clipsRows(a)) continue;
    offset += a.scrollTop;
    const r = a.getBoundingClientRect();
    clips.push(r.top + a.clientTop + a.clientHeight);
  }
  const head = grid.querySelector<HTMLElement>(".ag__row--head")?.getBoundingClientRect().height ?? 0;
  const top = g.top + offset + head;
  /* A clipping ancestor's own box does not move with its scroll, so its bottom is already at rest;
     only the content inside it (the grid and its rows) is shifted by `offset`. */
  const bottom = Math.min(g.bottom + offset, ...clips) - shrink;
  let n = 0;
  for (const row of rows) {
    const r = row.getBoundingClientRect();
    const mid = (r.top + r.bottom) / 2 + offset;
    if (r.height > 0 && mid >= top && mid <= bottom) n += 1;
  }
  return n;
}

/* ── props ──────────────────────────────────────────────────────────────────── */

export interface PriorityQueueProps {
  /**
   * The drill affordance: open the raw source record behind a row. Defaults to selecting the row
   * and switching Rail B to its `raw` tab, which is the third of the three interactions acceptance
   * A1 budgets for reaching configuration evidence.
   */
  onOpenEvidence?: (cite: Cite, id: string) => void;
  /** Overrides what selecting a row does. The default re-aims the shared investigation context. */
  onSelectFinding?: (id: string) => void;
  /** Debounce before a keystroke reaches the shared query state. 0 in tests. */
  debounceMs?: number;
  className?: string;
}

/* ── the surface ────────────────────────────────────────────────────────────── */

export function PriorityQueue({
  onOpenEvidence,
  onSelectFinding,
  debounceMs = 120,
  className,
}: PriorityQueueProps): ReactNode {
  const query = useInvestigation((s) => s.query);
  const setQuery = useInvestigation((s) => s.setQuery);
  const severities = useInvestigation((s) => s.severities);
  const roles = useInvestigation((s) => s.roles);
  const onlyUncollected = useInvestigation((s) => s.onlyUncollected);
  const toggleSeverity = useInvestigation((s) => s.toggleSeverity);
  const toggleRole = useInvestigation((s) => s.toggleRole);
  const setOnlyUncollected = useInvestigation((s) => s.setOnlyUncollected);
  /* The shared selection is read DEFERRED (acceptance E3, journeys 1 and 4). A selection made on
     another surface — a trace landing, a device picked in 3-D, a finding chosen in the Inspector —
     is one urgent store write that re-renders every subscriber in one task. The queue's share of
     that work (marking the related rows, then measuring and scrolling to the revealed one) is the
     largest single piece of it, so the queue takes it in a deferred render: React commits it in a
     task of its own after the other surfaces, and time-slices its render phase. The queue's OWN
     clicks do not wait on this — they are marked from local state (see pendingFinding). */
  const urgentFindingId = useInvestigation((s) => s.findingId);
  const findingId = useDeferredValue(urgentFindingId);
  const urgentDeviceId = useInvestigation((s) => s.deviceId);
  const urgentLinkId = useInvestigation((s) => s.linkId);
  const deviceId = useDeferredValue(urgentDeviceId);
  const linkId = useDeferredValue(urgentLinkId);
  const urgentHopIndex = useInvestigation((s) => s.hopIndex);
  const hopIndex = useDeferredValue(urgentHopIndex);
  const selectFinding = useInvestigation((s) => s.selectFinding);
  const setEvidenceTab = useInvestigation((s) => s.setEvidenceTab);

  const [corpus, setCorpus] = usePref<CorpusId>(
    "corpus",
    "findings",
    (r) => (r === "findings" || r === "cross-layer" ? r : null),
    (v) => v,
  );
  const [density, setDensity] = usePref<"comfortable" | "compact">(
    "density",
    "comfortable",
    (r) => (r === "comfortable" || r === "compact" ? r : null),
    (v) => v,
  );
  const [showEmptyGroups, setShowEmptyGroups] = usePref<boolean>(
    "emptyGroups",
    true,
    (r) => (r === "0" ? false : r === "1" ? true : null),
    (v) => (v ? "1" : "0"),
  );
  const [hidden, setHidden] = usePref<ReadonlySet<string>>(
    "hiddenColumns",
    /* `devices` / `hosts` are off by default because the row now LEADS with the device (see
       TitleCell): showing it a second time in its own track spends the rail's scarcest resource on
       a duplicate. Both are still real, sortable columns — the Display popover brings either back,
       and the Order control sorts by them whether or not they are on screen. */
    new Set(["wave", "priority", "rank", "devices", "hosts"]),
    (r) => new Set(r.split(",").filter(Boolean)),
    (v) => [...v].join(","),
  );
  const [collapsedRaw, setCollapsedRaw] = usePref<ReadonlySet<string>>(
    "collapsed",
    new Set<string>(),
    (r) => new Set(r.split("\u0000").filter(Boolean)),
    (v) => [...v].join("\u0000"),
  );
  const [groupKey, setGroupKey] = usePref<string>("groupKey", "severity", (r) => r, (v) => v);
  const [ordering, setOrdering] = useState<Ordering>(RANKED);
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({});

  /* The rail's content-box width, published as `--pq-inline` for the category track. Replaces a
     `container-type: inline-size` query container whose every layout re-resolved all 146 row grids
     — see the note on `.pq` in PriorityQueue.css for the measurement. */
  const rootRef = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (el === null || typeof ResizeObserver === "undefined") return;
    let last = -1;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        if (w === last) continue;
        last = w;
        el.style.setProperty("--pq-inline", `${w}px`);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const queryInputRef = useRef<HTMLInputElement | null>(null);
  /** The filter field: where focus goes when a control that removes itself (a scope chip, the empty
   *  state's "Clear the filter text") leaves nothing else in its group (acceptance D3). */
  const queryField = useCallback((): HTMLInputElement | null => queryInputRef.current, []);
  /**
   * The painted-token layer under the real characters. It is a SEPARATE box from the input, so it
   * does not inherit the input's horizontal scroll: once a query was longer than the field, the
   * input scrolled and the ink did not, and the reader was shown the first 34 characters of their
   * filter cut flush at the field edge with the caret somewhere else entirely. Syncing scrollLeft
   * on every scroll and every keystroke is what makes a long query readable at all.
   */
  const queryInkRef = useRef<HTMLDivElement | null>(null);
  const syncInkScroll = useCallback((): void => {
    const input = queryInputRef.current;
    const ink = queryInkRef.current;
    if (input && ink) ink.scrollLeft = input.scrollLeft;
  }, []);
  const accountingId = useId();

  /* ── the view controls fold (O24) ──
     MEASURED (acceptance, O24): at 1280x800 with a trace open only 2 of 146 finding rows were
     hit-testable — the queue's chrome was ~330 px at the 280 px rail, and 145 px of it was the
     Group / Order / Display block, stacked because the rail is too narrow to seat them side by side.
     The grid kept its 19rem floor and ran under the end of its rail. So when the controls leave
     fewer than MIN_UNFOLDED_ROWS finding rows in view at rest, they fold behind ONE disclosure
     ("View", beside the filter field, so folding costs no line of its own).

     The condition is MEASURED, never a width, and it is kept only while it WORKS:
       - shown, the rows actually in view are counted (restingRowsInView); fewer than the floor folds;
       - folded, the rows in view are counted again. If folding put no more rows on screen than the
         unfolded count taken at the same geometry, it is undone and not retried at that geometry.
         MEASURED: at 1920x1080 and 1440x900 with a trace, the rail's path track sits below its
         share and takes whatever the queue gives up, so folding showed 4 rows exactly as unfolded
         did — it hid the controls for nothing. At 1280x800 the path track is already at its floor,
         and the same fold took the rows from 2 to 4.
       - folded at a geometry never measured unfolded (the window grew while folded), the unfolded
         count is estimated from the block's last measured height; enough rows unfolds.
     Geometry is the clipping ancestors' size and child count and the queue's width: a resize, a
     path panel arriving or leaving, starts a fresh measurement. Nothing about the controls' state
     moves: they stay mounted (hidden while folded) and read and write exactly the preferences they
     did before. */
  const viewId = `${accountingId}-view`;
  const controlsRef = useRef<HTMLDivElement | null>(null);
  const viewButtonRef = useRef<HTMLButtonElement | null>(null);
  const controlsCost = useRef<number | null>(null);
  /** At which geometry the unfolded rows were counted, how many, and whether folding there helped. */
  const foldTrial = useRef<{ geometry: string; unfolded: number | null; futile: boolean }>({ geometry: "", unfolded: null, futile: false });
  const [viewFolded, setViewFolded] = useState(false);
  const [viewOpen, setViewOpen] = useState(false);
  const foldRef = useRef({ viewFolded, viewOpen });
  foldRef.current = { viewFolded, viewOpen };
  /* Whatever hides the Group/Order/Display block while focus is inside it (the fold below keeps it open
     for a resize, but not for every path), focus goes to the View disclosure that stands for it. */
  useReleaseFocusOnHide(controlsRef, !(viewFolded && !viewOpen), () => [viewButtonRef.current]);
  /* And the reverse: UNFOLDING removes the View disclosure, which may hold focus. MEASURED on a
     release build (independent verifier, D3-R2-1): 'LOST 1100->1440 stop 13: BUTTON.ui-btn "View" ->
     BODY'. The hand-off used to be a microtask queued from the ResizeObserver callback, which ran
     BEFORE React committed the unfold — focus was still on the button, so it did nothing, and the
     commit then removed the button. The fold is this panel's layout decision, so it is declared to the
     owner (focus-return.ts, fourth door), which runs in the commit that removes the button: focus goes
     to the successor the button states — the Group/Order/Display controls it stood for. */
  useReleaseFocusOnLayoutChange(viewFolded);
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (root === null || typeof ResizeObserver === "undefined") return;
    const geometryOf = (): string => {
      const parts = [String(root.clientWidth)];
      for (let a = root.parentElement; a !== null; a = a.parentElement) {
        if (clipsRows(a)) parts.push(`${a.clientWidth}x${a.clientHeight}/${a.childElementCount}`);
      }
      return parts.join("|");
    };
    const setFold = (fold: boolean, controls: HTMLElement): void => {
      const active = document.activeElement;
      if (fold) {
        /* Folding under a reader who is IN the controls would hide the control they hold: keep the
           block open under its disclosure instead, so their focus never falls to <body>. */
        if (active instanceof Node && controls.contains(active)) setViewOpen(true);
      } else {
        /* The disclosure is about to go; the controls it stood for take its place and the focus
           (useReleaseFocusOnLayoutChange above, in the commit that removes it). */
        setViewOpen(false);
      }
      setViewFolded(fold);
    };
    const decide = (): void => {
      const controls = controlsRef.current;
      if (controls === null) return;
      const { viewFolded: folded, viewOpen: open } = foldRef.current;
      const shown = !controls.hidden;
      if (shown) {
        const h = controls.getBoundingClientRect().height;
        if (h > 0) controlsCost.current = h;
      }
      /* Open under the disclosure is the reader's choice; the fold does not re-decide under them. */
      if (folded && open) return;
      const rows = restingRowsInView(root, 0);
      if (rows === null) return;
      const geometry = geometryOf();
      const trial = foldTrial.current;
      if (trial.geometry !== geometry) foldTrial.current = { geometry, unfolded: null, futile: false };
      const t = foldTrial.current;
      if (!folded) {
        t.unfolded = rows;
        if (rows < MIN_UNFOLDED_ROWS && !t.futile) setFold(true, controls);
        return;
      }
      if (t.unfolded !== null) {
        if (rows <= t.unfolded) {
          t.futile = true;
          setFold(false, controls);
        }
        return;
      }
      const cost = controlsCost.current;
      const estimate = cost === null ? null : restingRowsInView(root, cost);
      if (estimate !== null && estimate >= MIN_UNFOLDED_ROWS) setFold(false, controls);
    };
    const ro = new ResizeObserver(decide);
    ro.observe(root);
    const grid = root.querySelector(".ag__grid");
    if (grid !== null) ro.observe(grid);
    /* The space also moves when something ABOVE the queue in a clipping ancestor changes size (the
       path panel's height handle) or arrives (a trace opening the path panel): observe every
       clipping ancestor, each of its children, and its child list. MEASURED: without the child
       list, a restored trace mounted the path panel after this effect ran and nothing re-decided —
       the controls stayed unfolded at 1280x800 with 2 rows hit-testable. */
    const mo = typeof MutationObserver === "undefined" ? null : new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes) if (n instanceof Element) ro.observe(n);
      decide();
    });
    for (let a = root.parentElement; a !== null; a = a.parentElement) {
      if (!clipsRows(a)) continue;
      ro.observe(a);
      for (const child of a.children) ro.observe(child);
      mo?.observe(a, { childList: true });
    }
    window.addEventListener("resize", decide);
    decide();
    return () => {
      ro.disconnect();
      mo?.disconnect();
      window.removeEventListener("resize", decide);
    };
    /* `density` moves the row height, which moves the answer without resizing any observed box. */
  }, [viewFolded, viewOpen, density]);

  /* ── the drill and selection handlers ── */

  /* The caller's callbacks are read through a ref, NOT listed as dependencies.
     RESPONSIVENESS FIX, 2026-09-21 (acceptance E2/E3, journey 1): the app passes
     `onOpenEvidence={(cite) => onOpenCite(cite)}`, a fresh function on every render of the
     surface, and every selection re-renders that surface. Listed as a dependency it rebuilt
     `openEvidence`, which rebuilt the column set, which re-rendered all 146 rows of the grid
     inside the click — the long `DIV#root.onclick` task. The queue must not depend on every caller
     remembering to memoise; the ref makes the identity of the handlers the queue's own business. */
  const callerRef = useRef({ onOpenEvidence, onSelectFinding });
  useLayoutEffect(() => {
    callerRef.current = { onOpenEvidence, onSelectFinding };
  });

  const openEvidence = useCallback(
    (cite: Cite, id: string): void => {
      const open = callerRef.current.onOpenEvidence;
      if (open) {
        open(cite, id);
        return;
      }
      if (findingById.has(id)) selectFinding(id);
      setEvidenceTab("raw");
    },
    [selectFinding, setEvidenceTab],
  );

  /* ══ the selection commit is SPLIT — acceptance E3, journey 1 ═══════════════════════════
   *
   * THE DEFECT (critic, release build, headed): selecting a finding ran a 57-195 ms task INSIDE
   * the click handler on every repetition — LoAF `DIV#root.onclick`, max 170 ms. `selectFinding`
   * is a store write, a store write is an urgent `useSyncExternalStore` update, and it re-aimed
   * the queue, the device pane, the evidence rail, the Inspector, the status bar and the fabric in
   * that one task. PathTrace.run had already been split for exactly this reason; this handler had
   * not.
   *
   * WHAT THIS DOES. The row the reader clicked is marked from LOCAL state, so the click commits
   * this panel alone and the acknowledgement frame already shows the new active row. The shared
   * write that re-aims every other surface goes to `deferPastPaint` — a task of its own after that
   * frame is painted. `selectSeq` makes a later click, or an Escape, supersede a write that has
   * not landed yet, so a quick second click can never be overwritten by the first. */
  const [pendingFinding, setPendingFinding] = useState<{ id: string | null } | null>(null);
  const selectSeq = useRef(0);
  /** What THIS panel marks: the locally-committed selection until the store catches up. */
  const shownFindingId = pendingFinding === null ? findingId : pendingFinding.id;
  useEffect(() => {
    if (pendingFinding !== null && findingId === pendingFinding.id) setPendingFinding(null);
  }, [pendingFinding, findingId]);

  const selectRow = useCallback(
    (id: string): void => {
      const select = callerRef.current.onSelectFinding;
      if (select) {
        select(id);
        return;
      }
      const seq = ++selectSeq.current;
      setPendingFinding({ id });
      deferPastPaint(() => {
        if (selectSeq.current !== seq) return;
        /* Re-aiming, not resetting: the device, the flow and the camera are untouched, and Rail B
           swaps to the tab that can actually show this record (design-brief §5.1, interaction 1).
           Two setters, one task: React batches them into one commit. */
        selectFinding(id);
        setEvidenceTab("findings");
      });
    },
    [selectFinding, setEvidenceTab],
  );

  /** Clear the selection NOW, superseding any selection write that has not landed yet. */
  const clearSelection = useCallback((): void => {
    selectSeq.current += 1;
    setPendingFinding(null);
    selectFinding(null);
  }, [selectFinding]);

  /* ── corpora ── */

  const findingColumns = useMemo(() => buildFindingColumns((f) => openEvidence(f.cite, f.id)), [openEvidence]);
  const crossColumns = useMemo(
    () => buildCrossColumns((c) => openEvidence(c.cite, crossLayerBridge.get(crossRowId(c)) ?? c.id)),
    [openEvidence],
  );

  const findingCorpus: CorpusSpec<Finding> = useMemo(
    () => ({
      id: "findings",
      noun: "findings",
      rows: fabric.findings,
      idOf: (f) => f.id,
      citeOf: (f) => f.cite,
      lineOf: (f) => `${f.severity}	${f.id}	${f.title}	${f.category ?? "category not observed"}	${f.devices.length > 0 ? f.devices.join(" ") : "no device named"}	${f.cite}`,
      columns: findingColumns,
      groupKeys: [
        { value: "severity", label: "Severity", vocabulary: () => SEVERITY_ORDER.map(String) },
        { value: "category", label: "Category", vocabulary: () => domainValues("category") },
        { value: "host", label: "Device", vocabulary: () => domainValues("host") },
        { value: "wave", label: "Migration wave", vocabulary: () => domainValues("wave") },
        { value: "band", label: "Device health band", vocabulary: () => domainValues("band") },
        { value: "role", label: "Device role", vocabulary: () => domainValues("role") },
        { value: "none", label: "No grouping", vocabulary: () => [] },
      ],
      group: (rows, key) => groupBy(rows, key as FindingGroupKey),
      sortFieldOf: (columnId) => own(FINDING_SORT_OF, columnId) ?? null,
      order: (rows, o) =>
        o.kind === "ranked"
          ? [...rows].sort(bySeverityThenRank)
          : sortBy(rows, [{ field: o.spec.field as FindingSortField, direction: o.spec.direction }]),
      filter: (rows, parsed) => applyToFindings(rows, parsed),
      rankedLabel: "Ranked: severity, then priority, then rank",
    }),
    [findingColumns],
  );

  const crossCorpus: CorpusSpec<CrossLayerFinding> = useMemo(
    () => ({
      id: "cross-layer",
      noun: "cross-layer records",
      rows: fabric.crossLayer,
      idOf: crossRowId,
      citeOf: (c) => c.cite,
      lineOf: (c) => `${c.severity}	${c.id}	${c.title}	${c.layers ?? "layers not observed"}	${c.hosts.length > 0 ? c.hosts.join(" ") : "no host named"}	${c.cite}`,
      columns: crossColumns,
      groupKeys: [
        { value: "severity", label: "Severity", vocabulary: () => SEVERITY_ORDER.map(String) },
        { value: "layer", label: "Layers", vocabulary: () => domainValues("layer") },
        { value: "host", label: "Device", vocabulary: () => domainValues("host") },
        { value: "none", label: "No grouping", vocabulary: () => [] },
      ],
      group: groupCross,
      sortFieldOf: (columnId) => own(CROSS_SORT_OF, columnId) ?? null,
      order: (rows, o) =>
        o.kind === "ranked"
          ? [...rows].sort(
              (a, b) => severityRank(a.severity) - severityRank(b.severity) || cmpStr(a.id, b.id) || cmpStr(a.cite, b.cite),
            )
          : [...rows].sort(
              (a, b) =>
                cmpCell(crossCell(a, o.spec.field), crossCell(b, o.spec.field), o.spec.direction) ||
                cmpStr(a.id, b.id) ||
                cmpStr(a.cite, b.cite),
            ),
      filter: (rows, parsed) => applyToCrossLayer(rows, parsed),
      rankedLabel: "Ranked: severity, then identifier",
    }),
    [crossColumns],
  );

  const spec = (corpus === "findings" ? findingCorpus : crossCorpus) as CorpusSpec<Finding | CrossLayerFinding>;

  /* ── query state: the echo is synchronous, the filter is debounced ──────────
     Coupling them is what makes a search box feel like it is thinking (§8.2 journey 3). */

  const [draft, setDraft] = useState(query);
  const [caret, setCaret] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState(0);
  const pushed = useRef(query);

  useEffect(() => {
    // An external write (URL hydrate, palette, a cleared filter) wins; our own echo does not
    // bounce back in and fight the caret.
    if (query !== pushed.current) {
      pushed.current = query;
      setDraft(query);
    }
  }, [query]);

  useEffect(() => {
    if (draft === pushed.current) return;
    const t = setTimeout(() => {
      pushed.current = draft;
      setQuery(draft);
    }, debounceMs);
    return () => clearTimeout(t);
  }, [draft, debounceMs, setQuery]);

  /* ── the effective query: the user's text plus the scope the store carries ──
     Folding the store's scope into the SAME grammar means the per-clause accounting covers it
     too, instead of a second filtering path with no explanation attached. */

  /* Each scope clause carries how to take it off again, so a control that widens the filter (the
     "outside your filter" reveal below) removes a chip through the same store action its own ×
     does, rather than through a second, parallel idea of what the scope is. */
  const scopeParts = useMemo((): ScopePart[] => {
    const out: ScopePart[] = [];
    if (severities.size > 0) {
      const on = SEVERITY_ORDER.filter((s) => severities.has(s));
      out.push({ text: `severity:${on.map(quoteValue).join(",")}`, clear: () => on.forEach((s) => toggleSeverity(s)) });
    }
    if (roles.size > 0) {
      const on = [...roles].sort(cmpStr);
      out.push({ text: `role:${on.map(quoteValue).join(",")}`, clear: () => on.forEach((r) => toggleRole(r)) });
    }
    if (onlyUncollected) out.push({ text: "is:uncollected", clear: () => setOnlyUncollected(false) });
    return out;
  }, [severities, roles, onlyUncollected, toggleSeverity, toggleRole, setOnlyUncollected]);
  const scopeClauses = useMemo(() => scopeParts.map((p) => p.text), [scopeParts]);

  /* The FILTER reads a deferred copy of the text; the field's echo (and its token ink) reads
     `draft` itself. RESPONSIVENESS FIX, 2026-09-21 (E2/E3, J3b): a query typed in the header
     reaches this surface as a store write, and re-filtering and re-rendering the 146-row grid in
     that same urgent render put 50-211 ms of React work between one keystroke and the next. As a
     deferred value the recompute is a transition render: React time-slices it, and abandons it
     when the next keystroke arrives, so the grid catches up once typing pauses instead of on every
     character (design brief 8.2 journey 3: "debounced and chunked"). `busy` below stays true
     until the grid answers the text on screen. */
  const filterText = useDeferredValue(draft);
  const effective = useMemo(
    () => [...scopeClauses, filterText.trim()].filter((s) => s.length > 0).join(" "),
    [scopeClauses, filterText],
  );

  const parsedDraft = useMemo(() => parseQuery(draft), [draft]);
  const result = useMemo(() => spec.filter(spec.rows, parseQuery(effective)), [spec, effective]);

  /* The shared store addresses a selection by punchlist id only, so in the cross-layer view the
     highlighted row is whichever record bridges to the selected finding — not a second, parallel
     selection state that could disagree with the rest of the application. */
  const activeRowId = useMemo((): string | null => {
    if (corpus === "findings") return shownFindingId;
    if (shownFindingId === null) return null;
    for (const [rowId, target] of crossLayerBridge) if (target === shownFindingId) return rowId;
    return null;
  }, [corpus, shownFindingId]);

  /* ── a selection the filter hides (acceptance A4) ────────────────────────────
   *
   * THE DEFECT (refuter, 2026-09-24): `?q=severity:Critical`, then Ctrl+K "F120" Enter. The URL,
   * the status bar, the scope bar, the Inspector and the fabric label all said F120 was selected;
   * the queue showed Critical 3 / F001 / F002 / F003 / High 0 …, no row carried aria-current, and
   * the rail did not contain "F120" at all. The reveal below pointed at a row the filter had
   * removed, so nothing was revealed and nothing was said. Present since the queue was first
   * committed (50a3dc5): every A4 check before then ran over an unfiltered queue.
   *
   * WHAT THE QUEUE DOES. The selected row is PINNED above the rows the filter shows, under its own
   * group, "Outside your filter", and revealed and marked current like any selection.
   * The accounting says so in words and names every part of the filter that hides it — each clause
   * or term as typed, or the scope chip it came from — and that the filter is unchanged. One
   * control widens the filter by exactly those parts and says what it removed; the row is then in
   * place. Nothing is discarded silently: the reader's filter changes only when they press it.
   *
   * WHICH PARTS HIDE IT is computed from the grammar, not from a list of keys: every clause and
   * every free-text term the parser produced is re-run ALONE over the whole corpus (a term's fuzzy
   * widening is decided over the corpus, so running it over one row would answer a different
   * question), and a part hides the row when the row is not in that part's result. Decided against
   * versus undecided is read off the part's own `excludedTotal` with and without the row. Every
   * clause key, its negation, free text, excluded text and all three scope chips take this one path.
   */
  const pinned = useMemo((): PinnedSelection<Finding | CrossLayerFinding> | null => {
    if (activeRowId === null) return null;
    if (result.items.some((it) => spec.idOf(it) === activeRowId)) return null;
    const item = spec.rows.find((it) => spec.idOf(it) === activeRowId);
    if (item === undefined) return null;
    /* Where each scope chip and the typed text sit inside `effective` (they are joined by one space). */
    const spans: { start: number; end: number; scope: number | null }[] = [];
    let at = 0;
    scopeParts.forEach((p, i) => {
      spans.push({ start: at, end: at + p.text.length, scope: i });
      at += p.text.length + 1;
    });
    const typed = filterText.trim();
    const lead = filterText.length - filterText.trimStart().length;
    if (typed.length > 0) spans.push({ start: at, end: at + typed.length, scope: null });
    const parsed = parseQuery(effective);
    const ranges = [...parsed.clauses.map((c) => c.range), ...parsed.textTerms.map((t) => t.range)].sort(
      (a, b) => a.start - b.start,
    );
    const others = spec.rows.filter((it) => it !== item);
    const parts: HidingPart[] = [];
    for (const range of ranges) {
      const text = effective.slice(range.start, range.end);
      const alone = parseQuery(text);
      const all = spec.filter(spec.rows, alone);
      if (all.items.includes(item)) continue;
      const decided = all.excludedTotal - spec.filter(others, alone).excludedTotal === 1;
      const span = spans.find((s) => range.start >= s.start && range.start < s.end);
      const origin: HidingPart["origin"] =
        span === undefined || span.scope === null
          ? { kind: "text", start: range.start - (span?.start ?? at) + lead, end: range.end - (span?.start ?? at) + lead }
          : { kind: "scope", index: span.scope };
      parts.push({ text, decided, isText: parsed.textTerms.some((t) => t.range.start === range.start), origin });
    }
    const label =
      corpus === "findings" || shownFindingId === null
        ? activeRowId
        : `${item.id} (the cross-layer record for ${shownFindingId})`;
    return { id: activeRowId, item, parts, label, short: item.id };
  }, [activeRowId, result.items, spec, scopeParts, filterText, effective, corpus, shownFindingId]);
  const hasPinned = pinned !== null;
  const pinnedId = pinned?.id ?? null;

  /* The control: widen the filter by exactly the parts that hide the row, and say what it removed.
     A typed part is cut out of the text (highest offset first, so earlier offsets stay valid); a
     scope chip is taken off through the store action its own × uses. The statement it leaves
     ("Removed … from the filter") stays while the same row is selected. */
  const [widened, setWidened] = useState<{ id: string; label: string; removed: string[]; draftAfter: string } | null>(null);
  const widenFilter = useCallback((): void => {
    if (pinned === null) return;
    const parts =
      pinned.parts.length > 0
        ? pinned.parts
        : /* No single part hides it: the filter as a whole does, so the whole filter is what widens. */
          [
            ...scopeParts.map((p, index): HidingPart => ({ text: p.text, decided: true, isText: false, origin: { kind: "scope", index } })),
            ...(filterText.trim() === ""
              ? []
              : [{ text: filterText.trim(), decided: true, isText: true, origin: { kind: "text", start: 0, end: filterText.length } } satisfies HidingPart]),
          ];
    let text = filterText;
    const typed = parts
      .map((p) => p.origin)
      .filter((o): o is { kind: "text"; start: number; end: number } => o.kind === "text")
      .sort((a, b) => b.start - a.start);
    for (const o of typed) text = `${text.slice(0, o.start).trimEnd()} ${text.slice(o.end).trimStart()}`.trim();
    for (const p of parts) if (p.origin.kind === "scope") scopeParts[p.origin.index]?.clear();
    if (typed.length > 0) setDraft(text);
    setWidened({ id: pinned.id, label: pinned.label, removed: parts.map((p) => p.text), draftAfter: typed.length > 0 ? text : draft });
  }, [pinned, scopeParts, filterText, draft]);
  /* The pinned statement and its control go in the SAME commit as the press, not when the filter
     catches up. The typed text reaches the rows through a deferred value, and MEASURED in the
     running app (1920x1080, headless) the deferred re-render landed ~2 s after the press: the
     control stood, focused, for that long, so the focus hand-off (which looks for a removed control
     for 200 ms) found it still standing, gave up, and focus fell to <body> when it finally went.
     A scope chip comes off at once but typed text does not, so a press that removed both left the
     statement standing on the part still in flight: MEASURED by review/audit-d3-focus.mjs
     --self-removing (seeded q=gateway, sev, role, unc, f=F001): "Show F001 in place" → BODY at 390
     and 768 px, Enter and Space alike. So while the text the reader widened TO is in the field and
     the rows have not caught up with it, the statement is replaced by the "Removed …" sentence; a
     filter that hides the row again afterwards is a new filter, and is stated again. */
  const widening = widened !== null && draft === widened.draftAfter && filterText !== draft;
  const showPinned = pinned !== null && !(widening && widened !== null && widened.id === pinned.id);
  /* The "Removed …" sentence belongs to the selection it was made for; a new selection drops it, so
     coming back to the same row later does not replay an old action as if it were current. */
  useEffect(() => {
    if (widened !== null && widened.id !== activeRowId) setWidened(null);
  }, [widened, activeRowId]);
  const widenedSentence =
    widened !== null && widened.id === activeRowId
      ? `Removed ${widened.removed.join(", ")} from the filter, so ${widened.label} shows in place.`
      : "";

  /* ── grouping, ordering, node list ── */

  const collapseKey = (g: string): string => `${corpus}:${groupKey}:${g}`;

  /* Every device the query's device clauses resolve to was never collected: the result is silence,
     not observation. An empty "Critical 0 / High 0 …" bucket list would then print zeros marked
     observed (data-observed="yes") for boxes nobody assessed, while the Device pane refuses to tally
     the very same scope ("finding counts: not observed"). So in that scope no empty bucket is drawn;
     the evidence-scope note beside the grid says why the list is empty. Derived from the clause
     scopes the query engine already computes, not from the one `is:uncollected` chip, so
     `host:AP-floor1` and any other all-uncollected scope take the same rule (critic B1). */
  const evidenceBlind = result.clauses.some((c) => c.scope.kind === "device-scope" && c.scope.evidenceBlind);

  const groups = useMemo(() => {
    const key = spec.groupKeys.some((g) => g.value === groupKey) ? groupKey : "severity";
    const built = spec.group(result.items, key);
    if (evidenceBlind) return built.filter((g) => g.items.length > 0);
    if (!showEmptyGroups || key === "none") return built;
    const vocabulary = spec.groupKeys.find((g) => g.value === key)?.vocabulary() ?? [];
    const seen = new Set(built.map((g) => g.key));
    const missing = vocabulary
      .filter((v) => !seen.has(v))
      /* An empty bucket is a claim, "searched, and nothing matched". For a device-keyed grouping
         (host, role, band) that holds only when a COLLECTED device carries the value; a bucket
         whose every device was never collected was never searched. Such buckets are left out
         rather than printed as an observed zero — the evidence-scope note beside the grid already
         names how many devices were never collected (critic B1: "AP-FLOOR1 0" read exactly like
         an assessed, clean box while the Device pane said "Finding count not observed"). */
      .filter((v) => searchedByCollection(key, v))
      .map<Group<Finding | CrossLayerFinding>>((v) => ({ key: v, label: key === "band" ? bandKeyLabel(v) : v, observed: true, items: [] }));
    if (missing.length === 0) return built;
    /* A fixed vocabulary keeps its own order; anything else appends the empty buckets after the
       populated ones, sorted, so the list order never depends on which values happened to survive
       the filter. */
    if (key === "severity") {
      const byKey = new Map([...built, ...missing].map((g) => [g.key, g]));
      const ordered = SEVERITY_ORDER.map(String)
        .map((s) => byKey.get(s))
        .filter((g): g is Group<Finding | CrossLayerFinding> => g !== undefined);
      const unobserved = built.find((g) => g.key === UNOBSERVED_GROUP);
      return unobserved ? [...ordered, unobserved] : ordered;
    }
    const unobserved = built.find((g) => g.key === UNOBSERVED_GROUP);
    const populated = built.filter((g) => g.key !== UNOBSERVED_GROUP);
    const extra = [...missing].sort((a, b) => cmpStr(a.key, b.key));
    return unobserved ? [...populated, ...extra, unobserved] : [...populated, ...extra];
  }, [spec, groupKey, result.items, showEmptyGroups, evidenceBlind]);

  const nodes = useMemo<GridNode<Finding | CrossLayerFinding>[]>(() => {
    const out: GridNode<Finding | CrossLayerFinding>[] = [];
    /* With a pinned selection the rows the filter shows get their header too, even ungrouped:
       otherwise they would read as more rows of the "outside your filter" group above them. */
    const single = groups.length === 1 && groups[0]?.key === "all" && pinned === null;
    if (pinned !== null) {
      const isCollapsed = collapsedRaw.has(collapseKey(OUTSIDE_FILTER_GROUP));
      out.push({
        kind: "group",
        id: OUTSIDE_FILTER_GROUP,
        label: "Outside your filter",
        count: 1,
        observed: true,
        collapsed: isCollapsed,
        detail: <span>{pinned.parts.length === 0 ? "hidden by the filter as a whole" : `hidden by ${pinned.parts.map((p) => p.text).join(", ")}`}</span>,
      });
      /* The pinned row carries the React identity its copy will have IN PLACE (the first group it
         belongs to under this grouping, or its bare id ungrouped). No row with that identity exists
         while it is pinned — the filter has removed it — so nothing collides, and when "Show … in
         place" lands React MOVES this element rather than unmounting it: a reader whose focus is on
         the pinned row keeps it through the move. With a key of its own the element was destroyed
         and focus fell to <body> between the press and the filter catching up (MEASURED by
         review/audit-d3-focus.mjs --self-removing, 768 px). */
      const gk = spec.groupKeys.some((g) => g.value === groupKey) ? groupKey : "severity";
      const home = gk === "none" ? undefined : spec.group([pinned.item], gk)[0]?.key;
      if (!isCollapsed) {
        out.push(
          home === undefined
            ? { kind: "row", id: pinned.id, item: pinned.item }
            : { kind: "row", id: pinned.id, item: pinned.item, key: JSON.stringify([home, pinned.id]) },
        );
      }
    }
    for (const g of groups) {
      const items = spec.order(g.items, ordering);
      if (!single) {
        const isCollapsed = collapsedRaw.has(collapseKey(g.key));
        out.push({
          kind: "group",
          id: g.key,
          label: g.observed ? g.label : `${g.label} · ${groupKey}`,
          count: g.items.length,
          observed: g.observed,
          collapsed: isCollapsed,
          ...(g.observed
            ? {}
            : { detail: <span>{`no ${groupKey} value was collected for these rows`}</span>}),
        });
        if (isCollapsed) continue;
      }
      /* A multi-valued group key (host, layer) lists one item under every group it belongs to, so
         the row's React identity is qualified by its group; `id` stays the item's own. */
      for (const item of items) {
        const id = spec.idOf(item);
        out.push(single ? { kind: "row", id, item } : { kind: "row", id, item, key: JSON.stringify([g.key, id]) });
      }
    }
    return out;
    // `collapseKey` closes over corpus + groupKey, both already listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, spec, ordering, collapsedRaw, groupKey, corpus, pinned]);

  const toggleGroup = useCallback(
    (id: string): void => {
      const k = collapseKey(id);
      const next = new Set(collapsedRaw);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      setCollapsedRaw(next);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [collapsedRaw, setCollapsedRaw, corpus, groupKey],
  );

  /* ── columns, template and per-density placement ────────────────────────────
     The brief's single-line 32px row cannot hold severity + id + a 32ch title + category +
     devices inside a 300px rail: the fixed tracks alone consume ~240px, leaving the title about
     36px, which fails acceptance C3 outright. So the DEFAULT density is a two-line 46px row that
     shows all five without truncating the title below 32ch, and the brief's exact single-line row
     survives as `compact`, where the metadata columns are hidden by default and can be brought
     back at the cost of horizontal scrolling. Both are true APG grids over the same columns. */

  const visibleColumns = useMemo(
    () => spec.columns.filter((c) => !hidden.has(c.id)),
    [spec.columns, hidden],
  );

  const { columns, template } = useMemo(() => {
    const track = (c: GridColumn<Finding | CrossLayerFinding>): string => `var(--ag-w-${c.id}, ${c.width})`;
    const lead = visibleColumns.filter((c) => c.id === "sev" || c.id === "id");
    const title = visibleColumns.find((c) => c.id === "title");
    const drill = visibleColumns.find((c) => c.id === "drill");
    const metas = visibleColumns.filter((c) => !lead.includes(c) && c !== title && c !== drill);

    if (density === "compact" || !title) {
      return { columns: visibleColumns, template: visibleColumns.map(track).join(" ") };
    }
    /*
     * THE FIRST METADATA COLUMN RIDES ON THE TITLE LINE.
     *
     * Every row used to push its category onto a second line as an outlined chip, so a 32px row
     * became 49px to carry one repeated word and the rail showed half the findings it could. The
     * brief's row anatomy puts the category in its own track on line 1; that is where it goes, as
     * a right-aligned muted tag, and the row is one line again. Only columns the reader ADDS
     * through Display (wave, priority, rank ...) wrap onto a second line, under the title.
     */
    const [inline, ...wrapped] = metas;
    /*
     * THE HEADER IS ONE ROW, ALWAYS — AND EVERY GRID COLUMN HAS A REAL HEADER IN IT.
     *
     * A two-line data row previously produced a two-line header, and the second header line then
     * sat immediately above the FIRST row's first line rather than above the cells it named. The
     * next version kept one header row but left the line-2 columns in the grid's column model with
     * their header cells clipped to 1x1 px (`headerHidden`). That is a column a keyboard cannot
     * keep: ArrowRight along the header skipped it, ArrowUp from one of its data cells landed on a
     * DIFFERENT column (APG: Up/Down keep the column), its resize separator was exposed at 8x1 px
     * and could not be reached by pointer or key, and aria-colcount counted a column no sighted
     * reader could find (A11Y critic, 2026-09-21, D2/D5).
     *
     * So the columns the reader adds through Display are no longer grid columns at all in this
     * density: they are FOLDED into the title cell as its second line, each chip carrying its own
     * field name, and aria-colcount counts only the columns that have a visible header. They stay
     * sortable through the Order control, which names every field in words; switching to compact
     * density restores them as full columns with their own headers and resizers.
     */
    const folded = wrapped;
    const titleCol: GridColumn<Finding | CrossLayerFinding> =
      folded.length === 0
        ? title
        : {
            ...title,
            render: (item, cell) => (
              <span className="pq-fold">
                {title.render(item, cell)}
                <span className="pq-fold__line2">
                  {folded.map((c) => {
                    const out = c.render(item, { tabIndex: -1 });
                    const absent = out === null || out === undefined || out === false || out === "";
                    return (
                      <span key={c.id} className="pq-fold__item" data-col={c.id}>
                        <span className="pq-fold__key">{c.headerLabel ?? c.header}</span>
                        {absent ? (
                          <NotObserved compact {...(c.unobservedWhat ? { what: c.unobservedWhat } : {})} />
                        ) : (
                          out
                        )}
                      </span>
                    );
                  })}
                </span>
              </span>
            ),
          };
    const gridColumns = [...lead, titleCol, ...(inline ? [inline] : []), ...(drill ? [drill] : [])];
    const placed = gridColumns.map((c, i) => ({ ...c, place: `1 / ${i + 1} / 2 / ${i + 2}` }));
    const template = gridColumns.map((c) => (c === titleCol ? "minmax(0, 1fr)" : track(c))).join(" ");
    return { columns: placed, template };
  }, [visibleColumns, density]);

  /* ── sort wiring ── */

  const gridSort: GridSort | null =
    ordering.kind === "field"
      ? {
          columnId:
            spec.columns.find((c) => spec.sortFieldOf(c.id) === ordering.spec.field)?.id ?? ordering.spec.field,
          direction: ordering.spec.direction,
        }
      : null;

  const onSort = useCallback(
    (columnId: string): void => {
      const field = spec.sortFieldOf(columnId);
      if (field === null) return;
      setOrdering((prev) =>
        prev.kind === "field" && prev.spec.field === field
          ? { kind: "field", spec: { field, direction: prev.spec.direction === "asc" ? "desc" : "asc" } }
          : { kind: "field", spec: { field, direction: "asc" } },
      );
    },
    [spec],
  );

  /* ── suggestions ── */

  const suggestion = useMemo(() => suggest(draft, caret), [draft, caret]);
  const suggestions = useMemo(() => suggestion.suggestions.slice(0, 8), [suggestion]);
  const ghost = useMemo(() => {
    if (!menuOpen || caret !== draft.length) return "";
    const top = suggestions[activeSuggestion] ?? suggestions[0];
    if (!top) return "";
    const typed = draft.slice(suggestion.replace.start, caret);
    return top.insert.toLowerCase().startsWith(typed.toLowerCase()) ? top.insert.slice(typed.length) : "";
  }, [menuOpen, caret, draft, suggestions, activeSuggestion, suggestion.replace.start]);

  const accept = useCallback(
    (index: number): void => {
      const s = suggestions[index];
      if (!s) return;
      const next = splice(draft, suggestion.replace.start, suggestion.replace.end, s.insert);
      const pos = suggestion.replace.start + s.insert.length;
      setDraft(next);
      setCaret(pos);
      setActiveSuggestion(0);
      requestAnimationFrame(() => {
        const el = queryInputRef.current;
        if (el) {
          el.focus();
          el.setSelectionRange(pos, pos);
        }
      });
    },
    [suggestions, draft, suggestion.replace.start, suggestion.replace.end],
  );

  /* ── row counts and announcements ── */

  /* A finding selected from ANOTHER surface (the palette, the Evidence rail, the URL) while the
     cross-layer table is showing must still land on a row. Only the findings with a cross-layer
     record that joins to them uniquely have a row there, so for the rest the selected row was not
     in the DOM at all — neither marked nor revealed — while every other surface said it was
     selected (2026-09-22 critic, A4). When the new selection has no cross-layer row, the queue
     re-aims to the punchlist, which holds every finding. It fires on a CHANGE of selection only,
     so a reader who deliberately switches to the cross-layer table afterwards is not bounced back. */
  // null, not the mounted selection: a deep link (?f=F001) onto a persisted cross-layer choice is
  // a selection arriving from another surface too.
  const lastAimedFinding = useRef<string | null>(null);
  const corpusRef = useRef(corpus);
  corpusRef.current = corpus;
  const setCorpusRef = useRef(setCorpus);
  setCorpusRef.current = setCorpus;
  useEffect(() => {
    if (findingId === lastAimedFinding.current) return;
    lastAimedFinding.current = findingId;
    if (findingId === null || corpusRef.current !== "cross-layer") return;
    for (const target of crossLayerBridge.values()) if (target === findingId) return;
    setCorpusRef.current("findings");
  }, [findingId]);

  /* ── re-aiming on a device or a cable ────────────────────────────────────────
   *
   * A4 asks that selecting a device or a link re-aim EVERY other surface. The queue was the one
   * exception, and measurably so: before this existed, `?d=core2` and `?l=L18` produced a
   * BYTE-IDENTICAL grid against `?d=core2` — same innerHTML length (269,825), zero changed pixels
   * — so the surface that lists what is wrong with the fleet said nothing whatever about the box
   * the reader had just clicked.
   *
   * Marked, not filtered, and not selected:
   *   · Filtering would silently narrow the punchlist to one host while still calling itself the
   *     fleet queue — the corpus would shrink under the reader with no statement that it had.
   *   · Selecting would invent a second selection state that could disagree with `findingId`,
   *     which the whole store exists to prevent.
   * A link resolves to BOTH its endpoints, because a cable's findings are the findings of the two
   * boxes it joins; neither end is the cable.
   */
  /* The count is taken over the WHOLE shown corpus — every group, folded or not — because the
     sentence it feeds is "N of <shown> shown findings name <host>", and <shown> counts folded rows
     too. Counting only the rendered rows made that sentence false whenever a group was collapsed
     (a persisted, ordinary state): with Medium folded, core1 read "21 of 146" while the Device pane
     on the same screen said 32. The rows that are named but folded away are reported per group so
     the reader can find every one of them. */
  const relatedFor = useCallback((devId: string | null, lnkId: string | null): {
    ids: ReadonlySet<string>;
    hosts: string[];
    folded: { label: string; count: number }[];
  } => {
    const hosts: string[] = [];
    if (lnkId !== null) {
      const l = linkById.get(lnkId);
      if (l) hosts.push(l.a, l.b);
    } else if (devId !== null) {
      const d = deviceById.get(devId);
      hosts.push(d ? d.host : devId);
    }
    if (hosts.length === 0) return { ids: EMPTY_IDS, hosts, folded: [] };
    const want = new Set(hosts);
    const ids = new Set<string>();
    const folded: { label: string; count: number }[] = [];
    // The same rule as `nodes`: with a pinned row the ungrouped list has a (foldable) header.
    const single = groups.length === 1 && groups[0]?.key === "all" && !hasPinned;
    for (const g of groups) {
      const isCollapsed = !single && collapsedRaw.has(collapseKey(g.key));
      let inGroup = 0;
      for (const item of g.items) {
        const named = "devices" in item ? item.devices : item.hosts;
        if (!named.some((h) => want.has(h))) continue;
        ids.add(spec.idOf(item));
        inGroup += 1;
      }
      if (isCollapsed && inGroup > 0) folded.push({ label: g.observed ? g.label : `${g.label} · ${groupKey}`, count: inGroup });
    }
    return { ids, hosts, folded };
    // `collapseKey` closes over corpus + groupKey, both already listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, collapsedRaw, spec, corpus, groupKey, hasPinned]);
  /* The ROW MARKS follow the deferred selection (E3, above). The STATEMENT does not: it is one
     O(findings) count, and reading it deferred left "N of 146 shown findings name core1" on screen
     for 7-8 s after core2 was clicked on a loaded host (2026-09-21 critic, A4) — a sentence about
     the wrong device. It follows the urgent selection, and says so while the marks catch up. */
  const related = useMemo(() => relatedFor(deviceId, linkId), [relatedFor, deviceId, linkId]);
  const relatedNow = useMemo(() => relatedFor(urgentDeviceId, urgentLinkId), [relatedFor, urgentDeviceId, urgentLinkId]);
  const marksPending = urgentDeviceId !== deviceId || urgentLinkId !== linkId;
  const relatedFolded = relatedNow.folded.reduce((a, f) => a + f.count, 0);

  /* A selection must never land inside a collapsed group. With Critical and High collapsed from a
     previous session, `?f=F002` produced a queue with no marked row at all — no aria-current, no
     F002 row — while the URL, the evidence pane and the live region all said F002 was selected.
     The group that holds the selected row is expanded when the SELECTION changes (not on every
     collapse), so a reader can still fold that group deliberately afterwards. The collapsed set is
     read through a ref for exactly that reason: it is not a trigger. */
  const collapsedRef = useRef(collapsedRaw);
  collapsedRef.current = collapsedRaw;
  useEffect(() => {
    if (activeRowId === null) return;
    /* A selection the filter hides lands in the "outside your filter" group, which obeys the same
       rule: it is opened when the selection (or its pinning) changes, never re-opened behind a
       reader who folds it afterwards. */
    if (pinnedId === activeRowId) {
      const k = collapseKey(OUTSIDE_FILTER_GROUP);
      if (!collapsedRef.current.has(k)) return;
      const next = new Set(collapsedRef.current);
      next.delete(k);
      setCollapsedRaw(next);
      return;
    }
    /* A multi-valued group key (host, band, role) lists the row under EVERY group it belongs to.
       One open holder already puts it on screen, so a group is expanded only when every holder is
       collapsed — and then the first one. Opening the first holder regardless re-opened a group the
       reader had folded while the row they were looking at sat in another (A4). */
    const holders = groups.filter((g) => g.items.some((it) => spec.idOf(it) === activeRowId));
    const holder = holders[0];
    if (!holder) return;
    if (holders.some((g) => !collapsedRef.current.has(collapseKey(g.key)))) return;
    const k = collapseKey(holder.key);
    const next = new Set(collapsedRef.current);
    next.delete(k);
    setCollapsedRaw(next);
    // Keyed on the selection and the grouping, deliberately not on `groups` identity or the
    // collapsed set, so filtering or folding never re-opens a group behind the reader's back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRowId, corpus, groupKey, pinnedId]);

  /* What the grid should put in front of the reader. A selected finding wins: it is the stronger
     statement of what is being read. With no finding, the first row naming the selected box is
     what the reader came for — a mark 6,000 px below the fold is not an answer. */
  const revealId = useMemo((): string | null => {
    if (activeRowId !== null) return activeRowId;
    for (const n of nodes) if (n.kind === "row" && related.ids.has(n.id)) return n.id;
    return null;
  }, [activeRowId, nodes, related]);

  /* ── landing the widened row: re-aim the grid, then hand the reader to the row ──────────────
   *
   * When "Show … in place" lands, the SAME item moves from the pinned slot to its place in the list.
   * The grid aims its roving cell (the one Tab enters on) only when the reveal target CHANGES, and
   * here it does not: MEASURED (1920x1080) Tab into the grid after the widening landed on F001 —
   * the row now standing where the pinned F120 had been — thousands of px from the revealed F120.
   * So for exactly one commit the reveal target is withdrawn and then restored, which is the grid's
   * own contract for "aim again": its roving cell and its reveal both follow the row to its place.
   *
   * Focus follows the row. The control hands it to the pinned row, which moves into place with it
   * (see `nodes`); a grid that owns focus moves focus with its re-aimed roving cell. Should focus
   * have fallen back to the "Removed …" sentence or to <body> instead, it is moved to the landed row
   * here: MEASURED at 390x844 (review/audit-d3-focus.mjs --self-removing) the filter landing grew the
   * page above the queue by ~2,300 px and left a focused sentence 30 px below the viewport.
   */
  const [reaimGrid, setReaimGrid] = useState(false);
  const landing = useRef<{ pinned: string | null; focusRow: boolean }>({ pinned: null, focusRow: false });
  useLayoutEffect(() => {
    const was = landing.current.pinned;
    landing.current.pinned = pinnedId;
    if (was !== null && pinnedId === null && was === activeRowId && widened !== null && widened.id === activeRowId) {
      landing.current.focusRow = true;
      setReaimGrid(true);
    }
  }, [pinnedId, activeRowId, widened]);
  useLayoutEffect(() => {
    if (reaimGrid) setReaimGrid(false);
  }, [reaimGrid]);
  useEffect(() => {
    if (reaimGrid || !landing.current.focusRow) return;
    landing.current.focusRow = false;
    const root = rootRef.current;
    const row = root?.querySelector<HTMLElement>('[role="grid"] [aria-current]') ?? null;
    if (root === null || row === null) return;
    const active = document.activeElement;
    const sentence = root.querySelector(".pq-widened");
    /* Only from where the control left the reader: never out of a field or a cell they moved to. */
    if (active === null || active === document.body || active === sentence) {
      (row.querySelector<HTMLElement>('[tabindex="0"]') ?? row.querySelector<HTMLElement>('[role="rowheader"]'))?.focus();
    }
    if (!row.contains(document.activeElement) || typeof ResizeObserver === "undefined") return;
    /* Keep the focused row on screen while the rest of the page catches up with the wider filter.
       The other surfaces re-filter in commits of their own, after this one: MEASURED at 390x844 the
       page above the queue grew by ~2,300 px about 0.3 s after the row had been revealed and
       focused, and scroll anchoring left the focused row 136 px below the viewport. So until the
       reader does anything (a key, a pointer, a wheel, a touch) or 5 s pass, a layout change that
       pushes the focused row out of the viewport brings it back by the least movement. */
    const inputs = ["keydown", "pointerdown", "wheel", "touchstart"] as const;
    let done = false;
    const stop = (): void => {
      if (done) return;
      done = true;
      ro.disconnect();
      for (const t of inputs) window.removeEventListener(t, stop, true);
      clearTimeout(timer);
    };
    const ro = new ResizeObserver(() => {
      if (!row.isConnected || !row.contains(document.activeElement)) return stop();
      const r = row.getBoundingClientRect();
      if (r.top < 0 || r.bottom > window.innerHeight) row.scrollIntoView({ block: "nearest" });
    });
    ro.observe(document.body);
    for (const t of inputs) window.addEventListener(t, stop, true);
    const timer = setTimeout(stop, 5000);
    return stop;
  }, [reaimGrid]);

  /* ── the batch ──────────────────────────────────────────────────────────────
     Focus, selection and the batch are three separate states (design-brief §7.2). The batch has
     to DO something or it is decoration, so it copies one tab-separated line per row, each
     carrying its citation — the form an engineer pastes into a ticket. A verdict pasted without
     its citation is the most common way an honest result becomes a dishonest quotation. */
  const [batch, setBatch] = useState<ReadonlySet<string>>(new Set<string>());
  const [copied, setCopied] = useState("");

  // A batch is a set of ids from ONE corpus; carrying it across would select phantom rows.
  useEffect(() => setBatch(new Set<string>()), [corpus]);

  const toggleBatch = useCallback((_item: Finding | CrossLayerFinding, id: string): void => {
    setBatch((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  /* The rows the grid actually renders. Ctrl+A is described as "every shown row", so it selects
     exactly these — a row folded inside a collapsed group is not shown. It previously batched
     `result.items` (146) while 42 rows were on screen, so what was announced and what was
     selected disagreed. */
  const shownIds = useMemo(() => nodes.filter((n) => n.kind === "row").map((n) => n.id), [nodes]);
  /* A batch can still hold rows that are now folded (batched, then collapsed). Say how many, so
     the count is never a number the reader cannot find on screen. */
  const batchFolded = useMemo(() => {
    if (batch.size === 0) return 0;
    const onScreen = new Set(shownIds);
    let n = 0;
    for (const id of batch) if (!onScreen.has(id)) n += 1;
    return n;
  }, [batch, shownIds]);
  const batchLabel =
    batch.size === 0
      ? ""
      : batchFolded > 0
        ? `${batch.size} selected, ${batchFolded} in collapsed groups`
        : `${batch.size} selected`;

  const copyBatch = useCallback((): void => {
    // The pinned "outside your filter" row is a shown row too (Ctrl+A takes it), so it copies too.
    const rows = [...(pinned === null ? [] : [pinned.item]), ...result.items].filter((r) => batch.has(spec.idOf(r)));
    const text = rows.map((r) => spec.lineOf(r)).join("\n");
    const write = navigator.clipboard?.writeText?.bind(navigator.clipboard);
    if (!write) {
      // No clipboard access (insecure context, a locked-down profile). Say so rather than
      // reporting a copy that did not happen.
      setCopied("This browser did not grant clipboard access, so nothing was copied.");
      return;
    }
    void write(text).then(
      () => setCopied(`${rows.length} row(s) copied with their citations.`),
      () => setCopied("The clipboard write was refused, so nothing was copied."),
    );
  }, [result.items, batch, spec, pinned]);

  const shown = result.items.length;
  const total = result.total;
  const announce = `${shown} of ${total} ${spec.noun} match the current scope`;

  const problems = result.clauses.filter(
    (c) => c.applicability === "unrecognised" || c.applicability === "not-applicable",
  );
  const [whyOpen, setWhyOpen] = useState(false);

  const emptyReason = useMemo((): string => {
    if (problems.length > 0) {
      return problems.map((p) => p.note).filter((n): n is string => n !== null).join(" ");
    }
    const worst = [...result.clauses].sort(
      (a, b) => b.excluded + b.undetermined - (a.excluded + a.undetermined),
    )[0];
    const parts: string[] = [];
    if (worst) {
      parts.push(
        `${clauseLabel(worst.clause)} decided against ${worst.excluded} of ${total} ${spec.noun} and could not decide ${worst.undetermined}; without it ${worst.withoutThisClause} would be shown.`,
      );
      if (worst.note) parts.push(worst.note);
    }
    if (result.textOutcome && result.textOutcome.terms.length > 0) {
      parts.push(`Free text ${result.textOutcome.terms.map((t) => `"${t}"`).join(", ")} matched ${result.textOutcome.matched} of ${total}.`);
    }
    if (result.evidenceScope.note) parts.push(result.evidenceScope.note);
    return parts.length > 0
      ? parts.join(" ")
      : `The query ran over all ${total} ${spec.noun} in this snapshot and returned zero rows.`;
  }, [problems, result, spec.noun, total]);

  /* ── render ── */

  const groupOptions = spec.groupKeys.map((g) => ({ value: g.value, label: g.label }));
  const orderOptions = [
    { value: "ranked", label: spec.rankedLabel },
    ...spec.columns
      .map((c) => ({ column: c, field: spec.sortFieldOf(c.id) }))
      .filter((x): x is { column: GridColumn<Finding | CrossLayerFinding>; field: string } => x.field !== null)
      .map((x) => ({ value: `${x.field}:asc`, label: `${x.column.headerLabel ?? x.column.header}, ascending` })),
    ...spec.columns
      .map((c) => ({ column: c, field: spec.sortFieldOf(c.id) }))
      .filter((x): x is { column: GridColumn<Finding | CrossLayerFinding>; field: string } => x.field !== null)
      .map((x) => ({ value: `${x.field}:desc`, label: `${x.column.headerLabel ?? x.column.header}, descending` })),
  ];
  const groupValueNow = spec.groupKeys.some((g) => g.value === groupKey) ? groupKey : "severity";
  const orderValueNow = ordering.kind === "ranked" ? "ranked" : `${ordering.spec.field}:${ordering.spec.direction}`;
  /* What the folded "View" disclosure says it holds, read from the same options the selects show. */
  const groupLabelNow = groupOptions.find((g) => g.value === groupValueNow)?.label ?? groupValueNow;
  const orderLabelNow = orderOptions.find((o) => o.value === orderValueNow)?.label ?? spec.rankedLabel;

  return (
    <section className={["pq", className].filter(Boolean).join(" ")} aria-label="Priority queue" ref={rootRef}>
      {/* ── corpus ── */}
      <div className="pq-corpus">
        {/* APG radio group: ONE tab stop, arrows move and select. Two buttons is not many, but a
            keyboard contract that holds only where the list is long is not a contract. */}
        <div className="pq-corpus__group" role="radiogroup" aria-label="Which evidence table to read">
          {CORPORA.map((c, i) => (
            <button
              key={c.id}
              type="button"
              role="radio"
              aria-checked={corpus === c.id}
              tabIndex={corpus === c.id ? 0 : -1}
              className="pq-corpus__btn"
              onClick={() => setCorpus(c.id)}
              onKeyDown={(e) => {
                const delta = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
                if (delta === 0) return;
                e.preventDefault();
                const next = CORPORA[(i + delta + CORPORA.length) % CORPORA.length];
                if (!next) return;
                setCorpus(next.id);
                (e.currentTarget.parentElement?.children[CORPORA.indexOf(next)] as HTMLElement | undefined)?.focus();
              }}
            >
              <span>{c.label}</span>
              <span className="pq-corpus__count">{c.id === "findings" ? fabric.findings.length : fabric.crossLayer.length}</span>
            </button>
          ))}
        </div>
        {/* The sentence is not deleted, it is disclosed. Three lines of documentation above the
            first result is a fifth of the panel spent before any evidence appears; the clause below
            carries the fact and the disclosure carries the reasoning. */}
        <p className="pq-corpus__note">
          <span>Counted separately, never concatenated.</span>
          <Popover
            label="Why the two tables are counted separately"
            trigger={
              <IconButton size="sm" label="Why the two tables are counted separately" icon={<IconInfo />} />
            }
          >
            <p className="pq-note__full">
              Two views of the same snapshot. Every cross-layer record also appears in the punchlist,
              but only the cross-layer table names the layers it spans, so the two are not
              concatenated.
            </p>
          </Popover>
        </p>
      </div>

      {/* ── query bar ── */}
      <div className="pq-queryrow">
        <div className="pq-query">
          <IconSearch className="pq-query__glyph" />
          <div className="pq-query__box">
            <div className="pq-query__ink" aria-hidden="true" ref={queryInkRef}>
              <QueryTokens input={draft} parsed={parsedDraft} />
              {ghost ? <span className="pq-tok pq-ghost">{ghost}</span> : null}
            </div>
            <input
              ref={queryInputRef}
              id={`${accountingId}-q`}
              className="pq-query__input"
              type="text"
              role="combobox"
              aria-expanded={menuOpen && suggestions.length > 0}
              // aria-controls only while the listbox exists: a reference to an absent id is a broken
              // relationship, not an empty one.
              {...(menuOpen && suggestions.length > 0 ? { "aria-controls": `${accountingId}-listbox` } : {})}
              aria-autocomplete="list"
              aria-label={`Filter ${spec.noun}`}
              aria-describedby={`${accountingId}-help`}
              {...(menuOpen && suggestions[activeSuggestion]
                ? { "aria-activedescendant": `${accountingId}-opt-${activeSuggestion}` }
                : {})}
              autoComplete="off"
              spellCheck={false}
              /* Short enough to FIT the field at the 300px rail width. The old placeholder was a
                 three-clause example that was cut flush at the field edge with no ellipsis, so the
                 first thing the field taught the reader was that it truncates silently. The full
                 grammar is in the suggestion popup and the help sheet, which is where an example
                 that does not fit belongs. */
              placeholder="severity:Critical"
              /* A value longer than the field is readable on hover as well as by scrolling: the ink
                 layer cannot ellipsise without moving the caret off the real characters. */
              title={draft === "" ? undefined : draft}
              value={draft}
              onChange={(e) => {
                setDraft(e.currentTarget.value);
                setCaret(e.currentTarget.selectionStart ?? e.currentTarget.value.length);
                setMenuOpen(true);
                setActiveSuggestion(0);
                syncInkScroll();
              }}
              onScroll={syncInkScroll}
              onClick={(e) => {
                setCaret(e.currentTarget.selectionStart ?? 0);
                syncInkScroll();
              }}
              onKeyUp={(e) => {
                setCaret(e.currentTarget.selectionStart ?? 0);
                syncInkScroll();
              }}
              onFocus={() => setMenuOpen(true)}
              onBlur={() => setMenuOpen(false)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setMenuOpen(true);
                  setActiveSuggestion((i) => Math.min(i + 1, Math.max(0, suggestions.length - 1)));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActiveSuggestion((i) => Math.max(0, i - 1));
                } else if (e.key === "Enter" && menuOpen && suggestions.length > 0 && ghost !== "") {
                  e.preventDefault();
                  accept(activeSuggestion);
                } else if (
                  e.key === "ArrowRight" &&
                  !e.shiftKey &&
                  !e.ctrlKey &&
                  !e.metaKey &&
                  !e.altKey &&
                  caret === draft.length &&
                  menuOpen &&
                  suggestions.length > 0 &&
                  ghost !== ""
                ) {
                  // Accepting the inline ghost with ArrowRight at end-of-line is the completion
                  // gesture Tab used to carry. It is safe because ArrowRight at the end of the value
                  // has no other effect: it is not a navigation key that leaves the field.
                  e.preventDefault();
                  accept(activeSuggestion);
                } else if (e.key === "Tab") {
                  // Tab MOVES FOCUS. It never accepts a completion and never mutates the query — a
                  // navigation key that silently rewrites the investigation scope is the defect this
                  // replaced. Closing the popup synchronously (rather than waiting for the blur
                  // handler's own render) also means the listbox is gone from the DOM before the
                  // next control in the tab order takes focus, so it cannot overlap that control's
                  // focus ring (SC 2.4.11/2.4.12).
                  if (menuOpen) flushSync(() => setMenuOpen(false));
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  e.stopPropagation();
                  if (menuOpen) setMenuOpen(false);
                  else if (draft !== "") setDraft("");
                }
              }}
            />
          </div>
          {draft !== "" ? (
            <IconButton
              size="sm"
              label="Clear the filter text"
              icon={<IconClose />}
              onClick={() => {
                setDraft("");
                queryInputRef.current?.focus();
              }}
            />
          ) : null}
          {menuOpen && suggestions.length > 0 ? (
            <ul className="pq-suggest" id={`${accountingId}-listbox`} role="listbox" aria-label="Filter completions">
              {suggestions.map((s, i) => (
                <li
                  key={`${s.kind}:${s.value}`}
                  id={`${accountingId}-opt-${i}`}
                  role="option"
                  aria-selected={i === activeSuggestion}
                  className="pq-suggest__opt"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    accept(i);
                  }}
                >
                  <span className="pq-suggest__value">{s.label}</span>
                  {s.detail ? <span className="pq-suggest__detail">{s.detail}</span> : null}
                  {s.count !== null ? <span className="pq-suggest__count">{s.count}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
          {menuOpen && suggestions.length === 0 && suggestion.note ? (
            <p className="pq-query__note">{suggestion.note}</p>
          ) : null}
        </div>
        {viewFolded ? (
          <Button
            ref={viewButtonRef}
            size="sm"
            className="pq-viewbtn"
            data-focus-successor={`[id="${viewId}"]`}
            aria-expanded={viewOpen}
            aria-controls={viewId}
            aria-describedby={`${viewId}-now`}
            icon={viewOpen ? <IconChevronUp /> : <IconChevronDown />}
            onClick={() => setViewOpen((v) => !v)}
          >
            View
          </Button>
        ) : null}
      </div>

      <p className="visually-hidden" id={`${accountingId}-help`}>
        Structured filter. A key and a colon filters, for example severity:Critical. A leading minus
        excludes. Anything else is free text. Down arrow lists completions.
      </p>

      {/* ── scope chips carried by the shared investigation state ── */}
      {scopeClauses.length > 0 ? (
        <div className="pq-chips" aria-label="Scope carried from the investigation">
          {SEVERITY_ORDER.filter((s) => severities.has(s)).map((s) => (
            <Chip key={s} removeSuccessor={queryField} removeLabel={`Remove the ${s} severity filter`} onRemove={() => toggleSeverity(s)}>
              {`severity ${s}`}
            </Chip>
          ))}
          {[...roles].sort(cmpStr).map((r) => (
            <Chip key={r} removeSuccessor={queryField} removeLabel={`Remove the ${r} role filter`} onRemove={() => toggleRole(r)}>
              {`role ${r}`}
            </Chip>
          ))}
          {onlyUncollected ? (
            <Chip removeSuccessor={queryField} removeLabel="Remove the uncollected-devices filter" onRemove={() => setOnlyUncollected(false)}>
              devices never collected
            </Chip>
          ) : null}
        </div>
      ) : null}

      {/* ── display options, inline — or folded under "View" when they would crowd out the rows ── */}
      {viewFolded ? (
        <p className="visually-hidden" id={`${viewId}-now`}>
          {`Group, order and display options. Grouped by ${groupLabelNow}; order: ${orderLabelNow}.`}
        </p>
      ) : null}
      <div
        className="pq-controls"
        id={viewId}
        ref={controlsRef}
        role="group"
        aria-label="Group, order and display"
        hidden={viewFolded && !viewOpen}
      >
        <Select
          label="Group"
          className="pq-select"
          options={groupOptions}
          value={groupValueNow}
          onChange={(e) => setGroupKey(e.currentTarget.value)}
        />
        <Select
          label="Order"
          className="pq-select"
          options={orderOptions}
          value={orderValueNow}
          onChange={(e) => {
            const v = e.currentTarget.value;
            if (v === "ranked") {
              setOrdering(RANKED);
              return;
            }
            const [field, dir] = v.split(":");
            if (field) setOrdering({ kind: "field", spec: { field, direction: dir === "desc" ? "desc" : "asc" } });
          }}
        />
        <Popover
          label="More display options"
          trigger={<Button size="sm">Display</Button>}
          align="end"
        >
          <div className="pq-display">
            <Toggle
              label="Show empty groups"
              checked={showEmptyGroups}
              onChange={setShowEmptyGroups}
              describedBy={`${accountingId}-empties`}
            />
            <p className="pq-display__hint" id={`${accountingId}-empties`}>
              An empty group states that this snapshot holds zero rows at that value. Hiding it
              turns that statement into silence.
            </p>
            <Toggle
              label="Two-line rows"
              checked={density === "comfortable"}
              onChange={(v) => setDensity(v ? "comfortable" : "compact")}
              describedBy={`${accountingId}-density`}
            />
            <p className="pq-display__hint" id={`${accountingId}-density`}>
              On, the category sits at the end of the title line and any further column you turn on
              below wraps onto a second line. Off, every row is one line and the metadata columns
              are hidden unless you turn them back on below.
            </p>
            <fieldset className="pq-display__cols">
              <legend>Columns</legend>
              {spec.columns
                .filter((c) => c.id !== "drill")
                .map((c) => {
                  const dom = domainValues(c.id === "devices" || c.id === "hosts" ? "host" : c.id);
                  const observedCount =
                    c.id === "wave" ? spec.rows.filter((r) => "wave" in r && r.wave !== null).length : null;
                  return (
                    <label key={c.id} className="pq-display__col">
                      <input
                        type="checkbox"
                        checked={!hidden.has(c.id)}
                        onChange={() => {
                          const next = new Set(hidden);
                          if (next.has(c.id)) next.delete(c.id);
                          else next.add(c.id);
                          setHidden(next);
                        }}
                      />
                      <span>{c.headerLabel ?? c.header}</span>
                      {observedCount === 0 ? (
                        <NotObserved what={c.headerLabel ?? c.header} why="no row in this snapshot carries it" compact />
                      ) : dom.length > 0 ? (
                        <span className="pq-display__domain">{`${dom.length} values`}</span>
                      ) : null}
                    </label>
                  );
                })}
            </fieldset>
            {/* The drag handle on a header rule has a pointer-free twin on the header cell
                (Shift+Arrow), but that twin is invisible and needs a keyboard. MEASURED (A11Y
                critic, D1 / WCAG 2.5.7): the separator could only be dragged. These buttons are
                the single-pointer, discoverable alternative, bound by the same column bounds. */}
            {spec.columns.some((c) => c.resizable && !hidden.has(c.id)) ? (
              <fieldset className="pq-display__cols">
                <legend>Column widths</legend>
                {spec.columns
                  .filter((c) => c.resizable && !hidden.has(c.id))
                  .map((c) => {
                    const name = c.headerLabel ?? c.header;
                    const px = own(columnWidths, c.id);
                    const stepBy = (delta: number): void => {
                      const measured = rootRef.current
                        ?.querySelector<HTMLElement>(`[role="columnheader"][data-col="${c.id}"]`)
                        ?.getBoundingClientRect().width;
                      const base = px ?? Math.round(measured ?? c.minPx ?? 32);
                      const next = Math.round(Math.min(Math.max(base + delta, c.minPx ?? 32), c.maxPx ?? 640));
                      setColumnWidths((prev) => ({ ...prev, [c.id]: next }));
                    };
                    return (
                      <div key={c.id} className="pq-display__col pq-display__width" role="group" aria-label={`${name} column width`}>
                        <span>{name}</span>
                        <span className="pq-display__domain" aria-live="polite">
                          {px === undefined ? "auto" : `${px} px`}
                        </span>
                        <Button size="sm" aria-label={`Narrow the ${name} column`} onClick={() => stepBy(-COLUMN_WIDTH_STEP_PX)}>
                          Narrower
                        </Button>
                        <Button size="sm" aria-label={`Widen the ${name} column`} onClick={() => stepBy(COLUMN_WIDTH_STEP_PX)}>
                          Wider
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={`Reset the ${name} column to its automatic width`}
                          disabled={px === undefined}
                          onClick={() =>
                            setColumnWidths((prev) => {
                              const next = { ...prev };
                              delete next[c.id];
                              return next;
                            })
                          }
                        >
                          Auto
                        </Button>
                      </div>
                    );
                  })}
              </fieldset>
            ) : null}
          </div>
        </Popover>
      </div>

      {/* ── accounting ── */}
      <div className="pq-account" id={accountingId}>
        <p className="pq-account__line">
          <strong className="pq-account__shown">{shown}</strong>
          {/* The noun is carried by the corpus switch directly above; it stays in the accessible
              text so the description read with the grid still says what was counted. Dropping it
              visually is what lets the shown count and the coverage clause share ONE line. */}
          <span>
            {` of ${total} `}
            <span className="visually-hidden">{`${spec.noun} `}</span>
            {"shown"}
          </span>
          {result.excludedTotal > 0 ? <span className="pq-account__ex">{`${result.excludedTotal} excluded`}</span> : null}
          {result.undeterminedTotal > 0 ? (
            <span className="pq-account__un">{`${result.undeterminedTotal} undetermined`}</span>
          ) : null}
          {result.clauses.length > 0 || result.textOutcome ? (
            <Button
              size="sm"
              variant="ghost"
              aria-expanded={whyOpen}
              onClick={() => setWhyOpen((v) => !v)}
            >
              {whyOpen ? "Hide the per-clause counts" : "Why?"}
            </Button>
          ) : null}
        </p>

        {/* The marking has to be stated as well as drawn: a trailing-edge bar is not readable from
            a screen reader, and a count of zero here is an ABSENCE of published findings within
            the current scope, never a statement that the box is healthy (B1). */}
        {relatedNow.hosts.length > 0 ? (
          <p className="pq-account__note" data-marks-pending={marksPending || undefined}>
            {relatedNow.ids.size === 0
              ? `No shown ${spec.noun} name ${relatedNow.hosts.join(" or ")}. That is the absence of a published record within the current scope, not an assessment that ${relatedNow.hosts.length > 1 ? "those hosts are" : "that host is"} healthy.`
              : marksPending
                ? `${relatedNow.ids.size} of ${shown} shown ${spec.noun} name ${relatedNow.hosts.join(" or ")} — marking the rows.`
              : relatedFolded === 0
                ? `${relatedNow.ids.size} of ${shown} shown ${spec.noun} name ${relatedNow.hosts.join(" or ")} — marked on the row's trailing edge.`
                : `${relatedNow.ids.size} of ${shown} shown ${spec.noun} name ${relatedNow.hosts.join(" or ")} — ${relatedNow.ids.size - relatedFolded} marked on the row's trailing edge, ${relatedNow.folded
                    .map((f) => `${f.count} in the collapsed ${f.label} group`)
                    .join(", ")}.`}
          </p>
        ) : null}

        {/* A selection the filter hides (A4). Its own named group, so the control that removes
            itself hands focus to its stated successor rather than to whatever tab stop happens to
            follow it in the queue. */}
        {showPinned && pinned !== null ? (
          <div className="pq-pinned" role="group" aria-label={`${pinned.label} is outside your filter`}>
            <p className="pq-pinned__text">
              {`${pinned.label} is selected, but your filter hides it: ${
                pinned.parts.length === 0 ? "the filter as a whole keeps it out" : pinned.parts.map(describePart).join("; ")
              }. It is pinned above the rows your filter shows, outside the filter; your filter is unchanged.`}
            </p>
            <Button
              size="sm"
              aria-label={`Show ${pinned.label} in place by removing ${
                pinned.parts.length === 0 ? "the whole filter" : pinned.parts.map((p) => p.text).join(", ")
              } from the filter`}
              /* The control removes itself, so focus is handed on — to the selected row itself, the
                 thing the reader asked to see. At the press that row is still the pinned copy (the
                 typed text reaches the rows through a deferred value); it carries its in-place
                 identity (see `nodes`), so React moves the focused element into place rather than
                 destroying it, and the landing effect below re-aims the grid onto it. MEASURED before
                 this, handing focus to the "Removed …" sentence instead: at 768 px the landing then
                 moved focus a second time, and at 390 px the page growing above the queue left the
                 focused sentence off screen (review/audit-d3-focus.mjs --self-removing). The sentence,
                 then the filter field, remain as fallbacks. */
              onClick={(e) =>
                handOffFocus(e.currentTarget, widenFilter, [
                  /* The row's own tab stop when the grid's roving cell is on it: focus arriving anywhere
                     else in a grid that was aimed from outside is redirected to that cell, which
                     would make the hand-off read as failed and fall through to the sentence. */
                  () =>
                    rootRef.current?.querySelector<HTMLElement>('[role="grid"] [aria-current] [tabindex="0"]') ??
                    rootRef.current?.querySelector<HTMLElement>('[role="grid"] [aria-current] [role="rowheader"]'),
                  () => rootRef.current?.querySelector<HTMLElement>(".pq-widened"),
                  queryField,
                ])
              }
            >
              {`Show ${pinned.short} in place`}
            </Button>
          </div>
        ) : widenedSentence !== "" ? (
          /* tabIndex -1: the widening control hands focus here when it removes itself. */
          <p className="pq-account__note pq-widened" tabIndex={-1}>
            {widenedSentence}
          </p>
        ) : null}

        {problems.length > 0 ? (
          <div className="pq-account__problem" role="alert">
            {problems.map((p) => (
              <p key={clauseLabel(p.clause)}>{p.note ?? `${clauseLabel(p.clause)} could not be evaluated.`}</p>
            ))}
          </div>
        ) : null}

        {result.textOutcome && result.textOutcome.fuzzyTerms.length > 0 ? (
          <p className="pq-account__note">
            {`Widened to an approximate match: ${result.textOutcome.fuzzyTerms.join(", ")} matched nothing literally.`}
          </p>
        ) : null}

        {result.unobservedKeys.length > 0 ? (
          <p className="pq-account__note">
            {`${result.unobservedKeys.join(", ")} was not observed on any record in this snapshot, so it filters nothing.`}
          </p>
        ) : null}

        {whyOpen ? (
          <ul className="pq-clauses">
            {result.clauses.map((c) => (
              <ClauseRow key={`${clauseLabel(c.clause)}@${c.clause.range.start}`} outcome={c} noun={spec.noun} />
            ))}
            {result.textOutcome ? (
              <li className="pq-clause">
                <span className="pq-clause__name">free text</span>
                <span className="pq-clause__nums">
                  <span>{`${result.textOutcome.matched} matched`}</span>
                  <span>{`${result.textOutcome.excluded} excluded`}</span>
                  {result.textOutcome.undetermined > 0 ? <span>{`${result.textOutcome.undetermined} undecided`}</span> : null}
                </span>
              </li>
            ) : null}
          </ul>
        ) : null}

        {/* Same rule as the corpus note: the coverage fact stays on screen permanently as one
            clause, and the paragraph that explains why it matters is one click away. Nothing is
            softened — the clause still names the gap in the denominator. */}
        {result.evidenceScope.note ? (
          <p className="pq-account__scope">
            <span>
              {result.evidenceScope.uncollected.length > 0
                ? `${result.evidenceScope.uncollected.length} of ${result.evidenceScope.totalDevices} devices never collected`
                : "Coverage note"}
            </span>
            <Popover
              label="What the collection gap means for this result"
              trigger={
                <IconButton
                  size="sm"
                  label="What the collection gap means for this result"
                  icon={<IconInfo />}
                />
              }
            >
              <p className="pq-note__full">{result.evidenceScope.note}</p>
            </Popover>
          </p>
        ) : null}
      </div>

      {/* An empty RESULT is not the same thing as an empty grid: with empty groups on, the grid
          still has rows — the zero buckets, which are themselves the denominator. So the
          explanation lives here, beside the counts, and renders whenever the result is empty
          rather than only when the grid has nothing in it at all. */}
      {shown === 0 ? (
        <Empty
          className="pq-empty"
          title={`No ${spec.noun} match this scope`}
          reason={emptyReason}
          {...(draft !== ""
            ? {
                action: (
                  <Button size="sm" onClick={(e) => handOffFocus(e.currentTarget, () => setDraft(""), [queryField])}>
                    Clear the filter text
                  </Button>
                ),
              }
            : {})}
        />
      ) : null}

      {/* The grid announces itself as multi-selectable, so it has to say with which keys. Every
          key named here is implemented in DataGrid's keydown switch. */}
      <p className="visually-hidden" id={`${accountingId}-selkeys`}>
        Multi-select: shift plus space, or x, adds one row to the batch. Shift plus up or down
        arrow, and shift plus page up or page down, extend the selection from the anchor row.
        Control plus A selects every shown row; rows inside collapsed groups are not selected.
        Escape clears the batch, then the selection; it does not leave the grid.
      </p>

      {/* ── the batch ── */}
      {batch.size > 0 ? (
        <div className="pq-batch">
          <span className="pq-batch__count">{batchLabel}</span>
          <Button size="sm" onClick={copyBatch}>
            Copy with citations
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setBatch(new Set<string>())}>
            Clear
          </Button>
        </div>
      ) : null}

      {/* ── the grid ── */}
      <DataGrid<Finding | CrossLayerFinding>
        label={corpus === "findings" ? "Findings, ranked" : "Cross-layer records, ranked"}
        columns={columns}
        nodes={nodes}
        template={template}
        layout={density === "comfortable" ? "stacked" : "line"}
        density={density}
        activeId={activeRowId}
        /* The rows on screen answer `query`; the reader has typed `draft`. For the length of the
           debounce those are different questions, and the grid is showing the older one — which is
           exactly what `aria-busy` is for. Measured by review/audit-e5-sweep.mjs at 233-396 ms per
           recompute, which was silent to assistive technology because nothing ever passed this
           prop. It is deliberately NOT held true across the recompute commit itself: that commit is
           synchronous, so there is no moment in it for a reader to observe. */
        busy={draft !== query || filterText !== draft}
        revealId={reaimGrid ? null : revealId}
        /* What re-runs the reveal. With a finding selected, ONLY the finding: a device, link or hop
           picked on another surface does not change what this queue is showing, and A4 says the
           reader's scroll position survives a device change. MEASURED before this (1920x1080,
           f=F106): the reader scrolled the queue to 1404/1904/2604/4704 px, then one device pick
           from the canvas, the Fabric list, the palette, a chain chip or a hop threw every one of
           them back to 3404 — the row they had deliberately scrolled away from. The hold (below, in
           DataGrid) still keeps a row the reader has NOT scrolled away in view when a trace reflows
           the rail. With no finding selected, `revealId` IS derived from the device/link, so the
           whole selection keys the reveal and the first row naming it is brought into view. */
        revealKey={
          activeRowId !== null
            ? `f|${activeRowId}|${hasPinned ? "outside-filter" : "in-filter"}`
            : `d|${deviceId ?? ""}|${linkId ?? ""}|${hopIndex ?? ""}`
        }
        /* With no finding selected, the first naming row is only a REPRESENTATIVE: every marked row
           answers "what names this box". So a pick whose answer is already on screen does not move
           the list. MEASURED before this (1920x1080, ?s=queue, no finding): the reader at scrollTop
           3200 with F060 and F069 (both naming access13) in view picked access13 on the canvas, the
           Fabric list or the palette and was thrown to 0 once the marks committed; core2 went 3200
           -> 2681, dist1 the same. With a finding selected the reveal is of the selection itself and
           this does not apply (the with-finding half of A4 is unchanged). */
        {...(activeRowId === null ? { revealUnlessVisible: related.ids } : {})}
        /* The reader's ACT, read URGENTLY: the grid records what was on screen before this act's
           first commit — the one that mounts or re-words the "N of 146 shown findings name <host>"
           sentence above it — so the deferred reveal's "already visible?" decision is taken
           against what the reader could see when they acted, not against the layout that sentence
           has since moved. MEASURED before this (A4, 1920x1080, no finding): F099, the only visible
           row naming access13, sat at 999-1041 in a port of 352-1054; the sentence moved the port's
           top to 389.7, the reveal judged F099 hidden and threw the queue 4777 -> 0 (access5/F094:
           4511 -> 0). Every entry path — canvas, Fabric list, palette, chain chip, hop, Back — writes
           the same store fields, so one key covers them all. */
        actKey={`${urgentFindingId ?? ""}|${urgentDeviceId ?? ""}|${urgentLinkId ?? ""}|${urgentHopIndex ?? ""}`}
        relatedIds={related.ids}
        /* Worded from the SAME deferred selection as the marks, so a row's description can never
           name a different host from the mark drawn on it. */
        {...(related.hosts.length > 0
          ? {
              relatedDescription:
                linkId !== null
                  ? `names an end of the selected link, ${related.hosts.join(" or ")}`
                  : `names the selected device ${related.hosts.join(" or ")}`,
            }
          : {})}
        /* aria-sort can only state a single-column order; the default ranking is composite, so
           the order the reader is looking at is also stated in words (A11Y critic, D2). The words
           are the Order control's own option label, so the two cannot disagree. */
        orderDescription={`Order: ${
          orderOptions.find(
            (o) =>
              o.value ===
              (ordering.kind === "ranked" ? "ranked" : `${ordering.spec.field}:${ordering.spec.direction}`),
          )?.label ?? spec.rankedLabel
        }. ${(() => {
          const g = groupOptions.find((o) => o.value === groupKey) ?? groupOptions.find((o) => o.value === "severity");
          return !g || g.value === "none" ? "Not grouped." : `Grouped by ${g.label}, ordered within each group.`;
        })()}`}
        sort={gridSort}
        onSort={onSort}
        onActivate={(item, id) => {
          const target = corpus === "findings" ? id : crossLayerBridge.get(id);
          if (target !== undefined) {
            selectRow(target);
            return;
          }
          /* No unique punchlist row carries this record, so there is nothing the shared selection
             could point at. Say so rather than selecting something adjacent and plausible. */
          openEvidence(spec.citeOf(item), id);
        }}
        onToggleGroup={toggleGroup}
        batchIds={batch}
        onToggleBatch={toggleBatch}
        onSelectRange={(_items, ids) => setBatch(new Set(ids))}
        onSelectAll={() => setBatch(new Set(shownIds))}
        onEscape={() => {
          /* Widest state first: a user pressing Escape is undoing the last thing they added, and
             leaving the grid is the last resort rather than the first. */
          if (batch.size > 0) {
            setBatch(new Set<string>());
            return true;
          }
          if (shownFindingId !== null) clearSelection();
          /* Escape never MOVES focus out of the grid. It used to fall through to DataGrid's exit
             and land on the "Filter findings" input when there was nothing to clear, so an Escape
             pressed on a column header teleported the keyboard to a different region (A11Y critic
             2026-09-21, D3). Escape undoes state; Tab and Shift+Tab leave. */
          return true;
        }}
        columnWidths={columnWidths}
        onResizeColumn={(id, px) =>
          setColumnWidths((prev) => {
            const next = { ...prev };
            if (px <= 0) delete next[id];
            else next[id] = px;
            return next;
          })
        }
        describedBy={`${accountingId} ${accountingId}-selkeys`}
        /* Windowing needs a UNIFORM row height to place a row at all, and only the compact
           density guarantees one — a two-line row is auto-height between 32 and 56px, and
           windowing it against an assumed height would put rows at the wrong scroll offsets.
           At 146 and 43 rows neither corpus reaches the threshold anyway (measured in
           PriorityQueue.test.tsx: 887 cells, 3,546 elements), so this is the mechanism being
           available rather than the mechanism being needed. */
        {...(density === "compact" ? { window: { rowHeightPx: 32, threshold: 200 } } : {})}
      />

      <LiveRegion message={announce} />
      <LiveRegion message={copied} />
      {/* The batch count was visible only; a keyboard batch (x, shift+arrows, Ctrl+A) gave a
          screen-reader user no statement of how many rows it now holds. */}
      <LiveRegion message={batchLabel} />
      {/* The widening changed the reader's filter; that is said aloud as well as shown. */}
      <LiveRegion message={widenedSentence} />
    </section>
  );
}
