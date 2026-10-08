// Hand-authored synthetic HTTP documents for renderer tests. No stored snapshot or customer data.
export const published = <T,>(value: T) => ({ state: "published", value, subject: "/synthetic", refs: [], basis: "synthetic.owner" });
export const withheld = () => ({ state: "not_collected", value: null, reason: "Synthetic input was not collected", subject: "/missing", refs: [], basis: "synthetic.owner" });
const empty = (pointer: string) => ({ pointer, source_list: { state: "collected_but_empty", reason: "Synthetic source has no rows", subject: pointer, refs: [], basis: "synthetic.owner" }, page: { offset: 0, limit: 25, returned: 0, total: 0, has_more: false, items: [] } });
// An empty selection whose owner never says "none" for a device: the absence stays a blind spot.
const blindPage = (pointer: string, reason: string) => ({ ...empty(pointer), source_list: { state: "not_collected", reason, subject: pointer, refs: [], basis: "synthetic.owner" } });
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
    posture_statement: published(statement), fleet_health: { state: "not_assessed", engine_state: "not_assessed", reason: "Synthetic health not assessed", not_assessed_reason: "no_health_rows", n_scored: withheld(), n_rows: published(0),
      bands: ["Excellent", "Good", "Fair", "Poor", "Critical", "Insufficient Data"].map((band) => ({ band, n: withheld(), hosts: withheld() })) },
    readiness: { groups: { ...ownerPage("/readiness/groups", []), source_list: { state: "not_collected",
      reason: "Synthetic readiness inputs were not collected", subject: "/migration_readiness", refs: [], basis: "synthetic.owner" } } },
    lifecycle: { bands: [], of: published(0), asof: withheld() }, axes: empty("/axes"), top_gating: empty("/top_gating"), absent_axes: [],
  } };
}
export function overviewRollupsFixture(sid = 1) {
  const doc = overviewFixture(sid);
  const caveat = "move_group_endpoints_not_distinct";
  const groups = [
    { index: 3, pointer: "/migration_readiness/3", group: { ...published("Synthetic group B"), subject: "/migration_readiness/3/group" },
      readiness: published("CAUTION"), switches: published(["edge/a~b", "synthetic-peer"]),
      endpoints: { ...published(6), subject: "/migration_readiness/3/endpoints", caveats: [caveat],
        refs: [{ pointer: "/move_groups/3/endpoints", role: "witness" }] },
      n_fail: published(0), n_warn: published(1), checks: ownerList([
        { index: 4, pointer: "/migration_readiness/3/checks/4", check: published("Synthetic check B"), status: published("warn"), note: published("Synthetic owner check note"), phase: published("Rollback") },
        { index: 1, pointer: "/migration_readiness/3/checks/1", check: published("Synthetic check A"), status: published("pass"), note: published("Synthetic retained check order"), phase: published("Inventory") },
      ], "/migration_readiness/3/checks") },
    { index: 0, pointer: "/migration_readiness/0", group: published("Synthetic group A"), readiness: published("READY"),
      switches: published(["synthetic-ready"]), endpoints: { ...published(0), caveats: [caveat] }, n_fail: published(0), n_warn: published(0),
      checks: ownerList([{ index: 0, pointer: "/migration_readiness/0/checks/0", check: published("Synthetic ready check"),
        status: published("pass"), note: published("Synthetic assessed input"), phase: published("Inventory") }], "/migration_readiness/0/checks") },
  ];
  const bands = [
    { band: "Excellent", hosts: ["synthetic-healthy"] }, { band: "Good", hosts: [] },
    { band: "Fair", hosts: [] }, { band: "Poor", hosts: [] },
    { band: "Critical", hosts: ["edge/a~b"] }, { band: "Insufficient Data", hosts: ["synthetic-blind"] },
  ];
  const groupPage = ownerPage("/readiness/groups", groups);
  return { ...doc, limitations: [{ id: caveat, owner: "analyze.compute_move_groups", applies_to: ["/overview/readiness/groups"],
    text: "Endpoints is the sum of per-switch distinct learned MAC addresses on eligible access ports, not distinct endpoints across a move group; one MAC observed on multiple switches can be counted more than once." }], payload: { ...doc.payload,
    facts: { ...doc.payload.facts, n_critical: { ...doc.payload.facts.n_critical, fact: published(1) }, n_poor: { ...doc.payload.facts.n_poor, fact: published(0) },
      worst_band: { ...doc.payload.facts.worst_band, fact: published("Critical") } },
    fleet_health: { state: "published", engine_state: "measured", not_assessed_reason: null, n_scored: published(2), n_rows: published(3),
      bands: bands.map(({ band, hosts }) => ({ band, n: published(hosts.length),
        hosts: hosts.length ? published(hosts) : { state: "collected_but_empty", value: null,
          reason: "Synthetic source contains no hosts in this band", subject: "/health_scores", refs: [], basis: "synthetic.owner" } })) },
    readiness: { groups: { ...groupPage, source_list: { ...groupPage.source_list, caveats: [caveat] } } },
  } };
}
export function common(sid: number, view: string) {
  return { schema: "ui_projection_transport/1", projection_schema: "ui_projection/1", view,
    identity: { snapshot_id: sid, sha256: `sha256:${"a".repeat(64)}`, bytes: 42, digest_form: "assesshub-store-blob" },
    limitations: [], engine: { script_version: published("synthetic"), snapshot_schema: published("3.23.0"), generated_at: withheld(), collected_at: withheld(), snapshot_schema_supported: true, code_schema_version: "3.23.0" } };
}
// The engine's per-device analysis inputs (analyze.DOSSIER_AXIS_INPUTS order); each synthetic row is withheld.
const TRUST_INPUTS = "Health|Hardware EoL|Software risk|Control plane|Operational logs|Security posture|Config hygiene|Golden drift|QoS posture|Physical|Protocol";
const trustInputs = () => TRUST_INPUTS.split("|").map((input) => ({ input, sections: ["synthetic_section"], n: withheld(), of: withheld(),
  hosts: { state: "not_collected", reason: "Synthetic input custody was not collected", subject: null, refs: [], basis: "synthetic.owner", items: [] } }));
