/* oxlint-disable nextjs/no-html-link-for-pages -- full-document links preserve connect-src 'none'. */
import type { Metadata } from "next";
import { deliveryGovernance, horizonGapsViewModel } from "../atlas/data";
import { GapWorkbench } from "../atlas/GapWorkbench";
import { AtlasShell, SectionHeading, StateMark } from "../atlas/Shell";

export const metadata: Metadata = {
  title: "Decisions, Gaps & Horizon · Atlas Master Reference",
  description: "Human decisions, actionable capability gaps, transparent opportunities, and the open industry horizon.",
};

type GapPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function GapPage({ searchParams }: GapPageProps) {
  const params = (await searchParams) ?? {};
  const { horizon, safetyBoundary } = horizonGapsViewModel;
  return (
    <AtlasShell active="gaps" eyebrow="Decision intelligence">
      <header className="page-title">
        <h1>Choose with the uncertainty visible.</h1>
        <p>
          No hidden composite score chooses for the owner. Alternatives, evidence gaps,
          cost and value axes, Pareto position, and acceptance burden stay inspectable.
        </p>
      </header>

      <GapWorkbench
        model={deliveryGovernance}
        initialDisposition={first(params.disposition)}
        initialQuery={first(params.q)}
        initialSelected={(first(params.compare) ?? "").split(",").filter(Boolean)}
      />

      <section className="workspace-section" id="horizon">
        <SectionHeading
          index="04"
          title="Open Horizon Register"
          description="Source-owned scope, promotion, and safety boundaries remain inspectable."
        />
        <p data-horizon-slot="web.gaps.horizon.heading.promise">{horizon.promise}</p>
        <div className="publication-boundary" aria-label="Horizon safety boundary">
          <article>
            <StateMark state="advisory" />
            <h3>Advisory content only</h3>
            <p>
              Source role: {" "}
              <strong data-horizon-slot="web.gaps.horizon.safety.content-role">
                {safetyBoundary.contentRole}
              </strong>
            </p>
          </article>
          <article>
            <StateMark state="none" />
            <h3>No support claim</h3>
            <p>
              Source support claim: {" "}
              <strong data-horizon-slot="web.gaps.horizon.safety.support-claim">
                {safetyBoundary.supportClaim}
              </strong>
            </p>
          </article>
          <article>
            <StateMark state="protected" />
            <h3>No assessment-truth mutation</h3>
            <p>
              Mutates assessment truth: {" "}
              <strong data-horizon-slot="web.gaps.horizon.safety.truth-mutation">
                {String(safetyBoundary.mutatesAssessmentTruth)}
              </strong>
            </p>
          </article>
        </div>
        <div className="horizon-grid">
          {horizon.signals.map((signal) => (
            <article key={signal.id} id={signal.id}>
              <div>
                <span data-horizon-slot={`web.gaps.horizon.signal.${signal.id}.disposition`}>
                  <StateMark state={signal.disposition} />
                </span>
                <span data-horizon-slot={`web.gaps.horizon.signal.${signal.id}.maturity`}>
                  {signal.maturity}
                </span>
              </div>
              <p className="micro-label">{signal.theme}</p>
              <h3>{signal.title}</h3>
              <p data-horizon-slot={`web.gaps.horizon.signal.${signal.id}.current-coverage`}>
                {signal.current_coverage}
              </p>
              <dl>
                <div><dt>Why it matters</dt><dd data-horizon-slot={`web.gaps.horizon.signal.${signal.id}.business-relevance`}>{signal.business_relevance}</dd></div>
                <div><dt>Uncertainty</dt><dd data-horizon-slot={`web.gaps.horizon.signal.${signal.id}.uncertainty`}>{signal.uncertainty}</dd></div>
                <div><dt>Next review</dt><dd data-horizon-slot={`web.gaps.horizon.signal.${signal.id}.next-review-rule`}>{signal.next_review_rule}</dd></div>
              </dl>
              <details>
                <summary>Promotion criteria and source families</summary>
                <ol data-horizon-slot={`web.gaps.horizon.signal.${signal.id}.promotion-criteria`}>
                  {signal.promotion_criteria.map((item) => <li key={item}>{item}</li>)}
                </ol>
                <p>{signal.source_refs.join(" · ")}</p>
              </details>
            </article>
          ))}
        </div>
        <div className="watch-family-list">
          {horizon.watch_families.map((watch) => (
            <a href={watch.source_url} rel="noreferrer" key={watch.id}>
              <strong>{watch.name}</strong>
              <span data-horizon-slot={`web.gaps.horizon.watch.${watch.id}.authority-scope`}>
                {watch.authority_scope}
              </span>
              <small>
                Review cadence: <span data-horizon-slot={`web.gaps.horizon.watch.${watch.id}.review-cadence`}>{watch.review_cadence}</span>
                {" / "}engine ingestion: <span data-horizon-slot={`web.gaps.horizon.watch.${watch.id}.engine-ingestion`}>{watch.engine_ingestion}</span>
              </small>
              {watch.additional_urls ? <small>Additional sources: {watch.additional_urls.join(" / ")}</small> : null}
            </a>
          ))}
        </div>
      </section>
    </AtlasShell>
  );
}
