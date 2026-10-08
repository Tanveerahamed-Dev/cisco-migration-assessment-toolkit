/**
 * claims.ts — the claim-honesty layer. Implements design-brief.md §6.
 *
 * ── THIS FILE IS ALREADY IMPLEMENTED AND TESTED. DO NOT REWRITE IT. ──
 * The brief says "implement these as pure functions in src/core/claims.ts"; that work is done.
 * T1–T10, the badge ladder, the band mapping, the absence renderer and the reserved-word gate are
 * all below, covered by `claims.test.ts` (against real engine output) and enforced by
 * `claim-lint.test.ts`. IMPORT from here; do not re-derive. If something you need is missing, add
 * it alongside what exists rather than replacing the file — the tests pin behaviour that other
 * surfaces already depend on.
 *
 * Division of labour with the forwarding engine: `engine.ts` owns the REASONING sentence (why this
 * flow ended the way it did, naming the route or ACL line that decided it). This module owns the
 * FRAMING and the ENFORCEMENT around that sentence — the badge, the scope denominators, the
 * templated absence text, and the share payload that keeps a verdict attached to its bounds.
 *
 * The rule that makes it worth having: verdict prose is GENERATED, never authored. A renderer that
 * writes its own summary sentence can drift into a stronger claim than the evidence supports, and
 * that drift is invisible in review because the sentence reads well. So every strong word in this
 * product comes from here, and `FORBIDDEN_CLAIM_WORDS` is greppable so a build gate can prove no
 * surface emits one.
 */
import { fabric } from "./data";
import { listPhrase } from "./phrases";
import { isRouteRecord, routeFieldReading } from "./route-fields";
import type { Cite, Device, Hop, Trace, TraceOutcome } from "./types";
import { INVALID_INPUT_REFUSALS, isDefiniteDelivery, portOperatorsInText, REFUSAL_UNDECIDING_KINDS, refusalOf, unobservedPolicyInputs, type PolicyGap } from "../forwarding/engine";

/* ── §6.2 reserved-word grammar ────────────────────────────────────────────── */

/**
 * Words this product never emits about network state, at any strength, on any surface.
 *
 * They are banned rather than discouraged because each one converts a bounded observation into an
 * unbounded assurance, and the conversion is silent: "healthy" reads as a measurement when it is
 * actually the absence of one. The list is exported so a lint gate can grep the rendered string
 * table for it — honesty that depends on author discipline is not honesty, it is a hope.
 */
export const FORBIDDEN_CLAIM_WORDS: readonly string[] = [
  "proven",
  "guaranteed",
  "all traffic",
  "verified",
  "safe",
  "healthy",
  "clean",
  "no issues",
  "all clear",
  "passing",
];

/**
 * Words that assert completeness. Permitted ONLY on a SCOPED verdict — a traversal where every host
 * on the path had a collected RIB and no evidence item was indeterminate.
 */
export const STRONG_CLAIM_WORDS: readonly string[] = [
  "no counterexample was found",
  "within this scope, every",
  "bounded",
  "complete within",
];

/**
 * Negation markers. A forbidden word inside a NEGATED clause is the opposite of an overclaim — it
 * is the product stating its own limits, which is exactly the behaviour we want.
 *
 * This distinction is not academic. The forwarding engine's own caveats legitimately read "nothing
 * can be proven about forwarding on them" and "it does not show that ALL traffic does". A gate that
 * flagged those would pressure an author to remove the honest sentence in order to go green — the
 * gate would then be actively making the product less truthful. That failure mode is worse than
 * having no gate, so the gate has to be able to read the difference.
 */
const NEGATIONS = [
  "not",
  "never",
  "no",
  "none",
  "nothing",
  "cannot",
  "can't",
  "without",
  "neither",
  "nor",
  "unproven",
];

/** Clause boundaries. Negation does not carry across one: "we found no errors, the link is healthy". */
const CLAUSE_BOUNDARY = /[.;:,\n—]|\s-\s/;

/**
 * Returns the forbidden words ASSERTED in a string, so a gate can report which one it caught.
 *
 * Detection is clause-scoped: for each hit, only the text from the nearest preceding clause
 * boundary up to the word is searched for a negation. That is deliberately tighter than
 * sentence-scoped, because "we found no errors, so the link is healthy" must still be caught — the
 * negation belongs to a different clause than the claim.
 *
 * LIMIT, stated honestly: this is lexical, not semantic. It will miss an overclaim phrased without
 * any listed word, and it can be fooled by an unusual construction. It is a backstop against the
 * common case, not a proof of honesty — the templates in this module are the actual mechanism.
 */
