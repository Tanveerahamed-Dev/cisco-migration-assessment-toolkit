/**
 * JsonView.tsx — a real JSON tree over the compiled evidence document.
 *
 * This is the last stop in the audit chain: when a reader does not believe a rendered claim, this
 * is where they read the bytes for themselves. Three properties follow from that job:
 *
 *   1. NOTHING IS SUMMARISED AWAY. `null` renders through the NotObserved treatment, never as a
 *      blank or a dash, and an EMPTY array renders as an empty array — "we collected nothing" and
 *      "we never collected" are opposite claims and this is the surface where the difference is
 *      checkable.
 *   2. IT IS A TREE, NOT A PRE BLOCK. APG treeview keys, roving tabindex, aria-level/setsize/
 *      posinset, copy-path on every node. A reader navigating by keyboard reaches any record.
 *      A row whose key or value is a record path the model resolves OPENS that record when it is
 *      activated (Enter, or double-click), through the citation control's own `onOpenCite` — the
 *      row stays one treeitem, with no control added inside it (acceptance B6).
 *   3. IT STAYS RESPONSIVE ON THE WHOLE DOCUMENT. Child rows are materialised only for expanded
 *      subtrees, and an oversized array is cut into chunks with the remainder stated, so the row
 *      count never tracks the document size.
 *
 * Determinism: no Math.random(), no Date.now(). Typeahead uses a reset timer rather than reading a
 * clock, so what is drawn is a pure function of props and user input (acceptance F6).
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import { IconChevronDown, IconChevronRight, IconCopy } from "../ui/icons";
import { Button, IconButton, Input, LiveRegion, NotObserved } from "../ui/primitives";
import { citeShows, citesIn } from "./cited-text";
/* The tree's styles live with the Inspector's because the tree only ever appears inside it;
   importing here keeps the component usable standalone without a second stylesheet to keep in
   step with the first. */
import "./Inspector.css";

/**
 * How many children of one container are materialised before the remainder is held behind an
 * explicit row. The largest array in the shipped snapshot is smaller than this, so the cut is a
 * GUARD against a future document rather than a behaviour a reader meets today — which is exactly
 * why its branch is exercised by a test with a synthetic oversized array. An unexecuted guard is
 * not a guard.
 */
const CHUNK = 200;

/** Cap on stored search hits. The count reported to the reader is the TRUE total, not the cap. */
const MAX_HITS = 500;

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Path syntax matches `Cite` (`a.b[0]`), so a path copied from this tree is a usable citation. */
const childPath = (parentId: string, key: string, isIndex: boolean): string =>
  isIndex ? `${parentId}${key}` : parentId === "" ? key : `${parentId}.${key}`;

interface Entry {
  /** Display key: an object key, or `[3]` for an array element. */
  key: string;
  value: unknown;
  id: string;
  isIndex: boolean;
}

function childEntries(value: unknown, parentId: string): Entry[] {
  if (Array.isArray(value)) {
    return value.map((v, i) => ({
      key: `[${i}]`,
      value: v,
      id: childPath(parentId, `[${i}]`, true),
      isIndex: true,
    }));
  }
  if (isPlainObject(value)) {
    return Object.keys(value).map((k) => ({
      key: k,
      value: value[k],
      id: childPath(parentId, k, false),
      isIndex: false,
    }));
  }
  return [];
}

/**
 * Ancestor ids of `target`, found by walking the document and generating ids the same way the
 * tree does — NOT by parsing the path string. A host key such as `wan-edge-rtr1.lab` contains a
 * dot, so a string parser would split it into two segments and silently fail to expand the branch
 * the reader asked for. Returns null when the path names nothing in this document.
 */
export function ancestorsOf(root: unknown, target: string): string[] | null {
  if (target === "") return [];
  const walk = (value: unknown, id: string, trail: string[]): string[] | null => {
    for (const entry of childEntries(value, id)) {
      if (entry.id === target) return trail;
      // Only descend where the target could still be: ids grow by prefix.
      if (target.startsWith(entry.id)) {
        const found = walk(entry.value, entry.id, [...trail, entry.id]);
        if (found) return found;
      }
    }
    return null;
  };
  return walk(root, "", [""]);
}

