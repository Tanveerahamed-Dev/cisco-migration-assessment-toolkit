import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import DesignBlueprintPanel, { P_COLOR, scoreColor, phaseColor } from "./DesignBlueprint";
import { api } from "../api";

describe("P_COLOR (decision priority)", () => {
  it("maps priority to a severity colour, defaulting low/unknown to ok", () => {
    expect(P_COLOR("Critical")).toBe("var(--crit)");
    expect(P_COLOR("High")).toBe("var(--risk)");
    expect(P_COLOR("Medium")).toBe("var(--watch)");
    expect(P_COLOR("Low")).toBe("var(--ok)");
    expect(P_COLOR("")).toBe("var(--ok)");
  });
});

describe("scoreColor", () => {
  it("is neutral for a null score, then reds→ambers→greens up the 0–4 scale", () => {
    expect(scoreColor(null)).toBe("var(--text-faint)");
    expect(scoreColor(0)).toBe("var(--crit)");
    expect(scoreColor(1)).toBe("var(--crit)");
    expect(scoreColor(2)).toBe("var(--risk)");
    expect(scoreColor(3)).toBe("var(--watch)");
    expect(scoreColor(4)).toBe("var(--ok)");
  });

  it("uses ≤ boundaries (a fractional score falls into the higher band)", () => {
    expect(scoreColor(1.5)).toBe("var(--risk)"); // >1 and ≤2
    expect(scoreColor(2.5)).toBe("var(--watch)"); // >2 and ≤3
  });
});

describe("phaseColor", () => {
  it("reds pre-cutover, risks post-cutover-functional, ambers everything else", () => {
    expect(phaseColor("pre-cutover")).toBe("var(--crit)");
    expect(phaseColor("post-cutover-functional")).toBe("var(--risk)");
    expect(phaseColor("post-cutover-nonfunctional")).toBe("var(--watch)");
    expect(phaseColor("")).toBe("var(--watch)");
  });
});

// ── render smoke (primary + two non-blocking secondaries; no router needed) ──
const design = {
  decisions: [],
  tradeoff_scorecard: [],
  summary: { headline: "Target-state blueprint from the assessed fleet.", n_recommended: 0, n_needs_requirement: 0, n_critical: 0 },
  requirements_model: { note: "Supply requirements to right-size the design." },
  coverage: { caveat: "Computed from the offline snapshot; live telemetry not included." },
};
const archCoverage = {
  classes: [],
  summary: { n_classes: 27, n_observed: 12, n_with_findings: 3, n_clean: 9, n_not_observed: 15, by_channel: { ssh: 10, json: 2 } },
};
const domainPacks = { selected: [], loaded: [], note: "No domain lenses engaged." };

describe("DesignBlueprintPanel (render)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the loading state while the blueprint loads", () => {
    vi.spyOn(api, "design").mockReturnValue(new Promise(() => {}) as never);
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    render(<DesignBlueprintPanel snapId={1} />);
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  it("surfaces a load error from the primary design fetch", async () => {
    vi.spyOn(api, "design").mockRejectedValue(new Error("design 1 failed"));
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    render(<DesignBlueprintPanel snapId={1} />);
    expect(await screen.findByText("design 1 failed")).toBeInTheDocument();
  });

  it("renders the blueprint tab on success", async () => {
    vi.spyOn(api, "design").mockResolvedValue(design as never);
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    render(<DesignBlueprintPanel snapId={1} />);
    expect(await screen.findByText("Right-size to requirements (the WHY)")).toBeInTheDocument();
  });

  it("keeps both tab panels mounted across switches — hidden, never refetched", async () => {
    const dSpy = vi.spyOn(api, "design").mockResolvedValue(design as never);
    const cSpy = vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    const nSpy = vi.spyOn(api, "designNrfu").mockResolvedValue(
      { items: [], note: "NRFU derives from the recommended decisions." } as never);
    render(<DesignBlueprintPanel snapId={1} />);
    await screen.findByText("Right-size to requirements (the WHY)");

    // first NRFU visit mounts + fetches the checklist exactly once…
    fireEvent.click(screen.getByRole("tab", { name: "NRFU checklist" }));
    expect(await screen.findByText("NRFU derives from the recommended decisions.")).toBeVisible();
    expect(nSpy).toHaveBeenCalledTimes(1);
    // …and the blueprint panel is HIDDEN, not unmounted (still in the document)
    expect(screen.getByText("Right-size to requirements (the WHY)")).not.toBeVisible();

    // back to blueprint: instant reuse — the old conditional-render remounted + refetched here
    fireEvent.click(screen.getByRole("tab", { name: "Design blueprint" }));
    expect(screen.getByText("Right-size to requirements (the WHY)")).toBeVisible();
    expect(screen.getByText("NRFU derives from the recommended decisions.")).not.toBeVisible();

    // a second NRFU visit reuses the mounted panel — every fetch still counted exactly once
    fireEvent.click(screen.getByRole("tab", { name: "NRFU checklist" }));
    expect(screen.getByText("NRFU derives from the recommended decisions.")).toBeVisible();
    expect(nSpy).toHaveBeenCalledTimes(1);
    expect(cSpy).toHaveBeenCalledTimes(1);
    expect(dSpy).toHaveBeenCalledTimes(1);
  });
});
