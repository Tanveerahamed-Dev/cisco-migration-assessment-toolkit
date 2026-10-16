import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api } from "../api";
import CoreSnapshot from "./CoreSnapshot";
import "./snapshotWorkspace.css";

const secondaryViews = [
  ["overview", "Overview"], ["trust", "Trust"], ["inventory", "Inventory"],
  ["findings", "Findings"], ["topology", "Topology & Paths"],
] as const;

// One opaque Explorer per snapshot. Query-only navigation to a Core tab must not reload
// its drawing or mode-local investigation. Explicit Core links keep all source/ref params.
function SnapshotSession({ id }: { id: string }) {
  const [params] = useSearchParams();
  const core = params.has("view");
  const [visited, setVisited] = useState(!core);
  const [generation, setGeneration] = useState(0);
  const [frameError, setFrameError] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  // Frame error events do not bubble. Bind to the frame itself, and detach the old
  // listener on replacement so a late event cannot label the new frame as failed.
  // HTTP generation failures still belong to the opaque document's own response.
  const attachFrame = useCallback((node: HTMLIFrameElement | null) => {
    if (frame.current) frame.current.onerror = null;
    frame.current = node;
    if (node) node.onerror = () => setFrameError(true);
  }, []);
  useEffect(() => { if (!core) setVisited(true); }, [core]);
  const requested = params.get("view");
  const sid = Number(id);
  const validId = /^[1-9][0-9]*$/.test(id) && Number.isSafeInteger(sid);
  return <main className="snapshot-workspace">
    <header className="snapshot-workspace-header">
      <div className="snapshot-workspace-title"><Link to="/campaigns">Campaigns</Link><span aria-hidden="true">/</span><strong>Snapshot {id}</strong></div>
      <div className="snapshot-workspace-actions">
        {!core && <button type="button" className="btn" disabled={!validId} onClick={() => frame.current?.focus()}>Focus topology</button>}
        {!core && <button type="button" className="btn" disabled={!validId} onClick={() => { setFrameError(false); setGeneration((n) => n + 1); }}>Reload topology</button>}
        <Link className="btn" to={`/snapshots/${id}/tools`}>Tools and downloads</Link>
        <details className="snapshot-workspace-info"><summary>Workspace info</summary>
          <div><p>Select a device or connection in the diagram to inspect it. The Explorer tool bar opens Cable Map, health, failure, endpoint, path, traffic, protocol and cross-layer investigations.</p>
            <p>These tools model saved assessment evidence. They do not test live traffic or establish application delivery. Path trace and Flow have their own disclosed scope; Flow is not canonical Traffic Assurance.</p>
            <p>Core tabs provide the structured assessment and evidence readers. If the diagram reports a loading or generation error, use Reload topology or open Tools and downloads.</p></div>
        </details>
      </div>
    </header>
    <nav className="snapshot-workspace-nav" aria-label="Snapshot views">
      <Link to={`/snapshots/${id}`} aria-current={!core ? "page" : undefined}>Network</Link>
      <span className="snapshot-workspace-secondary">Core</span>
      {secondaryViews.map(([view, label]) => <Link key={view} to={`/snapshots/${id}?view=${view}`}
        aria-current={requested === view || (requested === "device" && view === "inventory") ? "page" : undefined}>{label}</Link>)}
    </nav>
    {!validId ? <section className="panel" role="alert"><h1>Snapshot unavailable</h1><p>Choose a valid snapshot from Campaigns.</p></section> : <>
      {(visited || !core) && <section className="snapshot-network-pane" hidden={core} inert={core} aria-label="Network workspace">
        <h1 className="snapshot-workspace-sr">Network workspace</h1>
        {frameError && <div className="snapshot-workspace-error" role="alert">The Explorer frame could not load. Use Reload topology to try again.</div>}
        <iframe key={`${id}:${generation}`} ref={attachFrame} title="Network Migration Explorer"
          src={`${api.explorerUrl(sid)}#mode=cablemap`}
          sandbox="allow-scripts allow-downloads allow-modals" />
      </section>}
      {core && <section className="snapshot-core-pane" aria-label="Core assessment"><CoreSnapshot embedded /></section>}
    </>}
  </main>;
}

export default function SnapshotWorkspace() {
  const { id = "" } = useParams();
  return <SnapshotSession key={id} id={id} />;
}
