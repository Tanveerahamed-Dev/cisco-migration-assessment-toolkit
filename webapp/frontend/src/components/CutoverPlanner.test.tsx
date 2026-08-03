import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router";
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

  // FE-14: ExecutionRuns destructured useAsync for `data` + `reload` only, so a failed
  // GET /api/snapshots/{id}/executions (403 from the cross-site guard, 404 "Snapshot not found",
  // a dropped connection) left `runs === null` and the chip list simply did not render. The
  // engineer sees a bare "Start execution run" button and concludes no run exists for this
  // snapshot — then opens a SECOND war room over a cutover another operator already has live.
  it("FE-14: a failed run list says so instead of looking like 'no runs exist'", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockRejectedValue(new Error("403 cross-site refused"));
    renderPlanner();
    await screen.findByText("Cutover plan · run-of-show");

    expect(await screen.findByText(/403 cross-site refused/)).toBeInTheDocument();
    expect(screen.getByText(/not evidence that no run is open/i)).toBeInTheDocument();
  });

  it("FE-14: a successful empty run list stays quiet — the fix must not cry wolf", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    await screen.findByText("Cutover plan · run-of-show");

    expect(screen.queryByText(/not evidence that no run is open/i)).toBeNull();
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
