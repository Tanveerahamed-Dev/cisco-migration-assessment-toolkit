import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import CampaignPage, { NEXT_DECISION, VERDICT_COLOR } from "./Campaign";
import { api } from "../api";
import type { Campaign, SnapshotMeta, GateBoardData } from "../api";

// ── pure maps ─────────────────────────────────────────────────────────────
// The gate cell cycles pending → GO → NO-GO → SLIPPED → pending (a closed 4-state ring).
describe("NEXT_DECISION", () => {
  it("advances each state to the next in the ring", () => {
    expect(NEXT_DECISION.pending).toBe("go");
    expect(NEXT_DECISION.go).toBe("no-go");
    expect(NEXT_DECISION["no-go"]).toBe("slipped");
    expect(NEXT_DECISION.slipped).toBe("pending");
  });

  it("closes the ring — four cycles from pending return to pending", () => {
    let d = "pending";
    for (let i = 0; i < 4; i++) d = NEXT_DECISION[d];
    expect(d).toBe("pending");
  });
});

describe("VERDICT_COLOR", () => {
  it("colours the snapshot-delta verdicts (audit-5 CA#5 — these keys once fell through to a flat chip)", () => {
    for (const k of ["CLEAN", "REVIEW", "REGRESSED"]) {
      expect(VERDICT_COLOR[k], `${k} must be coloured`).toBeTruthy();
    }
    // distinct semantics, not a single fallback colour
    expect(VERDICT_COLOR.CLEAN).toBe("var(--ok)");
    expect(VERDICT_COLOR.REGRESSED).toBe("var(--crit)");
    expect(VERDICT_COLOR.REVIEW).toBe("var(--watch)");
  });

  it("also colours the campaign-trend verdicts", () => {
    for (const k of ["IMPROVING", "REGRESSING", "MIXED", "FLAT", "INSUFFICIENT"]) {
      expect(VERDICT_COLOR[k], `${k} must be coloured`).toBeTruthy();
    }
    expect(VERDICT_COLOR.IMPROVING).toBe("var(--ok)");
    expect(VERDICT_COLOR.REGRESSING).toBe("var(--crit)");
  });
});

// ── page integration ──────────────────────────────────────────────────────
function campaign(over: Partial<Campaign> = {}): Campaign {
  return {
    id: 3,
    name: "DC East Migration",
    description: "east fabric refresh",
    created_at: "2026-01-01T00:00:00Z",
    snapshots: [],
    ...over,
  };
}

function snap(id: number): SnapshotMeta {
  return {
    id,
    campaign_id: 3,
    label: `Wave ${id}`,
    uploaded_at: "2026-01-01T00:00:00Z",
    script_version: "3.30.0",
    n_devices: 10,
    summary: { bands: { critical: 1, watch: 2, healthy: 7 } } as SnapshotMeta["summary"],
  };
}

const emptyGates: GateBoardData = { cadence: [], waves: [], records: [] };

