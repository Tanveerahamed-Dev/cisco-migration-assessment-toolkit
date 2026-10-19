import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../savedPlanApi";
import type { Deliverable, Meta, SavedPlanRecord, SavedPlanState } from "../savedPlanApi";
import SavedPlanPage from "./SavedPlan";

function record(revision = 1, selection = 3, sid = 1): SavedPlanRecord {
  const requirements = { availability_tier: "gold", critical_apps: ["voice", "video"],
    convergence_budget_ms: 0, fabric_operating_model: "aci", constraints: ["budget"] };
  const blueprint = {
    decisions: [{ id: "EXAMPLE-decision", title: `Saved design decision ${revision}`,
      domain: "EXAMPLE", priority: "High", status: "recommended", confidence: "Requirement-driven",
      driver: "EXAMPLE supplied requirement", evidence: { summary: "EXAMPLE", count: 1, devices: [], fields: [] },
      principle: { id: "EXAMPLE", title: "EXAMPLE principle", citation: "EXAMPLE reference" },
      recommended_action: "EXAMPLE saved action", alternatives: "", tradeoffs: "", axes: [], requirements_needed: [] }],
    tradeoff_scorecard: [], requirements_model: { provided: true, fields: [], open_questions: [], note: "EXAMPLE requirements" },
    methodology: "EXAMPLE", axes: [], coverage: { inventory: 1, collected: 1, not_collected: 0, caveat: "EXAMPLE scope" },
    summary: { n_decisions: 1, n_recommended: 1, n_needs_requirement: 0, n_critical: 0,
      by_domain: { EXAMPLE: 1 }, requirements_provided: true, headline: `Saved EXAMPLE design ${revision} for source ${sid}` },
  };
  const nrfu = { items: [{ decision_id: "EXAMPLE-decision", title: `Verify saved design ${revision}`,
    priority: "High", phase: "post-cutover-functional" as const, description: "EXAMPLE planned verification",
    pass_criteria: "EXAMPLE expected observed state", setup: "EXAMPLE test preparation", devices: [], principle_citation: "EXAMPLE" }],
    n_items: 1, note: "EXAMPLE planned checks, not passed results." };
  return {
    vlan_form_rows: [], schema: "atlas.saved_plan/1", revision, label: `EXAMPLE plan ${revision}`, created_at: "2026-10-16T00:00:00Z",
    sha256: `sha256:${String(revision).repeat(64)}`, status: "UNAPPROVED_DRAFT", selection_id: selection,
    assessment: { source: "persisted snapshots.snapshot_json blob", sha256: `sha256:${"a".repeat(64)}`,
      bytes: 100, snapshot_id: sid, campaign_id: 7, engagement_id: "EXAMPLE-engagement", label: `EXAMPLE source ${sid}`, script_version: "3.23.0" },
    projection: { schema: "atlas.saved_plan_projection/2", requirements,
      sections: { requirements_register: requirements, design_blueprint: blueprint, design_nrfu: nrfu },
      derivation: { schema: "atlas.saved_plan_derivation/2", profile: "saved_plan", owners: ["EXAMPLE-owner"], engine_schema_version: "3.23.0",
        implementation_identity: null, implementation_identity_status: "not_established", authority: "none", note: "EXAMPLE persisted projection" } },
  } as SavedPlanRecord;
}

function state(selected: SavedPlanRecord | null = record(), rows = selected ? [selected] : [], sid = 1): SavedPlanState {
  return { assessment: selected?.assessment ?? record(1, 3, sid).assessment,
    selection_id: selected?.selection_id ?? 0, selected_revision: selected?.revision ?? null,
    revisions: rows.map(({ schema, revision, label, created_at, sha256, status }) =>
      ({ schema, revision, label, created_at, sha256, status })) };
}