export function forbiddenWordsIn(text: string): string[] {
  const lower = text.toLowerCase();
  const hits: string[] = [];
  for (const word of FORBIDDEN_CLAIM_WORDS) {
    /* Word boundaries, not substrings. "unproven" contains "proven", and "unproven" is a
       DISCLAIMER — flagging it would invert the gate's purpose on exactly the sentences we most
       want an author to write. The same trap waits in "unverified", "unsafe" and "uncleaned". */
    const re = new RegExp(`\\b${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "g");
    for (let m = re.exec(lower); m !== null; m = re.exec(lower)) {
      // Walk back to the start of this clause, then look for a negation inside it.
      const parts = lower.slice(0, m.index).split(CLAUSE_BOUNDARY);
      const clause = parts[parts.length - 1] ?? "";
      const negated = clause.split(/\W+/).some((t) => NEGATIONS.includes(t));
      if (!negated) {
        hits.push(word);
        break; // one report per word is enough to fail a gate
      }
    }
  }
  return hits;
}

/* ── §6.1 disposition bands ────────────────────────────────────────────────── */

export type ClaimBand = "RESOLVED" | "REFUTED" | "UNDETERMINED";

/**
 * UNDETERMINED is a third thing, not a weak failure and not a missing success. It is rendered as
 * loudly as REFUTED because "the model could not decide" is a finding about our evidence, and
 * greying it out would read as "not applicable" — which is the false-health failure in miniature.
 */
export function bandOfOutcome(outcome: TraceOutcome): ClaimBand {
  switch (outcome) {
    case "delivered":
      return "RESOLVED";
    case "dropped":
    case "denied":
      return "REFUTED";
    case "indeterminate":
    case "out-of-scope":
      return "UNDETERMINED";
  }
  /* A value this function does not recognise bands as UNDETERMINED, never as `undefined`.
     Found by the 2026-09-21 refuter (docs/refutation.md C3): both switches fell off the end and
     returned `undefined` for an unrecognised string, which a renderer draws as a blank band — a
     verdict with NO band reads as "nothing to say here", which is absence presented as a settled
     state in the one function that exists to prevent that. These values originate in compiled
     snapshot JSON, so an unanticipated verdict from a future producer is a runtime input, not a
     hypothetical.
     Exhaustiveness is NOT given up to get this: `outcome` is narrowed to `never` by the switch, so
     adding a variant to `TraceOutcome` without handling it still fails the compile on the next
     line rather than quietly banding UNDETERMINED. */
  const exhaustive: never = outcome;
  void exhaustive;
  return "UNDETERMINED";
}

export function bandOfHop(hop: Hop): ClaimBand {
  switch (hop.verdict) {
    case "forwarded":
    case "delivered":
      return "RESOLVED";
    case "no-route":
    case "denied":
    case "loop":
    case "ttl-exceeded":
      return "REFUTED";
    case "unmodeled":
      return "UNDETERMINED";
  }
  // Same rule, same reason, same preserved exhaustiveness — see `bandOfOutcome`.
  const exhaustive: never = hop.verdict;
  void exhaustive;
  return "UNDETERMINED";
}

/**
 * Is this trace's outcome DECIDED — does nothing it rests on remain open?
 *
 * The outcome word alone cannot answer that: the engine returns "delivered" over a host whose ACLs
 * were never collected, and "denied" by a list whose interface binding was never observed. Both
 * are what the ROUTING and the ACL TEXT say; neither is a decided filtering result. This is the one
 * owner of that rule — the intent search's decided/undecided tally, the verdict band, the hop band
 * and the counterexample offer all ask it, so a surface cannot draw as settled what the tally
 * counts as undecided.
 */
/** The gap kinds that leave a refusal (denied / dropped) undecided. See `isDecidedOutcome`. */
/* Owned by the engine, which also names these gaps in the claim sentence itself: one set, so the
   sentence and the band cannot disagree about which refusals are decided. */
export const REFUSAL_UNDECIDING: ReadonlySet<PolicyGap["kind"]> = REFUSAL_UNDECIDING_KINDS;

/**
 * The gaps that make THIS trace's outcome undecided — the ones `isDecidedOutcome` counts. Empty when
 * the outcome is decided. A surface explaining "why is this not decided" names these, never merely
 * the first gap on the trace (which may be one that does not bear on the outcome at all).
 */
export function outcomeUndecidingGaps(trace: Trace): PolicyGap[] {
  if (isDecidedOutcome(trace)) return [];
  const gaps = unobservedPolicyInputs(trace);
  return trace.outcome === "delivered" ? gaps : gaps.filter((g) => REFUSAL_UNDECIDING.has(g.kind));
}

/**
 * Do the HOPS support the trace's outcome word? One rule, read through `bandOfHop` so the hop layer
 * and the trace layer cannot disagree about the same path: no hop may band UNDETERMINED, the last
 * hop must band exactly as the outcome does, and a `delivered` outcome needs EVERY hop to band
 * RESOLVED — a pass is only as strong as the weakest hop it crossed. A `denied`/`dropped` outcome
 * needs a terminal hop that bands REFUTED; a refused hop earlier on the path does not weaken a
 * refusal, so it is not counted against one. Undecided outcome words (indeterminate / out-of-scope)
 * claim nothing, so there is nothing for the hops to contradict.
 *
 * Found by the 2026-09-21 refuter (docs/refutation.md C2): `claimBadge` read only the outcome word,
 * so a `delivered` trace whose only hop was a `loop` earned SCOPED while `bandOfHop` on that hop said
 * REFUTED — two parts of this module disagreeing about one trace, and the badge taking the more
 * flattering side. This is deliberately NOT "every hop must be RESOLVED": a denial ends on a REFUTED
 * hop, and a denied flow is a confidently answered question.
 */
export function hopsSupportOutcome(trace: Trace): boolean {
  const claimed = bandOfOutcome(trace.outcome);
  if (claimed === "UNDETERMINED") return true;
  const last = trace.hops[trace.hops.length - 1];
  if (last === undefined) return false;
  const bands = trace.hops.map(bandOfHop);
  if (bands.includes("UNDETERMINED")) return false;
  if (claimed === "RESOLVED" && bands.some((b) => b !== "RESOLVED")) return false;
  return bandOfHop(last) === claimed;
}

export function isDecidedOutcome(trace: Trace): boolean {
  // An outcome its own hops contradict is not decided, whatever the policy inputs say (C2).
  if (!hopsSupportOutcome(trace)) return false;
  switch (trace.outcome) {
    case "delivered":
      return isDefiniteDelivery(trace);
    case "denied":
    case "dropped":
      /* A denial by a list whose binding was never observed, a drop for want of a route in a table
         the snapshot shows to be incomplete, or either one reached by an ingress choice an alternate
         FHRP member does not reproduce, is not a decided refusal. One rule for both refusals: a drop
         used to be decided unconditionally, so the SAME ingress-alternate gap that undecided a
         denial left a drop decided, and 60 no-route drops over core2's partial table were counted
         as a clean "no counterexample" (2026-09-21 critic, B1 blocker). (A physical ingress port
         whose filtering is unobserved, or an uncollected ACL, can only refuse EARLIER — neither can
         turn a refusal into a pass — so neither undecides the refusal, only the badge.) */
      return !unobservedPolicyInputs(trace).some((g) => REFUSAL_UNDECIDING.has(g.kind));
    case "indeterminate":
    case "out-of-scope":
      return false;
  }
  return false;
}

/**
 * The band of a whole TRACE — the outcome's band, capped at UNDETERMINED when the outcome is not
 * decided (`isDecidedOutcome`). Found by the 2026-09-21 critic (B1): a card badged INDETERMINATE
 * ("the model could not decide this flow") still drew a green check reading "delivered", because
 * its colour came from the outcome word. Render surfaces use this; `bandOfOutcome` stays the
 * word-level mapping.
 */
export function bandOfTrace(trace: Trace): ClaimBand {
  const b = bandOfOutcome(trace.outcome);
  return b !== "UNDETERMINED" && !isDecidedOutcome(trace) ? "UNDETERMINED" : b;
}

/**
 * Why an outcome the engine returned was NOT decided (`isDecidedOutcome` false), as short phrases
 * built from the actual undecided inputs — never from the outcome word alone. A fixed
 * "denied by list text — binding not observed" headline was drawn over a denial whose binding WAS
 * observed and which was undecided only by its FHRP-alternate ingress (2026-09-21 critic, A3).
 * Exhaustive over the gap kinds, so a new kind cannot borrow another's wording. Empty when the
 * outcome is decided or is itself an undecided word (indeterminate / out-of-scope).
 */
export function outcomeUndecidedCauses(trace: Trace): string[] {
  if (trace.outcome !== "delivered" && trace.outcome !== "denied" && trace.outcome !== "dropped") return [];
  if (isDecidedOutcome(trace)) return [];
  // Only the gap kinds `isDecidedOutcome` counts can undecide a refusal (see its comment).
  const gaps = outcomeUndecidingGaps(trace);
  const out: string[] = [];
  const add = (p: string): void => {
    if (!out.includes(p)) out.push(p);
  };
  for (const g of gaps) {
    switch (g.kind) {
      case "acl-uncollected":
        add(`no ACLs collected at ${g.host}`);
        break;
      case "acl-unbound-denial":
        add(`binding not observed at ${g.host}`);
        break;
      case "ingress-alternate":
        add(`ingress via ${g.host} not modelled equivalently`);
        break;
      case "ingress-port-unobserved":
        add(`ingress port filtering at ${g.host} unobserved`);
        break;
      case "rib-partial":
        add(`${g.host}'s routing table incomplete`);
        break;
      default: {
        const exhaustive: never = g.kind;
        add(String(exhaustive));
      }
    }
  }
  if (trace.outcome === "delivered") {
    if (trace.hops.some((h) => h.verdict === "unmodeled")) add("a hop not modelled");
    if (trace.hops.some((h) => h.evidence.some((e) => e.kind === "absence"))) add("an input recorded as absent");
  }
  return out;
}

