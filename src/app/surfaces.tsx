/**
 * surfaces.tsx — the regions of the frame, and the routing between them.
 *
 * The brief's architecture (section 2.1) is SIMULTANEOUS, not tabbed: at the reference width the
 * queue, the path panel, the fabric and the evidence rail are all on screen at once, and
 * `InvestigationState.surface` names which of them has emphasis and where a `g`-sequence lands.
 * `commands.ts` encodes the same model — its REGION_SELECTOR maps all four surfaces to four
 * selectors it expects to resolve at the same time. So "routing" here means two things:
 *
 *   - at >= 1024px, moving emphasis and focus between regions that are all mounted, and
 *   - below that, choosing which single region occupies the one available column,
 *
 * and in BOTH cases every region stays mounted. That is acceptance A4: switching surfaces cannot
 * clear a selection or reset the camera, because nothing is unmounted to switch.
 *
 * The 3-D fabric is lazy-loaded (acceptance F4: three.js must not be in the entry chunk) and then
 * kept for the life of the session. Unmounting it would drop the WebGL context, the compiled
 * programs and the camera pose — the reader would come back to a re-framed fabric and would have
 * to find their device again, which is exactly the discontinuity the product exists to avoid.
 *
 * WHAT THAT SPLIT DOES AND DOES NOT BUY, measured rather than assumed (cold load of the built app,
 * every js/css/html response recorded):
 *
 *   - At the reference width the fabric is ON SCREEN by section 2.1, so `Stage` mounts it on the
 *     first commit and the renderer chunk is fetched 191 ms into the first load. The split makes it
 *     a SEPARATE, SEPARATELY-CACHEABLE 797 KB on a second waterfall hop; it does not keep it off
 *     the first load. Any claim that "a user who never opens the fabric never downloads a renderer"
 *     is about the stacked rung only.
 *   - At <= 767px, where the brief collapses the stage, it genuinely is not fetched: 849,042 bytes
 *     on first load instead of 1,767,100. That was NOT true until 2026-09-21 — `App` seeded
 *     `fabricVisible` to `true` and corrected it in an effect, one commit after `Stage` had already
 *     latched. `surfaces.test.tsx` holds it.
 */
import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
  type RefObject,
} from "react";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import type { SurfaceId } from "../core/types";
import { DevicePane } from "../panels/DevicePane";
import { EvidencePane } from "../panels/EvidencePane";
import { Inspector } from "../panels/Inspector";
import { PathTrace } from "../panels/PathTrace";
import { PriorityQueue } from "../panels/PriorityQueue";
import { useSceneStats } from "../fabric3d/telemetry";
import type { SceneStatsEx } from "../fabric3d/scene";
import { ErrorBoundary } from "./ErrorBoundary";
import "./App.css";

/* The three.js + postprocessing chunk. Named so the build output is readable and so a failure to
   split it is visible in the chunk list rather than only in the entry size. */
/* The chunk's module evaluation (three.js + postprocessing, ~0.8 MB) is one uninterruptible task,
   and the scene's creation follows it. Started as soon as the stage first rendered, it landed at
   about 1.2 s into the cold load, where a keystroke then waited 184-216 ms (review/audit-e5-coldload.mjs,
   2026-09-22 critic, E5). So the import is requested only once the browser reports an idle period —
   an idle callback does not run while input is pending — bounded so the fabric is never withheld
   for long. The Suspense fallback (StagePending) says the fabric is loading throughout the wait. */
const FABRIC_IDLE_TIMEOUT_MS = 1200;
function whenInputIdle(): Promise<void> {
  return new Promise((resolve) => {
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number };
    if (typeof w.requestIdleCallback === "function") w.requestIdleCallback(() => resolve(), { timeout: FABRIC_IDLE_TIMEOUT_MS });
    else setTimeout(resolve, 0);
  });
}
const Fabric3D = lazy(() => whenInputIdle().then(() => import("../fabric3d/Fabric3D")));

/* ── viewport ladder (design brief 2.5), read live ─────────────────────────── */

function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      const mq = typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query) : null;
      mq?.addEventListener("change", cb);
      /* `resize` as well as the query's own event, because the two must never disagree: measured
         in this harness, a viewport change applied by the debugger moved the CSS breakpoint
         without delivering a `change` event, so the stylesheet was in single-column mode while
         React still believed it was at the reference width — rails stacked with no control to
         choose between them. Re-reading on resize costs one matchMedia call per resize event and
         removes a whole class of "the layout disagrees with its own stylesheet" defect. */
      window.addEventListener("resize", cb);
      return () => {
        mq?.removeEventListener("change", cb);
        window.removeEventListener("resize", cb);
      };
    },
    [query],
  );
  const get = useCallback(
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false),
    [query],
  );
  return useSyncExternalStore(subscribe, get, () => false);
}

