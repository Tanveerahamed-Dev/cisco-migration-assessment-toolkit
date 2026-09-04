import type { Metadata } from "vinext/shims/metadata";
import { AtlasShell } from "../../atlas/Shell";
import { RecordDossier } from "../../atlas/RecordDossier";

export const metadata: Metadata = {
  title: "Workflow Dossier · Atlas Master Reference",
  description: "A source-bound workflow declaration with permissions, artifacts, and failure effects visibly unresolved where absent.",
};

export default async function WorkflowPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AtlasShell active="source" eyebrow="Universal dossier"><RecordDossier kind="workflow" id={id} /></AtlasShell>;
}
