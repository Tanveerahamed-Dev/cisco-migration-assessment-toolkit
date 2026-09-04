import type { Metadata } from "vinext/shims/metadata";
import { AtlasShell } from "../../atlas/Shell";
import { RecordDossier } from "../../atlas/RecordDossier";

export const metadata: Metadata = {
  title: "Dataset Dossier · Atlas Master Reference",
  description: "A source-bound structured-data inventory with lineage gaps left explicit.",
};

export default async function DatasetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AtlasShell active="source" eyebrow="Universal dossier"><RecordDossier kind="data" id={id} /></AtlasShell>;
}
