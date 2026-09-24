/**
 * engine.ts — the forwarding simulator.
 *
 * It answers one question: can this flow get from A to B, and if not, exactly what stopped it?
 * The answer is always paired with the scope it holds over, because this snapshot is thin where it
 * matters: RIBs were collected for 2 of 26 hosts and ACLs for 1, and the interface ACL bindings
 * (`ip access-group`) are only partly observed — see ./bindings.ts. Every one of those gaps is a reason a result is narrower than it looks, and
 * each is emitted as a caveat rather than silently absorbed.
 *
 * The invariant that shapes the whole file: a missing input never produces a positive result.
 * No RIB for a host is "unmodeled" and the trace outcome becomes indeterminate — never "delivered".
 * An ACL line we cannot evaluate poisons the lines below it, because we cannot prove our match is
 * the one that fires. Absence is absence.
 */
import { aclsOf, fabric, hasRib, linksByHost, routesOf } from "../core/data";
import { adminDistanceRank, routeFieldReading } from "../core/route-fields";
import { aclLineName } from "./acl-line";
import { ribIncompleteness, ribIncompletenessSentence } from "./rib-completeness";
import {
  bindingCoverageSentences,
  bindingEvidence,
  connectedInterfaceFor,
  hopHasObservedBinding,
  pathBindings,
  physicalIngressStates,
  type PathBindings,
} from "./bindings";
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
  describeFlowProblem,
  flowFieldName,
  flowProblems,
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

/**
 * The work the engine has done since it loaded, counted in its own units: `traceFlow` calls
 * (including the memoised alternate-ingress traces a trace judges itself by), hop-loop iterations,
 * and ACL line matches (`matchTri` calls — the innermost loop, where a quadratic would live). A
 * COUNT, not a clock — it is the same on a quiet host and a loaded one, which is what lets a unit
 * test bound the engine's work structurally (see `COUNTEREXAMPLE_CANDIDATE_CAP` and
 * `engine.work-bound.test.ts`). No trace outcome, claim or surface reads it.
 */
export interface EngineWork {
  traces: number;
  hops: number;
  lineMatches: number;
}
const WORK: EngineWork = { traces: 0, hops: 0, lineMatches: 0 };

/**
 * How many times one hop may ask the matcher about each ACL line on its host. Counted from the code,
 * not measured: `evaluateAcls` runs the observed-binding pass (one `runLists`) and, where a binding
 * was not observed, the specificity pass (`undecidableInUnappliedAcls`, `notAppliedCaveat`,
 * `runLists` — one pass each over the lists they read); `receivedAtOwner` may run one more
 * observed-binding pass at the delivering hop. Five passes, each over at most every line on the
 * host. A sixth pass, or a pass nested inside another, is a change to the engine's cost that has to
 * raise this number on purpose — which is what `engine.work-bound.test.ts` holds it to.
 */
export const ACL_PASSES_PER_HOP = 5;

/** A copy of the running work counters; take two and subtract to measure one call. */
export function engineWork(): EngineWork {
  return { ...WORK };
}

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
  /**
   * Why this flow is worth posing — the evidence it was derived from. It NAMES the question and never
   * states the answer: the outcome is the trace's, and a surface states it through the claims owner
   * (`ClaimCard.tsx :: verdictStatement`) with the trace's scope clause and caveats. A rationale that
   * pre-announced the answer ("…to the explicit deny, which is the blocking-hop answer with its
   * exact configuration line") was printed by the palette and the Path presets over a denial whose
   * own trace says "That denial is not decided" (acceptance B2). Pinned by
   * `src/app/verdict-scope.b2.test.tsx`.
   */
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

/**
 * Which port operators the configuration TEXT carries, read by position with the same grammar the
 * evaluability check uses: `<action> <proto> <src> [src-port-op] <dst> [dst-port-op] …`. Null when
 * the text cannot be read that far (an unresolvable group, an unreadable address), so a caller can
 * only ever narrow "not observed" to "no constraint" on a line whose text was actually read.
 *
 * Exists because a reader once asked "is there an `eq` ANYWHERE on the line" to decide whether a
 * null SOURCE port was a parse gap, and so marked `sport` "not observed" on
 * `permit tcp 10.0.10.0 0.0.0.255 10.0.30.0 0.0.0.255 eq 443`, whose `eq` constrains the
 * DESTINATION port (2026-09-22 auditor, B1).
 */
export function portOperatorsInText(raw: string, host: string | null = null): { sport: boolean; dport: boolean } | null {
  const toks = raw.trim().split(/\s+/);
  if (toks.length < 3) return null;
  const src = consumeAddress(toks, 2, host);
  if (!src.ok) return null;
  const sport = consumePortOp(toks, src.next);
  if (!sport.ok) return null;
  const dst = consumeAddress(toks, sport.next, host);
  if (!dst.ok) return null;
  const dport = consumePortOp(toks, dst.next);
  if (!dport.ok) return null;
  return { sport: Boolean(sport.sawPortOp), dport: Boolean(dport.sawPortOp) };
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
  WORK.lineMatches += 1;
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

/**
 * Does this address field resolve to a readable address space in this snapshot? The SAME resolution
 * `groupTri` and `lineEvaluability` use: an object-group reference resolves when the group was
 * collected with at least one member and every member parses. It used to test `ip === null` alone,
 * so a group that resolved (core1 MGMT_HOSTS → 10.0.99.10/32, 10.0.40.0/24) was still described as
 * "could not be resolved in this snapshot" while `lineEvaluability` called the line evaluable
 * (2026-09-22 critic, B5).
 */
function resolvedGroupOf(f: AclMatchField | null, host: string | null): { name: string; members: number } | null {
  const name = fieldGroup(f);
  if (name === null) return null;
  const g = resolveObjectGroup(host, name);
  if (g === null || g.members.length === 0) return null;
  const parses = g.members.every((m) => m.ip !== null && parseIpv4(m.ip) !== null && (m.wild === null || parseIpv4(m.wild) !== null));
  return parses ? { name, members: g.members.length } : null;
}

function fieldResolves(f: AclMatchField | null, host: string | null): boolean {
  if (f === null) return true;
  if (fieldGroup(f) !== null) return resolvedGroupOf(f, host) !== null;
  return f.ip !== null;
}

function hasUnresolvedAddressing(line: AclLine): boolean {
  const host = hostOfAclLine(line);
  return !fieldResolves(line.src, host) || !fieldResolves(line.dst, host);
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
  decision: {
    aclName: string;
    lineIndex: number | null;
    /** How many lines the deciding list holds, so prose can say "line 4 of 4". */
    lineCount: number;
    raw: string | null;
    /** The observed interface binding that applies the deciding list here, or null when none was observed. */
    binding: AclBindingFact | null;
  } | null;
  /**
   * How the lists were chosen: `observed` — every binding on this hop's interfaces was observed and
   * exactly the bound lists were applied; `specificity` — at least one binding was unknown (or none
   * was consulted) and the address-specificity rule chose. Absent on results built outside a hop.
   */
  bindingMode?: "observed" | "specificity";
}

export interface AclBindingFact {
  intf: string;
  dir: "in" | "out";
  cite: Cite;
}

function aclEvidence(host: string, name: string, line: AclLine, total: number, note: string): HopEvidence {
  return {
    kind: "acl",
    label: `${host} ACL ${name} ${aclLineName(line.index, total)} ${note}`,
    raw: line.raw,
    cite: line.cite,
  };
}

/**
 * Which ACLs apply here?
 *
 * The FALLBACK, used only at a hop where a binding the flow depends on was not observed (see
 * ./bindings.ts — where the bindings of the ingress and egress interface are observed, exactly the
 * bound lists apply and this rule does not run). Rather than pretend every defined ACL filters every
 * flow (which would deny nearly everything on the strength of MGMT_IN), or that none do (which would
 * hide the real filters), this selects the ACL whose own match space names this flow most
 * specifically, and the hop says which binding was unknown and why. The rule is deterministic and
 * stated out loud; it is not evidence that the ACL is applied on the path.
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
  gap: string,
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
          `${host} ACL ${name} ${aclLineName(line.index, (named[name] ?? []).length)} could match this flow and cannot be evaluated ` +
          `(${ev.reason ?? "no reason recorded"}); the list was not applied by the specificity rule, ` +
          `and because ${gap}, that is not evidence it does not filter this flow`,
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
 * references object-group MGMT_HOSTS, which resolves, but the specificity score reads literal
 * addresses only, so the list can never score and the caveat says exactly that.
 */
function notAppliedCaveat(
  host: string,
  named: Record<string, AclLine[]>,
  applied: readonly string[],
  flow: Flow,
  srcIp: Ipv4,
  dstIp: Ipv4,
  gap: string,
): string | null {
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
    const unresolved = lines.find((l) => !lineEvaluability(l).evaluable && hasUnresolvedAddressing(l));
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
    const addressed = lines.filter(
      (l) => addrTri(l.src, srcIp, hostOfAclLine(l)) !== "no" && addrTri(l.dst, dstIp, hostOfAclLine(l)) !== "no",
    );
    if (addressed.length === 0) {
      outscored.push(`${name} (names other address space)`);
      continue;
    }
    /* Address overlap is not a match. This list of candidate lines used to stop at the addresses, so
       a udp or icmp flow was told INET_RETURN "matches this flow at" its `permit tcp … eq 443` line
       (2026-09-23 acceptance report, adjacent to B5: 50 of 3,968 traces). Every dimension is now
       asked of the ONE matcher the verdict itself uses — `matchTri`, which only lets a dimension the
       text check vouched for say "no" — so a line whose protocol or port excludes this flow is not
       described as matching it, and a line whose match is undecidable stays "could match". */
    const triOf = new Map(addressed.map((l) => [l, matchTri(l, flow, srcIp, dstIp)] as const));
    const matching = addressed.filter((l) => triOf.get(l) !== "no");
    const verb = (ls: readonly AclLine[]): string => (ls.some((l) => triOf.get(l) === "yes") ? "matches" : "could match");
    if (matching.length === 0) {
      // Every line naming these addresses excludes the flow by protocol or port, so applied to this
      // flow the list would fall through to its implicit deny. The first exclusion is named.
      const first = addressed[0]!;
      outscored.push(
        `${name} (names this flow's addresses but no line of it can match this flow — at ${first.cite} ${excludedBecause(first, flow, srcIp, dstIp) ?? "the line excludes it"} — so, were it applied, this flow would fall to the list's implicit deny)`,
      );
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
    /* A line that reaches this flow through an object-group that DID resolve. The specificity score
       reads literal addresses only (`lineSpecificity`), so such a list is outscored by construction —
       that is what the reader must be told, not that its addresses were unresolvable. */
    const groupMatch = matching
      .filter((l) => lineEvaluability(l).evaluable)
      .map((l) => ({ l, g: resolvedGroupOf(l.src, hostOfAclLine(l)) ?? resolvedGroupOf(l.dst, hostOfAclLine(l)) }))
      .find((x) => x.g !== null);
    if (!topEval.evaluable) {
      outscored.push(`${name} (${verb([top])} this flow at ${top.cite}, which cannot be evaluated: ${topEval.reason ?? "no reason recorded"})`);
    } else if (everyMatchIsCatchAll) {
      outscored.push(`${name} (${verb(matching)} this flow only through catch-all lines)`);
    } else if (groupMatch !== undefined && groupMatch.g !== null) {
      outscored.push(
        `${name} (${verb([groupMatch.l])} this flow at ${groupMatch.l.cite} through object-group ${groupMatch.g.name}, which resolved in this snapshot to ${groupMatch.g.members} member${groupMatch.g.members === 1 ? "" : "s"} covering this flow's address; the specificity rule scores literal addresses only, so a group reference does not make the list selectable)`,
      );
    } else if (unresolvedMatch !== undefined) {
      outscored.push(`${name} (${verb([unresolvedMatch])} this flow at ${unresolvedMatch.cite}, whose address space could not be resolved in this snapshot)`);
    } else {
      outscored.push(`${name} (${verb([top])} this flow at ${top.cite}, which names its addresses specifically)`);
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
    `Because ${gap}, that is not evidence ${rest.length === 1 ? "it does" : "they do"} not filter this flow.`,
  );
  return parts.join(" ");
}

/** The interfaces a packet enters and leaves a hop by, when the trace could resolve them. */
export interface HopInterfaces {
  ingress: string | null;
  egress: string | null;
  /**
   * The address the packet is framed toward when it leaves: the destination on a connected route,
   * the next hop otherwise. A port ACL on the egress VLAN matters only if THIS address is attached
   * behind that port. Defaults to the destination.
   */
  egressTarget?: Ipv4 | null;
}

/** What evaluating a set of lists in order produced — shared by both selection modes. */
interface ListRun {
  evidence: HopEvidence[];
  caveats: string[];
  denial: HopEvidence | null;
  indeterminate: HopEvidence | null;
  denialDecision: AclEval["decision"];
  indeterminateDecision: AclEval["decision"];
}

type BindingOf = (name: string) => AclBindingFact | null;

function runLists(
  host: string,
  flow: Flow,
  srcIp: Ipv4,
  dstIp: Ipv4,
  named: Record<string, AclLine[]>,
  names: readonly string[],
  bindingOf: BindingOf,
): ListRun {
  const evidence: HopEvidence[] = [];
  const caveats: string[] = [];
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
        const ev2 = aclEvidence(host, name, line, lines.length, action === "deny" ? "denies this flow" : "permits this flow");
        evidence.push(ev2);
        if (action === "deny" && denial === null) {
          denial = ev2;
          denialDecision = { aclName: name, lineIndex: line.index, lineCount: lines.length, raw: line.raw, binding: bindingOf(name) };
        }
        decided = true;
        const snapshotVerdict = ACL_FINDING_BY_CITE.get(line.cite);
        if (snapshotVerdict !== undefined || setAside.length > 0) {
          caveats.push(
            `${host} ACL ${name} ${aclLineName(line.index, lines.length)} (${line.cite}) decides this flow` +
              (snapshotVerdict === undefined
                ? ""
                : `, and the snapshot's own acl_line_reachability marks that line ${String(snapshotVerdict.verdict).toUpperCase()} in general (${snapshotVerdict.detail ?? "no detail recorded"})`) +
              (setAside.length === 0
                ? ". That verdict is about the line across all flows; for this flow no unevaluable line above it can match."
                : `. For this flow ${setAside.join("; ")}, so the line above it cannot fire here — which is a claim about this flow only, not about the line in general.`),
          );
        }
      } else {
        evidence.push(aclEvidence(host, name, line, lines.length, "would match, but an earlier unevaluable line may fire first"));
        decided = true;
      }
      break;
    }

    if (poisonedBy !== null) {
      const ev2 = aclEvidence(host, name, poisonedBy.line, lines.length, `cannot be evaluated — ${poisonedBy.why}`);
      evidence.push(ev2);
      if (indeterminate === null) {
        indeterminate = ev2;
        indeterminateDecision = { aclName: name, lineIndex: poisonedBy.line.index, lineCount: lines.length, raw: poisonedBy.line.raw, binding: bindingOf(name) };
      }
      caveats.push(
        `${host} ACL ${name} ${aclLineName(poisonedBy.line.index, lines.length)} (${poisonedBy.line.cite}) "${poisonedBy.line.raw ?? "text not collected"}" could match this flow but ${poisonedBy.why}; no verdict below it can be proven.`,
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
        denialDecision = { aclName: name, lineIndex: null, lineCount: lines.length, raw: null, binding: bindingOf(name) };
      }
    }
  }


  return { evidence, caveats, denial, indeterminate, denialDecision, indeterminateDecision };
}

