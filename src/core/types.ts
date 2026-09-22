/**
 * Atlas Scope domain model — the contract every surface builds against.
 *
 * These types mirror `tools/compile-snapshot.mjs` exactly. The rule that makes the whole app
 * trustworthy: `null` means NOT OBSERVED. It never means zero, healthy, or absent-therefore-fine.
 * Any renderer that turns a `null` into a green tick is a coverage-honesty defect.
 */

/** A dotted path back into the source snapshot, e.g. `punchlist[12]` or `acls.core1.MGMT_IN[3]`. */
export type Cite = string;

export type Severity = "Critical" | "High" | "Medium" | "Low" | "Info";
export type Band = "Excellent" | "Good" | "Fair" | "Poor" | "Critical";
export type OpStatus = "up" | "down" | "unknown" | string;

export const SEVERITY_ORDER: readonly Severity[] = ["Critical", "High", "Medium", "Low", "Info"];
export const BAND_ORDER: readonly Band[] = ["Excellent", "Good", "Fair", "Poor", "Critical"];

export interface FailureImpact {
  severity: string | null;
  vlans: number | null;
  stranded: number | null;
  hard: number | null;
  backup: number | null;
  fhrp: number | null;
  detail: string | null;
  cite: Cite;
}

export interface Device {
  id: string;
  host: string;
  /** Did the collector actually reach this device? A topology-only neighbour has collected:false. */
  collected: boolean;
  /** Is there an inventory record (model/serial/software) for it? */
  inventoried: boolean;
  kind: string;
  role: string | null;
  tier: number | null;
  order: number;
  opStatus: OpStatus;
  badges: string[];
  platform: string | null;
  model: string | null;
  serial: string | null;
  swVersion: string | null;
  uptime: string | null;
  powerSupplies: number | null;
  modules: number | null;
  score: number | null;
  band: Band | null;
  criticality: number | null;
  dataQuality: number | null;
  deductions: string[];
  impact: FailureImpact | null;
  cite: Cite;
}

export interface Link {
  id: string;
  a: string;
  aPort: string | null;
  b: string;
  bPort: string | null;
  isPortChannel: boolean;
  members: string[];
  speedMbps: number | null;
  opStatus: OpStatus;
  /** How the engine confirmed the adjacency, e.g. "Both ends" vs "One end (access1)". */
  confirmation: string | null;
  betweenness: number | null;
  /** True when cutting this link partitions the graph. `null` = centrality not computed for it. */
  isBridge: boolean | null;
  pairsCut: number | null;
  centralityRank: number | null;
  cite: Cite;
}

export interface Finding {
  id: string;
  severity: Severity;
  rank: number | null;
  priority: number | null;
  category: string | null;
  devices: string[];
  wave: string | null;
  title: string;
  detail: string | null;
  remediation: string | null;
  /**
   * The show-command the engine cites as this finding's evidence (`punchlist[i].source_command`,
   * cited by `cite`), or null when the producer named none — a composite category with no single
   * backing command. A command NAME, not a record: the snapshot keeps no raw command output, so
   * this is provenance and never a route to literal configuration text. Optional so fixtures built
   * before the field existed stay valid; the compiler always emits it.
   */
  sourceCommand?: string | null;
  cite: Cite;
}

export interface CrossLayerFinding {
  id: string;
  severity: Severity;
  layers: string | null;
  title: string;
  detail: string | null;
  recommendation: string | null;
  hosts: string[];
  cite: Cite;
}

export interface RouteEntry {
  prefix: string;
  source: string | null;
  nextHop: string | null;
  outIntf: string | null;
  adminDistance: number | null;
  cite: Cite;
}

export interface AclMatchField {
  ip: string | null;
  wild: string | null;
  /** Names an object-group instead of an address/wildcard pair. Resolve against `Fabric.objectGroups`. */
  group: string | null;
}
export interface AclPortMatch {
  op: string;
  /** `null` when the producer could not resolve a port NAME (e.g. `eq citrix`). Never compare it
   *  numerically: `port === null` is a definite non-match, which silently turns a permit into a
   *  deny. A line carrying one is marked `unevaluable`. */
  val: number | null;
  val2?: number | null;
}
export interface AclLine {
  index: number;
  action: string | null;
  raw: string | null;
  proto: string | null;
  src: AclMatchField | null;
  dst: AclMatchField | null;
  sport: AclPortMatch | null;
  dport: AclPortMatch | null;
  /**
   * The PRODUCER's own verdict that it could not model this line. This is ground truth and takes
   * precedence over any re-derivation from `raw`: re-deriving evaluability in the consumer is the
   * parser-versus-detector drift that lets a line the parser knew was unmodellable be evaluated
   * anyway, turning an unknown into a confident wrong answer.
   */
  unevaluable: boolean;
  /** Which qualifiers defeated the producer, e.g. `["icmp_type"]`. */
  unmodeledQualifiers: string[];
  /** Stateful match. A forward-direction model cannot decide it. */
  established: boolean;
  /** An ICMP qualifier the matcher does not implement. */
  icmpType: string | null;
  /** The rule is only active inside this named window, so ANY verdict on it is conditional. */
  timeRange: string | null;
  cite: Cite;
}

export interface ObjectGroupMember {
  ip: string | null;
  wild: string | null;
}
export interface ObjectGroup {
  kind: string | null;
  members: ObjectGroupMember[];
  cite: Cite;
}

export interface AclFinding {
  host: string | null;
  acl: string | null;
  lineIndex: number | null;
  action: string | null;
  raw: string | null;
  verdict: string | null;
  reason: string | null;
  detail: string | null;
  blockingLines: unknown[];
  sourceCommand: string | null;
  cite: Cite;
}

