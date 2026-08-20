import type { Metadata } from "next";
import architecture from "../../governance/architecture.json";
import { core, deliveryGovernance } from "../atlas/data";
import { AtlasShell, SectionHeading, StateMark } from "../atlas/Shell";
import { SystemLens } from "../atlas/SystemLens";

export const metadata: Metadata = {
  title: "System & Assurance · Atlas Master Reference",
  description: "The executable architecture, digital thread, invariants, and traffic-truth model for Atlas.",
};

type SystemPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function SystemPage({ searchParams }: SystemPageProps) {
  const params = (await searchParams) ?? {};
  const requestedLens = first(params.lens);
  const lens = ["map", "trace", "matrix", "dossier"].includes(requestedLens ?? "")
    ? (requestedLens as "map" | "trace" | "matrix" | "dossier")
    : "map";
  return (
    <AtlasShell active="system" eyebrow="Living system map">
      <header className="page-title">
        <h1>Architecture is a contract, not a diagram.</h1>
        <p>
          Declared layers, static dependencies, runtime phases, truth boundaries, and
          human gates are evaluated together. Unexplained consequential edges block release.
        </p>
      </header>

      <section className="workspace-section">
        <SystemLens
          planes={core.system_architecture.planes}
          flow={core.system_architecture.flow}
          lifecycle={core.lifecycle_stages}
          initialLens={lens}
          initialEntity={first(params.entity)}
        />
      </section>

      <section className="workspace-section" id="traffic">
        <SectionHeading
          index="02"
          title="Eight traffic lenses keep different proofs separate"
          description={core.traffic_model.warning}
        />
        <div className="traffic-grid">
          {core.traffic_model.planes.map((plane) => (
            <article key={plane.id}>
              <div>
                <span>{String(plane.order).padStart(2, "0")}</span>
                <StateMark state={plane.state} />
              </div>
              <h3>{plane.title}</h3>
              <p>{plane.current_scope}</p>
              <details>
                <summary>Questions this lens must answer</summary>
                <ul>{plane.questions.map((question) => <li key={question}>{question}</li>)}</ul>
              </details>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="03"
          title="Protected invariants are executable release inputs"
          description="Each invariant is owned and independently challenged. A policy exception cannot waive a protected constraint."
        />
        <div className="invariant-list">
          {deliveryGovernance.invariants.map((invariant, index) => (
            <article id={invariant.id} key={invariant.id}>
              <span>I-{String(index + 1).padStart(2, "0")}</span>
              <p>{invariant.statement}</p>
              <code>{invariant.owner_refs.join(" · ")}</code>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <SectionHeading
          index="04"
          title="Declared dependency directions"
          description="The checked contract distinguishes allowed collaboration from explicit forbidden crossings."
        />
        <div className="architecture-contract">
          <div>
            <strong>{architecture.components.length}</strong>
            <span>declared components</span>
          </div>
          <div>
            <strong>{architecture.allowed_edges.length}</strong>
            <span>allowed directions</span>
          </div>
          <div>
            <strong>{architecture.forbidden_edges.length}</strong>
            <span>explicit forbidden edges</span>
          </div>
          <div>
            <strong>{architecture.runtime_phases.length}</strong>
            <span>runtime phases</span>
          </div>
        </div>
        <div className="forbidden-edges">
          {architecture.forbidden_edges.map((edge) => (
            <article key={`${edge.from}-${edge.to}`}>
              <code>{edge.from}</code>
              <span>must not depend on</span>
              <code>{edge.to}</code>
              <p>{edge.reason}</p>
            </article>
          ))}
        </div>
      </section>
    </AtlasShell>
  );
}
