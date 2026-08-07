/* oxlint-disable nextjs/no-html-link-for-pages -- full-document links preserve connect-src 'none'. */
import type { Metadata } from "next";
import { deliveryGovernance, horizon } from "../atlas/data";
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
          description={horizon.promise}
        />
        <div className="horizon-grid">
          {horizon.signals.map((signal) => (
            <article key={signal.id}>
              <div>
                <StateMark state={signal.disposition} />
                <span>{signal.maturity}</span>
              </div>
              <p className="micro-label">{signal.theme}</p>
              <h3>{signal.title}</h3>
              <p>{signal.current_coverage}</p>
              <dl>
                <div><dt>Why it matters</dt><dd>{signal.business_relevance}</dd></div>
                <div><dt>Uncertainty</dt><dd>{signal.uncertainty}</dd></div>
                <div><dt>Next review</dt><dd>{signal.next_review_rule}</dd></div>
              </dl>
              <details>
                <summary>Promotion criteria and source families</summary>
                <ul>{signal.promotion_criteria.map((item) => <li key={item}>{item}</li>)}</ul>
                <p>{signal.source_refs.join(" · ")}</p>
              </details>
            </article>
          ))}
        </div>
        <div className="watch-family-list">
          {horizon.watch_families.map((watch) => (
            <a href={watch.source_url} rel="noreferrer" key={watch.id}>
              <strong>{watch.name}</strong>
              <span>{watch.authority_scope}</span>
              <small>{watch.review_cadence} · engine ingestion: {watch.engine_ingestion}</small>
            </a>
          ))}
        </div>
      </section>
    </AtlasShell>
  );
}
