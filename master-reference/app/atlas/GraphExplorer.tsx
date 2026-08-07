"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  beginCommunitySelection,
  rejectCommunitySelection,
  resolveCommunitySelection,
} from "./GraphSelection.mjs";
import type { CommunitySelection } from "./GraphSelection.mjs";
import { loadProjection, sourceHref } from "./SourceExplorerData";
import type { ProjectionModule } from "./SourceExplorerTypes";
import styles from "./GraphExplorer.module.css";

type GraphNode = {
  id: string;
  graphify_id: string;
  file_id: string;
  source_file: string;
  source_location: string;
  label: string;
  language: string;
  kind: string;
  community: number | null;
  origin: string;
  extraction_mode: string;
  unresolved_reasons: string[];
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
  source_file: string | null;
  source_location: string;
  extraction_mode: string;
  confidence: number | null;
  unresolved_reasons: string[];
};

type GraphState =
  | { state: "loading" }
  | { state: "missing"; message: string }
  | {
      state: "ready";
      module: ProjectionModule;
      summary: GraphSummary;
      nodes: GraphNode[];
      edges: GraphEdge[];
      commit: string;
      communitySelection:
        | CommunitySelection<GraphNode, GraphEdge>
        | {
            state: "overview";
            requestedCommunity: null;
            loadedCommunity: null;
            reason: null;
            message: string;
          };
    };

type GraphSummary = {
  nodeCount: number;
  edgeCount: number;
  communities: Array<{ id: string; nodeCount: number; edgeCount: number; nodeShards: number; edgeShards: number }>;
  sampleNodes: GraphNode[];
  sampleEdges: GraphEdge[];
  disclosure: string;
};

const DRAW_LIMIT = 48;
const TABLE_PAGE_SIZE = 150;

function point(index: number, count: number) {
  const angle = (index / Math.max(1, count)) * Math.PI * 2 - Math.PI / 2;
  return { x: 310 + Math.cos(angle) * 245, y: 280 + Math.sin(angle) * 215 };
}

