/**
 * HopList.tsx — the hop-by-hop result of one forwarding question.
 *
 * The rule this surface is built around: the evidence that DECIDED a hop is on the hop, not behind
 * a disclosure. A path tool that makes you click to find out which ACL line dropped the packet has
 * answered a different, easier question than the one that was asked — and the click is exactly
 * where a reader stops, accepts the verdict, and never checks it.
 *
 * Three verdict bands are rendered, never two (claims.ts `bandOfHop`): RESOLVED, REFUTED and
 * UNDETERMINED. A hop on a host with no collected RIB is UNDETERMINED — it carries the not-observed
 * visual language (dashed edge, hatch, the literal words) so it cannot be mistaken for either a
 * pass or a failure. That is the single most important thing on this surface.
 *
 * Citations are resolved back into the compiled records rather than parsed out of the evidence
 * prose: `decidedBy.label` is a sentence written for a human, and re-deriving an ACL's line index
 * from it would be the parser-versus-detector drift the engine header warns about. The dotted path
 * IS structured, so the path names the host and the ACL and the RECORD supplies the index and the
 * literal configuration text. When a citation does not resolve we say so — an unresolvable
 * citation is a defect to surface, not an empty space to leave.
 */
import {
  useCallback,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import {
  bandOfHop,
  bandOfHopIn,
  hopUndecided,
  hopUndecidedGaps,
  routeFieldReading,
  type RouteField,
  outcomeUndecidingGaps,
  type ClaimBand,
  type HopUndecided,
} from "../core/claims";
import { aclsOf, hasRib, resolveCite } from "../core/data";
import { own } from "../core/own";
import { ACL_LINE_NUMBERING_NOTE, aclLineName } from "../forwarding/acl-line";
import { hopHasObservedBinding, hopUnobservedBindings } from "../forwarding/bindings";
import { aclLineBlock, resolveEgress, unobservedPolicyInputs, type PolicyGap } from "../forwarding/engine";
import { parseIpv4 } from "../forwarding/ip";
import type { AclLine, Cite, Hop, HopEvidence, HopVerdict, RouteEntry, Trace } from "../core/types";
import { VERDICT_ICON } from "../ui/icons";
import { Cite as CiteLink, Disclosure, NotObserved, orNotObserved } from "../ui/primitives";
import { CitedText } from "./cited-text";
import "./PathTrace.css";

/* ── verdict vocabulary ─────────────────────────────────────────────────────
   The enum spelling is the model's; the words below are the reader's. `unmodeled` becomes "not
   modelled" because the enum word looks like a synonym for "simple" to anyone who has not read
   types.ts, and this is the one verdict a reader must not skim past. */
const VERDICT_WORD: Readonly<Record<HopVerdict, string>> = {
  forwarded: "forwarded",
  delivered: "delivered",
  "no-route": "no route",
  denied: "denied",
  unmodeled: "not modelled",
  loop: "loop",
  "ttl-exceeded": "TTL exceeded",
};

/** What the band means, spelled out, so the colour is never the only carrier. */
const BAND_WORD: Readonly<Record<ClaimBand, string>> = {
  RESOLVED: "resolved",
  REFUTED: "refuted",
  UNDETERMINED: "undetermined",
};

/**
 * The band of a verdict, asked of `claims.ts` rather than restated here. The empty hop exists so
 * the question can be asked with only a verdict in hand: duplicating the three-band mapping in a
 * component is how a surface ends up disagreeing with the claim layer about what `unmodeled` is.
 */
const bandOfVerdict = (verdict: HopVerdict): ClaimBand =>
  bandOfHop({
    index: 0,
    host: "",
    outIntf: null,
    nextHop: null,
    nextHost: null,
    verdict,
    decidedBy: null,
    evidence: [],
    alternatives: [],
  });

export function HopVerdictBadge({
  verdict,
  word,
  band: bandIn,
}: {
  verdict: HopVerdict;
  word?: string;
  /** The hop's band IN its trace (`bandOfHopIn`) when the caller has the trace; the verdict word's band otherwise. */
  band?: ClaimBand;
}): ReactElement {
  const band = bandIn ?? bandOfVerdict(verdict);
  /* An undecided hop never wears the pass/fail glyph: the tick is the strongest single mark on
     this surface, and it must not sit on a result the engine itself rates as not decided. */
  const Glyph = band === "UNDETERMINED" && bandOfVerdict(verdict) !== "UNDETERMINED" ? VERDICT_ICON.unmodeled : VERDICT_ICON[verdict];
  return (
    <span className="verdict" data-verdict={verdict} data-band={band}>
      <Glyph className="verdict__glyph" />
      <span className="verdict__word">{word ?? VERDICT_WORD[verdict]}</span>
      <span className="visually-hidden">{` — ${BAND_WORD[band]}`}</span>
    </span>
  );
}

/**
 * WHO the header says decided the hop — read from the hop's own decider, the same `classify(hop.
 * decidedBy)` the "Decided by" / ACL block renders from, so header and block cannot name different
 * agents. The agent used to be a fixed word per undecided reason: a denial by PROTECT_SERVERS
 * reached through a route from core1's incomplete table was headed "denied by routing — table
 * incomplete" directly above the block saying the ACL decided it (2026-09-22 acceptance report, A2).
 * Null when the decider names neither a list nor a route; the header then names no agent at all
 * rather than guessing one.
 */
function deciderAgent(d: Decider | null): string | null {
  if (d === null) return null;
  if (d.kind === "acl") return `by ACL ${d.acl}`;
  if (d.kind === "route") return "by routing";
  return null;
}

const verdictBy = (v: HopVerdict, d: Decider | null): string => {
  const agent = deciderAgent(d);
  return agent === null ? VERDICT_WORD[v] : `${VERDICT_WORD[v]} ${agent}`;
};

/**
 * A hop whose verdict word is a pass or a refusal but whose deciding input was never observed
 * (claims.ts `hopUndecided`). The word keeps what the routing or the list text DID say, and names
 * the half that was not decided — "delivered — resolved" over a host with no collected ACLs was an
 * unasked filtering question drawn as a resolved pass (2026-09-21 critic, B1). The agent in the word
 * ("by routing", "by ACL X") comes from `deciderAgent`, never from the reason.
 */
const UNDECIDED_WORD: Readonly<Record<HopUndecided, (v: HopVerdict, d: Decider | null) => string>> = {
  "filtering-unobserved": (v, d) => `${verdictBy(v, d)} — filtering unobserved`,
  "ingress-unobserved": (v, d) => `${verdictBy(v, d)} — ingress filtering unobserved`,
  "input-unobserved": (v, d) => `${verdictBy(v, d)} — an input unobserved`,
  "binding-unobserved": () => "denied by list text — binding unobserved",
  /* A route decision from a partial table: for a pass or a no-route the route IS the decider; for a
     denial the list decided and the route only brought the packet to it, so the header names the
     list and says which half is open. */
  "route-table-partial": (v, d) =>
    v === "no-route"
      ? "no route in the collected table — table incomplete"
      : d?.kind === "acl"
        ? `${verdictBy(v, d)} — reached by a route from an incomplete table`
        : `${verdictBy(v, d)} — table incomplete`,
  /* The hop that ended an undecided refusal still has a decider — the list line or the route the block
     below marks — and the header names it like every other reason does. It named none ("denied — outcome
     not decided") above a block reading "ACL — this is what decided the hop" once the regenerated sample
     completed core1's table and PROTECT_SERVERS' denial became undecided by its FHRP-alternate ingress
     instead (phase 3, HopList.decider-header.test.tsx). */
  "refusal-undecided": (v, d) => `${verdictBy(v, d)} — outcome not decided`,
  "delivery-undecided": (v, d) => `${verdictBy(v, d)} — outcome not decided`,
};

/** The trace's alternate-ingress gaps — keyed on the alternate host, so read from the trace, not the hop. */
const ingressAlternateGaps = (trace: Trace): PolicyGap[] => unobservedPolicyInputs(trace).filter((g) => g.kind === "ingress-alternate");

/* `acl-uncollected` ("no ACLs were collected") and `ingress-port-unobserved` (ACLs WERE collected,
   the arrival port was not observed) are different facts; each reason names only its own. The
   ingress reason quotes the engine's gap labels — the unobserved ports, and any FHRP alternate the
   flow may enter by — rather than paraphrasing them. */
const UNDECIDED_REASON: Readonly<Record<HopUndecided, (hop: Hop, trace: Trace) => string>> = {
  "filtering-unobserved": (hop) =>
    `no ACLs were collected for ${hop.host}, so whether it filters this flow was never evaluated — the route below was decided; whether the packet passes was not`,
  "ingress-unobserved": (hop, trace) =>
    `${hopUndecidedGaps(hop, trace)
      .filter((g) => g.kind === "ingress-port-unobserved" || g.kind === "ingress-alternate")
      .map((g) => g.label)
      .join("; ")} — ${hop.host}'s collected ACLs were evaluated on the modelled path (below); the route was decided; whether the packet passes was not`,
  "input-unobserved": (hop) =>
    `${hop.evidence.filter((e) => e.kind === "absence").map((e) => e.label).join("; ")} — the route was decided; whether the packet passes was not`,
  "binding-unobserved": (hop) =>
    `the denying list at ${hop.host} was chosen by the address-specificity rule because no access-group binding on this hop was observed — the line says what the list would do, not that the list is applied here`,
  /* Quoted from the engine's own `rib-partial` label, which names the not-collected protocols and
     the control-plane evidence the table does not hold — never a paraphrase. */
  /* The route is the more fundamental open question, so it leads; any filtering gap on the same hop
     is still named after it rather than dropped — "no ACLs were collected" in the reason's own
     wording, so the host-attribution rule above holds for this reason too. */
  "route-table-partial": (hop, trace) => {
    const gaps = hopUndecidedGaps(hop, trace);
    const also = gaps
      .filter((g) => g.kind !== "rib-partial")
      .map((g) => (g.kind === "acl-uncollected" ? `no ACLs were collected for ${g.host}, so whether it filters this flow was never evaluated (${g.cite})` : g.label));
    return `${gaps
      .filter((g) => g.kind === "rib-partial")
      .map((g) => g.label)
      .join("; ")}${also.length === 0 ? "" : `; also, ${also.join("; ")}`}`;
  },
  "refusal-undecided": (hop, trace) =>
    `${outcomeUndecidingGaps(trace)
      .map((g) => g.label)
      .join("; ")} — what ${hop.host} did on the modelled path is shown below; whether this is where the flow ends was not decided`,
  "delivery-undecided": (hop, trace) =>
    `${ingressAlternateGaps(trace)
      .map((g) => g.label)
      .join("; ")} — ${hop.host} delivers it on the modelled path (below); whether the flow is delivered here was not decided`,
};

/**
 * The records an undecided reason rests on, for the citation controls beside it: the gaps the reason
 * quotes, and for an unobserved input the absence evidence it names. Read from the same inputs the
 * reason text is built from, so a reason cannot name a gap whose record it does not show.
 */
function undecidedCites(why: HopUndecided, hop: Hop, trace: Trace): string[] {
  if (why === "input-unobserved") return hop.evidence.filter((e) => e.kind === "absence").map((e) => e.cite);
  if (why === "refusal-undecided") return outcomeUndecidingGaps(trace).map((g) => g.cite);
  if (why === "delivery-undecided") return ingressAlternateGaps(trace).map((g) => g.cite);
  return hopUndecidedGaps(hop, trace).map((g) => g.cite);
}

/* ── citation → record ──────────────────────────────────────────────────────
   `acls.<host>.<name>[<index>]` and `routes.<host>[<index>]` are the two shapes the forwarding
   engine cites. The host and the ACL name come from the path because that is where they are
   structured data; the line index and the literal text come from the RESOLVED RECORD, which is
   ground truth. Where the two disagree the record wins and the discrepancy is rendered. */
const ACL_CITE = /^acls\.([^.[\]]+)\.([^[\]]+)\[(\d+)]$/;

const isAclLine = (v: unknown): v is AclLine =>
  typeof v === "object" && v !== null && "index" in v && "unevaluable" in v && "raw" in v;

const isRouteEntry = (v: unknown): v is RouteEntry =>
  typeof v === "object" && v !== null && "prefix" in v && "adminDistance" in v;

type Decider =
  | { kind: "acl"; host: string; acl: string; line: AclLine; ev: HopEvidence }
  | { kind: "route"; route: RouteEntry; ev: HopEvidence }
  | { kind: "absence"; ev: HopEvidence }
  | { kind: "unresolved"; ev: HopEvidence };

function classify(ev: HopEvidence): Decider {
  if (ev.kind === "acl") {
    const m = ACL_CITE.exec(ev.cite);
    const rec = resolveCite(ev.cite);
    if (m && isAclLine(rec)) return { kind: "acl", host: m[1] ?? "", acl: m[2] ?? "", line: rec, ev };
    return { kind: "unresolved", ev };
  }
  if (ev.kind === "route") {
    const rec = resolveCite(ev.cite);
    if (isRouteEntry(rec)) return { kind: "route", route: rec, ev };
    return { kind: "unresolved", ev };
  }
  // An `absence` that cites an ACL LINE is the engine saying "this line could apply and cannot be
  // evaluated" — a limit of the model over a line that WAS collected. Rendering it as "not observed"
  // would report a model gap as a collection gap, so it resolves to the line like any ACL citation.
  if (ev.kind === "absence") {
    const m = ACL_CITE.exec(ev.cite);
    const rec = m ? resolveCite(ev.cite) : undefined;
    if (m && isAclLine(rec)) return { kind: "acl", host: m[1] ?? "", acl: m[2] ?? "", line: rec, ev };
  }
  // Otherwise `absence` is the engine's own marker for "we have no evidence here", and `svi`/`topology`
  // carry their reasoning in the label; neither has a narrower record shape worth resolving.
  return { kind: "absence", ev };
}

/**
 * How an ACL line that left a hop undecided stands toward this trace's flow, as a predicate for
 * "ACL <list> line N on <host> …". Read from the engine's own classification, so the card and the
 * engine's evidence rows can never disagree about which kind of block it is.
 */
function aclDeciderPhrase(line: AclLine, trace: Trace): string {
  const src = parseIpv4(trace.flow.srcIp);
  const dst = parseIpv4(trace.flow.dstIp);
  const block = src === null || dst === null ? null : aclLineBlock(line, trace.flow, src, dst);
  if (block === null) return "leaves this flow undecided";
  return block.kind === "unevaluable" ? "cannot be evaluated for this flow" : `could match this flow and is not decided for it: ${block.why}`;
}

/** The route the hop actually took, when one is recorded among its evidence. */
function winningRoute(hop: Hop): RouteEntry | null {
  for (const ev of hop.evidence) {
    if (ev.kind !== "route") continue;
    const rec = resolveCite(ev.cite);
    if (isRouteEntry(rec)) return rec;
  }
  return null;
}

/**
 * The connected route through which the engine resolved this hop's egress, when the winning route
 * named only a next-hop address (`0.0.0.0/0 via 10.0.10.254` → `10.0.10.0/24` on Vlan10). Read from
 * the hop's own route evidence, so the second record is cited rather than asserted.
 */
function egressResolution(hop: Hop, winner: RouteEntry | null): RouteEntry | null {
  if (winner === null || winner.outIntf !== null || hop.outIntf === null) return null;
  for (const ev of hop.evidence) {
    if (ev.kind !== "route" || ev.cite === winner.cite) continue;
    const rec = resolveCite(ev.cite);
    if (!isRouteEntry(rec)) continue;
    if ((rec.source === "connected" || rec.source === "local") && rec.outIntf === hop.outIntf) return rec;
  }
  return null;
}

/**
 * The lists this hop APPLIED without an observed interface binding — i.e. the ones the engine's
 * address-specificity fallback chose. Read from the evidence's structure: an `acl` item is a line
 * of an applied list, and an `absence` citing a whole list (`acls.<host>.<name>`, no index) is that
 * list's implicit deny. An `absence` citing a single LINE is an unevaluable line of a list the rule
 * did NOT apply, so it is not counted. A list with an observed binding on this hop is exempt.
 */
function fallbackLists(hop: Hop): string[] {
  const out: string[] = [];
  const prefix = `acls.${hop.host}.`;
  for (const ev of hop.evidence) {
    if (!ev.cite.startsWith(prefix)) continue;
    const rest = ev.cite.slice(prefix.length);
    const bracket = rest.indexOf("[");
    const name = ev.kind === "acl" ? (bracket < 0 ? rest : rest.slice(0, bracket)) : ev.kind === "absence" && bracket < 0 ? rest : null;
    if (name === null || name === "" || out.includes(name)) continue;
    if (!hopHasObservedBinding(hop, name)) out.push(name);
  }
  return out;
}

function fallbackSentence(hop: Hop, lists: readonly string[]): string {
  const where = hopUnobservedBindings(hop).map((i) => i ?? "an unresolved interface");
  const gap =
    where.length === 0
      ? "no interface binding on this hop was observed"
      : `the ACL binding at ${where.join(" and ")} was not observed`;
  return `applied by the address-specificity fallback, not by an observed binding: no observed binding applies ${lists.join(" or ")} on this hop, and ${gap} — the ${lists.length === 1 ? "list's lines say" : "lists' lines say"} what ${lists.length === 1 ? "it" : "they"} would do, not that ${lists.length === 1 ? "it is" : "they are"} applied here`;
}

/** The ACL line that acted at this hop, when one did. */
function actingAcl(hop: Hop): Decider | null {
  for (const ev of hop.evidence) {
    if (ev.kind !== "acl") continue;
    const d = classify(ev);
    if (d.kind === "acl" || d.kind === "unresolved") return d;
  }
  return null;
}

/* ── per-verdict field semantics ────────────────────────────────────────────
   A `null` is NOT OBSERVED — except where the verdict itself is the reason the field is empty. A
   delivered hop has no next hop because there is nothing further to go to; rendering "not
   observed" there would invent a gap in the evidence that does not exist. So each verdict declares
   which fields it EXPECTS, and only an expected-but-missing field renders as an absence. */
interface FieldExpectation {
  egress: boolean;
  /** The egress on a denied hop is the one the route WOULD have used; the label has to say so. */
  egressLabel: string;
  nextHop: boolean;
  /** Why the unexpected fields are empty, in one clause. Rendered instead of an absence mark. */
  terminalNote: string | null;
}

/**
 * Why an `unmodeled` hop is unmodelled. The one enum value has two structurally different causes,
 * and conflating them is the "model gap reported as a collection gap" defect:
 *
 *  - `no-rib`: nothing was collected here — the host has no RIB, so no egress was ever decided;
 *  - `route-decided`: the RIB DID decide the route (egress, next hop), but something the model
 *    cannot evaluate — an ACL line, a subnet's broadcast address — keeps the OUTCOME undecided.
 *
 * Asked of the collection (`hasRib`) and of the hop's own route evidence, never of prose.
 */
type UnmodelledCause = "no-rib" | "route-decided";

function unmodelledCause(hop: Hop, route: RouteEntry | null): UnmodelledCause {
  if (!hasRib(hop.host)) return "no-rib";
  return route !== null || hop.outIntf !== null || hop.nextHop !== null ? "route-decided" : "no-rib";
}

function expectations(hop: Hop, route: RouteEntry | null): FieldExpectation {
  const verdict = hop.verdict;
  if (verdict === "unmodeled" && unmodelledCause(hop, route) === "route-decided") {
    // The forwarding decision was made; render it exactly as a forwarded/delivered hop would, so
    // the reader sees WHAT was decided next to the one thing that was not.
    const onLink = route !== null && (route.source === "connected" || route.source === "local");
    return onLink || (route === null && hop.nextHop === null)
      ? {
          egress: true,
          egressLabel: "Egress",
          nextHop: false,
          terminalNote: "none — the destination prefix is directly connected at this hop",
        }
      : { egress: true, egressLabel: "Egress", nextHop: true, terminalNote: null };
  }
  switch (verdict) {
    case "forwarded":
      return { egress: true, egressLabel: "Egress", nextHop: true, terminalNote: null };
    case "delivered":
      return {
        egress: true,
        egressLabel: "Egress",
        nextHop: false,
        terminalNote: "none — the destination prefix is directly connected at this hop",
      };
    case "denied":
      return {
        egress: true,
        egressLabel: "Egress if permitted",
        nextHop: false,
        terminalNote: "none — the filter dropped the packet before the forwarding decision mattered",
      };
    case "no-route":
      return {
        egress: false,
        egressLabel: "Egress",
        nextHop: false,
        terminalNote: "none — no prefix in the collected RIB matched",
      };
    case "unmodeled":
      return {
        egress: false,
        egressLabel: "Egress",
        nextHop: false,
        terminalNote: "not modelled — no routing table was collected for this host, so no egress was decided",
      };
    case "loop":
      return {
        egress: false,
        egressLabel: "Egress",
        nextHop: false,
        terminalNote: "none — this host was already visited on this path",
      };
    case "ttl-exceeded":
      return { egress: true, egressLabel: "Egress", nextHop: true, terminalNote: null };
  }
}

/* ── row primitives ─────────────────────────────────────────────────────────── */

function Fact({
  label,
  decided = false,
  children,
}: {
  label: string;
  /** Marks the row the engine named as the one that ended this hop. */
  decided?: boolean;
  children: ReactNode;
}): ReactElement {
  return (
    <div className="hop__fact" data-decided={decided || undefined}>
      <dt className="hop__key">
        {label}
        {decided ? <span className="visually-hidden"> — this is what decided the hop</span> : null}
      </dt>
      <dd className="hop__val">{children}</dd>
    </div>
  );
}

/**
 * One field of a route RECORD, as its ONE owner reads it (`route-fields.ts :: routeFieldReading`, re-exported by `claims.ts`).
 *
 * Exported because every surface that prints a route field renders THIS — the hop list here, the
 * Device pane's Routing tab and the Inspector's field table. B1 failed twice for one class: the same
 * connected route's null AD read "0 — … by definition" on one surface and "not observed" on another,
 * because each surface decided for itself, and the first fix wired two of the three to a shared
 * helper. Now none of them decides: they render the owner's reading, and a type-checker guard
 * (`HopList.admin-distance.test.tsx`) fails if any module outside the owner reads the field.
 * `classes` changes only the styling, never the words.
 */
export function RouteFieldValue({
  route,
  field,
  mono = false,
  compact = false,
  classes,
}: {
  route: RouteEntry;
  field: RouteField;
  mono?: boolean;
  /**
   * For a cell too narrow for the reason: the value-slot word is shown and the reason is carried
   * off-screen and in the tooltip. The element's words are the same either way — only what is
   * painted differs, so a reader, a screen reader and a test all read the owner's full reading.
   */
  compact?: boolean;
  classes?: { notApplicable?: string; value?: string };
}): ReactElement {
  const reading = routeFieldReading(route, field);
  if (reading.kind === "not-applicable") {
    return (
      <span className={classes?.notApplicable ?? "hop__note"} data-not-applicable="true" title={compact ? reading.text : undefined}>
        {compact && reading.reason !== null ? (
          <>
            {reading.short}
            <span className="visually-hidden">{` — ${reading.reason}`}</span>
          </>
        ) : (
          reading.text
        )}
      </span>
    );
  }
  if (reading.kind === "absent") return <NotObserved what={reading.what} why={reading.why} compact />;
  return <span className={classes?.value ?? (mono ? "hop__mono" : undefined)}>{reading.text}</span>;
}

/**
 * The hop list's route field: the owner's reading, marked with `data-route-field` /
 * `data-route-cite` so a test can compare this cell to the Inspector's for the same record.
 */
function RouteField({ route, field, mono = false }: { route: RouteEntry; field: RouteField; mono?: boolean }): ReactElement {
  return (
    <span className="hop__route-field" data-route-field={field} data-route-cite={route.cite}>
      <RouteFieldValue route={route} field={field} mono={mono} />
    </span>
  );
}

function RouteFact({
  route,
  decided,
  onOpenCite,
}: {
  route: RouteEntry;
  decided: boolean;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  return (
    <Fact label="Route" decided={decided}>
      <span className="hop__mono">{route.prefix}</span>
      {/* A connected or local route HAS no next hop — the prefix is on an interface. Rendering
          "not observed" there would manufacture a gap in evidence that is not missing, which is
          the mirror image of rendering absence as health and just as wrong. That judgement belongs
          to `routeFieldReading`, which RouteField renders; every other route source is expected
          to name a next hop, so a null there is a real absence. */}
      {routeFieldReading(route, "nextHop").kind === "not-applicable" ? null : <span className="hop__sep">via</span>}
      <RouteField route={route} field="nextHop" mono />
      <span className="hop__meta">
        {orNotObserved(route.source, (v) => <span>{v}</span>, { what: "route source", compact: true })}
        <span className="hop__sep">·</span>
        <span className="hop__key-inline">AD</span>
        <RouteField route={route} field="adminDistance" />
      </span>
      <CiteLink cite={route.cite} onOpen={onOpenCite} />
    </Fact>
  );
}

function AclFact({
  decider,
  decided,
  hypothesis = false,
  onOpenCite,
}: {
  decider: Decider;
  decided: boolean;
  /** The list was applied by the address-specificity fallback, not by an observed binding. */
  hypothesis?: boolean;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  if (decider.kind !== "acl") {
    return (
      <Fact label="ACL" decided={decided}>
        <span className="hop__unresolved">
          {decider.ev.label}
          <span className="hop__warn">
            {` — the record at ${decider.ev.cite} could not be resolved, so the line text below is the engine's summary rather than the configuration itself`}
          </span>
        </span>
        <CiteLink cite={decider.ev.cite} onOpen={onOpenCite} />
      </Fact>
    );
  }
  const { host, acl, line } = decider;
  const lineName = aclLineName(line.index, own(aclsOf(host), acl)?.length ?? null);
  /* What the engine said THIS line did for this flow — "denies this flow", "would match, but an
     earlier unevaluable line may fire first", "cannot be evaluated — …". The engine composes every
     ACL evidence label as `<host> ACL <name> <line> <qualifier>` from the same structured parts
     used here, so the qualifier is the label past that prefix; a label of any other shape is shown
     whole rather than trimmed. Without it a non-deciding row read as a bare `deny ip any any` on the
     hop, while its qualification sat in the collapsed evidence list (2026-09-21 critic, A2). */
  const prefix = `${host} ACL ${acl} ${lineName} `;
  const qualifier = decider.ev.label.startsWith(prefix) ? decider.ev.label.slice(prefix.length) : decider.ev.label;
  return (
    <Fact label={hypothesis ? "ACL · hypothesis" : "ACL"} decided={decided && !hypothesis}>
      <span className="hop__mono" title={ACL_LINE_NUMBERING_NOTE}>{`${acl} ${lineName}`}</span>
      <span className="hop__meta">{`on ${host}`}</span>
      {qualifier === "" ? null : (
        <span className="hop__note" data-acl-qualifier="">
          <CitedText text={qualifier} onOpenCite={onOpenCite} />
        </span>
      )}
      {line.unevaluable ? (
        <span className="hop__flag" title="the producer could not model this line">
          not evaluable
        </span>
      ) : null}
      {/* The literal configuration text, verbatim. Three lines of prose about a rule are not a
          rule; this is the thing an engineer will paste into a change request. */}
      {orNotObserved(line.raw, (v) => <code className="hop__raw">{v}</code>, {
        what: "configuration line text",
        why: "the collector recorded this line without its original text",
      })}
      <CiteLink cite={line.cite} onOpen={onOpenCite} />
    </Fact>
  );
}

function AbsenceFact({
  ev,
  onOpenCite,
}: {
  ev: HopEvidence;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  return (
    <Fact label="Decided by" decided>
      <NotObserved what="the evidence that would decide this hop" why={ev.label} cite={ev.cite} onOpenCite={onOpenCite} />
    </Fact>
  );
}

/* ── alternatives ───────────────────────────────────────────────────────────── */

function Alternatives({
  routes,
  host,
  dstIp,
  onOpenCite,
}: {
  routes: readonly RouteEntry[];
  host: string;
  dstIp: string;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  const dst = parseIpv4(dstIp);
  return (
    /* Explicit roles: in a narrow rail the stacked layout below sets `display: block` on the table
       parts, and some engines then drop the implicit table semantics. */
    <table className="hop__alts" role="table">
      <caption className="visually-hidden">Routes considered at this hop and beaten by the winner</caption>
      <thead role="rowgroup">
        <tr role="row">
          <th scope="col" role="columnheader">Prefix</th>
          <th scope="col" role="columnheader">Source</th>
          <th scope="col" role="columnheader">Next hop</th>
          <th scope="col" role="columnheader">Out</th>
          <th scope="col" role="columnheader">AD</th>
          <th scope="col" role="columnheader">Evidence</th>
        </tr>
      </thead>
      <tbody role="rowgroup">
        {routes.map((r) => (
          <tr key={`${r.prefix}-${r.cite}`} role="row">
            <td className="hop__mono" role="cell" data-col="Prefix">{r.prefix}</td>
            <td role="cell" data-col="Source">{orNotObserved(r.source, undefined, { what: "route source", compact: true })}</td>
            <td className="hop__mono" role="cell" data-col="Next hop">
              <RouteField route={r} field="nextHop" />
            </td>
            <td className="hop__mono" role="cell" data-col="Out">
              {(() => {
                /* The same one-level recursive lookup the engine does for the winner (A2): a route
                   naming only a next hop leaves by the connected interface that next hop lies in. */
                if (r.outIntf !== null || dst === null) {
                  return orNotObserved(r.outIntf, undefined, { what: "egress interface", compact: true });
                }
                const res = resolveEgress(host, r, dst);
                const via = res?.evidence[0];
                return res === null ? (
                  orNotObserved(null, undefined, {
                    what: "egress interface",
                    why: "the route names no outgoing interface, and its next hop does not resolve to a connected route in this host's RIB",
                    compact: true,
                  })
                ) : (
                  <>
                    {res.intf}
                    {via === undefined ? null : (
                      <>
                        <span className="hop__meta"> resolved</span>
                        <CiteLink cite={via.cite} onOpen={onOpenCite} />
                      </>
                    )}
                  </>
                );
              })()}
            </td>
            <td role="cell" data-col="AD">
              <RouteField route={r} field="adminDistance" />
            </td>
            <td role="cell" data-col="Evidence">
              <CiteLink cite={r.cite} onOpen={onOpenCite} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ── the list ───────────────────────────────────────────────────────────────── */

export interface HopListProps {
  trace: Trace;
  /** Which hop is selected. Drives the 3-D trace highlight through the shared store. */
  activeIndex: number | null;
  onSelect: (index: number) => void;
  onOpenCite?: (cite: Cite) => void;
}

export function HopList({ trace, activeIndex, onSelect, onOpenCite }: HopListProps): ReactElement {
  const listRef = useRef<HTMLOListElement>(null);
  const openCite = useCallback((c: Cite) => onOpenCite?.(c), [onOpenCite]);

  /* Roving focus over the hop headers only. Selection FOLLOWS focus here, which is the right
     trade-off for this list specifically: selecting a hop re-aims the fabric and the evidence rail
     but never moves the camera or unmounts anything, so arrowing down the path is browsing, not
     navigation. The citation buttons inside a row stay out of the arrow order and are reached with
     Tab, so a keyboard reader can walk the path without being dropped into its evidence. */
  const onKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLOListElement>): void => {
      const heads = [...(listRef.current?.querySelectorAll<HTMLButtonElement>(".hop__head") ?? [])];
      if (heads.length === 0) return;
      const at = heads.findIndex((h) => h === document.activeElement);
      if (at === -1) return; // focus is inside a row's evidence; leave its own keys alone
      const go = (i: number): void => {
        const next = heads[Math.min(Math.max(i, 0), heads.length - 1)];
        if (!next) return;
        e.preventDefault();
        next.focus();
        onSelect(Number(next.dataset["hopIndex"] ?? 0));
      };
      switch (e.key) {
        case "ArrowDown":
          go(at + 1);
          break;
        case "ArrowUp":
          go(at - 1);
          break;
        case "Home":
          go(0);
          break;
        case "End":
          go(heads.length - 1);
          break;
        default:
          break;
      }
    },
    [onSelect],
  );

  if (trace.hops.length === 0) {
    /* Not an empty state: a trace with no hops is a REFUSAL to start, and the reason for it is the
       claim sentence the caller renders above this list. Saying "no hops" alone would read as
       "nothing happened", which is the absence-as-health failure in miniature. */
    return (
      <p className="hoplist__none">
        No hop was simulated. No device was consulted for this flow — the sentence above says why —
        so this result describes the question, not the network.
      </p>
    );
  }

  return (
    <ol className="hoplist" ref={listRef} onKeyDown={onKeyDown} aria-label={`${trace.hops.length} hop path`}>
      {trace.hops.map((hop) => {
        const band = bandOfHopIn(hop, trace);
        const policyUndecided = hopUndecided(hop, trace);
        const active = activeIndex === hop.index;
        const decider = hop.decidedBy === null ? null : classify(hop.decidedBy);
        const route = winningRoute(hop);
        const egressVia = egressResolution(hop, route);
        const exp = expectations(hop, route);
        const ribCollected = hasRib(hop.host);
        /* An unmodelled hop whose route WAS decided is undecided for a reason the model owns, not
           the collection. Say which: the ACL line that cannot be evaluated, named by its record. */
        /* A list the fallback chose is bound to no interface observed on this hop, so it cannot be
           headlined as what decided the hop: the engine named a line of it, but whether the list
           filters this hop at all was not observed. Its lines are shown as a hypothesis and the
           hop states the missing binding as the thing that left it undecided (2026-09-22 critic,
           A2: INET_RETURN, bound nowhere in acl-bindings.json, read "this is what decided the hop"). */
        const fallback = fallbackLists(hop);
        const isHypothesis = (d: Decider | null): boolean => d?.kind === "acl" && fallback.includes(d.acl);
        const deciderIsHypothesis = decider !== null && isHypothesis(decider);
        /* What the deciding line does to this flow, in the engine's own kind (aclLineBlock): "cannot
           be evaluated" is said only of a line the model cannot read. An evaluable line the flow leaves
           open (an `ip` flow against a tcp line, no port against `eq 443`) used to get the same words
           (re-grade B5, 2026-10-03). */
        const deciderPhrase = decider?.kind === "acl" ? aclDeciderPhrase(decider.line, trace) : null;
        const undecidedBy =
          hop.verdict === "unmodeled" && unmodelledCause(hop, route) === "route-decided"
            ? decider?.kind === "acl" && deciderIsHypothesis
              ? `no observed filter binding on this hop — undecided: ${decider.acl} is bound to no interface observed here, and even as a hypothesis ACL ${decider.acl} ${aclLineName(decider.line.index, own(aclsOf(decider.host), decider.acl)?.length ?? null)} on ${decider.host} ${deciderPhrase}`
              : decider?.kind === "acl"
              ? `ACL ${decider.acl} ${aclLineName(decider.line.index, own(aclsOf(decider.host), decider.acl)?.length ?? null)} on ${decider.host} ${deciderPhrase}`
              : "a condition this collection cannot settle (named under “Decided by”) keeps the outcome open"
            : null;
        const acl = actingAcl(hop);
        const aclDecided = decider?.kind === "acl" && acl?.kind === "acl" && acl.line.cite === decider.line.cite;
        const routeDecided = decider?.kind === "route" && route !== null && route.cite === decider.route.cite;
        /* The FIRST acl evidence item is not always the one that decided the hop — a permit that
           matched earlier and a deny that ended it are two different lines. When they differ the
           decider gets its own row: the deciding evidence is never allowed to be the one thing
           missing from the hop that it decided. */
        const decidingAclSeparate = decider?.kind === "acl" && !aclDecided ? decider : null;
        /* A list applied by the specificity fallback says so ON THE CARD, beside its lines: the
           binding-gap sentence used to live only in the collapsed evidence list, so a reader saw a
           bare `deny ip any any` from a list bound to no interface observed on this path. (`fallback`,
           computed above with the undecided reason it also feeds.) */

        return (
          <li
            key={hop.index}
            className="hop"
            data-band={band}
            data-verdict={hop.verdict}
            data-active={active || undefined}
          >
            <button
              type="button"
              className="hop__head"
              data-hop-index={hop.index}
              /* One hop is in the tab order; the arrows reach the rest (roving tabindex). */
              tabIndex={active || (activeIndex === null && hop.index === 0) ? 0 : -1}
              aria-current={active ? "true" : undefined}
              onClick={() => onSelect(hop.index)}
            >
              <span className="hop__num" aria-hidden="true">
                {hop.index + 1}
              </span>
              <span className="visually-hidden">{`Hop ${hop.index + 1} of ${trace.hops.length}: `}</span>
              <span className="hop__host">{hop.host}</span>
              <HopVerdictBadge
                verdict={hop.verdict}
                band={band}
                word={
                  undecidedBy !== null
                    ? "undecided"
                    : policyUndecided !== null
                      ? UNDECIDED_WORD[policyUndecided](hop.verdict, decider)
                      : undefined
                }
              />
            </button>

            <dl className="hop__facts">
              {undecidedBy !== null ? (
                <Fact label="Undecided">
                  <span className="hop__note" data-undecided-reason="">
                    <CitedText
                      text={`${undecidedBy} — the route below was decided; whether the packet passes was not`}
                      onOpenCite={openCite}
                      also={decider === null ? [] : [decider.ev.cite]}
                    />
                  </span>
                </Fact>
              ) : null}
              {policyUndecided !== null ? (
                <Fact label="Undecided">
                  {/* The reason quotes the engine's gap sentences, which carry their records; each is
                      rendered as a control, and every gap's own record is shown beside it (B6). */}
                  <span className="hop__note" data-undecided-reason="">
                    <CitedText
                      text={UNDECIDED_REASON[policyUndecided](hop, trace)}
                      onOpenCite={openCite}
                      also={undecidedCites(policyUndecided, hop, trace)}
                    />
                  </span>
                </Fact>
              ) : null}
              {exp.egress ? (
                <Fact label={exp.egressLabel}>
                  {orNotObserved(hop.outIntf, (v) => <span className="hop__mono">{v}</span>, {
                    what: "egress interface",
                    why: "the winning route names no outgoing interface, and its next hop does not resolve to a connected route in this host's RIB",
                    compact: true,
                  })}
                  {egressVia !== null ? (
                    <>
                      <span className="hop__meta" data-egress-resolved="">
                        {`resolved: next hop ${hop.nextHop ?? ""} lies in ${egressVia.source ?? "a"} ${egressVia.prefix}`}
                      </span>
                      <CiteLink cite={egressVia.cite} onOpen={openCite} />
                    </>
                  ) : null}
                </Fact>
              ) : null}

              {exp.nextHop ? (
                <Fact label="Next">
                  {orNotObserved(hop.nextHop, (v) => <span className="hop__mono">{v}</span>, {
                    what: "next-hop address",
                    compact: true,
                  })}
                  <span className="hop__sep">→</span>
                  {orNotObserved(hop.nextHost, (v) => <span className="hop__host-inline">{v}</span>, {
                    what: "next host",
                    why: "no host in this collection owns that next-hop address, so the path cannot be followed further",
                    compact: true,
                  })}
                </Fact>
              ) : exp.terminalNote !== null ? (
                <Fact label="Next">
                  <span className="hop__note">{exp.terminalNote}</span>
                </Fact>
              ) : null}

              {route !== null ? <RouteFact route={route} decided={routeDecided} onOpenCite={openCite} /> : null}
              {deciderIsHypothesis && undecidedBy === null ? (
                <Fact label="Filter">
                  <span className="hop__note" data-acl-unbound="">
                    no observed filter binding — undecided: no access-group binding on this hop was observed, so no list is known to have decided it
                  </span>
                </Fact>
              ) : null}
              {acl !== null ? (
                <AclFact decider={acl} decided={aclDecided} hypothesis={isHypothesis(acl)} onOpenCite={openCite} />
              ) : null}
              {decidingAclSeparate !== null ? (
                <AclFact decider={decidingAclSeparate} decided hypothesis={isHypothesis(decidingAclSeparate)} onOpenCite={openCite} />
              ) : null}
              {fallback.length > 0 ? (
                <Fact label="ACL choice · hypothesis">
                  <span className="hop__note" data-acl-fallback="">
                    {fallbackSentence(hop, fallback)}
                  </span>
                </Fact>
              ) : null}
              {decider !== null && decider.kind === "absence" ? (
                <AbsenceFact ev={decider.ev} onOpenCite={openCite} />
              ) : null}
              {decider !== null && decider.kind === "unresolved" && decider.ev.kind !== "acl" ? (
                <Fact label="Decided by" decided>
                  <span className="hop__unresolved">
                    {decider.ev.label}
                    <span className="hop__warn">{` — the record at ${decider.ev.cite} could not be resolved`}</span>
                  </span>
                  <CiteLink cite={decider.ev.cite} onOpen={openCite} />
                </Fact>
              ) : null}
            </dl>

            {hop.alternatives.length > 0 ? (
              <Disclosure
                className="hop__why-not"
                summary={`Why not the others? ${hop.alternatives.length} route${
                  hop.alternatives.length === 1 ? "" : "s"
                } considered and beaten`}
              >
                <Alternatives routes={hop.alternatives} host={hop.host} dstIp={trace.flow.dstIp} onOpenCite={openCite} />
              </Disclosure>
            ) : ribCollected ? (
              <p className="hop__why-none">
                No other route in this host&rsquo;s collected RIB matched, so nothing was beaten here.
              </p>
            ) : null /* no RIB was collected: no routes were compared, so there is nothing "beaten" to report */}

            {hop.evidence.length > 0 ? (
              <Disclosure
                className="hop__evidence"
                summary={`Evidence consulted at this hop (${hop.evidence.length}), in evaluation order`}
              >
                <ol className="hop__evlist">
                  {hop.evidence.map((ev, i) => (
                    <li key={`${ev.cite}-${i}`} className="hop__ev" data-kind={ev.kind}>
                      <span className="hop__ev-kind">{ev.kind}</span>
                      <span className="hop__ev-label">
                        <CitedText text={ev.label} onOpenCite={openCite} />
                      </span>
                      {ev.raw === null ? null : <code className="hop__raw">{ev.raw}</code>}
                      <CiteLink cite={ev.cite} onOpen={openCite} />
                    </li>
                  ))}
                </ol>
              </Disclosure>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
