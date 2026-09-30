/**
 * Atlas Scope domain model — the contract every surface builds against.
 *
 * These types mirror `tools/lib/compile-model.mjs` (the one compiler) exactly. The rule that makes the whole app
 * trustworthy: `null` means NOT OBSERVED. It never means zero, healthy, or absent-therefore-fine.
 * Any renderer that turns a `null` into a green tick is a coverage-honesty defect.
 */

/** A dotted path back into the source snapshot, e.g. `punchlist[12]` or `acls.core1.MGMT_IN[3]`. */
export type Cite = string;

declare const NAME_KEYED: unique symbol;
/**
 * A dictionary keyed by names the SNAPSHOT supplies (hosts, ACL and object-group names, severities, producer
 * fields). Such a name is untrusted text, and `dict[name]` answers one the dictionary does not hold from the
 * prototype chain — so a host named "constructor" read the Object function as its routing table. Read one ONLY
 * through `own` / `holds` (core/own.ts). The optional brand member costs nothing at run time; it is what lets
 * `own-read.guard.test.ts` find every such dictionary by TYPE, and that guard also requires every string-keyed
 * dictionary the compiled documents carry to be one of these.
 */
export type NameKeyed<T> = Record<string, T> & { readonly [NAME_KEYED]?: never };

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
  /**
   * For each compiled field, the source record it was READ from (`devices.<host>`,
   * `cable_map.nodes[host=…]`, `health_scores[switch=…]`), emitted by the compiler and only where that
   * record exists. `cite` is the device's own record and holds none of the node or health fields, so a
   * surface citing a field cites THIS. A field with no entry is absent (null) or the compiler's own
   * default — never borrow another record's citation for it (acceptance B6).
   */
  fieldCites: Partial<Record<keyof Device, Cite>>;
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
  /** The `link_centrality[k]` row the four centrality figures were read from; null when none scored it. */
  centralityCite: Cite | null;
  cite: Cite;
}

/**
 * One row of the engine's `link_centrality`, compiled under its SOURCE path so the citation
 * `link_centrality[k]` resolves inside the model to the record that carries the figures (B6).
 */
export interface LinkCentrality {
  aHost: string | null;
  aPort: string | null;
  bHost: string | null;
  bPort: string | null;
  betweenness: number | null;
  isBridge: boolean | null;
  pairsCut: number | null;
  rank: number | null;
  cite: Cite;
}

/** One `health_scores` row, compiled under its source path (`health_scores[switch=…]`). */
export interface HealthScore {
  switch: string;
  role: string | null;
  score: number | null;
  band: string | null;
  criticality: number | null;
  dataQuality: number | null;
  deductions: string[];
  cite: Cite;
}

/** One `cable_map.nodes` row, compiled under its source path (`cable_map.nodes[host=…]`). */
export interface CableMapNode {
  host: string;
  kind: string | null;
  role: string | null;
  tier: number | null;
  order: number | null;
  collected: boolean | null;
  opStatus: string | null;
  badges: string[];
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
  /**
   * Why the finding carries its severity (`punchlist[i].severity_basis`), and how confident its
   * evidence is (`evidence_confidence`) — the producer's own words VERBATIM (even "N/A", "-" or ""), or
   * null only where the producer did not emit the key. The engine writes both on every Multicast/Media
   * row, with a non-empty "NOT published" sentence when it has no basis: that sentence is a DISCLOSURE,
   * never a measurement. Optional so fixtures built before the fields existed stay valid; the compiler
   * always emits them. Rendered, verbatim and labelled as the producer's words, in the Evidence pane header.
   */
  severityBasis?: string | null;
  evidenceConfidence?: string | null;
  /**
   * The per-finding evidence contract (`evidence_basis`, `evidence_refs`, `evidence_refs_total`).
   * `null` = the producer did not emit the key (an older snapshot) — never "no evidence". Every ref's
   * `ref` is an RFC 6901 JSON Pointer that the compiler RESOLVED against this model's own source
   * snapshot to a NON-NULL value; a pointer that did not stopped the build. `evidenceRefsTotal` is how many refs the
   * producer had before it capped the list, so a capped list is never read as complete. Rendered by the
   * Evidence pane (panels/EvidencePane.tsx `EngineEvidence`) from the projected `Fabric.evidenceRecords`.
   */
  evidenceBasis?: EvidenceBasis | null;
  evidenceRefs?: EvidenceRef[] | null;
  evidenceRefsTotal?: number | null;
  cite: Cite;
}

