/**
 * CommandPalette.tsx — one search box over the verbs AND the evidence.
 *
 * Two references meet here. Linear's palette makes navigation cost one keystroke; Forward's search
 * bar teaches its own grammar instead of waiting to be guessed. So this box answers three kinds of
 * question at once, and labels which kind each answer is:
 *
 *   "critical"                  -> the severity filter, and every record whose text says Critical
 *   "core1"                     -> the device, its interfaces, its findings
 *   "10.0.10.50 -> 10.0.30.10"  -> a forwarding question, offered as a trace
 *
 * The empty state is the teaching surface, and every example on it is generated from this snapshot
 * (`grammarExamples()`) carrying the number of rows it returns. An example that would return
 * nothing is never shown: a search box that teaches a query returning zero results teaches the
 * user that search does not work.
 *
 * Honesty rules apply here as everywhere else: a record with no observed band or role renders the
 * absence through `NotObserved`, never as a blank; a command that cannot act right now is listed
 * WITH its reason rather than hidden; and every evidence row carries the citation it came from.
 *
 * Responsiveness (design brief 8.2, journey 5): the search index is built once and memoised inside
 * `rankedSearch`, so opening is a mount over an existing index; the per-keystroke work runs against
 * a DEFERRED value, so the character echoes in the same frame and the list catches up in the next.
 * Measured numbers are in CommandPalette.test.tsx.
 */
