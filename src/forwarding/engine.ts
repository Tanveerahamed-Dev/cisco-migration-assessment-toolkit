/**
 * engine.ts — the forwarding simulator.
 *
 * It answers one question: can this flow get from A to B, and if not, exactly what stopped it?
 * The answer is always paired with the scope it holds over, because this snapshot is thin where it
 * matters: RIBs were collected for 2 of 26 hosts, ACLs for 1, and NO `ip access-group` binding was
 * collected anywhere. Every one of those gaps is a reason a result is narrower than it looks, and
 * each is emitted as a caveat rather than silently absorbed.
 *
 * The invariant that shapes the whole file: a missing input never produces a positive result.
 * No RIB for a host is "unmodeled" and the trace outcome becomes indeterminate — never "delivered".
 * An ACL line we cannot evaluate poisons the lines below it, because we cannot prove our match is
 * the one that fires. Absence is absence.
 */
import { aclsOf, fabric, hasRib, linksByHost, routesOf } from "../core/data";
import type {
  AclFinding,
  AclLine,
  AclMatchField,
  ObjectGroup,
  AclPortMatch,
  Cite,
  Flow,
  Hop,
  HopEvidence,
  L3Interface,
  RouteEntry,
  Trace,
  TraceOutcome,
} from "../core/types";
import {
  addressRoleIn,
  formatIpv4,
  formatPrefix,
  hostAddressIn,
  parseInterfaceAddress,
  parseIpv4,
  parsePrefix,
  prefixContains,
  rankPrefixMatches,
  wildcardMatches,
  wildcardSpecificity,
  type Ipv4,
  type Prefix,
} from "./ip";

/** Hop cap. 16 is far above this fabric's diameter (5 tiers), so hitting it means a routing loop. */
export const TTL_LIMIT = 16;

/** Ternary match: `maybe` is the whole point — it is what stops a guess becoming a claim. */
export type Tri = "yes" | "no" | "maybe";

/**
 * Which of a line's parsed match fields were shown to REPRESENT its configuration text.
 *
 * A dimension is true only once the text-reading below has reached it and agreed with the parse.
 * The matcher may draw a definite conclusion from a dimension only when it is true here, because
 * the alternative is what happened with `eq 443 8443`: a port field holding 443 stood in for text
 * naming two ports, and the matcher then read 8443 as a definite non-match on a line permitting it.
 */
export interface FieldRepresentation {
  proto: boolean;
  src: boolean;
  dst: boolean;
  sport: boolean;
  dport: boolean;
}

export interface LineEvaluability {
  evaluable: boolean;
  /** Why not, in the engine's own words. Null only when evaluable. */
  reason: string | null;
  /** The snapshot's own acl_line_reachability detail for this line, when it raised one. */
  snapshotDetail: string | null;
  /** Per-dimension trust. Everything not reached before a refusal stays false — fail closed. */
  representative: FieldRepresentation;
}

/**
 * Where a suggested flow's source address came from.
 *
 * Not every suggested source was seen on the wire: two of them are DERIVED — a usable host address
 * inside a subnet the collection observed — because the interesting cases (a gateway whose RIB was
 * never collected, a subnet with no default route) have no observed endpoint to start from. That is
 * a legitimate way to pose a question and an illegitimate thing to leave unsaid, so it is a field
 * rather than a footnote: a consumer that renders these must be able to mark a derived address as
 * derived without re-deriving the fact.
 */
export interface SourceProvenance {
  kind: "observed" | "derived-from-observed-subnet" | "outside-every-observed-subnet";
  /** The record that observed the address, named the subnet it was derived from, or bounds the scope. */
  cite: Cite;
  note: string;
}

export interface SuggestedFlow {
  id: string;
  title: string;
  flow: Flow;
  rationale: string;
  /** The outcome this flow ACTUALLY produced when traced at module load — not an intention. */
  expectedOutcome: TraceOutcome;
  /** Whether `flow.srcIp` was observed or derived. Never absent: an unlabelled address reads as observed. */
  srcProvenance: SourceProvenance;
}

export type CounterexampleResult =
  | { found: true; flow: Flow; trace: Trace; rationale: string }
  | { found: false; reason: string };

/* ── indexes over the compiled evidence, built once ─────────────────────────── */

interface SviSubnet {
  host: string;
  ip: Ipv4;
  prefix: Prefix;
  vip: Ipv4 | null;
  fhrpRole: string | null;
  record: L3Interface;
}

const SVI_SUBNETS: readonly SviSubnet[] = fabric.l3.flatMap((r) => {
  if (r.host === null || r.sviIp === null) return [];
  const addr = parseInterfaceAddress(r.sviIp);
  if (addr === null) return [];
  return [
    {
      host: r.host,
      ip: addr.ip,
      prefix: addr.prefix,
      vip: r.vip === null ? null : parseIpv4(r.vip),
      fhrpRole: r.fhrpRole,
      record: r,
    },
  ];
});

interface OwnedAddress {
  host: string;
  label: string;
  cite: Cite;
  kind: HopEvidence["kind"];
  /** The FHRP role observed for the interface that owns this address; null when none was observed. */
  fhrpRole: string | null;
  /** How the interface's FHRP is spelled in the evidence, for prose that quotes the record. */
  fhrp: string | null;
}

/** ip -> the hosts that own it (SVI address, FHRP virtual address, or a `local` /32 in a RIB). */
const ADDRESS_OWNERS: ReadonlyMap<number, OwnedAddress[]> = (() => {
  const m = new Map<number, OwnedAddress[]>();
  const add = (ip: Ipv4 | null, o: OwnedAddress) => {
    if (ip === null) return;
    const list = m.get(ip);
    if (list) list.push(o);
    else m.set(ip, [o]);
  };
  for (const s of SVI_SUBNETS) {
    add(s.ip, {
      host: s.host,
      label: `${s.host} Vlan${s.record.vlan ?? "?"} address ${formatIpv4(s.ip)}`,
      cite: s.record.cite,
      kind: "svi",
      fhrpRole: s.fhrpRole,
      fhrp: s.record.fhrp,
    });
    add(s.vip, {
      host: s.host,
      label: `${s.host} Vlan${s.record.vlan ?? "?"} ${s.record.fhrp ?? "FHRP"} virtual address ${s.record.vip}`,
      cite: s.record.cite,
      kind: "svi",
      fhrpRole: s.fhrpRole,
      fhrp: s.record.fhrp,
    });
  }
  for (const [host, routes] of Object.entries(fabric.routes)) {
    for (const r of routes) {
      if (r.source !== "local") continue;
      const p = parsePrefix(r.prefix);
      if (p === null || p.bits !== 32) continue;
      // A RIB `local` /32 carries no FHRP state of its own; leaving it null keeps "no role observed"
      // distinct from "observed as Standby", which is what the ingress tie-break has to tell apart.
      add(p.base, {
        host,
        label: `${host} local address ${formatIpv4(p.base)} (${r.outIntf ?? "no interface named"})`,
        cite: r.cite,
        kind: "route",
        fhrpRole: null,
        fhrp: null,
      });
    }
  }
  return m;
})();

/** ip -> endpoint records claiming it. This sample fleet reports one address on 17 access switches. */
const ENDPOINTS_BY_IP: ReadonlyMap<number, { host: string; port: string | null; cite: Cite; evidence: string | null }[]> = (() => {
  const m = new Map<number, { host: string; port: string | null; cite: Cite; evidence: string | null }[]>();
  for (const e of fabric.endpoints) {
    if (e.ip === null || e.host === null) continue;
    const ip = parseIpv4(e.ip);
    if (ip === null) continue;
    const list = m.get(ip);
    const rec = { host: e.host, port: e.port, cite: e.cite, evidence: e.evidence };
    if (list) list.push(rec);
    else m.set(ip, [rec]);
  }
  return m;
})();

const ACL_FINDING_BY_CITE: ReadonlyMap<string, AclFinding> = new Map(
  fabric.aclFindings.map((f) => [f.cite, f] as const),
);

const ROUTABLE = fabric.coverage.routableHosts;
const HOST_COUNT = fabric.devices.length;
const UNROUTABLE_COUNT = HOST_COUNT - ROUTABLE.length;

/* ── ACL line evaluability, decided structurally ────────────────────────────── */

/**
 * These two keywords change what a line LOGS, not what it MATCHES, so they do not make a line
 * unevaluable. Everything else left over after the address/port grammar does — including keywords
 * this engine has never seen. That direction matters: a list of known-bad keywords would silently
 * pass the next qualifier someone invents, which is the "named subset standing in for the class"
 * defect this repository keeps finding.
 */
const MATCH_NEUTRAL_KEYWORDS = new Set(["log", "log-input"]);

const PORT_OPS_1 = new Set(["eq", "neq", "lt", "gt"]);
const MODELLED_PORT_OPS = new Set(["eq", "neq", "lt", "gt", "range"]);

/**
 * A port operand this model can actually compare, or null.
 *
 * `AclPortMatch.val` is TYPED `number`, but the type describes the compiler's intent, not the
 * bytes: the upstream producer emits `{"op":"eq","val":null}` for a service name it could not
 * resolve (`eq citrix`), and `tools/compile-snapshot.mjs` copies the port object through verbatim.
 * So the field's PRESENCE is not the presence of a value, and every read of it goes through here.
 * Reading `val` directly is what turned `1494 === null` into a definite non-match and silently
 * denied a flow the configuration text permits.
 */
function portValue(v: unknown): number | null {
  return typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 65535 ? v : null;
}

/**
 * Why a port match cannot be evaluated, or null when every operand it needs is a real port.
 *
 * Checked per OPERAND rather than per known-bad keyword: the failure is "a field the model must
 * compare against holds no comparable value", whatever produced it, and an operator this engine
 * does not model is the same failure one level up.
 */
function portMatchUnresolved(m: AclPortMatch | null): string | null {
  if (m === null) return null;
  const op = m.op.toLowerCase();
  if (!MODELLED_PORT_OPS.has(op)) return `uses operator "${m.op}", which this model does not evaluate`;
  if (portValue(m.val) === null) {
    return `names a port ("${m.op}") the collection did not resolve to a number, so the ports it matches are unknown`;
  }
  if (op === "range" && portValue(m.val2) === null) {
    return `is a range whose upper bound was not resolved to a number, so the ports it matches are unknown`;
  }
  return null;
}

/**
 * The honest description of an unresolvable group reference.
 *
 * It says MODEL, not COLLECTION, and the distinction is the whole point: whether the collector saw
 * a group is a different question from whether we can resolve it, and conflating them tells a user
 * to go and gather evidence they may already have.
 *
 * `tools/compile-snapshot.mjs` now emits `objectGroups`, so most references DO resolve — see
 * `groupTri` below. This string is reserved for the case where the group genuinely is not in the
 * compiled model, and it still refuses to speak for the collector.
 */
const GROUP_NOT_CARRIED =
  "whose member addresses this compiled evidence model does not carry, so its match space cannot be resolved here — that is a limit of this model, and says nothing about whether the group was collected";

