/**
 * ClaimCard.tsx — the verdict, and everything that bounds it.
 *
 * The argument this component makes, in its layout: a verdict and the boundary of that verdict are
 * ONE object. The scope, the caveats and the counterexample are not supporting material tucked
 * under the answer — they are rendered inside the same card, at the same weight, because a verdict
 * quoted without them is a different and stronger claim than the one the engine made.
 *
 * Consequently:
 *   - `indeterminate` and `out-of-scope` get the SAME card chrome as `delivered` and `denied`, in
 *     --claim-indeterminate, never greyed. An honest "I cannot tell you" is the product working,
 *     and a greyed card reads as "not applicable" — which is the false-health failure in miniature.
 *   - the caveat list is never collapsed. There is no disclosure to leave shut.
 *   - the counterexample affordance is rendered even when no counterexample exists, carrying the
 *     engine's reason. A vanished affordance reads as "there is nothing to try".
 *   - every claim sentence comes from `claims.ts` or from the engine. Nothing here writes prose
 *     about network state, so nothing here can drift into a stronger word than the evidence bears.
 */
import { useCallback, useId, useState, type ReactElement, type ReactNode } from "react";
import {
  T1_verdict,
  T10_SAMPLE_PATH,
  bandOfOutcome,
  bandOfTrace,
  claimBadge,
  isDecidedOutcome,
  isInvalidInput,
  scopeTuple,
  sharePayload,
  undecidedOutcomeWord,
  type ClaimBadge,
  type ClaimBand,
} from "../core/claims";
import {
  aclUndecidability,
  type AclUndecidability,
  type UndecidableAclLine,
  type UndecidableSource,
} from "../core/acl-coverage";
import { fabric } from "../core/data";
import type { Cite, Flow, Trace, TraceOutcome } from "../core/types";
import { scopeClauseOf, type CounterexampleResult } from "../forwarding/engine";
import {
  IconCopy,
  IconNoRoute,
  IconNotObserved,
  IconOctagon,
  IconStateUnknown,
  IconTarget,
  type IconProps,
} from "../ui/icons";
import { Button, Cite as CiteLink, IconButton, LiveRegion } from "../ui/primitives";
import type { IntentVerdict } from "./PathTrace";
import "./PathTrace.css";

type Glyph = (p: IconProps) => ReactElement;

/* The enum spelling is the model's; these are the reader's words. `out-of-scope` becomes "outside
   the collected evidence" because "out of scope" reads like a product decision rather than what it
   is: a statement about how far the collection reaches. */
const OUTCOME_WORD: Readonly<Record<TraceOutcome, string>> = {
  delivered: "delivered",
  dropped: "dropped",
  denied: "denied",
  indeterminate: "indeterminate",
  "out-of-scope": "outside the collected evidence",
};

const OUTCOME_ICON: Readonly<Record<TraceOutcome, Glyph>> = {
  delivered: IconTarget,
  dropped: IconNoRoute,
  denied: IconOctagon,
  indeterminate: IconNotObserved,
  "out-of-scope": IconStateUnknown,
};

const BADGE_HELP: Readonly<Record<ClaimBadge, string>> = {
  SCOPED:
    "every host on this path had a collected routing table the snapshot does not show to be incomplete for this route decision, and collected ACLs, every other ingress the source could take reproduced this result, the gateway port it arrives by had observed filtering, and every evidence item consulted was decided",
  PARTIAL: "the traversal completed, but over evidence that does not cover the whole path — the scope below names what is missing",
  INDETERMINATE: "the model could not decide this flow; the reasons are listed below",
  "OUT OF SCOPE": "the question falls outside what this collection observed, so it was not evaluated",
  "INVALID INPUT": "the question is not a well-formed flow, so nothing was simulated — correct the input and run it again",
};

/* Reason rows are grouped by the CITATION that ended each trace, so one row is one piece of
   evidence rather than one flow. The wording shown is the first flow's, which can name a single
   address while standing for several — said out loud rather than left for a reader to trip over. */
const REASON_GROUPING =
  "Grouped by the record that decided them. The wording of each row comes from the first flow in its group, so an address inside it is an example rather than the whole group.";

