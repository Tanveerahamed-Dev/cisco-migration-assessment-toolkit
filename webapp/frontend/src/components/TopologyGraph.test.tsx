import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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

  it("re-solves the observed graph on selection and scopes the result to its named reference anchor", async () => {
    vi.spyOn(api, "graph").mockResolvedValue({
      nodes: [
        { ...nodeOf("core", 3), role: "core" },
        { ...nodeOf("dist", 2), role: "distribution" },
        nodeOf("acc", 1), nodeOf("edge-a", 1), nodeOf("edge-b", 1),
      ],
      edges: [
        ["core", "dist"], ["dist", "acc"], ["core", "edge-a"], ["core", "edge-b"],
      ].map(([source, target]) => ({ source, target, bridge_assessed: true, is_bridge: false, pairs_cut: 0 })),
      link_centrality_assessed: true,
      offscan_peers: [],
    } as never);
    render(<TopologyGraph snapId={1} />);
    const distLabel = await screen.findByText("dist");
    fireEvent.click(distLabel.closest("g")!);
    const impact = await screen.findByTestId("topology-failure-impact");
    expect(impact.textContent).toMatch(/1 baseline-reached device loses the resolved path/i);
    expect(impact.textContent).toMatch(/reference anchor core/i);
    expect(impact.textContent).toMatch(/not a fleet-wide bound/i);
    expect(screen.getByText(/selected failure — loses path to core/i)).toBeInTheDocument();
  });

  it("does not publish a tautological impact count when the selected device is the reference anchor", async () => {
    vi.spyOn(api, "graph").mockResolvedValue({
      nodes: [nodeOf("a", 2), nodeOf("b", 2), nodeOf("c", 2)],
      edges: [
        ["a", "b"], ["b", "c"], ["c", "a"],
      ].map(([source, target]) => ({ source, target, bridge_assessed: true, is_bridge: false, pairs_cut: 0 })),
      link_centrality_assessed: true,
      offscan_peers: [],
    } as never);
    const { container } = render(<TopologyGraph snapId={1} />);
    const anchorLabel = await screen.findByText("a");
    fireEvent.click(anchorLabel.closest("g")!);
    const impact = await screen.findByTestId("topology-failure-impact");
    expect(impact.textContent).toMatch(/\[REFERENCE ANCHOR SELECTED\]/);
    expect(impact.textContent).toMatch(/no failure-impact count is claimed/i);
    expect(screen.queryByText(/selected failure — loses path/i)).toBeNull();
    const paths = [...container.querySelectorAll("svg path")];
    expect(paths.filter((path) => path.getAttribute("stroke-opacity") === "0.1")).toHaveLength(1);
  });

  it("clears snapshot-specific selection before rendering a different snapshot", async () => {
    const first = {
      nodes: [{ ...nodeOf("core", 2), role: "core" }, nodeOf("dist", 2), nodeOf("acc", 1)],
      edges: [
        { source: "core", target: "dist", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
        { source: "dist", target: "acc", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
      ],
      link_centrality_assessed: true, offscan_peers: [],
    };
    const second = {
      nodes: [nodeOf("fresh", 0)], edges: [], link_centrality_assessed: false, offscan_peers: [],
    };
    vi.spyOn(api, "graph").mockImplementation((id) => Promise.resolve(id === 1 ? first : second) as never);
    const { rerender } = render(<TopologyGraph snapId={1} />);
    const distLabel = await screen.findByText("dist");
    fireEvent.click(distLabel.closest("g")!);
    await screen.findByTestId("topology-failure-impact");

    rerender(<TopologyGraph snapId={2} />);
    const fresh = await screen.findByText("fresh");
    expect(screen.queryByTestId("topology-failure-impact")).toBeNull();
    expect(fresh.closest("g")).toHaveStyle({ opacity: "1" });
  });
});
