import type { Metadata } from "next";
import { BuildIdentity } from "../atlas/BuildIdentity";
import {
  capabilities,
  capabilityCatalog,
  capabilityCounts,
  core,
  deliveryGovernance,
} from "../atlas/data";
import { AtlasShell, OwnerLinks, SectionHeading, StateMark } from "../atlas/Shell";
import styles from "../atlas/Workspace.module.css";

export const metadata: Metadata = {
  title: "Progress & Debt | Atlas Master Reference",
  description:
    "Current source identity, catalog state, actionable gaps, human decisions, freshness, and explicit change-history abstention.",
};

const incompleteStates = new Set(["partial", "missing", "gated", "unknown"]);
const debtEntries = capabilities.filter((entry) => incompleteStates.has(entry.state));
const excludedEntries = capabilities.filter((entry) => entry.state === "excluded");
const consequentialGaps = deliveryGovernance.gaps.filter((gap) =>
  gap.priority === "P0" || gap.priority === "P1",
);
const activeDecisions = deliveryGovernance.decision_queue.filter(
  (decision) => decision.status === "open" || decision.status === "gated",
);
const dispositionCounts = deliveryGovernance.gaps.reduce<Record<string, number>>(
  (counts, gap) => {
    counts[gap.disposition] = (counts[gap.disposition] ?? 0) + 1;
    return counts;
  },
  {},
);

export default function ProgressPage() {
  return (
    <AtlasShell active="progress" eyebrow="Current progress and debt">
      <header className="page-title">
        <h1>Current state comes from owners, not stale task language.</h1>
        <p>
          This workspace derives its denominators from the current catalogs and exact-source
          projection. Dated plans, handoffs, and closeouts are historical evidence, not an
          executable queue.
        </p>
      </header>

      <section className="workspace-section" aria-label="Progress status summary">
        <div className={styles.metricGrid}>
          <div><span>Capability denominator</span><strong>{capabilities.length}</strong><small>{capabilityCatalog.catalog_version}</small></div>
          <div><span>Current</span><strong>{capabilityCounts.current}</strong><small>bounded owner-backed slices</small></div>
          <div><span>Incomplete debt</span><strong>{debtEntries.length}</strong><small>partial, missing, gated, or unknown</small></div>
          <BuildIdentity />
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="01"
          title="Freshness and source binding"
          description="Content freshness and source identity are separate. A recent date cannot repair a missing exact-tree receipt."
        />
        <div className={styles.split}>
          <article className={styles.card}>
            <h3>Curated reference identity</h3>
            <dl>
              <div><dt>Reference ID</dt><dd><code>{core.id}</code></dd></div>
              <div><dt>As of</dt><dd>{core.as_of}</dd></div>
              <div><dt>Catalog version</dt><dd>{core.catalog_version}</dd></div>
              <div><dt>Scope</dt><dd>{core.scope}</dd></div>
            </dl>
          </article>
          <div className={styles.abstention}>
            <strong>Semantic change delta unavailable in the curated model</strong>
            The exact-source projection can bind this build to a tree, but the current curated
            content does not declare a reconciled previous semantic baseline. This view will not
            infer a change log from dated plans or handoff prose.
          </div>
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="02"
          title="Capability state distribution"
          description="Excluded capability is deliberate scope, not implementation debt. Unknown remains distinct from missing and partial."
        />
        <div className={styles.cardGrid}>
          {Object.entries(capabilityCounts).map(([state, count]) => (
            <article className={styles.card} key={state}>
              <StateMark state={state} />
              <h3>{count} capability cells</h3>
              <p><a href={`/capabilities?state=${encodeURIComponent(state)}`}>Inspect the exact {state} denominator</a></p>
            </article>
          ))}
        </div>
        {excludedEntries.length ? (
          <div className={styles.notice}>
            <strong>{excludedEntries.length} deliberate exclusion{excludedEntries.length === 1 ? "" : "s"}</strong>
            {excludedEntries.map((entry) => entry.title).join("; ")}
          </div>
        ) : null}
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="03"
          title="P0 and P1 gap queue"
          description="The queue is composed only from current dispositioned gap records. Priority indicates consequence, not automatic authorization to implement."
        />
        <div className={styles.cardGrid}>
          {consequentialGaps.map((gap) => (
            <article className={styles.card} id={gap.id} key={gap.id}>
              <div><StateMark state={gap.disposition} /> <code>{gap.priority}</code></div>
              <h3>{gap.title}</h3>
              <p>{gap.problem}</p>
              <p><strong>Smallest next action:</strong> {gap.next_actions[0] ?? "No next action declared; gap remains unresolved."}</p>
              <p><strong>Acceptance:</strong> {gap.acceptance_evidence[0] ?? "No acceptance evidence declared."}</p>
              <p><strong>Owner role:</strong> {gap.owner_role}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="04"
          title="Human decision queue"
          description="Open and gated decisions expose alternatives and evidence burden; the reference does not choose on the owner's behalf."
        />
        <div className={styles.stack}>
          {activeDecisions.map((decision) => (
            <article className={styles.row} id={decision.id} key={decision.id}>
              <div><StateMark state={decision.status} /><h3>{decision.title}</h3></div>
              <div>
                <p>{decision.current_recommendation}</p>
                <p><strong>Authority:</strong> {decision.authority}</p>
                <p><strong>Evidence:</strong> {decision.evidence_needed.join("; ")}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="05"
          title="Current baseline statements"
          description="These statements are current-looking only because their owner references are part of the canonical core model; their source values must still reconcile at build time."
        />
        <div className={styles.stack}>
          {core.current_baseline.map((baseline) => (
            <article className={styles.row} id={baseline.id} key={baseline.id}>
              <div><code>{baseline.id}</code><h3>{String(baseline.value)}</h3></div>
              <div><p>{baseline.statement}</p><OwnerLinks ownerRefs={baseline.owner_refs} /></div>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="06"
          title="Gap disposition mix"
          description="Disposition is an accountable next mode: build, evidence, research, defer, human decision, or protected exclusion."
        />
        <ul className={styles.tagList}>
          {Object.entries(dispositionCounts).map(([disposition, count]) => (
            <li key={disposition}><a href={`/gaps?disposition=${encodeURIComponent(disposition)}`}>{disposition}: {count}</a></li>
          ))}
        </ul>
      </section>
    </AtlasShell>
  );
}
