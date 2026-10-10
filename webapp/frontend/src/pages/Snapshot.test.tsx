import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import SnapshotPage from "./Snapshot";

// Integration test of the snapshot cockpit: it renders the KPI hero from the summary, and it PINS the
// two shipped regressions the page's comments call out — WEBAP-02 + audit-5 FH#22: an un-assessed
// fleet (engine emitted avg_health "") must read as UNKNOWN ("—", neutral tone), never a fake green 0.
// Only meta + graph are mocked with real shapes; the other panels 404 → their own ErrorBox, so the
// page renders. jsdom-safe: the 3D fabric is lazy and never toggled here.
const summary = (avg: number | string) => ({
  avg_health: avg, n_critical: 3, n_switches: 40, version: "V3.23.0",
  punchlist: { crit_high: 5, total: 20, by_severity: { High: 3 }, by_category: { Security: 4 } },
  readiness: { READY: 30, CAUTION: 8, "NOT READY": 2 },
  bands: { Good: 25, Critical: 3 },
  sections: [{ key: "overview", label: "Overview" }, { key: "punchlist", label: "Punch list" }],
  lifecycle: { past_eos: 2 },
});
const meta = (avg: number | string) => ({
  campaign_id: 1, label: "Demo Fleet", n_devices: 50, script_version: "V3.23.0",
  uploaded_at: "2026-06-13T06:32:00Z", summary: summary(avg),
});

function mockFetch(m: unknown) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (/\/api\/snapshots\/\d+\/graph\b/.test(url)) return new Response(JSON.stringify({ nodes: [], edges: [] }), { status: 200 });
    if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return new Response(JSON.stringify(m), { status: 200 });
    return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 }); // unrelated panels → ErrorBox
  });
}

const renderSnap = () =>
  render(
    <MemoryRouter initialEntries={["/snapshots/1"]}>
      <Routes>
        <Route path="/snapshots/:id" element={<SnapshotPage />} />
      </Routes>
    </MemoryRouter>,
  );