/** What a finding's evidence rests on: a record, an analysis row, or an observed absence. */
export const EVIDENCE_BASES = ["record", "row", "absence"] as const;
export type EvidenceBasis = (typeof EVIDENCE_BASES)[number];
/** What kind of record an evidence ref points at. The compiler refuses any other kind. */
export const EVIDENCE_REF_KINDS = [
  "interface",
  "acl_line",
  "route",
  "config_text",
  "device_fact",
  "analysis_row",
  "adjacency",
  "absence_witness",
] as const;
export type EvidenceRefKind = (typeof EVIDENCE_REF_KINDS)[number];
/** How the pointed-at record relates to the finding. */
export const EVIDENCE_REF_ROLES = ["derived_from", "subject", "witness"] as const;
export type EvidenceRefRole = (typeof EVIDENCE_REF_ROLES)[number];

/**
 * One pointer from a finding to the snapshot record it rests on (`punchlist[i].evidence_refs[k]`).
 *
 * The producer's short human label arrives as `cite` and is compiled as `label`. In this model `cite`
 * means ONE thing — a path back into the source snapshot — and every object carrying a string `cite` is
 * indexed as that citation's bearer (panels/Inspector.tsx `citeBearers`). Carried under `cite`, every
 * producer label — "(fleet) QoS finding row (best-effort-fleet)" first among them — became a "citation" that
 * no resolver could recognise (the inert-citation census's copy-tool case, 2026-09-28). The path is `ref`.
 */
export interface EvidenceRef {
  kind: EvidenceRefKind;
  /** The device the record belongs to, or null for a fabric-wide record. */
  host: string | null;
  /** An RFC 6901 JSON Pointer into the SOURCE snapshot, resolved at compile time. */
  ref: string;
  role: EvidenceRefRole;
  /** The producer's short human label for the record (its `cite`), verbatim. */
  label: string;
}

/** The JSON type of a projected value. */
export type EvidenceValueType = "string" | "number" | "boolean" | "null" | "object" | "array";

/** A member as the projection carries it: a scalar the engine wrote, or a nested value's compact JSON text. */
export type EvidenceScalar = string | number | boolean | null;

/**
 * The record an engine evidence pointer names, projected into the model (`Fabric.evidenceRecords`). The
 * compiler copies ONLY values some finding's `evidence_refs` point at, once per distinct pointer, and bounds
 * every one (EvidenceProjection). Its `cite` IS its pointer, so the Inspector resolves the pointer to it.
 *
 * - `value` is the engine's value, one level deep: an object's or list's members in the engine's order, each
 *   scalar as the engine wrote it; a member that is itself an object or list is its compact JSON TEXT and is
 *   named in `nested`. A scalar record (a configuration line, a literal evidence string) is the scalar.
 * - `cut` names every text shortened to its cap, with the WHOLE length (a scalar record's own under ""), so a
 *   cut is always stated. `fieldsTotal` is how many members the record has; fewer carried = members omitted.
 * - `withheld`: the model's total budget was spent before this record, so no value is carried (`value` is
 *   null) — the record is still in the source snapshot at `pointer`, and a surface must say so.
 */
export interface EvidenceRecord {
  pointer: string;
  cite: Cite;
  type: EvidenceValueType;
  /** Length of the whole record, as compact JSON, in the source. */
  jsonChars: number;
  value: EvidenceScalar | NameKeyed<EvidenceScalar> | EvidenceScalar[];
  nested: string[];
  cut: NameKeyed<number>;
  fieldsTotal: number;
  withheld: boolean;
}

