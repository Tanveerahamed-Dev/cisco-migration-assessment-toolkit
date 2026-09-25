/**
 * PathTrace.tsx — the path-trace investigation surface.
 *
 * Two questions live here, and the second is the one that matters.
 *
 *   TRACE     "can A reach B, and what stopped it?" — one five-tuple, one traversal, one verdict,
 *             with the deciding line of configuration on the hop that decided it.
 *   INTENT    "is it EVER possible for A to reach B?" — a universal claim over a finite flow space
 *             this snapshot can actually derive, searched exhaustively for its own negation.
 *
 * The second is Batfish's move and it is the reason this surface is more than a path tool: a
 * successful sample path proves nothing about a flow class, and a tool that only ever shows sample
 * paths lets a reader conclude something it never tested. So the intent search enumerates, traces
 * every flow, and reports exactly three outcomes that are never blurred into each other —
 * COUNTEREXAMPLE FOUND, NO COUNTEREXAMPLE FOUND, INDETERMINATE — each carrying the size and the
 * shape of the space it searched.
 *
 * What keeps the second question honest, mechanically:
 *   - the flow space is DERIVED from the snapshot (real subnets, real endpoint addresses, the
 *     services the collected ACLs actually name). Nothing is typed from nothing.
 *   - an undecided flow is never counted as consistent with the intent. A space containing one
 *     undecided flow is INDETERMINATE, not "no counterexample found".
 *   - "no counterexample found" ALWAYS carries the unmodelled-hosts sentence while any host in the
 *     topology has no collected RIB. On partial data, a bare "no counterexample found" is exactly
 *     the false-health claim this product exists to prevent.
 *   - the cap is part of the result. A capped enumeration reported as exhaustive is a lie about the
 *     proof, so a search that dropped flows cannot return "no counterexample found" at all.
 *
 * Responsiveness (acceptance E5): the search is the one thing here that can exceed the 200 ms
 * interaction budget, so it is budgeted separately — chunked, yielding to the event loop between
 * chunks, reporting real progress against a known denominator, and cancellable. It never blocks
 * the input handler and it is never hidden behind a frozen UI.
 */
import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
} from "react";
import { deviceById, fabric, hasRib, linksByHost } from "../core/data";
import { useInvestigation } from "../core/store";
import type { Cite, Flow, Trace, TraceOutcome } from "../core/types";
import { isDecidedOutcome, outcomeUndecidingGaps } from "../core/claims";
import { blockingHop, counterexample, refusalOf, suggestedFlows, traceFlow, unobservedPolicyInputs, type SuggestedFlow } from "../forwarding/engine";
import { ribIncompletenessSentence } from "../forwarding/rib-completeness";
import {
  FLOW_PROTOCOLS,
  flowProblemSentence,
  formatIpv4,
  formatPrefix,
  hostAddressIn,
  parseInterfaceAddress,
  parseIpv4,
  prefixContains,
  protocolCarriesPorts,
  readFlow,
  wildcardSpecificity,
  type FlowField,
  type FlowProblem,
  type Prefix,
} from "../forwarding/ip";
import { IconSearch, IconSortNone } from "../ui/icons";
import {
  Button,
  Cite as CiteLink,
  IconButton,
  Input,
  LiveRegion,
  Select,
  TabPanel,
  Tabs,
} from "../ui/primitives";
import { ClaimCard, IntentClaimCard, outcomeTallyWord, outcomeWordOf, verdictStatement } from "./ClaimCard";
import { HopList } from "./HopList";
import { CitedText } from "./cited-text";
import { deferPastPaint } from "./deferPastPaint";
import "./PathTrace.css";

/* ══ the flow form ═════════════════════════════════════════════════════════ */

export interface FlowFormState {
  srcIp: string;
  dstIp: string;
  protocol: Flow["protocol"];
  dstPort: string;
}

export interface FlowFormErrors {
  srcIp?: string;
  dstIp?: string;
  protocol?: string;
  dstPort?: string;
}

const PORTED = (p: Flow["protocol"]): boolean => protocolCarriesPorts(p);

/** Which error slot a problem belongs in. A problem with the link's SHAPE is shown with the protocol. */
const ERROR_SLOT: Readonly<Record<FlowField, keyof FlowFormErrors>> = {
  srcIp: "srcIp",
  dstIp: "dstIp",
  protocol: "protocol",
  dstPort: "dstPort",
  srcPort: "dstPort",
  flow: "protocol",
};

/**
 * Turn the shared validator's problems into one message per field.
 *
 * "Invalid input" is not a message, it is a shrug. Each message names the thing that is wrong and,
 * for an address, shows a real address from this snapshot, because the most common failure is not
 * a typo — it is a reader who does not yet know which addresses this collection can answer
 * questions about. The WORDS are `describeFlowProblem`'s (src/forwarding/ip.ts), the one owner the
 * engine's own refusal uses too; this only chooses the reader (`form` or `link`) and the example.
 */
function errorsOf(problems: readonly FlowProblem[], where: "form" | "link", protocol: string): FlowFormErrors {
  const errors: FlowFormErrors = {};
  for (const p of problems) {
    const example =
      p.field === "srcIp" ? EXAMPLE_ADDRESSES.source : p.field === "dstIp" ? EXAMPLE_ADDRESSES.destination : undefined;
    const slot = ERROR_SLOT[p.field];
    const words = flowProblemSentence(p, { where, protocol, ...(example === undefined ? {} : { example }) });
    errors[slot] = errors[slot] === undefined ? words : `${errors[slot]} ${words}`;
  }
  return errors;
}

/**
 * Validate the form through the ONE flow validator (`readFlow`, src/forwarding/ip.ts) that a shared
 * link and the engine's entry check also go through — the form used to carry its own copy of the
 * port rule, and the link carried none (2026-09-23 acceptance report, B1). The port field is hidden
 * for a protocol with no ports, so what it still holds is not part of the reader's question.
 */
export function validateFlowForm(state: FlowFormState): { errors: FlowFormErrors; flow: Flow | null } {
  const read = readFlow({
    srcIp: state.srcIp,
    dstIp: state.dstIp,
    protocol: state.protocol,
    dstPort: PORTED(state.protocol) ? state.dstPort : "",
  });
  return { errors: errorsOf(read.problems, "form", state.protocol), flow: read.flow };
}

/* ══ evidence derived once, at module load ═════════════════════════════════
   Nothing below traces a flow: building the catalogue must stay free, because it happens whether
   or not the reader ever opens the intent tab. The traces happen only when a search is run. */

interface SubnetEvidence {
  prefix: Prefix;
  text: string;
  vlan: number | null;
  gateways: string[];
  /** The FHRP virtual address, when the collection recorded one. */
  vip: string | null;
  cite: Cite;
}

/** Every subnet this collection actually observed, from the collected L3 interfaces. */
const OBSERVED_SUBNETS: readonly SubnetEvidence[] = (() => {
  const by = new Map<string, SubnetEvidence>();
  for (const r of fabric.l3) {
    if (r.host === null || r.sviIp === null) continue;
    const addr = parseInterfaceAddress(r.sviIp);
    if (addr === null) continue;
    const text = formatPrefix(addr.prefix);
    const cur = by.get(text);
    if (cur) {
      if (!cur.gateways.includes(r.host)) cur.gateways.push(r.host);
      if (cur.vip === null) cur.vip = r.vip;
      continue;
    }
    by.set(text, { prefix: addr.prefix, text, vlan: r.vlan, gateways: [r.host], vip: r.vip, cite: r.cite });
  }
  return [...by.values()].sort((a, b) => a.text.localeCompare(b.text));
})();

/** Router-owned addresses, excluded from the source sets: a gateway is not a client. */
const ROUTER_ADDRESSES: ReadonlySet<number> = (() => {
  const s = new Set<number>();
  for (const r of fabric.l3) {
    const addr = r.sviIp === null ? null : parseInterfaceAddress(r.sviIp);
    if (addr !== null) s.add(addr.ip);
    const vip = r.vip === null ? null : parseIpv4(r.vip);
    if (vip !== null) s.add(vip);
  }
  return s;
})();

export interface IntentAddress {
  ip: string;
  /** `observed` was seen in an endpoint record; `derived` is a usable address inside a real subnet. */
  provenance: "observed" | "derived";
  cite: Cite;
  note: string;
}

export interface IntentService {
  protocol: Flow["protocol"];
  dstPort: number | null;
  label: string;
  cite: Cite;
}

export interface IntentSpace {
  prefix: string;
  label: string;
  usableHosts: number;
  enumerated: number;
  cite: Cite;
}

export type IntentKind = "none-reach" | "all-reach";

export interface Intent {
  id: string;
  /** The universal claim, as one sentence. This is what the search tries to refute. */
  claim: string;
  kind: IntentKind;
  /** Why this claim is worth searching, naming the record that motivates it. */
  rationale: string;
  sources: IntentAddress[];
  destinations: IntentAddress[];
  services: readonly IntentService[];
  sourceSpace: IntentSpace;
  destSpace: IntentSpace;
}

/** Deterministic host offsets inside a subnet. No randomness: two runs enumerate the same flows. */
const DERIVED_OFFSETS: readonly number[] = [10, 50, 100, 200];

const usableHostsIn = (p: Prefix): number => (p.bits >= 31 ? 2 ** (32 - p.bits) : 2 ** (32 - p.bits) - 2);

function addressesIn(sub: SubnetEvidence, max: number, includeRouters: boolean): IntentAddress[] {
  const out: IntentAddress[] = [];
  const seen = new Set<number>();

  const observed = fabric.endpoints
    .flatMap((e) => {
      const ip = e.ip === null ? null : parseIpv4(e.ip);
      return ip === null || !prefixContains(sub.prefix, ip) ? [] : [{ ip, e }];
    })
    .sort((a, b) => a.ip - b.ip);

  for (const { ip, e } of observed) {
    if (out.length >= max || seen.has(ip)) continue;
    seen.add(ip);
    // Naming only the first record overstates a single attachment when the address is reported on
    // several hosts (critic B2, same shape as the engine's suggested-flow provenance).
    const hosts = new Set(observed.filter((o) => o.ip === ip).map((o) => o.e.host ?? "")).size;
    const where = `${e.host ?? "an unnamed host"} ${e.port ?? "(no port recorded)"}`;
    out.push({
      ip: formatIpv4(ip),
      provenance: "observed",
      cite: e.cite,
      note: hosts > 1 ? `observed as an endpoint on ${hosts} hosts (first ${where}); attachment ambiguous` : `observed as an endpoint on ${where}`,
    });
  }

  for (const off of DERIVED_OFFSETS) {
    if (out.length >= max) break;
    const ip = hostAddressIn(sub.prefix, off);
    if (ip === null || seen.has(ip)) continue;
    if (!includeRouters && ROUTER_ADDRESSES.has(ip)) continue;
    seen.add(ip);
    out.push({
      ip: formatIpv4(ip),
      provenance: "derived",
      cite: sub.cite,
      /* Derived, and said so. An unlabelled address reads as observed, and "we saw this host" is a
         much stronger statement than "this address is inside a subnet we saw". */
      note: `not itself observed — a usable host address inside ${sub.text}, which ${sub.gateways.join(" and ")} gateway${sub.gateways.length === 1 ? "s" : ""}`,
    });
  }
  return out;
}

