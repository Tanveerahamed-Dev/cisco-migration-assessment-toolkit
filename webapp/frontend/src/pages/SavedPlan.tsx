import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router";
import { api, ApiError, SAVED_PLAN_MAX_CONVERGENCE_MS, designRequirementsContract } from "../api";
import type {
  Deliverable, Meta, SavedPlanPin, SavedPlanRecord, SavedPlanRequirements, SavedPlanState,
} from "../api";
import "./savedPlan.css";

type Draft = {
  label: string; tier: string; apps: string; convergence: string; growth: string;
  fabric: string; constraints: string; classification: string; address: string; zones: string;
};

const emptyDraft = (): Draft => ({
  label: "", tier: "", apps: "", convergence: "", growth: "", fabric: "",
  constraints: "", classification: "", address: "", zones: "",
});

function listText(value: unknown): string {
  return typeof value === "string" ? value : Array.isArray(value) ? value.join(", ") : "";
}

function planDraft(plan: SavedPlanRecord): Draft {
  const r = plan.projection.requirements;
  const zoneLines: string[] = [];
  for (const [key, value] of Object.entries(r.vlan_zones ?? {})) {
    if (typeof value === "string") zoneLines.push(`${key}=${value}`);
    else for (const vid of value) zoneLines.push(`${vid}=${key}`);
  }
  return {
    label: plan.label, tier: r.availability_tier ?? "", apps: listText(r.critical_apps),
    convergence: r.convergence_budget_ms === undefined ? "" : String(r.convergence_budget_ms),
    growth: r.growth_horizon ?? "", fabric: r.fabric_operating_model ?? "",
    constraints: listText(r.constraints), classification: listText(r.data_classification),
    address: r.address_space ?? "", zones: zoneLines.join("\n"),
  };
}

function formRequirements(draft: Draft): SavedPlanRequirements {
  const requirements: SavedPlanRequirements = {};
  if (draft.tier) requirements.availability_tier = draft.tier;
  if (draft.apps.trim()) requirements.critical_apps = draft.apps;
  // Keep the text, including "0". The server owns normalization, bounds and design reasoning.
  if (draft.convergence.trim()) {
    const text = draft.convergence.trim();
    if (!/^[0-9]{1,19}$/.test(text)) throw new Error("Convergence budget must be whole non-negative milliseconds, using at most 19 digits; 0 is allowed.");
    const digits = text.replace(/^0+/, "") || "0";
    if (digits.length > SAVED_PLAN_MAX_CONVERGENCE_MS.length
        || (digits.length === SAVED_PLAN_MAX_CONVERGENCE_MS.length && digits > SAVED_PLAN_MAX_CONVERGENCE_MS)) {
      throw new Error(`Convergence budget must be at most ${SAVED_PLAN_MAX_CONVERGENCE_MS} milliseconds on this page.`);
    }
    requirements.convergence_budget_ms = draft.convergence;
  }
  if (draft.growth.trim()) requirements.growth_horizon = draft.growth;
  if (draft.fabric) requirements.fabric_operating_model = draft.fabric;
  if (draft.constraints.trim()) requirements.constraints = draft.constraints;
  if (draft.classification.trim()) requirements.data_classification = draft.classification;
  if (draft.address.trim()) requirements.address_space = draft.address;
  if (draft.zones.trim()) {
    const zones: Record<string, string> = {};
    const seen = new Set<string>();
    for (const [index, line] of draft.zones.split(/\r?\n/).entries()) {
      if (!line.trim()) continue;
      const separator = line.indexOf("=");
      const vid = line.slice(0, separator).trim();
      const zone = line.slice(separator + 1).trim();
      const { minimum, maximum } = designRequirementsContract.vlan_id;
      if (separator < 1 || vid.length > String(maximum).length || !/^[1-9][0-9]*$/.test(vid) || !zone) {
        throw new Error(`VLAN zones line ${index + 1}: use one VLAN number without leading zeros, then = and a zone name.`);
      }
      if (Number(vid) < minimum || Number(vid) > maximum) {
        throw new Error(`VLAN zones line ${index + 1}: VLAN numbers must be between ${minimum} and ${maximum}.`);
      }
      // Detect duplicate lines before constructing an object could silently replace an earlier zone.
      if (seen.has(vid)) throw new Error(`VLAN ${vid} appears twice. Keep one zone assignment per VLAN.`);
      seen.add(vid);
      zones[vid] = zone;
    }
    requirements.vlan_zones = zones;
  }
  return requirements;
}