/**
 * Why this hop fell back to the specificity rule, in one clause. Every sentence that used to say
 * "no access-group binding was collected" now says WHICH binding was not observed and why — the
 * old sentence was false for this snapshot, which binds two lists on core1.
 */
function bindingGapClause(pb: PathBindings | null): string {
  if (pb === null) return "no interface binding was consulted for this evaluation";
  const parts = pb.unknown.map((u) => `${u.intf ?? "an unresolved interface"} ${u.dir} (${u.reason})`);
  return `the ACL binding at ${parts.join("; ")} was not observed`;
}

/**
 * `named` is a parameter so the ACL half of the engine can be driven with a REAL ACL set that is
 * not core1's — the only host in this snapshot that has one. Producer output for a construct this
 * fabric happens not to contain (`eq citrix`, `eq 443 8443`) is still real producer output, and
 * this is the seam that lets it reach the same code path a trace uses.
 *
 * `path` is the ingress and egress interface of this hop. When given, the OBSERVED bindings of those
 * interfaces decide which lists apply (see ./bindings.ts); the address-specificity rule is used only
 * when one of those bindings is unknown, and the hop then says which one and why. Without `path`
 * (the unit-test seam) no binding is consulted and the specificity rule runs as before.
 */
export function evaluateAcls(
  host: string,
  flow: Flow,
  srcIp: Ipv4,
  dstIp: Ipv4,
  named: Record<string, AclLine[]> = aclsOf(host),
  path?: HopInterfaces,
): AclEval {
  const pb = path === undefined || Object.keys(named).length === 0 ? null : pathBindings(host, path.ingress, path.egress, srcIp, path.egressTarget === undefined ? dstIp : path.egressTarget);
  if (pb !== null && pb.unknown.length === 0) return evaluateObservedBindings(host, flow, srcIp, dstIp, named, pb);
  /* A denial by a list that IS observed bound on this path stands even when another binding here is
     unknown: an unknown filter can only drop more, never admit what a bound list drops. Only a
     result that would let the flow through depends on the unknown binding, so only that case falls
     back to the specificity rule. */
  if (pb !== null && pb.bound.length > 0) {
    const observed = evaluateObservedBindings(host, flow, srcIp, dstIp, named, pb);
    if (observed.verdict === "deny") return observed;
  }
  return evaluateBySpecificity(host, flow, srcIp, dstIp, named, pb);
}

/** Every binding on the path was observed: apply exactly the bound lists, nothing else. */
function evaluateObservedBindings(
  host: string,
  flow: Flow,
  srcIp: Ipv4,
  dstIp: Ipv4,
  named: Record<string, AclLine[]>,
  pb: PathBindings,
): AclEval {
  const caveats = [...pb.notes];
  const where = pb.states.map((st) => `${st.intf ?? "?"} ${st.dir}`).join(", ");
  const boundNames = [...new Set(pb.bound.map((b) => b.acl))];
  const unbound = Object.keys(named)
    .sort()
    .filter((n) => !boundNames.includes(n));
  const incomplete = pb.unknown.length > 0;
  if (incomplete) {
    caveats.push(
      `At ${host}, ${pb.unknown.map((u) => `the ${u.dir === "in" ? "inbound" : "outbound"} binding on ${u.intf ?? "an unresolved interface"} (${u.reason})`).join("; ")} was not observed; a filter there can only drop more traffic, so it cannot undo the denial below.`,
    );
  } else if (unbound.length > 0) {
    caveats.push(
      `${host} also defines ${unbound.join(", ")}, bound to none of the interfaces this flow crosses at ${host} (${where}; observed running configuration), so ${unbound.length === 1 ? "it does" : "they do"} not filter this flow here.`,
    );
  }
  if (pb.bound.length === 0) {
    return { verdict: "not-applicable", decidedBy: null, evidence: pb.evidence, caveats, decision: null, bindingMode: "observed" };
  }
  const missing = pb.bound.filter((b) => named[b.acl] === undefined);
  const present = boundNames.filter((n) => named[n] !== undefined);
  const bindingOf: BindingOf = (name) => {
    const b = pb.bound.find((x) => x.acl === name);
    return b === undefined ? null : { intf: b.intf, dir: b.dir, cite: b.cite };
  };
  const run = runLists(host, flow, srcIp, dstIp, named, present, bindingOf);
  const missingEv: HopEvidence[] = missing.map((b) => ({
    kind: "absence",
    label: `${host} ${b.intf} applies ACL ${b.acl} ${b.dir === "in" ? "inbound" : "outbound"}, but the lines of ${b.acl} were not collected, so what it does to this flow is unknown`,
    raw: null,
    cite: b.cite,
  }));
  const bindingEv = pb.states.filter((st) => st.kind !== "unknown").map(bindingEvidence);
  const evidence = [...run.evidence, ...missingEv, ...(incomplete ? bindingEv : pb.evidence)];
  caveats.push(...run.caveats);
  if (run.denial !== null) {
    return { verdict: "deny", decidedBy: run.denial, evidence, caveats, decision: run.denialDecision, bindingMode: "observed" };
  }
  if (run.indeterminate !== null) {
    return { verdict: "indeterminate", decidedBy: run.indeterminate, evidence, caveats, decision: run.indeterminateDecision, bindingMode: "observed" };
  }
  const firstMissing = missingEv[0];
  if (firstMissing !== undefined) {
    return { verdict: "indeterminate", decidedBy: firstMissing, evidence, caveats, decision: null, bindingMode: "observed" };
  }
  const decidedByPermit = run.evidence.find((e) => e.kind === "acl") ?? null;
  return { verdict: "permit", decidedBy: decidedByPermit, evidence, caveats, decision: null, bindingMode: "observed" };
}

/**
 * The fallback: at least one binding this hop depends on was not observed (or none was consulted),
 * so the list to apply is chosen by the address-specificity rule — plus every list that IS
 * observed bound on this hop's interfaces.
 */
