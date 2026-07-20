import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import Landing from "./pages/Landing";
import Dashboard from "./pages/Dashboard";
import CampaignPage from "./pages/Campaign";
import SnapshotPage from "./pages/Snapshot";
import ExecutionPage from "./pages/Execution";
import AboutPage from "./pages/About";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { useViewTransition } from "./components/ui";
import { api } from "./api";
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
  useEffect(() => {
    // Fire-and-forget: an unreachable API leaves the fallback brand (the SPA still renders).
    api.meta()
      .then((m) => {
        setApp(m.app ?? null);
        if (m.app?.name) document.title = `${m.app.name} — Network Migration Assessment`;
      })
      .catch(() => {});
  }, []);
  return (
    <>
      <TopBar app={app} />
      {/* WEBAP-01: a render crash in any one route/panel must degrade to a recoverable card, not white-screen
          the whole SPA. The boundary is keyed by pathname so navigating (the TopBar nav lives ABOVE it) remounts
          it fresh and clears a prior error. Keyed to `shown` (the LAGGED pathname), never `location` directly —
          keying to `location` would remount the boundary, and destroy the outgoing page, before the view
          transition below gets to snapshot it, silently defeating the whole mechanism. */}
      <ErrorBoundary key={shown.pathname}>
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
