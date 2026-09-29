/**
 * blast.ts — topology and blast-radius analysis over the compiled cable map.
 *
 * This is the layer that turns the fabric view into an investigation surface: what is load-bearing,
 * what breaks when a given box or cable fails, and how two hosts could be adjacent at all. Every
 * function here is pure over the compiled snapshot and deterministic — same input, same bytes out —
 * so a result can be put in a URL and reproduced by someone else.
 *
 * Four honesty rules shape every type in this file:
 *
 *  1. A link is only connectivity when the collector observed it up. `down` carries nothing;
 *     anything else (including `unknown`) is a THIRD class that is neither, and a result that
 *     depends on one is reported uncertain rather than assumed working. We refuse to guess vendor
 *     spellings: exactly "up" carries, exactly "down" is down, every other string is unknown — an
 *     unrecognised status silently mapped to either pole is how absence becomes health.
 *  2. A device the collector never reached (`collected:false`) cannot be shown to forward anything.
 *     It is still really there — it stays in the topology as an attached node — but the default
 *     projection does not route paths through it. The alternative projection is always computed and
 *     reported alongside, because which one you believe changes the answer (in this snapshot it
 *     inverts it), and that choice belongs to the engineer, not to this module.
 *  3. Nothing returns a value that reads as success when the question could not be answered. Where
 *     a count is unknowable the field is `null` with `determinable:false` and a stated reason. The
 *     converse holds too: nothing returns a value that reads as damage the failure did not cause.
 *  4. A failure is charged only with what IT breaks. Brownfield snapshots arrive already in pieces,
 *     so every blast radius is measured inside the failed element's own component against the
 *     largest piece that component survives as — never against the globally largest component, and
 *     never including hosts that were isolated or in another component to begin with. What was
 *     already broken is reported separately, in `alreadyDisconnected`.
 *
 * Nothing here is a forwarding claim. Adjacency is L1/L2 cable evidence; whether a packet actually
 * traverses it is decided by the RIB and ACLs, which live in src/forwarding.
 */
import { deviceById, endpointsByHost, fabric, linkById } from "../core/data";
import type { Cite, Device, FailureImpact, Link, OpStatus } from "../core/types";
import { cableCountPhrase, disputeSentence, findPortDisputes, hostCableAccount, type PortDispute } from "./port-claims";

/* ── graph contract ─────────────────────────────────────────────────────────── */

export type CarryingClass = "carrying" | "observed-down" | "unknown-status";

/** Whether a never-collected device may be used as a transit hop. See honesty rule 2. */
export type TransitPolicy = "collected-only" | "all-nodes";
export type UnknownStatusPolicy = "exclude" | "include";

export interface GraphOptions {
  transit: TransitPolicy;
  unknownStatus: UnknownStatusPolicy;
}

export const DEFAULT_GRAPH_OPTIONS: GraphOptions = { transit: "collected-only", unknownStatus: "exclude" };

export type Certainty = "observed" | "uncertain" | "not-determinable";

export type AssumptionId =
  | "link-status-policy"
  | "unknown-status-links"
  | "uncollected-transit"
  | "single-end-confirmation"
  | "port-channel-granularity"
  | "endpoint-record-floor"
  | "topology-not-forwarding"
  | "engine-measure-basis";

export interface Assumption {
  id: AssumptionId;
  statement: string;
  cites: Cite[];
}

export interface AdjacencyEntry {
  host: string;
  linkId: string;
}

export interface GraphEdge {
  linkId: string;
  a: string;
  b: string;
  status: OpStatus;
  carrying: CarryingClass;
  isPortChannel: boolean;
  memberCount: number;
  confirmation: string | null;
  cite: Cite;
}

export type ExclusionReason = "self-loop" | "observed-down" | "unknown-status" | "non-transit-endpoint";

export interface ExcludedLink {
  linkId: string;
  a: string;
  b: string;
  reason: ExclusionReason;
  detail: string;
  cite: Cite;
}

/** A node that is in the topology but not carrying transit in this projection. */
export interface AttachedNode {
  host: string;
  /** `null` when no device record exists at all — different from a device known to be uncollected. */
  collected: boolean | null;
  carryingAttachments: AdjacencyEntry[];
  uncertainAttachments: AdjacencyEntry[];
  downAttachments: AdjacencyEntry[];
  cite: Cite;
}

export interface TopologyGraph {
  options: GraphOptions;
  /** Transit-capable nodes only, sorted. Attached-but-not-transit nodes live in `attachedNonTransit`. */
  nodes: string[];
  /** A view, not a Map: it has no `set`/`delete` at all. See `readonlyAdjacency`. */
  adjacency: ReadonlyMap<string, readonly AdjacencyEntry[]>;
  edges: GraphEdge[];
  excluded: ExcludedLink[];
  downLinkIds: string[];
  uncertainLinkIds: string[];
  attachedNonTransit: AttachedNode[];
  /** Transit nodes with no carrying edge at all. Isolated is a finding, not a clean slate. */
  isolatedNodes: string[];
  assumptions: Assumption[];
  claim: string;
  /** Kept so any analysis can rebuild the counter-projection from the same evidence. */
  source: { links: readonly Link[]; devices: readonly Device[] };
}

/* ── status classification ──────────────────────────────────────────────────── */

const classify = (status: OpStatus): CarryingClass => {
  const s = String(status ?? "").trim().toLowerCase();
  if (s === "up") return "carrying";
  if (s === "down") return "observed-down";
  return "unknown-status";
};

const ONE_END = /one end/i;

const sortedUnique = (xs: Iterable<string>): string[] => [...new Set(xs)].sort();

/**
 * Code-unit ordering. `localeCompare` without an explicit locale is ICU- and environment-dependent,
 * and mixing it with `Array.prototype.sort` (which is code-unit) in one module means two machines
 * can enumerate the same fabric in different orders — a result that cannot be put in a URL and
 * reproduced is not the contract this file claims.
 */
const cmp = (x: string, y: string): number => (x < y ? -1 : x > y ? 1 : 0);

const byHostThenLink = (x: AdjacencyEntry, y: AdjacencyEntry): number =>
  cmp(x.host, y.host) || cmp(x.linkId, y.linkId);

/* ── graph construction ─────────────────────────────────────────────────────── */

/**
 * `Object.freeze` does nothing to a Map: `set` and `delete` are prototype methods, not own
 * properties, so a frozen Map still mutates. The memoised graph is handed to every surface, so the
 * adjacency index is exposed as a delegating view that has no mutator to call in the first place —
 * a stray `adjacency.set(...)` from a renderer is a TypeError here and a compile error there.
 */
function readonlyAdjacency(
  m: ReadonlyMap<string, readonly AdjacencyEntry[]>,
): ReadonlyMap<string, readonly AdjacencyEntry[]> {
  const view: ReadonlyMap<string, readonly AdjacencyEntry[]> = {
    get size() {
      return m.size;
    },
    get: (k) => m.get(k),
    has: (k) => m.has(k),
    keys: () => m.keys(),
    values: () => m.values(),
    entries: () => m.entries(),
    forEach(cb, thisArg?: unknown) {
      m.forEach((v, k) => cb.call(thisArg, v, k, view));
    },
    [Symbol.iterator]: () => m[Symbol.iterator](),
  };
  return Object.freeze(view);
}

/**
 * Freeze every object this module created for the graph — the collections AND their members.
 *
 * Scope stated honestly: the `Link` and `Device` records reachable through `source` are inputs owned
 * by core/data.ts and shared with every other surface, so they are NOT frozen here; only the arrays
 * holding them (private copies) are. Freezing another module's records from this one would be a
 * cross-module side effect, and a guarantee this file cannot enforce should not be claimed.
 */
function freezeGraph(g: TopologyGraph): TopologyGraph {
  Object.freeze(g.options);
  for (const list of g.adjacency.values()) {
    for (const entry of list) Object.freeze(entry);
    Object.freeze(list);
  }
  for (const e of g.edges) Object.freeze(e);
  for (const x of g.excluded) Object.freeze(x);
  for (const a of g.attachedNonTransit) {
    for (const group of [a.carryingAttachments, a.uncertainAttachments, a.downAttachments]) {
      for (const entry of group) Object.freeze(entry);
      Object.freeze(group);
    }
    Object.freeze(a);
  }
  for (const a of g.assumptions) {
    Object.freeze(a.cites);
    Object.freeze(a);
  }
  for (const coll of [
    g.nodes,
    g.edges,
    g.excluded,
    g.downLinkIds,
    g.uncertainLinkIds,
    g.attachedNonTransit,
    g.isolatedNodes,
    g.assumptions,
    g.source.links,
    g.source.devices,
  ]) {
    Object.freeze(coll);
  }
  Object.freeze(g.source);
  return Object.freeze(g);
}

const graphCache = new Map<string, TopologyGraph>();

/** The default projection over the compiled snapshot. Memoised: the inputs are frozen at build. */
export function buildAdjacency(options?: Partial<GraphOptions>): TopologyGraph {
  const opts: GraphOptions = { ...DEFAULT_GRAPH_OPTIONS, ...options };
  const key = `${opts.transit}|${opts.unknownStatus}`;
  const hit = graphCache.get(key);
  if (hit) return hit;
  const built = buildAdjacencyFrom(fabric.links, fabric.devices, opts);
  graphCache.set(key, built);
  return built;
}

/**
 * Build a projection from explicit records. Exported so an analysis can be run against a
 * hypothesis ("what if this cable were down") using the real link records rather than fabricated
 * ones, and so tests can exercise a status class this snapshot happens not to contain.
 */
