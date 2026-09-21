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
  claimBadge,
  scopeTuple,
  sharePayload,
  type ClaimBadge,
} from "../core/claims";
import { aclUndecidability } from "../core/acl-coverage";
import { fabric } from "../core/data";
import type { Cite, Flow, Trace, TraceOutcome } from "../core/types";
import type { CounterexampleResult } from "../forwarding/engine";
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
  SCOPED: "every host on this path had a collected routing table and every evidence item was decided",
  OBSERVED: "the traversal completed, but over evidence that does not cover the whole path",
  INDETERMINATE: "the model could not decide this flow; the reasons are listed below",
  "OUT OF SCOPE": "the question falls outside what this collection observed, so it was not evaluated",
};

/* Reason rows are grouped by the CITATION that ended each trace, so one row is one piece of
   evidence rather than one flow. The wording shown is the first flow's, which can name a single
   address while standing for several — said out loud rather than left for a reader to trip over. */
const REASON_GROUPING =
  "Grouped by the record that decided them. The wording of each row comes from the first flow in its group, so an address inside it is an example rather than the whole group.";

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

function ScopeBlock({ trace, onOpenCite }: { trace: Trace; onOpenCite: (c: Cite) => void }): ReactElement {
  const s = scopeTuple(trace);
  const c = fabric.coverage;
  const undecidable = aclUndecidability();
  const total = fabric.devices.length;
  const withoutRib = total - c.hostsWithRoutes;
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
            {`collected for ${c.hostsWithAcls} of ${total} hosts: ${c.aclHosts.join(", ") || "no host"}. ${undecidable.count} of ${undecidable.total} collected ACL lines cannot be decided${undecidable.count === 0 ? "" : ` (${undecidable.members.map((m) => m.label).join(", ")})`} — the union of what this model refuses to evaluate, what the collector's parser could not model, and what the snapshot's own reachability analysis returned indeterminate.`}
          </span>
          <CiteLink cite={c.cite} onOpen={onOpenCite} />
        </li>
        <li>
          <span className="claim__k">Unmodelled</span>
          <span>
            {`${withoutRib} of ${total} hosts have no collected routing table. A hop through any of them is reported as not modelled, never as forwarded.`}
          </span>
        </li>
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
  return (
    <>
      <Section title="Counterexample — the nearest flow that behaves differently" tone="counter">
        {result.found ? (
          <div className="claim__counter">
            <p className="claim__counter-flow">
              <span className="claim__mono">{flowText(result.flow)}</span>
              <span className="claim__counter-outcome">{OUTCOME_WORD[result.trace.outcome]}</span>
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

      {result.found && blocked !== null && blocked.decidedBy !== null ? (
        <Section title="Intended effect, and what this result does not establish" tone="intent">
          <dl className="claim__pair">
            <dt>Intended</dt>
            <dd>
              {`${flowText(trace.flow)} is ${OUTCOME_WORD[trace.outcome]} at ${blocked.host}: ${blocked.decidedBy.label}.`}
              <CiteLink cite={blocked.decidedBy.cite} onOpen={onOpenCite} />
            </dd>
            <dt>Not established</dt>
            <dd>
              {`that neighbouring traffic between the same addresses is treated the same way — ${flowText(
                result.flow,
              )} is ${OUTCOME_WORD[result.trace.outcome]}. The two statements rest on different lines of evidence and neither one closes the other.`}
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
  const band = bandOfOutcome(trace.outcome);
  const badge = claimBadge(trace);
  const Glyph = OUTCOME_ICON[trace.outcome];
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
          <span className="claim__outcome-word">{OUTCOME_WORD[trace.outcome]}</span>
        </h3>
        <span className="claim__flow claim__mono">{flowText(trace.flow)}</span>
        <CopyClaim payload={sharePayload(trace)} what="verdict" />
      </header>

      {band === "UNDETERMINED" ? (
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
              <span className="claim__counter-outcome">{OUTCOME_WORD[first.trace.outcome]}</span>
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