/**
 * The fields in which the counterexample differs from the traced flow, named — never a fixed
 * phrase. The search may change the destination address, the port or the protocol; the sentence
 * used to say "neighbouring traffic between the same addresses" whichever it changed, which was
 * false whenever it moved the destination (2026-09-21 critic, B8).
 */
function flowDifferences(a: Flow, b: Flow): string[] {
  const out: string[] = [];
  if (a.srcIp !== b.srcIp) out.push(`its source (${b.srcIp} instead of ${a.srcIp})`);
  if (a.dstIp !== b.dstIp) out.push(`its destination (${b.dstIp} instead of ${a.dstIp})`);
  if (a.protocol !== b.protocol) out.push(`its protocol (${b.protocol} instead of ${a.protocol})`);
  else if (a.dstPort !== b.dstPort) out.push(`its destination port (${b.dstPort ?? "any"} instead of ${a.dstPort ?? "any"})`);
  return out;
}

/* The headline word for an outcome the engine returned but did not decide is built from the
   ACTUAL undecided inputs (claims.ts `undecidedOutcomeWord`), never from a fixed map keyed on the
   outcome: "denied by list text — binding not observed" was drawn over a denial whose binding WAS
   observed and which was undecided by its FHRP-alternate ingress (2026-09-21 critic, A3). */

/** The word for ANY trace this card draws — the verdict, a counterexample, an intent's first contradiction. */
/** The card's headline word for a trace. Exported so the live-region announcement speaks the SAME
 *  word the card draws — it once announced the raw outcome ("Result: dropped") under a headline
 *  reading "dropped for want of a collected route — not decided" (2026-09-22 critic, B2). */
export const outcomeWordOf = (t: Trace): string => (isInvalidInput(t) ? "invalid input" : (undecidedOutcomeWord(t) ?? OUTCOME_WORD[t.outcome]));

/**
 * A verdict stated AWAY from this card — a palette row, a Path preset, a live-region announcement —
 * and the bounds it must travel with. The one owner of those words (acceptance B2).
 *
 * Every part is read from an owner, never restated: the word and band from the claims owner (via
 * `outcomeWordOf` / `bandOfTrace`), the badge from `claimBadge`, the scope clause from the trace's OWN
 * claim (`scopeClauseOf`), the caveat count from the trace's own caveat list. So a surface cannot
 * state a verdict more strongly than this card does, and cannot state it without the scope the
 * engine attached: the palette once read "trace a path — this one ends denied" and "…the
 * blocking-hop answer with its exact configuration line" for a denial whose own claim says "That
 * denial is not decided", with no scope and no caveat anywhere on the row.
 *
 * `src/forwarding/verdict-wording.guard.test.ts` finds any outcome turned into text outside the
 * owners, so a new surface cannot bypass this function; `src/app/verdict-scope.b2.test.tsx` proves
 * the surfaces that exist carry what it returns.
 */
export interface VerdictStatement {
  /** The headline word this card draws — undecided wording included. */
  word: string;
  band: ClaimBand;
  badge: ClaimBadge;
  decided: boolean;
  /** The scope clause the trace's claim opens with; null when the claim carries none (a finding). */
  scope: string | null;
  caveats: number;
  /** Scope, badge and caveat count as one clause: what any restatement of the verdict must carry. */
  bounds: string;
  /** The word followed by its bounds. What a surface prints when it states the verdict. */
  sentence: string;
}

const NO_SCOPE =
  "This trace's claim opens with no scope clause, so this verdict is unbounded as stated — read the claim on its card before relying on it";

export function verdictStatement(t: Trace): VerdictStatement {
  const word = outcomeWordOf(t);
  const band = bandOfTrace(t);
  const badge = claimBadge(t);
  const scope = scopeClauseOf(t);
  const caveats = t.caveats.length;
  const bounds = `${scope ?? NO_SCOPE} · ${badge} · ${caveats} ${caveats === 1 ? "caveat" : "caveats"} on its card.`;
  return { word, band, badge, decided: isDecidedOutcome(t), scope, caveats, bounds, sentence: `${word}. ${bounds}` };
}

