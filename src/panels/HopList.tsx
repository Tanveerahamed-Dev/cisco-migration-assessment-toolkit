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
import { bandOfHop, type ClaimBand } from "../core/claims";
import { resolveCite } from "../core/data";
import type { AclLine, Cite, Hop, HopEvidence, HopVerdict, RouteEntry, Trace } from "../core/types";
import { VERDICT_ICON } from "../ui/icons";
import { Cite as CiteLink, Disclosure, NotObserved, orNotObserved } from "../ui/primitives";
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

export function HopVerdictBadge({ verdict }: { verdict: HopVerdict }): ReactElement {
  const Glyph = VERDICT_ICON[verdict];
  const band = bandOfVerdict(verdict);
  return (
    <span className="verdict" data-verdict={verdict} data-band={band}>
      <Glyph className="verdict__glyph" />
      <span className="verdict__word">{VERDICT_WORD[verdict]}</span>
      <span className="visually-hidden">{` — ${BAND_WORD[band]}`}</span>
    </span>
  );
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
  // `absence` is the engine's own marker for "we have no evidence here", and `svi`/`topology`
  // carry their reasoning in the label; neither has a narrower record shape worth resolving.
  return { kind: "absence", ev };
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

function expectations(verdict: HopVerdict): FieldExpectation {
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
        terminalNote: "not modelled — nothing was collected here to decide an egress from",
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
          the mirror image of rendering absence as health and just as wrong. Every other route
          source is expected to name one, so a null there is a real absence. */}
      {route.source === "connected" || route.source === "local" ? (
        <span className="hop__note">directly connected — no next-hop address</span>
      ) : (
        <>
          <span className="hop__sep">via</span>
          {orNotObserved(route.nextHop, (v) => <span className="hop__mono">{v}</span>, {
            what: "next-hop address",
            why: "the collected route names no next-hop address",
            compact: true,
          })}
        </>
      )}
      <span className="hop__meta">
        {orNotObserved(route.source, (v) => <span>{v}</span>, { what: "route source", compact: true })}
        <span className="hop__sep">·</span>
        <span className="hop__key-inline">AD</span>
        {orNotObserved(route.adminDistance, (v) => <span>{v}</span>, {
          what: "administrative distance",
          why: "the collected routing table did not record a distance for this entry",
          compact: true,
        })}
      </span>
      <CiteLink cite={route.cite} onOpen={onOpenCite} />
    </Fact>
  );
}

function AclFact({
  decider,
  decided,
  onOpenCite,
}: {
  decider: Decider;
  decided: boolean;
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
  return (
    <Fact label="ACL" decided={decided}>
      <span className="hop__mono">{`${acl} line ${line.index}`}</span>
      <span className="hop__meta">{`on ${host}`}</span>
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
  onOpenCite,
}: {
  routes: readonly RouteEntry[];
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  return (
    <table className="hop__alts">
      <caption className="visually-hidden">Routes considered at this hop and beaten by the winner</caption>
      <thead>
        <tr>
          <th scope="col">Prefix</th>
          <th scope="col">Source</th>
          <th scope="col">Next hop</th>
          <th scope="col">Out</th>
          <th scope="col">AD</th>
          <th scope="col">Evidence</th>
        </tr>
      </thead>
      <tbody>
        {routes.map((r) => (
          <tr key={`${r.prefix}-${r.cite}`}>
            <td className="hop__mono">{r.prefix}</td>
            <td>{orNotObserved(r.source, undefined, { what: "route source", compact: true })}</td>
            <td className="hop__mono">
              {r.source === "connected" || r.source === "local" ? (
                <span className="hop__note">on-link</span>
              ) : (
                orNotObserved(r.nextHop, undefined, { what: "next-hop address", compact: true })
              )}
            </td>
            <td className="hop__mono">
              {orNotObserved(r.outIntf, undefined, { what: "egress interface", compact: true })}
            </td>
            <td>
              {orNotObserved(r.adminDistance, undefined, { what: "administrative distance", compact: true })}
            </td>
            <td>
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
        No hop was simulated. The flow was rejected before any device was consulted, so this result
        describes the question, not the network.
      </p>
    );
  }

  return (
    <ol className="hoplist" ref={listRef} onKeyDown={onKeyDown} aria-label={`${trace.hops.length} hop path`}>
      {trace.hops.map((hop) => {
        const band = bandOfHop(hop);
        const active = activeIndex === hop.index;
        const exp = expectations(hop.verdict);
        const decider = hop.decidedBy === null ? null : classify(hop.decidedBy);
        const route = winningRoute(hop);
        const acl = actingAcl(hop);
        const aclDecided = decider?.kind === "acl" && acl?.kind === "acl" && acl.line.cite === decider.line.cite;
        const routeDecided = decider?.kind === "route" && route !== null && route.cite === decider.route.cite;
        /* The FIRST acl evidence item is not always the one that decided the hop — a permit that
           matched earlier and a deny that ended it are two different lines. When they differ the
           decider gets its own row: the deciding evidence is never allowed to be the one thing
           missing from the hop that it decided. */
        const decidingAclSeparate = decider?.kind === "acl" && !aclDecided ? decider : null;

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
              <HopVerdictBadge verdict={hop.verdict} />
            </button>

            <dl className="hop__facts">
              {exp.egress ? (
                <Fact label={exp.egressLabel}>
                  {orNotObserved(hop.outIntf, (v) => <span className="hop__mono">{v}</span>, {
                    what: "egress interface",
                    why: "the winning route names no outgoing interface",
                    compact: true,
                  })}
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
              {acl !== null ? <AclFact decider={acl} decided={aclDecided} onOpenCite={openCite} /> : null}
              {decidingAclSeparate !== null ? (
                <AclFact decider={decidingAclSeparate} decided onOpenCite={openCite} />
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
                <Alternatives routes={hop.alternatives} onOpenCite={openCite} />
              </Disclosure>
            ) : (
              <p className="hop__why-none">
                No other route in this host&rsquo;s collected RIB matched, so nothing was beaten here.
              </p>
            )}

            {hop.evidence.length > 0 ? (
              <Disclosure
                className="hop__evidence"
                summary={`Evidence consulted at this hop (${hop.evidence.length}), in evaluation order`}
              >
                <ol className="hop__evlist">
                  {hop.evidence.map((ev, i) => (
                    <li key={`${ev.cite}-${i}`} className="hop__ev" data-kind={ev.kind}>
                      <span className="hop__ev-kind">{ev.kind}</span>
                      <span className="hop__ev-label">{ev.label}</span>
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
