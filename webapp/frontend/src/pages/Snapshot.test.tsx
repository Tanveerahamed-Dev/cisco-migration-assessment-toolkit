import { fireEvent, render, screen } from "@testing-library/react";
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
