import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, bandColor, gateColor, readyColor, sevColor, sevSoft } from "./api";

// The shared colour helpers map the engine's category vocabulary onto CSS custom-property names
// (with a fallback var). The contract worth pinning: the label is squashed into a token, and the
// fallback / suffix differ per family — a drift here silently mis-colours every severity chip, band,
// and gate in the cockpit. (src/api.ts colour helpers.)
describe("colour token helpers", () => {
  it("sevColor squashes whitespace into the --sev token with a faint fallback", () => {
    expect(sevColor("High")).toBe("var(--sev-High, var(--text-faint))");
    expect(sevColor("High Risk")).toBe("var(--sev-HighRisk, var(--text-faint))");
    expect(sevColor("High   Risk")).toBe("var(--sev-HighRisk, var(--text-faint))"); // \s+ collapses runs
  });

  it("sevSoft carries the -soft suffix and a DIFFERENT (surface) fallback", () => {
    expect(sevSoft("High Risk")).toBe("var(--sev-HighRisk-soft, var(--surface-3))");
  });

  it("bandColor and readyColor use their own token families", () => {
    expect(bandColor("Band A")).toBe("var(--band-BandA, var(--text-faint))");
    expect(readyColor("Not Ready")).toBe("var(--ready-NotReady, var(--text-faint))");
  });

  it("gateColor ALSO strips hyphens — the one helper that does (GO/NO-GO gate labels)", () => {
    expect(gateColor("GO")).toBe("var(--gate-GO, var(--text-faint))");
    expect(gateColor("NO-GO")).toBe("var(--gate-NOGO, var(--text-faint))");
    expect(gateColor("NO GO")).toBe("var(--gate-NOGO, var(--text-faint))");
  });

  it("the hyphen behaviour is what distinguishes gateColor from the others", () => {
    // a hyphen SURVIVES in the sev token but is stripped in the gate token — the meaningful contrast
    expect(sevColor("A-B")).toBe("var(--sev-A-B, var(--text-faint))");
    expect(gateColor("A-B")).toBe("var(--gate-AB, var(--text-faint))");
  });

  it("an empty label still yields a well-formed var() (no crash, honest empty token)", () => {
    expect(sevColor("")).toBe("var(--sev-, var(--text-faint))");
  });
});

// Folder ingest (ADR-0004 P1): a plain JSON POST — the path is a SERVER-local directory, so there
// is no multipart body here, unlike the ZIP/snapshot uploads.
describe("api.ingestFolder", () => {
  afterEach(() => vi.restoreAllMocks());

  it("POSTs JSON {path, label} to the campaign's ingest-folder route", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ id: 7, ingest: {} }), { status: 201 }));
    await api.ingestFolder(3, "D:\\data\\siteA", "field");
    expect(spy).toHaveBeenCalledWith(
      "/api/campaigns/3/ingest-folder",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: "D:\\data\\siteA", label: "field" }),
      }),
    );
  });
});

