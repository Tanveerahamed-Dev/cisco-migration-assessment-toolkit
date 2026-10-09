import { useEffect, useRef, useState, type FormEvent } from "react";
import { loadPathProjection, ProjectionContextError, type Fact, type PathProjection, type SourceList } from "../../projection";
import { ApiError } from "../../api";
import { projectionImpactBound } from "../../components/ImpactValue";
import { FactView, ListState, ValueText } from "./ProjectionEvidence";
import { ProjectionList } from "./ProjectionList";
import { TopologyDiagram } from "./TopologyDiagram";
import { TopologyScope } from "./TopologyScope";
import { assembleTopology, exactEndpoint, hasTarget, initialTopologyRows, rowKey, TOPOLOGY_LISTS,
  TopologyCapacityError, type TopologyDocument, type TopologyListName, type TopologyRow,
  type TopologyRows, type TopologyTarget } from "./topologyData";

const TITLES: Record<TopologyListName, string> = {
  nodes: "Nodes", cables: "Cable map", structural_links: "Structural links", failure_impact: "Failure impact", source_addresses: "Observed address records",
};
export type DesiredPathQuery = { request_id: string; query: { src_ip: string; dst_ip: string } | null };
type NestedEvidence = SourceList & { readonly items: readonly ({ readonly index?: number; readonly pointer?: string; readonly role?: string;
  readonly a_port?: Fact; readonly b_port?: Fact })[] };

function fieldLabel(name: string) { return name.replaceAll("_", " "); }
function RowFacts({ row, list }: { row: TopologyRow; list: TopologyListName }) {
  // Every fact here is a typed engine field. This merely selects envelope fields for display;
  // it does not classify their values or construct a replacement for a withheld fact. The one
  // owner mark it forwards is a failure-impact lower bound: a published measure that cites a
  // witness (projectionImpactBound), shown as "≥ N" like every other failure-impact surface.
  const facts = Object.entries(row).filter(([, value]) => typeof value === "object" && value !== null && "value" in value) as [string, Fact][];
  return <div className="projection-fact-grid">{facts.map(([name, fact]) => <FactView key={name} label={fieldLabel(name)} fact={fact} compact
    lowerBound={list === "failure_impact" ? projectionImpactBound(name, fact) : undefined} />)}</div>;
}
function RowEvidence({ row }: { row: TopologyRow }) {
  const lists = Object.entries(row).filter(([, value]) => typeof value === "object" && value !== null && "items" in value) as [string, NestedEvidence][];
  return <>{lists.map(([name, list]) => <details key={name}><summary>{fieldLabel(name)}</summary>
    <ListState label={fieldLabel(name)} source={list} />
    <ul>{list.items.map((item, index) => <li key={`${item.pointer ?? "row"}:${item.index ?? index}`}>
      {item.pointer && <code>{item.pointer}</code>}{item.index !== undefined && <span> · source row {item.index}</span>}
      {item.role && <span> · {item.role}</span>}
      {item.a_port && <FactView label="Member A port" fact={item.a_port} compact />}
      {item.b_port && <FactView label="Member B port" fact={item.b_port} compact />}
    </li>)}</ul>
  </details>)}</>;
}
function pathNodeKeys(path: PathProjection | null, rows: TopologyRows): ReadonlySet<string> {
  const result = new Set<string>();
  if (path?.payload.result.state !== "published" || path.payload.hop_evidence.state !== "published") return result;
  for (const hop of path.payload.hop_evidence.items) {
    const node = exactEndpoint(hop.node_rows, rows.nodes);
    if (node) result.add(rowKey(node));
  }
  return result;
}

