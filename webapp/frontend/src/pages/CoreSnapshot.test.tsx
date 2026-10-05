import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import CoreSnapshot from "./CoreSnapshot";
import { overviewFixture, overviewRollupsFixture, trustFixture, inventoryFixture, findingsFixture, deviceFixture, findingsRollupFixture, coverageRollupFixture, coverageAxisFixture, published, topologyFixture } from "../test/projectionFixtures";

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
    expect(screen.getByRole("heading", { name: "Insufficient Data" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic readiness inputs were not collected")).toBeInTheDocument();
    expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
  });
  it("shows the owner's health partition and move-group checks in supplied order with source qualifications", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/overview?") ? overviewRollupsFixture() : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    const bands = screen.getAllByRole("article").filter((row) => row.getAttribute("aria-label")?.endsWith(" health band"));
    expect(bands.map((row) => row.getAttribute("aria-label"))).toEqual([
      "Excellent health band", "Good health band", "Fair health band", "Poor health band", "Critical health band", "Insufficient Data health band",
    ]);
    const poor = screen.getByRole("article", { name: "Poor health band" });
    expect(within(poor).getByText("0")).toBeInTheDocument();
    expect(within(poor).getByText("Collected, empty")).toBeInTheDocument();
    expect(within(poor).queryByRole("link")).not.toBeInTheDocument();
    const criticalLink = within(screen.getByRole("article", { name: "Critical health band" })).getByRole("link", { name: "edge/a~b ↗" });
    expect(new URL(criticalLink.getAttribute("href")!, "http://localhost").searchParams.get("host")).toBe("edge/a~b");
    const groupRows = screen.getAllByRole("group").filter((row) => row.getAttribute("aria-label")?.startsWith("Move-group source row"));
    expect(groupRows.map((row) => row.getAttribute("aria-label"))).toEqual(["Move-group source row 3", "Move-group source row 0"]);
    const group = within(groupRows[0]);
    expect(group.getByText("CAUTION")).toBeInTheDocument();
    expect(group.getByText("0")).toBeInTheDocument();
    expect(group.getByText("6")).toBeInTheDocument();
    fireEvent.click(group.getByText("Readiness checks and evidence"));
    expect(group.getAllByText(/Synthetic check [AB]/).map((node) => node.textContent)).toEqual(["Synthetic check B", "Synthetic check A"]);
    expect(group.getByText("Rollback")).toBeInTheDocument();
    fireEvent.click(group.getByRole("button", { name: "Qualifications for endpoints" }));
    const drawer = screen.getByRole("dialog");
    expect(drawer).toHaveTextContent("not distinct endpoints across a move group");
    expect(drawer).toHaveTextContent("/migration_readiness/3/endpoints");
    expect(drawer).toHaveTextContent("/move_groups/3/endpoints");
    expect(drawer).toHaveTextContent(`sha256:${"a".repeat(64)}`);
    expect(screen.queryByText(/complete health-band partition is not published/)).not.toBeInTheDocument();
    expect(screen.getByText(/Design-decision details are available in Tools/)).toBeInTheDocument();
  });
  it("keeps canonical health contradictions withheld without band counts or host links", async () => {
    const doc = overviewFixture();
    const failed = { state: "unverified", value: null, reason: "Synthetic canonical health contradiction", subject: "/health_scores", refs: [], basis: "ssot.reconcile" };
    const altered = { ...doc, payload: { ...doc.payload, fleet_health: { ...doc.payload.fleet_health,
      bands: doc.payload.fleet_health.bands.map((band) => ({ ...band, n: failed, hosts: failed })) } } };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/overview?") ? altered : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    for (const band of ["Critical", "Poor"]) {
      const row = within(screen.getByRole("article", { name: `${band} health band` }));
      expect(row.getAllByText("Unverified")).toHaveLength(2);
      expect(row.getAllByText("Synthetic canonical health contradiction")).toHaveLength(2);
      expect(row.queryByText("0")).not.toBeInTheDocument();
      expect(row.queryByRole("link")).not.toBeInTheDocument();
    }
  });
  it("shows uncollected rollups as blind spots without zero bands or a READY group", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/overview?") ? overviewFixture() : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    const critical = within(screen.getByRole("article", { name: "Critical health band" }));
    expect(critical.getAllByText("Not collected")).toHaveLength(2);
    expect(critical.queryByText("0")).not.toBeInTheDocument();
    expect(critical.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic readiness inputs were not collected")).toBeInTheDocument();
    expect(screen.queryByText("READY")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Move-group source row/ })).not.toBeInTheDocument();
  });
  it("preserves an unverified move-group label and withheld readiness rather than inventing a verdict", async () => {
    const doc = overviewRollupsFixture();
    const failed = { state: "unverified", value: null, reason: "Synthetic label does not match the move-group owner", subject: "/migration_readiness/3", refs: [], basis: "synthetic.owner" };
    const row = doc.payload.readiness.groups.page.items[0];
    const altered = { ...doc, payload: { ...doc.payload, readiness: { groups: { ...doc.payload.readiness.groups,
      source_list: { ...doc.payload.readiness.groups.source_list, state: "unverified", reason: failed.reason },
      page: { ...doc.payload.readiness.groups.page, total: 1, returned: 1, items: [{ ...row,
      group: failed, readiness: failed, switches: failed, endpoints: failed, n_fail: failed, n_warn: failed,
      checks: { ...row.checks, state: "unverified", reason: failed.reason, items: [] } }] } } } } };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/overview?") ? altered : { available: false })));
    show(); await screen.findByText("Synthetic fleet needs review");
    const group = within(screen.getByRole("group", { name: "Move-group source row 3" }));
    expect(group.getAllByText("Unverified").length).toBeGreaterThan(0);
    expect(group.queryByText("READY")).not.toBeInTheDocument();
    expect(group.queryByText("0")).not.toBeInTheDocument();
    expect(group.queryByRole("link")).not.toBeInTheDocument();
    expect(group.queryByText("Synthetic group B")).not.toBeInTheDocument();
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
  it("opens the fifth Topology & Paths tab through the projection without a legacy graph or snapshot fetch", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/ui-projection/overview?")) return new Response(JSON.stringify(overviewFixture()));
      if (url.includes("/ui-projection/topology?")) return new Response(JSON.stringify(topologyFixture()));
      if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
      throw new Error(`Unexpected legacy request: ${url}`);
    });
    show(); await screen.findByText("Synthetic fleet needs review");
    fireEvent.click(screen.getByRole("link", { name: "Topology & Paths" }));
    await screen.findByRole("img", { name: "Engine topology diagram" });
    expect(screen.getByRole("heading", { name: "Investigate an IP path" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Topology & Paths" })).toHaveLength(1);
    expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
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
  describe.each([
    { view: "inventory", path: "/snapshots/1?view=inventory", label: "Finding severity for edge/a~b" },
    { view: "device", path: "/snapshots/1?view=device&host=edge%2Fa%7Eb", label: "Device finding severity" },
  ] as const)("$view finding rollup", ({ view, path, label }) => {
    function serve(rollup: ReturnType<typeof findingsRollupFixture>) {
      const document = view === "inventory" ? inventoryFixture(1, rollup) : deviceFixture(1, "edge/a~b", rollup);
      return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes(`/ui-projection/${view}?`)) return new Response(JSON.stringify(document));
        if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
        throw new Error(`Unexpected non-projection request: ${url}`);
      });
    }
    it("renders supplied worst severity and ordered counts with their own evidence", async () => {
      const fetcher = serve(findingsRollupFixture());
      show(path);
      const rollup = within(await screen.findByRole("group", { name: label }));
      const worst = rollup.getByRole("button", { name: "Evidence for Worst finding severity" }).closest(".projection-fact")! as HTMLElement;
      const counts = rollup.getByRole("button", { name: "Evidence for Findings by severity" }).closest(".projection-fact")! as HTMLElement;
      expect(within(worst).getByText("High", { exact: true })).toBeInTheDocument();
      expect(within(worst).queryByText("Critical", { exact: true })).not.toBeInTheDocument();
      expect(within(counts).getAllByRole("term").map((node) => node.textContent)).toEqual(["Critical", "High", "Medium", "Low", "Info"]);
      expect(within(counts).getAllByRole("definition").map((node) => node.textContent)).toEqual(["0", "2", "0", "1", "0"]);
      expect(within(counts).getAllByText("0", { exact: true })).toHaveLength(3);
      fireEvent.click(within(counts).getByRole("button", { name: "Evidence for Findings by severity" }));
      let drawer = screen.getByRole("dialog");
      expect(drawer).toHaveTextContent("synthetic.owner:device_findings");
      expect(drawer).toHaveTextContent("/punchlist/7");
      expect(drawer).toHaveTextContent("/devices/edge~1a~0b");
      expect(drawer).toHaveTextContent(`sha256:${"a".repeat(64)}`);
      fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
      fireEvent.click(within(worst).getByRole("button", { name: "Evidence for Worst finding severity" }));
      drawer = screen.getByRole("dialog");
      expect(drawer).toHaveTextContent("High");
      expect(drawer).toHaveTextContent("/punchlist/7");
      expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
    });
    it.each([
      ["unverified", "Unverified", "Synthetic canonical finding custody is missing or malformed"],
      ["not_collected", "Not collected", "Synthetic canonical finding custody reports incomplete capture"],
      ["configless", "Not collected", "Synthetic running configuration was not collected"],
    ] as const)("keeps %s facts withheld without inferred zeros or a severity", async (mode, state, reason) => {
      serve(findingsRollupFixture(mode)); show(path);
      const rollup = within(await screen.findByRole("group", { name: label }));
      expect(rollup.getAllByText(state, { exact: true })).toHaveLength(2);
      expect(rollup.getAllByText(reason, { exact: true })).toHaveLength(2);
      expect(rollup.queryByText("0", { exact: true })).not.toBeInTheDocument();
      expect(rollup.queryByText("High", { exact: true })).not.toBeInTheDocument();
      expect(rollup.queryByRole("definition")).not.toBeInTheDocument();
      fireEvent.click(rollup.getByRole("button", { name: "Evidence for Findings by severity" }));
      const drawer = screen.getByRole("dialog");
      expect(drawer).toHaveTextContent(reason);
      expect(drawer).toHaveTextContent("/devices/edge~1a~0b");
      expect(drawer).toHaveTextContent("synthetic.owner:device_findings");
    });
    it("keeps assessed-empty worst severity empty while showing five published zeros", async () => {
      serve(findingsRollupFixture("assessed_empty")); show(path);
      const rollup = within(await screen.findByRole("group", { name: label }));
      const worst = rollup.getByRole("button", { name: "Evidence for Worst finding severity" }).closest(".projection-fact")! as HTMLElement;
      const counts = rollup.getByRole("button", { name: "Evidence for Findings by severity" }).closest(".projection-fact")! as HTMLElement;
      expect(within(worst).getByText("Collected, empty")).toBeInTheDocument();
      expect(within(worst).getByText("Synthetic captured assessment has no findings")).toBeInTheDocument();
      expect(within(worst).queryByText("0", { exact: true })).not.toBeInTheDocument();
      expect(within(worst).queryByText("Info", { exact: true })).not.toBeInTheDocument();
      expect(within(counts).getByText("Published", { exact: true })).toBeInTheDocument();
      expect(within(counts).getAllByRole("term").map((node) => node.textContent)).toEqual(["Critical", "High", "Medium", "Low", "Info"]);
      expect(within(counts).getAllByRole("definition").map((node) => node.textContent)).toEqual(["0", "0", "0", "0", "0"]);
      expect(within(counts).getAllByText("0", { exact: true })).toHaveLength(5);
    });
  });
  it.each(["unverified", "not_collected", "configless"] as const)("retains independently paginated finding references while the rollup is %s", async (mode) => {
    const document = deviceFixture(1, "edge/a~b", findingsRollupFixture(mode));
    const qualification = { id: "findings_without_running_config", owner: "synthetic.owner:exact_host_refs", applies_to: ["/device/findings"],
      text: "Synthetic observed references do not establish assessed severity" };
    const references = { pointer: "/findings", source_list: { state: "published", subject: "/punchlist", refs: [],
      basis: "synthetic.owner:exact_host_refs", caveats: [qualification.id] },
      page: { offset: 0, limit: 1, returned: 1, total: 2, has_more: true, items: [{ index: 7, pointer: "/punchlist/7" }] } };
    const current = { ...document, limitations: [qualification], payload: { ...document.payload, findings: references } };
    const next = { ...references, page: { offset: 1, limit: 1, returned: 1, total: 2, has_more: false, items: [{ index: 93, pointer: "/punchlist/93" }] } };
    const { payload: _payload, ...envelope } = current;
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/device/lists?")) return new Response(JSON.stringify({ ...envelope, list: next }));
      if (url.includes("/device?")) return new Response(JSON.stringify(current));
      if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
      throw new Error(`Unexpected non-projection request: ${url}`);
    });
    show("/snapshots/1?view=device&host=edge%2Fa%7Eb");
    const referencesRegion = await screen.findByRole("region", { name: "Device finding references" });
    const first = within(referencesRegion).getByRole("link", { name: "Open referenced finding ↗" });
    let query = new URL(first.getAttribute("href")!, "http://localhost").searchParams;
    expect(query.get("ref")).toBe("/punchlist/7"); expect(query.get("row")).toBe("7");
    expect(query.get("source")).toBe(`sha256:${"a".repeat(64)}`); expect(query.get("source_bytes")).toBe("42");
    fireEvent.click(within(referencesRegion).getByRole("button", { name: "Evidence for Device finding references" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("synthetic.owner:exact_host_refs");
    fireEvent.click(screen.getByRole("button", { name: "Close evidence" }));
    fireEvent.click(within(referencesRegion).getByRole("button", { name: "Qualifications for Device finding references" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(qualification.text);
    fireEvent.click(screen.getByRole("button", { name: "Close evidence" }));
    fireEvent.click(within(referencesRegion).getByRole("button", { name: "Next Device finding references page" }));
    await within(referencesRegion).findByText("Finding source index 93");
    expect(within(referencesRegion).queryByText("Finding source index 7")).not.toBeInTheDocument();
    query = new URL(within(referencesRegion).getByRole("link", { name: "Open referenced finding ↗" }).getAttribute("href")!, "http://localhost").searchParams;
    expect(query.get("ref")).toBe("/punchlist/93"); expect(query.get("row")).toBe("93");
    expect(query.get("source")).toBe(`sha256:${"a".repeat(64)}`);
    const requested = fetcher.mock.calls.map(([input]) => String(input)).find((url) => url.includes("/device/lists?"))!;
    const pageQuery = new URL(requested, "http://localhost").searchParams;
    expect(pageQuery.get("pointer")).toBe("/findings"); expect(pageQuery.get("offset")).toBe("1"); expect(pageQuery.get("host")).toBe("edge/a~b");
    const rollup = within(screen.getByRole("group", { name: "Device finding severity" }));
    expect(rollup.getAllByText(mode === "unverified" ? "Unverified" : "Not collected", { exact: true })).toHaveLength(2);
    expect(rollup.queryByText("0", { exact: true })).not.toBeInTheDocument();
  });
  describe.each([
    { view: "inventory", path: "/snapshots/1?view=inventory", label: "Coverage for edge/a~b" },
    { view: "device", path: "/snapshots/1?view=device&host=edge%2Fa%7Eb", label: "Device coverage summary" },
  ] as const)("$view coverage rollup", ({ view, path, label }) => {
    function serve(rollup: ReturnType<typeof coverageRollupFixture>) {
      const document = view === "inventory" ? inventoryFixture(1, findingsRollupFixture("not_collected"), rollup)
        : deviceFixture(1, "edge/a~b", findingsRollupFixture("not_collected"), rollup);
      return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes(`/ui-projection/${view}?`)) return new Response(JSON.stringify(document));
        if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
        throw new Error(`Unexpected non-projection request: ${url}`);
      });
    }
    it("renders the owner's worst state and abstention total with their own evidence", async () => {
      const fetcher = serve(coverageRollupFixture()); show(path);
      const rollup = within(await screen.findByRole("group", { name: label }));
      const worst = rollup.getByRole("button", { name: "Evidence for Worst coverage state" }).closest(".projection-fact")! as HTMLElement;
      const abstained = rollup.getByRole("button", { name: "Evidence for Abstaining coverage axes" }).closest(".projection-fact")! as HTMLElement;
      expect(within(worst).getByText("unverified", { exact: true })).toBeInTheDocument();
      expect(within(worst).getByText("Published", { exact: true })).toBeInTheDocument();
      expect(within(abstained).getByText("7", { exact: true })).toBeInTheDocument();
      expect(rollup.queryByText("0", { exact: true })).not.toBeInTheDocument();
      fireEvent.click(within(abstained).getByRole("button", { name: "Evidence for Abstaining coverage axes" }));
      const drawer = screen.getByRole("dialog");
      expect(drawer).toHaveTextContent("synthetic.owner:device_coverage");
      expect(drawer).toHaveTextContent("/coverage_matrix/by_device/edge~1a~0b");
      expect(drawer).toHaveTextContent("/coverage_matrix/rows/4");
      expect(drawer).toHaveTextContent(`sha256:${"a".repeat(64)}`);
      expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
    });
    it.each([
      ["unverified", "Unverified", "Synthetic device coverage custody is missing or ambiguous"],
      ["not_collected", "Not collected", "Synthetic device coverage inputs were not collected"],
      ["all_covered", "Unverified", "Synthetic source silence does not prove complete device coverage"],
    ] as const)("keeps %s rollups withheld without inventing covered or zero", async (mode, state, reason) => {
      serve(coverageRollupFixture(mode)); show(path);
      const rollup = within(await screen.findByRole("group", { name: label }));
      expect(rollup.getAllByText(state, { exact: true })).toHaveLength(2);
      expect(rollup.getAllByText(reason, { exact: true })).toHaveLength(2);
      expect(rollup.queryByText("covered", { exact: true })).not.toBeInTheDocument();
      expect(rollup.queryByText("0", { exact: true })).not.toBeInTheDocument();
      expect(rollup.queryByText("No", { exact: true })).not.toBeInTheDocument();
      fireEvent.click(rollup.getByRole("button", { name: "Evidence for Worst coverage state" }));
      expect(screen.getByRole("dialog")).toHaveTextContent(reason);
      expect(screen.getByRole("dialog")).toHaveTextContent("synthetic.owner:device_coverage");
    });
  });
  describe("device coverage metadata", () => {
    function serveRow(row: ReturnType<typeof coverageAxisFixture>) {
      const document = deviceFixture(1, "edge/a~b", findingsRollupFixture("not_collected"), coverageRollupFixture());
      const source_list = { state: "published", subject: "/coverage_matrix", refs: [], basis: "synthetic.owner:exact_device_axis" };
      const coverage = { pointer: "/coverage", source_list,
        page: { offset: 0, limit: 1, returned: 1, total: 1, has_more: false, items: [row] } };
      const current = { ...document, payload: { ...document.payload, coverage } };
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/ui-projection/device?")) return new Response(JSON.stringify(current));
        if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
        throw new Error(`Unexpected non-projection request: ${url}`);
      });
    }
    it("shows supplied dimension, verdict source and true abstention beside the axis", async () => {
      serveRow(coverageAxisFixture()); show("/snapshots/1?view=device&host=edge%2Fa%7Eb");
      const row = within(await screen.findByRole("group", { name: "Coverage axis capture" }));
      const factFor = (label: string) => within(row.getByRole("button", { name: `Evidence for ${label}` }).closest(".projection-fact")! as HTMLElement);
      expect(factFor("dimension").getByText("capture", { exact: true })).toBeInTheDocument();
      expect(factFor("verdict source").getByText("capture_integrity", { exact: true })).toBeInTheDocument();
      expect(factFor("is abstention").getByText("Yes", { exact: true })).toBeInTheDocument();
      expect(factFor("capture").getByText("unverified", { exact: true })).toBeInTheDocument();
      fireEvent.click(row.getByRole("button", { name: "Evidence for verdict source" }));
      expect(screen.getByRole("dialog")).toHaveTextContent("synthetic.owner:exact_device_axis");
      expect(screen.getByRole("dialog")).toHaveTextContent("/coverage_matrix/rows/4");
    });
    it.each([
      ["unverified", "Unverified", "Synthetic exact device and axis join is ambiguous"],
      ["not_collected", "Not collected", "Synthetic device coverage inputs were not collected"],
    ] as const)("keeps %s metadata withheld instead of false, covered or zero", async (mode, state, reason) => {
      serveRow(coverageAxisFixture("capture", mode)); show("/snapshots/1?view=device&host=edge%2Fa%7Eb");
      const row = within(await screen.findByRole("group", { name: "Coverage axis capture" }));
      expect(row.getAllByText(state, { exact: true })).toHaveLength(4);
      expect(row.getAllByText(reason, { exact: true })).toHaveLength(4);
      expect(row.queryByText("covered", { exact: true })).not.toBeInTheDocument();
      expect(row.queryByText("No", { exact: true })).not.toBeInTheDocument();
      expect(row.queryByText("0", { exact: true })).not.toBeInTheDocument();
      expect(row.queryByRole("term")).not.toBeInTheDocument();
    });
    it("renders an explicit false abstention while keeping the all-covered rollup unverified", async () => {
      const document = deviceFixture(1, "edge/a~b", findingsRollupFixture("not_collected"), coverageRollupFixture("all_covered"));
      const coverage = { pointer: "/coverage", source_list: { state: "published", subject: "/coverage_matrix", refs: [], basis: "synthetic.owner" },
        page: { offset: 0, limit: 1, returned: 1, total: 1, has_more: false, items: [coverageAxisFixture("capture", "covered")] } };
      const current = { ...document, payload: { ...document.payload, coverage } };
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/ui-projection/device?") ? current : { available: false })));
      show("/snapshots/1?view=device&host=edge%2Fa%7Eb");
      const row = within(await screen.findByRole("group", { name: "Coverage axis capture" }));
      const abstention = within(row.getByRole("button", { name: "Evidence for is abstention" }).closest(".projection-fact")! as HTMLElement);
      expect(abstention.getByText("No", { exact: true })).toBeInTheDocument();
      expect(abstention.getByText("Published", { exact: true })).toBeInTheDocument();
      const rollup = within(screen.getByRole("group", { name: "Device coverage summary" }));
      expect(rollup.getAllByText("Unverified", { exact: true })).toHaveLength(2);
      expect(rollup.queryByText("covered", { exact: true })).not.toBeInTheDocument();
      expect(rollup.queryByText("0", { exact: true })).not.toBeInTheDocument();
    });
    it("retains the full owner rollup while paging individual coverage axes", async () => {
      const document = deviceFixture(1, "edge/a~b", findingsRollupFixture("not_collected"), coverageRollupFixture());
      const source_list = { state: "published", subject: "/coverage_matrix", refs: [], basis: "synthetic.owner:exact_device_axis" };
      const coverage = { pointer: "/coverage", source_list,
        page: { offset: 0, limit: 1, returned: 1, total: 9, has_more: true, items: [coverageAxisFixture()] } };
      const current = { ...document, payload: { ...document.payload, coverage } };
      const nextRow = { ...coverageAxisFixture("parse", "published", 8), dimension: published("parse"), verdict_source: published("parse_yield") };
      const next = { ...coverage, page: { offset: 1, limit: 1, returned: 1, total: 9, has_more: true, items: [nextRow] } };
      const { payload: _payload, ...envelope } = current;
      const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/device/lists?")) return new Response(JSON.stringify({ ...envelope, list: next }));
        if (url.includes("/ui-projection/device?")) return new Response(JSON.stringify(current));
        if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
        throw new Error(`Unexpected non-projection request: ${url}`);
      });
      show("/snapshots/1?view=device&host=edge%2Fa%7Eb");
      const list = within(await screen.findByRole("region", { name: "Device coverage" }));
      const rollup = within(screen.getByRole("group", { name: "Device coverage summary" }));
      expect(list.getByRole("group", { name: "Coverage axis capture" })).toBeInTheDocument();
      expect(rollup.getByText("7", { exact: true })).toBeInTheDocument();
      fireEvent.click(list.getByRole("button", { name: "Next Device coverage page" }));
      await list.findByRole("group", { name: "Coverage axis parse" });
      expect(list.queryByRole("group", { name: "Coverage axis capture" })).not.toBeInTheDocument();
      expect(rollup.getByText("7", { exact: true })).toBeInTheDocument();
      expect(rollup.getByText("unverified", { exact: true })).toBeInTheDocument();
      expect(rollup.queryByText("1", { exact: true })).not.toBeInTheDocument();
      expect(rollup.queryByText("9", { exact: true })).not.toBeInTheDocument();
      const requested = fetcher.mock.calls.map(([input]) => String(input)).find((url) => url.includes("/device/lists?"))!;
      const query = new URL(requested, "http://localhost").searchParams;
      expect(query.get("host")).toBe("edge/a~b"); expect(query.get("pointer")).toBe("/coverage"); expect(query.get("offset")).toBe("1");
    });
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
