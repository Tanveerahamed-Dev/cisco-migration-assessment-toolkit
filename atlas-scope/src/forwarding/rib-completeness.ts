/**
 * rib-completeness.ts — is a collected routing table COMPLETE enough to decide "no route"?
 *
 * A "dropped — no route" outcome is a claim about an ABSENCE: nothing in the table matches. That
 * claim is only as strong as the table's completeness, and the table cannot testify to its own
 * completeness — four connected routes look the same whether they are everything or a sliver. The
 * snapshot does testify, in two places this module reads (compiled by
 * `tools/compile-rib-evidence.mjs` into `rib-evidence.json`, sha-bound to the same bytes):
 *
 *  - `protocol_assessability.rows`: for each routing-protocol family (the producer's own routing
 *    vocabulary — the keys of its `routing_neighbors` records), what the engine's receipt
 *    (cisco_toolkit/analyze.py compute_protocol_assessability) says was collected on this host.
 *    `assessed` means a neighbor state parsed from usable current-run output. A family teaches this
 *    host no routes ONLY on POSITIVE evidence of absence: `captured_empty` (the neighbor table was
 *    captured and holds nothing) or `not_running` (the capture is the platform's no-process banner,
 *    e.g. IOS `% BGP not active`) — the owner's rule, honoured only while the engine's own state
 *    vocabulary (`contracts/engine-contract.v1.json`, generated from cisco_toolkit) still declares
 *    each state. The producer always names ospf/eigrp/bgp, so demanding `assessed` for all three
 *    demanded that every router run all three protocols. Every other state — `captured_no_record`
 *    (output present but nothing parsed: a parser gap is as likely as an idle protocol), `partial`,
 *    `capture_error`, `not_collected`, `analysis_unavailable`, a missing row, or a state this code
 *    has never seen — leaves what the family installs unknown, and is a reason citing its row;
 *  - the routes themselves: a route learned by a protocol OUTSIDE the receipted vocabulary (IS-IS,
 *    RIP, LISP, NHRP, mobile, ODR, or any code the engine's route parser passes through unmapped) has
 *    no collection receipt at all, so what that protocol installs is unknown — a reason naming the
 *    source as the engine recorded it. The set is the COMPLEMENT of the receipted families and of the
 *    sources the table itself evidences (connected, local, static), never a list of protocols: the
 *    parser's vocabulary is open (2026-09-27 verifier, E2R2-V1: an IS-IS host whose three receipted
 *    families were captured empty read complete);
 *  - control-plane evidence the table does not reflect: an established overlay peer reporting
 *    received prefixes, an adjacency exchanging routes (OSPF `FULL`, a listed EIGRP neighbor
 *    `up …`, a BGP peer whose State/PfxRcd is a positive count — a number IS the Established
 *    state) while the table holds no route of its family, or an empty neighbor table beside routes
 *    of that family, where the table and the control plane disagree;
 *  - PER ADJACENCY, the link every session runs over. A session (OSPF `FULL`/`2WAY`, EIGRP `up`, a
 *    BGP peer in the Established state — any State/PfxRcd count, 0 included) exists only over a path
 *    to the neighbour: when the record names the interface it formed on, the table must hold a
 *    connected route on that interface covering the neighbour's link address; when it names none
 *    (BGP), some route OTHER THAN THE DEFAULT must cover the peer — a default covers every address,
 *    so it is no evidence of a path to this one (2026-09-27 verifier, E2R2-V2). A table that does not is missing
 *    that link AND whatever the session teaches. A per-family test ("the table holds SOME OSPF
 *    route") let routes learned over one adjacency vouch for another: on the substrate fleet,
 *    core1's OSPF routes from dist1 cancelled its FULL/DR neighbour 10.0.99.2 on Po1, whose link
 *    the table does not hold, and the B1 false decision came back (2026-09-26 verifier, E2-V1). The
 *    link is read from the record's `address` (the OSPF link address; an EIGRP/BGP record names its
 *    neighbour BY address, so `neighbor` is the address there) and `interface`. A record compiled
 *    without those fields leaves that session's link unknown — never held. An adjacency stuck below
 *    2-WAY (INIT/EXSTART/…) is not read as a session: a stated boundary, not evidence of a link.
 *
 * Every reason is derived from those records — never from a list of host names. When the sidecar
 * was compiled from other bytes, or names no routing vocabulary at all, completeness is UNKNOWN and
 * every table reads as incomplete: an unreadable completeness record can never make a table look
 * whole. (2026-09-21 critic, B1 blocker: core2's four-route table decided 60 "no counterexample"
 * drops while the snapshot recorded OSPF/BGP/EIGRP not_collected and a 240-prefix EVPN peer.)
 */
