import type { components } from "./generated/openapi";
import { ApiError } from "./api";
import { readProjectionIdentity } from "./projectionEmbed";

export type Schemas = components["schemas"];
export type Projection = Schemas["UiProjectionViewResponse"];
export type ProjectionList = Schemas["UiProjectionListResponse"];
export type PathProjection = Schemas["UiProjectionPathResponse"];
export type View = Projection["view"];
export type Identity = Projection["identity"];
export type ViewDocument<V extends View> = Extract<Projection, { view: V }>;
export type State = Schemas["UiProjection1_State"];
export type Fact = Schemas[Extract<keyof Schemas, `UiProjection1_${string}Fact`>];
export type Page = Schemas[Extract<keyof Schemas, `UiProjection1_Page_${string}`>];
export type SourceList = Page["source_list"];
export type Limitation = Schemas["UiProjection1_Limitation"];

type ComparableJson = null | string | number | boolean | readonly ComparableJson[] | { readonly [key: string]: ComparableJson };
export class ProjectionContextError extends Error {}
export function equalJson(a: ComparableJson, b: ComparableJson): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((item, index) => equalJson(item, b[index]));
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const left = Object.entries(a), right = new Map(Object.entries(b));
    return left.length === right.size && left.every(([key, value]) => right.has(key) && equalJson(value, right.get(key)!));
  }
  return false;
}

export function sameIdentity(a: Identity, b: Identity): boolean {
  return a.snapshot_id === b.snapshot_id && a.sha256 === b.sha256 &&
    a.bytes === b.bytes && a.digest_form === b.digest_form;
}

function requireIdentity(identity: Identity, sid: number) {
  const admitted = readProjectionIdentity(identity);
  if (!admitted || admitted.snapshot_id !== sid) {
    throw new Error("The response does not identify the requested stored snapshot.");
  }
}

export function requireProjectionPage(page: Page["page"]): void {
  if (![page.offset, page.limit, page.returned, page.total].every(Number.isSafeInteger) ||
      page.offset < 0 || page.limit < 1 || page.limit > 200 || page.returned < 0 || page.total < 0 ||
      !Array.isArray(page.items) || page.returned !== page.items.length || page.returned > page.limit ||
      page.returned !== Math.min(page.limit, Math.max(0, page.total - page.offset)) ||
      page.has_more !== (page.offset + page.returned < page.total)) {
    throw new Error("Projection page is incomplete or inconsistent. Reload the view.");
  }
}

async function response<T>(result: Response): Promise<T> {
  if (!result.ok) throw new ApiError(`Projection request failed (${result.status}). Retry or return to Campaigns.`, result.status);
  return result.json() as Promise<T>;
}

export async function loadProjection<V extends View>(sid: number, view: V, host?: string, signal?: AbortSignal): Promise<ViewDocument<V>> {
  if (!Number.isSafeInteger(sid)) throw new Error("Snapshot identifier is not safely representable.");
  const query = new URLSearchParams({ limit: "25" });
  if (host !== undefined) query.set("host", host);
  const data = await fetch(`/api/snapshots/${sid}/ui-projection/${view}?${query}`, { signal })
    .then(response<Projection>);
  if (data.schema !== "ui_projection_transport/1" || data.projection_schema !== "ui_projection/1" || data.view !== view) {
    throw new Error("The response uses a different projection contract or view.");
  }
  requireIdentity(data.identity, sid);
  if (data.view === "device" && data.payload.host !== host) throw new Error("The response names a different device.");
  // The discriminant and request identity are checked above; domain types are generated from OpenAPI.
  return data as ViewDocument<V>;
}

export async function loadProjectionPage<P extends Page>(document: Projection, source: P, offset: number, host?: string, signal?: AbortSignal): Promise<P> {
  if ((document.view === "device" && (typeof document.payload.host !== "string" || host !== document.payload.host)) ||
      (document.view !== "device" && host !== undefined)) {
    throw new Error("Page request names a different device context.");
  }
  const query = new URLSearchParams({ pointer: source.pointer, offset: String(offset), limit: String(source.page.limit) });
  if (host !== undefined) query.set("host", host);
  const data = await fetch(`/api/snapshots/${document.identity.snapshot_id}/ui-projection/${document.view}/lists?${query}`, { signal })
    .then(response<ProjectionList>);
  if (data.schema !== document.schema || data.projection_schema !== document.projection_schema || data.view !== document.view ||
      data.list.pointer !== source.pointer || !sameIdentity(data.identity, document.identity)) {
    throw new ProjectionContextError("Snapshot identity or list changed. Reload this view before continuing.");
  }
  if (!equalJson(data.engine, document.engine) || !equalJson(data.limitations, document.limitations)) {
    throw new ProjectionContextError("Engine or qualification context changed. Reload this view before continuing.");
  }
  const page = data.list.page;
  requireProjectionPage(page);
  if (page.offset !== offset || page.limit !== source.page.limit || page.returned !== page.items.length ||
      page.total !== source.page.total || !equalJson(data.list.source_list, source.source_list)) {
    throw new ProjectionContextError("List context changed. Reload this view before continuing.");
  }
  // The same view/pointer selects this exact owner row schema; the backend validates every response.
  return data.list as P;
}

export async function loadPathProjection(document: ViewDocument<"topology">, src_ip: string, dst_ip: string,
  signal?: AbortSignal): Promise<PathProjection> {
  const query = new URLSearchParams({ src_ip, dst_ip });
  const data = await fetch(`/api/snapshots/${document.identity.snapshot_id}/ui-projection/topology/path?${query}`, { signal })
    .then(response<PathProjection>);
  if (data.schema !== document.schema || data.projection_schema !== document.projection_schema || data.view !== "path" ||
      !sameIdentity(data.identity, document.identity)) {
    throw new ProjectionContextError("Path snapshot identity changed. Reload this view before continuing.");
  }
  if (!equalJson(data.engine, document.engine) || !equalJson(data.limitations, document.limitations)) {
    throw new ProjectionContextError("Path engine or qualification context changed. Reload this view before continuing.");
  }
  const echoed = data.payload.query;
  if (echoed.src_ip !== src_ip || echoed.dst_ip !== dst_ip || echoed.max_hops !== 32 ||
      echoed.required_mtu !== null || echoed.disclose !== true) {
    throw new Error("The path response belongs to a different query.");
  }
  return data;
}
