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
import type { Cite, Hop, Trace, TraceOutcome } from "./types";

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

/* ── §6.4 claim-strength badge ─────────────────────────────────────────────── */

export type ClaimBadge = "SCOPED" | "OBSERVED" | "INDETERMINATE" | "OUT OF SCOPE";

export interface ScopeTuple {
  hops: number;
  /** Hosts on THIS path whose RIB we hold. */
  modelledOnPath: number;
  /** Hosts on this path with no collected RIB. Any value above zero forecloses a SCOPED badge. */
  unmodelledOnPath: number;
  /** Evidence items the engine could not decide (chiefly unevaluable ACL lines). */
  indeterminateEvidence: number;
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
    unmodelledOnPath: unmodelled.size,
    indeterminateEvidence: indeterminate,
    hostsWithRibs: fabric.coverage.hostsWithRoutes,
    hostsTotal: fabric.devices.length,
    routableHosts: fabric.coverage.routableHosts,
    sha8: fabric.meta.sourceSha256.slice(0, 8),
    collectedAt: fabric.meta.collectedAt,
  };
}

/**
 * SCOPED is the strongest badge that exists in this product. There is deliberately no badge above
 * it: with RIBs for 2 of 26 hosts there is no exhaustive search to be had, so no result here can
 * earn the word "proven" no matter how clean the traversal was.
 */
export function claimBadge(trace: Trace): ClaimBadge {
  if (trace.outcome === "out-of-scope") return "OUT OF SCOPE";
  if (trace.outcome === "indeterminate") return "INDETERMINATE";
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
     traversed. */
  if (trace.hops.length === 0) return "INDETERMINATE";
  // A complete traversal still only earns SCOPED when every host it touched was one we modelled.
  const allOnPathModelled = trace.hops.every((h) => s.routableHosts.includes(h.host));
  return allOnPathModelled ? "SCOPED" : "OBSERVED";
}

/** The CSS custom property that carries this badge's colour. Kept here so badge and token cannot drift. */
export const badgeToken = (b: ClaimBadge): string =>
  b === "SCOPED"
    ? "var(--claim-scoped)"
    : b === "OBSERVED"
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

/** T1 — the scoped verdict header. Emitted for every trace, always. */
export function T1_verdict(trace: Trace): string {
  const s = scopeTuple(trace);
  return (
    `${claimBadge(trace)}: ${flowLabel(trace)} is ${trace.outcome} — traversed ${plural(s.hops, "hop")} ` +
    `across ${s.hostsWithRibs} of ${s.hostsTotal} hosts with a collected RIB; ` +
    `${plural(s.unmodelledOnPath, "host")} on this path could not be modelled; ` +
    `${plural(s.indeterminateEvidence, "evidence item")} ${s.indeterminateEvidence === 1 ? "was" : "were"} indeterminate. ` +
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
    `cannot evaluate it. Observed subnets: ${observedSubnets.length ? observedSubnets.join(", ") : "none recorded"}.`
  );
}

/** T4 — traversal reached a host with no RIB (acceptance B3). */
export function T4_unmodelledHost(host: string): string {
  const c = fabric.coverage;
  return (
    `INDETERMINATE: forwarding could not be modelled at ${host} because no routing table was ` +
    `collected for it (${c.hostsWithRoutes} of ${fabric.devices.length} hosts have one: ` +
    `${c.routableHosts.join(", ")}). The result above stops here. It is NOT a delivery and NOT a drop.`
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
  return (
    `${c.devicesInventoried}/${total} collected · RIBs ${c.hostsWithRoutes}/${total} · ` +
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
    `SCOPE: RIBs collected for ${s.routableHosts.join(", ")} (${s.hostsWithRibs} of ${s.hostsTotal} hosts). ` +
      `ACLs collected for ${fabric.coverage.aclHosts.join(", ") || "no host"}.`,
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