const kinds = ["engagement", "crd", "runbook", "design", "archreview", "mop", "cutover", "nrfu", "opshandbook", "deck"];
function catalogue(): Meta {
  return { requirementsContract: { availability_tiers: ["gold", "silver", "bronze"], fabric_models: ["nxos-evpn", "aci"],
    vlan_id: { minimum: 1, maximum: 4094 }, convergence_budget_ms: { minimum: 0, maximum: 9007199254740991 } },
    display_limits: { revision_maximum: 64, label_maximum_code_points: 200 },
    deliverables: kinds.map((key) => ({ key, label: `EXAMPLE ${key} document`, available: true,
      ext: key === "deck" ? "pptx" : "docx", saved_plan_supported: true,
      saved_plan_basis: ["design", "crd", "mop", "nrfu", "deck"].includes(key) ? "selected-requirements" : "assessment-baseline" })) };
}

function Harness() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/snapshots/2/plans")}>Switch source</button>
    <Routes><Route path="/snapshots/:id/plans" element={<SavedPlanPage />} /></Routes></>;
}
const show = (path = "/snapshots/1/plans") => render(<MemoryRouter initialEntries={[path]}><Harness /></MemoryRouter>);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function defaults(selected = record()) {
  const meta = vi.spyOn(api, "meta").mockResolvedValue(catalogue());
  const plans = vi.spyOn(api, "savedPlans").mockResolvedValue(state(selected));
  const reopen = vi.spyOn(api, "savedPlan").mockResolvedValue(selected);
  const save = vi.spyOn(api, "savePlan").mockResolvedValue(record(2, 4));
  const select = vi.spyOn(api, "selectSavedPlan").mockResolvedValue(record(1, 8));
  const download = vi.spyOn(api, "savedPlanDocument").mockImplementation(async (_sid, _plan, _kind, extension) =>
    ({ blob: new Blob(["EXAMPLE verified Office bytes"]), extension }));
  const preview = vi.spyOn(api, "designOverlay");
  const previewNrfu = vi.spyOn(api, "designNrfuOverlay");
  return { meta, plans, reopen, save, select, download, preview, previewNrfu };
}