import engineContract from "../../contracts/engine-contract.v1.json";
import evidenceJson from "./rib-evidence.json";
import { fabric, routesOf } from "../core/data";
import { listPhrase } from "../core/phrases";
import { sameSourceBinding, type Cite, type SourceBinding } from "../core/types";
import { parseIpv4, parsePrefix, prefixContains } from "./ip";

interface ProtocolRow {
  protocol: string;
  state: string | null;
  reason: string | null;
  cite: Cite;
}
interface Adjacency {
  protocol: string;
  neighbor: string | null;
  state: string | null;
  cite: Cite;
  /** The neighbour's link address as the producer's record carries it (null when the record has
   *  none: EIGRP/BGP records name the neighbour BY its address). Absent — the key itself missing —
   *  when the compiler did not publish it, which leaves the link unreadable, never held. */
  address?: string | null;
  /** The interface the adjacency formed on (null when the record names none, as BGP's does). */
  interface?: string | null;
}
interface OverlayPeer {
  kind: string;
  neighbor: string | null;
  state: string | null;
  prefixes: number | null;
  cite: Cite;
}
interface HostEvidence {
  protocols: ProtocolRow[];
  adjacencies: Adjacency[];
  overlay: OverlayPeer[];
}
interface EvidenceFile {
  meta: SourceBinding & { routingProtocols: string[]; routingProtocolsFrom: string };
  hosts: Record<string, HostEvidence>;
}

const FILE = evidenceJson as unknown as EvidenceFile;

/** The engine's own protocol-assessability state vocabulary, read from the contract generated from
 *  cisco_toolkit (`contracts/engine-contract.v1.json`; `tests/test_engine_contract_projection.py` pins it to
 *  `analyze.PROTOCOL_ASSESSABILITY_STATES`). A malformed contract yields no vocabulary. */
export function engineAssessabilityStates(contract: unknown): ReadonlySet<string> {
  const states = (contract as { protocol_assessability_states?: unknown } | null | undefined)?.protocol_assessability_states;
  return new Set(Array.isArray(states) ? states.filter((x): x is string => typeof x === "string") : []);
}
export const ENGINE_ASSESSABILITY_STATES = engineAssessabilityStates(engineContract);

/* What counts as POSITIVE evidence that a family has no adjacency on a host — and so installs no learned
   route there — is the owner's rule (2026-09-27, R2 RULE): a neighbour table captured and empty, or the
   platform's no-process banner. Nothing else: output that parsed to nothing, an error, an uncollected
   command and any state this code has never seen all stay UNKNOWN. A state counts only while the ENGINE's
   vocabulary still declares it, so a renamed or retired engine state stops vouching for anything (fail
   closed) instead of silently matching nothing. */
const POSITIVE_ABSENCE = ["captured_empty", "not_running"] as const;
export const RIB_ABSENCE_STATES: ReadonlySet<string> = new Set(
  POSITIVE_ABSENCE.filter((s) => ENGINE_ASSESSABILITY_STATES.has(s)),
);

/** Route sources whose presence the table itself evidences: an interface's own subnet and address, and
 *  configured statics. Every OTHER source is learned from a peer and needs a collection receipt. */
const SELF_EVIDENT_SOURCES = new Set(["connected", "local", "static"]);

/** The sidecar is evidence only about the bytes it was compiled from: every binding field must
 *  agree — digest, its form, byte length and source (O15, `sameSourceBinding`). */
export const RIB_EVIDENCE_TRUSTED = sameSourceBinding(FILE.meta, fabric.meta);

