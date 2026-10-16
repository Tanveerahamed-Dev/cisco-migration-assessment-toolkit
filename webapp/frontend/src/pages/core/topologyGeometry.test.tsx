import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { topologyFixture, topologyNodeFixture, withheld } from "../../test/projectionFixtures";
import { initialTopologyRows, rowKey, type TopologyRows } from "./topologyData";
import { cableCurve, CHASSIS_WIDTH, chassisLinks, displayedNodes, forceTopologyLayout, matchesLoadedNode, publishedPortLabels } from "./topologyGeometry";
import { NetworkCanvas } from "./NetworkCanvas";

const fixtureRows = () => initialTopologyRows(topologyFixture() as never);

describe("Native topology geometry and interaction", () => {
  it("uses disposable force coordinates without mutating frozen projection rows or reading semantic tiers", () => {
    const rows = fixtureRows(), before = JSON.stringify(rows);
    const first = forceTopologyLayout(rows.nodes, rows.cables);
    expect(JSON.stringify(rows)).toBe(before);
    expect(Object.isFrozen(rows.nodes[0])).toBe(true);
    expect(rows.nodes[0]).not.toHaveProperty("x");
    expect(first).toEqual(forceTopologyLayout(rows.nodes, rows.cables));
    const changed = rows.nodes.map((node) => ({ ...node, role: { ...node.role, value: "access" },
      kind: { ...node.kind, value: "ap" }, collected: { ...node.collected, value: false } })) as typeof rows.nodes;
    expect(forceTopologyLayout(changed, rows.cables)).toEqual(first);
  });

  it("keeps empty and capped layouts finite and fits every rounded chassis within the extent", () => {
    expect(forceTopologyLayout([], [])).toEqual({ positions: new Map(), width: 1000, height: 600 });
    const many = Array.from({ length: 501 }, (_, index) => topologyNodeFixture(index)) as unknown as TopologyRows["nodes"];
    for (const nodes of [many.slice(0, 1), many.slice(0, 20), many]) {
      const layout = forceTopologyLayout(nodes, []);
      expect(layout.positions.size).toBe(Math.min(500, nodes.length));
      for (const position of layout.positions.values()) {
        expect(Number.isFinite(position.x) && Number.isFinite(position.y)).toBe(true);
        expect(position.x - CHASSIS_WIDTH / 2).toBeGreaterThan(0);
        expect(position.x + CHASSIS_WIDTH / 2).toBeLessThan(layout.width);
        expect(position.y).toBeGreaterThan(0);
        expect(position.y).toBeLessThan(layout.height);
      }
    }
  });

  it("draws exact reference joins and retains parallel source cable identities with separate anchors", () => {
    const rows = fixtureRows(), cable = rows.cables[0];
    const parallel = { ...cable, index: 9, pointer: "/cable_map/cables/9" };
    const layout = forceTopologyLayout(rows.nodes, [cable, parallel]);
    const drawn = chassisLinks(rows.nodes, [cable, parallel], layout.positions);
    expect(drawn.map(({ row }) => row)).toEqual([cable, parallel]);
    expect(drawn[0].a).not.toEqual(drawn[1].a);
    expect(drawn[0].b).not.toEqual(drawn[1].b);
    expect(drawn[0].path).not.toBe(drawn[1].path);
    const duplicate = { ...cable, a_nodes: { ...cable.a_nodes, items: [...cable.a_nodes.items, ...cable.a_nodes.items] } };
    const missing = { ...cable, a_nodes: { ...cable.a_nodes, items: [{ index: 999, pointer: "/missing" }] } };
    expect(chassisLinks(rows.nodes, [duplicate, missing], layout.positions)).toEqual([]);
    expect(forceTopologyLayout(rows.nodes, [duplicate, missing])).toEqual(forceTopologyLayout(rows.nodes, []));
  });

  it("caps drawn link rows and never substitutes a structural or withheld port claim", () => {
    const rows = fixtureRows(), cable = rows.cables[0];
    const links = Array.from({ length: 1001 }, (_, index) => ({ ...cable, index, pointer: `/cable_map/cables/${index}` }));
    const layout = forceTopologyLayout(rows.nodes, links);
    expect(chassisLinks(rows.nodes, links, layout.positions)).toHaveLength(1000);
    expect(publishedPortLabels(cable)).toEqual({ a: "Gi1", b: "Gi2" });
    expect(publishedPortLabels(rows.structural_links[0])).toBeNull();
    expect(publishedPortLabels({ ...cable, ends: withheld() } as never)).toBeNull();
    expect(cableCurve({ x: 1, y: 2 }, { x: 9, y: 10 }, true)).toBe("M1,2 C5,2 5,10 9,10");
    expect(cableCurve({ x: 1, y: 2 }, { x: 9, y: 10 }, false)).toBe("M1,2 C1,6 9,6 9,10");
  });

  it("treats collected-only and name search as presentation of published loaded fields", () => {
    const rows = fixtureRows();
    expect(displayedNodes(rows.nodes, true)).toEqual([rows.nodes[0]]);
    expect(displayedNodes(rows.nodes, false)).toEqual(rows.nodes);
    expect(displayedNodes([{ ...rows.nodes[0], collected: withheld() } as never], true)).toEqual([]);
    expect(matchesLoadedNode(rows.nodes[0], " EDGE-A ")).toBe(true);
    expect(matchesLoadedNode(rows.nodes[0], "192.0.2.40")).toBe(false);
    expect(matchesLoadedNode(rows.nodes[0], " ")).toBe(false);
    expect(matchesLoadedNode({ ...rows.nodes[0], host: withheld() } as never, "edge")).toBe(false);
  });

  it("keeps source styles, exact selection and keyboard navigation available", () => {
    const document = topologyFixture(), rows = initialTopologyRows(document as never), select = vi.fn();
    render(<NetworkCanvas rows={rows} legend={document.payload.legend as never} selected={null} select={select} pathNodes={new Set([rowKey(rows.nodes[0])])} />);
    const node = screen.getByRole("button", { name: "Inspect node synthetic-peer-b: Synthetic uncollected peer" });
    expect(node).toHaveClass("topology-tone-muted");
    expect(node).toHaveAttribute("data-stroke", "dotted");
    fireEvent.keyDown(node, { key: "Enter" });
    expect(select).toHaveBeenLastCalledWith({ list: "nodes", row: { index: 1, pointer: "/cable_map/nodes/1" } });
    const cable = screen.getByRole("button", { name: /Inspect cable row 0/ });
    expect(cable.tagName.toLowerCase()).toBe("path");
    fireEvent.keyDown(cable, { key: " " });
    expect(select).toHaveBeenLastCalledWith({ list: "cables", row: { index: 0, pointer: "/cable_map/cables/0" } });
    const map = screen.getByRole("img", { name: "Engine topology diagram" }), initial = map.getAttribute("viewBox")!;
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.keyDown(map, { key: "ArrowRight" });
    expect(map.getAttribute("viewBox")).not.toBe(initial);
    fireEvent.keyDown(map, { key: "0" });
    expect(map).toHaveAttribute("viewBox", initial);
    fireEvent.keyDown(map, { key: "+" });
    expect(map.getAttribute("viewBox")).not.toBe(initial);
    fireEvent.click(screen.getByRole("button", { name: "Fit map" }));
    expect(map).toHaveAttribute("viewBox", initial);
    fireEvent.change(screen.getByLabelText("Find device name"), { target: { value: "peer-b" } });
    expect(node).toHaveClass("name-match");
    fireEvent.change(screen.getByLabelText("Find device name"), { target: { value: "192.0.2.40" } });
    expect(screen.getByRole("status")).toHaveTextContent("No matching device name in the displayed map");
    expect(node).not.toHaveClass("name-match");
  });

  it("filters only the picture while leaving the immutable evidence and selection identity untouched", () => {
    const document = topologyFixture(), rows = initialTopologyRows(document as never), select = vi.fn();
    render(<NetworkCanvas rows={rows} legend={document.payload.legend as never} selected={{ list: "nodes", row: { index: 1, pointer: "/cable_map/nodes/1" } }} select={select} />);
    fireEvent.click(screen.getByLabelText("Collected devices only"));
    expect(screen.queryByRole("button", { name: /Inspect node synthetic-peer-b/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Inspect cable row/ })).not.toBeInTheDocument();
    expect(rows.nodes).toHaveLength(2);
    expect(rows.cables).toHaveLength(1);
    expect(select).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Collected devices only"));
    expect(screen.getByRole("button", { name: /Inspect node synthetic-peer-b/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(screen.getByLabelText("Additional relationship view"), { target: { value: "structural_links" } });
    expect(screen.queryByRole("button", { name: /Inspect cable row/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Inspect structural link row/ })).toBeInTheDocument();
  });

  it("keeps pending layers and overlays unavailable and hatches only an explicit uncollected flag", () => {
    const document = topologyFixture(), rows = initialTopologyRows(document as never);
    render(<NetworkCanvas rows={rows} legend={document.payload.legend as never} selected={null} select={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Physical", exact: true })).toHaveAttribute("aria-pressed", "true");
    for (const name of ["L2 · VLAN", "L3 · routing", "Health", "Lifecycle", "Findings"]) {
      expect(screen.getByRole("button", { name, exact: true })).toBeDisabled();
    }
    expect(screen.getByText(/await their Python-owned projection contracts/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Inspect node synthetic-peer-b/ }).querySelector("rect[data-uncollected]")).toHaveAttribute("fill", expect.stringMatching(/^url\(#.+\)$/));
    expect(screen.getByRole("button", { name: /Inspect node synthetic-edge-a/ }).querySelector("rect[data-uncollected]")).toBeNull();
    expect(screen.getByLabelText("Map legend")).toHaveTextContent("Not collected (source flag)");
  });
});