/**
 * The three rungs are mutually exclusive, and each matches a block in shell.css exactly. They are
 * written as disjoint ranges rather than as nested `max-width` thresholds because two rungs true
 * at once is the shape of every layout bug in a ladder: the widest rule wins in CSS and the
 * narrowest in JavaScript, and nothing reports the disagreement.
 */
export interface Ladder {
  /** 1024–1279px: Rail B is an overlay drawer over the stage rather than a column. */
  drawer: boolean;
  /** 768–1023px: one column, and a segmented control chooses which region occupies it. */
  singleColumn: boolean;
  /** <= 767px: every rail is a stacked full-width section and the fabric is behind a toggle. */
  stacked: boolean;
}

export function useLadder(): Ladder {
  const drawer = useMediaQuery("(min-width: 64rem) and (max-width: 79.9375rem)");
  const singleColumn = useMediaQuery("(min-width: 48rem) and (max-width: 63.9375rem)");
  const stacked = useMediaQuery("(max-width: 47.9375rem)");
  return { drawer, singleColumn, stacked };
}

/* ── which single region owns the column below 1024px ──────────────────────── */

export type PaneId = "queue" | "path" | "evidence";

/** The fabric is not in this list: below 1024px it is the stage, which sits above the pane. */
const PANE_OF_SURFACE: Readonly<Record<SurfaceId, PaneId>> = {
  fabric: "queue",
  findings: "queue",
  path: "path",
  evidence: "evidence",
};

export const paneForSurface = (s: SurfaceId): PaneId => PANE_OF_SURFACE[s];

/* ── Rail A: the path panel over the queue, with a keyboard-operable splitter ── */

const SPLIT_KEY = "atlas-scope.railSplit";
const SPLIT_DEFAULT = 60;
const SPLIT_MIN = 30;
const SPLIT_MAX = 80;
const SPLIT_STEP = 2;
/** A coarse step for PageUp/PageDown, so crossing the whole range is a few keys, not twenty-five. */
const SPLIT_PAGE = 10;

const clampSplit = (v: number): number => Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, Math.round(v)));

function readSplit(): number {
  try {
    const raw = window.localStorage.getItem(SPLIT_KEY);
    const n = raw === null ? Number.NaN : Number(raw);
    return Number.isFinite(n) ? clampSplit(n) : SPLIT_DEFAULT;
  } catch {
    /* A browser set to block site data throws on access rather than returning null. The split is
       a preference; losing it costs one drag, so it is not worth failing the render over. */
    return SPLIT_DEFAULT;
  }
}

function writeSplit(v: number): void {
  try {
    window.localStorage.setItem(SPLIT_KEY, String(v));
  } catch {
    /* See readSplit. */
  }
}

interface SplitterProps {
  value: number;
  onChange: (v: number) => void;
  /** The element the fraction is measured against, so a drag maps pointer travel to a percentage. */
  railRef: RefObject<HTMLElement | null>;
}

/**
 * WCAG 2.5.7 (Dragging Movements) requires a single-pointer alternative to every drag, not the
 * removal of the drag. So this is a real `separator` widget: arrows and PageUp/PageDown move it,
 * Home/End reach the limits, double-click resets, and the pointer drag remains as the fast path.
 */