function evaluateBySpecificity(
  host: string,
  flow: Flow,
  srcIp: Ipv4,
  dstIp: Ipv4,
  named: Record<string, AclLine[]>,
  pb: PathBindings | null,
): AclEval {
  const gap = bindingGapClause(pb);
  const boundHere = (pb?.bound ?? []).map((b) => b.acl).filter((n) => named[n] !== undefined);
  const names = [...new Set([...boundHere, ...selectAcls(named, srcIp, dstIp)])];
  const bindingOf: BindingOf = (name) => {
    const b = pb?.bound.find((x) => x.acl === name);
    return b === undefined ? null : { intf: b.intf, dir: b.dir, cite: b.cite };
  };
  const bindingEv = pb?.evidence ?? [];
  const notes = pb?.notes ?? [];
  /* Undecidability is a property of the DECIDING HOST, not of the list the heuristic happened to
     pick. Computed for both branches below and appended to `evidence` LAST, so it lowers the
     badge without ever becoming the thing a verdict says it was decided by. */
  const unappliedUndecidable = undecidableInUnappliedAcls(host, named, names, flow, srcIp, dstIp, gap);
  if (names.length === 0) {
    const only = notAppliedCaveat(host, named, [], flow, srcIp, dstIp, gap);
    const first = unappliedUndecidable[0];
    /* Same rule as the tail of this function: a line on this host that could match and cannot be
       evaluated means no ACL verdict here is decidable, so "not-applicable" (which lets the trace
       go on to claim a clean delivery) would be a permit by omission. */
    if (first !== undefined) {
      const n = unappliedUndecidable.length;
      return {
        verdict: "indeterminate",
        decidedBy: first,
        evidence: [...unappliedUndecidable, ...bindingEv],
        caveats: [
          ...notes,
          ...(only === null ? [] : [only]),
          `${host} holds ${n} ${n === 1 ? "line" : "lines"} in access lists the specificity rule did not apply which could ` +
            `match this flow and cannot be evaluated (${unappliedUndecidable.map((e) => e.cite).join(", ")}). ` +
            `Because ${gap}, the ACL result at ${host} is indeterminate, not a permit.`,
        ],
        decision: null,
        bindingMode: "specificity",
      };
    }
    return {
      verdict: "not-applicable",
      decidedBy: null,
      evidence: [...unappliedUndecidable, ...bindingEv],
      caveats: [...notes, ...(only === null ? [] : [only])],
      decision: null,
      bindingMode: "specificity",
    };
  }
  const caveats: string[] = [...notes];
  const unapplied = notAppliedCaveat(host, named, names, flow, srcIp, dstIp, gap);
  if (unapplied !== null) caveats.push(unapplied);
  const run = runLists(host, flow, srcIp, dstIp, named, names, bindingOf);
  const evidence = [...run.evidence];
  caveats.push(...run.caveats);
  const { denial, indeterminate, denialDecision, indeterminateDecision } = run;

  /* Appended after every applied-ACL item so the applied line that matched is still listed first.
     These items used to "change the badge, not the verdict" — and that split was the defect: the
     trace said `delivered`, the hop rendered a green RESOLVED "delivered", the intent search counted
     it as a DECIDED contradiction and the counterexample search offered it as a proven success,
     while the caveat directly beneath said "never a definite permit". A permit that steps over an
     undecidable line that could match is not a permit, so the VERDICT now follows the caveat: no
     denial ⇒ indeterminate, decided by the first such line. A denial still stands — a list that
     denies the flow is not made less denying by a second list we cannot read. */
  if (unappliedUndecidable.length > 0) {
    evidence.push(...unappliedUndecidable);
    const n = unappliedUndecidable.length;
    caveats.push(
      `${host} holds ${n} ${n === 1 ? "line" : "lines"} in access lists the specificity rule did not apply which could ` +
        `match this flow and cannot be evaluated (${unappliedUndecidable.map((e) => e.cite).join(", ")}). ` +
        `Because ${gap}, a verdict here steps over ${n === 1 ? "it" : "them"}: ` +
        `it is at best indeterminate, never a definite permit.`,
    );
  }

  if (denial !== null) return { verdict: "deny", decidedBy: denial, evidence: [...evidence, ...bindingEv], caveats, decision: denialDecision, bindingMode: "specificity" };
  if (indeterminate !== null) {
    return { verdict: "indeterminate", decidedBy: indeterminate, evidence: [...evidence, ...bindingEv], caveats, decision: indeterminateDecision, bindingMode: "specificity" };
  }
  const firstUnapplied = unappliedUndecidable[0];
  if (firstUnapplied !== undefined) {
    return { verdict: "indeterminate", decidedBy: firstUnapplied, evidence: [...evidence, ...bindingEv], caveats, decision: null, bindingMode: "specificity" };
  }
  const decidedByPermit = evidence.find((e) => e.kind === "acl") ?? null;
  return { verdict: "permit", decidedBy: decidedByPermit, evidence: [...evidence, ...bindingEv], caveats, decision: null, bindingMode: "specificity" };
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

/**
 * When set, the ingress chooser puts this host first among the FHRP/SVI candidates instead of the
 * observed Active member. Set ONLY by `traceVia` below, for the duration of one `traceFlow` call, so
 * the alternate ingress a trace's own caveat names ("traffic may enter via core2") is traced too.
 */
let ingressOverride: string | null = null;

/** The ingress candidate ordering, shared by resolution and the alternate-ingress check. */
function orderIngress<T extends { host: string; fhrpRole: string | null }>(xs: readonly T[]): T[] {
  const sorted = [...xs].sort(
    (a, b) =>
      Number(isActive(b.fhrpRole)) - Number(isActive(a.fhrpRole)) ||
      Number(hasRib(b.host)) - Number(hasRib(a.host)) ||
      a.host.localeCompare(b.host),
  );
  const pin = ingressOverride;
  if (pin === null || !sorted.some((s) => s.host === pin)) return sorted;
  return [...sorted.filter((s) => s.host === pin), ...sorted.filter((s) => s.host !== pin)];
}

/** One host the source's traffic could enter the routed fabric by, with the record that says so. */
export interface IngressCandidate {
  host: string;
  /** How the candidate's role is spelled for prose, e.g. "HSRP Standby" or "no FHRP role observed". */
  role: string;
  cite: Cite;
}

/**
 * Every host an FHRP group or a shared SVI subnet offers as this source's first routed hop, in the
 * order `resolveIngress` ranks them (the chosen one first). The SAME ordering function drives both,
 * so the alternates named here are exactly the ones the trace's caveat says it did not take. Empty
 * when the source resolves by a connected route or an endpoint record alone.
 */
export function ingressCandidates(ip: Ipv4): IngressCandidate[] {
  const role = (fhrp: string | null, r: string | null): string => (r === null ? "no FHRP role observed" : `${fhrp ?? "FHRP"} ${r}`);
  const out: IngressCandidate[] = [];
  const push = (c: IngressCandidate): void => {
    if (!out.some((o) => o.host === c.host)) out.push(c);
  };
  const owners = ADDRESS_OWNERS.get(ip);
  if (owners !== undefined && owners.length > 0) {
    for (const o of orderIngress(owners)) push({ host: o.host, role: role(o.fhrp, o.fhrpRole), cite: o.cite });
    return out;
  }
  for (const s of orderIngress(SVI_SUBNETS.filter((x) => prefixContains(x.prefix, ip)))) {
    push({ host: s.host, role: role(s.record.fhrp, s.fhrpRole), cite: s.record.cite });
  }
  return out;
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
    const sorted = orderIngress(owners);
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
    const sorted = orderIngress(inSubnet);
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

/* How a route's administrative distance RANKS (a connected/local null ranks as 0) and how it READS
   are decided by one owner, core/route-fields.ts — a leaf module, so importing it makes no cycle. */
const adminDistanceOf = adminDistanceRank;

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
      caveat = `${tied.length} routes at ${host} tie at /${topBits} for ${formatIpv4(dstIp)}; the lowest administrative distance (${routeFieldReading(winner, "adminDistance").text}) was followed and equal-cost paths were not explored.`;
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
  return `ACL ${d.aclName} ${aclLineName(d.lineIndex, d.lineCount)}`;
}

const SCOPE_PHRASE = `Under the collected RIBs of ${ROUTABLE.join(" and ")} only (${ROUTABLE.length} of ${HOST_COUNT} hosts in this topology)`;

/**
 * The scope clause THIS trace's claim opens with, read from the claim itself — or null when the claim
 * does not open with it. A surface that re-states a verdict away from its card (a palette row, a
 * preset, an announcement) carries this clause, so the words it prints are bounded by the same
 * sentence the engine wrote, not by a restatement of the denominator (acceptance B2). Null is a
 * finding, never an empty string: a claim without its scope must be visible as one.
 */
export function scopeClauseOf(trace: Trace): string | null {
  return trace.claim.startsWith(SCOPE_PHRASE) ? SCOPE_PHRASE : null;
}

function baseCaveats(): string[] {
  return [
    `Forwarding is modelled only from the RIBs collected for ${ROUTABLE.join(", ")}; ${UNROUTABLE_COUNT} of ${HOST_COUNT} hosts in this topology have no collected routing table, so nothing can be proven about forwarding on them.`,
    ...bindingCoverageSentences(),
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

/**
 * The policy-gap kinds that leave a refusal (denied / dropped) undecided. One owner: the engine's
 * claim sentence and `claims.ts :: isDecidedOutcome` (band, badge, intent tally) both read it, so the
 * sentence cannot call decided what the band calls undecided. An uncollected ACL or an unobserved
 * ingress port can only refuse EARLIER, so neither can turn a refusal into a pass.
 */
export const REFUSAL_UNDECIDING_KINDS: ReadonlySet<PolicyGap["kind"]> = new Set<PolicyGap["kind"]>([
  "acl-unbound-denial",
  "ingress-alternate",
  "rib-partial",
]);

/* ── why a trace consulted no device ─────────────────────────────────────────── */

/**
 * Why a trace ended before any device was consulted (zero hops), as the engine decided it.
 *
 * A surface that has only `hops.length === 0` to go on cannot tell these apart, and one did not: the
 * intent search labelled every hop-less trace "the source address is outside every subnet this
 * collection observed" — including 20 flows inside 10.0.10.0/24, an observed subnet, that the engine
 * had declined as intra-subnet L2 (2026-09-22 critic, B1). The reason is recorded HERE, at each
 * zero-hop return, so the classification is the engine's own decision rather than a reader's
 * reconstruction from the claim prose. `refusalOf` is null for every trace that consulted a device.
 */
export type RefusalKind =
  | "invalid-address"
  | "invalid-flow"
  | "not-a-host-address"
  | "intra-subnet"
  | "router-originated"
  | "outside-observed-subnets";

/**
 * The refusals that say "this was not a valid question" rather than anything about the network: a
 * malformed address, or a port/protocol field that is not one (`flowProblems`, ./ip.ts). One set,
 * read by `claims.ts :: isInvalidInput`, so a new malformed-input kind cannot wear OUT OF SCOPE.
 */
export const INVALID_INPUT_REFUSALS: ReadonlySet<RefusalKind> = new Set<RefusalKind>(["invalid-address", "invalid-flow"]);

export interface Refusal {
  kind: RefusalKind;
  /** Groups refusals that share one piece of evidence (the kind, plus the subnet where there is one). */
  key: string;
  /** One clause, suitable after "N flows: ". Names the evidence, never guesses past it. */
  reason: string;
  cite: Cite;
}

const REFUSALS = new WeakMap<Trace, Refusal>();

export function refusalOf(trace: Trace): Refusal | null {
  return REFUSALS.get(trace) ?? null;
}

function refuse(refusal: Refusal, trace: Trace): Trace {
  REFUSALS.set(trace, refusal);
  return trace;
}

/**
 * A hop whose outcome was reached through a route chosen from a table the snapshot itself shows to
 * be incomplete (./rib-completeness.ts). "No route" was the only route decision this used to ask
 * about; a CHOSEN route from a partial table is the same absence in disguise: core1's table lacks
 * any OSPF route although its OSPF adjacency with 10.0.99.2 is FULL, so the static 10.0.0.0/16
 * summary won, egress resolved to Vlan30, and PROTECT_SERVERS "decided" a denial on an interface
 * the packet may never leave by (2026-09-22 critic, B1 blocker).
 *
 * A connected or local route (or a local SVI) containing the destination is not UNDECIDED by this
 * rule, but it is no longer SILENT either. It used to be exempt outright on the premise that "nothing
 * a missing protocol installs outranks a directly connected subnet" — false under longest-prefix
 * match: an OSPF, BGP or static route more specific than the connected /24 would win. core1's table
 * is shown incomplete, yet a delivery on its connected 10.0.30.0/24 carried no word about the partial
 * table (2026-09-22 auditor, B2). It was then only DISCLOSED, keeping the decided band — which still
 * rendered the uncollected BGP/EIGRP routes, and the OSPF routes of a FULL adjacency the table holds
 * none of, as "no more-specific route exists": absence as a decided result (2026-09-22 auditor, B1).
 * Every non-/32 connected basis on a table the snapshot shows incomplete is now UN-DECIDED exactly
 * like a static one (a /32 is the one case the premise holds for: nothing is longer, and connected
 * wins an equal-length tie on administrative distance 0). The rule reads the route's source and
 * prefix length and the host's own completeness record, never a list of hosts.
 */
const PARTIAL_ROUTE_BASIS = new WeakMap<Hop, { route: RouteEntry; sentence: string }>();

function notePartialRouteBasis(hop: Hop, host: string, win: RouteEntry, dstIp: Ipv4, caveats: string[]): void {
  const directlyAttached =
    win.source === "connected" ||
    win.source === "local" ||
    SVI_SUBNETS.some((s) => s.host === host && prefixContains(s.prefix, dstIp));
  const sentence = ribIncompletenessSentence(host);
  if (sentence === null) return;
  if (directlyAttached) {
    /* A /32 is the one connected basis nothing can outrank: no prefix is longer, and connected wins
       an equal-length tie on administrative distance 0. Every other connected basis is un-decided
       exactly like a static one — see the comment above. */
    if (parsePrefix(win.prefix)?.bits === 32) return;
    PARTIAL_ROUTE_BASIS.set(hop, { route: win, sentence });
    caveats.push(
      `${host} reached this destination on its ${win.source ?? "unlabelled"} ${win.prefix} (${win.cite}), a route chosen from a table the snapshot shows to be incomplete: ${sentence}. Under longest-prefix match a more specific route the table does not hold would outrank this subnet, so the outcome at ${host} is not decided.`,
    );
    return;
  }
  PARTIAL_ROUTE_BASIS.set(hop, { route: win, sentence });
  caveats.push(
    `The route ${host} followed (${win.source ?? "unlabelled"} ${win.prefix}, ${win.cite}) was chosen from a table the snapshot shows to be incomplete: ${sentence}. A route the table does not hold may carry this flow by another interface, so the outcome at ${host} is not decided.`,
  );
}

/* ── traffic addressed to a device itself ──────────────────────────────────────
   What IS and is NOT modelled for a destination a collected device owns (acceptance B8):
    - modelled: forwarding up to the owning device, every transit filter on the way, and the
      owning device's OBSERVED inbound interface ACL on the interface the packet arrives by — an
      inbound access-group filters every packet received on the interface, including packets
      addressed to the router, so a denial by it is a real refusal;
    - NOT modelled: an OUTBOUND ACL on the interface that owns the address (the packet is received,
      not switched out of that interface, so the list does not see it), and everything that decides
      whether the device ACCEPTS traffic addressed to itself — control-plane policing,
      management-plane and service access lists (a VTY access-class, an SNMP or HTTP server list).
   So such a flow is never "delivered" and never refused by an outbound list: it is a decided denial
   only when an observed inbound list denies it, and indeterminate otherwise. */

const CONTROL_PLANE_UNMODELLED =
  "how a device treats traffic addressed to itself — control-plane policing, management-plane and service access lists such as a VTY access-class — is not modelled";

interface Received {
  hop: Omit<Hop, "index">;
  outcome: TraceOutcome;
  claim: string;
  caveats: string[];
}

function ownerEvidence(owner: OwnedAddress): HopEvidence {
  return { kind: owner.kind, label: `${owner.label} is an address of ${owner.host} itself`, raw: null, cite: owner.cite };
}

function receivedAtOwner(
  host: string,
  flow: Flow,
  srcIp: Ipv4,
  dstIp: Ipv4,
  owner: OwnedAddress,
  ingressIntf: string | null,
  carried: HopEvidence[],
): Received {
  const named = aclsOf(host);
  const where = ingressIntf ?? "an interface this collection could not resolve";
  /* Inbound side only: the egress is not an interface here, so every outbound state is dropped
     before anything is evaluated — no outbound list can reach the decision, not even as the
     address-specificity fallback (which would pick PROTECT_SERVERS for a 10.0.30.x address). */
  const all = Object.keys(named).length === 0 ? null : pathBindings(host, ingressIntf, null, srcIp, null);
  const states = all === null ? [] : all.states.filter((s) => s.dir === "in");
  const pb: PathBindings | null =
    all === null
      ? null
      : {
          states,
          bound: all.bound.filter((b) => b.dir === "in"),
          unknown: all.unknown.filter((u) => u.dir === "in"),
          evidence: states.map(bindingEvidence),
          notes: all.notes,
        };
  const inbound = pb !== null && pb.bound.length > 0 ? evaluateObservedBindings(host, flow, srcIp, dstIp, named, pb) : null;
  const ownerEv = ownerEvidence(owner);
  const received = `${flow.dstIp} is ${owner.label} (${owner.cite}), an address of ${host} itself, so the packet is received by ${host} rather than forwarded out of that interface`;

  if (inbound !== null && inbound.verdict === "deny" && inbound.decidedBy !== null) {
    const bound = inbound.decision?.binding ?? null;
    return {
      hop: {
        host,
        outIntf: null,
        nextHop: null,
        nextHost: null,
        verdict: "denied",
        decidedBy: inbound.decidedBy,
        evidence: [...carried, ...inbound.evidence, ownerEv],
        alternatives: [],
      },
      outcome: "denied",
      claim: `${SCOPE_PHRASE}, ${flowPhrase(flow)} is denied at ${host} by ${denialPhrase(inbound)} (${inbound.decidedBy.cite}${inbound.decidedBy.raw === null ? "" : `: "${inbound.decidedBy.raw}"`}); the list is applied inbound on ${host} ${bound?.intf ?? where}${bound === null ? "" : ` (${bound.cite})`}, which filters every packet received there, including packets addressed to ${host} itself. ${received}; stateful return traffic is not modelled.`,
      caveats: [...inbound.caveats],
    };
  }

  const inboundState =
    pb === null
      ? `no ACLs were collected for ${host}, so its inbound filtering on ${where} is unobserved, not absent`
      : pb.unknown.length > 0
        ? `the inbound binding on ${where} was not observed (${pb.unknown.map((u) => u.reason).join("; ")})`
        : inbound === null
          ? `no inbound list is bound on ${where} in the observed running configuration`
          : inbound.verdict === "permit"
            ? `the inbound list on ${where} lets it through${inbound.decidedBy === null ? "" : ` (${inbound.decidedBy.cite})`}`
            : `the inbound list on ${where} cannot be evaluated for this flow${inbound.decidedBy === null ? "" : ` (${inbound.decidedBy.cite})`}`;
  return {
    hop: {
      host,
      outIntf: null,
      nextHop: null,
      nextHost: null,
      verdict: "unmodeled",
      decidedBy: {
        kind: "absence",
        label: `${flow.dstIp} is addressed to ${host} itself (${owner.label}): the packet is received by ${host}, not forwarded out of an interface, so no outbound interface ACL decides it, and ${CONTROL_PLANE_UNMODELLED}`,
        raw: null,
        cite: owner.cite,
      },
      evidence: [...carried, ...(inbound?.evidence ?? pb?.evidence ?? []), ownerEv],
      alternatives: [],
    },
    outcome: "indeterminate",
    claim: `${SCOPE_PHRASE}, ${flowPhrase(flow)} is not decided: ${received}. An outbound interface ACL does not filter traffic addressed to the router, so none was applied; ${inboundState}; and ${CONTROL_PLANE_UNMODELLED}, so no forwarding or filtering outcome is claimed.`,
    caveats: [
      ...(inbound?.caveats ?? pb?.notes ?? []),
      `Traffic addressed to ${host} itself is outside this model beyond its inbound interface ACL: ${CONTROL_PLANE_UNMODELLED}. Re-run toward a host behind ${host} to ask about transit traffic.`,
    ],
  };
}

/**
 * When the destination is owned by a collected device OTHER than the one delivering onto its subnet:
 * the reason a pass there is not a delivery, and the ownership record. Null when no device owns it.
 */
function receivedElsewhereEvidence(dstIp: Ipv4): { decidedBy: HopEvidence; owner: HopEvidence; caveat: string } | null {
  const owners = ADDRESS_OWNERS.get(dstIp);
  if (owners === undefined || owners.length === 0) return null;
  const who = distinctHosts(owners).join(", ");
  const first = owners[0]!;
  return {
    decidedBy: {
      kind: "absence",
      label: `${formatIpv4(dstIp)} is ${first.label}, an address of ${who} itself, so the packet is received by ${who}; its inbound interface ACLs and its control-plane policy decide whether it is accepted, and neither is modelled for traffic arriving there`,
      raw: null,
      cite: first.cite,
    },
    owner: ownerEvidence(first),
    caveat: `Traffic addressed to ${who} itself is outside this model once it leaves the delivering interface: ${CONTROL_PLANE_UNMODELLED}.`,
  };
}

export function traceFlow(flow: Flow): Trace {
  /* determinism: start of the elapsed-time measurement above; feeds `elapsedMs` and nothing else.
     No branch in this function reads it, so no trace outcome can depend on it. */
  const startedAt = performance.now();
  WORK.traces += 1;

  /* ENTRY CHECK — every field, not only the addresses. The type says `dstPort: number`, and a link
     once delivered `NaN` in it: the walk below then answered "a tcp/NaN flow … is delivered" (2026-09-23
     acceptance report, B1). `flowProblems` is the one validator the form and the link also use, so
     the engine refuses exactly what they refuse, and names the field. */
  const problems = flowProblems(flow);
  if (problems.length > 0) {
    const addressOnly = problems.every((p) => p.field === "srcIp" || p.field === "dstIp");
    const fields = [...new Set(problems.map((p) => flowFieldName(p.field)))];
    return refuse({
      kind: addressOnly ? "invalid-address" : "invalid-flow",
      key: addressOnly ? "invalid-address" : "invalid-flow",
      reason: `the flow's ${fields.join(", ")} ${fields.length === 1 ? "is" : "are"} not valid${addressOnly ? " (not an IPv4 address)" : ""}, so nothing was simulated`,
      cite: fabric.coverage.cite,
    }, finish(
      flow,
      "out-of-scope",
      [],
      /* Every verdict carries the scope in the SENTENCE, not only in the caveat list below it.
         The out-of-scope returns used to be the exception — measured over a 343-flow sweep, all 49
         out-of-scope claims omitted the 2-of-26 RIB denominator that all 294 other claims carried
         inline, leaving a reader who reads the verdict and the badge but not the eight caveats
         with no idea how narrow the collection is. */
      `${SCOPE_PHRASE}, the question is not a valid flow: ${problems
        .map((p) => describeFlowProblem(p, { where: "question", protocol: String(flow.protocol) }).problem)
        .join(" ")} Nothing was simulated.`,
      ["The flow was rejected before any evidence was consulted; this says nothing about the network."],
      [],
      startedAt,
    ));
  }
  /* Valid by the check above; re-read as numbers for the walk. */
  const srcIp = parseIpv4(flow.srcIp)!;
  const dstIp = parseIpv4(flow.dstIp)!;

  // A packet cannot originate from the network or directed-broadcast address of a subnet, so a
  // trace from one is not a narrower answer — it is a question about a host that does not exist.
  const srcSubnet = narrowestObservedSubnet(srcIp);
  const srcRole = srcSubnet === null ? "host" : addressRoleIn(srcSubnet.prefix, srcIp);
  if (srcSubnet !== null && srcRole !== "host") {
    return refuse({
      kind: "not-a-host-address",
      key: `not-a-host-address|${formatPrefix(srcSubnet.prefix)}`,
      reason: `the source is the network or directed-broadcast address of ${formatPrefix(srcSubnet.prefix)} (${srcSubnet.label}), not a host address, so nothing was simulated`,
      cite: srcSubnet.cite,
    }, finish(
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
    ));
  }

  /* Both endpoints in ONE observed subnet: the flow never crosses a routed boundary. Between two
     hosts in a VLAN the traffic is bridged at L2 and never reaches the SVI's routed ACLs; toward a
     device's own address on that subnet it is addressed to the device, not routed through it. This
     model walks the RIB and routed-interface ACLs only, so it has nothing to say about either — it
     used to route 10.0.30.10 → 10.0.30.20 "Vlan30 in, Vlan30 out" through core1 and report a DECIDED
     denial by PROTECT_SERVERS, a model gap presented as an observed policy decision. The test is
     structural (the narrowest observed subnet of the source contains the destination), not a list
     of VLANs. Found by the 2026-09-21 critic (B1). */
  if (srcSubnet !== null && prefixContains(srcSubnet.prefix, dstIp)) {
    const where = `${formatPrefix(srcSubnet.prefix)} (${srcSubnet.label}, ${srcSubnet.cite})`;
    return refuse({
      kind: "intra-subnet",
      key: `intra-subnet|${formatPrefix(srcSubnet.prefix)}`,
      reason: `source and destination both lie in ${formatPrefix(srcSubnet.prefix)} (${srcSubnet.label}), a subnet this collection observed, so the flow stays inside one subnet — intra-subnet L2 forwarding, VLAN ACLs and port ACLs are outside this model, so no outcome was claimed`,
      cite: srcSubnet.cite,
    }, finish(
      flow,
      "indeterminate",
      [],
      `${SCOPE_PHRASE}, ${flowPhrase(flow)} is not decided: ${flow.srcIp} and ${flow.dstIp} both lie in ${where}, so the flow stays inside one subnet — it is bridged at L2, or addressed to a device on that subnet, and never crosses the routed interface where interface ACLs are evaluated. L2 forwarding, VLAN ACLs and port ACLs are not simulated, so no forwarding or filtering outcome is claimed.`,
      [
        `Traffic within ${formatPrefix(srcSubnet.prefix)} is outside this model: it walks collected RIBs and routed-interface ACLs, and a flow that never leaves its subnet meets neither. Its fate turns on L2 forwarding, VACLs and port ACLs, none of which is simulated.`,
        ...baseCaveats(),
      ],
      [],
      startedAt,
    ));
  }

  /* The source IS an address a collected device owns — an SVI address, an FHRP virtual address or a
     RIB `local` /32. Such a packet is originated by that device's own control plane: it does not
     arrive inbound on the SVI that carries the address, so that interface's inbound access-group
     does not filter it (IOS applies interface ACLs to transit traffic; output ACLs do not filter
     locally-originated packets by default), and it has no gateway port and no alternate FHRP
     ingress. The model only walks packets that ENTER a router, so tracing one anyway applied core1
     Vlan20's inbound VOICE_FILTER to core1's own 10.0.20.2 and reported a DECIDED, SCOPED denial —
     every decided verdict this fabric produced came from that shape (2026-09-22 auditor, B2). The
     test reads the address-ownership index every other rule reads, never a list of addresses, and it
     runs before an ingress is chosen, so no ingress, port or alternate claim is made about a flow
     that has none. */
  const srcOwners = ADDRESS_OWNERS.get(srcIp);
  if (srcOwners !== undefined && srcOwners.length > 0) {
    const ownerHosts = distinctHosts(srcOwners);
    const owner = srcOwners[0]!;
    const who = ownerHosts.join(", ");
    const device = ownerHosts.length === 1 ? "that device" : "one of those devices";
    return refuse({
      kind: "router-originated",
      key: `router-originated|${who}`,
      reason: `the source is ${owner.label}, an address of ${who} itself, so the flow would be originated by ${device} — inbound interface ACLs do not apply to locally-originated traffic and its own filtering is not modelled, so no outcome was claimed`,
      cite: owner.cite,
    }, finish(
      flow,
      "indeterminate",
      [],
      `${SCOPE_PHRASE}, ${flowPhrase(flow)} is not decided: ${flow.srcIp} is ${owner.label} (${owner.cite}), an address of ${who} itself, so this traffic would be originated by ${device} rather than arrive at it. Locally-originated traffic is not filtered by the inbound access-group of the interface that owns its address, and how a device filters and routes its own traffic is not modelled, so no forwarding or filtering outcome is claimed.`,
      [
        `Traffic sourced by ${who} itself is outside this model: it walks packets that enter a router and applies that router's interface ACLs, and a self-originated packet enters none. Re-run with a host address in the same subnet to ask about transit traffic.`,
        ...baseCaveats(),
      ],
      [],
      startedAt,
    ));
  }

  const ingress = resolveIngress(srcIp);
  if ("none" in ingress) {
    return refuse({
      kind: "outside-observed-subnets",
      key: "outside-observed-subnets",
      reason: "the flow was refused before any device was consulted — the source address is outside every subnet this collection observed",
      cite: fabric.coverage.cite,
    }, finish(
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
    ));
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
  /* The address the packet was last forwarded toward — the source on the first hop, the previous
     hop's next-hop address after that. The connected interface of THIS host that contains it is
     the interface the packet arrives on. */
  let arrivalIp: Ipv4 | null = srcIp;

  for (let index = 0; index < TTL_LIMIT; index += 1) {
    WORK.hops += 1;
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

    /* The DESTINATION is an address this host owns — the mirror of the router-originated refusal
       above. A packet addressed to the router's own interface is received by the router (punted to
       its control plane), not switched out of the interface that owns the address, so an OUTBOUND
       interface ACL on that interface does not decide it. It used to: 10.0.10.50 → 10.0.30.1
       (core1's own Vlan30 address) was "denied" on tcp/3389 and "delivered" on tcp/22 by
       PROTECT_SERVERS, a list bound outbound on Vlan30, and that pair was the one counterexample the
       product offered on real data (2026-09-22 acceptance report, B8). The test reads the same
       address-ownership index the source rule reads — every collected SVI, FHRP virtual and RIB
       `local` /32 address — never a list of addresses. See `receivedAtOwner`. */
    const receivedAs = (ADDRESS_OWNERS.get(dstIp) ?? []).find((o) => o.host === host);
    if (receivedAs !== undefined) {
      const r = receivedAtOwner(host, flow, srcIp, dstIp, receivedAs, arrivalIp === null ? null : connectedInterfaceFor(host, arrivalIp), carriedEvidence);
      hops.push({ ...r.hop, index });
      outcome = r.outcome;
      claim = r.claim;
      caveats.push(...r.caveats);
      break;
    }

    /* The route is chosen FIRST because it names the egress interface, and the egress interface is
       half of the question "which ACLs apply here" — the other half being the interface the packet
       arrived on. Both are resolved from collected evidence, never assumed. */
    const route = chooseRoute(host, dstIp);
    if (route?.caveat) caveats.push(route.caveat);
    const egress = route === null ? null : resolveEgress(host, route.winner, dstIp);
    const ingressIntf = arrivalIp === null ? null : connectedInterfaceFor(host, arrivalIp);

    const acl = evaluateAcls(host, flow, srcIp, dstIp, aclsOf(host), {
      ingress: ingressIntf,
      egress: egress?.intf ?? null,
      egressTarget:
        route === null || route.winner.source === "connected" || route.winner.source === "local" || route.winner.nextHop === null
          ? dstIp
          : parseIpv4(route.winner.nextHop),
    });
    if (acl.verdict === "indeterminate") aclIndeterminateSeen = true;
    caveats.push(...acl.caveats);
    if (Object.keys(aclsOf(host)).length === 0) {
      caveats.push(`No ACLs were collected for ${host}; filtering there is unobserved, not absent.`);
    } else if (acl.verdict === "not-applicable") {
      caveats.push(
        acl.bindingMode === "observed"
          ? `${Object.keys(aclsOf(host)).length} ACL(s) are defined on ${host}, and none is bound to the interfaces this flow enters (${ingressIntf ?? "unresolved"}) or leaves (${egress?.intf ?? "unresolved"}) by in the observed running configuration, so none was applied here.`
          : `${Object.keys(aclsOf(host)).length} ACL(s) are defined on ${host} but none names this flow's addresses specifically, so none was applied. Because a binding this hop depends on was not observed, that is an absence of evidence, not evidence of an unfiltered path.`,
      );
    }

    const evidence = [...carriedEvidence, ...acl.evidence];
    carriedEvidence = [];

    // ACL denial takes precedence over the routing result: an inbound filter drops the packet
    // before the FIB lookup matters, and naming the line is the more useful answer either way.
    if (acl.verdict === "deny" && acl.decidedBy !== null) {
      const ev = acl.decidedBy;
      hops.push({
        index,
        host,
        outIntf: egress?.intf ?? null,
        nextHop: route?.winner.nextHop ?? null,
        nextHost: null,
        verdict: "denied",
        decidedBy: ev,
        evidence: route ? [...evidence, routeEvidence(host, route.winner), ...(egress?.evidence ?? [])] : evidence,
        alternatives: route?.alternatives ?? [],
      });
      outcome = "denied";
      const bound = acl.decision?.binding ?? null;
      /* An inbound binding refuses the packet before the FIB lookup, so the route is not what
         decided it. Any other denial (outbound binding, or a list chosen by address specificity)
         was reached through the egress the route named. */
      if (route !== null && (bound === null || bound.dir !== "in")) notePartialRouteBasis(hops[hops.length - 1]!, host, route.winner, dstIp, caveats);
      claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} is denied at ${host} by ${denialPhrase(acl)} (${ev.cite}${ev.raw === null ? "" : `: "${ev.raw}"`}); ${
        bound === null
          ? "that list was chosen by the address-specificity rule because a binding on this hop was not observed"
          : `the list is applied ${bound.dir === "in" ? "inbound" : "outbound"} on ${host} ${bound.intf} (${bound.cite})`
      }, and stateful return traffic is not modelled.`;
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
      /* The table's completeness is itself evidenced — or contradicted — by the snapshot. When the
         routing protocols that populate it were not collected, or the control plane reports prefixes
         it does not hold, the drop is what a partial table says, and is named so (./rib-completeness.ts;
         `pathPolicyGaps` turns the same fact into an undecided input). */
      const partial = ribIncompletenessSentence(host);
      if (partial !== null) caveats.push(`${partial}, so this drop is not a decided absence of a route.`);
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
      /* The destination is an address ANOTHER collected device owns (this host does not — that case
         was taken above). This host really does switch the packet out of its connected interface, so
         its outbound ACL there is a real filter and a denial by it (the branch above) stands. But
         what arrives is addressed to that device itself, which receives it: its inbound ACLs and
         control-plane policy decide it, and neither is modelled here, so a pass is not a delivery. */
      const ownedElsewhere = nonHostEv === null && !undecided ? receivedElsewhereEvidence(dstIp) : null;
      hops.push({
        index,
        host,
        outIntf: egress?.intf ?? win.outIntf,
        nextHop: null,
        nextHost: null,
        // A hop that reads "delivered" inside an undecidable trace is a green tick over an unknown.
        // "unmodeled" is the honest verdict for this hop: the RIB got the packet here, the filter
        // could not be evaluated, so the outcome AT this hop was not modelled.
        verdict: undecided || nonHostEv !== null || ownedElsewhere !== null ? "unmodeled" : "delivered",
        decidedBy: nonHostEv ?? ownedElsewhere?.decidedBy ?? (undecided ? acl.decidedBy : routeEv),
        evidence: [...evidence, routeEv, ...sviEv, ...(nonHostEv === null ? [] : [nonHostEv]), ...(ownedElsewhere === null ? [] : [ownedElsewhere.owner])],
        alternatives: route.alternatives,
      });
      /* A delivery is a route decision too: the connected prefix it landed on was chosen from this
         host's table, and a partial table can hide a longer prefix that outranks it. */
      notePartialRouteBasis(hops[hops.length - 1]!, host, win, dstIp, caveats);
      /* The non-host case is named first: it is the more fundamental answer (there is no host to
         deliver to). When the ACL result is ALSO undecided, that is appended rather than hidden. */
      if (nonHostEv !== null) {
        outcome = "indeterminate";
        claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} is routed to ${host}'s ${win.source ?? "unlabelled"} ${win.prefix} (${win.cite}), but ${flow.dstIp} is that subnet's ${dstRole === "network" ? "network" : "directed-broadcast"} address rather than a host address, so what ${host} does with it cannot be decided from this collection.${
          undecided && acl.decidedBy !== null ? ` The ACL result there is also undecided: ${acl.decidedBy.label} (${acl.decidedBy.cite}).` : ""
        }`;
        caveats.push(
          `${flow.dstIp} addresses the subnet ${formatPrefix(deliveryPrefix!)} itself. Whether ${host} forwards, floods or discards it turns on \`ip directed-broadcast\` and platform defaults, neither of which was collected (${fabric.coverage.cite}).`,
        );
      } else if (undecided && acl.decidedBy !== null) {
        /* The forwarding fact and the filtering fact are stated separately: the RIB really does put
           the destination on a connected prefix here; what cannot be decided is whether a filter on
           this host lets it through. */
        outcome = "indeterminate";
        claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} reaches ${host}'s connected ${win.prefix} (${win.cite}), but the result cannot be decided: ${acl.decidedBy.label} (${acl.decidedBy.cite}).`;
      } else if (ownedElsewhere !== null) {
        outcome = "indeterminate";
        claim = `${SCOPE_PHRASE}, ${flowPhrase(flow)} is not decided: ${host} switches it out of its ${win.source ?? "unlabelled"} ${win.prefix} via ${win.outIntf ?? "an unnamed interface"} (${win.cite}), and ${host}'s own filtering there was evaluated, but ${ownedElsewhere.decidedBy.label}.`;
        caveats.push(ownedElsewhere.caveat);
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
      outIntf: egress?.intf ?? null,
      nextHop: win.nextHop,
      nextHost: next.host,
      verdict: acl.verdict === "indeterminate" ? "unmodeled" : "forwarded",
      decidedBy: acl.verdict === "indeterminate" ? acl.decidedBy : routeEv,
      evidence: [...evidence, routeEv, ...(egress?.evidence ?? []), ...(next.evidence === null ? [] : [next.evidence])],
      alternatives: route.alternatives,
    });
    notePartialRouteBasis(hops[hops.length - 1]!, host, win, dstIp, caveats);
    arrivalIp = win.nextHop === null ? null : parseIpv4(win.nextHop);

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
      const basis = PARTIAL_ROUTE_BASIS.get(last);
      if (basis !== undefined) PARTIAL_ROUTE_BASIS.set(hops[hops.length - 1]!, basis);
      caveats.push(`The trace was cut at the ${TTL_LIMIT}-hop cap; the path was longer than this fabric's diameter, which usually means a routing loop.`);
    }
  }

  // An indeterminate ACL ANYWHERE on the path withdraws a positive claim, even when a later hop
  // routes cleanly: we could not prove the packet got past the earlier filter. Tracked as a flag,
  // not by reading the caveat prose back — a guard that greps its own output stops guarding the
  // moment the wording changes.
  if (aclIndeterminateSeen && outcome === "delivered") outcome = "indeterminate";

  const trace = finish(flow, outcome, hops, claim, [...caveats, ...baseCaveats()], unmodelledHosts, startedAt);
  /* A delivery the engine itself does not rate as definite (a host passed with no collected ACLs,
     an evidence item recorded as an absence) is a ROUTING result, not a decided pass. The sentence
     used to read exactly like a fully-scoped delivery — "is delivered at core2 on connected route …"
     — so the one line a reader quotes carried none of the gap. The gap is now named in the claim
     itself, from the same inputs `isDefiniteDelivery` reads, never from a list of hosts. Found by
     the 2026-09-21 critic (B1). */
  if (trace.outcome === "delivered" && !isDefiniteDelivery(trace)) {
    return { ...trace, claim: `${trace.claim} ${undecidedDeliverySentence(trace)}` };
  }
  /* The same rule for a refusal. A drop at a host whose collected table the snapshot shows to be
     incomplete, a denial by a list whose binding was not observed, or either reached by an ingress an
     alternate FHRP member does not reproduce, is not a decided refusal — and the sentence said it was:
     "is dropped at core2: no prefix in its collected RIB matches …", announced to a screen reader as
     a definite drop while the card's headline read "not decided" (2026-09-22 critic, B2). The gap is
     named in the claim itself, from the gap kinds that undecide a refusal
     (`REFUSAL_UNDECIDING_KINDS`, which `claims.ts :: isDecidedOutcome` also reads). */
  if (trace.outcome === "denied" || trace.outcome === "dropped") {
    const undeciding = unobservedPolicyInputs(trace).filter((g) => REFUSAL_UNDECIDING_KINDS.has(g.kind));
    if (undeciding.length > 0) return { ...trace, claim: `${trace.claim} ${undecidedRefusalSentence(trace.outcome, undeciding)}` };
  }
  return trace;
}


