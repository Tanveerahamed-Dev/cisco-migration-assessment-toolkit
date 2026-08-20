import type { Metadata } from "next";
import { AtlasShell } from "../../atlas/Shell";
import { SourceFileView } from "../../atlas/SourceFileView";

export const metadata: Metadata = {
  title: "Source File · Atlas Master Reference",
  description: "A digest-bound, per-file lazy source view with line-level structural mapping and explicit uncertainty.",
};

type SourceFilePageProps = {
  params: Promise<{ path: string[] }>;
};

export default async function SourceFilePage({ params }: SourceFilePageProps) {
  const resolved = await params;
  return (
    <AtlasShell active="source" eyebrow="Safe line-level source">
      <SourceFileView path={resolved.path.join("/")} />
    </AtlasShell>
  );
}
