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
 * WITH its reason rather than hidden; and every evidence row says, in words, why it matched. A row
 * prints no citation: it is one option whose activation SELECTS (a device, a finding, a host), so a
 * record path printed on it would be a citation that choosing the row does not open (B6). The
 * record stays one step away — on the pane the row lands on, as a working citation.
 *
 * Responsiveness (design brief 8.2, journey 5): the search index is built once and memoised inside
 * `rankedSearch`, so opening is a mount over an existing index; the per-keystroke work runs against
 * a DEFERRED value, so the character echoes in the same frame and the list catches up in the next.
 * Measured numbers are in CommandPalette.test.tsx.
 */
import {
  memo,
  startTransition,
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

import { flushSync } from "react-dom";
import { presentBand } from "../core/band-qualification";
import { deviceById, fabric, findingById } from "../core/data";
import { applyToFindings, parseQuery, rankedSearch, type SearchHit } from "../core/query";
import { useInvestigation } from "../core/store";
import { useSceneStats } from "../fabric3d/telemetry";
import { IconArrowRight, IconSearch } from "../ui/icons";
import { Band, coverageFigures, Dialog, Kbd, LiveRegion, NotObserved, SeverityBadge } from "../ui/primitives";
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
import { returnFocus } from "./focus-return";
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
  /**
   * The band of the forwarding verdict `detail` states, when it states one (ClaimCard
   * `verdictStatement`). Such a detail is drawn WHOLE: the two-line clamp every other hint gets
   * would cut a verdict after its word and before its scope and caveat count (acceptance B2).
   */
  verdictBand?: string;
  /* No `cite`. A row is one role=option whose activation runs `run`, and no row's `run` opens a
     record: a citation printed on it (the "Source record" chip it used to carry) was one the reader
     could see and not open, and an option may not hold a control to open it with. */
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

function commandRow(c: Command, close: Close): Row {
  const a = commandAvailability(c);
  return {
    key: `command:${c.id}`,
    label: <span className="palette__text">{c.title}</span>,
    text: c.shortcut ? `${c.title}, ${shortcutText(c.shortcut)}` : c.title,
    ...(c.shortcut === undefined ? {} : { meta: <ShortcutKeys keys={c.shortcut} /> }),
    /* The reason REPLACES the detail when the command cannot act, so the second line always
       answers the question the user is about to ask. */
    ...(a.ok ? (c.detail ? { detail: c.detail } : {}) : { detail: a.reason }),
    ...(a.ok && c.detail && c.verdict ? { verdictBand: c.verdict.band } : {}),
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
        band <Band band={presentBand(d)} />
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

/** Where focus goes when the palette closes and there was NO invoking element to return to. `tick`
 *  counts the attempts, so a landing can wait for its preferred target before settling for less. */
type Landing = (tick: number) => HTMLElement | null;
type Close = (landing?: Landing) => void;

/* A palette opened from a fresh load has no invoker: focus sat on <body>. Returning it there
   (measured, A11Y critic D3: Ctrl+K, F099, Enter left focus on BODY at 100-4000 ms, so the next Tab
   restarted at the skip link) throws away the place the user just asked to go. */

const LANDING_TICKS = 20;
const LANDING_TICK_MS = 50;

const visible = (el: HTMLElement | null | undefined): el is HTMLElement =>
  el !== null && el !== undefined && el.isConnected && el.getClientRects().length > 0;

/** The main stage — programmatically focusable, and always present. */
const stageLanding: Landing = () => document.getElementById("stage");

/** After a finding selection: the queue's newly current row (its roving cell — the grid moves it
 *  on an external selection); if no visible row shows the finding after half the wait (filtered
 *  out, or the queue is not on screen), the evidence title that shows it; then the stage. */
const activeFindingLanding: Landing = (tick) => {
  for (const row of document.querySelectorAll<HTMLElement>('[role="grid"] [role="row"][aria-current="true"]')) {
    const roving = row.querySelector<HTMLElement>('[tabindex="0"]');
    if (visible(roving)) return roving;
  }
  if (tick < LANDING_TICKS / 2) return null;
  const title = [...document.querySelectorAll<HTMLElement>('section[aria-label="Evidence chain"] h2')].find(visible);
  if (title) {
    if (!title.hasAttribute("tabindex")) title.tabIndex = -1;
    return title;
  }
  return tick >= LANDING_TICKS - 1 ? stageLanding(tick) : null;
};

/** Waits for the selection to commit and reveal (a paged-in row mounts a render or two later), and
 *  lands focus only while nothing else has taken it. Bounded (~1 s). Timers, not animation frames:
 *  frames are throttled to zero in a hidden or occluded document. */
function landFocus(find: Landing): void {
  let tick = 0;
  const step = (): void => {
    const a = document.activeElement;
    if (a !== null && a !== document.body) return;
    const el = find(tick);
    if (el && returnFocus(el, null) === el) return;
    tick += 1;
    if (tick < LANDING_TICKS) setTimeout(step, LANDING_TICK_MS);
  };
  setTimeout(step, 0);
}

/** What a hit is, as a reader would name it. */
const KIND_NOUN: Readonly<Record<SearchHit["kind"], string>> = {
  device: "device",
  finding: "finding",
  "cross-layer": "cross-layer finding",
  interface: "interface",
  endpoint: "endpoint",
};

/** The indexed field names (`rankedSearch`'s `field`) in words. TOTAL over the fields query.ts
 *  indexes: CommandPalette.test.tsx reads every `iv`/`ivList` field literal there and fails on one
 *  missing here. A field it still does not know (a future index entry) is printed as what it is, an
 *  identifier — see `MatchReason`. */
export const FIELD_WORDS: Readonly<Record<string, string>> = {
  host: "host name",
  id: "identifier",
  model: "model",
  serial: "serial number",
  software: "software version",
  role: "role",
  kind: "kind",
  platform: "platform",
  deductions: "health deductions",
  impact: "impact",
  devices: "device list",
  category: "category",
  severity: "severity",
  title: "title",
  detail: "detail",
  remediation: "remediation",
  hosts: "host list",
  layers: "layers",
  recommendation: "recommendation",
  port: "port",
  "host+port": "host and port",
  description: "description",
  portChannel: "port-channel",
  status: "status",
  ip: "IP address",
  mac: "MAC address",
  vlan: "VLAN",
  class: "endpoint class",
  vendor: "vendor",
  evidence: "evidence basis",
};

/**
 * Why this row is a hit, in words — "matched this endpoint's IP address". It replaces the record
 * path the row used to print (see `Row`): the reader keeps the reason, and the record itself is one
 * step away on the pane the row lands on.
 */
export function MatchReason({ hit }: { hit: SearchHit }): ReactNode {
  const words = FIELD_WORDS[hit.field];
  return (
    <span className="palette__matched">
      matched this {KIND_NOUN[hit.kind]}'s{" "}
      {words !== undefined ? (
        <span className="palette__matched-field">{words}</span>
      ) : (
        /* An identifier, not prose: in a <code>, which primitives.css ("wrapping") gives
           `overflow-wrap: normal`, with a <wbr> after each separator so a long name breaks at a
           boundary a reader accepts and never between two letters. The sentence itself carries no
           token-break licence (C2, wave 8). */
        <code className="palette__matched-field palette__matched-id">{fieldBreaks(hit.field)}</code>
      )}
    </span>
  );
}

/** `text` with a <wbr> after every identifier separator (`.` `_` `/` `-` `:` `+`); text is unchanged. */
function fieldBreaks(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let run = "";
  for (const ch of text) {
    run += ch;
    if ("._/-:+".includes(ch)) {
      out.push(run, <wbr key={out.length} />);
      run = "";
    }
  }
  if (run !== "") out.push(run);
  return out;
}

function hitRow(hit: SearchHit, close: Close): Row {
  const base = {
    key: `hit:${hit.kind}:${hit.id}:${hit.cite}`,
    meta: <MatchReason hit={hit} />,
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
        close(hit.kind === "finding" ? activeFindingLanding : undefined);
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
     on the row, rather than appearing to select a record the rest of the app cannot hold — and it
     opens the host's Ports tab, the one evidence tab that lists both kinds of record, each with its
     working citation. That is what keeps the record one step away once the row prints no path. */
  const host = hit.host;
  return {
    ...base,
    label: (
      <span className="palette__title">
        <span className="palette__mono">{hit.label}</span>
        {host === null ? null : (
          <span className="palette__action">
            <IconArrowRight className="palette__action-glyph" /> select {host}, Ports tab
          </span>
        )}
      </span>
    ),
    text: `${hit.label}${host === null ? "" : `, selects ${host} and opens its Ports tab`}`,
    detail: hit.detail ?? <NotObserved what="description" compact />,
    disabledReason:
      host === null ? "This record names no host, so there is nothing to select from it." : null,
    run: () => {
      if (host === null) {
        announce("That record names no host, so there is nothing to select from it.");
        return;
      }
      close();
      const store = useInvestigation.getState();
      store.selectDevice(host, { surface: "fabric" });
      store.setEvidenceTab("ports");
      announce(`Selected ${host}, on its Ports tab, where this ${KIND_NOUN[hit.kind]} record is cited.`);
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
  live,
  onHover,
  onRun,
}: {
  row: Row;
  id: string;
  index: number;
  isActive: boolean;
  /** False while the palette is only pre-warming: the row is drawn but exposes no option. */
  live: boolean;
  onHover: (i: number) => void;
  onRun: (r: Row) => void;
}): ReactNode {
  const disabled = typeof row.disabledReason === "string";
  return (
    <div
      id={id}
      {...(live ? { role: "option", "aria-selected": isActive } : {})}
      {...(live && disabled ? { "aria-disabled": true } : {})}
      {...(isActive ? { "data-active": "true" } : {})}
      className="palette__row"
      onMouseEnter={() => onHover(index)}
      onClick={() => onRun(row)}
    >
      <span className="palette__row-main">
        <span className="palette__row-label">{row.label}</span>
        {row.detail === undefined || row.detail === null ? null : (
          <span className="palette__row-detail" {...(row.verdictBand === undefined ? {} : { "data-verdict-band": row.verdictBand })}>
            {row.detail}
          </span>
        )}
      </span>
      <span className="palette__row-side">{row.meta ?? null}</span>
    </div>
  );
});

/* ══ the pre-warm (acceptance E2/E3: the first Ctrl+K after load) ══════════
   MEASURED (release build, fresh headed browser per trial, 1280x800, 2026-09-26): the FIRST Ctrl+K
   after load had worst-interaction p95 320 ms and ran `#document.onkeydown` as a 51-83 ms long task;
   every later open was warm (p95 64). Two first-time costs, measured apart:
     - main thread: React built the palette's DOM from nothing inside the keydown (8-17 ms, much of
       it `grammarExamples()` tracing its flows), then `focus()` forced the first style and layout of
       that subtree (24-51 ms cold, 5-9 warm);
     - GPU: the palette's paint operations needed six Skia programs compiled on first raster
       (~120 ms of shader compile and link), and the open's frame waited behind them.
   So the palette's own frame is rendered ONCE in advance — after the scene has converged (the one
   period nothing else is competing for the GPU), in idle time, in a transition — invisibly but
   really rasterised ("raster": opacity 0.001) for a few presented frames, and then PARKED
   (`visibility: hidden`: painting nothing, its boxes kept) until the first real open, which turns
   those same, already styled and laid-out nodes into the dialog by flipping attributes: the first
   Ctrl+K creates no DOM and forces no first layout (owner decision, cluster E2E3, 2026-09-26; the
   first repair removed the frame after the raster, and the first open still built and laid out the
   subtree inside the keydown — measured 36-46 ms of forced style/layout on a loaded host). Parking
   ends at that first open: a closed palette renders nothing again, exactly as before, so every later
   open is the ordinary warm one. While parked, the frame's rows are FROZEN (they are not recomputed
   when the set of command owners changes), so it adds no render work to any other interaction.
   `Dialog`'s `prewarm` owns what that frame may not do (no focus, no trap, no inert page, no dialog
   role, hidden and inert itself); this component withholds every combobox/listbox/option/group role
   and its live region while it is only pre-warming, so the warm frame exposes nothing to a harness
   either.

   The state is published on `<html data-palette-warm>` for the harnesses and captures (a capture
   taken while the 0.001-opacity frame is up could differ by one colour step):
     waiting     — mounted, the scene has not settled yet;
     scheduled   — the idle slices are queued;
     mounted     — the frame is in the document, being rasterised;
     done        — it was held for WARM_HOLD_FRAMES presented frames AND at least WARM_MIN_HOLD_MS, and
                   is now parked (paints nothing);
     unpresented — no frame was presented within WARM_UNPRESENTED_MS (an occluded or minimised
                   window), so it was parked without having been rasterised;
     superseded  — a real open came before the frame was parked; that open paid what was left.
   A Ctrl+K pressed before the pre-warm has run is still a cold open; that window is the cold-load
   audit's (acceptance E5), and `review/measure-inp.mjs` reports it apart. */

type WarmState = "waiting" | "scheduled" | "mounted" | "done" | "unpresented" | "superseded";

function markWarm(state: WarmState): void {
  if (typeof document !== "undefined") document.documentElement.dataset.paletteWarm = state;
}

/** Presented frames the pre-warm is held for: more than one, so the first frame's raster is flushed. */
const WARM_HOLD_FRAMES = 3;
/**
 * ...and for at least this long. Frames alone are not a bound on the GPU: measured (release build,
 * 2026-09-26), three rAF callbacks after the mount completed within 13-63 ms, while the first raster's
 * program compile the frame exists to trigger was measured at ~120 ms. A frame parked before its raster
 * work ran could leave that compile to the first open. Parking costs nothing, so the drawn phase is
 * held long enough for the compile to have run; the harnesses wait for the terminal state anyway.
 */
const WARM_MIN_HOLD_MS = 250;
/** The pre-warm is never left drawn longer than this, presented or not: then it is parked. */
const WARM_UNPRESENTED_MS = 1000;
/** Idle callbacks run by this deadline even on a page that is never idle. */
const WARM_IDLE_TIMEOUT_MS = 4000;
/** Without requestIdleCallback (Safari), the gap between slices. */
const WARM_IDLE_FALLBACK_MS = 50;
/** A scene that never reports convergence (no WebGL, never settles) does not keep the palette cold. */
const WARM_SETTLE_CEILING_MS = 10000;

type IdleWindow = Window & {
  requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number;
  cancelIdleCallback?: (id: number) => void;
};

/** Run `fn` when the page is idle, at the latest after `timeout`. Returns the cancel. */
function whenIdle(fn: () => void, timeout: number, fallbackMs: number): () => void {
  const w = window as IdleWindow;
  if (typeof w.requestIdleCallback === "function") {
    const id = w.requestIdleCallback(fn, { timeout });
    return () => w.cancelIdleCallback?.(id);
  }
  const t = setTimeout(fn, fallbackMs);
  return () => clearTimeout(t);
}

/** Each step in its OWN idle slice, in order — so no one slice is a long task. Returns the cancel. */
function idleSteps(steps: readonly (() => void)[], timeout: number, fallbackMs: number): () => void {
  let cancel: () => void = () => {};
  let next = 0;
  const run = (): void => {
    if (next >= steps.length) return;
    cancel = whenIdle(
      () => {
        const step = steps[next];
        next += 1;
        step?.();
        run();
      },
      timeout,
      fallbackMs,
    );
  };
  run();
  return () => cancel();
}

/**
 * Reports once the scene has converged (or after a ceiling, when it never does). A component of
 * its own so that only it re-renders on a telemetry notification — the same reason `App` isolates
 * its subscriber — and it is unmounted once the pre-warm no longer needs it.
 */
function SceneSettledGate({ onSettled }: { onSettled: () => void }): null {
  const converged = useSceneStats()?.converged === true;
  useEffect(() => {
    if (converged) onSettled();
  }, [converged, onSettled]);
  useEffect(() => {
    const t = setTimeout(onSettled, WARM_SETTLE_CEILING_MS);
    return () => clearTimeout(t);
  }, [onSettled]);
  return null;
}

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
  /** An Enter pressed while `term` lagged `input`: the input text it was pressed on. */
  const pendingEnterRef = useRef<string | null>(null);

  const close = useCallback<Close>((landing) => {
    /* Synchronous unmount: while the dialog is mounted the page behind it is `inert` (acceptance
       D3) and refuses focus, so the focus return below — and a command run straight after, such as
       "Go to the queue" — would otherwise land on an element that cannot take it. */
    flushSync(() => setPaletteOpen(false));
    /* The store carries the exact invoking element (design brief 7.4 rule 4). Dialog restores too,
       but it restores to whatever was active when it mounted; this is the explicit target. */
    const back = focusReturn;
    if (returnFocus(back === document.body ? null : back, null) === null) landFocus(landing ?? stageLanding);
  }, [setPaletteOpen, focusReturn]);

  useEffect(() => {
    if (!open) return;
    /* Read-once: a seed that survived its opening would re-apply on the next, unrelated open. */
    const seed = consumePaletteSeed();
    pendingEnterRef.current = null;
    setInput(seed ?? "");
    setActive(0);
  }, [open]);

  /* ...and pays for the command list, the grammar examples (each one TRACED), the scope line and the
     dialog's coverage line once the page is IDLE, each in its own slice, so neither the first open
     nor the pre-warm's render reads the dataset (CommandPalette.test.tsx counts those reads). The
     idle callback runs only when no input is pending; the timeout is a floor, not a schedule. */
  useEffect(
    () =>
      idleSteps(
        [() => void allCommands(), () => void grammarExamples(), () => void searchScope(), () => void coverageFigures()],
        15000,
        5000,
      ),
    [],
  );

  /* The pre-warm (see the block above `SceneSettledGate`). */
  const [sceneSettled, setSceneSettled] = useState(false);
  /** The pre-warm frame while the palette is closed: none, being rasterised, or parked. */
  const [frame, setFrame] = useState<"none" | "raster" | "parked">("none");
  const warmPhase = useRef<"pending" | "scheduled" | "mounted" | "parked" | "finished">("pending");
  const cancelWarm = useRef<() => void>(() => {});
  const onSceneSettled = useCallback(() => setSceneSettled(true), []);
  const rastering = frame === "raster" && !open;
  /** The frame is in the document (rasterising or parked): its rows are drawn while closed. */
  const drawn = frame !== "none";

  useEffect(() => {
    if (warmPhase.current === "pending") markWarm("waiting");
  }, []);

  /* The first real open ends the pre-warm at any stage. Before the frame was parked it supersedes it
     (that open paid what was left); a parked frame has already become this open's dialog, and after
     it closes the palette renders nothing again. */
  useEffect(() => {
    if (!open) return;
    const phase = warmPhase.current;
    if (phase === "finished") return;
    warmPhase.current = "finished";
    cancelWarm.current();
    if (phase !== "parked") markWarm("superseded");
    setFrame("none");
  }, [open]);

  useEffect(() => {
    if (!sceneSettled || warmPhase.current !== "pending") return;
    warmPhase.current = "scheduled";
    markWarm("scheduled");
    const cancel = idleSteps(
      [
        () => void allCommands(),
        () => void grammarExamples(),
        () => void searchScope(),
        /* The dialog's own coverage line (read once; it filters the RIB coverage). */
        () => void coverageFigures(),
        () => {
          if (warmPhase.current === "scheduled") startTransition(() => setFrame("raster"));
        },
      ],
      WARM_IDLE_TIMEOUT_MS,
      WARM_IDLE_FALLBACK_MS,
    );
    cancelWarm.current = cancel;
    return () => {
      cancel();
      /* A cleanup that is not the end of the pre-warm (StrictMode's re-run) leaves it pending. */
      if (warmPhase.current === "scheduled") warmPhase.current = "pending";
    };
  }, [sceneSettled]);

  useEffect(() => {
    if (!rastering) return;
    warmPhase.current = "mounted";
    markWarm("mounted");
    let raf: number | null = null;
    let done: ReturnType<typeof setTimeout> | null = null;
    let presented = 0;
    /* The minimum hold is its own timer from mount, joined with the last frame: the frame is parked no
       earlier than both. No clock is read (determinism.test.ts), and the moment is the same as
       "after the last frame, the rest of WARM_MIN_HOLD_MS". */
    let held = false;
    let framesDone = false;
    const finish = (state: "done" | "unpresented"): void => {
      if (warmPhase.current !== "mounted") return;
      warmPhase.current = "parked";
      markWarm(state);
      setFrame("parked");
    };
    const bound = setTimeout(() => finish("unpresented"), WARM_UNPRESENTED_MS);
    const hold = setTimeout(() => {
      held = true;
      if (framesDone) finish("done");
    }, WARM_MIN_HOLD_MS);
    const tick = (): void => {
      raf = null;
      presented += 1;
      if (presented < WARM_HOLD_FRAMES) raf = requestAnimationFrame(tick);
      /* After the last frame's callback: that frame is then drawn, and the timer runs after it —
         no earlier than the minimum hold. */ else
        done = setTimeout(() => {
          framesDone = true;
          if (held) finish("done");
        }, 0);
    };
    if (typeof requestAnimationFrame === "function") raf = requestAnimationFrame(tick);
    return () => {
      if (raf !== null && typeof cancelAnimationFrame === "function") cancelAnimationFrame(raf);
      if (done !== null) clearTimeout(done);
      clearTimeout(hold);
      clearTimeout(bound);
      /* Unmounted or opened mid-hold: an effect re-run (StrictMode) must be able to hold again. */
      if (warmPhase.current === "mounted") warmPhase.current = "scheduled";
    };
  }, [rastering]);

  /* Availability is recomputed when the set of mounted owners changes — while OPEN. A closed palette
     (including a parked pre-warm frame) does not follow it: nothing reads those rows, and following
     it would put a recompute and a row re-render into whichever interaction mounted a surface. The
     first open recomputes them anyway (`open` changes). */
  const groupsEpoch = open ? targetEpoch : -1;
  const groups = useMemo<RowGroup[]>(() => {
    void groupsEpoch;
    /* A closed palette lists nothing, so it computes nothing (acceptance E5, cold load). The
       palette is mounted at boot for its keyboard model, and building every command then — every
       suggested flow TRACED — ran inside the first render, where a keystroke cannot interrupt it.
       The one exception is the pre-warm, which draws the EMPTY state — what the first open draws. */
    if (!open && !drawn) return [];
    const q = open ? term.trim() : "";
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
          ...(ex.verdict === undefined ? {} : { verdictBand: ex.verdict.band }),
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

    const result = rankedSearch(searchTerm, { limit: SEARCH_LIMIT });
    const byKind = new Map<SearchHit["kind"], SearchHit[]>();
    for (const h of result.hits) {
      const list = byKind.get(h.kind);
      if (list) list.push(h);
      else byKind.set(h.kind, [h]);
    }
    /* A record the query NAMES exactly (its identity field equals the text) is what the user asked
       for, so its group goes ahead of the commands. Measured before this rule: typing "core2"
       pre-selected "Trace core2 Vlan20 …", and Enter replaced the user's flow, moved the camera
       and collapsed the hop sections instead of selecting the device (acceptance A4). The rule is
       by match class, not a list of kinds or commands, so it holds for every record kind and for
       any command whose title happens to mention the name. */
    const named: RowGroup[] = [];
    const rest: RowGroup[] = [];
    for (const kind of KIND_ORDER) {
      const hits = byKind.get(kind);
      if (!hits || hits.length === 0) continue;
      const shown = hits.slice(0, HITS_PER_KIND);
      (shown.some((h) => h.matchType === "exact-id") ? named : rest).push({
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
    out.push(...named);
    if (matchedCommands.length > 0)
      out.push({ key: "commands", label: "Commands", rows: matchedCommands });
    out.push(...rest);

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
  }, [open, drawn, term, close, groupsEpoch]);

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
          /* The list is derived from the DEFERRED term. Enter pressed straight after typing (a fast
             typist, or a paste then Enter) used to run the stale list's top row — measured:
             "F099" + Enter at once ran "severity:Critical" (A1). When the list has not caught up
             with what is in the box, the Enter is held and runs against the current input's list
             as soon as it commits (the effect below). */
          if (term !== input) {
            e.preventDefault();
            pendingEnterRef.current = input;
            return;
          }
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
    [move, rows, active, input, term],
  );

  /* The held Enter (see "Enter" above): runs once the deferred term equals the text that was in
     the box when Enter was pressed. Any further edit cancels it (onChange), so it never runs a row
     for a query the user has since changed. */
  useEffect(() => {
    const held = pendingEnterRef.current;
    if (held === null || held !== term || term !== input) return;
    pendingEnterRef.current = null;
    rows[active]?.run();
  }, [term, input, rows, active]);

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
    <>
    {sceneSettled ? null : <SceneSettledGate onSettled={onSceneSettled} />}
    <Dialog
      open={open}
      prewarm={open || frame === "none" ? false : frame}
      onClose={() => close()}
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
          autoComplete="off"
          spellCheck={false}
          aria-label="Search commands, devices, findings and paths"
          /* The combobox contract only while OPEN: a pre-warm frame exposes no widget role. */
          {...(open
            ? {
                role: "combobox",
                "aria-expanded": count > 0,
                "aria-controls": listId,
                ...(activeId === undefined ? {} : { "aria-activedescendant": activeId }),
              }
            : {})}
          aria-describedby={`${baseId}-scope`}
          placeholder={`Search a command, a device, a finding ${EM_DASH} or an address pair to trace`}
          value={input}
          onChange={(e) => {
            pendingEnterRef.current = null;
            setInput(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
      </div>

      <div
        className="palette__results"
        id={listId}
        {...(open ? { role: "listbox", "aria-label": "Results" } : {})}
        ref={listRef}
      >
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
              {...(open ? { role: "group", "aria-label": g.note ? `${g.label}, ${g.note}` : g.label } : {})}
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
                    live={open}
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
      {/* The announcement channel exists only while the palette is open: a pre-warm says nothing. */}
      {open ? <LiveRegion message={status} /> : null}
    </Dialog>
    </>
  );
}

export default CommandPalette;