function pin(plan: SavedPlanRecord): SavedPlanPin {
  return { revision: plan.revision, sha256: plan.sha256, selection_id: plan.selection_id };
}

function samePin(a: SavedPlanPin, b: SavedPlanPin): boolean {
  return a.revision === b.revision && a.sha256 === b.sha256 && a.selection_id === b.selection_id;
}

function checkRecord(plan: SavedPlanRecord, state: SavedPlanState, requestedRevision?: number, requestedHash?: string) {
  const a = plan.assessment;
  const b = state.assessment;
  if (plan.status !== "UNAPPROVED_DRAFT" || !Number.isSafeInteger(plan.revision) || plan.revision < 1
      || !Number.isSafeInteger(plan.selection_id) || plan.selection_id < 1
      || (requestedRevision !== undefined && plan.revision !== requestedRevision)
      || (requestedHash !== undefined && plan.sha256 !== requestedHash)
      || a.source !== b.source || a.sha256 !== b.sha256 || a.bytes !== b.bytes
      || a.snapshot_id !== b.snapshot_id || a.campaign_id !== b.campaign_id
      || a.engagement_id !== b.engagement_id || a.label !== b.label || a.script_version !== b.script_version) {
    throw new ApiError("The saved plan identity differs from this assessment. Reload saved plans.", 409);
  }
}

function saveVerifiedDocument(blob: Blob, extension: "docx" | "pptx", snapshotId: number, revision: number, kind: string) {
  if (!Number.isSafeInteger(snapshotId) || snapshotId < 1 || !Number.isSafeInteger(revision) || revision < 1
      || !/^[a-z][a-z0-9_-]{0,63}$/.test(kind)) throw new Error("The document filename identity could not be verified.");
  let url: string | null = null;
  let anchor: HTMLAnchorElement | null = null;
  try {
    url = URL.createObjectURL(blob);
    anchor = document.createElement("a");
    anchor.href = url;
    // Only checked numeric identities and a closed ASCII registry key enter the literal extensions.
    // Neither customer labels nor paths become a file name; MOP and NRFU remain distinguishable.
    if (extension === "docx") anchor.download = `Atlas-snapshot-${snapshotId}-plan-r${revision}-${kind}.docx`;
    else anchor.download = `Atlas-snapshot-${snapshotId}-plan-r${revision}-${kind}.pptx`;
    document.body.appendChild(anchor);
    anchor.click();
  } finally {
    anchor?.remove();
    if (url !== null) URL.revokeObjectURL(url);
  }
}

