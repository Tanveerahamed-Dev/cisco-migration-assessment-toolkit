import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CutoverPlanner from "./CutoverPlanner";
import { api } from "../api";

// CutoverPlanner reaches three api methods on a populated render (cutover + meta + listExecutions),
// and its ExecutionRuns child uses useNavigate/Link — so it must be wrapped in a router.
const cutover = {
  summary: {
    verdict: "CONDITIONAL GO",
    statement: "Pilot-first cutover: one zero-outage wave proves the method before hard cuts.",
    n_waves: 1, n_devices: 3, n_make_before_break: 1, n_hard_cutover: 0,
    hard_cutover_endpoints: 0, est_window_minutes: 0, est_window_label: "0 min",
    gates: { "CONDITIONAL GO": 1 },
  },
  waves: [{
    group: "Access-Pilot", order: 1, gate: "GO", strategy: "make-before-break",
    readiness: "READY", n_switches: 3, endpoints: 120,
    est_window_minutes: 0, est_window_label: "0 min",
    make_before_break: [], hard_cutover: [], blast_radius: null, keystones: [],
    blockers: [], critical_crosslayer: [], run_of_show: [], validation: [], remediation: [],
  }],
};

function renderPlanner() {
  return render(
    <MemoryRouter>
      <CutoverPlanner snapId={1} />
    </MemoryRouter>,
  );
}

describe("CutoverPlanner (render)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the loading state while the plan builds", () => {
    vi.spyOn(api, "cutover").mockReturnValue(new Promise(() => {}) as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    expect(screen.getByText(/Building cutover plan/i)).toBeInTheDocument();
  });

  it("surfaces a load error from the primary cutover fetch", async () => {
    vi.spyOn(api, "cutover").mockRejectedValue(new Error("cutover 1 failed"));
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    expect(await screen.findByText("cutover 1 failed")).toBeInTheDocument();
  });

  it("renders the run-of-show once the plan loads", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    expect(await screen.findByText("Cutover plan · run-of-show")).toBeInTheDocument();
    // the populated wave rendered its stat labels
    expect(screen.getByText("est. total window")).toBeInTheDocument();
  });

  it("flips aria-expanded on the wave's run-of-show toggle as it opens/closes", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    await screen.findByText("Cutover plan · run-of-show");
    const toggle = screen.getByRole("button", { name: /Run-of-show/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
