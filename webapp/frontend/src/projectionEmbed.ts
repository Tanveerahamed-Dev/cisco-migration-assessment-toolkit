/** Same-hub coordination only. Facts always arrive independently through the guarded API. */
import type { components } from "./generated/openapi";

type Schemas = components["schemas"];
export type ProjectionIdentity = Schemas["UiProjectionViewResponse"]["identity"];
export type ProjectionRowRef = Schemas["UiProjection1_RowRef"];
export type ProjectionEngine = Schemas["UiProjection1_Engine"];
export type ProjectionLimitation = Schemas["UiProjection1_Limitation"];
export type ContextHasher = { digest(algorithm: string, data: Uint8Array<ArrayBuffer>): Promise<ArrayBuffer> };

export const EMBED_PROTOCOL = "atlas.ui_projection_embed/1" as const;
export const PROJECTION_SCHEMA = "ui_projection/1" as const;
export const TOPOLOGY_STYLE_SCHEMA = "ui_projection_topology_style/1" as const;
export const PROJECTION_NONCE_PARAM = "projection_nonce" as const;
export const TOPOLOGY_LISTS = ["nodes", "cables", "structural_links", "failure_impact", "source_addresses"] as const;
/** Resource bounds refuse an incomplete assembly; they never turn it into a smaller network. */
export const EMBED_MAX_ROWS = 20_000;
export const EMBED_MAX_PAGES = 2_000;
export const EMBED_MAX_QUERY_IDS = 2_000;
const MAX_CONTEXT_BYTES = 262_144;

export type TopologyList = (typeof TOPOLOGY_LISTS)[number];
export type SelectionTarget = Readonly<{ list: TopologyList; row: ProjectionRowRef }>;
export type EmbedQuery = Readonly<{ src_ip: string; dst_ip: string }>;
export type EmbedRefusalCode = "UNSUPPORTED_CONTRACT" | "IDENTITY_MISMATCH" | "CONTEXT_MISMATCH" |
  "INCOMPLETE_PAGES" | "HTTP_REFUSED" | "INVALID_MESSAGE" | "WEBGL_UNAVAILABLE" | "RENDER_FAILED" | "RENDER_CAPACITY";
const REFUSAL_CODES: readonly EmbedRefusalCode[] = ["UNSUPPORTED_CONTRACT", "IDENTITY_MISMATCH", "CONTEXT_MISMATCH",
  "INCOMPLETE_PAGES", "HTTP_REFUSED", "INVALID_MESSAGE", "WEBGL_UNAVAILABLE", "RENDER_FAILED", "RENDER_CAPACITY"];

type Envelope = Readonly<{ protocol: typeof EMBED_PROTOCOL; nonce: string }>;
type Versions = Readonly<{ projection_schema: typeof PROJECTION_SCHEMA; style_schema: typeof TOPOLOGY_STYLE_SCHEMA }>;
type Bound = Readonly<{ identity: ProjectionIdentity; context_digest: string }>;
export type EmbedMessage =
  | (Envelope & Versions & Readonly<{ type: "ready"; snapshot_id: number }>)
  | (Envelope & Versions & Bound & Readonly<{ type: "init" }>)
  | (Envelope & Bound & Readonly<{ type: "bound" }>)
  | (Envelope & Bound & Readonly<{ type: "select"; target: SelectionTarget | null }>)
  | (Envelope & Bound & Readonly<{ type: "query"; request_id: string; query: EmbedQuery | null }>)
  | (Envelope & Bound & Readonly<{ type: "query_applied"; request_id: string }>)
  | (Envelope & Readonly<{ type: "refused"; code: EmbedRefusalCode; request_id: string | null }> &
    (Bound | Readonly<{ identity: null; context_digest: null }>));

function record(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype: unknown = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return false;
  return Reflect.ownKeys(value).every((key) => typeof key === "string" &&
    Object.getOwnPropertyDescriptor(value, key)?.enumerable === true &&
    Object.getOwnPropertyDescriptor(value, key)?.get === undefined &&
    Object.getOwnPropertyDescriptor(value, key)?.set === undefined);
}