export function buildAdjacencyFrom(
  links: readonly Link[],
  devices: readonly Device[],
  options?: Partial<GraphOptions>,
): TopologyGraph {
  const opts: GraphOptions = { ...DEFAULT_GRAPH_OPTIONS, ...options };
  const deviceRec = new Map(devices.map((d) => [d.id, d]));
  const collectedOf = (h: string): boolean | null => {
    const d = deviceRec.get(h);
    return d ? d.collected : null;
  };
  const citeOf = (h: string): Cite => deviceRec.get(h)?.cite ?? `cable_map.nodes[host=${h}]`;
  const isTransit = (h: string): boolean => opts.transit === "all-nodes" || collectedOf(h) === true;

  const allHosts = sortedUnique([...devices.map((d) => d.id), ...links.flatMap((l) => [l.a, l.b])]);
  const nodes = allHosts.filter(isTransit);
  const nodeSet = new Set(nodes);

  const adjacency = new Map<string, AdjacencyEntry[]>(nodes.map((n) => [n, []]));
  const edges: GraphEdge[] = [];
  const excluded: ExcludedLink[] = [];
  const downLinkIds: string[] = [];
  const uncertainLinkIds: string[] = [];
  const attachments = new Map<string, AttachedNode>();

  const attachmentFor = (h: string): AttachedNode => {
    const found = attachments.get(h);
    if (found) return found;
    const fresh: AttachedNode = {
      host: h,
      collected: collectedOf(h),
      carryingAttachments: [],
      uncertainAttachments: [],
      downAttachments: [],
      cite: citeOf(h),
    };
    attachments.set(h, fresh);
    return fresh;
  };

  for (const l of links) {
    const carrying = classify(l.opStatus);
    if (carrying === "observed-down") downLinkIds.push(l.id);
    if (carrying === "unknown-status") uncertainLinkIds.push(l.id);

    // Record the far side of every cable touching a non-transit node, whatever its status: the
    // node is really cabled there even when we refuse to route through it.
    for (const [near, far] of [[l.a, l.b], [l.b, l.a]] as const) {
      if (nodeSet.has(near)) continue;
      const rec = attachmentFor(near);
      const entry: AdjacencyEntry = { host: far, linkId: l.id };
      if (carrying === "carrying") rec.carryingAttachments.push(entry);
      else if (carrying === "observed-down") rec.downAttachments.push(entry);
      else rec.uncertainAttachments.push(entry);
    }

    const reason: ExclusionReason | null =
      l.a === l.b
        ? "self-loop"
        : carrying === "observed-down"
          ? "observed-down"
          : carrying === "unknown-status" && opts.unknownStatus === "exclude"
            ? "unknown-status"
            : !nodeSet.has(l.a) || !nodeSet.has(l.b)
              ? "non-transit-endpoint"
              : null;

    if (reason !== null) {
      excluded.push({
        linkId: l.id,
        a: l.a,
        b: l.b,
        reason,
        detail: exclusionDetail(reason, l, collectedOf),
        cite: l.cite,
      });
      continue;
    }

    edges.push({
      linkId: l.id,
      a: l.a,
      b: l.b,
      status: l.opStatus,
      carrying,
      isPortChannel: l.isPortChannel,
      memberCount: l.members.length,
      confirmation: l.confirmation,
      cite: l.cite,
    });
    adjacency.get(l.a)?.push({ host: l.b, linkId: l.id });
    adjacency.get(l.b)?.push({ host: l.a, linkId: l.id });
  }

  for (const list of adjacency.values()) list.sort(byHostThenLink);

  const isolatedNodes = nodes.filter((n) => (adjacency.get(n) ?? []).length === 0);
  const attachedNonTransit = [...attachments.values()].sort((x, y) => cmp(x.host, y.host));

  const graph: TopologyGraph = {
    options: opts,
    nodes,
    adjacency: readonlyAdjacency(adjacency),
    edges,
    excluded,
    downLinkIds,
    uncertainLinkIds,
    attachedNonTransit,
    isolatedNodes,
    assumptions: [],
    claim:
      "Connectivity projection over observed cable-map adjacency: " +
      `${edges.length} of ${links.length} cables carry traffic here, ${nodes.length} of ${allHosts.length} hosts can transit. ` +
      "It describes physical/L2 adjacency, not forwarding.",
    // Private copies: the caller keeps whatever array it passed, and freezing ours cannot reach
    // back into fabric.links and immobilise a shared input other surfaces still own.
    source: { links: [...links], devices: [...devices] },
  };
  graph.assumptions = graphAssumptions(graph, links, deviceRec);
  // The projection is memoised and handed to every surface, so a stray write from a renderer would
  // be silent cross-surface corruption of shared evidence. Deep-freeze turns it into a loud error.
  return freezeGraph(graph);
}

function exclusionDetail(
  reason: ExclusionReason,
  l: Link,
  collectedOf: (h: string) => boolean | null,
): string {
  switch (reason) {
    case "self-loop":
      return `Both ends of ${l.id} name ${l.a}; it cannot carry traffic between distinct hosts.`;
    case "observed-down":
      return `${l.id} was observed down (${l.opStatus}); a down cable carries nothing.`;
    case "unknown-status":
      return `${l.id} has no observed operational status (${l.opStatus}); excluded from connectivity, which is not a claim that it is down.`;
    case "non-transit-endpoint": {
      const ends = [l.a, l.b].filter((h) => collectedOf(h) !== true);
      return `${l.id} ends on ${ends.join(", ")}, never collected, so this projection cannot show it forwarding.`;
    }
  }
}

function graphAssumptions(
  g: TopologyGraph,
  links: readonly Link[],
  deviceRec: ReadonlyMap<string, Device>,
): Assumption[] {
  const out: Assumption[] = [];
  const down = links.filter((l) => classify(l.opStatus) === "observed-down");
  const unknown = links.filter((l) => classify(l.opStatus) === "unknown-status");

  out.push({
    id: "link-status-policy",
    statement:
      `Only cables the collector observed up carry connectivity (${g.edges.length} in this projection). ` +
      `${down.length} observed down carry nothing. ${unknown.length} have no observed status and are ` +
      `${g.options.unknownStatus === "exclude" ? "excluded" : "included"} here.`,
    cites: [fabric.coverage.cite, ...down.map((l) => l.cite)],
  });

  out.push({
    id: "topology-not-forwarding",
    statement:
      "This is cable-map adjacency. A path here says two hosts are physically/L2 adjacent, never that " +
      `traffic is forwarded along it; RIBs were collected for ${fabric.coverage.routableHosts.length} host(s) only ` +
      `(${fabric.coverage.routableHosts.join(", ") || "none"}).`,
    cites: [fabric.coverage.cite],
  });

  if (unknown.length > 0) {
    out.push({
      id: "unknown-status-links",
      statement:
        `${unknown.length} cable(s) (${unknown.map((l) => l.id).join(", ")}) have no observed operational status. ` +
        "Anything reachable only through them is reported unreachable here — that is a gap in evidence, not a down link.",
      cites: unknown.map((l) => l.cite),
    });
  }

  if (g.options.transit === "collected-only") {
    const uncollected = g.attachedNonTransit;
    if (uncollected.length > 0) {
      const widest = [...uncollected].sort(
        (x, y) => y.carryingAttachments.length - x.carryingAttachments.length || cmp(x.host, y.host),
      )[0];
      out.push({
        id: "uncollected-transit",
        statement:
          `${uncollected.length} host(s) present in the cable map were never collected ` +
          `(${uncollected.map((u) => u.host).join(", ")}). They are kept as attached nodes but no path is routed ` +
          `through them, because a device we never reached cannot be shown to forward.` +
          (widest && widest.carryingAttachments.length > 1
            ? ` ${widest.host} alone carries ${widest.carryingAttachments.length} such adjacencies, so this choice moves the answer.`
            : ""),
        cites: [fabric.coverage.cite, ...uncollected.map((u) => u.cite)],
      });
    }
  } else {
    const uncollectedIn = g.nodes.filter((n) => deviceRec.get(n)?.collected === false);
    if (uncollectedIn.length > 0) {
      out.push({
        id: "uncollected-transit",
        statement:
          `${uncollectedIn.length} never-collected host(s) (${uncollectedIn.join(", ")}) are treated as transit here. ` +
          "Their forwarding behaviour was never observed, so every path through one is an assumption.",
        cites: uncollectedIn.map((h) => deviceRec.get(h)?.cite ?? fabric.coverage.cite),
      });
    }
  }

  const oneEnd = links.filter((l) => l.confirmation !== null && ONE_END.test(l.confirmation));
  if (oneEnd.length > 0) {
    out.push({
      id: "single-end-confirmation",
      statement:
        `${oneEnd.length} of ${links.length} adjacencies are confirmed from one end only — one device's neighbour ` +
        "table, never corroborated by the far end. A name collision there becomes a false adjacency here.",
      cites: oneEnd.map((l) => l.cite),
    });
  }

  const pcs = g.edges.filter((e) => e.isPortChannel);
  if (pcs.length > 0) {
    out.push({
      id: "port-channel-granularity",
      statement:
        `${pcs.length} carrying edge(s) are port-channels modelled as a single link ` +
        `(${pcs.map((p) => `${p.linkId}:${p.memberCount} member(s)`).join(", ")}). Loss of individual members is not modelled.`,
      cites: pcs.map((p) => p.cite),
    });
  }

  return out;
}

/**
 * Every failure question reports its counter-projection, so an unmemoised `alternateGraph` rebuilds
 * the whole fabric two or three times per call — the dominant cost of a hypothesis sweep and of the
 * interaction budget. Keyed on the graph's own private `source.links` array, which is frozen and
 * unique per projection, so the memo is a pure function of identical inputs.
 */
const projectionCache = new WeakMap<readonly Link[], Map<string, TopologyGraph>>();

const alternateGraph = (g: TopologyGraph, patch: Partial<GraphOptions>): TopologyGraph => {
  const opts: GraphOptions = { ...g.options, ...patch };
  const key = `${opts.transit}|${opts.unknownStatus}`;
  let per = projectionCache.get(g.source.links);
  if (per === undefined) {
    per = new Map();
    projectionCache.set(g.source.links, per);
  }
  const hit = per.get(key);
  if (hit) return hit;
  const built = buildAdjacencyFrom(g.source.links, g.source.devices, opts);
  per.set(key, built);
  return built;
};

/** Same reasoning: graphs are immutable, so one Hopcroft–Tarjan pass per graph is enough. */
const lowlinkCache = new WeakMap<TopologyGraph, { articulation: string[]; bridges: string[] }>();

function cutSets(g: TopologyGraph): { articulation: string[]; bridges: string[] } {
  const hit = lowlinkCache.get(g);
  if (hit) return hit;
  const computed = lowlink(g);
  lowlinkCache.set(g, computed);
  return computed;
}

/* ── primitive traversals ───────────────────────────────────────────────────── */

interface Skip {
  node?: string | null;
  link?: string | null;
}

/** Components sorted largest first, then by first member; members sorted. Deterministic by construction. */
function componentsOf(g: TopologyGraph, skip: Skip = {}): string[][] {
  const seen = new Set<string>();
  const out: string[][] = [];
  for (const start of g.nodes) {
    if (start === skip.node || seen.has(start)) continue;
    const stack = [start];
    seen.add(start);
    const comp: string[] = [];
    while (stack.length > 0) {
      const cur = stack.pop();
      if (cur === undefined) break;
      comp.push(cur);
      for (const e of g.adjacency.get(cur) ?? []) {
        if (e.host === skip.node || e.linkId === skip.link || seen.has(e.host)) continue;
        seen.add(e.host);
        stack.push(e.host);
      }
    }
    out.push(comp.sort());
  }
  return out.sort((x, y) => y.length - x.length || cmp(x[0] ?? "", y[0] ?? ""));
}

function componentOf(g: TopologyGraph, host: string, skip: Skip = {}): string[] {
  if (!g.adjacency.has(host) || host === skip.node) return [];
  const seen = new Set([host]);
  const stack = [host];
  while (stack.length > 0) {
    const cur = stack.pop();
    if (cur === undefined) break;
    for (const e of g.adjacency.get(cur) ?? []) {
      if (e.host === skip.node || e.linkId === skip.link || seen.has(e.host)) continue;
      seen.add(e.host);
      stack.push(e.host);
    }
  }
  return [...seen].sort();
}

