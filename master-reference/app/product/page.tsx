import type { Metadata } from "next";
import {
  capabilityCatalog,
  core,
  deliveryGovernance,
  gapById,
} from "../atlas/data";
import { AtlasShell, OwnerLinks, SectionHeading, StateMark } from "../atlas/Shell";
import styles from "../atlas/Workspace.module.css";

export const metadata: Metadata = {
  title: "Product & Business | Atlas Master Reference",
  description:
    "The source-bound product purpose, outcomes, maturity, operating surfaces, boundary decisions, value contract, and white-label gaps.",
};

const domain = (id: string) =>
  capabilityCatalog.domains.find((candidate) => candidate.id === id)?.entries ?? [];

const productCapabilities = domain("domain.product-business");
const guiCapabilities = domain("domain.gui-white-label");
const operatingSurfaceIds = new Set([
  "cap.gui.engine-cli",
  "cap.gui.assesshub",
  "cap.gui.explorer",
  "cap.gui.portable-atlas",
  "cap.gui.master-reference",
]);
const operatingSurfaces = guiCapabilities.filter((entry) => operatingSurfaceIds.has(entry.id));
const referencedGapIds = new Set(
  [...productCapabilities, ...guiCapabilities].flatMap((entry) => entry.gap_refs ?? []),
);
const productGaps = [...referencedGapIds]
  .map((id) => gapById.get(id))
  .filter((gap) => gap !== undefined);
const currentProductCount = productCapabilities.filter((entry) => entry.state === "current").length;
const productBoundary = deliveryGovernance.decision_queue.find(
  (decision) => decision.id === "decision.product-boundary",
);
const whiteLabelBoundary = deliveryGovernance.decision_queue.find(
  (decision) => decision.id === "decision.white-label-depth",
);
const valueOutcome = core.outcomes.find((outcome) => outcome.id === "outcome.business-value");
const valueCapability = productCapabilities.find((entry) => entry.id === "cap.product.roi-tco");

export default function ProductPage() {
  return (
    <AtlasShell active="product" eyebrow="Product and business contract">
      <header className="page-title">
        <h1>What Atlas is, what it protects, and what is still a product decision.</h1>
        <p>
          This workspace is assembled from the current outcome, maturity, capability, gap,
          and decision owners. Candidate commercial and deployment models remain candidates.
        </p>
      </header>

      <section className="workspace-section" aria-label="Product status summary">
        <div className={styles.metricGrid}>
          <div><span>Outcome contracts</span><strong>{core.outcomes.length}</strong><small>declared success signals</small></div>
          <div><span>Maturity dimensions</span><strong>{core.current_maturity.length}</strong><small>each carries basis and state</small></div>
          <div><span>Current product cells</span><strong>{currentProductCount}/{productCapabilities.length}</strong><small>catalog presence is not support</small></div>
          <div><span>Linked product gaps</span><strong>{productGaps.length}</strong><small>deduplicated from product and GUI cells</small></div>
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="01"
          title="Purpose and outcome contracts"
          description={core.scope}
        />
        <div className={styles.cardGrid}>
          {core.outcomes.map((outcome) => (
            <article className={styles.card} id={outcome.id} key={outcome.id}>
              <code>{outcome.id}</code>
              <h3>{outcome.title}</h3>
              <p>{outcome.success_signal}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="02"
          title="Current maturity"
          description="Levels are bounded assessments with live owner and gap references, not one blended product score."
        />
        <div className={styles.cardGrid}>
          {core.current_maturity.map((item) => (
            <article className={styles.card} id={item.id} key={item.id}>
              <StateMark state={item.state} />
              <h3>{item.dimension}</h3>
              <p><strong>Level {item.level}</strong> - {item.basis}</p>
              <OwnerLinks ownerRefs={item.owner_refs} />
              {item.gap_refs?.length ? <p>Gaps: {item.gap_refs.join(", ")}</p> : null}
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="03"
          title="Operating surfaces and deployment boundary"
          description="The repository proves these read-only or offline surfaces. It does not yet choose a commercial hosting or tenancy model."
        />
        <div className={styles.split}>
          <div className={styles.stack}>
            {operatingSurfaces.map((surface) => (
              <article className={styles.row} key={surface.id}>
                <div><StateMark state={surface.state} /><h3>{surface.title}</h3></div>
                <div><p>{surface.current_scope}</p><OwnerLinks ownerRefs={surface.owner_refs} /></div>
              </article>
            ))}
          </div>
          {productBoundary ? (
            <article className={styles.card} id={productBoundary.id}>
              <StateMark state={productBoundary.status} />
              <h3>{productBoundary.title}</h3>
              <p>{productBoundary.current_recommendation}</p>
              <h4>Candidate boundaries</h4>
              <ul>{productBoundary.options.map((option) => <li key={option}>{option}</li>)}</ul>
              <h4>Evidence still required</h4>
              <ul>{productBoundary.evidence_needed.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
          ) : (
            <div className={styles.abstention}><strong>Boundary decision unavailable</strong>The canonical decision queue does not contain the product-boundary record.</div>
          )}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="04"
          title="Value without invented economics"
          description="Atlas declares the decision outcome and the missing capability separately; it does not manufacture customer financial inputs."
        />
        <div className={styles.split}>
          <article className={styles.card}>
            <StateMark state="target" />
            <h3>{valueOutcome?.title ?? "Business-value outcome is not declared"}</h3>
            <p>{valueOutcome?.success_signal ?? "The canonical outcome owner is absent, so this view abstains."}</p>
          </article>
          <article className={styles.card}>
            <StateMark state={valueCapability?.state ?? "unknown"} />
            <h3>{valueCapability?.title ?? "ROI/TCO capability is not declared"}</h3>
            <p>{valueCapability?.current_scope ?? "No canonical capability scope is available."}</p>
            <OwnerLinks ownerRefs={valueCapability?.owner_refs} />
          </article>
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="05"
          title="Protected non-goals"
          description="These constraints define what product expansion may not silently turn Atlas into."
        />
        <div className={styles.stack}>
          {core.non_goals.map((item) => (
            <article className={styles.row} id={item.id} key={item.id}>
              <h3>{item.id}</h3>
              <div><p>{item.statement}</p><OwnerLinks ownerRefs={item.owner_refs} /></div>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="06"
          title="White-label and product gap ledger"
          description="Brand depth, packaging, legal, support, localization, tenancy, and adoption remain explicit instead of being inferred from a theme switch."
        />
        {whiteLabelBoundary ? (
          <div className={styles.notice}>
            <strong>{whiteLabelBoundary.title} - {whiteLabelBoundary.status}</strong>
            {whiteLabelBoundary.current_recommendation}
          </div>
        ) : null}
        <div className={styles.cardGrid}>
          {productGaps.map((gap) => (
            <article className={styles.card} id={gap.id} key={gap.id}>
              <div><StateMark state={gap.disposition} /> <code>{gap.priority}</code></div>
              <h3>{gap.title}</h3>
              <p>{gap.problem}</p>
              <p><strong>Owner role:</strong> {gap.owner_role}</p>
              <a href={`/gaps?q=${encodeURIComponent(gap.id)}`}>Open gap dossier</a>
            </article>
          ))}
        </div>
      </section>
    </AtlasShell>
  );
}
