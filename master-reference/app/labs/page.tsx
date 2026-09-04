import type { Metadata } from "vinext/shims/metadata";
import { core, deliveryGovernance } from "../atlas/data";
import { LabsExplorer } from "../atlas/LabsExplorer";
import { AtlasShell } from "../atlas/Shell";

export const metadata: Metadata = {
  title: "Deterministic Labs · Atlas Master Reference",
  description: "Fourteen synthetic, advisory walkthroughs that preserve Atlas assessment truth.",
};

type LabsPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function stepNumber(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "1", 10);
  return Number.isFinite(parsed) ? parsed - 1 : 0;
}

export default async function LabsPage({ searchParams }: LabsPageProps) {
  const params = (await searchParams) ?? {};
  return (
    <AtlasShell active="labs" eyebrow="Synthetic learning environments">
      <header className="page-title">
        <h1>Learn the boundary without crossing it.</h1>
        <p>
          Fourteen deterministic labs expose the reasoning model, support state, evidence boundary,
          and explicit non-proof. They never ingest client data, execute network actions, or alter
          canonical assessment truth.
        </p>
      </header>
      <LabsExplorer
        initialLab={first(params.lab)}
        initialStep={stepNumber(first(params.step))}
        labs={deliveryGovernance.labs}
        owners={core.owners}
      />
    </AtlasShell>
  );
}