describe("Saved plan field workflow", () => {
  const downloads: Array<{ name: string; href: string }> = [];
  beforeEach(() => {
    downloads.length = 0;
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = vi.fn(() => "blob:EXAMPLE-verified");
      static revokeObjectURL = vi.fn();
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push({ name: this.download, href: this.href });
    });
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("reopens the pinned saved projection and saves canonical zero without transient design calls", async () => {
    const calls = defaults();
    calls.save.mockResolvedValueOnce({ ...record(2, 4), label: "EXAMPLE second plan" });
    show();
    expect(await screen.findByText("Saved EXAMPLE design 1 for source 1")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Convergence budget (ms)" })).toHaveValue("0");
    expect(screen.getByText("Decisions needing requirements")).toBeInTheDocument();
    expect(calls.reopen).toHaveBeenCalledWith(1, 1, record().sha256, 3, expect.any(AbortSignal), record().assessment);
    fireEvent.change(screen.getByLabelText("Plan name"), { target: { value: "EXAMPLE second plan" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    expect(await screen.findByText("Saved EXAMPLE design 2 for source 1")).toBeInTheDocument();
    expect(calls.save).toHaveBeenCalledWith(1, expect.objectContaining({
      label: "EXAMPLE second plan", expected_selection_id: 3, assessment: record().assessment,
      requirements: expect.objectContaining({ convergence_budget_ms: "0", critical_apps: "voice, video" }),
    }), expect.any(AbortSignal));
    expect(calls.preview).not.toHaveBeenCalled();
    expect(calls.previewNrfu).not.toHaveBeenCalled();
    expect(calls.reopen).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Convergence budget (ms)")).toHaveValue("0");
    expect(screen.queryByText(/Unsaved changes\./)).not.toBeInTheDocument();
    expect(screen.getByText("Verify saved design 2")).toBeInTheDocument();
    expect(screen.getByText(/UNAPPROVED DRAFT/)).toBeInTheDocument();
  });

  it("creates the first revision from a confirmed empty history using selection zero", async () => {
    const calls = defaults();
    const source = state(null);
    calls.plans.mockResolvedValueOnce(source);
    calls.save.mockResolvedValueOnce({ ...record(1, 1), label: "EXAMPLE first plan" });
    show();
    expect(await screen.findByText("No saved plan revisions yet.")).toBeInTheDocument();
    expect(calls.reopen).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Download MOP" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Plan name"), { target: { value: "EXAMPLE first plan" } });
    fireEvent.change(screen.getByLabelText("Convergence budget (ms)"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    expect(await screen.findByText("Saved EXAMPLE design 1 for source 1")).toBeInTheDocument();
    expect(calls.save).toHaveBeenCalledWith(1, {
      label: "EXAMPLE first plan", assessment: source.assessment,
      requirements: { convergence_budget_ms: "0" }, expected_selection_id: 0,
    }, expect.any(AbortSignal));
    expect(screen.getByRole("button", { name: "Download MOP" })).toBeEnabled();
    expect(screen.queryByText("No saved plan revisions yet.")).not.toBeInTheDocument();
    expect(calls.reopen).not.toHaveBeenCalled();
  });

  it("blocks dirty exports and cleans the verified Blob URL and native download anchor", async () => {
    const calls = defaults();
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    const mop = screen.getByRole("button", { name: "Download MOP" });
    expect(mop).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Constraints"), { target: { value: "EXAMPLE unsaved change" } });
    expect(screen.getByText(/Unsaved changes\./)).toBeInTheDocument();
    expect(mop).toBeDisabled();
    fireEvent.click(mop);
    expect(calls.download).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getByLabelText("Constraints")).toHaveValue("budget");
    fireEvent.click(mop);
    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(downloads[0]).toEqual({ name: "Atlas-snapshot-1-plan-r1-mop.docx", href: "blob:EXAMPLE-verified" });
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:EXAMPLE-verified");
    expect(document.querySelector("a[download]")).toBeNull();
    expect(calls.download).toHaveBeenCalledWith(1, expect.objectContaining({ revision: 1, selection_id: 3, sha256: record().sha256 }), "mop", "docx", expect.any(AbortSignal), "selected-requirements");
  });

  it("offers all ten registry documents with the same pin and distinct useful names, with server-owned PIR refusal and CLI-only XLSX", async () => {
    const calls = defaults();
    const meta = catalogue();
    meta.deliverables.push({ key: "pir", label: "Forbidden premature PIR", ext: "docx", available: true, saved_plan_basis: null, saved_plan_supported: false });
    calls.meta.mockResolvedValue(meta);
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    fireEvent.click(screen.getByText("Other document drafts"));
    for (const kind of kinds) {
      const name = kind === "mop" ? "Download MOP" : kind === "nrfu" ? "Download NRFU" : `EXAMPLE ${kind} document`;
      fireEvent.click(screen.getByRole("button", { name }));
      await waitFor(() => expect(calls.download).toHaveBeenCalledWith(
        1, expect.objectContaining({ revision: 1, selection_id: 3, sha256: record().sha256 }),
        kind, kind === "deck" ? "pptx" : "docx", expect.any(AbortSignal), meta.deliverables.find((entry) => entry.key === kind)!.saved_plan_basis,
      ));
      await waitFor(() => expect(screen.getByRole("button", { name })).toBeEnabled());
    }
    expect(calls.download).toHaveBeenCalledTimes(10);
    expect(new Set(downloads.map((item) => item.name)).size).toBe(10);
    expect(downloads.map((item) => item.name)).toContain("Atlas-snapshot-1-plan-r1-nrfu.docx");
    expect(downloads.map((item) => item.name)).toContain("Atlas-snapshot-1-plan-r1-deck.pptx");
    expect(screen.getByRole("button", { name: "Forbidden premature PIR" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /workbook|xlsx/i })).not.toBeInTheDocument();
    expect(screen.getByText(/workbook remains CLI-only/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open original assessment JSON" })).toHaveAttribute("href", "/api/snapshots/1/raw");
    expect(screen.getByRole("link", { name: "Download original Protocol Assurance JSON" })).toHaveAttribute("href", "/api/snapshots/1/protocol-assurance/export");
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(10);
  });

  it("does not download before API verification succeeds, and removes resources even if native click fails", async () => {
    const calls = defaults();
    const pending = deferred<{ blob: Blob; extension: "docx" }>();
    calls.download.mockReturnValueOnce(pending.promise);
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    fireEvent.click(screen.getByRole("button", { name: "Download MOP" }));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    await act(async () => pending.reject(new ApiError("Document identity could not be verified", 502)));
    expect(await screen.findByText(/Document identity could not be verified/)).toBeInTheDocument();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    vi.mocked(HTMLAnchorElement.prototype.click).mockImplementationOnce(() => { throw new Error("EXAMPLE native download failed"); });
    fireEvent.click(screen.getByRole("button", { name: "Download NRFU" }));
    expect(await screen.findByText(/EXAMPLE native download failed/)).toBeInTheDocument();
    expect(document.querySelector("a[download]")).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:EXAMPLE-verified");
  });

  it("keeps loading, unavailable, unclassified and failed catalogue states distinct from an empty catalogue", async () => {
    const calls = defaults();
    const pending = deferred<Meta>();
    calls.meta.mockReturnValueOnce(pending.promise);
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    expect(screen.getByText("Loading document availability…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download MOP" })).toBeDisabled();
    const meta = catalogue();
    meta.deliverables.find((item) => item.key === "mop")!.available = false;
    meta.deliverables.push({ key: "unclassified", label: "Unclassified document", available: true, ext: "docx" } as Deliverable);
    await act(async () => pending.resolve(meta));
    expect(screen.getByText("Unavailable in this installation.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download MOP" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download NRFU" })).toBeEnabled();
    fireEvent.click(screen.getByText("Other document drafts"));
    expect(screen.getByRole("button", { name: "Unclassified document" })).toBeDisabled();
    calls.meta.mockRejectedValueOnce(new ApiError("EXAMPLE catalogue offline", 503));
    fireEvent.click(screen.getByRole("button", { name: "Reload saved plans" }));
    expect(await screen.findByText(/Document catalogue could not be read: EXAMPLE catalogue offline/)).toBeInTheDocument();
    expect(screen.queryByText("No document entries were provided by this server.")).not.toBeInTheDocument();
    expect(screen.queryByText("No saved plan revisions yet.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download NRFU" })).toBeDisabled();
    calls.meta.mockRejectedValueOnce(new ApiError("document catalogue returned unsupported data", 502));
    fireEvent.click(screen.getByRole("button", { name: "Reload saved plans" }));
    expect(await screen.findByText(/document catalogue returned unsupported data/)).toBeInTheDocument();
    expect(screen.queryByText("No document entries were provided by this server.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download NRFU" })).toBeDisabled();
  });

  it("does not render a failed source read as no saved revisions", async () => {
    const calls = defaults();
    calls.plans.mockRejectedValue(new ApiError("EXAMPLE source not readable", 503));
    show();
    expect(await screen.findByText(/EXAMPLE source not readable/)).toBeInTheDocument();
    expect(screen.queryByText("No saved plan revisions yet.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save new revision" })).toBeDisabled();
    expect(calls.reopen).not.toHaveBeenCalled();
  });

  it("uses compare-and-select and blocks an ABA conflict until an explicit reload, without latest fallback", async () => {
    const second = record(2, 7);
    const first = record(1, 3);
    const calls = defaults(second);
    calls.plans.mockResolvedValueOnce(state(second, [first, second]));
    calls.select.mockRejectedValueOnce(new ApiError("EXAMPLE selection changed", 409));
    show();
    await screen.findByText("Saved EXAMPLE design 2 for source 1");
    fireEvent.click(screen.getByRole("button", { name: "Select revision 1" }));
    expect(await screen.findByText(/EXAMPLE selection changed/)).toBeInTheDocument();
    expect(calls.select).toHaveBeenCalledWith(1, 1, { plan_sha256: first.sha256, expected_selection_id: 7 }, expect.any(AbortSignal), second.assessment);
    expect(screen.getByRole("button", { name: "Save new revision" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download MOP" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Select revision 1" })).toBeDisabled();
    expect(calls.plans).toHaveBeenCalledTimes(1);
    expect(calls.reopen).toHaveBeenCalledTimes(1);
    const recovered = record(1, 9);
    calls.plans.mockResolvedValueOnce(state(recovered, [first, second]));
    calls.reopen.mockResolvedValueOnce(recovered);
    fireEvent.click(screen.getByRole("button", { name: "Reload saved plans" }));
    expect(await screen.findByText("Saved EXAMPLE design 1 for source 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download MOP" })).toBeEnabled();
    expect(calls.reopen).toHaveBeenLastCalledWith(1, 1, first.sha256, 9, expect.any(AbortSignal), recovered.assessment);
  });

  it("freezes stale downloads on a 409 without silently requesting the latest revision", async () => {
    const calls = defaults();
    calls.download.mockRejectedValueOnce(new ApiError("EXAMPLE stale download selection", 409));
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    fireEvent.click(screen.getByRole("button", { name: "Download MOP" }));
    expect(await screen.findByText(/EXAMPLE stale download selection/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download NRFU" })).toBeDisabled();
    expect(downloads).toHaveLength(0);
    expect(calls.plans).toHaveBeenCalledTimes(1);
    expect(calls.reopen).toHaveBeenCalledTimes(1);
  });

  it("aborts and ignores a late saved-plan source after navigating to another assessment", async () => {
    const calls = defaults();
    const old = deferred<SavedPlanState>();
    calls.plans.mockImplementation((sid) => sid === 1 ? old.promise : Promise.resolve(state(record(1, 3, 2))));
    calls.reopen.mockImplementation(async (sid) => record(1, 3, sid));
    show();
    const signal = calls.plans.mock.calls[0][1];
    fireEvent.click(screen.getByRole("button", { name: "Switch source" }));
    await screen.findByText("Saved EXAMPLE design 1 for source 2");
    expect(signal?.aborted).toBe(true);
    await act(async () => old.resolve(state(record())));
    expect(screen.queryByText("EXAMPLE source 1")).not.toBeInTheDocument();
    expect(calls.reopen.mock.calls.every(([sid]) => sid === 2)).toBe(true);
  });

  it("never offers an old-source file whose verified response arrives after navigation", async () => {
    const calls = defaults();
    calls.plans.mockImplementation(async (sid) => state(record(1, 3, sid)));
    calls.reopen.mockImplementation(async (sid) => record(1, 3, sid));
    const pending = deferred<{ blob: Blob; extension: "docx" }>();
    calls.download.mockReturnValueOnce(pending.promise);
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    fireEvent.click(screen.getByRole("button", { name: "Download MOP" }));
    const signal = calls.download.mock.calls[0][4];
    fireEvent.click(screen.getByRole("button", { name: "Switch source" }));
    await screen.findByText("Saved EXAMPLE design 1 for source 2");
    expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve({ blob: new Blob(["EXAMPLE old file"]), extension: "docx" }));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(downloads).toHaveLength(0);
  });

  it.each(["10=Users\n10=Servers", "010=Users\n10=Servers", "4095=Users"])("preserves raw VLAN rows and displays the owner refusal: %s", async (zones) => {
    const calls = defaults();
    calls.save.mockRejectedValueOnce(new ApiError("VLAN requirements were not admitted", 400));
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    fireEvent.click(screen.getByText("Advanced: VLAN zones"));
    fireEvent.change(screen.getByLabelText("VLAN zones — one assignment per line"), { target: { value: zones } });
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/VLAN/);
    expect(calls.save).toHaveBeenCalledOnce();
    expect(calls.save.mock.calls[0][1].requirements.vlan_zones).toEqual({ raw_rows: zones.split("\n").map((line) => { const [vids, zone] = line.split("="); return { vids, zone }; }) });
  });

  it.each(["-1", "0.5", "1e3", "１２", "9007199254740992", "9007199254740993", "9223372036854775808"])("preserves convergence text and displays the owner refusal: %s", async (value) => {
    const calls = defaults();
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    calls.save.mockRejectedValueOnce(new ApiError("Convergence budget was not admitted", 400));
    fireEvent.change(screen.getByLabelText("Convergence budget (ms)"), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Convergence budget/);
    expect(calls.save).toHaveBeenCalledOnce();
    expect(calls.save.mock.calls[0][1].requirements.convergence_budget_ms).toBe(value);
  });

  it("preserves the maximum supported whole-millisecond text and exposes native keyboard form semantics", async () => {
    const calls = defaults();
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    const name = screen.getByRole("textbox", { name: "Plan name" });
    name.focus();
    expect(name).toHaveFocus();
    const convergence = screen.getByRole("textbox", { name: "Convergence budget (ms)" });
    fireEvent.change(convergence, { target: { value: "9007199254740991" } });
    expect(convergence).toHaveAccessibleDescription("Whole milliseconds, from 0 to 9007199254740991.");
    expect(screen.getByRole("button", { name: "Save new revision" })).toHaveAttribute("type", "submit");
    fireEvent.submit(name.closest("form")!);
    await waitFor(() => expect(calls.save).toHaveBeenCalled());
    expect(calls.save.mock.calls[0][1].requirements.convergence_budget_ms).toBe("9007199254740991");
  });
  it("renders the zero-count engine NRFU note without a client-authored empty verdict", async () => {
    const plan = record();
    plan.projection.sections.design_nrfu = { n_items: 0, items: [],
      note: "Design-driven NRFU/ATP checklist: 0 acceptance-test item(s) — EXAMPLE owner note." };
    defaults(plan); show();
    expect(await screen.findByText(/0 acceptance-test item/)).toBeInTheDocument();
    expect(document.querySelectorAll(".saved-plan-checklist li")).toHaveLength(0);
    expect(screen.queryByText("No NRFU item rows were supplied for this revision.")).not.toBeInTheDocument();
  });

  it("renders unknown owner basis verbatim while obeying its unavailable support flag", async () => {
    const calls = defaults();
    const meta = catalogue();
    meta.deliverables.push({ key: "future", label: "EXAMPLE future document", ext: "docx", available: true,
      saved_plan_basis: "EXAMPLE_OWNER_BASIS", saved_plan_supported: false });
    calls.meta.mockResolvedValueOnce(meta);
    show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    fireEvent.click(screen.getByText("Other document drafts"));
    expect(screen.getByRole("button", { name: "EXAMPLE future document" })).toBeDisabled();
    expect(screen.getByText("EXAMPLE_OWNER_BASIS")).toBeInTheDocument();
    expect(calls.download).not.toHaveBeenCalled();
  });

  it("renders engine-grouped VLAN form rows and retains duplicate zone rows for the owner", async () => {
    const plan = record();
    plan.vlan_form_rows = [{ zone: "EXAMPLE zone", vids: "10, 20" }];
    const calls = defaults(plan); show();
    await screen.findByText("Saved EXAMPLE design 1 for source 1");
    fireEvent.click(screen.getByText("Advanced: VLAN zones"));
    const input = screen.getByLabelText("VLAN zones — one assignment per line");
    expect(input).toHaveValue("10, 20=EXAMPLE zone");
    fireEvent.change(input, { target: { value: " 10 = EXAMPLE zone \n20=EXAMPLE zone" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    await waitFor(() => expect(calls.save).toHaveBeenCalled());
    expect(calls.save.mock.calls[0][1].requirements.vlan_zones).toEqual({ raw_rows: [
      { zone: "EXAMPLE zone", vids: "10" }, { zone: "EXAMPLE zone", vids: "20" },
    ] });
  });

});