const spaceOf = (sub: SubnetEvidence, addrs: readonly IntentAddress[]): IntentSpace => ({
  prefix: sub.text,
  label: sub.vlan === null ? sub.text : `VLAN ${sub.vlan}`,
  usableHosts: usableHostsIn(sub.prefix),
  enumerated: addrs.length,
  cite: sub.cite,
});

/**
 * The services to search: exactly the protocol/port pairs the collected ACLs name.
 *
 * Choosing them from the ACL text rather than from a list of well-known ports is what makes the
 * search relevant to THIS network: the lines that exist are the lines that can decide a flow, and
 * a service no collected rule mentions can only ever fall through to a catch-all.
 */
const ACL_SERVICES: readonly IntentService[] = (() => {
  const by = new Map<string, IntentService>();
  // Sorted, then values only: the host and ACL name fix the ORDER of the walk, and the citation on
  // each line already names both, so nothing here needs to carry them separately.
  const hosts = Object.entries(fabric.acls).sort(([a], [b]) => a.localeCompare(b));
  for (const [, named] of hosts) {
    for (const [, lines] of Object.entries(named).sort(([a], [b]) => a.localeCompare(b))) {
      for (const line of lines) {
        const proto = (line.proto ?? "").toLowerCase();
        if (proto !== "tcp" && proto !== "udp" && proto !== "icmp") continue;
        const op = line.dport === null ? "" : line.dport.op.toLowerCase();
        const port =
          proto === "icmp" ? null : op === "eq" || op === "range" ? (line.dport?.val ?? null) : null;
        if (proto !== "icmp" && port === null) continue;
        const label = port === null ? proto : `${proto}/${port}`;
        if (by.has(label)) continue;
        by.set(label, {
          protocol: proto as Flow["protocol"],
          dstPort: port,
          label,
          cite: line.cite,
        });
      }
    }
  }
  return [...by.values()].sort((a, b) => a.label.localeCompare(b.label));
})();

/** Destination prefixes a collected ACL names explicitly — the things policy is written about. */
const PROTECTED_PREFIXES: readonly { text: string; cite: Cite; acl: string; host: string }[] = (() => {
  const out: { text: string; cite: Cite; acl: string; host: string }[] = [];
  const seen = new Set<string>();
  for (const [host, named] of Object.entries(fabric.acls).sort(([a], [b]) => a.localeCompare(b))) {
    for (const [acl, lines] of Object.entries(named).sort(([a], [b]) => a.localeCompare(b))) {
      for (const line of lines) {
        const d = line.dst;
        if (d === null || d.ip === null || d.wild === null) continue;
        /* `wildcardSpecificity` takes the wildcard VALUE, not a prefix length: feeding it the
           output of `parseWildcard` (which already returns a length) silently produced /30s here
           and emptied the whole catalogue. Parsed as an address, exactly as the engine does. */
        const bits = wildcardSpecificity(parseIpv4(d.wild) ?? 0xffffffff);
        // A /0 is "any" and a /32 is one host: neither is a subnet policy is written ABOUT.
        if (bits === 0 || bits === 32) continue;
        const text = `${d.ip}/${bits}`;
        if (seen.has(text)) continue;
        seen.add(text);
        out.push({ text, cite: line.cite, acl, host });
      }
    }
  }
  return out;
})();

const SRC_MAX = 4;
const DST_MAX = 3;

/**
 * The example each address field shows — its placeholder, and the "for example" in its validation
 * message. ONE PER FIELD (acceptance C2, 2026-09-22): a single shared example put "10.0.10.50" in
 * both Source IP and Destination IP, so the empty form suggested a flow from a host to itself, the
 * one question nobody asks.
 *
 * Both come from the same evidence the intent catalogue uses (`addressesIn`), so neither is typed
 * from nothing:
 *   - the SOURCE is a client address inside an observed subnet, an observed endpoint when there is
 *     one (the subnet with an observed endpoint is preferred for exactly that reason);
 *   - the DESTINATION is a client address in a DIFFERENT observed subnet, preferring one a collected
 *     ACL names, because that is where policy decides a flow and so where a trace is most telling.
 * Router-owned addresses are excluded from both: a gateway is not a client. Only when the snapshot
 * observed a single subnet does the destination fall back to a second address inside it, and only
 * when it observed none do the fields show RFC 5737 documentation addresses, which can never be
 * mistaken for a host on this network.
 */
const EXAMPLE_ADDRESSES: { readonly source: string; readonly destination: string } = (() => {
  const clients = (sub: SubnetEvidence): IntentAddress[] =>
    addressesIn(sub, SRC_MAX, false).filter((a) => {
      const v = parseIpv4(a.ip);
      return v !== null && !ROUTER_ADDRESSES.has(v);
    });
  const srcSub =
    OBSERVED_SUBNETS.find((s) => clients(s)[0]?.provenance === "observed") ??
    OBSERVED_SUBNETS.find((s) => clients(s).length > 0) ??
    null;
  const source = srcSub === null ? null : (clients(srcSub)[0]?.ip ?? null);

  const named = (s: SubnetEvidence): boolean => PROTECTED_PREFIXES.some((p) => p.text === s.text);
  const others = OBSERVED_SUBNETS.filter((s) => s !== srcSub);
  let destination: string | null = null;
  for (const s of [...others.filter(named), ...others.filter((s) => !named(s))]) {
    destination = clients(s)[0]?.ip ?? null;
    if (destination !== null) break;
  }
  if (destination === null && srcSub !== null) {
    destination = clients(srcSub).find((a) => a.ip !== source)?.ip ?? null;
  }
  return { source: source ?? "192.0.2.10", destination: destination ?? "192.0.2.20" };
})();

/**
 * The intents on offer, constructed from the snapshot rather than written down.
 *
 * Two shapes, both of which a reader can check against the data:
 *   - for every observed subnet, "no flow from here reaches the subnet an ACL protects";
 *   - for every observed subnet with a recorded gateway address, "every address observed here
 *     reaches that gateway".
 * If the snapshot named no protected prefix, or observed no subnet, the catalogue is empty and the
 * UI says so — an offer of intents this data cannot support would be worse than none.
 */
export function intentCatalog(): Intent[] {
  const out: Intent[] = [];
  const protectedTarget = PROTECTED_PREFIXES[0] ?? null;

  if (protectedTarget !== null) {
    const dstSub = OBSERVED_SUBNETS.find((s) => s.text === protectedTarget.text) ?? null;
    if (dstSub !== null) {
      const dstAddrs = addressesIn(dstSub, DST_MAX, false);
      for (const src of OBSERVED_SUBNETS) {
        if (src.text === dstSub.text) continue;
        const srcAddrs = addressesIn(src, SRC_MAX, false);
        if (srcAddrs.length === 0 || dstAddrs.length === 0) continue;
        out.push({
          id: `no-reach-${src.text}-${dstSub.text}`.replace(/[./]/g, "_"),
          kind: "none-reach",
          claim: `No flow from ${src.vlan === null ? src.text : `VLAN ${src.vlan} (${src.text})`} reaches ${dstSub.text}.`,
          rationale: `${dstSub.text} is the destination ${protectedTarget.host} names in ACL ${protectedTarget.acl} (${protectedTarget.cite}), so whether ${src.text} can reach it is a policy question this snapshot can be searched over.`,
          sources: srcAddrs,
          destinations: dstAddrs,
          services: ACL_SERVICES,
          sourceSpace: spaceOf(src, srcAddrs),
          destSpace: spaceOf(dstSub, dstAddrs),
        });
      }
    }
  }

  for (const sub of OBSERVED_SUBNETS) {
    if (sub.vip === null) continue;
    const srcAddrs = addressesIn(sub, SRC_MAX, false);
    const observedHere = srcAddrs.filter((a) => a.provenance === "observed");
    if (observedHere.length === 0) continue;
    const gateway: IntentAddress = {
      ip: sub.vip,
      provenance: "observed",
      cite: sub.cite,
      note: `the virtual gateway address recorded for ${sub.text} on ${sub.gateways.join(" and ")}`,
    };
    out.push({
      id: `reach-gateway-${sub.text}`.replace(/[./]/g, "_"),
      kind: "all-reach",
      /* The claim says "every address in", not "every address observed in": the search enumerates
         observed addresses AND derived ones, and a claim narrower than the space it searches would
         misdescribe its own result. The address list marks which is which, and the search-cost
         block states how many of the subnet's usable addresses were enumerated. */
      claim: `Every address in ${sub.vlan === null ? sub.text : `VLAN ${sub.vlan} (${sub.text})`} reaches its gateway ${sub.vip}.`,
      rationale: `${sub.vip} is the gateway address the collection recorded for ${sub.text} (${sub.cite}), and ${observedHere.length} address(es) here were actually observed on the wire; a client that cannot reach its own gateway is a first-order fault, so the claim is worth refuting.`,
      sources: srcAddrs,
      destinations: [gateway],
      services: ACL_SERVICES,
      sourceSpace: spaceOf(sub, srcAddrs),
      destSpace: spaceOf(sub, [gateway]),
    });
  }

  return out;
}

/* ══ the intent search ═════════════════════════════════════════════════════ */

/** The responsiveness cap. Exceeding it withdraws the verdict rather than shrinking it silently. */
export const INTENT_FLOW_CAP = 400;

/** Flows traced between two yields. Sized so a chunk stays well inside one animation frame. */
const CHUNK = 12;

export interface IntentPlan {
  intent: Intent;
  flows: Flow[];
  enumerated: number;
  dropped: number;
  cap: number;
}

