import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type Campaign, type Summary } from "../../api";
import { AtlasRail } from "./AtlasRail";

const campaign = (id = 7, name = "Synthetic assessment"): Campaign => ({
  id, name, description: "Synthetic brownfield engagement", created_at: "2026-10-16T00:00:00Z",
});
const tree = (generation = 0) => <MemoryRouter initialEntries={["/snapshots/1"]}><AtlasRail key={generation} app={null} /></MemoryRouter>;

describe("Native engagement rail", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reloads the engagement list after an authenticated key remount following an initial401", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected analysis or legacy request"));
    const list = vi.spyOn(api, "listCampaigns").mockRejectedValueOnce(new ApiError("Synthetic token required", 401))
      .mockResolvedValueOnce([campaign()]);
    const view = render(tree());
    await screen.findByText(/Engagement list unavailable/);
    expect(list).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: /Synthetic assessment/ })).not.toBeInTheDocument();
    view.rerender(tree(1));
    expect(await screen.findByRole("link", { name: /Synthetic assessment/ })).toHaveAttribute("href", "/engagements/7");
    expect(screen.queryByText(/Engagement list unavailable/)).not.toBeInTheDocument();
    expect(list).toHaveBeenCalledTimes(2);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("retries an engagement API failure from the rail and removes the failed-state message", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected non-list request"));
    const list = vi.spyOn(api, "listCampaigns").mockRejectedValueOnce(new Error("Synthetic offline list"))
      .mockResolvedValueOnce([campaign(11, "Recovered assessment")]);
    render(tree());
    fireEvent.click(await screen.findByRole("button", { name: "Retry engagements", exact: true }));
    expect(await screen.findByRole("link", { name: /Recovered assessment/ })).toHaveAttribute("href", "/engagements/11");
    expect(screen.queryByText(/Engagement list unavailable/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry engagements", exact: true })).not.toBeInTheDocument();
    expect(list).toHaveBeenCalledTimes(2);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("renders record names as text and keeps cached summary KPIs out of native navigation", async () => {
    const name = "<img src=x onerror=untrusted()>";
    const description = "<script>untrusted()</script>";
    const fetcher = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected analysis request"));
    const record = { ...campaign(9, name), description, n_snapshots: 8888,
      latest_summary: { avg_health: 9999, n_critical: 7777, n_switches: 6666 } as Summary };
    const list = vi.spyOn(api, "listCampaigns").mockResolvedValue([record]);
    const view = render(tree());
    await screen.findByText(name, { exact: true });
    expect(screen.getByText(description, { exact: true })).toBeInTheDocument();
    expect(view.container.querySelector("img, script, iframe")).toBeNull();
    for (const sentinel of ["8888", "9999", "7777", "6666"]) expect(view.container).not.toHaveTextContent(sentinel);
    const links = screen.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(links).toContain("/engagements/9");
    expect(links).not.toContain("/campaigns/9");
    expect(screen.getByRole("button", { name: /New assessment/ })).toBeDisabled();
    expect(list).toHaveBeenCalledTimes(1);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not restore a late old engagement response after a session remount", async () => {
    let finishOld!: (rows: Campaign[]) => void;
    const list = vi.spyOn(api, "listCampaigns").mockImplementationOnce(() => new Promise<Campaign[]>((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce([campaign(12, "Current session assessment")]);
    const view = render(tree());
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    view.rerender(tree(1));
    await screen.findByRole("link", { name: /Current session assessment/ });
    await act(async () => { finishOld([campaign(13, "Old session assessment")]); });
    expect(screen.queryByRole("link", { name: /Old session assessment/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Current session assessment/ })).toHaveAttribute("href", "/engagements/12");
  });
});