// The `api` client is the app's whole data layer; the shared `j` response handler is where every
// call's success/error semantics live (FastAPI `detail` extraction, 204 -> null, status fallback).
// Tested through the client with a mocked global fetch — no network, no backend.
describe("api client (request construction + the j response handler)", () => {
  afterEach(() => vi.restoreAllMocks());

  function mockFetch(resp: Response) {
    return vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
  }

  it("GETs the right URL and parses the JSON body on success", async () => {
    const spy = mockFetch(new Response(JSON.stringify([{ id: 1, name: "[HISTORY-REDACTED]" }]), { status: 200 }));
    await expect(api.listCampaigns()).resolves.toEqual([{ id: 1, name: "[HISTORY-REDACTED]" }]);
    expect(spy).toHaveBeenCalledWith("/api/campaigns");
  });

  it("interpolates path params (getCampaign)", async () => {
    const spy = mockFetch(new Response(JSON.stringify({ id: 42 }), { status: 200 }));
    await api.getCampaign(42);
    expect(spy).toHaveBeenCalledWith("/api/campaigns/42");
  });

  it("returns null for a 204 without parsing a body (deleteCampaign)", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(api.deleteCampaign(3)).resolves.toBeNull();
  });

  it("throws the FastAPI `detail` string on an error response", async () => {
    mockFetch(new Response(JSON.stringify({ detail: "campaign not found" }), { status: 404 }));
    await expect(api.getCampaign(9)).rejects.toThrow("campaign not found");
  });

  it("falls back to the status when the error body has no usable detail", async () => {
    mockFetch(new Response("not json", { status: 500 }));
    await expect(api.health()).rejects.toThrow("500");
  });

  it("POSTs JSON with the content-type header and the exact body (createCampaign)", async () => {
    const spy = mockFetch(new Response(JSON.stringify({ id: 1, name: "X" }), { status: 200 }));
    await api.createCampaign("X", "a description");
    expect(spy).toHaveBeenCalledWith("/api/campaigns", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "X", description: "a description" }),
    });
  });

  it("builds pure deliverable/explorer/report URLs without touching the network", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    expect(api.explorerUrl(7)).toBe("/api/snapshots/7/explorer");
    expect(api.deliverableUrl(7, "runbook")).toBe("/api/snapshots/7/deliverable/runbook");
    expect(api.executionReportUrl(42)).toBe("/api/executions/42/report");
    expect(spy).not.toHaveBeenCalled(); // pure string builders, no fetch
  });
});

// ── FE-11: the error object carries the STATUS, and a FastAPI validation body is humanised ──
// The hardened backend answers 403 / 409 / 413 / 422 / 503+Retry-After where it previously did not.
// `new Error(detail)` collapsed every one of those into an opaque string, so nothing downstream
// could tell a transient generation-cap shed from a permanent 404, and a per-field length-cap
// rejection (FastAPI's `detail` is a LIST there, not a string) reached the toast as raw JSON.
describe("ApiError (status-aware failures)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("carries the HTTP status, and marks a 503 generation-cap shed retryable with its Retry-After", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "AssessHub is generating too many deliverables at once — please retry shortly." }),
        { status: 503, headers: { "Retry-After": "5" } },
      ),
    );
    const err = await api.getCampaign(1).then(() => null, (e) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect(err!.status).toBe(503);
    expect(err!.retryAfter).toBe(5);
    expect(err!.retryable).toBe(true);
    expect(err!.message).toContain("too many deliverables");
  });

  it("a 403 cross-site refusal is NOT retryable and keeps its own status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Cross-site state-changing request refused" }), { status: 403 }),
    );
    const err = await api.getCampaign(1).then(() => null, (e) => e as ApiError);
    expect(err!.status).toBe(403);
    expect(err!.retryable).toBe(false);
    expect(err!.retryAfter).toBeNull();
  });

  it("humanises FastAPI's 422 validation LIST into field: message, never raw JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [
            { type: "string_too_long", loc: ["body", "note"], msg: "String should have at most 2000 characters" },
            { type: "string_too_long", loc: ["body", "operator"], msg: "String should have at most 200 characters" },
          ],
        }),
        { status: 422 },
      ),
    );
    const err = await api.getCampaign(1).then(() => null, (e) => e as ApiError);
    expect(err!.status).toBe(422);
    expect(err!.message).toBe(
      "note: String should have at most 2000 characters; operator: String should have at most 200 characters",
    );
    expect(err!.message).not.toContain("{");   // no JSON blob in the war-room toast
  });

  it("a 413 body-ceiling refusal still reports its plain detail string unchanged", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Request body exceeds the 1024 KB limit for this endpoint" }), { status: 413 }),
    );
    const err = await api.getCampaign(1).then(() => null, (e) => e as ApiError);
    expect(err!.status).toBe(413);
    expect(err!.message).toBe("Request body exceeds the 1024 KB limit for this endpoint");
  });
});
