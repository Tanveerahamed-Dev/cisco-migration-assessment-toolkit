import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import ExecutionPage, { fmtClock, OUTCOME_COLOR } from "./Execution";
import { api } from "../api";
import type { ExecutionState, SnapshotMeta } from "../api";

// ── pure helpers ──────────────────────────────────────────────────────────
// The war-room elapsed clock: seconds → H:MM:SS, recomputed from started_at each tick.
describe("fmtClock", () => {
  it("formats sub-minute durations with zero hours and padded seconds", () => {
    expect(fmtClock(0)).toBe("0:00:00");
    expect(fmtClock(5)).toBe("0:00:05");
    expect(fmtClock(59)).toBe("0:00:59");
  });

  it("rolls seconds→minutes→hours, zero-padding minutes and seconds to two digits", () => {
    expect(fmtClock(60)).toBe("0:01:00");
    expect(fmtClock(65)).toBe("0:01:05");
    expect(fmtClock(3599)).toBe("0:59:59");
    expect(fmtClock(3600)).toBe("1:00:00");
    expect(fmtClock(3723)).toBe("1:02:03");
  });

  it("does NOT pad the hours field — a long cutover can run past 9:59:59", () => {
    expect(fmtClock(36000)).toBe("10:00:00");
    expect(fmtClock(3600 * 25 + 61)).toBe("25:01:01");
  });
});

// Outcome badge colour — a rolled-back / aborted run must never read as a green success.
describe("OUTCOME_COLOR", () => {
  it("greens a clean cutover", () => {
    expect(OUTCOME_COLOR("SUCCESSFUL")).toBe("var(--ok)");
  });

  it("reds the failure outcomes", () => {
    expect(OUTCOME_COLOR("ROLLED BACK")).toBe("var(--crit)");
    expect(OUTCOME_COLOR("ABORTED")).toBe("var(--crit)");
  });

  it("ambers partial / unknown outcomes — coverage-honest, never a false green", () => {
    expect(OUTCOME_COLOR("PARTIALLY IMPLEMENTED")).toBe("var(--watch)");
    expect(OUTCOME_COLOR("")).toBe("var(--watch)");
    expect(OUTCOME_COLOR("SOMETHING NEW")).toBe("var(--watch)");
  });
});

// ── page integration ──────────────────────────────────────────────────────
function execState(over: Partial<ExecutionState> = {}): ExecutionState {
  return {
    id: 1,
    snapshot_id: 7,
    label: "Cutover Run A",
    operator: "",
    status: "in_progress",
    outcome: null,
    started_at: "2026-01-01T10:00:00Z",
    ended_at: null,
    plan_summary: {} as ExecutionState["plan_summary"],
    waves: [
      {
        group: "Core-fabric",
        order: 1,
        gate: "GO",
        strategy: "phased",
        n_switches: 2,
        switches: [],
        endpoints: 0,
        hard_cutover_endpoints: 0,
        est_window_minutes: 30,
        est_window_label: "30m",
        blockers: [],
        steps: [],
        checks: [],
        closeout: { decision: null, at: null, by: "", note: "" },
      },
    ],
    events: [],
    progress: {
      n_steps: 4,
      n_steps_done: 1,
      n_steps_skipped: 0,
      pct: 25,
      checks: { pending: 0, pass: 2, fail: 0, na: 0 },
      n_deviations: 0,
      elapsed_seconds: 0,
      planned_window_minutes: 30,
      waves: [{ group: "Core-fabric", state: "active", n_steps: 4, n_actioned: 1 }],
    },
    ...over,
  };
}

const snapMeta: SnapshotMeta = {
  id: 7,
  campaign_id: 3,
  label: "Baseline",
  uploaded_at: "2026-01-01T00:00:00Z",
  script_version: "3.30.0",
  n_devices: 10,
  summary: {} as SnapshotMeta["summary"],
};

