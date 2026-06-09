import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, bandColor, Campaign } from "../api";
import { ErrorBox, Loading, SegBar, useAsync, useToast } from "../components/ui";

function PostureStrip({ c }: { c: Campaign }) {
  const s = c.latest_summary;
  if (!s) return <div className="faint" style={{ fontSize: 12, marginTop: 10 }}>No snapshots yet.</div>;
  return (
    <div style={{ marginTop: 14 }}>
      <div className="row-flex" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <span className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".5px" }}>Latest posture</span>
        <span className="dim" style={{ fontSize: 12 }}>
          {s.n_switches} switches · avg {s.avg_health || "—"}/100 · {s.punchlist.crit_high} crit/high
        </span>
      </div>
      <SegBar data={s.bands} colorFor={bandColor} />
    </div>
  );
}

export default function Dashboard() {
  const nav = useNavigate();
  const { toast, node } = useToast();
  const { data, error, loading, reload } = useAsync(() => api.listCampaigns(), []);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);

  async function create() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const c = await api.createCampaign(name, desc);
      setCreating(false); setName(""); setDesc("");
      nav(`/campaigns/${c.id}`);
    } catch (e: any) { toast(e.message); } finally { setBusy(false); }
  }
  async function seed() {
    setBusy(true);
    try { const r = await api.seedDemo(); toast("Sample fleet added."); reload(); nav(`/campaigns/${r.campaign.id}`); }
    catch (e: any) { toast(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="container">
      <div className="page-head">
        <div>
          <h1>Campaigns</h1>
          <div className="sub">Each campaign is a fleet tracked across migration waves.</div>
        </div>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={seed} disabled={busy}>＋ Sample fleet</button>
        <button className="btn primary" onClick={() => setCreating((v) => !v)}>＋ New campaign</button>
      </div>

      {creating && (
        <div className="panel pad-lg" style={{ marginBottom: 18 }}>
          <h3>New campaign</h3>
          <label className="field"><span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. DC-East core refresh" autoFocus />
          </label>
          <label className="field"><span>Description (optional)</span>
            <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Scope, target dates…" />
          </label>
          <div className="row-flex">
            <button className="btn primary" onClick={create} disabled={busy || !name.trim()}>Create</button>
            <button className="btn ghost" onClick={() => setCreating(false)}>Cancel</button>
          </div>
        </div>
      )}

      {loading ? <Loading /> : error ? <ErrorBox msg={error} /> : !data?.length ? (
        <div className="panel"><div className="empty">
          No campaigns yet.<br />
          <div className="row-flex" style={{ justifyContent: "center", marginTop: 16 }}>
            <button className="btn primary" onClick={seed} disabled={busy}>Load the sample fleet</button>
          </div>
        </div></div>
      ) : (
        <div className="grid auto">
          {data.map((c) => (
            <Link to={`/campaigns/${c.id}`} key={c.id} className="panel" style={{ color: "inherit", textDecoration: "none", display: "block" }}>
              <div className="spread">
                <h3 style={{ textTransform: "none", letterSpacing: 0, fontSize: 16, color: "var(--text)", margin: 0 }}>{c.name}</h3>
                <span className="chip">{c.n_snapshots || 0} wave{(c.n_snapshots || 0) === 1 ? "" : "s"}</span>
              </div>
              {c.description && <div className="dim" style={{ fontSize: 13, marginTop: 6 }}>{c.description}</div>}
              <PostureStrip c={c} />
            </Link>
          ))}
        </div>
      )}
      {node}
    </div>
  );
}
