import type { Metadata } from "vinext/shims/metadata";
import {
  capabilityCatalog,
  core,
  deliveryGovernance,
  protocolDepth,
} from "../atlas/data";
import { ProtocolDepthExplorer } from "../atlas/ProtocolDepthExplorer";
import { AtlasShell } from "../atlas/Shell";

export const metadata: Metadata = {
  title: "Protocol Depth · Atlas Master Reference",
  description:
    "A source-bound seven-family protocol stage matrix with evidence prerequisites, boundaries, and direct implementation witnesses.",
};

type ProtocolPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function familySelection(value: string | string[] | undefined): {
  selectedFamily?: string;
  selectionError?: string;
} {
  if (value === undefined) return {};
  const values = Array.isArray(value) ? value : [value];
  if (values.length !== 1 || !values[0].trim()) {
    return {
      selectionError:
        "The family parameter must contain exactly one non-empty protocol ID. No substitute family was inferred.",
    };
  }
  return { selectedFamily: values[0] };
}

export default async function ProtocolPage({ searchParams }: ProtocolPageProps) {
  const params = (await searchParams) ?? {};
  const selection = familySelection(params.family);
  const protocolCapabilities =
    capabilityCatalog.domains.find((domain) => domain.id === "domain.protocols")?.entries ?? [];

  return (
    <AtlasShell active="protocols" eyebrow="Protocol intelligence">
      <header className="page-title">
        <h1>Protocol depth, family by family.</h1>
        <p>
          See exactly what Atlas can collect, parse, assess, explain, validate, and deliver for
          each runtime health family—and where it must abstain.
        </p>
      </header>
      <section className="workspace-section">
        <ProtocolDepthExplorer
          gaps={deliveryGovernance.gaps}
          model={protocolDepth}
          owners={core.owners}
          protocolCapabilities={protocolCapabilities}
          selectedFamily={selection.selectedFamily}
          selectionError={selection.selectionError}
        />
      </section>
    </AtlasShell>
  );
}
