import type { Metadata } from "next";
import { GraphExplorer } from "../atlas/GraphExplorer";
import { AtlasShell } from "../atlas/Shell";

export const metadata: Metadata = {
  title: "Complete Graphify Projection · Atlas Master Reference",
  description: "Every safe Graphify node, edge and community, including thin and disconnected records.",
};

export default function GraphPage() {
  return (
    <AtlasShell active="graph" eyebrow="Complete static graph">
      <header className="page-title">
        <h1>Keep every safe node and edge, including the awkward ones.</h1>
        <p>Search the complete privacy-filtered Graphify projection. Inferred edges remain distinct from extracted records, and neither is represented as runtime truth.</p>
      </header>
      <section className="workspace-section"><GraphExplorer /></section>
    </AtlasShell>
  );
}
