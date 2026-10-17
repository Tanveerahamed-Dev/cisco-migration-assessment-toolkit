import { deviceFixture, published, topologyFixture, withheld } from "../test/projectionFixtures";
import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import TopologyGraph from "./TopologyGraph";
import { api } from "../api";

// Render-level coverage for the fleet-topology panel. topology.test.ts pins the pure layout/linkPath
// maths; this file pins what the DIAGRAM CLAIMS. The 3D layer stays unmounted in 2D mode, so nothing
// here pulls three.js.

const nodeOf = (id: string, degree: number, band = "Good") =>
  ({ id, band, score: 80, role: "access", degree, keystone: false });

describe("TopologyGraph (render)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the loading state while the topology builds", () => {
    vi.spyOn(api, "graph").mockReturnValue(new Promise(() => {}) as never);
    render(<TopologyGraph snapId={1} />);
    expect(screen.getByText(/Building topology/i)).toBeInTheDocument();
  });

  // Guardrail 3. A fleet drawn with ZERO links is not evidence of an unlinked estate — /graph resolves
  // a CDP neighbour by matching a CANONICALISED (lower-cased, domain-stripped) name against the RAW
  // snapshot hostnames, so an estate whose hostnames are not already lower-case resolves nothing and
  // every switch arrives degree 0. That silence also silences the red single-point-of-failure overlay:
  // the picture then reads "no chokepoints" when the truth is "topology not established".
  it("declares [NOT OBSERVED] when no inter-switch link resolved for ANY switch", async () => {
    vi.spyOn(api, "graph").mockResolvedValue(
      { nodes: [nodeOf("CORE1", 0), nodeOf("ACC1", 0), nodeOf("ACC2", 0)], edges: [] } as never);
    render(<TopologyGraph snapId={1} />);
    const banner = await screen.findByRole("status");
    expect(banner.textContent).toMatch(/\[NOT OBSERVED\]/);
    expect(banner.textContent).toMatch(/no inter-switch link resolved for any of the 3 switches/i);
    // the reading it must forbid, stated outright
    expect(banner.textContent).toMatch(/never as .no chokepoints/i);
  });

  it("stays quiet when the fabric IS drawn (the banner is not a permanent disclaimer)", async () => {
    vi.spyOn(api, "graph").mockResolvedValue({
      nodes: [nodeOf("core1", 1), nodeOf("acc1", 1)],
      edges: [{ source: "acc1", target: "core1", bridge_assessed: true, is_bridge: true, pairs_cut: 2 }],
      link_centrality_assessed: true,
      offscan_peers: [],
    } as never);
    render(<TopologyGraph snapId={1} />);
    await screen.findByText(/2 switches · 1 links/);
    expect(screen.queryByRole("status")).toBeNull();
  });

  // The "Linked only" affordance may state WHAT was not observed, never WHY: standalone, uncollected
  // and an unresolved neighbour name are indistinguishable from this payload.
  it("does not attribute a cause to an unlinked switch", async () => {
    vi.spyOn(api, "graph").mockResolvedValue({
      nodes: [nodeOf("core1", 1), nodeOf("acc1", 1), nodeOf("orphan1", 0)],
      edges: [{ source: "acc1", target: "core1", bridge_assessed: true, is_bridge: false, pairs_cut: 0 }],
      link_centrality_assessed: true,
      offscan_peers: [],
    } as never);
    render(<TopologyGraph snapId={1} />);
    const btn = await screen.findByRole("button", { name: /Linked only/ });
    const title = btn.getAttribute("title") || "";
    expect(title).toMatch(/no CDP link was resolved/i);
    expect(title).toMatch(/Why is NOT observed/i);
    expect(title).not.toMatch(/\(uncollected or standalone\)/);
  });

  it("renders unassessed link centrality as a loud third state, never as measured-redundant", async () => {
    vi.spyOn(api, "graph").mockResolvedValue({
      nodes: [nodeOf("core1", 1), nodeOf("acc1", 1)],
      edges: [{ source: "acc1", target: "core1", bridge_assessed: false, is_bridge: false, pairs_cut: 0 }],
      link_centrality_assessed: false,
      offscan_peers: [],
    } as never);
    render(<TopologyGraph snapId={1} />);
    const gap = await screen.findByTestId("topology-assessment-gap");
    expect(gap.textContent).toMatch(/\[NOT ASSESSED\]/);
    expect(gap.textContent).toMatch(/0 of 1 resolved links/i);
    expect(gap.textContent).toMatch(/not healthy or redundant verdicts/i);
    expect(screen.getByText("redundancy not assessed")).toBeInTheDocument();
  });

  it("fails closed for an edge-bearing legacy payload that omits the assessment fields", async () => {
    vi.spyOn(api, "graph").mockResolvedValue({
      nodes: [nodeOf("legacy-core", 1), nodeOf("legacy-access", 1)],
      // A stale true is still not a verdict without the assessment bit.
      edges: [{ source: "legacy-access", target: "legacy-core", is_bridge: true, pairs_cut: 3 }],
    });
    render(<TopologyGraph snapId={1} />);
    const gap = await screen.findByTestId("topology-assessment-gap");
    expect(gap.textContent).toMatch(/\[NOT ASSESSED\]/);
    expect(gap.textContent).toMatch(/0 of 1 resolved links/i);
    expect(screen.getByText("redundancy not assessed")).toBeInTheDocument();
    expect(screen.getByText(/Redundancy not assessed — discovered link/i)).toBeInTheDocument();
    expect(screen.queryByText("assessed single point of failure")).toBeNull();
  });

  it("discloses peers omitted from the collected snapshot instead of drawing a falsely closed fabric", async () => {
    vi.spyOn(api, "graph").mockResolvedValue({
      nodes: [nodeOf("core1", 1), nodeOf("acc1", 1)],
      edges: [{ source: "acc1", target: "core1", bridge_assessed: true, is_bridge: false, pairs_cut: 0 }],
      link_centrality_assessed: true,
      offscan_peers: ["wan-edge-01.example", "uncollected-core-02.example"],
    } as never);
    render(<TopologyGraph snapId={1} />);
    const gap = await screen.findByTestId("topology-offscan-gap");
    expect(gap.textContent).toMatch(/\[PARTIAL TOPOLOGY\]/);
    expect(gap.textContent).toMatch(/2 discovered peers were outside this snapshot/i);
    expect(gap.textContent).toContain("wan-edge-01.example");
    expect(gap.textContent).toMatch(/hide additional paths or failure impact/i);
  });

});