function SavedPlanWorkspace({ snapshotId, activeSource }: {
  snapshotId: number; activeSource: { current: string | undefined };
}) {
  const formId = useId();
  const [state, setState] = useState<SavedPlanState | null>(null);
  const [selected, setSelected] = useState<SavedPlanRecord | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);
  const [metaLoading, setMetaLoading] = useState(true);
  const [error, setError] = useState("");
  const [metaError, setMetaError] = useState("");
  const [formError, setFormError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [savedDraft, setSavedDraft] = useState<Draft>(emptyDraft);
  const mounted = useRef(false);
  const epoch = useRef(0);
  const operation = useRef(false);
  const requests = useRef(new Set<AbortController>());
  const selectedRef = useRef<SavedPlanRecord | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(savedDraft);
  const current = useCallback((version: number, controller: AbortController) =>
    activeSource.current === String(snapshotId) && mounted.current
      && epoch.current === version && !controller.signal.aborted, [snapshotId, activeSource]);

  const adopt = useCallback((record: SavedPlanRecord) => {
    selectedRef.current = record;
    setSelected(record);
    const form = planDraft(record);
    setDraft(form);
    setSavedDraft(form);
    setFormError("");
  }, []);

  const reload = useCallback(() => {
    const version = ++epoch.current;
    for (const request of requests.current) request.abort();
    requests.current.clear();
    const controller = new AbortController();
    requests.current.add(controller);
    operation.current = false;
    selectedRef.current = null;
    setState(null); setSelected(null); setDraft(emptyDraft()); setSavedDraft(emptyDraft());
    setLoading(true); setMetaLoading(true); setMeta(null); setError(""); setMetaError("");
    setFormError(""); setConflict(false); setBusy(""); setMessage("");
    void api.meta().then((value) => {
      if (!Array.isArray(value?.deliverables) || value.deliverables.some((item) =>
        !item || typeof item.key !== "string" || typeof item.label !== "string"
        || typeof item.ext !== "string" || typeof item.available !== "boolean")) {
        throw new Error("The document catalogue returned unsupported data.");
      }
      if (current(version, controller)) setMeta(value);
    }).catch((reason: unknown) => {
      if (current(version, controller)) setMetaError(reason instanceof Error ? reason.message : "Document catalogue could not be read.");
    }).finally(() => {
      if (current(version, controller)) setMetaLoading(false);
    });
    void (async () => {
      const next = await api.savedPlans(snapshotId, controller.signal);
      if (!current(version, controller)) return;
      if (next.assessment.snapshot_id !== snapshotId || !Number.isSafeInteger(next.selection_id) || next.selection_id < 0) {
        throw new ApiError("The saved-plan source could not be confirmed. Reload saved plans.", 409);
      }
      if (next.revisions.some((row) => !Number.isSafeInteger(row.revision) || row.revision < 1)
          || (next.selected_revision !== null && (!Number.isSafeInteger(next.selected_revision) || next.selected_revision < 1))) {
        throw new ApiError("A saved revision identifier could not be confirmed. Reload saved plans.", 409);
      }
      let record: SavedPlanRecord | null = null;
      if (next.selected_revision !== null) {
        const row = next.revisions.find((entry) => entry.revision === next.selected_revision);
        if (!row) throw new ApiError("The selected revision is missing from the saved-plan list. Reload saved plans.", 409);
        record = await api.savedPlan(snapshotId, row.revision, row.sha256, next.selection_id, controller.signal);
        if (!current(version, controller)) return;
        checkRecord(record, next, row.revision, row.sha256);
        if (record.selection_id !== next.selection_id) throw new ApiError("The plan selection changed. Reload saved plans.", 409);
      }
      if (!current(version, controller)) return;
      setState(next);
      if (record) adopt(record);
    })().catch((reason: unknown) => {
      if (!current(version, controller)) return;
      setError(reason instanceof Error ? reason.message : "Saved plans could not be read.");
      setConflict(reason instanceof ApiError && reason.status === 409);
    }).finally(() => {
      if (current(version, controller)) setLoading(false);
      requests.current.delete(controller);
    });
  }, [snapshotId, current, adopt]);

  useEffect(() => {
    mounted.current = true;
    reload();
    return () => {
      mounted.current = false;
      ++epoch.current;
      for (const request of requests.current) request.abort();
      requests.current.clear();
    };
  }, [reload]);

  const change = (key: keyof Draft, value: string) => {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setFormError(""); setMessage("");
  };

  function mutationError(reason: unknown) {
    const knownValidation = reason instanceof ApiError && (reason.status === 400 || reason.status === 422);
    setError(reason instanceof Error ? reason.message : "The request could not be confirmed.");
    if (!knownValidation) setConflict(true);
    setMessage(knownValidation ? "Correct the requirements before saving." : "Reload saved plans before continuing; the request outcome may have changed the selection.");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!state || loading || conflict || operation.current) return;
    let requirements: SavedPlanRequirements;
    try {
      if (!draft.label.trim()) throw new Error("Give this revision a plan name.");
      requirements = formRequirements(draft);
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : "Check the requirements.");
      return;
    }
    operation.current = true;
    setBusy("save"); setError(""); setMessage("");
    const version = epoch.current;
    const controller = new AbortController();
    requests.current.add(controller);
    try {
      const record = await api.savePlan(snapshotId, {
        label: draft.label.trim(), requirements, assessment: state.assessment,
        expected_selection_id: state.selection_id,
      }, controller.signal);
      if (!current(version, controller)) return;
      checkRecord(record, state);
      if (record.selection_id <= state.selection_id || state.revisions.some((row) => row.revision === record.revision)) {
        throw new ApiError("The new revision identity could not be confirmed. Reload saved plans.", 409);
      }
      setState({ ...state, assessment: record.assessment, selection_id: record.selection_id,
        selected_revision: record.revision, revisions: [...state.revisions, {
          schema: record.schema, revision: record.revision, label: record.label,
          created_at: record.created_at, sha256: record.sha256, status: record.status,
        }] });
      adopt(record);
      setMessage(`Revision ${record.revision} saved and selected. It remains an unapproved draft.`);
    } catch (reason) {
      if (current(version, controller)) mutationError(reason);
    } finally {
      requests.current.delete(controller);
      if (current(version, controller)) { operation.current = false; setBusy(""); }
    }
  }

  async function select(revision: number, sha256: string) {
    if (!state || dirty || conflict || loading || operation.current) return;
    operation.current = true;
    setBusy(`select:${revision}`); setError(""); setMessage("");
    const version = epoch.current;
    const controller = new AbortController();
    requests.current.add(controller);
    try {
      const record = await api.selectSavedPlan(snapshotId, revision, {
        plan_sha256: sha256, expected_selection_id: state.selection_id,
      }, controller.signal);
      if (!current(version, controller)) return;
      checkRecord(record, state, revision, sha256);
      if (record.selection_id <= state.selection_id) throw new ApiError("The selection event did not advance. Reload saved plans.", 409);
      setState({ ...state, selection_id: record.selection_id, selected_revision: record.revision });
      adopt(record);
      setMessage(`Revision ${record.revision} selected. Its saved design and documents are shown below.`);
    } catch (reason) {
      if (current(version, controller)) mutationError(reason);
    } finally {
      requests.current.delete(controller);
      if (current(version, controller)) { operation.current = false; setBusy(""); }
    }
  }

  const blueprint = selected?.projection.sections.design_blueprint;
  const nrfu = selected?.projection.sections.design_nrfu;
  const previewAvailable = !!blueprint?.summary && Array.isArray(blueprint.decisions) && Array.isArray(nrfu?.items);
  const blocked = loading || conflict || !!busy || !state;
  const exportBlocked = blocked || dirty || !selected || !previewAvailable || metaLoading || !!metaError;
  const items = meta?.deliverables.filter((item) => item.key !== "pir") ?? [];

  async function download(item: Deliverable) {
    if (exportBlocked || !selected || !item.available || operation.current
        || (item.ext !== "docx" && item.ext !== "pptx")
        || (item.saved_plan_basis !== "selected-requirements" && item.saved_plan_basis !== "assessment-baseline")) return;
    operation.current = true;
    setBusy(`download:${item.key}`); setError(""); setMessage("");
    const version = epoch.current;
    const controller = new AbortController();
    const requested = selected;
    requests.current.add(controller);
    try {
      const document = await api.savedPlanDocument(snapshotId, requested, item.key, item.ext, controller.signal);
      if (!current(version, controller) || !selectedRef.current || !samePin(pin(selectedRef.current), pin(requested))) return;
      saveVerifiedDocument(document.blob, document.extension, snapshotId, requested.revision, item.key);
      setMessage(`${item.label} download prepared for revision ${requested.revision}.`);
    } catch (reason) {
      if (!current(version, controller)) return;
      setError(reason instanceof Error ? reason.message : "The document could not be downloaded.");
      if (reason instanceof ApiError && reason.status === 409) {
        setConflict(true);
        setMessage("The selection is stale. Reload saved plans before downloading again.");
      }
    } finally {
      requests.current.delete(controller);
      if (current(version, controller)) { operation.current = false; setBusy(""); }
    }
  }

  function documentButton(item: Deliverable | undefined, primaryLabel?: string) {
    const supported = item && (item.ext === "docx" || item.ext === "pptx")
      && (item.saved_plan_basis === "selected-requirements" || item.saved_plan_basis === "assessment-baseline");
    return <div className="saved-plan-document" key={primaryLabel ?? item?.key}>
      <button type="button" className={`btn ${primaryLabel ? "primary saved-plan-primary" : ""}`}
        disabled={exportBlocked || !item?.available || !supported}
        onClick={() => { if (item) void download(item); }}>
        {busy === `download:${item?.key}` ? "Preparing download…" : primaryLabel ?? item?.label}
      </button>
      {item && <p className="dim">{!item.available ? "Unavailable in this installation."
        : !supported ? "The server did not provide a supported saved-plan content basis or format."
        : item.saved_plan_basis === "selected-requirements" ? "Uses the saved requirements and design."
        : "Original assessment baseline associated with this revision; no new approval."}</p>}
      {!item && !metaLoading && !metaError && <p className="dim">Not listed by this installation.</p>}
    </div>;
  }

  const formDisabled = blocked;
  return <main className="saved-plan-page">
    <header className="saved-plan-header">
      <div><Link to={`/snapshots/${snapshotId}`}>← Assessment</Link><h1>Saved plans and downloads</h1>
        <p className="dim">Save requirements, choose a revision, then download matching MOP and NRFU drafts.</p></div>
      <button type="button" className="btn" onClick={reload} disabled={!!busy}>Reload saved plans</button>
    </header>
    <div role="status" aria-live="polite">{loading ? "Loading saved plans…" : message}</div>
    {error && <div role="alert" className="saved-plan-alert"><strong>{conflict ? "Selection needs reloading." : "Request failed."}</strong> {error}</div>}
    {conflict && <p className="saved-plan-alert">Plan actions are disabled. Use Reload saved plans to confirm the current selection; nothing will switch to the latest revision automatically.</p>}

    <section className="panel" aria-labelledby={`${formId}-source`}>
      <h2 id={`${formId}-source`}>Original assessment</h2>
      {state ? <><p><strong>{state.assessment.label}</strong> · Snapshot {state.assessment.snapshot_id}</p>
        <p className="saved-plan-hash">{state.assessment.sha256}</p>
        <div className="saved-plan-links"><a href={`/api/snapshots/${snapshotId}/raw`} target="_blank" rel="noreferrer">Open original assessment JSON</a>
          <a href={api.protocolAssuranceExportUrl(snapshotId)}>Download original Protocol Assurance JSON</a></div>
        <p className="dim">These are assessment evidence, separate from the selected design. The assessment workbook remains CLI-only; this page does not offer an XLSX download.</p></>
        : <p className="dim">{loading ? "Confirming assessment identity…" : "Assessment identity could not be loaded."}</p>}
    </section>

    <div className="saved-plan-editor-layout">
      <section className="panel" aria-labelledby={`${formId}-requirements`}>
        <h2 id={`${formId}-requirements`}>Requirements for a new revision</h2>
        <p className="dim">These design requirements are optional. The server evaluates them; unanswered questions remain open. Saving creates a new draft revision.</p>
        <form onSubmit={(event) => { void save(event); }}>
          <fieldset disabled={formDisabled} className="saved-plan-fields">
            <label htmlFor={`${formId}-name`}>Plan name<input id={`${formId}-name`} value={draft.label} maxLength={200} required onChange={(event) => change("label", event.target.value)} /></label>
            <div className="saved-plan-select-field"><label htmlFor={`${formId}-tier`}>Availability tier</label>
              <select id={`${formId}-tier`} value={draft.tier} onChange={(event) => change("tier", event.target.value)}>
                <option value="">Not specified</option>{designRequirementsContract.availability_tiers.map((tier) => <option key={tier} value={tier}>{tier[0].toUpperCase() + tier.slice(1)}</option>)}</select></div>
            <label htmlFor={`${formId}-apps`}>Critical applications<input id={`${formId}-apps`} value={draft.apps} placeholder="voice, video, ERP" onChange={(event) => change("apps", event.target.value)} /></label>
            <div className="saved-plan-field"><label htmlFor={`${formId}-convergence`}>Convergence budget (ms)<input id={`${formId}-convergence`} inputMode="numeric" value={draft.convergence} placeholder="0 is retained" aria-describedby={`${formId}-convergence-limit`} onChange={(event) => change("convergence", event.target.value)} /></label><p className="dim saved-plan-help" id={`${formId}-convergence-limit`}>Whole milliseconds, from 0 to {SAVED_PLAN_MAX_CONVERGENCE_MS}.</p></div>
            <label htmlFor={`${formId}-growth`}>Growth horizon<input id={`${formId}-growth`} value={draft.growth} onChange={(event) => change("growth", event.target.value)} /></label>
            <div className="saved-plan-select-field"><label htmlFor={`${formId}-fabric`}>Fabric operating model</label>
              <select id={`${formId}-fabric`} value={draft.fabric} onChange={(event) => change("fabric", event.target.value)}>
                <option value="">Not specified</option>{designRequirementsContract.fabric_models.map((model) => <option key={model} value={model}>{model === "aci" ? "Cisco ACI" : model === "nxos-evpn" ? "NX-OS VXLAN-EVPN" : model}</option>)}</select></div>
            <label htmlFor={`${formId}-constraints`}>Constraints<input id={`${formId}-constraints`} value={draft.constraints} placeholder="budget, installed base" onChange={(event) => change("constraints", event.target.value)} /></label>
            <label htmlFor={`${formId}-classification`}>Data classification<input id={`${formId}-classification`} value={draft.classification} placeholder="restricted, internal" onChange={(event) => change("classification", event.target.value)} /></label>
            <label htmlFor={`${formId}-address`}>Target IPv4 address space<input id={`${formId}-address`} value={draft.address} placeholder="10.0.0.0/16" onChange={(event) => change("address", event.target.value)} /></label>
            <details className="saved-plan-advanced"><summary>Advanced: VLAN zones</summary>
              <label htmlFor={`${formId}-zones`}>VLAN zones — one assignment per line<textarea id={`${formId}-zones`} rows={4} value={draft.zones} placeholder={"10=Users\n20=Servers"} onChange={(event) => change("zones", event.target.value)} /></label>
              <p className="dim">Use VLAN=Zone, such as 10=Users. Repeated VLANs are rejected; a zone is never inferred from a VLAN number.</p>
            </details>
          </fieldset>
          {formError && <p role="alert" className="saved-plan-alert">{formError}</p>}
          {dirty && <p role="status" className="saved-plan-unsaved">Unsaved changes. Save a new revision or discard these changes before downloading.</p>}
          <div className="saved-plan-actions"><button className="btn primary" type="submit" disabled={formDisabled}>{busy === "save" ? "Saving…" : "Save new revision"}</button>
            <button className="btn" type="button" disabled={!dirty || formDisabled} onClick={() => { setDraft({ ...savedDraft }); setFormError(""); setMessage("Unsaved changes discarded."); }}>Discard changes</button></div>
        </form>
      </section>

      <section className="panel" aria-labelledby={`${formId}-history`}>
        <h2 id={`${formId}-history`}>Saved revisions</h2>
        {!loading && state && state.revisions.length === 0 && <p>No saved plan revisions yet.</p>}
        {loading && <p className="dim">Reading revision history…</p>}
        {state && <ol className="saved-plan-roster">{state.revisions.map((row) => <li key={row.revision}>
          <strong>{row.label}</strong><p className="dim">Revision {row.revision} · <time dateTime={row.created_at}>{row.created_at}</time></p>
          <p className="saved-plan-hash">{row.sha256}</p>
          <button className="btn" type="button" disabled={blocked || dirty || row.revision === selected?.revision}
            onClick={() => { void select(row.revision, row.sha256); }}>{row.revision === selected?.revision ? `Selected revision ${row.revision}` : `Select revision ${row.revision}`}</button>
        </li>)}</ol>}
      </section>
    </div>

    <section className="panel" aria-labelledby={`${formId}-selected`}>
      <h2 id={`${formId}-selected`}>Selected plan and documents</h2>
      <p className="saved-plan-draft">UNAPPROVED DRAFT — saving or selecting is not approval.</p>
      {selected ? <><p><strong>{selected.label}</strong> · Revision {selected.revision} · Selection {selected.selection_id}</p>
        <p className="saved-plan-hash">Selected plan SHA-256: {selected.sha256}</p>
        <p className="dim">Downloads use this saved revision. Original assessment protocol evidence retains its own receipt; no device change or acceptance result is created.</p></>
        : <p className="dim">{loading ? "Opening the selected revision…" : state
          ? "Save or select a revision to view its design and download its documents."
          : "Reload saved plans to confirm assessment identity before saving or selecting."}</p>}
      {metaLoading && <p role="status">Loading document availability…</p>}
      {metaError && <p role="alert" className="saved-plan-alert">Document catalogue could not be read: {metaError}. Reload before concluding that documents are unavailable.</p>}
      {!metaLoading && !metaError && meta && items.length === 0 && <p>No document entries were provided by this server.</p>}
      <div className="saved-plan-primary-actions">{documentButton(items.find((item) => item.key === "mop"), "Download MOP")}{documentButton(items.find((item) => item.key === "nrfu"), "Download NRFU")}</div>
      <details><summary>Other document drafts</summary><div className="saved-plan-other-documents">{items.filter((item) => item.key !== "mop" && item.key !== "nrfu").map((item) => documentButton(item))}</div></details>
    </section>

    {selected && previewAvailable && blueprint && nrfu && <section className="panel" aria-labelledby={`${formId}-preview`}>
      <h2 id={`${formId}-preview`}>Saved design and NRFU plan</h2>
      <p className="dim">This is the persisted projection for Revision {selected.revision}, not a fresh preview of unsaved form edits.</p>
      <h3>Design summary</h3><p>{blueprint.summary.headline}</p>
      <dl className="saved-plan-summary"><div><dt>Recommended decisions</dt><dd>{blueprint.summary.n_recommended}</dd></div><div><dt>Decisions needing requirements</dt><dd>{blueprint.summary.n_needs_requirement}</dd></div><div><dt>Critical recommendations</dt><dd>{blueprint.summary.n_critical}</dd></div></dl>
      <details><summary>Saved design decisions</summary><ul className="saved-plan-decision-list">{blueprint.decisions.map((decision) => <li key={decision.id}><h4>{decision.title}</h4><p>{decision.priority} · {decision.status}</p><p>{decision.recommended_action || decision.driver}</p></li>)}</ul></details>
      <h3>NRFU checklist</h3><p className="dim">Planned verification checks, not passed test results. {nrfu.note}</p>
      {nrfu.items.length === 0 ? <p>No NRFU item rows were supplied for this revision.</p> : <ol className="saved-plan-checklist">{nrfu.items.map((item) => <li key={item.decision_id}><h4>{item.title}</h4><p>{item.phase}</p><p>{item.description}</p><p><strong>Pass criteria:</strong> {item.pass_criteria}</p></li>)}</ol>}
    </section>}
    {selected && !previewAvailable && <p role="alert" className="saved-plan-alert">The saved design or NRFU projection could not be read. Downloads are disabled; reload saved plans.</p>}
  </main>;
}

export default function SavedPlanPage() {
  const { id } = useParams();
  const activeSource = useRef(id);
  // The synchronous source key also gates old side effects before passive unmount cleanup runs.
  activeSource.current = id;
  const snapshotId = id && /^[1-9][0-9]*$/.test(id) ? Number(id) : NaN;
  if (!Number.isSafeInteger(snapshotId) || snapshotId < 1) {
    return <main className="saved-plan-page"><h1>Saved plans and downloads</h1><p role="alert">The snapshot address is not supported.</p><Link to="/">Return to AssessHub</Link></main>;
  }
  // A route change replaces every local form/selection, and unmount aborts/guards pending responses.
  return <SavedPlanWorkspace key={id} snapshotId={snapshotId} activeSource={activeSource} />;
}