function closed(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return record(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}

export function isEmbedNonce(value: unknown): value is string {
  return typeof value === "string" && value.length === 32 && !/[^0-9a-f]/.test(value);
}

export function isContextDigest(value: unknown): value is string {
  return typeof value === "string" && value.length === 71 && /^sha256:[0-9a-f]{64}$/.test(value);
}

export function readProjectionIdentity(value: unknown): ProjectionIdentity | null {
  if (!closed(value, ["snapshot_id", "sha256", "bytes", "digest_form"]) ||
    typeof value.snapshot_id !== "number" || !Number.isSafeInteger(value.snapshot_id) ||
    typeof value.bytes !== "number" || !Number.isSafeInteger(value.bytes) || value.bytes < 0 ||
    !isContextDigest(value.sha256) || value.digest_form !== "assesshub-store-blob") return null;
  return { snapshot_id: value.snapshot_id, sha256: value.sha256, bytes: value.bytes, digest_form: value.digest_form };
}

export function sameProjectionIdentity(a: ProjectionIdentity, b: ProjectionIdentity): boolean {
  return a.snapshot_id === b.snapshot_id && a.sha256 === b.sha256 && a.bytes === b.bytes && a.digest_form === b.digest_form;
}

export function readProjectionRowRef(value: unknown): ProjectionRowRef | null {
  if (!closed(value, ["index", "pointer"]) || typeof value.index !== "number" || !Number.isSafeInteger(value.index) ||
    value.index < 0 || typeof value.pointer !== "string" || !/^(?:\/(?:[^~/]|~[01])*)*$/.test(value.pointer)) return null;
  return { index: value.index, pointer: value.pointer };
}

export function sameSelection(a: SelectionTarget | null, b: SelectionTarget | null): boolean {
  return a === null || b === null ? a === b : a.list === b.list && a.row.index === b.row.index && a.row.pointer === b.row.pointer;
}

function selection(value: unknown): SelectionTarget | null | false {
  if (value === null) return null;
  if (!closed(value, ["list", "row"]) || !TOPOLOGY_LISTS.some((name) => name === value.list)) return false;
  const row = readProjectionRowRef(value.row);
  return row ? { list: value.list as TopologyList, row } : false;
}

function requestId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 64 && !/[^A-Za-z0-9_-]/.test(value);
}

function query(value: unknown): EmbedQuery | null | false {
  if (value === null) return null;
  if (!closed(value, ["src_ip", "dst_ip"]) || typeof value.src_ip !== "string" || typeof value.dst_ip !== "string" ||
    value.src_ip.length < 1 || value.src_ip.length > 128 || value.dst_ip.length < 1 || value.dst_ip.length > 128) return false;
  // Address meaning belongs to the engine, including its bad-address and cross-family results.
  return { src_ip: value.src_ip, dst_ip: value.dst_ip };
}

/** Closed, owned copies prevent another message listener from mutating a retained command. */
export function parseEmbedMessage(value: unknown): EmbedMessage | null {
  try {
    if (!record(value) || value.protocol !== EMBED_PROTOCOL || !isEmbedNonce(value.nonce)) return null;
    const envelope = { protocol: EMBED_PROTOCOL, nonce: value.nonce };
    const common = ["protocol", "type", "nonce"];
    const versionKeys = ["projection_schema", "style_schema"];
    const versions = { projection_schema: PROJECTION_SCHEMA, style_schema: TOPOLOGY_STYLE_SCHEMA };
    const hasVersions = value.projection_schema === PROJECTION_SCHEMA && value.style_schema === TOPOLOGY_STYLE_SCHEMA;
    if (value.type === "ready") {
      return closed(value, [...common, ...versionKeys, "snapshot_id"]) && hasVersions &&
        typeof value.snapshot_id === "number" && Number.isSafeInteger(value.snapshot_id)
        ? { ...envelope, ...versions, type: "ready", snapshot_id: value.snapshot_id } : null;
    }
    const identity = readProjectionIdentity(value.identity);
    const bound = identity && isContextDigest(value.context_digest) ? { identity, context_digest: value.context_digest } : null;
    const boundKeys = ["identity", "context_digest"];
    if (value.type === "refused") {
      if (!closed(value, [...common, ...boundKeys, "code", "request_id"]) ||
        !REFUSAL_CODES.some((code) => code === value.code) || (value.request_id !== null && !requestId(value.request_id))) return null;
      const context = bound ?? (value.identity === null && value.context_digest === null ? { identity: null, context_digest: null } : null);
      return context ? { ...envelope, ...context, type: "refused", code: value.code as EmbedRefusalCode,
        request_id: value.request_id as string | null } : null;
    }
    if (!bound) return null;
    switch (value.type) {
      case "init": return closed(value, [...common, ...boundKeys, ...versionKeys]) && hasVersions
        ? { ...envelope, ...versions, ...bound, type: "init" } : null;
      case "bound": return closed(value, [...common, ...boundKeys]) ? { ...envelope, ...bound, type: "bound" } : null;
      case "select": {
        if (!closed(value, [...common, ...boundKeys, "target"])) return null;
        const target = selection(value.target);
        return target === false ? null : { ...envelope, ...bound, type: "select", target };
      }
      case "query": {
        if (!closed(value, [...common, ...boundKeys, "request_id", "query"]) || !requestId(value.request_id)) return null;
        const input = query(value.query);
        return input === false ? null : { ...envelope, ...bound, type: "query", request_id: value.request_id, query: input };
      }
      case "query_applied": return closed(value, [...common, ...boundKeys, "request_id"]) && requestId(value.request_id)
        ? { ...envelope, ...bound, type: "query_applied", request_id: value.request_id } : null;
      default: return null;
    }
  } catch { return null; }
}

