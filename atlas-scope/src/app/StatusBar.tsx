/**
 * StatusBar.tsx — the permanent honesty line (acceptance B7).
 *
 * It states the denominators on every screen, for the whole life of the investigation: how many
 * devices the engine says were collected completely (core/collection.ts), how many carry a routing table, how many carry an access list,
 * how many links have measured centrality. Those figures are the boundary of every claim the rest
 * of the application makes, and a boundary that is one click away is a boundary people forget.
 *
 * Each denominator is a CONTROL, not a caption: it opens the coverage disclosure at its own row,
 * so "RIBs 2 of 26" leads straight to what that means rather than leaving the reader to infer it.
 * The disclosure is rendered here rather than delegated, because `onOpenCoverage` may be unwired
 * while the shell is being assembled, and a coverage figure that leads nowhere is exactly the
 * quiet failure this bar exists to prevent.
 *
 * It also carries the live scene telemetry. Adaptive quality is only honest if it is visible: a
 * renderer that has silently dropped to the `low` tier is showing you a different picture than
 * the one you think you are reading, so the tier is named at all times and a reduced tier is
 * marked with a word, not only a colour. Before the 3-D subsystem reports its first frame there
 * is no measurement — that renders as `not observed`, never as a zero or a blank.
 *
 * WHAT THE SCENE READOUT DELIBERATELY DOES NOT DRAW, and why (acceptance F6). It drew
 * `Math.round(stats.fps)` — a frame-timing measurement — in the permanent chrome. Measured
 * 2026-09-21: two consecutive `node review/capture.mjs app` runs differed in 23 of 32 frames, and
 * every differing pixel fell inside the 24x16 box holding those digits ("fabric 43 fps" against
 * "fabric 56 fps"). F6 asks for byte-identical captures; a machine- and moment-dependent number
 * painted into every frame of the chrome makes that impossible by construction, and it did so
 * while the 3-D canvas underneath was already byte-identical.
 *
 * The fix is a product decision, not a capture-time one: the permanent line carries only values
 * that are a function of the DATA — the tier word, `reduced`, `settled`/`refining` — and every
 * frame-timing digit moved one click away, into the same disclosure the coverage denominators
 * open. That is what the design brief asks for in the first place (§8: "the active tier is named
 * in the status bar at all times"; T8's permanent line is coverage + snapshot, and never carried a
 * frame rate). Nothing is hidden: the readout is a control, it says so, and the numbers are behind
 * it. Deliberately NOT a `?capture=1` mode — a capture that photographs a state the product does
 * not otherwise show proves a property the product does not have.
 *
 * Every number is read from `fabric` / `SceneStats` at render time. Nothing here is hardcoded.
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { aclUndecidability } from "../core/acl-coverage";
import { collectedDescription, collectedFigure } from "../core/collection";
import { fabric } from "../core/data";
import { datasetNotices, isBundledSample } from "../core/dataset";
import { DatasetBanner, digestFormLabel } from "./OpenSnapshot";
import { ribCountQualifier, ribHostsShownIncomplete } from "../forwarding/rib-completeness";
import { useInvestigation } from "../core/store";
import type { Cite } from "../core/types";
import type { QualityTier, SceneStats } from "../fabric3d/contract";
import { IconClose } from "../ui/icons";
import { CoverageStatement, IconButton, NotObserved } from "../ui/primitives";
import { CoverageBar } from "./CoverageBar";
import { returnFocus } from "./focus-return";
import "./chrome.css";

/** The claim-strength vocabulary, with the token each badge is drawn in (design brief §6.4). */
const CLAIM_LEGEND: readonly { badge: string; meaning: string }[] = [
  {
    badge: "SCOPED",
    meaning:
      "the traversal completed, every host on the path had a collected routing table the snapshot does not show to be incomplete for this route decision, and collected ACLs, no evidence item was indeterminate, and no ingress assumption was left open — any alternate FHRP ingress reproduced the result and the gateway port the source arrives by had observed filtering. This is the strongest badge that exists here.",
  },
  {
    badge: "PARTIAL",
    meaning: "a complete traversal of the modelled path that rested on partial evidence. Like every badge here it describes a simulation, never observed traffic.",
  },
  {
    badge: "INDETERMINATE",
    meaning:
      "the model could not decide — an unmodeled hop, an unevaluable access-list line, or a computation that was cancelled. It is a finding, not an omission.",
  },
  {
    badge: "OUT OF SCOPE",
    meaning: "the flow could not be entered into the model at all.",
  },
  {
    badge: "INVALID INPUT",
    meaning: "the question was not a well-formed flow (for example a prefix where an address belongs), so nothing was simulated.",
  },
];

