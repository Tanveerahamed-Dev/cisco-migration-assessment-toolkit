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
  it("shows a failure-impact measure the engine publishes only as a lower bound as ≥ N, never the bare count", async () => {
    // The bounded row as ui_projection._topology_impact emits it for a switch cabled to an uncollected neighbour
    // (_impact_peers): every measure cites the bound's witness (the cable row), whatever its state. High and each
    // positive count stay published as lower bounds; each zero count is withheld as not collected with the bound's
    // zero reason, because a lower bound of 0 is not a measurement of none. The non-measures (host,
    // off_scan_gw_vlans, detail) cite no witness, and a per-VLAN detail stays published.
    const document = topologyFixture();
    const row = document.payload.failure_impact.page.items[0] as any;
    const witness = { pointer: "/cable_map/cables/0", role: "witness" };
    const ZERO = "not collected: this row cannot account for endpoints behind 1 uncollected neighbour(s): the stored cable "
      + "map cables this switch to 1 peer(s) it does not show as collected, so this 0 is only a lower bound, not a "
      + "measurement of none";
    const cell = (field: string, value: unknown, measure: boolean) => ({ state: "published", value,
      subject: `/failure_impact/0/${field}`, basis: `analyze.compute_failure_impact:failure_impact[].${field}`,
      refs: [{ pointer: `/failure_impact/0/${field}`, role: "subject" }, ...(measure ? [witness] : [])] });
    const heldZero = (field: string) => ({ ...cell(field, null, true), state: "not_collected", reason: ZERO });
    Object.assign(row, {
      host: cell("host", "synthetic-edge-a", false), severity: cell("severity", "High", true),
      vlans_impacted: cell("vlans_impacted", 3, true), stranded: cell("stranded", 42, true), hard: cell("hard", 2, true),
      backup: heldZero("backup"), fhrp: heldZero("fhrp"), off_scan_gw_vlans: cell("off_scan_gw_vlans", 0, false),
      detail: cell("detail", "VLAN 10: Hard partition (42 ep)", false),
    });
    show(document); await screen.findByText(/All projected list pages loaded/);
    fireEvent.click(screen.getByText("Topology evidence lists"));
    const list = screen.getByRole("region", { name: "Failure impact" });
    expect(within(list).queryByText("42")).toBeNull();
    const bounds = Array.from(list.querySelectorAll('[data-impact="lower_bound"]'));
    expect(bounds.map((bound) => bound.textContent)).toEqual([      // the four published measures, in row order
      expect.stringContaining("≥ High"), expect.stringContaining("≥ 3"), expect.stringContaining("≥ 42"),
      expect.stringContaining("≥ 2")]);
    expect(bounds[2].getAttribute("title")).toMatch(/At least 42: a lower bound, not an exact measurement/);
    expect(bounds[2].getAttribute("title")).toContain("the record at /cable_map/cables/0");
    // the reason is a visible line beside the value, as a withheld cell's reason is, never hover-only
    const reasons = list.querySelectorAll('[data-impact="lower_bound_reason"]');
    expect(reasons).toHaveLength(4);
    expect(reasons[2]).toHaveTextContent(/^At least 42: a lower bound, not an exact measurement\. Why: .*\/cable_map\/cables\/0/);
    // the held zeros keep their state and reason, never a 0; the unbounded non-measure 0 stays a 0
    expect(within(list).getAllByText(ZERO)).toHaveLength(2);
    expect(within(list).getAllByText("0")).toHaveLength(1);
    expect(within(list).getByText("VLAN 10: Hard partition (42 ep)")).toBeInTheDocument();
    // the same row in the inspector reads the same way
    fireEvent.click(within(list).getByRole("button", { name: "Inspect failure impact row 0" }));
    const inspector = screen.getByRole("region", { name: "Topology record details" });
    expect(inspector.querySelectorAll('[data-impact="lower_bound"]')).toHaveLength(4);
    expect(within(inspector).queryByText("42")).toBeNull();
  });
  it("keeps a witness on a failure-impact non-measure plain: off_scan_gw_vlans is never shown as a lower bound", async () => {
    // The component-level negative control for projectionImpactBound's measure gate (ImpactValue.test.tsx covers the
    // helper alone). _topology_impact cites a bound's witnesses on the measures only, so a witness on the off-scan
    // count would mean something else, never "only a minimum": it renders as its plain published value, in the list
    // and in the inspector. The same witness on the stranded measure of the same row is the control.
    const document = topologyFixture();
    const row = document.payload.failure_impact.page.items[0] as any;
    const witness = { pointer: "/cable_map/cables/0", role: "witness" };
    row.off_scan_gw_vlans = { ...row.off_scan_gw_vlans, value: 3,
      refs: [{ pointer: "/failure_impact/0/off_scan_gw_vlans", role: "subject" }, witness] };
    row.stranded = { ...row.stranded, value: 42, refs: [{ pointer: "/failure_impact/0/stranded", role: "subject" }, witness] };
    show(document); await screen.findByText(/All projected list pages loaded/);
    fireEvent.click(screen.getByText("Topology evidence lists"));
    const factIn = (region: HTMLElement, label: string) =>
      within(region).getByRole("button", { name: `Evidence for ${label}` }).closest(".projection-fact") as HTMLElement;
    const list = screen.getByRole("region", { name: "Failure impact" });
    const offScan = factIn(list, "off scan gw vlans");
    expect(within(offScan).getByText("3")).toBeInTheDocument();
    expect(offScan.querySelector("[data-impact]")).toBeNull();
    expect(offScan).not.toHaveTextContent("≥");
    expect(offScan).not.toHaveTextContent(/lower bound|At least/);
    // the control: the same witness on a measure of the same row is a lower bound
    expect(factIn(list, "stranded").querySelector('[data-impact="lower_bound"]')).toHaveTextContent("≥ 42");
    expect(list.querySelectorAll('[data-impact="lower_bound"]')).toHaveLength(1);
    // the inspector reads the same row the same way
    fireEvent.click(within(list).getByRole("button", { name: "Inspect failure impact row 0" }));
    const inspector = screen.getByRole("region", { name: "Topology record details" });
    const inspected = factIn(inspector, "off scan gw vlans");
    expect(within(inspected).getByText("3")).toBeInTheDocument();
    expect(inspected.querySelector("[data-impact]")).toBeNull();
    expect(factIn(inspector, "stranded").querySelector('[data-impact="lower_bound"]')).toHaveTextContent("≥ 42");
  });
  it("applies the lower-bound mark only to the failure-impact list: a witness on another list's fact stays plain", async () => {
    // No other topology list carries a measure-named fact today, so the list gate is defensive; this proves it is the
    // gate, not the field name, that keeps a witness-carrying fact of another list plain. A witness there means
    // something else (an unreadable source row, an ambiguous join), never "only a minimum".
    const document = topologyFixture();
    const refs = [{ pointer: "/cable_map/nodes/0", role: "subject" }, { pointer: "/cable_map/cables/0", role: "witness" }];
    const node = document.payload.nodes.page.items[0] as any;
    node.stranded = { ...node.collected, value: 41, refs };
    // the control: the same witness-carrying fact on a failure-impact row is a lower bound
    const row = document.payload.failure_impact.page.items[0] as any;
    row.stranded = { ...row.stranded, value: 42, refs };
    show(document); await screen.findByText(/All projected list pages loaded/);
    fireEvent.click(screen.getByText("Topology evidence lists"));
    const nodes = screen.getByRole("region", { name: "Nodes" });
    expect(within(nodes).getByText("41")).toBeInTheDocument();
    expect(nodes.querySelector('[data-impact="lower_bound"], [data-impact="lower_bound_reason"]')).toBeNull();
    const impact = screen.getByRole("region", { name: "Failure impact" });
    expect(within(impact).queryByText("42")).toBeNull();
    expect(impact.querySelector('[data-impact="lower_bound"]')).toHaveTextContent("≥ 42");
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
