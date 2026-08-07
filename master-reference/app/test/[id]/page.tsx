import type { Metadata } from "next";
import { AtlasShell } from "../../atlas/Shell";
import { RecordDossier } from "../../atlas/RecordDossier";

export const metadata: Metadata = {
  title: "Test Dossier · Atlas Master Reference",
  description: "A source-bound test declaration with coverage and proof limitations kept explicit.",
};

export default async function TestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AtlasShell active="source" eyebrow="Universal dossier"><RecordDossier kind="test" id={id} /></AtlasShell>;
}
