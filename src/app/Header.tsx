/**
 * Header.tsx — identity, question, destination. The three things that must never be ambiguous.
 *
 * SNAPSHOT IDENTITY IS NOT A DETAIL VIEW. The source file, its schema and its collection time sit
 * in the chrome permanently, exactly as Forward keeps its snapshot selector in the header. Every
 * verdict this application renders is a statement about one frozen collection, and a reader who
 * has to go and look up which one is a reader who will eventually assume the wrong one. The full
 * sha256 and the byte count are one click away; the identity itself never is.
 *
 * THE QUERY BAR TEACHES ITS OWN GRAMMAR, using values that exist in THIS snapshot. A placeholder
 * showing an invented hostname sends the reader to an empty result and teaches them that the tool
 * is broken, so the example is derived from `fabric` at render time.
 *
 * COOPERATIVE KEY BINDING. Several surfaces bind global keys and none of them can see the others.
 * Every handler here checks `event.defaultPrevented` first and marks the event when it acts, so
 * one keystroke never runs two handlers. `Cmd/Ctrl+K` focuses the query bar only if nothing else
 * has already claimed it — the command palette, when it is mounted, gets first refusal.
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactElement,
} from "react";
import { fabric, severityCounts } from "../core/data";
import { encodeInvestigation, useInvestigation } from "../core/store";
import { SEVERITY_ORDER, type SurfaceId } from "../core/types";
import { IconClose, IconCommand, IconCopy, IconSearch } from "../ui/icons";
import {
  Copyable,
  IconButton,
  Kbd,
  LiveRegion,
  NotObserved,
  Popover,
  Toolbar,
  orNotObserved,
} from "../ui/primitives";
import { setHelpOpen } from "./keyboard";
import { recordReturn, returnFocus, type ReturnRecord } from "./focus-return";
import { ThemeToggle, useThemeShortcut } from "./ThemeToggle";
import "./chrome.css";

/* ── the frame's own breakpoint ────────────────────────────────────────────────
   Measured, not guessed: brand 32 + identity 256 + query 128 + toolbar 231 + theme 81 + two icon
   buttons 56 + six 12px gaps = 856px of content. Below 1024 that starts to overlap — and because
   the header sets no scroll region, overlap is what it does rather than clipping, which is worse
   because it still looks deliberate in a screenshot.
   So at 1023px and below the toolbar, the theme group and the utilities move into ONE overflow
   popover. They are moved, never dropped: a control that disappears at a narrow viewport is a
   function the keyboard user has lost, not a layout that has adapted. */
const COMPACT_QUERY = "(max-width: 63.9375rem)";

const compactQuery = (): MediaQueryList | null =>
  typeof window === "undefined" || !window.matchMedia ? null : window.matchMedia(COMPACT_QUERY);

/**
 * Deliberately NOT memoised at module scope. `matchMedia` returns a fresh `MediaQueryList` per
 * call, so the subscription closes over the exact object it registered on — which is what makes
 * the unsubscribe remove the listener it added rather than a different instance's. A module-level
 * cache would also freeze whatever `matchMedia` existed at import time, which silently defeats
 * any harness that replaces it.
 */
function useCompact(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = compactQuery();
      mq?.addEventListener?.("change", cb);
      return () => mq?.removeEventListener?.("change", cb);
    },
    () => compactQuery()?.matches ?? false,
    () => false,
  );
}

/* ── surfaces ──────────────────────────────────────────────────────────────── */

interface SurfaceDef {
  id: SurfaceId;
  label: string;
  hint: string;
}

const SURFACES: readonly SurfaceDef[] = [
  { id: "fabric", label: "Fabric", hint: "the 3-D topology and everything selectable on it" },
  { id: "findings", label: "Findings", hint: "the priority queue, grouped by severity" },
  { id: "path", label: "Path", hint: "a forwarding question and its hop-by-hop answer" },
  { id: "evidence", label: "Evidence", hint: "the records behind the current selection" },
];

/* ── shortcuts ─────────────────────────────────────────────────────────────── */


/*
 * Header registers NO shortcuts of its own, and that is the point.
 *
 * It used to install `/` with a raw `window.addEventListener`, which was invisible to the
 * registry — so the generated help sheet could not list it, which is why a second, hand-written
 * help overlay grew up inside this file to compensate.
 *
 * But `/` was never Header's to own: `commands.ts` already declares `query.focus` as a
 * capability bound to `/`, and `App.tsx` registers the query input as its target. The raw
 * listener was a duplicate of an existing capability, not a missing one. Removing it is the entire
 * fix; adding a registration here just recreated the duplicate under a new name, which showed up on
 * the sheet as "Focus the query bar: //" with two key chips.
 *
 * A surface that needs a key asks for the capability. It does not bind the key itself.
 */

