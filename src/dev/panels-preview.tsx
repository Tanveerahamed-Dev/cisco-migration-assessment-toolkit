/**
 * panels-preview.tsx — mount every investigation panel with real data, before integration.
 *
 * Why this exists: the panels have jsdom unit tests and nobody has LOOKED at them. That is exactly
 * the gap that hid a shader bug in the 3-D subsystem for two hours while its suite stayed green —
 * jsdom asserts structure, and structure is not appearance. Putting each panel on screen with the
 * real snapshot behind it is the cheapest way to find the things a DOM assertion cannot see:
 * overlapping text, collapsed layout, a panel that renders nothing, a missing token, a dense grid
 * that is actually four visible rows.
 *
 * Separate Vite entry and separate root, so it cannot collide with the integration agent's App.tsx.
 * `?panel=<name>` shows one full-width; the default shows all of them side by side.
 */
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { DevicePane } from "../panels/DevicePane";
import { EvidencePane } from "../panels/EvidencePane";
import { Inspector } from "../panels/Inspector";
import { PathTrace } from "../panels/PathTrace";
import { PriorityQueue } from "../panels/PriorityQueue";
import { useInvestigation } from "../core/store";
import { fabric } from "../core/data";
import "../core/tokens.css";
import "../app/shell.css";
import "../ui/primitives.css";
import "../panels/DataGrid.css";
import "../panels/PriorityQueue.css";
import "../panels/DevicePane.css";
import "../panels/EvidencePane.css";
import "../panels/PathTrace.css";
import "../panels/Inspector.css";

const params = new URLSearchParams(window.location.search);
document.documentElement.setAttribute("data-theme", params.get("theme") === "light" ? "light" : "dark");
const only = params.get("panel");

/** Seed a realistic investigation so no panel renders its empty state by accident. */
function seed() {
  const s = useInvestigation.getState();
  s.selectDevice("core1");
  s.selectFinding("F001");
  s.setFlow({ srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null });
}

function Frame({ title, width, children }: { title: string; width: number; children: React.ReactNode }) {
  return (
    <section
      style={{
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
        width: only ? "100%" : width,
        flex: only ? "1 1 auto" : "0 0 auto",
        borderRight: "1px solid var(--border)",
        height: "100%",
        overflow: "hidden",
      }}
    >
      <header
        style={{
          padding: "4px 10px",
          font: "600 11px/1.6 var(--font-mono)",
          letterSpacing: "0.06em",
          color: "var(--text-faint)",
          background: "var(--surface-2)",
          borderBottom: "1px solid var(--border)",
          flex: "0 0 auto",
        }}
      >
        {title} · {width}px
      </header>
      <div style={{ flex: "1 1 auto", minHeight: 0, overflow: "auto", background: "var(--bg)" }}>{children}</div>
    </section>
  );
}

function Preview() {
  const [cite, setCite] = useState<string | null>(null);
  useState(() => {
    seed();
    return null;
  });

  const panels: Record<string, { w: number; el: React.ReactNode }> = {
    queue: { w: 300, el: <PriorityQueue onOpenEvidence={() => {}} onSelectFinding={() => {}} /> },
    path: { w: 300, el: <PathTrace onOpenCite={setCite} /> },
    device: { w: 380, el: <DevicePane onOpenCite={setCite} /> },
    evidence: { w: 380, el: <EvidencePane onOpenCite={setCite} onShowConfig={() => {}} /> },
    inspector: { w: 560, el: <Inspector cite={cite} forceOpen /> },
  };

  const show = only && panels[only] ? [only] : Object.keys(panels);

  return (
    <div style={{ position: "fixed", inset: 0, display: "flex", background: "var(--surface-1)" }}>
      {show.map((k) => (
        <Frame key={k} title={k} width={panels[k]!.w}>
          {panels[k]!.el}
        </Frame>
      ))}
      <div
        style={{
          position: "fixed",
          right: 8,
          bottom: 8,
          padding: "5px 9px",
          font: "400 11px var(--font-mono)",
          color: "var(--text-muted)",
          background: "var(--overlay)",
          border: "1px solid var(--border)",
          borderRadius: 4,
        }}
      >
        {fabric.devices.length} devices · {fabric.findings.length} findings · cite: {cite ?? "—"}
      </div>
    </div>
  );
}

const el = document.getElementById("root");
if (el)
  createRoot(el).render(
    <StrictMode>
      <Preview />
    </StrictMode>,
  );