/* The intent search's tally reads each outcome in the same words the single-trace headline uses: the
   decided word, or the lead of `claims.ts :: undecidedOutcomeWord` for one returned but not decided.
   Kept beside `OUTCOME_WORD` so there is one outcome→word table in the product, not three. */
const UNDECIDED_TALLY_WORD: Readonly<Record<TraceOutcome, string>> = {
  delivered: "delivered by routing — not decided",
  denied: "denied by list text — not decided",
  dropped: "dropped for want of a collected route — not decided",
  indeterminate: "indeterminate — not decided",
  "out-of-scope": "outside the collected evidence — not decided",
};

/** The word for a COUNT of traces with one outcome, split by whether they were decided. */
export const outcomeTallyWord = (outcome: TraceOutcome, decided: boolean): string =>
  decided ? `${OUTCOME_WORD[outcome]} (decided)` : UNDECIDED_TALLY_WORD[outcome];

const flowText = (f: Flow): string =>
  `${f.protocol} ${f.srcIp} → ${f.dstIp}${f.protocol === "tcp" || f.protocol === "udp" ? `:${f.dstPort ?? "any port"}` : ""}`;

/* ── shared card chrome ─────────────────────────────────────────────────────── */

function CopyClaim({ payload, what }: { payload: string; what: string }): ReactElement {
  const [status, setStatus] = useState("");
  /* Copy emits claim + scope + caveats as one block, never the sentence alone: a verdict pasted
     into a ticket without its bounds is how an honest result becomes a dishonest quotation. */
  const copy = useCallback(() => {
    const write = navigator.clipboard?.writeText?.(payload);
    if (!write) {
      setStatus(`Could not copy the ${what}. Select the text and copy it manually.`);
      return;
    }
    write.then(
      () => setStatus(`Copied the ${what} with its scope and caveats`),
      () => setStatus(`Could not copy the ${what}. Select the text and copy it manually.`),
    );
  }, [payload, what]);
  return (
    <>
      <IconButton label={`Copy the ${what} with its scope and caveats`} icon={<IconCopy />} size="sm" onClick={copy} />
      <LiveRegion message={status} />
    </>
  );
}

function Section({
  title,
  tone,
  children,
}: {
  title: string;
  tone?: "scope" | "counter" | "caveat" | "intent";
  children: ReactNode;
}): ReactElement {
  return (
    <section className="claim__section" data-tone={tone}>
      <h4 className="claim__section-title">{title}</h4>
      {children}
    </section>
  );
}

/* ── the scope block: the denominators, read from the compiled coverage ─────── */

/* Why a line is in the general undecidable union, per source: `many` introduces a labelled member
   list, `one` names the doubt about a single line that nevertheless decided this flow. Keyed on the
   owner's `UndecidableSource`, so a source added there fails type-checking here instead of silently
   dropping out of the sentence. */
const UNDECIDABLE_BY: Readonly<Record<UndecidableSource, { many: (n: number) => string; one: string }>> = {
  engine: { many: (n) => `this model refuses to evaluate ${n}`, one: "this model does not evaluate it in general" },
  producer: { many: (n) => `the collector's parser could not model ${n}`, one: "the collector's parser flagged it as not fully modelled" },
  snapshot: {
    many: (n) => `the snapshot's own reachability analysis could not prove ${n} live or dead`,
    one: "the snapshot's own reachability analysis could not prove it live or dead",
  },
};
const UNDECIDABLE_ORDER: readonly UndecidableSource[] = ["engine", "producer", "snapshot"];

/**
 * The ACL row of the scope block (A3 audit fix, 2026-09-21).
 *
 * It used to print the whole general undecidable union — the deciding line included — under
 * "cannot be decided in general", then add a sentence explaining that the listing did not weaken
 * the verdict. A reader met "the deciding line is undecidable" first and the retraction second. Now
 * the union is split by REASON, each reason with its own members, and a line that decided THIS
 * flow is taken out of the "cannot be decided" sentence and stated on its own, with the general
 * doubt about it named for what it is. Every member of the union is still named — the count moves
 * from one sentence to the other, the coverage does not shrink.
 */