/**
 * Hopcroft–Tarjan, iterative — one DFS yields both cut vertices and bridges.
 *
 * Iterative rather than recursive because depth is bounded by the fabric, not by us, and a stack
 * overflow in an analysis engine reads to the user as "no findings". Parallel cables are handled by
 * skipping the parent EDGE id rather than the parent host: two cables between the same pair mean
 * neither is a bridge, and a host-keyed skip would wrongly call both one.
 */
function lowlink(g: TopologyGraph): { articulation: string[]; bridges: string[] } {
  const disc = new Map<string, number>();
  const low = new Map<string, number>();
  const artic = new Set<string>();
  const bridgeIds: string[] = [];
  let timer = 0;

  for (const root of g.nodes) {
    if (disc.has(root)) continue;
    disc.set(root, timer);
    low.set(root, timer);
    timer += 1;
    let rootChildren = 0;
    const stack: { node: string; parent: string | null; parentEdge: string | null; i: number }[] = [
      { node: root, parent: null, parentEdge: null, i: 0 },
    ];
    while (stack.length > 0) {
      const fr = stack[stack.length - 1];
      if (fr === undefined) break;
      const adj = g.adjacency.get(fr.node) ?? [];
      if (fr.i < adj.length) {
        const e = adj[fr.i];
        fr.i += 1;
        if (e === undefined || e.linkId === fr.parentEdge) continue;
        const seenAt = disc.get(e.host);
        if (seenAt !== undefined) {
          low.set(fr.node, Math.min(low.get(fr.node) ?? seenAt, seenAt));
          continue;
        }
        disc.set(e.host, timer);
        low.set(e.host, timer);
        timer += 1;
        if (fr.node === root) rootChildren += 1;
        stack.push({ node: e.host, parent: fr.node, parentEdge: e.linkId, i: 0 });
        continue;
      }
      stack.pop();
      const parent = fr.parent;
      if (parent === null) continue;
      const lowChild = low.get(fr.node) ?? 0;
      const lowParent = low.get(parent) ?? 0;
      const discParent = disc.get(parent) ?? 0;
      low.set(parent, Math.min(lowParent, lowChild));
      if (lowChild > discParent && fr.parentEdge !== null) bridgeIds.push(fr.parentEdge);
      if (parent !== root && lowChild >= discParent) artic.add(parent);
    }
    if (rootChildren > 1) artic.add(root);
  }
  return { articulation: [...artic].sort(), bridges: bridgeIds.sort() };
}

/* ── endpoint stranding ─────────────────────────────────────────────────────── */

export interface StrandedEndpoints {
  /** False when the question could not be answered at all — then `total` is null, never 0. */
  determinable: boolean;
  /** Arithmetic sum of observed endpoint_identity records across the affected hosts. */
  total: number | null;
  /**
   * The same sum, but only where it may be read as a floor: `null` when there ARE affected hosts and
   * not one of them carries a single endpoint record. This is the number a surface should render.
   * `total` would be 0 there, and 0 reads as "nothing is behind this cut" — the affected hosts'
   * endpoints are unknown in size, not absent. `hostsWithoutEndpointRecords` names them.
   */
  floorTotal: number | null;
  onFailedElement: number | null;
  onStrandedHosts: number | null;
  byHost: { host: string; count: number; cites: Cite[] }[];
  /** Hosts in the blast radius with no endpoint records: absence of records is not absence of endpoints. */
  hostsWithoutEndpointRecords: string[];
  /** Always true: endpoint_identity is what the collection observed, never a complete inventory. */
  floor: boolean;
  note: string;
}

const NOT_DETERMINABLE_ENDPOINTS = (note: string): StrandedEndpoints => ({
  determinable: false,
  total: null,
  floorTotal: null,
  onFailedElement: null,
  onStrandedHosts: null,
  byHost: [],
  hostsWithoutEndpointRecords: [],
  floor: true,
  note,
});

function strandedEndpoints(failed: string[], stranded: string[]): StrandedEndpoints {
  const count = (hosts: string[]): number =>
    hosts.reduce((sum, h) => sum + (endpointsByHost.get(h) ?? []).length, 0);
  const all = [...failed, ...stranded];
  const byHost = all
    .map((h) => {
      const eps = endpointsByHost.get(h) ?? [];
      return { host: h, count: eps.length, cites: eps.map((e) => e.cite) };
    })
    .filter((r) => r.count > 0)
    .sort((x, y) => y.count - x.count || cmp(x.host, y.host));
  const onFailedElement = count(failed);
  const onStrandedHosts = count(stranded);
  const total = onFailedElement + onStrandedHosts;
  return {
    determinable: true,
    total,
    // Nothing affected at all means a measured zero. Affected hosts with no records at all mean an
    // unknown, and publishing that as 0 is how absence becomes health.
    floorTotal: all.length === 0 || byHost.length > 0 ? total : null,
    onFailedElement,
    onStrandedHosts,
    byHost,
    hostsWithoutEndpointRecords: all.filter((h) => (endpointsByHost.get(h) ?? []).length === 0).sort(),
    floor: true,
    note:
      "A floor, not a total: the count is of observed endpoint_identity records on the affected hosts. " +
      "Hosts with no records are listed rather than counted as zero.",
  };
}

const endpointPhrase = (eps: StrandedEndpoints): string =>
  eps.floorTotal === null
    ? "an unknown number of endpoints (no endpoint_identity record exists for the affected host(s))"
    : `at least ${eps.floorTotal} observed endpoint(s)`;

/* ── articulation points ────────────────────────────────────────────────────── */

export interface ArticulationPoint {
  host: string;
  collected: boolean | null;
  componentsAfterRemoval: number;
  /**
   * Hosts that lose their path to the largest piece THIS HOST'S OWN component survives as. Hosts
   * that were already isolated or already in another component lose nothing here and are excluded —
   * `TopologyGraph.isolatedNodes` names the former in the same projection.
   */
  separatedHosts: string[];
  /** Observed-record floor, or `null` when no separated host has an endpoint record at all. */
  endpointsBehind: number | null;
  /** Separated hosts with no endpoint_identity record: absence of records is not absence of endpoints. */
  hostsWithoutEndpointRecords: string[];
  cite: Cite;
}

export interface ArticulationResult {
  graphOptions: GraphOptions;
  points: ArticulationPoint[];
  certainty: Certainty;
  caveats: string[];
  assumptions: Assumption[];
  claim: string;
}

export function articulationPoints(graph?: TopologyGraph): ArticulationResult {
  const g = graph ?? buildAdjacency();
  const found = cutSets(g).articulation;
  const before = componentsOf(g).length;

  // The same accounting failureImpact publishes, so the two surfaces cannot tell different stories
  // about one graph — the earlier divergence was itself the evidence that one of them was wrong.
  const points: ArticulationPoint[] = found.map((host) => {
    const outcome = removalOutcome(g, { node: host });
    const eps = strandedEndpoints([], outcome.newlyStranded);
    return {
      host,
      collected: deviceById.get(host)?.collected ?? null,
      componentsAfterRemoval: outcome.componentsAfter,
      separatedHosts: outcome.newlyStranded,
      endpointsBehind: eps.floorTotal,
      hostsWithoutEndpointRecords: eps.hostsWithoutEndpointRecords,
      cite: deviceById.get(host)?.cite ?? `cable_map.nodes[host=${host}]`,
    };
  });

  const alt = cutSets(alternateGraph(g, { unknownStatus: flip(g.options.unknownStatus) })).articulation;
  const differs = !sameSet(alt, found);
  const caveats: string[] = [];
  if (differs) {
    caveats.push(
      `Unknown-status cables move this answer: with them ${g.options.unknownStatus === "exclude" ? "included" : "excluded"} ` +
        `the cut vertices are ${alt.length > 0 ? alt.join(", ") : "none"}.`,
    );
  }
  if (before > 1) {
    caveats.push(`The projection is already in ${before} pieces before any failure; cut vertices are per-component.`);
  }
  // linkFailureImpact has always carried this; dropping it here made one module honest on one
  // surface and silent on the other about the same missing evidence.
  const unrecorded = sortedUnique(points.flatMap((p) => p.hostsWithoutEndpointRecords));
  if (unrecorded.length > 0) {
    caveats.push(
      `${unrecorded.join(", ")} sit behind a cut vertex with no endpoint_identity record; what they carry is unknown in size, not zero.`,
    );
  }
  return {
    graphOptions: g.options,
    points,
    certainty: differs ? "uncertain" : "observed",
    caveats,
    assumptions: g.assumptions,
    claim:
      `${points.length} host(s) are cut vertices of the observed adjacency graph: removing one splits the graph it ` +
      "belongs to. Single points of failure at the cable-map layer only — not a redundancy verdict for L3 or FHRP.",
  };
}

/* ── bridges, cross-checked against the engine's own centrality ─────────────── */

export interface BridgeEdge {
  linkId: string;
  a: string;
  b: string;
  /** The smaller of the two sides the cut produces — the blast radius of that cable. */
  smallerSide: string[];
  engineIsBridge: boolean | null;
  cite: Cite;
}

export interface BridgeAgreementRow {
  linkId: string;
  a: string;
  b: string;
  ours: boolean;
  /** `null` = the engine computed no centrality for this cable. Silence, not a "no". */
  engine: boolean | null;
  agreement: "agree" | "disagree" | "engine-silent";
  cite: Cite;
}

export interface BridgeComparison {
  rows: BridgeAgreementRow[];
  agreed: BridgeAgreementRow[];
  disagreed: BridgeAgreementRow[];
  /** Cables with no link_centrality record at all — absence of a record is not evidence of non-bridgehood. */
  linksWithoutEngineRecord: string[];
  ourBridgesOutsideEngineScope: string[];
  note: string;
}

export interface BridgeResult {
  graphOptions: GraphOptions;
  bridges: BridgeEdge[];
  engineComparison: BridgeComparison;
  certainty: Certainty;
  caveats: string[];
  assumptions: Assumption[];
  claim: string;
}