export function planIntent(intent: Intent, cap: number = INTENT_FLOW_CAP): IntentPlan {
  const flows: Flow[] = [];
  let enumerated = 0;
  for (const s of intent.sources) {
    for (const d of intent.destinations) {
      if (s.ip === d.ip) continue; // a flow to itself is not a question, and it must not pad the denominator
      for (const svc of intent.services) {
        enumerated += 1;
        if (flows.length < cap) {
          flows.push({
            srcIp: s.ip,
            dstIp: d.ip,
            protocol: svc.protocol,
            dstPort: svc.dstPort,
            srcPort: null,
          });
        }
      }
    }
  }
  return { intent, flows, enumerated, dropped: enumerated - flows.length, cap };
}

export interface IntentFinding {
  flow: Flow;
  trace: Trace;
}

export interface ReasonRow {
  reason: string;
  count: number;
  cite: Cite;
}

export type IntentOutcome = "counterexample-found" | "no-counterexample-found" | "indeterminate";

export interface IntentVerdict {
  intent: Intent;
  outcome: IntentOutcome;
  counterexamples: IntentFinding[];
  enumerated: number;
  searched: number;
  dropped: number;
  cap: number;
  decided: number;
  undecided: number;
  satisfying: number;
  /** The sentence that names the bound. Rendered first, never collapsed. */
  boundSentence: string;
  /** Mandatory whenever any host in the topology has no collected RIB. */
  unmodelledSentence: string | null;
  intendedEffect: string;
  collateral: string[];
  undecidedReasons: ReasonRow[];
  decidedReasons: ReasonRow[];
  hostsTouched: string[];
  unmodelledHostsSeen: string[];
  /**
   * The deduped union of `Trace.caveats` across every flow this search actually traced.
   *
   * WHY A UNIVERSAL CLAIM NEEDS THESE MORE THAN A SINGLE TRACE DOES. A single trace card renders
   * its caveats and the reader sees eleven bounds under one answer about one flow. The intent card
   * makes the strongest claim in the product — "no counterexample found" over a whole flow class —
   * and used to render none of them at all, discarding every caveat the constituent traces
   * produced. The bounds that matter most (an FHRP role read as a point-in-time observation, an
   * ACL never applied because no `ip access-group` binding was collected, forward-direction only,
   * ECMP not modelled) bound a universal statement far harder than they bound one flow.
   */
  caveats: IntentCaveat[];
}

export interface IntentCaveat {
  /** The caveat text, verbatim from the trace that produced it. */
  text: string;
  /** How many of the searched flows carried it. `searched` means every one of them. */
  flows: number;
}

export interface IntentSearch {
  plan: IntentPlan;
  cursor: number;
  counterexamples: IntentFinding[];
  satisfying: number;
  undecided: number;
  outcomeCounts: Record<TraceOutcome, number>;
  /** The subset of `outcomeCounts` whose outcome was DECIDED (`isDecidedOutcome`). The tally line
   *  reads both, so a raw "24 denied" cannot sit under "0 decided". */
  decidedOutcomeCounts: Record<TraceOutcome, number>;
  decidedReasons: Map<string, ReasonRow>;
  undecidedReasons: Map<string, ReasonRow>;
  hostsTouched: Set<string>;
  /** The host each traced flow ENTERED at. Ingress is chosen from point-in-time FHRP/SVI evidence,
   *  so every counterfactual this search states is conditional on it. */
  ingressHosts: Set<string>;
  /** The records each ingress was chosen from (the entry hop's SVI/route evidence), cited wherever
   *  the ingress assumption is stated. */
  ingressCites: Set<string>;
  unmodelledHostsSeen: Set<string>;
  /** Terminal hop verdicts among the flows consistent with the intent — the collateral question. */
  satisfyingVerdicts: Map<string, number>;
  /** Caveat text → how many searched flows carried it. Deduped here so the union is O(1) to read. */
  caveats: Map<string, number>;
}

/**
 * Does this flow contradict the intent?
 *
 * `indeterminate` and `out-of-scope` are neither — they are undecided, and an undecided flow never
 * counts towards the intent holding. Folding them into "consistent" is how a search over partial
 * evidence reports a clean sweep it did not perform.
 *
 * A "delivered" outcome is only DECIDED when nothing on its path was left undecided
 * (`isDefiniteDelivery`). The search once reported 24 decided contradictions of a none-reach
 * intent, every one a delivery whose own caveat said "at best indeterminate, never a definite
 * permit" — a refutation built on evidence the engine had already said it could not decide. The
 * engine no longer emits such a delivery; this guard holds the rule here too, over the trace rather
 * than its outcome word, so the tally cannot regress if a new source of undecided evidence appears.
 */
function contradicts(kind: IntentKind, trace: Trace): boolean | null {
  const outcome = trace.outcome;
  /* The same rule for a denial. Where the `ip access-group` binding was not observed, a denial by a list the
     specificity heuristic selected says what that list WOULD do — not that it is applied on this
     path. It once reported 12 "decided" contradictions of a reach-gateway intent, every one resting
     on a line the scope block beneath listed as undecidable. It is undecided either way round.
     Both rules are owned by `claims.ts :: isDecidedOutcome`, which the verdict and hop bands also
     ask — so the tally and the colour on the card cannot disagree about what was decided. */
  if (!isDecidedOutcome(trace)) return null;
  return kind === "none-reach" ? outcome === "delivered" : outcome !== "delivered";
}

export function startIntentSearch(intent: Intent, cap: number = INTENT_FLOW_CAP): IntentSearch {
  return {
    plan: planIntent(intent, cap),
    cursor: 0,
    counterexamples: [],
    satisfying: 0,
    undecided: 0,
    outcomeCounts: { delivered: 0, dropped: 0, denied: 0, indeterminate: 0, "out-of-scope": 0 },
    decidedOutcomeCounts: { delivered: 0, dropped: 0, denied: 0, indeterminate: 0, "out-of-scope": 0 },
    decidedReasons: new Map(),
    undecidedReasons: new Map(),
    hostsTouched: new Set(),
    ingressHosts: new Set(),
    ingressCites: new Set(),
    unmodelledHostsSeen: new Set(),
    satisfyingVerdicts: new Map(),
    caveats: new Map(),
  };
}

/**
 * The record that decided a trace: the evidence on the hop that ended it; for a trace that consulted
 * no device, the engine's OWN record of why (`refusalOf`); failing both, the coverage matrix. One rule
 * for the intent search's reason rows (`record`, below) and the preset cards' verdict words, so a
 * reason row and the word it groups cannot name different records for the same trace.
 */
function decidingCiteOf(trace: Trace): Cite {
  const last = trace.hops[trace.hops.length - 1] ?? null;
  return last?.decidedBy?.cite ?? (last === null ? refusalOf(trace)?.cite : undefined) ?? fabric.coverage.cite;
}

/** Group by the CITATION that ended the trace, so one bucket is one piece of evidence. */
function record(into: Map<string, ReasonRow>, trace: Trace): void {
  const last = trace.hops[trace.hops.length - 1] ?? null;
  const ev = last?.decidedBy ?? null;
  /* A hop-less trace is grouped and explained by the engine's OWN record of why it consulted no
     device (`refusalOf`), never by `hops.length === 0` alone: that once labelled 20 intra-subnet
     flows inside the observed 10.0.10.0/24 "outside every subnet this collection observed"
     (2026-09-22 critic, B1). */
  const refusal = last === null ? refusalOf(trace) : null;
  const key = ev !== null ? ev.cite : refusal !== null ? `refusal|${refusal.key}` : "no-hop";
  const reason =
    ev !== null
      ? `${last?.host ?? "an unnamed host"}: ${ev.label}`
      : refusal !== null
        ? refusal.reason
        : last === null
          ? "no device was consulted for this flow, and the engine recorded no reason why"
          : `${last.host}: the hop that ended this trace recorded no deciding evidence`;
  /* A row under "could not be decided" that reads "… denies this flow" needs its reason said: the
     line decides what the list would do; whether the list is applied here was not observed. */
  /* The same for every other undecided input the engine names — an uncollected ACL, an FHRP ingress
     the alternate member does not reproduce, an unobserved ingress port — so an undecided row never
     reads as a bare "core1 permits" with nothing to say why it was not counted as decided. */
  /* The gap named is one that ACTUALLY undecided the outcome (claims.ts `outcomeUndecidingGaps`), not
     merely the first on the trace: for a no-route drop at core2 that first gap was "no ACLs
     collected", which cannot undecide a drop — the reason that does, the incomplete routing table,
     went unsaid. */
  const unbound = isDecidedOutcome(trace)
    ? undefined
    : (outcomeUndecidingGaps(trace)[0] ?? unobservedPolicyInputs(trace)[0]);
  const fullReason = unbound === undefined ? reason : `${reason} — but ${unbound.label}`;
  const cite = decidingCiteOf(trace);
  const row = into.get(key);
  if (row) row.count += 1;
  else into.set(key, { reason: fullReason, count: 1, cite });
}

/** Trace up to `budget` flows. Mutates in place: the caller owns the yield between chunks. */
export function stepIntentSearch(s: IntentSearch, budget: number): void {
  const end = Math.min(s.cursor + budget, s.plan.flows.length);
  for (; s.cursor < end; s.cursor += 1) {
    const flow = s.plan.flows[s.cursor];
    if (flow === undefined) continue;
    const trace = traceFlow(flow);
    s.outcomeCounts[trace.outcome] += 1;
    if (isDecidedOutcome(trace)) s.decidedOutcomeCounts[trace.outcome] += 1;
    for (const h of trace.hops) s.hostsTouched.add(h.host);
    const entry = trace.hops[0];
    if (entry !== undefined) {
      s.ingressHosts.add(entry.host);
      const basis = entry.evidence.find((e) => e.kind === "svi" || e.kind === "route") ?? entry.evidence[0];
      if (basis !== undefined) s.ingressCites.add(basis.cite);
    }
    for (const h of trace.unmodelledHosts) s.unmodelledHostsSeen.add(h);
    /* Every bound the constituent traces produced is kept. Discarding them was how the strongest
       claim in the product came to carry fewer caveats than the weakest one. */
    for (const cv of trace.caveats) s.caveats.set(cv, (s.caveats.get(cv) ?? 0) + 1);

    const verdict = contradicts(s.plan.intent.kind, trace);
    if (verdict === null) {
      s.undecided += 1;
      record(s.undecidedReasons, trace);
    } else if (verdict) {
      s.counterexamples.push({ flow, trace });
      record(s.decidedReasons, trace);
    } else {
      s.satisfying += 1;
      record(s.decidedReasons, trace);
      const last = trace.hops[trace.hops.length - 1];
      if (last) s.satisfyingVerdicts.set(last.verdict, (s.satisfyingVerdicts.get(last.verdict) ?? 0) + 1);
    }
  }
}