/* ── search ────────────────────────────────────────────────────────────────
   A full-document walk over every key and every primitive value. The compiled model is ~9k nodes,
   so this is a sub-millisecond pass and needs no index; building one would add a cache that can go
   stale against the document it claims to describe. */

export interface SearchResult {
  /** Ids of matching nodes, in document order, capped at MAX_HITS. */
  hits: string[];
  /** The true number of matches, which may exceed `hits.length`. */
  total: number;
}

export function searchDocument(root: unknown, needle: string): SearchResult {
  const q = needle.trim().toLowerCase();
  if (q === "") return { hits: [], total: 0 };
  const hits: string[] = [];
  let total = 0;
  const matches = (text: string): boolean => text.toLowerCase().includes(q);
  const walk = (value: unknown, id: string): void => {
    for (const entry of childEntries(value, id)) {
      const leafText =
        entry.value === null
          ? "null"
          : typeof entry.value === "object"
            ? null
            : String(entry.value);
      if (matches(entry.key) || (leafText !== null && matches(leafText))) {
        total += 1;
        if (hits.length < MAX_HITS) hits.push(entry.id);
      }
      walk(entry.value, entry.id);
    }
  };
  walk(root, "");
  return { hits, total };
}

/* ── clipboard ─────────────────────────────────────────────────────────────
   Shared with Inspector.tsx. A copy control that silently does nothing is worse than one that
   says it failed: the reader walks away believing they hold the evidence. */

export interface CopyState {
  copy: (value: string, what: string) => void;
  status: string;
}

export function useCopyToClipboard(): CopyState {
  const [status, setStatus] = useState("");
  const copy = useCallback((value: string, what: string) => {
    const write = navigator.clipboard?.writeText?.(value);
    if (!write) {
      setStatus(`Could not copy ${what}. Select the text and copy it manually.`);
      return;
    }
    write.then(
      () => setStatus(`Copied ${what}`),
      () => setStatus(`Could not copy ${what}. Select the text and copy it manually.`),
    );
  }, []);
  return { copy, status };
}

/* ── row model ─────────────────────────────────────────────────────────────── */

interface Row {
  id: string;
  key: string;
  value: unknown;
  depth: number;
  parentId: string | null;
  expandable: boolean;
  childCount: number;
  posInSet: number;
  setSize: number;
  /** A "show the rest of this array" row rather than a datum. */
  more: { parentId: string; shown: number; total: number } | null;
}

function flatten(
  root: unknown,
  rootLabel: string,
  expanded: ReadonlySet<string>,
  limits: ReadonlyMap<string, number>,
): Row[] {
  const rows: Row[] = [];
  const emit = (
    entry: Entry,
    depth: number,
    parentId: string | null,
    pos: number,
    size: number,
  ): void => {
    const kids = childEntries(entry.value, entry.id);
    rows.push({
      id: entry.id,
      key: entry.key,
      value: entry.value,
      depth,
      parentId,
      expandable: kids.length > 0,
      childCount: kids.length,
      posInSet: pos,
      setSize: size,
      more: null,
    });
    if (kids.length === 0 || !expanded.has(entry.id)) return;
    const limit = limits.get(entry.id) ?? CHUNK;
    const slice = kids.slice(0, limit);
    slice.forEach((k, i) => emit(k, depth + 1, entry.id, i + 1, kids.length));
    if (kids.length > limit) {
      rows.push({
        id: `${entry.id}\u0000more`,
        key: "",
        value: null,
        depth: depth + 1,
        parentId: entry.id,
        expandable: false,
        childCount: 0,
        posInSet: limit + 1,
        setSize: kids.length,
        more: { parentId: entry.id, shown: limit, total: kids.length },
      });
    }
  };
  emit({ key: rootLabel, value: root, id: "", isIndex: false }, 0, null, 1, 1);
  return rows;
}

/* ── value rendering ───────────────────────────────────────────────────────── */

/** Longer than this and a value is elided in the row; the full text stays in the title and in
 *  the copied JSON, so nothing is lost — only the row height is bounded. */