export function bridges(graph?: TopologyGraph): BridgeResult {
  const g = graph ?? buildAdjacency();
  const ours = new Set(cutSets(g).bridges);

  const bridgeEdges: BridgeEdge[] = g.edges
    .filter((e) => ours.has(e.linkId))
    .map((e) => {
      const sides = componentsOf(g, { link: e.linkId });
      const sideWithA = sides.find((c) => c.includes(e.a)) ?? [];
      const sideWithB = sides.find((c) => c.includes(e.b)) ?? [];
      const smaller = sideWithA.length <= sideWithB.length ? sideWithA : sideWithB;
      return {
        linkId: e.linkId,
        a: e.a,
        b: e.b,
        smallerSide: smaller,
        engineIsBridge: linkById.get(e.linkId)?.isBridge ?? null,
        cite: e.cite,
      };
    });

  const rows: BridgeAgreementRow[] = g.edges.map((e) => {
    const engine = linkById.get(e.linkId)?.isBridge ?? null;
    const oursIs = ours.has(e.linkId);
    return {
      linkId: e.linkId,
      a: e.a,
      b: e.b,
      ours: oursIs,
      engine,
      agreement: engine === null ? "engine-silent" : engine === oursIs ? "agree" : "disagree",
      cite: e.cite,
    };
  });
  const disagreed = rows.filter((r) => r.agreement === "disagree");

  const comparison: BridgeComparison = {
    rows,
    agreed: rows.filter((r) => r.agreement === "agree"),
    disagreed,
    linksWithoutEngineRecord: g.source.links.filter((l) => l.isBridge === null).map((l) => l.id),
    ourBridgesOutsideEngineScope: bridgeEdges.filter((b) => b.engineIsBridge === null).map((b) => b.linkId),
    note:
      disagreed.length === 0
        ? `Our cut edges match link_centrality on all ${rows.filter((r) => r.agreement !== "engine-silent").length} cable(s) it scored in this projection. ` +
          `${g.source.links.filter((l) => l.isBridge === null).length} cable(s) carry no centrality record at all and are not claimed either way.`
        : `${disagreed.length} cable(s) disagree with the engine's link_centrality. ` +
          `The engine scored the collected-only fabric; this projection is "${g.options.transit}". ` +
          "Where the two differ, one of the two graphs is the wrong model of the network — that is the finding, and it is " +
          "shown rather than reconciled.",
  };

  const altOurs = new Set(cutSets(alternateGraph(g, { unknownStatus: flip(g.options.unknownStatus) })).bridges);
  const differs = !sameSet([...altOurs], [...ours]);
  const caveats: string[] = [];
  if (differs) {
    caveats.push(
      "Unknown-status cables change which edges are cut edges; this result holds only under the stated status policy.",
    );
  }
  if (comparison.linksWithoutEngineRecord.length > 0) {
    caveats.push(
      `${comparison.linksWithoutEngineRecord.length} cable(s) have no engine centrality record; they are unscored by the engine, not scored as safe.`,
    );
  }

  return {
    graphOptions: g.options,
    bridges: bridgeEdges,
    engineComparison: comparison,
    certainty: differs ? "uncertain" : "observed",
    caveats,
    assumptions: g.assumptions,
    claim:
      `${bridgeEdges.length} cable(s) are cut edges of this projection: losing one partitions the fabric. ` +
      "Cable-map adjacency only; a port-channel counts as one cable.",
  };
}

/* ── failure impact ─────────────────────────────────────────────────────────── */

export interface SeveredLink {
  linkId: string;
  a: string;
  b: string;
  isPortChannel: boolean;
  memberCount: number;
  cite: Cite;
}

export interface EngineImpactComparison {
  record: FailureImpact | null;
  basis: "different-measure";
  qualitative:
    | "both-impact"
    | "both-none"
    | "engine-impact-only"
    | "ours-impact-only"
    /** The engine holds no record, or holds one with nothing observed in it. */
    | "engine-silent"
    /** We could not compute a blast radius at all — distinct from computing "none". */
    | "ours-not-determined";
  note: string;
}

export interface ProjectionDelta {
  options: GraphOptions;
  differs: boolean;
  /**
   * Each way this projection's answer differs from the one being reported, naming the quantity that
   * actually moved. Empty exactly when `differs` is false — a difference stated by quoting a
   * quantity that is equal ("3 stranded instead of 3") tells the engineer the opposite of the truth.
   */
  differences: string[];
  componentsAfter: number;
  newlyStrandedCount: number;
  /** Observed-record floor under this projection, `null` when no affected host has a record. */
  strandedEndpointTotal: number | null;
  note: string;
}

const listOrNone = (xs: readonly string[]): string => (xs.length === 0 ? "none" : xs.join(", "));

const floorWords = (n: number | null): string => (n === null ? "an unknown number of" : String(n));

/** The differences between two removal outcomes, each sentence built from a quantity that moved. */
function describeDelta(
  here: RemovalOutcome,
  there: RemovalOutcome,
  hereEps: number | null,
  thereEps: number | null,
): string[] {
  const out: string[] = [];
  if (!sameSet(here.newlyStranded, there.newlyStranded)) {
    out.push(
      here.newlyStranded.length === there.newlyStranded.length
        ? `the same ${there.newlyStranded.length} host(s) but a different set — ${listOrNone(there.newlyStranded)} instead of ${listOrNone(here.newlyStranded)}`
        : `${there.newlyStranded.length} host(s) stranded instead of ${here.newlyStranded.length}`,
    );
  }
  if (there.componentsAfter !== here.componentsAfter) {
    out.push(`${there.componentsAfter} component(s) remain instead of ${here.componentsAfter}`);
  }
  if (thereEps !== hereEps) {
    out.push(`${floorWords(thereEps)} endpoint(s) behind the cut instead of ${floorWords(hereEps)}`);
  }
  return out;
}

/**
 * The alternate projection's answer when the REPORTED projection has no answer to compare it with.
 *
 * If the element is not modelled under the reported projection (a device that does not transit, a
 * cable that does not carry), the reported pane says its blast radius is not observed. Diffing
 * against a removal of something that is not in the graph used to manufacture a baseline — "2
 * component(s) remain instead of 1" — so a value the pane had just declared unobserved came back as
 * a concrete "1 component", which reads as "no partition". There is no base number, so none is quoted.
 */
function unbasedDelta(alt: TopologyGraph, there: RemovalOutcome, thereEps: number | null, element: string, verb: string): ProjectionDelta {
  const stranded = there.newlyStranded.length;
  const reason =
    `Under this projection ${there.componentsAfter} component(s) remain and ${stranded} host(s) are stranded` +
    `${thereEps === null ? "" : `, with ${thereEps} observed endpoint(s) behind the cut`}. ` +
    `There is no reported count to compare this with: ${element} does not ${verb} under the reported projection, so its blast radius there is not observed rather than zero.`;
  return {
    options: alt.options,
    differs: true,
    differences: [reason],
    componentsAfter: there.componentsAfter,
    newlyStrandedCount: stranded,
    strandedEndpointTotal: thereEps,
    note: reason,
  };
}

const deltaNote = (differences: readonly string[]): string =>
  differences.length === 0
    ? "Same answer under this projection."
    : `Changing the projection changes the answer: ${differences.join("; ")}.`;

export type HostPresence = "transit-node" | "attached-non-transit" | "absent-from-topology";

export interface HostFailureResult {
  kind: "host";
  hostId: string;
  graphOptions: GraphOptions;
  presence: HostPresence;
  collected: boolean | null;
  /** Non-null when this host's internals were never collected, i.e. what rides on it is unknown. */
  reasoningLimit: string | null;
  componentsBefore: number;
  componentsAfter: number;
  /**
   * The largest piece THIS HOST'S OWN component survives as — the reference the radius is measured
   * against. Where no radius was computed (`certainty: "not-determinable"`) nothing was removed, so
   * it is the projection's largest component, unchanged.
   */
  largestRemaining: string[];
  /** Hosts that lose their path to `largestRemaining` BECAUSE of this failure. */
  newlyStranded: string[];
  /** Hosts already off this host's component before the failure — not attributable to it. */
  alreadyDisconnected: string[];
  /**
   * Attached non-transit nodes (APs, uncollected neighbours) whose every carrying cable lands in the
   * blast radius, so their observed cabling no longer reaches the largest remaining component.
   */
  strandedNonTransit: string[];
  severedLinks: SeveredLink[];
  strandedEndpoints: StrandedEndpoints;
  isArticulationPoint: boolean;
  engine: EngineImpactComparison;
  alternateProjections: ProjectionDelta[];
  certainty: Certainty;
  caveats: string[];
  assumptions: Assumption[];
  claim: string;
}

interface RemovalOutcome {
  componentsBefore: number;
  componentsAfter: number;
  largestRemaining: string[];
  newlyStranded: string[];
  alreadyDisconnected: string[];
  largestIsTied: boolean;
  /** The projection was in more than one piece before this failure; "largest" is then per-component. */
  preExistingPartition: boolean;
}

/**
 * What a removal actually costs, measured strictly inside the failed element's OWN component.
 *
 * The reference a blast radius is measured against must be the largest piece THAT component
 * survives as — not the largest component in the whole projection. On an already-partitioned
 * brownfield graph the two differ, and the global reading reports every peer of the failed element
 * as newly cut off from a component none of them ever reached: a pre-existing partition billed to
 * the element under test, complete with an endpoint count and `certainty: "observed"`.
 */
function removalOutcome(g: TopologyGraph, skip: Skip): RemovalOutcome {
  const anchor = skip.node ?? edgeEnd(g, skip.link);
  const before = componentsOf(g);
  const homeBefore = anchor === null ? (before[0] ?? []) : componentOf(g, anchor);
  const after = componentsOf(g, skip);
  const home = new Set(homeBefore);
  // Removal never merges components, so every post-removal piece is wholly inside or wholly outside
  // `home`; `after` is already ordered largest-first, so the first home piece is the reference.
  const homePieces = after.filter((c) => c.some((n) => home.has(n)));
  const reference = new Set(homePieces[0] ?? []);
  const second = homePieces[1];
  return {
    componentsBefore: before.length,
    componentsAfter: after.length,
    largestRemaining: homePieces[0] ?? [],
    newlyStranded: g.nodes.filter((n) => n !== skip.node && home.has(n) && !reference.has(n)).sort(),
    alreadyDisconnected: g.nodes.filter((n) => n !== skip.node && !home.has(n)).sort(),
    largestIsTied: second !== undefined && second.length === reference.size,
    preExistingPartition: before.length > 1,
  };
}

/** The end of a cut edge we measure "home" from — either end works, they are connected before the cut. */
function edgeEnd(g: TopologyGraph, linkId: string | null | undefined): string | null {
  if (!linkId) return null;
  return g.edges.find((e) => e.linkId === linkId)?.a ?? null;
}

const flip = (p: UnknownStatusPolicy): UnknownStatusPolicy => (p === "exclude" ? "include" : "exclude");
const flipTransit = (p: TransitPolicy): TransitPolicy => (p === "collected-only" ? "all-nodes" : "collected-only");

const sameSet = (x: readonly string[], y: readonly string[]): boolean =>
  x.length === y.length && [...x].sort().join("\u0000") === [...y].sort().join("\u0000");

