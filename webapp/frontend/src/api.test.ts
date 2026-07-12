import { afterEach, describe, expect, it, vi } from "vitest";
import { api, bandColor, gateColor, readyColor, sevColor, sevSoft } from "./api";

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

// The `api` client is the app's whole data layer; the shared `j` response handler is where every
// call's success/error semantics live (FastAPI `detail` extraction, 204 -> null, status fallback).
// Tested through the client with a mocked global fetch — no network, no backend.
describe("api client (request construction + the j response handler)", () => {
  afterEach(() => vi.restoreAllMocks());

  function mockFetch(resp: Response) {
    return vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
  }

  it("GETs the right URL and parses the JSON body on success", async () => {
    const spy = mockFetch(new Response(JSON.stringify([{ id: 1, name: "AJ" }]), { status: 200 }));
    await expect(api.listCampaigns()).resolves.toEqual([{ id: 1, name: "AJ" }]);
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