/**
 * The headline word for an outcome the engine returned but did not decide: what the routing or the
 * list text said and — from `outcomeUndecidedCauses` — WHY it is not a decided result. Null when the
 * outcome is decided or is itself an undecided word.
 */
export function undecidedOutcomeWord(trace: Trace): string | null {
  const lead =
    trace.outcome === "delivered"
      ? "delivered by routing"
      : trace.outcome === "denied"
        ? "denied by list text"
        : trace.outcome === "dropped"
          ? "dropped for want of a collected route"
          : null;
  if (lead === null || isDecidedOutcome(trace)) return null;
  const causes = outcomeUndecidedCauses(trace);
  return causes.length === 0 ? `${lead} — not decided` : `${lead} — not decided: ${causes.join("; ")}`;
}

/** Why a hop that its verdict word alone would band RESOLVED or REFUTED is not decided. */
export type HopUndecided =
  | "filtering-unobserved"
  | "ingress-unobserved"
  | "input-unobserved"
  | "binding-unobserved"
  /** A route decision — no-route, a pass, or an outbound denial reached by the route — at a host whose collected table the snapshot shows to be incomplete (`rib-partial`). */
  | "route-table-partial"
  /** The hop that ended an undecided refusal — reached only under an ingress the alternate does not reproduce. */
  | "refusal-undecided";

/**
 * The policy gaps that qualify THIS hop, for its reason line. `acl-uncollected` means the host has
 * no collected ACLs at all; `ingress-port-unobserved` means the host HAS collected ACLs but the
 * physical port the source's frames arrive by was not observed. They are different facts and must
 * never share wording — core1 (ACLs collected) was described as "no ACLs were collected" while the
 * same card cited its PROTECT_SERVERS line (2026-09-21 critic, A2). Ingress-alternate gaps are keyed
 * on the ALTERNATE host, so they are attached to the first hop, whose ingress they qualify.
 */
export function hopUndecidedGaps(hop: Hop, trace: Trace): PolicyGap[] {
  const isFirst = trace.hops[0] === hop;
  return unobservedPolicyInputs(trace).filter((g) => g.host === hop.host || (isFirst && g.kind === "ingress-alternate"));
}