export function GraphExplorer() {
  const [loadState, setLoadState] = useState<GraphState>({ state: "loading" });
  const [query, setQuery] = useState("");
  const [community, setCommunity] = useState("all");
  const [nodePage, setNodePage] = useState(0);
  const [edgePage, setEdgePage] = useState(0);
  const [urlReady, setUrlReady] = useState(false);
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());

  useEffect(() => {
    let active = true;
    void loadProjection()
      .then(async (module) => {
        const graph = module.projection.completeness.graphify;
        if (
          !graph ||
          graph.available !== true ||
          graph.status !== "current" ||
          graph.stale !== false ||
          graph.source_commit !== module.projection.sourceCommit
        ) {
          throw new Error("Graphify receipt is missing, stale, or not bound to this exact source commit.");
        }
        const summary = await module.loadGraphSummary() as GraphSummary;
        if (active) setLoadState({
          state: "ready",
          module,
          summary,
          nodes: summary.sampleNodes,
          edges: summary.sampleEdges,
          commit: module.projection.sourceCommit,
          communitySelection: {
            state: "overview",
            requestedCommunity: null,
            loadedCommunity: null,
            reason: null,
            message: "Showing the deterministic all-community overview.",
          },
        });
      })
      .catch(() => {
        if (active) {
          setLoadState({
            state: "missing",
            message: "The exact-commit Graphify projection is absent, unsafe, stale, or failed integrity validation.",
          });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const projectionModule = loadState.state === "ready" ? loadState.module : null;
  const graphSummary = loadState.state === "ready" ? loadState.summary : null;
  useEffect(() => {
    if (!projectionModule || !graphSummary) return;
    if (community === "all") {
      setLoadState((current) => current.state === "ready" ? {
        ...current,
        nodes: current.summary.sampleNodes,
        edges: current.summary.sampleEdges,
        communitySelection: {
          state: "overview",
          requestedCommunity: null,
          loadedCommunity: null,
          reason: null,
          message: "Showing the deterministic all-community overview.",
        },
      } : current);
      return;
    }
    const started = beginCommunitySelection<GraphNode, GraphEdge>(
      community,
      graphSummary.communities.map((entry) => entry.id),
    );
    setLoadState((current) => current.state === "ready" ? {
      ...current,
      nodes: [],
      edges: [],
      communitySelection: started,
    } : current);
    if (started.state === "abstained") return;
    let active = true;
    void projectionModule.loadGraphCommunity(community)
      .then((payload) => {
        if (!active) return;
        const selected = resolveCommunitySelection<GraphNode, GraphEdge>(community, payload);
        setLoadState((current) => current.state === "ready" ? {
          ...current,
          nodes: selected.nodes,
          edges: selected.edges,
          communitySelection: selected,
        } : current);
      })
      .catch(() => {
        if (!active) return;
        const selected = rejectCommunitySelection<GraphNode, GraphEdge>(community);
        setLoadState((current) => current.state === "ready" ? {
          ...current,
          nodes: selected.nodes,
          edges: selected.edges,
          communitySelection: selected,
        } : current);
      });
    return () => { active = false; };
  }, [community, graphSummary, projectionModule]);

  useEffect(() => {
    const parameters = new URLSearchParams(window.location.search);
    setQuery(parameters.get("q") ?? "");
    setCommunity(parameters.get("community") ?? "all");
    setUrlReady(true);
  }, []);

  useEffect(() => {
    if (!urlReady) return;
    const location = new URL(window.location.href);
    if (query) location.searchParams.set("q", query);
    else location.searchParams.delete("q");
    if (community !== "all") location.searchParams.set("community", community);
    else location.searchParams.delete("community");
    window.history.replaceState(null, "", `${location.pathname}${location.search}${location.hash}`);
    setNodePage(0);
    setEdgePage(0);
  }, [community, query, urlReady]);

  const ready = loadState.state === "ready" ? loadState : null;
  const communities = useMemo(
    () => ready?.summary.communities.map((entry) => entry.id) ?? [],
    [ready],
  );
  const unavailableCommunity = community !== "all" && !communities.includes(community);
  const viewBound = Boolean(
    ready && (
      (community === "all" && ready.communitySelection.state === "overview") ||
      (community !== "all" &&
        ready.communitySelection.state === "ready" &&
        ready.communitySelection.loadedCommunity === community)
    ),
  );
  const filtered = useMemo(() => {
    if (!ready || !viewBound) return [];
    return ready.nodes.filter((node) => {
      if (!deferredQuery) return true;
      return [node.label, node.source_file, node.language, node.kind, node.origin]
        .join(" ")
        .toLowerCase()
        .includes(deferredQuery);
    });
  }, [deferredQuery, ready, viewBound]);
  const filteredIds = useMemo(() => new Set(filtered.map((node) => node.id)), [filtered]);
  const filteredEdges = useMemo(() => {
    if (!ready || !viewBound) return [];
    if (!deferredQuery) return ready.edges;
    return ready.edges.filter((edge) => filteredIds.has(edge.source) || filteredIds.has(edge.target));
  }, [deferredQuery, filteredIds, ready, viewBound]);
  const nodeRows = filtered.slice(nodePage * TABLE_PAGE_SIZE, (nodePage + 1) * TABLE_PAGE_SIZE);
  const edgeRows = filteredEdges.slice(edgePage * TABLE_PAGE_SIZE, (edgePage + 1) * TABLE_PAGE_SIZE);
  const nodeById = useMemo(
    () => new Map((ready?.nodes ?? []).map((node) => [node.id, node])),
    [ready],
  );
  const drawn = filtered.slice(0, DRAW_LIMIT);
  const positions = new Map(drawn.map((node, index) => [node.id, point(index, drawn.length)]));
  const drawnEdges = ready?.edges.filter((edge) => positions.has(edge.source) && positions.has(edge.target)) ?? [];
  const communityCounts = useMemo(
    () => (ready?.summary.communities ?? []).map((entry) => [entry.id, entry.nodeCount] as const).sort((left, right) => right[1] - left[1]),
    [ready],
  );

  if (loadState.state === "loading") {
    return <output className={styles.state}><strong>Loading bounded graph overview…</strong><span>Complete node and edge partitions remain lazy until a community is selected.</span></output>;
  }
  if (loadState.state === "missing") {
    return <div className={styles.state}><strong>Graph unavailable</strong><span>{loadState.message}</span></div>;
  }

  return (
    <div className={styles.workspace}>
      <div className={styles.proof}>
        <div><strong>{loadState.summary.nodeCount.toLocaleString()}</strong><span>safe nodes retained</span></div>
        <div><strong>{loadState.summary.edgeCount.toLocaleString()}</strong><span>safe edges retained</span></div>
        <div><strong>{communityCounts.length.toLocaleString()}</strong><span>communities incl. unassigned</span></div>
        <div><strong>{loadState.commit.slice(0, 12)}</strong><span>source commit</span></div>
      </div>

      <div className={styles.controls}>
        <label><span>Find node</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="symbol, path, language…" /></label>
        <label><span>Community</span><select value={community} onChange={(event) => setCommunity(event.target.value)}><option value="all">Bounded all-community overview</option>{unavailableCommunity ? <option value={community}>Unavailable: {community}</option> : null}{communities.map((value) => <option value={String(value)} key={value}>{value === "unassigned" ? "Unassigned" : `Community ${value}`}</option>)}</select></label>
      </div>

      <p className={styles.disclosure}>
        {loadState.communitySelection.state === "loading"
          ? loadState.communitySelection.message
          : loadState.communitySelection.state === "abstained"
            ? loadState.communitySelection.message
            : community === "all"
              ? `Showing a deterministic ${loadState.nodes.length}-node / ${loadState.edges.length}-edge overview. Select one community to load its complete retained records; all ${loadState.summary.nodeCount.toLocaleString()} nodes and ${loadState.summary.edgeCount.toLocaleString()} edges remain reachable community by community.`
              : `Showing ${filtered.length.toLocaleString()} matching nodes and ${filteredEdges.length.toLocaleString()} source-assigned edges for ${community === "unassigned" ? "the unassigned partition" : `community ${community}`}. Static extraction is not runtime truth.`}
      </p>

      <div className={styles.graphLayout}>
        <svg className={styles.graph} viewBox="0 0 620 560">
          <title>Deterministic Graphify node-and-edge sample</title>
          <desc>Up to forty-eight filtered nodes arranged in a circle, with retained edges between them. Use the adjacent table for exact accessible records.</desc>
          {drawnEdges.slice(0, 400).map((edge) => {
            const start = positions.get(edge.source);
            const end = positions.get(edge.target);
            return start && end ? <line x1={start.x} y1={start.y} x2={end.x} y2={end.y} key={edge.id} data-mode={edge.extraction_mode} /> : null;
          })}
          {drawn.map((node) => {
            const position = positions.get(node.id);
            return position ? <g key={node.id} transform={`translate(${position.x} ${position.y})`}><circle r="7" data-origin={node.origin} /><title>{node.label} · {node.source_file}</title></g> : null;
          })}
        </svg>
        <aside className={styles.communities} aria-label="Largest communities">
          <h2>Community shape</h2>
          {communityCounts.slice(0, 16).map(([id, count]) => <button type="button" onClick={() => setCommunity(id)} key={id}><span>{id === "unassigned" ? "Unassigned" : `Community ${id}`}</span><i><i style={{ width: `${Math.max(3, (count / communityCounts[0][1]) * 100)}%` }} /></i><strong>{count}</strong></button>)}
        </aside>
      </div>

      {loadState.communitySelection.state === "loading" ? (
        <output className={styles.state} aria-live="polite"><strong>Loading selected community…</strong><span>{loadState.communitySelection.message}</span></output>
      ) : loadState.communitySelection.state === "abstained" ? (
        <output className={styles.state} aria-live="polite"><strong>Community view abstained</strong><span>{loadState.communitySelection.message}</span><button type="button" onClick={() => setCommunity("all")}>Return to overview</button></output>
      ) : filtered.length ? (
        <div className={styles.tableWrap}>
          <table>
            <caption className="visually-hidden">{community === "all" ? "Bounded Graphify node overview" : "Complete filtered Graphify community node records"}</caption>
            <thead><tr><th scope="col">Node</th><th scope="col">Source</th><th scope="col">Kind / language</th><th scope="col">Community</th><th scope="col">Origin</th></tr></thead>
            <tbody>{nodeRows.map((node) => <tr key={node.id}><th scope="row">{node.label || node.graphify_id}<code>{node.id}</code></th><td><a href={sourceHref(node.source_file)}>{node.source_file}{node.source_location ? `:${node.source_location}` : ""}</a></td><td>{node.kind || "unknown"} · {node.language || "unknown"}</td><td>{node.community ?? "unassigned"}</td><td>{node.extraction_mode}</td></tr>)}</tbody>
          </table>
          <TablePager label="node" page={nodePage} total={filtered.length} onPage={setNodePage} />
          <table>
            <caption className="visually-hidden">{community === "all" ? "Bounded Graphify edge overview" : "Complete source-assigned Graphify community edge records"}</caption>
            <thead><tr><th scope="col">Source node</th><th scope="col">Relation</th><th scope="col">Target node</th><th scope="col">Extraction</th><th scope="col">Confidence</th></tr></thead>
            <tbody>{edgeRows.map((edge) => {
              const source = nodeById.get(edge.source);
              const target = nodeById.get(edge.target);
              return <tr key={edge.id}><th scope="row">{source?.label || edge.source}<code>{edge.source}</code></th><td>{edge.relation}</td><td>{target?.label || edge.target}<code>{edge.target}</code></td><td>{edge.extraction_mode}</td><td>{edge.confidence ?? "not scored"}</td></tr>;
            })}</tbody>
          </table>
          <TablePager label="edge" page={edgePage} total={filteredEdges.length} onPage={setEdgePage} />
        </div>
      ) : <div className={styles.state}><strong>No graph node matches this view.</strong><button type="button" onClick={() => { setQuery(""); setCommunity("all"); }}>Clear graph filters</button></div>}
    </div>
  );
}

function TablePager({ label, page, total, onPage }: { label: string; page: number; total: number; onPage: (page: number) => void }) {
  const pageCount = Math.max(1, Math.ceil(total / TABLE_PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  return <nav className={styles.pager} aria-label={`Graph ${label} table pages`}><button type="button" disabled={safePage === 0} onClick={() => onPage(safePage - 1)}>Previous</button><span>Page {safePage + 1} of {pageCount} · {total.toLocaleString()} {label}s</span><button type="button" disabled={safePage + 1 >= pageCount} onClick={() => onPage(safePage + 1)}>Next</button></nav>;
}