/** Why a denial or drop is not a decided refusal, stated from the trace's own undeciding gaps. */
function undecidedRefusalSentence(outcome: "denied" | "dropped", gaps: readonly PolicyGap[]): string {
  const reasons: string[] = [];
  for (const g of gaps) if (!reasons.includes(g.label)) reasons.push(g.label);
  return `That ${outcome === "denied" ? "denial" : "drop"} is not decided: ${reasons.join("; ")}.`;
}

/** Why a "delivered" trace is not a decided pass, stated from the trace's own undecided inputs. */
export function undecidedDeliverySentence(t: Trace): string {
  const reasons: string[] = [];
  const add = (r: string): void => {
    if (!reasons.includes(r)) reasons.push(r);
  };
  for (const g of unobservedPolicyInputs(t)) add(g.label);
  for (const h of t.hops) {
    if (h.verdict === "unmodeled") add(`${h.host} is not modelled`);
    for (const e of h.evidence) if (e.kind === "absence") add(e.label);
  }
  return `That is a routing result, not a decided pass — filtering on this path was not decided: ${reasons.join("; ")}.`;
}

/**
 * The interface a packet leaves `host` by for this route.
 *
 * A static or default route that names only a next-hop address ("0.0.0.0/0 via 10.0.10.254") used
 * to be shown as "egress interface: not observed", as if evidence were missing. It is not: a router
 * resolves that next hop recursively through its own RIB, and the RIB we hold says 10.0.10.254 lies
 * in the connected 10.0.10.0/24 on Vlan10. That one recursive lookup is done here and BOTH records
 * are cited. It stops after one level, and only accepts a connected/local route that names an
 * interface — anything deeper is left unresolved rather than guessed.
 */