/**
 * Which host an ACL line belongs to, read from its own citation (`acls.<host>.<name>[<i>]`).
 *
 * Derived rather than threaded because the alternative is a `host` parameter on `addrTri`,
 * `matchTri`, `lineEvaluability`, `consumeAddress` and every one of their ~20 call sites — a wide
 * change to a module other surfaces are already importing, to carry a value the line can answer
 * for itself. `citeHostIsStable` in the test suite pins the format this depends on.
 */
export function hostOfAclLine(line: AclLine): string | null {
  const m = /^acls\.([^.]+)\./.exec(line.cite);
  return m?.[1] ?? null;
}

/**
 * The group a match field names, or null.
 *
 * Treats `undefined` and `null` identically and on purpose. Our compiled model always emits
 * `group: null`, but the real producer omits the key entirely when there is no group — and the
 * engine is fed producer-shaped objects directly in tests and in any future ingest path. An
 * identity check against `null` alone silently classifies every ordinary address field as "a group
 * field", which turns the drift guard against exactly the lines it is supposed to pass.
 */
function fieldGroup(field: AclMatchField | null): string | null {
  const g = field?.group;
  return typeof g === "string" && g.length > 0 ? g : null;
}

export function resolveObjectGroup(host: string | null, name: string | null): ObjectGroup | null {
  if (host === null || name === null) return null;
  return fabric.objectGroups[host]?.[name] ?? null;
}

/**
 * Does `ip` fall inside an object-group's member space?
 *
 * Tri-state, and the "no" case is deliberately the hardest to reach: it requires that the group
 * resolved, that it has members, and that EVERY member parsed. A single unparseable member makes
 * the answer "maybe", because a group we only partly understand cannot be used to rule a flow out.
 * Ruling something out on incomplete evidence is how a permit silently becomes a deny.
 */
function groupTri(host: string | null, name: string, ip: Ipv4): Tri {
  const g = resolveObjectGroup(host, name);
  if (g === null || g.members.length === 0) return "maybe";
  let allParsed = true;
  for (const m of g.members) {
    if (m.ip === null) {
      allParsed = false;
      continue;
    }
    const base = parseIpv4(m.ip);
    if (base === null) {
      allParsed = false;
      continue;
    }
    // A member with no wildcard is a single host.
    const wild = m.wild === null ? 0 : parseIpv4(m.wild);
    if (wild === null) {
      allParsed = false;
      continue;
    }
    if (wildcardMatches(ip, base, wild)) return "yes";
  }
  return allParsed ? "no" : "maybe";
}

type Consume = { ok: true; next: number; sawPortOp?: boolean; text?: string } | { ok: false; reason: string };

function consumeAddress(toks: readonly string[], i: number, host?: string | null): Consume {
  const t = toks[i];
  if (t === undefined) return { ok: false, reason: "address specification is missing from the configuration text" };
  const low = t.toLowerCase();
  if (low === "any") return { ok: true, next: i + 1, text: "any" };
  if (low === "host") {
    const ip = toks[i + 1];
    if (ip === undefined || parseIpv4(ip) === null) return { ok: false, reason: `"host" is not followed by an address` };
    return { ok: true, next: i + 2, text: `host ${ip}` };
  }
  if (low === "object-group" || low === "addrgroup" || low === "group-object") {
    const name = toks[i + 1];
    const g = resolveObjectGroup(host ?? null, name ?? null);
    /* A group we can resolve is a normal address space and the line is evaluable. A group with no
       members is NOT: an empty match space would silently match nothing, turning a permit into a
       no-op, which is the same false-deny this guard exists to prevent. */
    if (g !== null && g.members.length > 0) {
      return { ok: true, next: i + 2, text: `${low} ${name}` };
    }
    return { ok: false, reason: `references ${low} ${name ?? "(unnamed)"}, ${GROUP_NOT_CARRIED}` };
  }
  const next = toks[i + 1];
  if (parseIpv4(t) !== null && next !== undefined && parseIpv4(next) !== null) {
    return { ok: true, next: i + 2, text: `${t} ${next}` };
  }
  if (parsePrefix(t) !== null) return { ok: true, next: i + 1, text: t };
  return { ok: false, reason: `address specification "${t}" could not be read from the configuration text` };
}

function consumePortOp(toks: readonly string[], i: number): Consume {
  const t = toks[i];
  if (t === undefined) return { ok: true, next: i, sawPortOp: false };
  const low = t.toLowerCase();
  if (low === "object-group" || low === "portgroup") {
    return { ok: false, reason: `port match uses ${low} ${toks[i + 1] ?? "(unnamed)"}, ${GROUP_NOT_CARRIED}` };
  }
  if (PORT_OPS_1.has(low)) {
    const port = toks[i + 1];
    if (port === undefined) return { ok: false, reason: `"${low}" is not followed by a port` };
    // IOS allows a port LIST here (`eq 80 443`), and the producer keeps only the first port. This
    // model matches one port per operator, so consuming the extras would hide them from the
    // residual guard below and evaluate a configuration permitting two ports as permitting one.
    // A token this engine's MATCHER cannot represent is refused where it is read, not swallowed.
    const extra: string[] = [];
    let n = i + 2;
    while (toks[n] !== undefined && /^\d+$/.test(toks[n]!)) {
      extra.push(toks[n]!);
      n += 1;
    }
    if (extra.length > 0) {
      return {
        ok: false,
        reason: `port list "${low} ${port} ${extra.join(" ")}" names ${extra.length + 1} ports and this model matches one port per operator`,
      };
    }
    return { ok: true, next: i + 2, sawPortOp: true };
  }
  if (low === "range") {
    if (toks[i + 1] === undefined || toks[i + 2] === undefined) return { ok: false, reason: `"range" is not followed by two ports` };
    return { ok: true, next: i + 3, sawPortOp: true };
  }
  return { ok: true, next: i, sawPortOp: false };
}

/** Does the parsed field say the same thing the configuration text says? */
function fieldAgrees(field: AclMatchField | null, text: string | undefined): boolean {
  if (text === undefined) return true;
  if (text === "any") return field === null || (field.ip === "0.0.0.0" && field.wild === "255.255.255.255");
  /* An object-group field carries a NAME where an address pair would sit, so it has to be compared
     against the text by name. Without this the drift guard rejects a correctly-parsed group field
     for "not representing the configuration text" — the guard firing on the one case it should
     pass, which would keep every group-referencing line permanently unevaluable even once the
     group resolves. */
  const groupText = /^(?:object-group|addrgroup|group-object) (\S+)$/i.exec(text);
  if (groupText) return field !== null && fieldGroup(field) === groupText[1];
  if (fieldGroup(field) !== null) return false; // a group field cannot represent a literal address
  if (field === null || field.ip === null) return false;
  const host = /^host (\S+)$/.exec(text);
  if (host) return field.ip === host[1] && (field.wild === null || field.wild === "0.0.0.0");
  const pair = /^(\S+) (\S+)$/.exec(text);
  if (pair) return field.ip === pair[1] && field.wild === pair[2];
  const p = parsePrefix(text);
  if (p !== null) return parseIpv4(field.ip) !== null && formatPrefix({ base: parseIpv4(field.ip)!, bits: p.bits }) === formatPrefix(p);
  return false;
}

/**
 * Can this ACL line be evaluated against a flow AT ALL?
 *
 * The check is structural: re-read the raw configuration text with the grammar this engine models
 * and refuse the line if anything is left over, if an address or port group cannot be resolved, or
 * if the parsed fields disagree with the text. The last case is the parser/detector drift guard —
 * a line whose text carries `eq www` but whose parsed port is null would otherwise be matched as
 * "no port constraint", i.e. far wider than the configuration says.
 */
const EVALUABILITY_CACHE = new WeakMap<AclLine, LineEvaluability>();

/** Memoised: the matcher now consults this per dimension per line, and re-reading the text is pure. */
export function lineEvaluability(line: AclLine): LineEvaluability {
  const hit = EVALUABILITY_CACHE.get(line);
  if (hit !== undefined) return hit;
  const computed = computeEvaluability(line);
  EVALUABILITY_CACHE.set(line, computed);
  return computed;
}

function computeEvaluability(line: AclLine): LineEvaluability {
  const snapshotDetail = ACL_FINDING_BY_CITE.get(line.cite)?.detail ?? null;
  const representative: FieldRepresentation = { proto: false, src: false, dst: false, sport: false, dport: false };
  const fail = (reason: string): LineEvaluability => ({ evaluable: false, reason, snapshotDetail, representative });

  if (line.action === null) return fail("no action was parsed from this line");
  if (line.raw === null) return fail("the configuration text for this line was not collected");

  const toks = line.raw.trim().split(/\s+/);
  if (toks.length < 3) return fail(`configuration text "${line.raw}" is too short to be an access-list entry`);
  if (line.proto === null) return fail("no protocol was parsed from this line");
  representative.proto = true;

  // Each dimension is marked representative the moment the text it stands for has been read and
  // agrees with it — not at the end. A refusal below therefore leaves every later dimension false,
  // and the matcher treats an unvouched dimension as "unknown" rather than as a usable value.
  let i = 2; // action, protocol
  const src = consumeAddress(toks, i, hostOfAclLine(line));
  if (!src.ok) return fail(src.reason);
  i = src.next;
  representative.src = fieldAgrees(line.src, src.text);

  const sport = consumePortOp(toks, i);
  if (!sport.ok) return fail(sport.reason);
  i = sport.next;
  representative.sport = portFieldAgrees(line.sport, Boolean(sport.sawPortOp));

  const dst = consumeAddress(toks, i, hostOfAclLine(line));
  if (!dst.ok) return fail(dst.reason);
  i = dst.next;
  representative.dst = fieldAgrees(line.dst, dst.text);

  const dport = consumePortOp(toks, i);
  if (!dport.ok) return fail(dport.reason);
  i = dport.next;
  representative.dport = portFieldAgrees(line.dport, Boolean(dport.sawPortOp));

  const residual = toks.slice(i).filter((t) => !MATCH_NEUTRAL_KEYWORDS.has(t.toLowerCase()));
  if (residual.length > 0) {
    return fail(`carries match qualifier(s) this model cannot evaluate: ${residual.join(" ")}`);
  }
  if (!representative.sport || !representative.dport) {
    // Presence of a port field is not a port: the producer emits `{"op":"eq","val":null}` for a
    // service name it could not resolve, and a presence-only check passes it straight through.
    const bad = portMatchUnresolved(representative.sport ? line.dport : line.sport);
    return fail(
      bad === null
        ? "the parsed port fields do not represent the configuration text, so the line cannot be matched safely"
        : `its ${representative.sport ? "destination" : "source"}-port match ${bad}`,
    );
  }
  if (!representative.src || !representative.dst) {
    return fail("the parsed address fields do not represent the configuration text, so the line cannot be matched safely");
  }
  return { evaluable: true, reason: null, snapshotDetail, representative };
}

/** A port field represents its text when its presence matches AND every operand it needs is real. */
function portFieldAgrees(field: AclPortMatch | null, sawPortOp: boolean): boolean {
  if (sawPortOp !== (field !== null)) return false;
  return portMatchUnresolved(field) === null;
}

/* ── matching a flow against a line ─────────────────────────────────────────── */

