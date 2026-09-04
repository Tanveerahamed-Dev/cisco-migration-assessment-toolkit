import type { Metadata } from "vinext/shims/metadata";
import { CapabilityExplorer } from "../atlas/CapabilityExplorer";
import { capabilityCatalog, core, deliveryGovernance } from "../atlas/data";
import { AtlasShell } from "../atlas/Shell";

export const metadata: Metadata = {
  title: "Capability Matrix · Atlas Master Reference",
  description: "The closed, coverage-honest catalog of Atlas product and industry capabilities.",
};

type CapabilityPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function CapabilityPage({ searchParams }: CapabilityPageProps) {
  const params = (await searchParams) ?? {};
  const lineageDefaultView = Object.keys(params).length === 0;
  const titles = Object.fromEntries(core.domain_registry.map((item) => [item.id, item.title]));
  return (
    <AtlasShell active="capabilities" eyebrow="Closed Capability Catalog">
      <header className="page-title">
        <h1>Every declared capability has a state.</h1>
        <p>
          Presence in this matrix is not a support claim. Current entries cite live owners;
          every incomplete entry points to a dispositioned gap.
        </p>
      </header>
      <section className="workspace-section">
        <CapabilityExplorer
          catalog={capabilityCatalog}
          gaps={deliveryGovernance.gaps}
          domainTitles={titles}
          initialDomain={first(params.domain)}
          initialState={first(params.state)}
          initialQuery={first(params.q)}
          lineageDefaultView={lineageDefaultView}
        />
      </section>
    </AtlasShell>
  );
}