export function resolveEgress(
  host: string,
  win: RouteEntry,
  dstIp: Ipv4,
  routes: readonly RouteEntry[] = routesOf(host),
): { intf: string; evidence: HopEvidence[] } | null {
  if (win.outIntf !== null) return { intf: win.outIntf, evidence: [] };
  // A destination on a local SVI with no connected route in the RIB still leaves by that SVI.
  const svi = SVI_SUBNETS.find((s) => s.host === host && prefixContains(s.prefix, dstIp));
  if (svi !== undefined && (win.source === "connected" || win.source === "local") && svi.record.vlan !== null) {
    return {
      intf: `Vlan${svi.record.vlan}`,
      evidence: [{ kind: "svi", label: `${host} Vlan${svi.record.vlan} ${formatPrefix(svi.prefix)} contains ${formatIpv4(dstIp)}`, raw: svi.record.sviIp, cite: svi.record.cite }],
    };
  }
  if (win.nextHop === null) return null;
  const nh = parseIpv4(win.nextHop);
  if (nh === null) return null;
  const via = chooseRoute(host, nh, routes)?.winner ?? null;
  if (via === null || via === win || via.outIntf === null || (via.source !== "connected" && via.source !== "local")) return null;
  return {
    intf: via.outIntf,
    evidence: [
      {
        kind: "route",
        label: `${host} resolves next hop ${win.nextHop} recursively: it lies in ${via.source} ${via.prefix} out ${via.outIntf}`,
        raw: null,
        cite: via.cite,
      },
    ],
  };
}