const byCountDesc = (a: ReasonRow, b: ReasonRow): number => b.count - a.count || a.reason.localeCompare(b.reason);

/* The tally words (decided, and the lead of `claims.ts :: undecidedOutcomeWord` for returned-but-not-
   decided) are `ClaimCard.tsx :: outcomeTallyWord` — the one outcome→word table, beside the card's. */

export function finishIntentSearch(s: IntentSearch): IntentVerdict {
  const c = fabric.coverage;
  const total = fabric.devices.length;
  const withoutRib = total - c.hostsWithRoutes;
  const searched = s.cursor;
  const decided = searched - s.undecided;
  const { dropped, cap, enumerated, intent } = s.plan;

  /* A capped search cannot return "no counterexample found": the flows it never traced could each
     be the counterexample. Reporting it as a clean result is the exact overclaim this surface is
     built to refuse, so the cap forces INDETERMINATE and says how many were dropped. */
  const outcome: IntentOutcome =
    s.counterexamples.length > 0
      ? "counterexample-found"
      : s.undecided > 0 || dropped > 0
        ? "indeterminate"
        : "no-counterexample-found";

  /* A collected RIB is not a complete one. Every traversed table the snapshot itself shows to be
     incomplete (./rib-completeness.ts) is named in the bound, with why — "under the collected RIBs
     of core1 and core2" alone read as if those two tables were whole, while 60 drops rested on
     core2's four connected routes (2026-09-21 critic, B1 blocker). */
  const partialRibs = c.routableHosts
    .filter((h) => s.hostsTouched.has(h))
    .map((h) => ribIncompletenessSentence(h))
    .filter((x): x is string => x !== null);
  /* Every clause of the bound names the record behind it — the coverage matrix for the RIB hosts, and
     each incompleteness reason its own record (./rib-completeness.ts) — so the strongest claim in the
     product is never displayed without its citations (acceptance B6). */
  const under =
    `under the collected RIBs of ${c.routableHosts.join(" and ")} only (${c.hostsWithRoutes} of ${total} hosts, ${c.cite})` +
    (partialRibs.length === 0 ? "" : ` — and ${partialRibs.join("; ")}`);
  const spaceText = `${searched} flows derivable from ${intent.sources.length} source address(es) and ${intent.destinations.length} destination address(es) across ${intent.services.length} service(s)`;

  const first = s.counterexamples[0];
  /* The record the counterexample's own trace was decided by. */
  const firstLast = first === undefined ? undefined : first.trace.hops[first.trace.hops.length - 1];
  const firstCite = firstLast?.decidedBy?.cite ?? (firstLast === undefined ? c.cite : `routes.${firstLast.host}`);
  const boundSentence =
    outcome === "counterexample-found" && first !== undefined
      ? `A counterexample was found: ${first.flow.protocol} ${first.flow.srcIp} to ${first.flow.dstIp}${
          first.flow.dstPort === null ? "" : `:${first.flow.dstPort}`
        } is ${outcomeWordOf(first.trace)} (${firstCite}), which contradicts the intent. ${s.counterexamples.length} of the ${searched} flows searched contradict it, ${under}.${
          dropped > 0
            ? ` ${dropped} of the ${enumerated} flows this intent implies were never traced because the enumeration was capped at ${cap}, so the contradicting count is a lower bound.`
            : ""
        }`
      : outcome === "no-counterexample-found"
        ? `No counterexample was found among the ${spaceText}, ${under}.`
        : `${s.undecided} of the ${searched} flows searched could not be decided${
            dropped > 0 ? `, and ${dropped} of the ${enumerated} flows this intent implies were never traced because the enumeration was capped at ${cap}` : ""
          }, so this intent is undecided over its own flow space, ${under}.`;

  /* The mandatory sentence. It is not conditional on the outcome and it is not conditional on
     whether the search happened to touch an unmodelled host: while ANY host lacks a RIB, a flow
     that would have crossed it could violate the intent without this search seeing it. */
  /* The hosts are NAMED, not merely counted. A count tells the reader how big the hole is; only
     the names tell them whether the hole is where their question lives. They are derived here
     rather than stored, so the sentence cannot go stale against the model: every device that is
     not in `coverage.routableHosts` has no collected RIB. */
  const unmodelledHosts = fabric.devices.map((d) => d.host).filter((h) => !c.routableHosts.includes(h));
  const unmodelledSentence =
    withoutRib > 0
      ? `Flows through the ${withoutRib} host(s) with no collected RIB were not modelled and could violate this intent (${unmodelledHosts.join(", ")}; ${c.cite}).${
          s.unmodelledHostsSeen.size > 0
            ? ` ${[...s.unmodelledHostsSeen].sort().join(", ")} ${s.unmodelledHostsSeen.size === 1 ? "was" : "were"} reached by this search itself and could not be modelled there (${c.cite}).`
            : ""
        }`
      : null;

  const intendedEffect =
    intent.kind === "none-reach"
      ? `The intent asserts that nothing from ${intent.sourceSpace.prefix} (${intent.sourceSpace.cite}) reaches ${intent.destSpace.prefix} (${intent.destSpace.cite}). Inside the searched space, ${s.counterexamples.length} flow(s) reach it, ${s.satisfying} do not, and ${s.undecided} could not be decided.`
      : `The intent asserts that everything observed in ${intent.sourceSpace.prefix} (${intent.sourceSpace.cite}) reaches ${intent.destinations[0]?.ip ?? "its gateway"} (${intent.destSpace.cite}). Inside the searched space, ${s.satisfying} flow(s) reach it, ${s.counterexamples.length} do not, and ${s.undecided} could not be decided.`;

  const collateral: string[] = [];
  /* Each outcome is split into what was decided and what the engine returned but did not decide,
     in the same words the single-trace headline uses. "6 delivered, 24 denied, 30 indeterminate"
     once sat under "0 decided · 60 could not be decided" (2026-09-22 critic, B1). */
  const counts = (Object.keys(s.outcomeCounts) as TraceOutcome[])
    .flatMap((k) => {
      const n = s.outcomeCounts[k];
      const d = s.decidedOutcomeCounts[k];
      const parts: string[] = [];
      if (d > 0) parts.push(`${d} ${outcomeTallyWord(k, true)}`);
      if (n - d > 0) parts.push(`${n - d} ${outcomeTallyWord(k, false)}`);
      return parts;
    })
    .join(", ");
  collateral.push(
    `Outcomes inside the searched space, as the modelled path returned them — ${decided} of ${searched} decided: ${counts || "none — no flow was traced"}.`,
  );
  collateral.push(
    s.hostsTouched.size === 0
      ? "No host was traversed: every flow was refused before a device was consulted."
      : `Hosts traversed: ${[...s.hostsTouched]
          .sort()
          .map((h) => (hasRib(h) ? `${h} (routes.${h})` : `${h} (${c.cite})`))
          .join(", ")}. No other device in the topology was consulted, so nothing here describes them.`,
  );

  /* The intended-versus-unintended reading. An intent that holds because no route exists is a
     different fact from an intent that holds because a filter denies the traffic, and the
     difference decides what a change would break: adding a route would silently end the first. */
  const noRoute = s.satisfyingVerdicts.get("no-route") ?? 0;
  const denied = s.satisfyingVerdicts.get("denied") ?? 0;
  /* No counterfactual is stated. "A route added later would end this result without any change to
     an ACL" was once printed here, and it was false on the shipped data: under the alternate FHRP
     ingress the caveats name (core1, which holds the connected route) the same 60 flows are all
     DENIED by an ACL — adding a route would not end the result (critic B2, 2026-09-21). What a
     change would do depends on paths this search never traced, so it only says what it observed,
     at the ingress it assumed. */
  const ingress = [...s.ingressHosts].sort();
  const atIngress =
    ingress.length === 0
      ? ""
      : ` with ${ingress.join(" and ")} as ingress — chosen from point-in-time FHRP/SVI evidence (${[...s.ingressCites].sort().join(", ") || c.cite}); another member of the group may be the ingress, and its forwarding and filtering were not searched here`;
  if (intent.kind === "none-reach" && s.satisfying > 0) {
    if (noRoute === s.satisfying) {
      collateral.push(
        `Every flow consistent with this intent stops for want of a route${atIngress}. No filter decided any of them, so this result is an absence of forwarding, not an observed policy decision; whether a filter would stop these flows on a path that does have a route was not evaluated.`,
      );
    } else if (denied > 0 && noRoute > 0) {
      collateral.push(
        `${denied} flow(s) are stopped by a filter and ${noRoute} for want of a route${atIngress}. The two rest on different evidence; how either would change under a routing change was not evaluated.`,
      );
    }
  }
  if (dropped > 0) {
    collateral.push(
      `${dropped} of the ${enumerated} enumerated flows were not traced because of the ${cap}-flow cap, so this result says nothing whatever about them.`,
    );
  }

  /* The deduped union of every constituent trace's caveats. Ordered by how much of the searched
     space each one bounds — a caveat carried by every flow bounds the universal claim completely,
     one carried by a handful bounds it only there — then alphabetically so the list is stable.
     A search that traced nothing says so rather than rendering an empty, reassuring list. */
  const caveats: IntentCaveat[] =
    searched === 0
      ? [
          {
            text: "No flow was traced, so this result carries no per-flow bound at all. The scope sentences above are the only limits stated, and they are not a substitute for having searched.",
            flows: 0,
          },
        ]
      : [...s.caveats.entries()]
          .map(([text, flows]) => ({ text, flows }))
          .sort((a, b) => b.flows - a.flows || a.text.localeCompare(b.text));

  const undecidedReasons = [...s.undecidedReasons.values()].sort(byCountDesc);
  if (dropped > 0) {
    undecidedReasons.push({
      reason: `not traced at all — the enumeration was capped at ${cap} flows for responsiveness`,
      count: dropped,
      cite: fabric.coverage.cite,
    });
  }

  return {
    intent,
    outcome,
    counterexamples: s.counterexamples,
    enumerated,
    searched,
    dropped,
    cap,
    decided,
    undecided: s.undecided,
    satisfying: s.satisfying,
    boundSentence,
    unmodelledSentence,
    intendedEffect,
    collateral,
    undecidedReasons,
    decidedReasons: [...s.decidedReasons.values()].sort(byCountDesc),
    hostsTouched: [...s.hostsTouched].sort(),
    unmodelledHostsSeen: [...s.unmodelledHostsSeen].sort(),
    caveats,
  };
}

