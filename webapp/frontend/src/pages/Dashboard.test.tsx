import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";
import { api } from "../api";

// Integration test of the campaigns dashboard: the useAsync load state machine, the empty/error
// states, the pluralised wave count + per-campaign posture, and the create flow. jsdom-safe.
const CAMPAIGNS = [
  { id: 1, name: "DC-East", description: "core refresh", n_snapshots: 1,
    latest_summary: { n_switches: 40, avg_health: 72, punchlist: { crit_high: 3 }, bands: { Good: 30 } } },
  { id: 2, name: "DC-West", description: "", n_snapshots: 3, latest_summary: null },
];

const renderDash = () => render(<MemoryRouter><Dashboard /></MemoryRouter>);

describe("Dashboard (campaigns)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders each campaign with its pluralised wave count + posture strip", async () => {
    vi.spyOn(api, "listCampaigns").mockResolvedValue(CAMPAIGNS as never);
    renderDash();
    expect(await screen.findByText("DC-East")).toBeInTheDocument();
    expect(screen.getByText("DC-West")).toBeInTheDocument();
    expect(screen.getByText("1 wave")).toBeInTheDocument(); // singular
    expect(screen.getByText("3 waves")).toBeInTheDocument(); // plural
    expect(screen.getByText("No snapshots yet.")).toBeInTheDocument(); // DC-West has no latest_summary
  });

  it("shows the empty state with a load-sample CTA when there are no campaigns", async () => {
    vi.spyOn(api, "listCampaigns").mockResolvedValue([] as never);
    renderDash();
    expect(await screen.findByText(/No campaigns yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Load the sample fleet/ })).toBeInTheDocument();
  });

  it("surfaces a load error instead of a blank page", async () => {
    vi.spyOn(api, "listCampaigns").mockRejectedValue(new Error("database is locked"));
    renderDash();
    expect(await screen.findByText("database is locked")).toBeInTheDocument();
  });

  it("creates a campaign from the inline form and posts the entered name", async () => {
    vi.spyOn(api, "listCampaigns").mockResolvedValue([] as never);
    const create = vi.spyOn(api, "createCampaign").mockResolvedValue({ id: 9, name: "New Fleet" } as never);
    renderDash();
    await screen.findByText(/No campaigns yet/);
    fireEvent.click(screen.getByRole("button", { name: /New campaign/ }));
    fireEvent.change(screen.getByPlaceholderText(/DC-East core refresh/), { target: { value: "New Fleet" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(create).toHaveBeenCalledWith("New Fleet", "");
  });
});
