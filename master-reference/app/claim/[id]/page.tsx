import type { Metadata } from "vinext/shims/metadata";
import { AtlasShell } from "../../atlas/Shell";
import { RecordDossier } from "../../atlas/RecordDossier";

export const metadata: Metadata = {
  title: "Claim Dossier · Atlas Master Reference",
  description: "A typed, source-bound claim with evidence, denominator, time, verdict and uncertainty preserved.",
};

export default async function ClaimPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AtlasShell active="source" eyebrow="Universal dossier"><RecordDossier kind="claim" id={id} /></AtlasShell>;
}
