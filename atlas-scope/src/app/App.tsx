/**
 * App.tsx — the frame, and the wiring between every surface in it.
 *
 * The shell owns four things and deliberately nothing else:
 *
 *   1. the region grid from design brief 2.1 — header, query bar, rail A, stage, rail B, status
 *      bar — with every region mounted for the life of the session (acceptance A4);
 *   2. the investigation's link (urlSync.ts);
 *   3. the global input model: the keyboard manager, the command registrations, the capabilities
 *      that only the frame can own, and the three live regions from design brief 7.5;
 *   4. one error boundary per surface, so a renderer defect in one panel costs that panel and not
 *      the investigation.
 *
 * Everything else belongs to the surface that renders it, and is called here with its own props.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { flushSync } from "react-dom";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { SEVERITY_ORDER } from "../core/types";
import { verdictStatement } from "../panels/ClaimCard";
import { OPEN_CITE_EVENT } from "../panels/DevicePane";
import { openInspector, setInspectorCite } from "../panels/Inspector";
import { flowKey } from "../panels/PathTrace";
import { Chip } from "../ui/primitives";
import { handOffFocus, keepFocusSeen, releaseFocusLeftUnseen, returnFocus, useReleaseFocusOnHide, useReleaseFocusOnLayoutChange } from "./focus-return";
import { CommandPalette } from "./CommandPalette";
import {
  announce,
  formatFlow,
  parseFlowQuery,
  registerCommandTarget,
  registerSurfaceReveal,
  runFlow,
  useAppCommands,
  useCommandAnnouncement,
} from "./commands";
import { Header } from "./Header";
import { useGlobalKeyboard } from "./keyboard";
import { ShortcutHelp } from "./ShortcutHelp";
import { useSceneStats } from "../fabric3d/telemetry";
import { StatusBar } from "./StatusBar";
import { setThemePreference } from "./ThemeToggle";
import { ErrorBoundary } from "./ErrorBoundary";
import { PaneSwitch, RailA, RailB, Stage, paneForSurface, useLadder, useRungIndex, useStageDefault, type EvidenceView, type PaneId } from "./surfaces";
import { useUrlSync, type RestoredAim } from "./urlSync";
import "./App.css";

/* The investigation log is append-only and bounded. Unbounded, it would grow for the length of a
   session and a screen reader walking it would have to traverse every step ever taken. */
const LOG_LIMIT = 24;

/* ── the query bar: the investigation question as removable tokens ─────────── */

/** The header's question field: the "query.focus" command's target, and the field focus falls back
 *  to when a scope token's removal (or "Clear scope") leaves no other token to move to. */
const QUERY_FIELD = '#app-header form[role="search"] input';
const queryField = (): HTMLInputElement | null => document.querySelector<HTMLInputElement>(QUERY_FIELD);