const TIER_WORD: Readonly<Record<QualityTier, string>> = {
  high: "high",
  balanced: "balanced",
  low: "low",
};

export interface StatusBarProps {
  /**
   * Live telemetry from the 3-D subsystem. `null` until it reports its first frame — which is a
   * genuine absence of measurement and is rendered as one.
   */
  stats?: SceneStats | null;
  /** Wired when the inspector gains a coverage view; the local disclosure opens either way. */
  onOpenCoverage?: (rowId: string) => void;
  /** Wired when the inspector can resolve a citation to its raw record. */
  onOpenCite?: (cite: Cite) => void;
}

export function StatusBar({ stats = null, onOpenCoverage, onOpenCite }: StatusBarProps): ReactElement {
  const c = fabric.coverage;
  /* The undecidable ACL surface is the UNION of three sets (see core/acl-coverage.ts). The old
     `coverage.aclLinesUnevaluable` named only the producer's flag, which on this snapshot is
     disjoint from the lines the engine actually refuses.
     Computed once per mount, as CoverageBar does: `fabric` is a static import, so there is nothing
     for it to go stale against. The status bar re-renders on every scene-stats emission and every
     selection, and recomputing the union each time was the largest application-side cost in the
     path-trace commit profile (E3, journey 4: ~4.6 ms per render, unminified release build). */
  const undecidable = useMemo(() => aclUndecidability(), []);
  const totalDevices = fabric.devices.length;
  const totalLinks = fabric.links.length;

  const deviceId = useInvestigation((s) => s.deviceId);
  const linkId = useInvestigation((s) => s.linkId);
  const findingId = useInvestigation((s) => s.findingId);

  const panelId = useId();
  const [open, setOpen] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  const close = useCallback(() => {
    setOpen(null);
    /* Focus returns to the exact control that opened the panel. Dropping focus on <body> silently
       resets keyboard navigation to the top of the document, which costs a keyboard user the
       whole header every time they check a denominator. */
    returnFocus(returnTo.current, barRef.current);
    returnTo.current = null;
  }, []);

  const toggle = useCallback(
    (rowId: string) => {
      onOpenCoverage?.(rowId);
      /* Deliberately computed OUTSIDE the state updater. A `setState` callback must be pure, and
         React invokes it twice under StrictMode — focusing and writing a ref in there would move
         focus twice and record the wrong element to return it to. */
      if (open === rowId) {
        close();
        return;
      }
      if (open === null) returnTo.current = document.activeElement as HTMLElement | null;
      setOpen(rowId);
    },
    [open, close, onOpenCoverage],
  );

  useEffect(() => {
    if (open === null) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      e.preventDefault();
      close();
    };
    /* The panel is NOT modal: the investigation behind it stays live and readable, so an outside
       click is a dismissal rather than a blocked interaction. */
    const onDown = (e: MouseEvent): void => {
      const t = e.target as Node;
      if (panelRef.current?.contains(t) || barRef.current?.contains(t)) return;
      setOpen(null);
      returnTo.current = null;
    };
    /* WCAG 2.4.11 (Focus Not Obscured): the panel is large and non-modal, so a keyboard user who
       tabs out of it would otherwise land on controls it covers (the fabric legend, Rail B's
       queue). Focus leaving both the panel and its triggering bar dismisses it, exactly as an
       outside click does — the other popovers in the product already behave this way. Focus is
       NOT pulled back to the trigger: the user moved it deliberately. */
    const onFocusIn = (e: FocusEvent): void => {
      const t = e.target as Node | null;
      if (t === null || t === document.body) return;
      if (panelRef.current?.contains(t) || barRef.current?.contains(t)) return;
      setOpen(null);
      returnTo.current = null;
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [open, close]);

  useEffect(() => {
    if (open === null) return;
    panelRef.current?.focus();
  }, [open]);

  /* WCAG 2.4.11 (Focus Not Obscured), 2026-09-24. Below 768px this bar is `position: sticky` at the
     viewport's bottom edge, and it WRAPS (85 px tall at 390, not the 26 px token). Measured with real
     Tab presses (review/audit-d3-focus.mjs --sweep, 390x844, a traced flow): the browser scrolled
     each newly focused control only as far as the viewport's edge, which is under this bar — "Open
     source record collection_completeness / coverage_matrix" landed with 0 of 9 hit-test points on
     itself, a path preset with 3 of 9. The document's scroll padding (shell.css, <= 767px) is what a
     focus scroll respects, so the bar publishes its REAL block size for it, live, rather than the
     stylesheet restating a height that changes with the width and the figures. */
  useEffect(() => {
    const bar = barRef.current;
    const root = document.documentElement;
    if (bar === null) return;
    const publish = (): void => root.style.setProperty("--statusbar-block", `${Math.ceil(bar.getBoundingClientRect().height)}px`);
    publish();
    if (typeof ResizeObserver !== "function") return () => root.style.removeProperty("--statusbar-block");
    const ro = new ResizeObserver(publish);
    ro.observe(bar);
    return () => {
      ro.disconnect();
      root.style.removeProperty("--statusbar-block");
    };
  }, []);

  const denominator = (rowId: string, text: string, description: string): ReactElement => (
    <button
      type="button"
      className="sb__cov"
      aria-expanded={open === rowId}
      /* Only while the panel exists: `aria-controls` is an IDREF, and one pointing at nothing is
         a broken relationship rather than a dormant one. */
      aria-controls={open === rowId ? panelId : undefined}
      onClick={() => toggle(rowId)}
      title={description}
    >
      {text}
    </button>
  );

  const selection: ReactNode =
    findingId === null && deviceId === null && linkId === null ? (
      <span className="sb__sel-none">nothing selected</span>
    ) : (
      [findingId, deviceId, linkId].filter((v): v is string => v !== null).map((v) => (
        <code key={v} className="sb__sel-id">
          {v}
        </code>
      ))
    );

  /* The dataset line (OpenSnapshot.tsx) sits on this bar because the bar is on every screen: when the
     page shows anything but this build's bundled sample — an AssessHub snapshot, an opened file — or an
     opened file could not be restored, it is said here permanently, on its own row. The bar wraps only
     then, so the bundled sample's line is unchanged. */
  const datasetLine = !isBundledSample || datasetNotices.length > 0;

  return (
    <footer ref={barRef} id="status-bar" className="app__status sb" style={datasetLine ? { flexWrap: "wrap" } : undefined}>
      {datasetLine ? <DatasetBanner /> : null}
      <div className="sb__group" role="group" aria-label="Collection coverage">
        <span className="sb__key">coverage</span>
        {denominator(
          "collected",
          /* The ENGINE's count (core/collection.ts), never record presence: the engine writes a device record for
             every inventoried host, an empty capture included (2026-10 refuter, B7). */
          collectedFigure(),
          `${collectedDescription()} Open the coverage disclosure.`,
        )}
        {denominator(
          "rib",
          /* A count of collected tables read as that many WHOLE tables; the snapshot shows them
             partial (./rib-completeness.ts; 2026-09-22 critic, B7). */
          `RIBs ${c.hostsWithRoutes}/${totalDevices}${ribCountQualifier() === "" ? "" : ` ${ribCountQualifier()}`}`,
          `Routing tables were collected for ${c.routableHosts.join(", ") || "no host"}. Forwarding is modelled on those hosts and no wider.${
            ribHostsShownIncomplete().length === 0
              ? ""
              : ` The snapshot shows ${ribHostsShownIncomplete().join(" and ")}'s ${ribHostsShownIncomplete().length === 1 ? "table" : "tables"} to be incomplete, so a forwarding claim resting on a route there is not decided.`
          }`,
        )}
        {denominator(
          "acl",
          `ACLs ${c.hostsWithAcls}/${totalDevices}`,
          `Access lists were collected for ${c.aclHosts.join(", ") || "no host"}, ${undecidable.total} lines, of which ${undecidable.count} cannot be decided${undecidable.count === 0 ? "" : `: ${undecidable.members.map((m) => m.label).join(", ")}`}. That is the union of the lines this model refuses to evaluate (${undecidable.bySource.engine}), the lines the collector's parser could not model (${undecidable.bySource.producer}) and the lines the snapshot's own reachability analysis returned indeterminate (${undecidable.bySource.snapshot}).`,
        )}
        {denominator(
          "centrality",
          `centrality ${c.linksWithCentrality}/${totalLinks}`,
          `Betweenness was computed for ${c.linksWithCentrality} of ${totalLinks} links. The remainder are unmeasured, which is not the same as unimportant.`,
        )}
      </div>

      {/* B7: EVERYTHING ELSE on the line scrolls; the coverage group never does. The whole bar used
          to be one horizontal scroll region, so at a 390px phone width "ACLs 1/26" sat at x369-418,
          off-screen until the reader scrolled a bar they had no reason to know scrolls. Now the
          coverage group is outside the scroll region and wraps onto a second line when it must
          (chrome.css `.sb__group`), and only this remainder — snapshot, selection, legend and scene
          readout — scrolls sideways when the bar is too narrow for it. */}
      <div className="sb__rest">
        <span className="sb__sep" aria-hidden="true" />

        <p className="sb__snap">
          <span className="sb__key">snapshot</span>
          {/* Which sha256 this is, said in the tooltip rather than left to be inferred. It is the
              digest of the SOURCE snapshot the compiler read, not of the compiled `fabric.json` the
              page is running on — two different numbers, and the source one is what binds this model
              to an upstream artefact. The Inspector's Provenance tab carries the full argument,
              including that this value is the compiler's declaration read back, not a recomputation. */}
          <code className="sb__sha" title={`Source snapshot sha256 (${digestFormLabel(fabric.meta.sourceDigestForm)}) ${fabric.meta.sourceSha256}`}>
            {fabric.meta.sourceSha256.slice(0, 8)}
          </code>
          <span className="sb__when">
            {fabric.meta.collectedAt === null ? (
              <NotObserved what="collection time" compact />
            ) : (
              <time dateTime={fabric.meta.collectedAt}>{fabric.meta.collectedAt.slice(0, 10)}</time>
            )}
          </span>
        </p>

        <p className="sb__sel">
          <span className="sb__key">selection</span>
          {selection}
        </p>

        <span className="sb__spacer" />
        <span className="sb__sep" aria-hidden="true" />

        <button
          type="button"
          className="sb__cov"
          aria-expanded={open === "legend"}
          aria-controls={open === "legend" ? panelId : undefined}
          onClick={() => toggle("legend")}
          title="What each claim-strength badge means, and the boundary each one carries."
        >
          claim strength
        </button>

        {/* determinism: the tier word (`stats.quality`) and "below frame-rate bar"
            (`stats.frameRateBelowBar`) below are WORDS derived from this host's rAF frame times, and
            they sit on the permanent chrome. They are allowed here only because the capture harness
            refuses a frame that carries either one: review/capture.mjs records both and fails any
            capture whose tier is not "high" or whose status line reads "below frame-rate bar", so a
            comparable capture always draws the same words (acceptance F6). */}
        {stats === null ? (
          <p className="sb__scene" data-tier="unknown">
            <span className="sb__key">fabric</span>
            <NotObserved
              what="scene telemetry"
              why="the 3-D subsystem has not reported a frame yet"
              compact
            />
          </p>
        ) : (
          /* A CONTROL, for the same reason the denominators are: the words below are a summary, and
             the measurements behind them are one click away rather than one inference away. It is
             also what keeps the permanent chrome free of frame-timing digits (see the file header). */
          <button
            type="button"
            className="sb__scene sb__scene--btn"
            data-tier={stats.quality}
            aria-expanded={open === "renderer"}
            aria-controls={open === "renderer" ? panelId : undefined}
            onClick={() => toggle("renderer")}
            title="The renderer's quality tier and convergence. Open for the measured frame rate and frame cost."
          >
            <span className="sb__key">fabric</span>
            {/* The tier is named in WORDS, and a reduced tier says so in words too. No glyph:
                the severity silhouettes are a closed semantic set, and borrowing the High
                triangle for "the renderer stepped down" would make two screens disagree about
                what that shape means. No chroma either — chroma belongs to severity and
                operational state, not to the chrome reporting on itself. */}
            <span className="sb__tier">{`tier ${TIER_WORD[stats.quality]}`}</span>
            {stats.quality === "high" ? null : (
              <>
                <span className="sb__dot" aria-hidden="true" />
                <span className="sb__reduced">reduced</span>
              </>
            )}
            {/* Acceptance E4: the step-down rule tolerates 45-55 fps, and that band used to read as
                a plain "tier high". Words, not digits, for the same reason the tier is words: the
                measured rate is one click away in the renderer disclosure. The field is read with an
                `in` guard because the prop is the frozen contract's `SceneStats`; the live channel
                publishes the scene's widened reading. */}
            {"frameRateBelowBar" in stats && stats.frameRateBelowBar === true ? (
              <>
                <span className="sb__dot" aria-hidden="true" />
                <span className="sb__reduced">below frame-rate bar</span>
              </>
            ) : null}
            {/* The separator glyph is generated content with an empty alternative (chrome.css
                `.sb__dot::before`): decoration, so it is not document text. */}
            <span className="sb__dot" aria-hidden="true" />
            {/* Progressive refinement has not finished, so what is on screen is not the final
                frame. A screenshot taken now is a draft, and saying so is cheaper than someone
                filing a rendering defect against a half-converged image. */}
            <span className="sb__converged">{stats.converged ? "settled" : "refining"}</span>
          </button>
        )}
      </div>

      {open === null
        ? null
        : createPortal(
            <div
              ref={panelRef}
              id={panelId}
              role="dialog"
              aria-modal="false"
              aria-label="Collection coverage"
              tabIndex={-1}
              className="covpanel"
            >
              <div className="covpanel__head">
                <h2 className="covpanel__title">Collection coverage</h2>
                <p className="covpanel__lede">
                  {`Everything below is read from the snapshot at ${fabric.meta.source}. A category with nothing observed is a gap in what was collected, not a statement about the network.`}
                </p>
                {/* At <= 767 px this panel is docked over the whole bar (chrome.css), so it states the
                    bar's figures itself, from the same owner (acceptance B7). */}
                <CoverageStatement />
                <IconButton
                  label="Close the coverage disclosure"
                  icon={<IconClose />}
                  size="sm"
                  onClick={close}
                />
              </div>

              <CoverageBar
                highlight={open === "legend" ? null : open}
                {...(onOpenCite ? { onOpenCite } : {})}
              />

              {/* The frame-timing measurements, and the only place in the product they are drawn.
                  determinism: these are the rAF-derived readings. They reach the DOM ONLY here,
                  inside a disclosure that no default view and no capture state opens, which is
                  what makes a capture of the chrome a function of the data (acceptance F6). */}
              <section className="covpanel__renderer" data-highlight={open === "renderer" || undefined}>
                <h3 className="covpanel__subtitle">Renderer</h3>
                {stats === null ? (
                  <NotObserved
                    what="scene telemetry"
                    why="the 3-D subsystem has not reported a frame yet"
                  />
                ) : (
                  <>
                    <p className="covpanel__note">
                      Measured on this machine, in this session, and updated about once a second.
                      These are the only figures on this screen that are not a function of the
                      snapshot — which is why they are here and not on the permanent line.
                    </p>
                    <dl className="covpanel__diag">
                      <div className="covpanel__diag-row">
                        <dt>frame rate</dt>
                        <dd>{`${Math.round(stats.fps)} fps`}</dd>
                      </div>
                      <div className="covpanel__diag-row">
                        <dt>last frame</dt>
                        <dd>{`${stats.frameMs.toFixed(1)} ms`}</dd>
                      </div>
                      <div className="covpanel__diag-row">
                        <dt>draw calls</dt>
                        <dd>{stats.drawCalls}</dd>
                      </div>
                      <div className="covpanel__diag-row">
                        <dt>triangles</dt>
                        <dd>{stats.triangles.toLocaleString("en-GB")}</dd>
                      </div>
                      <div className="covpanel__diag-row">
                        <dt>quality tier</dt>
                        <dd>{TIER_WORD[stats.quality]}</dd>
                      </div>
                      <div className="covpanel__diag-row">
                        <dt>refinement</dt>
                        <dd>{stats.converged ? "settled" : "refining"}</dd>
                      </div>
                    </dl>
                  </>
                )}
              </section>

              <section className="covpanel__legend" data-highlight={open === "legend" || undefined}>
                <h3 className="covpanel__subtitle">Claim strength</h3>
                <dl className="covpanel__badges">
                  {CLAIM_LEGEND.map((l) => (
                    <div key={l.badge} className="covpanel__badge-row">
                      <dt>
                        <span className="covpanel__badge" data-badge={l.badge}>
                          {l.badge}
                        </span>
                      </dt>
                      <dd>{l.meaning}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            </div>,
            document.body,
          )}
    </footer>
  );
}
