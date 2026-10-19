import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../savedPlanApi";
import type { Meta, SavedPlanState } from "../savedPlanApi";
import SavedPlanPage from "./SavedPlan";

// A different runtime owner domain detects copied client vocabulary or range policy.
const source: SavedPlanState = {
  assessment: { source: "persisted snapshots.snapshot_json blob", sha256: `sha256:${"a".repeat(64)}`,
    bytes: 100, snapshot_id: 1, campaign_id: 7, engagement_id: "EXAMPLE", label: "EXAMPLE", script_version: "3.23.0" },
  selection_id: 0, selected_revision: null, revisions: [],
};

beforeEach(() => {
  vi.spyOn(api, "savedPlans").mockResolvedValue(source);
  vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [], display_limits: { revision_maximum: 64, label_maximum_code_points: 200 },
    requirementsContract: { availability_tiers: ["platinum", "standard"], fabric_models: ["example-fabric"],
      vlan_id: { minimum: 7, maximum: 12 }, convergence_budget_ms: { minimum: 0, maximum: 9007199254740991 } } } satisfies Meta);
  vi.spyOn(api, "savePlan").mockImplementation(() => new Promise<never>(() => {}));
});
afterEach(() => vi.restoreAllMocks());

async function show() {
  render(<MemoryRouter initialEntries={["/snapshots/1/plans"]}>
    <Routes><Route path="/snapshots/:id/plans" element={<SavedPlanPage />} /></Routes>
  </MemoryRouter>);
  await screen.findByText("No saved plan revisions yet.");
  fireEvent.change(screen.getByLabelText("Plan name"), { target: { value: "EXAMPLE owner domain" } });
}

describe("runtime requirements owner contract", () => {
  it("offers the runtime tier/fabric domains and sends the selected tier without a copied allow-list", async () => {
    await show();
    const tiers = screen.getByLabelText("Availability tier") as HTMLSelectElement;
    expect(Array.from(tiers.options, (option) => option.value)).toEqual(["", "platinum", "standard"]);
    const fabrics = screen.getByLabelText("Fabric operating model") as HTMLSelectElement;
    expect(Array.from(fabrics.options, (option) => option.value)).toEqual(["", "example-fabric"]);
    fireEvent.change(tiers, { target: { value: "platinum" } });
    fireEvent.change(screen.getByLabelText("Convergence budget (ms)"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    await waitFor(() => expect(api.savePlan).toHaveBeenCalledWith(1, expect.objectContaining({
      requirements: { availability_tier: "platinum", convergence_budget_ms: "0" },
    }), expect.any(AbortSignal)));
  });

  it.each(["6=EXAMPLE", "13=EXAMPLE"])("sends VLAN %s to its owner and displays the refusal", async (zones) => {
    vi.mocked(api.savePlan).mockRejectedValueOnce(new ApiError("VLAN requirements were not admitted", 400));
    await show();
    fireEvent.click(screen.getByText("Advanced: VLAN zones"));
    fireEvent.change(screen.getByLabelText("VLAN zones — one assignment per line"), { target: { value: zones } });
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("VLAN requirements were not admitted");
    expect(api.savePlan).toHaveBeenCalledWith(1, expect.objectContaining({ requirements: { vlan_zones: { raw_rows: [{ vids: zones.split("=")[0], zone: "EXAMPLE" }] } } }), expect.any(AbortSignal));
  });

  it("accepts both runtime VLAN bounds without coercing zone identity", async () => {
    await show();
    fireEvent.click(screen.getByText("Advanced: VLAN zones"));
    fireEvent.change(screen.getByLabelText("VLAN zones — one assignment per line"), {
      target: { value: "7=EXAMPLE low\n12=EXAMPLE high" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    await waitFor(() => expect(api.savePlan).toHaveBeenCalledWith(1, expect.objectContaining({
      requirements: { vlan_zones: { raw_rows: [{ zone: "EXAMPLE low", vids: "7" }, { zone: "EXAMPLE high", vids: "12" }] } },
    }), expect.any(AbortSignal)));
  });
});