export function trustFixture(sid = 1) {
  return { ...common(sid, "trust"), payload: { inputs: trustInputs(),
    coverage_matrix: fields("n_devices n_axes n_rows n_covered n_abstained by_state note"),
    unknown_evidence: { ...fields("state n_events n_unresolved source_coverage_complete claim_scope note"), sources: empty("/unknown_evidence/sources") },
    ssot: { ...fields("verified n_facts n_checked n_violations engine_stamp"), stamp_matches_live: null, violations: empty("/ssot/violations") },
    census: { basis: "synthetic.owner", embedded: { state: "not_collected", matches_live: null }, summary: fields("n_published n_collected_but_empty n_not_collected n_analysis_unavailable n_sections"), rows: empty("/census/rows") },
    failures: { record: empty("/failures/record"), direct_sections: [], unattributed: false },
  } };
}
export function findingsRollupFixture(mode: "published" | "unverified" | "not_collected" | "configless" | "assessed_empty" = "published") {
  const evidence = { subject: "/punchlist", refs: [{ pointer: "/devices/edge~1a~0b", role: "witness" }], basis: "synthetic.owner:device_findings" };
  if (mode === "published") {
    const observed = { ...evidence, refs: [{ pointer: "/punchlist/7", role: "basis" }, ...evidence.refs] };
    return { worst: { ...published("High"), ...observed },
      by_severity: { ...published({ Critical: 0, High: 2, Medium: 0, Low: 1, Info: 0 }), ...observed } };
  }
  if (mode === "assessed_empty") return {
    worst: { ...evidence, state: "collected_but_empty", value: null, reason: "Synthetic captured assessment has no findings" },
    by_severity: { ...published({ Critical: 0, High: 0, Medium: 0, Low: 0, Info: 0 }), ...evidence },
  };
  const state = mode === "unverified" ? "unverified" : "not_collected";
  const reason = mode === "unverified" ? "Synthetic canonical finding custody is missing or malformed"
    : mode === "configless" ? "Synthetic running configuration was not collected"
      : "Synthetic canonical finding custody reports incomplete capture";
  return { worst: { ...evidence, state, value: null, reason }, by_severity: { ...evidence, state, value: null, reason } };
}
export function coverageRollupFixture(mode: "published" | "unverified" | "not_collected" | "all_covered" = "published") {
  const evidence = { subject: "/coverage_matrix/by_device/edge~1a~0b",
    refs: [{ pointer: "/coverage_matrix/rows/4", role: "basis" }], basis: "synthetic.owner:device_coverage" };
  if (mode === "published") return {
    // Only collection/capture/parse can abstain for an admitted device; architecture
    // abstentions are fleet-only. Three core abstentions coexist with six covered axes.
    worst: { ...published("unverified"), ...evidence }, n_abstained: { ...published(3), ...evidence },
  };
  const state = mode === "not_collected" ? "not_collected" : "unverified";
  const reason = mode === "all_covered" ? "Synthetic source silence does not prove complete device coverage"
    : mode === "not_collected" ? "Synthetic device coverage inputs were not collected"
      : "Synthetic device coverage custody is missing or ambiguous";
  return { worst: { ...evidence, state, value: null, reason }, n_abstained: { ...evidence, state, value: null, reason } };
}
export function coverageAxisFixture(axis = "capture", mode: "published" | "unverified" | "not_collected" | "covered" = "published", index = 4) {
  const pointer = `/coverage_matrix/by_device/edge~1a~0b/${axis.replaceAll("~", "~0").replaceAll("/", "~1")}`;
  const evidence = { subject: `/coverage_matrix/rows/${index}`, refs: [{ pointer: `/coverage_matrix/rows/${index}`, role: "basis" }],
    basis: "synthetic.owner:exact_device_axis" };
  if (mode === "published" || mode === "covered") return {
    axis, pointer, fact: { ...published({ axis, state: mode === "covered" ? "covered" : axis === "parse" ? "unparsed" : "unverified" }), ...evidence },
    dimension: { ...published(axis === "parse" ? "parse" : "capture"), ...evidence },
    verdict_source: { ...published(axis === "parse" ? "parse_yield" : "capture_integrity"), ...evidence },
    is_abstention: { ...published(mode !== "covered"), ...evidence },
  };
  const reason = mode === "unverified" ? "Synthetic exact device and axis join is ambiguous"
    : "Synthetic device coverage inputs were not collected";
  const fact = { ...evidence, state: mode, value: null, reason };
  return { axis, pointer, fact, dimension: fact, verdict_source: fact, is_abstention: fact };
}
export function inventoryFixture(sid = 1, findings = findingsRollupFixture("not_collected"), coverage = coverageRollupFixture("not_collected")) {
  const row = { host: "edge/a~b", pointer: "/devices/edge~1a~0b", findings, coverage, ...fields("model platform sw_version serial_number role health_score health_band lifecycle_band risk_band move_group collection_status") };
  return { ...common(sid, "inventory"), payload: {
    devices: { total: published(1), rows: { ...empty("/devices/rows"), source_list: { state: "published", subject: "/devices", refs: [], basis: "synthetic.owner" }, page: { offset: 0, limit: 25, returned: 1, total: 1, has_more: false, items: [row] } } },
    vlans: { total: published(0), rows: empty("/vlans/rows") }, endpoints: { total: published(0), rows: empty("/endpoints/rows"), shared_ip: empty("/endpoints/shared_ip"), dual_homed: empty("/endpoints/dual_homed") }, uncollected_peers: empty("/uncollected_peers"),
  } };
}
export function deviceFixture(sid = 1, host = "edge/a~b", findings_rollup = findingsRollupFixture("not_collected"), coverage_rollup = coverageRollupFixture("not_collected")) {
  const cap = { limit: 64, reached: false, total: withheld() };
  // This synthetic published rollup represents three stored rows (High, High, Low).
  // Only the first reference is on this page; the row total is not a UI calculation.
  const findings = findings_rollup.worst.state === "published" && findings_rollup.by_severity.state === "published"
    ? { pointer: "/findings", source_list: { state: "published", subject: "/punchlist", refs: [], basis: "synthetic.owner:exact_host_refs" },
      page: { offset: 0, limit: 1, returned: 1, total: 3, has_more: true, items: [{ index: 7, pointer: "/punchlist/7" }] } }
    : empty("/findings");
  // Seven abstaining axes belong to the full nine-axis source, not the single visible row.
  const coverage = coverage_rollup.worst.state === "published" && coverage_rollup.n_abstained.state === "published"
    ? { pointer: "/coverage", source_list: { state: "published", subject: "/coverage_matrix/by_device/edge~1a~0b", refs: [], basis: "synthetic.owner:exact_device_axis" },
      page: { offset: 0, limit: 1, returned: 1, total: 9, has_more: true, items: [coverageAxisFixture()] } }
    : empty("/coverage");
  return { ...common(sid, "device"), payload: { host, findings_rollup, coverage_rollup, move_group: withheld(), identity: fields("model platform reported_hostname serial_number chassis_serial system_mac sw_version uptime"),
    physical: fields("active_ports total_ports num_modules num_power_supplies ps_status temperature_status fan_status power_capacity_w power_drawn_w power_remaining_w"), collection: fields("status missing data_quality"), lifecycle: fields("band status conf eos ldos source citation_status"),
    health: { ...fields("score band role"), deductions: empty("/health/deductions"), deduction_refs: empty("/health/deduction_refs"), deductions_cap: cap, deduction_refs_cap: cap },
    dossier: { risk_band: withheld(), exposures: empty("/dossier/exposures"), compound: empty("/dossier/compound") }, coverage,
    interfaces: { rows: empty("/interfaces/rows") }, links: empty("/links"), routes: empty("/routes"), routing_neighbors: empty("/routing_neighbors"),
    security: { summary: withheld(), checks: empty("/security/checks") }, native_vlan_mismatches: empty("/native_vlan_mismatches"),
    remediation: { banner: withheld(), items: empty("/remediation/items") }, nrfu_cases: empty("/nrfu_cases"), findings, endpoints: empty("/endpoints"),
    failure_impact: blindPage("/failure_impact", "Synthetic device has no simulation row; an absent row is not 'no impact'"),
    structural_links: blindPage("/structural_links", "Synthetic device is named by no scanned host-pair link; that is not proof of no link"),
  } };
}
export function findingsFixture(sid = 1, offset = 0) {
  const row = { index: offset === 0 ? 7 : 93, pointer: `/punchlist/${offset === 0 ? 7 : 93}`, ...fields("priority rank severity category wave severity_basis evidence_confidence source_command evidence_basis"),
    title: published(offset === 0 ? "Synthetic finding" : "Next source finding"), detail: published("Synthetic issue detail"), remediation: published("Synthetic owner remediation"), devices: published(["edge/a~b"]),
    evidence_refs: { state: "collected_but_empty", reason: "No synthetic references", items: [], basis: "synthetic.owner", subject: "/punchlist", refs: [] } };
  const rows = { ...empty("/rows"), source_list: { state: "published", basis: "synthetic.owner", subject: "/punchlist", refs: [] }, page: { offset, limit: 1, returned: 1, total: 2, has_more: offset === 0, items: [row] } };
  return { ...common(sid, "findings"), payload: { total: published(2), headline_axis_index: null, rows } };
}
