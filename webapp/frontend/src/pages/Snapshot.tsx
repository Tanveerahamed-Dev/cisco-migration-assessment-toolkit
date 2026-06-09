import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, bandColor, readyColor, sevColor, SnapshotMeta } from "../api";
import { Bars, ErrorBox, Gauge, Loading, SegBar, SevChip, useAsync } from "../components/ui";
import TopologyGraph from "../components/TopologyGraph";

const HEALTH_TONE = (n: number) => (n >= 80 ? "ok" : n >= 60 ? "watch" : n >= 35 ? "risk" : "crit");
const GAUGE_COLOR = (n: number) => (n >= 80 ? "var(--ok)" : n >= 60 ? "var(--watch)" : n >= 35 ? "var(--risk)" : "var(--crit)");

/* ---------- generic, shape-robust section renderer ---------- */
function cell(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.map(cell).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function truncate(s: string, n = 90) { return s.length > n ? s.slice(0, n) + "…" : s; }

function GenericTable({ data }: { data: any }) {
  if (Array.isArray(data)) {
    if (data.length === 0) return <div className="faint" style={{ fontSize: 13 }}>Empty.</div>;
    const first = data[0];
    if (first && typeof first === "object" && !Array.isArray(first)) {
      const cols = Array.from(new Set(data.flatMap((r: any) => Object.keys(r || {})))).slice(0, 8);
      return (
        <div style={{ overflow: "auto" }}>
          <table className="tbl">
            <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {data.slice(0, 200).map((r: any, i: number) => (
                <tr key={i}>{cols.map((c) => <td key={c} title={cell(r?.[c])}>{truncate(cell(r?.[c]))}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    // array of arrays / scalars
    return (
      <div style={{ overflow: "auto" }}>
        <table className="tbl"><tbody>
          {data.slice(0, 200).map((r: any, i: number) => (
            <tr key={i}>{(Array.isArray(r) ? r : [r]).map((v: any, k: number) => <td key={k} title={cell(v)}>{truncate(cell(v))}</td>)}</tr>
          ))}
        </tbody></table>
      </div>
    );
  }
  if (data && typeof data === "object") {
    return (
      <table className="tbl"><tbody>
        {Object.entries(data).map(([k, v]) => (
          <tr key={k}><td style={{ color: "var(--text-dim)", width: 220, fontWeight: 600 }}>{k}</td>
            <td title={cell(v)}>{Array.isArray(v) ? `${v.length} item(s)` : truncate(cell(v), 160)}</td></tr>
        ))}
      </tbody></table>
    );
  }
  return <div className="faint">{cell(data)}</div>;
}

function PunchTable({ rows }: { rows: any[] }) {
  return (
    <div style={{ overflow: "auto" }}>
      <table className="tbl">
        <thead><tr><th>Sev</th><th>Category</th><th>Devices</th><th>Title</th><th>Detail</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><SevChip sev={r.severity} /></td>
              <td className="dim">{r.category}</td>
              <td className="mono" style={{ fontSize: 12 }}>{(r.devices || []).join(", ") || "—"}</td>
              <td><b>{r.title}</b></td>
              <td className="dim" title={r.detail} style={{ maxWidth: 360 }}>{truncate(r.detail || "", 140)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectionPane({ snapId, name }: { snapId: number; name: string }) {
  const { data, error, loading } = useAsync(() => api.section(snapId, name), [snapId, name]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox msg={error} />;
  const d = data!.data;
  if (name === "punchlist" && Array.isArray(d)) return <PunchTable rows={d} />;
  return <GenericTable data={d} />;
}

function Keystones({ meta }: { meta: SnapshotMeta }) {
  const ks = meta.summary.keystones || [];
  if (!ks.length) return null;
  return (
    <div className="panel">
      <h3>Keystone devices · fleet depends on these most</h3>
      <table className="tbl">
        <thead><tr><th>Device</th><th>Severity</th><th className="num">Stranded</th><th className="num">VLANs</th><th>Impact</th></tr></thead>
        <tbody>
          {ks.map((k, i) => (
            <tr key={i}>
              <td className="mono"><b>{k.host || k.device || "—"}</b></td>
              <td>{k.severity ? <SevChip sev={k.severity} /> : "—"}</td>
              <td className="num">{k.stranded ?? "—"}</td>
              <td className="num">{k.vlans_impacted ?? "—"}</td>
              <td className="dim" title={k.detail} style={{ maxWidth: 380 }}>{truncate(k.detail || "", 120)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeliverablesPanel({ snapId }: { snapId: number }) {
  const { data } = useAsync(() => api.meta(), []);
  const items = data?.deliverables || [];
  if (!items.length) return null;
  return (
    <div className="panel">
      <h3>Deliverables · generated from this snapshot</h3>
      <div className="row-flex">
        {items.map((d) =>
          d.available ? (
            <a key={d.key} className="btn" href={api.deliverableUrl(snapId, d.key)} download>
              ↓ {d.label} <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>{d.ext.toUpperCase()}</span>
            </a>
          ) : (
            <span key={d.key} className="btn" style={{ opacity: 0.45, cursor: "not-allowed" }}
              title="Unavailable — the server is missing the optional library for this format">
              {d.label} <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>{d.ext.toUpperCase()}</span>
            </span>
          ),
        )}
        <a className="btn" href={api.explorerUrl(snapId)} target="_blank" rel="noreferrer">
          ◈ Interactive Explorer <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>HTML</span>
        </a>
      </div>
      <div className="faint" style={{ fontSize: 11, marginTop: 10 }}>
        Each is produced by the engine's own writer from this exact snapshot — identical to the CLI output.
      </div>
    </div>
  );
}

export default function SnapshotPage() {
  const { id } = useParams();
  const sid = Number(id);
  const { data: meta, error, loading } = useAsync(() => api.getSnapshot(sid), [sid]);
  const [tab, setTab] = useState<string>("");
  const [showExplorer, setShowExplorer] = useState(false);

  if (loading) return <div className="container"><Loading /></div>;
  if (error) return <div className="container"><ErrorBox msg={error} /></div>;
  const s = meta!.summary;
  const avg = typeof s.avg_health === "number" ? s.avg_health : Number(s.avg_health) || 0;
  const eol = s.lifecycle?.past_eos;

  const tabs = s.sections;
  const activeTab = tab || (tabs[0]?.key ?? "");

  return (
    <div className="container">
      <div className="breadcrumb">
        <Link to="/campaigns">Campaigns</Link> / <Link to={`/campaigns/${meta!.campaign_id}`}>campaign</Link> / {meta!.label}
      </div>
      <div className="page-head">
        <div>
          <h1>{meta!.label}</h1>
          <div className="sub">{meta!.n_devices} devices · engine {meta!.script_version || s.version} · uploaded {new Date(meta!.uploaded_at).toLocaleString()}</div>
        </div>
        <span style={{ flex: 1 }} />
        <a className="btn" href={api.explorerUrl(sid)} target="_blank" rel="noreferrer">↗ Explorer (new tab)</a>
        <button className="btn primary" onClick={() => setShowExplorer((v) => !v)}>{showExplorer ? "Hide" : "◈ Open"} explorer</button>
      </div>

      {/* KPI hero */}
      <div className="grid" style={{ gridTemplateColumns: "auto 1fr 1fr 1fr", gap: 16, alignItems: "stretch" }}>
        <div className="panel" style={{ display: "grid", placeItems: "center" }}>
          <Gauge value={avg} color={GAUGE_COLOR(avg)} label="avg health" />
        </div>
        <div className={`panel kpi ${s.n_critical > 0 ? "crit" : "ok"}`}>
          <div className="l">Critical-band switches</div>
          <div className="v">{s.n_critical}</div>
          <div className="hint">of {s.n_switches} switches</div>
        </div>
        <div className={`panel kpi ${HEALTH_TONE(100 - Math.min(100, s.punchlist.crit_high * 8))}`}>
          <div className="l">Punch-list (crit/high)</div>
          <div className="v">{s.punchlist.crit_high}<span className="faint" style={{ fontSize: 16, fontWeight: 600 }}> / {s.punchlist.total}</span></div>
          <div className="hint">prioritised actions</div>
        </div>
        <div className={`panel kpi ${s.readiness["NOT READY"] > 0 ? "crit" : s.readiness.CAUTION > 0 ? "watch" : "ok"}`}>
          <div className="l">Move-group readiness</div>
          <div className="v" style={{ fontSize: 20, display: "flex", gap: 12 }}>
            <span style={{ color: readyColor("READY") }}>{s.readiness.READY}✓</span>
            <span style={{ color: readyColor("CAUTION") }}>{s.readiness.CAUTION}!</span>
            <span style={{ color: readyColor("NOT READY") }}>{s.readiness["NOT READY"]}✕</span>
          </div>
          <div className="hint">ready · caution · not ready{eol ? ` · ${eol} past-EoS` : ""}</div>
        </div>
      </div>

      {/* distributions */}
      <div className="grid cols-3" style={{ marginTop: 16 }}>
        <div className="panel"><h3>Health bands</h3><SegBar data={s.bands} colorFor={bandColor} /></div>
        <div className="panel"><h3>Punch-list by severity</h3><Bars data={s.punchlist.by_severity} colorFor={sevColor} /></div>
        <div className="panel"><h3>Punch-list by category</h3><Bars data={s.punchlist.by_category} /></div>
      </div>

      <div className="grid" style={{ marginTop: 16, gap: 16 }}>
        <DeliverablesPanel snapId={sid} />

        <div className="panel">
          <h3>Fleet topology · coloured by health band</h3>
          <TopologyGraph snapId={sid} />
        </div>

        <Keystones meta={meta!} />

        {showExplorer && (
          <div className="panel" style={{ padding: 0, overflow: "hidden" }}>
            <iframe title="Network Migration Explorer" src={api.explorerUrl(sid)}
              style={{ width: "100%", height: "78vh", border: 0, display: "block", background: "var(--bg)" }} />
          </div>
        )}

        {/* detail sections */}
        {tabs.length > 0 && (
          <div className="panel">
            <div className="tabs" style={{ marginBottom: 16 }}>
              {tabs.map((t) => (
                <button key={t.key} className={activeTab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>
                  {t.label}<span className="ct">{t.count}</span>
                </button>
              ))}
            </div>
            <SectionPane snapId={sid} name={activeTab} />
          </div>
        )}
      </div>
    </div>
  );
}
