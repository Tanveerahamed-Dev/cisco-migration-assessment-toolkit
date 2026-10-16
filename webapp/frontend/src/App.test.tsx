import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import App from "./App";
import { api, ApiError } from "./api";
import type { Meta } from "./api";
import { deviceFixture, overviewFixture, topologyFixture, trustFixture } from "./test/projectionFixtures";
import type { TopologyRows, TopologyTarget } from "./pages/core/topologyData";

// Real geometry is exercised in hosted E2E; routing/session checks retain the actual workspace.
vi.mock("./pages/core/NetworkCanvas", () => ({ NetworkCanvas: ({ rows, selected, select }: {
  rows: TopologyRows; selected: TopologyTarget | null; select: (target: TopologyTarget) => void;
}) => <div data-testid="native-canvas" data-selection={selected ? JSON.stringify(selected) : "none"}>
  {rows.nodes.map((node) => <button key={node.pointer} onClick={() => select({ list: "nodes", row: { index: node.index, pointer: node.pointer } })}>Select {node.host.state === "published" ? node.host.value : node.index}</button>)}
</div> }));

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

describe("ADR-0008 snapshot route and session ownership", () => {
  afterEach(() => vi.restoreAllMocks());
  it("adds the native Engagements entry while keeping an explicit Classic door", async () => {
    vi.spyOn(api, "meta").mockRejectedValue(new Error("offline identity"));
    vi.spyOn(api, "listCampaigns").mockResolvedValue([]);
    renderApp("/engagements");
    expect(await screen.findByRole("heading", { name: "Start with an engagement" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Engagement rail" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Engagements", exact: true })).toHaveAttribute("href", "/engagements");
    expect(screen.getByRole("link", { name: "Classic view", exact: true })).toHaveAttribute("href", "/campaigns");
    expect(screen.getByRole("button", { name: /New assessment/ })).toBeDisabled();
  });
  function serve() {
    return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost"), sid = Number(url.pathname.split("/")[3]);
      if (url.pathname === "/api/campaigns") return new Response(JSON.stringify([]));
      if (/^\/api\/snapshots\/\d+$/.test(url.pathname)) return new Response(JSON.stringify({ id: sid, campaign_id: 1, label: `Synthetic snapshot ${sid}`, uploaded_at: "2026-10-16T00:00:00Z" }));
      if (url.pathname === "/api/campaigns/1") return new Response(JSON.stringify({ id: 1, name: "Synthetic engagement", snapshots: [{ id: 1, label: "Synthetic snapshot 1" }, { id: 2, label: "Synthetic snapshot 2" }] }));
      if (url.pathname.endsWith("/ui-projection/topology")) return new Response(JSON.stringify(topologyFixture(sid)));
      if (url.pathname.endsWith("/ui-projection/trust")) return new Response(JSON.stringify(trustFixture(sid)));
      if (url.pathname.endsWith("/ui-projection/overview")) return new Response(JSON.stringify(overviewFixture(sid)));
      if (url.pathname.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null, status: "not_built", detail: "Synthetic unavailable Scope" }));
      if (url.pathname.endsWith("/ui-projection/device")) return new Response(JSON.stringify(deviceFixture(sid, url.searchParams.get("host")!)));
      throw new Error(`Forbidden legacy request: ${url.pathname}`);
    });
  }
  it.each(["/snapshots/1", "/snapshots/1/", "/snapshots/1///", "/SNAPSHOTS/1", "/snapshots/%31"])("enters native Network at %s and keeps selection across tabs", async (path) => {
    vi.spyOn(api, "meta").mockRejectedValue(new Error("offline identity")); const fetcher = serve();
    const rendered = renderApp(path); const canvas = await screen.findByTestId("native-canvas");
    expect(screen.getByRole("complementary", { name: "Engagement rail" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /New assessment/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Select synthetic-edge-a", exact: true }));
    await screen.findByRole("region", { name: "Device identity" });
    fireEvent.click(screen.getByRole("button", { name: "Plan", exact: true }));
    expect(screen.getByRole("heading", { name: "Plan", exact: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Return to Network" }));
    expect(screen.getByTestId("native-canvas")).toBe(canvas);
    expect(canvas).toHaveAttribute("data-selection", JSON.stringify({ list: "nodes", row: { index: 0, pointer: "/cable_map/nodes/0" } }));
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/ui-projection/topology?")).length).toBe(1);
    expect(rendered.container.querySelector("iframe")).toBeNull();
    expect(screen.queryByRole("link", { name: /Scope|Explorer|Tools/i })).not.toBeInTheDocument();
  });
  it.each([{ matching: true, view: false }, { matching: false, view: false }, { matching: true, view: true }, { matching: false, view: true }])("keeps exact stored-byte guards with legacy view supplied=$view (matching=$matching)", async ({ matching, view }) => {
    vi.spyOn(api, "meta").mockRejectedValue(new Error("offline identity")); const fetcher = serve(); const doc = topologyFixture();
    const params = new URLSearchParams({ source: matching ? doc.identity.sha256 : `sha256:${"b".repeat(64)}`, source_bytes: String(doc.identity.bytes) });
    if (view) params.set("view", "overview");
    renderApp(`/snapshots/1?${params}`);
    if (matching && !view) await screen.findByTestId("native-canvas");
    else if (matching && view) expect(await screen.findByText("Synthetic fleet needs review")).toBeInTheDocument();
    else { expect(await screen.findByRole("alert")).toHaveTextContent("different stored snapshot"); expect(screen.queryByTestId("native-canvas")).not.toBeInTheDocument(); }
    const projectionCalls = fetcher.mock.calls.filter(([url]) => String(url).includes("/ui-projection/"));
    expect(projectionCalls.every(([url]) => view ? /\/ui-projection\/overview\?/.test(String(url)) : /\/ui-projection\/(topology|trust)\?/.test(String(url)))).toBe(true);
    if (view) expect(screen.queryByTestId("native-canvas")).not.toBeInTheDocument();
  });
  it("remounts source-bound investigation after a successful authentication exchange", async () => {
    vi.spyOn(api, "meta").mockRejectedValueOnce(new ApiError("token required", 401)).mockResolvedValueOnce({
      engine_schema: "3.23.0", severity_order: [], bands: [], section_labels: [], deliverables: [], app: { name: "Atlas", byline: "Synthetic", title: "Atlas", release: "synthetic" },
    });
    const authenticate = vi.spyOn(api, "authenticate").mockResolvedValue(null); const fetcher = serve();
    renderApp("/snapshots/1"); const previous = await screen.findByTestId("native-canvas");
    const dialog = await screen.findByRole("dialog", { name: "Atlas sign-in" });
    fireEvent.change(screen.getByLabelText("API token"), { target: { value: "synthetic-session-token" } }); fireEvent.submit(dialog);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Atlas sign-in" })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("native-canvas")).not.toBe(previous));
    expect(previous).not.toBeInTheDocument(); expect(screen.getByTestId("native-canvas")).toHaveAttribute("data-selection", "none");
    expect(authenticate).toHaveBeenCalledWith("synthetic-session-token");
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/ui-projection/topology?")).length).toBe(2);
  });
});