const VALUE_CLAMP = 180;

function highlight(text: string, needle: string): ReactNode {
  const q = needle.trim();
  if (q === "") return text;
  const lower = text.toLowerCase();
  const target = q.toLowerCase();
  const out: ReactNode[] = [];
  let at = 0;
  for (;;) {
    const found = lower.indexOf(target, at);
    if (found === -1) break;
    if (found > at) out.push(text.slice(at, found));
    out.push(
      <mark key={`${found}`} className="jsonview__mark">
        {text.slice(found, found + target.length)}
      </mark>,
    );
    at = found + target.length;
  }
  if (out.length === 0) return text;
  if (at < text.length) out.push(text.slice(at));
  return out;
}

function ValueCell({
  row,
  needle,
  expanded,
}: {
  row: Row;
  needle: string;
  expanded: boolean;
}): ReactElement {
  const v = row.value;
  if (v === null) {
    /* The whole reason this tree exists rather than a <pre>: a bare `null` in monospace reads as
       a filled-in field. It is not one. */
    return <NotObserved what={row.key} compact className="jsonview__value" />;
  }
  if (Array.isArray(v)) {
    return (
      <span className="jsonview__value jsonview__value--meta">
        {v.length === 0 ? "[ ] empty array" : expanded ? "[" : `[ ${v.length} items ]`}
      </span>
    );
  }
  if (isPlainObject(v)) {
    const n = Object.keys(v).length;
    return (
      <span className="jsonview__value jsonview__value--meta">
        {n === 0 ? "{ } empty object" : expanded ? "{" : `{ ${n} keys }`}
      </span>
    );
  }
  if (typeof v === "string") {
    const clipped = v.length > VALUE_CLAMP;
    const text = clipped ? `${v.slice(0, VALUE_CLAMP)}…` : v;
    return (
      <span className="jsonview__value jsonview__value--string" title={clipped ? v : undefined}>
        {"“"}
        {highlight(text, needle)}
        {"”"}
      </span>
    );
  }
  return (
    <span
      className={`jsonview__value jsonview__value--${typeof v === "number" ? "number" : "bool"}`}
    >
      {highlight(String(v), needle)}
    </span>
  );
}

/* ── the tree ──────────────────────────────────────────────────────────────── */

export interface JsonViewProps {
  /** The document to render. */
  value: unknown;
  /** Name for the root row, e.g. the compiled model's filename. */
  rootLabel: string;
  /** Accessible name for the tree. */
  label: string;
  /** A path inside `value` to pre-expand, highlight and reveal. */
  citedPath?: string | null;
  /**
   * Whether the tree is on screen. A tab panel is hidden, not unmounted — so the cited row cannot
   * be scrolled into view at mount time, because a hidden element has no layout to scroll. Pass
   * the tab's visibility and the reveal happens the moment the reader arrives.
   */
  visible?: boolean;
  /**
   * A reader-facing note per path, drawn beside that row's value — for a field whose bare value
   * would be misread. The Inspector annotates `coverage.aclLinesUnevaluable`, the collector's parser
   * flag, which read bare contradicts the status bar's undecidable count (review item 13).
   */
  annotations?: Readonly<Record<string, string>>;
  /**
   * Open the record a citation names — the Inspector passes `openInspector`, the call every
   * citation control makes. With it, a row whose key or value is a record path the model resolves
   * (the Inspector's own resolver, via `citesIn`) opens that record when activated: Enter or
   * double-click, stated in the row's accessible description and announced. Every other row is
   * plain data and the tree states NOTHING about it — in particular never that it "names no record":
   * that would be a claim about the whole model resting on a guess about a string's shape, and an
   * independent verifier found it false on ACL rows, MAC addresses, host names and version strings
   * that ARE in the model (Inspector.test.tsx pins both halves, over every node of fabric.json).
   * Without it (a standalone tree) no row claims to open anything.
   */
  onOpenCite?: (cite: string) => void;
  className?: string;
}