/** The whole search, synchronously. The UI never calls this; tests and a headless run do. */
export function runIntentSearch(intent: Intent, cap: number = INTENT_FLOW_CAP): IntentVerdict {
  const s = startIntentSearch(intent, cap);
  stepIntentSearch(s, s.plan.flows.length);
  return finishIntentSearch(s);
}

/* ══ the surface ═══════════════════════════════════════════════════════════ */

export const flowKey = (f: Flow): string => `${f.protocol}|${f.srcIp}|${f.dstIp}|${f.dstPort ?? ""}`;

const PROTOCOL_OPTIONS = [
  { value: "tcp", label: "TCP" },
  { value: "udp", label: "UDP" },
  { value: "icmp", label: "ICMP" },
  { value: "ip", label: "IP (any protocol)" },
] as const;

/**
 * The records behind a trace's verdict word: the evidence that ended it (`decidingCiteOf`), then every
 * input the claims owner says left the outcome undecided (`outcomeUndecidingGaps`) — the "core1's
 * routing table incomplete; ingress via core2 not modelled equivalently" a preset's word spells out.
 * A verdict word printed without these was a claim with nothing behind it (acceptance B6, wave 7).
 */
function verdictCitesOf(trace: Trace): Cite[] {
  return [...new Set([decidingCiteOf(trace), ...outcomeUndecidingGaps(trace).map((g) => g.cite)])];
}