function protoTri(lineProto: string | null, flowProto: Flow["protocol"]): Tri {
  if (lineProto === null) return "maybe";
  const p = lineProto.toLowerCase();
  if (p === "ip") return "yes";
  if (flowProto === "ip") return "maybe"; // the question spans protocols this line separates
  return p === flowProto ? "yes" : "no";
}

function addrTri(field: AclMatchField | null, ip: Ipv4, host?: string | null): Tri {
  // An object-group reference resolves against the compiled group table when we carry it.
  const grp = fieldGroup(field);
  if (grp !== null) return groupTri(host ?? null, grp, ip);
  if (field === null || field.ip === null) return "maybe"; // unresolved group: unknown, never "no"
  const base = parseIpv4(field.ip);
  if (base === null) return "maybe";
  const wild = field.wild === null ? 0 : parseIpv4(field.wild);
  if (wild === null) return "maybe";
  return wildcardMatches(ip, base, wild) ? "yes" : "no";
}

function portTri(match: AclPortMatch | null, port: number | null): Tri {
  if (match === null) return "yes"; // no port constraint on this line
  // An operand we cannot read excludes nothing. This is the second half of the same guard as
  // `portMatchUnresolved` in lineEvaluability: even if a caller reaches the matcher without
  // consulting evaluability, an unresolved field can only ever produce "maybe" here.
  if (portMatchUnresolved(match) !== null) return "maybe";
  if (port === null) return "maybe"; // the flow does not name a port; the line does
  const val = portValue(match.val);
  if (val === null) return "maybe";
  switch (match.op.toLowerCase()) {
    case "eq":
      return port === val ? "yes" : "no";
    case "neq":
      return port !== val ? "yes" : "no";
    case "lt":
      return port < val ? "yes" : "no";
    case "gt":
      return port > val ? "yes" : "no";
    case "range": {
      const upper = portValue(match.val2);
      if (upper === null) return "maybe";
      return port >= val && port <= upper ? "yes" : "no";
    }
    default:
      return "maybe"; // an operator we do not model is not a non-match
  }
}

function andTri(parts: readonly Tri[]): Tri {
  if (parts.includes("no")) return "no";
  return parts.includes("maybe") ? "maybe" : "yes";
}

/**
 * Why a line definitely cannot match — the reason an unevaluable line above our match can be set
 * aside. Without this, every flow under `permit icmp … echo-reply` would be indeterminate, which is
 * over-claiming in the other direction: an icmp ACE genuinely cannot match a tcp packet.
 */
function excludedBecause(line: AclLine, flow: Flow, srcIp: Ipv4, dstIp: Ipv4): string | null {
  // Only a vouched dimension can exclude: setting a line aside is a definite claim about it.
  const rep = lineEvaluability(line).representative;
  if (rep.proto && protoTri(line.proto, flow.protocol) === "no") {
    return `its protocol (${line.proto}) cannot match a ${flow.protocol} flow`;
  }
  if (rep.src && addrTri(line.src, srcIp, hostOfAclLine(line)) === "no") return `its source space ${line.src?.ip} ${line.src?.wild} does not contain ${flow.srcIp}`;
  if (rep.dst && addrTri(line.dst, dstIp, hostOfAclLine(line)) === "no") return `its destination space ${line.dst?.ip} ${line.dst?.wild} does not contain ${flow.dstIp}`;
  if (rep.dport && line.dport !== null && portTri(line.dport, flow.dstPort) === "no") {
    return `its destination-port test (${line.dport.op} ${line.dport.val}${line.dport.val2 === undefined ? "" : ` ${line.dport.val2}`}) excludes port ${flow.dstPort}`;
  }
  if (rep.sport && line.sport !== null && portTri(line.sport, flow.srcPort) === "no") {
    return `its source-port test (${line.sport.op} ${line.sport.val}) excludes port ${flow.srcPort}`;
  }
  return null;
}

/**
 * Can this line match this flow? Exported because "no" is the strongest word the matcher has: it is
 * what lets an unevaluable line above a verdict be set aside, so a wrong "no" converts an unknown
 * into a definite answer with no caveat. That makes it worth testing directly against producer
 * output rather than only through a trace.
 */
export function matchTri(line: AclLine, flow: Flow, srcIp: Ipv4, dstIp: Ipv4): Tri {
  const rep = lineEvaluability(line).representative;
  const portsApply = line.proto !== null && ["tcp", "udp"].includes(line.proto.toLowerCase());
  // A dimension the text check did not vouch for contributes "unknown", never a verdict. This is
  // the structural form of the guard: it holds for any field the reader stopped short of, not for
  // a list of the particular constructs we have so far seen break it.
  const dim = (vouched: boolean, t: Tri): Tri => (vouched ? t : "maybe");
  return andTri([
    dim(rep.proto, protoTri(line.proto, flow.protocol)),
    dim(rep.src, addrTri(line.src, srcIp, hostOfAclLine(line))),
    dim(rep.dst, addrTri(line.dst, dstIp, hostOfAclLine(line))),
    portsApply ? dim(rep.sport, portTri(line.sport, flow.srcPort)) : "yes",
    portsApply ? dim(rep.dport, portTri(line.dport, flow.dstPort)) : "yes",
  ]);
}

/**
 * Is this address field literally `any` — present, readable, and matching everything?
 *
 * `null` (the field was not written at all) is `any` by Cisco grammar. A field carrying an
 * object-group, or an address the producer could not resolve, is NOT `any`: it is unknown, and the
 * two must never be reported with the same word.
 */
function isAnyAddress(f: AclMatchField | null): boolean {
  if (f === null) return true;
  if (fieldGroup(f) !== null) return false;
  if (f.ip === null) return false;
  const wild = f.wild === null ? null : parseIpv4(f.wild);
  return wild === 0xffffffff;
}

function hasUnresolvedAddressing(line: AclLine): boolean {
  const unresolved = (f: AclMatchField | null): boolean => f !== null && f.ip === null;
  return unresolved(line.src) || unresolved(line.dst);
}

function isCatchAllAddressing(line: AclLine): boolean {
  return isAnyAddress(line.src) && isAnyAddress(line.dst);
}

/** How tightly a line names THIS flow's address space. `any`/`any` scores 0 and never selects an ACL. */
function lineSpecificity(line: AclLine): number {
  const spec = (f: AclMatchField | null): number => {
    if (f === null || f.ip === null) return 0;
    const wild = f.wild === null ? 0 : parseIpv4(f.wild);
    return wild === null ? 0 : wildcardSpecificity(wild);
  };
  return spec(line.src) + spec(line.dst);
}

/* ── evaluating the ACLs that apply at a hop ────────────────────────────────── */

export interface AclEval {
  verdict: "permit" | "deny" | "indeterminate" | "not-applicable";
  decidedBy: HopEvidence | null;
  evidence: HopEvidence[];
  caveats: string[];
  /** Structured facts about the deciding line, so prose is composed rather than re-parsed. */
  decision: { aclName: string; lineIndex: number | null; raw: string | null } | null;
}

function aclEvidence(host: string, name: string, line: AclLine, note: string): HopEvidence {
  return {
    kind: "acl",
    label: `${host} ACL ${name} line ${line.index} ${note}`,
    raw: line.raw,
    cite: line.cite,
  };
}

/**
 * Which ACLs apply here?
 *
 * No `ip access-group` binding exists anywhere in this snapshot, so the honest answer is "unknown".
 * Rather than pretend every defined ACL filters every flow (which would deny nearly everything on
 * the strength of an unbound MGMT_IN), or that none do (which would hide the real filters), this
 * selects the ACL whose own match space names this flow most specifically, and every trace carries
 * a caveat saying the binding was never observed. The rule is deterministic and stated out loud;
 * it is not evidence that the ACL is applied on the path.
 */
function selectAcls(named: Record<string, AclLine[]>, srcIp: Ipv4, dstIp: Ipv4): string[] {
  let best = 0;
  const scores = new Map<string, number>();
  for (const name of Object.keys(named).sort()) {
    const lines = named[name] ?? [];
    let score = 0;
    for (const line of lines) {
      // Relevance is an ADDRESS question, not a protocol/port one. A list whose specific lines name
      // this flow's subnets is about this flow even when the line that ultimately fires is its
      // catch-all deny — which is precisely the interesting case.
      if (addrTri(line.src, srcIp, hostOfAclLine(line)) === "no" || addrTri(line.dst, dstIp, hostOfAclLine(line)) === "no") continue;
      score = Math.max(score, lineSpecificity(line));
    }
    scores.set(name, score);
    best = Math.max(best, score);
  }
  if (best === 0) return [];
  return [...scores.entries()].filter(([, s]) => s === best).map(([n]) => n);
}

/**
 * The lines of a NOT-APPLIED ACL that could match this flow and cannot be decided.
 *
 * This is the undecidability that used to be invisible. `scopeTuple()` counts indeterminate
 * evidence over `hop.evidence`, and evidence is only ever emitted for the ACL the specificity
 * contest SELECTED — so a line that could fire, in a list we chose not to apply, on a snapshot
 * that collected no `ip access-group` binding at all, could not lower the badge. The product then
 * rendered SCOPED and "0 evidence items were indeterminate" for a flow whose own coverage panel
 * lists, by cite, the lines it stepped over.
 *
 * Selection is a heuristic; it is NOT evidence that the discarded list is inert. So an unevaluable
 * line in a discarded list is exactly the same kind of fact as one in the applied list — an
 * undecided input — and it is emitted as such.
 */
function undecidableInUnappliedAcls(
  host: string,
  named: Record<string, AclLine[]>,
  applied: readonly string[],
  flow: Flow,
  srcIp: Ipv4,
  dstIp: Ipv4,
): HopEvidence[] {
  const out: HopEvidence[] = [];
  for (const name of Object.keys(named).sort()) {
    if (applied.includes(name)) continue;
    for (const line of named[name] ?? []) {
      if (matchTri(line, flow, srcIp, dstIp) === "no") continue;
      const ev = lineEvaluability(line);
      if (ev.evaluable) continue;
      out.push({
        kind: "absence",
        label:
          `${host} ACL ${name} line ${line.index} could match this flow and cannot be evaluated ` +
          `(${ev.reason ?? "no reason recorded"}); the list was not applied by the specificity rule, ` +
          `and with no collected access-group binding that is not evidence it does not filter this flow`,
        raw: line.raw,
        cite: line.cite,
      });
    }
  }
  return out;
}

/**
 * Every ACL on this host that was NOT applied, and why. This is the other half of the selection
 * rule: with no collected binding, an ACL we did not apply is an ACL whose effect is UNKNOWN, not
 * one that is known to let the flow through. MGMT_IN is the live example — its only selective line
 * references an object-group whose members were never collected, so it can never score.
 */
