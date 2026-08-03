import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import App from "./App";
import { api, ApiError } from "./api";
import type { Meta } from "./api";

// App is the routing spine: the top bar (always present), the route table, and the theme toggle.
// These exercise the parts jsdom can reach without mocking every page's API — the catch-all route
// and the persisted-theme logic. (Real route→page navigation is covered by the Playwright E2E.)
function renderApp(path = "/nowhere") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App shell", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("renders the top bar (brand + nav) on any route", () => {
    renderApp();
    expect(screen.getByText("AssessHub")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Campaigns" })).toBeInTheDocument();
  });

  it("degrades an unknown route to a recoverable Not-Found card, not a white screen (WEBAP-01 spirit)", () => {
    renderApp("/definitely-not-a-real-route");
    expect(screen.getByText(/Not found/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Go home/i })).toBeInTheDocument();
    // the chrome survives — the boundary is below the top bar
    expect(screen.getByText("AssessHub")).toBeInTheDocument();
  });

  it("defaults to the dark theme and persists a toggle to light", () => {
    renderApp();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    fireEvent.click(screen.getByRole("button", { name: /toggle theme/i }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("assesshub-theme")).toBe("light");
  });

  it("restores the persisted theme from localStorage on load", () => {
    localStorage.setItem("assesshub-theme", "light");
    renderApp();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});

// Unit 2: Routes now renders a LAGGED location (`shown`), synced from the router's real location
// via a view-transition-wrapped effect (jsdom has no startViewTransition, so the sync fallback
// applies it immediately — see components/ui.test.tsx). This only asserts the settled DOM after
// navigation, never a mid-animation frame (house convention).
describe("route transitions (Unit 2 — view-transition lag)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("navigating swaps the routed page while the chrome (top bar) stays mounted", async () => {
    vi.spyOn(api, "listCampaigns").mockResolvedValue([]);
    renderApp("/");
    expect(screen.queryByRole("heading", { name: "Campaigns" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "Campaigns" }));

    expect(await screen.findByRole("heading", { name: "Campaigns" })).toBeInTheDocument();
    expect(screen.getByText("AssessHub")).toBeInTheDocument(); // chrome survives the swap
  });
});

// ADR-0004 D1: the cockpit brand comes from /api/meta (whose values come from the brand SSOT,
// cisco_toolkit/brand_tokens.py). "AssessHub" survives only as the pre-load / API-down fallback.
describe("TopBar app identity", () => {
  afterEach(() => vi.restoreAllMocks());

  const META: Meta = {
    engine_schema: "3.23.0",
    severity_order: [],
    bands: [],
    section_labels: [],
    deliverables: [],
    app: { name: "Atlas", byline: "by Tanveer Ahamed", title: "Atlas — by Tanveer Ahamed", release: "3.31.0 (checkout)" },
  };

  it("upgrades the brand (and document title) to the served identity once meta loads", async () => {
    vi.spyOn(api, "meta").mockResolvedValue(META);
    renderApp();
    expect(await screen.findByText("Atlas")).toBeInTheDocument();
    expect(screen.getByText("by Tanveer Ahamed")).toBeInTheDocument();
    expect(screen.queryByText("AssessHub")).not.toBeInTheDocument();
    await waitFor(() => expect(document.title).toContain("Atlas"));
  });

  it("keeps the AssessHub fallback when meta is unreachable", async () => {
    vi.spyOn(api, "meta").mockRejectedValue(new Error("api down"));
    renderApp();
    expect(screen.getByText("AssessHub")).toBeInTheDocument();
  });

  it("exposes an About nav link routing to the About page", () => {
    vi.spyOn(api, "meta").mockRejectedValue(new Error("api down"));
    renderApp();
    expect(screen.getByRole("link", { name: "About" })).toBeInTheDocument();
  });

  it("exchanges the bearer for a browser session when meta answers 401", async () => {
    vi.spyOn(api, "meta")
      .mockRejectedValueOnce(new ApiError("token required", 401))
      .mockResolvedValueOnce(META);
    const authenticate = vi.spyOn(api, "authenticate").mockResolvedValue(null);
    renderApp();

    const dialog = await screen.findByRole("dialog", { name: "Atlas sign-in" });
    fireEvent.change(screen.getByLabelText("API token"), { target: { value: "field-secret" } });
    fireEvent.submit(dialog);

    await waitFor(() => expect(authenticate).toHaveBeenCalledWith("field-secret"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Atlas")).toBeInTheDocument();
  });
});