function Presets({
  onPick,
  onOpenCite,
  title,
}: {
  onPick: (f: Flow) => void;
  onOpenCite?: ((cite: Cite) => void) | undefined;
  title: string;
}): ReactElement {
  /* Derived from the snapshot and TRACED by the engine at module load, so each one advertises the
     outcome it actually produced. A form with no starting point is a dead end for anyone who does
     not already know which addresses this collection can answer for. */
  /* Each preset's word and colour come from the SAME rule as the card it opens (claims.ts
     `bandOfTrace` / `undecidedOutcomeWord`), never from the outcome word alone: the list once drew a
     green "delivered" and a red "denied" for two flows whose own cards read "the simulation ran and
     declined to decide this flow" (2026-09-21 critic, B1). The trace is the engine's (memoised
     per module, sub-millisecond), so the preset and the card cannot disagree. */
  /* And each preset carries the BOUNDS of that word — the trace's own scope clause, badge and caveat
     count (ClaimCard `verdictStatement`). A preset that stated its outcome bare, over a rationale
     calling an undecided denial "the blocking-hop answer", was a verdict with no claim attached
     (acceptance B2). The rationale now names the question; the trace states the answer. */
  /* THE CARD IS NOT THE BUTTON (acceptance B6, wave 7). The whole card used to be one
     `<button onClick={run}>`, so the rationale and the provenance note — which print their records
     (`acls.core1.PROTECT_SERVERS[2]`, `l3_forwarding[5]` …) — were inert text inside a run control:
     clicking the `l3_forwarding[5]` sentence re-ran the preset's flow and opened no Inspector, and no
     citation there could have been a control, because a button may not contain another. So the run
     action is one button (the question: its title and its flow), and everything the card SAYS about
     that question sits beside it, rendered through `CitedText` so every citation in it is the same
     control every other surface uses. The verdict word carries the records that decided it and the
     bounds carry the coverage record their denominator is read from. The button's description points
     at the verdict and its bounds, so a reader who reaches the button alone still hears what running
     it will answer (B2). */
  const flows = useMemo(
    () =>
      suggestedFlows().map((s: SuggestedFlow) => {
        const trace = traceFlow(s.flow);
        return { s, verdict: verdictStatement(trace), cites: verdictCitesOf(trace) };
      }),
    [],
  );
  const baseId = useId();
  const open = useCallback((c: Cite) => onOpenCite?.(c), [onOpenCite]);
  return (
    <div className="pt-presets">
      <h3 className="pt-presets__title">{title}</h3>
      <ul className="pt-presets__list">
        {flows.map(({ s, verdict, cites }, i) => {
          const verdictId = `${baseId}-${i}-verdict`;
          const boundsId = `${baseId}-${i}-bounds`;
          return (
            <li key={s.id} className="pt-preset" data-preset={s.id}>
              <button
                type="button"
                className="pt-preset__btn"
                aria-describedby={`${verdictId} ${boundsId}`}
                onClick={() => onPick(s.flow)}
              >
                <span className="pt-preset__title">{s.title}</span>
                <span className="pt-preset__flow">
                  {`${s.flow.protocol} ${s.flow.srcIp} → ${s.flow.dstIp}${s.flow.dstPort === null ? "" : `:${s.flow.dstPort}`}`}
                </span>
              </button>
              <p className="pt-preset__verdict">
                <span
                  id={verdictId}
                  className="pt-preset__outcome"
                  data-outcome={s.expectedOutcome}
                  data-band={verdict.band}
                >
                  {verdict.word}
                </span>
                {cites.map((c) => (
                  <Fragment key={c}>
                    {" "}
                    <CiteLink cite={c} onOpen={open} className="cited-text__cite" />
                  </Fragment>
                ))}
              </p>
              <p className="pt-preset__bounds" id={boundsId}>
                <CitedText text={verdict.bounds} onOpenCite={open} also={[fabric.coverage.cite]} />
              </p>
              <p className="pt-preset__why">
                <CitedText text={s.rationale} onOpenCite={open} />
              </p>
              <p className="pt-preset__prov" data-kind={s.srcProvenance.kind}>
                <CitedText text={s.srcProvenance.note} onOpenCite={open} also={[s.srcProvenance.cite]} />
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export interface PathTraceProps {
  /** Opens the raw snapshot record behind a citation. Wired to the Inspector by the shell. */
  onOpenCite?: (cite: Cite) => void;
  /** The region id from the layout contract. Override only if the shell owns the element. */
  id?: string;
}

export function PathTrace({ onOpenCite, id = "rail-path" }: PathTraceProps): ReactElement {
  const flow = useInvestigation((s) => s.flow);
  const flowRefused = useInvestigation((s) => s.flowRefused);
  const trace = useInvestigation((s) => s.trace);
  const hopIndex = useInvestigation((s) => s.hopIndex);
  const setFlow = useInvestigation((s) => s.setFlow);
  const setTrace = useInvestigation((s) => s.setTrace);
  const selectHop = useInvestigation((s) => s.selectHop);
  const selectDevice = useInvestigation((s) => s.selectDevice);
  const selectLink = useInvestigation((s) => s.selectLink);

  const [mode, setMode] = useState<string>("trace");
  const [form, setForm] = useState<FlowFormState>({
    srcIp: "",
    dstIp: "",
    protocol: "tcp",
    dstPort: "",
  });
  const [errors, setErrors] = useState<FlowFormErrors>({});
  /** Whose question the errors are about: the reader's own typing, or a link they were sent. */
  const [errorSource, setErrorSource] = useState<"form" | "link">("form");
  const [announce, setAnnounce] = useState("");
  const srcRef = useRef<HTMLInputElement>(null);
  const dstRef = useRef<HTMLInputElement>(null);
  const portRef = useRef<HTMLInputElement>(null);
  const formId = useId();
  /** The locally-committed trace until the store catches up — see the re-aim split below. */
  const [pending, setPending] = useState<{ flow: Flow; trace: Trace; hop?: number } | null>(null);
  /** Bumped by every explicit run, so re-running the SAME flow still lands on its answer. */
  const [runSeq, setRunSeq] = useState(0);
  /** Cancels the store write a `run` has deferred past the next paint, while it has not landed. */
  const runCommit = useRef<(() => void) | null>(null);

  /* `pending` is an acknowledgement of a flow the STORE is about to hold — never a second owner.
     When the store's question moves somewhere else before that write lands (a Back, a shared link,
     another surface setting a flow), the acknowledgement is stale and goes, and a `run` commit still
     in flight is dropped rather than landing afterwards and undoing the move.

     Found as a lead in the 2026-09-23 acceptance report and reproduced through real browser history
     traversal in a background tab, where no frame is painted: a restored flow's store write was
     cancelled by the next Back, nothing released `pending`, and a PARTIAL card for the flow the
     reader had left stood under a refused shared link — and stayed when the tab was shown.

     Runs only when the store's flow or refusal CHANGES, so a run's own in-flight window (store still
     on the previous flow) is untouched; the functional update compares identity, so a `pending`
     the restore effect set in this same commit is never the one released. */
  useEffect(() => {
    if (pending === null) return;
    if (flow !== null && flowKey(flow) === flowKey(pending.flow)) return;
    runCommit.current?.();
    runCommit.current = null;
    const stale = pending;
    setPending((p) => (p === stale ? null : p));
    /* `pending` is read, not tracked: only a move of the store's question can make it stale. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow, flowRefused]);

  /* The store owns the flow, so a flow that arrives from anywhere — this form, a preset, a
     counterexample, a shared URL — is traced the same way. That is what makes a link reproducible:
     the URL carries the flow, and the flow alone regenerates the result. */
  useEffect(() => {
    if (flow === null) return;
    if (trace !== null && flowKey(trace.flow) === flowKey(flow)) return;
    /* A flow with no matching trace only exists after a URL restore (first load or Back): every
       interactive writer sets flow and trace in one batch. On a restore the LINK names the hop,
       and `setTrace` parks on hop 0 by contract — so the named hop is re-applied after it, or a
       shared "hop 2 of this flow" would silently open on hop 1 (acceptance A4, URL restore). The
       device the link names is kept by App's hop re-aim, which knows a restore from a selection. */
    /* SPLIT like `run` below — acceptance E5, 2026-09-22. The two store writes here used to run
       synchronously. On a cold restore (`?s=path&flow=…`) they are the urgent re-aim commit of
       every surface, issued from a passive effect of the very first mount — the same scheduler
       task as the mount, BEFORE the first paint. Measured by review/audit-e5-sweep.mjs ("path
       trace: seed a flow by navigation"): over 200 ms in 3 of 3 repetitions, worst 711 ms in
       react's MessagePort.onmessage, and judged UNCOMMUNICATED: the boot line had been removed and
       the stage's "Drawing the 3-D fabric" status, mounted in that same commit, never painted.

       Now a restore takes the path an explicit run takes: the trace (sub-millisecond) is shown
       from LOCAL state, so this panel answers in the next frame, and the store writes that re-aim
       the queue, the device pane, the evidence rail and the fabric go to a task of their own AFTER
       that frame is painted — by which time the stage's status is on screen. The named hop is read
       NOW, before anything can move it. `pending` already carries a flow `run` is handling, and the
       returned cancel drops a write superseded before it landed (the flow changed again). */
    if (pending !== null && flowKey(pending.flow) === flowKey(flow)) return;
    const named = useInvestigation.getState().hopIndex;
    const restored = traceFlow(flow);
    const hop = named !== null && named > 0 && named < restored.hops.length ? named : null;
    setPending(hop === null ? { flow, trace: restored } : { flow, trace: restored, hop });
    return deferPastPaint(() => {
      setTrace(restored);
      if (hop !== null) selectHop(hop);
    });
    /* `pending` is read, not tracked: this effect's own setPending must not cancel its own write. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow, trace, setTrace, selectHop]);

  /* Everything below reads `shown`, not `trace`. See `run`. */

  // Keep the form showing the flow that produced the visible result, however that flow arrived.
  useEffect(() => {
    if (flow === null) return;
    setForm({
      srcIp: flow.srcIp,
      dstIp: flow.dstIp,
      protocol: flow.protocol,
      dstPort: flow.dstPort === null ? "" : String(flow.dstPort),
    });
    setErrors({});
    setErrorSource("form");
  }, [flow]);

  /* A link whose flow the validator refused (store.ts :: decodeInvestigation). It is shown back in
     the form, field by field, with the refusal in words — the same place and shape the form's own
     refusal takes — and NOTHING is traced: tracing it answered `tcp>abc` with "a tcp/NaN flow … is
     delivered" (2026-09-23 acceptance report, B1). A protocol the select cannot hold is left at the
     select's default; the error names the one the link carried. */
  useEffect(() => {
    if (flowRefused === null) return;
    const f = flowRefused.fields;
    const protocol = (FLOW_PROTOCOLS as readonly string[]).includes(f.protocol) ? (f.protocol as Flow["protocol"]) : "tcp";
    setForm({ srcIp: f.srcIp, dstIp: f.dstIp, protocol, dstPort: f.dstPort });
    const found = errorsOf(flowRefused.problems, "link", f.protocol);
    setErrors(found);
    setErrorSource("link");
    setAnnounce(`The flow in the shared link was not run. ${Object.values(found).join(" ")}`);
  }, [flowRefused]);


  /* ══ the re-aim commit is SPLIT — acceptance E2/E3 ═══════════════════════════════════════
   *
   * THE DEFECT. Running a path trace was the one journey over the 200 ms laboratory bar:
   * measured on the release build with a hardware renderer, p95 224 ms, worst 384 ms, at or
   * over 200 ms in 9 of 12 runs, and 22 long tasks over 50 ms ON its own interaction path with
   * the worst at 350 ms. Long Animation Frames attribution put 752 ms over 19 repetitions into
   * one script: `react :: event-listener :: DIV#root.onsubmit`, worst 57 ms — eight times the
   * fabric's whole per-frame cost.
   *
   * THE TRACE IS NOT THE COST. `Trace.elapsedMs` is measured, not estimated: 0.03-0.21 ms per
   * flow. The cost is the React commit that re-aims four surfaces from one store write, and
   * a `useSyncExternalStore` update is specified urgent — React will not time-slice it, so
   * `startTransition` cannot break it up. Design brief 8.3 rule 3 is the written answer and was
   * never implemented: paint the acknowledgement frame first, then
   * `requestAnimationFrame(() => setTimeout(rest, 0))` the expensive part.
   *
   * WHAT THIS DOES. The trace is computed synchronously in the handler (sub-millisecond) and
   * shown from LOCAL state, so the interaction commits this panel alone — the verdict word, the
   * hops and the selected hop are on screen in the acknowledgement frame. The store write that
   * re-aims the queue, the device pane, the evidence rail and the fabric is handed to a later
   * task, off the interaction path.
   *
   * IT ALSO HALVES THE WORK. `setFlow` alone used to commit every surface with the NEW flow and
   * the OLD trace, and the effect below then committed them all again with the trace. Writing
   * both in one batch means the effect finds the keys already matching and does nothing: one
   * commit where there were two.
   *
   * NOT a spinner and not a delay: the panel's own content is complete in the first frame. What
   * arrives a frame later is the OTHER surfaces re-aiming, which is what cost the 200 ms. */
  /* `pending` and `runSeq` are declared with the other local state, above: the flow-restore
     effect reads `pending` too. */

  /** What THIS panel draws: the locally-committed trace until the store catches up. */
  const shown = pending?.trace ?? trace;
  /** `setTrace` parks on the first hop; the acknowledgement frame must agree with it. */
  const shownHopIndex = pending === null ? hopIndex : (pending.hop ?? (pending.trace.hops.length > 0 ? 0 : null));

  const run = useCallback(
    (next: Flow) => {
      setMode("trace");
      const traced = traceFlow(next);
      setPending({ flow: next, trace: traced });
      setRunSeq((n) => n + 1);
      const commitRest = (): void => {
        /* One batch. See above: two writes here are one commit, not two. */
        setFlow(next);
        setTrace(traced);
      };
      /* rAF puts this after the acknowledgement frame has been PAINTED; the setTimeout inside
         it puts it in a task of its own rather than inside the frame callback, where it would
         extend that same animation frame and defeat the split — `deferPastPaint` is exactly
         `requestAnimationFrame(() => setTimeout(fn, 0))`, feature-detected (a render with neither
         commits at once), and it returns a cancel. The cancel is kept so a move of the store's
         question before this lands can drop it (see the effect beside `pending`); a newer run
         supersedes an older one the same way. */
      runCommit.current?.();
      runCommit.current = deferPastPaint(() => {
        runCommit.current = null;
        commitRest();
      });
    },
    [setFlow, setTrace],
  );

  /* The local acknowledgement is released the moment the store holds the same answer. Comparing
     FLOW KEYS rather than object identity: the store is the owner, and once it agrees there is
     nothing left for the local copy to say. */
  useEffect(() => {
    if (pending === null) return;
    if (trace !== null && flowKey(trace.flow) === flowKey(pending.flow)) setPending(null);
  }, [pending, trace]);

  /* Keyed on what the panel DRAWS, so the announcement goes out with the acknowledgement frame
     rather than a task later when the other surfaces land. */
  useEffect(() => {
    if (shown === null) return;
    /* The headline word the card draws, never the raw outcome: "Result: dropped" was announced
       under a card headed "dropped for want of a collected route — not decided". */
    setAnnounce(`Result: ${outcomeWordOf(shown)}. ${shown.claim}`);
  }, [shown]);

  const onSubmit = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const { errors: found, flow: built } = validateFlowForm(form);
      setErrors(found);
      setErrorSource("form");
      if (built === null) {
        /* Focus the first field that is wrong. An error message the reader has to hunt for is an
           error message they will not read. */
        const target = found.srcIp ? srcRef.current : found.dstIp ? dstRef.current : portRef.current;
        target?.focus();
        setAnnounce(
          `The flow was not run. ${[found.srcIp, found.dstIp, found.protocol, found.dstPort].filter(Boolean).join(" ")}`,
        );
        return;
      }
      /* Through `run`, so the submit button and every preset/counterexample share ONE commit
         path. A second copy of the split here is a second thing to get wrong. */
      run(built);
    },
    [form, run],
  );

  /**
   * The ONE way this form writes a field, and the reason it is a named helper rather than four
   * inline arrow functions.
   *
   * Every `onChange` here used to read the value from inside the `setForm` updater:
   *
   *     onChange={(e) => setForm((f) => ({ ...f, dstPort: e.currentTarget.value }))}
   *
   * A functional updater does not run at the time the event fires. React may call it later — and
   * StrictMode deliberately calls it TWICE, the second time during the render pass — by which point
   * React has nulled `currentTarget` on the pooled-in-spirit synthetic event. The updater then
   * throws `Cannot read properties of null (reading 'value')` mid-render, which the error boundary
   * catches, and `#rail-path` is replaced by "The path panel stopped rendering". Measured
   * 2026-09-21 on the dev server: ONE real keystroke into Source IP, Destination IP or Destination
   * port, or one change of the Protocol select, destroyed the panel every time
   * (`review/_audit_pathtrace_repro.mjs`). Production survived only because StrictMode's
   * double-invoke is development-only — React makes no promise about WHEN an updater runs, so that
   * was luck, not safety.
   *
   * `setField` takes the value as an argument, so the read happens in the handler, synchronously,
   * while `currentTarget` is still live. The signature is the fix: there is no longer a shape of
   * this call in which an event can be captured by the updater at all.
   */
  const setField = useCallback(<K extends keyof FlowFormState>(key: K, value: FlowFormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
  }, []);

  const swap = useCallback(() => {
    setForm((f) => ({ ...f, srcIp: f.dstIp, dstIp: f.srcIp }));
  }, []);

  /**
   * A4: selecting a hop must RE-AIM the other surfaces, not merely move a marker inside this panel.
   *
   * The store's `selectHop` writes `hopIndex` and nothing else, so with device access13 selected and
   * the denied trace open, clicking "Hop 1 of 1: core1 denied" left the device pane still showing
   * access13 ("Routing: no RIB collected"), the evidence rail still on access13, and the fabric
   * selection unmoved — the hop click led nowhere. The hop is one of the four selections A4 names,
   * so it re-aims the device pane, the evidence rail and the fabric exactly as the others do.
   *
   * The host is resolved by id FIRST and then by host name rather than assuming the two are the
   * same string. They are identical for all 26 devices in this snapshot, and a lookup that silently
   * depends on that is one that breaks on the next snapshot with no failing test to say so.
   */
  const selectHopAndAim = useCallback(
    (i: number | null) => {
      selectHop(i);
      if (i === null || shown === null) return;
      const hop = shown.hops.find((h) => h.index === i);
      if (hop === undefined) return;
      const device = deviceById.get(hop.host) ?? fabric.devices.find((d) => d.host === hop.host);
      if (device === undefined) return;
      selectDevice(device.id, { surface: "path" });
      /* Then the egress cable, when the hop names a next host we actually hold a link to. This runs
         AFTER selectDevice because selectDevice clears linkId by contract. A hop with no next host,
         or one whose next hop belongs to no collected device, selects no link rather than guessing. */
      if (hop.nextHost !== null) {
        const link = (linksByHost.get(hop.host) ?? []).find(
          (l) => l.a === hop.nextHost || l.b === hop.nextHost,
        );
        selectLink(link === undefined ? null : link.id);
      }
    },
    [selectHop, selectDevice, selectLink, shown],
  );

  const counter = useMemo(() => (shown === null ? null : counterexample(shown.flow, shown)), [shown]);

  /* ══ land the reader ON the answer — acceptance A3 ═══════════════════════════════════════
   *
   * MEASURED (critic, 1920x1080): after "Trace this flow" the panel's scroller stayed at
   * scrollTop 0 with the form filling it. The verdict sat 68 px below the fold and the deciding
   * ACL line `deny ip any any` about 3,000 px below it — every fact the trace was run to produce
   * was in the DOM and none of it was on screen.
   *
   * So each NEW result scrolls its own scroller to the evidence that answers the question: the
   * blocking hop when one exists (it carries the device, the verdict, the ACL name, the line index
   * and the literal text on one card — HopList renders the decider ON the hop), otherwise the
   * claim card's verdict. Keyed on the flow, so selecting a hop, or re-rendering, never yanks
   * the reader back. Only the panel's own scroller moves: never the page, never the camera. */
  const resultRef = useRef<HTMLDivElement>(null);
  /** The runSeq the focus-landing effect last handled: tells an explicit run from a re-render. */
  const landedSeqRef = useRef(0);
  const shownKey = shown === null ? null : flowKey(shown.flow);
  const blockingIndex = useMemo(() => (shown === null ? null : (blockingHop(shown)?.hop.index ?? null)), [shown]);
  useEffect(() => {
    if (shownKey === null) return;
    const root = resultRef.current;
    if (root === null) return;
    const target =
      (blockingIndex === null
        ? null
        : root.querySelector<HTMLElement>(`.hop__head[data-hop-index="${blockingIndex}"]`)?.closest<HTMLElement>(".hop")) ??
      root.firstElementChild;
    if (!(target instanceof HTMLElement)) return;
    const explicitRun = runSeq !== landedSeqRef.current;
    landedSeqRef.current = runSeq;
    /* WHEN the landing reads layout — acceptance E5, 2026-09-22. Everything below reads geometry
       (getComputedStyle, getBoundingClientRect), which forces a synchronous style and layout of
       whatever is dirty. For an EXPLICIT run that is this panel alone, and the landing belongs in
       the interaction's own frame. For a result that ARRIVED — a cold link restore above all — the
       whole freshly-mounted page is dirty: a CPU profile of `?s=path&flow=…` put 153 ms of self
       time in this effect, inside the pre-paint task the sweep measures. So an arrived result lands
       after the next paint, when the layout the reads need has already been computed by the
       browser's own rendering step; the cancel drops it if the result changed again first. */
    const landOnAnswer = (): void => {
      if (!root.isConnected || !target.isConnected) return;
      /* The element the scroll aligned to the top of the port — and therefore the one focus must go
         to when it moves (D3, WCAG 2.4.7 / 2.4.11). MEASURED (critic, 2026-09-22, 1440×900): the
         scroll below chose the ACL deciding line because head and line did not fit together, and
         focus then went to the hop HEAD — fully above the port, so the ring was invisible. Scroll
         target and focus target are now the same element by construction, not two choices. */
      let aligned: HTMLElement | null = null;
      let scroller: HTMLElement | null = root.parentElement;
      while (scroller !== null) {
        const oy = getComputedStyle(scroller).overflowY;
        if ((oy === "auto" || oy === "scroll") && scroller.scrollHeight > scroller.clientHeight) break;
        scroller = scroller.parentElement;
      }
      if (scroller !== null) {
        /* The hop's HEAD is not the answer; the line that decided it is. MEASURED (critic, A3):
           landing the head at the top put the ACL fact carrying the literal line at y=595 against a
           scroll port ending at y=510 — the reason for the verdict was one more scroll away. So the
           landing is solved for the decided fact: the head stays at the top when head and deciding
           line fit together, and when they do not, the deciding line wins and is put at the top. */
        const box = scroller.getBoundingClientRect();
        const PAD = 8;
        const headDelta = target.getBoundingClientRect().top - box.top - PAD;
        const decided = target === root.firstElementChild ? null : target.querySelector<HTMLElement>("[data-decided]");
        let delta = headDelta;
        if (decided !== null) {
          const at = decided.getBoundingClientRect();
          if (at.bottom + PAD - headDelta > box.bottom) {
            delta = at.top - box.top - PAD;
            aligned = decided;
          }
        }
        scroller.scrollTop += delta;
      }

      /* Focus goes with the answer (D3, WCAG 2.4.7 / 2.4.3). MEASURED (critic): Enter in the
         Destination port field scrolled this panel 3,208 px to the blocking hop while focus stayed
         on the port input, now 2,841 px above the scroll port — no visible focus anywhere, and the
         next Tab ("Trace this flow") scrolled the panel straight back up, away from the hop the
         reader asked about. The rule is stated over the class, not over that one field: whenever
         the scroll leaves this panel's focused control outside its scroller's visible box, focus
         moves to the thing the scroll went to — the blocking hop's own header button (a real
         control, already in the hop list's arrow model), otherwise the verdict heading. A focused
         control the scroll left in view (a preset below the result, a hop) is not disturbed. */
      /* The second half of the class: an explicit run whose trigger UNMOUNTED under the reader.
         MEASURED (critic): Enter on a suggested-flow card replaced the card list with the result
         and focus fell to <body>. The counterexample button and "Verify an intent" (whose panel
         hides on the switch to trace mode) have the same shape. Whatever control started the run,
         if focus is gone when the answer arrives, it lands where the Trace button's does. Scoped
         to an EXPLICIT run from this panel (runSeq moved), so a trace arriving from the fabric or
         the URL while focus is elsewhere never pulls the reader into the panel. */
      const focused = document.activeElement;
      const focusLost =
        explicitRun && (!(focused instanceof HTMLElement) || focused === document.body || !focused.isConnected);
      if (!focusLost) {
        if (scroller === null || !(focused instanceof HTMLElement) || !scroller.contains(focused)) return;
        const box = scroller.getBoundingClientRect();
        const at = focused.getBoundingClientRect();
        if (at.bottom > box.top && at.top < box.bottom) return;
      }
      const land =
        aligned ??
        target.querySelector<HTMLElement>(".hop__head") ??
        root.querySelector<HTMLElement>(".claim__outcome") ??
        target;
      if (!land.matches("button,a[href],input,select,textarea,[tabindex]")) land.tabIndex = -1;
      land.focus({ preventScroll: true });
    };
    if (explicitRun) {
      landOnAnswer();
      return;
    }
    return deferPastPaint(landOnAnswer);
  }, [shownKey, blockingIndex, runSeq]);

  const errorSummary = [errors.srcIp, errors.dstIp, errors.protocol, errors.dstPort].filter(Boolean);

  return (
    <section
      id={id}
      className="pathtrace"
      aria-label="Path investigation"
      /* The panels clip horizontally (overflow-x: hidden), which still leaves them PROGRAMMATICALLY
         scrollable: a scroll-into-view or a focus landing on a wide descendant shifted the whole
         panel 42px left, with no wheel or bar to bring it back. The panel is a vertical reader, so
         any horizontal offset is a defect; undo it wherever it comes from. Scroll does not bubble,
         so this listens in the capture phase. */
      onScrollCapture={(e) => {
        const el = e.target;
        if (el instanceof HTMLElement && el.classList.contains("pt-panel") && el.scrollLeft !== 0) el.scrollLeft = 0;
      }}
    >
      <Tabs
        id={`${formId}-mode`}
        label="Path investigation mode"
        value={mode}
        onChange={setMode}
        items={[
          { id: "trace", label: "Trace a flow" },
          { id: "intent", label: "Verify an intent" },
        ]}
      />

      <TabPanel id={`${formId}-mode`} tabId="trace" active={mode === "trace"} className="pt-panel">
        <form className="pt-form" onSubmit={onSubmit} noValidate>
          <div className="pt-form__addresses">
            <Input
              ref={srcRef}
              label="Source IP"
              mono
              inputMode="decimal"
              autoComplete="off"
              spellCheck={false}
              placeholder={EXAMPLE_ADDRESSES.source}
              value={form.srcIp}
              onChange={(e) => setField("srcIp", e.currentTarget.value)}
              {...(errors.srcIp ? { error: errors.srcIp } : {})}
            />
            <IconButton
              label="Swap the source and destination addresses"
              icon={<IconSortNone />}
              className="pt-form__swap"
              onClick={swap}
            />
            <Input
              ref={dstRef}
              label="Destination IP"
              mono
              inputMode="decimal"
              autoComplete="off"
              spellCheck={false}
              placeholder={EXAMPLE_ADDRESSES.destination}
              value={form.dstIp}
              onChange={(e) => setField("dstIp", e.currentTarget.value)}
              {...(errors.dstIp ? { error: errors.dstIp } : {})}
            />
          </div>

          <div className="pt-form__service">
            <Select
              label="Protocol"
              value={form.protocol}
              onChange={(e) => setField("protocol", e.currentTarget.value as Flow["protocol"])}
              options={PROTOCOL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
            {/* Progressive disclosure: a destination port is meaningless for ICMP and for a bare
                IP question, and a field that cannot affect the answer invites one that does not. */}
            {PORTED(form.protocol) ? (
              <Input
                ref={portRef}
                label="Destination port"
                mono
                inputMode="numeric"
                autoComplete="off"
                placeholder="443"
                hint="Leave empty to ask about the protocol alone. A rule that matches on a port cannot then be decided, and the result will say so."
                value={form.dstPort}
                onChange={(e) => setField("dstPort", e.currentTarget.value)}
                {...(errors.dstPort ? { error: errors.dstPort } : {})}
              />
            ) : null}
          </div>

          {errorSummary.length > 0 ? (
            <div className="pt-form__errors" role="alert">
              <p>
                {`${errorSource === "link" ? "The flow in the shared link was not run" : "The flow was not run"}. ${errorSummary.length} field${errorSummary.length === 1 ? "" : "s"} need${errorSummary.length === 1 ? "s" : ""} attention:`}
              </p>
              <ul>
                {errorSummary.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="pt-form__actions">
            <Button type="submit" variant="primary" icon={<IconSearch />}>
              Trace this flow
            </Button>
            <span className="pt-form__scope">
              {`Forwarding is modelled on ${fabric.coverage.routableHosts.join(", ")} only — ${fabric.coverage.hostsWithRoutes} of ${fabric.devices.length} hosts have a collected routing table.`}
              <CiteLink cite={fabric.coverage.cite} onOpen={(c) => onOpenCite?.(c)} />
            </span>
          </div>
        </form>

        {shown === null ? (
          <Presets onPick={run} onOpenCite={onOpenCite} title="Questions this snapshot can answer" />
        ) : (
          <div className="pt-result" ref={resultRef}>
            <ClaimCard
              trace={shown}
              counterexample={counter}
              onRunFlow={run}
              {...(onOpenCite ? { onOpenCite } : {})}
            />
            <h3 className="pt-result__title">{`Hops (${shown.hops.length})`}</h3>
            {/* What the fabric can and cannot show for THIS trace, said where the reader reads it.
                A one-hop trace has no second device to draw a cable to, and the snapshot observes
                neither the port the source attaches to nor a host owning the next hop, so the
                fabric carries a verdict mark on one node and no path geometry. Drawing a stub
                from an inferred attachment would be inventing topology (2026-09-22 critic, A5). */}
            {shown.hops.length <= 1 ? (
              <p className="pt-result__fabric" data-fabric-drawn="marker-only">
                {shown.hops.length === 0
                  ? "On the fabric: nothing is drawn — no device was consulted for this flow."
                  : `On the fabric: ${shown.hops[0]?.host ?? "the host"} carries the verdict mark; no path is drawn. This trace consulted one device: ${shown.hops[0]?.nextHost ? `its next hop belongs to ${shown.hops[0].nextHost}, which the trace did not follow` : "no collected host owns its next hop"}, and the snapshot does not observe the port the source attaches to, so there is no second observed device to draw a cable to.`}
              </p>
            ) : null}
            <HopList
              trace={shown}
              activeIndex={shownHopIndex}
              onSelect={selectHopAndAim}
              {...(onOpenCite ? { onOpenCite } : {})}
            />
            <Presets onPick={run} onOpenCite={onOpenCite} title="Other questions this snapshot can answer" />
          </div>
        )}
      </TabPanel>

      <TabPanel id={`${formId}-mode`} tabId="intent" active={mode === "intent"} className="pt-panel">
        <IntentMode onRunFlow={run} {...(onOpenCite ? { onOpenCite } : {})} />
      </TabPanel>

      <LiveRegion message={announce} />
    </section>
  );
}

/* ══ intent mode ═══════════════════════════════════════════════════════════ */

type SearchPhase =
  | { kind: "idle" }
  | { kind: "running"; done: number; total: number }
  | { kind: "cancelled"; done: number; total: number }
  | { kind: "done"; verdict: IntentVerdict };

function IntentMode({
  onRunFlow,
  onOpenCite,
}: {
  onRunFlow: (f: Flow) => void;
  onOpenCite?: (c: Cite) => void;
}): ReactElement {
  const catalog = useMemo(() => intentCatalog(), []);
  const [selectedId, setSelectedId] = useState<string>(catalog[0]?.id ?? "");
  const [phase, setPhase] = useState<SearchPhase>({ kind: "idle" });
  const [announce, setAnnounce] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelled = useRef(false);
  /* Every search carries a generation. A chunk loop left over from a previous intent would
     otherwise finish and write ITS verdict into the panel now showing a different intent — a
     result attached to the wrong claim, which is worse than no result. */
  const generation = useRef(0);

  const intent = catalog.find((i) => i.id === selectedId) ?? catalog[0] ?? null;
  const plan = useMemo(() => (intent === null ? null : planIntent(intent)), [intent]);

  const stop = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  // A search must not outlive the panel: an orphaned chunk loop would keep tracing forever.
  useEffect(() => stop, [stop]);

  const start = useCallback(() => {
    if (intent === null) return;
    stop();
    cancelled.current = false;
    generation.current += 1;
    const mine = generation.current;
    const search = startIntentSearch(intent);
    const total = search.plan.flows.length;
    setPhase({ kind: "running", done: 0, total });
    setAnnounce(`Searching ${total} flows for a counterexample.`);

    const tick = (): void => {
      if (generation.current !== mine) return;
      if (cancelled.current) {
        setPhase({ kind: "cancelled", done: search.cursor, total });
        setAnnounce(`Search cancelled after ${search.cursor} of ${total} flows. No verdict is given.`);
        return;
      }
      stepIntentSearch(search, CHUNK);
      if (search.cursor >= total) {
        const verdict = finishIntentSearch(search);
        setPhase({ kind: "done", verdict });
        /* The announcement carries the SAME sentences as the card, unmodelled-hosts sentence
           included. It is the only non-visual form of this verdict, and dropping the mandatory
           sentence from it shipped "no counterexample found" to a screen-reader user without the
           bound that makes it honest — the visual path honoured the rule, the announced path did
           not. This file's own header calls that sentence unconditional; here it is. */
        setAnnounce(
          [verdict.outcome.replace(/-/g, " "), verdict.boundSentence, verdict.unmodelledSentence]
            .filter((s): s is string => typeof s === "string" && s.length > 0)
            .map((s) => (/[.!?]$/.test(s.trim()) ? s.trim() : `${s.trim()}.`))
            .join(" "),
        );
        return;
      }
      setPhase({ kind: "running", done: search.cursor, total });
      /* setTimeout rather than a tight loop or a microtask: it returns to the event loop, so a
         keystroke or a click lands between chunks instead of behind the whole search. */
      timer.current = setTimeout(tick, 0);
    };
    timer.current = setTimeout(tick, 0);
  }, [intent, stop]);

  const cancel = useCallback(() => {
    cancelled.current = true;
    stop();
    setPhase((p) =>
      p.kind === "running" ? { kind: "cancelled", done: p.done, total: p.total } : p,
    );
  }, [stop]);

  if (intent === null || plan === null) {
    return (
      <p className="pt-intent__none">
        This snapshot names no destination prefix in a collected ACL and no observed subnet with a
        gateway address, so no intent can be constructed from it. Offering one anyway would mean
        inventing the addresses it searches.
      </p>
    );
  }

  return (
    <div className="pt-intent">
      <p className="pt-intent__lead">
        State a universal claim, then search the flow space this snapshot can derive for a flow that
        contradicts it. A search that finds nothing is bounded by the space it searched, and that
        bound is reported with the result.
      </p>

      <Select
        label="Intent to search"
        value={selectedId}
        onChange={(e) => {
          // Retire any running search before the claim it belongs to leaves the screen.
          generation.current += 1;
          stop();
          setSelectedId(e.currentTarget.value);
          setPhase({ kind: "idle" });
        }}
        options={catalog.map((i) => ({ value: i.id, label: i.claim }))}
      />

      <div className="pt-intent__plan">
        <p className="pt-intent__claim">{intent.claim}</p>
        {/* The rationale names the ACL line or FHRP record that motivates the claim, in parentheses;
            printed as a plain string that citation was inert text (the inert-citation census,
            acceptance B6 wave 7), so it goes through the same `CitedText` every claim uses. */}
        <p className="pt-intent__why">
          <CitedText text={intent.rationale} onOpenCite={(c) => onOpenCite?.(c)} />
        </p>
        <dl className="pt-intent__facts">
          <div>
            <dt>Sources</dt>
            <dd>
              {intent.sources.map((a) => (
                <span key={a.ip} className="pt-addr" data-prov={a.provenance}>
                  <span className="pt-addr__ip">{a.ip}</span>
                  <span className="pt-addr__prov">{a.provenance}</span>
                  <CiteLink cite={a.cite} onOpen={(c) => onOpenCite?.(c)} />
                </span>
              ))}
            </dd>
          </div>
          <div>
            <dt>Destinations</dt>
            <dd>
              {intent.destinations.map((a) => (
                <span key={a.ip} className="pt-addr" data-prov={a.provenance}>
                  <span className="pt-addr__ip">{a.ip}</span>
                  <span className="pt-addr__prov">{a.provenance}</span>
                  <CiteLink cite={a.cite} onOpen={(c) => onOpenCite?.(c)} />
                </span>
              ))}
            </dd>
          </div>
          <div>
            <dt>Services</dt>
            <dd>
              {intent.services.map((s) => (
                <span key={s.label} className="pt-addr">
                  <span className="pt-addr__ip">{s.label}</span>
                  <CiteLink cite={s.cite} onOpen={(c) => onOpenCite?.(c)} />
                </span>
              ))}
            </dd>
          </div>
          <div>
            <dt>Flow space</dt>
            <dd>
              {`${plan.enumerated} flows${plan.dropped > 0 ? `, of which ${plan.dropped} exceed the ${plan.cap}-flow cap and would not be traced` : ""}. Each one is traced; the search does not stop at the first counterexample.`}
            </dd>
          </div>
        </dl>
      </div>

      <div className="pt-intent__actions">
        {phase.kind === "running" ? (
          <Button variant="secondary" onClick={cancel}>
            Cancel the search
          </Button>
        ) : (
          <Button variant="primary" icon={<IconSearch />} onClick={start}>
            Search for a counterexample
          </Button>
        )}
        {phase.kind === "running" ? (
          <span
            className="pt-progress"
            role="progressbar"
            aria-label="Counterexample search"
            aria-valuemin={0}
            aria-valuemax={phase.total}
            aria-valuenow={phase.done}
            aria-valuetext={`${phase.done} of ${phase.total} flows traced`}
          >
            <span
              className="pt-progress__fill"
              style={{ inlineSize: `${phase.total === 0 ? 0 : (phase.done / phase.total) * 100}%` }}
            />
            <span className="pt-progress__text">{`${phase.done} / ${phase.total} flows`}</span>
          </span>
        ) : null}
      </div>

      {phase.kind === "cancelled" ? (
        <p className="pt-intent__cancelled">
          {`Search cancelled after ${phase.done} of ${phase.total} flows. No verdict is offered: a partial search cannot support one, and the flows already traced are not a sample of anything in particular.`}
        </p>
      ) : null}

      {phase.kind === "done" ? (
        <IntentClaimCard
          verdict={phase.verdict}
          onRunFlow={onRunFlow}
          {...(onOpenCite ? { onOpenCite } : {})}
        />
      ) : null}

      <LiveRegion message={announce} />
    </div>
  );
}