export function failureImpact(hostId: string, graph?: TopologyGraph): HostFailureResult {
  const g = graph ?? buildAdjacency();
  const device = deviceById.get(hostId);
  const collected = device ? device.collected : null;
  const attached = g.attachedNonTransit.find((a) => a.host === hostId) ?? null;
  const presence: HostPresence = g.adjacency.has(hostId)
    ? "transit-node"
    : attached !== null
      ? "attached-non-transit"
      : "absent-from-topology";

  const touching = g.source.links.filter((l) => l.a === hostId || l.b === hostId);
  const severedLinks: SeveredLink[] = touching.map((l) => ({
    linkId: l.id,
    a: l.a,
    b: l.b,
    isPortChannel: l.isPortChannel,
    memberCount: l.members.length,
    cite: l.cite,
  }));

  const base = componentsOf(g).length;

  if (presence !== "transit-node") {
    const reason =
      presence === "absent-from-topology"
        ? `${hostId} is not present in this topology projection. That is not a claim that its failure has no impact — it is an absence of evidence about it.`
        : `${hostId} was never collected (${collected === false ? "collected:false" : "no device record"}), so what rides on it, and what it forwards, was never observed. The cable map records cables to it (how many can be real is stated below); its internals are unknown.`;
    return {
      kind: "host",
      hostId,
      graphOptions: g.options,
      presence,
      collected,
      reasoningLimit: reason,
      componentsBefore: base,
      componentsAfter: base,
      largestRemaining: componentsOf(g)[0] ?? [],
      newlyStranded: [],
      alreadyDisconnected: [],
      strandedNonTransit: [],
      severedLinks,
      strandedEndpoints: NOT_DETERMINABLE_ENDPOINTS(reason),
      isArticulationPoint: false,
      engine: compareEngineImpact(device ?? null, null),
      alternateProjections:
        presence === "attached-non-transit"
          ? [projectionDelta(g, { transit: flipTransit(g.options.transit) }, hostId)]
          : [],
      certainty: "not-determinable",
      caveats: [
        reason,
        ...(severedLinks.length > 0
          ? [
              (() => {
                /* Stated through the same one-port-one-cable detector as the link pane: when the
                   host's own port is claimed by several cables, the records are not all cables. */
                const acct = hostCableAccount(hostId, touching, findPortDisputes(g.source.links));
                const list = severedLinks.map((s) => s.linkId).join(", ");
                return acct.disputedLinkIds.length === 0
                  ? `${severedLinks.length} cable(s) terminate on it (${list}); their far ends lose this adjacency.`
                  : `${cableCountPhrase(acct)}. Records: ${list}; the far end of each one that is real loses this adjacency.`;
              })(),
            ]
          : []),
      ],
      assumptions: g.assumptions,
      claim: `No blast radius is computed for ${hostId}: ${presence === "absent-from-topology" ? "it is outside this projection" : "it was never collected and is not modelled as forwarding"}.`,
    };
  }

  const outcome = removalOutcome(g, { node: hostId });
  const detached = g.attachedNonTransit
    .filter(
      (a) =>
        a.carryingAttachments.length > 0 &&
        a.carryingAttachments.every((c) => c.host === hostId || outcome.newlyStranded.includes(c.host)),
    )
    .map((a) => a.host)
    .sort();
  const eps = strandedEndpoints([hostId], outcome.newlyStranded);
  const isArtic = cutSets(g).articulation.includes(hostId);

  const alternates = [
    projectionDelta(g, { transit: flipTransit(g.options.transit) }, hostId),
    ...(g.uncertainLinkIds.length > 0 ? [projectionDelta(g, { unknownStatus: flip(g.options.unknownStatus) }, hostId)] : []),
  ];

  const uncertainNear = g.uncertainLinkIds.filter((id) => {
    const l = g.source.links.find((s) => s.id === id);
    if (!l) return false;
    const near = new Set([hostId, ...outcome.newlyStranded]);
    return near.has(l.a) || near.has(l.b);
  });
  /* A cable near the radius whose port the cable map also places on another cable: the radius was
     computed over an adjacency that may not exist (./port-claims.ts). */
  const nearHosts = new Set([hostId, ...outcome.newlyStranded]);
  const disputedNear = findPortDisputes(g.source.links).filter((d) =>
    d.claims.some((c) => {
      const l = g.source.links.find((s) => s.id === c.linkId);
      return l !== undefined && g.edges.some((e) => e.linkId === l.id) && (nearHosts.has(l.a) || nearHosts.has(l.b));
    }),
  );
  const uncertain =
    uncertainNear.length > 0 || disputedNear.length > 0 || alternates.some((a) => a.differs && a.options.transit === g.options.transit);

  const caveats: string[] = [];
  for (const d of disputedNear) {
    caveats.push(
      `${d.host} ${d.port} is placed on ${d.claims.length} cables (${d.claims.map((c) => `${c.linkId}: ${c.confirmation ?? "confirmation not recorded"}`).join("; ")}); at most one is real and this radius was computed with every carrying one of them in place, so it may be wrong where they reach.`,
    );
  }
  if (uncertainNear.length > 0) {
    caveats.push(
      `Cable(s) ${uncertainNear.join(", ")} touch the blast radius and have no observed status; if they carry, this radius is smaller than stated.`,
    );
  }
  if (outcome.largestIsTied) {
    caveats.push(
      "Two remaining components are the same size, so 'largest remaining' is an arbitrary choice here; read the component list, not the label.",
    );
  }
  if (detached.length > 0) {
    caveats.push(
      `${detached.join(", ")} are cabled only into the blast radius and were never collected, so whatever they serve is absent from the endpoint count rather than unaffected.`,
    );
  }
  if (eps.hostsWithoutEndpointRecords.length > 0) {
    caveats.push(
      `${eps.hostsWithoutEndpointRecords.length} affected host(s) have no endpoint records; they are counted as unknown, not as zero endpoints.`,
    );
  }
  const altTransit = alternates.find((a) => a.options.transit !== g.options.transit);
  if (altTransit?.differs) {
    caveats.push(
      `The "${altTransit.options.transit}" projection answers differently: ${altTransit.differences.join("; ")}.`,
    );
  }
  if (outcome.preExistingPartition) {
    caveats.push(
      `The projection was already in ${outcome.componentsBefore} pieces before this failure; this radius is measured inside ${hostId}'s own piece, and the ${outcome.alreadyDisconnected.length} host(s) outside it were already unreachable from here.`,
    );
  }

  return {
    kind: "host",
    hostId,
    graphOptions: g.options,
    presence,
    collected,
    reasoningLimit: collected === true ? null : `${hostId} was never collected; its internal state is unknown even though its adjacency is observed.`,
    componentsBefore: outcome.componentsBefore,
    componentsAfter: outcome.componentsAfter,
    largestRemaining: outcome.largestRemaining,
    newlyStranded: outcome.newlyStranded,
    alreadyDisconnected: outcome.alreadyDisconnected,
    strandedNonTransit: detached,
    severedLinks,
    strandedEndpoints: eps,
    isArticulationPoint: isArtic,
    engine: compareEngineImpact(device ?? null, outcome.newlyStranded),
    alternateProjections: alternates,
    certainty: uncertain ? "uncertain" : "observed",
    caveats,
    assumptions: g.assumptions,
    claim:
      `Removing ${hostId} from the observed adjacency graph leaves ${outcome.componentsAfter} component(s) and cuts ` +
      `${outcome.newlyStranded.length} host(s) off the largest piece of its own component, with ` +
      `${endpointPhrase(eps)} behind the cut. ` +
      "Topology reachability only: it is not a claim about L3 convergence, FHRP failover or application impact.",
  };
}

export function compareEngineImpact(device: Device | null, ourStranded: string[] | null): EngineImpactComparison {
  const record = device?.impact ?? null;
  const note =
    "The engine's failure_impact counts VLAN-scoped endpoints from its own L2 analysis; ours counts endpoint records " +
    "on hosts separated in the topology graph. The two measure different things, so a numeric gap is not a contradiction — " +
    "a qualitative gap (one says partition, the other says none) is.";
  if (record === null || (record.stranded === null && record.hard === null)) {
    return { record, basis: "different-measure", qualitative: "engine-silent", note };
  }
  // Our side produced no verdict (host absent, or never collected). Reporting that as "we found no
  // impact" would manufacture a disagreement with the engine out of our own blind spot.
  if (ourStranded === null) {
    return { record, basis: "different-measure", qualitative: "ours-not-determined", note };
  }
  /* A half-null record is not "no impact": a null count is an unanswered question, never 0. One
     positive count is a positive observation on its own; but "no impact" needs BOTH counts present
     and zero, otherwise the engine was silent on the half that could have said otherwise. */
  const engineImpact = (record.stranded ?? 0) > 0 || (record.hard ?? 0) > 0;
  if (!engineImpact && (record.stranded === null || record.hard === null)) {
    return { record, basis: "different-measure", qualitative: "engine-silent", note };
  }
  const oursImpact = ourStranded.length > 0;
  const qualitative = engineImpact
    ? oursImpact
      ? "both-impact"
      : "engine-impact-only"
    : oursImpact
      ? "ours-impact-only"
      : "both-none";
  return { record, basis: "different-measure", qualitative, note };
}

function projectionDelta(g: TopologyGraph, patch: Partial<GraphOptions>, hostId: string): ProjectionDelta {
  const alt = alternateGraph(g, patch);
  if (!alt.adjacency.has(hostId)) {
    const reason = `${hostId} does not transit under this projection, so no blast radius is computed for it there.`;
    return {
      options: alt.options,
      differs: true,
      differences: [reason],
      componentsAfter: componentsOf(alt).length,
      newlyStrandedCount: 0,
      strandedEndpointTotal: null,
      note: reason,
    };
  }
  const there = removalOutcome(alt, { node: hostId });
  const thereEps = strandedEndpoints([hostId], there.newlyStranded);
  if (!g.adjacency.has(hostId)) return unbasedDelta(alt, there, thereEps.floorTotal, hostId, "transit");
  const here = removalOutcome(g, { node: hostId });
  const hereEps = strandedEndpoints([hostId], here.newlyStranded);
  const differences = describeDelta(here, there, hereEps.floorTotal, thereEps.floorTotal);
  return {
    options: alt.options,
    differs: differences.length > 0,
    differences,
    componentsAfter: there.componentsAfter,
    newlyStrandedCount: there.newlyStranded.length,
    strandedEndpointTotal: thereEps.floorTotal,
    note: deltaNote(differences),
  };
}

/* ── single-cable failure ───────────────────────────────────────────────────── */

export type LinkPresence =
  | "carrying"
  | "not-carrying-observed-down"
  | "not-carrying-unknown-status"
  | "not-in-projection"
  | "absent-from-topology";

export interface LinkFailureResult {
  kind: "link";
  linkId: string;
  a: string | null;
  b: string | null;
  graphOptions: GraphOptions;
  presence: LinkPresence;
  /** `null` when the cable is not in this projection — we decline to call it "not a bridge". */
  isBridge: boolean | null;
  componentsBefore: number;
  componentsAfter: number;
  newlyStranded: string[];
  alreadyDisconnected: string[];
  strandedNonTransit: string[];
  strandedEndpoints: StrandedEndpoints;
  engine: {
    isBridge: boolean | null;
    betweenness: number | null;
    pairsCut: number | null;
    centralityRank: number | null;
    agreement: "agree" | "disagree" | "engine-silent";
    cite: Cite | null;
  };
  alternateProjections: ProjectionDelta[];
  certainty: Certainty;
  caveats: string[];
  assumptions: Assumption[];
  claim: string;
}