export interface L3Interface {
  host: string | null;
  vlan: number | null;
  sviIp: string | null;
  fhrp: string | null;
  fhrpRole: string | null;
  vip: string | null;
  routingSource: string | null;
  nextHop: string | null;
  primarySubnet: string | null;
  secondary: string | null;
  tracking: string | null;
  /** The engine's own "[NOT OBSERVED] - ..." prose, kept verbatim when it carries a reason. */
  trackingUnobserved: string | null;
  risk: string | null;
  riskUnobserved: string | null;
  severity: string | null;
  cite: Cite;
}

export interface InterfaceRecord {
  port: string;
  status: string | null;
  duplex: string | null;
  speed: string | null;
  portType: string | null;
  linkType: string | null;
  description: string | null;
  portChannel: string | null;
  pcProtocol: string | null;
  runConfigObserved: boolean;
  cite: Cite;
}

export interface PhysicalHealth {
  host: string | null;
  port: string | null;
  status: string | null;
  speed: string | null;
  duplex: string | null;
  media: string | null;
  inputErrors: number | null;
  crcErrors: number | null;
  outputErrors: number | null;
  outputDrops: number | null;
  poe: string | null;
  risk: string | null;
  severity: string | null;
  cite: Cite;
}

export interface ProtocolHealth {
  host: string | null;
  protocol: string | null;
  severity: string | null;
  summary: string | null;
  detail: string | null;
  cite: Cite;
}

export interface Endpoint {
  host: string | null;
  port: string | null;
  vlan: string | null;
  ip: string | null;
  mac: string | null;
  macCount: number | null;
  vendor: string | null;
  endpointClass: string | null;
  confidence: string | null;
  evidence: string | null;
  cite: Cite;
}

export interface Coverage {
  devicesInventoried: number;
  devicesOnTopologyOnly: number;
  hostsWithRoutes: number;
  hostsWithAcls: number;
  hostsWithObjectGroups: number;
  /** ACL lines the PRODUCER could not model. A definite verdict that steps over one is an overclaim. */
  aclLinesUnevaluable: number;
  aclLinesTotal: number;
  hostsWithInterfaces: number;
  /** The exact hosts whose RIB we hold. Forwarding claims are scoped to THIS list and no wider. */
  routableHosts: string[];
  aclHosts: string[];
  linksWithCentrality: number;
  aclSummary: Record<string, number>;
  cite: Cite;
}

export interface SnapshotMeta {
  source: string;
  sourceBytes: number;
  sourceSha256: string;
  schema: string | null;
  scriptVersion: string | null;
  collectedAt: string | null;
  generatedAt: string | null;
}

export interface Fabric {
  meta: SnapshotMeta;
  tiers: string[][];
  devices: Device[];
  links: Link[];
  findings: Finding[];
  crossLayer: CrossLayerFinding[];
  routes: Record<string, RouteEntry[]>;
  acls: Record<string, Record<string, AclLine[]>>;
  /** Object groups an ACL match field may reference, keyed by host then group name. */
  objectGroups: Record<string, Record<string, ObjectGroup>>;
  aclFindings: AclFinding[];
  l3: L3Interface[];
  interfaces: Record<string, InterfaceRecord[]>;
  physical: PhysicalHealth[];
  protocols: ProtocolHealth[];
  endpoints: Endpoint[];
  coverage: Coverage;
}

/* ── forwarding simulation contract ─────────────────────────────────────────
   Produced by src/forwarding/engine.ts, consumed by the 3-D flow renderer, the Path panel and
   the Inspector. Deliberately shaped after Batfish's claim discipline: a verdict is always
   accompanied by the scope it holds over and the evidence it rests on. */

export type HopVerdict =
  | "forwarded"
  | "delivered"
  | "no-route"
  | "denied"
  | "unmodeled"
  | "loop"
  | "ttl-exceeded";

export interface Flow {
  srcIp: string;
  dstIp: string;
  protocol: "tcp" | "udp" | "icmp" | "ip";
  dstPort: number | null;
  srcPort: number | null;
}

export interface HopEvidence {
  kind: "route" | "acl" | "svi" | "topology" | "absence";
  label: string;
  raw: string | null;
  cite: Cite;
}

export interface Hop {
  index: number;
  host: string;
  /** Egress interface chosen by the longest-prefix match, when the RIB names one. */
  outIntf: string | null;
  nextHop: string | null;
  nextHost: string | null;
  verdict: HopVerdict;
  /** The single line that decided this hop — the "blocking hop" answer. */
  decidedBy: HopEvidence | null;
  evidence: HopEvidence[];
  /** Route entries considered but beaten by the winner, for the "why not that one" question. */
  alternatives: RouteEntry[];
}

export type TraceOutcome = "delivered" | "dropped" | "denied" | "indeterminate" | "out-of-scope";

export interface Trace {
  flow: Flow;
  outcome: TraceOutcome;
  hops: Hop[];
  /** One sentence stating exactly what this result does and does not claim. */
  claim: string;
  /** Every reason the result is narrower than it looks. Never empty when scope is limited. */
  caveats: string[];
  /** Hosts whose forwarding could NOT be modelled because no RIB was collected for them. */
  unmodelledHosts: string[];
  /** Wall-clock milliseconds the simulation took, for the responsiveness budget. */
  elapsedMs: number;
}

/* ── investigation state contract ───────────────────────────────────────────── */

export type SurfaceId = "fabric" | "findings" | "path" | "evidence";

export interface Selection {
  deviceId: string | null;
  linkId: string | null;
  findingId: string | null;
}
