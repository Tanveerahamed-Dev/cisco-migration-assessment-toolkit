import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import CoreSnapshot from "./CoreSnapshot";
import { overviewFixture, overviewRollupsFixture, trustFixture, inventoryFixture, findingsFixture, deviceFixture, findingsRollupFixture, coverageRollupFixture, coverageAxisFixture, published, topologyFixture,
  deviceSelectionPage, deviceImpactRowFixture, deviceStructuralRowFixture, findingFacetsFixture } from "../test/projectionFixtures";

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
  describe("Trust analysis-input gaps", () => {
    const scope = { id: "trust_inputs_scope", owner: "synthetic.owner:trust_inputs", applies_to: ["/trust/inputs"],
      text: "Synthetic scope: the inputs are the engine's per-device register axes, not every analysis" };
    const evidence = { refs: [{ pointer: "/device_dossiers/per_device", role: "basis" }, { pointer: "/collection_completeness/summary/inventory", role: "denominator" }],
      basis: "synthetic.owner:trust_inputs" };
    const count = (value: number) => ({ ...published(value), ...evidence, subject: null, caveats: [scope.id] });
    const total = (value: number) => ({ ...published(value), subject: "/collection_completeness/summary/inventory", refs: [], basis: "synthetic.owner:inventory" });
    const held = (state: string, reason: string) => ({ ...evidence, state, value: null, reason, subject: null });
    // ui_projection._listing keeps a list's caveats when it is published or collected but empty, or carries items: an
    // empty, collected list is qualified too.
    const hostList = (state: string, items: object[], reason?: string) => ({ ...evidence, state, subject: null, items,
      ...(reason ? { reason } : {}),
      ...(items.length || state === "published" || state === "collected_but_empty" ? { caveats: [scope.id] } : {}) });
    function serveTrust(rows: Record<string, object>, limitations: object[] = [scope]) {
      const doc = trustFixture();
      const document = { ...doc, limitations, payload: { ...doc.payload,
        inputs: doc.payload.inputs.map((row) => ({ ...row, ...rows[row.input] })) } };
      return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/ui-projection/trust?")) return new Response(JSON.stringify(document));
        if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
        throw new Error(`Unexpected non-projection request: ${url}`);
      });
    }
    async function openTrust() {
      show("/snapshots/1?view=trust");
      await screen.findByRole("heading", { name: "What the analysis could not see" });
    }
    const inputRow = (input: string) => within(screen.getByRole("article", { name: `${input} analysis input` }));
    const factIn = (row: ReturnType<typeof within>, label: string) =>
      within(row.getByRole("button", { name: `Evidence for ${label}` }).closest(".projection-fact")! as HTMLElement);
    // Any ratio sentence at all, whatever its numbers: a sentence rendered over a withheld count or denominator
    // ("3 of null …") must fail the tests below, so the pattern never requires a number.
    const ratio = /inventory devices could not be assessed/;

    it("renders published input gaps with the supplied ratio, host order, custody labels and evidence pointers", async () => {
      const hosts = [
        { host: "edge/a~b", custody: "not_collected", label: null, pointer: "/collection_completeness/devices/3" },
        { host: "synthetic-dist", custody: "analysis_unavailable", label: "Synthetic engine label: input phase failed", pointer: "/device_dossiers/per_device/2/exposures/1" },
        { host: "synthetic-core", custody: "collected_but_empty", label: "Synthetic engine label: no authoritative lifecycle band", pointer: "/device_dossiers/per_device/1/exposures/1" },
      ];
      const fetcher = serveTrust({
        "Hardware EoL": { sections: ["lifecycle_risk"], n: count(3), of: total(5), hosts: hostList("published", hosts) },
        Health: { sections: ["health_scores"], n: count(0), of: total(5),
          hosts: hostList("collected_but_empty", [], "Synthetic: every inventory device carries one readable exposure") },
      });
      await openTrust();
      const rows = screen.getAllByRole("article").filter((row) => row.getAttribute("aria-label")?.endsWith(" analysis input"));
      expect(rows.map((row) => row.getAttribute("aria-label"))).toEqual(trustFixture().payload.inputs.map(({ input }) => `${input} analysis input`));
      const eol = inputRow("Hardware EoL");
      expect(eol.getByText("3 of 5 inventory devices could not be assessed", { exact: true })).toBeInTheDocument();
      // the sentence carries the count's qualifications beside it, not only on the count fact below
      fireEvent.click(eol.getByRole("button", { name: "Qualifications for 3 of 5 inventory devices could not be assessed" }));
      expect(screen.getByRole("dialog")).toHaveTextContent(scope.text);
      fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close evidence" }));
      expect(factIn(eol, "could not be assessed").getByText("3", { exact: true })).toBeInTheDocument();
      expect(factIn(eol, "inventory devices").getByText("5", { exact: true })).toBeInTheDocument();
      expect(eol.getByText("Input sections: lifecycle_risk", { exact: true })).toBeInTheDocument();
      fireEvent.click(eol.getByText("Devices and custody", { exact: true }));
      const listed = eol.getAllByRole("group").filter((node) => node.getAttribute("aria-label")?.endsWith(" not assessed by Hardware EoL"));
      expect(listed.map((node) => node.getAttribute("aria-label"))).toEqual(hosts.map(({ host }) => `${host} not assessed by Hardware EoL`));
      const [blind, failed, assessedEmpty] = listed.map((node) => within(node));
      expect(blind.getByText("Not collected", { exact: true })).toBeInTheDocument();
      expect(blind.getByText("/collection_completeness/devices/3", { exact: true })).toBeInTheDocument();
      expect(new URL(blind.getByRole("link", { name: "edge/a~b ↗" }).getAttribute("href")!, "http://localhost").searchParams.get("host")).toBe("edge/a~b");
      expect(failed.getByText("Analysis unavailable", { exact: true })).toBeInTheDocument();
      expect(failed.getByText("Synthetic engine label: input phase failed", { exact: true })).toBeInTheDocument();
      // a device the input could not assess is never labelled as an empty, clean collection
      expect(assessedEmpty.getByText("Evidence collected, nothing assessable", { exact: true })).toHaveClass("state-collected_but_empty");
      expect(assessedEmpty.queryByText("Collected, empty", { exact: true })).not.toBeInTheDocument();
      expect(assessedEmpty.getByText("Synthetic engine label: no authoritative lifecycle band", { exact: true })).toBeInTheDocument();
      expect(assessedEmpty.getByText("/device_dossiers/per_device/1/exposures/1", { exact: true })).toBeInTheDocument();
      expect(new URL(assessedEmpty.getByRole("link", { name: "synthetic-core ↗" }).getAttribute("href")!, "http://localhost").searchParams.get("view")).toBe("device");
      fireEvent.click(eol.getByRole("button", { name: "Evidence for Devices not assessed by Hardware EoL" }));
      let drawer = screen.getByRole("dialog");
      expect(drawer).toHaveTextContent("synthetic.owner:trust_inputs");
      expect(drawer).toHaveTextContent("/device_dossiers/per_device");
      expect(drawer).toHaveTextContent("/collection_completeness/summary/inventory");
      fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
      fireEvent.click(eol.getByRole("button", { name: "Qualifications for Devices not assessed by Hardware EoL" }));
      drawer = screen.getByRole("dialog");
      expect(drawer).toHaveTextContent(scope.text);
      fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
      const health = inputRow("Health");
      expect(health.getByText("0 of 5 inventory devices could not be assessed", { exact: true })).toBeInTheDocument();
      expect(factIn(health, "could not be assessed").getByText("0", { exact: true })).toBeInTheDocument();
      expect(health.getByText("Collected, empty", { exact: true })).toBeInTheDocument();
      expect(health.getByText("Synthetic: every inventory device carries one readable exposure", { exact: true })).toBeInTheDocument();
      // a measured 0 over an empty, collected list is qualified like any count: the count, its sentence and the list
      // each carry the scope qualification, which the engine keeps on the empty list too
      for (const label of ["could not be assessed", "0 of 5 inventory devices could not be assessed", "Devices not assessed by Health"]) {
        fireEvent.click(health.getByRole("button", { name: `Qualifications for ${label}` }));
        expect(screen.getByRole("dialog")).toHaveTextContent(scope.text);
        fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close evidence" }));
      }
      expect(health.queryByText("Devices and custody")).not.toBeInTheDocument();
      expect(health.queryByRole("link")).not.toBeInTheDocument();
      expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
    });
    it.each([
      ["unverified", "Unverified", "Synthetic: one device carries no single readable exposure for this input"],
      ["analysis_unavailable", "Analysis unavailable", "Synthetic: the risk-register phase failed"],
      ["not_collected", "Not collected", "Synthetic: the snapshot carries no risk register"],
    ] as const)("keeps a %s input count withheld with its reason and never as 0 of N", async (state, label, reason) => {
      const carried = state === "unverified" ? [{ host: "edge/a~b", custody: "unverified", label: null, pointer: "/devices/edge~1a~0b" }] : [];
      serveTrust({ Protocol: { n: held(state, reason), of: total(5), hosts: hostList(state, carried, reason) } });
      await openTrust();
      const row = inputRow("Protocol");
      const n = factIn(row, "could not be assessed");
      expect(n.getByText(label, { exact: true })).toBeInTheDocument();
      expect(n.getByText(reason, { exact: true })).toBeInTheDocument();
      expect(n.queryByText("0", { exact: true })).not.toBeInTheDocument();
      expect(row.getAllByText(reason, { exact: true })).toHaveLength(2);
      expect(row.queryByText(ratio)).not.toBeInTheDocument();
      expect(row.queryByText(/^0 of/)).not.toBeInTheDocument();
      expect(row.queryByText("0", { exact: true })).not.toBeInTheDocument();
      expect(factIn(row, "inventory devices").getByText("5", { exact: true })).toBeInTheDocument();
      fireEvent.click(row.getByRole("button", { name: "Evidence for could not be assessed" }));
      expect(screen.getByRole("dialog")).toHaveTextContent(reason);
      expect(screen.getByRole("dialog")).toHaveTextContent("synthetic.owner:trust_inputs");
      fireEvent.click(screen.getByRole("button", { name: "Close evidence" }));
      if (carried.length) {
        fireEvent.click(row.getByText("Devices and custody", { exact: true }));
        const host = within(row.getByRole("group", { name: "edge/a~b not assessed by Protocol" }));
        expect(host.getByText("Unverified", { exact: true })).toBeInTheDocument();
        expect(host.getByText("/devices/edge~1a~0b", { exact: true })).toBeInTheDocument();
      } else {
        expect(row.queryByText("Devices and custody")).not.toBeInTheDocument();
        expect(row.queryByRole("link")).not.toBeInTheDocument();
      }
    });
    it("renders every withheld fixture input with its state and reason, never a ratio or a zero", async () => {
      serveTrust({});
      await openTrust();
      for (const { input } of trustFixture().payload.inputs) {
        const row = inputRow(input);
        expect(row.getAllByText("Not collected", { exact: true })).toHaveLength(3);
        expect(row.getAllByText("Synthetic input was not collected", { exact: true })).toHaveLength(2);
        expect(row.getByText("Synthetic input custody was not collected", { exact: true })).toBeInTheDocument();
        expect(row.queryByText(ratio)).not.toBeInTheDocument();
        expect(row.queryByText("0", { exact: true })).not.toBeInTheDocument();
        expect(row.queryByRole("link")).not.toBeInTheDocument();
      }
    });
    it("carries the inventory denominator's own qualifications beside the ratio sentence, apart from the count's", async () => {
      // ui_projection._inventory_total publishes the denominator with its own caveats (one_hop_failure_attribution
      // when a phase failed), which the count does not inherit, so the sentence that states both carries both. Each
      // control opens its own fact's caveats, never the other's.
      const oneHop = { id: "one_hop_failure_attribution", owner: "synthetic.owner:one_hop", applies_to: ["/trust/inputs"],
        text: "Synthetic: a failed phase is attributed to its direct consumers only" };
      const qualifiedTotal = (value: number) => ({ ...total(value), caveats: [oneHop.id] });
      serveTrust({
        "Hardware EoL": { n: count(3), of: qualifiedTotal(5), hosts: hostList("published", [
          { host: "edge/a~b", custody: "not_collected", label: null, pointer: "/collection_completeness/devices/3" }]) },
        Health: { n: { ...count(2), caveats: [] }, of: qualifiedTotal(5), hosts: hostList("published", [
          { host: "synthetic-core", custody: "not_collected", label: null, pointer: "/collection_completeness/devices/1" }]) },
      }, [scope, oneHop]);
      await openTrust();
      const eol = inputRow("Hardware EoL");
      const sentence = eol.getByText("3 of 5 inventory devices could not be assessed", { exact: true });
      const countControl = eol.getByRole("button", { name: "Qualifications for 3 of 5 inventory devices could not be assessed" });
      const denominatorControl = eol.getByRole("button",
        { name: "Denominator qualifications for the inventory denominator of 3 of 5 inventory devices could not be assessed" });
      expect(sentence).toContainElement(countControl);
      expect(sentence).toContainElement(denominatorControl);
      expect(denominatorControl).toHaveTextContent("Denominator qualifications (1)");
      expect(countControl).toHaveTextContent("Qualifications (1)");
      fireEvent.click(denominatorControl);
      let drawer = screen.getByRole("dialog");
      expect(drawer).toHaveTextContent(oneHop.text);
      expect(drawer).toHaveTextContent("/collection_completeness/summary/inventory");
      expect(drawer).not.toHaveTextContent(scope.text);
      fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
      fireEvent.click(countControl);
      drawer = screen.getByRole("dialog");
      expect(drawer).toHaveTextContent(scope.text);
      expect(drawer).not.toHaveTextContent(oneHop.text);
      fireEvent.click(within(drawer).getByRole("button", { name: "Close evidence" }));
      // a count with no caveat of its own: the sentence still carries the denominator's
      const health = inputRow("Health");
      const healthSentence = health.getByText("2 of 5 inventory devices could not be assessed", { exact: true });
      expect(within(healthSentence).queryByRole("button", { name: /^Qualifications for/ })).toBeNull();
      fireEvent.click(within(healthSentence).getByRole("button",
        { name: "Denominator qualifications for the inventory denominator of 2 of 5 inventory devices could not be assessed" }));
      expect(screen.getByRole("dialog")).toHaveTextContent(oneHop.text);
      fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close evidence" }));
    });
    it("carries no denominator control while the denominator publishes no caveat", async () => {
      serveTrust({ "Hardware EoL": { n: count(3), of: total(5), hosts: hostList("published", [
        { host: "edge/a~b", custody: "not_collected", label: null, pointer: "/collection_completeness/devices/3" }]) } });
      await openTrust();
      const sentence = inputRow("Hardware EoL").getByText("3 of 5 inventory devices could not be assessed", { exact: true });
      expect(within(sentence).getByRole("button", { name: "Qualifications for 3 of 5 inventory devices could not be assessed" }))
        .toBeInTheDocument();
      expect(within(sentence).queryByRole("button", { name: /^Denominator qualifications/ })).toBeNull();
    });
    it("shows no ratio while the inventory denominator is withheld", async () => {
      const denominator = "Synthetic: the owner's inventory count disagrees with the device rows";
      serveTrust({
        "Golden drift": { n: held("unverified", "Synthetic: the device universe is not verified"), of: held("unverified", denominator),
          hosts: hostList("unverified", [], "Synthetic: the device universe is not verified") },
        "QoS posture": { n: count(3), of: held("unverified", denominator), hosts: hostList("published", [
          { host: "synthetic-core", custody: "not_collected", label: null, pointer: "/collection_completeness/devices/1" }]) },
      });
      await openTrust();
      for (const input of ["Golden drift", "QoS posture"]) {
        const row = inputRow(input);
        const of = factIn(row, "inventory devices");
        expect(of.getByText("Unverified", { exact: true })).toBeInTheDocument();
        expect(of.getByText(denominator, { exact: true })).toBeInTheDocument();
        expect(row.queryByText(ratio)).not.toBeInTheDocument();
        expect(row.queryByText("0", { exact: true })).not.toBeInTheDocument();
      }
      expect(factIn(inputRow("Golden drift"), "could not be assessed").getByText("Synthetic: the device universe is not verified", { exact: true })).toBeInTheDocument();
      expect(factIn(inputRow("QoS posture"), "could not be assessed").getByText("3", { exact: true })).toBeInTheDocument();
    });
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
      expect(within(abstained).getByText("3", { exact: true })).toBeInTheDocument();
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
      const mode = row.fact.state === "published" ? "published" : row.fact.state === "not_collected" ? "not_collected" : "unverified";
      const document = deviceFixture(1, "edge/a~b", findingsRollupFixture("not_collected"), coverageRollupFixture(mode));
      const source_list = { state: "published", subject: "/coverage_matrix", refs: [], basis: "synthetic.owner:exact_device_axis" };
      const coverage = { pointer: "/coverage", source_list,
        page: { offset: 0, limit: 1, returned: 1, total: mode === "published" ? 9 : 1, has_more: mode === "published", items: [row] } };
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
      const nextRow = coverageAxisFixture("parse", "published", 8);
      const next = { ...coverage, page: { offset: 1, limit: 1, returned: 1, total: 9, has_more: true, items: [nextRow] } };
      const { payload: _payload, ...envelope } = current;
      let releasePage!: (response: Response) => void;
      const pageResponse = new Promise<Response>((resolve) => { releasePage = resolve; });
      const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/device/lists?")) return pageResponse;
        if (url.includes("/ui-projection/device?")) return new Response(JSON.stringify(current));
        if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
        throw new Error(`Unexpected non-projection request: ${url}`);
      });
      await act(async () => { show("/snapshots/1?view=device&host=edge%2Fa%7Eb"); });
      const list = within(await screen.findByRole("region", { name: "Device coverage" }));
      const rollup = within(screen.getByRole("group", { name: "Device coverage summary" }));
      expect(list.getByRole("group", { name: "Coverage axis capture" })).toBeInTheDocument();
      expect(rollup.getByText("3", { exact: true })).toBeInTheDocument();
      await act(async () => { fireEvent.click(list.getByRole("button", { name: "Next Device coverage page" })); });
      const pageCalls = fetcher.mock.calls.filter(([input]) => String(input).includes("/device/lists?"));
      expect(pageCalls).toHaveLength(1);
      const [requested, options] = pageCalls[0];
      const query = new URL(String(requested), "http://localhost").searchParams;
      expect(query.get("host")).toBe("edge/a~b"); expect(query.get("pointer")).toBe("/coverage"); expect(query.get("offset")).toBe("1");
      const signal = options?.signal;
      expect(signal).toBeInstanceOf(AbortSignal);
      expect(signal?.aborted).toBe(false);
      expect(screen.getByRole("region", { name: "Device coverage" })).toHaveAttribute("aria-busy", "true");
      expect(list.getByRole("group", { name: "Coverage axis capture" })).toBeInTheDocument();
      expect(rollup.getByText("3", { exact: true })).toBeInTheDocument();
      await act(async () => { releasePage(new Response(JSON.stringify({ ...envelope, list: next }))); });
      expect(signal?.aborted).toBe(false);
      const nextAxis = within(await list.findByRole("group", { name: "Coverage axis parse" }));
      expect(nextAxis.getByText("unparsed", { exact: true })).toBeInTheDocument();
      expect(nextAxis.getByText("parse_yield", { exact: true })).toBeInTheDocument();
      expect(list.queryByRole("group", { name: "Coverage axis capture" })).not.toBeInTheDocument();
      expect(rollup.getByText("3", { exact: true })).toBeInTheDocument();
      expect(rollup.getByText("unverified", { exact: true })).toBeInTheDocument();
      expect(rollup.queryByText("1", { exact: true })).not.toBeInTheDocument();
      expect(rollup.queryByText("9", { exact: true })).not.toBeInTheDocument();
      expect(fetcher.mock.calls.filter(([input]) => String(input).includes("/device/lists?"))).toHaveLength(1);
      expect(signal?.aborted).toBe(false);
    });
  });
  describe("device failure impact and structural links", () => {
    const path = "/snapshots/1?view=device&host=edge%2Fa%7Eb";
    const MEASURES = ["Severity", "VLANs impacted", "Stranded endpoints", "Hard-partition VLANs", "Backup-covered VLANs", "FHRP-covered VLANs", "Per-VLAN detail"];
    const CLAIMS = ["Link ends", "Bridge", "Switch pairs severed", "Betweenness", "Betweenness rank"];
    function serve(changes: Record<string, unknown>) {
      const document = deviceFixture();
      const current = { ...document, payload: { ...document.payload, ...changes } };
      const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/ui-projection/device?")) return new Response(JSON.stringify(current));
        if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
        throw new Error(`Unexpected non-projection request: ${url}`);
      });
      return { current, fetcher };
    }
    const factIn = (scope: HTMLElement, label: string) =>
      within(within(scope).getByRole("button", { name: `Evidence for ${label}` }).closest(".projection-fact")! as HTMLElement);

    it("renders published failure-impact values, published zeros and the engine's own row presentation", async () => {
      const { fetcher } = serve({ failure_impact: deviceSelectionPage("/failure_impact", [deviceImpactRowFixture()]) });
      show(path);
      const region = await screen.findByRole("region", { name: "If this device fails" });
      const row = within(region).getByRole("group", { name: "Failure impact source row 4" });
      expect(factIn(row, "Severity").getByText("High", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "VLANs impacted").getByText("3", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "Stranded endpoints").getByText("42", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "Hard-partition VLANs").getByText("3", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "Backup-covered VLANs").getByText("0", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "FHRP-covered VLANs").getByText("0", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "Off-scan gateway VLANs").getByText("0", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "Per-VLAN detail").getByText("Synthetic VLAN 10: Hard partition (42 ep)", { exact: true })).toBeInTheDocument();
      const presentation = factIn(row, "Engine presentation");
      expect(presentation.getByText("Synthetic engine high-impact presentation", { exact: true })).toBeInTheDocument();
      expect(presentation.getByText("impact_high", { exact: true })).toBeInTheDocument();
      for (const label of MEASURES) expect(factIn(row, label).getByText("Published", { exact: true })).toBeInTheDocument();
      expect(within(row).queryByText(/^(Not collected|Unverified|Analysis unavailable)$/)).not.toBeInTheDocument();
      // the negative control for the lower-bound mark: these published measures cite no witness, so 42 is a measurement
      expect(row.querySelector('[data-impact="lower_bound"], [data-impact="lower_bound_reason"]')).toBeNull();
      // No page-side tone: the device document carries no legend, and the page invents no severity mapping.
      expect(region.querySelector('[class*="topology-tone-"]')).toBeNull();
      fireEvent.click(within(row).getByRole("button", { name: "Evidence for Severity" }));
      expect(screen.getByRole("dialog")).toHaveTextContent("High");
      expect(screen.getByRole("dialog")).toHaveTextContent(`sha256:${"a".repeat(64)}`);
      expect(fetcher.mock.calls.every(([url]) => /ui-projection|scope-view/.test(String(url)))).toBe(true);
    });
    it("shows a measure the engine publishes only as a lower bound as ≥ N with its reason, as the topology rows do", async () => {
      // The device row comes from ui_projection._topology_impact, the builder of the fleet topology's rows. This is
      // its row for a switch simulated only in part (2 VLANs with an off-scan gateway): every measure cites the
      // off_scan_gw_vlans cell as its witness, High and each positive count stay published as lower bounds, and each
      // zero count is withheld with the bound's zero reason. The non-measures cite no witness.
      const pointer = "/failure_impact/4", witness = { pointer: `${pointer}/off_scan_gw_vlans`, role: "witness" };
      const ZERO = "not collected: this 0 is only a lower bound: 2 VLAN(s) on this switch have an off-scan gateway the "
        + "simulation could not assess (off_scan_gw_vlans), so it is not a measurement of none";
      const cell = (field: string, value: unknown, measure: boolean) => ({ state: "published", value, subject: `${pointer}/${field}`,
        basis: `analyze.compute_failure_impact:failure_impact[].${field}`,
        refs: [{ pointer: `${pointer}/${field}`, role: "subject" }, ...(measure ? [witness] : [])] });
      const bounded = { ...deviceImpactRowFixture(), severity: cell("severity", "High", true), vlans_impacted: cell("vlans_impacted", 3, true),
        stranded: cell("stranded", 42, true), hard: cell("hard", 3, true),
        backup: { ...cell("backup", null, true), state: "not_collected", reason: ZERO },
        fhrp: { ...cell("fhrp", null, true), state: "not_collected", reason: ZERO },
        off_scan_gw_vlans: cell("off_scan_gw_vlans", 2, false), detail: cell("detail", "Synthetic VLAN 10: Hard partition (42 ep)", false) };
      serve({ failure_impact: deviceSelectionPage("/failure_impact", [bounded]) });
      show(path);
      const region = await screen.findByRole("region", { name: "If this device fails" });
      const row = within(region).getByRole("group", { name: "Failure impact source row 4" });
      const stranded = factIn(row, "Stranded endpoints");
      // the pre-fix device page printed a plain 42: a minimum read as an exact measurement
      expect(stranded.queryByText("42", { exact: true })).not.toBeInTheDocument();
      expect(stranded.getByText("≥ 42", { exact: true }).closest('[data-impact="lower_bound"]')).toHaveClass("impact-bound");
      expect(stranded.getByText("Published", { exact: true })).toBeInTheDocument();
      // its reason is a visible line naming the cited cell of this row, never hover-only
      const reason = row.querySelectorAll('[data-impact="lower_bound_reason"]');
      expect(reason).toHaveLength(4);
      expect(stranded.getByText(/^At least 42: a lower bound, not an exact measurement\. Why: /))
        .toHaveTextContent(`this row's off_scan_gw_vlans cell (${pointer}/off_scan_gw_vlans)`);
      expect(factIn(row, "Severity").getByText("≥ High", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "VLANs impacted").getByText("≥ 3", { exact: true })).toBeInTheDocument();
      expect(factIn(row, "Hard-partition VLANs").getByText("≥ 3", { exact: true })).toBeInTheDocument();
      // the held zeros keep their state and reason, never a 0
      for (const label of ["Backup-covered VLANs", "FHRP-covered VLANs"]) {
        expect(factIn(row, label).getByText("Not collected", { exact: true })).toBeInTheDocument();
        expect(factIn(row, label).getByText(ZERO, { exact: true })).toBeInTheDocument();
        expect(factIn(row, label).queryByText("0", { exact: true })).not.toBeInTheDocument();
      }
      // a non-measure is never a lower bound: the off-scan count is the engine's own count
      const offScan = factIn(row, "Off-scan gateway VLANs");
      expect(offScan.getByText("2", { exact: true })).toBeInTheDocument();
      expect(offScan.queryByText(/^≥/)).not.toBeInTheDocument();
      expect(row.querySelectorAll('[data-impact="lower_bound"]')).toHaveLength(4);
    });
    it.each([
      ["not_collected", "Not collected", "not_observed"],
      ["unverified", "Unverified", "unverified"],
      ["analysis_unavailable", "Analysis unavailable", "analysis_unavailable"],
    ] as const)("keeps %s impact cells as engine reasons, never a value, a zero or a clean bill", async (state, label, token) => {
      const reason = `Synthetic ${state} reason for this row's measures`;
      serve({ failure_impact: deviceSelectionPage("/failure_impact", [deviceImpactRowFixture(4, { state, reason, token })]) });
      show(path);
      const row = await screen.findByRole("group", { name: "Failure impact source row 4" });
      for (const measure of MEASURES) {
        const fact = factIn(row, measure);
        expect(fact.getByText(label, { exact: true })).toBeInTheDocument();
        expect(fact.getByText(reason, { exact: true })).toBeInTheDocument();
        expect(fact.queryByText("0", { exact: true })).not.toBeInTheDocument();
        expect(fact.queryByRole("definition")).not.toBeInTheDocument();
      }
      expect(within(row).queryByText(/^(High|Medium|Low|Info)$/)).not.toBeInTheDocument();
      // The engine presentation's own glyph value may read "none"; the clean-bill wording must not appear anywhere.
      expect(within(row).queryByText(/no (reachability )?impact/i)).not.toBeInTheDocument();
      expect(within(row).queryByText(/^impact_/)).not.toBeInTheDocument();
      expect(factIn(row, "Engine presentation").getByText(token, { exact: true })).toBeInTheDocument();
      expect(factIn(row, "Off-scan gateway VLANs").getByText("2", { exact: true })).toBeInTheDocument();
      fireEvent.click(within(row).getByRole("button", { name: "Evidence for Stranded endpoints" }));
      expect(screen.getByRole("dialog")).toHaveTextContent(reason);
      expect(screen.getByRole("dialog")).toHaveTextContent("/failure_impact/4/witness");
    });
    it("shows the default blind selections as their own engine reasons, not as no impact or no link", async () => {
      const blind = deviceFixture().payload;
      serve({});
      show(path);
      const impact = within(await screen.findByRole("region", { name: "If this device fails" }));
      const links = within(screen.getByRole("region", { name: "Structural links" }));
      for (const [region, source] of [[impact, blind.failure_impact], [links, blind.structural_links]] as const) {
        expect(region.getByText("Not collected", { exact: true })).toBeInTheDocument();
        expect(region.getByText(source.source_list.reason, { exact: true })).toBeInTheDocument();
        expect(region.queryByRole("group", { name: /source row/ })).not.toBeInTheDocument();
        expect(region.queryByText("0", { exact: true })).not.toBeInTheDocument();
        expect(region.queryByText(/^none$/i)).not.toBeInTheDocument();
      }
      // The only "no impact" wording on the page is the engine's own reason, quoting what an absent row is not.
      expect(screen.getAllByText(/no impact/i).map((node) => node.textContent)).toEqual([blind.failure_impact.source_list.reason]);
    });
    describe.each([
      { name: "failure_impact", title: "If this device fails" },
      { name: "structural_links", title: "Structural links" },
    ] as const)("$title selection state", ({ name, title }) => {
      it.each([
        ["not_collected", "Not collected"], ["collected_but_empty", "Collected, empty"],
        ["analysis_unavailable", "Analysis unavailable"], ["unverified", "Unverified"],
      ] as const)("renders a %s selection as its own state and reason, not as an empty result", async (state, label) => {
        const reason = `Synthetic ${state} selection reason`;
        serve({ [name]: deviceSelectionPage(`/${name}`, [], { state, reason }) });
        show(path);
        const region = within(await screen.findByRole("region", { name: title }));
        expect(region.getByText(label, { exact: true })).toBeInTheDocument();
        expect(region.getByText(reason, { exact: true })).toBeInTheDocument();
        for (const other of ["Published", "Not collected", "Collected, empty", "Analysis unavailable", "Unverified"].filter((item) => item !== label)) {
          expect(region.queryByText(other, { exact: true })).not.toBeInTheDocument();
        }
        expect(region.queryByRole("group", { name: /source row/ })).not.toBeInTheDocument();
        expect(region.queryByText("0", { exact: true })).not.toBeInTheDocument();
        expect(region.queryByText(/no impact|no link|^none$/i)).not.toBeInTheDocument();
        fireEvent.click(region.getByRole("button", { name: `Evidence for ${title}` }));
        expect(screen.getByRole("dialog")).toHaveTextContent(reason);
      });
    });
    it("marks a bridge only through the engine's row presentation and keeps engine row order", async () => {
      // Engine order is supplied as rank 7 before rank 1; a page-side ranking would reverse it.
      serve({ structural_links: deviceSelectionPage("/structural_links", [deviceStructuralRowFixture(9, false, 7), deviceStructuralRowFixture(2, true, 1)]) });
      show(path);
      const region = await screen.findByRole("region", { name: "Structural links" });
      expect(within(region).getAllByRole("group", { name: /^Structural link source row / }).map((row) => row.getAttribute("aria-label")))
        .toEqual(["Structural link source row 9", "Structural link source row 2"]);
      const bridge = within(region).getByRole("group", { name: "Structural link source row 2" });
      expect(factIn(bridge, "Engine presentation").getByText("Synthetic engine bridge presentation", { exact: true })).toBeInTheDocument();
      expect(factIn(bridge, "Engine presentation").getByText("structural_bridge", { exact: true })).toBeInTheDocument();
      expect(factIn(bridge, "Bridge").getByText("Yes", { exact: true })).toBeInTheDocument();
      expect(factIn(bridge, "Switch pairs severed").getByText("4", { exact: true })).toBeInTheDocument();
      expect(factIn(bridge, "Betweenness").getByText("0.5", { exact: true })).toBeInTheDocument();
      expect(factIn(bridge, "Betweenness rank").getByText("1", { exact: true })).toBeInTheDocument();
      expect(factIn(bridge, "Link ends").getByText("synthetic-peer-2", { exact: true })).toBeInTheDocument();
      const link = within(region).getByRole("group", { name: "Structural link source row 9" });
      expect(factIn(link, "Engine presentation").getByText("structural_link", { exact: true })).toBeInTheDocument();
      expect(within(link).queryByText("structural_bridge", { exact: true })).not.toBeInTheDocument();
      expect(within(link).queryByText("Synthetic engine bridge presentation", { exact: true })).not.toBeInTheDocument();
      expect(factIn(link, "Bridge").getByText("No", { exact: true })).toBeInTheDocument();
      expect(factIn(link, "Switch pairs severed").getByText("0", { exact: true })).toBeInTheDocument();
      expect(factIn(link, "Betweenness rank").getByText("7", { exact: true })).toBeInTheDocument();
      expect(region.querySelector('[class*="topology-tone-"]')).toBeNull();
    });
    it("keeps an unverified host pair withheld without a bridge marker, a Yes/No or a zero", async () => {
      const reason = "Synthetic host pair is named by more than one stored row";
      serve({ structural_links: deviceSelectionPage("/structural_links", [deviceStructuralRowFixture(3, true, 1, { state: "unverified", reason, token: "unverified" })]) });
      show(path);
      const row = await screen.findByRole("group", { name: "Structural link source row 3" });
      for (const claim of CLAIMS) {
        const fact = factIn(row, claim);
        expect(fact.getByText("Unverified", { exact: true })).toBeInTheDocument();
        expect(fact.getByText(reason, { exact: true })).toBeInTheDocument();
        expect(fact.queryByRole("definition")).not.toBeInTheDocument();
      }
      expect(within(row).queryByText(/^(Yes|No|0)$/)).not.toBeInTheDocument();
      expect(within(row).queryByText(/structural_(bridge|link)/)).not.toBeInTheDocument();
      expect(factIn(row, "Engine presentation").getByText("unverified", { exact: true })).toBeInTheDocument();
    });
    it("pages the structural selection with the exact device host and the owner's list pointer", async () => {
      // Deterministic: the page response is held until the test releases it, so the request is observed in flight
      // (busy, not reset or aborted by a late list effect) and the next page is asserted only after its response.
      const first = deviceStructuralRowFixture(2, true, 1), second = deviceStructuralRowFixture(5, false, 2);
      const initial = { ...deviceSelectionPage("/structural_links", [first]), page: { offset: 0, limit: 1, returned: 1, total: 2, has_more: true, items: [first] } };
      const { current, fetcher } = serve({ structural_links: initial });
      const next = { ...initial, page: { offset: 1, limit: 1, returned: 1, total: 2, has_more: false, items: [second] } };
      const { payload: _payload, ...envelope } = current;
      let release!: (response: Response) => void;
      fetcher.mockImplementation(async (input) => {
        const url = String(input);
        if (url.includes("/device/lists?")) return new Promise<Response>((resolve) => { release = resolve; });
        if (url.includes("/ui-projection/device?")) return new Response(JSON.stringify(current));
        if (url.endsWith("/scope-view")) return new Response(JSON.stringify({ available: false, href: null }));
        throw new Error(`Unexpected non-projection request: ${url}`);
      });
      const listCalls = () => fetcher.mock.calls.map(([input]) => String(input)).filter((url) => url.includes("/device/lists?"));
      show(path);
      const section = await screen.findByRole("region", { name: "Structural links" });
      const region = within(section);
      expect(region.getByRole("group", { name: "Structural link source row 2" })).toBeInTheDocument();
      fireEvent.click(region.getByRole("button", { name: "Next Structural links page" }));
      await waitFor(() => expect(listCalls()).toHaveLength(1));
      expect(release).toBeDefined();
      // the request is still the list's own: busy, Next disabled, no reset to the first page while it is in flight
      expect(section).toHaveAttribute("aria-busy", "true");
      expect(region.getByRole("button", { name: "Next Structural links page" })).toBeDisabled();
      await act(async () => { release(new Response(JSON.stringify({ ...envelope, list: next }))); });
      expect(await region.findByRole("group", { name: "Structural link source row 5" })).toBeInTheDocument();
      expect(region.queryByRole("group", { name: "Structural link source row 2" })).not.toBeInTheDocument();
      expect(section).toHaveAttribute("aria-busy", "false");
      expect(listCalls()).toHaveLength(1);
      const query = new URL(listCalls()[0], "http://localhost").searchParams;
      expect(query.get("pointer")).toBe("/structural_links"); expect(query.get("offset")).toBe("1"); expect(query.get("host")).toBe("edge/a~b");
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
  it("renders the engine's finding facet totals with their own states (G21), never a withheld total as zero", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(String(input).includes("/findings?") ? findingsFixture() : { available: false })));
    show("/snapshots/1?view=findings");
    await screen.findByText("Synthetic finding");
    expect(screen.queryByText(/facet totals are not published/)).not.toBeInTheDocument();
    const facets = findingFacetsFixture();
    const severity = screen.getByRole("heading", { name: "Findings by severity" }).closest("section") as HTMLElement;
    for (const row of facets.severity) {
      expect(within(severity).getByRole("button", { name: `Evidence for ${row.k} findings` })).toBeInTheDocument();
    }
    // every severity total is withheld in the fixture: each shows its reason, and none reads as a measured zero
    expect(within(severity).getAllByText("Synthetic input was not collected")).toHaveLength(facets.severity.length);
    expect(within(severity).queryByText("0")).not.toBeInTheDocument();
    const category = screen.getByRole("heading", { name: "Findings by category" }).closest("section") as HTMLElement;
    expect(within(category).getAllByText("Synthetic input was not collected")).toHaveLength(facets.category.length);
    const device = screen.getByRole("region", { name: "Findings by inventory device" });
    expect(within(device).getByRole("button", { name: "Evidence for Findings on edge/a~b" })).toBeInTheDocument();
    expect(within(device).getByText("1")).toBeInTheDocument();
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