/** One reason a collected table cannot be read as complete, with the record that says so. */
export interface RibIncompleteness {
  label: string;
  cite: Cite;
}

/** An adjacency / session state that means routes are being exchanged, in every encoding the
 *  producer's neighbor parsers emit: OSPF `FULL/…`, EIGRP `up <uptime>` (its table lists only up
 *  neighbors), an `Established` word, or BGP's State/PfxRcd count — a number is the Established
 *  state carrying the received-prefix count, so it exchanges routes exactly when it is positive. */
const EXCHANGING = /^(full|established|up)\b/i;
const PREFIX_COUNT = /^\d+$/;
function exchanging(state: string | null): boolean {
  if (state === null) return false;
  const s = state.trim();
  if (PREFIX_COUNT.test(s)) return Number(s) > 0;
  return EXCHANGING.test(s);
}
function describeState(state: string): string {
  const s = state.trim();
  return PREFIX_COUNT.test(s) ? `Established (${s} prefix${s === "1" ? "" : "es"} received)` : state;
}

/** Is this route of `family`? The engine's route-source vocabulary sub-types a family as
 *  `<family>-<subtype>` (`ospf-ext2`, `ospf-interarea`, `eigrp-external`), so an O E2 route IS an
 *  OSPF route; an exact-string match on the source missed every sub-typed route. */
function ofFamily(source: string | null, family: string): boolean {
  const s = (source ?? "").toLowerCase();
  const f = family.toLowerCase();
  return s === f || s.startsWith(`${f}-`);
}

/** "an OSPF", "an EIGRP", "a BGP": the article for an acronym read letter by letter. */
function article(acronym: string): string {
  return /^[aefhilmnorsx]/i.test(acronym) ? "an" : "a";
}

/** A session is up over a path to the neighbour: OSPF `FULL`/`2WAY` (2-WAY is a stable session on a
 *  shared segment that exchanges no routes), EIGRP `up`, `Established`, or BGP's numeric
 *  State/PfxRcd — any count, 0 included: an Established peer that sent nothing is still a session. */
const SESSION = /^(full|2way|established|up)\b/i;
function sessionUp(state: string | null): boolean {
  if (state === null) return false;
  const s = state.trim();
  return PREFIX_COUNT.test(s) || SESSION.test(s);
}

/** Two spellings of one interface: the same number and one name a prefix of the other, whatever the
 *  case (`Po1` / `Port-channel1`, `Gi1/0/3` / `GigabitEthernet1/0/3`, `Vl40` / `Vlan40`). */
function sameInterface(a: string, b: string): boolean {
  const split = (t: string) => {
    const m = /^([a-z][a-z-]*)\s*(\S.*)$/i.exec(t.trim());
    return m === null ? null : { name: m[1]!.toLowerCase(), num: m[2]!.toLowerCase() };
  };
  const x = split(a);
  const y = split(b);
  if (x === null || y === null) return a.trim().toLowerCase() === b.trim().toLowerCase();
  return x.num === y.num && (x.name.startsWith(y.name) || y.name.startsWith(x.name));
}

/** What an absence state says, for a family `P` on `host` ("the P neighbor table was captured on host
 *  and is empty"). A state the contract names but this code has no phrasing for is quoted as-is. */
function absenceClause(protocol: string, state: string, host: string): string {
  switch (state) {
    case "captured_empty":
      return `the ${protocol} neighbor table was captured on ${host} and is empty`;
    case "not_running":
      return `no ${protocol} process is running on ${host} (its capture is the platform's no-process banner)`;
    default:
      return `the engine records ${protocol} as ${state.replace(/_/g, " ")} on ${host}`;
  }
}