export function QueryBar(): ReactElement {
  const summaryRef = useRef<HTMLParagraphElement | null>(null);
  const query = useInvestigation((s) => s.query);
  const severities = useInvestigation((s) => s.severities);
  const roles = useInvestigation((s) => s.roles);
  const onlyUncollected = useInvestigation((s) => s.onlyUncollected);
  const deviceId = useInvestigation((s) => s.deviceId);
  const linkId = useInvestigation((s) => s.linkId);
  const findingId = useInvestigation((s) => s.findingId);
  const flow = useInvestigation((s) => s.flow);

  const setQuery = useInvestigation((s) => s.setQuery);
  const toggleSeverity = useInvestigation((s) => s.toggleSeverity);
  const toggleRole = useInvestigation((s) => s.toggleRole);
  const setOnlyUncollected = useInvestigation((s) => s.setOnlyUncollected);
  const selectDevice = useInvestigation((s) => s.selectDevice);
  const selectLink = useInvestigation((s) => s.selectLink);
  const selectFinding = useInvestigation((s) => s.selectFinding);
  const setFlow = useInvestigation((s) => s.setFlow);
  const setTrace = useInvestigation((s) => s.setTrace);

  const tokens: ReactElement[] = [];

  if (query !== "") {
    tokens.push(
      <Chip key="q" removeSuccessor={queryField} mono removeLabel="Remove the free-text query" onRemove={() => setQuery("")}>
        {query}
      </Chip>,
    );
  }
  for (const s of SEVERITY_ORDER) {
    if (!severities.has(s)) continue;
    tokens.push(
      <Chip key={`sev-${s}`} removeSuccessor={queryField} tone="accent" removeLabel={`Remove the ${s} severity filter`} onRemove={() => toggleSeverity(s)}>
        {`severity ${s}`}
      </Chip>,
    );
  }
  for (const r of [...roles].sort()) {
    tokens.push(
      <Chip key={`role-${r}`} removeSuccessor={queryField} tone="accent" removeLabel={`Remove the ${r} role filter`} onRemove={() => toggleRole(r)}>
        {`role ${r}`}
      </Chip>,
    );
  }
  if (onlyUncollected) {
    tokens.push(
      <Chip
        removeSuccessor={queryField}
        key="unc"
        tone="accent"
        removeLabel="Stop restricting to devices the collector never reached"
        onRemove={() => setOnlyUncollected(false)}
      >
        only devices the collector never reached
      </Chip>,
    );
  }
  if (findingId !== null) {
    tokens.push(
      <Chip key="f" removeSuccessor={queryField} mono removeLabel={`Deselect finding ${findingId}`} onRemove={() => selectFinding(null)}>
        {`finding ${findingId}`}
      </Chip>,
    );
  }
  if (deviceId !== null) {
    tokens.push(
      <Chip key="d" removeSuccessor={queryField} mono removeLabel={`Deselect device ${deviceId}`} onRemove={() => selectDevice(null)}>
        {`device ${deviceId}`}
      </Chip>,
    );
  }
  if (linkId !== null) {
    tokens.push(
      <Chip key="l" removeSuccessor={queryField} mono removeLabel={`Deselect link ${linkId}`} onRemove={() => selectLink(null)}>
        {`link ${linkId}`}
      </Chip>,
    );
  }
  if (flow !== null) {
    const label = `${flow.srcIp} to ${flow.dstIp} ${flow.protocol}${flow.dstPort === null ? "" : `:${flow.dstPort}`}`;
    tokens.push(
      <Chip
        removeSuccessor={queryField}
        key="flow"
        mono
        tone="accent"
        removeLabel={`Stop investigating the flow ${label}`}
        onRemove={() => {
          /* Both, in this order: a trace left behind its flow would be a hop list with no question
             above it, which reads as a result rather than as a leftover. */
          setFlow(null);
          setTrace(null);
        }}
      >
        {`flow ${label}`}
      </Chip>,
    );
  }

  /* The same exact paragraph is handed to the focus owner's third door. It releases any focus
     before making the inactive reservation inert, and removes only the inert it set on return. */
  useReleaseFocusOnHide(summaryRef, tokens.length === 0, () => [queryField()]);

  const clearAll = (): void => {
    useInvestigation.getState().reset();
    announce("Investigation scope cleared. The whole snapshot is in view again.");
  };

  return (
    <div id="query-bar" className="app__query">
      <div className="qbar">
        <span className="qbar__label" id="qbar-label">
          Scope
        </span>
        <div className="qbar__content">
          {/* Both states share this sentence's intrinsic, wrapped block size. The inactive
              reservation contains text only: no hidden button can receive focus or speak a
              whole-snapshot claim while the real selection controls are in view. */}
          <p ref={summaryRef} className="qbar__empty" aria-hidden={tokens.length > 0 ? true : undefined}>
            {`Nothing is selected and no filter is applied, so every record in this snapshot is in scope: all ${fabric.devices.length} devices and all ${fabric.findings.length} findings.`}
          </p>
          {tokens.length === 0 ? null : (
            <div className="qbar__selection">
              <div className="qbar__tokens" role="group" aria-labelledby="qbar-label">
                {tokens}
              </div>
              <button type="button" className="qbar__clear" onClick={(e) => handOffFocus(e.currentTarget, clearAll, [queryField])}>
                Clear scope
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── the shell ─────────────────────────────────────────────────────────────── */

/** How many frames `v` waits for the configuration button to be rendered visible (see config.open). */
const CONFIG_OPEN_MAX_FRAMES = 6;

export function App(): ReactElement {
  /* Both are ref-counted, and the palette and the help sheet ask for them too. Asking here means
     the bindings exist even in a build where one of those layers is not rendered. */
  useGlobalKeyboard();
  useAppCommands();

  /* The restored (flow, hop) landing the hop re-aim below must leave alone — see that effect. A
     history step that keeps its trace reports one through `onRestoredAim` (urlSync.ts
     applyHistoryState, acceptance C6 round 2): there the store never passes through "flow, no
     trace", so the render-time recording below cannot see it. */
  const restoredAim = useRef<string | null>(null);
  const onRestoredAim = useCallback((aim: RestoredAim) => {
    restoredAim.current = `${flowKey(aim.flow)}#${aim.hop}`;
  }, []);
  const urlProblem = useUrlSync({ onRestoredAim });
  const [noticeDismissed, setNoticeDismissed] = useState(false);
  const status = useCommandAnnouncement();

  const surface = useInvestigation((s) => s.surface);
  const flow = useInvestigation((s) => s.flow);
  const trace = useInvestigation((s) => s.trace);
  const deviceId = useInvestigation((s) => s.deviceId);
  const linkId = useInvestigation((s) => s.linkId);
  const findingId = useInvestigation((s) => s.findingId);
  const hopIndex = useInvestigation((s) => s.hopIndex);

  const ladder = useLadder();
  /* The evidence drawer's open state lives in the store (so the one Escape binding can close it);
     the frame owns what it MEANS: it is only ever true at the drawer rung (see the layout effect
     below that clears it off-rung). */
  const drawerOpen = useInvestigation((s) => s.evidenceDrawerOpen);
  /* Seeded from the ladder, NOT from `true`. `Stage` latches `mounted` the first time it is told
     the fabric is visible and never un-latches — so a first render that says "visible" and an
     effect that corrects it one commit later still triggers the lazy `import("../fabric3d/
     Fabric3D")`. Measured on the production build at 375x812: 797,340 bytes of renderer fetched at
     +624 ms on a viewport where the stage is supposed to default to COLLAPSED and the DOM mirror
     stands in for it. `useLadder` reads `matchMedia` synchronously, so the answer IS available on
     the first render; the effect below remains for later breakpoint crossings.
     Seeded from the stage's own CSS-pixel line (`useStageDefault`, 768 px), NOT from the layout
     ladder's `stacked` rung: that rung is in rem, and a media query's rem is the reader's default
     font size. MEASURED (re-grade 2 refuter): keyed on `!ladder.stacked`, a 700 px load at a 12 px
     default seeded the fabric ON and fetched three.js, and a 900 px load at 20 px never fetched it
     (acceptance F4(c); src/app/stage-font-size.test.tsx). */
  const stageDefault = useStageDefault();
  const [fabricChoice, setFabricVisible] = useState(stageDefault);
  /* What the frame shows. Only the stacked layout offers the toggle; every other layout shows the
     stage unconditionally (it begins at 768 px or wider by construction, surfaces.tsx `atLeast`), so
     a "hide" chosen in the stacked layout of a large default font must not leave a wider layout's
     stage on its "Building the 3-D fabric" placeholder with no control to bring it back. */
  const fabricVisible = fabricChoice || !ladder.stacked;
  /* Set the moment the reader uses the fabric toggle. After that the ladder stops overriding the
     choice: a control that silently undoes itself on the next breakpoint crossing is worse than
     no control. */
  const fabricChosen = useRef(false);
  /** The frame's body: where the skip link lands when the stage is not on screen. */
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [evidenceView, setEvidenceView] = useState<EvidenceView>("finding");
  const [alert, setAlert] = useState("");
  const [log, setLog] = useState<readonly string[]>([]);

  const pane: PaneId = paneForSurface(surface);

  const openCite = useCallback((cite: string) => openInspector(cite), []);

  /**
   * Design brief 5.1 step 1: the query bar accepts a Flow. Without this the only route to a path
   * question is the palette's list of pre-computed flows, and a reader with an address in mind has
   * nowhere to type it — `#rail-path` is absent until a flow exists, so the form that would ask
   * for one is not on screen either.
   *
   * The assumptions are announced rather than swallowed. `parseFlowQuery` supplies a protocol when
   * the user gave only a port, and an unstated protocol inside a forwarding verdict is exactly the
   * kind of silent substitution that turns a scoped answer into an apparent fact.
   */
  const submitQuery = useCallback((text: string) => {
    const parsed = parseFlowQuery(text);
    if (parsed === null) return;
    runFlow(parsed.flow);
    /* The text was a question about forwarding, not a search for findings. Leaving it in `query`
       would also run it as a free-text filter, and a pair of IP addresses matches no punchlist
       row — the queue would empty out and read as "nothing is wrong with this path" at the exact
       moment the trace is saying the opposite. Design brief 5.2 step 2: on run, the question
       becomes tokens, which the scope bar now carries. */
    useInvestigation.getState().setQuery("");
    if (parsed.assumptions.length > 0) {
      announce(`${formatFlow(parsed.flow)} traced. ${parsed.assumptions.join(" ")}`);
    }
    /* The header sets the surface to "findings" immediately after calling this, so the path
       surface `runFlow` selected would be overwritten. A microtask lands after both writes and
       before React commits, which puts the reader on the answer they just asked for. Owned here
       rather than in the header because the header cannot know a query was a flow. */
    queueMicrotask(() => useInvestigation.getState().setSurface("path"));
  }, []);

  const appendLog = useCallback((line: string) => {
    setLog((prev) => (prev[prev.length - 1] === line ? prev : [...prev, line].slice(-LOG_LIMIT)));
  }, []);

  /* ── the investigation timeline (design brief 7.5, #sr-log) ──
     Derived from the state that changed rather than emitted at each call site, so a selection made
     from the fabric, the queue, the palette or a shared link all produce the same entry. */
  useEffect(() => {
    if (findingId !== null) appendLog(`Selected finding ${findingId}.`);
  }, [findingId, appendLog]);
  useEffect(() => {
    if (deviceId !== null) appendLog(`Selected device ${deviceId}.`);
  }, [deviceId, appendLog]);
  useEffect(() => {
    if (linkId !== null) appendLog(`Selected link ${linkId}.`);
  }, [linkId, appendLog]);
  useEffect(() => {
    if (trace === null) return;
    const hops = trace.hops.length;
    appendLog(`Trace: ${verdictStatement(trace).sentence} ${hops} hop${hops === 1 ? "" : "s"}.`);
  }, [trace, appendLog]);

  /* Design brief 2.5, and the WCAG 1.4.10 answer for the canvas: below 768px the stage defaults to
     COLLAPSED and the DOM mirror stands in for it, because at that width a 26-node fabric is not
     legible and drawing it anyway is decoration. The INITIAL state is seeded from the same CSS-pixel line
     (see `useState` above); this effect exists for the breakpoint crossings that follow, and it is
     deliberately not the only thing that decides — by the time an effect runs, the stage has
     already latched and the renderer chunk is already on the wire. */
  useEffect(() => {
    if (fabricChosen.current) return;
    setFabricVisible(stageDefault);
  }, [stageDefault]);

  /* Acceptance A4: selecting a hop must re-aim every other surface. The path panel writes only
     `hopIndex`, and the fabric and the hop list both read it — but the evidence rail is keyed on
     the device, so without this the reader steps through a trace while Rail B keeps showing
     whatever was selected before the trace began. Wired here rather than in the path panel because
     the rule is about the shared context, not about that panel. The link is cleared implicitly by
     `selectDevice`, which is correct: a hop names a host, not a cable. */
  /* ...EXCEPT on a URL restore that names its own device. A flow with no trace yet exists only
     after the URL was read (first load or Back; every interactive writer sets flow and trace in
     one batch). If that link also carries `d=`, the reader's device choice IS part of the
     investigation — "dist1 selected while investigating this flow" — and the trace landing on its
     hop must not overwrite it with the hop's host. The restored (flow, hop) pair is recorded here,
     from this render's values, and the hop effect below skips exactly that one landing. A link
     with no `d=` is not recorded, so the device still defaults to the hop's host. Consumed once:
     a later re-run of the same flow, or a hop step, re-aims as before. */
  useEffect(() => {
    if (flow === null || trace !== null) return;
    restoredAim.current = deviceId === null ? null : `${flowKey(flow)}#${hopIndex ?? 0}`;
  }, [flow, trace, deviceId, hopIndex]);

  useEffect(() => {
    if (hopIndex === null || trace === null) return;
    const hop = trace.hops[hopIndex];
    if (hop === undefined) return;
    const landing = `${flowKey(trace.flow)}#${hopIndex}`;
    if (restoredAim.current !== null) {
      const restored = restoredAim.current === landing;
      restoredAim.current = null;
      if (restored) return;
    }
    /* The re-aim says WHO made it (store.ts SelectionOrigin, acceptance A6 over A5): this selection
       is the trace's question, and the fabric draws no blast radius over it — until the reader
       chooses a device, the same host included, which `selectDevice` records as explicit. A landing
       on a host that is already selected claims it the same way: a new trace re-asks the question.
       A selected cable is kept in that case (no selectDevice clears it), exactly as before. */
    const st = useInvestigation.getState();
    if (st.deviceId === hop.host) {
      if (st.deviceOrigin !== "hop") st.hydrate({ deviceOrigin: "hop" });
      return;
    }
    st.selectDevice(hop.host, { origin: "hop" });
  }, [hopIndex, trace]);

  /* A refused link is an error, not a status: it says the state on screen is NOT the state that
     was shared, and a polite region can be missed entirely. */
  useEffect(() => {
    if (urlProblem !== null) setAlert(urlProblem.message);
  }, [urlProblem]);

  const onSurfaceError = useCallback((where: string, err: Error) => {
    setAlert(`${where} stopped rendering: ${err.message}. The rest of the investigation is unchanged.`);
  }, []);

  /* ── theme: one owner, two writers ──
     `commands.ts` has its own `setTheme` and announces the change on `atlas-scope:theme`, but it
     cannot notify `ThemeToggle`'s subscribers, so the header control would keep reporting the
     theme that was in force before the shortcut ran. Re-entering the change through the
     preference store is what keeps the two in agreement. `setThemePreference` does not dispatch
     the event, so this cannot loop. */
  useEffect(() => {
    const onTheme = (e: Event): void => {
      const detail = (e as CustomEvent<unknown>).detail;
      if (detail === "dark" || detail === "light") setThemePreference(detail);
    };
    window.addEventListener("atlas-scope:theme", onTheme);
    return () => window.removeEventListener("atlas-scope:theme", onTheme);
  }, []);

  /* A panel rendered without an explicit citation handler falls back to this event. Nothing else
     listens for it, so without this backstop such a panel would set `inspectorOpen` and leave the
     Inspector pointed at the previous record — the wrong evidence under the right heading. */
  useEffect(() => {
    const onCite = (e: Event): void => {
      const detail = (e as CustomEvent<{ cite?: unknown }>).detail;
      if (detail && typeof detail.cite === "string") setInspectorCite(detail.cite);
    };
    window.addEventListener(OPEN_CITE_EVENT, onCite);
    return () => window.removeEventListener(OPEN_CITE_EVENT, onCite);
  }, []);

  /* ── capabilities the frame owns ──
     Registered through a ref so the registration itself is stable: re-registering on every layout
     change would churn `useCommandTargets` and re-render the palette while it is open. */
  const capabilities = useRef({ ladder, evidenceView });
  capabilities.current = { ladder, evidenceView };

  /* THE DRAWER'S STATE MEANS NOTHING OFF ITS RUNG. It used to be local state that survived a resize:
     open at 1100, resized to 900 and back, the drawer reopened by itself (acceptance D3 discovery,
     2026-09-26). Cleared in the layout phase of the commit that left the rung. Where focus goes when
     the rail stops being shown is not decided here: RailB releases it through the focus-return
     owner on every shown -> hidden transition, whatever caused it. */
  useLayoutEffect(() => {
    if (!ladder.drawer && useInvestigation.getState().evidenceDrawerOpen) useInvestigation.getState().setEvidenceDrawerOpen(false);
  }, [ladder.drawer]);

  /* A LAYOUT CHANGE KEEPS FOCUS IN VIEW. A rung crossing re-flows every region; focus that survives
     it (its region is still shown) can end up anywhere the new layout put it. MEASURED (review/
     audit-d3-focus.mjs drawer pass, 1152 -> 390 px): the drawer's "Finding" radio kept focus, now in
     the stacked evidence section far below the fold — "no part of it is on screen". Runs after the
     rails' own release-on-hide (children's layout effects run first), so it scrolls whatever holds
     focus once the crossing is settled. Not on the first render: nothing has moved yet. CENTRED,
     not "nearest": measured with "nearest" at 390 px, the radio was scrolled to the bottom edge and
     the sticky status bar painted over it (0/9 hit-test points on it, review/audit-d3-focus.mjs). */
  /* The rung of the WHOLE ladder (every LADDER_REM edge, the stylesheet-only wide one included): the
     stylesheet re-flows every region at each of them, whether or not JavaScript lays out anything
     differently there (surfaces.tsx, useRungIndex). */
  const rung = useRungIndex();

  /** Where focus goes when a rail stops being shown and neither its opener nor the place focus
   *  came from can take it (focus-return.ts, third door, step c) — and the last resort of the
   *  layout door below (fourth door, step c). */
  const railFallbacks = useCallback(() => [document.getElementById("stage"), queryField()], []);

  /* A LAYOUT CHANGE NEVER DROPS FOCUS (acceptance D3, the class the independent verifier named
     D3-R2-1). A rung crossing mounts and unmounts whole controls — the pane switch exists only below
     1024 px, its radios only from 768 px, its fabric toggle only below 768 px — and the stage stops
     being rendered below 768 px when the fabric is off, taking every fabric control with it.
     MEASURED on a release build: 11 of 74 tab stops lost to <body> across 7 crossings ('900->1100
     BUTTON.paneswitch__btn "Queue" -> BODY', '768->390 BUTTON.fabric3d__btn "Legend" -> BODY').
     The frame owns the layout, so the frame declares it to the owner: on every commit that changes
     the rung or the fabric's visibility, focus the change took away goes to its documented successor
     (its twin, else the `data-focus-successor` its surface states, else these fallbacks) — never
     <body>. The owner runs it once the commit's layout effects are done (after the rails' own third
     doors, which know more); focusing the successor scrolls it into view. The effect below centres
     focus that SURVIVED the crossing. */
  useReleaseFocusOnLayoutChange(`${rung}|${fabricVisible ? "fabric" : "no-fabric"}`, railFallbacks);

  const lastRung = useRef(rung);
  useLayoutEffect(() => {
    if (lastRung.current === rung) return;
    lastRung.current = rung;
    const a = document.activeElement;
    if (a instanceof HTMLElement && a !== document.body) a.scrollIntoView?.({ block: "center", inline: "nearest" });
    /* AND ONCE THE NEW LAYOUT HAS SETTLED. The crossing's commit is not its last re-flow: MEASURED
       (review/audit-d3-focus.mjs rung-crossing pass, 390 -> 768 px with a trace open), a focused
       citation in the path panel was centred in this commit, then the path panel's measured form
       floor (a ResizeObserver, RailA) re-laid the rail and left it outside the rail's scroller — "no
       part of it is on screen". So it is checked again two frames later and after the settle the
       owner allows a slow step (the drawer's 240 ms), and brought back only if it drifted out of view
       ("nearest": a control still in view does not move under the reader).
       WHATEVER holds focus then, not only the element that held it at the commit: the fourth door may have handed
       focus to a successor in this crossing, and that successor is owed the same.
       AND IF NO SCROLL CAN REVEAL IT, focus moves (focus-return.ts, `releaseFocusLeftUnseen`). MEASURED (review/
       audit-d3-focus.mjs, every recorded run, 768 -> 390 px in four page states): the Inspector's "Copy the citation
       path" stayed focused right of the viewport under `.app`'s `overflow-x: clip` — a clip is not a scroll
       container, so scrollIntoView did nothing and nothing noticed. Checked once the settle is over (400 ms), when
       the layout it judges is the one the reader is left with.
       NOT REDUNDANT WITH THE RESIZE LISTENER BELOW (independent verifier V2-2): the ladder is in rem, so a rung is
       crossed with NO resize event when the reader's default font size changes — then this settle is the only owner
       that runs. Each path is pinned on its own (focus-return.unseen.test.tsx: a crossing by the media queries alone,
       and a resize inside one rung). */
    const keep = (settled: boolean): void => {
      const now = document.activeElement;
      if (!(now instanceof HTMLElement) || now === document.body || !now.isConnected) return;
      now.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      if (settled) releaseFocusLeftUnseen(railFallbacks());
    };
    const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (cb: FrameRequestCallback) => setTimeout(() => cb(0), 16);
    raf(() => raf(() => keep(false)));
    setTimeout(() => keep(true), 400);
  }, [rung, railFallbacks]);

  /* AND AFTER EVERY RESIZE, not only one that crosses a rung (independent verifier V1-4). A resize inside one rung
     re-flows the same layout at another width, and can leave the focused control wholly off screen just as a
     crossing can: MEASURED with an injected offset inside the stacked rung, 700 -> 390 px, focus stayed on a button
     at x = 782..810 for 1.35 s and nothing ran. Once the resizing has stopped for the same 400 ms settle, the owner
     scrolls an unseen focused element into view, and moves focus only if no scroll can reveal it (focus-return.ts,
     `keepFocusSeen`). Focus that is seen is not touched, so a reader who resizes a window around a visible focus
     sees nothing move. */
  useEffect(() => {
    let settle: ReturnType<typeof setTimeout> | null = null;
    const onResize = (): void => {
      if (settle !== null) clearTimeout(settle);
      settle = setTimeout(() => {
        settle = null;
        keepFocusSeen(railFallbacks());
      }, 400);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      if (settle !== null) clearTimeout(settle);
    };
  }, [railFallbacks]);

  useEffect(() => {
    const release = [
      registerCommandTarget("query.focus", () => {
        const el = queryField();
        if (el === null) {
          announce("The query bar is not on screen in this layout.");
          return;
        }
        el.focus();
        el.select();
      }),

      registerCommandTarget("evidence.toggle", () => {
        const { ladder: l } = capabilities.current;
        if (l.drawer) {
          /* Read, write, then announce — never inside a state updater, which StrictMode may run
             twice and which must stay pure. Where focus goes on close is RailB's release on hide. */
          const s = useInvestigation.getState();
          const next = !s.evidenceDrawerOpen;
          s.setEvidenceDrawerOpen(next);
          announce(next ? "Evidence drawer opened." : "Evidence drawer closed.");
          return;
        }
        if (l.singleColumn) {
          useInvestigation.getState().setSurface("evidence");
          announce("Showing the evidence panel.");
          return;
        }
        /* At the reference width the rail is a permanent column. "Toggle" there means "take me to
           it" — collapsing a persistent rail is exactly what design brief 7.1 forbids Escape and
           this key from doing. */
        const el = document.querySelector<HTMLElement>("#rail-evidence button");
        el?.focus();
        announce("The evidence rail is a permanent column at this width. Focus moved into it.");
      }),

      registerCommandTarget("config.open", () => {
        const s = useInvestigation.getState();
        if (s.findingId === null) {
          announce("No finding is selected, so there is no configuration evidence to open.");
          return;
        }
        /* Committed NOW, not whenever React next renders: a closed drawer (or a rail hidden at the
           single-column rung) is `inert` until the commit that shows it (focus-return.ts, third
           door), so the frame below must never run ahead of that commit — from a key, from the
           palette, or from anywhere else this target is called. */
        flushSync(() => {
          setEvidenceView("finding");
          if (capabilities.current.ladder.drawer) s.setEvidenceDrawerOpen(true);
          if (capabilities.current.ladder.singleColumn) s.setSurface("evidence");
        });
        /* A frame, so the pane the button lives in has been committed and styled. Activating the
           button the mouse would activate keeps one behaviour behind one control.
           NOT ALWAYS ONE FRAME. MEASURED (independent verifier, then this cluster, release build, 1100
           px, prefers-reduced-motion: reduce): `v` opened the drawer and the overlay but focus stayed on
           the grid cell. At that frame the rail itself was `visibility: visible`, yet the button's OWN
           computed visibility was still `hidden`: EvidencePane.css's reduced-motion rule gives every
           `.ev *` a 1 ms transition over `all`, so each descendant transitions the visibility it
           inherits, and a hidden -> visible transition reads `hidden` at its start. focus() on it did
           nothing, and neither did the overlay's own heading focus. So wait, a frame at a time and a
           few frames at most, until the button is rendered visible; the stylesheet rule is routed to
           its owner. */
        let frames = 0;
        const activate = (): void => {
          const btn = document.querySelector<HTMLElement>("#rail-evidence .ev-cfgactions button");
          if (btn === null) {
            announce(
              `${s.findingId} names no configuration record that was collected, so there is no configuration text to open for it.`,
            );
            return;
          }
          const rendered = typeof btn.checkVisibility !== "function" || btn.checkVisibility({ visibilityProperty: true });
          frames += 1;
          if (!rendered && frames < CONFIG_OPEN_MAX_FRAMES) {
            requestAnimationFrame(activate);
            return;
          }
          btn.focus();
          btn.click();
        };
        requestAnimationFrame(activate);
      }),
      /* "Go to the evidence rail" at the drawer rung: the rail is a closed overlay there, so the
         move opens it first (commands.ts goToSurface commits this before it moves focus, and
         announces a move only if focus landed). The opener is recorded by RailB as it is shown. */
      registerSurfaceReveal((target) => {
        if (target === "evidence" && capabilities.current.ladder.drawer) useInvestigation.getState().setEvidenceDrawerOpen(true);
      }),
    ];
    return () => {
      for (const r of release) r();
    };
  }, []);

  const notice = urlProblem !== null && !noticeDismissed ? urlProblem : null;

  /* Only in the 768–1023px band. Below 768 every rail is a stacked section and all of them are on
     screen (design brief 2.5), so hiding one there would remove content the ladder says to keep. */
  const railHidden = useMemo(
    () => ({
      a: ladder.singleColumn && pane === "evidence",
      b: ladder.singleColumn && pane !== "evidence",
    }),
    [ladder.singleColumn, pane],
  );

  return (
    <div
      className="app"
      data-surface={surface}
      data-pane={ladder.singleColumn ? pane : undefined}
      data-drawer={ladder.drawer && drawerOpen ? "open" : undefined}
      data-fabric3d={fabricVisible ? "on" : "off"}
    >
      <a
        className="skip-link"
        href="#stage"
        onClick={(e) => {
          /* Below the stacked breakpoint the stage is display:none until the reader turns the fabric
             on, and following "#stage" there moved focus nowhere: MEASURED (review/audit-d3-focus.mjs
             --self-removing, 390x844, pre-fix build) Enter on this link left focus on <body>. With
             no stage on screen, the link skips the header to the first control of the body instead
             (the pane switch and the fabric toggle live there) — the owner decides. */
          const stage = document.getElementById("stage");
          if (stage !== null && stage.getClientRects().length > 0) return;
          e.preventDefault();
          const body = bodyRef.current;
          const first = body?.querySelector<HTMLElement>("a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex='0']");
          returnFocus(null, body, [first]);
        }}
      >
        Skip to the fabric
      </a>

      <ErrorBoundary surface="The header" onError={onSurfaceError}>
        <Header onSubmitQuery={submitQuery} />
      </ErrorBoundary>

      <ErrorBoundary surface="The query bar" onError={onSurfaceError}>
        <QueryBar />
      </ErrorBoundary>

      <div className="app__body" ref={bodyRef}>
        {notice === null ? null : (
          <div className="url-notice" role="presentation">
            <span className="url-notice__mark" aria-hidden="true">
              !
            </span>
            <p className="url-notice__text">{notice.message}</p>
            <button
              type="button"
              className="url-notice__dismiss"
              onClick={(e) => handOffFocus(e.currentTarget, () => setNoticeDismissed(true), [queryField])}
            >
              Dismiss
            </button>
          </div>
        )}

        {ladder.singleColumn || ladder.stacked ? (
          <PaneSwitch
            value={pane}
            onChange={(p) =>
              useInvestigation.getState().setSurface(p === "queue" ? "findings" : p === "path" ? "path" : "evidence")
            }
            pathAvailable={flow !== null}
            showPanes={ladder.singleColumn}
            fabricVisible={fabricVisible}
            onToggleFabric={() => {
              fabricChosen.current = true;
              setFabricVisible((v) => !v);
            }}
            fabricOptional={ladder.stacked}
          />
        ) : null}

        <RailA hidden={railHidden.a} onOpenCite={openCite} fallbacks={railFallbacks} />
        <Stage fabricVisible={fabricVisible} />
        <RailB
          hidden={railHidden.b}
          closed={ladder.drawer && !drawerOpen}
          onOpenCite={openCite}
          view={evidenceView}
          onView={setEvidenceView}
          fallbacks={railFallbacks}
        />
      </div>

      <ErrorBoundary surface="The status bar" onError={onSurfaceError}>
        <LiveStatusBar onOpenCite={openCite} />
      </ErrorBoundary>

      <CommandPalette />
      <ShortcutHelp />

      {/* Design brief 7.5. The containers exist before any text is injected: a live region created
          at the moment it is first written is not announced by most screen readers. */}
      <div id="sr-status" className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {status}
      </div>
      <div id="sr-alert" className="visually-hidden" role="alert" aria-live="assertive" aria-atomic="true">
        {alert}
      </div>
      <div id="sr-log" className="visually-hidden" role="log" aria-live="polite">
        {log.map((line, i) => (
          <p key={`${i}-${line}`}>{line}</p>
        ))}
      </div>
    </div>
  );
}

/**
 * The status bar, subscribed to the live scene telemetry.
 *
 * A component of its own on purpose: `useSceneStats` re-renders its subscriber whenever the scene
 * reports (twice a second at most), and subscribing in `App` would put the entire investigation
 * tree on that timer. This way the readout is live and the four surfaces are not re-rendered for
 * it.
 */
export function LiveStatusBar({ onOpenCite }: { onOpenCite: (cite: string) => void }): ReactElement {
  const stats = useSceneStats();
  return <StatusBar stats={stats} onOpenCite={onOpenCite} />;
}

export default App;