export function hopUndecided(hop: Hop, trace: Trace): HopUndecided | null {
  const base = bandOfHop(hop);
  if (base === "UNDETERMINED") return null;
  const gaps = unobservedPolicyInputs(trace).filter((g) => g.host === hop.host);
  if (base === "REFUTED") {
    if (hop.verdict === "denied" && gaps.some((g) => g.kind === "acl-unbound-denial")) return "binding-unobserved";
    if ((hop.verdict === "no-route" || hop.verdict === "denied") && gaps.some((g) => g.kind === "rib-partial")) return "route-table-partial";
    /* The hop that ENDED a refusal the trace does not decide (`isDecidedOutcome`) must not wear a
       decided refusal mark while the card over it says "not decided" — the same trace, two answers
       (2026-09-21 critic, B1: the fabric drew "✕ BLOCKED" beside an UNDETERMINED card). */
    const terminal = trace.hops[trace.hops.length - 1] === hop;
    if (terminal && (trace.outcome === "denied" || trace.outcome === "dropped") && !isDecidedOutcome(trace)) return "refusal-undecided";
    return null;
  }
  /* A pass (forward or delivery) whose route was chosen from a table the snapshot shows incomplete —
     including a connected subnet a longer, uncollected route could outrank — is not a resolved pass. */
  if (gaps.some((g) => g.kind === "rib-partial")) return "route-table-partial";
  if (gaps.some((g) => g.kind === "acl-uncollected")) return "filtering-unobserved";
  if (gaps.some((g) => g.kind === "ingress-port-unobserved")) return "ingress-unobserved";
  if (hop.evidence.some((e) => e.kind === "absence")) return "input-unobserved";
  return null;
}

/**
 * The band of one hop IN its trace. A hop that passed or delivered at a host whose filtering was
 * never observed, or that carries an evidence item recorded as an absence, is not a resolved pass;
 * a denial by a list whose binding was never observed is not a decided refusal. Both band
 * UNDETERMINED — derived from the same inputs `isDefiniteDelivery`/`unobservedPolicyInputs` read.
 */
export function bandOfHopIn(hop: Hop, trace: Trace): ClaimBand {
  return hopUndecided(hop, trace) === null ? bandOfHop(hop) : "UNDETERMINED";
}

/* ── §6.4 claim-strength badge ─────────────────────────────────────────────── */

/* "PARTIAL" was spelled "OBSERVED" until 2026-09-22 (critic, B2). Every verdict here is simulated
   control-plane analysis; the card's own closing caveat says "not observed traffic", so the badge
   at its head may not use the word that caveat denies. The colour token keeps its old name. */
export type ClaimBadge = "SCOPED" | "PARTIAL" | "INDETERMINATE" | "OUT OF SCOPE" | "INVALID INPUT";

/**
 * A malformed question ("10.0.10.3/24" as an address) is not a statement about how far the
 * collection reaches, so it may not wear OUT OF SCOPE (2026-09-22 critic, B4). The trace outcome
 * enum is a frozen contract, so the distinction is read from the engine's own refusal record
 * (`refusalOf`), never from the claim prose.
 */
export const isInvalidInput = (trace: Trace): boolean => {
  const kind = refusalOf(trace)?.kind;
  /* Read through the engine's own set, not a restated kind: a malformed port or protocol (added
     2026-09-23, B1) is as much "not a valid question" as a malformed address. */
  return kind !== undefined && INVALID_INPUT_REFUSALS.has(kind);
};

export interface ScopeTuple {
  hops: number;
  /** Hosts on THIS path whose RIB we hold. */
  modelledOnPath: number;
  /** Hops on THIS path taken at a host whose RIB we hold (a host visited twice counts twice). */
  ribHops: number;
  /** Hosts on this path with no collected RIB. Any value above zero forecloses a SCOPED badge. */
  unmodelledOnPath: number;
  /** Evidence items the engine could not decide (chiefly unevaluable ACL lines). */
  indeterminateEvidence: number;
  /**
   * Filtering questions this trace left open for want of evidence — a host passed with no collected ACL,
   * or a denial by a list whose interface binding was never collected. Any value above zero
   * forecloses SCOPED. See `unobservedPolicyInputs` in the engine.
   */
  policyGaps: PolicyGap[];
  /** Fleet-wide denominators, read from the compiled coverage — never hardcoded. */
  hostsWithRibs: number;
  hostsTotal: number;
  routableHosts: string[];
  sha8: string;
  collectedAt: string | null;
}

export function scopeTuple(trace: Trace): ScopeTuple {
  const unmodelled = new Set(trace.unmodelledHosts);
  const onPath = new Set(trace.hops.map((h) => h.host));
  let indeterminate = 0;
  for (const h of trace.hops) {
    if (h.verdict === "unmodeled") indeterminate++;
    // An evidence item explicitly recorded as an absence is an undecided input, not a neutral one.
    for (const e of h.evidence) if (e.kind === "absence") indeterminate++;
  }
  return {
    hops: trace.hops.length,
    modelledOnPath: [...onPath].filter((h) => !unmodelled.has(h)).length,
    ribHops: trace.hops.filter((h) => fabric.coverage.routableHosts.includes(h.host)).length,
    unmodelledOnPath: unmodelled.size,
    indeterminateEvidence: indeterminate,
    policyGaps: unobservedPolicyInputs(trace),
    hostsWithRibs: fabric.coverage.hostsWithRoutes,
    hostsTotal: fabric.devices.length,
    routableHosts: fabric.coverage.routableHosts,
    sha8: fabric.meta.sourceSha256.slice(0, 8),
    collectedAt: fabric.meta.collectedAt,
  };
}