/** The bounds the compiler projected evidence records under, and what they cost (stated, never implied). */
export interface EvidenceProjection {
  /** Most characters of one member's text, and of a scalar record's text. */
  fieldTextChars: number;
  scalarTextChars: number;
  /** Most members carried for one record, and most characters one projected record may take. */
  recordFields: number;
  recordChars: number;
  /**
   * Most characters the whole projection may take AS WRITTEN, the withheld records' pointer-only stubs
   * included; records past it are `withheld`, chosen in the engine's priority order (a lower-ranked record never
   * displaces a higher-ranked one). Exceeded only when the stubs alone outgrow it — then every record is
   * withheld, and `writtenChars` > `totalChars` states it.
   */
  totalChars: number;
  /** Distinct pointers the findings carry (= evidenceRecords.length). */
  records: number;
  /** Characters the carried (not withheld) records take together; a withheld record carries its pointer only. */
  projectedChars: number;
  recordsWithheld: number;
  /** Members not carried because a record hit `recordFields` or `recordChars`. */
  fieldsOmitted: number;
  /** Field or scalar texts shortened to their cap. */
  textsCut: number;
  /** Characters the withheld records' pointer-only stubs take together. */
  withheldChars: number;
  /**
   * Characters the whole `evidenceRecords` array takes as written (compact JSON): projectedChars + withheldChars plus
   * its brackets and separating commas — the figure `totalChars` bounds.
   */
  writtenChars: number;
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
  /* Compiled since the port-health compiler was written but never declared here — found by
     compile-types.test.ts, which checks the compiler's real output against these types (S1-R2V-5). */
  lateCollisions: number | null;
  outputDrops: number | null;
  poe: string | null;
  risk: string | null;
  /** The engine's own "[NOT OBSERVED] …" explanation for a port with no counters, kept verbatim. */
  riskUnobserved: string | null;
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
  aclSummary: NameKeyed<number>;
  cite: Cite;
}

/** The byte form `sourceSha256` is taken over. */
export type SourceDigestForm = "lf-normalised" | "assesshub-store-blob";
/** Where the source bytes came from; it decides what "the exact bytes" are (tools/lib/compile-model.mjs `bindingPreimages`). */
export type SourceOrigin = "repository-file" | "external-file" | "assesshub-store";

/**
 * What binds a compiled file to the snapshot it was read from. Written by the one compiler
 * (`tools/lib/compile-model.mjs` `bindSourceWith`); in Node the hashes come from `tools/source-binding.mjs`.
 *
 * - `source` / `sourceOrigin`: WHICH snapshot — a repository-relative path ("repository-file": a file
 *   Git TRACKS in this repository), a bare file name ("external-file": any other file, including an
 *   untracked or ignored one inside the repository), or `assesshub:snapshot/<id>` ("assesshub-store").
 *   Never an absolute path. (Where Git does not own the tree — a copied package — containment decides.)
 * - `sourceSha256` / `sourceBytes` / `sourceDigestForm`: the digest over the LF-NORMALISED bytes (every
 *   CR LF read as LF, nothing else changed) — the form Git stores, so it equals
 *   `git cat-file blob HEAD:<source> | sha256sum` and is the same from a CRLF or an LF checkout (O15);
 *   or, form "assesshub-store-blob", over an AssessHub stored blob exactly. A digest without its form
 *   does not say which bytes it binds. The form is TIED to the origin: "assesshub-store-blob" if and only
 *   if the origin is "assesshub-store"; any other combination is refused (E_SOURCE_LABEL).
 * - `sourceExactSha256`: `"sha256:" + hex` over the bytes AS READ — exactly what its name says, for every
 *   origin, in the ENGINE's own binding form (cisco_toolkit/protocol_assurance.py), so a model joins an
 *   engine receipt by value. It is therefore the one BYTE-DEPENDENT key (SOURCE_BINDING_BYTE_KEYS): a CRLF
 *   and an LF checkout of the same repository file give different values, and every other key the same.
 *   A test that compares compiles of the two checkouts compares the model with these keys excluded, and
 *   separately checks that each one is the digest of the bytes that compile read. The TRACKED compiled
 *   files are compiled from the committed (LF) bytes, so for them it equals `"sha256:" + sourceSha256`.
 * - `sourceGitBlob`: the Git blob id of the LF-normalised bytes (`git hash-object`; for an unmodified
 *   tracked source, `git rev-parse HEAD:<source>`).
 */