function Splitter({ value, onChange, railRef }: SplitterProps): ReactElement {
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    const rail = railRef.current;
    if (rail === null || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const rect = rail.getBoundingClientRect();
    if (rect.height <= 0) return;

    const move = (ev: PointerEvent): void => {
      onChange(clampSplit(((ev.clientY - rect.top) / rect.height) * 100));
    };
    const up = (ev: PointerEvent): void => {
      e.currentTarget.releasePointerCapture?.(ev.pointerId);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    const delta =
      e.key === "ArrowUp" || e.key === "ArrowLeft"
        ? -SPLIT_STEP
        : e.key === "ArrowDown" || e.key === "ArrowRight"
          ? SPLIT_STEP
          : e.key === "PageUp"
            ? -SPLIT_PAGE
            : e.key === "PageDown"
              ? SPLIT_PAGE
              : 0;
    if (delta !== 0) {
      e.preventDefault();
      onChange(clampSplit(value + delta));
      return;
    }
    if (e.key === "Home") {
      e.preventDefault();
      onChange(SPLIT_MIN);
    } else if (e.key === "End") {
      e.preventDefault();
      onChange(SPLIT_MAX);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onChange(SPLIT_DEFAULT);
    }
  };

  return (
    <div
      className="splitter"
      role="separator"
      tabIndex={0}
      aria-orientation="horizontal"
      aria-label="Height given to the path panel"
      aria-valuenow={value}
      aria-valuemin={SPLIT_MIN}
      aria-valuemax={SPLIT_MAX}
      aria-valuetext={`Path panel takes ${value} percent of the rail`}
      onPointerDown={onPointerDown}
      onDoubleClick={() => onChange(SPLIT_DEFAULT)}
      onKeyDown={onKeyDown}
    />
  );
}

export interface RailAProps {
  /** Hidden rather than unmounted below 1024px, so its scroll position and filters survive. */
  hidden?: boolean;
  onOpenCite: (cite: string) => void;
}

/**
 * `#rail-path` is present when a flow is being investigated OR when the reader has asked for the
 * path surface, and is ABSENT from the DOM otherwise. `#rail-queue` is always present.
 *
 * The brief's rule (2.2) is that a panel saying "no path yet" is chrome, while a panel that appears
 * when the question is asked is an answer. Gating purely on `flow !== null` read that rule as "a
 * flow exists", which is a different test and it closed the only door into the product's central
 * feature: pressing the header's Path control — whose own description is "a forwarding question and
 * its hop-by-hop answer" — set ?s=path, marked itself selected, and changed NOTHING on screen at
 * 1600, 1280 or 900px wide. A first-time reader who could not guess the syntax
 * "10.0.10.50 -> 10.0.30.10:443 tcp" could not reach the trace engine at all.
 *
 * Pressing Path IS asking the question, so the panel mounted here is not chrome: PathTrace with no
 * trace renders its "Trace a flow" / "Verify an intent" form — source, destination, protocol, port
 * — plus the suggested-flow presets this snapshot can actually answer. That is an answer-shaped
 * affordance, which is exactly what the brief asks for.
 */
export function RailA({ hidden = false, onOpenCite }: RailAProps): ReactElement {
  const flow = useInvestigation((s) => s.flow);
  const surface = useInvestigation((s) => s.surface);
  const railRef = useRef<HTMLElement | null>(null);
  const [split, setSplit] = useState(SPLIT_DEFAULT);

  useEffect(() => {
    setSplit(readSplit());
  }, []);

  const change = useCallback((v: number) => {
    setSplit(v);
    writeSplit(v);
  }, []);

  /* A link whose flow was REFUSED still asked a path question; its refusal is the answer, and it can
     only be read if the panel is there (2026-09-23, B1). */
  const flowRefused = useInvestigation((s) => s.flowRefused);
  const hasPath = flow !== null || flowRefused !== null || surface === "path";

  /* ON THE PATH SURFACE, THE PATH PANEL GETS ITS FORM'S HEIGHT — acceptance C2, 2026-09-23. The
     shell gave the panel only its 10rem floor (the queue's min-content floor is resolved first),
     which at 1440x900 was a 170 px port with Destination, Protocol, Port and "Trace this flow" all
     below it, and at 1920x1080 cut the submit in half. So while the reader is ON the path surface —
     the one they chose — the path track's floor is its flow form's own height: tab row, fields and
     submit, whole. MEASURED here, from the rendered form, because it rewraps with the rail's width
     and grows with the errors it shows; a restated length is the constant that drifts (see the
     queue-floor history in shell.css). The same floor stays once a trace answers, so the answer is
     not then squeezed into 10rem either. The queue keeps its own floor, and the rail scrolls
     internally when both do not fit — which it already did on the short rungs — so every queue row
     stays reachable. On any OTHER surface with a flow open, the queue is what the reader is working
     in, and the path panel keeps the 10rem floor (review/layout-guard.mjs invariant 2 holds that).
     The splitter is untouched: its value is still the path's share above the floor. Guarded by
     `node review/capture.mjs text`, which fails on any form split by its scroll port. */
  const pathSlotRef = useRef<HTMLDivElement | null>(null);
  const pathLead = hasPath && surface === "path";
  const [formNeed, setFormNeed] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (!pathLead) {
      setFormNeed(null);
      return;
    }
    const slot = pathSlotRef.current;
    const form = slot?.querySelector<HTMLElement>("form");
    if (!slot || !form) return;
    const measure = (): void => {
      const box = form.getBoundingClientRect();
      /* A hidden tab panel (the intent mode) lays the form out at zero. The floor it last measured
         is kept, so switching tabs does not resize the rail under the reader. */
      if (box.height <= 0) return;
      /* Everything between the form's bottom edge and the slot's: the form's own scroller's end
         padding and the slot's (the cut-row scrim's run-out), so the submit is not flush with a cut. */
      const panel = form.closest<HTMLElement>(".pt-panel");
      const scrolled = panel?.scrollTop ?? 0;
      const padOf = (el: HTMLElement | null): number => (el === null ? 0 : Number.parseFloat(getComputedStyle(el).paddingBottom) || 0);
      setFormNeed(Math.ceil(box.bottom - slot.getBoundingClientRect().top + scrolled + padOf(panel) + padOf(slot)));
    };
    measure();
    if (typeof ResizeObserver !== "function") return;
    /* The form (its own height: errors, the port field appearing) and the slot (its width, which
       rewraps the form). Setting the floor changes the slot's HEIGHT only, which moves neither the
       form nor the slot's top, so a measurement never feeds itself. */
    const ro = new ResizeObserver(measure);
    ro.observe(form);
    ro.observe(slot);
    return () => ro.disconnect();
  }, [pathLead]);

  const railStyle: CSSProperties | undefined = hasPath
    ? ({
        ["--rail-a-split" as string]: `${split}%`,
        ...(pathLead && formNeed !== null ? { ["--rail-a-path-need" as string]: `${formNeed}px` } : {}),
      } as CSSProperties)
    : undefined;

  return (
    <nav
      ref={railRef}
      className="rail rail--a"
      aria-label="Investigation queue and path"
      data-split={hasPath ? "true" : undefined}
      data-path-lead={pathLead && formNeed !== null ? "form" : undefined}
      style={railStyle}
      hidden={hidden}
    >
      {hasPath ? (
        <>
          <div className="rail__slot scroll-y" ref={pathSlotRef}>
            <ErrorBoundary surface="The path panel">
              <PathTrace onOpenCite={onOpenCite} />
            </ErrorBoundary>
          </div>
          <Splitter value={split} onChange={change} railRef={railRef} />
        </>
      ) : null}

      <div id="rail-queue" className="rail__slot rail__slot--queue">
        <ErrorBoundary surface="The priority queue">
          <PriorityQueue onOpenEvidence={(cite) => onOpenCite(cite)} />
        </ErrorBoundary>
      </div>
    </nav>
  );
}

