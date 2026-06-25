import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import Landing from "./pages/Landing";
import Dashboard from "./pages/Dashboard";
import CampaignPage from "./pages/Campaign";
import SnapshotPage from "./pages/Snapshot";
import ExecutionPage from "./pages/Execution";
import { ErrorBoundary } from "./components/ErrorBoundary";

function useTheme() {
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("assesshub-theme") || "dark");
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("assesshub-theme", theme);
  }, [theme]);
  return { theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) };
}

function TopBar() {
  const { theme, toggle } = useTheme();
  return (
    <header className="topbar">
      <Link to="/" className="brand" style={{ color: "var(--text)" }}>
        <span className="mark" /> AssessHub <span className="ver">migration cockpit</span>
      </Link>
      <span className="spacer" />
      <nav>
        <NavLink to="/" end>Home</NavLink>
        <NavLink to="/campaigns">Campaigns</NavLink>
      </nav>
      <button className="btn ghost" onClick={toggle} title="Toggle theme" aria-label="Toggle theme">
        {theme === "dark" ? "☀" : "☾"}
      </button>
    </header>
  );
}

export default function App() {
  const location = useLocation();
  return (
    <>
      <TopBar />
      {/* WEBAP-01: a render crash in any one route/panel must degrade to a recoverable card, not white-screen
          the whole SPA. The boundary is keyed by pathname so navigating (the TopBar nav lives ABOVE it) remounts
          it fresh and clears a prior error. */}
      <ErrorBoundary key={location.pathname}>
        <Routes location={location}>
          <Route path="/" element={<Landing />} />
          <Route path="/campaigns" element={<Dashboard />} />
          <Route path="/campaigns/:id" element={<CampaignPage />} />
          <Route path="/snapshots/:id" element={<SnapshotPage />} />
          <Route path="/executions/:id" element={<ExecutionPage />} />
          <Route path="*" element={<div className="container"><div className="empty">Not found. <Link to="/">Go home</Link></div></div>} />
        </Routes>
      </ErrorBoundary>
    </>
  );
}