export interface SourceBinding {
  source: string;
  sourceOrigin: SourceOrigin;
  sourceDigestForm: SourceDigestForm;
  sourceSha256: string;
  sourceBytes: number;
  sourceExactSha256: string;
  sourceGitBlob: string;
}

/**
 * Every key of SourceBinding, in the order the compiler writes them. `SourceBindingKeysCoverTheType`
 * below fails to compile if a key is added to SourceBinding and not here, so `sameSourceBinding` —
 * which iterates this list — can never silently skip a binding field.
 */
export const SOURCE_BINDING_KEYS = [
  "source",
  "sourceOrigin",
  "sourceDigestForm",
  "sourceSha256",
  "sourceBytes",
  "sourceExactSha256",
  "sourceGitBlob",
] as const satisfies readonly (keyof SourceBinding)[];
/**
 * The binding keys whose value depends on the exact bytes read (line endings included), rather than on
 * the content every checkout shares. `src/core/compile-binding.test.ts` derives this set from two real
 * bindings of a CRLF and an LF copy and requires it to equal this list.
 */
export const SOURCE_BINDING_BYTE_KEYS = ["sourceExactSha256"] as const satisfies readonly (keyof SourceBinding)[];
type AssertNever<T extends never> = T;
/** Compile-time proof that SOURCE_BINDING_KEYS covers SourceBinding. */
export type SourceBindingKeysCoverTheType = AssertNever<Exclude<keyof SourceBinding, (typeof SOURCE_BINDING_KEYS)[number]>>;

/**
 * Whether a sidecar's `meta` binds the SAME source bytes as `bound`. EVERY binding key must agree —
 * the form and the origin included, and a sidecar that omits any key fails — so a digest taken over
 * other bytes (another snapshot, or the same snapshot in another byte form) can never be read as this
 * build's.
 */
export function sameSourceBinding(meta: Partial<Record<keyof SourceBinding, unknown>> | null | undefined, bound: SourceBinding): boolean {
  if (meta === null || meta === undefined) return false;
  return SOURCE_BINDING_KEYS.every((k) => meta[k] !== undefined && meta[k] === bound[k]);
}

export interface SnapshotMeta extends SourceBinding {
  schema: string | null;
  /** The schema a legacy (schema-less) snapshot was READ AS under --allow-legacy; null when the snapshot stated its own. */
  schemaAssumed: string | null;
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
  routes: NameKeyed<RouteEntry[]>;
  acls: NameKeyed<NameKeyed<AclLine[]>>;
  /** Object groups an ACL match field may reference, keyed by host then group name. */
  objectGroups: NameKeyed<NameKeyed<ObjectGroup>>;
  aclFindings: AclFinding[];
  l3: L3Interface[];
  interfaces: NameKeyed<InterfaceRecord[]>;
  physical: PhysicalHealth[];
  protocols: ProtocolHealth[];
  endpoints: Endpoint[];
  coverage: Coverage;
  /** The source records device and link figures are read from, under the paths their citations name. */
  cable_map: { nodes: CableMapNode[] };
  health_scores: HealthScore[];
  link_centrality: LinkCentrality[];
  /**
   * The records the findings' engine evidence pointers name, one per distinct pointer, sorted by pointer
   * (tools/lib/compile-model.mjs `compileEvidenceRecords`). Optional so a model compiled before the
   * projection existed stays readable; the compiler always emits both keys.
   */
  evidenceRecords?: EvidenceRecord[];
  evidenceProjection?: EvidenceProjection;
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
  /**
   * The statement of exactly what this result does and does not claim. Prose, not a single sentence:
   * a decided claim routinely runs to two or more (the verdict, then what it does not cover — e.g.
   * "…is denied at core1 by … . Received traffic …; stateful return traffic is not modelled."), and
   * an undecided delivery appends the sentence saying why it is undecided.
   */
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
