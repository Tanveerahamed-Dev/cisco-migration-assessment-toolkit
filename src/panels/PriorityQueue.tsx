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
  useEffect,
  useId,
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
import { useInvestigation } from "../core/store";
import type { Cite, CrossLayerFinding, Finding } from "../core/types";
import { SEVERITY_ORDER } from "../core/types";
import { IconCite, IconClose, IconInfo, IconSearch } from "../ui/icons";
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
import "./PriorityQueue.css";

/* One shared empty set, so "nothing is related" is reference-stable and cannot re-render the grid
   on every keystroke. */
const EMPTY_IDS: ReadonlySet<string> = new Set<string>();

/* ── preferences: furniture, so localStorage and never the URL (design-brief §5.4) ─────────── */

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
      align: "end",
      render: (f) => (
        <IconButton
          size="sm"
          label={`Open the source record for ${f.id} at ${f.cite}`}
          icon={<IconCite />}
          tabIndex={-1}
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
      align: "end",
      render: (c) => (
        <IconButton
          size="sm"
          label={`Open the source record for ${c.id} at ${c.cite}`}
          icon={<IconCite />}
          tabIndex={-1}
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
  const findingId = useInvestigation((s) => s.findingId);
  const deviceId = useInvestigation((s) => s.deviceId);
  const linkId = useInvestigation((s) => s.linkId);
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

  const queryInputRef = useRef<HTMLInputElement | null>(null);
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

  /* ── the drill and selection handlers ── */

  const openEvidence = useCallback(
    (cite: Cite, id: string): void => {
      if (onOpenEvidence) {
        onOpenEvidence(cite, id);
        return;
      }
      if (findingById.has(id)) selectFinding(id);
      setEvidenceTab("raw");
    },
    [onOpenEvidence, selectFinding, setEvidenceTab],
  );

  const selectRow = useCallback(
    (id: string): void => {
      if (onSelectFinding) {
        onSelectFinding(id);
        return;
      }
      /* Re-aiming, not resetting: the device, the flow and the camera are untouched, and Rail B
         swaps to the tab that can actually show this record (design-brief §5.1, interaction 1). */
      selectFinding(id);
      setEvidenceTab("findings");
    },
    [onSelectFinding, selectFinding, setEvidenceTab],
  );

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
      sortFieldOf: (columnId) => FINDING_SORT_OF[columnId] ?? null,
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
      sortFieldOf: (columnId) => CROSS_SORT_OF[columnId] ?? null,
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

  const scopeClauses = useMemo(() => {
    const out: string[] = [];
    if (severities.size > 0) {
      out.push(`severity:${SEVERITY_ORDER.filter((s) => severities.has(s)).map(quoteValue).join(",")}`);
    }
    if (roles.size > 0) out.push(`role:${[...roles].sort(cmpStr).map(quoteValue).join(",")}`);
    if (onlyUncollected) out.push("is:uncollected");
    return out;
  }, [severities, roles, onlyUncollected]);

  const effective = useMemo(
    () => [...scopeClauses, draft.trim()].filter((s) => s.length > 0).join(" "),
    [scopeClauses, draft],
  );

  const parsedDraft = useMemo(() => parseQuery(draft), [draft]);
  const result = useMemo(() => spec.filter(spec.rows, parseQuery(effective)), [spec, effective]);

  /* ── grouping, ordering, node list ── */

  const collapseKey = (g: string): string => `${corpus}:${groupKey}:${g}`;

  const groups = useMemo(() => {
    const key = spec.groupKeys.some((g) => g.value === groupKey) ? groupKey : "severity";
    const built = spec.group(result.items, key);
    if (!showEmptyGroups || key === "none") return built;
    const vocabulary = spec.groupKeys.find((g) => g.value === key)?.vocabulary() ?? [];
    const seen = new Set(built.map((g) => g.key));
    const missing = vocabulary
      .filter((v) => !seen.has(v))
      .map<Group<Finding | CrossLayerFinding>>((v) => ({ key: v, label: v, observed: true, items: [] }));
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
  }, [spec, groupKey, result.items, showEmptyGroups]);

  const nodes = useMemo<GridNode<Finding | CrossLayerFinding>[]>(() => {
    const out: GridNode<Finding | CrossLayerFinding>[] = [];
    const single = groups.length === 1 && groups[0]?.key === "all";
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
      for (const item of items) out.push({ kind: "row", id: spec.idOf(item), item });
    }
    return out;
    // `collapseKey` closes over corpus + groupKey, both already listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, spec, ordering, collapsedRaw, groupKey, corpus]);

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
    const n = metas.length;
    const cols: string[] = [...lead.map(track), "minmax(0, 1fr)", ...metas.slice(1).map(track)];
    if (drill) cols.push(track(drill));
    const lastCol = cols.length;
    /*
     * THE HEADER IS ONE ROW, ALWAYS.
     *
     * A two-line data row previously produced a two-line header, and the second header line then
     * sat immediately above the FIRST row's first line rather than above the cells it named — a
     * column header that labels the wrong line is worse than none. A single header row can only
     * honestly label the line-1 tracks, so that is what it labels; the line-2 metadata is demoted
     * to self-describing inline chips in the row, and every one of those columns stays sortable
     * through the Order control. `headerPlace` parks the demoted header cells on row 1, and
     * `headerHidden` is the fact that they are CLIPPED there — one flag, set at the one place that
     * demotes them, which both the stylesheet (`[data-headhidden]`) and DataGrid read.
     *
     * It used to be two independent statements of the same fact: this map, and a CSS selector
     * listing the four columns that are NOT demoted by name. They disagreed. The clipped cells
     * kept rendering a sort button, which measured 1x24 px at y=-11 — invisible, unclickable, and
     * still announced through `aria-sort` and still operable with Enter. A demoted column is now
     * demoted on every surface at once.
     */
    const headRow1 = (from: number, to: number): string => `1 / ${from} / 2 / ${to}`;
    const placed = visibleColumns.map((c) => {
      if (c.id === "sev") return { ...c, place: "1 / 1 / 2 / 2" };
      if (c.id === "id") return { ...c, place: "1 / 2 / 2 / 3" };
      if (c === title) return { ...c, place: `1 / 3 / 2 / span ${Math.max(1, n)}` };
      if (c === drill)
        return {
          ...c,
          place: `1 / ${lastCol} / ${n > 0 ? 3 : 2} / ${lastCol + 1}`,
          headerPlace: headRow1(lastCol, lastCol + 1),
        };
      const i = metas.indexOf(c);
      return { ...c, place: `2 / ${3 + i} / 3 / ${4 + i}`, headerPlace: headRow1(3, 4), headerHidden: true };
    });
    return { columns: placed, template: cols.join(" ") };
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

  /* The shared store addresses a selection by punchlist id only, so in the cross-layer view the
     highlighted row is whichever record bridges to the selected finding — not a second, parallel
     selection state that could disagree with the rest of the application. */
  const activeRowId = useMemo((): string | null => {
    if (corpus === "findings") return findingId;
    if (findingId === null) return null;
    for (const [rowId, target] of crossLayerBridge) if (target === findingId) return rowId;
    return null;
  }, [corpus, findingId]);

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
  const related = useMemo((): { ids: ReadonlySet<string>; hosts: string[] } => {
    const hosts: string[] = [];
    if (linkId !== null) {
      const l = linkById.get(linkId);
      if (l) hosts.push(l.a, l.b);
    } else if (deviceId !== null) {
      const d = deviceById.get(deviceId);
      hosts.push(d ? d.host : deviceId);
    }
    if (hosts.length === 0) return { ids: EMPTY_IDS, hosts };
    const want = new Set(hosts);
    const ids = new Set<string>();
    for (const n of nodes) {
      if (n.kind !== "row") continue;
      const named = "devices" in n.item ? n.item.devices : n.item.hosts;
      if (named.some((h) => want.has(h))) ids.add(n.id);
    }
    return { ids, hosts };
  }, [deviceId, linkId, nodes]);

  /* What the grid should put in front of the reader. A selected finding wins: it is the stronger
     statement of what is being read. With no finding, the first row naming the selected box is
     what the reader came for — a mark 6,000 px below the fold is not an answer. */
  const revealId = useMemo((): string | null => {
    if (activeRowId !== null) return activeRowId;
    for (const n of nodes) if (n.kind === "row" && related.ids.has(n.id)) return n.id;
    return null;
  }, [activeRowId, nodes, related]);

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

  const copyBatch = useCallback((): void => {
    const rows = result.items.filter((r) => batch.has(spec.idOf(r)));
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
  }, [result.items, batch, spec]);

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

  return (
    <section className={["pq", className].filter(Boolean).join(" ")} aria-label="Priority queue">
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

      <p className="visually-hidden" id={`${accountingId}-help`}>
        Structured filter. A key and a colon filters, for example severity:Critical. A leading minus
        excludes. Anything else is free text. Down arrow lists completions.
      </p>

      {/* ── scope chips carried by the shared investigation state ── */}
      {scopeClauses.length > 0 ? (
        <div className="pq-chips" aria-label="Scope carried from the investigation">
          {SEVERITY_ORDER.filter((s) => severities.has(s)).map((s) => (
            <Chip key={s} removeLabel={`Remove the ${s} severity filter`} onRemove={() => toggleSeverity(s)}>
              {`severity ${s}`}
            </Chip>
          ))}
          {[...roles].sort(cmpStr).map((r) => (
            <Chip key={r} removeLabel={`Remove the ${r} role filter`} onRemove={() => toggleRole(r)}>
              {`role ${r}`}
            </Chip>
          ))}
          {onlyUncollected ? (
            <Chip removeLabel="Remove the uncollected-devices filter" onRemove={() => setOnlyUncollected(false)}>
              devices never collected
            </Chip>
          ) : null}
        </div>
      ) : null}

      {/* ── display options, inline ── */}
      <div className="pq-controls">
        <Select
          label="Group"
          className="pq-select"
          options={groupOptions}
          value={spec.groupKeys.some((g) => g.value === groupKey) ? groupKey : "severity"}
          onChange={(e) => setGroupKey(e.currentTarget.value)}
        />
        <Select
          label="Order"
          className="pq-select"
          options={orderOptions}
          value={ordering.kind === "ranked" ? "ranked" : `${ordering.spec.field}:${ordering.spec.direction}`}
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
              Two lines fit the category and the devices beside the title at this rail width. One
              line is denser and hides them unless you turn them back on below.
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
          </div>
        </Popover>
      </div>

      {/* ── accounting ── */}
      <div className="pq-account" id={accountingId}>
        <p className="pq-account__line">
          <strong className="pq-account__shown">{shown}</strong>
          <span>{` of ${total} ${spec.noun} shown`}</span>
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
        {related.hosts.length > 0 ? (
          <p className="pq-account__note">
            {related.ids.size === 0
              ? `No shown ${spec.noun} name ${related.hosts.join(" or ")}. That is the absence of a published record within the current scope, not an assessment that ${related.hosts.length > 1 ? "those hosts are" : "that host is"} healthy.`
              : `${related.ids.size} of ${shown} shown ${spec.noun} name ${related.hosts.join(" or ")} — marked on the row's trailing edge.`}
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
                  <Button size="sm" onClick={() => setDraft("")}>
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
        Control plus A selects every shown row. Escape clears the batch.
      </p>

      {/* ── the batch ── */}
      {batch.size > 0 ? (
        <div className="pq-batch">
          <span className="pq-batch__count">{`${batch.size} selected`}</span>
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
        revealId={revealId}
        relatedIds={related.ids}
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
        onSelectAll={() => setBatch(new Set(result.items.map((r) => spec.idOf(r))))}
        onEscape={() => {
          /* Widest state first: a user pressing Escape is undoing the last thing they added, and
             leaving the grid is the last resort rather than the first. */
          if (batch.size > 0) {
            setBatch(new Set<string>());
            return true;
          }
          if (findingId === null) return false;
          selectFinding(null);
          return true;
        }}
        exitFocusRef={queryInputRef}
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
    </section>
  );
}