describe("Snapshot cockpit", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the snapshot header and the KPI hero from the summary", async () => {
    mockFetch(meta(72));
    renderSnap();
    expect(await screen.findByRole("heading", { name: "Demo Fleet" })).toBeInTheDocument();
    expect(screen.getByText("Critical-band switches")).toBeInTheDocument();
    expect(screen.getByText("Move-group readiness")).toBeInTheDocument();
  });

  it("explains lifecycle NOT ASSESSED as no-match or provenance-withheld", async () => {
    const m: any = meta(72);
    m.summary.lifecycle = {
      past_eos: 0,
      past_ldos: 0,
      unknown: 1,
      n_devices: 1,
      coverage_gap: true,
    };
    mockFetch(m);
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    const gap = screen.getByText(/1\/1 Unknown \/ EoL NOT ASSESSED/);
    expect(gap).toHaveAttribute("title", expect.stringMatching(/no exact EoX bulletin row matched/i));
    expect(gap).toHaveAttribute("title", expect.stringMatching(/retained source proof\/complete dates did not verify/i));
    expect(gap.getAttribute("title")).not.toMatch(/^No EoX bulletin matched/);
  });

  it("renders a near-LDoS-only lifecycle risk instead of hiding it behind zero past-EoS", async () => {
    const m: any = meta(72);
    m.summary.lifecycle = {
      past_eos: 0,
      near_eos: 3,
      past_ldos: 0,
      unknown: 0,
      n_devices: 3,
      coverage_gap: false,
    };
    mockFetch(m);
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    expect(screen.getByText(/3 within 1yr of LDoS/)).toBeInTheDocument();
  });

  it("renders the full lifecycle census in canonical urgency order from by_band", async () => {
    const m: any = meta(72);
    m.summary.lifecycle = {
      by_band: { "Past-LDoS": 1, "Near-LDoS": 2, "Past-EoS": 3, Active: 4, Unknown: 5 },
      n_devices: 15,
      coverage_gap: true,
    };
    mockFetch(m);
    const { container } = renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    const hint = screen.getByText("Move-group readiness").closest(".kpi")!.querySelector(".hint")!;
    const line = hint.textContent || "";
    const labels = ["1 past-LDoS", "2 within 1yr of LDoS", "3 past-EoS (LDoS future)",
      "4 Active (pre-EoS date position)", "5/15 Unknown / EoL NOT ASSESSED"];
    labels.reduce((previous, label) => {
      const position = line.indexOf(label);
      expect(position).toBeGreaterThan(previous);
      return position;
    }, -1);

    expect(container.querySelector('[data-lifecycle-band="Past-LDoS"]')).toHaveStyle({ color: "var(--crit)" });
    expect(container.querySelector('[data-lifecycle-band="Near-LDoS"]')).toHaveStyle({ color: "var(--risk)" });
    expect(container.querySelector('[data-lifecycle-band="Past-EoS"]')).toHaveStyle({ color: "var(--watch)" });
    expect(container.querySelector('[data-lifecycle-band="Active"]')).toHaveAttribute(
      "title", expect.stringMatching(/support entitlement was not assessed/i));
    const unknown = container.querySelector('[data-lifecycle-band="Unknown"]');
    expect(unknown).toHaveAttribute("title", expect.stringMatching(/no exact EoX bulletin row matched/i));
    expect(unknown).toHaveAttribute("title", expect.stringMatching(/source proof\/complete dates did not verify/i));
  });

  it("renders future lifecycle bands after the canonical five and fails them closed", async () => {
    const m: any = meta(72);
    m.summary.lifecycle = {
      by_band: { Active: 4, "Future-Band": 6, Unknown: 0, "Past-EoS": 3, "Past-LDoS": 1, "Near-LDoS": 2 },
      unknown: 6,
      n_devices: 16,
      coverage_gap: true,
    };
    mockFetch(m);
    const { container } = renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    const hint = screen.getByText("Move-group readiness").closest(".kpi")!.querySelector(".hint")!;
    const line = hint.textContent || "";
    expect(line.indexOf("0 Unknown / EoL NOT ASSESSED")).toBeGreaterThan(
      line.indexOf("4 Active (pre-EoS date position)"),
    );
    expect(line.indexOf("6 NOT ASSESSED (unrecognized band: Future-Band)")).toBeGreaterThan(
      line.indexOf("0 Unknown / EoL NOT ASSESSED"),
    );
    expect(line).not.toContain("6/16 Unknown / EoL NOT ASSESSED");
    expect(container.querySelector('[data-lifecycle-band="Future-Band"]')).toHaveAttribute(
      "title", expect.stringMatching(/treated as un-assessed rather than healthy/i),
    );
  });

  it("preserves an owner-reported unknown remainder outside the published band census", async () => {
    const m: any = meta(72);
    m.summary.lifecycle = {
      by_band: { Active: 8 },
      unknown: 4,
      n_devices: 12,
      coverage_gap: true,
    };
    mockFetch(m);
    const { container } = renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    expect(container.querySelector('[data-lifecycle-band="Unknown"]')?.textContent).toContain(
      "0 Unknown / EoL NOT ASSESSED",
    );
    const remainder = container.querySelector('[data-lifecycle-band="Unknown-remainder"]');
    expect(remainder?.textContent).toContain("4 NOT ASSESSED (reported outside band census)");
    expect(remainder).toHaveAttribute("title", expect.stringMatching(/not represented by a named by_band bucket/i));
    expect(screen.queryByText(/no lifecycle figure was published/i)).not.toBeInTheDocument();
  });

  it("WEBAP-02 / FH#22: an un-assessed fleet (avg_health '') reads UNKNOWN, not a fake green 0", async () => {
    mockFetch(meta(""));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    // the health gauge shows the em-dash unknown state, never a measured-looking 0
    const gauge = screen.getByText("avg health").closest(".gauge");
    expect(gauge?.textContent).toContain("—");
    // The unassessed fleet must not retain a filled/invalid progress arc behind the dash.
    expect(gauge?.querySelectorAll("circle")).toHaveLength(1);
    expect(gauge?.querySelector("circle")).toHaveAttribute("stroke", "var(--surface-3)");
    expect(gauge?.querySelector("[stroke-dashoffset]")).toBeNull();
    expect(gauge?.querySelector("svg")?.innerHTML).not.toMatch(/NaN|Infinity/);
    // and the critical KPI card is tone-NEUTRAL, so "0 critical" doesn't read as a verified-clean fleet
    const card = screen.getByText("Critical-band switches").closest(".kpi");
    expect(card?.className).not.toMatch(/\b(ok|crit|watch)\b/);
  });

  it("surfaces a load error for a missing snapshot instead of a blank page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "snapshot not found" }), { status: 404 }),
    );
    renderSnap();
    expect(await screen.findByText("snapshot not found")).toBeInTheDocument();
  });

  // Unit 11: the detail-section tab bar is a real ARIA tablist (house pattern from DesignBlueprint's
  // tab bar), not plain buttons — clicking a tab flips aria-selected and the tabpanel's aria-labelledby.
  it("Unit 11: detail-section tabs are real ARIA tabs, and clicking one flips aria-selected + the tabpanel label", async () => {
    mockFetch(meta(72));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    expect(screen.getByRole("tablist", { name: /detail sections/i })).toBeInTheDocument();
    const overview = screen.getByRole("tab", { name: /Overview/ });
    const punchlist = screen.getByRole("tab", { name: /Punch list/ });
    expect(overview).toHaveAttribute("aria-selected", "true");
    expect(punchlist).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tabpanel", { name: /Overview/ })).toHaveAttribute("aria-labelledby", overview.id);

    fireEvent.click(punchlist);

    expect(punchlist).toHaveAttribute("aria-selected", "true");
    expect(overview).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tabpanel", { name: /Punch list/ })).toHaveAttribute("aria-labelledby", punchlist.id);
  });

  // Unit 10: a data-gated panel with nothing to show renders a designed empty state (a real .panel
  // with a message) instead of silently vanishing — here Keystones, since the fixture has no
  // summary.keystones at all. W47 (P3-4): the message says the ranking is unavailable; it never
  // claims "no keystone devices" or "no single switch dominates" from a list that is not there.
  // Its tag says the same word as its text, "unavailable": an absent list is not a ranking that
  // was not assessed (that is the empty list's NOT ASSESSED, below).
  it("Unit 10: an empty section renders a designed empty state instead of vanishing (return null)", async () => {
    mockFetch(meta(72));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    const note = await screen.findByText(/Keystone ranking unavailable: this snapshot's summary carries no keystone list/);
    const panel = note.closest(".panel") as HTMLElement;
    expect(within(panel).getByRole("heading", { name: /Keystone devices/ })).toBeInTheDocument();
    expect(panel).toHaveAttribute("data-keystones", "unavailable");
    const tag = panel.querySelector('[data-impact="unavailable"]');
    expect(tag?.firstChild?.textContent).toBe("unavailable");
    expect(panel.querySelector('[data-impact="not_assessed"]')).toBeNull();
    expect(panel).not.toHaveTextContent("NOT ASSESSED");
    // the reason is the visible text beside the tag, so the tag is neither a tab stop nor a second copy of it
    expect(within(panel).queryByRole("button")).toBeNull();
    // One explicit negative per phrase (CodeQL js/regex/missing-regexp-anchor): an alternation would bind the `$`
    // anchor to its second branch only, which reads as if both phrases were end-anchored.
    expect(within(panel).queryByText(/No keystone devices flagged/)).toBeNull();
    expect(within(panel).queryByText(/dominates the fleet's dependency graph\.?$/)).toBeNull();
  });

  // Unit 12: the explorer toggle announces its expanded/collapsed state non-visually.
  it("Unit 12: the explorer toggle announces aria-expanded", async () => {
    mockFetch(meta(72));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    const toggle = screen.getByRole("button", { name: /open explorer/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);

    expect(await screen.findByRole("button", { name: /hide explorer/i })).toHaveAttribute("aria-expanded", "true");
  });
});

// ── coverage-honesty audit (FE-1 / FE-2 / FE-3 / FE-4) ────────────────────────
// CLAUDE.md guardrail 3: "not observed" must NEVER silently become "healthy". These pin the four
// places on this page where it did — three of them by rendering a positive claim about the SNAPSHOT
// or the SERVER out of a state that was really "we do not know yet" or "the request failed".
describe("Snapshot cockpit · coverage honesty", () => {
  afterEach(() => vi.restoreAllMocks());

  const richSummary = {
    avg_health: 72, n_critical: 3, n_switches: 40, version: "V3.23.0",
    punchlist: { crit_high: 5, total: 20, by_severity: { High: 3 }, by_category: { Security: 4 } },
    readiness: { READY: 30, CAUTION: 8, "NOT READY": 2 },
    bands: { Good: 25, Critical: 3 },
    sections: [{ key: "health_scores", label: "Health scores", count: 303 }],
    lifecycle: { past_eos: 2 }, keystones: [],
  };
  const richMeta = {
    id: 1, campaign_id: 1, label: "Demo Fleet", n_devices: 303, script_version: "V3.23.0",
    uploaded_at: "2026-06-13T06:32:00Z", summary: richSummary,
  };

  function dossiers(bands: Record<string, number>, per_device: any[]) {
    return { section: "device_dossiers", data: { note: "", summary: { bands }, per_device } };
  }
  const dev = (host: string, risk_band: string) =>
    ({ host, risk_band, risk_index: 50, impact_score: 5, exposure_score: 5, verdict: "v", compound: [] });

  // FE-1: the risk chip was a mutually-exclusive ternary chain, so the Unassessed (no-evidence)
  // count only ever reached the header when Severe AND Elevated were both zero — the coverage gap
  // was hidden by exactly the finding that makes it matter.
  it("FE-1: un-assessed devices are disclosed even when Severe devices exist", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "meta").mockRejectedValue(new Error("no meta"));
    vi.spyOn(api, "section").mockResolvedValue(
      dossiers({ Severe: 3, Unassessed: 40, Low: 260 },
        [dev("sw-a", "Severe"), dev("sw-b", "Severe"), dev("blind-1", "Unassessed")]) as any,
    );
    renderSnap();
    const panel = await waitFor(() => {
      const p = screen.getByText(/Device Risk Register/).closest(".panel")!;
      if (!p.querySelector("tbody tr")) throw new Error("register not loaded");
      return p;
    });
    // the 40 blind devices are named — they are excluded from the RANKING, never from the page
    expect(panel.textContent).toContain("40");
    expect(panel.textContent).toMatch(/not assessed/i);
    expect(panel.textContent).toMatch(/never a clean bill of health/i);
  });

  // FE-2: the fetch carried its own `.catch(() => null)`, so a 403/500/503 landed on the benign
  // "older snapshots didn't compute it" empty state — a claim about the snapshot manufactured from
  // a server fault, on the one panel that surfaces blind devices.
  it("FE-2: a failed risk-register load reads as an error, not as 'this snapshot has none'", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "meta").mockRejectedValue(new Error("no meta"));
    vi.spyOn(api, "section").mockRejectedValue(new Error("dossier recompute exploded"));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    // scoped to the register panel — the section tab renders its own ErrorBox for the same rejection
    const panel = await waitFor(() => {
      const p = screen.getByText(/Device Risk Register/).closest(".panel")!;
      if (!p.textContent?.includes("dossier recompute exploded")) throw new Error("not surfaced yet");
      return p;
    });
    expect(panel.textContent).toMatch(/Something went wrong/);
    expect(panel.textContent).toMatch(/still un-assessed/);
    expect(screen.queryByText(/older snapshots didn't compute it/)).toBeNull();
  });

  // FE-2/FE-3: the same false claims used to render for the WHOLE duration of the fetch, because
  // neither panel read `loading`.
  it("FE-2/FE-3: while loading, neither panel asserts an absence it has not established", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "section").mockReturnValue(new Promise(() => {}) as any);  // never settles
    vi.spyOn(api, "meta").mockReturnValue(new Promise(() => {}) as any);
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    expect(screen.queryByText(/older snapshots didn't compute it/)).toBeNull();
    expect(screen.queryByText(/No deliverables are available from this server build/)).toBeNull();
  });

  // FE-3: a failed /api/meta is a fact about the request, not about the server's document family.
  it("FE-3: a failed deliverable catalogue does not read as 'this build has no deliverables'", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "section").mockRejectedValue(new Error("x"));
    vi.spyOn(api, "meta").mockRejectedValue(new Error("meta 503 shed"));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    expect(await screen.findByText("meta 503 shed")).toBeInTheDocument();
    expect(screen.queryByText(/No deliverables are available from this server build/)).toBeNull();
  });

  it("labels AssessHub synthesis without claiming every download is identical to CLI output", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "section").mockRejectedValue(new Error("not relevant"));
    vi.spyOn(api, "meta").mockResolvedValue({
      deliverables: [
        { key: "runbook", label: "Runbook", ext: "docx", available: true,
          producer: "engine-cli", engine_cli_member: true, stage: "pre-cutover" },
        { key: "cutover", label: "Cutover Plan", ext: "docx", available: true,
          producer: "assesshub-snapshot", engine_cli_member: false, stage: "pre-cutover" },
      ],
    } as any);
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    expect(await screen.findByText("ASSESSHUB")).toBeInTheDocument();
    expect(screen.getByText(/Engine-backed artifacts reuse the CLI writer/)).toBeInTheDocument();
    expect(screen.queryByText(/identical to the CLI output/i)).toBeNull();
  });

  // FE-12: summarize() seeds readiness as {READY:0, CAUTION:0, "NOT READY":0} and only ever
  // INCREMENTS it from snap["migration_readiness"] (webapp/backend/summary.py). A snapshot that
  // carries no migration_readiness section therefore yields all-zeros — indistinguishable, in the
  // payload, from a fleet whose groups were all assessed and none came back NOT READY. The tile
  // painted that as the green `ok` tone with "0✓ 0! 0✕", i.e. a positive readiness verdict derived
  // from nothing being classified. The CutoverPlanner on the SAME page says "No migration waves
  // were derived from this snapshot" for the same input.
  it("FE-12: an unclassified move-group set reads as NOT ASSESSED, not as a green all-ready", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue({
      ...richMeta,
      summary: { ...richSummary, readiness: { READY: 0, CAUTION: 0, "NOT READY": 0 } },
    } as any);
    vi.spyOn(api, "meta").mockRejectedValue(new Error("x"));
    vi.spyOn(api, "section").mockRejectedValue(new Error("x"));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    const card = screen.getByText("Move-group readiness").closest(".kpi")!;
    // the fleet IS health-assessed (avg 72), so the page-wide `unknownFleet` neutraliser is OFF —
    // this tile has to make the distinction on its own evidence
    expect(card.className).not.toMatch(/\b(ok|crit|watch)\b/);
    expect(card.textContent).toMatch(/not assessed|NOT OBSERVED/i);
    // and it must not display a counted-looking zero triple
    expect(card.textContent).not.toMatch(/0✓/);
  });

  it("FE-12: a genuinely classified move-group set still reads as measured (the fix must not cry wolf)", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);   // 30 / 8 / 2
    vi.spyOn(api, "meta").mockRejectedValue(new Error("x"));
    vi.spyOn(api, "section").mockRejectedValue(new Error("x"));
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });

    const card = screen.getByText("Move-group readiness").closest(".kpi")!;
    expect(card.className).toMatch(/\bcrit\b/);        // 2 NOT READY dominates
    expect(card.textContent).toContain("30✓");
    expect(card.textContent).not.toMatch(/not assessed/i);
  });

  // FE-4: the section table caps at 200 rows / 8 columns while the tab badge keeps announcing the
  // engine's FULL count — on the 303-device fleet, 103 devices were simply not there for a reader
  // who scrolled to the last row.
  it("FE-4: a row/column-capped section table discloses the cap instead of ending silently", async () => {
    vi.spyOn(api, "getSnapshot").mockResolvedValue(richMeta as any);
    vi.spyOn(api, "meta").mockRejectedValue(new Error("x"));
    const rows = Array.from({ length: 303 }, (_, i) => ({
      host: `sw-${i}`, band: "Good", score: 90, a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, dropped: "x",
    }));
    vi.spyOn(api, "section").mockImplementation(async (_id: number, name: string) => {
      if (name === "device_dossiers") throw new Error("no dossiers");
      return { section: name, data: rows } as any;
    });
    const { container } = renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    const big = await waitFor(() => {
      const t = Array.from(container.querySelectorAll("table.tbl")).find((x) => x.querySelectorAll("tbody tr").length > 50);
      if (!t) throw new Error("section table not rendered");
      return t;
    });
    expect(big.querySelectorAll("tbody tr").length).toBe(200);   // the cap itself is unchanged
    const note = big.closest("div")!.parentElement!.textContent || "";
    expect(note).toMatch(/first 200 of 303 rows/);
    expect(note).toMatch(/8 of 10 columns/);
    expect(note).toMatch(/NOT absent/);
  });
});

