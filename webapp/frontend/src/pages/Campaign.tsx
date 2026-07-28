import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, bandColor, gateColor } from "../api";
import type { GateRecord } from "../api";
import { ErrorBox, Loading, SegBar, useAsync, useToast } from "../components/ui";

export const NEXT_DECISION: Record<string, string> = { pending: "go", go: "no-go", "no-go": "slipped", slipped: "pending" };

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
  // audit FE-8: the guard above only fires on the FIRST load. useAsync keeps `data` across a
  // refetch, so once the board had ever loaded a later failure (a 403 cross-site refusal, a 404
  // after the campaign's snapshot set changed, a dropped connection) set `error` while the stale
  // grid kept rendering — indistinguishable from a successful refresh. The board is a governance
  // record; showing a superseded wave set as if it were current is the wrong failure. Disclose the
  // stale read ABOVE the grid rather than replacing it (the last-known board is still useful).
  const staleBanner = error ? (
    <div className="panel" style={{ borderColor: "var(--risk)", padding: "8px 12px", marginBottom: 10 }}>
      <b style={{ color: "var(--risk)" }}>Gate board is STALE.</b>{" "}
      <span className="dim" style={{ fontSize: 12.5 }}>
        The last refresh failed ({error}) — the sign-offs below are the previous read and may not
        reflect the current campaign.
      </span>
    </div>
  ) : null;
  const records = recOverride ?? data.records;
  // union: waves derivable from the latest snapshot + any wave that already has recorded history
  const waves = Array.from(new Set([...data.waves, ...records.map((r) => r.wave)]));
  // A board with nothing to show hides itself (by design) — but never at the cost of hiding a failed
  // refresh, which is the difference between "no waves" and "we could not find out".
  if (waves.length === 0) return staleBanner && <div className="panel">{staleBanner}</div>;
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
      {staleBanner}
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
                // Coverage-honest disclosure (backend gates.annotate_out_of_order, PR #376): a GO signed
                // before its upstream cadence gate was GO. We surface it, we don't block it — the sign-off
                // still stands; the ⚠ + tooltip just make the out-of-order state visible on the board.
                const ooo = r?.out_of_order === true;
                const oooTip = `Out of order: signed before upstream ${r?.out_of_order_upstream || "gate"} was GO`;
                const tip = r
                  ? `${d.toUpperCase()} — ${r.signed_by || "unsigned"} · ${new Date(r.decided_at).toLocaleString()}${r.note ? ` · ${r.note}` : ""}${ooo ? ` · ${oooTip}` : ""}`
                  : "pending — click to sign";
                return (
                  <span key={`${w}|${g.key}`} role="button" tabIndex={0} className="chip gate"
                    onClick={() => cycle(w, g.key)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); cycle(w, g.key); } }}
                    data-wave={w} data-gate={g.key} data-out-of-order={ooo || undefined} title={tip} aria-label={tip}
                    style={{ ["--gc" as any]: gateColor(d === "pending" ? "PENDING" : d.toUpperCase()), cursor: "pointer", justifyContent: "center", gap: 4, fontSize: 11, opacity: busy ? 0.65 : 1 }}>
                    {d === "pending" ? "—" : d.toUpperCase()}
                    {ooo && (
                      <span className="gate-ooo" role="img" aria-label={oooTip} title={oooTip}
                        style={{ color: "var(--watch)", fontWeight: 700 }}>⚠</span>
                    )}
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
export const VERDICT_COLOR: Record<string, string> = {
  // campaign-trend vocabulary (compute_campaign_trend)
  IMPROVING: "var(--ok)", REGRESSING: "var(--crit)", MIXED: "var(--watch)", FLAT: "var(--text-dim)", INSUFFICIENT: "var(--text-faint)",
  // snapshot_delta vocabulary (compute_snapshot_delta) — the 'Compare two waves' panel reuses this map; without
  // these keys cmp.verdict (CLEAN/REVIEW/REGRESSED) fell through to a flat dim chip, never colored (audit-5 CA#5).
  CLEAN: "var(--ok)", REVIEW: "var(--watch)", REGRESSED: "var(--crit)",
};

