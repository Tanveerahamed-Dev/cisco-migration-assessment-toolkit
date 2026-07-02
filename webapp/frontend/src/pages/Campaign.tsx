import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, bandColor, gateColor } from "../api";
import type { GateRecord } from "../api";
import { ErrorBox, Loading, SegBar, useAsync, useToast } from "../components/ui";

const NEXT_DECISION: Record<string, string> = { pending: "go", go: "no-go", "no-go": "slipped", slipped: "pending" };

function GateBoard({ id, latest, toast }: { id: number; latest: number; toast: (m: string) => void }) {
  // `latest` (newest snapshot id) is a dependency so uploading/ingesting a snapshot refetches the
  // derivable waves (V3.23.159 — the board previously kept the old snapshot's waves until remount).
  const { data, error, reload } = useAsync(() => api.getGates(id), [id, latest]);
  const [signer, setSigner] = useState("");
  const [busy, setBusy] = useState(false);
  // The POST response already carries the authoritative records — apply it locally instead of a
  // second round-trip GET; a real refetch (deps change) supersedes the optimistic list.
  const [recOverride, setRecOverride] = useState<GateRecord[] | null>(null);
  useEffect(() => setRecOverride(null), [data]);

  // Keep the last data rendered through a refetch (no unmount-flash); surface a failed load
  // instead of silently vanishing (V3.23.159).
  if (!data) {
    if (error) {
      return (
        <div className="panel">
          <h3>Gate board · T-minus sign-offs</h3>
          <ErrorBox msg={error} />
        </div>
      );
    }
    return null;
  }
  const records = recOverride ?? data.records;
  // union: waves derivable from the latest snapshot + any wave that already has recorded history
  const waves = Array.from(new Set([...data.waves, ...records.map((r) => r.wave)]));
  if (waves.length === 0) return null;
  const rec = new Map(records.map((r) => [`${r.wave}|${r.gate}`, r]));

  async function cycle(wave: string, gate: string) {
    if (busy) return; // one decision in flight — a double-click must not re-read stale state
    const r = rec.get(`${wave}|${gate}`);
    const next = NEXT_DECISION[r?.decision || "pending"] || "go";
    // Advancing a signed gate must not erase its trail: a typed signer wins, otherwise the
    // existing signer and note carry forward (V3.23.159 — empty re-posts were stomping them).
    const by = signer.trim() || r?.signed_by || "";
    const note = r?.note || "";
    setBusy(true);
    try {
      const resp = await api.setGate(id, wave, gate, next, by, note);
      setRecOverride(resp.records);
    } catch (e: any) {
      toast(e.message);
      reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <div className="spread" style={{ marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>Gate board · T-minus sign-offs</h3>
        <input value={signer} onChange={(e) => setSigner(e.target.value)} placeholder="signed by…"
          style={{ width: 140, fontSize: 12 }} />
      </div>
      <div className="dim" style={{ fontSize: 12.5, marginBottom: 12 }}>
        Click a cell to cycle pending → GO → NO-GO → SLIPPED → pending. Decisions are recorded
        against this campaign and land in the Engagement Workflow &amp; Plan of Record (§4.3 “Gate
        record (as signed)”) the next time it is downloaded.
      </div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: `minmax(90px, auto) repeat(${data.cadence.length}, 1fr)`, gap: 6, minWidth: 640 }}>
          <span />
          {data.cadence.map((g) => (
            <div key={g.key} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 11.5, fontWeight: 700 }}>{g.label}</div>
              <div className="faint mono" style={{ fontSize: 10.5 }}>{g.when}</div>
            </div>
          ))}
          {waves.map((w) => (
            <Fragment key={w}>
              <span className="chip mono" style={{ alignSelf: "center" }}>{w}</span>
              {data.cadence.map((g) => {
                const r = rec.get(`${w}|${g.key}`);
                const d = r?.decision || "pending";
                const tip = r ? `${d.toUpperCase()} — ${r.signed_by || "unsigned"} · ${new Date(r.decided_at).toLocaleString()}${r.note ? ` · ${r.note}` : ""}` : "pending — click to sign";
                return (
                  <span key={`${w}|${g.key}`} role="button" tabIndex={0} className="chip gate"
                    onClick={() => cycle(w, g.key)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); cycle(w, g.key); } }}
                    data-wave={w} data-gate={g.key} title={tip}
                    style={{ ["--gc" as any]: gateColor(d === "pending" ? "PENDING" : d.toUpperCase()), cursor: "pointer", justifyContent: "center", fontSize: 11, opacity: busy ? 0.65 : 1 }}>
                    {d === "pending" ? "—" : d.toUpperCase()}
                  </span>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
    </div>
  );
}

const DIR_ICON: Record<string, string> = { improving: "▲", worsening: "▼", flat: "▬" };
const DIR_COLOR: Record<string, string> = { improving: "var(--ok)", worsening: "var(--crit)", flat: "var(--text-faint)" };
const VERDICT_COLOR: Record<string, string> = {
  // campaign-trend vocabulary (compute_campaign_trend)
  IMPROVING: "var(--ok)", REGRESSING: "var(--crit)", MIXED: "var(--watch)", FLAT: "var(--text-dim)", INSUFFICIENT: "var(--text-faint)",
  // snapshot_delta vocabulary (compute_snapshot_delta) — the 'Compare two waves' panel reuses this map; without
  // these keys cmp.verdict (CLEAN/REVIEW/REGRESSED) fell through to a flat dim chip, never colored (audit-5 CA#5).
  CLEAN: "var(--ok)", REVIEW: "var(--watch)", REGRESSED: "var(--crit)",
};

function Trend({ id }: { id: number }) {
  const { data, loading } = useAsync(() => api.trend(id), [id]);
  if (loading || !data) return null;
  if (data.verdict === "INSUFFICIENT") {
    return <div className="panel"><h3>Campaign trajectory</h3><div className="dim" style={{ fontSize: 13 }}>{data.verdict_note}</div></div>;
  }
  return (
    <div className="panel">
      <div className="spread" style={{ marginBottom: 14 }}>
        <h3 style={{ margin: 0 }}>Campaign trajectory</h3>
        <span className="chip" style={{ color: VERDICT_COLOR[data.verdict], borderColor: VERDICT_COLOR[data.verdict] }}>
          <span className="dot" /> {data.verdict}
        </span>
      </div>
      <div className="dim" style={{ fontSize: 13, marginBottom: 14 }}>{data.verdict_note}</div>
      <div className="grid cols-3">
        {data.trajectory.map((t: any) => (
          <div key={t.metric} style={{ border: "1px solid var(--border)", borderRadius: 9, padding: "10px 12px" }}>
            <div className="faint" style={{ fontSize: 11 }}>{t.metric}</div>
            <div className="row-flex" style={{ gap: 8, marginTop: 4 }}>
              <span style={{ fontWeight: 700, fontSize: 18 }}>{t.first} → {t.last}</span>
              <span style={{ color: DIR_COLOR[t.direction], fontSize: 13, fontWeight: 700 }}>
                {DIR_ICON[t.direction]} {t.delta > 0 ? "+" : ""}{t.delta}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function CampaignPage() {
  const { id } = useParams();
  const cid = Number(id);
  const nav = useNavigate();
  const { toast, node } = useToast();
  const { data, error, loading, reload } = useAsync(() => api.getCampaign(cid), [cid]);
  const fileRef = useRef<HTMLInputElement>(null);
  const zipRef = useRef<HTMLInputElement>(null);
  const [label, setLabel] = useState("");
  const [zipLabel, setZipLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [cmpA, setCmpA] = useState<number | "">("");
  const [cmpB, setCmpB] = useState<number | "">("");
  const [cmp, setCmp] = useState<any>(null);

  async function upload() {
    const f = fileRef.current?.files?.[0];
    if (!f) { toast("Choose a snapshot .json first."); return; }
    setBusy(true);
    try { await api.uploadSnapshot(cid, f, label); toast("Snapshot added."); setLabel(""); if (fileRef.current) fileRef.current.value = ""; reload(); }
    catch (e: any) { toast(e.message); } finally { setBusy(false); }
  }
  async function ingestZip() {
    const f = zipRef.current?.files?.[0];
    if (!f) { toast("Choose a collection .zip first."); return; }
    setIngesting(true);
    try {
      const meta = await api.ingestCollection(cid, f, zipLabel);
      toast(`Engine run complete — ${meta.ingest.n_device_dirs} device(s) in ${meta.ingest.engine_seconds}s.`);
      nav(`/snapshots/${meta.id}`);
    } catch (e: any) { toast(e.message); } finally { setIngesting(false); }
  }
  async function runCompare() {
    if (cmpA === "" || cmpB === "" || cmpA === cmpB) { toast("Pick two different snapshots."); return; }
    try { setCmp(await api.compare(Number(cmpA), Number(cmpB))); }
    catch (e: any) { toast(e.message); }
  }
  async function delCampaign() {
    if (!confirm("Delete this campaign and all its snapshots?")) return;
    try { await api.deleteCampaign(cid); nav("/campaigns"); } catch (e: any) { toast(e.message); }
  }

  if (loading) return <div className="container"><Loading /></div>;
  if (error) return <div className="container"><ErrorBox msg={error} /></div>;
  const snaps = data!.snapshots || [];

  return (
    <div className="container">
      <div className="breadcrumb"><Link to="/campaigns">Campaigns</Link> / {data!.name}</div>
      <div className="page-head">
        <div>
          <h1>{data!.name}</h1>
          {data!.description && <div className="sub">{data!.description}</div>}
        </div>
        <span style={{ flex: 1 }} />
        <button className="btn danger ghost" onClick={delCampaign}>Delete</button>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1.4fr 1fr", gap: 16 }}>
        <div className="grid" style={{ gap: 16 }}>
          {snaps.length >= 2 && <Trend id={cid} />}
          <div className="panel">
            <h3>Waves ({snaps.length})</h3>
            {snaps.length === 0 ? <div className="faint" style={{ fontSize: 13 }}>No snapshots yet — upload one on the right.</div> : (
              <div className="grid" style={{ gap: 10 }}>
                {snaps.map((s, i) => (
                  <Link key={s.id} to={`/snapshots/${s.id}`} className="panel" style={{ padding: 14, display: "block", color: "inherit", textDecoration: "none", background: "var(--surface-2)" }}>
                    <div className="spread">
                      <div className="row-flex" style={{ gap: 10 }}>
                        <span className="chip mono">C{i + 1}</span>
                        <b style={{ fontSize: 15 }}>{s.label}</b>
                      </div>
                      <span className="dim" style={{ fontSize: 12 }}>{s.n_devices} dev · {new Date(s.uploaded_at).toLocaleDateString()}</span>
                    </div>
                    <div style={{ marginTop: 10 }}><SegBar data={s.summary.bands} colorFor={bandColor} /></div>
                  </Link>
                ))}
              </div>
            )}
          </div>
          {/* Always mounted: gate records are campaign-scoped and must stay visible/clearable
              even with zero snapshots (the board hides itself when there is nothing to show). */}
          <GateBoard id={cid} latest={snaps[snaps.length - 1]?.id ?? 0} toast={toast} />
        </div>

        <div className="grid" style={{ gap: 16, alignSelf: "start" }}>
          <div className="panel">
            <h3>Add a wave</h3>
            <label className="field"><span>Snapshot file (.json from the engine)</span>
              <input ref={fileRef} type="file" accept=".json,application/json" />
            </label>
            <label className="field"><span>Label (optional)</span>
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Wave 2 post-cutover" />
            </label>
            <button className="btn primary" onClick={upload} disabled={busy}>{busy ? "Uploading…" : "Upload snapshot"}</button>
          </div>

          <div className="panel">
            <h3>…or ingest a raw collection</h3>
            <div className="dim" style={{ fontSize: 12.5, marginBottom: 12 }}>
              Upload a ZIP of show-command outputs (one folder per device, e.g.{" "}
              <span className="mono">core1/show_interface_status.txt</span> — the collector's own
              layout). The real engine pipeline runs on the server and the snapshot lands here.
              A bundled <span className="mono">devices.json</span> is used if present; otherwise
              platforms are autodetected.
            </div>
            <label className="field"><span>Collection archive (.zip)</span>
              <input ref={zipRef} type="file" accept=".zip,application/zip" disabled={ingesting} />
            </label>
            <label className="field"><span>Label (optional)</span>
              <input value={zipLabel} onChange={(e) => setZipLabel(e.target.value)}
                placeholder="e.g. Baseline collection" disabled={ingesting} />
            </label>
            <button className="btn primary" onClick={ingestZip} disabled={ingesting}>
              {ingesting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Running engine…</> : "⚙ Run engine & ingest"}
            </button>
            {ingesting && (
              <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
                The full assessment pipeline is running over your outputs — typically seconds for a
                small fleet, a few minutes for a large one.
              </div>
            )}
          </div>

          {snaps.length >= 2 && (
            <div className="panel">
              <h3>Compare two waves</h3>
              <div className="row-flex" style={{ gap: 8 }}>
                <select value={cmpA} onChange={(e) => setCmpA(Number(e.target.value))}>
                  <option value="">from…</option>
                  {snaps.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select>
                <span className="faint">→</span>
                <select value={cmpB} onChange={(e) => setCmpB(Number(e.target.value))}>
                  <option value="">to…</option>
                  {snaps.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select>
              </div>
              <button className="btn" style={{ marginTop: 10 }} onClick={runCompare}>Compare</button>
              {cmp && (
                <div style={{ marginTop: 14, fontSize: 13 }}>
                  <div className="row-flex" style={{ marginBottom: 8 }}>
                    <span className="chip" style={{ color: VERDICT_COLOR[cmp.verdict] || "var(--text-dim)" }}><span className="dot" /> {cmp.verdict}</span>
                  </div>
                  <div className="grid cols-2" style={{ gap: 8 }}>
                    <div>Opened: <b style={{ color: "var(--crit)" }}>{cmp.findings?.n_opened ?? "—"}</b> ({cmp.findings?.n_opened_high ?? 0} high)</div>
                    <div>Resolved: <b style={{ color: "var(--ok)" }}>{cmp.findings?.n_resolved ?? "—"}</b></div>
                    <div>Regressed: <b style={{ color: "var(--crit)" }}>{cmp.health?.n_regressed ?? "—"}</b></div>
                    <div>Improved: <b style={{ color: "var(--ok)" }}>{cmp.health?.n_improved ?? "—"}</b></div>
                    {/* physical cabling delta (EDA cable-map SSOT) — coverage-honest: 'not assessed' is disclosed, never a silent zero */}
                    <div>Cables ±: <b>{cmp.cabling?.assessed ? `${cmp.cabling.summary?.n_added ?? 0} added / ${cmp.cabling.summary?.n_removed ?? 0} removed` : "not assessed"}</b></div>
                    <div>Cables down: <b style={{ color: (cmp.cabling?.summary?.n_went_down ?? 0) > 0 ? "var(--crit)" : "var(--ok)" }}>{cmp.cabling?.assessed ? (cmp.cabling.summary?.n_went_down ?? 0) : "—"}</b></div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {node}
    </div>
  );
}