describe("Snapshot cockpit · Protocol Assurance portfolio", () => {
  afterEach(() => vi.restoreAllMocks());

  function assuranceReceipt(overrides: Record<string, unknown> = {}) {
    const family = {
      family: "ipv4_routing_adjacency",
      owner_schema: "protocol_adjacency_delta/1",
      assurance_level: "observed_state_preservation",
      evidence_contracts: ["routing_adjacency_baseline/1"],
      evidence_status: "partial",
      status_reason: "One producer leaf remains not verified.",
      source_custody: "embedded_unverified",
      producer_summary: {},
      producer_state_counts: { assessed: 3 },
      coverage_state_counts: { not_verified: 1 },
      subject_total: 5,
      subjects: {
        total: 5,
        rendered: 3,
        omitted: 2,
        rows: Array.from({ length: 3 }, (_, index) => ({
          family: "ipv4_routing_adjacency",
          subject: `core1|OSPF|10.0.0.${index + 1}`,
          kind: "observed_peer",
          evidence_state: "assessed",
          source_contract: "routing_adjacency_baseline/1",
          detail: { switch: "core1", protocol: "OSPF" },
        })),
      },
      limitations: [],
      ...overrides,
    };
    return {
      section: "protocol_assurance",
      data: {
        receipt: {
          schema: "protocol_single_snapshot_receipt/1",
          owner_version: "1",
          owns_score: false,
          owns_verdict: false,
          custody_status: "bound",
          custody_failures: [],
          source_binding: {
            source: "persisted snapshots.snapshot_json blob",
            sha256: `sha256:${"a".repeat(64)}`,
            bytes: 4321,
            snapshot_id: 1,
            campaign_id: 1,
            engagement_id: "eng-1",
            label: "Demo Fleet",
            script_version: "V3.23.0",
          },
          script_owner: {
            source: "snapshot.script_version + snapshots.script_version column",
            snapshot_value: "V3.23.0",
            stored_value: "V3.23.0",
            status: "bound",
          },
          support_profiles: [],
          summary: { n_families: 1, n_subjects_total: 5, by_evidence_status: { partial: 1 } },
          families: [family],
          render_cap: 3,
          complete_export: {
            schema: "protocol_single_snapshot_export/1",
            sha256: `sha256:${"b".repeat(64)}`,
            media_type: "application/json",
          },
          custody_note: "This receipt binds exact persisted snapshot_json bytes; original upload bytes are not retained.",
          receipt_sha256: `sha256:${"c".repeat(64)}`,
        },
        complete_export: {
          schema: "protocol_single_snapshot_export/1",
          sha256: `sha256:${"b".repeat(64)}`,
          media_type: "application/json",
          url: "/api/snapshots/1/protocol-assurance/export",
        },
      },
    };
  }

  function mockAssurance(value: ReturnType<typeof assuranceReceipt>) {
    const m: any = meta(72);
    m.id = 1;
    m.summary.sections = [{ key: "protocol_assurance", label: "Protocol Assurance", count: 1 }];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/snapshots/1/section/protocol_assurance")) {
        return new Response(JSON.stringify(value), { status: 200 });
      }
      if (/\/api\/snapshots\/1\/graph\b/.test(url)) {
        return new Response(JSON.stringify({ nodes: [], edges: [] }), { status: 200 });
      }
      if (/\/api\/snapshots\/1(\?.*)?$/.test(url)) {
        return new Response(JSON.stringify(m), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 });
    });
  }

  it("renders source custody, family-to-subject drill-down, cap disclosure, and complete export", async () => {
    mockAssurance(assuranceReceipt());
    renderSnap();

    expect(await screen.findByRole("heading", { name: "Protocol Assurance portfolio" })).toBeInTheDocument();
    expect(screen.getByText(/persisted-source custody/i).parentElement?.textContent).toMatch(/BOUND/);
    expect(screen.getByText(/4321 bytes/)).toHaveTextContent(`sha256:${"a".repeat(64)}`);
    expect(screen.getByText(/catalog presence is not runtime support/i)).toBeInTheDocument();

    const family = screen.getByText("ipv4_routing_adjacency").closest("details")!;
    fireEvent.click(family.querySelector("summary")!);
    expect(await screen.findByRole("table", { name: /ipv4_routing_adjacency protocol subjects/i }))
      .toBeInTheDocument();
    expect(family).toHaveTextContent(/Showing 3 of 5 subjects; 2 omitted/);
    expect(family).toHaveTextContent(/complete JSON export contains all 5 subjects/);

    const link = screen.getByRole("link", { name: /complete json export/i });
    expect(link).toHaveAttribute("href", "/api/snapshots/1/protocol-assurance/export");
    expect(link).toHaveAttribute("download", "snapshot-1.protocol-assurance.json");
  });

  it("renders missing or malformed family evidence as neutral NOT VERIFIED without inventing a verdict", async () => {
    mockAssurance(assuranceReceipt({
      evidence_status: "not_verified",
      assurance_level: "not_verified",
      status_reason: "Required family evidence is malformed (baseline not object).",
      subject_total: 0,
      subjects: { total: 0, rendered: 0, omitted: 0, rows: [] },
    }));
    renderSnap();

    await screen.findByRole("heading", { name: "Protocol Assurance portfolio" });
    const family = screen.getByText("ipv4_routing_adjacency").closest("details")!;
    expect(family).toHaveTextContent(/NOT VERIFIED/);
    fireEvent.click(family.querySelector("summary")!);
    expect(family).toHaveTextContent(/Required family evidence is malformed/);
    expect(family).toHaveTextContent(/No validated subject rows are rendered/);
    expect(family.className).not.toMatch(/\bok\b/);
    expect(family.textContent).not.toMatch(/\bPASS\b|\bCLEAR\b/);
  });

  it("expands typed VTP subject evidence without rendering uncontracted secret fields", async () => {
    mockAssurance(assuranceReceipt({
      family: "vtp_safety",
      owner_schema: "vtp_extended_evidence/1",
      assurance_level: "local_safety_preservation",
      evidence_contracts: ["vtp_extended_evidence/1"],
      evidence_status: "observed",
      status_reason: "Typed VTP evidence is source-bound.",
      source_custody: "current_run_source_bound",
      subject_total: 1,
      subjects: {
        total: 1,
        rendered: 1,
        omitted: 0,
        rows: [{
          family: "vtp_safety",
          subject: "dist1",
          kind: "device",
          evidence_state: "safe",
          source_contract: "vtp_extended_evidence/1",
          detail: {
            switch: "dist1",
            mode: "server",
            domain: "CAMPUS",
            version: "2",
            revision: 9,
            vlan_count: 42,
            pruning_state: "configured",
            authentication_configured: true,
            password: "must-never-render",
          },
        }],
      },
    }));
    renderSnap();

    await screen.findByRole("heading", { name: "Protocol Assurance portfolio" });
    const family = screen.getByText("vtp_safety").closest("details")!;
    fireEvent.click(family.querySelector("summary")!);
    const subjectDetail = family.querySelector("tbody details") as HTMLDetailsElement;
    expect(subjectDetail).not.toBeNull();
    expect(subjectDetail.open).toBe(false);
    fireEvent.click(subjectDetail.querySelector("summary")!);
    expect(subjectDetail.open).toBe(true);
    expect(screen.getByText("mode").nextElementSibling).toHaveTextContent("server");
    expect(screen.getByText("domain").nextElementSibling).toHaveTextContent("CAMPUS");
    expect(screen.getByText("revision").nextElementSibling).toHaveTextContent("9");
    expect(screen.getByText("authentication configured").nextElementSibling).toHaveTextContent("true");
    expect(family).not.toHaveTextContent("must-never-render");
    expect(family).not.toHaveTextContent(/password/i);
  });
});