/**
 * Why a link that is neither carrying, down, nor unknown-status is outside the projection.
 *
 * It must name the ends that were ACTUALLY never collected, not both ends of the cable. The
 * previous wording interpolated `excluded?.a` and `excluded?.b` — the link's two endpoints — inside
 * a parenthetical that reads as the list of uncollected ends, so it told the reader that a device
 * the collector reached, scored and published eighteen findings for had never been collected. On
 * L0 that meant printing "(access1, AP-floor1) was never collected" when only AP-floor1 was.
 *
 * `excluded === null` is handled explicitly rather than with optional chaining: `${excluded?.a}`
 * renders the literal string "undefined" into the DOM, which is the worst possible thing for a
 * refusal message to say about a device. It cannot be reached on the shipped data, which is
 * exactly why it must not be left to chance.
 */
function notInProjectionWhy(
  linkId: string,
  excluded: ExcludedLink | null,
  devices: readonly Device[],
): string {
  if (excluded === null) {
    return `${linkId} is not in this connectivity projection and no exclusion reason was recorded for it, so its failure impact is not computed. That is a gap in this projection, not a finding of "no impact".`;
  }
  if (excluded.reason === "self-loop") {
    return `Both ends of ${linkId} name ${excluded.a}, so it cannot carry traffic between distinct hosts and its failure changes nothing in this projection.`;
  }
  const collected = new Map(devices.map((d) => [d.id, d.collected]));
  const uncollected = [excluded.a, excluded.b].filter((h) => collected.get(h) !== true);
  const ends =
    uncollected.length === 0
      ? /* Neither end is uncollected, so the exclusion came from somewhere this branch does not
           model. Say that rather than naming an innocent device. */
        `it is excluded from this connectivity projection (${excluded.detail})`
      : uncollected.length === 1
        ? `its end ${uncollected[0]} was never collected`
        : `both its ends (${uncollected.join(", ")}) were never collected`;
  return `${linkId} is up but ${ends}, so this projection does not model it forwarding; its failure impact is not computed.`;
}

export function linkFailureImpact(linkId: string, graph?: TopologyGraph): LinkFailureResult {
  const g = graph ?? buildAdjacency();
  const link = g.source.links.find((l) => l.id === linkId) ?? null;
  const edge = g.edges.find((e) => e.linkId === linkId) ?? null;
  const excluded = g.excluded.find((x) => x.linkId === linkId) ?? null;
  const base = componentsOf(g).length;

  const presence: LinkPresence =
    edge !== null
      ? "carrying"
      : link === null
        ? "absent-from-topology"
        : excluded?.reason === "observed-down"
          ? "not-carrying-observed-down"
          : excluded?.reason === "unknown-status"
            ? "not-carrying-unknown-status"
            : "not-in-projection";

  const engineRec = link;
  const engineBlock = (ours: boolean | null) => ({
    isBridge: engineRec?.isBridge ?? null,
    betweenness: engineRec?.betweenness ?? null,
    pairsCut: engineRec?.pairsCut ?? null,
    centralityRank: engineRec?.centralityRank ?? null,
    agreement: (engineRec?.isBridge ?? null) === null || ours === null
      ? ("engine-silent" as const)
      : engineRec?.isBridge === ours
        ? ("agree" as const)
        : ("disagree" as const),
    cite: engineRec?.cite ?? null,
  });

  /* A port the cable map places on more than one cable (./port-claims.ts). At most one of those
     cables is real and the evidence does not say which, so a radius computed over this one is a
     radius over a cable that may not exist (2026-09-22 critic, B1). */
  const disputes = disputesIn(g, linkId);
  const disputeCaveats = disputes.map((d) => disputeSentence(linkId, d));

  if (presence !== "carrying") {
    const why =
      presence === "absent-from-topology"
        ? `${linkId} is not a cable in this snapshot; nothing can be said about its failure.`
        : presence === "not-carrying-observed-down"
          ? `${linkId} was already observed down, so its failure changes nothing in this projection — but everything already depending on its absence is the current state, not a healthy one.`
          : presence === "not-carrying-unknown-status"
            ? `${linkId} has no observed operational status, so it is not in this connectivity graph. Its failure impact is unknown — this is not a finding of "no impact".`
            : notInProjectionWhy(linkId, excluded, g.source.devices);
    return {
      kind: "link",
      linkId,
      a: link?.a ?? null,
      b: link?.b ?? null,
      graphOptions: g.options,
      presence,
      isBridge: null,
      componentsBefore: base,
      componentsAfter: base,
      newlyStranded: [],
      alreadyDisconnected: [],
      strandedNonTransit: [],
      strandedEndpoints: NOT_DETERMINABLE_ENDPOINTS(why),
      engine: engineBlock(null),
      alternateProjections: [],
      certainty: presence === "not-carrying-observed-down" && disputes.length === 0 ? "observed" : "not-determinable",
      caveats: [why, ...disputeCaveats],
      assumptions: g.assumptions,
      claim: `No blast radius computed for ${linkId}: ${why}`,
    };
  }

  const outcome = removalOutcome(g, { link: linkId });
  // From Hopcroft–Tarjan, the same pass bridges() publishes and the brute-force suite pins — NOT
  // from "did anything end up stranded". A cut-edge verdict derived from the stranding accounting
  // inherits every error in it, and this one is cross-checked against the engine's link_centrality:
  // a wrong verdict here does not just mislead, it manufactures an evidence conflict.
  const ourBridge = cutSets(g).bridges.includes(linkId);
  const eps = strandedEndpoints([], outcome.newlyStranded);
  const detached = g.attachedNonTransit
    .filter(
      (a) =>
        a.carryingAttachments.length > 0 &&
        a.carryingAttachments.every((c) => outcome.newlyStranded.includes(c.host)),
    )
    .map((a) => a.host)
    .sort();

  const caveats: string[] = [];
  if (edge?.isPortChannel) {
    caveats.push(
      `${linkId} is a port-channel of ${edge.memberCount} member(s) modelled as one cable; losing a single member is not this scenario.`,
    );
  }
  if (edge?.confirmation !== null && edge?.confirmation !== undefined && ONE_END.test(edge.confirmation)) {
    caveats.push(`${linkId} is confirmed from one end only (${edge.confirmation}); the adjacency itself rests on a single neighbour table.`);
  }
  if ((engineRec?.isBridge ?? null) === null) {
    caveats.push(`The engine computed no centrality for ${linkId}; its silence is not a second opinion.`);
  }
  if (eps.hostsWithoutEndpointRecords.length > 0) {
    caveats.push(
      `${eps.hostsWithoutEndpointRecords.join(", ")} have no endpoint records; stranding there is unknown in size, not zero.`,
    );
  }
  if (outcome.preExistingPartition) {
    caveats.push(
      `The projection was already in ${outcome.componentsBefore} pieces before this cut; this radius is measured inside the piece ${linkId} sits in, and the ${outcome.alreadyDisconnected.length} host(s) outside it were already unreachable across it.`,
    );
  }

  if (disputes.length > 0) {
    const why = `${linkId} shares a port with another cable in the cable map, so whether ${linkId} exists at all is disputed and its failure impact is not determinable`;
    const conditional =
      `Were ${linkId} the real cable, this projection would have it ${ourBridge ? "partition the graph" : "not partition the graph"}, stranding ` +
      `${outcome.newlyStranded.length === 0 ? "no host" : outcome.newlyStranded.join(", ")} — stated as a conditional, not as the result.`;
    return {
      kind: "link",
      linkId,
      a: edge?.a ?? null,
      b: edge?.b ?? null,
      graphOptions: g.options,
      presence,
      isBridge: null,
      componentsBefore: outcome.componentsBefore,
      componentsAfter: outcome.componentsBefore,
      newlyStranded: [],
      alreadyDisconnected: outcome.alreadyDisconnected,
      strandedNonTransit: [],
      strandedEndpoints: NOT_DETERMINABLE_ENDPOINTS(`${why}.`),
      engine: engineBlock(null),
      alternateProjections: [],
      certainty: "not-determinable",
      caveats: [...disputeCaveats, conditional, ...caveats],
      assumptions: g.assumptions,
      claim: `No blast radius is given for ${linkId}: ${why}.`,
    };
  }

  const altUnknown =
    g.uncertainLinkIds.length > 0 ? [projectionDeltaLink(g, { unknownStatus: flip(g.options.unknownStatus) }, linkId)] : [];
  const alternates = [projectionDeltaLink(g, { transit: flipTransit(g.options.transit) }, linkId), ...altUnknown];

  return {
    kind: "link",
    linkId,
    a: edge?.a ?? null,
    b: edge?.b ?? null,
    graphOptions: g.options,
    presence,
    isBridge: ourBridge,
    componentsBefore: outcome.componentsBefore,
    componentsAfter: outcome.componentsAfter,
    newlyStranded: outcome.newlyStranded,
    alreadyDisconnected: outcome.alreadyDisconnected,
    strandedNonTransit: detached,
    strandedEndpoints: eps,
    engine: engineBlock(ourBridge),
    alternateProjections: alternates,
    certainty: altUnknown.some((a) => a.differs) ? "uncertain" : "observed",
    caveats,
    assumptions: g.assumptions,
    claim:
      `Cutting ${linkId} (${edge?.a} ↔ ${edge?.b}) leaves ${outcome.componentsAfter} component(s), stranding ` +
      `${outcome.newlyStranded.length} host(s) and ${endpointPhrase(eps)}. Cable-map adjacency only.`,
  };
}

/** The port disputes `linkId` is party to, over THIS graph's own cable map (not the shipped one). */
function disputesIn(g: TopologyGraph, linkId: string): PortDispute[] {
  return findPortDisputes(g.source.links).filter((d) => d.claims.some((c) => c.linkId === linkId));
}

function projectionDeltaLink(g: TopologyGraph, patch: Partial<GraphOptions>, linkId: string): ProjectionDelta {
  const alt = alternateGraph(g, patch);
  if (!alt.edges.some((e) => e.linkId === linkId)) {
    const reason = `${linkId} does not carry under this projection, so its failure is not modelled there.`;
    return {
      options: alt.options,
      differs: true,
      differences: [reason],
      componentsAfter: componentsOf(alt).length,
      newlyStrandedCount: 0,
      strandedEndpointTotal: null,
      note: reason,
    };
  }
  const there = removalOutcome(alt, { link: linkId });
  const thereEps = strandedEndpoints([], there.newlyStranded);
  if (!g.edges.some((e) => e.linkId === linkId)) return unbasedDelta(alt, there, thereEps.floorTotal, linkId, "carry");
  const here = removalOutcome(g, { link: linkId });
  const differences = describeDelta(here, there, strandedEndpoints([], here.newlyStranded).floorTotal, thereEps.floorTotal);
  return {
    options: alt.options,
    differs: differences.length > 0,
    differences,
    componentsAfter: there.componentsAfter,
    newlyStrandedCount: there.newlyStranded.length,
    strandedEndpointTotal: thereEps.floorTotal,
    note: deltaNote(differences),
  };
}

