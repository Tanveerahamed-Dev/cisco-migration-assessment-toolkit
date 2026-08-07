import type { Metadata } from "next";
import { AtlasShell } from "../atlas/Shell";
import { SourceExplorer } from "../atlas/SourceExplorer";

export const metadata: Metadata = {
  title: "Whole-Repository Source Explorer · Atlas Master Reference",
  description: "The exact-tree file census, safe lazy source view, and explicit repository-understanding depth ledger.",
};

type SourcePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function SourcePage({ searchParams }: SourcePageProps) {
  const params = (await searchParams) ?? {};
  return (
    <AtlasShell active="source" eyebrow="Whole-repository accounting">
      <header className="page-title">
        <h1>Find any tracked path. See what is known—and what is not.</h1>
        <p>
          The Git tree defines the denominator. Metadata loads independently from exact safe source;
          restricted and binary content stays opaque while its role and digest remain accounted for.
        </p>
      </header>
      <section className="workspace-section">
        <SourceExplorer
          initialQuery={first(params.q)}
          initialLanguage={first(params.language)}
          initialExposure={first(params.exposure)}
        />
      </section>
    </AtlasShell>
  );
}