/* ── helpers ───────────────────────────────────────────────────────────────── */

/** Locale-free digit grouping: `toLocaleString()` renders differently per machine, and a capture
 *  that differs between machines cannot be byte-compared (acceptance F6). */
/** Design brief §8.2 journey 3: the filter recompute is debounced 120 ms — the queue's own field
 *  uses the same figure, so the two query inputs agree on when a filter lands. */
export const QUERY_DEBOUNCE_MS = 120;

const groupDigits = (n: number): string => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ");

const isTypingTarget = (el: EventTarget | null): boolean => {
  if (!(el instanceof HTMLElement)) return false;
  return (
    el.isContentEditable ||
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT"
  );
};

/**
 * An example query built from this snapshot's own vocabulary: the highest severity that actually
 * has findings, and a host whose routing table we actually hold.
 */
export function exampleQuery(): string {
  const counts = severityCounts(fabric.findings);
  const sev = SEVERITY_ORDER.find((s) => (counts[s] ?? 0) > 0) ?? null;
  const host = fabric.coverage.routableHosts[0] ?? fabric.devices[0]?.host ?? null;
  const parts = [sev === null ? null : `severity:${sev}`, host === null ? null : `host:${host}`];
  const built = parts.filter((p): p is string => p !== null).join(" ");
  return built === "" ? "is:uncollected" : built;
}

/* ── the brand mark ────────────────────────────────────────────────────────── */

/** Three tiers and the link that crosses them: the product's own subject, at 16 units. */
function Mark(): ReactElement {
  return (
    <svg viewBox="0 0 16 16" width="1.125rem" height="1.125rem" aria-hidden="true" focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <path d="M2.4 3.4h11.2M4.4 8h7.2M6.4 12.6h3.2" />
      </g>
      <circle cx="8" cy="8" r="1.9" fill="currentColor" />
    </svg>
  );
}

/* ── snapshot identity ─────────────────────────────────────────────────────── */

function SnapshotIdentity({ compact }: { compact: boolean }): ReactElement {
  const m = fabric.meta;
  const file = m.source.split("/").pop() ?? m.source;
  const sha8 = m.sourceSha256.slice(0, 8);

  return (
    <Popover
      label="Snapshot provenance"
      align="start"
      trigger={
        <button type="button" className="hdr-snap" title={`${m.source} — sha256 (${m.sourceDigestForm}) ${m.sourceSha256}`}>
          <span className="hdr-snap__line1">
            <span className="hdr-snap__file">{compact ? sha8 : file}</span>
          </span>
          <span className="hdr-snap__line2">
            {compact ? null : (
              <>
                <span className="hdr-snap__schema">
                  {orNotObserved(m.schema, (s) => s, { what: "schema", compact: true })}
                </span>
                <span className="hdr-snap__dot" aria-hidden="true">
                  ·
                </span>
                <code className="hdr-snap__sha">{sha8}</code>
                <span className="hdr-snap__dot" aria-hidden="true">
                  ·
                </span>
              </>
            )}
            <span className="hdr-snap__when">
              {m.collectedAt === null ? (
                <NotObserved what="collection time" compact />
              ) : (
                <>
                  <span className="hdr-snap__key">collected</span>{" "}
                  <time dateTime={m.collectedAt}>{m.collectedAt.slice(0, 10)}</time>
                </>
              )}
            </span>
          </span>
        </button>
      }
    >
      <div className="snapdetail">
        <h2 className="snapdetail__title">Snapshot provenance</h2>
        <dl className="snapdetail__list">
          <div className="snapdetail__row">
            <dt>Source</dt>
            <dd>
              <code>{m.source}</code>
            </dd>
          </div>
          <div className="snapdetail__row">
            <dt>sha256</dt>
            <dd>
              <Copyable value={m.sourceSha256} label="the snapshot sha256" digest />
            </dd>
          </div>
          <div className="snapdetail__row">
            <dt>Size</dt>
            <dd>{`${groupDigits(m.sourceBytes)} bytes (LF-normalised)`}</dd>
          </div>
          <div className="snapdetail__row">
            <dt>Schema</dt>
            <dd>{orNotObserved(m.schema, (s) => <code>{s}</code>, { what: "schema" })}</dd>
          </div>
          <div className="snapdetail__row">
            <dt>Engine</dt>
            <dd>
              {orNotObserved(m.scriptVersion, (s) => <code>{s}</code>, { what: "engine version" })}
            </dd>
          </div>
          <div className="snapdetail__row">
            <dt>Collected</dt>
            <dd>
              {orNotObserved(m.collectedAt, (s) => <time dateTime={s}>{s}</time>, {
                what: "collection time",
              })}
            </dd>
          </div>
          <div className="snapdetail__row">
            <dt>Compiled</dt>
            <dd>
              {orNotObserved(m.generatedAt, (s) => <time dateTime={s}>{s}</time>, {
                what: "compile time",
              })}
            </dd>
          </div>
        </dl>
        <p className="snapdetail__note">
          Every figure in this application is read from this file. It is a frozen collection, not a
          live view of the network: nothing here reflects a change made after the collection time
          above. The sha256 and size are taken over the file's LF-normalised form (every CR LF read
          as LF, the form Git stores), so they are the same on a Windows and a Linux checkout.
        </p>
      </div>
    </Popover>
  );
}

