import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api, type Campaign, type SnapshotMeta } from "../api";
import { loadProjection, sameIdentity, equalJson, type Fact, type ViewDocument } from "../projection";
import { EvidenceProvider, FactView, ListState, ValueText } from "./core/NativeEvidence";
import { NativeProjectionList } from "./core/NativeProjectionList";
import { NetworkCanvas } from "./core/NetworkCanvas";
import { assembleTopology, initialTopologyRows, hasTarget, rowKey, type TopologyDocument, type TopologyRow, type TopologyRows, type TopologyTarget } from "./core/topologyData";
import type { SourceList } from "../projection";
import { DeviceDossier } from "../components/DeviceDossier";
import "./coreSnapshot.css";
import "./snapshotWorkspace.css";

const tabs = ["Network", "Findings", "Inventory", "Plan", "Change", "Reports"] as const;
type Tab = typeof tabs[number];
function SnapshotHeader({ sid, id, classicHref, changeTab }: { sid: number; id: string; classicHref: string; changeTab: (tab: Tab) => void }) {
  const navigate = useNavigate();
  const [record, setRecord] = useState<{ sid: number; snapshot: SnapshotMeta; campaign: Campaign } | null>(null);
  useEffect(() => {
    let active = true; setRecord(null);
    if (!Number.isSafeInteger(sid)) return () => { active = false; };
    api.getSnapshot(sid).then(async (snapshot) => {
      if (snapshot.id !== sid) throw new Error("Snapshot metadata identity mismatch.");
      const campaign = await api.getCampaign(snapshot.campaign_id);
      if (campaign.id !== snapshot.campaign_id) throw new Error("Engagement metadata identity mismatch.");
      if (active) setRecord({ sid, snapshot, campaign });
    }).catch(() => {});
    return () => { active = false; };
  }, [sid]);
  const current = record?.sid === sid ? record : null;
  return <header className="workspace-heading"><div><Link to="/engagements">{current?.campaign.name ?? "Engagements"}</Link><h1>Snapshot {id}</h1>
    {current ? <label className="workspace-snapshot-select">Stored snapshot <select aria-label="Snapshot selector" value={sid} onChange={(event) => navigate(`/snapshots/${event.target.value}`)}>
      <option value={sid}>{current.snapshot.label || `Snapshot ${sid}`}</option>{current.campaign.snapshots?.filter((item) => item.id !== sid).map((item) => <option key={item.id} value={item.id}>{item.label || `Snapshot ${item.id}`}</option>)}</select></label>
      : <p>Understand the network. Investigate the evidence. Prepare the migration.</p>}
  </div><div className="workspace-header-actions"><Link className="btn" to={classicHref}>Classic view</Link><button className="btn" onClick={() => changeTab("Change")}>Compare snapshots</button><button className="btn primary" onClick={() => changeTab("Reports")}>Reports</button></div></header>;
}
function Coverage({ document }: { document: TopologyDocument }) {
  const [result, setResult] = useState<ViewDocument<"trust"> | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setResult(null); setError("");
    const timeout = window.setTimeout(() => { controller.abort(); setError("Coverage request timed out. Retry coverage."); }, 30_000);
    loadProjection(document.identity.snapshot_id, "trust", undefined, controller.signal).then((next) => {
      if (!sameIdentity(document.identity, next.identity) || !equalJson(document.engine, next.engine)) throw new Error("Coverage belongs to a different snapshot context. Reload Network.");
      if (!controller.signal.aborted) setResult(next);
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Coverage unavailable."); }).finally(() => window.clearTimeout(timeout));
    return () => { controller.abort(); window.clearTimeout(timeout); };
  }, [document, retry]);
  return <section className="workspace-coverage" aria-label="Evidence coverage">
    <strong>Evidence coverage</strong><span>Uncollected and withheld evidence remains a blind spot.</span>
    {error ? <p role="alert">{error} <button className="btn" onClick={() => setRetry((n) => n + 1)}>Retry coverage</button></p>
      : !result || !sameIdentity(document.identity, result.identity) || !equalJson(document.engine, result.engine) ? <span role="status">Loading engine coverage…</span>
      : <EvidenceProvider identity={result.identity} limitations={result.limitations}><details><summary>Review engine coverage and qualifications</summary>
        <div className="projection-fact-grid">{Object.entries(result.payload.coverage_matrix).map(([key, fact]) => <FactView key={key} label={key.replaceAll("_", " ")} fact={fact} compact />)}</div>
        <FactView label="Source coverage complete" fact={result.payload.unknown_evidence.source_coverage_complete} compact />
        <FactView label="Coverage claim scope" fact={result.payload.unknown_evidence.claim_scope} compact />
        <ul>{result.limitations.map((item) => <li key={item.id}>{item.text}</li>)}</ul>
      </details></EvidenceProvider>}
  </section>;
}