/** Why a protocol row that is neither `assessed` nor an absence state leaves the table's completeness unknown. */
function unknownStateLabel(protocol: string, state: string | null, host: string): string {
  switch (state) {
    case "captured_no_record":
      return `${protocol} output was captured on ${host} but no neighbor state was parsed from it, so what ${protocol} installs is unknown (not evidence that it is idle)`;
    case "partial":
      return `${protocol} is only partly collected on ${host}, so what it installs is unknown`;
    case "capture_error":
      return `the ${protocol} capture on ${host} returned an error, so what ${protocol} installs is unknown`;
    case "not_collected":
      return `${protocol} is not collected on ${host}`;
    case "analysis_unavailable":
      return `${protocol} on ${host}: protocol analysis was unavailable for this run, so what it installs is unknown`;
    default:
      return `${protocol} is ${(state ?? "unrecorded").replace(/_/g, " ")} on ${host}`;
  }
}

/** A reason plus the family it concerns (null: every family), so the basis can never vouch for a
 *  family that is itself the reason (2026-09-26 verifier, E2-V3). */
interface Reason extends RibIncompleteness {
  family: string | null;
}

const CACHE = new Map<string, Reason[]>();
const PUBLIC = new Map<string, RibIncompleteness[]>();

/** Why the session `a` is not accounted for by a link `host`'s table holds, or null when it is. */
function linkReason(a: Adjacency, host: string, routes: ReturnType<typeof routesOf>): string | null {
  const P = a.protocol.toUpperCase();
  const head = `${article(P)} ${P} adjacency with ${a.neighbor ?? "an unrecorded neighbour"} is ${describeState(a.state ?? "")}`;
  if (!("address" in a) || !("interface" in a)) {
    return `${head}, but its compiled record does not carry the neighbour's address and interface, so whether ${host}'s table holds the link that session runs over is unknown`;
  }
  const addrText = a.address ?? a.neighbor;
  const addr = addrText === null ? null : parseIpv4(addrText);
  if (addrText === null || addr === null) {
    return `${head}, but its record names no neighbour address, so whether ${host}'s table holds the link that session runs over is unknown`;
  }
  const covers = (prefix: string) => {
    const p = parsePrefix(prefix);
    return p !== null && prefixContains(p, addr);
  };
  const intf = a.interface ?? null;
  if (intf !== null) {
    const held = routes.some(
      (r) => r.source === "connected" && r.outIntf !== null && sameInterface(r.outIntf, intf) && covers(r.prefix),
    );
    if (held) return null;
    return `${head}, yet the table holds no connected route on ${intf} covering its address ${addrText} — the link that adjacency runs over, and whatever it teaches, are missing from the table`;
  }
  const covering = routes.filter((r) => covers(r.prefix));
  if (covering.some((r) => parsePrefix(r.prefix)?.bits !== 0)) return null;
  const dflt = covering[0];
  if (dflt !== undefined) {
    return `${head}, yet no route in the table other than the default (${dflt.cite}) covers ${addrText} — a default covers every address, so it is no evidence of a path to this peer`;
  }
  return `${head}, yet no route in the table covers ${addrText} — the session could not be up over the table as collected`;
}

/**
 * Why `host`'s collected routing table is not complete. Empty means every family of the snapshot's
 * routing vocabulary is accounted for by its own receipt (`assessed`, or a neighbor table captured
 * empty — see `ribCompletenessBasis`), every session the host holds runs over a link its table
 * holds, and nothing observed contradicts the table — NOT that the table is proven complete (the
 * families' own boundaries still apply). A host with no collected table is not asked here: it is
 * unmodelled, which is a stronger statement.
 */
export function ribIncompleteness(host: string): RibIncompleteness[] {
  const hit = PUBLIC.get(host);
  if (hit !== undefined) return hit;
  const out = reasonsOf(host).map(({ label, cite }) => ({ label, cite }));
  PUBLIC.set(host, out);
  return out;
}

function reasonsOf(host: string): Reason[] {
  const hit = CACHE.get(host);
  if (hit !== undefined) return hit;
  const out = computeReasons(host);
  CACHE.set(host, out);
  return out;
}