function PathResult({ path, rows, select }: { path: PathProjection; rows: TopologyRows; select: (target: TopologyTarget) => void }) {
  const p = path.payload;
  return <section className="panel topology-path-result" aria-label="Route-model result">
    <h2>Route-model result</h2><FactView label="Engine path presentation" fact={p.style} compact />
    <p>Accepted query: <code>{p.query.src_ip}</code> → <code>{p.query.dst_ip}</code></p>
    <p className="projection-disclosure">This is an investigation of the stored route model. It does not prove live traffic, ACL/NAT behavior, return-path delivery or IPv6 MTU suitability.</p>
    {p.result.state === "published" && <>
      <dl className="projection-record"><div><dt>Owner status</dt><dd>{p.result.value.status}</dd></div>
        <div><dt>Owner source</dt><dd>{p.result.value.src}</dd></div><div><dt>Owner destination</dt><dd>{p.result.value.dst}</dd></div></dl>
      <ol className="topology-hops">{p.result.value.hops.map((hop, index) => {
        const evidence = p.hop_evidence.items.filter((item) => item.hop_index === index);
        return <li key={index}><h3>Hop {index + 1}: {hop.host}</h3><ValueText value={hop} />
          {evidence.map((item, ordinal) => <div key={ordinal}>
            <ListState label={`Hop ${index + 1} route evidence`} source={item.route_rows} />
            {item.route_rows.items.map((ref) => <code className="projection-pointer" key={rowKey(ref)}>{ref.pointer}</code>)}
            <ListState label={`Hop ${index + 1} interface evidence`} source={item.interfaces} />
            {item.interfaces.items.map((ref, i) => <code className="projection-pointer" key={`${ref.pointer}:${i}`}>{ref.role}: {ref.pointer}</code>)}
            <ListState label={`Hop ${index + 1} node evidence`} source={item.node_rows} />
            {item.node_rows.state === "published" && item.node_rows.items.length === 1 && item.node_rows.items.map((ref) => {
              const target = { list: "nodes" as const, row: ref };
              return hasTarget(rows, target) ? <button className="btn" key={rowKey(ref)} onClick={() => select(target)}>Locate node record for hop {index + 1}</button> : null;
            })}
            {!exactEndpoint(item.node_rows, rows.nodes) && <p className="projection-disclosure">No unique engine-published node join is available for this hop.</p>}
          </div>)}
        </li>;
      })}</ol>
      {!p.result.value.hops.length && <p>The owner returned no hop records.</p>}
    </>}
    <ListState label="Path hop evidence" source={p.hop_evidence} />
    <details><summary>Complete owner result, including ECMP and MTU details</summary><FactView label="Complete route-model result" fact={p.result} /></details>
    {p.result.state !== "published" && <FactView label="Withheld route-model result" fact={p.result} />}
  </section>;
}

