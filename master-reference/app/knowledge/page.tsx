/* oxlint-disable nextjs/no-html-link-for-pages -- local full-document links preserve the connect-src 'none' boundary. */
import type { Metadata } from "vinext/shims/metadata";
import {
  capabilityCatalog,
  deliveryGovernance,
  horizon,
  ownerById,
} from "../atlas/data";
import { AtlasShell, OwnerLinks, SectionHeading, StateMark } from "../atlas/Shell";
import styles from "../atlas/Workspace.module.css";

export const metadata: Metadata = {
  title: "Knowledge & Authority | Atlas Master Reference",
  description:
    "The source-bound SSOT, Graphify, protocol, design, horizon, learnings, and Vault privacy boundaries.",
};

const domain = (id: string) =>
  capabilityCatalog.domains.find((candidate) => candidate.id === id)?.entries ?? [];

const knowledge = domain("domain.code-tests-release-knowledge");
const protocols = domain("domain.protocols");
const designs = domain("domain.enterprise-design");
const authorityCellIds = new Set([
  "cap.engine.ssot-reconciliation",
  "cap.engine.ast-graph",
  "cap.engine.research-quarantine",
  "cap.engine.vault-digest",
  "cap.engine.generic-learnings",
  "cap.engine.external-promotion",
]);
const authorityCells = knowledge.filter((entry) => authorityCellIds.has(entry.id));
const knowledgeGapIds = new Set(authorityCells.flatMap((entry) => entry.gap_refs ?? []));
const knowledgeGaps = deliveryGovernance.gaps.filter((gap) => knowledgeGapIds.has(gap.id));

function stateSummary(entries: typeof protocols) {
  return entries.reduce<Record<string, number>>((counts, entry) => {
    counts[entry.state] = (counts[entry.state] ?? 0) + 1;
    return counts;
  }, {});
}

function sourceHref(path: string): string {
  return `/source/${path.split("/").map(encodeURIComponent).join("/")}`;
}

const protocolStates = stateSummary(protocols);
const designStates = stateSummary(designs);
const citedOwnerIds = [...new Set(authorityCells.flatMap((entry) => entry.owner_refs ?? []))];

export default function KnowledgePage() {
  return (
    <AtlasShell active="knowledge" eyebrow="Knowledge and authority">
      <header className="page-title">
        <h1>Knowledge may advise Atlas; only owned evidence may establish truth.</h1>
        <p>
          Repository owners, Graphify extraction, curated knowledge, and external horizons
          remain separate authority classes. Raw Vault and client evidence never enter this site.
        </p>
      </header>

      <section className="workspace-section" aria-label="Knowledge status summary">
        <div className={styles.metricGrid}>
          <div><span>Knowledge cells</span><strong>{knowledge.length}</strong><small>closed-catalog denominator</small></div>
          <div><span>Protocol cells</span><strong>{protocols.length}</strong><small>{protocolStates.current ?? 0} current; {protocolStates.partial ?? 0} partial</small></div>
          <div><span>Design cells</span><strong>{designs.length}</strong><small>{designStates.current ?? 0} current; {designStates.partial ?? 0} partial</small></div>
          <div><span>Horizon signals</span><strong>{horizon.signals.length}</strong><small>candidates, never product facts</small></div>
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="01"
          title="Authority stack"
          description="Each cell says what it can establish, the live owner of that bounded slice, and the gap when promotion or proof is incomplete."
        />
        <div className={styles.cardGrid}>
          {authorityCells.map((entry) => (
            <article className={styles.card} id={entry.id} key={entry.id}>
              <StateMark state={entry.state} />
              <h3>{entry.title}</h3>
              <p>{entry.current_scope}</p>
              <OwnerLinks ownerRefs={entry.owner_refs} />
              {entry.gap_refs?.length ? <p>Disposition: {entry.gap_refs.join(", ")}</p> : null}
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="02"
          title="Source-of-truth and code-graph owners"
          description="These links open the exact tracked owner path. The AST graph is structural evidence; it is not runtime truth."
        />
        <div className={styles.cardGrid}>
          {citedOwnerIds.map((ownerId) => {
            const owner = ownerById.get(ownerId);
            return owner ? (
              <article className={styles.card} key={owner.id}>
                <code>{owner.id}</code>
                <h3>{owner.kind}</h3>
                <p>{owner.claim_scope}</p>
                <a href={sourceHref(owner.path)}>{owner.path}{owner.symbol ? `::${owner.symbol}` : ""}</a>
              </article>
            ) : (
              <div className={styles.abstention} key={ownerId}><strong>Owner unresolved</strong>{ownerId} is referenced but not present in the canonical owner registry.</div>
            );
          })}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="03"
          title="Protocol and enterprise-design knowledge"
          description="Breadth is reported with the full denominators and actual states. A primer or registry row never upgrades implementation support."
        />
        <div className={styles.split}>
          <article className={styles.card}>
            <h3>Protocol intelligence</h3>
            <p>{protocols.length} declared families across implemented, partial, and missing depth.</p>
            <ul className={styles.tagList}>
              {Object.entries(protocolStates).map(([state, count]) => <li key={state}>{state}: {count}</li>)}
            </ul>
            <a href="/protocols">Inspect the seven-family stage matrix</a>
          </article>
          <article className={styles.card}>
            <h3>Enterprise designs</h3>
            <p>{designs.length} independently classified domains; absence remains an explicit gap.</p>
            <ul className={styles.tagList}>
              {Object.entries(designStates).map(([state, count]) => <li key={state}>{state}: {count}</li>)}
            </ul>
            <a href="/capabilities?domain=domain.enterprise-design">Inspect every design cell</a>
          </article>
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="04"
          title="Open horizon"
          description={horizon.promise}
        />
        <div className={styles.cardGrid}>
          {horizon.signals.map((signal) => (
            <article className={styles.card} id={signal.id} key={signal.id}>
              <StateMark state={signal.disposition} />
              <p className={styles.micro}>{signal.theme} / {signal.maturity}</p>
              <h3>{signal.title}</h3>
              <p>{signal.current_coverage}</p>
              <p><strong>Uncertainty:</strong> {signal.uncertainty}</p>
              <p><strong>Promotion:</strong> {signal.promotion_criteria.join("; ")}</p>
            </article>
          ))}
        </div>
        <p><a href="/gaps#horizon">Open watch families and complete horizon dossiers</a></p>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="05"
          title="Vault and private-evidence boundary"
          description="The boundary is accounted for without importing private content."
        />
        <div className={styles.abstention}>
          <strong>No repository or reference read of the personal Vault</strong>
          Only an owner-produced, sanitized, one-way digest may be consumed when separately
          authorized. Raw pages, client snapshots, captures, credentials, and machine-local agent
          memory remain outside the tracked project universe.
        </div>
        <div className={styles.cardGrid}>
          {knowledgeGaps.map((gap) => (
            <article className={styles.card} key={gap.id}>
              <StateMark state={gap.disposition} />
              <h3>{gap.title}</h3>
              <p>{gap.problem}</p>
              <p><strong>Next:</strong> {gap.next_actions.join("; ")}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="06"
          title="Current authority rule"
          description="Dated plans, handoffs, and memories preserve reasoning; they do not become a live work queue without reconciliation against current owners."
        />
        <div className={styles.notice}>
          <strong>Repository truth wins</strong>
          Current owner code, tests, manifests, runtime evidence, and live Git state outrank
          dated instructions. Conflicts remain visible until reconciled; connected research stays
          advisory until the promotion gate passes.
        </div>
      </section>
    </AtlasShell>
  );
}
