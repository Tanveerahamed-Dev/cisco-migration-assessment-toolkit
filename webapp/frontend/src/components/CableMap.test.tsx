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
