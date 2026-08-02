import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
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
      edges: [{ source: "acc1", target: "core1", is_bridge: true, pairs_cut: 2 }],
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
      edges: [{ source: "acc1", target: "core1", is_bridge: false, pairs_cut: 0 }],
    } as never);
    render(<TopologyGraph snapId={1} />);
    const btn = await screen.findByRole("button", { name: /Linked only/ });
    const title = btn.getAttribute("title") || "";
    expect(title).toMatch(/no CDP link was resolved/i);
    expect(title).toMatch(/Why is NOT observed/i);
    expect(title).not.toMatch(/\(uncollected or standalone\)/);
  });
});