function routeEvidence(host: string, r: RouteEntry): HopEvidence {
  return {
    kind: "route",
    label: `${host} longest-prefix match ${r.prefix} (${r.source ?? "source not recorded"}${r.nextHop === null ? "" : ` via ${r.nextHop}`}${r.outIntf === null ? "" : ` out ${r.outIntf}`})`,
    raw: null,
    cite: r.cite,
  };
}

/**
 * A delivery that nothing on its path left undecided. `traceFlow` already refuses to return
 * "delivered" over an indeterminate ACL; this is the same rule stated over the trace itself, for
 * every consumer that turns a delivery into a stronger claim (a counterexample offered as a proven
 * success, a flow counted as a decided contradiction of an intent). It reads the same inputs
 * `scopeTuple()` counts as indeterminate — an unmodelled hop or an evidence item recorded as an
 * absence — so a delivery that would render with an INDETERMINATE badge can never be promoted.
 */
export function isDefiniteDelivery(t: Trace): boolean {
  if (t.outcome !== "delivered" || t.hops.length === 0) return false;
  // A filter question nobody collected the evidence to ask is an undecided input too.
  if (unobservedPolicyInputs(t).length > 0) return false;
  return t.hops.every((h) => h.verdict !== "unmodeled" && h.evidence.every((e) => e.kind !== "absence"));
}

