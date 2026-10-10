import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import CampaignPage from "./pages/Campaign";
import { api } from "./api";
import type { Campaign, CampaignAdjacentComparison, CampaignTrendResponse, CompareResponse, GateBoardData,
  RehearsalImpactsView, SnapshotMeta } from "./api";
import { DISPLAY_ONLY_FIELDS, TREND_EXPORT_FIELDS, TREND_PAIR_EXPORT_FIELDS, comparisonExportDocument, exportJsonText,
  trendReceiptsExportDocument } from "./receiptExport";

// A downloaded receipt file holds bound evidence only. The display-only impacts_view AssessHub serves beside each
// trend pair and execution receipt (W50) must never reach either JSON export, and neither may any other key that is
// not part of the bound trend or comparison. These tests read the files the two buttons actually write.

const VIEW: RehearsalImpactsView = {
  schema: "rehearsal_impacts_view/1", display_only: true, available: false,
  code: "snapshot_unreadable", reason: "synthetic display-only reading",
};

// The comparison shape the Campaign page tests render (pages/Campaign.test.tsx trendPair).
function comparison(index: number): CompareResponse {
  return {
    verdict: "CLEAN", findings: {}, health: {}, cabling: { assessed: true, summary: {} },
    cutover_gate: {
      schema: "cutover_gate/1", verdict: "PASS", note: `server basis ${index}`,
      operator_note: `server operator decision ${index}`, delta_verdict: "CLEAN", delta_display: "CLEAN",
      delta_note: "legacy delta only", certificate_verdict: "PASS", certificate_note: "server precert",
      protocol_gate: "PASS", protocol_baseline_peers: 1, protocol_regressions: 0, protocol_coverage_gaps: 0,
      l2_rehearsal_status: "simulation_only", l2_rehearsal_note: `server-owned L2 basis ${index}`,
      l2_rehearsal_applicable_families: ["etherchannel"], l2_rehearsal_current_faults: 0,
      l2_rehearsal_projected_risks: 0, l2_rehearsal_not_verified: 0,
    },
    comparison_receipt: { schema: "protocol_receipt_envelope/1", payload_sha256: `sha256:payload-${index}`,
      receipt_sha256: `sha256:receipt-${index}` },
  } as unknown as CompareResponse;
}

function pair(index: number): CampaignAdjacentComparison {
  return {
    schema: "campaign_adjacent_comparison/1", index, from: `C${index + 1}`, to: `C${index + 2}`,
    before_snapshot_id: index + 1, after_snapshot_id: index + 2,
    before_label: `Wave ${index + 1}`, after_label: `Wave ${index + 2}`,
    comparison: comparison(index),
    impacts_view: VIEW,
    // A key a later server might add beside the comparison: not classified, so it must stay out of the file.
    rendered_hint: "display",
  } as CampaignAdjacentComparison;
}

function trend(): CampaignTrendResponse {
  return {
    verdict: "IMPROVING", verdict_note: "Aggregate direction only.", trajectory: [],
    adjacent_comparison_status: { schema: "campaign_adjacent_comparison_set/1", status: "verified", n_pairs_total: 2,
      n_pairs_returned: 2, complete: true, note: "Two adjacent receipts." },
    adjacent_comparisons: [pair(0), pair(1)],
    // An unclassified top-level key: it must stay out of the file as well.
    display_banner: "rendered only",
  } as CampaignTrendResponse;
}

/** Every key path in `value` named `key`, at any depth. */
function keyPaths(value: unknown, key: string, at = "$"): string[] {
  if (Array.isArray(value)) return value.flatMap((item, i) => keyPaths(item, key, `${at}[${i}]`));
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([k, v]) => [...(k === key ? [`${at}.${k}`] : []), ...keyPaths(v, key, `${at}.${k}`)]);
}

/** Why a trend file is not bound evidence only: a display-only key anywhere, or a key outside either allowlist. */
function trendFileProblems(file: unknown): string[] {
  const problems = DISPLAY_ONLY_FIELDS.flatMap((field) => keyPaths(file, field));
  const top = file as Record<string, unknown>;
  problems.push(...Object.keys(top).filter((k) => !(TREND_EXPORT_FIELDS as readonly string[]).includes(k)).map((k) => `$.${k}`));
  const pairs = Array.isArray(top.adjacent_comparisons) ? top.adjacent_comparisons as Record<string, unknown>[] : [];
  pairs.forEach((p, i) => problems.push(...Object.keys(p)
    .filter((k) => !(TREND_PAIR_EXPORT_FIELDS as readonly string[]).includes(k)).map((k) => `$.adjacent_comparisons[${i}].${k}`)));
  return problems;
}

