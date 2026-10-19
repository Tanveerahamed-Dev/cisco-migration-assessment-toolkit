// Saved-plan transport only. Business admission and normalization stay server-owned.
import type { components } from "./generated/openapi";
import { api as legacyApi, ApiError, j } from "./api";
import { equalJson } from "./projection";
import { closed, isContextDigest, record as planObject } from "./projectionEmbed";
export { ApiError } from "./api";

type Schemas = components["schemas"];
export type SavedPlanAssessment = Schemas["SavedPlanAssessmentResponse"];
export type SavedPlanMeta = Schemas["SavedPlanMetaResponse"];
export type SavedPlanRecord = Schemas["SavedPlanResponse"];
export type SavedPlanState = Schemas["SavedPlanListResponse"];
export type SavedPlanRequirements = Schemas["SavedPlanRequirements"];
export type SavedPlanPin = Pick<SavedPlanRecord, "revision" | "sha256" | "selection_id">;
export type SavedPlanSaveInput = Omit<Schemas["SavedPlanIn"], "assessment"> & { assessment: SavedPlanAssessment };
export type SavedPlanSelectionInput = Schemas["SavedPlanSelectionIn"];
export type Deliverable = { key: string; label: string; ext: string; available: boolean;
  saved_plan_basis: string | null; saved_plan_supported: boolean };
type RequirementsView = { availability_tiers: string[]; fabric_models: string[];
  vlan_id: { minimum: number; maximum: number }; convergence_budget_ms: { minimum: number; maximum: number } };
export type Meta = { deliverables: Deliverable[]; requirementsContract: RequirementsView;
  display_limits: { revision_maximum: number; label_maximum_code_points: number } };