import {
  memo,
  useCallback,
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import { deviceById, fabric, findingById } from "../core/data";
import { applyToFindings, parseQuery, rankedSearch, type SearchHit } from "../core/query";
import { useInvestigation } from "../core/store";
import { IconArrowRight, IconSearch } from "../ui/icons";
import { Band, Dialog, Kbd, LiveRegion, NotObserved, SeverityBadge } from "../ui/primitives";
import {
  GROUP_ORDER,
  allCommands,
  announce,
  commandAvailability,
  consumePaletteSeed,
  formatFlow,
  grammarExamples,
  parseFlowQuery,
  runFlow,
  useAppCommands,
  useCommandTargets,
  type Command,
} from "./commands";
import { formatShortcut, shortcutText, useGlobalKeyboard } from "./keyboard";
import "./CommandPalette.css";

/* ══ the result model ══════════════════════════════════════════════════════ */

interface Row {
  key: string;
  label: ReactNode;
  /** Plain-text form, for the accessible name and for what the live region announces. */
  text: string;
  /** Right-hand side: a shortcut, a match explanation, an outcome. */
  meta?: ReactNode;
  /** Second line: evidence, rationale, or the reason this row cannot act. */
  detail?: ReactNode;
  /** The citation of the record behind the row. Commands are verbs and carry none. */
  cite?: string;
  /** A string makes the row `aria-disabled` and states why. */
  disabledReason?: string | null;
  run: () => void;
}

interface RowGroup {
  key: string;
  label: string;
  /** A denominator or caveat for this group — shown beside the heading, never hidden. */
  note?: string | null;
  rows: Row[];
}

const HITS_PER_KIND = 6;
const SEARCH_LIMIT = 40;

const KIND_GROUP: Readonly<Record<SearchHit["kind"], string>> = {
  device: "Devices",
  finding: "Findings",
  "cross-layer": "Cross-layer findings",
  interface: "Interfaces",
  endpoint: "Endpoints",
};

const KIND_ORDER: readonly SearchHit["kind"][] = [
  "device",
  "finding",
  "cross-layer",
  "interface",
  "endpoint",
];

const EM_DASH = "—";

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** What this box actually searches, counted from the compiled fabric rather than written down. */
const searchScope = (() => {
  let cached: string | null = null;
  return (): string => {
    if (cached !== null) return cached;
    const interfaces = Object.values(fabric.interfaces).reduce((n, rows) => n + rows.length, 0);
    cached = [
      `${fabric.devices.length} devices`,
      `${fabric.findings.length} findings`,
      `${fabric.crossLayer.length} cross-layer`,
      `${interfaces} interfaces`,
      `${fabric.endpoints.length} endpoints`,
    ].join(" · ");
    return cached;
  };
})();

/**
 * Scored over the title first, keywords second. A word-boundary hit outranks a mid-token one for
 * the same reason it does in `rankedSearch`: it is likelier to be what the user meant.
 */
function scoreCommand(c: Command, term: string, wordRe: RegExp): number {
  const title = c.title.toLowerCase();
  if (title.startsWith(term)) return 100;
  if (wordRe.test(title)) return 80;
  if (title.includes(term)) return 60;
  for (const k of c.keywords) {
    const kw = k.toLowerCase();
    if (kw.startsWith(term)) return 45;
    if (kw.includes(term)) return 30;
  }
  return c.group.toLowerCase().includes(term) ? 20 : 0;
}

/* ══ row builders ══════════════════════════════════════════════════════════ */

function ShortcutKeys({ keys }: { keys: string }): ReactNode {
  return (
    <span className="palette__keys" aria-hidden="true">
      {formatShortcut(keys).map((t, i) =>
        t.kind === "then" ? (
          <span key={`${t.text}-${i}`} className="palette__then">
            then
          </span>
        ) : (
          <Kbd key={`${t.text}-${i}`}>{t.text}</Kbd>
        ),
      )}
    </span>
  );
}

function commandRow(c: Command, close: () => void): Row {
  const a = commandAvailability(c);
  return {
    key: `command:${c.id}`,
    label: <span className="palette__text">{c.title}</span>,
    text: c.shortcut ? `${c.title}, ${shortcutText(c.shortcut)}` : c.title,
    ...(c.shortcut === undefined ? {} : { meta: <ShortcutKeys keys={c.shortcut} /> }),
    /* The reason REPLACES the detail when the command cannot act, so the second line always
       answers the question the user is about to ask. */
    ...(a.ok ? (c.detail ? { detail: c.detail } : {}) : { detail: a.reason }),
    disabledReason: a.ok ? null : a.reason,
    run: () => {
      if (!a.ok) {
        announce(a.reason ?? "That action is not available right now.");
        return;
      }
      close();
      c.run();
    },
  };
}

function DeviceDetail({ hostId }: { hostId: string }): ReactNode {
  const d = deviceById.get(hostId);
  if (!d) return null;
  return (
    <>
      <span className="palette__kv">
        role {d.role === null ? <NotObserved what="role" compact /> : d.role}
      </span>
      <span className="palette__kv">
        band <Band band={d.band} />
      </span>
      {d.collected ? null : (
        <span className="palette__kv palette__kv--absent">
          topology only {EM_DASH} no evidence collected
        </span>
      )}
    </>
  );
}

const crossLayerByCite = (() => {
  let cached: Map<string, (typeof fabric.crossLayer)[number]> | null = null;
  return (cite: string) => {
    cached ??= new Map(fabric.crossLayer.map((c) => [c.cite, c]));
    return cached.get(cite) ?? null;
  };
})();

function hitRow(hit: SearchHit, close: () => void): Row {
  const base = {
    key: `hit:${hit.kind}:${hit.id}:${hit.cite}`,
    cite: hit.cite,
    meta: (
      <span className="palette__matched">
        matched <span className="palette__matched-field">{hit.field}</span>
      </span>
    ),
  };

  if (hit.kind === "device") {
    return {
      ...base,
      label: (
        <span className="palette__title">
          <span className="palette__mono">{hit.label}</span>
        </span>
      ),
      text: `${hit.label}, device`,
      detail: <DeviceDetail hostId={hit.id} />,
      run: () => {
        close();
        useInvestigation.getState().selectDevice(hit.id, { surface: "fabric" });
        announce(`Selected device ${hit.label}.`);
      },
    };
  }

  if (hit.kind === "finding" || hit.kind === "cross-layer") {
    const severity =
      hit.kind === "finding"
        ? (findingById.get(hit.id)?.severity ?? null)
        : (crossLayerByCite(hit.cite)?.severity ?? null);
    return {
      ...base,
      label: (
        <span className="palette__title">
          {severity === null ? (
            <NotObserved what="severity" compact />
          ) : (
            <SeverityBadge severity={severity} compact />
          )}
          <span className="palette__mono">{hit.id}</span>
          <span className="palette__text">{hit.label}</span>
        </span>
      ),
      text: `${severity ?? "severity not observed"}, ${hit.id}, ${hit.label}`,
      detail: hit.detail ?? <NotObserved what="detail" compact />,
      run: () => {
        close();
        const store = useInvestigation.getState();
        if (hit.kind === "finding") {
          store.selectFinding(hit.id);
          announce(`Selected finding ${hit.id}.`);
          return;
        }
        /* A cross-layer row names hosts, not a finding id the queue holds; selecting its first
           host is the closest true action, and the row says so before it is run. */
        if (hit.host === null) {
          announce(`${hit.id} names no host, so there is nothing to select from it.`);
          return;
        }
        store.selectDevice(hit.host, { surface: "fabric" });
        announce(`Selected ${hit.host}, named by ${hit.id}.`);
      },
    };
  }

  /* Interfaces and endpoints are evidence ABOUT a host. The palette selects that host and says so
     on the row, rather than appearing to select a record the rest of the app cannot hold. */
  const host = hit.host;
  return {
    ...base,
    label: (
      <span className="palette__title">
        <span className="palette__mono">{hit.label}</span>
        {host === null ? null : (
          <span className="palette__action">
            <IconArrowRight className="palette__action-glyph" /> select {host}
          </span>
        )}
      </span>
    ),
    text: `${hit.label}${host === null ? "" : `, selects ${host}`}`,
    detail: hit.detail ?? <NotObserved what="description" compact />,
    disabledReason:
      host === null ? "This record names no host, so there is nothing to select from it." : null,
    run: () => {
      if (host === null) {
        announce("That record names no host, so there is nothing to select from it.");
        return;
      }
      close();
      useInvestigation.getState().selectDevice(host, { surface: "fabric" });
      announce(`Selected ${host}.`);
    },
  };
}

/**
 * One result row, memoised on its identity and its active flag.
 *
 * Why it matters: moving the cursor changes exactly two rows, and without the memo an arrow key
 * re-renders every row in the list. At 30-odd rows that is the difference between an arrow key
 * that feels like a cursor and one that feels like a request (design brief 8.3 rule 1).
 */
const PaletteRow = memo(function PaletteRow({
  row,
  id,
  index,
  isActive,
  onHover,
  onRun,
}: {
  row: Row;
  id: string;
  index: number;
  isActive: boolean;
  onHover: (i: number) => void;
  onRun: (r: Row) => void;
}): ReactNode {
  const disabled = typeof row.disabledReason === "string";
  return (
    <div
      id={id}
      role="option"
      aria-selected={isActive}
      {...(disabled ? { "aria-disabled": true } : {})}
      {...(isActive ? { "data-active": "true" } : {})}
      className="palette__row"
      onMouseEnter={() => onHover(index)}
      onClick={() => onRun(row)}
    >
      <span className="palette__row-main">
        <span className="palette__row-label">{row.label}</span>
        {row.detail === undefined || row.detail === null ? null : (
          <span className="palette__row-detail">{row.detail}</span>
        )}
      </span>
      <span className="palette__row-side">
        {row.meta ?? null}
        {row.cite === undefined ? null : (
          <span className="palette__cite" title={`Source record: ${row.cite}`}>
            {row.cite}
          </span>
        )}
      </span>
    </div>
  );
});

/* ══ the component ═════════════════════════════════════════════════════════ */

export function CommandPalette(): ReactNode {
  /* Mounting the palette is enough to make Cmd/Ctrl+K work: it owns the keyboard model's lifetime
     as well as its own. Both installs are ref-counted, so an App shell that also asks for them is
     not a double registration. */
  useGlobalKeyboard();
  useAppCommands();

  const open = useInvestigation((s) => s.paletteOpen);
  const setPaletteOpen = useInvestigation((s) => s.setPaletteOpen);
  const focusReturn = useInvestigation((s) => s.focusReturn);
  /* Availability is read at render; this subscription is what makes a command stop saying "not on
     screen" the moment the surface that owns it mounts. */
  const targetEpoch = useCommandTargets();

  const [input, setInput] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const baseId = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const listId = `${baseId}-list`;

  /* The echo is synchronous; the list is derived from the deferred value, so a keystroke never
     waits on the search. React may commit the input ahead of the list — that is the point. */
  const term = useDeferredValue(input);

  const close = useCallback(() => {
    setPaletteOpen(false);
    /* The store carries the exact invoking element (design brief 7.4 rule 4). Dialog restores too,
       but it restores to whatever was active when it mounted; this is the explicit target. */
    focusReturn?.focus?.();
  }, [setPaletteOpen, focusReturn]);

  useEffect(() => {
    if (!open) return;
    /* Read-once: a seed that survived its opening would re-apply on the next, unrelated open. */
    const seed = consumePaletteSeed();
    setInput(seed ?? "");
    setActive(0);
  }, [open]);

  const groups = useMemo<RowGroup[]>(() => {
    void targetEpoch; // availability is recomputed when the set of mounted owners changes
    const q = term.trim();
    const commands = allCommands();

    if (q === "") {
      const examples: RowGroup = {
        key: "examples",
        label: "Try a query",
        note: "generated from this snapshot",
        rows: grammarExamples().map((ex) => ({
          key: `example:${ex.query}`,
          label: <span className="palette__mono palette__example">{ex.query}</span>,
          text: `${ex.query}. ${ex.detail}`,
          detail: ex.detail,
          meta: <span className="palette__matched">fills the search box</span>,
          run: () => {
            setInput(ex.query);
            setActive(0);
            inputRef.current?.focus();
          },
        })),
      };
      const byGroup: RowGroup[] = GROUP_ORDER.map((g) => ({
        key: `group-${g.replace(/\s+/g, "-").toLowerCase()}`,
        label: g,
        rows: commands.filter((c) => c.group === g).map((c) => commandRow(c, close)),
      })).filter((g) => g.rows.length > 0);
      return examples.rows.length > 0 ? [examples, ...byGroup] : byGroup;
    }

    const out: RowGroup[] = [];

    const flow = parseFlowQuery(q);
    if (flow) {
      out.push({
        key: "flow",
        label: "Path question",
        rows: [
          {
            key: `flow:${flow.flow.srcIp}:${flow.flow.dstIp}:${flow.flow.dstPort ?? "any"}`,
            label: (
              <span className="palette__title">
                <span className="palette__text">Trace</span>
                <span className="palette__mono">{formatFlow(flow.flow)}</span>
              </span>
            ),
            text: `Trace ${formatFlow(flow.flow)}`,
            meta: <ShortcutKeys keys="enter" />,
            /* Every value the grammar supplied rather than the user is printed BEFORE the trace
               runs, so no assumption enters a forwarding verdict unannounced. */
            detail:
              flow.assumptions.length === 0
                ? "Every field was given explicitly."
                : flow.assumptions.join(" "),
            run: () => {
              close();
              runFlow(flow.flow);
            },
          },
        ],
      });
    }

    /* A `key:value` query is a FILTER, and the palette must be able to run it — otherwise the
       grammar the empty state teaches dead-ends here, which is worse than not teaching it. The
       row carries the three-way accounting the filter engine returns: matched, and how many rows
       it could not decide because the evidence was never collected. */
    const parsed = parseQuery(q);
    if (parsed.clauses.length > 0) {
      const applied = applyToFindings(fabric.findings, parsed);
      const unrecognised = applied.unrecognisedKeys;
      const blocked =
        unrecognised.length === 0
          ? null
          : `${unrecognised.map((k) => `"${k}"`).join(", ")} ${unrecognised.length === 1 ? "is not a filter" : "are not filters"} this data model answers, so the query would return nothing at all.`;
      out.push({
        key: "filter",
        label: "Filter the investigation",
        rows: [
          {
            key: `filter:${q}`,
            label: (
              <span className="palette__title">
                <span className="palette__text">Apply filter</span>
                <span className="palette__mono">{q}</span>
              </span>
            ),
            text: `Apply filter ${q}`,
            meta: <ShortcutKeys keys="enter" />,
            detail:
              blocked ??
              `${applied.items.length} of ${applied.total} findings match` +
                (applied.undeterminedTotal > 0
                  ? `, ${applied.undeterminedTotal} undecided — the evidence to decide was never collected, so they are neither in nor out.`
                  : "."),
            disabledReason: blocked,
            run: () => {
              if (blocked !== null) {
                announce(blocked);
                return;
              }
              close();
              const store = useInvestigation.getState();
              store.setQuery(q);
              store.setSurface("findings");
              announce(`Filter applied: ${applied.items.length} of ${applied.total} findings match.`);
            },
          },
        ],
      });
    }

    /* With a clause and no free text, the thing worth searching for is the clause's own value:
       `host:core1` should still surface core1 itself. The group says which string it matched on,
       so the result set is never wider than the label explains. */
    const firstValue = parsed.clauses.find((c) => c.values.length > 0)?.values[0];
    const searchTerm =
      parsed.terms.length === 0 && firstValue !== undefined ? firstValue : q;
    const searchNote = searchTerm === q ? null : `matching “${searchTerm}”`;

    const lower = q.toLowerCase();
    const wordRe = new RegExp(`\\b${escapeRe(lower)}`);
    const matchedCommands = commands
      .map((c) => ({ c, score: scoreCommand(c, lower, wordRe) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score || a.c.title.localeCompare(b.c.title))
      .map((x) => commandRow(x.c, close));
    if (matchedCommands.length > 0)
      out.push({ key: "commands", label: "Commands", rows: matchedCommands });

    const result = rankedSearch(searchTerm, { limit: SEARCH_LIMIT });
    const byKind = new Map<SearchHit["kind"], SearchHit[]>();
    for (const h of result.hits) {
      const list = byKind.get(h.kind);
      if (list) list.push(h);
      else byKind.set(h.kind, [h]);
    }
    for (const kind of KIND_ORDER) {
      const hits = byKind.get(kind);
      if (!hits || hits.length === 0) continue;
      const shown = hits.slice(0, HITS_PER_KIND);
      out.push({
        key: `hits-${kind}`,
        label: KIND_GROUP[kind],
        /* The denominator is the number this search RETURNED for the kind, not a claim about how
           many exist — `rankedSearch` was capped, and the cap is reported separately below. */
        note: [
          shown.length < hits.length
            ? `showing ${shown.length} of ${hits.length} returned`
            : `${hits.length}`,
          searchNote,
        ]
          .filter((s): s is string => s !== null)
          .join(" · "),
        rows: shown.map((h) => hitRow(h, close)),
      });
    }

    if (result.truncated)
      out.push({
        key: "truncation",
        label: "Result limit",
        rows: [
          {
            key: "truncation-note",
            label: (
              <span className="palette__text">
                Ranked search returned the top {SEARCH_LIMIT} of {result.totalHits} matching
                records.
              </span>
            ),
            text: `Ranked search returned the top ${SEARCH_LIMIT} of ${result.totalHits} matching records.`,
            detail:
              "Add another word, or a key:value filter, to narrow the set rather than scroll it.",
            disabledReason: "This row states the limit; it is not an action.",
            run: () => {},
          },
        ],
      });

    return out;
  }, [term, close, targetEpoch]);

  const rows = useMemo(() => groups.flatMap((g) => g.rows), [groups]);

  /* Clamp rather than reset: a list that shrinks under the cursor should keep the cursor near
     where the user left it, not throw them back to the top. */
  useEffect(() => {
    setActive((i) => (rows.length === 0 ? 0 : Math.min(i, rows.length - 1)));
  }, [rows.length]);

  const activeRow = rows[active];
  const activeId = activeRow ? `${baseId}-opt-${active}` : undefined;

  useEffect(() => {
    if (!open || activeId === undefined) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[id="${activeId}"]`);
    /* jsdom implements neither scrollIntoView nor CSS.escape; the guards keep the unit tests
       honest instead of mocking browser APIs into existence. */
    el?.scrollIntoView?.({ block: "nearest" });
  }, [open, activeId]);

  const move = useCallback(
    (delta: number) => {
      setActive((i) => {
        if (rows.length === 0) return 0;
        /* A palette list WRAPS — unlike the findings grid, which clamps (design brief 7.2). A
           short menu read top-to-bottom carries no positional model to preserve, and wrapping
           saves a full traversal to reach the last row. */
        return (i + delta + rows.length) % rows.length;
      });
    },
    [rows.length],
  );

  const onKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLInputElement>) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          move(1);
          return;
        case "ArrowUp":
          e.preventDefault();
          move(-1);
          return;
        case "Home":
          /* Home and End belong to the text caret while there is text to move through; they only
             jump the list when the box is empty. Taking them unconditionally would make editing a
             long query impossible. */
          if (input !== "") return;
          e.preventDefault();
          setActive(0);
          return;
        case "End":
          if (input !== "") return;
          e.preventDefault();
          setActive(Math.max(0, rows.length - 1));
          return;
        case "Enter": {
          const row = rows[active];
          if (!row) return;
          e.preventDefault();
          row.run();
          return;
        }
        default:
          return;
      }
    },
    [move, rows, active, input],
  );

  const count = rows.length;
  const trimmed = term.trim();
  const status =
    trimmed === ""
      ? ""
      : `${count} result${count === 1 ? "" : "s"} for ${trimmed}${activeRow ? `. ${activeRow.text}` : ""}`;

  /* Stable callbacks, so `PaletteRow`'s memo actually bails out: a new closure per render would
     invalidate every row on every cursor move, which is the thing the memo exists to prevent. */
  const hover = useCallback((i: number) => setActive(i), []);
  const runRow = useCallback((r: Row) => r.run(), []);

  /* One flat index over the groups, so the rendering pass does not have to mutate a counter and
     the id of a row is a pure function of the result set. */
  const indexOf = useMemo(() => {
    const m = new Map<string, number>();
    rows.forEach((r, i) => m.set(r.key, i));
    return m;
  }, [rows]);

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Command palette"
      width="lg"
      className="palette"
      initialFocus={inputRef}
      footer={
        <div className="palette__foot">
          <span className="palette__scope">Searching {searchScope()} in this snapshot</span>
          <span className="palette__hints">
            <ShortcutKeys keys="arrowup" />
            <ShortcutKeys keys="arrowdown" />
            <span className="palette__hint-label">move</span>
            <ShortcutKeys keys="enter" />
            <span className="palette__hint-label">run</span>
            <ShortcutKeys keys="escape" />
            <span className="palette__hint-label">close</span>
          </span>
        </div>
      }
    >
      <div className="palette__search">
        <IconSearch className="palette__search-glyph" />
        {/* A raw input rather than the `Input` primitive: this is an APG combobox, which owns
            aria-expanded / aria-controls / aria-activedescendant on the input element itself, and
            the primitive's visible Field label would break the single-line search affordance. The
            accessible name is on the element — not in a tooltip, and not the placeholder. */}
        <input
          ref={inputRef}
          className="palette__input"
          type="text"
          role="combobox"
          autoComplete="off"
          spellCheck={false}
          aria-label="Search commands, devices, findings and paths"
          aria-expanded={count > 0}
          aria-controls={listId}
          {...(activeId === undefined ? {} : { "aria-activedescendant": activeId })}
          aria-describedby={`${baseId}-scope`}
          placeholder={`Search a command, a device, a finding ${EM_DASH} or an address pair to trace`}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
      </div>

      <div className="palette__results" id={listId} role="listbox" aria-label="Results" ref={listRef}>
        {groups.length === 0 ? (
          <div className="palette__empty">
            <p className="palette__empty-title">Nothing in this snapshot matches that.</p>
            <p className="palette__empty-reason">
              The search covers {searchScope()}. A term that matches nothing here means no collected
              record carries it {EM_DASH} it does not mean the network does not have it.
            </p>
          </div>
        ) : (
          groups.map((g) => (
            <div
              className="palette__group"
              role="group"
              aria-label={g.note ? `${g.label}, ${g.note}` : g.label}
              key={g.key}
            >
              <div className="palette__group-head" aria-hidden="true">
                <span className="palette__group-label">{g.label}</span>
                {g.note ? <span className="palette__group-note">{g.note}</span> : null}
              </div>
              {g.rows.map((row) => {
                const i = indexOf.get(row.key) ?? 0;
                return (
                  <PaletteRow
                    key={row.key}
                    row={row}
                    id={`${baseId}-opt-${i}`}
                    index={i}
                    isActive={i === active}
                    onHover={hover}
                    onRun={runRow}
                  />
                );
              })}
            </div>
          ))
        )}
      </div>

      <span className="visually-hidden" id={`${baseId}-scope`}>
        Searching {searchScope()} in this snapshot. Type a key and a value to filter, or two
        addresses to trace a path.
      </span>
      <LiveRegion message={status} />
    </Dialog>
  );
}

export default CommandPalette;