function computeReasons(host: string): Reason[] {
  const out: Reason[] = [];
  if (!RIB_EVIDENCE_TRUSTED) {
    out.push({
      label: `the routing-completeness record was compiled from different snapshot bytes (${FILE.meta.sourceSha256.slice(0, 8)}) than this build's data, so whether ${host}'s table is complete is unknown`,
      cite: `routes.${host}`,
      family: null,
    });
    return out;
  }
  const vocab = FILE.meta.routingProtocols;
  if (vocab.length === 0) {
    out.push({
      label: `the snapshot names no routing-protocol families (no ${FILE.meta.routingProtocolsFrom} keys), so whether ${host}'s table is complete is unknown`,
      cite: `routes.${host}`,
      family: null,
    });
    return out;
  }
  const ev = FILE.hosts[host];
  const routes = routesOf(host);
  /** The first route of `family` in the table, or undefined. */
  const routeOf = (family: string) => routes.find((r) => ofFamily(r.source, family));
  for (const proto of vocab) {
    const row = ev?.protocols.find((p) => p.protocol.toLowerCase() === proto);
    if (row === undefined) {
      out.push({ label: `no ${proto.toUpperCase()} collection receipt exists for ${host}`, cite: "protocol_assessability", family: proto });
    } else if (row.state !== null && RIB_ABSENCE_STATES.has(row.state)) {
      const held = routeOf(proto);
      if (held !== undefined) {
        out.push({
          label: `${absenceClause(row.protocol, row.state, host)}, yet the table holds ${article(row.protocol)} ${row.protocol} route (${held.cite}) — the two captures disagree, so what ${row.protocol} installs is unknown`,
          cite: row.cite,
          family: proto,
        });
      }
    } else if (row.state !== "assessed") {
      out.push({ label: unknownStateLabel(row.protocol, row.state, host), cite: row.cite, family: proto });
    }
  }
  /* A route learned by a protocol with no receipt at all: the complement of the receipted families and the
     self-evident sources, so an open parser vocabulary can never slip a protocol past this check. */
  const unreceipted = new Map<string, (typeof routes)[number]>();
  for (const r of routes) {
    const source = (r.source ?? "").trim().toLowerCase();
    if (SELF_EVIDENT_SOURCES.has(source)) continue;
    const fam = source.split("-")[0] ?? "";
    if (fam !== "" && vocab.includes(fam)) continue;
    if (!unreceipted.has(fam)) unreceipted.set(fam, r);
  }
  for (const [fam, r] of unreceipted) {
    const named = r.source === null || r.source.trim() === "" ? "an unrecorded source" : `"${r.source.trim()}"`;
    out.push({
      label: `the table holds a route whose source is ${named} (${r.cite}), a protocol with no collection receipt in the snapshot (its receipted routing families are ${listPhrase(vocab, "none")}), so what it installs on ${host} is unknown`,
      cite: r.cite,
      family: fam === "" ? null : fam,
    });
  }
  /* One reason per session — the first contradiction found: a session exchanging routes while the
     table holds none of its family (the kept rule), then, per adjacency, a session whose link the
     table does not hold. */
  for (const a of ev?.adjacencies ?? []) {
    if (!sessionUp(a.state)) continue;
    const family = a.protocol.toLowerCase();
    if (exchanging(a.state) && routeOf(a.protocol) === undefined) {
      out.push({
        label: `${article(a.protocol)} ${a.protocol.toUpperCase()} adjacency with ${a.neighbor ?? "an unrecorded neighbour"} is ${describeState(a.state ?? "")}, yet the table holds no ${a.protocol.toUpperCase()} route`,
        cite: a.cite,
        family,
      });
      continue;
    }
    const link = linkReason(a, host, routes);
    if (link !== null) out.push({ label: link, cite: a.cite, family });
  }
  for (const p of ev?.overlay ?? []) {
    if (p.state === null || !exchanging(p.state) || p.prefixes === null || p.prefixes <= 0 || routeOf("bgp") !== undefined) continue;
    out.push({
      label: `an established ${p.kind.toUpperCase()} peer ${p.neighbor ?? "(unrecorded)"} reports ${p.prefixes} received prefixes, none of which the table holds`,
      cite: p.cite,
      family: "bgp",
    });
  }
  return out;
}

/** Why one routing-protocol family does NOT make a host's table incomplete, with the row that says so. */
export interface RibCompletenessBasis {
  protocol: string;
  label: string;
  cite: Cite;
}

