import type { Metadata } from "next";
import { AskAtlas } from "../atlas/AskAtlas";
import { AtlasShell } from "../atlas/Shell";

export const metadata: Metadata = {
  title: "Ask Atlas & Enhancement Compiler · Atlas Master Reference",
  description: "Deterministic, citation-first project queries and gap-bound enhancement briefs.",
};

type AskPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AskPage({ searchParams }: AskPageProps) {
  const params = (await searchParams) ?? {};
  return (
    <AtlasShell active="ask" eyebrow="Citation-first local intelligence">
      <header className="page-title">
        <h1>Answers must show their records—or abstain.</h1>
        <p>
          Ask Atlas is a deterministic local index, not a runtime AI. It resolves stable catalog
          records, keeps advisory and product truth separate, and compiles governed enhancement
          briefs only from exact gap IDs.
        </p>
      </header>
      <AskAtlas initialQuery={first(params.q)} initialTarget={first(params.target)} />
    </AtlasShell>
  );
}
