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
import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { SEVERITY_ORDER } from "../core/types";
import { OPEN_CITE_EVENT } from "../panels/DevicePane";
import { openInspector, setInspectorCite } from "../panels/Inspector";
import { flowKey } from "../panels/PathTrace";
import { Chip } from "../ui/primitives";
import { CommandPalette } from "./CommandPalette";
import {
  announce,
  formatFlow,
  parseFlowQuery,
  registerCommandTarget,
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
import { PaneSwitch, RailA, RailB, Stage, paneForSurface, useLadder, type EvidenceView, type PaneId } from "./surfaces";
import { useUrlSync } from "./urlSync";
import "./App.css";

/* The investigation log is append-only and bounded. Unbounded, it would grow for the length of a
   session and a screen reader walking it would have to traverse every step ever taken. */
const LOG_LIMIT = 24;

/* ── the query bar: the investigation question as removable tokens ─────────── */

function QueryBar(): ReactElement {
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
      <Chip key="q" mono removeLabel="Remove the free-text query" onRemove={() => setQuery("")}>
        {query}
      </Chip>,
    );
  }
  for (const s of SEVERITY_ORDER) {
    if (!severities.has(s)) continue;
    tokens.push(
      <Chip key={`sev-${s}`} tone="accent" removeLabel={`Remove the ${s} severity filter`} onRemove={() => toggleSeverity(s)}>
        {`severity ${s}`}
      </Chip>,
    );
  }
  for (const r of [...roles].sort()) {
    tokens.push(
      <Chip key={`role-${r}`} tone="accent" removeLabel={`Remove the ${r} role filter`} onRemove={() => toggleRole(r)}>
        {`role ${r}`}
      </Chip>,
    );
  }
  if (onlyUncollected) {
    tokens.push(
      <Chip
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
      <Chip key="f" mono removeLabel={`Deselect finding ${findingId}`} onRemove={() => selectFinding(null)}>
        {`finding ${findingId}`}
      </Chip>,
    );
  }
  if (deviceId !== null) {
    tokens.push(
      <Chip key="d" mono removeLabel={`Deselect device ${deviceId}`} onRemove={() => selectDevice(null)}>
        {`device ${deviceId}`}
      </Chip>,
    );
  }
  if (linkId !== null) {
    tokens.push(
      <Chip key="l" mono removeLabel={`Deselect link ${linkId}`} onRemove={() => selectLink(null)}>
        {`link ${linkId}`}
      </Chip>,
    );
  }
  if (flow !== null) {
    const label = `${flow.srcIp} to ${flow.dstIp} ${flow.protocol}${flow.dstPort === null ? "" : `:${flow.dstPort}`}`;
    tokens.push(
      <Chip
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
        {tokens.length === 0 ? (
          <p className="qbar__empty">
            {`Nothing is selected and no filter is applied, so every record in this snapshot is in scope: all ${fabric.devices.length} devices and all ${fabric.findings.length} findings.`}
          </p>
        ) : (
          <div className="qbar__tokens" role="group" aria-labelledby="qbar-label">
            {tokens}
          </div>
        )}
        {tokens.length === 0 ? null : (
          <button type="button" className="qbar__clear" onClick={clearAll}>
            Clear scope
          </button>
        )}
      </div>
    </div>
  );
}

/* ── the shell ─────────────────────────────────────────────────────────────── */

export function App(): ReactElement {
  /* Both are ref-counted, and the palette and the help sheet ask for them too. Asking here means
     the bindings exist even in a build where one of those layers is not rendered. */
  useGlobalKeyboard();
  useAppCommands();

  const urlProblem = useUrlSync();
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
  const [drawerOpen, setDrawerOpen] = useState(false);
  /* Seeded from the ladder, NOT from `true`. `Stage` latches `mounted` the first time it is told
     the fabric is visible and never un-latches — so a first render that says "visible" and an
     effect that corrects it one commit later still triggers the lazy `import("../fabric3d/
     Fabric3D")`. Measured on the production build at 375x812: 797,340 bytes of renderer fetched at
     +624 ms on a viewport where the stage is supposed to default to COLLAPSED and the DOM mirror
     stands in for it. `useLadder` reads `matchMedia` synchronously, so the answer IS available on
     the first render; the effect below remains for later breakpoint crossings. */
  const [fabricVisible, setFabricVisible] = useState(!ladder.stacked);
  /* Set the moment the reader uses the fabric toggle. After that the ladder stops overriding the
     choice: a control that silently undoes itself on the next breakpoint crossing is worse than
     no control. */
  const fabricChosen = useRef(false);
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
    appendLog(`Trace ${trace.outcome}: ${hops} hop${hops === 1 ? "" : "s"}.`);
  }, [trace, appendLog]);

  /* Design brief 2.5, and the WCAG 1.4.10 answer for the canvas: below 768px the stage defaults to
     COLLAPSED and the DOM mirror stands in for it, because at that width a 26-node fabric is not
     legible and drawing it anyway is decoration. The INITIAL state is seeded from the same ladder
     (see `useState` above); this effect exists for the breakpoint crossings that follow, and it is
     deliberately not the only thing that decides — by the time an effect runs, the stage has
     already latched and the renderer chunk is already on the wire. */
  useEffect(() => {
    if (fabricChosen.current) return;
    setFabricVisible(!ladder.stacked);
  }, [ladder.stacked]);

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
  const restoredAim = useRef<string | null>(null);
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
    if (useInvestigation.getState().deviceId === hop.host) return;
    useInvestigation.getState().selectDevice(hop.host);
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
  const capabilities = useRef({ drawerOpen, ladder, evidenceView });
  capabilities.current = { drawerOpen, ladder, evidenceView };

  useEffect(() => {
    const release = [
      registerCommandTarget("query.focus", () => {
        const el = document.querySelector<HTMLInputElement>('#app-header form[role="search"] input');
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
          setDrawerOpen((v) => {
            announce(v ? "Evidence drawer closed." : "Evidence drawer opened.");
            return !v;
          });
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
        setEvidenceView("finding");
        if (capabilities.current.ladder.drawer) setDrawerOpen(true);
        if (capabilities.current.ladder.singleColumn) s.setSurface("evidence");
        /* One frame, so the pane the button lives in has been committed. Activating the button the
           mouse would activate keeps one behaviour behind one control. */
        requestAnimationFrame(() => {
          const btn = document.querySelector<HTMLElement>("#rail-evidence .ev-cfgactions button");
          if (btn === null) {
            announce(
              `${s.findingId} names no configuration record that was collected, so there is no configuration text to open for it.`,
            );
            return;
          }
          btn.focus();
          btn.click();
        });
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
      <a className="skip-link" href="#stage">
        Skip to the fabric
      </a>

      <ErrorBoundary surface="The header" onError={onSurfaceError}>
        <Header onSubmitQuery={submitQuery} />
      </ErrorBoundary>

      <ErrorBoundary surface="The query bar" onError={onSurfaceError}>
        <QueryBar />
      </ErrorBoundary>

      <div className="app__body">
        {notice === null ? null : (
          <div className="url-notice" role="presentation">
            <span className="url-notice__mark" aria-hidden="true">
              !
            </span>
            <p className="url-notice__text">{notice.message}</p>
            <button type="button" className="url-notice__dismiss" onClick={() => setNoticeDismissed(true)}>
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

        <RailA hidden={railHidden.a} onOpenCite={openCite} />
        <Stage fabricVisible={fabricVisible} />
        <RailB hidden={railHidden.b} onOpenCite={openCite} view={evidenceView} onView={setEvidenceView} />
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