/**
 * A delivery with nothing left undecided ON THE MODELLED PATH — the same rule as
 * `isDefiniteDelivery` minus the ingress gaps (alternate FHRP ingress, unobserved physical ingress
 * port), which belong to the SOURCE rather than to the flow. Used only where a flow is compared
 * with another from the same source (the counterexample, the suggested-flow outcome label), so both
 * sides carry the identical ingress assumption; every such use restates that assumption. It never
 * decides a badge or a band — those read `isDefiniteDelivery`.
 */
export function isDefiniteOnModelledPath(t: Trace): boolean {
  if (t.outcome !== "delivered" || t.hops.length === 0) return false;
  if (pathPolicyGaps(t).length > 0) return false;
  return t.hops.every((h) => h.verdict !== "unmodeled" && h.evidence.every((e) => e.kind !== "absence"));
}

/* ── unobserved policy inputs ───────────────────────────────────────────────── */

/**
 * The filtering questions a trace left OPEN for want of evidence.
 *
 * Two shapes, both derived from the trace and the compiled coverage — never from a list of names:
 *
 *  - `acl-uncollected`: any host the trace traversed — passed, delivered at, or stopped at — that
 *    has no collected ACL. The trace used to treat that as a clean pass — SCOPED, "0 evidence items
 *    were indeterminate" — while its own caveat said "filtering there is unobserved, not absent".
 *    An unasked question is not a decided one.
 *  - `acl-unbound-denial`: a denial decided by a list whose `ip access-group` binding on this hop
 *    was NOT observed (so the specificity heuristic chose it). Whether that list is applied on this
 *    flow's path at all is then unknown: the configuration line is observed; that it filters this
 *    flow is not. A denial by a list whose binding the hop's evidence carries is exempt — that one
 *    is applied by evidence (see ./bindings.ts `hopHasObservedBinding`).
 *
 * Two more shapes sit BEFORE the modelled segment, which starts at the chosen gateway's SVI. Both
 * used to be invisible to every count, so a trace resting on them still earned SCOPED ("every
 * evidence item was decided") while its own caveat said the ingress was "not a guarantee" — absence
 * counted as decided. Found by the 2026-09-21 critic (B1):
 *
 *  - `ingress-alternate`: the source's first routed hop was chosen from an FHRP group / shared SVI
 *    subnet by a point-in-time role, and an alternate member is NOT modelled equivalently — traced
 *    from that member the flow ends differently, or rests on inputs of its own that were never
 *    observed (no collected ACLs, an unmodelled hop). The alternate is TRACED (`traceVia`), not
 *    judged by a list of names; an alternate that reproduces the same, fully decided outcome is not
 *    a gap.
 *  - `ingress-port-unobserved`: a physical port on the gateway that the source's frames could
 *    arrive by (./bindings.ts `physicalIngressStates`) has a binding state other than an observed
 *    "none" — running configuration not observed, or an access-group this model does not apply.
 *
 * Any of them caps the badge below SCOPED (`claimBadge`) and stops a delivery being definite (so it
 * is never offered as a counterexample or suggested as a delivery). An unbound denial and an
 * alternate ingress also make a denial an undecided — not a decided — contradiction of an intent.
 */
export interface PolicyGap {
  host: string;
  kind: "acl-uncollected" | "acl-unbound-denial" | "ingress-alternate" | "ingress-port-unobserved" | "rib-partial";
  label: string;
  cite: Cite;
}

/*
 * A fifth shape is about ROUTING, not filtering, and rides the same channel so every consumer that
 * already refuses to promote an unobserved input (badge, band, intent tally, T1) refuses this one too:
 *
 *  - `rib-partial`: a hop that ended the trace for want of a route (`no-route`) at a host whose
 *    collected routing table the snapshot itself shows to be incomplete — a route-populating
 *    protocol not collected there, or control-plane prefixes the table does not hold
 *    (./rib-completeness.ts). "No route" is then what a partial table says, not a decided absence.
 *    Found by the 2026-09-21 critic (B1 blocker): 60 no-route drops at core2 decided an intent while
 *    the snapshot recorded core2's OSPF/BGP/EIGRP as not_collected and a 240-prefix EVPN peer.
 */

/** How an alternate-ingress trace's own gap is summarised. Exhaustive over the kinds. */
function altGapPhrase(g: PolicyGap): string {
  switch (g.kind) {
    case "acl-uncollected":
      return `${g.host} has no collected ACLs`;
    case "acl-unbound-denial":
      return `the denying list at ${g.host} has no observed binding`;
    case "ingress-alternate":
      return `the ingress at ${g.host} is itself not modelled equivalently`;
    case "ingress-port-unobserved":
      return `the ingress port filtering at ${g.host} is unobserved`;
    case "rib-partial":
      return `the routing decision at ${g.host} rests on a table the snapshot shows to be incomplete`;
  }
  const exhaustive: never = g.kind;
  return exhaustive;
}

/** Hop verdicts at which the packet PASSED the host, so the host's filter was a live question. */
const PASSING: ReadonlySet<Hop["verdict"]> = new Set(["forwarded", "delivered", "ttl-exceeded"]);

/** Set while an alternate-ingress trace is being judged, so judging it cannot recurse into ITS alternates. */
let judgingAlternate = false;
const ALTERNATE_TRACES = new Map<string, Trace>();
const GAPS = new WeakMap<Trace, PolicyGap[]>();

/** The same flow, traced with `host` taken as its ingress. Memoised: the trace is deterministic. */
function traceVia(flow: Flow, host: string): Trace {
  const key = `${host}|${flow.srcIp}|${flow.dstIp}|${flow.protocol}|${flow.dstPort ?? ""}|${flow.srcPort ?? ""}`;
  const hit = ALTERNATE_TRACES.get(key);
  if (hit !== undefined) return hit;
  const prevPin = ingressOverride;
  const prevJudging = judgingAlternate;
  ingressOverride = host;
  judgingAlternate = true;
  try {
    const t = traceFlow(flow);
    ALTERNATE_TRACES.set(key, t);
    return t;
  } finally {
    ingressOverride = prevPin;
    judgingAlternate = prevJudging;
  }
}

/** Gaps before the modelled segment: an alternate ingress, and the gateway's physical ingress port. */
function ingressPolicyGaps(t: Trace): PolicyGap[] {
  const first = t.hops[0];
  const src = parseIpv4(t.flow.srcIp);
  if (first === undefined || src === null || judgingAlternate) return [];
  const out: PolicyGap[] = [];

  const cands = ingressCandidates(src);
  const chosen = cands.find((c) => c.host === first.host);
  if (chosen !== undefined) {
    for (const alt of cands) {
      if (alt.host === first.host) continue;
      const at = traceVia(t.flow, alt.host);
      if (at.hops[0]?.host !== alt.host) continue; // the override could not place it; nothing was traced from there
      const altGaps = pathPolicyGaps(at);
      const altUndecided = at.hops.some((h) => h.verdict === "unmodeled" || h.evidence.some((e) => e.kind === "absence"));
      if (at.outcome === t.outcome && altGaps.length === 0 && !altUndecided) continue; // modelled equivalently
      const why: string[] = [];
      if (at.outcome !== t.outcome) why.push(`traced from ${alt.host} this flow is ${at.outcome}, not ${t.outcome}`);
      for (const g of altGaps) why.push(altGapPhrase(g));
      if (altUndecided) why.push(`the trace from ${alt.host} rests on evidence recorded as absent`);
      out.push({
        host: alt.host,
        kind: "ingress-alternate",
        label: `${first.host} was taken as ingress on a point-in-time role (${chosen.role}); the flow may instead enter via ${alt.host} (${alt.role}), which is not modelled equivalently: ${why.join("; ")}`,
        cite: alt.cite,
      });
    }
  }

  /* The physical port the source's frames reach the gateway by. Only asked where the gateway's ACLs
     were collected — elsewhere the whole host is already an `acl-uncollected` gap — and only when
     the flow enters by an SVI (a source owned by the device itself arrives by no port). */
  if (fabric.coverage.aclHosts.includes(first.host) && !ADDRESS_OWNERS.has(src)) {
    const svi = connectedInterfaceFor(first.host, src);
    const vlan = svi === null ? null : (/^Vlan(\d+)$/i.exec(svi)?.[1] ?? null);
    if (vlan !== null) {
      const open = physicalIngressStates(first.host, vlan, src);
      if (open.length > 0) {
        const shown = open.slice(0, 4).map((s) => `${s.intf ?? "(unresolved)"}${s.kind === "bound" ? ` binds ${s.acl} ${s.dir}, not evaluated by this model` : ""}`);
        out.push({
          host: first.host,
          kind: "ingress-port-unobserved",
          label: `${formatIpv4(src)}'s frames could reach ${first.host} Vlan${vlan} by ${open.length} physical ${open.length === 1 ? "port" : "ports"} whose inbound filtering was not observed (${shown.join(", ")}${open.length > 4 ? ` and ${open.length - 4} more` : ""}) — the attachment path is not simulated, so which port it is, and what it filters, is unobserved`,
          cite: open[0]!.cite ?? `interfaces.${first.host}`,
        });
      }
    }
  }
  return out;
}

export function unobservedPolicyInputs(t: Trace): PolicyGap[] {
  if (judgingAlternate) return pathPolicyGaps(t);
  const hit = GAPS.get(t);
  if (hit !== undefined) return hit;
  const all = [...pathPolicyGaps(t), ...ingressPolicyGaps(t)];
  GAPS.set(t, all);
  return all;
}

