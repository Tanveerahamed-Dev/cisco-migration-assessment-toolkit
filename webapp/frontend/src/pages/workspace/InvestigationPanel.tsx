import type { ReactNode } from "react";

export interface InvestigationTool {
  id: string;
  label: string;
  disabled?: boolean;
  pendingReason?: string;
}

// Presentation frame only. The caller supplies the selection and projection-backed body;
// tool availability describes implemented UI controls, never a network verdict.
export function InvestigationPanel({ title, hasSelection, clear, tools, activeTool, selectTool, children }: {
  title: string; hasSelection: boolean; clear: () => void;
  tools: readonly InvestigationTool[]; activeTool: string; selectTool?: (id: string) => void;
  children: ReactNode;
}) {
  return <aside className="workspace-selection" aria-label="Selection details">
    <header><h2>{title}</h2>{hasSelection && <button className="btn ghost" onClick={clear}>Clear selection</button>}</header>
    <div className="workspace-device-tools" role="group" aria-label="Device tools">{tools.map((tool) =>
      <button key={tool.id} className={`btn${activeTool === tool.id ? "" : " ghost"}`}
        aria-pressed={activeTool === tool.id} disabled={tool.disabled} title={tool.pendingReason}
        onClick={selectTool ? () => selectTool(tool.id) : undefined}>{tool.label}</button>)}</div>
    {children}
  </aside>;
}