// "Open in Atlas Scope" — a plain, top-level, same-origin link, rendered ONLY from the server's
// scope-view capability (GET /api/snapshots/{id}/scope-view owns the href). It must never be a dead
// link (absent/withdrawn scope build, or an unreadable capability) and never a sandboxed iframe:
// Atlas Scope's module scripts and its /api fetch need the real AssessHub origin.
describe("Open in Atlas Scope", () => {
  afterEach(() => vi.restoreAllMocks());

  function mockScope(view: unknown, status = 200) {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (/\/api\/snapshots\/\d+\/scope-view$/.test(url)) return new Response(JSON.stringify(view), { status });
      if (/\/api\/snapshots\/\d+\/graph\b/.test(url)) return new Response(JSON.stringify({ nodes: [], edges: [] }), { status: 200 });
      if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return new Response(JSON.stringify(meta(72)), { status: 200 });
      return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 });
    });
  }

  it("renders a plain top-level link to the server-owned href when the scope view is available", async () => {
    mockScope({ available: true, status: "ready", href: "/scope/snapshots/1/", detail: "ready" });
    renderSnap();
    const link = await screen.findByRole("link", { name: /Open in Atlas Scope/ });
    expect(link).toHaveAttribute("href", "/scope/snapshots/1/");
    // top-level navigation in this browsing context — not a new-window opener, not an iframe
    expect(link).not.toHaveAttribute("target");
    expect(document.querySelector('iframe[src^="/scope"]')).toBeNull();
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/snapshots/1/scope-view", { cache: "no-store" });
  });

  it("renders no link when the server reports the scope view unavailable", async () => {
    mockScope({ available: false, status: "not_built", href: null, detail: "Atlas Scope is not built in this installation." });
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith("/api/snapshots/1/scope-view", { cache: "no-store" }));
    expect(screen.queryByRole("link", { name: /Atlas Scope/ })).toBeNull();
  });

  it("renders no link when the capability cannot be read (absence is not availability)", async () => {
    mockScope({ detail: "Snapshot not found" }, 404);
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith("/api/snapshots/1/scope-view", { cache: "no-store" }));
    expect(screen.queryByRole("link", { name: /Atlas Scope/ })).toBeNull();
  });

  it("drops the previous snapshot's link when the next snapshot's capability fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/snapshots/1/scope-view")
        return new Response(JSON.stringify({ available: true, status: "ready", href: "/scope/snapshots/1/", detail: "" }), { status: 200 });
      if (url === "/api/snapshots/2/scope-view") return new Response(JSON.stringify({ detail: "boom" }), { status: 500 });
      if (/\/api\/snapshots\/\d+\/graph\b/.test(url)) return new Response(JSON.stringify({ nodes: [], edges: [] }), { status: 200 });
      if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return new Response(JSON.stringify(meta(72)), { status: 200 });
      return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 });
    });
    function GoToTwo() {
      const navigate = useNavigate();
      return <button onClick={() => navigate("/snapshots/2")}>go-two</button>;
    }
    render(
      <MemoryRouter initialEntries={["/snapshots/1"]}>
        <GoToTwo />
        <Routes>
          <Route path="/snapshots/:id" element={<SnapshotPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: /Open in Atlas Scope/ })).toHaveAttribute("href", "/scope/snapshots/1/");
    fireEvent.click(screen.getByRole("button", { name: "go-two" }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith("/api/snapshots/2/scope-view", { cache: "no-store" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: /Atlas Scope/ })).toBeNull());
  });

  it("renders no link for an href outside the /scope mount, even if flagged available", async () => {
    mockScope({ available: true, status: "ready", href: "https://evil.example/scope/", detail: "" });
    renderSnap();
    await screen.findByRole("heading", { name: "Demo Fleet" });
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith("/api/snapshots/1/scope-view", { cache: "no-store" }));
    expect(screen.queryByRole("link", { name: /Atlas Scope/ })).toBeNull();
  });
});

