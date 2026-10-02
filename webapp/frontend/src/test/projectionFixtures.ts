// Hand-authored synthetic HTTP documents for renderer tests. No stored snapshot or customer data.
export const published = <T,>(value: T) => ({ state: "published", value, subject: "/synthetic", refs: [], basis: "synthetic.owner" });
export const withheld = () => ({ state: "not_collected", value: null, reason: "Synthetic input was not collected", subject: "/missing", refs: [], basis: "synthetic.owner" });
const empty = (pointer: string) => ({ pointer, source_list: { state: "collected_but_empty", reason: "Synthetic source has no rows", subject: pointer, refs: [], basis: "synthetic.owner" }, page: { offset: 0, limit: 25, returned: 0, total: 0, has_more: false, items: [] } });
const fields = (keys: string) => Object.fromEntries(keys.split(" ").map((key) => [key, withheld()]));
export function overviewFixture(sid = 1, statement = "Synthetic fleet needs review") {
  const keys = "n_devices n_collected n_endpoints n_vlans n_domains avg_health n_critical n_poor worst_band n_past_ldos n_near n_past_eos n_active n_unknown n_design_decisions";
  return { ...common(sid, "overview"), payload: {
    facts: Object.fromEntries(keys.split(" ").map((key) => [key, { path: `/facts/${key}`, concept: key, fact: key === "worst_band" ? published("Poor") : published(0) }])),
    posture_statement: published(statement), fleet_health: { state: "not_assessed", reason: "Synthetic health not assessed", not_assessed_reason: "No scoring inputs", n_scored: withheld(), n_rows: published(0) },
    lifecycle: { bands: [], of: published(0), asof: withheld() }, axes: empty("/axes"), top_gating: empty("/top_gating"), absent_axes: [],
  } };
}
export function common(sid: number, view: string) {
  return { schema: "ui_projection_transport/1", projection_schema: "ui_projection/1", view,
    identity: { snapshot_id: sid, sha256: `sha256:${"a".repeat(64)}`, bytes: 42, digest_form: "assesshub-store-blob" },
    limitations: [], engine: { script_version: published("synthetic"), snapshot_schema: published("3.23.0"), generated_at: withheld(), collected_at: withheld(), snapshot_schema_supported: true, code_schema_version: "3.23.0" } };
}
export function trustFixture(sid = 1) {
  return { ...common(sid, "trust"), payload: {
    coverage_matrix: fields("n_devices n_axes n_rows n_covered n_abstained by_state note"),
    unknown_evidence: { ...fields("state n_events n_unresolved source_coverage_complete claim_scope note"), sources: empty("/unknown_evidence/sources") },
    ssot: { ...fields("verified n_facts n_checked n_violations engine_stamp"), stamp_matches_live: null, violations: empty("/ssot/violations") },
    census: { basis: "synthetic.owner", embedded: { state: "not_collected", matches_live: null }, summary: fields("n_published n_collected_but_empty n_not_collected n_analysis_unavailable n_sections"), rows: empty("/census/rows") },
    failures: { record: empty("/failures/record"), direct_sections: [], unattributed: false },
  } };
}
export function inventoryFixture(sid = 1) {
  const row = { host: "edge/a~b", pointer: "/devices/edge~1a~0b", ...fields("model platform sw_version serial_number role health_score health_band lifecycle_band risk_band move_group collection_status") };
  return { ...common(sid, "inventory"), payload: {
    devices: { total: published(1), rows: { ...empty("/devices/rows"), source_list: { state: "published", subject: "/devices", refs: [], basis: "synthetic.owner" }, page: { offset: 0, limit: 25, returned: 1, total: 1, has_more: false, items: [row] } } },
    vlans: { total: published(0), rows: empty("/vlans/rows") }, endpoints: { total: published(0), rows: empty("/endpoints/rows"), shared_ip: empty("/endpoints/shared_ip"), dual_homed: empty("/endpoints/dual_homed") }, uncollected_peers: empty("/uncollected_peers"),
  } };
}
export function deviceFixture(sid = 1, host = "edge/a~b") {
  const cap = { limit: 64, reached: false, total: withheld() };
  return { ...common(sid, "device"), payload: { host, move_group: withheld(), identity: fields("model platform reported_hostname serial_number chassis_serial system_mac sw_version uptime"),
    physical: fields("active_ports total_ports num_modules num_power_supplies ps_status temperature_status fan_status power_capacity_w power_drawn_w power_remaining_w"), collection: fields("status missing data_quality"), lifecycle: fields("band status conf eos ldos source citation_status"),
    health: { ...fields("score band role"), deductions: empty("/health/deductions"), deduction_refs: empty("/health/deduction_refs"), deductions_cap: cap, deduction_refs_cap: cap },
    dossier: { risk_band: withheld(), exposures: empty("/dossier/exposures"), compound: empty("/dossier/compound") }, coverage: empty("/coverage"),
    interfaces: { rows: empty("/interfaces/rows") }, links: empty("/links"), routes: empty("/routes"), routing_neighbors: empty("/routing_neighbors"),
    security: { summary: withheld(), checks: empty("/security/checks") }, native_vlan_mismatches: empty("/native_vlan_mismatches"),
    remediation: { banner: withheld(), items: empty("/remediation/items") }, nrfu_cases: empty("/nrfu_cases"), findings: empty("/findings"), endpoints: empty("/endpoints"),
  } };
}
export function findingsFixture(sid = 1, offset = 0) {
  const row = { index: offset === 0 ? 7 : 93, pointer: `/punchlist/${offset === 0 ? 7 : 93}`, ...fields("priority rank severity category wave severity_basis evidence_confidence source_command evidence_basis"),
    title: published(offset === 0 ? "Synthetic finding" : "Next source finding"), detail: published("Synthetic issue detail"), remediation: published("Synthetic owner remediation"), devices: published(["edge/a~b"]),
    evidence_refs: { state: "collected_but_empty", reason: "No synthetic references", items: [], basis: "synthetic.owner", subject: "/punchlist", refs: [] } };
  const rows = { ...empty("/rows"), source_list: { state: "published", basis: "synthetic.owner", subject: "/punchlist", refs: [] }, page: { offset, limit: 1, returned: 1, total: 2, has_more: offset === 0, items: [row] } };
  return { ...common(sid, "findings"), payload: { total: published(2), headline_axis_index: null, rows } };
}