function notAppliedCaveat(host: string, named: Record<string, AclLine[]>, applied: readonly string[], srcIp: Ipv4, dstIp: Ipv4): string | null {
  const rest = Object.keys(named)
    .sort()
    .filter((n) => !applied.includes(n));
  if (rest.length === 0) return null;

  // Two different absences, previously reported as one. An ACL that LOST the specificity contest
  // was weighed against this flow; an ACL whose address space this model cannot resolve was never
  // in the contest at all, for any flow ever — and saying it "was not applied because another list
  // names these addresses more specifically" describes a comparison that never happened.
  const unscoreable: string[] = [];
  const outscored: string[] = [];
  for (const name of rest) {
    const lines = named[name] ?? [];
    const unresolved = lines.find((l) => !lineEvaluability(l).evaluable && (l.src?.ip === null || l.dst?.ip === null));
    if (unresolved !== undefined) {
      unscoreable.push(`${name} (${unresolved.cite}: ${lineEvaluability(unresolved).reason ?? "cannot be evaluated"})`);
      continue;
    }
    /* MEASURE the claim, never assert it.
     *
     * This used to read "matches this flow only through catch-all lines" for EVERY overlap, with
     * no catch-all test anywhere in the function. On the headline flow that sentence dismissed
     * INET_RETURN — whose line 1 is `permit tcp 10.0.10.0 0.0.0.255 any eq 443 time-range
     * BUSINESS_HOURS`, a /24-specific source naming that flow's own subnet with an exact protocol
     * and port — as irrelevant boilerplate. It is the single most relevant line on the host, and
     * it cannot be evaluated. So the parenthetical is now derived from the matching lines. */
    const matching = lines.filter(
      (l) => addrTri(l.src, srcIp, hostOfAclLine(l)) !== "no" && addrTri(l.dst, dstIp, hostOfAclLine(l)) !== "no",
    );
    if (matching.length === 0) {
      outscored.push(`${name} (names other address space)`);
      continue;
    }
    // The most specific line this flow can reach in the discarded list, undecidable ones first:
    // an undecidable line is the one a reader most needs named, because it is the reason a verdict
    // that steps over this list cannot be definite.
    const ranked = [...matching].sort((a, b) => {
      const ua = lineEvaluability(a).evaluable ? 0 : 1;
      const ub = lineEvaluability(b).evaluable ? 0 : 1;
      return ub - ua || lineSpecificity(b) - lineSpecificity(a);
    });
    const top = ranked[0]!;
    const topEval = lineEvaluability(top);
    /* "catch-all" has to MEAN catch-all: both address fields present and explicitly wide. A field
       naming an object-group whose members were never collected is neither specific nor a
       catch-all — it is unresolved — and calling it a catch-all is the same overclaim in a
       smaller place. */
    const everyMatchIsCatchAll = matching.every((l) => isCatchAllAddressing(l));
    const unresolvedMatch = matching.find((l) => hasUnresolvedAddressing(l));
    if (!topEval.evaluable) {
      outscored.push(`${name} (matches this flow at ${top.cite}, which cannot be evaluated: ${topEval.reason ?? "no reason recorded"})`);
    } else if (everyMatchIsCatchAll) {
      outscored.push(`${name} (matches this flow only through catch-all lines)`);
    } else if (unresolvedMatch !== undefined) {
      outscored.push(`${name} (matches this flow at ${unresolvedMatch.cite}, whose address space could not be resolved in this snapshot)`);
    } else {
      outscored.push(`${name} (matches this flow at ${top.cite}, which names its addresses specifically)`);
    }
  }

  const parts: string[] = [];
  if (outscored.length > 0) {
    parts.push(
      `${host} also defines ${outscored.join(", ")}; ${outscored.length === 1 ? "it was" : "they were"} not applied to this flow because ${applied.length === 0 ? "no ACL on this host names its addresses specifically" : `${applied.join(", ")} names its addresses more specifically`}.`,
    );
  }
  if (unscoreable.length > 0) {
    parts.push(
      `${host} also defines ${unscoreable.join(", ")}; because that address space cannot be resolved in this model, ${unscoreable.length === 1 ? "the list scores nothing and is" : "those lists score nothing and are"} excluded from selection for EVERY flow, not only this one — ${unscoreable.length === 1 ? "its" : "their"} catch-all deny can therefore never fire here, which is a property of this model rather than of the device.`,
    );
  }
  parts.push(
    `With no collected access-group binding, that is not evidence ${rest.length === 1 ? "it does" : "they do"} not filter this flow.`,
  );
  return parts.join(" ");
}

/**
 * `named` is a parameter so the ACL half of the engine can be driven with a REAL ACL set that is
 * not core1's — the only host in this snapshot that has one. Producer output for a construct this
 * fabric happens not to contain (`eq citrix`, `eq 443 8443`) is still real producer output, and
 * this is the seam that lets it reach the same code path a trace uses.
 */
export function evaluateAcls(host: string, flow: Flow, srcIp: Ipv4, dstIp: Ipv4, named: Record<string, AclLine[]> = aclsOf(host)): AclEval {
  const names = selectAcls(named, srcIp, dstIp);
  /* Undecidability is a property of the DECIDING HOST, not of the list the heuristic happened to
     pick. Computed for both branches below and appended to `evidence` LAST, so it lowers the
     badge without ever becoming the thing a verdict says it was decided by. */
  const unappliedUndecidable = undecidableInUnappliedAcls(host, named, names, flow, srcIp, dstIp);
  if (names.length === 0) {
    const only = notAppliedCaveat(host, named, [], srcIp, dstIp);
    return {
      verdict: "not-applicable",
      decidedBy: null,
      evidence: unappliedUndecidable,
      caveats: only === null ? [] : [only],
      decision: null,
    };
  }
  const evidence: HopEvidence[] = [];
  const caveats: string[] = [];
  const unapplied = notAppliedCaveat(host, named, names, srcIp, dstIp);
  if (unapplied !== null) caveats.push(unapplied);
  let denial: HopEvidence | null = null;
  let indeterminate: HopEvidence | null = null;
  let denialDecision: AclEval["decision"] = null;
  let indeterminateDecision: AclEval["decision"] = null;

  for (const name of names) {
    const lines = named[name] ?? [];
    let poisonedBy: { line: AclLine; why: string } | null = null;
    let decided = false;
    const setAside: string[] = [];

    for (const line of lines) {
      const tri = matchTri(line, flow, srcIp, dstIp);
      if (tri === "no") {
        // The fields we CAN read exclude this flow, qualifier or not. Record it when the line was
        // otherwise unevaluable, because that is the assumption the verdict below rests on.
        if (!lineEvaluability(line).evaluable) {
          const why = excludedBecause(line, flow, srcIp, dstIp);
          if (why !== null) setAside.push(`${line.cite} ("${line.raw ?? "text not collected"}") was set aside because ${why}`);
        }
        continue;
      }
      const ev = lineEvaluability(line);
      if (!ev.evaluable) {
        // It could match and we cannot tell: everything below it is now unprovable.
        poisonedBy ??= { line, why: ev.snapshotDetail ?? ev.reason ?? "cannot be evaluated" };
        continue;
      }
      if (tri === "maybe") {
        poisonedBy ??= { line, why: "the flow does not specify a field this line matches on" };
        continue;
      }
      // tri === "yes" and the line is evaluable.
      if (poisonedBy === null) {
        const action = (line.action ?? "").toLowerCase();
        const ev2 = aclEvidence(host, name, line, action === "deny" ? "denies this flow" : "permits this flow");
        evidence.push(ev2);
        if (action === "deny" && denial === null) {
          denial = ev2;
          denialDecision = { aclName: name, lineIndex: line.index, raw: line.raw };
        }
        decided = true;
        const snapshotVerdict = ACL_FINDING_BY_CITE.get(line.cite);
        if (snapshotVerdict !== undefined || setAside.length > 0) {
          caveats.push(
            `${host} ACL ${name} line ${line.index} (${line.cite}) decides this flow` +
              (snapshotVerdict === undefined
                ? ""
                : `, and the snapshot's own acl_line_reachability marks that line ${String(snapshotVerdict.verdict).toUpperCase()} in general (${snapshotVerdict.detail ?? "no detail recorded"})`) +
              (setAside.length === 0
                ? ". That verdict is about the line across all flows; for this flow no unevaluable line above it can match."
                : `. For this flow ${setAside.join("; ")}, so the line above it cannot fire here — which is a claim about this flow only, not about the line in general.`),
          );
        }
      } else {
        evidence.push(aclEvidence(host, name, line, "would match, but an earlier unevaluable line may fire first"));
        decided = true;
      }
      break;
    }

    if (poisonedBy !== null) {
      const ev2 = aclEvidence(host, name, poisonedBy.line, `cannot be evaluated — ${poisonedBy.why}`);
      evidence.push(ev2);
      if (indeterminate === null) {
        indeterminate = ev2;
        indeterminateDecision = { aclName: name, lineIndex: poisonedBy.line.index, raw: poisonedBy.line.raw };
      }
      caveats.push(
        `${host} ACL ${name} line ${poisonedBy.line.index} (${poisonedBy.line.cite}) "${poisonedBy.line.raw ?? "text not collected"}" could match this flow but ${poisonedBy.why}; no verdict below it can be proven.`,
      );
      continue;
    }
    if (!decided) {
      // Fell off the end of the list: Cisco's implicit deny. That is a real deny, and it is cited
      // as an ABSENCE of a permitting line rather than as a line that exists.
      const ev2: HopEvidence = {
        kind: "absence",
        label: `${host} ACL ${name}: no line matches, implicit deny at end of list`,
        raw: null,
        cite: `acls.${host}.${name}`,
      };
      evidence.push(ev2);
      if (denial === null) {
        denial = ev2;
        denialDecision = { aclName: name, lineIndex: null, raw: null };
      }
    }
  }

  /* Appended after every applied-ACL item so `evidence[0]` still names the line that DECIDED the
     flow. These items change the badge, not the verdict. */
  if (unappliedUndecidable.length > 0) {
    evidence.push(...unappliedUndecidable);
    const n = unappliedUndecidable.length;
    caveats.push(
      `${host} holds ${n} ${n === 1 ? "line" : "lines"} in access lists the specificity rule did not apply which could ` +
        `match this flow and cannot be evaluated (${unappliedUndecidable.map((e) => e.cite).join(", ")}). ` +
        `No access-group binding was collected, so a verdict here steps over ${n === 1 ? "it" : "them"}: ` +
        `it is at best indeterminate, never a definite permit.`,
    );
  }

  if (denial !== null) return { verdict: "deny", decidedBy: denial, evidence, caveats, decision: denialDecision };
  if (indeterminate !== null) {
    return { verdict: "indeterminate", decidedBy: indeterminate, evidence, caveats, decision: indeterminateDecision };
  }
  const decidedByPermit = evidence.find((e) => e.kind === "acl") ?? null;
  return { verdict: "permit", decidedBy: decidedByPermit, evidence, caveats, decision: null };
}

/* ── ingress resolution ─────────────────────────────────────────────────────── */

interface Ingress {
  host: string;
  evidence: HopEvidence[];
  caveats: string[];
}