function renderExec() {
  return render(
    <MemoryRouter initialEntries={["/executions/1"]}>
      <Routes>
        <Route path="/executions/:id" element={<ExecutionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ExecutionPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the war-room loading state while the run loads", () => {
    vi.spyOn(api, "getExecution").mockReturnValue(new Promise<ExecutionState>(() => {}));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();
    expect(screen.getByText(/Opening the war room/i)).toBeInTheDocument();
  });

  it("surfaces a load error instead of a blank console", async () => {
    vi.spyOn(api, "getExecution").mockRejectedValue(new Error("run 1 not found"));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();
    expect(await screen.findByText("run 1 not found")).toBeInTheDocument();
  });

  it("renders a live run: LIVE badge, waves, progress, and the operator input", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(execState());
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByText("Cutover Run A")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("Core-fabric")).toBeInTheDocument();
    // server-derived progress line (the pct itself is an animated CountUp, so assert the stable text)
    expect(screen.getByText(/1 of 4 steps done/)).toBeInTheDocument();
    // a live run is signable — the operator field and Finish control are present
    expect(screen.getByPlaceholderText(/Operator/i)).toBeInTheDocument();
    expect(screen.getByText(/Finish run/i)).toBeInTheDocument();
  });

  it("renders a finished run read-only: outcome badge, no operator field or Finish control", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(
      execState({ status: "completed", outcome: "ROLLED BACK", ended_at: "2026-01-01T12:00:00Z" }),
    );
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByText("ROLLED BACK")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("LIVE")).not.toBeInTheDocument());
    expect(screen.queryByPlaceholderText(/Operator/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Finish run/i)).not.toBeInTheDocument();
  });

  // Validation-checks accordion: showChecks starts true, so the toggle's aria-expanded must start
  // true and flip with every click — a screen reader user relies on this, not just the glyph swap.
  it("flips the validation-checks accordion's aria-expanded with its open state", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(
      execState({
        waves: [
          {
            group: "Core-fabric", order: 1, gate: "GO", strategy: "phased",
            n_switches: 2, switches: [], endpoints: 0, hard_cutover_endpoints: 0,
            est_window_minutes: 30, est_window_label: "30m", blockers: [],
            steps: [],
            checks: [
              {
                category: "l2", severity: "High", check: "VLAN present", command: "show vlan brief",
                expect: "vlan 10 up", result: "pending", observed: "", at: null, by: "",
              },
            ],
            closeout: { decision: null, at: null, by: "", note: "" },
          },
        ],
      }),
    );
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    const toggle = await screen.findByRole("button", { name: /Validation checks/i });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  // Live log empty state: with zero events the log used to render nothing at all — an honest
  // placeholder replaces that silent blank (companion test below confirms it steps aside once
  // entries exist).
  it("shows an honest placeholder in the live log at zero events", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(execState({ events: [] }));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByText(/No entries yet/i)).toBeInTheDocument();
  });

  it("renders logged entries instead of the empty placeholder once events exist", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(
      execState({
        events: [{ at: "2026-01-01T10:05:00Z", kind: "step", wave: "Core-fabric", text: "did a thing", by: "operator" }],
      }),
    );
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByText("did a thing")).toBeInTheDocument();
    expect(screen.queryByText(/No entries yet/i)).not.toBeInTheDocument();
  });
});

// ── FE-10: the finish-confirm must not disagree with the backend's own outcome derivation ──
// webapp/backend/execution.py :: _derive_outcome is
//   `if not decisions or any(d != "COMPLETE" for d in decisions): return OUTCOME_PARTIAL`
// so a wave closed out DEFERRED forces PARTIALLY IMPLEMENTED — while the page's `open` counter
// (waves with NO decision) reads 0 and used to show the unconditional "the outcome is derived for
// the PIR" wording, i.e. no warning at all before an irreversible, signed sign-off.
describe("ExecutionPage · finish-confirm matches the backend outcome derivation", () => {
  afterEach(() => vi.restoreAllMocks());

  function closedAs(decision: string) {
    const st = execState();
    st.waves[0].closeout = { decision, at: "2026-01-01T11:00:00Z", by: "eng", note: "" };
    return st;
  }

  it("FE-10: a DEFERRED-closed wave warns that finishing derives PARTIALLY IMPLEMENTED", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(closedAs("DEFERRED"));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderExec();
    fireEvent.click(await screen.findByRole("button", { name: /Finish run/i }));
    expect(confirm).toHaveBeenCalledTimes(1);
    const msg = confirm.mock.calls[0][0] as string;
    expect(msg).toMatch(/other than COMPLETE/);
    expect(msg).toContain("PARTIALLY IMPLEMENTED");
  });

  it("FE-10: a ROLLED BACK wave predicts ROLLED BACK, matching _derive_outcome's precedence", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(closedAs("ROLLED BACK"));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderExec();
    fireEvent.click(await screen.findByRole("button", { name: /Finish run/i }));
    expect(confirm.mock.calls[0][0] as string).toContain("ROLLED BACK");
  });

  it("FE-10: an all-COMPLETE run keeps the plain confirm — the fix must not cry wolf", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(closedAs("COMPLETE"));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderExec();
    fireEvent.click(await screen.findByRole("button", { name: /Finish run/i }));
    const msg = confirm.mock.calls[0][0] as string;
    expect(msg).toMatch(/becomes read-only/);
    expect(msg).not.toMatch(/PARTIALLY IMPLEMENTED/);
  });
});