/**
 * The record a row opens: the first citation the Inspector's own resolver finds in the row's key or
 * string value, or null. Positive facts only — a row the resolver finds nothing in is data, not an
 * absence to report. Exported so the class can be tested over every node of the compiled model.
 */
export function rowCite(key: string, value: unknown): string | null {
  const texts = [key, typeof value === "string" ? value : ""];
  return texts.flatMap((t) => citesIn(t))[0] ?? null;
}

/** What a row's key or value names: the record it opens. */
interface RowNames {
  cite: string;
}

function namesOf(row: Row): RowNames | null {
  if (row.more || row.depth === 0) return null; // the root row's key is the document's name, not data
  const cite = rowCite(row.key, row.value);
  return cite === null ? null : { cite };
}

const describeNames = (n: RowNames): string => `Enter or double-click opens the record ${n.cite} in the Inspector.`;

export function JsonView({
  value,
  rootLabel,
  label,
  citedPath = null,
  visible = true,
  annotations,
  onOpenCite,
  className,
}: JsonViewProps): ReactElement {
  const initialExpanded = useMemo(() => {
    const set = new Set<string>([""]);
    if (citedPath) for (const a of ancestorsOf(value, citedPath) ?? []) set.add(a);
    return set;
  }, [value, citedPath]);

  const [expanded, setExpanded] = useState<ReadonlySet<string>>(initialExpanded);
  const [limits, setLimits] = useState<ReadonlyMap<string, number>>(new Map());
  const [activeId, setActiveId] = useState<string>(citedPath ?? "");
  const [needle, setNeedle] = useState("");
  const [hitAt, setHitAt] = useState(0);
  const { copy, status } = useCopyToClipboard();
  /* One live region for the tree: what the last copy or the last activation did. */
  const [said, setSaid] = useState("");
  /* The message currently in the region, and a pending re-announcement. A polite region only speaks
     when its text CHANGES, so saying the same thing twice (opening the same record again) must empty
     the region first and write it back a moment later (a timer, never a clock read: acceptance F6). */
  const saidNow = useRef("");
  const reannounce = useRef(0);
  const say = useCallback((message: string): void => {
    window.clearTimeout(reannounce.current);
    if (saidNow.current !== message) {
      saidNow.current = message;
      setSaid(message);
      return;
    }
    saidNow.current = "";
    setSaid("");
    reannounce.current = window.setTimeout(() => {
      saidNow.current = message;
      setSaid(message);
    }, 120);
  }, []);
  useEffect(() => () => window.clearTimeout(reannounce.current), []);
  /* The record this tree last opened. When the Inspector is re-pointed at anything ELSE — by another
     control — "Opened X" is no longer current, and a reader who moves into the region must not find it. */
  const lastOpened = useRef<string | null>(null);
  useEffect(() => {
    if (status !== "") say(status);
  }, [status, say]);
  useEffect(() => {
    const mine = lastOpened.current;
    if (mine === null) return;
    if (citedPath !== null && citeShows(mine, citedPath)) return; // the tree's own open: still current
    lastOpened.current = null;
    window.clearTimeout(reannounce.current);
    saidNow.current = "";
    setSaid("");
  }, [citedPath]);

  const treeRef = useRef<HTMLDivElement>(null);
  /* Focus is moved only in response to a key or a click. Focusing on mount would rip focus out of
     whatever the reader was using to open the Inspector. */
  const wantFocus = useRef(false);
  const typeahead = useRef({ buffer: "", timer: 0 });

  /* A new citation re-aims the tree: it expands and reveals, and it does NOT collapse what the
     reader had already opened. Continuity outranks tidiness (design brief §1). */
  useEffect(() => {
    if (!citedPath) return;
    const trail = ancestorsOf(value, citedPath);
    if (!trail) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      for (const a of trail) next.add(a);
      return next;
    });
    setActiveId(citedPath);
  }, [value, citedPath]);

  const search = useMemo(() => searchDocument(value, needle), [value, needle]);

  const rows = useMemo(
    () => flatten(value, rootLabel, expanded, limits),
    [value, rootLabel, expanded, limits],
  );
  const index = useMemo(() => new Map(rows.map((r, i) => [r.id, i])), [rows]);
  /* Only the rows on screen are asked, and only when there is somewhere to open a record. */
  const names = useMemo(() => {
    const m = new Map<string, RowNames>();
    if (onOpenCite === undefined) return m;
    for (const r of rows) {
      const n = namesOf(r);
      if (n !== null) m.set(r.id, n);
    }
    return m;
  }, [rows, onOpenCite]);
  const hitSet = useMemo(() => new Set(search.hits), [search.hits]);

  /* When the active row is inside a subtree the reader has since collapsed, the tree would have no
     tabbable element at all and Tab would skip the whole component. Fall back to the root. */
  const focusId = index.has(activeId) ? activeId : (rows[0]?.id ?? "");

  useEffect(() => {
    if (!wantFocus.current) return;
    wantFocus.current = false;
    /* Node ids carry `.`, `[`, `]` and the chunk sentinel, all of which are selector syntax.
       CSS.escape is the only correct quoting here; where it is missing we fall back to a scan
       rather than building a selector by hand and matching the wrong row. */
    const all = [...(treeRef.current?.querySelectorAll<HTMLElement>("[data-node-id]") ?? [])];
    const el = all.find((n) => n.dataset["nodeId"] === focusId);
    el?.focus();
    el?.scrollIntoView?.({ block: "nearest" });
  }, [focusId, rows]);

  /* Bring the cited row into view — WITHOUT focusing it. Highlighting a row the reader has to
     hunt for is the same as not highlighting it, and the JSON tab opens onto the top of a 16-key
     document where the cited node is usually below the fold. Runs when the tab becomes visible,
     because a hidden panel has no layout to scroll. */
  useEffect(() => {
    if (!visible || citedPath === null) return;
    const all = [...(treeRef.current?.querySelectorAll<HTMLElement>("[data-node-id]") ?? [])];
    const el = all.find((n) => n.dataset["nodeId"] === citedPath);
    el?.scrollIntoView?.({ block: "center" });
    /* Deliberately NOT keyed on `rows`: re-running on every expand would yank the viewport back to
       the citation each time the reader opened a branch somewhere else. */
  }, [visible, citedPath]);

  const move = useCallback(
    (id: string) => {
      wantFocus.current = true;
      setActiveId(id);
    },
    [setActiveId],
  );

  const setExpandedFor = useCallback((id: string, open: boolean) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  /** Reveal a path: expand every ancestor, then make it the active row. */
  const reveal = useCallback(
    (id: string) => {
      const trail = ancestorsOf(value, id);
      if (trail) {
        setExpanded((prev) => {
          const next = new Set(prev);
          for (const a of trail) next.add(a);
          return next;
        });
      }
      move(id);
    },
    [value, move],
  );

  const gotoHit = useCallback(
    (delta: number) => {
      if (search.hits.length === 0) return;
      const at = (hitAt + delta + search.hits.length) % search.hits.length;
      setHitAt(at);
      const id = search.hits[at];
      if (id !== undefined) reveal(id);
    },
    [search.hits, hitAt, reveal],
  );

  const copyPath = useCallback(
    (id: string) => {
      copy(id === "" ? rootLabel : id, `path ${id === "" ? rootLabel : id}`);
    },
    [copy, rootLabel],
  );

  /** Activate a row as a citation: open the record it names. A row that names none is not in `names`, so this does nothing for it. */
  const openRow = useCallback(
    (id: string): void => {
      const n = names.get(id);
      if (n === undefined || onOpenCite === undefined) return;
      lastOpened.current = n.cite;
      onOpenCite(n.cite);
      say(`Opened ${n.cite} in the Inspector.`);
    },
    [names, onOpenCite, say],
  );

  const showMore = useCallback((parentId: string) => {
    setLimits((prev) => {
      const next = new Map(prev);
      next.set(parentId, (next.get(parentId) ?? CHUNK) + CHUNK);
      return next;
    });
  }, []);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    /* The row the key was pressed ON. With roving focus that is the active row; reading it from the
       event rather than from state keeps a key pressed on a row meaning that row. */
    const on = (e.target as Element).closest?.<HTMLElement>("[data-node-id]")?.dataset["nodeId"];
    const at = index.get(on !== undefined && index.has(on) ? on : focusId);
    if (at === undefined) return;
    const row = rows[at];
    if (!row) return;
    const step = (delta: number): void => {
      const next = rows[at + delta];
      if (next) move(next.id);
    };
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        step(1);
        break;
      case "ArrowUp":
        e.preventDefault();
        step(-1);
        break;
      case "ArrowRight":
        e.preventDefault();
        if (row.expandable && !expanded.has(row.id)) setExpandedFor(row.id, true);
        else if (row.expandable) step(1);
        break;
      case "ArrowLeft":
        e.preventDefault();
        if (row.expandable && expanded.has(row.id)) setExpandedFor(row.id, false);
        else if (row.parentId !== null) move(row.parentId);
        break;
      case "Home": {
        e.preventDefault();
        const first = rows[0];
        if (first) move(first.id);
        break;
      }
      case "End": {
        e.preventDefault();
        const last = rows[rows.length - 1];
        if (last) move(last.id);
        break;
      }
      case "Enter": {
        /* APG: Enter performs the node's default action. A row that names a record opens it; any
           other row keeps the tree's own default (load more, expand or collapse), and a leaf that
           opens nothing does nothing — it is data, and nothing is claimed about it. */
        e.preventDefault();
        if (row.more) showMore(row.more.parentId);
        else if (names.has(row.id)) openRow(row.id);
        else if (row.expandable) setExpandedFor(row.id, !expanded.has(row.id));
        break;
      }
      case " ":
        /* Space keeps its tree meaning on every row, so a row that opens a record can still be
           expanded and collapsed from the keyboard. */
        e.preventDefault();
        if (row.more) showMore(row.more.parentId);
        else if (row.expandable) setExpandedFor(row.id, !expanded.has(row.id));
        break;
      case "*": {
        /* APG: expand every sibling at this level. Deliberately NOT recursive — a recursive
           expand-all on a 9k-node document is the jank this component exists to avoid. */
        e.preventDefault();
        const siblings = rows.filter((r) => r.parentId === row.parentId && r.expandable);
        setExpanded((prev) => {
          const next = new Set(prev);
          for (const s of siblings) next.add(s.id);
          return next;
        });
        break;
      }
      case "c":
      case "C":
        /* The copy-path control on a row is deliberately out of the tab order (it would break the
           tree's roving tabindex), so the keyboard route to it is this key. It is advertised in the
           tree's help text, not left for a reader to discover. */
        if (!e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault();
          copyPath(row.id);
        }
        break;
      default: {
        if (e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey) break;
        /* Typeahead over the visible rows. The buffer is cleared by a timer rather than by
           comparing clock readings, so nothing here reads a clock. */
        const t = typeahead.current;
        t.buffer += e.key.toLowerCase();
        window.clearTimeout(t.timer);
        t.timer = window.setTimeout(() => {
          t.buffer = "";
        }, 600);
        const order = [...rows.slice(at + 1), ...rows.slice(0, at + 1)];
        const found = order.find((r) => r.key.toLowerCase().startsWith(t.buffer));
        if (found) {
          e.preventDefault();
          move(found.id);
        }
        break;
      }
    }
  };

  const hitLabel =
    needle.trim() === ""
      ? ""
      : search.total === 0
        ? `No node in this document matches ${needle.trim()}`
        : search.hits.length < search.total
          ? `${search.total} matches; the first ${search.hits.length} are navigable`
          : `${search.total} match${search.total === 1 ? "" : "es"}`;

  return (
    <div className={["jsonview", className].filter(Boolean).join(" ")}>
      <div className="jsonview__toolbar">
        <div className="jsonview__search">
          <Input
            label="Search this document"
            value={needle}
            spellCheck={false}
            autoComplete="off"
            mono
            onChange={(e) => {
              setNeedle(e.currentTarget.value);
              setHitAt(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                gotoHit(e.shiftKey ? -1 : 1);
              }
            }}
          />
        </div>
        <div className="jsonview__hits">
          <span className="jsonview__hitcount">
            {hitLabel === "" ? (
              <span className="jsonview__hint">
                Keys and values. Enter steps through matches; c copies the focused path.
                {onOpenCite === undefined ? null : " A row underlined with dots names a record: Enter or double-click opens it."}
              </span>
            ) : (
              hitLabel
            )}
          </span>
          <Button size="sm" onClick={() => gotoHit(-1)} disabled={search.hits.length === 0}>
            Previous match
          </Button>
          <Button size="sm" onClick={() => gotoHit(1)} disabled={search.hits.length === 0}>
            Next match
          </Button>
        </div>
      </div>

      <div
        ref={treeRef}
        role="tree"
        aria-label={label}
        className="jsonview__tree"
        onKeyDown={onKeyDown}
      >
        {rows.map((row) => {
          const open = expanded.has(row.id);
          const isCited = citedPath !== null && row.id === citedPath;
          const currentHit = search.hits[hitAt];
          const more = row.more;
          const named = names.get(row.id);
          if (more) {
            return (
              <div
                key={row.id}
                role="treeitem"
                data-node-id={row.id}
                aria-level={row.depth + 1}
                aria-posinset={row.posInSet}
                aria-setsize={row.setSize}
                aria-selected={row.id === focusId}
                tabIndex={row.id === focusId ? 0 : -1}
                className="jsonview__row jsonview__row--more"
                style={{
                  paddingLeft: `calc(var(--sp-3) + ${row.depth} * var(--sp-4))`,
                }}
                onClick={() => {
                  move(row.id);
                  showMore(more.parentId);
                }}
              >
                <span className="jsonview__morelabel">
                  {more.total - more.shown} more of {more.total} not rendered — activate to load the
                  next {CHUNK}
                </span>
              </div>
            );
          }
          return (
            <div
              key={row.id}
              role="treeitem"
              data-node-id={row.id}
              data-cited={isCited ? "true" : undefined}
              data-match={hitSet.has(row.id) ? "true" : undefined}
              data-current-match={row.id === currentHit ? "true" : undefined}
              aria-level={row.depth + 1}
              aria-posinset={row.posInSet}
              aria-setsize={row.setSize}
              aria-selected={row.id === focusId}
              aria-expanded={row.expandable ? open : undefined}
              aria-description={named === undefined ? undefined : describeNames(named)}
              data-opens={named !== undefined ? "true" : undefined}
              tabIndex={row.id === focusId ? 0 : -1}
              className="jsonview__row"
              style={{
                paddingLeft: `calc(var(--sp-2) + ${row.depth} * var(--sp-4))`,
              }}
              onClick={(e) => {
                if ((e.target as HTMLElement).closest(".jsonview__copy")) return;
                move(row.id);
                if (row.expandable) setExpandedFor(row.id, !open);
              }}
              onDoubleClick={(e) => {
                if ((e.target as HTMLElement).closest(".jsonview__copy")) return;
                openRow(row.id);
              }}
            >
              <span className="jsonview__twisty" aria-hidden="true">
                {row.expandable ? open ? <IconChevronDown /> : <IconChevronRight /> : null}
              </span>
              <span className="jsonview__key">{highlight(row.key, needle)}</span>
              {row.depth > 0 ? <span className="jsonview__colon">:</span> : null}
              <ValueCell row={row} needle={needle} expanded={open} />
              {isCited ? <span className="jsonview__citedmark">cited here</span> : null}
              {annotations?.[row.id] !== undefined ? <span className="jsonview__note" title={annotations[row.id]}>{annotations[row.id]}</span> : null}
              <IconButton
                label={`Copy path ${row.id === "" ? rootLabel : row.id}`}
                icon={<IconCopy />}
                size="sm"
                /* Out of the tab order on purpose: a focusable control inside a treeitem breaks the
                   roving tabindex the tree pattern depends on. The `c` key is the keyboard route. */
                tabIndex={-1}
                className="jsonview__copy"
                onClick={() => copyPath(row.id)}
              />
            </div>
          );
        })}
      </div>
      <LiveRegion message={said} />
    </div>
  );
}