function attachmentEvidence(ip: Ipv4): { evidence: HopEvidence[]; caveats: string[] } {
  const eps = ENDPOINTS_BY_IP.get(ip);
  if (eps === undefined || eps.length === 0) return { evidence: [], caveats: [] };
  const sorted = [...eps].sort((a, b) => a.host.localeCompare(b.host) || (a.port ?? "").localeCompare(b.port ?? ""));
  const first = sorted[0]!;
  const evidence: HopEvidence[] = [
    {
      kind: "topology",
      label: `${formatIpv4(ip)} observed on ${first.host} ${first.port ?? "(no port)"}${sorted.length > 1 ? ` and ${sorted.length - 1} other host(s)` : ""}`,
      raw: first.evidence,
      cite: first.cite,
    },
  ];
  const caveats = [
    sorted.length > 1
      ? `${formatIpv4(ip)} is reported as an endpoint on ${sorted.length} hosts (${sorted.map((s) => s.host).join(", ")}); the attachment point is ambiguous in the collected evidence, and the L2 path from it to the gateway is not simulated.`
      : `${formatIpv4(ip)} attaches at ${first.host} ${first.port ?? "(no port)"} (${first.cite}); the L2 path from that port to the gateway is not simulated.`,
  ];
  return { evidence, caveats };
}

interface ObservedSubnet {
  prefix: Prefix;
  cite: Cite;
  label: string;
}

/**
 * The narrowest subnet in the collected evidence that contains an address, or null.
 *
 * Exists so the network/broadcast rule can be applied to addresses the USER supplies, not only to
 * the ones this module generates. `hostAddressIn` has always refused to emit 10.0.30.0 or
 * 10.0.30.255; without this, the same module accepted both as flow endpoints and answered
 * "delivered" for them, which is the knowledge being held on one path and missing on the other.
 */
function narrowestObservedSubnet(ip: Ipv4): ObservedSubnet | null {
  let best: ObservedSubnet | null = null;
  const consider = (prefix: Prefix, cite: Cite, label: string): void => {
    if (!prefixContains(prefix, ip)) return;
    if (best === null || prefix.bits > best.prefix.bits) best = { prefix, cite, label };
  };
  for (const s of SVI_SUBNETS) consider(s.prefix, s.record.cite, `${s.host} Vlan${s.record.vlan ?? "?"}`);
  for (const host of ROUTABLE) {
    for (const r of routesOf(host)) {
      if (r.source !== "connected") continue;
      const p = parsePrefix(r.prefix);
      if (p !== null) consider(p, r.cite, `${host}'s connected ${r.prefix}`);
    }
  }
  return best;
}

function resolveIngress(ip: Ipv4): Ingress | { none: string } {
  const attach = attachmentEvidence(ip);

  // 1. The address IS a collected device address: the flow originates on that device.
  //    An FHRP VIRTUAL address is owned by every member of the group, so this branch has exactly
  //    the ambiguity the SVI branch below discloses, and it is resolved the same way: the observed
  //    active member first. Sorting by host NAME instead put the Standby ahead of the Active for
  //    VLAN 20 purely because "core1" < "core2", and since only core1 holds a route to 10.0.30.0/24
  //    the same forwarding question then answered "denied" for the gateway address and "dropped"
  //    for a host in the same subnet, with nothing said about the other candidate.
  const owners = ADDRESS_OWNERS.get(ip);
  if (owners !== undefined && owners.length > 0) {
    const sorted = [...owners].sort(
      (a, b) =>
        Number(isActive(b.fhrpRole)) - Number(isActive(a.fhrpRole)) ||
        Number(hasRib(b.host)) - Number(hasRib(a.host)) ||
        a.host.localeCompare(b.host),
    );
    const chosen = sorted[0]!;
    const others = distinctHosts(sorted).filter((h) => h !== chosen.host);
    const caveats = [...attach.caveats];
    if (others.length > 0) {
      const describe = (h: string): string => {
        const o = sorted.find((s) => s.host === h)!;
        return `${h} (${o.fhrpRole === null ? "no FHRP role observed" : `${o.fhrp ?? "FHRP"} ${o.fhrpRole}`})`;
      };
      caveats.push(
        `${formatIpv4(ip)} is an address of ${others.length + 1} collected hosts (${[chosen.host, ...others].join(", ")}) — an FHRP group shares its virtual address. ${chosen.host} was taken as ingress because ${chosen.cite} records it as ${chosen.fhrpRole === null ? "the first candidate holding a collected RIB" : `${chosen.fhrp ?? "FHRP"} ${chosen.fhrpRole}`}; that is a point-in-time observation, and the flow may instead enter via ${others.map(describe).join(", ")}, whose forwarding may differ.`,
      );
    }
    return {
      host: chosen.host,
      evidence: [{ kind: chosen.kind, label: `source address is ${chosen.label}`, raw: null, cite: chosen.cite }, ...attach.evidence],
      caveats,
    };
  }

  // 2. An SVI subnet contains it: the first L3 hop is that subnet's gateway.
  const inSubnet = SVI_SUBNETS.filter((s) => prefixContains(s.prefix, ip));
  if (inSubnet.length > 0) {
    const sorted = [...inSubnet].sort(
      (a, b) =>
        Number(isActive(b.fhrpRole)) - Number(isActive(a.fhrpRole)) ||
        Number(hasRib(b.host)) - Number(hasRib(a.host)) ||
        a.host.localeCompare(b.host),
    );
    const chosen = sorted[0]!;
    const caveats = [...attach.caveats];
    if (sorted.length > 1) {
      const others = sorted.slice(1).map((s) => `${s.host} (${s.record.fhrpRole ?? "no FHRP role observed"})`).join(", ");
      caveats.push(
        isActive(chosen.fhrpRole)
          ? `${formatIpv4(ip)} sits in ${formatPrefix(chosen.prefix)}, gatewayed by ${sorted.length} collected SVIs; ${chosen.host} was taken as ingress because ${chosen.record.cite} records it as ${chosen.record.fhrp ?? "FHRP"} ${chosen.fhrpRole}. That role is a point-in-time observation, not a guarantee — traffic may enter via ${others}.`
          : `${formatIpv4(ip)} sits in ${formatPrefix(chosen.prefix)}, gatewayed by ${sorted.length} collected SVIs and no active FHRP role was observed; ${chosen.host} was taken as ingress by deterministic ordering. Traffic may enter via ${others}.`,
      );
    }
    return {
      host: chosen.host,
      evidence: [
        {
          kind: "svi",
          label: `${chosen.host} Vlan${chosen.record.vlan ?? "?"} ${formatPrefix(chosen.prefix)} contains ${formatIpv4(ip)}${chosen.fhrpRole ? ` (${chosen.record.fhrp ?? "FHRP"} ${chosen.fhrpRole})` : ""}`,
          raw: chosen.record.sviIp,
          cite: chosen.record.cite,
        },
        ...attach.evidence,
      ],
      caveats,
    };
  }

  // 3. A connected route in some collected RIB covers it.
  for (const host of ROUTABLE) {
    for (const r of routesOf(host)) {
      if (r.source !== "connected") continue;
      const p = parsePrefix(r.prefix);
      if (p === null || !prefixContains(p, ip)) continue;
      return {
        host,
        evidence: [
          { kind: "route", label: `${host} has ${r.prefix} connected via ${r.outIntf ?? "an unnamed interface"}`, raw: null, cite: r.cite },
          ...attach.evidence,
        ],
        caveats: attach.caveats,
      };
    }
  }

  // 4. Only an endpoint record places it — the attachment switch is the ingress, and we almost
  //    certainly hold no RIB for it, which the hop loop will report as unmodeled.
  const eps = ENDPOINTS_BY_IP.get(ip);
  if (eps !== undefined && eps.length > 0) {
    const chosen = [...eps].sort((a, b) => a.host.localeCompare(b.host))[0]!;
    return { host: chosen.host, evidence: attach.evidence, caveats: attach.caveats };
  }

  return {
    none: `${formatIpv4(ip)} lies in no subnet this collection observed — no SVI, connected route or endpoint record contains it`,
  };
}

const isActive = (role: string | null): boolean => role !== null && role.toLowerCase() === "active";

/**
 * The distinct hosts behind a list of owner records, in list order.
 *
 * One host can own the same address twice — core1's Vlan10 address is also a `local` /32 in its
 * RIB — so counting RECORDS to decide whether ownership is ambiguous reports "2 hosts (core1,
 * core1)". Ambiguity is a question about hosts, so it is counted over hosts.
 */
function distinctHosts(owners: readonly OwnedAddress[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const o of owners) {
    if (seen.has(o.host)) continue;
    seen.add(o.host);
    out.push(o.host);
  }
  return out;
}

/* ── next-hop resolution ────────────────────────────────────────────────────── */

interface NextHop {
  host: string | null;
  evidence: HopEvidence | null;
  caveat: string | null;
}

/**
 * `links` is a parameter so the cable-map branch can be driven in a test: no route in the collected
 * RIBs names a physical egress port, so on this data the branch is structurally unreachable, and a
 * branch that never executes is not a tested branch (see engine.test.ts's coverage ratchet).
 */
export function resolveNextHost(fromHost: string, route: RouteEntry, links = linksByHost.get(fromHost) ?? []): NextHop {
  if (route.nextHop !== null) {
    const nh = parseIpv4(route.nextHop);
    if (nh !== null) {
      const owners = ADDRESS_OWNERS.get(nh);
      if (owners !== undefined && owners.length > 0) {
        const sorted = [...owners].sort(
          (a, b) =>
            Number(isActive(b.fhrpRole)) - Number(isActive(a.fhrpRole)) ||
            Number(hasRib(b.host)) - Number(hasRib(a.host)) ||
            a.host.localeCompare(b.host),
        );
        const chosen = sorted[0]!;
        const hosts = distinctHosts(sorted);
        return {
          host: chosen.host,
          evidence: { kind: "topology", label: `next hop ${route.nextHop} is ${chosen.label}`, raw: null, cite: chosen.cite },
          caveat:
            hosts.length > 1
              ? `Next hop ${route.nextHop} is an address of ${hosts.length} collected hosts (${hosts.join(", ")}); ${chosen.host} was followed because ${chosen.fhrpRole === null ? "it is the first candidate holding a collected RIB" : `${chosen.cite} records it as ${chosen.fhrp ?? "FHRP"} ${chosen.fhrpRole}`}. The others were not explored.`
              : null,
        };
      }
      return {
        host: null,
        evidence: null,
        caveat: `Next hop ${route.nextHop} (${route.cite}) is not an address of any collected host, so the path beyond ${fromHost} was not simulated. It is an unknown device, not a proven dead end.`,
      };
    }
  }
  // No next-hop address: try the egress interface against the cable map.
  if (route.outIntf !== null) {
    const hit = links.find((l) => (l.a === fromHost && l.aPort === route.outIntf) || (l.b === fromHost && l.bPort === route.outIntf));
    if (hit !== undefined) {
      const other = hit.a === fromHost ? hit.b : hit.a;
      return {
        host: other,
        evidence: { kind: "topology", label: `${fromHost} ${route.outIntf} connects to ${other} (${hit.confirmation ?? "confirmation not recorded"})`, raw: null, cite: hit.cite },
        caveat: null,
      };
    }
  }
  return {
    host: null,
    evidence: null,
    caveat: `The winning route at ${fromHost} (${route.cite}) names neither a resolvable next-hop address nor a physical egress port in the cable map, so the next device could not be identified.`,
  };
}

/* ── route selection ────────────────────────────────────────────────────────── */

/** Connected and local routes are AD 0 on every platform; an unobserved AD is left unknown. */
function adminDistanceOf(r: RouteEntry): number | null {
  if (r.adminDistance !== null) return r.adminDistance;
  if (r.source === "connected" || r.source === "local") return 0;
  return null;
}