/* ── keyboard reference ────────────────────────────────────────────────────── */


/* ── the header ────────────────────────────────────────────────────────────── */

export interface HeaderProps {
  /**
   * Bindings installed by other surfaces, merged into the keyboard reference. Pass only what is
   * genuinely wired: this overlay is read by someone who is already stuck.
   */
  /** Called when the query is submitted, for a shell that owns its own run semantics. */
  onSubmitQuery?: (query: string) => void;
}

export function Header({ onSubmitQuery }: HeaderProps): ReactElement {
  const compact = useCompact();
  const query = useInvestigation((s) => s.query);
  const surface = useInvestigation((s) => s.surface);
  const trace = useInvestigation((s) => s.trace);
  const setQuery = useInvestigation((s) => s.setQuery);
  const setSurface = useInvestigation((s) => s.setSurface);

  const inputRef = useRef<HTMLInputElement>(null);
  const focusReturn = useRef<ReturnRecord | null>(null);
  const [notice, setNotice] = useState("");
  const queryId = useId();
  const hintId = `${queryId}-hint`;

  const example = useMemo(() => exampleQuery(), []);

  /* ── the echo is synchronous, the filter is debounced (design brief §8.2 journey 3) ──────────
     This input used to write the SHARED store on every keystroke, so each character re-rendered
     every subscriber and re-aimed the fabric's emphasis — a scene animation per keystroke — inside
     the typing burst. MEASURED 2026-09-21 on the release build (scripted 'core' + 4 x Backspace at
     150 ms, CPU profile): ~1.0 s of fabric render per 32 keystrokes on the main thread, keydown
     p95 304 ms, and acceptance review saw 106-240 ms on-path tasks on the SECOND and later
     characters and on Backspace. The brief says the echo and the recompute "must never be
     coupled"; the queue's own filter field already honoured that, this one did not.
     So the field echoes a local draft in the keystroke's own frame, and the store — the filter, the
     fabric emphasis, the URL — takes the text once typing pauses for QUERY_DEBOUNCE_MS. Submit and
     Clear flush immediately: an explicit action never waits on a timer. */
  const [draft, setDraft] = useState(query);
  const pushed = useRef(query);
  useEffect(() => {
    /* An external write (palette, a removed chip, URL hydrate) wins over the draft. */
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
    }, QUERY_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [draft, setQuery]);
  const commitQuery = useCallback(
    (text: string) => {
      pushed.current = text;
      setDraft(text);
      setQuery(text);
    },
    [setQuery],
  );

  /* Bound by the frame, not by the control: at narrow viewports the theme control lives inside a
     popover that only exists while it is open, and a shortcut that disappears with its button is
     a shortcut the keyboard user has lost. */
  useThemeShortcut();

  const focusQuery = useCallback(() => {
    const el = inputRef.current;
    focusReturn.current = recordReturn(document.activeElement, el);
    el?.focus();
    /* Selecting the existing text makes the fast path — replace the question — one keystroke,
       while Home/End still leave it editable for the slow path. */
    el?.select();
  }, []);


  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.defaultPrevented) return;
      if (isTypingTarget(e.target)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        /* Deliberately NOT capture-phase. The command palette owns this key by the design brief;
           if it is mounted it handles the event and marks it, and the guard at the top of this
           handler stands down. Focusing the query bar is the fallback for a build where the
           palette is not present, so the key never does nothing. */
        e.preventDefault();
        focusQuery();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusQuery]);

  const copyLink = useCallback(() => {
    const s = useInvestigation.getState();
    const params = encodeInvestigation(s);
    const base = `${window.location.origin}${window.location.pathname}`;
    const url = params === "" ? base : `${base}?${params}`;
    const write = navigator.clipboard?.writeText?.(url);
    if (!write) {
      setNotice("This browser did not allow the link to be copied. Copy it from the address bar.");
      return;
    }
    write.then(
      () => setNotice("Investigation link copied. It carries the query, the selection and the flow."),
      () => setNotice("This browser did not allow the link to be copied. Copy it from the address bar."),
    );
  }, []);

  const surfaceToolbar = (
    <Toolbar label="Surface" className="hdr-surfaces">
      {SURFACES.map((s) => {
        const active = s.id === surface;
        const hops = s.id === "path" && trace !== null ? trace.hops.length : null;
        return (
          <button
            key={s.id}
            type="button"
            className="hdr-surface"
            aria-pressed={active}
            title={s.hint}
            onClick={() => setSurface(s.id)}
          >
            <span className="hdr-surface__label">{s.label}</span>
            {hops === null ? null : (
              <span className="hdr-surface__count">
                {hops}
                <span className="visually-hidden">{` hop${hops === 1 ? "" : "s"} in the current trace`}</span>
              </span>
            )}
          </button>
        );
      })}
    </Toolbar>
  );

  const utilities = (
    <>
      <ThemeToggle />
      <IconButton
        label="Keyboard reference"
        icon={<IconCommand />}
        onClick={() => setHelpOpen(true)}
        className="hdr-util"
      />
      <IconButton
        label="Copy the link to this investigation"
        icon={<IconCopy />}
        onClick={copyLink}
        className="hdr-util"
      />
    </>
  );

  return (
    <header id="app-header" className="app__header hdr" data-compact={compact || undefined}>
      <p className="hdr-brand">
        <span className="hdr-brand__mark">
          <Mark />
        </span>
        <span className="hdr-brand__name">Atlas Scope</span>
      </p>

      <SnapshotIdentity compact={compact} />

      <form
        className="hdr-query"
        role="search"
        aria-label="Investigation query"
        onSubmit={(e) => {
          e.preventDefault();
          commitQuery(draft);
          onSubmitQuery?.(draft);
          setSurface("findings");
        }}
      >
        <label className="visually-hidden" htmlFor={queryId}>
          Search findings, devices and links
        </label>
        <IconSearch className="hdr-query__glyph" />
        <input
          ref={inputRef}
          id={queryId}
          type="text"
          className="hdr-query__input"
          value={draft}
          autoComplete="off"
          spellCheck={false}
          aria-describedby={hintId}
          placeholder={`Search or filter — try ${example}`}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={(e) => {
            /* Record where focus came FROM, here rather than in whatever moved it.
               This used to be set by Header's own `/` handler, so Escape only returned focus when
               the reader had arrived by that one key. `/` is now the `query.focus` capability,
               which focuses this input directly — and Escape had nowhere to go back to. Recording
               on focus covers every entry path there is: the key, the command palette, a click on
               the search icon, a screen reader moving through the header. */
            focusReturn.current = recordReturn(e.relatedTarget, e.currentTarget);
          }}
          onKeyDown={(e) => {
            if (e.key !== "Escape") return;
            /* Esc leaves the input and puts focus back where it came from, rather than clearing
               the query: losing a typed question to a stray keystroke is unrecoverable, while
               clearing it has its own button one tab away. */
            e.preventDefault();
            /* The return target can have unmounted since it was recorded (a popover's own
               control, when Tab closed the popover on the way here). `returnFocus` then goes to
               whatever OPENED that surface, and failing that to this search region — never to
               <body>, which is where the `blur()` this replaced put it (acceptance D3). */
            const back = focusReturn.current;
            focusReturn.current = null;
            returnFocus(back, e.currentTarget);
          }}
        />
        <span id={hintId} className="visually-hidden">
          {`Filter with key colon value — severity, host, role, band, category, is and has. Free text searches identifiers and titles. Example: ${example}.`}
        </span>
        {draft === "" ? (
          <Kbd>/</Kbd>
        ) : (
          <IconButton
            label="Clear the query"
            icon={<IconClose />}
            size="sm"
            onClick={() => {
              commitQuery("");
              inputRef.current?.focus();
            }}
          />
        )}
      </form>

      {compact ? (
        <Popover
          label="More controls"
          align="end"
          trigger={
            <button type="button" className="hdr-more">
              More
            </button>
          }
        >
          <div className="hdr-more__panel">
            {surfaceToolbar}
            <div className="hdr-more__utils">
              <ThemeToggle />
              <IconButton
                label="Keyboard reference"
                icon={<IconCommand />}
                showLabel
                onClick={() => setHelpOpen(true)}
              />
              <IconButton
                label="Copy the link to this investigation"
                icon={<IconCopy />}
                showLabel
                onClick={copyLink}
              />
            </div>
          </div>
        </Popover>
      ) : (
        <>
          {surfaceToolbar}
          {utilities}
        </>
      )}

      <LiveRegion message={notice} />
    </header>
  );
}
