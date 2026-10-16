import type { InvestigationTool } from "../components/InvestigationPanel";

// Provisional presentation configuration while the consolidated product concept is prepared.
// No request, projection ownership, analysis result or selection lifetime depends on this list.
export const workspaceSections = [
  { label: "Network", description: "Explore the stored network and its evidence." },
  { label: "Findings", description: "Engine findings will link directly to devices on the Network map." },
  { label: "Inventory", description: "Device and endpoint evidence will be available here." },
  { label: "Plan", description: "Design, move groups and saved plans will be brought into this workspace." },
  { label: "Change", description: "MOP, runbook, wave decisions, NRFU and comparison will be brought into this workspace." },
  { label: "Reports", description: "Deliverable downloads will be brought into this workspace." },
] as const;
export type WorkspaceSection = typeof workspaceSections[number]["label"];
export const networkTools: readonly InvestigationTool[] = [
  { id: "details", label: "Details" },
  ...["If this fails", "Path", "Endpoint", "VLAN"].map((label) => ({
    id: label, label, disabled: true, pendingReason: "Available in the next reviewed Network tools increment",
  })),
];
