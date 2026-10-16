import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router";
import { api, type AppIdentity, type Campaign } from "../../api";
import { useViewTransition } from "../../components/ui";

export function AtlasRail({ app }: { app: AppIdentity | null }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [theme, setTheme] = useState(() => localStorage.getItem("assesshub-theme") || "dark");
  const run = useViewTransition();
  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); localStorage.setItem("assesshub-theme", theme); }, [theme]);
  useEffect(() => { let active = true; setError(""); api.listCampaigns().then((rows) => { if (active) setCampaigns(rows); }).catch(() => { if (active) setError("Engagement list unavailable."); }); return () => { active = false; }; }, [retry]);
  return <aside className="atlas-rail" aria-label="Engagement rail">
    <Link to="/engagements" className="brand"><svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="12" fill="none" stroke="currentColor" strokeWidth="2" /><circle cx="14" cy="14" r="4" fill="currentColor" /><path d="M14 2v6M14 20v6M2 14h6M20 14h6" stroke="currentColor" strokeWidth="2" /></svg>{app?.name ?? "AssessHub"}<span className="ver">{app?.byline ?? "migration cockpit"}</span></Link>
    <nav aria-label="Application navigation"><NavLink to="/engagements">Engagements</NavLink>
      {campaigns.map((item) => <NavLink key={item.id} to={`/engagements/${item.id}`}><strong>{item.name}</strong><small>{item.description}</small></NavLink>)}
      {error && <p className="dim" role="alert">{error} <button className="btn" onClick={() => setRetry((value) => value + 1)}>Retry engagements</button></p>}
      <button className="btn ghost" disabled title="Assessment creation will follow in a later increment">＋ New assessment <small>Coming next</small></button>
    </nav>
    <div className="atlas-rail-footer"><Link to="/campaigns">Classic view</Link><Link to="/about">About</Link><button className="btn ghost" aria-label="Toggle theme" onClick={() => run(() => setTheme((value) => value === "dark" ? "light" : "dark"))}>{theme === "dark" ? "☀" : "☾"}</button></div>
  </aside>;
}
