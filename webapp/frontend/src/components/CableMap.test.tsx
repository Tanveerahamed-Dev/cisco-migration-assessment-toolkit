import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import CableMap from "./CableMap";
import { api } from "../api";
import type { CableMap as CableMapModel, CableMapNode, CableMapCable } from "../api";

// Render-level coverage for the motion polish: CableMap.test.ts pins the pure layout/filter
// functions; this file exercises the actual mount — the relayout tween + cable-anchor delta math
// only run inside a real render, and a bug there throws (undefined anchor math) rather than
// quietly misdrawing, so a plain successful render + selection is itself a meaningful check.
// Per the animated-primitives convention (ui.test.tsx), assert STABLE final state only — never a
// mid-animation frame.

function node(host: string, tier: number, kind: string, role: string, ports: CableMapNode["ports"] = []): CableMapNode {
  return { host, role, tier, order: 0, collected: true, op_status: "up", badges: [], ports, kind };
}
function cable(a: string, aPort: string, b: string, bPort: string): CableMapCable {
  return { a, a_port: aPort, b, b_port: bPort, is_pc: false, members: [], op_status: "up", confirmation: "", speed: "1000" };
}

const model: CableMapModel = {
  nodes: [
    node("core1", 0, "switch", "core", [{ name: "Gi0/1", peer: "acc1", peer_port: "Gi0/1", op_status: "up", is_pc: false }]),
    node("acc1", 1, "switch", "access", [{ name: "Gi0/1", peer: "core1", peer_port: "Gi0/1", op_status: "up", is_pc: false }]),
  ],
  cables: [cable("core1", "Gi0/1", "acc1", "Gi0/1")],
  tiers: [["core1"], ["acc1"]],
  summary: { n_nodes: 2, n_cables: 1, n_tiers: 2, op: { up: 1, down: 0, unknown: 0 } },
};

describe("CableMap (render)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the loading state while the map builds", () => {
    vi.spyOn(api, "cableMap").mockReturnValue(new Promise(() => {}) as never);
    render(<CableMap snapId={1} />);
    expect(screen.getByText(/Building cable map/i)).toBeInTheDocument();
  });

  it("selecting a node settles with the inspector panel shown, carrying the .tabfade entrance", async () => {
    vi.spyOn(api, "cableMap").mockResolvedValue(model as never);
    const { container } = render(<CableMap snapId={1} />);
    const label = await screen.findByText("core1"); // the chassis label — proves layout+render didn't throw
    fireEvent.click(label.closest("g")!); // click the node GROUP (the element the onClick actually lives on)

    const panel = container.querySelector(".tabfade");
    expect(panel).not.toBeNull();
    expect(panel).toHaveClass("tabfade");
    expect(panel!.textContent).toContain("core1");
  });

  // FE-15: the sibling TopologyGraph panel banners the "nodes drawn, zero links resolved" case
  // ([NOT OBSERVED] — read as "topology not established", never "no chokepoints"). CableMap did
  // not: it drew every chassis unconnected and captioned it "N nodes · 0 cables", with the legend
  // strip reading "0 up · 0 down · 0 not observed" — an all-zero op census that an engineer reads
  // as "nothing is down". Zero resolved cables is a COLLECTION result (no CDP/LLDP evidence, or a
  // neighbour name that did not match), not a fact about the cabling.
  it("FE-15: a map with nodes but zero resolved cables says [NOT OBSERVED] on its face", async () => {
    vi.spyOn(api, "cableMap").mockResolvedValue({
      ...model,
      cables: [],
      summary: { n_nodes: 2, n_cables: 0, n_tiers: 2, op: { up: 0, down: 0, unknown: 0 } },
    } as never);
    const { container } = render(<CableMap snapId={1} />);
    await screen.findByText("core1");

    const banner = container.querySelector('[role="status"]');
    expect(banner).not.toBeNull();
    expect(banner!.textContent).toMatch(/NOT OBSERVED/);
    expect(banner!.textContent).toMatch(/no down link|not established/i);
  });

  it("FE-15: a map that DID resolve cables carries no such banner", async () => {
    vi.spyOn(api, "cableMap").mockResolvedValue(model as never);
    const { container } = render(<CableMap snapId={1} />);
    await screen.findByText("core1");
    expect(container.querySelector('[role="status"]')).toBeNull();
  });

  // FE-16: filterModel spreads the source model, so `summary` survives the filter UNCHANGED — the
  // footer caption ("N nodes · M cables · T tiers · physical CDP/LLDP cabling in role tiers · click
  // a node …") kept quoting the FLEET totals while the diagram above it drew a subset, and the
  // legend's op census likewise. The sibling TopologyGraph footer counts what it drew.
  it("FE-16: the footer caption tracks what is DRAWN once a filter hides part of the fleet", async () => {
    vi.spyOn(api, "cableMap").mockResolvedValue({
      nodes: [
        node("core1", 0, "switch", "core", [{ name: "Gi0/1", peer: "acc1", peer_port: "Gi0/1", op_status: "up", is_pc: false }]),
        node("acc1", 1, "switch", "access", [{ name: "Gi0/1", peer: "core1", peer_port: "Gi0/1", op_status: "up", is_pc: false }]),
        node("ap1", 2, "ap", ""),
      ],
      cables: [cable("core1", "Gi0/1", "acc1", "Gi0/1"), cable("acc1", "Gi0/2", "ap1", "Gi0/1")],
      tiers: [["core1"], ["acc1"], ["ap1"]],
      summary: { n_nodes: 3, n_cables: 2, n_tiers: 3, op: { up: 2, down: 0, unknown: 0 } },
    } as never);
    const { container } = render(<CableMap snapId={1} />);
    await screen.findByText("core1");

    const footer = () => Array.from(container.querySelectorAll(".faint"))
      .find((e) => /physical CDP\/LLDP cabling/.test(e.textContent || ""))!.textContent!;
    expect(footer()).toMatch(/3 nodes · 2 cables/);          // unfiltered: the engine summary, verbatim

    fireEvent.click(screen.getByRole("button", { name: /Fabric only/i }));

    // the AP and its cable are gone from the picture — the caption must not keep claiming them
    expect(footer()).toMatch(/2 of 3 nodes/);
    expect(footer()).toMatch(/1 of 2 cables/);
  });

  it("selecting a cable also shows the panel, retargeting its key to the new selection", async () => {
    vi.spyOn(api, "cableMap").mockResolvedValue(model as never);
    const { container } = render(<CableMap snapId={1} />);
    await screen.findByText("core1");
    const cablePath = container.querySelector("svg path");
    expect(cablePath).not.toBeNull(); // the one core1<->acc1 cable rendered via the new anchor-delta helper
    fireEvent.click(cablePath!);

    const panel = container.querySelector(".tabfade");
    expect(panel).not.toBeNull();
    expect(panel!.textContent).toContain("Cable");
    expect(panel!.textContent).toContain("core1"); // endpoint host listed in the cable detail
  });
});
