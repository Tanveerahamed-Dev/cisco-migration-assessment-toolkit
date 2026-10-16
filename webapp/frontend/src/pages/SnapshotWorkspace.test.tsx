import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { deviceFixture, published, topologyFixture, trustFixture } from "../test/projectionFixtures";
import type { TopologyRows, TopologyTarget } from "./core/topologyData";
import SnapshotWorkspace from "./SnapshotWorkspace";

// Geometry has its own renderer checks. Keep the real loader, page assembler, coverage and
// dossier here, and expose only exact source-row selection through this lightweight canvas.
vi.mock("./core/NetworkCanvas", () => ({ NetworkCanvas: ({ rows, selected, select }: {
  rows: TopologyRows; selected: TopologyTarget | null; select: (target: TopologyTarget | null) => void;
}) => <div data-testid="native-canvas" data-selection={selected ? JSON.stringify(selected) : "none"}>
  {rows.nodes.map((node) => <button key={node.pointer} onClick={() => select({ list: "nodes", row: { index: node.index, pointer: node.pointer } })}>Select {node.host.state === "published" ? node.host.value : `node row ${node.index}`}</button>)}
  {rows.cables.filter((row) => row.a_nodes.items.length === 1 && row.b_nodes.items.length === 1).map((row) => <button key={row.pointer} onClick={() => select({ list: "cables", row: { index: row.index, pointer: row.pointer } })}>Select cable row {row.index}</button>)}
  <input aria-label="Canvas local state" defaultValue="" />
</div> }));
function Harness() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/snapshots/2")}>Switch snapshot</button><Routes><Route path="/snapshots/:id" element={<SnapshotWorkspace />} /></Routes></>;
}
function show(path = "/snapshots/1") { return render(<MemoryRouter initialEntries={[path]}><Harness /></MemoryRouter>); }
function serve(options: { device?: (sid: number, host: string) => object; trust?: (sid: number) => object; topology?: (sid: number) => object | Promise<object> } = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL(String(input), "http://localhost"), sid = Number(url.pathname.split("/")[3]);
    if (/^\/api\/snapshots\/\d+$/.test(url.pathname)) return new Response(JSON.stringify({ id: sid, campaign_id: 1, label: `Synthetic snapshot ${sid}`, uploaded_at: "2026-10-16T00:00:00Z" }));
    if (url.pathname === "/api/campaigns/1") return new Response(JSON.stringify({ id: 1, name: "Synthetic engagement", snapshots: [{ id: 1, label: "Synthetic snapshot 1" }, { id: 2, label: "Synthetic snapshot 2" }] }));
    if (url.pathname.endsWith("/ui-projection/topology")) return new Response(JSON.stringify(await (options.topology?.(sid) ?? topologyFixture(sid))));
    if (url.pathname.endsWith("/ui-projection/trust")) return new Response(JSON.stringify(options.trust?.(sid) ?? trustFixture(sid)));
    if (url.pathname.endsWith("/ui-projection/device")) return new Response(JSON.stringify(options.device?.(sid, url.searchParams.get("host")!) ?? deviceFixture(sid, url.searchParams.get("host")!)));
    throw new Error(`Forbidden legacy or unexpected request: ${url.pathname}`);
  });
}
const selectNode = () => fireEvent.click(screen.getByRole("button", { name: "Select synthetic-edge-a", exact: true }));
const TABS = ["Network", "Findings", "Inventory", "Plan", "Change", "Reports"];