/* ── Rail B: evidence, which re-aims and never blanks ──────────────────────── */

export type EvidenceView = "finding" | "device";

const VIEWS: readonly { id: EvidenceView; label: string }[] = [
  { id: "finding", label: "Finding" },
  { id: "device", label: "Device" },
];
const VIEW_IDS: readonly EvidenceView[] = VIEWS.map((v) => v.id);

export interface RailBProps {
  hidden?: boolean;
  onOpenCite: (cite: string) => void;
  /** Controlled by the frame so the `v` command can bring the configuration evidence on screen. */
  view: EvidenceView;
  onView: (v: EvidenceView) => void;
}

/**
 * Two panes share this rail: the evidence CHAIN behind a finding (flow A, steps 3–5) and the
 * six-tab record view of a device or a link (design brief 2.1). Both stay mounted and the inactive
 * one is `hidden`, so switching between them keeps each pane's scroll position and open
 * disclosures — a rail that rebuilt itself on every selection would lose the reader's place every
 * time they compared two findings.
 *
 * The active pane re-aims with the selection: choosing a finding shows its chain, choosing a
 * device or a link shows that record. An explicit choice from the control survives until the
 * selection next changes, which is the behaviour of a preference rather than a mode.
 */
export function RailB({ hidden = false, onOpenCite, view, onView }: RailBProps): ReactElement {
  const findingId = useInvestigation((s) => s.findingId);
  const deviceId = useInvestigation((s) => s.deviceId);
  const linkId = useInvestigation((s) => s.linkId);
  const setView = onView;
  const groupId = useId();

  const lastFinding = useRef(findingId);
  const lastSubject = useRef(`${deviceId ?? ""}|${linkId ?? ""}`);

  useEffect(() => {
    const subject = `${deviceId ?? ""}|${linkId ?? ""}`;
    const findingChanged = findingId !== lastFinding.current;
    const subjectChanged = subject !== lastSubject.current;
    lastFinding.current = findingId;
    lastSubject.current = subject;

    /* A device selection made BY choosing a finding arrives in the same commit as the finding.
       Checking the finding first means the chain wins that tie, which is the order of flow A. */
    if (findingChanged && findingId !== null) setView("finding");
    else if (subjectChanged && (deviceId !== null || linkId !== null)) setView("device");
  }, [findingId, deviceId, linkId, setView]);

  /* ── focus survives the pane switch ──
   *
   * A11Y AUDIT FIX, 2026-09-21 (D3). The device chips in a finding's evidence chain select a
   * device, the selection flips this rail to the Device pane, and the Finding pane — which held
   * the focused chip — becomes `hidden`. Chrome's focus fixup then dropped focus to <body>:
   * measured `activeElement: body` after Enter on "core1 assessed" in step 2 of flow A1, with
   * nothing announced. The ACL "Show the configuration" button already hands focus to what it
   * opened; this path did not.
   *
   * Handled HERE, at the one place a pane is hidden, rather than in each control that happens to
   * cause a switch — the chips in steps 2 and 3, a URL restore, the `v` command, and anything
   * added later all hide a pane the same way. The test is structural: after the commit that
   * changed the view, is focus still inside a pane that is now hidden? If so it is about to be
   * lost, and it goes to the heading of the pane the reader was sent to. Focus anywhere else —
   * the radio that made the switch, the query bar, the fabric — is left exactly where it is.
   */
  const panesRef = useRef<Record<EvidenceView, HTMLDivElement | null>>({ finding: null, device: null });
  useLayoutEffect(() => {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) return;
    const stranded = VIEWS.some((v) => v.id !== view && panesRef.current[v.id]?.contains(active) === true);
    if (!stranded) return;
    const pane = panesRef.current[view];
    const heading = pane?.querySelector<HTMLElement>("h2, h3");
    if (!heading) return;
    if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
    heading.focus({ preventScroll: false });
  }, [view]);

  return (
    <aside
      id="rail-evidence"
      className="rail rail--b"
      aria-label="Evidence"
      hidden={hidden}
    >
      <div className="railb__switch" role="radiogroup" aria-label="Which evidence to read">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            type="button"
            role="radio"
            id={`${groupId}-${v.id}`}
            aria-checked={view === v.id}
            tabIndex={rovingStop(VIEW_IDS, view) === v.id ? 0 : -1}
            className="railb__switch-btn"
            onClick={() => setView(v.id)}
            onKeyDown={(e) => {
              const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
              if (d === 0) return;
              e.preventDefault();
              const i = VIEWS.findIndex((x) => x.id === view);
              const next = VIEWS[(i + d + VIEWS.length) % VIEWS.length];
              if (next === undefined) return;
              setView(next.id);
              document.getElementById(`${groupId}-${next.id}`)?.focus();
            }}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div
        className="railb__pane scroll-y"
        hidden={view !== "finding"}
        ref={(el) => {
          panesRef.current.finding = el;
        }}
      >
        <ErrorBoundary surface="The finding evidence chain">
          <EvidencePane onOpenCite={onOpenCite} />
        </ErrorBoundary>
      </div>
      <div
        className="railb__pane scroll-y"
        hidden={view !== "device"}
        ref={(el) => {
          panesRef.current.device = el;
        }}
      >
        <ErrorBoundary surface="The device evidence pane">
          <DevicePane onOpenCite={onOpenCite} />
        </ErrorBoundary>
      </div>
    </aside>
  );
}