function aclScopeSentence(u: AclUndecidability, decidedHere: readonly UndecidableAclLine[]): string {
  if (u.total === 0) return "No access-list line was collected, so no ACL verdict is modelled at all.";
  const decided = new Set(decidedHere.map((m) => m.cite));
  const general = u.members.filter((m) => !decided.has(m.cite));
  const labels = (ms: readonly UndecidableAclLine[]): string => ms.map((m) => m.label).join(", ");
  const one = decidedHere.length === 1;
  const byReason = UNDECIDABLE_ORDER.flatMap((src) => {
    const ms = general.filter((m) => m.sources.includes(src));
    return ms.length === 0 ? [] : [`${UNDECIDABLE_BY[src].many(ms.length)} (${labels(ms)})`];
  });
  const head =
    general.length === 0
      ? `No other collected ACL line (of ${u.total}) is reported undecidable by this model, the collector's parser or the snapshot's reachability analysis.`
      : `${general.length} of the ${u.total} collected ACL lines cannot be decided in general${
          decidedHere.length === 0 ? "" : ` — not counting the ${one ? "line" : "lines"} that decided this flow`
        }. By reason, and a line can carry more than one: ${byReason.join("; ")}. That is a statement about each line across every possible flow, not about this one.`;
  if (decidedHere.length === 0) return head;
  const doubts = UNDECIDABLE_ORDER.filter((src) => decidedHere.some((m) => m.sources.includes(src)));
  return (
    `${head} ${labels(decidedHere)} decided this flow: ${one ? "it was" : "they were"} evaluated in full against it.` +
    (doubts.length === 0
      ? ""
      : ` Separately, ${doubts.map((src) => UNDECIDABLE_BY[src].one).join(", and ")} across every possible flow; that does not bear on this one.`)
  );
}

function ScopeBlock({ trace, onOpenCite }: { trace: Trace; onOpenCite: (c: Cite) => void }): ReactElement {
  const s = scopeTuple(trace);
  const c = fabric.coverage;
  const undecidable = aclUndecidability();
  const total = fabric.devices.length;
  const withoutRib = total - c.hostsWithRoutes;
  /* Members of the general undecidable union that THIS flow nevertheless decided on (A3). The
     union mixes per-line questions — including the snapshot's dead-line reachability verdict — with
     nothing flow-specific, so without this the scope block listed the very line the verdict quotes
     as "cannot be decided" beside a badge saying every evidence item was decided. A hop decided by
     an ACL line is decided unless the hop is unmodelled (HopList's "undecided" rule). Lines already
     explained in the Filtering row below (a binding gap) are left to that row. */
  const explainedBelow = new Set(s.policyGaps.flatMap((g) => (g.kind === "acl-uncollected" ? [] : [g.cite])));
  const decidedCites = new Set(
    trace.hops.flatMap((h) =>
      h.decidedBy?.kind === "acl" && h.verdict !== "unmodeled" && !explainedBelow.has(h.decidedBy.cite)
        ? [h.decidedBy.cite]
        : [],
    ),
  );
  const decidedHere = undecidable.members.filter((m) => decidedCites.has(m.cite));
  return (
    <Section title="Scope of this result" tone="scope">
      <p className="claim__scope-line">{T1_verdict(trace)}</p>
      <ul className="claim__scope-list">
        <li>
          <span className="claim__k">RIBs</span>
          <span>
            {`collected for ${c.hostsWithRoutes} of ${total} hosts: ${c.routableHosts.join(", ")}. Forwarding is modelled on those and no others.`}
          </span>
          <CiteLink cite={c.cite} onOpen={onOpenCite} />
        </li>
        <li>
          <span className="claim__k">ACLs</span>
          <span>
            {`collected for ${c.hostsWithAcls} of ${total} hosts: ${c.aclHosts.join(", ") || "no host"}. ${aclScopeSentence(undecidable, decidedHere)}`}
          </span>
          <CiteLink cite={c.cite} onOpen={onOpenCite} />
        </li>
        <li>
          <span className="claim__k">Unmodelled</span>
          <span>
            {`${withoutRib} of ${total} hosts have no collected routing table. A hop through any of them is reported as not modelled, never as forwarded.`}
          </span>
        </li>
        {s.policyGaps.length > 0 ? (
          <li data-emphasis="true">
            <span className="claim__k">Filtering</span>
            <span>
              {s.policyGaps
                .map((g) => {
                  if (g.kind === "acl-uncollected") return `${g.label}.`;
                  /* The denying line can be a member of the undecidable union above. That union is a
                     statement about the line across ALL flows; this flow is decided by it only
                     because every field it matches on is readable for this flow. Said here, so the
                     list above and the verdict do not read as a contradiction. */
                  const listed = undecidable.members.find((m) => m.cite === g.cite);
                  return (
                    `${g.label}.` +
                    (listed === undefined
                      ? ""
                      : ` ${listed.label} is listed above as undecidable in general (${listed.reasons.join("; ")}); for this flow its fields could be read, so it decides what the list would do — not whether the list is applied.`)
                  );
                })
                .join(" ")}
            </span>
          </li>
        ) : null}
        {trace.unmodelledHosts.length > 0 ? (
          <li data-emphasis="true">
            <span className="claim__k">On this path</span>
            <span>{`${trace.unmodelledHosts.join(", ")} — traversed with no collected routing table, so the result stops there.`}</span>
          </li>
        ) : null}
        <li>
          <span className="claim__k">Snapshot</span>
          <span className="claim__mono">{`${s.sha8} · collected ${s.collectedAt ?? "at an unrecorded time"}`}</span>
        </li>
      </ul>
    </Section>
  );
}

