import { afterEach, describe, expect, it, vi } from "vitest";
import { runInNewContext } from "node:vm";
import { api, ApiError, type SavedPlanAssessment, type SavedPlanRecord, type SavedPlanState } from "./api";

const docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const pptx = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
const zip = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 1, 2, 3, 4]);

function assessment(): SavedPlanAssessment {
  return { source: "persisted snapshots.snapshot_json blob", sha256: "sha256:" + "a".repeat(64),
    bytes: 123, snapshot_id: 7, campaign_id: 3, engagement_id: "EXAMPLE-engagement",
    label: "EXAMPLE baseline", script_version: "3.23.0" };
}
function record(): SavedPlanRecord {
  return {
    schema: "atlas.saved_plan/1", revision: 1, label: "EXAMPLE plan", created_at: "2026-10-15T12:30:00.123456+00:00",
    sha256: "sha256:" + "b".repeat(64), status: "UNAPPROVED_DRAFT", selection_id: 11, assessment: assessment(),
    projection: {
      schema: "atlas.saved_plan_projection/1", requirements: { convergence_budget_ms: 0 },
      sections: {
        requirements_register: { convergence_budget_ms: 0 },
        design_blueprint: {
          decisions: [], tradeoff_scorecard: [], methodology: "EXAMPLE bounded design", axes: [],
          requirements_model: { fields: [], open_questions: [], provided: true, note: "EXAMPLE" },
          summary: { n_decisions: 0, n_recommended: 0, n_needs_requirement: 0, n_critical: 0,
            by_domain: {}, requirements_provided: true, headline: "EXAMPLE preview" },
          coverage: { inventory: 1, collected: 1, not_collected: 0, caveat: "Captured evidence only" },
        },
        design_nrfu: { items: [], n_items: 0, note: "EXAMPLE checklist" },
        architecture_coverage: { classes: [], summary: { n_classes: 0, n_observed: 0, n_not_observed: 0,
          n_with_findings: 0, n_clean: 0, by_channel: { ssh: 0, json: 0 } } },
        coverage_matrix: {}, unknown_evidence: {}, schema_census: {}, fact_lineage: {},
      },
      derivation: { schema: "atlas.saved_plan_derivation/1", owners: ["EXAMPLE-owner"], engine_schema_version: "3.23.0",
        implementation_identity: null, implementation_identity_status: "not_established", authority: "none", note: "EXAMPLE" },
    },
  };
}
function state(): SavedPlanState {
  const plan = record();
  const { schema, revision, label, created_at, sha256, status } = plan;
  return { assessment: assessment(), selection_id: 11, selected_revision: 1,
    revisions: [{ schema, revision, label, created_at, sha256, status }] };
}
function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}
function documentHeaders(plan = record(), type = docx): Record<string, string> {
  return { "content-type": type, "X-Atlas-Assessment-SHA256": plan.assessment.sha256,
    "X-Atlas-Plan-Revision": String(plan.revision), "X-Atlas-Plan-SHA256": plan.sha256,
    "X-Atlas-Plan-Selection": String(plan.selection_id), "X-Atlas-Plan-Status": plan.status };
}
function documentResponse(body: BodyInit | null = zip, headers = documentHeaders()): Response {
  return new Response(body, { headers });
}
function pinnedUrl(kind?: string): string {
  return `/api/snapshots/7/plans/1${kind ? `/deliverable/${kind}` : ""}?plan_sha256=sha256%3A${"b".repeat(64)}&selection_id=11`;
}

afterEach(() => vi.restoreAllMocks());