export interface RouteChoice {
  winner: RouteEntry;
  alternatives: RouteEntry[];
  caveat: string | null;
}

/**
 * `routes` is a parameter for the same reason `resolveNextHost` takes `links`: no host in this
 * snapshot carries two routes of equal prefix length, so the tie-break below never runs on the real
 * fabric, and the only way to exercise it without inventing a RIB is to hand it real route records
 * from two collected hosts.
 */
export function chooseRoute(host: string, dstIp: Ipv4, routes: readonly RouteEntry[] = routesOf(host)): RouteChoice | null {
  const ranked = rankPrefixMatches(routes, dstIp, (r) => r.prefix);
  if (ranked.length === 0) return null;
  const topBits = ranked[0]!.prefix.bits;
  const tied = ranked.filter((r) => r.prefix.bits === topBits);
  let caveat: string | null = null;
  let winner = tied[0]!.item;
  if (tied.length > 1) {
    const withAd = tied.filter((t) => adminDistanceOf(t.item) !== null);
    if (withAd.length === tied.length) {
      winner = [...tied].sort((a, b) => adminDistanceOf(a.item)! - adminDistanceOf(b.item)!)[0]!.item;
      caveat = `${tied.length} routes at ${host} tie at /${topBits} for ${formatIpv4(dstIp)}; the lowest administrative distance (${adminDistanceOf(winner)}) was followed and equal-cost paths were not explored.`;
    } else {
      caveat = `${tied.length} routes at ${host} tie at /${topBits} for ${formatIpv4(dstIp)} and administrative distance was not observed for all of them (${tied.filter((t) => adminDistanceOf(t.item) === null).map((t) => t.item.cite).join(", ")}); the first in RIB order was followed. Which one the device actually prefers is unproven.`;
    }
  }
  return { winner, alternatives: ranked.map((r) => r.item).filter((r) => r !== winner), caveat };
}

/* ── the trace ──────────────────────────────────────────────────────────────── */

function protoLabel(flow: Flow): string {
  if (flow.protocol === "tcp" || flow.protocol === "udp") {
    return `${flow.protocol}/${flow.dstPort === null ? "any port" : flow.dstPort}`;
  }
  return flow.protocol;
}

/**
 * "an icmp flow", "a udp/5060 flow". Protocol names here are read as initialisms, so the article
 * follows the sound of the first LETTER's name ("eye-cee-em-pee" takes "an", "you-dee-pee" takes
 * "a") — a plain vowel test gets `udp` wrong.
 */
const VOWEL_SOUNDING_INITIALS = new Set([..."aefhilmnorsx"]);
function flowPhrase(flow: Flow): string {
  const label = protoLabel(flow);
  const article = VOWEL_SOUNDING_INITIALS.has(label[0]?.toLowerCase() ?? "") ? "an" : "a";
  return `${article} ${label} flow from ${flow.srcIp} to ${flow.dstIp}`;
}

/** The deny sentence, composed from the decision's own fields rather than re-using a UI label. */
function denialPhrase(acl: AclEval): string {
  const d = acl.decision;
  if (d === null) return "an access-list decision whose line was not recorded";
  if (d.lineIndex === null) return `ACL ${d.aclName}'s implicit deny (no line in the list matches this flow)`;
  return `ACL ${d.aclName} line ${d.lineIndex}`;
}

const SCOPE_PHRASE = `Under the collected RIBs of ${ROUTABLE.join(" and ")} only (${ROUTABLE.length} of ${HOST_COUNT} hosts in this topology)`;

function baseCaveats(): string[] {
  return [
    `Forwarding is modelled only from the RIBs collected for ${ROUTABLE.join(", ")}; ${UNROUTABLE_COUNT} of ${HOST_COUNT} hosts in this topology have no collected routing table, so nothing can be proven about forwarding on them.`,
    `No \`ip access-group\` binding was collected anywhere in this snapshot (${fabric.meta.source}), so which interface and direction an ACL is applied to is unknown; an ACL applied elsewhere on the path could filter this flow without appearing in this trace.`,
    "Stateful inspection, NAT, policy-based routing and any firewall in the path are not modelled: this walks stateless ACL text and the collected RIB only.",
    "Only the forward direction was simulated; the return path may be filtered or routed differently.",
    "ECMP is not modelled — one path is followed per hop and equal-cost alternates are listed, not explored.",
    "L2 forwarding, ARP/CAM state and VLAN pruning are not simulated: \"delivered\" means the destination prefix is directly connected at the last hop, not that a host answered.",
    `This is control-plane analysis of configuration and routing text collected at ${fabric.meta.collectedAt ?? "an unrecorded time"}, not observed traffic.`,
  ];
}

function finish(flow: Flow, outcome: TraceOutcome, hops: Hop[], claim: string, caveats: string[], unmodelledHosts: string[], startedAt: number): Trace {
  const seen = new Set<string>();
  const deduped = caveats.filter((c) => (seen.has(c) ? false : (seen.add(c), true)));
  return {
    flow,
    outcome,
    hops,
    claim,
    caveats: deduped,
    unmodelledHosts,
    /* determinism: a MEASUREMENT of this machine, never rendered. `src/core/determinism.test.ts`
       holds that second half — no surface may interpolate `elapsedMs` — because a number that is
       allowed into the DOM makes two runs of the same investigation differ, which is how it was
       reaching `#sr-status` before an audit found it. The tripwire tests read it; the UI does not. */
    elapsedMs: performance.now() - startedAt,
  };
}

