import {
  canonicalProjectionJson, EMBED_MAX_PAGES, EMBED_MAX_ROWS, PROJECTION_SCHEMA, TOPOLOGY_LISTS,
  TOPOLOGY_STYLE_SCHEMA, projectionContextDigest, readProjectionIdentity, readProjectionRowRef, sameProjectionIdentity,
  type ContextHasher, type EmbedQuery, type ProjectionIdentity, type TopologyList,
} from "../../../webapp/frontend/src/projectionEmbed";
import { ContractRefusal } from "./errors";
import { holds } from "../core/own";
import type { CompleteTopology, PathDocument, TopologyDocument, TopologyPageDocument, TopologyRows } from "./types";

const PAGE_SIZE = 200;
type JsonObject = Record<string, unknown>;
type Page = { offset: number; limit: number; returned: number; total: number; has_more: boolean; items: readonly unknown[] };
type Wrapper = { pointer: string; source_list: JsonObject; page: Page };
export type LoaderDeps = Readonly<{ fetch: typeof fetch; signal: AbortSignal; subtle?: ContextHasher }>;

function object(value: unknown): value is JsonObject { return value !== null && typeof value === "object" && !Array.isArray(value); }
function keys(value: unknown, names: readonly string[]): value is JsonObject {
  return object(value) && Object.keys(value).length === names.length && names.every((name) => holds(value, name));
}
function checkSignal(signal: AbortSignal): void { if (signal.aborted) throw new DOMException("Aborted", "AbortError"); }
function equal(a: unknown, b: unknown): boolean { return canonicalProjectionJson(a) === canonicalProjectionJson(b); }
function count(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }

