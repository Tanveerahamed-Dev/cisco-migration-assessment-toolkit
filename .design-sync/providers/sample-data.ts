/* Synthetic sample fleet for AssessHub previews and Claude Design mockups.
 *
 * ENTIRELY FICTIONAL: the "Meridian" campus (MBG-*) does not exist; addresses use the
 * TEST-NET documentation ranges. Never replace this with data derived from a real client
 * snapshot — this file ships inside the design-system bundle to claude.ai.
 *
 * Shapes mirror webapp/frontend/src/api.ts interfaces; the widgets render these verbatim.
 */

const GRAPH = {
  nodes: [
    { id: "MBG-CORE-01", band: "Good", score: 78, role: "core", degree: 3, keystone: true },
    { id: "MBG-CORE-02", band: "Fair", score: 61, role: "core", degree: 3, keystone: true },
    { id: "MBG-DS-01", band: "Good", score: 74, role: "distribution", degree: 5, keystone: false },
    { id: "MBG-DS-02", band: "Poor", score: 44, role: "distribution", degree: 7, keystone: false },
    { id: "STU-AS-01", band: "Excellent", score: 92, role: "access", degree: 2, keystone: false },
    { id: "STU-AS-02", band: "Good", score: 81, role: "access", degree: 2, keystone: false },
    { id: "STU-AS-03", band: "Critical", score: 22, role: "access", degree: 1, keystone: false },
    { id: "NOC-AS-01", band: "Fair", score: 58, role: "access", degree: 2, keystone: false },
    { id: "CAM-AS-01", band: "Insufficient Data", score: null, role: "access", degree: 1, keystone: false },
  ],
  edges: [
    { source: "MBG-CORE-01", target: "MBG-CORE-02", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-CORE-01", target: "MBG-DS-01", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-CORE-01", target: "MBG-DS-02", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-CORE-02", target: "MBG-DS-01", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-CORE-02", target: "MBG-DS-02", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-01", target: "STU-AS-01", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "STU-AS-01", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-01", target: "STU-AS-02", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "STU-AS-02", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "STU-AS-03", bridge_assessed: true, is_bridge: true, pairs_cut: 8 },
    { source: "MBG-DS-01", target: "NOC-AS-01", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "NOC-AS-01", bridge_assessed: true, is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "CAM-AS-01", bridge_assessed: true, is_bridge: true, pairs_cut: 8 },
  ],
  link_centrality_assessed: true,
  offscan_peers: [],
};

