/* oxlint-disable nextjs/no-html-link-for-pages -- full-document navigation preserves the connect-src 'none' privacy boundary. */
import { capabilityCounts, capabilities, core, deliveryGovernance } from "./data";
import { AtlasShell, SectionHeading, StateMark } from "./Shell";
import { BuildIdentity } from "./BuildIdentity";

const INCOMPLETE =
  capabilityCounts.partial +
  capabilityCounts.missing +
  capabilityCounts.gated +
  capabilityCounts.unknown;

export function OwnerCockpit() {
  const dispositionCounts = deliveryGovernance.gaps.reduce<Record<string, number>>(
    (counts, gap) => {
      counts[gap.disposition] = (counts[gap.disposition] ?? 0) + 1;
      return counts;
    },
    {},
  );

  return (
    <AtlasShell active="overview">
      <section className="cockpit-hero">
        <div className="hero-copy">
          <p className="page-eyebrow">Project intelligence · {core.as_of}</p>
          <h1>
            See the whole system.
            <span>Choose the next safe improvement.</span>
          </h1>
          <p>
            Atlas turns repository evidence into a navigable digital thread: source,
            behavior, claims, tests, screens, deliverables, gaps, and decisions—without
            hiding uncertainty or inventing support.
          </p>
          <div className="hero-actions">
            <a className="action action-primary" href="/source">
              Trace the repository
            </a>
            <a className="action" href="/gaps">
              Open the decision queue
            </a>
          </div>
        </div>
        <div className="truth-orbit" aria-label="Six-plane project architecture">
          <div className="orbit-core">
            <strong>SSOT</strong>
            <span>canonical truth</span>
          </div>
          {core.system_architecture.planes.map((plane) => (
            <span className={`orbit-node orbit-node-${plane.order}`} key={plane.id}>
              {plane.title.replace(" plane", "")}
            </span>
          ))}
        </div>
      </section>

      <section className="status-rail" aria-label="Current reference posture">
        <div>
          <span>Declared catalog</span>
          <strong>{capabilities.length}</strong>
          <small>classified capabilities</small>
        </div>
        <div>
          <span>Implemented</span>
          <strong>{capabilityCounts.current}</strong>
          <small>bounded current claims</small>
        </div>
        <div>
          <span>Coverage debt</span>
          <strong>{INCOMPLETE}</strong>
          <small>partial, missing, gated, unknown</small>
        </div>
        <div>
          <span>Decision queue</span>
          <strong>{deliveryGovernance.decision_queue.length}</strong>
          <small>human-owned choices</small>
        </div>
        <BuildIdentity />
      </section>

      <section className="cockpit-section">
        <SectionHeading
          index="01"
          title="Nine outcomes hold the project together"
          description="Every subsystem should earn its place by contributing to an owner-visible outcome. Unlinked work is scope debt."
        />
        <div className="outcome-grid">
          {core.outcomes.map((outcome, index) => (
            <article key={outcome.id}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <h3>{outcome.title}</h3>
              <p>{outcome.success_signal}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="cockpit-section split-section">
        <div>
          <SectionHeading
            index="02"
            title="Capability truth, not a feature count"
            description="The denominator is closed for this catalog version; industry change stays in a separate open horizon."
          />
          <div className="state-distribution" aria-label="Capability states">
            {Object.entries(capabilityCounts).map(([state, count]) => (
              <div key={state}>
                <StateMark state={state} />
                <span className="distribution-track">
                  <span
                    className={`distribution-fill state-fill-${state}`}
                    style={{ width: `${Math.max(2, (count / capabilities.length) * 100)}%` }}
                  />
                </span>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
          <a className="text-link" href="/capabilities">
            Inspect every capability and disposition →
          </a>
        </div>

        <div className="decision-preview">
          <SectionHeading
            index="03"
            title="Owner decisions—not engineering tasks"
            description="These choices alter the product boundary, evidence burden, or delivery model and therefore remain human-owned."
          />
          {deliveryGovernance.decision_queue.slice(0, 4).map((decision) => (
            <article key={decision.id}>
              <div>
                <StateMark state={decision.status} />
                <span>{decision.authority}</span>
              </div>
              <h3>{decision.title}</h3>
              <p>{decision.current_recommendation}</p>
            </article>
          ))}
          <a className="text-link" href="/gaps#decisions">
            Resolve the complete queue →
          </a>
        </div>
      </section>

      <section className="cockpit-section">
        <SectionHeading
          index="04"
          title="Six planes, one guarded digital thread"
          description="Each handoff names what may cross the boundary. A downstream surface does not become an alternate source of truth."
        />
        <ol className="plane-flow">
          {core.system_architecture.planes.map((plane) => (
            <li key={plane.id}>
              <span>{String(plane.order).padStart(2, "0")}</span>
              <div>
                <h3>{plane.title}</h3>
                <p>{plane.purpose}</p>
                <code>{plane.owner_refs[0]}</code>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="cockpit-section gap-radar">
        <SectionHeading
          index="05"
          title="Coverage debt has different meanings"
          description="A missing engine, an evidence gate, an owner choice, and a research horizon demand different actions."
        />
        <div className="disposition-grid">
          {Object.entries(dispositionCounts)
            .sort(([, left], [, right]) => right - left)
            .map(([disposition, count]) => (
              <a href={`/gaps?disposition=${encodeURIComponent(disposition)}`} key={disposition}>
                <strong>{count}</strong>
                <span>{disposition.replaceAll("-", " ")}</span>
              </a>
            ))}
        </div>
      </section>
    </AtlasShell>
  );
}
