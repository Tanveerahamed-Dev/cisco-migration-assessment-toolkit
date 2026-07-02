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
    { source: "MBG-CORE-01", target: "MBG-CORE-02", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-CORE-01", target: "MBG-DS-01", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-CORE-01", target: "MBG-DS-02", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-CORE-02", target: "MBG-DS-01", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-CORE-02", target: "MBG-DS-02", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-01", target: "STU-AS-01", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "STU-AS-01", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-01", target: "STU-AS-02", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "STU-AS-02", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "STU-AS-03", is_bridge: true, pairs_cut: 8 },
    { source: "MBG-DS-01", target: "NOC-AS-01", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "NOC-AS-01", is_bridge: false, pairs_cut: 0 },
    { source: "MBG-DS-02", target: "CAM-AS-01", is_bridge: true, pairs_cut: 8 },
  ],
};

const CABLE_MAP = {
  nodes: [
    {
      host: "MBG-CORE-01", role: "core", tier: 0, order: 0, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Po1", peer: "MBG-CORE-02", peer_port: "Po1", op_status: "up", is_pc: true },
        { name: "Te1/0/1", peer: "MBG-DS-01", peer_port: "Te1/1/1", op_status: "up", is_pc: false },
        { name: "Te1/0/2", peer: "MBG-DS-02", peer_port: "Te1/1/1", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "MBG-CORE-02", role: "core", tier: 0, order: 1, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Po1", peer: "MBG-CORE-01", peer_port: "Po1", op_status: "up", is_pc: true },
        { name: "Te1/0/1", peer: "MBG-DS-01", peer_port: "Te1/1/2", op_status: "up", is_pc: false },
        { name: "Te1/0/2", peer: "MBG-DS-02", peer_port: "Te1/1/2", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "MBG-DS-01", role: "distribution", tier: 1, order: 0, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Te1/1/1", peer: "MBG-CORE-01", peer_port: "Te1/0/1", op_status: "up", is_pc: false },
        { name: "Te1/1/2", peer: "MBG-CORE-02", peer_port: "Te1/0/1", op_status: "up", is_pc: false },
        { name: "Gi1/0/1", peer: "STU-AS-01", peer_port: "Gi1/0/49", op_status: "up", is_pc: false },
        { name: "Gi1/0/2", peer: "STU-AS-02", peer_port: "Gi1/0/49", op_status: "up", is_pc: false },
        { name: "Gi1/0/3", peer: "NOC-AS-01", peer_port: "Gi1/0/49", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "MBG-DS-02", role: "distribution", tier: 1, order: 1, collected: true, op_status: "up", badges: ["links-down"],
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
      host: "STU-AS-01", role: "access", tier: 2, order: 0, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Gi1/0/49", peer: "MBG-DS-01", peer_port: "Gi1/0/1", op_status: "up", is_pc: false },
        { name: "Gi1/0/50", peer: "MBG-DS-02", peer_port: "Gi1/0/1", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "STU-AS-02", role: "access", tier: 2, order: 1, collected: true, op_status: "up", badges: ["links-down"],
      ports: [
        { name: "Gi1/0/49", peer: "MBG-DS-01", peer_port: "Gi1/0/2", op_status: "up", is_pc: false },
        { name: "Gi1/0/50", peer: "MBG-DS-02", peer_port: "Gi1/0/2", op_status: "down", is_pc: false },
      ],
    },
    {
      host: "STU-AS-03", role: "access", tier: 2, order: 2, collected: true, op_status: "down", badges: ["links-down"],
      ports: [
        { name: "Gi1/0/49", peer: "MBG-DS-02", peer_port: "Gi1/0/3", op_status: "down", is_pc: false },
      ],
    },
    {
      host: "NOC-AS-01", role: "access", tier: 2, order: 3, collected: true, op_status: "up", badges: [],
      ports: [
        { name: "Gi1/0/49", peer: "MBG-DS-01", peer_port: "Gi1/0/3", op_status: "up", is_pc: false },
        { name: "Gi1/0/50", peer: "MBG-DS-02", peer_port: "Gi1/0/4", op_status: "up", is_pc: false },
      ],
    },
    {
      host: "CAM-AS-01", role: "access", tier: 2, order: 4, collected: false, op_status: "unknown", badges: ["uncollected"],
      ports: [
        { name: "Gi1/0/49", peer: "MBG-DS-02", peer_port: "Gi1/0/5", op_status: "unknown", is_pc: false },
      ],
    },
  ],
  cables: [
    { a: "MBG-CORE-01", a_port: "Po1", b: "MBG-CORE-02", b_port: "Po1", is_pc: true, members: [{ a_port: "Te1/1/1", b_port: "Te1/1/1" }, { a_port: "Te1/1/2", b_port: "Te1/1/2" }], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-CORE-01", a_port: "Te1/0/1", b: "MBG-DS-01", b_port: "Te1/1/1", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-CORE-01", a_port: "Te1/0/2", b: "MBG-DS-02", b_port: "Te1/1/1", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-CORE-02", a_port: "Te1/0/1", b: "MBG-DS-01", b_port: "Te1/1/2", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-CORE-02", a_port: "Te1/0/2", b: "MBG-DS-02", b_port: "Te1/1/2", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-DS-01", a_port: "Gi1/0/1", b: "STU-AS-01", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-DS-02", a_port: "Gi1/0/1", b: "STU-AS-01", b_port: "Gi1/0/50", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-DS-01", a_port: "Gi1/0/2", b: "STU-AS-02", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-DS-02", a_port: "Gi1/0/2", b: "STU-AS-02", b_port: "Gi1/0/50", is_pc: false, members: [], op_status: "down", confirmation: "both-seen" },
    { a: "MBG-DS-02", a_port: "Gi1/0/3", b: "STU-AS-03", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "down", confirmation: "one-side" },
    { a: "MBG-DS-01", a_port: "Gi1/0/3", b: "NOC-AS-01", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-DS-02", a_port: "Gi1/0/4", b: "NOC-AS-01", b_port: "Gi1/0/50", is_pc: false, members: [], op_status: "up", confirmation: "both-seen" },
    { a: "MBG-DS-02", a_port: "Gi1/0/5", b: "CAM-AS-01", b_port: "Gi1/0/49", is_pc: false, members: [], op_status: "unknown", confirmation: "cdp-only" },
  ],
  tiers: [
    ["MBG-CORE-01", "MBG-CORE-02"],
    ["MBG-DS-01", "MBG-DS-02"],
    ["STU-AS-01", "STU-AS-02", "STU-AS-03", "NOC-AS-01", "CAM-AS-01"],
  ],
  summary: { n_nodes: 9, n_cables: 13, n_tiers: 3, op: { up: 10, down: 2, unknown: 1 } },
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
      key: "lifecycle-eos-access", family: "lifecycle", family_label: "Lifecycle", icon: "⏳",
      title: "Past-EoS access switches carry production video",
      severity: "High", sev_tok: "risk",
      trigger: "Hardware fault on a past-EoS chassis",
      mechanism: "No vendor support or replacement stock for the platform",
      impact: "Studio edge stays down for days, not hours",
      mitigation: "Replace the 2 past-EoS access switches in wave 3",
      hosts: ["STU-AS-03", "CAM-AS-01"], blast: 420, blast_unit: "endpoints", shape: "linear",
      evidence: { summary: "2 platforms past end-of-support", count: 2, devices: ["STU-AS-03", "CAM-AS-01"], fields: ["lifecycle"], precision: "DEVICE", grounded: true },
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
      evidence: { summary: "aaa new-model absent on 4 of 7 collected devices", count: 4, devices: ["STU-AS-01", "STU-AS-02", "STU-AS-03", "NOC-AS-01"], fields: ["aaa_config"], precision: "DEVICE", grounded: true },
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
    { key: "lifecycle", label: "Lifecycle", icon: "⏳", n: 1, crit: 0 },
    { key: "security", label: "Security", icon: "🔒", n: 1, crit: 0 },
    { key: "topology", label: "Topology", icon: "🕸", n: 1, crit: 0 },
    { key: "coverage", label: "Coverage", icon: "👁", n: 1, crit: 0 },
  ],
  summary: { n_flows: 5, n_families: 5, n_critical: 1, by_severity: { Critical: 1, High: 2, Medium: 1, Info: 1 } },
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
        { id: "XL-03", title: "Hard cutover on past-EoS hardware", layers: "L1+lifecycle", recommendation: "Stage replacement units on site before the window." },
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
      axes: ["resilience", "operability"], requirements_needed: [], effective_priority: 98,
    },
    {
      id: "D-02", title: "Dual-home the single-homed access tier", domain: "resiliency",
      priority: "High", status: "recommended", confidence: "Observed",
      driver: "STU-AS-03 and CAM-AS-01 are bridge links — one cable from dark.",
      evidence: { summary: "2 bridge links in the CDP topology", count: 2, devices: ["STU-AS-03", "CAM-AS-01"], fields: ["topology_bridges"] },
      principle: { id: "CCDE-RES-4", title: "No single-homed aggregation of production endpoints", citation: "CCDE v3 practical — resiliency domain" },
      recommended_action: "Second uplink from each to MBG-DS-01; port-channel where optics allow.",
      alternatives: "Accept the risk for camera edge only, with a documented RTO.",
      tradeoffs: "2 optics + fibre runs; wave-3 window grows by ~30 minutes.",
      axes: ["resilience"], requirements_needed: [], effective_priority: 84,
    },
    {
      id: "D-03", title: "Replace past-EoS access hardware before the hard cutover", domain: "lifecycle",
      priority: "High", status: "recommended", confidence: "Observed",
      driver: "2 platforms are past end-of-support; the hard cutover would re-home production endpoints onto unsupported gear.",
      evidence: { summary: "2 platforms past EoS in the lifecycle register", count: 2, devices: ["STU-AS-03", "CAM-AS-01"], fields: ["lifecycle"] },
      principle: { id: "CCDE-LCM-1", title: "Never migrate onto unsupported hardware", citation: "CCDE v3 practical — lifecycle" },
      recommended_action: "Stage the replacement units (see BoM) and swap during the wave-3 window.",
      alternatives: "Defer replacement to a follow-on project (extends the risk window).",
      tradeoffs: "Capex now vs a second maintenance window later.",
      axes: ["resilience", "cost"], requirements_needed: [], effective_priority: 80,
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
      { area: "Hardware lifecycle", current: "2 past-EoS access platforms in production", target: "Supported platforms across the studio edge", rationale: "Vendor support restored before the hard cutover.", confidence: "Recommended" },
    ],
    replacement_bom: {
      replace_now: [["WS-C2960S-48", 2]], refresh_soon: [["WS-C3750X-48T", 2]],
      n_replace: 2, n_refresh: 2,
      note: "Replace-now covers the past-EoS studio edge; refresh-soon tracks the near-EoS distribution pair.",
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
    n_decisions: 5, n_recommended: 3, n_needs_requirement: 2, n_critical: 1,
    by_domain: { resiliency: 2, lifecycle: 1, segmentation: 1, capacity: 1 },
    requirements_provided: false,
    headline: "A fragile first hop and a single-homed studio edge dominate the design risk.",
  },
  coverage: { inventory: 9, collected: 7, not_collected: 2, caveat: "2 of 9 inventoried devices were not collected — their verdicts are declared, never scored." },
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
      decision_id: "D-02", title: "Both uplinks forwarding on every access switch", priority: "High",
      phase: "post-cutover-functional", description: "Each access switch shows two connected uplinks with traffic on both.",
      pass_criteria: "show interfaces status: 2 × connected; counters increment on both within 60s.",
      setup: "Per-switch console list from the MOP.",
      devices: ["STU-AS-01", "STU-AS-02", "STU-AS-03", "NOC-AS-01", "CAM-AS-01"], principle_citation: "CCDE-RES-4 — dual-homing",
    },
    {
      decision_id: "D-03", title: "Replacement hardware passing production traffic", priority: "High",
      phase: "post-cutover-functional", description: "The replaced studio-edge switches carry their full endpoint census.",
      pass_criteria: "MAC census within ±2 of the pre-cutover baseline per switch.",
      setup: "Pre-cutover census export attached to the wave record.",
      devices: ["STU-AS-03", "CAM-AS-01"], principle_citation: "CCDE-LCM-1 — supported hardware",
    },
    {
      decision_id: "D-01", title: "Failover drill: reload the standby core", priority: "Medium",
      phase: "post-cutover-operational", description: "Reload the HSRP standby and confirm zero gateway loss from a user VLAN.",
      pass_criteria: "Continuous ping from VLAN 110 loses ≤1 reply during the reload.",
      setup: "Change-window approval; continuous ping harness in the NOC.",
      devices: ["MBG-CORE-02"], principle_citation: "CCDE-RES-2 — verified failover",
    },
  ],
  n_items: 4,
  note: "One acceptance item per recommended design decision, phased pre-cutover → functional → operational.",
};

const COVERAGE = {
  classes: [
    { key: "fhrp", label: "First-hop redundancy (HSRP/VRRP)", channel: "ssh", detectors: ["fhrp_absence"], observed: true, n_hosts: 2, hosts: ["MBG-CORE-01", "MBG-CORE-02"], status: "finding", findings: ["No FHRP on 18 user VLANs"] },
    { key: "lifecycle", label: "Hardware lifecycle (EoS/LDoS)", channel: "ssh", detectors: ["eos_register"], observed: true, n_hosts: 2, hosts: ["STU-AS-03", "CAM-AS-01"], status: "finding", findings: ["2 platforms past end-of-support"] },
    { key: "etherchannel", label: "Link aggregation health", channel: "ssh", detectors: ["po_health"], observed: true, n_hosts: 4, hosts: ["MBG-CORE-01", "MBG-CORE-02", "MBG-DS-01", "MBG-DS-02"], status: "clean", findings: [] },
    { key: "igp", label: "Interior routing protocol", channel: "ssh", detectors: ["ospf_neighbors"], observed: true, n_hosts: 4, hosts: ["MBG-CORE-01", "MBG-CORE-02", "MBG-DS-01", "MBG-DS-02"], status: "clean", findings: [] },
    { key: "dmvpn", label: "DMVPN overlay", channel: "ssh", detectors: ["dmvpn_tunnels"], observed: false, n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
    { key: "trustsec", label: "TrustSec / CTS", channel: "ssh", detectors: ["cts_config"], observed: false, n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
    { key: "aci", label: "ACI fabric (APIC REST)", channel: "json", detectors: ["apic_tenants"], observed: false, n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
    { key: "sdwan", label: "Catalyst SD-WAN (vManage REST)", channel: "json", detectors: ["vmanage_sites"], observed: false, n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
  ],
  summary: { n_classes: 8, n_observed: 4, n_with_findings: 2, n_clean: 2, n_not_observed: 4, by_channel: { ssh: 6, json: 2 } },
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
  [/^\/api\/snapshots\/\d+\/executions$/, EXECUTIONS],
  [/^\/api\/meta$/, META],
  [/^\/api\/health$/, HEALTH],
];
