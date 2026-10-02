import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import CoreSnapshot from "./CoreSnapshot";
import { overviewFixture, trustFixture, inventoryFixture, findingsFixture, deviceFixture, published } from "../test/projectionFixtures";

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
    expect(screen.getByText(/complete health-band partition is not published/)).toBeInTheDocument();
    expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
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
