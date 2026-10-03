import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { pathFixture, topologyFixture } from "../../test/projectionFixtures";
import { EvidenceProvider } from "./ProjectionEvidence";
import { TopologyPaths } from "./TopologyPaths";

const show = (document = topologyFixture()) => render(<EvidenceProvider identity={document.identity as never} limitations={[]}>
  <TopologyPaths document={document as never} reload={vi.fn()} /></EvidenceProvider>);

describe("Engine-owned topology and path screen", () => {
  afterEach(() => vi.restoreAllMocks());
  it("shows off-scan facts and follows the supplied node/cable styles", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    show();
    await screen.findByText(/All projected list pages loaded/);
    const peer = screen.getByRole("button", { name: "Inspect node synthetic-peer-b: Synthetic uncollected peer" });
    expect(peer).toHaveClass("topology-tone-muted");
    expect(peer).toHaveAttribute("data-stroke", "dotted");
    fireEvent.click(peer);
    const inspector = screen.getByRole("region", { name: "Topology record details" });
    expect(within(inspector).getByText("No")).toBeInTheDocument();
    fireEvent.click(within(inspector).getByRole("button", { name: "Evidence for collected" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("synthetic.owner");
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("retains ambiguous cable records without drawing a hostname-derived connection", async () => {
    const document = topologyFixture();
    document.payload.cables.page.items[0].a_nodes.items.push({ index: 1, pointer: "/cable_map/nodes/1" });
    show(document); await screen.findByText(/All projected list pages loaded/);
    expect(screen.queryByRole("button", { name: /Inspect cable row/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Links without a unique engine-published join/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Topology evidence lists"));
    expect(screen.getByRole("button", { name: "Inspect cable map row 0" })).toBeInTheDocument();
  });
  it("shows complete owner path detail and highlights only its published pointer join", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      if (!url.pathname.endsWith("/ui-projection/topology/path")) throw new Error("Unexpected legacy request");
      return new Response(JSON.stringify(pathFixture(1, url.searchParams.get("src_ip")!, url.searchParams.get("dst_ip")!)));
    });
    show(); await screen.findByText(/All projected list pages loaded/);
    fireEvent.change(screen.getByLabelText("Source IP"), { target: { value: "192.0.2.10" } });
    fireEvent.change(screen.getByLabelText("Destination IP"), { target: { value: "198.51.100.10" } });
    fireEvent.click(screen.getByRole("button", { name: "Investigate path" }));
    const result = await screen.findByRole("region", { name: "Route-model result" });
    expect(result).toHaveTextContent("synthetic_partial_drop");
    expect(result).toHaveTextContent("different-raw-host-label");
    expect(result).toHaveTextContent("observed_discard");
    expect(result).toHaveTextContent("egress_interface_not_observed");
    expect(result).toHaveTextContent("does not prove live traffic");
    expect(screen.getByRole("button", { name: "Inspect node synthetic-edge-a: Synthetic engine node presentation" })).toHaveClass("path-node");
    expect(screen.getByRole("button", { name: "Inspect node synthetic-peer-b: Synthetic uncollected peer" })).not.toHaveClass("path-node");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("clears old path highlights immediately on input change and rejects late old responses", async () => {
    let resolveOld!: (value: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise((resolve) => { resolveOld = resolve; }));
    show(); await screen.findByText(/All projected list pages loaded/);
    fireEvent.change(screen.getByLabelText("Source IP"), { target: { value: "192.0.2.10" } });
    fireEvent.change(screen.getByLabelText("Destination IP"), { target: { value: "198.51.100.10" } });
    fireEvent.click(screen.getByRole("button", { name: "Investigate path" }));
    await waitFor(() => expect(resolveOld).toBeDefined());
    fireEvent.change(screen.getByLabelText("Destination IP"), { target: { value: "203.0.113.10" } });
    await act(async () => resolveOld(new Response(JSON.stringify(pathFixture()))));
    expect(screen.queryByRole("region", { name: "Route-model result" })).not.toBeInTheDocument();
    expect(document.querySelectorAll(".path-node")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Investigate path" })).toBeEnabled();
  });
  it("clears path/source presentation when the server identifies different snapshot authority", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...pathFixture(), identity: { ...pathFixture().identity, bytes: 99 } })));
    show(); await screen.findByText(/All projected list pages loaded/);
    fireEvent.change(screen.getByLabelText("Source IP"), { target: { value: "192.0.2.10" } });
    fireEvent.change(screen.getByLabelText("Destination IP"), { target: { value: "198.51.100.10" } });
    fireEvent.click(screen.getByRole("button", { name: "Investigate path" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Stored snapshot authority or context changed");
    expect(screen.queryByRole("img", { name: "Engine topology diagram" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Route-model result" })).not.toBeInTheDocument();
  });
});