const ASSESSMENT_KEYS = ["source", "sha256", "bytes", "snapshot_id", "campaign_id", "engagement_id", "label", "script_version"];
const META_KEYS = ["schema", "revision", "label", "created_at", "sha256", "status"];
const SAVED_PLAN_DOCUMENT_LIMIT = 32 * 1024 * 1024;
const SAVED_PLAN_DOCUMENT_TYPES = { docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation" } as const;
const PLAN_TYPED_ARRAY_PROTOTYPE = Object.getPrototypeOf(Uint8Array.prototype);
const PLAN_BYTE_TAG = Object.getOwnPropertyDescriptor(PLAN_TYPED_ARRAY_PROTOTYPE, Symbol.toStringTag)?.get;
const PLAN_BYTE_LENGTH = Object.getOwnPropertyDescriptor(PLAN_TYPED_ARRAY_PROTOTYPE, "byteLength")?.get;
const PLAN_BYTE_OFFSET = Object.getOwnPropertyDescriptor(PLAN_TYPED_ARRAY_PROTOTYPE, "byteOffset")?.get;
const PLAN_BYTE_BUFFER = Object.getOwnPropertyDescriptor(PLAN_TYPED_ARRAY_PROTOTYPE, "buffer")?.get;

function planAssert(condition: unknown, message = "The saved-plan response has unsupported data", status = 502): asserts condition {
  if (!condition) throw new ApiError(message, status);
}
function planInteger(value: unknown, status = 502): asserts value is number {
  if (typeof value !== "number") throw new ApiError("The integer representation is invalid", status);
  if (!Number.isSafeInteger(value)) throw new ApiError("The integer representation is invalid", status);
}
function planId(value: unknown): asserts value is number { planInteger(value, 400); }
function planString(value: unknown): asserts value is string { planAssert(typeof value === "string"); }
function planRecord(value: unknown): asserts value is Record<string, unknown> { planAssert(planObject(value)); }
function planArray(value: unknown): asserts value is unknown[] { planAssert(Array.isArray(value)); }
function planStrings(value: unknown): asserts value is string[] {
  planArray(value);
  for (const item of value) planString(item);
}
function planAbort(signal?: AbortSignal): void { if (signal?.aborted) throw new DOMException("Aborted", "AbortError"); }
function planPin(pin: SavedPlanPin): void {
  planInteger(pin.revision); planInteger(pin.selection_id); planAssert(isContextDigest(pin.sha256));
}
function checkedAssessment(value: unknown, sid: number): SavedPlanAssessment {
  planAssert(closed(value, ASSESSMENT_KEYS));
  planInteger(value.snapshot_id); planInteger(value.campaign_id); planInteger(value.bytes);
  planAssert(value.snapshot_id === sid && isContextDigest(value.sha256), "The assessment does not match the request");
  for (const key of ["source", "engagement_id", "label", "script_version"]) planString(value[key]);
  return value as unknown as SavedPlanAssessment;
}
function checkedMeta(value: unknown): SavedPlanMeta {
  planAssert(closed(value, META_KEYS));
  metaFields(value);
  // Posture, date, label normalization and history policies have already been admitted by the server.
  return value as unknown as SavedPlanMeta;
}
function metaFields(value: Record<string, unknown>): void {
  planInteger(value.revision); planString(value.label); planString(value.created_at);
  planAssert(isContextDigest(value.sha256));
}
function renderedRequirements(value: unknown): void {
  planRecord(value);
  for (const key of ["availability_tier", "growth_horizon", "fabric_operating_model", "address_space"]) {
    if (value[key] !== undefined) planString(value[key]);
  }
  for (const key of ["critical_apps", "constraints", "data_classification"]) {
    if (value[key] !== undefined) planStrings(value[key]);
  }
  if (value.convergence_budget_ms !== undefined) planInteger(value.convergence_budget_ms);
  if (value.vlan_zones !== undefined) {
    planRecord(value.vlan_zones);
    for (const zone of Object.values(value.vlan_zones)) planString(zone);
  }
}
function checkedPlan(value: unknown, sid: number, pin?: SavedPlanPin, expected?: SavedPlanAssessment): SavedPlanRecord {
  planAssert(closed(value, [...META_KEYS, "selection_id", "assessment", "projection"]));
  metaFields(value); planInteger(value.selection_id);
  const assessment = checkedAssessment(value.assessment, sid);
  if (expected) planAssert(equalJson(assessment, expected), "The response does not match the captured assessment");
  if (pin) planAssert(equalJson({ revision: value.revision, sha256: value.sha256, selection_id: value.selection_id }, pin),
    "The response does not match the captured selection");
  const projection = value.projection;
  planAssert(closed(projection, ["schema", "requirements", "sections", "derivation"]));
  renderedRequirements(projection.requirements);
  const sections = projection.sections;
  planAssert(closed(sections, ["requirements_register", "design_blueprint", "design_nrfu"]));
  const blueprint = sections.design_blueprint, nrfu = sections.design_nrfu;
  planRecord(blueprint); planRecord(blueprint.summary); planString(blueprint.summary.headline);
  for (const key of ["n_recommended", "n_needs_requirement", "n_critical"]) planInteger(blueprint.summary[key]);
  planArray(blueprint.decisions);
  for (const row of blueprint.decisions) {
    planRecord(row);
    for (const key of ["id", "title", "priority", "status", "driver"]) planString(row[key]);
    if (row.recommended_action !== undefined && row.recommended_action !== null) planString(row.recommended_action);
  }
  planRecord(nrfu); planInteger(nrfu.n_items); planString(nrfu.note); planArray(nrfu.items);
  for (const row of nrfu.items) {
    planRecord(row);
    for (const key of ["decision_id", "title", "phase", "description", "pass_criteria"]) planString(row[key]);
  }
  return value as unknown as SavedPlanRecord;
}
function checkedPlanState(value: unknown, sid: number): SavedPlanState {
  planAssert(closed(value, ["assessment", "selection_id", "selected_revision", "revisions"]));
  checkedAssessment(value.assessment, sid); planInteger(value.selection_id);
  if (value.selected_revision !== null) planInteger(value.selected_revision);
  planArray(value.revisions);
  for (const row of value.revisions) checkedMeta(row);
  return value as unknown as SavedPlanState;
}
function checkedContract(value: unknown): Meta {
  planAssert(closed(value, ["requirements", "display_limits", "catalogue"]));
  const r = value.requirements, limits = value.display_limits;
  planRecord(r); planStrings(r.availability_tiers); planStrings(r.fabric_models);
  planRecord(r.vlan_id); planInteger(r.vlan_id.minimum); planInteger(r.vlan_id.maximum);
  planRecord(r.convergence_budget_ms); planInteger(r.convergence_budget_ms.minimum); planInteger(r.convergence_budget_ms.maximum);
  planRecord(limits); planInteger(limits.revision_maximum); planInteger(limits.label_maximum_code_points);
  planArray(value.catalogue);
  for (const row of value.catalogue) {
    planRecord(row);
    for (const key of ["key", "label", "ext"]) planString(row[key]);
    planAssert(typeof row.available === "boolean" && typeof row.saved_plan_supported === "boolean");
    if (row.saved_plan_basis !== null) planString(row.saved_plan_basis);
  }
  return { deliverables: value.catalogue as Deliverable[], requirementsContract: r as unknown as RequirementsView,
    display_limits: limits as Meta["display_limits"] };
}
function savedPlanUrl(sid: number, pin: SavedPlanPin, kind?: string): string {
  planId(sid); planPin(pin);
  if (kind !== undefined) planAssert(/^[a-z][a-z0-9_-]{0,63}$/.test(kind), "The document kind is invalid", 400);
  const suffix = kind === undefined ? "" : `/deliverable/${encodeURIComponent(kind)}`;
  return `/api/snapshots/${sid}/plans/${pin.revision}${suffix}?plan_sha256=${encodeURIComponent(pin.sha256)}&selection_id=${pin.selection_id}`;
}
async function savedPlanJson(url: string, signal?: AbortSignal, body?: unknown): Promise<unknown> {
  planAbort(signal);
  const response = await fetch(url, { cache: "no-store", signal,
    ...(body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }) });
  const value = await j<unknown>(response); planAbort(signal); return value;
}