/** Normalize the advertised same-hub capability, then add a fresh mount nonce. */
export function projectionEmbedUrl(href: unknown, sid: number, nonce: string, origin: string): string | null {
  try {
    if (typeof href !== "string" || href.length > 2048 || !Number.isSafeInteger(sid) || !isEmbedNonce(nonce)) return null;
    const expected = new URL(origin);
    if (expected.origin !== origin || !["http:", "https:"].includes(expected.protocol)) return null;
    const url = new URL(href, expected);
    if (url.origin !== origin || url.username || url.password || url.hash || url.pathname !== `/scope/snapshots/${sid}/` ||
      [...url.searchParams].length !== 1 || url.searchParams.get("engine_projection") !== "1") return null;
    url.search = new URLSearchParams({ engine_projection: "1", [PROJECTION_NONCE_PARAM]: nonce }).toString();
    return url.href;
  } catch { return null; }
}

/** Explicit JSON canonicalization; no toJSON, accessors, holes, foreign objects or omitted values. */
export function canonicalProjectionJson(value: unknown): string {
  const active = new Set<object>();
  const visit = (item: unknown, depth: number): string => {
    if (depth > 128) throw new Error("Projection context exceeds the supported depth.");
    if (item === null || typeof item === "string" || typeof item === "boolean") return JSON.stringify(item);
    if (typeof item === "number" && Number.isFinite(item)) return JSON.stringify(item);
    if (typeof item !== "object" || item === null || active.has(item)) throw new Error("Projection context is not finite JSON.");
    active.add(item);
    try {
      if (Array.isArray(item)) {
        if (Object.getPrototypeOf(item) !== Array.prototype || Reflect.ownKeys(item).length !== item.length + 1) {
          throw new Error("Projection context is not an ordinary JSON array.");
        }
        const items: string[] = [];
        for (let index = 0; index < item.length; index++) {
          const descriptor = Object.getOwnPropertyDescriptor(item, String(index));
          if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, "value") || !descriptor.enumerable) throw new Error("Projection context has a missing array item.");
          items.push(visit(descriptor.value, depth + 1));
        }
        return `[${items.join(",")}]`;
      }
      if (!record(item)) throw new Error("Projection context is not an ordinary JSON object.");
      return `{${Object.keys(item).sort().map((key) => `${JSON.stringify(key)}:${visit(item[key], depth + 1)}`).join(",")}}`;
    } finally { active.delete(item); }
  };
  return visit(value, 0);
}

/** Comparison of independently fetched metadata, never a signature or source of rendered facts. */
export async function projectionContextDigest(
  engine: ProjectionEngine,
  limitations: readonly ProjectionLimitation[],
  subtle: ContextHasher | undefined = globalThis.crypto?.subtle,
): Promise<string> {
  if (!subtle) throw new Error("Projection context verification is unavailable.");
  const bytes = new TextEncoder().encode(canonicalProjectionJson({ engine, limitations }));
  if (bytes.byteLength > MAX_CONTEXT_BYTES) throw new Error("Projection context exceeds the comparison bound.");
  const digest = await subtle.digest("SHA-256", bytes);
  return `sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}