function TopologyRecord({ row }: { row: TopologyRow }) {
  return <div className="workspace-record"><code>{row.pointer}</code>{Object.entries(row).map(([key, value]) => {
    if (!value || typeof value !== "object" || !("state" in value)) return null;
    const label = key.replaceAll("_", " ");
    if ("value" in value) return <FactView key={key} label={label} fact={value as Fact} compact />;
    if ("items" in value) return <details key={key}><summary>{label}</summary><ListState label={label} source={value as SourceList} /><ValueText value={value.items as Parameters<typeof ValueText>[0]["value"]} /></details>;
    return null;
  })}</div>;
}
function MapEvidence({ document }: { document: TopologyDocument }) {
  const [open, setOpen] = useState(false);
  return <details className="workspace-map-evidence" onToggle={(event) => setOpen(event.currentTarget.open)}><summary>All topology records and cable evidence</summary>{open && <><p>Inspect exact engine records here, including links not drawn because their joins are ambiguous or the display budget is reached.</p>{(["nodes", "cables", "structural_links"] as const).map((name) => <NativeProjectionList key={name} title={`Map ${name.replaceAll("_", " ")}`} document={document} initial={document.payload[name]} renderRow={(row) => <TopologyRecord row={row} />} />)}</>}</details>;
}
function Network({ document, reload, active }: { document: TopologyDocument; reload: () => void; active: boolean }) {
  const [rows, setRows] = useState<TopologyRows | null>(null);
  const [message, setMessage] = useState("Loading source-bound map pages…");
  const [failure, setFailure] = useState("");
  const [selected, setSelected] = useState<TopologyTarget | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setRows(null); setSelected(null); setFailure(""); setMessage("Loading source-bound map pages…");
    try { setRows(initialTopologyRows(document)); } catch (error) { setFailure(String(error)); return () => controller.abort(); }
    const timeout = window.setTimeout(() => { controller.abort(); setRows(null); setSelected(null); setFailure("Map pagination timed out. Reload Network or inspect the paged evidence records."); }, 30_000);
    assembleTopology(document, controller.signal, (next) => { if (!controller.signal.aborted) setRows(next); }).then((next) => {
      if (!controller.signal.aborted) { setRows(next); setMessage("Projected map pages loaded. Network evidence may be incomplete."); }
    }).catch((error: unknown) => { if (!controller.signal.aborted) { setRows(null); setSelected(null); setFailure(error instanceof Error ? error.message : "Map pages unavailable."); } }).finally(() => window.clearTimeout(timeout));
    return () => { controller.abort(); window.clearTimeout(timeout); };
  }, [document]);
  const row = selected && rows ? rows[selected.list].find((item) => rowKey(item) === rowKey(selected.row)) : null;
  const host = row && "host" in row && row.host.state === "published" ? row.host.value : null;
  if (failure) return <section className="panel"><div role="alert"><h2>Network unavailable</h2><p>{failure}</p></div><button className="btn" onClick={reload}>Reload Network</button><MapEvidence document={document} /></section>;
  return <div className="workspace-network">
    <section className="workspace-map" aria-label="Network map">
      <div className="workspace-map-heading"><div><h2>Explore your network</h2><p>Select a device to inspect its evidence. Select a cable to see its published port records.</p></div>
        <div className="workspace-map-totals"><FactView label="Engine node total" fact={document.payload.summary.nodes} compact /><FactView label="Engine cable total" fact={document.payload.summary.cables} compact /></div></div>
      <p className="dim" role="status">{message}</p>
      {rows ? <NetworkCanvas rows={rows} legend={document.payload.legend} selected={selected} pathNodes={new Set()} select={(target) => { if (hasTarget(rows, target)) setSelected(target); }} /> : <p role="status">Preparing map…</p>}
      <details className="workspace-overlay-info"><summary>Overlays and map coverage</summary><p>Collection and cable styles come from the engine legend. Health, lifecycle, findings and VLAN overlays await engine-owned map contracts.</p>
        {(["nodes", "cables", "structural_links"] as const).map((key) => <ListState key={key} label={key.replaceAll("_", " ")} source={document.payload[key].source_list} />)}</details>
      <MapEvidence document={document} />
    </section>
    <aside className="workspace-selection" aria-label="Selection details"><header><h2>{host ?? (row ? "Cable evidence" : "Inspect a device")}</h2>{selected && <button className="btn ghost" onClick={() => setSelected(null)}>Clear selection</button>}</header>
      <div className="workspace-device-tools" role="group" aria-label="Device tools"><button className="btn" aria-pressed="true">Details</button>{["If this fails", "Path", "Endpoint", "VLAN"].map((item) => <button key={item} className="btn ghost" disabled title="Available in the next reviewed Network tools increment">{item}</button>)}</div>
      {host ? <DeviceDossier document={document} host={host} snapshotId={document.identity.snapshot_id} active={active} /> : row ? <TopologyRecord row={row} />
        : <div className="workspace-selection-empty"><span aria-hidden="true">◎</span><p>Your map is the starting point.</p><p>Choose a device for its collection, health, lifecycle and source evidence. Cable details remain tied to their engine records.</p><p className="dim">Failure investigation, path, endpoint finder and VLAN tools follow in the next reviewed increment.</p></div>}
    </aside>
  </div>;
}

