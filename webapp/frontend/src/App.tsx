import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import Landing from "./pages/Landing";
import Dashboard from "./pages/Dashboard";
import CampaignPage from "./pages/Campaign";
import SnapshotPage from "./pages/Snapshot";
import ExecutionPage from "./pages/Execution";
import AboutPage from "./pages/About";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { useViewTransition } from "./components/ui";
import { api, ApiError } from "./api";
import type { AppIdentity } from "./api";

function useTheme() {
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("assesshub-theme") || "dark");
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("assesshub-theme", theme);
  }, [theme]);
  return { theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) };
}

// ADR-0004 D1: the brand comes from /api/meta (fed by cisco_toolkit/brand_tokens.py — the SSOT).
// "AssessHub / migration cockpit" survives only as the pre-load / API-down fallback.
function TopBar({ app }: { app: AppIdentity | null }) {
  const { theme, toggle } = useTheme();
  // Same view-transition machinery as route changes (Unit 24): startViewTransition snapshots the
  // pre-toggle palette, flushSync commits the flip (+ useTheme's data-theme effect), then the UA
  // cross-fades old->new for free — no manual color tweening.
  const run = useViewTransition();
  return (
    <header className="topbar">
      <Link to="/" className="brand" style={{ color: "var(--text)" }}>
        <span className="mark" /> {app?.name ?? "AssessHub"}{" "}
        <span className="ver">{app?.byline ?? "migration cockpit"}</span>
      </Link>
      <span className="spacer" />
      <nav>
        <NavLink to="/" end>Home</NavLink>
        <NavLink to="/campaigns">Campaigns</NavLink>
        <NavLink to="/about">About</NavLink>
      </nav>
      <button className="btn ghost" onClick={() => run(toggle)} title="Toggle theme" aria-label="Toggle theme">
        {theme === "dark" ? "☀" : "☾"}
      </button>
    </header>
  );
}

export default function App() {
  const location = useLocation();
  const run = useViewTransition();
  // Lags one render behind the router: Routes below renders `shown`, not `location`, so
  // startViewTransition can snapshot the OUTGOING page before it's replaced. The effect only
  // catches `shown` up once a real navigation lands (key changes) — flushSync (inside run) makes
  // that catch-up synchronous, either inside the transition callback or, under reduced motion /
  // unsupported browsers, immediately.
  const [shown, setShown] = useState(location);
  useEffect(() => {
    if (shown.key === location.key) return;
    run(() => setShown(location));
  }, [location, shown, run]);

  const [app, setApp] = useState<AppIdentity | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [token, setToken] = useState("");
  const [authError, setAuthError] = useState("");
  const [authGeneration, setAuthGeneration] = useState(0);

  const applyIdentity = (identity: AppIdentity | null) => {
    setApp(identity);
    if (identity?.name) document.title = `${identity.name} — Network Migration Assessment`;
  };

  useEffect(() => {
    // An unreachable API leaves the fallback brand. A 401 means token mode is active, so expose
    // the shipped browser-session exchange rather than leaving every route permanently broken.
    api.meta()
      .then((m) => applyIdentity(m.app ?? null))
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) setAuthRequired(true);
      });
  }, []);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setAuthError("");
    try {
      await api.authenticate(token);
      // Prove the HttpOnly cookie is usable before dismissing the gate.
      const meta = await api.meta();
      applyIdentity(meta.app ?? null);
      setToken("");
      setAuthRequired(false);
      // Pages may have mounted and received their own 401 before the meta probe exposed the
      // sign-in gate. Remount the routed page so every data request retries with the new cookie.
      setAuthGeneration((generation) => generation + 1);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Authentication failed.");
    }
  }

  return (
    <>
      <TopBar app={app} />
      {authRequired && (
        <div className="auth-overlay">
          <form className="auth-card" role="dialog" aria-modal="true"
                aria-labelledby="auth-title" onSubmit={signIn}>
            <h2 id="auth-title">Atlas sign-in</h2>
            <p className="muted">
              This server requires its ASSESSHUB_TOKEN. The token is exchanged for an HttpOnly
              same-site browser session and is not saved in local storage.
            </p>
            <label htmlFor="atlas-token">API token</label>
            <input id="atlas-token" type="password" value={token} autoFocus autoComplete="off"
                   onChange={(event) => setToken(event.target.value)} />
            {authError && <div className="auth-error" role="alert">{authError}</div>}
            <button className="btn primary" type="submit" disabled={!token}>Sign in</button>
          </form>
        </div>
      )}
      {/* WEBAP-01: a render crash in any one route/panel must degrade to a recoverable card, not white-screen
          the whole SPA. The boundary is keyed by pathname so navigating (the TopBar nav lives ABOVE it) remounts
          it fresh and clears a prior error. Keyed to `shown` (the LAGGED pathname), never `location` directly —
          keying to `location` would remount the boundary, and destroy the outgoing page, before the view
          transition below gets to snapshot it, silently defeating the whole mechanism. */}
      <ErrorBoundary key={`${shown.pathname}:${authGeneration}`}>
        <Routes location={shown}>
          <Route path="/" element={<Landing />} />
          <Route path="/campaigns" element={<Dashboard />} />
          <Route path="/campaigns/:id" element={<CampaignPage />} />
          <Route path="/snapshots/:id" element={<SnapshotPage />} />
          <Route path="/executions/:id" element={<ExecutionPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="*" element={<div className="container"><div className="empty">Not found. <Link to="/">Go home</Link></div></div>} />
        </Routes>
      </ErrorBoundary>
    </>
  );
}