/**
 * SCOPED is the strongest badge that exists in this product. There is deliberately no badge above
 * it: RIBs are collected for only some hosts (fabric.coverage.hostsWithRoutes of fabric.devices.length on
 * whatever snapshot is loaded), so there is no exhaustive search to be had, and no result here can
 * earn the word "proven" no matter how clean the traversal was.
 */
export function claimBadge(trace: Trace): ClaimBadge {
  if (isInvalidInput(trace)) return "INVALID INPUT";
  if (trace.outcome === "out-of-scope") return "OUT OF SCOPE";
  /* The badge may not claim more than the outcome WORD does. A word that bands UNDETERMINED claims
     nothing — `indeterminate`, and any value this module does not recognise (C3: a runtime string
     from compiled JSON). This used to test `outcome === "indeterminate"` only, so an unrecognised
     word over a clean, fully-modelled traversal fell through to the traversal checks and earned
     SCOPED while `bandOfTrace` beside it said UNDETERMINED (2026-09-22 probe, claims.test.ts): the
     C2 disagreement reached through the C3 door. Read through `bandOfOutcome`, the one owner of the
     word-level mapping, so a word it cannot band can never out-rank its own band here. */
  if (bandOfOutcome(trace.outcome) === "UNDETERMINED") return "INDETERMINATE";
  const s = scopeTuple(trace);
  if (s.unmodelledOnPath > 0 || s.indeterminateEvidence > 0) return "INDETERMINATE";
  /* A traversal that visited NOTHING decided nothing, and must not be able to earn the strongest
     badge in the product by being empty.
     Found by the 2026-09-21 refuter (docs/refutation.md C1). Every test in this function was a
     test for a DISQUALIFIER — no unmodelled host, no indeterminate evidence, every host modelled —
     and `[].every(…)` is `true`, so a `delivered` trace with zero hops satisfied all of them and
     returned SCOPED. The badge was computed from what was ABSENT rather than from what was
     PRESENT, which is the product's own named failure shape occurring in the function that decides
     its strongest claim. The repair is to require positive evidence: at least one hop actually
     traversed.
     WHERE THAT RULE LIVES NOW (2026-09-22). It used to be a line here, `if (trace.hops.length === 0)
     return "INDETERMINATE"`, and that line was unpinned (acceptance F2): for a decided word
     (delivered / denied / dropped) `hopsSupportOutcome` refuses a zero-hop trace too (`last ===
     undefined`), so the line only ever decided an UNRECOGNISED word. The outcome-band rule above
     now withholds every badge from such a word, hops or none — so the line decided nothing on any
     input (measured: deleted, all claims tests stay green) and was removed rather than kept as a
     guard no test can reach. The rule has exactly two owners, each load-bearing and each pinned in
     claims.test.ts: the outcome-band rule above (every UNDETERMINED word), and `hopsSupportOutcome`
     just below (every decided word; `review/mutation-check.mjs` claims-c1-decided-owner and
     claims-c1-both-owners). */
  /* The outcome word may not claim more than the hops say (docs/refutation.md C2): a `delivered`
     trace whose path ends in a loop, or a refusal whose terminal hop passed, is a trace that
     contradicts itself, and a self-contradicting answer is not a scoped one. Read through
     `bandOfHop` via `hopsSupportOutcome` — the same owner `isDecidedOutcome` uses for the band. */
  if (!hopsSupportOutcome(trace)) return "INDETERMINATE";
  // A complete traversal still only earns SCOPED when every host it touched was one we modelled.
  const allOnPathModelled = trace.hops.every((h) => s.routableHosts.includes(h.host));
  /* A filter question the collection never asked — a host passed with no collected ACL, or a denial
     by a list whose binding was never collected — is evidence that does not cover the path. It used
     to be invisible here, so a delivery at a host with no ACLs earned "every evidence item was
     decided". PARTIAL is the honest ceiling: the traversal completed; the filtering is unobserved. */
  if (s.policyGaps.length > 0) return "PARTIAL";
  return allOnPathModelled ? "SCOPED" : "PARTIAL";
}

/** The CSS custom property that carries this badge's colour. Kept here so badge and token cannot drift. */
export const badgeToken = (b: ClaimBadge): string =>
  b === "SCOPED"
    ? "var(--claim-scoped)"
    : b === "PARTIAL"
      ? "var(--claim-observed)"
      : b === "INDETERMINATE"
        ? "var(--claim-indeterminate)"
        : "var(--claim-out-of-scope)";

/* ── §6.3 literal templates ────────────────────────────────────────────────── */

const day = (iso: string | null): string => (iso === null ? "an unrecorded time" : iso.slice(0, 10));
const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

const flowLabel = (t: Trace): string => {
  const f = t.flow;
  const port = f.protocol === "tcp" || f.protocol === "udp" ? `:${f.dstPort ?? "any"}` : "";
  return `${f.protocol} ${f.srcIp} -> ${f.dstIp}${port}`;
};

/** The short form of a policy gap for T1. Exhaustive over the kinds, so a new kind cannot borrow another's wording. */
function gapPhrase(g: PolicyGap): string {
  switch (g.kind) {
    case "acl-uncollected":
      return `no ACLs collected for ${g.host}`;
    case "acl-unbound-denial":
      return `no access-group binding for the denying list at ${g.host}`;
    case "ingress-alternate":
      return `the flow may enter via ${g.host}, which was not modelled equivalently`;
    case "ingress-port-unobserved":
      return `the physical port the source reaches ${g.host} by has unobserved filtering`;
    case "rib-partial":
      return `the routing table at ${g.host} is shown incomplete by the snapshot, so its route decision for this flow is not decided`;
  }
  const exhaustive: never = g.kind;
  return exhaustive;
}