export function traceFlow(flow: Flow): Trace {
  /* determinism: start of the elapsed-time measurement above; feeds `elapsedMs` and nothing else.
     No branch in this function reads it, so no trace outcome can depend on it. */
  const startedAt = performance.now();
  const srcIp = parseIpv4(flow.srcIp);
  const dstIp = parseIpv4(flow.dstIp);

  if (srcIp === null || dstIp === null) {
    const bad = srcIp === null ? flow.srcIp : flow.dstIp;
    return finish(
      flow,
      "out-of-scope",
      [],
      /* Every verdict carries the scope in the SENTENCE, not only in the caveat list below it.
         The out-of-scope returns used to be the exception — measured over a 343-flow sweep, all 49
         out-of-scope claims omitted the 2-of-26 RIB denominator that all 294 other claims carried
         inline, leaving a reader who reads the verdict and the badge but not the eight caveats
         with no idea how narrow the collection is. */
      `${SCOPE_PHRASE}, "${bad}" is not a valid IPv4 address, so nothing was simulated.`,
      ["The flow was rejected before any evidence was consulted; this says nothing about the network."],
      [],
      startedAt,
    );
  }

  // A packet cannot originate from the network or directed-broadcast address of a subnet, so a
  // trace from one is not a narrower answer — it is a question about a host that does not exist.
  const srcSubnet = narrowestObservedSubnet(srcIp);
  const srcRole = srcSubnet === null ? "host" : addressRoleIn(srcSubnet.prefix, srcIp);
  if (srcSubnet !== null && srcRole !== "host") {
    return finish(
      flow,
      "out-of-scope",
      [],
      `${SCOPE_PHRASE}, ${flow.srcIp} is the ${srcRole === "network" ? "network" : "directed-broadcast"} address of ${formatPrefix(srcSubnet.prefix)} (${srcSubnet.label}, ${srcSubnet.cite}), not a host address, so no flow was simulated from it.`,
      [
        `A source address must be a host address; ${flow.srcIp} identifies the subnet itself. Re-run with an address inside ${formatPrefix(srcSubnet.prefix)} to get a forwarding answer.`,
        ...baseCaveats(),
      ],
      [],
      startedAt,
    );
  }

  const ingress = resolveIngress(srcIp);
  if ("none" in ingress) {
    return finish(
      flow,
      "out-of-scope",
      [],
      `${SCOPE_PHRASE}, ${ingress.none}, so no ingress device can be named and no forwarding claim is made about ${flowPhrase(flow)}.`,
      [
        `${flow.srcIp} is outside every subnet in the collected evidence. That is a limit of the collection, not proof that the address does not exist on this network.`,
        ...baseCaveats(),
      ],
      [],
      startedAt,
    );
  }

  const caveats: string[] = [...ingress.caveats];
  const unmodelledHosts: string[] = [];
  const hops: Hop[] = [];
  const visited = new Set<string>();
  let host: string = ingress.host;
  let carriedEvidence: HopEvidence[] = ingress.evidence;
  let outcome: TraceOutcome = "indeterminate";
  let aclIndeterminateSeen = false;
  let claim = "";

  for (let index = 0; index < TTL_LIMIT; index += 1) {
    if (visited.has(host)) {
      hops.push({
        index,
        host,
        outIntf: null,
        nextHop: null,
        nextHost: null,
        verdict: "loop",
        decidedBy: { kind: "absence", label: `${host} has already been visited in this trace — the collected routes form a loop for ${flow.dstIp}`, raw: null, cite: fabric.coverage.cite },
        evidence: carriedEvidence,
        alternatives: [],
      });
      outcome = "dropped";
      claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} loops: ${host} is reached twice, so the packet is dropped by TTL expiry rather than delivered.`;
      caveats.push("A forwarding loop was detected in the collected routes; on real hardware the packet dies at TTL 0, which this model reports as a drop.");
      break;
    }
    visited.add(host);

    if (!hasRib(host)) {
      unmodelledHosts.push(host);
      hops.push({
        index,
        host,
        outIntf: null,
        nextHop: null,
        nextHost: null,
        verdict: "unmodeled",
        decidedBy: {
          kind: "absence",
          label: `no routing table was collected for ${host}; its forwarding cannot be modelled`,
          raw: null,
          cite: fabric.coverage.cite,
        },
        evidence: carriedEvidence,
        alternatives: [],
      });
      outcome = "indeterminate";
      claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} cannot be decided: it reaches ${host}, for which no routing table was collected, so forwarding past ${host} is unmodelled — not clear, and not blocked.`;
      caveats.push(
        `${host} was traversed with no collected RIB (${fabric.coverage.cite}); every statement about what happens at or beyond ${host} is unproven.`,
      );
      if (Object.keys(aclsOf(host)).length === 0) {
        caveats.push(`No ACLs were collected for ${host}; filtering there is unobserved, not absent.`);
      }
      break;
    }

    const acl = evaluateAcls(host, flow, srcIp, dstIp);
    if (acl.verdict === "indeterminate") aclIndeterminateSeen = true;
    caveats.push(...acl.caveats);
    if (Object.keys(aclsOf(host)).length === 0) {
      caveats.push(`No ACLs were collected for ${host}; filtering there is unobserved, not absent.`);
    } else if (acl.verdict === "not-applicable") {
      caveats.push(
        `${Object.keys(aclsOf(host)).length} ACL(s) are defined on ${host} but none names this flow's addresses specifically, so none was applied. With no collected access-group binding, that is an absence of evidence, not evidence of an unfiltered path.`,
      );
    }

    const route = chooseRoute(host, dstIp);
    if (route?.caveat) caveats.push(route.caveat);

    const evidence = [...carriedEvidence, ...acl.evidence];
    carriedEvidence = [];

    // ACL denial takes precedence over the routing result: an inbound filter drops the packet
    // before the FIB lookup matters, and naming the line is the more useful answer either way.
    if (acl.verdict === "deny" && acl.decidedBy !== null) {
      const ev = acl.decidedBy;
      hops.push({
        index,
        host,
        outIntf: route?.winner.outIntf ?? null,
        nextHop: route?.winner.nextHop ?? null,
        nextHost: null,
        verdict: "denied",
        decidedBy: ev,
        evidence: route ? [...evidence, routeEvidence(host, route.winner)] : evidence,
        alternatives: route?.alternatives ?? [],
      });
      outcome = "denied";
      claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} is denied at ${host} by ${denialPhrase(acl)} (${ev.cite}${ev.raw === null ? "" : `: "${ev.raw}"`}); the ACL's interface binding was not collected, and stateful return traffic is not modelled.`;
      break;
    }

    if (route === null) {
      hops.push({
        index,
        host,
        outIntf: null,
        nextHop: null,
        nextHost: null,
        verdict: "no-route",
        decidedBy: {
          kind: "absence",
          label: `no prefix in ${host}'s collected RIB (${routesOf(host).length} routes, including no default route) matches ${flow.dstIp}`,
          raw: null,
          cite: `routes.${host}`,
        },
        evidence,
        alternatives: [],
      });
      outcome = "dropped";
      claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} is dropped at ${host}: no prefix in its collected RIB matches ${flow.dstIp} and it carries no default route.`;
      caveats.push(
        `The drop at ${host} rests on the RIB as collected (routes.${host}); a route learned after collection, or a VRF not collected, would change it.`,
      );
      break;
    }

    const win = route.winner;
    const routeEv = routeEvidence(host, win);
    const connected = win.source === "connected" || win.source === "local";
    const localSvi = SVI_SUBNETS.find((s) => s.host === host && prefixContains(s.prefix, dstIp));

    if (connected || localSvi !== undefined) {
      const sviEv: HopEvidence[] =
        localSvi === undefined
          ? []
          : [{ kind: "svi", label: `${host} Vlan${localSvi.record.vlan ?? "?"} ${formatPrefix(localSvi.prefix)} contains ${flow.dstIp}`, raw: localSvi.record.sviIp, cite: localSvi.record.cite }];
      const undecided = acl.verdict === "indeterminate";
      // "Delivered" is a statement about reaching a HOST. The network and directed-broadcast
      // addresses of the delivering subnet are not hosts: what a device does with one depends on
      // `ip directed-broadcast`, which this collection does not carry, so the honest answer there
      // is that the packet reached the wire and the rest is unobserved.
      const deliveryPrefix = (connected ? parsePrefix(win.prefix) : null) ?? localSvi?.prefix ?? null;
      const dstRole = deliveryPrefix === null ? "host" : addressRoleIn(deliveryPrefix, dstIp);
      const nonHostEv: HopEvidence | null =
        dstRole === "host"
          ? null
          : {
              kind: "absence",
              label: `${flow.dstIp} is the ${dstRole === "network" ? "network" : "directed-broadcast"} address of ${formatPrefix(deliveryPrefix!)}, not a host address; no \`ip directed-broadcast\` setting was collected for ${host}`,
              raw: null,
              cite: fabric.coverage.cite,
            };
      hops.push({
        index,
        host,
        outIntf: win.outIntf,
        nextHop: null,
        nextHost: null,
        // A hop that reads "delivered" inside an undecidable trace is a green tick over an unknown.
        // "unmodeled" is the honest verdict for this hop: the RIB got the packet here, the filter
        // could not be evaluated, so the outcome AT this hop was not modelled.
        verdict: undecided || nonHostEv !== null ? "unmodeled" : "delivered",
        decidedBy: undecided ? acl.decidedBy : (nonHostEv ?? routeEv),
        evidence: [...evidence, routeEv, ...sviEv, ...(nonHostEv === null ? [] : [nonHostEv])],
        alternatives: route.alternatives,
      });
      if (acl.verdict === "indeterminate" && acl.decidedBy !== null) {
        outcome = "indeterminate";
        claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} reaches ${host}'s connected ${win.prefix} (${win.cite}), but the result cannot be decided: ${acl.decidedBy.label} (${acl.decidedBy.cite}).`;
      } else if (nonHostEv !== null) {
        outcome = "indeterminate";
        claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} is routed to ${host}'s ${win.source ?? "unlabelled"} ${win.prefix} (${win.cite}), but ${flow.dstIp} is that subnet's ${dstRole === "network" ? "network" : "directed-broadcast"} address rather than a host address, so what ${host} does with it cannot be decided from this collection.`;
        caveats.push(
          `${flow.dstIp} addresses the subnet ${formatPrefix(deliveryPrefix!)} itself. Whether ${host} forwards, floods or discards it turns on \`ip directed-broadcast\` and platform defaults, neither of which was collected (${fabric.coverage.cite}).`,
        );
      } else {
        outcome = "delivered";
        claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} is delivered at ${host} on ${win.source ?? "an unlabelled"} route ${win.prefix} via ${win.outIntf ?? "an unnamed interface"} (${win.cite}); delivery means the destination prefix is directly connected there, not that a host replied.`;
      }
      break;
    }

    const next = resolveNextHost(host, win);
    if (next.caveat !== null) caveats.push(next.caveat);
    hops.push({
      index,
      host,
      outIntf: win.outIntf,
      nextHop: win.nextHop,
      nextHost: next.host,
      verdict: acl.verdict === "indeterminate" ? "unmodeled" : "forwarded",
      decidedBy: acl.verdict === "indeterminate" ? acl.decidedBy : routeEv,
      evidence: next.evidence === null ? [...evidence, routeEv] : [...evidence, routeEv, next.evidence],
      alternatives: route.alternatives,
    });

    if (next.host === null) {
      outcome = "indeterminate";
      claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} is forwarded by ${host} toward ${win.nextHop ?? win.outIntf ?? "an unresolved next hop"} on ${win.prefix} (${win.cite}), and cannot be followed further: that next hop belongs to no host in this collection.`;
      break;
    }
    if (acl.verdict === "indeterminate") {
      // Carry on routing, but the flow can no longer be claimed either way.
      caveats.push(`The ACL result at ${host} is indeterminate, so no outcome downstream of ${host} can be claimed as proven.`);
    }
    host = next.host;

    if (index === TTL_LIMIT - 1) {
      outcome = "dropped";
      claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} exceeded the ${TTL_LIMIT}-hop simulation cap without reaching its destination; on real hardware this is a TTL drop.`;
      const last = hops[hops.length - 1]!;
      hops[hops.length - 1] = { ...last, verdict: "ttl-exceeded" };
      caveats.push(`The trace was cut at the ${TTL_LIMIT}-hop cap; the path was longer than this fabric's diameter, which usually means a routing loop.`);
    }
  }

  // An indeterminate ACL ANYWHERE on the path withdraws a positive claim, even when a later hop
  // routes cleanly: we could not prove the packet got past the earlier filter. Tracked as a flag,
  // not by reading the caveat prose back — a guard that greps its own output stops guarding the
  // moment the wording changes.
  if (aclIndeterminateSeen && outcome === "delivered") outcome = "indeterminate";

  return finish(flow, outcome, hops, claim, [...caveats, ...baseCaveats()], unmodelledHosts, startedAt);
}

function routeEvidence(host: string, r: RouteEntry): HopEvidence {
  return {
    kind: "route",
    label: `${host} longest-prefix match ${r.prefix} (${r.source ?? "source not recorded"}${r.nextHop === null ? "" : ` via ${r.nextHop}`}${r.outIntf === null ? "" : ` out ${r.outIntf}`})`,
    raw: null,
    cite: r.cite,
  };
}

/* ── the blocking hop ───────────────────────────────────────────────────────── */

const BLOCKING: ReadonlySet<Hop["verdict"]> = new Set(["denied", "no-route", "unmodeled", "loop", "ttl-exceeded"]);

/** The hop that ended the trace and the single piece of evidence that ended it. */
export function blockingHop(trace: Trace): { hop: Hop; evidence: HopEvidence } | null {
  for (const hop of trace.hops) {
    if (BLOCKING.has(hop.verdict) && hop.decidedBy !== null) return { hop, evidence: hop.decidedBy };
  }
  return null;
}

/* ── counterexamples ────────────────────────────────────────────────────────── */

const CANDIDATE_CAP = 48; // keeps the search inside the interaction budget on the worst flow

/**
 * The nearest flow that WOULD succeed. Candidates are derived from the evidence that blocked this
 * one — the permit lines of the ACL that denied it, and the connected prefixes of the RIB that had
 * no route — and each candidate is traced before it is offered. Nothing is returned unless the
 * engine actually produced "delivered" for it.
 */
/**
 * The evidence the DELIVERED trace actually recorded, for the counterexample's rationale.
 *
 * This exists because the candidate that GENERATED a flow and the trace that JUDGED it are two
 * independent things. Candidates are varied by protocol and port only — never by address — so the
 * line that suggested a candidate frequently cannot match the flow's addresses at all, while the
 * verdict comes from a separate traceFlow() run that consulted whatever line really decided. A
 * rationale narrated from the candidate line is therefore an assertion about evidence nobody
 * checked: it stated "MGMT_IN line 0 permits tcp/22 for this address pair" for a flow whose source
 * is not in MGMT_IN's object-group, while the engine's own trace named PROTECT_SERVERS line 1.
 *
 * So the sentence is built from `t`'s hops and nothing else. Returning null means the trace
 * recorded no ACL evidence, and the caller must then state the outcome WITHOUT a causal clause
 * rather than reaching back to the candidate.
 */
function deliveringAclEvidence(t: Trace): HopEvidence | null {
  for (const hop of t.hops) {
    const decided = hop.decidedBy;
    if (decided !== null && decided.kind === "acl") return decided;
    for (const e of hop.evidence) if (e.kind === "acl") return e;
  }
  return null;
}