async function discardPlanResponse(response: Response): Promise<void> {
  if (response.body && !response.body.locked) {
    try { await response.body.cancel(); } catch { /* preserve the original failure */ }
  }
}
function ownedPlanChunk(value: unknown, remaining: number): Uint8Array<ArrayBuffer> {
  planAssert(ArrayBuffer.isView(value) && PLAN_BYTE_TAG?.call(value) === "Uint8Array",
    "The document stream is invalid");
  const length: unknown = PLAN_BYTE_LENGTH?.call(value);
  const offset: unknown = PLAN_BYTE_OFFSET?.call(value);
  const buffer: ArrayBufferLike | undefined = PLAN_BYTE_BUFFER?.call(value);
  planInteger(length); planInteger(offset);
  planAssert(buffer !== undefined, "The document stream is invalid");
  planAssert(length <= remaining, "The saved-plan document exceeds the download limit", 413);
  // A fixed-length view/copy does not retain a larger backing buffer, invoke an overridden
  // iterator, or let a spoofed .byteLength bypass the limit. It also admits cross-realm bytes.
  const owned = new Uint8Array(length);
  owned.set(new Uint8Array(buffer, offset, length));
  return owned;
}
async function planResponseChunks(response: Response, limit: number, signal?: AbortSignal): Promise<Uint8Array<ArrayBuffer>[]> {
  planAbort(signal);
  const length = response.headers.get("content-length");
  let declared: number | null = null;
  if (length !== null) {
    planAssert(/^\d+$/.test(length) && Number.isSafeInteger(Number(length)), "The document length is invalid");
    declared = Number(length);
    planAssert(declared <= limit, "The saved-plan document exceeds the download limit", 413);
  }
  planAssert(response.body, "The saved-plan response has no document body");
  const reader = response.body.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let total = 0, completed = false;
  const cancel = () => { void reader.cancel().catch(() => undefined); };
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    for (;;) {
      planAbort(signal);
      const { done, value } = await reader.read();
      planAbort(signal);
      if (done) { completed = true; break; }
      const chunk = ownedPlanChunk(value, limit - total);
      total += chunk.byteLength;
      chunks.push(chunk);
    }
    if (!response.headers.get("content-encoding") || response.headers.get("content-encoding") === "identity") {
      planAssert(declared === null || declared === total, "The saved-plan document was truncated");
    }
    return chunks;
  } finally {
    signal?.removeEventListener("abort", cancel);
    if (!completed) { try { await reader.cancel(); } catch { /* preserve the original failure */ } }
    reader.releaseLock();
  }
}
async function savedPlanDocument(sid: number, record: SavedPlanRecord, kind: string,
  extension: "docx" | "pptx", signal: AbortSignal | undefined, basis: string): Promise<{ blob: Blob; extension: "docx" | "pptx" }> {
  planAbort(signal);
  planId(sid);
  const plan = record;
  planPin(plan);
  planAssert(plan.assessment.snapshot_id === sid, "The document source differs");
  planString(basis);
  planAssert(extension === "docx" || extension === "pptx", "The document format is unsupported", 400);
  const response = await fetch(savedPlanUrl(sid, plan, kind), { cache: "no-store", signal });
  try {
    planAbort(signal);
    if (!response.ok) {
      // Preserve j/ApiError status/detail handling while bounding even a hostile error body.
      let parts: Uint8Array<ArrayBuffer>[] = [];
      try { parts = await planResponseChunks(response, 64 * 1024, signal); }
      catch (error) { planAbort(signal); if (!(error instanceof ApiError)) throw error; }
      const errorBody = new Uint8Array(parts.reduce((total, part) => total + part.byteLength, 0));
      let offset = 0;
      for (const part of parts) { errorBody.set(part, offset); offset += part.byteLength; }
      return await j<never>(new Response(errorBody, {
        status: response.status, statusText: response.statusText, headers: response.headers,
      }));
    }
    planAssert(response.status === 200, "The saved-plan download is not a complete document response");
    const headers = response.headers;
    planAssert(headers.get("X-Atlas-Assessment-SHA256") === plan.assessment.sha256
      && headers.get("X-Atlas-Plan-Revision") === String(plan.revision)
      && headers.get("X-Atlas-Plan-SHA256") === plan.sha256
      && headers.get("X-Atlas-Plan-Selection") === String(plan.selection_id)
      && headers.get("X-Atlas-Plan-Status") === plan.status
      && headers.get("X-Atlas-Plan-Basis") === basis,
    "The downloaded document belongs to a different assessment or saved-plan selection");
    const media = SAVED_PLAN_DOCUMENT_TYPES[extension];
    planAssert(headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() === media,
      "The downloaded document has an unexpected file type");
    const chunks = await planResponseChunks(response, SAVED_PLAN_DOCUMENT_LIMIT, signal);
    const prefix: number[] = [];
    for (const chunk of chunks) {
      for (const byte of chunk) { prefix.push(byte); if (prefix.length === 4) break; }
      if (prefix.length === 4) break;
    }
    planAssert(prefix.length === 4 && prefix[0] === 0x50 && prefix[1] === 0x4b
      && prefix[2] === 0x03 && prefix[3] === 0x04, "The downloaded document is empty or is not an Office ZIP container");
    planAbort(signal);
    return { blob: new Blob(chunks, { type: media }), extension };
  } catch (error) {
    await discardPlanResponse(response);
    throw error;
  }
}