/** T1 — the scoped verdict header. Emitted for every trace, always. */
export function T1_verdict(trace: Trace): string {
  const s = scopeTuple(trace);
  /* A search that never ran has no counts. "0 hosts on this path could not be modelled; 0 evidence
     items were indeterminate" for an out-of-scope flow rendered an absence as a clean measurement —
     there was no path, so nothing on it was modelled OR unmodelled. The fleet denominator still
     travels with the sentence, because it is what makes the refusal legible. */
  if (isInvalidInput(trace)) {
    return (
      `${claimBadge(trace)}: ${flowLabel(trace)} is not a valid flow, so nothing was simulated and no statement about the network is made; ` +
      `${s.hostsWithRibs} of ${s.hostsTotal} hosts have a collected RIB. Snapshot ${s.sha8}, collected ${day(s.collectedAt)}.`
    );
  }
  if (trace.outcome === "out-of-scope" || trace.hops.length === 0) {
    return (
      `${claimBadge(trace)}: ${flowLabel(trace)} is ${trace.outcome} — no path was evaluated, so no hop, ` +
      `unmodelled host or indeterminate evidence count applies; ${s.hostsWithRibs} of ${s.hostsTotal} hosts ` +
      `have a collected RIB. Snapshot ${s.sha8}, collected ${day(s.collectedAt)}.`
    );
  }
  const filtering = s.policyGaps.filter((g) => g.kind !== "rib-partial");
  const routing = s.policyGaps.filter((g) => g.kind === "rib-partial");
  return (
    /* The hop count and the fleet denominator are separate clauses: "traversed 1 hop across 2 of 26
       hosts with a collected RIB" read as if the one hop was on a RIB host when it was dist1, which
       has none (2026-09-22 auditor, B2). */
    `${claimBadge(trace)}: ${flowLabel(trace)} is ${trace.outcome} — traversed ${plural(s.hops, "hop")}, ` +
    `${s.ribHops} of them on a host with a collected RIB (${s.hostsWithRibs} of ${s.hostsTotal} hosts in this topology have one); ` +
    `${plural(s.unmodelledOnPath, "host")} on this path could not be modelled; ` +
    `${plural(s.indeterminateEvidence, "evidence item")} ${s.indeterminateEvidence === 1 ? "was" : "were"} indeterminate; ` +
    (filtering.length === 0
      ? "no filtering question on this path was left unobserved. "
      : `${plural(filtering.length, "filtering question")} ${filtering.length === 1 ? "was" : "were"} left open for want of collected evidence (${filtering
          .map(gapPhrase)
          .join("; ")}). `) +
    /* A routing gap is not a filtering question and is not counted as one: it is named on its own. */
    (routing.length === 0 ? "" : `The ${trace.outcome === "dropped" ? "drop" : "route decision"} rests on an incomplete routing table (${routing.map(gapPhrase).join("; ")}). `) +
    `Snapshot ${s.sha8}, collected ${day(s.collectedAt)}.`
  );
}

/** T2 — the blocking-hop sentence. The answer to "what stopped it". */
export function T2_blockingHop(hop: Hop): string | null {
  const e = hop.decidedBy;
  if (e === null || e.kind !== "acl") return null;
  return (
    `Blocked at ${hop.host}, ACL ${e.label}: ${e.raw ?? "(line text not recorded)"}. ` +
    `Cited at ${e.cite}. This names the first rule that matched; ` +
    `${plural(hop.alternatives.length, "route")} considered and beaten at this hop.`
  );
}

/** T3 — source address outside every observed subnet (acceptance B4). */
export function T3_outOfScope(srcIp: string, observedSubnets: readonly string[]): string {
  return (
    `OUT OF SCOPE: ${srcIp} is not inside any subnet observed in this snapshot, so no ingress point ` +
    `can be determined. This is not a statement that the flow fails; it is a statement that we ` +
    `cannot evaluate it. Observed subnets: ${listPhrase(observedSubnets, "none recorded")}.`
  );
}

/** T4 — traversal reached a host with no RIB (acceptance B3). */
export function T4_unmodelledHost(host: string): string {
  const c = fabric.coverage;
  return (
    `INDETERMINATE: forwarding could not be modelled at ${host} because no routing table was ` +
    `collected for it (${c.hostsWithRoutes} of ${fabric.devices.length} hosts have one: ` +
    `${listPhrase(c.routableHosts, "none")}). The result above stops here. It is NOT a delivery and NOT a drop.`
  );
}

/** T5 — ACL evaluation blocked by an unevaluable line (acceptance B5). */
export function T5_unevaluableAcl(
  aclName: string,
  host: string,
  lineIndex: number,
  rawLineText: string,
  reason: string,
  cite: Cite,
): string {
  return (
    `INDETERMINATE: ACL ${aclName} on ${host} could not be evaluated past line ${lineIndex} ` +
    `(${rawLineText}) — ${reason}. Lines after ${lineIndex} were not reached by this evaluation. ` +
    `Cited at ${cite}.`
  );
}

/** T6 — the intended-effect / collateral-damage pair, kept as two independent statements. */
export function T6_counterfactual(
  flowText: string,
  outcomeWithAcls: string,
  outcomeWithoutAcls: string,
  ignoredRules: readonly string[],
): string {
  const n = ignoredRules.length;
  return (
    `INTENDED       — with ACLs enforced: ${flowText} is ${outcomeWithAcls}.\n` +
    `COUNTERFACTUAL — with every ACL treated as permit: ${flowText} is ${outcomeWithoutAcls}.\n` +
    `${plural(n, "rule")} would have acted and ${n === 1 ? "is" : "are"} shown struck through, not removed: ` +
    `${n ? ignoredRules.join("; ") : "none"}.` +
    (n > 0 ? ` Clearing the ACL path requires addressing all ${n}.` : "")
  );
}