describe("ADR-0008 native snapshot workspace", () => {
  afterEach(() => vi.restoreAllMocks());
  it("loads only Python topology and coverage, with six honest tabs and no legacy entry", async () => {
    const fetcher = serve(); const rendered = show(); await screen.findByTestId("native-canvas");
    const tabs = within(screen.getByRole("navigation", { name: "Snapshot tabs" }));
    expect(tabs.getAllByRole("button").map((button) => button.textContent)).toEqual(TABS);
    expect(tabs.getByRole("button", { name: "Network", exact: true })).toHaveAttribute("aria-current", "page");
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/ui-projection/")).map(([url]) => new URL(String(url), "http://localhost").pathname).sort()).toEqual([
      "/api/snapshots/1/ui-projection/topology", "/api/snapshots/1/ui-projection/trust",
    ]);
    expect(rendered.container.querySelector("iframe")).toBeNull();
    expect(screen.queryByRole("link", { name: /Scope|Explorer|Tools|AssessHub/i })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Evidence coverage" })).toHaveTextContent("blind spot");
  });
  it("keeps the same native canvas, selected subject and local state through all five reserved tabs", async () => {
    const fetcher = serve(); show(); const canvas = await screen.findByTestId("native-canvas"); selectNode();
    await screen.findByRole("region", { name: "Device identity" });
    fireEvent.change(screen.getByRole("textbox", { name: "Canvas local state" }), { target: { value: "retained zoom/search state" } });
    for (const name of TABS.slice(1)) {
      fireEvent.click(within(screen.getByRole("navigation", { name: "Snapshot tabs" })).getByRole("button", { name, exact: true }));
      expect(screen.getByRole("heading", { name, exact: true })).toBeInTheDocument();
      expect(screen.getByText("This tab is reserved for a subsequent reviewed increment.")).toBeInTheDocument();
      expect(canvas.closest("[hidden]")).toHaveAttribute("inert");
      fireEvent.click(screen.getByRole("button", { name: "Return to Network" }));
      expect(screen.getByTestId("native-canvas")).toBe(canvas);
      expect(canvas).toHaveAttribute("data-selection", JSON.stringify({ list: "nodes", row: { index: 0, pointer: "/cable_map/nodes/0" } }));
      expect(screen.getByRole("textbox", { name: "Canvas local state" })).toHaveValue("retained zoom/search state");
      expect(screen.getByRole("complementary", { name: "Device dossier" })).toHaveTextContent("synthetic-edge-a");
    }
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/ui-projection/topology?")).length).toBe(1);
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/ui-projection/device?")).length).toBe(1);
  });
  it("requests an exact published host, while a cable shows evidence without guessing a device", async () => {
    const fetcher = serve(); show(); await screen.findByTestId("native-canvas");
    fireEvent.click(screen.getByRole("button", { name: "Select cable row 0" }));
    expect(screen.getByRole("complementary", { name: "Selection details" })).toHaveTextContent("/cable_map/cables/0");
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("/device?"))).toBe(false);
    selectNode(); await screen.findByRole("region", { name: "Device identity" });
    const request = fetcher.mock.calls.find(([url]) => String(url).includes("/device?"))!;
    expect(new URL(String(request[0]), "http://localhost").searchParams.get("host")).toBe("synthetic-edge-a");
  });
  it("admits legitimate device-only limitations under the child's own evidence registry", async () => {
    serve({ device: (sid, host) => {
      const doc = deviceFixture(sid, host), caveat = { id: "device_only", owner: "synthetic.device.owner", applies_to: ["/devices/model"], text: "Synthetic device-only qualification" };
      return { ...doc, limitations: [caveat], payload: { ...doc.payload, identity: { ...doc.payload.identity, model: { ...published("Synthetic model"), caveats: [caveat.id] } } } };
    } });
    show(); await screen.findByTestId("native-canvas"); selectNode();
    await screen.findByText("Synthetic model"); fireEvent.click(screen.getByRole("button", { name: "Info for model", exact: true }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Synthetic device-only qualification");
    expect(screen.getByRole("dialog")).toHaveTextContent("synthetic.device.owner");
    expect(screen.getByRole("dialog")).toHaveTextContent(`sha256:${"a".repeat(64)}`);
  });
  it.each(["identity", "engine", "host"])("refuses a dossier with changed %s without substituting another device", async (change) => {
    serve({ device: (sid, host) => {
      const doc = deviceFixture(sid, host);
      if (change === "identity") return { ...doc, identity: { ...doc.identity, sha256: `sha256:${"b".repeat(64)}` } };
      if (change === "engine") return { ...doc, engine: { ...doc.engine, code_schema_version: "different" } };
      return { ...doc, payload: { ...doc.payload, host: "wrong-device" } };
    } });
    show(); await screen.findByTestId("native-canvas"); selectNode();
    const error = await screen.findByRole("alert"); expect(error).toHaveTextContent(change === "host" ? "different device" : "context changed");
    expect(screen.queryByRole("region", { name: "Device identity" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry device dossier" })).toBeInTheDocument();
  });
  it("opens a device list's evidence under its own native child context", async () => {
    serve({ device: (sid, host) => {
      const doc = deviceFixture(sid, host), caveat = { id: "device_interface_list", owner: "synthetic.device.list.owner", applies_to: ["/interfaces/rows"], text: "Synthetic interface-list qualification survives an empty collected list" };
      return { ...doc, limitations: [caveat], payload: { ...doc.payload, interfaces: { ...doc.payload.interfaces, rows: {
        ...doc.payload.interfaces.rows, source_list: { ...doc.payload.interfaces.rows.source_list, caveats: [caveat.id] } } } } };
    } });
    show(); await screen.findByTestId("native-canvas"); selectNode();
    await screen.findByRole("region", { name: "Device identity" });
    fireEvent.click(screen.getByText("Interfaces & routes", { exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Info for Device interfaces", exact: true }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Synthetic interface-list qualification survives an empty collected list");
    expect(screen.getByRole("dialog")).toHaveTextContent("/interfaces/rows");
    expect(screen.getByRole("dialog")).toHaveTextContent(`sha256:${"a".repeat(64)}`);
  });
  it.each(["identity", "engine"])("refuses coverage with changed %s while preserving the native map", async (change) => {
    serve({ trust: (sid) => {
      const doc = trustFixture(sid);
      return change === "identity" ? { ...doc, identity: { ...doc.identity, sha256: `sha256:${"b".repeat(64)}` } }
        : { ...doc, engine: { ...doc.engine, code_schema_version: "different" } };
    } });
    show(); await screen.findByTestId("native-canvas"); expect(await screen.findByRole("alert")).toHaveTextContent("Coverage belongs to a different snapshot context");
    expect(screen.queryByText("Review engine coverage and qualifications")).not.toBeInTheDocument();
  });
  it("keeps a trust-only qualification in the coverage document's own drawer", async () => {
    serve({ trust: (sid) => {
      const doc = trustFixture(sid), caveat = { id: "trust_only", owner: "synthetic.trust.owner", applies_to: ["/coverage_matrix/note"], text: "Synthetic trust-only qualification" };
      return { ...doc, limitations: [caveat], payload: { ...doc.payload, coverage_matrix: { ...doc.payload.coverage_matrix,
        note: { ...published("Synthetic qualified coverage"), caveats: [caveat.id] } } } };
    } });
    show(); await screen.findByTestId("native-canvas");
    fireEvent.click(await screen.findByText("Review engine coverage and qualifications"));
    fireEvent.click(screen.getByRole("button", { name: "Info for note", exact: true }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Synthetic trust-only qualification");
    expect(screen.getByRole("dialog")).toHaveTextContent("synthetic.trust.owner");
  });
  it.each([true, false])("preserves source-only custody guard without a tab (matching=%s)", async (matching) => {
    const fetcher = serve(), doc = topologyFixture();
    show(`/snapshots/1?${new URLSearchParams({ source: matching ? doc.identity.sha256 : `sha256:${"b".repeat(64)}`, source_bytes: String(doc.identity.bytes) })}`);
    if (matching) await screen.findByTestId("native-canvas");
    else { expect(await screen.findByRole("alert")).toHaveTextContent("different stored snapshot"); expect(screen.queryByTestId("native-canvas")).not.toBeInTheDocument(); }
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/ui-projection/")).every(([url]) => /\/ui-projection\/(topology|trust)\?/.test(String(url)))).toBe(true);
  });
  it.each(["source", "source_bytes"])("refuses an incomplete stored-byte reference containing only %s", async (name) => {
    serve(); const doc = topologyFixture();
    const query = new URLSearchParams({ [name]: name === "source" ? doc.identity.sha256 : String(doc.identity.bytes) });
    show(`/snapshots/1?${query}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("different stored snapshot");
    expect(screen.queryByTestId("native-canvas")).not.toBeInTheDocument();
  });
  it("binds the Classic door to the admitted projection, preserving row hints and removing only the native tab", async () => {
    serve(); const doc = topologyFixture(); show("/snapshots/1?tab=reports&ref=%2Fsynthetic%2F4&row=4");
    await screen.findByText("This tab is reserved for a subsequent reviewed increment.");
    const href = new URL(screen.getByRole("link", { name: "Classic view", exact: true }).getAttribute("href")!, "http://localhost");
    expect(href.pathname).toBe("/snapshots/1"); expect(href.searchParams.get("view")).toBe("overview");
    expect(href.searchParams.get("source")).toBe(doc.identity.sha256); expect(href.searchParams.get("source_bytes")).toBe(String(doc.identity.bytes));
    expect(href.searchParams.get("ref")).toBe("/synthetic/4"); expect(href.searchParams.get("row")).toBe("4");
    expect(href.searchParams.has("tab")).toBe(false);
  });
  it.each(["full", "source-only", "bytes-only"])("does not erase a refused %s custody guard through the Classic door", async (shape) => {
    serve(); const input = new URLSearchParams({ tab: "network" });
    if (shape !== "bytes-only") input.set("source", `sha256:${"b".repeat(64)}`);
    if (shape !== "source-only") input.set("source_bytes", "999");
    show(`/snapshots/1?${input}`); expect(await screen.findByRole("alert")).toHaveTextContent("different stored snapshot");
    const target = new URL(screen.getByRole("link", { name: "Classic view", exact: true }).getAttribute("href")!, "http://localhost");
    expect(target.searchParams.get("source")).toBe(input.get("source"));
    expect(target.searchParams.get("source_bytes")).toBe(input.get("source_bytes"));
    expect(target.searchParams.get("view")).toBe("overview"); expect(target.searchParams.has("tab")).toBe(false);
  });
  it("keeps an undrawn ambiguous bundle's exact member ports and qualifications reachable through lazy map evidence", async () => {
    serve({ topology: (sid) => {
      const doc = topologyFixture(sid), cable = doc.payload.cables.page.items[0];
      const caveat = { id: "synthetic_bundle_members", owner: "synthetic.bundle.owner", applies_to: ["/cable_map/cables/0/members"], text: "Synthetic member ports require physical confirmation." };
      const members = { ...cable.members, state: "published", caveats: [caveat.id], items: [{ index: 0, pointer: "/cable_map/cables/0/members/0",
        a_port: { ...published("Gi1/0/47"), subject: "/cable_map/cables/0/members/0/a_port" },
        b_port: { ...published("Gi1/0/48"), subject: "/cable_map/cables/0/members/0/b_port" } }] };
      const altered = { ...cable, ends: { ...cable.ends, value: { ...cable.ends.value, is_pc: true } }, members,
        a_nodes: { ...cable.a_nodes, items: [...cable.a_nodes.items, { index: 1, pointer: "/cable_map/nodes/1" }] } };
      return { ...doc, limitations: [caveat], payload: { ...doc.payload, cables: { ...doc.payload.cables, page: { ...doc.payload.cables.page, items: [altered] } } } };
    } });
    show(); await screen.findByTestId("native-canvas");
    expect(screen.queryByRole("button", { name: "Select cable row 0" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Map cables" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("All topology records and cable evidence", { exact: true }));
    const cables = await screen.findByRole("region", { name: "Map cables" });
    expect(cables).toHaveTextContent("/cable_map/cables/0");
    fireEvent.click(within(cables).getByText("members", { selector: "summary", exact: true }));
    expect(within(cables).getByText("Gi1/0/47", { exact: true })).toBeVisible();
    expect(within(cables).getByText("Gi1/0/48", { exact: true })).toBeVisible();
    expect(cables).toHaveTextContent("/cable_map/cables/0/members/0");
    fireEvent.click(within(cables).getByRole("button", { name: "Info for members", exact: true }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Synthetic member ports require physical confirmation.");
    expect(screen.getByRole("dialog")).toHaveTextContent("synthetic.bundle.owner");
    expect(screen.getByRole("dialog")).toHaveTextContent(`sha256:${"a".repeat(64)}`);
  });
  it("withholds an inconsistent initial topology page instead of drawing a partial success", async () => {
    serve({ topology: (sid) => { const doc = topologyFixture(sid); return { ...doc, payload: { ...doc.payload, nodes: {
      ...doc.payload.nodes, page: { ...doc.payload.nodes.page, returned: 1 } } } }; } });
    show(); expect(await screen.findByRole("alert")).toHaveTextContent("Projection page is incomplete or inconsistent");
    expect(screen.queryByTestId("native-canvas")).not.toBeInTheDocument();
  });
  it("clears selected subject and canvas state when changing snapshot", async () => {
    serve(); show(); const previous = await screen.findByTestId("native-canvas"); selectNode();
    fireEvent.change(screen.getByRole("textbox", { name: "Canvas local state" }), { target: { value: "old source" } });
    fireEvent.change(await screen.findByRole("combobox", { name: "Snapshot selector" }), { target: { value: "2" } });
    await waitFor(() => expect(screen.getByTestId("native-canvas")).not.toBe(previous));
    expect(screen.getByTestId("native-canvas")).toHaveAttribute("data-selection", "none");
    expect(screen.getByRole("textbox", { name: "Canvas local state" })).toHaveValue("");
    expect(screen.queryByRole("complementary", { name: "Device dossier" })).not.toBeInTheDocument();
  });
  it("ignores a late old topology response after snapshot navigation", async () => {
    let finish!: (value: object) => void;
    serve({ topology: (sid) => sid === 1 ? new Promise<object>((resolve) => { finish = resolve; }) : topologyFixture(sid) });
    show(); fireEvent.click(screen.getByRole("button", { name: "Switch snapshot" }));
    const current = await screen.findByTestId("native-canvas");
    await act(async () => { finish(topologyFixture(1)); });
    expect(screen.getByTestId("native-canvas")).toBe(current); expect(screen.getByRole("heading", { name: "Snapshot 2" })).toBeInTheDocument();
  });
  it("reports topology failure and retries only the native projection", async () => {
    let first = true;
    const fetcher = serve({ topology: (sid) => { if (first) { first = false; throw new Error("Synthetic missing topology"); } return topologyFixture(sid); } }); show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Synthetic missing topology");
    expect(screen.queryByTestId("native-canvas")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry snapshot" })); await screen.findByTestId("native-canvas");
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/ui-projection/")).every(([url]) => /\/ui-projection\/(topology|trust)\?/.test(String(url)))).toBe(true);
  });
});