function ownerMock(topology: any = topologyFixture(), device?: any) {
  vi.spyOn(api, "graph").mockResolvedValue({
    nodes: [nodeOf("synthetic-edge-a", 1), nodeOf("synthetic-peer-b", 1)],
    edges: [{ source: "synthetic-edge-a", target: "synthetic-peer-b", bridge_assessed: true, is_bridge: false, pairs_cut: 0 }],
    engine: topology.engine, link_centrality_assessed: true, offscan_peers: [],
  } as never);
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/ui-projection/topology")) return new Response(JSON.stringify(topology));
    if (url.pathname.endsWith("/ui-projection/device") && device) return new Response(JSON.stringify(device));
    return new Response(JSON.stringify({ detail: "not supplied" }), { status: 404 });
  });
}
function deviceWith(fact: any) {
  const topology = topologyFixture();
  const device: any = deviceFixture(1, "synthetic-edge-a");
  device.payload.failure_impact = structuredClone(topology.payload.failure_impact);
  device.payload.failure_impact.page.items[0].stranded = fact;
  return device;
}
async function selectDevice() {
  fireEvent.click(await screen.findByText("synthetic-edge-a", { exact: true }));
  return screen.findByRole("heading", { name: "If synthetic-edge-a fails" });
}

describe("Tools failures use source-bound engine pages", () => {
  afterEach(() => vi.restoreAllMocks());
  it("uses the owner count even where browser graph connectivity suggests another", async () => {
    const fetch = ownerMock(topologyFixture(), deviceWith(published(17)));
    render(<TopologyGraph snapId={1} />);
    const heading = await selectDevice();
    expect(within(heading.closest("section")!).getByText("17")).toBeInTheDocument();
    expect(fetch.mock.calls.some(([url]) => String(url).includes("ui-projection/device?") && String(url).includes("host=synthetic-edge-a"))).toBe(true);
    expect(screen.queryByText(/reference anchor|baseline-reached/)).toBeNull();
  });
  it("shows a published zero for a connected device without inventing an anchor verdict", async () => {
    ownerMock(topologyFixture(), deviceWith(published(0)));
    render(<TopologyGraph snapId={1} />);
    const heading = await selectDevice();
    expect(within(heading.closest("section")!).getAllByText("0").length).toBeGreaterThan(0);
    expect(screen.queryByText(/REFERENCE ANCHOR SELECTED/)).toBeNull();
  });
  it("keeps a held value and its owner reason visible", async () => {
    ownerMock(topologyFixture(), deviceWith({ ...withheld(), reason: "No captured failure evidence" }));
    render(<TopologyGraph snapId={1} />); await selectDevice();
    expect(await screen.findByText("No captured failure evidence")).toBeInTheDocument();
  });
  it("preserves the engine lower-bound treatment", async () => {
    ownerMock(topologyFixture(), deviceWith({ ...published(17), refs: [{ role: "witness", pointer: "/collection_completeness/devices/0" }] }));
    render(<TopologyGraph snapId={1} />); await selectDevice();
    expect(await screen.findByText("≥ 17")).toBeInTheDocument();
  });
  it.each(["identity", "engine", "host"])("rejects a device with changed %s", async (key) => {
    const device: any = deviceWith(published(17));
    if (key === "identity") device.identity.sha256 = `sha256:${"f".repeat(64)}`;
    if (key === "engine") device.engine = { ...device.engine, script_version: "foreign" };
    if (key === "host") device.payload.host = "different-device";
    ownerMock(topologyFixture(), device); render(<TopologyGraph snapId={1} />);
    fireEvent.click(await screen.findByText("synthetic-edge-a", { exact: true }));
    expect(await screen.findByText(/changed|different device/)).toBeInTheDocument();
    expect(screen.queryByText("17")).toBeNull();
  });
  it("refuses a diagram whose engine binding differs from the topology page", async () => {
    ownerMock(topologyFixture(), deviceWith(published(17)));
    vi.mocked(api.graph).mockResolvedValue({
      nodes: [nodeOf("synthetic-edge-a", 0)], edges: [],
      engine: { ...topologyFixture().engine, code_schema_version: "foreign" },
    } as never);
    render(<TopologyGraph snapId={1} />);
    fireEvent.click(await screen.findByText("synthetic-edge-a", { exact: true }));
    expect(await screen.findByText(/Diagram evidence changed/)).toBeInTheDocument();
    expect(screen.queryByText("17")).toBeNull();
  });
  it("clears the old device result when the snapshot changes", async () => {
    ownerMock(topologyFixture(), deviceWith(published(17)));
    const { rerender } = render(<TopologyGraph snapId={1} />); await selectDevice();
    ownerMock(topologyFixture(2)); rerender(<TopologyGraph snapId={2} />);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "If synthetic-edge-a fails" })).toBeNull());
    expect(screen.queryByText("17")).toBeNull();
  });
});
