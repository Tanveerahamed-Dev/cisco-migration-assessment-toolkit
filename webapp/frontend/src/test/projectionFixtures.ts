// Hand-authored synthetic HTTP documents for renderer tests. No stored snapshot or customer data.
export const published = <T,>(value: T) => ({ state: "published", value, subject: "/synthetic", refs: [], basis: "synthetic.owner" });
export const withheld = () => ({ state: "not_collected", value: null, reason: "Synthetic input was not collected", subject: "/missing", refs: [], basis: "synthetic.owner" });
const empty = (pointer: string) => ({ pointer, source_list: { state: "collected_but_empty", reason: "Synthetic source has no rows", subject: pointer, refs: [], basis: "synthetic.owner" }, page: { offset: 0, limit: 25, returned: 0, total: 0, has_more: false, items: [] } });
const fields = (keys: string) => Object.fromEntries(keys.split(" ").map((key) => [key, withheld()]));
const ownerList = <T,>(items: T[], subject: string) => items.length
  ? { state: "published", subject, refs: [], basis: "synthetic.owner", items }
  : { state: "collected_but_empty", reason: "Synthetic source has no rows", subject, refs: [], basis: "synthetic.owner", items };
const ownerPage = <T,>(pointer: string, items: T[]) => {
  const { items: _items, ...source_list } = ownerList(items, pointer);
  return { pointer, source_list, page: { offset: 0, limit: 25, returned: items.length, total: items.length, has_more: false, items } };
};
export function topologyLegendFixture() {
  const tokens = ["observed", "uncollected", "unverified", "not_observed", "analysis_unavailable", "link_up", "link_down", "link_unknown",
    "structural_link", "structural_bridge", "impact_high", "impact_medium", "impact_low", "impact_info", "path_reached", "path_partial_drop",
    "path_observed_discard", "path_no_route_observed", "path_lower_bound", "path_withheld"];
  return { schema: "ui_projection_topology_style/1", fallback: { token: "unverified", glyph: "unknown", label: "Synthetic fallback presentation" },
    entries: tokens.map((token) => ({ token, tone: token === "uncollected" ? "muted" : token === "unverified" ? "warning" : "info",
      stroke: token === "uncollected" ? "dotted" : "solid", weight: "normal", meaning: `Synthetic engine meaning: ${token}` })) };
}
export function topologyNodeFixture(index = 0, host = "synthetic-edge-a") {
  return { index, pointer: `/cable_map/nodes/${index}`, host: published(host), kind: published("router"), role: published("core"),
    collected: published(true), style: published({ token: "observed", glyph: "device", label: "Synthetic engine node presentation" }) };
}
export function topologyFixture(sid = 1) {
  const a = topologyNodeFixture(), b = { ...topologyNodeFixture(1, "synthetic-peer-b"), collected: published(false),
    style: published({ token: "uncollected", glyph: "unknown", label: "Synthetic uncollected peer" }) };
  const aRef = { index: a.index, pointer: a.pointer }, bRef = { index: b.index, pointer: b.pointer };
  const joins = { a_nodes: ownerList([aRef], "/cable_map/nodes"), b_nodes: ownerList([bRef], "/cable_map/nodes") };
  return { ...common(sid, "topology"), payload: {
    summary: { nodes: published(2), cables: published(1) }, legend: topologyLegendFixture(),
    nodes: ownerPage("/nodes", [a, b]),
    cables: ownerPage("/cables", [{ index: 0, pointer: "/cable_map/cables/0", ends: published({ a: "synthetic-edge-a", a_port: "Gi1", b: "synthetic-peer-b", b_port: "Gi2", is_pc: false }),
      members: ownerList([], "/cable_map/cables/0/members"), speed: published("1G"), confirmation: published("observed"), op_status: published("up"), ...joins,
      style: published({ token: "link_unknown", glyph: "none", label: "Synthetic supplied cable style" }) }]),
    structural_links: ownerPage("/structural_links", [{ index: 0, pointer: "/link_centrality/0", ends: published({ a_host: "synthetic-edge-a", a_port: "Gi1", b_host: "synthetic-peer-b", b_port: "Gi2" }),
      betweenness: published(.25), is_bridge: published(true), pairs_cut: published(1), rank: published(1), ...joins,
      host_pair_cable_refs: ownerList([{ index: 0, pointer: "/cable_map/cables/0" }], "/cable_map/cables"),
      style: published({ token: "structural_bridge", glyph: "none", label: "Synthetic host-pair bridge" }) }]),
    failure_impact: ownerPage("/failure_impact", [{ index: 0, pointer: "/failure_impact/0", host: published("synthetic-edge-a"), node_refs: ownerList([aRef], "/cable_map/nodes"),
      severity: published("Info"), ...Object.fromEntries("vlans_impacted stranded hard backup fhrp off_scan_gw_vlans".split(" ").map((key) => [key, published(0)])),
      detail: published("Synthetic scanned-model detail; no traffic assertion"), style: published({ token: "impact_info", glyph: "none", label: "Synthetic impact presentation" }) }]),
    source_addresses: ownerPage("/source_addresses", [{ index: 0, pointer: "/interfaces/0/svi_ip", host: published("synthetic-edge-a"), interface: published("Vlan10"),
      address: published("192.0.2.10"), family: published(4), origin: published("interface_svi"), node_refs: ownerList([aRef], "/cable_map/nodes") }]),
  } };
}
export function pathFixture(sid = 1, src_ip = "192.0.2.10", dst_ip = "198.51.100.10") {
  return { ...common(sid, "path"), payload: {
    query: { src_ip, dst_ip, max_hops: 32, required_mtu: null, disclose: true }, legend: topologyLegendFixture(),
    style: published({ token: "path_partial_drop", glyph: "none", label: "Synthetic owner: reached with a dropping leg" }),
    result: published({ src: src_ip, dst: dst_ip, status: "synthetic_partial_drop", computed: true, reached: true, drop_evidence: "observed_discard",
      hops: [{ host: "different-raw-host-label", match: "198.51.100.0/24", next_hop: "192.0.2.1", out_intf: "Gi1", source: "static" }],
      ecmp_dropping_legs: [{ host: "synthetic-edge-a", match: "198.51.100.0/24", next_hop: "Null0", out_intf: "Null0", leg_status: "drop", drop_evidence: "observed_discard", resolved_hops: [] }],
      ambiguous_candidate_sets: [{ kind: "synthetic", candidate_hosts: ["synthetic-edge-a", "synthetic-peer-b"] }], mtu_min: null, mtu_bottleneck_hop: null,
      mtu_unobserved_hops: [{ host: "synthetic-edge-a", out_intf: "Gi1", reason: "egress_interface_not_observed" }], jumbo_blackhole: [], mtu_verdict: "not_assessed" }),
    hop_evidence: ownerList([{ hop_index: 0, route_rows: ownerList([{ index: 0, pointer: "/l3_forwarding/0" }], "/l3_forwarding"),
      interfaces: ownerList([{ pointer: "/interfaces/0", role: "basis" }], "/interfaces"), node_rows: ownerList([{ index: 0, pointer: "/cable_map/nodes/0" }], "/cable_map/nodes") }], "/l3_forwarding"),
  } };
}
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