/* ── load-bearing measures ──────────────────────────────────────────────────── */

export interface KCoreEntry {
  host: string;
  k: number;
  degree: number;
  collected: boolean | null;
  cite: Cite;
}

export interface KCoreResult {
  graphOptions: GraphOptions;
  coreness: KCoreEntry[];
  maxCore: number;
  shells: { k: number; hosts: string[] }[];
  /** Hosts in the topology that this projection cannot score, with the reason. Never scored as 0. */
  notScored: { host: string; reason: string; cite: Cite }[];
  certainty: Certainty;
  caveats: string[];
  assumptions: Assumption[];
  claim: string;
}

/**
 * Degeneracy ordering (k-core peeling). Ties are broken by host name so the shell assignment is
 * reproducible; with equal degrees the choice does not change the coreness values, only the order
 * the peel visits them in, but a stable order keeps two runs byte-identical.
 */
export function kCore(graph?: TopologyGraph): KCoreResult {
  const g = graph ?? buildAdjacency();
  const degree = new Map<string, number>(g.nodes.map((n) => [n, (g.adjacency.get(n) ?? []).length]));
  const originalDegree = new Map(degree);
  const removed = new Set<string>();
  const coreness = new Map<string, number>();
  let k = 0;

  while (removed.size < g.nodes.length) {
    let pick: string | null = null;
    let pickDeg = Number.POSITIVE_INFINITY;
    for (const n of g.nodes) {
      if (removed.has(n)) continue;
      const d = degree.get(n) ?? 0;
      if (d < pickDeg) {
        pick = n;
        pickDeg = d;
      }
    }
    if (pick === null) break;
    k = Math.max(k, pickDeg);
    coreness.set(pick, k);
    removed.add(pick);
    for (const e of g.adjacency.get(pick) ?? []) {
      if (removed.has(e.host)) continue;
      degree.set(e.host, (degree.get(e.host) ?? 1) - 1);
    }
  }

  const entries: KCoreEntry[] = g.nodes
    .map((host) => ({
      host,
      k: coreness.get(host) ?? 0,
      degree: originalDegree.get(host) ?? 0,
      collected: deviceById.get(host)?.collected ?? null,
      cite: deviceById.get(host)?.cite ?? `cable_map.nodes[host=${host}]`,
    }))
    .sort((x, y) => y.k - x.k || y.degree - x.degree || cmp(x.host, y.host));

  const shellMap = new Map<number, string[]>();
  for (const e of entries) {
    const list = shellMap.get(e.k);
    if (list) list.push(e.host);
    else shellMap.set(e.k, [e.host]);
  }
  const shells = [...shellMap.entries()]
    .map(([shellK, hosts]) => ({ k: shellK, hosts: hosts.sort() }))
    .sort((x, y) => y.k - x.k);

  const notScored = g.attachedNonTransit.map((a) => ({
    host: a.host,
    reason:
      a.collected === false
        ? `${a.host} was never collected, so it is not modelled as forwarding in this projection and has no coreness here.`
        : `${a.host} has no device record; it is a cable-map neighbour only.`,
    cite: a.cite,
  }));

  const maxCore = entries.length > 0 ? Math.max(...entries.map((e) => e.k)) : 0;

  return {
    graphOptions: g.options,
    coreness: entries,
    maxCore,
    shells,
    notScored,
    certainty: g.uncertainLinkIds.length > 0 ? "uncertain" : "observed",
    caveats: [
      ...(notScored.length > 0
        ? [`${notScored.length} host(s) are present in the cable map but unscored here: ${notScored.map((n) => n.host).join(", ")}.`]
        : []),
      ...(g.uncertainLinkIds.length > 0
        ? [`${g.uncertainLinkIds.length} unknown-status cable(s) are outside this measure; including them can only raise coreness, never lower it.`]
        : []),
    ],
    assumptions: g.assumptions,
    claim: kCoreClaim(maxCore, shells),
  };
}

const hostCount = (n: number): string => `${n} host${n === 1 ? "" : "s"}`;

/**
 * The k-core sentence, branched on THIS graph's maximum coreness and naming its shells from the data.
 *
 * It used to be one literal — "the N host(s) in the highest shell are the mutually redundant spine; shell 1 and 0
 * hosts hang off it" — true only of a fleet whose maximum coreness is 2. A graph whose maximum coreness is 1 is a
 * forest (degeneracy 1 means no cycle), so no host has a second, independent path and there is no redundant core
 * to name; one whose maximum is 0 has no carrying link at all.
 */
function kCoreClaim(maxCore: number, shells: readonly { k: number; hosts: readonly string[] }[]): string {
  const scope = "Structural redundancy only — it says nothing about capacity, control-plane state or configuration.";
  if (maxCore <= 0) {
    return `Coreness over observed adjacency: there is no carrying adjacency to peel (maximum coreness 0), so no host is in any core. ${scope}`;
  }
  if (maxCore === 1) {
    return (
      "Coreness over observed adjacency: the carrying links form a loop-free forest (maximum coreness 1), so no host has " +
      `redundant adjacency and there is no redundant core; every carrying link is a bridge. ${scope}`
    );
  }
  const top = shells.find((s) => s.k === maxCore);
  const lower = shells.filter((s) => s.k < maxCore).map((s) => `k = ${s.k} (${hostCount(s.hosts.length)})`);
  return (
    `Coreness over observed adjacency: the ${hostCount(top?.hosts.length ?? 0)} in the highest shell (k = ${maxCore}) each keep at least ` +
    `${maxCore} neighbours inside it — the most mutually redundant part of the graph` +
    (lower.length > 0 ? `; the lower shells hang off it: ${lower.join(", ")}. ` : "; there is no lower shell. ") +
    scope
  );
}

export interface BetweennessRow {
  linkId: string;
  a: string;
  b: string;
  betweenness: number;
  pairsCut: number | null;
  centralityRank: number | null;
  isBridge: boolean | null;
  inProjection: boolean;
  cite: Cite;
}

export interface BetweennessResult {
  graphOptions: GraphOptions;
  /** Read from the engine's link_centrality — this module does not recompute it. */
  supplied: BetweennessRow[];
  missing: string[];
  coverage: { withRecord: number; total: number; cite: Cite };
  note: string;
  certainty: Certainty;
  caveats: string[];
  assumptions: Assumption[];
  claim: string;
}

export function linkBetweenness(graph?: TopologyGraph): BetweennessResult {
  const g = graph ?? buildAdjacency();
  const inProjection = new Set(g.edges.map((e) => e.linkId));
  const supplied: BetweennessRow[] = g.source.links
    .filter((l): l is Link & { betweenness: number } => l.betweenness !== null)
    .map((l) => ({
      linkId: l.id,
      a: l.a,
      b: l.b,
      betweenness: l.betweenness,
      pairsCut: l.pairsCut,
      centralityRank: l.centralityRank,
      isBridge: l.isBridge,
      inProjection: inProjection.has(l.id),
      cite: l.cite,
    }))
    .sort((x, y) => y.betweenness - x.betweenness || cmp(x.linkId, y.linkId));
  const missing = g.source.links.filter((l) => l.betweenness === null).map((l) => l.id);

  return {
    graphOptions: g.options,
    supplied,
    missing,
    coverage: { withRecord: supplied.length, total: g.source.links.length, cite: fabric.coverage.cite },
    note:
      `${missing.length} of ${g.source.links.length} cables have no link_centrality record. A cable the engine never ` +
      "scored is unscored — it is not evidence of zero centrality, and it must not be rendered as a low-importance link.",
    certainty: missing.length > 0 ? "uncertain" : "observed",
    caveats: [
      "Betweenness here is the engine's own value, computed over its collected-only graph; it is reported, not recomputed, " +
        "so it can disagree with this projection's structure — see bridges().engineComparison for where that happens.",
    ],
    assumptions: g.assumptions,
    claim:
      `Engine-supplied link centrality for ${supplied.length} cable(s), with ${missing.length} unscored and named. ` +
      "Reported evidence, not an independent measurement.",
  };
}

/* ── reachability ───────────────────────────────────────────────────────────── */

export interface ReachabilityResult {
  hostId: string;
  graphOptions: GraphOptions;
  present: boolean;
  nodeClass: "transit" | "attached-non-transit" | "absent";
  /** Transit hosts in the same component, including the host itself. */
  hosts: string[];
  /** Non-transit nodes hanging off a reachable host by a carrying cable. */
  attachedReachable: string[];
  /** Nodes that would join only if unknown-status cables turn out to carry. */
  attachedOnlyViaUncertainLinks: string[];
  /** Empty when `certainty` is "not-determinable": an unanswered question yields no list of answers. */
  unreachable: string[];
  /** Unknown-status cables touching the subject or its set — the set is a floor while they stand. */
  uncertainLinksInScope: string[];
  certainty: Certainty;
  caveats: string[];
  assumptions: Assumption[];
  claim: string;
}