function Trend({ id }: { id: number }) {
  const { data, error, loading } = useAsync(() => api.trend(id), [id]);
  // A failed trend fetch must SURFACE, not vanish — every other panel on this page shows ErrorBox
  // (GateBoard's pattern); the old `!data → null` guard swallowed errors forever, silently.
  if (error) {
    return (
      <div className="panel">
        <h3>Campaign trajectory</h3>
        <ErrorBox msg={error} />
      </div>
    );
  }
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
  const [folderPath, setFolderPath] = useState("");
  const [folderLabel, setFolderLabel] = useState("");
  const [folderIngesting, setFolderIngesting] = useState(false);
  const [cmpA, setCmpA] = useState<number | "">("");
  const [cmpB, setCmpB] = useState<number | "">("");
  const [cmp, setCmp] = useState<any>(null);
  const [cmpErr, setCmpErr] = useState<string | null>(null);

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
  async function ingestFolder() {
    const p = folderPath.trim();
    if (!p) { toast("Enter the server-local folder path first."); return; }
    setFolderIngesting(true);
    try {
      const meta = await api.ingestFolder(cid, p, folderLabel);
      toast(`Engine run complete — ${meta.ingest.n_device_dirs} device(s) in ${meta.ingest.engine_seconds}s.`);
      nav(`/snapshots/${meta.id}`);
    } catch (e: any) { toast(e.message); } finally { setFolderIngesting(false); }
  }
  async function runCompare() {
    if (cmpA === "" || cmpB === "" || cmpA === cmpB) { toast("Pick two different snapshots."); return; }
    // audit FE-7: a failed re-compare used to leave the PREVIOUS pair's verdict on screen under the
    // newly-selected pair — the reader attributes an old CLEAN/REGRESSED to snapshots it was never
    // computed from. Drop the stale result first and say the run failed where the result would be.
    setCmp(null);
    setCmpErr(null);
    try { setCmp(await api.compare(Number(cmpA), Number(cmpB))); }
    catch (e: any) { setCmpErr(e.message || String(e)); toast(e.message); }
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
                  <Link key={s.id} to={`/snapshots/${s.id}`} className="panel"
                    style={{ padding: 14, display: "block", color: "inherit", textDecoration: "none", background: "var(--surface-2)", ["--stagger-i" as any]: Math.min(i, 8) }}>
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

          <div className="panel">
            <h3>…or ingest a local folder</h3>
            <div className="dim" style={{ fontSize: 12.5, marginBottom: 12 }}>
              Point at a collection folder on the <b>server&rsquo;s</b> disk (same per-device layout,
              no ZIP round-trip) — the portable-app path, where the collection already sits beside
              the app. The folder is only read; outputs stay in a private workdir.
            </div>
            <label className="field"><span>Folder path (on the server)</span>
              <input value={folderPath} onChange={(e) => setFolderPath(e.target.value)}
                placeholder="e.g. D:\collections\siteA" disabled={folderIngesting} />
            </label>
            <label className="field"><span>Label (optional)</span>
              <input value={folderLabel} onChange={(e) => setFolderLabel(e.target.value)}
                placeholder="e.g. Field baseline" disabled={folderIngesting} />
            </label>
            <button className="btn primary" onClick={ingestFolder} disabled={folderIngesting}>
              {folderIngesting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Running engine…</> : "⚙ Run engine on folder"}
            </button>
          </div>

          {snaps.length >= 2 && (
            <div className="panel">
              <h3>Compare two waves</h3>
              <div className="row-flex" style={{ gap: 8 }}>
                {/* audit FE-6: `Number(e.target.value)` turned the "from…"/"to…" placeholder ("") into
                    0, which is not "" — so the `cmpA === ""` guard passed and the app POSTed
                    /api/compare with old_id 0, getting back the server's "One or both snapshots not
                    found" 404 instead of the local "Pick two different snapshots." prompt. Keep ""
                    as "" so the unselected state stays distinguishable from a real id. */}
                <select value={cmpA} onChange={(e) => setCmpA(e.target.value === "" ? "" : Number(e.target.value))}>
                  <option value="">from…</option>
                  {snaps.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select>
                <span className="faint">→</span>
                <select value={cmpB} onChange={(e) => setCmpB(e.target.value === "" ? "" : Number(e.target.value))}>
                  <option value="">to…</option>
                  {snaps.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select>
              </div>
              <button className="btn" style={{ marginTop: 10 }} onClick={runCompare}>Compare</button>
              {cmpErr && (
                <div style={{ marginTop: 12 }}>
                  <ErrorBox msg={cmpErr} />
                  <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
                    No comparison was produced for this pair — nothing below is a result for it.
                  </div>
                </div>
              )}
              {cmp && (
                <div style={{ marginTop: 14, fontSize: 13 }}>
                  <div className="row-flex" style={{ marginBottom: 8 }}>
                    <span className="chip" style={{ color: VERDICT_COLOR[cmp.verdict] || "var(--text-dim)" }}><span className="dot" /> {cmp.verdict}</span>
                  </div>
                  <div className="grid cols-2" style={{ gap: 8 }}>
                    {/* `?? "—"` (not `?? 0`) throughout: an absent count is unknown, not a measured
                        zero. n_opened_high used to land on `?? 0`, so a comparison with no findings
                        block read "— (0 high)" — half honest, half a fabricated all-clear. */}
                    <div>Opened: <b style={{ color: "var(--crit)" }}>{cmp.findings?.n_opened ?? "—"}</b> ({cmp.findings?.n_opened_high ?? "—"} high)</div>
                    <div>Resolved: <b style={{ color: "var(--ok)" }}>{cmp.findings?.n_resolved ?? "—"}</b></div>
                    <div>Regressed: <b style={{ color: "var(--crit)" }}>{cmp.health?.n_regressed ?? "—"}</b></div>
                    <div>Improved: <b style={{ color: "var(--ok)" }}>{cmp.health?.n_improved ?? "—"}</b></div>
                    {/* physical cabling delta (EDA cable-map SSOT) — coverage-honest: 'not assessed' is disclosed, never a silent zero */}
                    <div>Cables ±: <b>{cmp.cabling?.assessed ? `${cmp.cabling.summary?.n_added ?? 0} added / ${cmp.cabling.summary?.n_removed ?? 0} removed` : "not assessed"}</b></div>
                    {/* audit FE-5: the colour was computed from `n_went_down ?? 0` BEFORE the
                        `assessed` check that picks the text, so an UNASSESSED cabling delta rendered
                        its "—" in var(--ok) — a green em-dash, i.e. the not-observed case painted as
                        the healthy case. Colour now follows the same assessed gate as the text. */}
                    <div>Cables down: <b style={{ color: !cmp.cabling?.assessed ? "var(--text-faint)" : (cmp.cabling.summary?.n_went_down ?? 0) > 0 ? "var(--crit)" : "var(--ok)" }}
                                       title={cmp.cabling?.assessed ? undefined : "No cable-map evidence in one or both snapshots — not assessed, not clean"}>
                      {cmp.cabling?.assessed ? (cmp.cabling.summary?.n_went_down ?? 0) : "—"}</b></div>
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