/* ── the stage ─────────────────────────────────────────────────────────────── */

/**
 * Shown while the renderer chunk is in flight and while the scene warms up behind it.
 *
 * It is a DETERMINATE skeleton, not a rectangle with a spinner in it: the tier structure is drawn
 * from `fabric.tiers` — the same array the 3-D layout is computed from — so the reader can already
 * see how many layers the fabric has and how many devices sit in each, and the arriving picture
 * confirms what the skeleton said rather than replacing a shrug.
 *
 * WHY THE SENTENCE CHANGED, THREE TIMES.
 *
 * It first said "…and do not wait on it", which was false: the cold load blocked the main thread
 * for 1.6-3.3 s in a single animation frame, so nothing responded. It was then rewritten to promise
 * only that the panels would respond "as soon as the renderer has finished building", which was
 * true and useless. The staged warm-up then made a responsiveness promise defensible, so the
 * sentence said the panels "stay responsive while it builds" on the strength of "keystrokes
 * during the cold load complete in 16 ms in most runs".
 *
 * THAT SENTENCE IS NOW WITHDRAWN, on this file's own instruction ("a reassurance that measures as
 * false is worse than no reassurance"). "In most runs" was the tell. Measured across seven cold
 * loads on the release build (`review/audit-e5-coldload.mjs`), the WORST keystroke in each run
 * was 88, 184, 240, 520, 424, 976 and 1024 ms, against a worst animation frame of 520-957 ms
 * (blocking 458-852). A reader who starts typing during the cold load can wait a full second. So
 * the sentence now says only what is true — the panels are already populated from the same
 * snapshot and can be read and used — and the warm-up states itself instead, through
 * `StageWarmup` below, which is on screen for the whole of it rather than only for the chunk
 * fetch. Restore a responsiveness promise only when the measurement supports it, and quote the
 * measurement here when you do.
 */