/* ── counterexample + the two-part change contract ──────────────────────────── */

function CounterBlock({
  trace,
  result,
  onRunFlow,
  onOpenCite,
}: {
  trace: Trace;
  result: CounterexampleResult;
  onRunFlow?: (flow: Flow) => void;
  onOpenCite: (c: Cite) => void;
}): ReactElement {
  const blocked = trace.hops.find((h) => h.verdict === "denied" || h.verdict === "no-route") ?? null;
  /* "The nearest flow that behaves differently" presumes a decided baseline to differ FROM. Over an
     undecided result (an unbound-list denial, a delivery with unobserved filtering) the nearby flow
     is still worth offering, but it is labelled as relative to an undecided result and the
     intended/not-established pair — which reads the baseline as settled — is not drawn. */
  const decided = isDecidedOutcome(trace);
  /* The OFFERED flow is judged by the same rule. The engine offers a flow decided on the modelled
     path, which still shares the source's ingress assumption — so its own outcome can be undecided,
     and it was drawn as a green "DELIVERED" beside a card that called the identical assumption
     UNDETERMINED (2026-09-21 critic, B1). Its word and band now come from `bandOfTrace`. */
  const counterDecided = result.found && isDecidedOutcome(result.trace);
  const diffs = result.found ? flowDifferences(trace.flow, result.flow) : [];
  return (
    <>
      <Section
        title={
          /* A search that offered nothing is headed as one. "Nearby flow with a different outcome"
             over a body reading "…so no counterexample is offered" named a flow the card then
             retracted (acceptance report, B8 observation). */
          !result.found
            ? decided
              ? "Counterexample — none offered by the bounded search"
              : "Nearby flow with a different outcome — none offered; relative to an UNDECIDED result, one would not be a counterexample"
            : decided && counterDecided
              ? "Counterexample — the nearest flow that behaves differently"
              : decided
                ? "Nearby flow with a different outcome — its own outcome is UNDECIDED, so not a counterexample"
                : "Nearby flow with a different outcome — relative to an UNDECIDED result, so not a counterexample"
        }
        tone="counter"
      >
        {result.found ? (
          <div className="claim__counter">
            <p className="claim__counter-flow">
              <span className="claim__mono">{flowText(result.flow)}</span>
              <span className="claim__counter-outcome" data-band={bandOfTrace(result.trace)}>
                {outcomeWordOf(result.trace)}
              </span>
            </p>
            <p className="claim__counter-why">{result.rationale}</p>
            {onRunFlow ? (
              <Button variant="secondary" size="sm" onClick={() => onRunFlow(result.flow)}>
                Trace this flow instead
              </Button>
            ) : null}
          </div>
        ) : (
          /* The affordance stays even with nothing to offer: its absence would read as "there is
             nothing to try", when the truth is that a bounded search found nothing to try. */
          <p className="claim__counter-none">{result.reason}</p>
        )}
      </Section>

      {decided && counterDecided && result.found && blocked !== null && blocked.decidedBy !== null ? (
        <Section title="Intended effect, and what this result does not establish" tone="intent">
          <dl className="claim__pair">
            <dt>Intended</dt>
            <dd>
              {`${flowText(trace.flow)} is ${outcomeWordOf(trace)} at ${blocked.host}: ${blocked.decidedBy.label}.`}
              <CiteLink cite={blocked.decidedBy.cite} onOpen={onOpenCite} />
            </dd>
            <dt>Not established</dt>
            <dd>
              {`that ${diffs.length === 0 ? "a neighbouring flow" : `a flow differing in ${diffs.join(" and ")}`} is treated the same way — ${flowText(
                result.flow,
              )} is ${outcomeWordOf(result.trace)}. The two statements rest on different lines of evidence and neither one closes the other.`}
            </dd>
          </dl>
        </Section>
      ) : null}
    </>
  );
}