export function reachableSet(hostId: string, graph?: TopologyGraph): ReachabilityResult {
  const g = graph ?? buildAdjacency();
  const attached = g.attachedNonTransit.find((a) => a.host === hostId) ?? null;
  const nodeClass = g.adjacency.has(hostId) ? "transit" : attached ? "attached-non-transit" : "absent";

  const hosts =
    nodeClass === "transit"
      ? componentOf(g, hostId)
      : nodeClass === "attached-non-transit"
        ? sortedUnique(
            (attached?.carryingAttachments ?? []).flatMap((c) => componentOf(g, c.host)),
          )
        : [];
  const inSet = new Set(hosts);

  const attachedReachable = g.attachedNonTransit
    .filter((a) => a.host !== hostId && a.carryingAttachments.some((c) => inSet.has(c.host)))
    .map((a) => a.host)
    .sort();
  const onlyUncertain = g.attachedNonTransit
    .filter(
      (a) =>
        a.host !== hostId &&
        !a.carryingAttachments.some((c) => inSet.has(c.host)) &&
        a.uncertainAttachments.some((c) => inSet.has(c.host)),
    )
    .map((a) => a.host)
    .sort();

  /*
   * The subject's OWN cabling decides whether this question can be answered at all. Building the
   * set from carryingAttachments alone and then judging certainty by looking at OTHER hosts meant a
   * host whose only cable has never-observed status got `hosts: []` with certainty "observed" — the
   * same L34 the module calls "uncertain" when asked from the far end. A down cable is evidence and
   * still answers; an unobserved one is not evidence of anything.
   */
  const ownUncertain = attached?.uncertainAttachments ?? [];
  const undetermined =
    nodeClass === "absent" ||
    (nodeClass === "attached-non-transit" && (attached?.carryingAttachments.length ?? 0) === 0 && ownUncertain.length > 0);

  const scope = new Set([hostId, ...hosts]);
  const uncertainLinksInScope = g.uncertainLinkIds.filter((id) => {
    const l = g.source.links.find((s) => s.id === id);
    return l !== undefined && (scope.has(l.a) || scope.has(l.b));
  });

  const caveats: string[] = [];
  if (nodeClass === "absent") {
    caveats.push(`${hostId} is not in this topology projection; an empty reachable set here is absence of evidence, not isolation.`);
  }
  if (nodeClass === "attached-non-transit") {
    caveats.push(
      `${hostId} was never collected, so it is not modelled as forwarding: this set is what its cabled neighbours can reach, not what it can.`,
    );
  }
  if (undetermined && ownUncertain.length > 0) {
    caveats.push(
      `Every cable ${hostId} has (${ownUncertain.map((c) => `${c.linkId} to ${c.host}`).join(", ")}) has no observed operational status, so what it reaches cannot be determined from this evidence. It is unobserved, not isolated.`,
    );
  }
  if (uncertainLinksInScope.length > 0) {
    caveats.push(
      `Unknown-status cable(s) ${uncertainLinksInScope.join(", ")} touch this set; anything beyond them is unobserved, so the set is a floor.`,
    );
  }
  if (onlyUncertain.length > 0) {
    caveats.push(
      `${onlyUncertain.join(", ")} are cabled to this set only through unknown-status links; whether they are reachable is unobserved.`,
    );
  }
  if (g.isolatedNodes.length > 0) {
    caveats.push(`${g.isolatedNodes.length} host(s) in this projection have no carrying cable at all: ${g.isolatedNodes.join(", ")}.`);
  }

  return {
    hostId,
    graphOptions: g.options,
    present: nodeClass !== "absent",
    nodeClass,
    hosts,
    attachedReachable,
    attachedOnlyViaUncertainLinks: onlyUncertain,
    // Listing 23 hosts as "unreachable" from a host whose reachability we cannot determine states
    // 23 negative facts we do not hold. No answer means no list.
    unreachable: undetermined ? [] : g.nodes.filter((n) => !inSet.has(n)).sort(),
    uncertainLinksInScope,
    certainty: undetermined
      ? "not-determinable"
      : onlyUncertain.length > 0 || uncertainLinksInScope.length > 0
        ? "uncertain"
        : "observed",
    caveats,
    assumptions: g.assumptions,
    claim: undetermined
      ? `Reachability from ${hostId} could not be determined under this projection${nodeClass === "absent" ? ": it is not in the topology" : ": its own cabling was never observed operational"}. That is a gap in evidence, not a finding of isolation.`
      : `${hosts.length} host(s) share a cable-map component with ${hostId} under the stated status and transit policy. ` +
        "Adjacency reachability — not a claim that any flow between them is permitted or routed.",
  };
}

/* ── shortest paths by hop count ────────────────────────────────────────────── */

export interface TopologyPath {
  hosts: string[];
  linkIds: string[];
  hops: number;
  traversesUncollected: string[];
  cites: Cite[];
}

export interface PathsResult {
  a: string;
  b: string;
  graphOptions: GraphOptions;
  paths: TopologyPath[];
  hopCount: number | null;
  totalShortestPaths: number;
  truncated: boolean;
  /** What was asked for and what was enforced — a ceiling nobody can see is a ceiling nobody trusts. */
  pathLimit: PathLimit;
  reachable: boolean;
  certainty: Certainty;
  caveats: string[];
  assumptions: Assumption[];
  claim: string;
}

/** Hard ceiling on enumeration: paths are for a human to read, and the count is reported separately. */
const MAX_PATHS_CEILING = 64;

export interface PathLimit {
  /** The caller's request once truncated to an integer; `null` when it was not a usable number. */
  requested: number | null;
  applied: number;
  ceiling: number;
  usable: boolean;
}

/**
 * Resolve a requested path limit against the hard ceiling.
 *
 * Exported and unit-tested because this is the only place the ceiling can actually execute: the
 * largest minimum-hop path count between any pair in this snapshot is 17, so no call through
 * `pathsBetween` reaches 64 and a test there would pin the caller's cap, never the ceiling.
 *
 * `Math.min(Math.trunc(x), 64)` is NaN for a NaN request — and `paths.length >= NaN` is never true,
 * so an unusable argument (`Number(<missing URL param>)`) removed the bound entirely while
 * `truncated` still reported false. An unparseable request is not a request for unlimited: it is
 * clamped to the ceiling and reported as unusable so the caller can see its input was discarded.
 */
export function resolvePathLimit(maxPaths: number): PathLimit {
  const requested = Math.trunc(Number(maxPaths));
  if (!Number.isFinite(requested)) {
    return { requested: null, applied: MAX_PATHS_CEILING, ceiling: MAX_PATHS_CEILING, usable: false };
  }
  return {
    requested,
    applied: Math.max(1, Math.min(requested, MAX_PATHS_CEILING)),
    ceiling: MAX_PATHS_CEILING,
    usable: true,
  };
}

/**
 * Up to `maxPaths` minimum-hop paths between two hosts, in deterministic order (neighbours are
 * visited host-then-cable sorted). Only minimum-hop paths are enumerated — a longer path is a
 * different question — and `totalShortestPaths` reports how many exist so a truncated list is never
 * mistaken for the whole answer.
 *
 * This is topology adjacency. The L3 forwarding trace answers a different question and can disagree
 * with it legitimately: a cable can exist where no route sends traffic, and a route can exist that
 * no cable in this snapshot supports.
 */
export function pathsBetween(a: string, b: string, maxPaths = 8, graph?: TopologyGraph): PathsResult {
  const g = graph ?? buildAdjacency();
  const pathLimit = resolvePathLimit(maxPaths);
  const cap = pathLimit.applied;
  const claim =
    "Topology adjacency only: minimum-hop paths through the observed cable map, not a claim that traffic is forwarded " +
    "along them — forwarding is decided by the RIB and ACLs, which this analysis does not consult.";

  const caveats: string[] = [];
  if (!pathLimit.usable) {
    caveats.push(
      `The requested path limit was not a usable number; the hard ceiling of ${pathLimit.ceiling} was applied instead.`,
    );
  }
  const missing = [a, b].filter((h) => !g.adjacency.has(h));
  if (missing.length > 0) {
    for (const h of missing) {
      const att = g.attachedNonTransit.find((x) => x.host === h);
      caveats.push(
        att
          ? `${h} is cabled into the fabric but was never collected, so this projection does not route through or to it.`
          : `${h} is not a transit node in this projection.`,
      );
    }
    return {
      a,
      b,
      graphOptions: g.options,
      paths: [],
      hopCount: null,
      totalShortestPaths: 0,
      truncated: false,
      pathLimit,
      reachable: false,
      certainty: "not-determinable",
      caveats,
      assumptions: g.assumptions,
      claim,
    };
  }

  // BFS from b so every node carries its distance to the target; shortest paths are then the DAG of
  // edges that strictly decrease that distance.
  const dist = new Map<string, number>([[b, 0]]);
  let frontier = [b];
  while (frontier.length > 0) {
    const next: string[] = [];
    for (const cur of frontier) {
      const d = dist.get(cur) ?? 0;
      for (const e of g.adjacency.get(cur) ?? []) {
        if (dist.has(e.host)) continue;
        dist.set(e.host, d + 1);
        next.push(e.host);
      }
    }
    frontier = next.sort();
  }

  const hopCount = dist.get(a);
  const uncertainIncident = g.uncertainLinkIds.filter((id) => {
    const l = g.source.links.find((s) => s.id === id);
    return l !== undefined && (l.a === a || l.b === a || l.a === b || l.b === b);
  });
  if (uncertainIncident.length > 0) {
    caveats.push(
      `Unknown-status cable(s) ${uncertainIncident.join(", ")} touch ${a} or ${b}: their operational state was never observed, so they are excluded here and a path could exist that this result does not show.`,
    );
  }

  if (hopCount === undefined) {
    caveats.push(
      `${a} and ${b} are in different components of this projection. That is a statement about observed cabling, not proof that no adjacency exists.`,
    );
    return {
      a,
      b,
      graphOptions: g.options,
      paths: [],
      hopCount: null,
      totalShortestPaths: 0,
      truncated: false,
      pathLimit,
      reachable: false,
      certainty: uncertainIncident.length > 0 ? "uncertain" : "observed",
      caveats,
      assumptions: g.assumptions,
      claim,
    };
  }

  // Count of minimum-hop paths over the distance DAG, memoised: reported even when the list below
  // is truncated, so "3 shown" never reads as "3 exist".
  const counts = new Map<string, number>();
  const countFrom = (node: string): number => {
    if (node === b) return 1;
    const memo = counts.get(node);
    if (memo !== undefined) return memo;
    const d = dist.get(node) ?? 0;
    let sum = 0;
    for (const e of g.adjacency.get(node) ?? []) {
      if ((dist.get(e.host) ?? Number.POSITIVE_INFINITY) === d - 1) sum += countFrom(e.host);
    }
    counts.set(node, sum);
    return sum;
  };
  const total = countFrom(a);

  const paths: TopologyPath[] = [];
  const hosts: string[] = [a];
  const linkIds: string[] = [];
  const walk = (node: string): void => {
    if (paths.length >= cap) return;
    if (node === b) {
      const cites = linkIds.map((id) => linkById.get(id)?.cite ?? `cable_map.cables[id=${id}]`);
      paths.push({
        hosts: [...hosts],
        linkIds: [...linkIds],
        hops: linkIds.length,
        traversesUncollected: hosts.filter((h) => deviceById.get(h)?.collected === false),
        cites,
      });
      return;
    }
    const d = dist.get(node) ?? 0;
    for (const e of g.adjacency.get(node) ?? []) {
      if ((dist.get(e.host) ?? Number.POSITIVE_INFINITY) !== d - 1) continue;
      hosts.push(e.host);
      linkIds.push(e.linkId);
      walk(e.host);
      hosts.pop();
      linkIds.pop();
      if (paths.length >= cap) return;
    }
  };
  walk(a);

  const viaUncollected = paths.some((p) => p.traversesUncollected.length > 0);
  if (viaUncollected) {
    caveats.push(
      "At least one path transits a host that was never collected; that hop is an assumption about a device we did not reach.",
    );
  }
  if (paths.length < total) {
    caveats.push(`${total} minimum-hop paths exist; ${paths.length} are listed.`);
  }

  return {
    a,
    b,
    graphOptions: g.options,
    paths,
    hopCount,
    totalShortestPaths: total,
    truncated: paths.length < total,
    pathLimit,
    reachable: true,
    certainty: uncertainIncident.length > 0 || viaUncollected ? "uncertain" : "observed",
    caveats,
    assumptions: g.assumptions,
    claim,
  };
}