/** The gaps ON the modelled segment — hosts traversed, and denials by unbound lists. */
function pathPolicyGaps(t: Trace): PolicyGap[] {
  const out: PolicyGap[] = [];
  const aclHosts = new Set(fabric.coverage.aclHosts);
  const ribHosts = new Set(fabric.coverage.routableHosts);
  const seen = new Set<string>();
  for (const h of t.hops) {
    /* EVERY traversed host without collected ACLs is an unobserved filtering question, whatever the
       hop's verdict. This used to be scoped to the PASSING verdicts, so a hop that ENDED the trace
       (unmodeled, no-route) produced no gap, and T1 printed "no filtering question on this path was
       left unobserved" beside the same trace's caveat "No ACLs were collected for <host>; filtering
       there is unobserved". An ingress filter is evaluated before the routing decision, so the
       question is just as live at a hop that drops. Found by the 2026-09-21 critic (B1). */
    if (!aclHosts.has(h.host) && !seen.has(h.host)) {
      seen.add(h.host);
      const holds = ribHosts.has(h.host)
        ? "holds a collected routing table but no collected ACLs"
        : "has neither a collected routing table nor collected ACLs";
      const effect = PASSING.has(h.verdict)
        ? "so whether it filters this flow was never evaluated"
        : `so whether it would filter this flow ahead of its ${h.verdict} outcome there was never evaluated`;
      out.push({
        host: h.host,
        kind: "acl-uncollected",
        label: `${h.host} ${holds}, ${effect} — unobserved, not absent`,
        cite: fabric.coverage.cite,
      });
    }
    const basis = PARTIAL_ROUTE_BASIS.get(h);
    if (basis !== undefined) {
      out.push({
        host: h.host,
        kind: "rib-partial",
        label: `${basis.sentence}, so the ${basis.route.source ?? "unlabelled"} route ${basis.route.prefix} that ${h.host} followed (${basis.route.cite}) may not be the route it actually uses for this flow`,
        cite: ribIncompleteness(h.host)[0]?.cite ?? basis.route.cite,
      });
    }
    if (h.verdict === "no-route") {
      const partial = ribIncompleteness(h.host);
      if (partial.length > 0) {
        out.push({
          host: h.host,
          kind: "rib-partial",
          label: `${ribIncompletenessSentence(h.host) ?? `${h.host}'s collected routing table is incomplete`}, so "no route" at ${h.host} is what a partial table says, not a decided absence of a route`,
          cite: partial[0]!.cite,
        });
      }
    }
    const d = h.decidedBy;
    const deniedBy = d === null ? null : (/^acls\.[^.]+\.([^[]+)/.exec(d.cite)?.[1] ?? null);
    if (
      h.verdict === "denied" &&
      d !== null &&
      (d.kind === "acl" || d.cite.startsWith(`acls.${h.host}.`)) &&
      !(deniedBy !== null && hopHasObservedBinding(h, deniedBy))
    ) {
      out.push({
        host: h.host,
        kind: "acl-unbound-denial",
        label: `the denying list at ${h.host} was chosen by the address-specificity rule because a binding on this hop was not observed, so that it is applied on this flow's path is not observed`,
        cite: d.cite,
      });
    }
  }
  return out;
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

/**
 * How many candidate flows one counterexample request may trace. This is the search's STRUCTURAL
 * budget: with at most `ingressCandidates(src).length` traces per candidate (the candidate itself
 * plus one memoised trace per alternate ingress, which cannot recurse — `judgingAlternate`), and at
 * most `TTL_LIMIT` hops per trace, the work one request can do is bounded by the data, not by the
 * machine. `engine.work-bound.test.ts` asserts that bound instead of a wall-clock figure, which
 * under parallel load could not tell a regression from a busy host (acceptance O26).
 */
export const COUNTEREXAMPLE_CANDIDATE_CAP = 48;
const CANDIDATE_CAP = COUNTEREXAMPLE_CANDIDATE_CAP;

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
    if (!isDefiniteOnModelledPath(t)) continue;
    // The rationale cites the trace that was actually run — never `c.why`, which describes only the
    // line that suggested this candidate. See deliveringAclEvidence().
    const decided = deliveringAclEvidence(t);
    const stated = `${protoLabel(c.flow)} from ${c.flow.srcIp} to ${c.flow.dstIp} is delivered`;
    /* The candidate shares the source, so it shares the source's ingress assumption. That is said in
       the rationale itself rather than dropped: the variation is decided on the modelled path, and
       the doubt before that path is carried with it, not laundered away. */
    const ingress = ingressPolicyGaps(t);
    const shared =
      ingress.length === 0
        ? ""
        : ` It rests on the same ingress assumption as the flow above, so it is decided on the modelled path only: ${ingress.map((g) => g.label).join("; ")}.`;
    return {
      found: true,
      flow: c.flow,
      trace: t,
      rationale:
        (decided === null
          ? `${stated}. No ACL line was consulted on its path, so nothing here claims which rule permitted it.`
          : `${stated}: ${decided.label} (${decided.cite}).`) + shared,
    };
  }
  return {
    found: false,
    reason: `None of the ${Math.min(candidates.length, CANDIDATE_CAP)} nearby variations derived from the evidence at ${host} traced as a delivery with nothing on its path left undecided, so no counterexample is offered. That is not proof that none exists — only the collected ACLs and RIBs were searched.`,
  };
}

/* ── suggested flows ────────────────────────────────────────────────────────── */

/**
 * Interesting flows, derived from this snapshot and then TRACED, so the outcome each one advertises
 * is the outcome the engine actually produced. A candidate whose trace does not match its intent is
 * dropped rather than relabelled: the list is evidence about the engine, not a brochure.
 *
 * Built on FIRST USE, not at module load (acceptance E5, cold load). Tracing every candidate is the
 * single largest piece of work in the entry chunk's evaluation — measured 101 ms of a 154 ms
 * evaluation on the release build, unminified profile — and module evaluation is one task that no
 * keystroke can interrupt. Nothing on the default screen needs the list: the path panel and the
 * command palette ask for it when they are opened. The result is the same pure function of the
 * snapshot either way; only WHEN it is paid for moved.
 */
let SUGGESTED: readonly SuggestedFlow[] | null = null;

export function suggestedFlows(): SuggestedFlow[] {
  SUGGESTED ??= buildSuggestions();
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
    // Same-source comparison: the ingress assumption is the source's and the flow's own card states it.
    if (want === "delivered" && !isDefiniteOnModelledPath(t)) return false;
    out.push({ id, title, flow, rationale, expectedOutcome: t.outcome, srcProvenance });
    return true;
  };

  /** The endpoint record that observed this address, so an "observed" claim carries its evidence. */
  const observedAt = (ip: Ipv4): SourceProvenance => {
    /* Same ordering as `attachmentEvidence`, so this note and the trace name the same first record.
       Naming only the first record once said "observed as an endpoint on access1 Gi0/2" for an
       address the same trace reports on 17 hosts with an ambiguous attachment (critic B2). */
    const recs = [...(ENDPOINTS_BY_IP.get(ip) ?? [])].sort(
      (a, b) => a.host.localeCompare(b.host) || (a.port ?? "").localeCompare(b.port ?? ""),
    );
    const rec = recs[0];
    const hosts = new Set(recs.map((r) => r.host)).size;
    const where = rec === undefined ? "a collected host" : `${rec.host} ${rec.port ?? "(no port recorded)"}`;
    return {
      kind: "observed",
      cite: rec?.cite ?? fabric.coverage.cite,
      note:
        hosts > 1
          ? `${formatIpv4(ip)} was observed as an endpoint, but on ${hosts} hosts (first ${where}); its attachment point is ambiguous in the collected evidence.`
          : `${formatIpv4(ip)} was observed as an endpoint on ${where}.`,
    };
  };

  const derivedFrom = (ip: Ipv4, prefix: Prefix, cite: Cite, why: string): SourceProvenance => ({
    kind: "derived-from-observed-subnet",
    cite,
    note: `${formatIpv4(ip)} was not itself observed: it is a usable host address inside ${formatPrefix(prefix)}, ${why} (${cite}). The subnet is evidence; this address is a question posed inside it.`,
  });

  // A source address the collection actually observed, preferring one inside an ACL's source space.
  const observedSources = [...ENDPOINTS_BY_IP.keys()].sort((a, b) => a - b);

  /* The first flow a permit line describes, whether or not it traces as delivered. The two cases
     below borrow its destination; they used to borrow it only from a "permitted" suggestion that
     had traced as delivered, so the moment the engine stopped calling an undecidable permit
     "delivered" they silently disappeared too. Their own outcomes are traced independently. */
  let permitCandidate: Flow | null = null;

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
        permitCandidate ??= permitted;
        take(
          "permitted",
          `${proto.toUpperCase()}/${port} into ${formatPrefix(dstPrefix)}`,
          permitted,
          /* No uniqueness clause. This used to end "…it is the one shape of traffic this snapshot
             can show ending in delivery" — a hardcoded constant inside a loop over every permit
             line, derived from no count, and contradicted two cards below by the denied demo's own
             counterexample and by the intent verifier reporting 24 contradicting flows on the same
             screen. A uniqueness claim has to be a measurement or it has to be absent. */
          `${host} ACL ${name} ${aclLineName(line.index, lines.length)} permits exactly this (${line.cite}).`,
          "delivered",
          observedAt(src),
        );

        // The same pair on a port no permit line names: posed to ask what the rest of the list does.
        // Whether that is a decided refusal is the TRACE's to say, not this rationale's (B2).
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
            `The same pair on ${proto.toUpperCase()}/${blockedPort}, a port no permit line of ${host} ACL ${name} names — posed to ask what the rest of that list does with it.`,
            "denied",
            observedAt(src),
          );
        }

        /* An unevaluable line above the deny: the honest "cannot say" case. The rationale says the
           line "could match this flow", so that is ASKED of the matcher for the flow actually built,
           not assumed from the line's protocol: a protocol this flow form cannot carry (gre, esp…)
           used to become a tcp flow, and a line whose port excludes the borrowed port was still
           described as able to match it. */
        const unevaluable = lines
          .filter((l) => !lineEvaluability(l).evaluable && l.proto !== null)
          .map((l) => {
            const p = (l.proto ?? "").toLowerCase();
            const isIcmp = p === "icmp";
            const flow: Flow = { ...permitted, protocol: (isIcmp ? "icmp" : p === "udp" ? "udp" : "tcp") as Flow["protocol"], dstPort: isIcmp ? null : permitted.dstPort };
            return { l, p, flow };
          })
          .find((c) => matchTri(c.l, c.flow, src, dst) !== "no");
        if (unevaluable !== undefined) {
          take(
            "unevaluable",
            `${unevaluable.p.toUpperCase()} into ${formatPrefix(dstPrefix)}`,
            unevaluable.flow,
            `${unevaluable.l.cite} ("${unevaluable.l.raw ?? "text not collected"}") could match this flow and cannot be evaluated — posed to show what the engine does with a line it cannot evaluate.`,
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
    const delivered = out.find((o) => o.id === "permitted")?.flow ?? permitCandidate;
    if (src === null || delivered === null) continue;
    if (
      take(
        "unmodelled",
        `From ${s.host} Vlan${s.record.vlan ?? "?"} — no RIB collected`,
        { ...delivered, srcIp: formatIpv4(src) },
        `${s.host} gateways ${formatPrefix(s.prefix)} (${s.record.cite}) but no routing table was collected for it — posed to show what the engine says about a source it holds no table for.`,
        "indeterminate",
        derivedFrom(src, s.prefix, s.record.cite, `which ${s.host} gateways on Vlan${s.record.vlan ?? "?"}`),
      )
    ) {
      break;
    }
  }

  // A source on a RIB host with no default route, aimed off-fabric: a drop — decided only when the
  // host's table is not shown incomplete by the snapshot (./rib-completeness.ts).
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
          /* The question only. This used to answer it too — "…so this address is unreachable from
             there…, so the drop is not decided" — a second, hand-written verdict beside the trace's
             own claim, which already says both and says them with its scope (B2). */
          `${s.host} is the observed active gateway for ${formatPrefix(s.prefix)} (${s.record.cite}) and its collected RIB holds no default route — posed to ask what that table does with an address outside every prefix it holds.`,
          "dropped",
          derivedFrom(src, s.prefix, s.record.cite, `for which ${s.host} is the observed active gateway`),
        )
      ) {
        break;
      }
    }
    // The mirror case: a source that is in no observed subnet at all.
    const insideDst = (out.find((o) => o.id === "permitted")?.flow ?? permitCandidate)?.dstIp;
    if (insideDst !== undefined) {
      take(
        "out-of-scope",
        `An address the collection never saw`,
        { srcIp: offFabric, dstIp: insideDst, protocol: "tcp", dstPort: 443, srcPort: null },
        `${offFabric} is in no SVI subnet, connected route or endpoint record — posed to show what the engine says about a source address it cannot place.`,
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