/** Click `button` and return the parsed JSON file the download would write, and its name. */
function downloaded(button: HTMLElement): { name: string; file: unknown } {
  const original = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
  // Force the data-URL branch so the written text is readable from the anchor itself.
  Object.defineProperty(URL, "createObjectURL", { value: undefined, configurable: true, writable: true });
  const clicked: HTMLAnchorElement[] = [];
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push(this);
  });
  try {
    fireEvent.click(button);
  } finally {
    click.mockRestore();
    if (original) Object.defineProperty(URL, "createObjectURL", original);
    else delete (URL as unknown as Record<string, unknown>).createObjectURL;
  }
  expect(clicked).toHaveLength(1);
  const prefix = "data:application/json;charset=utf-8,";
  const href = clicked[0].getAttribute("href") ?? "";
  expect(href.startsWith(prefix)).toBe(true);
  return { name: clicked[0].download, file: JSON.parse(decodeURIComponent(href.slice(prefix.length))) };
}

describe("receipt exports carry bound evidence only", () => {
  afterEach(() => vi.restoreAllMocks());

  it("the trend document keeps every bound field and drops impacts_view and every unclassified key", () => {
    const raw = trend();
    const file = JSON.parse(exportJsonText(trendReceiptsExportDocument(raw)));
    expect(trendFileProblems(file)).toEqual([]);
    expect(file.verdict).toBe("IMPROVING");
    expect(file.adjacent_comparison_status).toEqual(raw.adjacent_comparison_status);
    expect(file.adjacent_comparisons).toHaveLength(2);
    file.adjacent_comparisons.forEach((p: Record<string, unknown>, i: number) => {
      for (const field of TREND_PAIR_EXPORT_FIELDS) expect(p[field], field).toEqual(raw.adjacent_comparisons![i][field]);
    });
  });

  it("negative control: the raw response (what the export used to write) fails the same check", () => {
    const problems = trendFileProblems(JSON.parse(JSON.stringify(trend())));
    expect(problems).toContain("$.adjacent_comparisons[0].impacts_view");
    expect(problems).toContain("$.adjacent_comparisons[1].rendered_hint");
    expect(problems).toContain("$.display_banner");
  });

  it("the comparison document is the comparison exactly, without any display-only field", () => {
    const bound = comparison(7);
    expect(exportJsonText(comparisonExportDocument(bound))).toBe(JSON.stringify(bound, null, 2));
    const carrying = { ...bound, impacts_view: VIEW } as unknown as CompareResponse;
    expect(keyPaths(comparisonExportDocument(carrying), "impacts_view")).toEqual([]);
  });

  it("Export Trend JSON and Export complete JSON write files without impacts_view", async () => {
    const campaign: Campaign = { id: 3, name: "East", description: "", created_at: "2026-01-01T00:00:00Z",
      snapshots: [1, 2].map((id) => ({ id, campaign_id: 3, label: `Wave ${id}`, uploaded_at: "2026-01-01T00:00:00Z",
        script_version: "3.30.0", n_devices: 10, summary: { bands: {} } } as unknown as SnapshotMeta)) };
    const gates: GateBoardData = { cadence: [], waves: [], records: [] };
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaign);
    vi.spyOn(api, "getGates").mockResolvedValue(gates);
    vi.spyOn(api, "trend").mockResolvedValue(trend());
    render(<MemoryRouter initialEntries={["/campaigns/3"]}><Routes>
      <Route path="/campaigns/:id" element={<CampaignPage />} /></Routes></MemoryRouter>);

    const trendFile = downloaded(await screen.findByRole("button", { name: "Export Trend JSON" }));
    expect(trendFile.name).toBe("atlas-campaign-3-trend-receipts.json");
    expect(trendFileProblems(trendFile.file)).toEqual([]);
    const pairs = (trendFile.file as { adjacent_comparisons: Array<{ comparison: CompareResponse }> }).adjacent_comparisons;
    expect(pairs.map((p) => p.comparison.comparison_receipt?.receipt_sha256)).toEqual(["sha256:receipt-0", "sha256:receipt-1"]);

    // The per-pair export (ComparisonDecision, rendered with the pair's impacts_view beside it) is the comparison alone.
    const pairFile = downloaded(screen.getAllByTestId("comparison-json-export")[0]);
    expect(keyPaths(pairFile.file, "impacts_view")).toEqual([]);
    expect(pairFile.file).toEqual(JSON.parse(JSON.stringify(comparison(0))));
  });
});
