import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import CoreSnapshot from "./CoreSnapshot";
import { overviewFixture, overviewRollupsFixture, trustFixture, inventoryFixture, findingsFixture, deviceFixture, published, topologyFixture } from "../test/projectionFixtures";

function Harness() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/snapshots/2")}>Switch source</button><Routes><Route path="/snapshots/:id" element={<CoreSnapshot />} /></Routes></>;
}
const show = (path = "/snapshots/1") => render(<MemoryRouter initialEntries={[path]}><Harness /></MemoryRouter>);
describe("Core snapshot route", () => {
  afterEach(() => vi.restoreAllMocks());
  it("uses the projection alone for core facts and preserves published zero", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/ui-projection/overview?")) return new Response(JSON.stringify(overviewFixture()));
      if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
      throw new Error(`Unexpected legacy request: ${url}`);
    });
    show();
    expect(await screen.findByText("Synthetic fleet needs review")).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Insufficient Data" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic readiness inputs were not collected")).toBeInTheDocument();
    expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
  });
  it("shows the owner's health partition and move-group checks in supplied order with source qualifications", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/overview?") ? overviewRollupsFixture() : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    const bands = screen.getAllByRole("article").filter((row) => row.getAttribute("aria-label")?.endsWith(" health band"));
    expect(bands.map((row) => row.getAttribute("aria-label"))).toEqual([
      "Excellent health band", "Good health band", "Fair health band", "Poor health band", "Critical health band", "Insufficient Data health band",
    ]);
    const poor = screen.getByRole("article", { name: "Poor health band" });
    expect(within(poor).getByText("0")).toBeInTheDocument();
    expect(within(poor).getByText("Collected, empty")).toBeInTheDocument();
    expect(within(poor).queryByRole("link")).not.toBeInTheDocument();
    const criticalLink = within(screen.getByRole("article", { name: "Critical health band" })).getByRole("link", { name: "edge/a~b ↗" });
    expect(new URL(criticalLink.getAttribute("href")!, "http://localhost").searchParams.get("host")).toBe("edge/a~b");
    const groupRows = screen.getAllByRole("group").filter((row) => row.getAttribute("aria-label")?.startsWith("Move-group source row"));
    expect(groupRows.map((row) => row.getAttribute("aria-label"))).toEqual(["Move-group source row 3", "Move-group source row 0"]);
    const group = within(groupRows[0]);
    expect(group.getByText("CAUTION")).toBeInTheDocument();
    expect(group.getByText("0")).toBeInTheDocument();
    expect(group.getByText("6")).toBeInTheDocument();
    fireEvent.click(group.getByText("Readiness checks and evidence"));
    expect(group.getAllByText(/Synthetic check [AB]/).map((node) => node.textContent)).toEqual(["Synthetic check B", "Synthetic check A"]);
    expect(group.getByText("Rollback")).toBeInTheDocument();
    fireEvent.click(group.getByRole("button", { name: "Qualifications for endpoints" }));
    const drawer = screen.getByRole("dialog");
    expect(drawer).toHaveTextContent("not distinct endpoints across a move group");
    expect(drawer).toHaveTextContent("/migration_readiness/3/endpoints");
    expect(drawer).toHaveTextContent("/move_groups/3/endpoints");
    expect(drawer).toHaveTextContent(`sha256:${"a".repeat(64)}`);
    expect(screen.queryByText(/complete health-band partition is not published/)).not.toBeInTheDocument();
    expect(screen.getByText(/Design-decision details are available in Tools/)).toBeInTheDocument();
  });
  it("keeps canonical health contradictions withheld without band counts or host links", async () => {
    const doc = overviewFixture();
    const failed = { state: "unverified", value: null, reason: "Synthetic canonical health contradiction", subject: "/health_scores", refs: [], basis: "ssot.reconcile" };
    const altered = { ...doc, payload: { ...doc.payload, fleet_health: { ...doc.payload.fleet_health,
      bands: doc.payload.fleet_health.bands.map((band) => ({ ...band, n: failed, hosts: failed })) } } };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/overview?") ? altered : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    for (const band of ["Critical", "Poor"]) {
      const row = within(screen.getByRole("article", { name: `${band} health band` }));
      expect(row.getAllByText("Unverified")).toHaveLength(2);
      expect(row.getAllByText("Synthetic canonical health contradiction")).toHaveLength(2);
      expect(row.queryByText("0")).not.toBeInTheDocument();
      expect(row.queryByRole("link")).not.toBeInTheDocument();
    }
  });
  it("shows uncollected rollups as blind spots without zero bands or a READY group", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/overview?") ? overviewFixture() : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    const critical = within(screen.getByRole("article", { name: "Critical health band" }));
    expect(critical.getAllByText("Not collected")).toHaveLength(2);
    expect(critical.queryByText("0")).not.toBeInTheDocument();
    expect(critical.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic readiness inputs were not collected")).toBeInTheDocument();
    expect(screen.queryByText("READY")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Move-group source row/ })).not.toBeInTheDocument();
  });
  it("preserves an unverified move-group label and withheld readiness rather than inventing a verdict", async () => {
    const doc = overviewRollupsFixture();
    const failed = { state: "unverified", value: null, reason: "Synthetic label does not match the move-group owner", subject: "/migration_readiness/3", refs: [], basis: "synthetic.owner" };
    const row = doc.payload.readiness.groups.page.items[0];
    const altered = { ...doc, payload: { ...doc.payload, readiness: { groups: { ...doc.payload.readiness.groups,
      source_list: { ...doc.payload.readiness.groups.source_list, state: "unverified", reason: failed.reason },
      page: { ...doc.payload.readiness.groups.page, total: 1, returned: 1, items: [{ ...row,
      group: failed, readiness: failed, switches: failed, endpoints: failed, n_fail: failed, n_warn: failed,
      checks: { ...row.checks, state: "unverified", reason: failed.reason, items: [] } }] } } } } };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/overview?") ? altered : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    const group = within(screen.getByRole("group", { name: "Move-group source row 3" }));
    expect(group.getAllByText("Unverified").length).toBeGreaterThan(0);
    expect(group.queryByText("READY")).not.toBeInTheDocument();
    expect(group.queryByText("0")).not.toBeInTheDocument();
    expect(group.queryByRole("link")).not.toBeInTheDocument();
    expect(group.queryByText("Synthetic group B")).not.toBeInTheDocument();
  });
  it("loads Trust on navigation and closes the previous fact drawer", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/trust?") ? trustFixture() : String(input).includes("/overview?") ? overviewFixture() : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    fireEvent.click(screen.getByRole("button", { name: "Evidence for Engine statement" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Synthetic fleet needs review");
    fireEvent.click(screen.getByRole("link", { name: "Trust" }));
    await screen.findByRole("heading", { name: "Evidence coverage" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("opens the fifth Topology & Paths tab through the projection without a legacy graph or snapshot fetch", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/ui-projection/overview?")) return new Response(JSON.stringify(overviewFixture()));
      if (url.includes("/ui-projection/topology?")) return new Response(JSON.stringify(topologyFixture()));
      if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
      throw new Error(`Unexpected legacy request: ${url}`);
    });
    show(); await screen.findByText("Synthetic fleet needs review");
    fireEvent.click(screen.getByRole("link", { name: "Topology & Paths" }));
    await screen.findByRole("img", { name: "Engine topology diagram" });
    expect(screen.getByRole("heading", { name: "Investigate an IP path" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Topology & Paths" })).toHaveLength(1);
    expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
  });
  it("suppresses a late old-snapshot response", async () => {
    let resolveOld!: (response: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input).includes("/1/ui-projection")) return new Promise((resolve) => { resolveOld = resolve; });
      return Promise.resolve(new Response(JSON.stringify(String(input).includes("/2/ui-projection") ? overviewFixture(2, "Current source") : { available: false })));
    });
    show(); fireEvent.click(screen.getByRole("button", { name: "Switch source" }));
    await screen.findByText("Current source");
    await act(async () => { resolveOld(new Response(JSON.stringify(overviewFixture(1, "Stale source")))); });
    expect(screen.queryByText("Stale source")).not.toBeInTheDocument();
    expect(screen.getByText("Current source")).toBeInTheDocument();
  });
  it("encodes exact-host navigation and never backfills a missing device field", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/inventory?") ? inventoryFixture() : { available: false })));
    show("/snapshots/1?view=inventory");
    const link = await screen.findByRole("link", { name: "edge/a~b ↗" });
    expect(new URL(link.getAttribute("href")!, "http://localhost").searchParams.get("host")).toBe("edge/a~b");
    expect(screen.getAllByText("Synthetic input was not collected").length).toBeGreaterThan(0);
  });
  it("keeps Findings compact and expands owner issue/remediation text", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/findings?") ? findingsFixture() : { available: false })));
    show("/snapshots/1?view=findings");
    await screen.findByText("Synthetic finding");
    const summary = screen.getByText("Issue, remediation and evidence");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(summary); expect(summary.closest("details")).toHaveAttribute("open");
    expect(screen.getByText("Synthetic owner remediation")).toBeInTheDocument();
  });
  it("rejects a reference bound to another source without showing its rows", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/findings?") ? findingsFixture() : { available: false })));
    show(`/snapshots/1?view=findings&source=sha256:${"b".repeat(64)}&source_bytes=42&ref=/punchlist/7&row=7`);
    expect(await screen.findByRole("alert")).toHaveTextContent("different stored snapshot");
    expect(screen.queryByText("Synthetic finding")).not.toBeInTheDocument();
  });
  it("renders interface cells in the explicit engine column order even when JSON keys arrive reversed", async () => {
    const columns = ["status", "switchport_mode", "vlan", "speed", "duplex", "description", "cdp_neighbor", "neighbor_port", "trunk_allowed_vlans", "trunk_native_vlan", "stp_fwd_vlans", "stp_blk_vlans", "end_host_ip", "end_host_mac", "port_channel", "svi_ip", "vrf"];
    const doc = deviceFixture();
    const altered = { ...doc, payload: { ...doc.payload, interfaces: { columns, rows: { ...doc.payload.interfaces.rows,
      page: { offset: 0, limit: 25, total: 1, returned: 1, has_more: false, items: [{ port: "Gi1", pointer: "/interfaces/0", run_config_observed: published(true),
        cells: Object.fromEntries([...columns].reverse().map((key) => [key, published(`value:${key}`)])) }] } } } } };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/device?") ? altered : { available: false })));
    show("/snapshots/1?view=device&host=edge%2Fa%7Eb");
    await screen.findByRole("heading", { name: "Health", exact: true });
    fireEvent.click(screen.getByText("Interfaces, links and routing", { exact: true }));
    const row = screen.getByText("Gi1").closest(".projection-list-item")! as HTMLElement;
    const labels = within(row).getAllByRole("button").map((button) => button.getAttribute("aria-label")?.replace("Evidence for ", ""))
      .filter((label) => columns.map((key) => key.replaceAll("_", " ")).includes(label ?? ""));
    expect(labels).toEqual(columns.map((key) => key.replaceAll("_", " ")));
  });
  it.each([
    [false, "/scope/?snapshot=1"], [true, "https://example.invalid/scope/"],
    [true, "/scope/%2e%2e/campaigns"], [true, "/scope/\\outside"],
  ])("withholds a scope link for unavailable or escaping capability %s %s", async (available, href) => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).endsWith("/scope-view") ? { available, href } : overviewFixture())));
    show(); await screen.findByText("Synthetic fleet needs review");
    expect(screen.queryByRole("link", { name: /Open in Atlas Scope/ })).not.toBeInTheDocument();
  });
});