export default function SnapshotWorkspace() {
  const { id = "" } = useParams(); const [params, setParams] = useSearchParams();
  const sid = Number(id); const valid = /^\d+$/.test(id) && Number.isSafeInteger(sid);
  const requested = params.get("tab")?.toLowerCase();
  const tab: Tab = tabs.find((item) => item.toLowerCase() === requested) ?? "Network";
  const expected = params.get("source"), bytes = params.get("source_bytes");
  const key = JSON.stringify([sid, expected, bytes]);
  const [result, setResult] = useState<{ key: string; document: TopologyDocument } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null); const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setResult(null); setFailure(null);
    if (!valid) { setFailure({ key, message: "Choose a valid stored snapshot from Engagements." }); return () => controller.abort(); }
    const timeout = window.setTimeout(() => { controller.abort(); setFailure({ key, message: "The Network request timed out. Retry snapshot." }); }, 30_000);
    loadProjection(sid, "topology", undefined, controller.signal).then((document) => {
      if ((expected !== null || bytes !== null) && (document.identity.sha256 !== expected || String(document.identity.bytes) !== bytes)) throw new Error("The referenced record belongs to a different stored snapshot. Select it again from Engagements.");
      if (!controller.signal.aborted) setResult({ key, document });
    }).catch((error: unknown) => { if (!controller.signal.aborted) setFailure({ key, message: error instanceof Error ? error.message : "Snapshot unavailable." }); }).finally(() => window.clearTimeout(timeout));
    return () => { controller.abort(); window.clearTimeout(timeout); };
  }, [sid, key, valid, expected, bytes, retry]);
  const document = result?.key === key ? result.document : null;
  const changeTab = (item: Tab) => { const next = new URLSearchParams(params); next.set("tab", item.toLowerCase()); setParams(next); };
  const classicParams = new URLSearchParams(params); classicParams.set("view", "overview"); classicParams.delete("tab");
  if (document) { classicParams.set("source", document.identity.sha256); classicParams.set("source_bytes", String(document.identity.bytes)); }
  return <main className="snapshot-workspace"><SnapshotHeader sid={sid} id={id} classicHref={`/snapshots/${id}?${classicParams}`} changeTab={changeTab} />
    {failure?.key === key ? <section className="panel" role="alert"><h2>Snapshot unavailable</h2><p>{failure.message}</p><button className="btn" onClick={() => setRetry((n) => n + 1)}>Retry snapshot</button></section> : !document ? <p role="status">Loading Network…</p>
      : <EvidenceProvider key={JSON.stringify([key, document.identity, document.engine])} identity={document.identity} limitations={document.limitations} active={tab === "Network"}>
        <Coverage document={document} />
        <nav className="workspace-tabs" aria-label="Snapshot tabs">{tabs.map((item) => <button key={item} aria-current={tab === item ? "page" : undefined} onClick={() => changeTab(item)}>{item}</button>)}</nav>
        <div hidden={tab !== "Network"} inert={tab !== "Network"}><Network document={document} reload={() => setRetry((n) => n + 1)} active={tab === "Network"} /></div>
        {tab !== "Network" && <section className="panel workspace-upcoming"><h2>{tab}</h2><p>{tab === "Findings" ? "Engine findings will link directly to devices on the Network map." : tab === "Inventory" ? "Device and endpoint evidence will be available here." : tab === "Plan" ? "Design, move groups and saved plans will be brought into this workspace." : tab === "Change" ? "MOP, runbook, wave decisions, NRFU and comparison will be brought into this workspace." : "Deliverable downloads will be brought into this workspace."}</p><p className="dim">This tab is reserved for a subsequent reviewed increment.</p><button className="btn" onClick={() => { const next = new URLSearchParams(params); next.set("tab", "network"); setParams(next); }}>Return to Network</button></section>}
      </EvidenceProvider>}
  </main>;
}