/* ── T7 — the absence renderer. The single most-used string in the product. ── */

export const NOT_OBSERVED_TEXT = "not observed";

export const NOT_OBSERVED_DESCRIPTION =
  "Not present in the snapshot. This is not a measurement of zero, and not a statement of health.";

export interface Absence {
  text: string;
  description: string;
  /** True when the engine supplied its own reason, which is always better than the generic text. */
  hasReason: boolean;
}

/**
 * The one place a `null` becomes words. Where the compiler preserved the engine's own prose — e.g.
 * `L3Interface.trackingUnobserved` = "[NOT OBSERVED] - no 'show track' evidence; object tracking
 * NOT assessed" — that reason is rendered verbatim, because a stated reason is strictly more useful
 * than a generic placeholder and it is already evidence-grounded.
 */
export function absence(reason?: string | null): Absence {
  const raw = typeof reason === "string" ? reason.trim() : "";
  // The engine writes a bare "[NOT OBSERVED]" when it has no reason to give, and
  // "[NOT OBSERVED] - <why>" when it does. Strip the marker and keep only what is left.
  const detail = raw.replace(/^\[NOT OBSERVED\]\s*[-–—:]?\s*/i, "").trim();
  if (detail.length === 0) {
    // A bare marker carries no more information than the generic text, and appending an empty
    // reason would render "not observed — " with a dangling dash: worse than saying nothing.
    return { text: NOT_OBSERVED_TEXT, description: NOT_OBSERVED_DESCRIPTION, hasReason: false };
  }
  return { text: `${NOT_OBSERVED_TEXT} — ${detail}`, description: NOT_OBSERVED_DESCRIPTION, hasReason: true };
}

/* ── a route record's fields: owned by `route-fields.ts`, re-exported here ───────
   How a route record's `adminDistance` and `nextHop` read (and how a null distance RANKS) is decided
   in ONE place, `core/route-fields.ts`, which every surface renders through
   `HopList.tsx :: RouteFieldValue`. It lives in its own leaf module, not here, so the forwarding
   engine can consult the same owner without importing this module back (this module imports the
   engine). DECISION CHANGED 2026-09-23 (acceptance B1): a connected or local route's null
   administrative distance reads "not recorded", with the zero-by-platform-convention given as the
   reason, never as the value — superseding the 2026-09-22 auditor decision ("0 — … by definition").
   The decision record is in route-fields.ts. */
export { adminDistanceRank, isRouteRecord, routeFieldReading, type RouteField, type RouteFieldReading } from "./route-fields";

/**
 * A `null` that is STRUCTURAL rather than missing: the record's own shape says the field cannot
 * carry a value, so rendering it "not observed" would claim an evidence gap that does not exist —
 * and a marker that fires where nothing is missing teaches a reader to skim past the marker where
 * something is. Found by the 2026-09-21 critic (B1): `deny ip any any` rendered "sport: not
 * observed", and a connected route rendered "nextHop: not observed".
 *
 * Returns the not-applicable wording, or null when the null is (or may be) a real absence. Decided
 * from the record's OWN fields — its route source, its protocol and literal line text — never from
 * a list of record ids. When the line text is not recorded, or it carries a token the null could
 * have come from (a port operator, an ICMP qualifier, a time-range), the answer is null: an
 * absence we cannot rule out stays "not observed".
 */
export function notApplicableReason(record: unknown, field: string): string | null {
  if (typeof record !== "object" || record === null) return null;
  const r = record as Record<string, unknown>;
  // A routing-table entry: its route fields are read by the ONE owner below, never decided here twice.
  if ((field === "nextHop" || field === "adminDistance") && isRouteRecord(record)) {
    const reading = routeFieldReading(record, field);
    return reading.kind === "not-applicable" ? reading.text : null;
  }
  /* An interface ACL-binding record (forwarding/acl-bindings.json): a null direction on a port whose
     running configuration WAS observed, with no unprojected candidate for that direction, is an
     observed "no list bound" — the same reading `bindings.ts :: bindingAt` gives it — not an absence. */
  if ((field === "aclIn" || field === "aclOut") && r[field] === null && "gateUnmodeled" in r) {
    const dir = field === "aclIn" ? "in" : "out";
    const unprojected =
      Array.isArray(r.gateUnmodeled) &&
      r.gateUnmodeled.includes("candidate_projection_incomplete") &&
      Array.isArray(r.gateCandidates) &&
      r.gateCandidates.includes(`interface_acl_${dir}`);
    if (r.runConfigObserved === true && !unprojected) return `none — the running configuration was observed and binds no list ${dir === "in" ? "inbound" : "outbound"}`;
    return null;
  }
  // An ACL line: only when the line text is recorded and the producer modelled it.
  if (typeof r.raw !== "string" || typeof r.action !== "string" || !("proto" in r) || r.unevaluable === true) return null;
  const raw = r.raw.toLowerCase();
  const proto = typeof r.proto === "string" ? r.proto.toLowerCase() : null;
  if (proto === null) return null;
  if ((field === "sport" || field === "dport") && r[field] === null) {
    if (proto !== "tcp" && proto !== "udp") return `n/a — ${/^[aeiou]/.test(proto) ? "an" : "a"} ${proto} line matches no ports`;
    /* Read the operator's POSITION, not its presence anywhere on the line: `eq 443` after the
       destination constrains the destination port only, so it says nothing about a null SOURCE port
       (2026-09-22 auditor, B1). A line whose text cannot be read that far stays an absence. */
    const cite = typeof r.cite === "string" ? r.cite : "";
    const ops = portOperatorsInText(raw, /^acls\.([^.]+)\./.exec(cite)?.[1] ?? null);
    if (ops === null || ops[field]) return null; // an operator IS in this position; the null may be a parse gap
    return `any — this line places no ${field === "sport" ? "source" : "destination"}-port constraint`;
  }
  if (field === "icmpType" && r.icmpType === null) {
    if (proto !== "icmp") return `n/a — not an ICMP line`;
    return null; // an ICMP line: a qualifier may have been dropped, so this stays an absence
  }
  if (field === "timeRange" && r.timeRange === null) {
    return /\btime-range\b/.test(raw) ? null : "none — this line names no time-range";
  }
  return null;
}