export const api = {
  ...legacyApi,
  meta: async (signal?: AbortSignal): Promise<Meta> => checkedContract(await savedPlanJson("/api/saved-plan-contract", signal)),
  savedPlans: async (id: number, signal?: AbortSignal): Promise<SavedPlanState> => {
    planId(id); return checkedPlanState(await savedPlanJson(`/api/snapshots/${id}/plans`, signal), id);
  },
  savePlan: async (id: number, body: SavedPlanSaveInput, signal?: AbortSignal): Promise<SavedPlanRecord> => {
    planId(id); planInteger(body.expected_selection_id, 400);
    const expected = body.assessment, selection = body.expected_selection_id;
    const record = checkedPlan(await savedPlanJson(`/api/snapshots/${id}/plans`, signal, body), id, undefined, expected);
    planAssert(record.selection_id > selection, "The save response did not advance the captured selection");
    return record;
  },
  selectSavedPlan: async (id: number, revision: number, body: SavedPlanSelectionInput,
    signal?: AbortSignal, expected?: SavedPlanAssessment): Promise<SavedPlanRecord> => {
    planId(id); planInteger(revision, 400); planInteger(body.expected_selection_id, 400);
    planAssert(isContextDigest(body.plan_sha256), "The digest representation is invalid", 400);
    const selection = body.expected_selection_id, digest = body.plan_sha256;
    const record = checkedPlan(await savedPlanJson(`/api/snapshots/${id}/plans/${revision}/select`, signal, body), id, undefined, expected);
    planAssert(record.revision === revision && record.sha256 === digest && record.selection_id > selection,
      "The selection response does not match the captured request");
    return record;
  },
  savedPlan: async (id: number, revision: number, sha256: string, selectionId: number,
    signal?: AbortSignal, expected?: SavedPlanAssessment): Promise<SavedPlanRecord> =>
    checkedPlan(await savedPlanJson(savedPlanUrl(id, { revision, sha256, selection_id: selectionId }), signal),
      id, { revision, sha256, selection_id: selectionId }, expected),
  savedPlanDeliverableUrl: (id: number, pin: SavedPlanPin, kind: string) => savedPlanUrl(id, pin, kind),
  savedPlanDocument,
};