export function TopologyPaths({ document, reload }: { document: TopologyDocument; reload: () => void }) {
  const identityKey = JSON.stringify(document.identity);
  const [assembly, setAssembly] = useState<{ key: string; rows: TopologyRows; complete: boolean; message: string; fatal: boolean } | null>(null);
  const [selected, setSelected] = useState<TopologyTarget | null>(null);
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  const [src, setSrc] = useState(""); const [dst, setDst] = useState("");
  const [path, setPath] = useState<PathProjection | null>(null);
  const [pathError, setPathError] = useState(""); const [pathBusy, setPathBusy] = useState(false);
  const [desired, setDesired] = useState<DesiredPathQuery>({ request_id: "initial-clear", query: null });
  const pathController = useRef<AbortController | null>(null);
  const pathTimeout = useRef<number | null>(null);
  const generation = useRef(0);
  const rows = assembly?.key === identityKey ? assembly.rows : null;
  const currentAssembly = assembly?.key === identityKey ? assembly : null;

  function clearPath() {
    pathController.current?.abort(); generation.current += 1;
    if (pathTimeout.current !== null) window.clearTimeout(pathTimeout.current);
    setPath(null); setPathError(""); setPathBusy(false); setSelected(null);
    setDesired({ request_id: `clear-${generation.current}`, query: null });
  }
  useEffect(() => {
    const controller = new AbortController();
    clearPath(); setMode("2d"); setSrc(""); setDst(""); setAssembly(null);
    let initial: TopologyRows;
    try {
      initial = initialTopologyRows(document);
      setAssembly({ key: identityKey, rows: initial, complete: false, message: "Loading source-bound topology pages…", fatal: false });
    } catch {
      setAssembly({ key: identityKey, rows: { nodes: [], cables: [], structural_links: [], failure_impact: [], source_addresses: [] }, complete: false,
        message: "The topology transport is inconsistent. Reload the view.", fatal: true });
      return () => controller.abort();
    }
    assembleTopology(document, controller.signal, (next) => {
      if (!controller.signal.aborted) setAssembly({ key: identityKey, rows: next, complete: false, message: "Loading source-bound topology pages…", fatal: false });
    }).then((complete) => {
      if (!controller.signal.aborted) setAssembly({ key: identityKey, rows: complete, complete: true, message: "All projected list pages loaded. This is not a claim of complete network evidence.", fatal: false });
    }).catch((error) => {
      if (controller.signal.aborted) return;
      const limited = error instanceof TopologyCapacityError;
      setAssembly({ key: identityKey, rows: limited ? initial : { nodes: [], cables: [], structural_links: [], failure_impact: [], source_addresses: [] }, complete: false,
        message: error instanceof Error ? error.message : "Topology pages could not be loaded.", fatal: !limited });
      clearPath(); setMode("2d");
    });
    return () => { controller.abort(); pathController.current?.abort(); generation.current += 1;
      if (pathTimeout.current !== null) window.clearTimeout(pathTimeout.current); };
  }, [document, identityKey]);

  function choose(target: TopologyTarget | null) {
    if (target === null || (rows && hasTarget(rows, target))) setSelected(target);
  }
  function updateAddress(kind: "src" | "dst", value: string) {
    clearPath(); if (kind === "src") setSrc(value); else setDst(value);
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); clearPath();
    const currentGeneration = ++generation.current;
    const controller = new AbortController(); pathController.current = controller;
    const query = { src_ip: src, dst_ip: dst };
    setPathBusy(true); setDesired({ request_id: `path-${currentGeneration}`, query });
    pathTimeout.current = window.setTimeout(() => {
      if (generation.current !== currentGeneration) return;
      controller.abort(); generation.current += 1; setPathBusy(false);
      setPathError("The path request timed out. Retry the engine investigation.");
      setDesired({ request_id: `timeout-${generation.current}`, query: null });
    }, 30_000);
    try {
      const result = await loadPathProjection(document, query.src_ip, query.dst_ip, controller.signal);
      if (!controller.signal.aborted && generation.current === currentGeneration) setPath(result);
    } catch (error) {
      if (!controller.signal.aborted && generation.current === currentGeneration) {
        setPathError(error instanceof Error ? error.message : "Path investigation could not be loaded.");
        setDesired({ request_id: `failed-${currentGeneration}`, query: null });
        if (error instanceof ProjectionContextError || (error instanceof ApiError && [404, 409].includes(error.status))) {
          setAssembly((old) => old && ({ ...old, complete: false, fatal: true, message: "Stored snapshot authority or context changed. Reload this view before continuing." }));
          setMode("2d");
        }
      }
    } finally { if (generation.current === currentGeneration) {
      if (pathTimeout.current !== null) window.clearTimeout(pathTimeout.current);
      if (!controller.signal.aborted) setPathBusy(false);
    } }
  }
  if (!rows || !currentAssembly) return <section className="panel" role="status">Preparing topology…</section>;
  if (currentAssembly.fatal) return <section className="panel projection-error" role="alert"><h2>Topology unavailable</h2><p>{currentAssembly.message}</p><button className="btn" onClick={reload}>Reload topology</button></section>;
  const selectedRow = selected ? rows[selected.list].find((row) => rowKey(row) === rowKey(selected.row)) : undefined;
  return <>
    <section className="panel"><h2>Topology &amp; Paths</h2>
      <div className="projection-fact-grid"><FactView label="Engine node total" fact={document.payload.summary.nodes} compact />
        <FactView label="Engine cable total" fact={document.payload.summary.cables} compact /></div>
      <p className="projection-disclosure" role="status">{currentAssembly.message}</p>
      <ul className="topology-census">{TOPOLOGY_LISTS.map((name) => <li key={name}>{TITLES[name]}: {rows[name].length} / {document.payload[name].page.total} projected rows loaded
        <ListState label={TITLES[name]} source={document.payload[name].source_list} /></li>)}</ul>
      <div className="projection-subnav" aria-label="Topology display">
        <button className="btn" aria-pressed={mode === "2d"} onClick={() => { clearPath(); setMode("2d"); }}>2-D map</button>
        <button className="btn" aria-pressed={mode === "3d"} disabled={!currentAssembly.complete} onClick={() => { clearPath(); setMode("3d"); }}>3-D investigation</button>
      </div>
    </section>
    {mode === "3d" && currentAssembly.complete && <TopologyScope document={document} rows={rows} selected={selected}
      desired={desired} onSelect={choose} onClear={clearPath} onReturnTo2D={() => { clearPath(); setMode("2d"); }} />}
    <div className="topology-workspace">
      <TopologyDiagram rows={rows} legend={document.payload.legend} selected={selected} pathNodes={pathNodeKeys(path, rows)} select={choose} />
      <section className="panel topology-inspector" aria-label="Topology record details"><h2>Record details</h2>
        {selected && selectedRow ? <><h3>{TITLES[selected.list]} · source row {selected.row.index}</h3><code>{selected.row.pointer}</code>
          <RowFacts row={selectedRow} list={selected.list} /><RowEvidence row={selectedRow} /><button className="btn" onClick={() => choose(null)}>Clear selected record</button></>
          : <p>Select a node, link or evidence-list record. Facts and their qualifications come from the engine.</p>}
      </section>
    </div>
    <section className="panel topology-path-form"><h2>Investigate an IP path</h2>
      <p>Choose an observed address or enter an IP. The engine investigates the stored route model; no live traffic is sent.</p>
      <form onSubmit={(event) => void submit(event)}>
        <label>Source IP<input name="source-ip" value={src} maxLength={128} required onChange={(event) => updateAddress("src", event.target.value)} /></label>
        <label>Destination IP<input name="destination-ip" value={dst} maxLength={128} required onChange={(event) => updateAddress("dst", event.target.value)} /></label>
        <button className="btn" type="submit" disabled={pathBusy || !src.length || !dst.length}>Investigate path</button>
        <button className="btn" type="button" onClick={clearPath}>Clear path result</button>
      </form>
      {pathBusy && <p role="status">Requesting the engine route-model result…</p>}
      {pathError && <p role="alert" className="projection-error">{pathError}</p>}
    </section>
    {path && <PathResult path={path} rows={rows} select={choose} />}
    <details className="panel topology-records"><summary>Topology evidence lists</summary>
      {TOPOLOGY_LISTS.map((name) => <ProjectionList key={name} title={TITLES[name]} document={document} initial={document.payload[name]}
        renderRow={(row) => <><code>{row.pointer}</code><RowFacts row={row} list={name} />
          <button className="btn" disabled={!hasTarget(rows, { list: name, row })}
            onClick={() => choose({ list: name, row: { index: row.index, pointer: row.pointer } })}>Inspect {TITLES[name].toLowerCase()} row {row.index}</button>
          {name === "source_addresses" && "address" in row && row.address.state === "published" && <div className="topology-address-actions">
            <button className="btn" onClick={() => updateAddress("src", row.address.value!)}>Use address as source</button>
            <button className="btn" onClick={() => updateAddress("dst", row.address.value!)}>Use address as destination</button></div>}
        </>} />)}
    </details>
  </>;
}