/**
 * The DATA-LAYER absence guard. Returns the value when it is genuinely present, and the `Absence`
 * record otherwise.
 *
 * Deliberately NOT named `orNotObserved`: that name belongs to the RENDERER in
 * `src/ui/primitives.tsx`, which returns a React element and is what every surface calls. Two
 * exports with the same name and different return types, imported by six agents building in
 * parallel, is a mistake waiting to be made — so the layers are named apart:
 *
 *   src/core/claims.ts     resolveAbsence(value)            -> T | Absence   (logic, testable, no React)
 *   src/ui/primitives.tsx  orNotObserved(value, render, …)  -> ReactNode     (what surfaces render)
 *
 * Both agree on the semantics that matter: `0` and `false` are VALUES, not absences. A port with 0
 * CRC errors was measured, and collapsing that into "not observed" would be the mirror image of
 * rendering absence as health.
 */
export function resolveAbsence<T>(v: T | null | undefined, reason?: string | null): T | Absence {
  return v === null || v === undefined ? absence(reason) : v;
}

export const isAbsence = (v: unknown): v is Absence =>
  typeof v === "object" && v !== null && "text" in v && "description" in v && "hasReason" in v;

/** T8 — the permanent coverage denominator for the status bar (acceptance B7). */
export function T8_coverageLine(): string {
  const c = fabric.coverage;
  const total = fabric.devices.length;
  const inventoryRecords = fabric.devices.filter((d) => d.inventoried).length;
  return (
    `${inventoryRecords}/${total} inventory records · RIBs ${c.hostsWithRoutes}/${total} · ` +
    `ACLs ${c.hostsWithAcls}/${total} · link centrality ${c.linksWithCentrality}/${fabric.links.length} · ` +
    `snapshot ${fabric.meta.sourceSha256.slice(0, 8)} ${day(fabric.meta.collectedAt)}`
  );
}

/** T9 — our analysis and the snapshot's own analysis disagree (acceptance A6). */
export function T9_disagreement(
  element: string,
  ourValue: string | number,
  field: string,
  theirValue: string | number,
  cite: Cite,
): string {
  return (
    `DISAGREEMENT: our computed blast radius for ${element} (${ourValue}) differs from the ` +
    `snapshot's own ${field} (${theirValue}). Both are shown. Neither is suppressed. Cited at ${cite}.`
  );
}

/** T10 — the sample-path disclaimer, permanently inline on every single-flow result. */
export const T10_SAMPLE_PATH =
  "This is one flow. It shows that SOME traffic behaves this way. It does not show that ALL traffic " +
  "does, and this result cannot close a claim about the flow class.";

/* ── the share payload ─────────────────────────────────────────────────────── */

/**
 * Copy and Share always emit claim + scope + badge as ONE block.
 *
 * A verdict pasted into a ticket without its bounds is how an honest result becomes a dishonest
 * quotation — and it is the most likely way a claim from this tool ends up overstated in front of
 * someone who never saw the coverage numbers. So the bounds travel with the sentence, always.
 */
export function sharePayload(trace: Trace): string {
  const s = scopeTuple(trace);
  const lines = [
    T1_verdict(trace),
    "",
    trace.claim,
    "",
    `SCOPE: RIBs collected for ${listPhrase(s.routableHosts)} (${s.hostsWithRibs} of ${s.hostsTotal} hosts). ` +
      `ACLs collected for ${listPhrase(fabric.coverage.aclHosts)}.`,
    "",
    T10_SAMPLE_PATH,
    "",
    `CAVEATS (${trace.caveats.length}):`,
    ...trace.caveats.map((c) => `  - ${c}`),
    "",
    `Source: ${fabric.meta.source} sha256:${fabric.meta.sourceSha256}`,
  ];
  return lines.join("\n");
}

/* ── inventory record content ───────────────────────────────────────────── */
/**
 * what an inventory record must CARRY, not merely whether one was returned.
 *
 * `Device.inventoried` says a record came back. It does not say the record holds a model, a serial
 * and a software version, and core2's software version is empty in the source snapshot while its
 * flag is true. The coverage disclosure and the Inspector's gap list both read this one predicate so
 * a record-exists flag cannot be reported as record content on either surface (critic B7).
 */

export const INVENTORY_FIELDS: readonly { key: "model" | "serial" | "swVersion"; label: string }[] = [
  { key: "model", label: "model" },
  { key: "serial", label: "serial" },
  { key: "swVersion", label: "software version" },
];

/** The inventory fields this device's record does not carry (null, non-string or blank). */
export function missingInventoryFields(d: Device): string[] {
  return INVENTORY_FIELDS.filter((f) => {
    const v: unknown = d[f.key];
    return typeof v !== "string" || v.trim() === "";
  }).map((f) => f.label);
}