async function get(url: string, deps: LoaderDeps): Promise<unknown> {
  checkSignal(deps.signal);
  try {
    const response = await deps.fetch(url, { signal: deps.signal, credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    checkSignal(deps.signal);
    if (!response.ok) throw new ContractRefusal("HTTP_REFUSED");
    const value: unknown = await response.json();
    checkSignal(deps.signal);
    canonicalProjectionJson(value); // JSON type/finite checks, never a second fact schema.
    return value;
  } catch (error) {
    checkSignal(deps.signal);
    if (error instanceof ContractRefusal) throw error;
    throw new ContractRefusal("HTTP_REFUSED");
  }
}

function envelope(value: unknown, identity: ProjectionIdentity, view: "topology" | "path", list: boolean): JsonObject {
  if (!keys(value, ["schema", "projection_schema", "identity", "view", "engine", "limitations", list ? "list" : "payload"]) ||
    value.schema !== "ui_projection_transport/1" || value.projection_schema !== PROJECTION_SCHEMA || value.view !== view) {
    throw new ContractRefusal("UNSUPPORTED_CONTRACT");
  }
  const actual = readProjectionIdentity(value.identity);
  if (actual === null || !sameProjectionIdentity(actual, identity)) throw new ContractRefusal("IDENTITY_MISMATCH");
  if (!object(value.engine) || !Array.isArray(value.limitations)) throw new ContractRefusal("CONTEXT_MISMATCH");
  return value;
}

function wrapper(value: unknown, name: TopologyList, offset: number): Wrapper {
  if (!keys(value, ["pointer", "source_list", "page"]) || value.pointer !== `/${name}` || !object(value.source_list) ||
    !keys(value.page, ["offset", "limit", "returned", "total", "has_more", "items"])) throw new ContractRefusal("INCOMPLETE_PAGES");
  const page = value.page;
  if (!count(page.offset) || page.offset !== offset || page.limit !== PAGE_SIZE || !count(page.returned) || !count(page.total) ||
    !Array.isArray(page.items) || page.returned !== page.items.length ||
    page.returned !== Math.min(Math.max(page.total - offset, 0), PAGE_SIZE) ||
    page.has_more !== (offset + page.returned < page.total) ||
    (value.source_list.state === "published" && page.total === 0)) throw new ContractRefusal("INCOMPLETE_PAGES");
  return value as unknown as Wrapper;
}

function context(page: JsonObject, initial: TopologyDocument): void {
  if (!equal(page.engine, initial.engine) || !equal(page.limitations, initial.limitations)) throw new ContractRefusal("CONTEXT_MISMATCH");
}

function references(rows: readonly unknown[], known: Set<string>): void {
  for (const row of rows) {
    if (!object(row)) throw new ContractRefusal("INCOMPLETE_PAGES");
    const ref = readProjectionRowRef({ index: row.index, pointer: row.pointer });
    if (!ref) throw new ContractRefusal("INCOMPLETE_PAGES");
    const key = JSON.stringify([ref.index, ref.pointer]);
    if (known.has(key)) throw new ContractRefusal("INCOMPLETE_PAGES");
    known.add(key);
  }
}

/** The backend validates full owner schemas; this adapter additionally binds every page and its census. */
export async function loadCompleteTopology(identity: ProjectionIdentity, expectedDigest: string, deps: LoaderDeps): Promise<CompleteTopology> {
  const base = `/api/snapshots/${identity.snapshot_id}/ui-projection/topology`;
  const value = envelope(await get(`${base}?limit=${PAGE_SIZE}`, deps), identity, "topology", false);
  if (!keys(value.payload, ["summary", ...TOPOLOGY_LISTS, "legend"]) || !object(value.payload.legend) ||
    value.payload.legend.schema !== TOPOLOGY_STYLE_SCHEMA) throw new ContractRefusal("UNSUPPORTED_CONTRACT");
  const document = value as unknown as TopologyDocument;
  let digest: string;
  try { digest = await projectionContextDigest(document.engine, document.limitations, deps.subtle); }
  catch { checkSignal(deps.signal); throw new ContractRefusal("CONTEXT_MISMATCH"); }
  checkSignal(deps.signal);
  if (digest !== expectedDigest) throw new ContractRefusal("CONTEXT_MISMATCH");
  const initial = Object.fromEntries(TOPOLOGY_LISTS.map((name) => [name, wrapper(document.payload[name], name, 0)])) as Record<TopologyList, Wrapper>;
  const total = TOPOLOGY_LISTS.reduce((sum, name) => sum + initial[name].page.total, 0);
  if (!Number.isSafeInteger(total) || total > EMBED_MAX_ROWS) throw new ContractRefusal("INCOMPLETE_PAGES");
  let pages = TOPOLOGY_LISTS.length;
  const assemble = async <K extends TopologyList>(name: K): Promise<TopologyRows[K]> => {
    const first = initial[name];
    const all = [...first.page.items];
    const known = new Set<string>();
    references(all, known);
    while (all.length < first.page.total) {
      if (++pages > EMBED_MAX_PAGES) throw new ContractRefusal("INCOMPLETE_PAGES");
      const query = new URLSearchParams({ pointer: `/${name}`, offset: String(all.length), limit: String(PAGE_SIZE) });
      const pageValue = envelope(await get(`${base}/lists?${query}`, deps), identity, "topology", true);
      context(pageValue, document);
      const next = wrapper(pageValue.list, name, all.length);
      if (next.page.total !== first.page.total || !equal(next.source_list, first.source_list)) throw new ContractRefusal("INCOMPLETE_PAGES");
      references(next.page.items, known);
      all.push(...next.page.items);
    }
    checkSignal(deps.signal);
    // The exact topology view/pointer selects this generated owner row type; no facts are synthesized.
    return all as TopologyRows[K];
  };
  const rows: TopologyRows = { nodes: await assemble("nodes"), cables: await assemble("cables"),
    structural_links: await assemble("structural_links"), failure_impact: await assemble("failure_impact"),
    source_addresses: await assemble("source_addresses") };
  return { document, rows, contextDigest: digest };
}

export async function loadContractPath(model: CompleteTopology, query: EmbedQuery, deps: LoaderDeps): Promise<PathDocument> {
  const search = new URLSearchParams(query);
  const value = envelope(await get(`/api/snapshots/${model.document.identity.snapshot_id}/ui-projection/topology/path?${search}`, deps),
    model.document.identity, "path", false);
  context(value, model.document);
  if (!keys(value.payload, ["query", "result", "hop_evidence", "style", "legend"]) ||
    !keys(value.payload.query, ["src_ip", "dst_ip", "max_hops", "required_mtu", "disclose"]) ||
    value.payload.query.src_ip !== query.src_ip || value.payload.query.dst_ip !== query.dst_ip ||
    value.payload.query.max_hops !== 32 || value.payload.query.required_mtu !== null || value.payload.query.disclose !== true ||
    !equal(value.payload.legend, model.document.payload.legend)) throw new ContractRefusal("CONTEXT_MISMATCH");
  checkSignal(deps.signal);
  return value as unknown as PathDocument;
}

// Ensure the generic list consumer stays tied to the generated transport, not a manual domain copy.
export type ContractPage = TopologyPageDocument;