function renderCampaign() {
  return render(
    <MemoryRouter initialEntries={["/campaigns/3"]}>
      <Routes>
        <Route path="/campaigns/:id" element={<CampaignPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CampaignPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows a loading state while the campaign loads", () => {
    vi.spyOn(api, "getCampaign").mockReturnValue(new Promise<Campaign>(() => {}));
    const { container } = renderCampaign();
    expect(container.querySelector(".spinner, .loading")).toBeTruthy();
  });

  it("surfaces a load error", async () => {
    vi.spyOn(api, "getCampaign").mockRejectedValue(new Error("campaign 3 not found"));
    renderCampaign();
    expect(await screen.findByText("campaign 3 not found")).toBeInTheDocument();
  });

  it("renders the empty state and hides Trend/Compare with fewer than two waves", async () => {
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaign({ snapshots: [] }));
    vi.spyOn(api, "getGates").mockResolvedValue(emptyGates);
    const trend = vi.spyOn(api, "trend");
    renderCampaign();

    expect(await screen.findByText("DC East Migration")).toBeInTheDocument();
    expect(screen.getByText(/No snapshots yet/i)).toBeInTheDocument();
    expect(screen.getByText("Waves (0)")).toBeInTheDocument();
    // trend + compare panels are gated on ≥2 snapshots
    expect(screen.queryByText("Campaign trajectory")).not.toBeInTheDocument();
    expect(screen.queryByText("Compare two waves")).not.toBeInTheDocument();
    expect(trend).not.toHaveBeenCalled();
  });

  it("lists the waves and shows the Trend panel once there are two", async () => {
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaign({ snapshots: [snap(1), snap(2)] }));
    vi.spyOn(api, "getGates").mockResolvedValue(emptyGates);
    vi.spyOn(api, "trend").mockResolvedValue({
      verdict: "IMPROVING",
      verdict_note: "health rising",
      trajectory: [],
    });
    renderCampaign();

    expect(await screen.findByText("Waves (2)")).toBeInTheDocument();
    // the C1/C2 chips uniquely identify the waves list (the labels also appear in the Compare selects)
    expect(screen.getByText("C1")).toBeInTheDocument();
    expect(screen.getByText("C2")).toBeInTheDocument();
    expect(await screen.findByText("Campaign trajectory")).toBeInTheDocument();
    expect(screen.getByText("Compare two waves")).toBeInTheDocument();
  });

  it("surfaces a failed trend fetch as an error panel instead of silently vanishing", async () => {
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaign({ snapshots: [snap(1), snap(2)] }));
    vi.spyOn(api, "getGates").mockResolvedValue(emptyGates);
    vi.spyOn(api, "trend").mockRejectedValue(new Error("trend 3 failed"));
    renderCampaign();

    // the panel keeps its title AND shows the house ErrorBox — the old `!data → null` guard
    // rendered nothing at all on error, forever (the audit's one tracked correctness bug)
    expect(await screen.findByText("Campaign trajectory")).toBeInTheDocument();
    expect(screen.getByText("trend 3 failed")).toBeInTheDocument();
  });

  it("cycles a gate cell pending → GO and records it against the campaign", async () => {
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaign({ snapshots: [snap(1)] }));
    vi.spyOn(api, "getGates").mockResolvedValue({
      cadence: [{ key: "cab", label: "CAB", when: "T-2d" }],
      waves: ["Wave-A"],
      records: [],
    });
    const setGate = vi.spyOn(api, "setGate").mockResolvedValue({
      records: [
        { wave: "Wave-A", gate: "cab", decision: "go", signed_by: "", note: "", decided_at: "2026-01-01T00:00:00Z" },
      ],
    });
    const { container } = renderCampaign();

    const cell = (await waitFor(() => {
      const c = container.querySelector('[data-wave="Wave-A"][data-gate="cab"]');
      if (!c) throw new Error("gate cell not rendered yet");
      return c as HTMLElement;
    }));
    // a pending cell reads as an em-dash
    expect(cell.textContent).toBe("—");
    // the mouse-only `title` is mirrored to `aria-label` for keyboard/AT users
    expect(cell.getAttribute("aria-label")).toBe(cell.getAttribute("title"));

    fireEvent.click(cell);

    // pending → NEXT_DECISION → "go", with empty signer/note carried (nothing typed, no prior record)
    await waitFor(() => expect(setGate).toHaveBeenCalledWith(3, "Wave-A", "cab", "go", "", ""));
    // the POST response is applied optimistically — the cell now reads GO
    await waitFor(() => expect(cell.textContent).toBe("GO"));
    // the label tracks the updated decision too, not just the initial pending state
    expect(cell.getAttribute("aria-label")).toBe(cell.getAttribute("title"));
    expect(cell.getAttribute("aria-label")).toContain("GO");
  });

  it("flags an out-of-order sign-off with a ⚠ badge and disclosing tooltip, and leaves clean cells unmarked", async () => {
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaign({ snapshots: [snap(1)] }));
    vi.spyOn(api, "getGates").mockResolvedValue({
      cadence: [
        { key: "cab", label: "CAB", when: "T-2d" },
        { key: "nrfu", label: "NRFU", when: "T-0" },
      ],
      waves: ["Wave-A"],
      records: [
        // in order: no upstream unmet, no disclosure
        { wave: "Wave-A", gate: "cab", decision: "go", signed_by: "eng", note: "", decided_at: "2026-01-01T00:00:00Z" },
        // out of order: NRFU signed GO before upstream CAB was GO (backend gates.annotate_out_of_order, PR #376)
        { wave: "Wave-A", gate: "nrfu", decision: "go", signed_by: "eng", note: "", decided_at: "2026-01-01T00:00:00Z",
          out_of_order: true, out_of_order_upstream: "cab" },
      ],
    });
    const { container } = renderCampaign();

    const clean = (await waitFor(() => {
      const c = container.querySelector('[data-wave="Wave-A"][data-gate="cab"]');
      if (!c) throw new Error("gate board not rendered yet");
      return c as HTMLElement;
    }));
    const ooo = container.querySelector('[data-wave="Wave-A"][data-gate="nrfu"]') as HTMLElement;

    // the out-of-order cell carries a visible ⚠ marker; the clean one does not
    expect(ooo.textContent).toContain("⚠");
    expect(clean.textContent).not.toContain("⚠");
    expect(clean.querySelector(".gate-ooo")).toBeNull();

    // the disclosure names the first unmet upstream, on both the cell tooltip and the marker's a11y label
    expect(ooo.getAttribute("title")).toContain("Out of order: signed before upstream cab was GO");
    const badge = ooo.querySelector(".gate-ooo");
    expect(badge).toBeTruthy();
    expect(badge?.getAttribute("aria-label")).toBe("Out of order: signed before upstream cab was GO");

    // coverage-honest: disclosing the out-of-order state must not erase the sign-off — it still reads GO
    expect(ooo.textContent).toContain("GO");
    expect(ooo.getAttribute("data-out-of-order")).toBe("true");
  });
});

// ── folder ingest (ADR-0004 P1 — the portable-app channel beside the ZIP card) ──
describe("folder ingest", () => {
  afterEach(() => vi.restoreAllMocks());

  function mountEmptyCampaign() {
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaign({ snapshots: [] }));
    vi.spyOn(api, "getGates").mockResolvedValue(emptyGates);
    return renderCampaign();
  }

  it("renders the folder form beside the ZIP card and runs the engine over the typed path", async () => {
    const ing = vi.spyOn(api, "ingestFolder").mockResolvedValue({
      ...snap(9),
      ingest: { n_device_dirs: 3, engine_seconds: 4.2 },
    } as any);
    mountEmptyCampaign();
    await screen.findByText("DC East Migration");

    // both server-side ingest channels are offered
    expect(screen.getByText(/ingest a raw collection/i)).toBeInTheDocument();
    expect(screen.getByText(/ingest a local folder/i)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/collections\\siteA/i), {
      target: { value: "D:\\field\\siteA" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run engine on folder/i }));

    await waitFor(() => expect(ing).toHaveBeenCalledWith(3, "D:\\field\\siteA", ""));
  });

  it("refuses an empty path with a toast and never calls the API", async () => {
    const ing = vi.spyOn(api, "ingestFolder");
    mountEmptyCampaign();
    await screen.findByText("DC East Migration");

    fireEvent.click(screen.getByRole("button", { name: /run engine on folder/i }));

    expect(await screen.findByText("Enter the server-local folder path first.")).toBeInTheDocument();
    expect(ing).not.toHaveBeenCalled();
  });
});
