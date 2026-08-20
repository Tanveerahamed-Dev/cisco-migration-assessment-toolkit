import type { Metadata } from "next";
import { AtlasShell } from "../../atlas/Shell";
import { RecordDossier } from "../../atlas/RecordDossier";

export const metadata: Metadata = {
  title: "Symbol Dossier · Atlas Master Reference",
  description: "A source-bound symbol dossier with structural proof and explicit behavioral unknowns.",
};

export default async function SymbolPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AtlasShell active="source" eyebrow="Universal dossier"><RecordDossier kind="symbol" id={id} /></AtlasShell>;
}