/* ── the trace verdict card ─────────────────────────────────────────────────── */

export interface ClaimCardProps {
  trace: Trace;
  /** Result of `counterexample(flow, trace)`. Omit when it has not been computed. */
  counterexample?: CounterexampleResult | null;
  onRunFlow?: (flow: Flow) => void;
  onOpenCite?: (cite: Cite) => void;
}

export function ClaimCard({ trace, counterexample, onRunFlow, onOpenCite }: ClaimCardProps): ReactElement {
  const titleId = useId();
  /* The band — and so the headline colour and glyph — comes from whether the outcome was DECIDED,
     not from the outcome word: a delivery the engine does not rate as definite used to draw the
     green target beside an INDETERMINATE badge (2026-09-21 critic, B1). */
  const band = bandOfTrace(trace);
  const undecidedWord = band === "UNDETERMINED" && bandOfOutcome(trace.outcome) !== "UNDETERMINED" ? undecidedOutcomeWord(trace) : null;
  const badge = claimBadge(trace);
  const Glyph = undecidedWord !== null ? IconNotObserved : OUTCOME_ICON[trace.outcome];
  const openCite = useCallback((c: Cite) => onOpenCite?.(c), [onOpenCite]);
  const showCounter =
    counterexample != null &&
    (counterexample.found || trace.outcome === "denied" || trace.outcome === "dropped");

  return (
    <section className="claim" data-band={band} data-badge={badge} aria-labelledby={titleId}>
      <header className="claim__head">
        <span className="claim__badge" title={BADGE_HELP[badge]}>
          {badge}
          <span className="visually-hidden">{` — ${BADGE_HELP[badge]}`}</span>
        </span>
        <h3 className="claim__outcome" id={titleId}>
          <Glyph className="claim__outcome-glyph" />
          <span className="claim__outcome-word">{outcomeWordOf(trace)}</span>
        </h3>
        <span className="claim__flow claim__mono">{flowText(trace.flow)}</span>
        <CopyClaim payload={sharePayload(trace)} what="verdict" />
      </header>

      {/* Only for a flow that was actually simulated. An out-of-scope or invalid question was never
          run, and "the simulation ran and declined" under a header saying "not evaluated" was the
          card contradicting itself (2026-09-22 critic, B4). */}
      {band === "UNDETERMINED" && trace.outcome !== "out-of-scope" ? (
        /* Loud, not quiet. The tool ran; it declined to answer; that is a result about the
           evidence and it is as important as a denial. */
        <p className="claim__undetermined">
          The simulation ran and declined to decide this flow. That is a statement about the
          collected evidence, not a fault in the run and not a partial answer to be read
          optimistically.
        </p>
      ) : null}

      <p className="claim__sentence">{trace.claim}</p>
      <p className="claim__sample">{T10_SAMPLE_PATH}</p>

      <ScopeBlock trace={trace} onOpenCite={openCite} />

      {showCounter && counterexample != null ? (
        <CounterBlock
          trace={trace}
          result={counterexample}
          {...(onRunFlow ? { onRunFlow } : {})}
          onOpenCite={openCite}
        />
      ) : null}

      <Section
        title={`Caveats (${trace.caveats.length}) — every reason this result is narrower than it looks`}
        tone="caveat"
      >
        {trace.caveats.length === 0 ? (
          <p className="claim__counter-none">
            The engine recorded no caveat for this run. Treat that as a gap to check rather than as
            a broad result: every trace over this snapshot is bounded by the coverage above.
          </p>
        ) : (
          <ul className="claim__caveats">
            {trace.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        )}
      </Section>
    </section>
  );
}

/* ── the intent verdict card ────────────────────────────────────────────────── */

const INTENT_WORD: Readonly<Record<IntentVerdict["outcome"], string>> = {
  "counterexample-found": "counterexample found",
  "no-counterexample-found": "no counterexample found",
  indeterminate: "indeterminate",
};

const INTENT_BAND: Readonly<Record<IntentVerdict["outcome"], "RESOLVED" | "REFUTED" | "UNDETERMINED">> = {
  /* A counterexample REFUTES the stated intent; an exhausted search over a decided space is the
     strongest thing this product can say, and it is still only RESOLVED over that space. */
  "counterexample-found": "REFUTED",
  "no-counterexample-found": "RESOLVED",
  indeterminate: "UNDETERMINED",
};

const INTENT_ICON: Readonly<Record<IntentVerdict["outcome"], Glyph>> = {
  "counterexample-found": IconOctagon,
  "no-counterexample-found": IconTarget,
  indeterminate: IconNotObserved,
};

export interface IntentClaimCardProps {
  verdict: IntentVerdict;
  /** Loads a counterexample flow into the trace view, landing the reader on its deciding hop. */
  onRunFlow?: (flow: Flow) => void;
  onOpenCite?: (cite: Cite) => void;
}

export function IntentClaimCard({ verdict, onRunFlow, onOpenCite }: IntentClaimCardProps): ReactElement {
  const titleId = useId();
  const openCite = useCallback((c: Cite) => onOpenCite?.(c), [onOpenCite]);
  const Glyph = INTENT_ICON[verdict.outcome];
  const first = verdict.counterexamples[0] ?? null;

  return (
    <section
      className="claim claim--intent"
      data-band={INTENT_BAND[verdict.outcome]}
      data-intent-outcome={verdict.outcome}
      aria-labelledby={titleId}
    >
      <header className="claim__head">
        <h3 className="claim__outcome" id={titleId}>
          <Glyph className="claim__outcome-glyph" />
          <span className="claim__outcome-word">{INTENT_WORD[verdict.outcome]}</span>
        </h3>
        <span className="claim__flow">{verdict.intent.claim}</span>
      </header>

      {/* The bound is the result. It is rendered first and it is not collapsible: "no
          counterexample" without its denominator is the sentence this whole surface exists to
          prevent. */}
      <p className="claim__sentence">{verdict.boundSentence}</p>
      {verdict.unmodelledSentence === null ? null : (
        <p className="claim__undetermined">{verdict.unmodelledSentence}</p>
      )}

      {first !== null ? (
        <Section title="The counterexample" tone="counter">
          <div className="claim__counter">
            <p className="claim__counter-flow">
              <span className="claim__mono">{flowText(first.flow)}</span>
              <span className="claim__counter-outcome" data-band={bandOfTrace(first.trace)}>
                {outcomeWordOf(first.trace)}
              </span>
            </p>
            <p className="claim__counter-why">{first.trace.claim}</p>
            {onRunFlow ? (
              <Button variant="primary" size="sm" onClick={() => onRunFlow(first.flow)}>
                Open this flow in the trace view
              </Button>
            ) : null}
            {verdict.counterexamples.length > 1 ? (
              <p className="claim__counter-why">
                {`${verdict.counterexamples.length} of the ${verdict.searched} flows searched contradict this intent. The first in enumeration order is shown; the search did not stop at it.`}
              </p>
            ) : null}
          </div>
        </Section>
      ) : null}

      <Section title="Search cost" tone="scope">
        <ul className="claim__scope-list">
          <li>
            <span className="claim__k">Flow space</span>
            <span>
              {`${verdict.enumerated} flows = ${verdict.intent.sources.length} source address(es) × ${verdict.intent.destinations.length} destination address(es) × ${verdict.intent.services.length} service(s) named by the collected ACLs.`}
            </span>
          </li>
          <li>
            <span className="claim__k">Searched</span>
            <span>
              {verdict.dropped === 0
                ? `${verdict.searched} of ${verdict.enumerated} — the whole enumerated space was traced.`
                : `${verdict.searched} of ${verdict.enumerated}. ${verdict.dropped} were dropped by the ${verdict.cap}-flow cap and were NOT searched, so this result says nothing about them.`}
            </span>
          </li>
          <li>
            <span className="claim__k">Decided</span>
            <span>{`${verdict.decided} decided · ${verdict.undecided} could not be decided · ${verdict.satisfying} consistent with the intent · ${verdict.counterexamples.length} contradicting it.`}</span>
          </li>
          <li>
            <span className="claim__k">Addresses</span>
            <span>
              {`${verdict.intent.sourceSpace.enumerated} of the ${verdict.intent.sourceSpace.usableHosts} usable host addresses in ${verdict.intent.sourceSpace.prefix} were enumerated, and ${verdict.intent.destSpace.enumerated} of ${verdict.intent.destSpace.usableHosts} in ${verdict.intent.destSpace.prefix}. A flow from an address that was not enumerated was not searched.`}
            </span>
            <CiteLink cite={verdict.intent.sourceSpace.cite} onOpen={openCite} />
          </li>
        </ul>
      </Section>

      {verdict.undecidedReasons.length > 0 ? (
        <Section title={`Why ${verdict.undecided} flow(s) could not be decided`} tone="caveat">
          <p className="claim__counter-none">{REASON_GROUPING}</p>
          <ul className="claim__reasons">
            {verdict.undecidedReasons.map((r) => (
              <li key={r.reason}>
                <span className="claim__count">{r.count}</span>
                <span>{r.reason}</span>
                <CiteLink cite={r.cite} onOpen={openCite} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {/* The same never-collapsed section, with the same title, that a single-flow trace carries.
          A universal claim over a flow class is bounded by every one of these AT LEAST as hard as
          one flow is; rendering them on the weakest claim and omitting them from the strongest was
          the disclosure defect this section closes. */}
      <Section
        title={`Caveats (${verdict.caveats.length}) — every reason this result is narrower than it looks`}
        tone="caveat"
      >
        <p className="claim__counter-none">
          {`The union of the bounds every traced flow carried, deduped. "all ${verdict.searched}" means the caveat bounds the whole searched space; a smaller number bounds only that many flows — and an intent holds only as far as its weakest flow.`}
        </p>
        <ul className="claim__caveats">
          {verdict.caveats.map((c) => (
            <li key={c.text}>
              <span className="claim__count">
                {verdict.searched > 0 && c.flows === verdict.searched
                  ? `all ${verdict.searched}`
                  : c.flows}
              </span>
              <span>{c.text}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Intended effect" tone="intent">
        <p className="claim__sentence">{verdict.intendedEffect}</p>
      </Section>

      <Section title="Collateral — what else the search observed inside the same space" tone="caveat">
        <ul className="claim__caveats">
          {verdict.collateral.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        {verdict.decidedReasons.length > 0 ? (
          <>
            <p className="claim__counter-none">{REASON_GROUPING}</p>
            <ul className="claim__reasons">
              {verdict.decidedReasons.map((r) => (
                <li key={r.reason}>
                  <span className="claim__count">{r.count}</span>
                  <span>{r.reason}</span>
                  <CiteLink cite={r.cite} onOpen={openCite} />
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </Section>
    </section>
  );
}