describe("saved-plan JSON client", () => {
  it("reads finite metadata with no-store and the caller's cancellation signal", async () => {
    const signal = new AbortController().signal;
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(state()));
    await expect(api.savedPlans(7, signal)).resolves.toEqual(state());
    expect(fetch).toHaveBeenCalledWith("/api/snapshots/7/plans", { cache: "no-store", signal });
  });

  it("sends exact source binding, zero-valued requirements and the selection CAS on save", async () => {
    const signal = new AbortController().signal;
    const body = { label: "EXAMPLE plan", requirements: { convergence_budget_ms: 0 },
      assessment: assessment(), expected_selection_id: 0 };
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(record(), 201));
    await expect(api.savePlan(7, body, signal)).resolves.toEqual(record());
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith("/api/snapshots/7/plans", {
      cache: "no-store", signal, method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
  });

  it.each(["0", "9007199254740991"])("preserves accepted convergence string %s without numeric coercion", async (text) => {
    const plan = record();
    const normalized = text === "0" ? 0 : Number.MAX_SAFE_INTEGER;
    plan.projection.requirements.convergence_budget_ms = normalized;
    plan.projection.sections.requirements_register.convergence_budget_ms = normalized;
    const body = { label: plan.label, requirements: { convergence_budget_ms: text },
      assessment: assessment(), expected_selection_id: 0 };
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(plan, 201));
    await expect(api.savePlan(7, body)).resolves.toEqual(plan);
    expect(fetch).toHaveBeenCalledWith("/api/snapshots/7/plans", expect.objectContaining({ body: JSON.stringify(body) }));
    const sent = JSON.parse(String(fetch.mock.calls[0]?.[1]?.body));
    expect(sent.requirements.convergence_budget_ms).toBe(text);
  });

  it.each(["9007199254740992", "9223372036854775807", Number.MAX_SAFE_INTEGER + 1])(
    "rejects convergence %s before it can commit an unreadable rounded plan", async (value) => {
      const fetch = vi.spyOn(globalThis, "fetch");
      await expect(api.savePlan(7, { label: "EXAMPLE plan", requirements: { convergence_budget_ms: value },
        assessment: assessment(), expected_selection_id: 0 })).rejects.toMatchObject({
        status: 400, message: expect.stringContaining("9007199254740991"),
      });
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("selects the named revision with CAS and accepts a new selection identity", async () => {
    const selected = { ...record(), selection_id: 12 };
    const body = { plan_sha256: selected.sha256, expected_selection_id: 11 };
    const signal = new AbortController().signal;
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(selected));
    await expect(api.selectSavedPlan(7, 1, body, signal)).resolves.toEqual(selected);
    expect(fetch).toHaveBeenCalledWith("/api/snapshots/7/plans/1/select", {
      cache: "no-store", signal, method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    });
  });

  it("requires a successful save or select to advance the selection generation", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(record(), 201));
    await expect(api.savePlan(7, { label: "EXAMPLE plan", requirements: {}, assessment: assessment(),
      expected_selection_id: 11 })).rejects.toMatchObject({ status: 502 });
    fetch.mockResolvedValueOnce(jsonResponse(record()));
    await expect(api.selectSavedPlan(7, 1, { plan_sha256: record().sha256, expected_selection_id: 11 }))
      .rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("reopens only the exact pin and builds an exact document URL without a latest fallback", async () => {
    const plan = record();
    const signal = new AbortController().signal;
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(plan));
    expect(api.savedPlanDeliverableUrl(7, plan, "mop")).toBe(pinnedUrl("mop"));
    expect(fetch).not.toHaveBeenCalled();
    await expect(api.savedPlan(7, 1, plan.sha256, 11, signal)).resolves.toEqual(plan);
    expect(fetch).toHaveBeenCalledWith(pinnedUrl(), { cache: "no-store", signal });
  });

  it.each([0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1, true, "7"])(
    "rejects unsafe or coercible snapshot identity %s before fetch", async (sid) => {
      const fetch = vi.spyOn(globalThis, "fetch");
      await expect(api.savedPlans(sid as number)).rejects.toMatchObject({ name: "ApiError", status: 400 });
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it.each([
    { revision: 0 }, { revision: 65 }, { revision: 1.5 }, { selection_id: 0 },
    { selection_id: Number.MAX_SAFE_INTEGER + 1 }, { sha256: "sha256:" + "B".repeat(64) },
  ])("refuses an invalid pin before constructing a URL: %o", (change) => {
    expect(() => api.savedPlanDeliverableUrl(7, { ...record(), ...change }, "mop")).toThrow(ApiError);
  });

  it("rejects path-shaped document kinds", () => {
    expect(() => api.savedPlanDeliverableUrl(7, record(), "../mop")).toThrow(ApiError);
  });

  it.each(["list", "save", "select", "read", "document"])("does not retry or replace a 409 for %s", async (operation) => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ detail: "Reload the selected plan" }, 409));
    const plan = record();
    const pending = operation === "list" ? api.savedPlans(7)
      : operation === "save" ? api.savePlan(7, { label: plan.label, requirements: {}, assessment: assessment(), expected_selection_id: 11 })
      : operation === "select" ? api.selectSavedPlan(7, 1, { plan_sha256: plan.sha256, expected_selection_id: 11 })
      : operation === "document" ? api.savedPlanDocument(7, plan, "mop", "docx")
      : api.savedPlan(7, 1, plan.sha256, 11);
    await expect(pending).rejects.toMatchObject({ name: "ApiError", status: 409, message: "Reload the selected plan", retryable: false });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("rejects cross-snapshot and unsafe campaign bindings in wire metadata", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    for (const change of [{ snapshot_id: 8 }, { snapshot_id: true }, { campaign_id: 0 },
      { campaign_id: Number.MAX_SAFE_INTEGER + 1 }, { bytes: "123" }, { source: "uploaded bytes" }]) {
      const wrong = { ...state(), assessment: { ...assessment(), ...change } };
      fetch.mockResolvedValueOnce(jsonResponse(wrong));
      await expect(api.savedPlans(7)).rejects.toMatchObject({ status: 502 });
    }
  });

  it("requires the returned save binding to match every requested source field", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const body = { label: "EXAMPLE plan", requirements: {}, assessment: assessment(), expected_selection_id: 0 };
    for (const change of [{ campaign_id: 4 }, { engagement_id: "EXAMPLE-other" }, { label: "EXAMPLE-other" },
      { script_version: "old" }, { bytes: 124 }, { sha256: "sha256:" + "c".repeat(64) }]) {
      fetch.mockResolvedValueOnce(jsonResponse({ ...record(), assessment: { ...assessment(), ...change } }));
      await expect(api.savePlan(7, body)).rejects.toMatchObject({ status: 502 });
    }
  });

  it("rejects inconsistent, missing and non-draft selection states", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const valid = state();
    for (const wrong of [
      { ...valid, selected_revision: 2 }, { ...valid, selection_id: 0 },
      { ...valid, revisions: [] }, { ...valid, revisions: [valid.revisions[0], valid.revisions[0]] },
      { ...valid, revisions: [{ ...valid.revisions[0], status: "APPROVED" }] },
      { ...valid, selected_revision: "1" }, { ...valid, selection_id: Number.MAX_SAFE_INTEGER + 1 },
    ]) {
      fetch.mockResolvedValueOnce(jsonResponse(wrong));
      await expect(api.savedPlans(7)).rejects.toMatchObject({ status: 502 });
    }
    const empty = { assessment: assessment(), selection_id: 0, selected_revision: null, revisions: [] };
    fetch.mockResolvedValueOnce(jsonResponse(empty));
    await expect(api.savedPlans(7)).resolves.toEqual(empty);
  });

  it("rejects a returned different pin, unsupported posture or malformed projection", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const plan = record();
    for (const wrong of [
      { ...plan, selection_id: 12 }, { ...plan, revision: 2 }, { ...plan, sha256: "sha256:" + "c".repeat(64) },
      { ...plan, status: "APPROVED" }, { ...plan, created_at: "not a date" },
      { ...plan, projection: { ...plan.projection, sections: {} } },
      { ...plan, projection: { ...plan.projection, derivation: { ...plan.projection.derivation, authority: "approved" } } },
    ]) {
      fetch.mockResolvedValueOnce(jsonResponse(wrong));
      await expect(api.savedPlan(7, 1, plan.sha256, 11)).rejects.toMatchObject({ status: 502 });
    }
  });

  it("does not coerce an NRFU phase array into an accepted string enum", async () => {
    const plan = record();
    const wrong = { ...plan, projection: { ...plan.projection, sections: {
      ...plan.projection.sections, design_nrfu: { n_items: 1, note: "EXAMPLE", items: [{
        decision_id: "EXAMPLE", title: "EXAMPLE", priority: "High", phase: ["pre-cutover"],
        description: "EXAMPLE", pass_criteria: "EXAMPLE", setup: "EXAMPLE", devices: [], principle_citation: "EXAMPLE",
      }] },
    } } };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(wrong));
    await expect(api.savedPlan(7, 1, plan.sha256, 11)).rejects.toMatchObject({ status: 502 });
  });

  it("refuses already-aborted requests without network effects", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetch = vi.spyOn(globalThis, "fetch");
    await expect(api.savedPlans(7, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    await expect(api.savedPlanDocument(7, record(), "mop", "docx", controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("saved-plan document response boundary", () => {
  it.each([["mop", "docx", docx], ["deck", "pptx", pptx]] as const)(
    "returns a verified bounded Blob for %s with explicit %s extension", async (kind, ext, type) => {
      const signal = new AbortController().signal;
      const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(documentResponse(zip, documentHeaders(record(), type)));
      const result = await api.savedPlanDocument(7, record(), kind, ext, signal);
      expect(result.extension).toBe(ext);
      expect(result.blob.size).toBe(zip.byteLength);
      expect(result.blob.type).toBe(type);
      expect(fetch).toHaveBeenCalledWith(pinnedUrl(kind), { cache: "no-store", signal });
    },
  );

  it("accepts a ZIP signature split across streamed chunks", async () => {
    const stream = new ReadableStream<Uint8Array>({ start(controller) {
      controller.enqueue(zip.slice(0, 1)); controller.enqueue(zip.slice(1, 3)); controller.enqueue(zip.slice(3)); controller.close();
    } });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(documentResponse(stream));
    const result = await api.savedPlanDocument(7, record(), "mop", "docx");
    expect(result.blob.size).toBe(8);
  });

  it("accepts genuine cross-realm Uint8Array bytes and ignores spoofed own byte metadata", async () => {
    const foreign = runInNewContext("new Uint8Array([80,75,3,4,1,2,3,4])") as Uint8Array;
    expect(foreign instanceof Uint8Array).toBe(false);
    expect(ArrayBuffer.isView(foreign)).toBe(true);
    Object.defineProperty(foreign, "byteLength", { value: 0 });
    Object.defineProperty(foreign, "byteOffset", { value: 999 });
    Object.defineProperty(foreign, "buffer", { value: new ArrayBuffer(0) });
    const response = documentResponse(new ReadableStream<Uint8Array>({ start(controller) {
      controller.enqueue(foreign); controller.close();
    } }));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    const result = await api.savedPlanDocument(7, record(), "mop", "docx");
    expect(result.blob.size).toBe(zip.byteLength);
    expect(result.blob.type).toBe(docx);
  });

  it("rejects another typed-array kind even when its tag and raw bytes imitate Uint8Array", async () => {
    const foreign = runInNewContext("new Uint16Array(4)") as Uint16Array;
    new Uint8Array(foreign.buffer).set(zip);
    Object.defineProperty(foreign, Symbol.toStringTag, { value: "Uint8Array" });
    expect(Object.prototype.toString.call(foreign)).toBe("[object Uint8Array]");
    expect(ArrayBuffer.isView(foreign)).toBe(true);
    const response = documentResponse(new ReadableStream<Uint8Array>({ start(controller) {
      controller.enqueue(foreign as unknown as Uint8Array); controller.close();
    } }));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({
      status: 502, message: "The document stream is invalid",
    });
  });

  it("uses the intrinsic byte length to refuse an oversized cross-realm view", async () => {
    const foreign = runInNewContext("new Uint8Array(32 * 1024 * 1024 + 1)") as Uint8Array;
    foreign.set(zip);
    Object.defineProperty(foreign, "byteLength", { value: 0 });
    const cancel = vi.fn();
    const response = documentResponse(new ReadableStream<Uint8Array>({ start(controller) {
      controller.enqueue(foreign);
    }, cancel }));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 413 });
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body?.locked).toBe(false);
  });

  it("refuses a partial HTTP response even when it starts with the expected ZIP signature", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(zip, { status: 206, headers: documentHeaders() }));
    await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 502 });
  });

  it.each([
    "X-Atlas-Assessment-SHA256", "X-Atlas-Plan-Revision", "X-Atlas-Plan-SHA256", "X-Atlas-Plan-Selection", "X-Atlas-Plan-Status",
  ])("rejects a missing or tampered %s before returning body bytes", async (name) => {
    for (const value of [null, "wrong"]) {
      const cancel = vi.fn();
      const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(zip); }, cancel });
      const headers = documentHeaders();
      if (value === null) delete headers[name]; else headers[name] = value;
      const response = documentResponse(body, headers);
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response);
      await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 502 });
      expect(cancel).toHaveBeenCalledOnce();
      expect(response.body?.locked).toBe(false);
    }
  });

  it.each(["application/json", "text/html", pptx, "application/octet-stream"])(
    "refuses wrong MIME %s even with a ZIP prefix", async (type) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(documentResponse(zip, documentHeaders(record(), type)));
      await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 502 });
    },
  );

  it.each([null, ""])("refuses a missing or empty content type %s", async (contentType) => {
    const headers = documentHeaders();
    if (contentType === null) delete headers["content-type"];
    else headers["content-type"] = contentType;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(documentResponse(zip, headers));
    await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 502 });
  });

  it.each([new Uint8Array(), new Uint8Array([0x50, 0x4b]), new Uint8Array([0x50, 0x4b, 0x05, 0x06]), new TextEncoder().encode("<html>error</html>")])(
    "refuses empty, truncated or non-Office ZIP body %o", async (body) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(documentResponse(body));
      await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 502 });
    },
  );

  it("rejects cross-snapshot document input before fetching", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    await expect(api.savedPlanDocument(8, record(), "mop", "docx")).rejects.toMatchObject({ status: 502 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects declared oversize before reading and cancels its stream", async () => {
    const cancel = vi.fn();
    const response = documentResponse(new ReadableStream({ cancel }), {
      ...documentHeaders(), "content-length": String(32 * 1024 * 1024 + 1),
    });
    const read = vi.spyOn(response, "arrayBuffer");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 413 });
    expect(read).not.toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("stops an undeclared oversized stream before joining or creating an unbounded Blob", async () => {
    const chunk = new Uint8Array(8 * 1024 * 1024);
    chunk.set(zip);
    let pulls = 0;
    const cancel = vi.fn();
    const response = documentResponse(new ReadableStream<Uint8Array>({
      pull(controller) { pulls += 1; controller.enqueue(chunk); }, cancel,
    }));
    const blob = vi.spyOn(response, "blob"), arrayBuffer = vi.spyOn(response, "arrayBuffer");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 413 });
    expect(pulls).toBeLessThanOrEqual(6);
    expect(blob).not.toHaveBeenCalled();
    expect(arrayBuffer).not.toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body?.locked).toBe(false);
  });

  it("refuses a body shorter than the unencoded declared length", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(documentResponse(zip, { ...documentHeaders(), "content-length": "20" }));
    await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toMatchObject({ status: 502 });
  });

  it("cancels a pending stream read on abort and releases its reader", async () => {
    let began!: () => void;
    const reading = new Promise<void>((resolve) => { began = resolve; });
    const cancel = vi.fn();
    const response = documentResponse(new ReadableStream<Uint8Array>({ pull() { began(); }, cancel }));
    const controller = new AbortController();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    const pending = api.savedPlanDocument(7, record(), "mop", "docx", controller.signal);
    await reading;
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body?.locked).toBe(false);
  });

  it("preserves stream errors while cleaning up its reader", async () => {
    const response = documentResponse(new ReadableStream<Uint8Array>({ pull(controller) { controller.error(new Error("synthetic transport failure")); } }));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    await expect(api.savedPlanDocument(7, record(), "mop", "docx")).rejects.toThrow("synthetic transport failure");
    expect(response.body?.locked).toBe(false);
  });
});
