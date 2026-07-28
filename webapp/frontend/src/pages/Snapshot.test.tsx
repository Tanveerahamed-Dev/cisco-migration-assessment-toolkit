import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import SnapshotPage from "./Snapshot";

// Integration test of the snapshot cockpit: it renders the KPI hero from the summary, and it PINS the
// two shipped regressions the page's comments call out — WEBAP-02 + audit-5 FH#22: an un-assessed
// fleet (engine emitted avg_health "") must read as UNKNOWN ("—", neutral tone), never a fake green 0.
// Only meta + graph are mocked with real shapes; the other panels 404 → their own ErrorBox, so the
// page renders. jsdom-safe: the 3D fabric is lazy and never toggled here.
const summary = (avg: number | string) => ({
  avg_health: avg, n_critical: 3, n_switches: 40, version: "V3.23.0",
  punchlist: { crit_high: 5, total: 20, by_severity: { High: 3 }, by_category: { Security: 4 } },
  readiness: { READY: 30, CAUTION: 8, "NOT READY": 2 },
  bands: { Good: 25, Critical: 3 },
  sections: [{ key: "overview", label: "Overview" }, { key: "punchlist", label: "Punch list" }],
  lifecycle: { past_eos: 2 },
});
const meta = (avg: number | string) => ({
  campaign_id: 1, label: "Demo Fleet", n_devices: 50, script_version: "V3.23.0",
  uploaded_at: "2026-06-13T06:32:00Z", summary: summary(avg),
});

function mockFetch(m: unknown) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (/\/api\/snapshots\/\d+\/graph\b/.test(url)) return new Response(JSON.stringify({ nodes: [], edges: [] }), { status: 200 });
    if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return new Response(JSON.stringify(m), { status: 200 });
    return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 }); // unrelated panels → ErrorBox
  });
}

const renderSnap = () =>
  render(
    <MemoryRouter initialEntries={["/snapshots/1"]}>
      <Routes>
        <Route path="/snapshots/:id" element={<SnapshotPage />} />
      </Routes>
    </MemoryRouter>,
  );

describe("Snapshot cockpit", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the snapshot header and the KPI hero from the summary", async () => {
    mockFetch(meta(72));
    renderSnap();
    expect(await screen.findByRole("heading", { name: "Demo Fleet" })).toBeInTheDocument();
    expect(screen.getByText("Critical-band switches")).toBeInTheDocument();
    expect(screen.getByText("Move-group readiness")).toBeInTheDocument();
  });

  it("WEBAP-02 / FH#22: an un-assessed fleet (avg_health '') reads UNKNOWN, not a fake green 0", async () => {
    mockFetch(meta(""));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    // the health gauge shows the em-dash unknown state, never a measured-looking 0
    const gauge = screen.getByText("avg health").closest(".gauge");
    expect(gauge?.textContent).toContain("—");
    // and the critical KPI card is tone-NEUTRAL, so "0 critical" doesn't read as a verified-clean fleet
    const card = screen.getByText("Critical-band switches").closest(".kpi");
    expect(card?.className).not.toMatch(/\b(ok|crit|watch)\b/);
  });

  it("surfaces a load error for a missing snapshot instead of a blank page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "snapshot not found" }), { status: 404 }),
    );
    renderSnap();
    expect(await screen.findByText("snapshot not found")).toBeInTheDocument();
  });

  // Unit 11: the detail-section tab bar is a real ARIA tablist (house pattern from DesignBlueprint's
  // tab bar), not plain buttons — clicking a tab flips aria-selected and the tabpanel's aria-labelledby.
  it("Unit 11: detail-section tabs are real ARIA tabs, and clicking one flips aria-selected + the tabpanel label", async () => {
    mockFetch(meta(72));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    expect(screen.getByRole("tablist", { name: /detail sections/i })).toBeInTheDocument();
    const overview = screen.getByRole("tab", { name: /Overview/ });
    const punchlist = screen.getByRole("tab", { name: /Punch list/ });
    expect(overview).toHaveAttribute("aria-selected", "true");
    expect(punchlist).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tabpanel", { name: /Overview/ })).toHaveAttribute("aria-labelledby", overview.id);

    fireEvent.click(punchlist);

    expect(punchlist).toHaveAttribute("aria-selected", "true");
    expect(overview).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tabpanel", { name: /Punch list/ })).toHaveAttribute("aria-labelledby", punchlist.id);
  });

  // Unit 10: a data-gated panel with nothing to show renders a designed empty state (a real .panel
  // with a message) instead of silently vanishing — here Keystones, since the fixture has no
  // summary.keystones at all.
  it("Unit 10: an empty section renders a designed empty state instead of vanishing (return null)", async () => {
    mockFetch(meta(72));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    expect(await screen.findByText(/No keystone devices flagged/)).toBeInTheDocument();
  });

  // Unit 12: the explorer toggle announces its expanded/collapsed state non-visually.
  it("Unit 12: the explorer toggle announces aria-expanded", async () => {
    mockFetch(meta(72));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    const toggle = screen.getByRole("button", { name: /open explorer/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);

    expect(await screen.findByRole("button", { name: /hide explorer/i })).toHaveAttribute("aria-expanded", "true");
  });
});