/**
 * For each family of the snapshot's routing vocabulary that does not make `host`'s table
 * incomplete, the evidence that it does not: `assessed` (a neighbor state parsed from usable
 * output), or an absence state the engine contract declares (`captured_empty`: the neighbor table
 * was captured and is empty; `not_running`: no process) with no route of that family in the table —
 * and no reason concerns the family (none of its sessions lacks its routes or its link). Sorted by
 * protocol. A route of an unreceipted protocol never appears here: it has no row to vouch for it. Empty when the record is untrusted or names no
 * vocabulary — nothing then vouches for any family. This is what a surface quotes when it says a
 * table is NOT shown incomplete, so that "complete" is never an absence of reasons alone.
 */
export function ribCompletenessBasis(host: string): RibCompletenessBasis[] {
  if (!RIB_EVIDENCE_TRUSTED) return [];
  const vocab = FILE.meta.routingProtocols;
  const ev = FILE.hosts[host];
  const reasons = reasonsOf(host);
  if (reasons.some((r) => r.family === null)) return [];
  /* A family is vouched for only when NO reason concerns it — its row, its adjacencies' routes or
     links, or its overlay peers (2026-09-26 verifier, E2-V3: a cite-only filter listed OSPF as a basis
     while an OSPF adjacency was the very reason the table is incomplete). */
  const blocked = new Set(reasons.map((r) => r.family));
  const out: RibCompletenessBasis[] = [];
  for (const proto of vocab) {
    const row = ev?.protocols.find((p) => p.protocol.toLowerCase() === proto);
    if (row === undefined || blocked.has(proto)) continue;
    if (row.state === "assessed") {
      out.push({
        protocol: row.protocol,
        label: `${row.protocol} is assessed on ${host}: a neighbor state was parsed from usable current-run output`,
        cite: row.cite,
      });
    } else if (row.state !== null && RIB_ABSENCE_STATES.has(row.state)) {
      out.push({
        protocol: row.protocol,
        label: `${absenceClause(row.protocol, row.state, host)} — no adjacency, so no ${row.protocol}-learned route is missing from the table`,
        cite: row.cite,
      });
    }
  }
  return out.sort((a, b) => a.protocol.localeCompare(b.protocol));
}

/**
 * One sentence naming why `host`'s table is incomplete, or null when nothing says it is. Each reason
 * carries the record that says so, in parentheses right after it: the sentence is quoted verbatim by
 * the claim, the Filtering row, a caveat, the hop note and the announcement, so a citation that is
 * not IN the sentence is on none of those surfaces. It used to join the labels and drop the cites —
 * "an OSPF adjacency with 10.0.99.2 is FULL/DR, yet the table holds no OSPF route" was displayed five
 * times on the Path surface and `routing_neighbors.core1.ospf[0]` zero times (acceptance B6, refuter).
 */
export function ribIncompletenessSentence(host: string): string | null {
  const r = ribIncompleteness(host);
  if (r.length === 0) return null;
  return `${host}'s collected routing table is itself incomplete — ${r.map((x) => `${x.label} (${x.cite})`).join("; ")}`;
}

/**
 * The hosts whose collected table the snapshot shows to be incomplete, in coverage order. A count of
 * collected RIBs ("RIBs 2/26") without this reads as two whole tables; on this snapshot both are
 * partial (2026-09-22 critic, B7). Every surface that counts RIBs reads it here.
 */
export function ribHostsShownIncomplete(): string[] {
  return fabric.coverage.routableHosts.filter((h) => ribIncompleteness(h).length > 0);
}

/** "(both shown incomplete)", "(1 of 3 shown incomplete)", or "" when none is. */
export function ribCountQualifier(): string {
  const all = fabric.coverage.routableHosts.length;
  const partial = ribHostsShownIncomplete().length;
  if (partial === 0) return "";
  if (partial === all) return all === 1 ? "(shown incomplete)" : all === 2 ? "(both shown incomplete)" : `(all ${all} shown incomplete)`;
  return `(${partial} of ${all} shown incomplete)`;
}