export function counterexample(flow: Flow, trace: Trace): CounterexampleResult {
  if (trace.outcome !== "denied" && trace.outcome !== "dropped") {
    return { found: false, reason: `The trace outcome is "${trace.outcome}"; a counterexample is only meaningful for a denied or dropped flow.` };
  }
  const blocked = blockingHop(trace);
  if (blocked === null) return { found: false, reason: "No blocking hop was recorded, so there is nothing to vary." };
  const host = blocked.hop.host;
  /* Deliberately no `why` field: a candidate records only the flow to try. WHY a flow behaves as it
     does is a property of the traced result's own evidence, and carrying a plausible-sounding
     explanation alongside the candidate is exactly how a sentence about one ACL line came to be
     attached to a verdict decided by another. */
  const candidates: { flow: Flow }[] = [];

  // Vary the protocol/port to whatever the same host's ACLs actually permit for this pair.
  /* The ACL name is not read here — only the ORDER it imposes is, which is what keeps the
     candidate list identical between two runs. Binding it would fail `noUnusedLocals`. */
  for (const [, lines] of Object.entries(aclsOf(host)).sort(([a], [b]) => a.localeCompare(b))) {
    for (const line of lines) {
      if ((line.action ?? "").toLowerCase() !== "permit") continue;
      if (!lineEvaluability(line).evaluable) continue;
      const proto = (line.proto ?? "").toLowerCase();
      if (proto !== "tcp" && proto !== "udp" && proto !== "icmp") continue;
      // Read through portValue: an evaluable line cannot carry an unresolved operand, but the
      // record's type does not enforce that and a counterexample built on `null` is not a flow.
      const op = line.dport === null ? null : line.dport.op.toLowerCase();
      const port = op === "eq" || op === "range" ? portValue(line.dport!.val) : null;
      if ((proto === "tcp" || proto === "udp") && port === null) continue;
      candidates.push({
        flow: { ...flow, protocol: proto as Flow["protocol"], dstPort: proto === "icmp" ? null : port },
      });
    }
  }

  // Vary the destination to a prefix the blocking host can actually reach directly.
  for (const r of routesOf(host)) {
    if (r.source !== "connected") continue;
    const p = parsePrefix(r.prefix);
    if (p === null) continue;
    const dst = hostAddressIn(p, 10);
    if (dst === null) continue;
    candidates.push({ flow: { ...flow, dstIp: formatIpv4(dst) } });
  }

  for (const c of candidates.slice(0, CANDIDATE_CAP)) {
    if (c.flow.dstIp === flow.dstIp && c.flow.dstPort === flow.dstPort && c.flow.protocol === flow.protocol) continue;
    const t = traceFlow(c.flow);
    if (t.outcome !== "delivered") continue;
    // The rationale cites the trace that was actually run — never `c.why`, which describes only the
    // line that suggested this candidate. See deliveringAclEvidence().
    const decided = deliveringAclEvidence(t);
    const stated = `${protoLabel(c.flow)} from ${c.flow.srcIp} to ${c.flow.dstIp} is delivered`;
    return {
      found: true,
      flow: c.flow,
      trace: t,
      rationale:
        decided === null
          ? `${stated}. No ACL line was consulted on its path, so nothing here claims which rule permitted it.`
          : `${stated}: ${decided.label} (${decided.cite}).`,
    };
  }
  return {
    found: false,
    reason: `None of the ${Math.min(candidates.length, CANDIDATE_CAP)} nearby variations derived from the evidence at ${host} traced as delivered, so no counterexample is offered. That is not proof that none exists — only the collected ACLs and RIBs were searched.`,
  };
}

/* ── suggested flows ────────────────────────────────────────────────────────── */

/**
 * Interesting flows, derived from this snapshot at module load and then TRACED, so the outcome each
 * one advertises is the outcome the engine actually produced. A candidate whose trace does not match
 * its intent is dropped rather than relabelled: the list is evidence about the engine, not a brochure.
 */
const SUGGESTED: readonly SuggestedFlow[] = buildSuggestions();

export function suggestedFlows(): SuggestedFlow[] {
  return SUGGESTED.map((s) => ({ ...s, flow: { ...s.flow } }));
}

function buildSuggestions(): SuggestedFlow[] {
  const out: SuggestedFlow[] = [];
  const take = (
    id: string,
    title: string,
    flow: Flow,
    rationale: string,
    want: TraceOutcome,
    srcProvenance: SourceProvenance,
  ): boolean => {
    if (out.some((o) => o.id === id)) return false;
    const t = traceFlow(flow);
    if (t.outcome !== want) return false;
    out.push({ id, title, flow, rationale, expectedOutcome: t.outcome, srcProvenance });
    return true;
  };

  /** The endpoint record that observed this address, so an "observed" claim carries its evidence. */
  const observedAt = (ip: Ipv4): SourceProvenance => {
    const rec = ENDPOINTS_BY_IP.get(ip)?.[0];
    return {
      kind: "observed",
      cite: rec?.cite ?? fabric.coverage.cite,
      note: `${formatIpv4(ip)} was observed as an endpoint on ${rec?.host ?? "a collected host"} ${rec?.port ?? "(no port recorded)"}.`,
    };
  };

  const derivedFrom = (ip: Ipv4, prefix: Prefix, cite: Cite, why: string): SourceProvenance => ({
    kind: "derived-from-observed-subnet",
    cite,
    note: `${formatIpv4(ip)} was not itself observed: it is a usable host address inside ${formatPrefix(prefix)}, ${why} (${cite}). The subnet is evidence; this address is a question posed inside it.`,
  });

  // A source address the collection actually observed, preferring one inside an ACL's source space.
  const observedSources = [...ENDPOINTS_BY_IP.keys()].sort((a, b) => a - b);

  for (const [host, named] of Object.entries(fabric.acls).sort(([a], [b]) => a.localeCompare(b))) {
    for (const [name, lines] of Object.entries(named).sort(([a], [b]) => a.localeCompare(b))) {
      for (const line of lines) {
        if ((line.action ?? "").toLowerCase() !== "permit") continue;
        if (!lineEvaluability(line).evaluable) continue;
        const dstField = line.dst;
        if (dstField === null || dstField.ip === null || dstField.wild === null) continue;
        const dstBits = wildcardSpecificity(parseIpv4(dstField.wild) ?? 0xffffffff);
        if (dstBits === 0 || dstBits === 32) continue;
        const dstPrefix = parsePrefix(`${dstField.ip}/${dstBits}`);
        if (dstPrefix === null) continue;
        const dst = hostAddressIn(dstPrefix, 10);
        if (dst === null) continue;
        const src = observedSources.find((s) => addrTri(line.src, s, hostOfAclLine(line)) === "yes");
        if (src === undefined) continue;
        const proto = (line.proto ?? "").toLowerCase();
        if (proto !== "tcp" && proto !== "udp") continue;
        // portValue, not `.val`: the compiled record's port field is typed `number` but carries
        // whatever the producer emitted, including null for an unresolved service name.
        const port = line.dport !== null && line.dport.op.toLowerCase() === "eq" ? portValue(line.dport.val) : null;
        if (port === null) continue;

        const permitted: Flow = { srcIp: formatIpv4(src), dstIp: formatIpv4(dst), protocol: proto, dstPort: port, srcPort: null };
        take(
          "permitted",
          `${proto.toUpperCase()}/${port} into ${formatPrefix(dstPrefix)}`,
          permitted,
          /* No uniqueness clause. This used to end "…it is the one shape of traffic this snapshot
             can show ending in delivery" — a hardcoded constant inside a loop over every permit
             line, derived from no count, and contradicted two cards below by the denied demo's own
             counterexample and by the intent verifier reporting 24 contradicting flows on the same
             screen. A uniqueness claim has to be a measurement or it has to be absent. */
          `${host} ACL ${name} line ${line.index} permits exactly this (${line.cite}).`,
          "delivered",
          observedAt(src),
        );

        // The same pair on a port nothing permits: the blocking-hop demonstration.
        const permittedPorts = new Set(
          lines
            .filter((l) => (l.action ?? "").toLowerCase() === "permit" && l.dport?.op.toLowerCase() === "eq")
            .map((l) => portValue(l.dport!.val))
            .filter((v): v is number => v !== null),
        );
        const blockedPort = [3389, 23, 445, 8080, 1].find((p) => !permittedPorts.has(p));
        if (blockedPort !== undefined) {
          take(
            "denied",
            `${proto.toUpperCase()}/${blockedPort} into ${formatPrefix(dstPrefix)}`,
            { ...permitted, dstPort: blockedPort },
            `The same pair on a port no line permits — it falls through ${name} to the explicit deny, which is the blocking-hop answer with its exact configuration line.`,
            "denied",
            observedAt(src),
          );
        }

        // An unevaluable line above the deny: the honest "cannot say" case.
        const unevaluable = lines.find((l) => !lineEvaluability(l).evaluable && l.proto !== null);
        if (unevaluable !== undefined) {
          const p = (unevaluable.proto ?? "").toLowerCase();
          const isIcmp = p === "icmp";
          take(
            "unevaluable",
            `${p.toUpperCase()} into ${formatPrefix(dstPrefix)}`,
            { ...permitted, protocol: (isIcmp ? "icmp" : p === "udp" ? "udp" : "tcp") as Flow["protocol"], dstPort: isIcmp ? null : permitted.dstPort },
            `${unevaluable.cite} ("${unevaluable.raw ?? "text not collected"}") could match this flow and cannot be evaluated, so the engine refuses to decide it rather than guessing.`,
            "indeterminate",
            observedAt(src),
          );
        }
      }
    }
  }

  // A source gatewayed by a host whose RIB was never collected.
  for (const s of SVI_SUBNETS) {
    if (hasRib(s.host)) continue;
    const src = hostAddressIn(s.prefix, 50);
    const delivered = out.find((o) => o.id === "permitted");
    if (src === null || delivered === undefined) continue;
    if (
      take(
        "unmodelled",
        `From ${s.host} Vlan${s.record.vlan ?? "?"} — no RIB collected`,
        { ...delivered.flow, srcIp: formatIpv4(src) },
        `${s.host} gateways ${formatPrefix(s.prefix)} (${s.record.cite}) but no routing table was collected for it, so the honest answer is "unmodelled" — never "delivered".`,
        "indeterminate",
        derivedFrom(src, s.prefix, s.record.cite, `which ${s.host} gateways on Vlan${s.record.vlan ?? "?"}`),
      )
    ) {
      break;
    }
  }

  // A source on a RIB host with no default route, aimed off-fabric: a provable drop.
  const offFabric = ["198.51.100.7", "203.0.113.9", "192.0.2.5"].find((ip) => {
    const v = parseIpv4(ip);
    return v !== null && "none" in resolveIngress(v);
  });
  if (offFabric !== undefined) {
    for (const s of SVI_SUBNETS) {
      if (!hasRib(s.host) || !isActive(s.fhrpRole)) continue;
      const src = hostAddressIn(s.prefix, 50);
      if (src === null) continue;
      if (
        take(
          "no-route",
          `${s.host} Vlan${s.record.vlan ?? "?"} to the internet`,
          { srcIp: formatIpv4(src), dstIp: offFabric, protocol: "tcp", dstPort: 443, srcPort: null },
          `${s.host} is the observed active gateway for ${formatPrefix(s.prefix)} (${s.record.cite}) and its collected RIB holds no default route, so this address is provably unreachable from there.`,
          "dropped",
          derivedFrom(src, s.prefix, s.record.cite, `for which ${s.host} is the observed active gateway`),
        )
      ) {
        break;
      }
    }
    // The mirror case: a source that is in no observed subnet at all.
    const insideDst = out.find((o) => o.id === "permitted")?.flow.dstIp;
    if (insideDst !== undefined) {
      take(
        "out-of-scope",
        `An address the collection never saw`,
        { srcIp: offFabric, dstIp: insideDst, protocol: "tcp", dstPort: 443, srcPort: null },
        `${offFabric} is in no SVI subnet, connected route or endpoint record, so naming an ingress device would be a guess; the engine says out-of-scope instead.`,
        "out-of-scope",
        {
          kind: "outside-every-observed-subnet",
          cite: fabric.coverage.cite,
          note: `${offFabric} is deliberately outside every subnet this collection observed — that is the point of the case, and it is why no ingress device is named.`,
        },
      );
    }
  }

  return out;
}
