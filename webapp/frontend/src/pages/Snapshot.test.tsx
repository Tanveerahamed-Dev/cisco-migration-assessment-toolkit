import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
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
  sections: [{ key: "overview", label: "Overview" }],
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
});