const CABLE_MAP = {
  nodes: [
    {
      host: "MBG-CORE-01", role: "core", kind: "switch", tier: 0, order: 0, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Po1", peer: "MBG-CORE-02", peer_port: "Po1", op_status: "up", is_pc: true },
        { name: "Te1/0/1", peer: "MBG-DS-01", peer_port: "Te1/1/1", op_status: "up", is_pc: false },
        { name: "Te1/0/2", peer: "MBG-DS-02", peer_port: "Te1/1/1", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "MBG-CORE-02", role: "core", kind: "switch", tier: 0, order: 1, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Po1", peer: "MBG-CORE-01", peer_port: "Po1", op_status: "up", is_pc: true },
        { name: "Te1/0/1", peer: "MBG-DS-01", peer_port: "Te1/1/2", op_status: "up", is_pc: false },
        { name: "Te1/0/2", peer: "MBG-DS-02", peer_port: "Te1/1/2", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "MBG-DS-01", role: "distribution", kind: "switch", tier: 1, order: 0, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Te1/1/1", peer: "MBG-CORE-01", peer_port: "Te1/0/1", op_status: "up", is_pc: false },
        { name: "Te1/1/2", peer: "MBG-CORE-02", peer_port: "Te1/0/1", op_status: "up", is_pc: false },
        { name: "Gi1/0/1", peer: "STU-AS-01", peer_port: "Gi1/0/49", op_status: "up", is_pc: false },
        { name: "Gi1/0/2", peer: "STU-AS-02", peer_port: "Gi1/0/49", op_status: "up", is_pc: false },
        { name: "Gi1/0/3", peer: "NOC-AS-01", peer_port: "Gi1/0/49", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "MBG-DS-02", role: "distribution", kind: "switch", tier: 1, order: 1, collected: true, op_status: "up", badges: ["links-down"],
      ports: [
        { name: "Te1/1/1", peer: "MBG-CORE-01", peer_port: "Te1/0/2", op_status: "up", is_pc: false },
        { name: "Te1/1/2", peer: "MBG-CORE-02", peer_port: "Te1/0/2", op_status: "up", is_pc: false },
        { name: "Gi1/0/1", peer: "STU-AS-01", peer_port: "Gi1/0/50", op_status: "up", is_pc: false },
        { name: "Gi1/0/2", peer: "STU-AS-02", peer_port: "Gi1/0/50", op_status: "down", is_pc: false },
        { name: "Gi1/0/3", peer: "STU-AS-03", peer_port: "Gi1/0/49", op_status: "down", is_pc: false },
        { name: "Gi1/0/4", peer: "NOC-AS-01", peer_port: "Gi1/0/50", op_status: "up", is_pc: false },
        { name: "Gi1/0/5", peer: "CAM-AS-01", peer_port: "Gi1/0/49", op_status: "unknown", is_pc: false },
      ],
    },
    {
      host: "STU-AS-01", role: "access", kind: "switch", tier: 2, order: 0, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Gi1/0/1", peer: "STU-AP-01", peer_port: "Gi0", op_status: "up", is_pc: false },
        { name: "Gi1/0/49", peer: "MBG-DS-01", peer_port: "Gi1/0/1", op_status: "up", is_pc: false },
        { name: "Gi1/0/50", peer: "MBG-DS-02", peer_port: "Gi1/0/1", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "STU-AS-02", role: "access", kind: "switch", tier: 2, order: 1, collected: true, op_status: "up", badges: ["links-down"],
      ports: [
        { name: "Gi1/0/49", peer: "MBG-DS-01", peer_port: "Gi1/0/2", op_status: "up", is_pc: false },
        { name: "Gi1/0/50", peer: "MBG-DS-02", peer_port: "Gi1/0/2", op_status: "down", is_pc: false },
      ],
    },
    {
      host: "STU-AS-03", role: "access", kind: "switch", tier: 2, order: 2, collected: true, op_status: "down", badges: ["links-down"],
      ports: [
        { name: "Gi1/0/49", peer: "MBG-DS-02", peer_port: "Gi1/0/3", op_status: "down", is_pc: false },
      ],
    },
    {
      host: "NOC-AS-01", role: "access", kind: "switch", tier: 2, order: 3, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Gi1/0/1", peer: "NOC-PHONE-01", peer_port: "Gi0", op_status: "up", is_pc: false },
        { name: "Gi1/0/49", peer: "MBG-DS-01", peer_port: "Gi1/0/3", op_status: "up", is_pc: false },
        { name: "Gi1/0/50", peer: "MBG-DS-02", peer_port: "Gi1/0/4", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "CAM-AS-01", role: "access", kind: "switch", tier: 2, order: 4, collected: false, op_status: "unknown", badges: ["uncollected"],
      ports: [
        { name: "Gi1/0/49", peer: "MBG-DS-02", peer_port: "Gi1/0/5", op_status: "unknown", is_pc: false },
      ],
    },
    {
      host: "STU-AP-01", role: "edge", kind: "ap", tier: 3, order: 0, collected: true, op_status: "up", badges: [],
      ports: [{ name: "Gi0", peer: "STU-AS-01", peer_port: "Gi1/0/1", op_status: "up", is_pc: false }],
    },
    {
      host: "NOC-PHONE-01", role: "edge", kind: "phone", tier: 3, order: 1, collected: true, op_status: "up", badges: [],
      ports: [{ name: "Gi0", peer: "NOC-AS-01", peer_port: "Gi1/0/1", op_status: "up", is_pc: false }],
    },
  ],
  cables: [
    { a: "MBG-CORE-01", a_port: "Po1", b: "MBG-CORE-02", b_port: "Po1", is_pc: true, members: [{ a_port: "Te1/1/1", b_port: "Te1/1/1" }, { a_port: "Te1/1/2", b_port: "Te1/1/2" }], op_status: "up", confirmation: "both-seen", speed: "10G" },
    { a: "MBG-CORE-01", a_port: "Te1/0/1", b: "MBG-DS-01", b_port: "Te1/1/1", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "10G" },
    { a: "MBG-CORE-01", a_port: "Te1/0/2", b: "MBG-DS-02", b_port: "Te1/1/1", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "10G" },
    { a: "MBG-CORE-02", a_port: "Te1/0/1", b: "MBG-DS-01", b_port: "Te1/1/2", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "10G" },
    { a: "MBG-CORE-02", a_port: "Te1/0/2", b: "MBG-DS-02", b_port: "Te1/1/2", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "10G" },
    { a: "MBG-DS-01", a_port: "Gi1/0/1", b: "STU-AS-01", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "1000" },
    { a: "MBG-DS-02", a_port: "Gi1/0/1", b: "STU-AS-01", b_port: "Gi1/0/50", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "1000" },
    { a: "MBG-DS-01", a_port: "Gi1/0/2", b: "STU-AS-02", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "1000" },
    { a: "MBG-DS-02", a_port: "Gi1/0/2", b: "STU-AS-02", b_port: "Gi1/0/50", is_pc: false, members: [], op_status: "down", confirmation: "both-seen", speed: "a-1000" },
    { a: "MBG-DS-02", a_port: "Gi1/0/3", b: "STU-AS-03", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "down", confirmation: "one-side", speed: "" },
    { a: "MBG-DS-01", a_port: "Gi1/0/3", b: "NOC-AS-01", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "1000" },
    { a: "MBG-DS-02", a_port: "Gi1/0/4", b: "NOC-AS-01", b_port: "Gi1/0/50", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "1000" },
    { a: "MBG-DS-02", a_port: "Gi1/0/5", b: "CAM-AS-01", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "unknown", confirmation: "cdp-only", speed: "" },
    { a: "STU-AS-01", a_port: "Gi1/0/1", b: "STU-AP-01", b_port: "Gi0", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "1000" },
    { a: "NOC-AS-01", a_port: "Gi1/0/1", b: "NOC-PHONE-01", b_port: "Gi0", is_pc: false, members: [], op_status: "up", confirmation: "both-seen", speed: "100" },
  ],
  tiers: [
    ["MBG-CORE-01", "MBG-CORE-02"],
    ["MBG-DS-01", "MBG-DS-02"],
    ["STU-AS-01", "STU-AS-02", "STU-AS-03", "NOC-AS-01", "CAM-AS-01"],
    ["STU-AP-01", "NOC-PHONE-01"],
  ],
  summary: { n_nodes: 11, n_cables: 15, n_tiers: 4, op: { up: 12, down: 2, unknown: 1 } },
};

const CAUSAL_FLOWS = {
  flows: [
    {
      key: "resilience-core-fhrp", family: "resilience", family_label: "Resilience", icon: "🛡",
      title: "First-hop collapses with the active core",
      severity: "Critical", sev_tok: "crit",
      trigger: "MBG-CORE-01 fails or reloads",
      mechanism: "18 user SVIs have a single gateway and no FHRP standby",
      impact: "Every studio and corporate VLAN loses its default gateway",
      mitigation: "Deploy HSRP active/standby across the core pair",
      hosts: ["MBG-CORE-01", "MBG-CORE-02"], blast: 1480, blast_unit: "endpoints", shape: "bowtie",
      threats: [
        "No FHRP on 18 user VLANs",
        "Single supervisor in MBG-CORE-01",
        "Gateway SVIs concentrated on one chassis",
      ],
      top_event: "Default gateway unreachable",
      consequence: "Campus-wide outage until manual failover",
      evidence: { summary: "SVI census: 18 gateways on MBG-CORE-01, 0 standby", count: 18, devices: ["MBG-CORE-01", "MBG-CORE-02"], fields: ["svi_census", "fhrp_absence"], precision: "DEVICE", grounded: true },
    },
    {
      key: "lifecycle-past-ldos-access", family: "lifecycle", family_label: "Lifecycle", icon: "⏳",
      title: "Past-LDoS access switches carry production video",
      severity: "Critical", sev_tok: "crit",
      trigger: "Hardware fault on a Past-LDoS chassis",
      mechanism: "The recorded LDoS has passed; no standard TAC escalation path or software fix remains (support entitlement is separate evidence).",
      impact: "Studio edge stays down for days, not hours",
      mitigation: "Replace the 2 Past-LDoS access switches before wave 3 and stage the replacement hardware.",
      hosts: ["STU-AS-03", "CAM-AS-01"], blast: 420, blast_unit: "endpoints", shape: "linear",
      evidence: { summary: "2 platforms are past recorded LDoS", count: 2, devices: ["STU-AS-03", "CAM-AS-01"], fields: ["lifecycle_risk.per_device[].band"], precision: "DEVICE", grounded: true },
    },
    {
      key: "security-aaa-access", family: "security", family_label: "Security", icon: "🔒",
      title: "Local-only auth on the access tier",
      severity: "High", sev_tok: "risk",
      trigger: "Credential compromise or staff turnover",
      mechanism: "4 switches authenticate against local accounts with no AAA audit trail",
      impact: "Untraceable configuration change on production gear",
      mitigation: "Point management-plane auth at the central AAA pair",
      hosts: ["STU-AS-01", "STU-AS-02", "STU-AS-03", "NOC-AS-01"], blast: 4, blast_unit: "devices", shape: "linear",
      evidence: { summary: "aaa new-model absent on 4 of 8 collected devices", count: 4, devices: ["STU-AS-01", "STU-AS-02", "STU-AS-03", "NOC-AS-01"], fields: ["aaa_config"], precision: "DEVICE", grounded: true },
    },
    {
      key: "l2-single-homed", family: "topology", family_label: "Topology", icon: "🕸",
      title: "Single-homed edge switches are one cable from dark",
      severity: "Medium", sev_tok: "watch",
      trigger: "Uplink transceiver or fibre fault",
      mechanism: "STU-AS-03 and CAM-AS-01 have exactly one path into the distribution tier",
      impact: "All endpoints behind the switch strand instantly",
      mitigation: "Add a second uplink to MBG-DS-01 for both switches",
      hosts: ["STU-AS-03", "CAM-AS-01"], blast: 420, blast_unit: "endpoints", shape: "linear",
      evidence: { summary: "2 bridge links in the CDP topology", count: 2, devices: ["STU-AS-03", "CAM-AS-01"], fields: ["topology_bridges"], precision: "DEVICE", grounded: true },
    },
    {
      key: "coverage-uncollected", family: "coverage", family_label: "Coverage", icon: "👁",
      title: "One camera-edge switch was never collected",
      severity: "Info", sev_tok: "accent",
      trigger: "Assessment ran without credentials for CAM-AS-01",
      mechanism: "Its config, health and licence state are [NOT OBSERVED]",
      impact: "Wave 3 risk is judged on incomplete evidence",
      mitigation: "Collect CAM-AS-01 before the wave-3 gate",
      hosts: ["CAM-AS-01"], blast: 1, blast_unit: "devices", shape: "linear",
      evidence: { summary: "1 of 9 inventoried devices uncollected", count: 1, devices: ["CAM-AS-01"], fields: ["collection_coverage"], precision: "FLEET", grounded: true },
    },
  ],
  families: [
    { key: "resilience", label: "Resilience", icon: "🛡", n: 1, crit: 1 },
    { key: "lifecycle", label: "Lifecycle", icon: "⏳", n: 1, crit: 1 },
    { key: "security", label: "Security", icon: "🔒", n: 1, crit: 0 },
    { key: "topology", label: "Topology", icon: "🕸", n: 1, crit: 0 },
    { key: "coverage", label: "Coverage", icon: "👁", n: 1, crit: 0 },
  ],
  summary: { n_flows: 5, n_families: 5, n_critical: 2, by_severity: { Critical: 2, High: 1, Medium: 1, Info: 1 } },
};

const ARCH_REVIEW = {
  domains: [
    { key: "Resiliency & Availability", verdict: "critical", score_pct: 44, checks: ["AR-01", "AR-02", "AR-03"] },
    { key: "Security", verdict: "deviation", score_pct: 63, checks: ["AR-04", "AR-05"] },
    { key: "Management & Operations", verdict: "advisory", score_pct: 82, checks: ["AR-06", "AR-07"] },
    { key: "Wireless", verdict: "not-assessable", score_pct: null, checks: ["AR-08"] },
  ],
  checks: [
    {
      id: "AR-01", domain: "Resiliency & Availability", title: "First-hop redundancy on user VLANs", verdict: "critical",
      observed: "18 user SVIs terminate on MBG-CORE-01 with no HSRP/VRRP standby group configured.",
      implication: "A single core failure removes the default gateway for every user VLAN at once.",
      recommendation: "Configure HSRP active/standby across MBG-CORE-01/02 for all user SVIs.",
      reference: "Campus LAN CVD — first-hop redundancy", evidence: ["MBG-CORE-01", "MBG-CORE-02"],
    },
    {
      id: "AR-02", domain: "Resiliency & Availability", title: "Core interconnect redundancy", verdict: "conforms",
      observed: "Po1 between the cores carries two 10G members on separate line cards.",
      implication: "", recommendation: "", reference: "Campus LAN CVD — core links", evidence: ["MBG-CORE-01", "MBG-CORE-02"],
    },
    {
      id: "AR-03", domain: "Resiliency & Availability", title: "Access-tier dual-homing", verdict: "deviation",
      observed: "2 of 5 access switches (STU-AS-03, CAM-AS-01) are single-homed into MBG-DS-02.",
      implication: "One uplink fault strands every endpoint behind the switch.",
      recommendation: "Add a second uplink from each to MBG-DS-01.",
      reference: "Campus LAN CVD — access dual-homing", evidence: ["STU-AS-03", "CAM-AS-01"],
    },
    {
      id: "AR-04", domain: "Security", title: "Management-plane AAA", verdict: "deviation",
      observed: "4 access switches authenticate with local accounts only; no TACACS/RADIUS.",
      implication: "No per-admin accountability or central credential revocation.",
      recommendation: "Enable aaa new-model against the central AAA pair.",
      reference: "CIS Cisco IOS benchmark §AAA", evidence: ["STU-AS-01", "STU-AS-02", "STU-AS-03", "NOC-AS-01"],
    },
    {
      id: "AR-05", domain: "Security", title: "SSHv2-only management plane", verdict: "conforms",
      observed: "All collected devices enforce ip ssh version 2; telnet lines are closed.",
      implication: "", recommendation: "", reference: "CIS Cisco IOS benchmark §mgmt", evidence: ["MBG-CORE-01", "MBG-CORE-02", "MBG-DS-01", "MBG-DS-02"],
    },
    {
      id: "AR-06", domain: "Management & Operations", title: "Configuration backup currency", verdict: "advisory",
      observed: "Startup vs running config diverge on 2 devices; last archive is 90+ days old.",
      implication: "A reload loses uncommitted change; rollback baselines are stale.",
      recommendation: "Schedule daily config archive and reconcile the divergent pair.",
      reference: "Ops handbook — configuration management", evidence: ["MBG-DS-02", "NOC-AS-01"],
    },
    {
      id: "AR-07", domain: "Management & Operations", title: "Syslog and NTP alignment", verdict: "conforms",
      observed: "All collected devices log to 192.0.2.50 and chime the same NTP pair.",
      implication: "", recommendation: "", reference: "Ops handbook — telemetry", evidence: ["MBG-CORE-01", "MBG-DS-01"],
    },
    {
      id: "AR-08", domain: "Wireless", title: "Wireless controller redundancy", verdict: "not-assessable",
      observed: "No WLC evidence in this collection.",
      implication: "", recommendation: "Collect the WLC pair before judging wireless resiliency.",
      reference: "Wireless CVD", evidence: [],
    },
  ],
  top_actions: [
    { rank: 1, id: "AR-01", domain: "Resiliency & Availability", verdict: "critical", action: "Deploy HSRP across the core pair for all 18 user SVIs", evidence: ["MBG-CORE-01", "MBG-CORE-02"] },
    { rank: 2, id: "AR-03", domain: "Resiliency & Availability", verdict: "deviation", action: "Dual-home STU-AS-03 and CAM-AS-01 into MBG-DS-01", evidence: ["STU-AS-03", "CAM-AS-01"] },
    { rank: 3, id: "AR-04", domain: "Security", verdict: "deviation", action: "Move access-tier auth onto the central AAA pair", evidence: ["STU-AS-01", "NOC-AS-01"] },
    { rank: 4, id: "AR-06", domain: "Management & Operations", verdict: "advisory", action: "Re-baseline config archives and reconcile divergent pairs", evidence: ["MBG-DS-02", "NOC-AS-01"] },
  ],
  summary: {
    n_checks: 8, n_assessable: 7, n_conforms: 3, n_advisory: 1, n_deviation: 2, n_critical: 1, n_not_assessable: 1,
    score_pct: 68, grade: "C", grade_label: "Conditionally ready — material deviations to close",
    statement: "The fabric forwards today, but first-hop redundancy is absent and the studio edge is one fault from dark. Close AR-01 and AR-03 before wave scheduling.",
  },
};

const CUTOVER = {
  summary: {
    verdict: "CONDITIONAL GO", n_waves: 3, n_devices: 5, n_endpoints: 1480,
    n_make_before_break: 3, n_hard_cutover: 2, hard_cutover_endpoints: 420,
    est_window_minutes: 205, est_window_label: "3h 25m",
    gates: { "GO": 1, "CONDITIONAL GO": 1, "NO-GO": 1 },
    statement: "Pilot-first: the NOC wave proves the method with zero-outage moves, the studio wave runs once its uplink blocker clears, and the camera edge stays NO-GO until CAM-AS-01 is collected and STU-AS-03 is reachable.",
    methodology: [
      "Waves are move-groups from the endpoint/VLAN census — devices that strand endpoints together move together.",
      "Every wave gates on its pre-checks; a fail blocks the wave, never the campaign.",
      "Window estimates are first-order planning anchors from port counts, not commitments.",
    ],
  },
  waves: [
    {
      group: "NOC pilot", order: 1, readiness: "READY", gate: "GO", strategy: "make-before-break",
      n_switches: 1, switches: ["NOC-AS-01"], make_before_break: ["NOC-AS-01"], hard_cutover: [],
      endpoints: 120, hard_cutover_endpoints: 0, est_window_minutes: 45, est_window_label: "45m",
      sequence_note: "Safest wave first — dual-homed, no findings block it.",
      gateways: ["192.0.2.1"], spanning_vlans: [[30, "NOC-Mgmt", 2]],
      blast_radius: null, keystones: [], n_fail: 0, n_warn: 0, blockers: [], critical_crosslayer: [],
      remediation: [
        { device: "NOC-AS-01", title: "Archive running config", category: "ops", severity: "Low", why: "Rollback baseline before the move." },
      ],
      validation: [
        { category: "reachability", severity: "High", check: "Gateway reachable from NOC VLAN", command: "ping 192.0.2.1 source vlan 30", expect: "5/5 replies" },
        { category: "topology", severity: "Medium", check: "Both uplinks forwarding", command: "show etherchannel summary", expect: "Po flags SU" },
        { category: "endpoints", severity: "Medium", check: "Endpoint count matches baseline", command: "show mac address-table count", expect: "±2 of 120" },
      ],
      run_of_show: [
        { phase: "pre", action: "Freeze change window; capture pre-snapshot" },
        { phase: "pre", action: "Verify both uplinks up on NOC-AS-01" },
        { phase: "cut", action: "Move uplink A to the new distribution pair" },
        { phase: "cut", action: "Confirm forwarding, then move uplink B" },
        { phase: "post", action: "Run validation set; capture post-snapshot and diff" },
      ],
    },
    {
      group: "Studio access", order: 2, readiness: "CAUTION", gate: "CONDITIONAL GO", strategy: "make-before-break",
      n_switches: 2, switches: ["STU-AS-01", "STU-AS-02"], make_before_break: ["STU-AS-01", "STU-AS-02"], hard_cutover: [],
      endpoints: 940, hard_cutover_endpoints: 0, est_window_minutes: 40, est_window_label: "40m",
      sequence_note: "Runs only after the pilot validates and the STU-AS-02 uplink blocker clears.",
      gateways: ["192.0.2.1"], spanning_vlans: [[110, "Studio-Video", 4], [120, "Studio-Audio", 3]],
      blast_radius: { host: "STU-AS-02", severity: "High", stranded: 430, vlans_impacted: 3, detail: "With Gi1/0/50 down, STU-AS-02 is effectively single-homed — a fault on the remaining uplink strands 430 endpoints across 3 VLANs." },
      keystones: ["MBG-DS-01"], n_fail: 1, n_warn: 1,
      blockers: [
        { check: "Second uplink restored on STU-AS-02", status: "fail", note: "Gi1/0/50 to MBG-DS-02 is down — replace SFP before the wave.", phase: "pre" },
        { check: "Studio change freeze lifted", status: "warn", note: "Production schedule clears after 22:00.", phase: "pre" },
      ],
      critical_crosslayer: [
        { id: "XL-02", title: "Video VLAN spans both distribution switches", layers: "L1+L2", recommendation: "Confirm spanning-tree root stays on MBG-DS-01 during the move." },
      ],
      remediation: [
        { device: "STU-AS-02", title: "Replace failed uplink optic", category: "hardware", severity: "High", why: "Restores dual-homing before the move." },
        { device: "STU-AS-01", title: "Enable AAA against central pair", category: "security", severity: "Medium", why: "Wave window is the approved change slot." },
      ],
      validation: [
        { category: "reachability", severity: "Critical", check: "Studio gateway reachable", command: "ping 192.0.2.1 source vlan 110", expect: "5/5 replies" },
        { category: "topology", severity: "High", check: "Dual uplinks forwarding on both switches", command: "show interfaces status | i Gi1/0/49|Gi1/0/50", expect: "connected ×2" },
        { category: "l2", severity: "High", check: "STP root unchanged for VLAN 110/120", command: "show spanning-tree vlan 110", expect: "root = MBG-DS-01" },
        { category: "endpoints", severity: "Medium", check: "Endpoint census within tolerance", command: "show mac address-table count", expect: "±5 of 940" },
      ],
      run_of_show: [
        { phase: "pre", action: "Clear blocker: confirm Gi1/0/50 replaced and up" },
        { phase: "pre", action: "Capture pre-snapshot; verify STP root placement" },
        { phase: "cut", action: "Move STU-AS-01 uplinks one at a time (make-before-break)" },
        { phase: "cut", action: "Move STU-AS-02 uplinks one at a time" },
        { phase: "post", action: "Run validation set across both switches" },
        { phase: "post", action: "Post-snapshot, diff, and sign the gate record" },
      ],
    },
    {
      group: "Camera edge", order: 3, readiness: "NOT READY", gate: "NO-GO", strategy: "hard-cutover",
      n_switches: 2, switches: ["STU-AS-03", "CAM-AS-01"], make_before_break: [], hard_cutover: ["STU-AS-03", "CAM-AS-01"],
      endpoints: 420, hard_cutover_endpoints: 420, est_window_minutes: 120, est_window_label: "2h",
      sequence_note: "Single-homed hard cutover — endpoints WILL drop during the move; schedule a broadcast-safe window.",
      gateways: ["192.0.2.1"], spanning_vlans: [[140, "Camera-Feeds", 2]],
      blast_radius: { host: "CAM-AS-01", severity: "Critical", stranded: 260, vlans_impacted: 2, detail: "Uncollected and single-homed: the move is planned on [NOT OBSERVED] state." },
      keystones: ["MBG-DS-02"], n_fail: 2, n_warn: 0,
      blockers: [
        { check: "CAM-AS-01 collected", status: "fail", note: "No evidence — collect before planning the hard cut.", phase: "pre" },
        { check: "STU-AS-03 reachable", status: "fail", note: "Sole uplink is down; device unreachable.", phase: "pre" },
      ],
      critical_crosslayer: [
        { id: "XL-03", title: "Hard cutover on Past-LDoS hardware", layers: "L1+lifecycle", recommendation: "Stage replacement units on site before the window." },
      ],
      remediation: [
        { device: "STU-AS-03", title: "Restore uplink to MBG-DS-02", category: "hardware", severity: "Critical", why: "Device is dark; nothing can be verified until the link is up." },
        { device: "CAM-AS-01", title: "Collect device evidence", category: "coverage", severity: "High", why: "The wave plan is currently built on [NOT OBSERVED] state." },
      ],
      validation: [
        { category: "reachability", severity: "Critical", check: "Camera VLAN gateway reachable", command: "ping 192.0.2.1 source vlan 140", expect: "5/5 replies" },
        { category: "endpoints", severity: "Critical", check: "All camera feeds re-registered", command: "show mac address-table vlan 140", expect: "260 ±2 entries" },
        { category: "topology", severity: "High", check: "New dual uplinks forwarding", command: "show interfaces status", expect: "2 × connected" },
      ],
      run_of_show: [
        { phase: "pre", action: "Clear both blockers (collect CAM-AS-01, restore STU-AS-03 uplink)" },
        { phase: "cut", action: "Hard-cut both switches to the new distribution pair" },
        { phase: "post", action: "Verify every camera feed re-registers" },
        { phase: "post", action: "Post-snapshot, diff, PIR entry" },
      ],
    },
  ],
};

const DESIGN = {
  decisions: [
    {
      id: "D-01", title: "Deploy first-hop redundancy (HSRP) on all user VLANs", domain: "resiliency",
      priority: "Critical", status: "recommended", confidence: "Observed",
      driver: "18 user SVIs share one gateway chassis; any core reload is a campus outage.",
      evidence: { summary: "SVI census: 18 gateways on MBG-CORE-01, no standby group", count: 18, devices: ["MBG-CORE-01", "MBG-CORE-02"], fields: ["svi_census", "fhrp_absence"] },
      principle: { id: "CCDE-RES-2", title: "Eliminate single points of failure at the first hop", citation: "CCDE v3 practical — resiliency domain" },
      recommended_action: "HSRP active/standby split across MBG-CORE-01/02, preempt + tracked uplinks.",
      alternatives: "VRRP (multi-vendor), GLBP (per-flow load sharing).",
      tradeoffs: "One extra hop of config per SVI; marginal control-plane load.",
      axes: ["resilience", "operability"], requirements_needed: [],
    },
    {
      id: "lifecycle-eol-out-of-critical-roles", title: "Drive EoL/EoS hardware out of critical roles and protect against the upgrade flag-day", domain: "methodology",
      priority: "Critical", status: "recommended", confidence: "Observed",
      driver: "Supportability: the target fabric must not inherit end-of-support assets.",
      evidence: { summary: "2 device(s) are past last-day-of-support -- those end-of-support assets in forwarding roles cannot be safely relied on in the target design.", count: 2, devices: ["STU-AS-03", "CAM-AS-01"], fields: ["lifecycle_risk.per_device[].band", "software_risk.per_device[].train_band"] },
      principle: { id: "lifecycle-eol-out-of-critical-roles", title: "Drive EoL/EoS hardware out of critical roles and protect against the upgrade flag-day", citation: "CCDE In Depth Ch.2 Scalability (scale-out avoids the Flag Day) & Cost/TCO; engine EoL/software_risk axes" },
      recommended_action: "Prioritize refresh of EoL/EoS devices in core/critical roles; specify dual-supervisor/dual-RP (SSO/NSF) or paired-node scale-out so upgrades/swaps are non-disruptive; sequence the migration so no single change becomes a flag-day.",
      alternatives: "ISSU on a single chassis where supported; staged maintenance-window upgrades with rollback; time-boxed risk acceptance.",
      tradeoffs: "Investment-protection/HA vs CapEx and migration risk — refresh and scale-out cost up front but reduce long-run risk/TCO and enable hitless maintenance; deferring saves CapEx but raises outage and security exposure.",
      axes: ["availability", "cost"], requirements_needed: [],
    },
    {
      id: "fhrp-not-observed-is-not-healthy", title: "Treat unobserved FHRP/redundancy as UNKNOWN, never silently as healthy", domain: "methodology",
      priority: "Critical", status: "recommended", confidence: "Coverage-gap",
      driver: "Coverage honesty: do not design resilience on devices you have not seen.",
      evidence: { summary: "1 of 9 inventoried device(s) were not collected -- their role and redundancy are UNKNOWN. The design must collect them (incl. any uncollected core) before asserting target-state resilience; absence of evidence is not redundancy.", count: 1, devices: [], fields: ["collection_completeness.summary.not_collected"] },
      principle: { id: "fhrp-not-observed-is-not-healthy", title: "Treat unobserved FHRP/redundancy as UNKNOWN, never silently as healthy", citation: "Repo doctrine (evidence-grounded, coverage-honest); commits ee3a362/642ee31 (FHRP false-health fix); analyze.py:1886 canonical FHRP gate" },
      recommended_action: "Render 'FHRP absent' and 'not collected -> redundancy UNKNOWN' explicitly; never let a missing observation become a positive health claim. For the Meridian DS/CS core + EVS vPC pair (uncollected), mark redundancy UNKNOWN and recommend collection.",
      alternatives: "Collect the missing devices to convert UNKNOWN to a real verdict; explicit time-boxed risk acceptance only with a human sign-off.",
      tradeoffs: "Coverage-honesty vs a cleaner-looking report; surfacing UNKNOWN forces follow-up collection but prevents a customer-facing false-redundancy claim.",
      axes: ["availability", "manageability"], requirements_needed: [],
    },
    {
      id: "D-02", title: "Dual-home the single-homed access tier", domain: "resiliency",
      priority: "High", status: "recommended", confidence: "Observed",
      driver: "STU-AS-03 and CAM-AS-01 are bridge links — one cable from dark.",
      evidence: { summary: "2 bridge links in the CDP topology", count: 2, devices: ["STU-AS-03", "CAM-AS-01"], fields: ["topology_bridges", "link_centrality_assessed", "edges[].bridge_assessed"] },
      principle: { id: "CCDE-RES-4", title: "No single-homed aggregation of production endpoints", citation: "CCDE v3 practical — resiliency domain" },
      recommended_action: "Second uplink from each to MBG-DS-01; port-channel where optics allow.",
      alternatives: "Accept the risk for camera edge only, with a documented RTO.",
      tradeoffs: "2 optics + fibre runs; wave-3 window grows by ~30 minutes.",
      axes: ["resilience"], requirements_needed: [],
    },
    {
      id: "lifecycle-near-ldos-refresh-before-deadline", title: "Schedule Near-LDoS hardware replacement before the recorded support deadline", domain: "methodology",
      priority: "High", status: "recommended", confidence: "Observed",
      driver: "Deadline risk: preserve time for a staged replacement before recorded LDoS.",
      evidence: { summary: "1 device(s) are within one year of recorded LDoS. Give each an owned, approved replacement disposition and implementation window before that deadline; the date band does not establish contract entitlement.", count: 1, devices: ["MBG-DS-01"], fields: ["lifecycle_risk.per_device[].band", "lifecycle_risk.per_device[].ldos"] },
      principle: { id: "lifecycle-near-ldos-refresh-before-deadline", title: "Schedule Near-LDoS hardware replacement before the recorded support deadline", citation: "Cisco Product Lifecycle Policy; engine lifecycle_risk retained EoX evidence" },
      recommended_action: "Assign an owner, approved target disposition, budget, and implementation window before the recorded LDoS; verify exact PID/serial and any required contract entitlement separately.",
      alternatives: "A documented exception may retain the asset temporarily with explicit outage/spares exposure, but it does not change the recorded lifecycle deadline.",
      tradeoffs: "Earlier CapEx and migration effort versus a shrinking procurement and validation window; deferral preserves budget briefly but raises deadline and change-concentration risk.",
      axes: ["availability", "cost"], requirements_needed: [],
    },
    {
      id: "D-04", title: "Segment studio and corporate traffic into enforced zones", domain: "segmentation",
      priority: "Medium", status: "needs-requirement", confidence: "Declared",
      driver: "Studio video and corporate VLANs share the core with no inter-zone policy.",
      evidence: { summary: "VLAN census shows mixed studio/corporate on shared trunks", count: 24, devices: [], fields: ["vlan_census"] },
      principle: { id: "CCDE-SEC-3", title: "Segment by data classification, enforce at zone boundaries", citation: "CCDE v3 practical — security" },
      recommended_action: "Propose a VLAN-to-zone map once data_classification is supplied.",
      alternatives: "Flat network with ACL spot-controls (weaker audit posture).",
      tradeoffs: "Zone policy adds operational surface; clearer blast-radius boundaries.",
      axes: ["security", "operability"], requirements_needed: ["data_classification"],
    },
    {
      id: "lifecycle-past-eos-refresh-planning", title: "Place Past-EoS hardware in an owned refresh plan while recorded LDoS remains future", domain: "methodology",
      priority: "Medium", status: "recommended", confidence: "Observed",
      driver: "Investment planning: act before sourcing and migration choices narrow.",
      evidence: { summary: "1 device(s) are past end-of-sale with recorded LDoS still future. Place each in an owned, dated refresh plan; this is not an immediate-removal or support-entitlement claim.", count: 1, devices: ["MBG-DS-02"], fields: ["lifecycle_risk.per_device[].band", "lifecycle_risk.per_device[].eos", "lifecycle_risk.per_device[].ldos"] },
      principle: { id: "lifecycle-past-eos-refresh-planning", title: "Place Past-EoS hardware in an owned refresh plan while recorded LDoS remains future", citation: "Cisco Product Lifecycle Policy; engine lifecycle_risk retained EoX evidence" },
      recommended_action: "Record an owner, budget horizon, target disposition, and refresh date before recorded LDoS; verify exact PID/serial and any required contract entitlement in separate evidence.",
      alternatives: "Retain as a carry-forward candidate only through an explicit, dated risk acceptance that is reviewed against the approaching LDoS and available spares.",
      tradeoffs: "Planned refresh consumes future budget and engineering capacity; deferral may be reasonable while LDoS remains future, but narrows sourcing and migration choices over time.",
      axes: ["cost", "manageability"], requirements_needed: [],
    },
    {
      id: "lifecycle-unknown-resolve-authority", title: "Resolve lifecycle authority before approving hardware carry-forward or procurement", domain: "methodology",
      priority: "Medium", status: "recommended", confidence: "Coverage-gap",
      driver: "Coverage honesty: an unclassified asset needs evidence closure, not a healthy default.",
      evidence: { summary: "1 lifecycle row(s) are Unknown and 1 fleet asset(s) received no lifecycle row. Resolve exact PID/serial before carry-forward or procurement. Accept either a verified dated bulletin match, or a time-stamped authoritative EoX no-notice check with an owner and review date; no lifecycle or support-entitlement conclusion is inferred from absence.", count: 2, devices: ["NOC-AS-01", "STU-AS-02"], fields: ["lifecycle_risk.per_device[].band", "devices", "collection_completeness.summary.inventory"] },
      principle: { id: "lifecycle-unknown-resolve-authority", title: "Resolve lifecycle authority before approving hardware carry-forward or procurement", citation: "Cisco Product Lifecycle Policy; engine lifecycle_risk coverage and provenance contract" },
      recommended_action: "Collect exact PID and serial and resolve normalization. Either match a verified dated bulletin, or preserve a time-stamped authoritative EoX no-notice check with an owner, review date, and contingency/risk acceptance; verify entitlement separately and keep no-notice assets Unknown.",
      alternatives: "Carry the device only as an explicit unknown with contingency budget and a dated evidence-closure owner; do not classify it as Active or place it in a procurement bucket by subtraction.",
      tradeoffs: "Closing inventory and evidence gaps costs discovery time; proceeding without it may understate CapEx, retain obsolete hardware, or order against an incorrectly normalized platform.",
      axes: ["cost", "manageability"], requirements_needed: [],
    },
    {
      id: "D-05", title: "Right-size uplink capacity for the growth horizon", domain: "capacity",
      priority: "Low", status: "needs-requirement", confidence: "Declared",
      driver: "Uplink utilisation is healthy today; the 3-year picture depends on studio expansion plans.",
      evidence: { summary: "No sustained >40% utilisation in the sampled counters", count: 0, devices: [], fields: ["interface_counters"] },
      principle: { id: "CCDE-CAP-1", title: "Size for the stated horizon, not the peak day", citation: "CCDE v3 practical — capacity" },
      recommended_action: "Confirm growth_horizon; revisit 10G→25G on the studio distribution pair.",
      alternatives: "Reactive upgrades on utilisation alarms.",
      tradeoffs: "Early optics spend vs forklift risk later.",
      axes: ["capacity", "cost"], requirements_needed: ["growth_horizon"],
    },
  ],
  tradeoff_scorecard: [
    { axis: "resilience", label: "Resilience", score: 1, posture: "Fragile — no FHRP, single-homed edge", evidence: "AR-01, AR-03" },
    { axis: "capacity", label: "Capacity", score: 3, posture: "Headroom on every sampled uplink", evidence: "interface counters" },
    { axis: "security", label: "Security", score: 2, posture: "SSHv2 enforced; AAA gap on the access tier", evidence: "AR-04, AR-05" },
    { axis: "operability", label: "Operability", score: 2, posture: "Stale config archives; telemetry aligned", evidence: "AR-06, AR-07" },
    { axis: "cost", label: "Cost", score: null, posture: "Not scored — needs budget requirement", evidence: "" },
  ],
  target_state: {
    dimensions: [
      { area: "Gateway redundancy", current: "Single gateway chassis, no FHRP", target: "HSRP active/standby across the core pair", rationale: "Removes the campus-wide first-hop SPOF.", confidence: "Recommended" },
      { area: "Access uplinks", current: "2 of 5 access switches single-homed", target: "Every access switch dual-homed to both distribution switches", rationale: "One fibre fault must never strand an edge.", confidence: "Recommended" },
      {
        area: "Hardware lifecycle disposition",
        current: "2 past-LDoS, 2 approaching-LDoS or past-EoS (1 Near-LDoS; 1 Past-EoS), 1 not-collected of 9 inventoried. 1 of the 8 lifecycle-assessed asset(s) carry an UNDETERMINED band. 1 asset(s) of the fleet census were NOT lifecycle-assessed at all (the axis produced no row for them).",
        target: "Replace the 2 past-LDoS asset(s); schedule the 1 Near-LDoS asset(s) before recorded LDoS and place the 1 Past-EoS asset(s) in an owned refresh plan while LDoS remains future (together these are the replacement BoM's 2 refresh_soon asset(s) -- they are NOT in the carry-forward figure); identify ~3 pre-EoS date-band asset(s) as carry-forward candidates (schema: Active; support entitlement not assessed); collect the 1 un-assessed device(s) before finalising -- do not design resilience on unseen gear. 1 asset(s) have an UNDETERMINED lifecycle band (no exact EoX row matched or the matched row's source/date authority was withheld) -- they are not included among carry-forward candidates: resolve each model on the EoL portal before the list is final. A further 1 asset(s) were never lifecycle-assessed -- re-run the lifecycle axis before the carry-forward list is final; do not carry them forward by default.",
        rationale: "The target fabric must not inherit end-of-support hardware; coverage gaps are unknowns, not health.",
        confidence: "Recommended",
        drivers: ["lifecycle-eol-out-of-critical-roles", "lifecycle-near-ldos-refresh-before-deadline", "lifecycle-past-eos-refresh-planning", "lifecycle-unknown-resolve-authority", "fhrp-not-observed-is-not-healthy"],
      },
    ],
    replacement_bom: {
      replace_now: [["WS-C2960S-48", 2]],
      refresh_soon: [["N5K-C56128P", 1], ["WS-C2960X-48FPD-L", 1]],
      undetermined: [["C9300-48P", 1], ["Unknown", 1]],
      n_replace: 2, n_refresh: 2, n_near: 1, n_past_eos: 1, n_undetermined: 2, n_not_assessed: 1,
      note: "Quantities separate Past-LDoS replace-now assets from Near-LDoS and Past-EoS refresh-planning assets; a successor SKU is selected at detailed design (not auto-chosen here). Pre-EoS date-band assets are carry-forward candidates only; support entitlement was not assessed. Undetermined models either had no lifecycle row, no exact EoX row matched, or the matched row's source/date authority was withheld, so they are listed for evidence resolution, not costed. A time-stamped authoritative no-notice check may close the explanation while the asset correctly remains Unknown.",
    },
    addressing_plan: {
      status: "needs-requirement", requirement_needed: "address_space",
      n_census_vlans: 24, n_unsizable: 3, observed_vlans: 18,
      note: "Supply address_space (e.g. 10.0.0.0/16) to generate the candidate per-VLAN plan.",
    },
    wave_plan: {
      waves: [
        { wave: 1, kind: "pilot", n_switches: 1, switches: ["NOC-AS-01"], source_groups: [1] },
        { wave: 2, kind: "standard", n_switches: 2, switches: ["STU-AS-01", "STU-AS-02"], source_groups: [2] },
        { wave: 3, kind: "hard-cutover", n_switches: 2, switches: ["STU-AS-03", "CAM-AS-01"], source_groups: [3] },
      ],
      n_waves: 3, wave_cap: 12, n_move_groups: 3, largest_group: 2, n_subdivided_groups: 0,
      note: "Move-groups derived from shared-VLAN stranding; pilot-first ordering.",
    },
    segmentation_plan: {
      observed: "Studio and corporate VLANs share trunks and the core with no inter-zone enforcement.",
      status: "needs-requirement", requirement_needed: "data_classification",
      target: "Zone-per-classification with enforced boundaries at the distribution tier.",
    },
  },
  requirements_model: {
    fields: [
      { key: "availability_tier", label: "Availability tier", options: ["gold", "silver", "bronze"], value: null },
      { key: "address_space", label: "Target address space", example: "10.0.0.0/16", value: null },
      { key: "growth_horizon", label: "Growth horizon", example: "3y", value: null },
      { key: "data_classification", label: "Data classification", example: "broadcast,corp", value: null },
    ],
    open_questions: [
      { id: "Q-1", title: "Which VLANs carry regulated broadcast content?", needs: ["data_classification"] },
      { id: "Q-2", title: "What growth is planned for the studio floor?", needs: ["growth_horizon"] },
    ],
    provided: false,
    note: "Design top-down from the WHY: supply requirements and the engine right-sizes every decision server-side.",
  },
  methodology: "CCDE top-down: requirements → gap analysis → decisions traceable to evidence and principle.",
  axes: [
    { key: "resilience", label: "Resilience", intent: "Survive any single failure without endpoint impact" },
    { key: "capacity", label: "Capacity", intent: "Headroom for the stated growth horizon" },
    { key: "security", label: "Security", intent: "Segmented, auditable, least-privilege management" },
    { key: "operability", label: "Operability", intent: "Every change observable and reversible" },
    { key: "cost", label: "Cost", intent: "Spend where the risk register says, not by habit" },
  ],
  summary: {
    n_decisions: 9, n_recommended: 7, n_needs_requirement: 2, n_critical: 3,
    by_domain: { resiliency: 2, methodology: 5, segmentation: 1, capacity: 1 },
    requirements_provided: false,
    headline: "3 critical recommended target-state design decision(s); leading: Deploy first-hop redundancy (HSRP) on all user VLANs.",
  },
  coverage: { inventory: 9, collected: 8, not_collected: 1, caveat: "1 of 9 inventoried devices was not collected — its verdicts are declared, never scored." },
};

const NRFU = {
  items: [
    {
      decision_id: "D-01", title: "HSRP active/standby verified on every user VLAN", priority: "Critical",
      phase: "pre-cutover", description: "Confirm each user SVI has an HSRP group with the expected active/standby split and preempt.",
      pass_criteria: "show standby brief lists every user VLAN with Active on the designed chassis and a live Standby.",
      setup: "Console or SSH to both cores; the designed HSRP map printed from the LLD.",
      devices: ["MBG-CORE-01", "MBG-CORE-02"], principle_citation: "CCDE-RES-2 — first-hop redundancy",
    },
    {
      decision_id: "fhrp-not-observed-is-not-healthy", title: "Treat unobserved FHRP/redundancy as UNKNOWN, never silently as healthy", priority: "Critical",
      phase: "pre-cutover", description: "Verify ALL previously-uncollected devices are now reachable, collected, and their roles and redundancy are documented — 'unreachable' must not be accepted as a healthy state.",
      pass_criteria: "All devices respond to ICMP/SSH and appear in 'show cdp neighbors'; the assessment re-run collection-completeness.summary.not_collected == 0.",
      setup: "A fresh engine collection has been run against every previously-uncollected device.",
      devices: [], principle_citation: "Repo doctrine (evidence-grounded, coverage-honest); commits ee3a362/642ee31 (FHRP false-health fix); analyze.py:1886 canonical FHRP gate",
    },
    {
      decision_id: "lifecycle-eol-out-of-critical-roles", title: "Drive EoL/EoS hardware out of critical roles and protect against the upgrade flag-day", priority: "Critical",
      phase: "pre-cutover", description: "Verify every past-LDoS device has been replaced and is NOT in the forwarding path. Use 'show version' only to confirm the exact replacement PID/software; confirm any required active coverage from a separate serial-numbered contract or entitlement record.",
      pass_criteria: "'show version' confirms the exact PID/software on every replacement; a separate serial-numbered contract or entitlement record confirms any required active coverage; no past-LDoS device appears in 'show cdp neighbors' or the management inventory.",
      setup: "Replacement hardware is on site and staged for install; serial-numbered procurement and any required support-entitlement evidence are available for review.",
      devices: ["STU-AS-03", "CAM-AS-01"], principle_citation: "CCDE In Depth Ch.2 Scalability (scale-out avoids the Flag Day) & Cost/TCO; engine EoL/software_risk axes",
    },
    {
      decision_id: "lifecycle-near-ldos-refresh-before-deadline", title: "Schedule Near-LDoS hardware replacement before the recorded support deadline", priority: "High",
      phase: "pre-cutover", description: "Verify every Near-LDoS device has an approved replacement disposition, owner, budget, and dated implementation window before its recorded LDoS. Use 'show version' only to confirm the exact replacement PID/software; confirm any required coverage from a separate serial-numbered contract or entitlement record.",
      pass_criteria: "The inventory records exact PID/serial and recorded LDoS for every Near-LDoS device; an approved change or refresh record names the owner, funded target, and implementation date before LDoS; a separate contract or entitlement record confirms any required active coverage.",
      setup: "The authoritative EoX row is matched to exact PID/serial; the refresh owner, target, budget, and pre-LDoS change window are approved; any required support-entitlement evidence is available separately.",
      devices: ["MBG-DS-01"], principle_citation: "Cisco Product Lifecycle Policy; engine lifecycle_risk retained EoX evidence",
    },
    {
      decision_id: "lifecycle-past-eos-refresh-planning", title: "Place Past-EoS hardware in an owned refresh plan while recorded LDoS remains future", priority: "Medium",
      phase: "pre-cutover", description: "Verify every Past-EoS device has an owned, approved refresh disposition dated before its recorded LDoS; do not require immediate removal while LDoS remains future. Confirm exact PID/serial and any required coverage from separate entitlement evidence.",
      pass_criteria: "The inventory records exact PID/serial, EoS, and future LDoS for every Past-EoS device; each has an approved owner, target disposition, budget horizon, and review or implementation date before LDoS; any support entitlement is evidenced separately.",
      setup: "The authoritative EoX row is matched to exact PID/serial and shows LDoS still future; an owner and budget horizon are assigned, with any required support-entitlement evidence available separately.",
      devices: ["MBG-DS-02"], principle_citation: "Cisco Product Lifecycle Policy; engine lifecycle_risk retained EoX evidence",
    },
    {
      decision_id: "lifecycle-unknown-resolve-authority", title: "Resolve lifecycle authority before approving hardware carry-forward or procurement", priority: "Medium",
      phase: "pre-cutover", description: "Verify every Unknown or missing lifecycle asset has an exact PID/serial and an explained evidence outcome before approving carry-forward, refresh, or replacement: either a verified dated bulletin match, or a time-stamped authoritative EoX no-notice check with owner/review date. Do not infer a procurement disposition or support entitlement from missing evidence.",
      pass_criteria: "Missing lifecycle-row count is zero and every Unknown is explained: exact PID/serial plus either a verified dated bulletin match, or a time-stamped authoritative EoX no-notice record with owner, review date, and contingency/risk acceptance. Zero unexplained Unknowns remain; entitlement is evidenced separately and a no-notice result remains Unknown, never false Active.",
      setup: "A fresh inventory collection contains exact PID and serial for every unresolved asset; the retained EoX database is available, and current authoritative EoX lookup evidence can be time-stamped when no published notice exists.",
      devices: ["NOC-AS-01", "STU-AS-02"], principle_citation: "Cisco Product Lifecycle Policy; engine lifecycle_risk coverage and provenance contract",
    },
    {
      decision_id: "D-02", title: "Both uplinks forwarding on every access switch", priority: "High",
      phase: "post-cutover-functional", description: "Each access switch shows two connected uplinks with traffic on both.",
      pass_criteria: "show interfaces status: 2 × connected; counters increment on both within 60s.",
      setup: "Per-switch console list from the MOP.",
      devices: ["STU-AS-01", "STU-AS-02", "STU-AS-03", "NOC-AS-01", "CAM-AS-01"], principle_citation: "CCDE-RES-4 — dual-homing",
    },
  ],
  n_items: 7,
  evpn_acceptance: [],
  note: "Design-driven NRFU/ATP checklist: 7 acceptance-test item(s), one per recommended design decision, each traceable to the CCDE principle and the evidence that triggered it. Run after each migration wave; the pass/fail verdict for each item is independent of the design authors (proposer ≠ verifier). Items phased: pre-cutover → post-cutover-functional → post-cutover-operational.",
};

const COVERAGE = {
  // Representative nine-class visual subset only, not a literal serialization of the current
  // 27-class /architecture_coverage response. It deliberately stays compact for this Design card.
  // Class KEYS that trigger domain packs use the REAL _ARCH_COVERAGE_REGISTRY axes (fhrp_detail,
  // port_security, cts) so DOMAIN_PACKS below can never disagree with this grid — the same
  // "one coverage resolution" invariant the backend enforces for /domain_packs.
  classes: [
    { key: "fhrp_detail", label: "First-hop redundancy (HSRP/VRRP)", channel: "ssh", detectors: ["fhrp_absence"], observed: true, n_hosts: 2, hosts: ["MBG-CORE-01", "MBG-CORE-02"], status: "finding", findings: ["No FHRP on 18 user VLANs"] },
    { key: "lifecycle", label: "Hardware lifecycle (EoS/LDoS)", channel: "ssh", detectors: ["eos_register"], observed: true, n_hosts: 5, hosts: ["STU-AS-03", "CAM-AS-01", "MBG-DS-01", "MBG-DS-02", "NOC-AS-01"], status: "finding", findings: ["2 Past-LDoS; 1 Near-LDoS; 1 Past-EoS (LDoS future); 1 Unknown"] },
    { key: "etherchannel", label: "Link aggregation health", channel: "ssh", detectors: ["po_health"], observed: true, n_hosts: 4, hosts: ["MBG-CORE-01", "MBG-CORE-02", "MBG-DS-01", "MBG-DS-02"], status: "clean", findings: [] },
    { key: "igp", label: "Interior routing protocol", channel: "ssh", detectors: ["ospf_neighbors"], observed: true, n_hosts: 4, hosts: ["MBG-CORE-01", "MBG-CORE-02", "MBG-DS-01", "MBG-DS-02"], status: "clean", findings: [] },
    { key: "port_security", label: "Access-edge port security", channel: "ssh", detectors: ["port_security_config"], observed: true, n_hosts: 3, hosts: ["STU-AS-01", "STU-AS-02", "NOC-AS-01"], status: "clean", findings: [] },
    { key: "dmvpn", label: "DMVPN overlay", channel: "ssh", detectors: ["dmvpn_tunnels"], observed: false, n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
    { key: "cts", label: "TrustSec / CTS", channel: "ssh", detectors: ["cts_config"], observed: false, n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
    { key: "aci", label: "ACI fabric (APIC REST)", channel: "json", detectors: ["apic_tenants"], observed: false, n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
    { key: "sdwan", label: "Catalyst SD-WAN (vManage REST)", channel: "json", detectors: ["vmanage_sites"], observed: false, n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
  ],
  summary: { n_classes: 9, n_observed: 5, n_with_findings: 2, n_clean: 3, n_not_observed: 4, by_channel: { ssh: 7, json: 2 } },
};

/* Domain skill-packs (Phase-3/D6) for the SAME coverage above — exactly what the engine SSOT
 * cisco_toolkit.domain_packs.select_packs(COVERAGE) returns (selection is coverage-honest: a pack
 * loads iff one of its architecture classes is OBSERVED; port_security is deliberately in BOTH the
 * ent and sec packs, so this fleet shows one findings-bearing red chip and one clean green chip). */
const DOMAIN_PACKS = {
  selected: [
    { pack: "ent", title: "Enterprise / SD-Access", doc: "docs/packs/enterprise.md", triggered_by: ["fhrp_detail", "port_security"], with_findings: ["fhrp_detail"] },
    { pack: "sec", title: "Security / ISE-TrustSec-firewalls", doc: "docs/packs/security.md", triggered_by: ["port_security"], with_findings: [] },
  ],
  loaded: ["ent", "sec"],
  note: "2 pack(s) loaded: ent, sec",
};

const META = {
  engine_schema: "3.23",
  severity_order: ["Critical", "High", "Medium", "Low", "Info"],
  bands: ["Excellent", "Good", "Fair", "Poor", "Critical"],
  section_labels: [
    { key: "inventory", label: "Inventory" },
    { key: "health", label: "Health" },
    { key: "findings", label: "Findings" },
  ],
  deliverables: [
    { key: "workbook", label: "Assessment workbook", ext: "xlsx", available: true },
    { key: "cutover", label: "Cutover plan", ext: "docx", available: true },
    { key: "design", label: "HLD/LLD design", ext: "docx", available: true },
  ],
};

const EXECUTIONS = [
  { id: 101, snapshot_id: 1, label: "Run #1 — pilot rehearsal", status: "completed", started_at: "2026-06-20T21:00:00Z", ended_at: "2026-06-20T22:40:00Z" },
];

const HEALTH = { status: "ok", sample_available: true };

/** Ordered route table — first match wins (design/nrfu must precede design). */
export const DEMO_ROUTES: Array<[RegExp, unknown]> = [
  [/^\/api\/snapshots\/\d+\/graph$/, GRAPH],
  [/^\/api\/snapshots\/\d+\/cable_map$/, CABLE_MAP],
  [/^\/api\/snapshots\/\d+\/causal_flows$/, CAUSAL_FLOWS],
  [/^\/api\/snapshots\/\d+\/archreview$/, ARCH_REVIEW],
  [/^\/api\/snapshots\/\d+\/cutover$/, CUTOVER],
  [/^\/api\/snapshots\/\d+\/design\/nrfu$/, NRFU],
  [/^\/api\/snapshots\/\d+\/design$/, DESIGN],
  [/^\/api\/snapshots\/\d+\/architecture_coverage$/, COVERAGE],
  [/^\/api\/snapshots\/\d+\/domain_packs$/, DOMAIN_PACKS],
  [/^\/api\/snapshots\/\d+\/executions$/, EXECUTIONS],
  [/^\/api\/meta$/, META],
  [/^\/api\/health$/, HEALTH],
];
