import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import CausalFlowPanel from "./CausalFlow";
import { api, type CausalFlows } from "../api";

// ── render smoke + reveal-replay/filter regression (mocked api; no router needed) ──
// Covers Unit 20: (1) selecting a different card swaps `cur` and the diagram remounts on
// `cur.key` — asserted via the new flow's FINAL rendered title, never a mid-animation value;
// (2) a severity-filter click remounts the (keyed) card list without corrupting selection.
const causalFlows: CausalFlows = {
  flows: [
    {
      key: "f1", family: "spof", family_label: "SPOF", icon: "◆",
      title: "Core switch is a single point of failure", severity: "Critical", sev_tok: "crit",
      trigger: "No dual-homing", mechanism: "Single core switch carries the whole fabric",
      impact: "Fabric-wide outage on core failure", mitigation: "Add a second core switch",
      hosts: ["CS01"], blast: 40, blast_unit: "devices", shape: "linear", evidence: {},
    },
    {
      key: "f2", family: "spof", family_label: "SPOF", icon: "◆",
      title: "Access switch AS01 has no redundant uplink", severity: "High", sev_tok: "risk",
      trigger: "Single uplink to the core", mechanism: "AS01 has exactly one active uplink",
      impact: "AS01 endpoints go dark if the uplink fails", mitigation: "Add a second uplink to a different core",
      hosts: ["AS01"], blast: 12, blast_unit: "endpoints", shape: "linear", evidence: {},
    },
  ],
  families: [{ key: "spof", label: "SPOF", icon: "◆", n: 2, crit: 1 }],
  summary: { n_flows: 2, n_families: 1, n_critical: 1, by_severity: { Critical: 1, High: 1 } },
};

describe("CausalFlowPanel (render)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the loading state while flows load", () => {
    vi.spyOn(api, "causalFlows").mockReturnValue(new Promise(() => {}) as never);
    render(<CausalFlowPanel snapId={1} />);
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    vi.spyOn(api, "causalFlows").mockRejectedValue(new Error("causal_flows 1 failed"));
    render(<CausalFlowPanel snapId={1} />);
    expect(await screen.findByText("causal_flows 1 failed")).toBeInTheDocument();
  });

  it("selects the first flow by default, then swaps to the clicked card's flow (final state, not mid-animation)", async () => {
    vi.spyOn(api, "causalFlows").mockResolvedValue(causalFlows as never);
    render(<CausalFlowPanel snapId={1} />);
    expect(await screen.findByText("Causal flow — Core switch is a single point of failure")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Access switch AS01 has no redundant uplink"));

    // the diagram (keyed on cur.key) has swapped to the clicked flow, and aria-pressed tracks it
    expect(await screen.findByText("Causal flow — Access switch AS01 has no redundant uplink")).toBeInTheDocument();
    expect(screen.getByText("Access switch AS01 has no redundant uplink").closest('[role="button"]'))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Core switch is a single point of failure").closest('[role="button"]'))
      .toHaveAttribute("aria-pressed", "false");
  });

  it("a severity filter click remounts the (keyed) card list and re-derives the selection", async () => {
    vi.spyOn(api, "causalFlows").mockResolvedValue(causalFlows as never);
    const { container } = render(<CausalFlowPanel snapId={1} />);
    await screen.findByText("Causal flow — Core switch is a single point of failure");

    // the severity FChip is a `.czfchip` button — disambiguate from the card (also role="button",
    // whose own accessible name happens to contain the severity text too) via that class.
    const highChip = Array.from(container.querySelectorAll("button.czfchip")).find((b) => /High/.test(b.textContent || ""));
    expect(highChip).toBeTruthy();
    fireEvent.click(highChip!);

    // only the High-severity flow remains — it becomes the sole card and the selection
    expect(await screen.findByText("Causal flow — Access switch AS01 has no redundant uplink")).toBeInTheDocument();
    expect(screen.queryByText("Core switch is a single point of failure")).not.toBeInTheDocument();
  });
});