// ── W47 / F8: failure-impact values in their W27 engine states ────────────────
// The keystone panel and the "Failure impact" tab read the engine-owned projection through the backend (W27). A lower
// bound must read "≥ N" and say it is a minimum; a held cell must read NOT ASSESSED; a withheld value must read
// unavailable. None of them may render as a bare number, a 0 or a blank. Shapes follow
// webapp/tests/test_impact_surfaces.py's assertions on the real backend output.
describe("Snapshot cockpit · failure-impact engine states (W27)", () => {
  afterEach(() => vi.restoreAllMocks());

  const WHY = "the stored cable map cables this switch to a neighbour it does not show as collected (1 cable row(s)), "
    + "and the simulation counts only endpoints on scanned switches";
  const HELD = "not collected: analyze.compute_failure_impact could not simulate this switch's blast radius (its detail "
    + "says why), so its severity and counts are not measurements";
  const ZERO_BOUND = "not collected: this row cannot account for endpoints behind 1 uncollected neighbour(s), so this 0 "
    + "is only a lower bound, not a measurement of none";
  const bound = (v: string | number) => `≥ ${v} — a lower bound, not an exact measurement: ${WHY}`;

  function mockImpact(summaryPatch: Record<string, unknown>, failureImpact: unknown = []) {
    const m: any = meta(72);
    Object.assign(m.summary, summaryPatch);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (/\/api\/snapshots\/\d+\/section\/failure_impact$/.test(url)) {
        return new Response(JSON.stringify({ section: "failure_impact", data: failureImpact }), { status: 200 });
      }
      if (/\/api\/snapshots\/\d+(\?.*)?$/.test(url)) return new Response(JSON.stringify(m), { status: 200 });
      return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404 });
    });
  }
  const keystonePanel = async () =>
    (await screen.findByRole("heading", { name: /Keystone devices/ })).closest(".panel") as HTMLElement;
  const rowOf = (panel: HTMLElement, text: string) => within(panel).getByText(text).closest("tr") as HTMLElement;
  const cellsOf = (row: HTMLElement) => Array.from(row.querySelectorAll("td"));

  it("keystones: a lower bound reads ≥ N, the disclosure NOT ASSESSED, a withheld VLAN count unavailable", async () => {
    mockImpact({
      keystone_contract: 4,
      keystones: [
        { host: "core1", severity: "High", stranded: 45, vlans_impacted: 4, lower_bound: false, detail: "VLAN 20: Hard partition" },
        { host: "core2", severity: "High", stranded: 42, vlans_impacted: 3, lower_bound: true,
          lower_bound_reasons: [WHY], lower_bound_pointers: ["/cable_map/cables/35"],
          detail: `LOWER BOUND, at least 42 endpoint(s) stranded: ${WHY}. VLAN 10: Hard partition` },
        { host: "dist1", severity: "Medium", stranded: 7, vlans_impacted: null, lower_bound: false,
          detail: "not collected: this per-VLAN detail is withheld" },
        { host: "", severity: "NOT ASSESSED", stranded: null, vlans_impacted: null, n_not_ranked: 2,
          detail: `2 failure-impact row(s) were not ranked because the engine withholds their host, severity or stranded count, so any of them could rank above the devices shown: acc — ${HELD}.` },
      ],
    });
    renderSnap();
    const panel = await keystonePanel();
    expect(within(panel).queryByText(/No keystone devices flagged/)).toBeNull();

    // core2: the pre-W47 table printed 42 and 3 as plain numbers, an exact-looking measurement
    const core2 = rowOf(panel, "core2");
    const [, , stranded, vlans] = cellsOf(core2);
    expect(within(core2).queryByText("42")).toBeNull();
    expect(within(core2).queryByText("3")).toBeNull();
    expect(stranded.querySelector('[data-impact="lower_bound"]')).toHaveTextContent("≥ 42");
    // a toggletip: named by its state, described by its reason, no title beside the description
    const strandedBound = within(stranded).getByRole("button", { name: "At least 42" });
    expect(strandedBound).toHaveAttribute("data-impact", "lower_bound");
    expect(strandedBound).toHaveAccessibleDescription(/^At least 42: a lower bound, not an exact measurement/);
    expect(strandedBound).not.toHaveAttribute("title");
    expect(vlans.querySelector('[data-impact="lower_bound"]')).toHaveTextContent("≥ 3");

    // the NOT ASSESSED disclosure: said in both count columns, never "—", "0" or blank, and the device column says why
    const note = rowOf(panel, "2 row(s) not ranked");
    for (const td of cellsOf(note).slice(2, 4)) {
      expect(td.querySelector('[data-impact="not_assessed"]')?.firstChild?.textContent).toBe("NOT ASSESSED");
      expect(td.textContent).not.toMatch(/^\s*(0|—)?\s*$/);
    }
    expect(within(note).queryByText("0")).toBeNull();

    // dist1: a withheld VLAN count is unavailable, not "—" and not 0; its measured stranded stays exact
    const dist1 = rowOf(panel, "dist1");
    const [, , dStranded, dVlans] = cellsOf(dist1);
    expect(dVlans.querySelector('[data-impact="unavailable"]')?.firstChild?.textContent).toBe("unavailable");
    expect(within(dist1).queryByText("0")).toBeNull();
    expect(within(dStranded).getByText("7")).toHaveAttribute("data-impact", "measured");

    // the control: core1's exact counts render as measurements, with no lower-bound treatment
    const core1 = rowOf(panel, "core1");
    expect(within(core1).getByText("45")).toHaveAttribute("data-impact", "measured");
    expect(core1.querySelector('[data-impact="lower_bound"]')).toBeNull();
  });

  it("keystones: an empty ranking reads NOT ASSESSED, never 'no single switch dominates'", async () => {
    // summary._keystones lists every rankable row and discloses every other one, so [] means there was no
    // failure-impact row to rank (a collected-but-empty list): nothing was compared, and dominance was never computed.
    mockImpact({ keystone_contract: 4, keystones: [] });
    renderSnap();
    const panel = await keystonePanel();
    expect(panel.querySelector('[data-impact="not_assessed"]')).toHaveTextContent("NOT ASSESSED");
    // collected but empty is not assessed, never the absent list's "unavailable" (Unit 10 above)
    expect(panel).toHaveAttribute("data-keystones", "not_ranked");
    expect(panel.querySelector('[data-impact="unavailable"]')).toBeNull();
    expect(panel).toHaveTextContent(/No keystone ranking was computed: the summary carries no failure-impact row to rank/);
    expect(panel).toHaveTextContent(/This is not a finding that no single switch dominates/);
    expect(within(panel).queryByText(/No keystone devices flagged/)).toBeNull();
    expect(panel.querySelector("table")).toBeNull();
    expect(within(panel).queryByText("0")).toBeNull();
  });

  it("the Failure impact tab: a row key outside the engine's fields is disclosed, never dropped silently", async () => {
    mockImpact({ sections: [{ key: "failure_impact", label: "Failure impact", count: 1 }] }, [
      { host: "core1", severity: "High", vlans_impacted: 4, stranded: 45, hard: 4, backup: 0, fhrp: 0,
        off_scan_gw_vlans: 0, detail: "VLAN 20: Hard partition", future_measure: 7 },
    ]);
    renderSnap();
    const panel = await screen.findByRole("tabpanel", { name: /Failure impact/ });
    await within(panel).findByText("core1");
    const note = panel.querySelector('[data-impact="unrecognised_columns"]') as HTMLElement;
    expect(note).not.toBeNull();
    expect(note).toHaveTextContent(/1 unrecognised column\(s\) in the failure-impact rows, not shown here: future_measure/);
    expect(note.querySelector('[data-impact="not_assessed"]')).not.toBeNull();
    // its value is not shown as a bare number in a column this screen cannot classify
    expect(within(panel).queryByText("7")).toBeNull();
    expect(Array.from(panel.querySelectorAll("th")).map((th) => th.textContent)).not.toContain("future_measure");
  });

  it("the Failure impact tab: rows with only the engine's fields carry no unrecognised-column note", async () => {
    mockImpact({ sections: [{ key: "failure_impact", label: "Failure impact", count: 1 }] }, [
      { host: "core1", severity: "High", vlans_impacted: 4, stranded: 45, hard: 4, backup: 0, fhrp: 0,
        off_scan_gw_vlans: 0, detail: "VLAN 20: Hard partition" },
    ]);
    renderSnap();
    const panel = await screen.findByRole("tabpanel", { name: /Failure impact/ });
    await within(panel).findByText("core1");
    expect(panel.querySelector('[data-impact="unrecognised_columns"]')).toBeNull();
  });

  it("the Failure impact tab: ≥ N for a lower bound, NOT ASSESSED for a held cell, a published 0 stays 0", async () => {
    const MEASURES = ["severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp"];
    mockImpact({ sections: [{ key: "failure_impact", label: "Failure impact", count: 3 }] }, [
      { host: "core2", severity: bound("High"), vlans_impacted: bound(3), stranded: bound(42), hard: bound(3),
        backup: ZERO_BOUND, fhrp: ZERO_BOUND, off_scan_gw_vlans: 0, detail: "VLAN 10: Hard partition" },
      { host: "acc", ...Object.fromEntries(MEASURES.map((f) => [f, HELD])), off_scan_gw_vlans: 1,
        detail: "Blast radius INDETERMINATE: VLAN 30 has an off-scan gateway" },
      { host: "core1", severity: "High", vlans_impacted: 4, stranded: 45, hard: 4, backup: 0, fhrp: 0,
        off_scan_gw_vlans: 0, detail: "VLAN 20: Hard partition" },
    ]);
    renderSnap();
    const panel = await screen.findByRole("tabpanel", { name: /Failure impact/ });
    const core2 = (await within(panel).findByText("core2")).closest("tr") as HTMLElement;
    const header = Array.from(panel.querySelectorAll("th")).map((th) => th.textContent);
    // all nine producer fields show: the generic table's 8-column cap dropped the detail
    expect(header).toEqual(["host", "severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp",
      "off_scan_gw_vlans", "detail"]);
    const col = (row: HTMLElement, field: string) => cellsOf(row)[header.indexOf(field)];

    // core2: High and each positive count are published lower bounds; its zeros are held, never shown as 0
    for (const field of ["severity", "vlans_impacted", "stranded", "hard"]) {
      const cell = col(core2, field).querySelector('[data-impact="lower_bound"]');
      expect(cell, field).not.toBeNull();
      expect(cell?.getAttribute("title"), field).toMatch(/a lower bound, not an exact measurement/);
    }
    expect(col(core2, "stranded").querySelector('[data-impact="lower_bound"]')).toHaveTextContent("≥ 42");
    for (const field of ["backup", "fhrp"]) {
      expect(col(core2, field).querySelector('[data-impact="not_assessed"]')?.getAttribute("title")).toBe(ZERO_BOUND);
      expect(col(core2, field).textContent).not.toMatch(/^\s*0\s*$/);
    }

    // acc: every measure is held: NOT ASSESSED with the projection's reason, never Info, 0 or a blank cell
    const acc = within(panel).getByText("acc").closest("tr") as HTMLElement;
    for (const field of MEASURES) {
      const cell = col(acc, field).querySelector('[data-impact="not_assessed"]');
      expect(cell?.firstChild?.textContent, field).toBe("NOT ASSESSED");
      expect(cell?.getAttribute("title"), field).toBe(HELD);
    }
    expect(col(acc, "off_scan_gw_vlans").querySelector('[data-impact="measured"]')).toHaveTextContent(/^1$/);

    // the control: core1's exact row renders as measured, a published 0 included
    const core1 = within(panel).getByText("core1").closest("tr") as HTMLElement;
    expect(col(core1, "backup").querySelector('[data-impact="measured"]')).toHaveTextContent(/^0$/);
    expect(col(core1, "stranded").querySelector('[data-impact="measured"]')).toHaveTextContent(/^45$/);
    expect(core1.querySelector('[data-impact="lower_bound"], [data-impact="not_assessed"]')).toBeNull();
  });

  it("the Failure impact tab: at most one tab stop per row, a disclosure that reveals that row's reasons", async () => {
    // Every qualified cell used to be its own focusable value: an all-held fleet at ROW_CAP (200) rows put about 1,200
    // tab stops before the next control. Each row now carries at most one, a disclosure in its host cell that lists
    // the reason of each of its values that is not a measurement. A fully measured row has none.
    const MEASURES = ["severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp"];
    const heldRow = (host: string) => ({ host, ...Object.fromEntries(MEASURES.map((f) => [f, HELD])),
      off_scan_gw_vlans: null, detail: "Blast radius INDETERMINATE: VLAN 30 has an off-scan gateway" });
    const fleet = [
      { host: "core1", severity: "High", vlans_impacted: 4, stranded: 45, hard: 4, backup: 0, fhrp: 0,
        off_scan_gw_vlans: 0, detail: "VLAN 20: Hard partition" },
      { host: "core2", severity: bound("High"), vlans_impacted: bound(3), stranded: bound(42), hard: bound(3),
        backup: ZERO_BOUND, fhrp: ZERO_BOUND, off_scan_gw_vlans: 0, detail: "VLAN 10: Hard partition" },
      ...Array.from({ length: 12 }, (_, i) => heldRow(`acc${i}`)),
    ];
    mockImpact({ sections: [{ key: "failure_impact", label: "Failure impact", count: fleet.length }] }, fleet);
    renderSnap();
    const panel = await screen.findByRole("tabpanel", { name: /Failure impact/ });
    await within(panel).findByText("core1");
    const FOCUSABLE = 'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    const rows = Array.from(panel.querySelectorAll("tbody > tr:not(.impact-reasons)")) as HTMLElement[];
    expect(rows).toHaveLength(fleet.length);
    for (const row of rows) expect(row.querySelectorAll(FOCUSABLE).length).toBeLessThanOrEqual(1);
    // the whole table: one stop for each row with something to disclose, none for the fully measured control, and no
    // per-cell toggletip anywhere
    const table = panel.querySelector("table") as HTMLElement;
    expect(table.querySelectorAll(FOCUSABLE)).toHaveLength(fleet.length - 1);
    expect(table.querySelectorAll(".impact-why")).toHaveLength(0);
    const core1 = within(panel).getByText("core1").closest("tr") as HTMLElement;
    expect(core1.querySelectorAll(FOCUSABLE)).toHaveLength(0);
    expect(core1.nextElementSibling?.classList.contains("impact-reasons")).toBe(false);

    // core2: one non-submitting disclosure, collapsed, controlling the hidden row beneath
    const core2 = within(panel).getByText("core2").closest("tr") as HTMLElement;
    const toggle = within(core2).getByRole("button", { name: /^Reasons for core2: 6 value\(s\) not measured$/ });
    expect(toggle).toHaveAttribute("type", "button");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const reasons = document.getElementById(toggle.getAttribute("aria-controls")!) as HTMLElement;
    expect(reasons).toBe(core2.nextElementSibling);
    expect(reasons).not.toBeVisible();
    // the cells themselves show their state as text, are no tab stop, and carry no second description
    for (const value of Array.from(core2.querySelectorAll("[data-impact]"))) {
      expect(value.tagName).toBe("SPAN");
      expect(value).not.toHaveAttribute("aria-describedby");
    }
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAccessibleName(/^Hide reasons for core2/);
    expect(reasons).toBeVisible();
    const items = within(reasons).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("data-impact-reason"))).toEqual(MEASURES);
    expect(items[2]).toHaveTextContent(`stranded (≥ 42): At least 42: a lower bound, not an exact measurement. Why: ${WHY}.`);
    expect(items[0]).toHaveTextContent(/^severity \(≥ High\): At least High: a lower bound/);
    expect(items[4]).toHaveTextContent(`backup (NOT ASSESSED): ${ZERO_BOUND}`);
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(reasons).not.toBeVisible();

    // an all-held row lists every held cell, and its withheld off-scan count as unavailable
    const acc0 = within(panel).getByText("acc0").closest("tr") as HTMLElement;
    const accToggle = within(acc0).getByRole("button", { name: /^Reasons for acc0: 7 value\(s\) not measured$/ });
    fireEvent.click(accToggle);
    const accItems = within(document.getElementById(accToggle.getAttribute("aria-controls")!) as HTMLElement)
      .getAllByRole("listitem");
    expect(accItems.map((li) => li.getAttribute("data-impact-reason"))).toEqual([...MEASURES, "off_scan_gw_vlans"]);
    expect(accItems[0]).toHaveTextContent(`severity (NOT ASSESSED): ${HELD}`);
    expect(accItems[6]).toHaveTextContent(/^off_scan_gw_vlans \(unavailable\): Withheld by the engine/);
  });

  it("the Failure impact tab: a section the projection cannot list reads NOT ASSESSED with its reason", async () => {
    const reason = "unverified: the stored failure_impact section is not a list, so no row can be read";
    mockImpact({ sections: [{ key: "failure_impact", label: "Failure impact", count: 1 }] }, { state: "unverified", reason });
    renderSnap();
    const panel = await screen.findByRole("tabpanel", { name: /Failure impact/ });
    const held = await waitFor(() => {
      const node = panel.querySelector('[data-impact="not_assessed"]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    expect(held.getAttribute("title")).toBe(reason);
    expect(panel).toHaveTextContent(reason);
    // the reason is already visible beside the tag, so the tag is no tab stop and no second, described copy of it
    expect(held.tagName).toBe("SPAN");
    expect(held).not.toHaveAttribute("tabindex");
    expect(held).not.toHaveAttribute("aria-describedby");
    expect(within(panel).queryByRole("button")).toBeNull();
    expect(panel.querySelector(".impact-why")).toBeNull();
    expect(within(panel).getAllByText(reason, { exact: false })).toHaveLength(1);
    expect(within(panel).queryByText("0")).toBeNull();
    expect(within(panel).queryByText("Info")).toBeNull();
  });
});