function StagePending(): ReactElement {
  const tiers = fabric.tiers;
  const placed = tiers.reduce((n, t) => n + t.length, 0);
  return (
    <div className="stage-pending" role="status">
      {/* The skeleton is decorative: every device it stands for is already reachable by name in
          the fabric list and in the queue, so announcing 26 empty boxes to a screen reader would
          be noise. The sentence below is the accessible content. */}
      <div className="stage-skeleton" aria-hidden="true">
        {tiers.map((tier, i) => (
          <div className="stage-skeleton__tier" key={`tier-${i}`}>
            <span className="stage-skeleton__label">{`tier ${i + 1} · ${tier.length}`}</span>
            <div className="stage-skeleton__row">
              {tier.map((id) => (
                <span className="stage-skeleton__node" key={id} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="stage-pending__text">
        {`Drawing the 3-D fabric: ${placed} devices across ${tiers.length} tiers, laid out as shown. The queue, the path panel and the evidence rail are already populated from the same snapshot and can be read now; the fabric's warm-up can hold the main thread for up to about a second, so a keystroke made during it may take that long to land.`}
      </p>
    </div>
  );
}

/**
 * The fabric is still building — acceptance E5, the half that was missing.
 *
 * THE DEFECT. `StagePending` above is a Suspense fallback: it covers the renderer CHUNK being
 * fetched and vanishes the instant `Fabric3D` mounts. The scene's warm-up runs AFTER that, and it
 * is the expensive half. Measured over four cold loads on the release build
 * (`review/audit-e5-coldload.mjs`): worst animation frame 520.5 / 623.2 / 956.9 / 676.4 ms, and
 * in 4 of 4 runs `.stage-pending` was ABSENT during that frame. A DOM sweep at five points across
 * the load found `aria-busy` 0, `role="progressbar"` 0, `<progress>` 0, spinner 0 — the stage was
 * a blank white panel with nothing on screen saying work was happening. Section 8.4 of the design
 * brief says work allowed to be slow must be VISIBLY in progress; this is the one piece of work
 * in the product that clause is written about, and it was the one piece with no affordance.
 *
 * DETERMINATE, because the scene already publishes a real denominator. `programsLinked` /
 * `programsTotal` is a 0..51 count of shader programs the driver has finished linking, and
 * `warmupStage` names which of the six stages is running. So this is a progressbar with a value,
 * not a spinner — a spinner would be a guess where a measurement exists.
 *
 * WHEN THE DENOMINATOR IS NOT KNOWN YET (`programsTotal === 0`, the first two stages) the
 * progressbar carries NO `aria-valuenow`, which is how ARIA spells indeterminate. It does not
 * borrow a plausible number, and it does not fall back to 0 of 0 — a bar reading 0% and a bar
 * that does not know are different claims.
 *
 * THE READOUT IS UP TO A SECOND BEHIND. `telemetry.ts` throttles notifications to 1 Hz on
 * purpose (publishing every emit cost 6-7 fps, measured). So the stage word and the count step
 * rather than stream. That is stated here rather than hidden, because a reader comparing this
 * count against a DevTools trace would otherwise think one of them was wrong.
 */
function StageWarmup({ stats }: { stats: SceneStatsEx | null }): ReactElement {
  const total = stats?.programsTotal ?? 0;
  const done = stats?.programsLinked ?? 0;
  const known = total > 0;
  /* `stats === null` is the window between the renderer chunk mounting and the scene's first
     TIMED frame — the scene deliberately publishes nothing until a frame duration exists (the E4
     fix), and that window contains the most expensive frame of the whole load. Worded as what is
     known: the renderer is starting, and nothing has been counted yet. */
  const detail =
    stats === null
      ? "starting the renderer"
      : known
        ? `${done} of ${total} shader programs linked`
        : "counting the shader programs it needs";
  return (
    <div
      className="stage-warmup"
      role="progressbar"
      aria-label="Building the 3-D fabric"
      aria-valuemin={0}
      {...(known ? { "aria-valuemax": total, "aria-valuenow": done } : {})}
      aria-valuetext={detail}
    >
      <div className="stage-warmup__bar" data-known={known ? "true" : "false"}>
        <div
          className="stage-warmup__fill"
          style={known ? { inlineSize: `${Math.round((done / total) * 100)}%` } : undefined}
        />
      </div>
      <p className="stage-warmup__text">
        {`Building the 3-D fabric — ${detail}. The panels around it are already populated and can be read now.`}
      </p>
    </div>
  );
}

export interface StageProps {
  /** False below 768px until the reader asks for the fabric (design brief 2.5, WCAG 1.4.10). */
  fabricVisible: boolean;
}

/**
 * The stage holds the fabric for the life of the session and the inspector docked beneath it.
 *
 * `mounted` latches true and never returns to false: once the renderer has a context, a camera
 * pose and compiled programs, throwing them away to save a hidden canvas would cost the reader
 * their framing the next time they look at the fabric. Hiding the stage is a CSS concern, handled
 * by shell.css through `data-fabric3d` on the frame.
 */
export function Stage({ fabricVisible }: StageProps): ReactElement {
  const inspectorOpen = useInvestigation((s) => s.inspectorOpen);
  const mounted = useRef(false);
  if (fabricVisible) mounted.current = true;

  return (
    <main
      id="stage"
      className={`app__stage${inspectorOpen ? " app__stage--with-inspector" : ""}`}
      tabIndex={-1}
      aria-label="Fabric"
    >
      <ErrorBoundary surface="The 3-D fabric">
        {mounted.current ? (
          <Suspense fallback={<StagePending />}>
            <Fabric3D />
          </Suspense>
        ) : (
          <StagePending />
        )}
        <StageWarmupGate mounted={mounted.current} />
      </ErrorBoundary>

      <ErrorBoundary surface="The inspector">
        <Inspector />
      </ErrorBoundary>
    </main>
  );
}

/**
 * The one subscriber to the scene's readings inside the stage.
 *
 * RESPONSIVENESS FIX, 2026-09-21 (acceptance E2/E3). `Stage` itself used to call
 * `useSceneStats()`, so every telemetry notification re-rendered the whole stage subtree — the
 * Inspector included — on the telemetry timer: measured as a 35-55 ms `telemetry.ts` setTimeout
 * task recurring through every journey, landing on interactions at random. A component of its own
 * confines the notification to the one element that draws it, the same reason `App` keeps its
 * status-bar subscriber separate.
 */
function StageWarmupGate({ mounted }: { mounted: boolean }): ReactElement | null {
  /* The scene's own reading, not a timer. `warmupStage` is non-null for exactly as long as the
     warm-up runs — including the rebuild after an adaptive tier change or a theme change, which is
     real work and deserves the same affordance. */
  const sceneStats = useSceneStats();
  /* E5 AUDIT FIX, 2026-09-21 (second pass). This was `sceneStats !== null && warmupStage !== null`,
     and it collided with the E4 fix in scene.ts: the scene now publishes NOTHING until it has timed
     a frame, so between the Suspense fallback unmounting and that first timed frame the stage
     carried no affordance at all — and that window holds the worst frame of the load. Measured on
     a fresh release build (`review/audit-e5-coldload.mjs`, 3 runs): in 2 of 3 the worst frame
     (745.8 / 860.6 ms) fell there with `workingAffordancePresent: false`.

     So `null` while the fabric is MOUNTED now counts as warming: the stage has asked for a
     renderer and not yet heard from it. The failure case the old comment guarded against is still
     guarded, structurally rather than by guesswork — when the renderer cannot start, Fabric3D draws
     `.fabric3d__fallback`, and App.css hides `.stage-warmup` from the stage that contains one, so a
     failed renderer is never described as a starting one. */
  const warming = mounted && (sceneStats === null || sceneStats.warmupStage !== null);
  return warming ? <StageWarmup stats={sceneStats} /> : null;
}

/* ── the single-column pane control ────────────────────────────────────────── */

export interface PaneSwitchProps {
  value: PaneId;
  onChange: (p: PaneId) => void;
  /** Absent when no flow is being investigated: the path pane has nothing to select. */
  pathAvailable: boolean;
  /**
   * False below 768px, where every rail is stacked and visible at once. Offering a control that
   * chooses between panels that are all already on screen would be chrome that does nothing.
   */
  showPanes: boolean;
  fabricVisible: boolean;
  onToggleFabric: () => void;
  /** True below 768px, where the fabric is behind an explicit toggle (WCAG 1.4.10 reflow). */
  fabricOptional: boolean;
}

/**
 * The roving tab stop of a single-select group: the checked item, or — when the value names no
 * rendered item — the FIRST item, so the group is never left without a way in (APG radio group:
 * "if no radio button is checked, focus moves to the first radio button in the group").
 *
 * D1 REGRESSION, 2026-09-24. `tabIndex={value === id ? 0 : -1}` has no tab stop at all when the
 * value is not one of the items, and nothing about that shape says so: at 768 px on the Path surface
 * with no flow, the pane switch's value was `path`, the Path radio was not rendered, and Queue and
 * Evidence were both -1 — "paneswitch focused during 60 Tabs: 0". Every roving group in this file
 * takes its stop from here; `composite-tabstop.test.tsx` holds the rule over every composite widget
 * the app renders, whoever wrote it.
 */
export function rovingStop<T>(ids: readonly T[], value: T): T | undefined {
  return ids.includes(value) ? value : ids[0];
}

/** APG radio-group arrows: Right/Down next, Left/Up previous, wrapping; Home/End the ends. */
function arrowTarget<T>(ids: readonly T[], from: T, key: string): T | undefined {
  const i = Math.max(0, ids.indexOf(from));
  if (key === "ArrowRight" || key === "ArrowDown") return ids[(i + 1) % ids.length];
  if (key === "ArrowLeft" || key === "ArrowUp") return ids[(i - 1 + ids.length) % ids.length];
  if (key === "Home") return ids[0];
  if (key === "End") return ids[ids.length - 1];
  return undefined;
}

export function PaneSwitch({
  value,
  onChange,
  pathAvailable,
  showPanes,
  fabricVisible,
  onToggleFabric,
  fabricOptional,
}: PaneSwitchProps): ReactElement {
  /* The Path pane is offered when a flow exists OR when it is the pane on screen. RailA mounts the
     path panel on `surface === "path"` alone (the flow form is the answer to "trace a flow"), so a
     switch that left Path out while the column was showing it described a column that did not exist
     and checked nothing. */
  const panes: { id: PaneId; label: string }[] = [
    { id: "queue", label: "Queue" },
    ...(pathAvailable || value === "path" ? [{ id: "path" as const, label: "Path" }] : []),
    { id: "evidence", label: "Evidence" },
  ];
  const ids = panes.map((p) => p.id);
  const stop = rovingStop(ids, value);
  const groupRef = useRef<HTMLDivElement | null>(null);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>, from: PaneId): void => {
    const next = arrowTarget(ids, from, e.key);
    if (next === undefined) return;
    e.preventDefault();
    onChange(next);
    /* The target radio is already rendered (the list only ever LOSES Path once the value leaves it),
       so focus follows the selection in the same task. */
    groupRef.current?.querySelector<HTMLElement>(`[data-pane-id="${next}"]`)?.focus();
  };

  return (
    <div className="paneswitch">
      {showPanes ? (
        <div className="paneswitch__group" role="radiogroup" aria-label="Which panel to show" ref={groupRef}>
          {panes.map((p) => (
            <button
              key={p.id}
              type="button"
              role="radio"
              data-pane-id={p.id}
              aria-checked={value === p.id}
              tabIndex={stop === p.id ? 0 : -1}
              className="paneswitch__btn"
              onClick={() => onChange(p.id)}
              onKeyDown={(e) => onKeyDown(e, p.id)}
            >
              {p.label}
            </button>
          ))}
        </div>
      ) : null}
      {fabricOptional ? (
        <button
          type="button"
          className="paneswitch__fabric"
          aria-pressed={fabricVisible}
          onClick={onToggleFabric}
        >
          {fabricVisible ? "Hide the 3-D fabric" : "Show the 3-D fabric"}
        </button>
      ) : null}
    </div>
  );
}

