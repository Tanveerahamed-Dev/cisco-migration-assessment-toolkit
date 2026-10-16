import { useEffect, useRef, useState } from "react";
import { equalJson, loadProjection, ProjectionContextError, sameIdentity, type Fact, type Projection, type ViewDocument } from "../projection";
import { EvidenceProvider, FactView } from "../pages/core/NativeEvidence";
import { NativeProjectionList as ProjectionList } from "../pages/core/NativeProjectionList";
import "./deviceDossier.css";

export interface DeviceDossierProps {
  document: Projection;
  host: string | null;
  snapshotId: number;
  active?: boolean;
}
type DeviceDocument = ViewDocument<"device">;
type RequestContext = { source: Projection; host: string; snapshotId: number };
type Result = RequestContext & { document: DeviceDocument };
type Failure = RequestContext & { message: string };

// This is an admission check, not an analysis join. The child view may legitimately
// carry device-only caveats; it renders with its own registry rather than the parent's.
export function requireDossierContext(parent: Projection, child: DeviceDocument): void {
  if (!sameIdentity(parent.identity, child.identity) || !equalJson(parent.engine, child.engine)) {
    throw new ProjectionContextError("Stored snapshot identity or engine context changed. Reload the workspace before continuing.");
  }
}

function FactGrid({ facts, order }: { facts: Readonly<Record<string, Fact>>; order?: readonly string[] }) {
  const entries = order ? order.map((key) => [key, facts[key]] as const) : Object.entries(facts);
  return <div className="projection-fact-grid">{entries.map(([key, fact]) =>
    <FactView key={key} label={key.replaceAll("_", " ")} fact={fact} compact />)}</div>;
}

function DossierFacts({ document, active }: { document: DeviceDocument; active: boolean }) {
  const p = document.payload, host = p.host ?? "";
  return <EvidenceProvider identity={document.identity} limitations={document.limitations} active={active}>
    <section aria-label="Device identity"><h3>Identity</h3><FactGrid facts={p.identity} />
      <FactView label="Move group" fact={p.move_group} compact /></section>
    <section aria-label="Device health"><h3>Health</h3>
      <FactGrid facts={{ score: p.health.score, band: p.health.band, role: p.health.role }} />
      <FactView label="Risk band" fact={p.dossier.risk_band} compact /></section>
    <section aria-label="Device collection"><h3>Collection &amp; coverage</h3><FactGrid facts={p.collection} />
      <FactGrid facts={{ worst_coverage_state: p.coverage_rollup.worst, abstaining_coverage_axes: p.coverage_rollup.n_abstained }} /></section>
    <section aria-label="Device findings"><h3>Finding severity</h3>
      <FactGrid facts={{ worst_finding_severity: p.findings_rollup.worst, findings_by_severity: p.findings_rollup.by_severity }} /></section>
    <section aria-label="Device lifecycle"><h3>Lifecycle</h3><FactGrid facts={p.lifecycle} /></section>
    <details><summary>Physical inventory</summary><FactGrid facts={p.physical} /></details>
    <details><summary>Interfaces &amp; routes</summary>
      <ProjectionList title="Device interfaces" document={document} host={host} initial={p.interfaces.rows} renderRow={(row) => <>
        <h4>{row.port}</h4><FactGrid facts={row.cells} order={p.interfaces.columns} />
        <FactView label="Running configuration observed" fact={row.run_config_observed} compact /></>} />
      <ProjectionList title="Device routes" document={document} host={host} initial={p.routes} renderRow={(row) =>
        <FactGrid facts={{ prefix: row.prefix, source: row.source, next_hop: row.next_hop, interface: row.out_intf, admin_distance: row.admin_distance }} />} />
    </details>
    <details><summary>Device coverage evidence</summary>
      <ProjectionList title="Device coverage axes" document={document} host={host} initial={p.coverage} renderRow={(row) =>
        <FactView label={row.axis} fact={row.fact} />} />
    </details>
    <details className="device-dossier-source"><summary>Evidence: source, engine &amp; limitations</summary>
      <p>Stored snapshot {document.identity.snapshot_id} · {document.identity.bytes} bytes · {document.identity.digest_form}</p>
      <code>{document.identity.sha256}</code>
      <FactGrid facts={{ script_version: document.engine.script_version, snapshot_schema: document.engine.snapshot_schema,
        generated_at: document.engine.generated_at, collected_at: document.engine.collected_at }} />
      <p>Code schema: {document.engine.code_schema_version} · Source schema supported: {document.engine.snapshot_schema_supported === null ? "Not published" : document.engine.snapshot_schema_supported ? "Yes" : "No"}</p>
      <h3>Device view limitations</h3>
      {document.limitations.length ? <ul>{document.limitations.map((item) => <li key={item.id}><strong>{item.id}</strong>
        <p>{item.text}</p><small>Owner: {item.owner} · Applies to: {item.applies_to.join(", ")}</small></li>)}</ul>
        : <p>This device projection carries no additional limitation registry entries. Individual facts retain their own evidence states and references.</p>}
    </details>
  </EvidenceProvider>;
}

/** Selected device projection only. No CoreSnapshot, Scope, legacy graph or JS analysis dependency. */
export function DeviceDossier({ document, host, snapshotId, active = true }: DeviceDossierProps) {
  const [result, setResult] = useState<Result | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [retry, setRetry] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    setResult(null); setFailure(null);
    if (host === null) return;
    const context: RequestContext = { source: document, host, snapshotId };
    if (!Number.isSafeInteger(snapshotId) || snapshotId !== document.identity.snapshot_id) {
      setFailure({ ...context, message: "The selected device belongs to a different snapshot context. Reload the workspace." });
      return;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      if (generation.current !== current) return;
      controller.abort(); generation.current += 1;
      setFailure({ ...context, message: "The device projection request timed out. Retry the device dossier." });
    }, 30_000);
    loadProjection(snapshotId, "device", host, controller.signal).then((child) => {
      requireDossierContext(document, child);
      if (!controller.signal.aborted && generation.current === current) setResult({ ...context, document: child });
    }).catch((error) => {
      if (!controller.signal.aborted && generation.current === current) setFailure({ ...context,
        message: error instanceof Error ? error.message : "The device projection could not be loaded." });
    }).finally(() => window.clearTimeout(timeout));
    return () => { controller.abort(); generation.current += 1; window.clearTimeout(timeout); };
  }, [document, host, snapshotId, retry]);
  const matches = (context: RequestContext | null) => context?.source === document && context.host === host && context.snapshotId === snapshotId;
  const child = matches(result) ? result!.document : null;
  const error = matches(failure) ? failure!.message : null;
  return <aside className="device-dossier" aria-label="Device dossier" aria-busy={host !== null && !child && !error}>
    <header><p className="device-dossier-eyebrow">Selected device</p><h2>{host ?? "Device dossier"}</h2></header>
    {host === null ? <p>Select a device on the topology to inspect its identity, health, collection, findings and lifecycle evidence.</p>
      : error ? <div role="alert"><h3>Device dossier unavailable</h3><p>{error}</p><button type="button" className="btn" onClick={() => setRetry((value) => value + 1)}>Retry device dossier</button></div>
        : !child ? <p role="status">Loading device dossier…</p> : <DossierFacts document={child} active={active} />}
  </aside>;
}