// ── coverage-honesty audit (FE-1 / FE-2 / FE-3 / FE-4) ────────────────────────
// CLAUDE.md guardrail 3: "not observed" must NEVER silently become "healthy". These pin the four
// places on this page where it did — three of them by rendering a positive claim about the SNAPSHOT
// or the SERVER out of a state that was really "we do not know yet" or "the request failed".
describe("Snapshot cockpit · coverage honesty", () => {
  afterEach(() => vi.restoreAllMocks());

  const richSummary = {
    avg_health: 72, n_critical: 3, n_switches: 40, version: "V3.23.0",
    punchlist: { crit_high: 5, total: 20, by_severity: { High: 3 }, by_category: { Security: 4 } },
    readiness: { READY: 30, CAUTION: 8, "NOT READY": 2 },
    bands: { Good: 25, Critical: 3 },
    sections: [{ key: "health_scores", label: "Health scores", count: 303 }],
    lifecycle: { past_eos: 2 }, keystones: [],
  };
  const richMeta = {
    id: 1, campaign_id: 1, label: "Demo Fleet", n_devices: 303, script_version: "V3.23.0",
    uploaded_at: "2026-06-13T06:32:00Z", summary: richSummary,
  };

  function dossiers(bands: Record<string, number>, per_device: any[]) {
    return { section: "device_dossiers", data: { note: "", summary: { bands }, per_device } };
  }
  const dev = (host: string, risk_band: string) =>
    ({ host, risk_band, risk_index: 50, impact_score: 5, exposure_score: 5, verdict: "v", compound: [] });

  // FE-1: the risk chip was a mutually-exclusive ternary chain, so the Unassessed (no-evidence)
  // count only ever reached the header when Severe AND Elevated were both zero — the coverage gap
  // was hidden by exactly the finding that makes it matter.
  it("FE-1: un-assessed devices are disclosed even when Severe devices exist", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "meta").mockRejectedValue(new Error("no meta"));
    vi.spyOn(api, "section").mockResolvedValue(
      dossiers({ Severe: 3, Unassessed: 40, Low: 260 },
        [dev("sw-a", "Severe"), dev("sw-b", "Severe"), dev("blind-1", "Unassessed")]) as any,
    );
    renderSnap();
    const panel = await waitFor(() => {
      const p = screen.getByText(/Device Risk Register/).closest(".panel")!;
      if (!p.querySelector("tbody tr")) throw new Error("register not loaded");
      return p;
    });
    // the 40 blind devices are named — they are excluded from the RANKING, never from the page
    expect(panel.textContent).toContain("40");
    expect(panel.textContent).toMatch(/not assessed/i);
    expect(panel.textContent).toMatch(/never a clean bill of health/i);
  });

  // FE-2: the fetch carried its own `.catch(() => null)`, so a 403/500/503 landed on the benign
  // "older snapshots didn't compute it" empty state — a claim about the snapshot manufactured from
  // a server fault, on the one panel that surfaces blind devices.
  it("FE-2: a failed risk-register load reads as an error, not as 'this snapshot has none'", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "meta").mockRejectedValue(new Error("no meta"));
    vi.spyOn(api, "section").mockRejectedValue(new Error("dossier recompute exploded"));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    // scoped to the register panel — the section tab renders its own ErrorBox for the same rejection
    const panel = await waitFor(() => {
      const p = screen.getByText(/Device Risk Register/).closest(".panel")!;
      if (!p.textContent?.includes("dossier recompute exploded")) throw new Error("not surfaced yet");
      return p;
    });
    expect(panel.textContent).toMatch(/Something went wrong/);
    expect(panel.textContent).toMatch(/still un-assessed/);
    expect(screen.queryByText(/older snapshots didn't compute it/)).toBeNull();
  });

  // FE-2/FE-3: the same false claims used to render for the WHOLE duration of the fetch, because
  // neither panel read `loading`.
  it("FE-2/FE-3: while loading, neither panel asserts an absence it has not established", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "section").mockReturnValue(new Promise(() => {}) as any);  // never settles
    vi.spyOn(api, "meta").mockReturnValue(new Promise(() => {}) as any);
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    expect(screen.queryByText(/older snapshots didn't compute it/)).toBeNull();
    expect(screen.queryByText(/No deliverables are available from this server build/)).toBeNull();
  });

  // FE-3: a failed /api/meta is a fact about the request, not about the server's document family.
  it("FE-3: a failed deliverable catalogue does not read as 'this build has no deliverables'", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "section").mockRejectedValue(new Error("x"));
    vi.spyOn(api, "meta").mockRejectedValue(new Error("meta 503 shed"));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    expect(await screen.findByText("meta 503 shed")).toBeInTheDocument();
    expect(screen.queryByText(/No deliverables are available from this server build/)).toBeNull();
  });

  // FE-12: summarize() seeds readiness as {READY:0, CAUTION:0, "NOT READY":0} and only ever
  // INCREMENTS it from snap["migration_readiness"] (webapp/backend/summary.py). A snapshot that
  // carries no migration_readiness section therefore yields all-zeros — indistinguishable, in the
  // payload, from a fleet whose groups were all assessed and none came back NOT READY. The tile
  // painted that as the green `ok` tone with "0✓ 0! 0✕", i.e. a positive readiness verdict derived
  // from nothing being classified. The CutoverPlanner on the SAME page says "No migration waves
  // were derived from this snapshot" for the same input.
  it("FE-12: an unclassified move-group set reads as NOT ASSESSED, not as a green all-ready", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue({
      ...richMeta,
      summary: { ...richSummary, readiness: { READY: 0, CAUTION: 0, "NOT READY": 0 } },
    } as any);
    vi.spyOn(api, "meta").mockRejectedValue(new Error("x"));
    vi.spyOn(api, "section").mockRejectedValue(new Error("x"));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    const card = screen.getByText("Move-group readiness").closest(".kpi")!;
    // the fleet IS health-assessed (avg 72), so the page-wide `unknownFleet` neutraliser is OFF —
    // this tile has to make the distinction on its own evidence
    expect(card.className).not.toMatch(/\b(ok|crit|watch)\b/);
    expect(card.textContent).toMatch(/not assessed|NOT OBSERVED/i);
    // and it must not display a counted-looking zero triple
    expect(card.textContent).not.toMatch(/0✓/);
  });

  it("FE-12: a genuinely classified move-group set still reads as measured (the fix must not cry wolf)", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);   // 30 / 8 / 2
    vi.spyOn(api, "meta").mockRejectedValue(new Error("x"));
    vi.spyOn(api, "section").mockRejectedValue(new Error("x"));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    const card = screen.getByText("Move-group readiness").closest(".kpi")!;
    expect(card.className).toMatch(/\bcrit\b/);        // 2 NOT READY dominates
    expect(card.textContent).toContain("30✓");
    expect(card.textContent).not.toMatch(/not assessed/i);
  });

  // FE-4: the section table caps at 200 rows / 8 columns while the tab badge keeps announcing the
  // engine's FULL count — on the 303-device fleet, 103 devices were simply not there for a reader
  // who scrolled to the last row.
  it("FE-4: a row/column-capped section table discloses the cap instead of ending silently", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "meta").mockRejectedValue(new Error("x"));
    const rows = Array.from({ length: 303 }, (_, i) => ({
      host: `sw-${i}`, band: "Good", score: 90, a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, dropped: "x",
    }));
    vi.spyOn(api, "section").mockImplementation(async (_id: number, name: string) => {
      if (name === "device_dossiers") throw new Error("no dossiers");
      return { section: name, data: rows } as any;
    });
    const { container } = renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    const big = await waitFor(() => {
      const t = Array.from(container.querySelectorAll("table.tbl")).find((x) => x.querySelectorAll("tbody tr").length > 50);
      if (!t) throw new Error("section table not rendered");
      return t;
    });
    expect(big.querySelectorAll("tbody tr").length).toBe(200);   // the cap itself is unchanged
    const note = big.closest("div")!.parentElement!.textContent || "";
    expect(note).toMatch(/first 200 of 303 rows/);
    expect(note).toMatch(/8 of 10 columns/);
    expect(note).toMatch(/NOT absent/);
  });
});
