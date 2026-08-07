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
const nrfuWithItem = {
  items: [
    { decision_id: "d1", title: "Verify HSRP failover", priority: "Critical", phase: "pre-cutover",
      description: "Confirm sub-second failover on the core pair.",
      pass_criteria: "Failover completes within 900ms with zero packet loss.",
      setup: "", devices: [], principle_citation: "CCDE 1.2" },
  ],
  n_items: 1,
  note: "NRFU derives from the recommended decisions.",
};
// one real coverage row so col()/the channel chip actually render (an empty `classes: []` array,
// used by the other fixture above, never exercises the fallback branch being tested here)
const archCoverageWithRow = {
  classes: [
    { key: "dmvpn", label: "DMVPN", channel: "ssh", detectors: [], observed: false,
      n_hosts: 0, hosts: [], status: "not-observed", findings: [] },
  ],
  summary: { n_classes: 27, n_observed: 12, n_with_findings: 3, n_clean: 9, n_not_observed: 15, by_channel: { ssh: 10, json: 2 } },
};

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

  it("opens an NrfuItem's disclosure from the keyboard (Enter) — WCAG 2.1.1 regression guard", async () => {
    vi.spyOn(api, "design").mockResolvedValue(design as never);
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    vi.spyOn(api, "designNrfu").mockResolvedValue(nrfuWithItem as never);
    render(<DesignBlueprintPanel snapId={1} />);
    await screen.findByText("Right-size to requirements (the WHY)");

    fireEvent.click(screen.getByRole("tab", { name: "NRFU checklist" }));
    const header = await screen.findByRole("button", { name: /Verify HSRP failover/ });
    expect(header).toHaveAttribute("tabIndex", "0");
    expect(screen.queryByText(/Pass criteria:/)).not.toBeInTheDocument();

    fireEvent.keyDown(header, { key: "Enter" });

    expect(await screen.findByText(/Failover completes within 900ms with zero packet loss\./)).toBeInTheDocument();
    expect(screen.getByText(/^Pass criteria:$/)).toBeInTheDocument();
  });

  // A capped table that truncates SILENTLY is a coverage lie: an engineer provisions from the net-new
  // IP plan on screen, and 40 rows with no remainder reads as the whole plan. The cap stays (a 4000-row
  // table helps nobody) — the remainder must be disclosed, the house "+N more" idiom.
  it("discloses the remainder when the net-new IP plan is capped at 40 rows", async () => {
    const subnets = Array.from({ length: 45 }, (_, i) => ({ vlan: 100 + i, hosts: 12, subnet: `10.${i}.0.0/24` }));
    vi.spyOn(api, "design").mockResolvedValue({
      ...design,
      target_state: { dimensions: [], addressing_plan: { status: "candidate", subnets, note: "Candidate /24-per-VLAN allocation." } },
    } as never);
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    const { container } = render(<DesignBlueprintPanel snapId={1} />);
    await screen.findByText("Right-size to requirements (the WHY)");

    // the cap is real...
    const rows = Array.from(container.querySelectorAll("table.tbl tbody tr"))
      .filter((tr) => /10\.\d+\.0\.0\/24/.test(tr.textContent || ""));
    expect(rows.length).toBe(40);
    // ...and the 5 rows it drops are stated, next to the true total
    expect(screen.getByText(/Showing/)).toBeInTheDocument();
    expect(screen.getByText(/5 more row\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/Net-new IP plan · 45 subnet\(s\)/)).toBeInTheDocument();
  });

  it("adds no truncation notice when the plan fits under the cap", async () => {
    const subnets = [{ vlan: 10, hosts: 4, subnet: "10.0.0.0/24" }];
    vi.spyOn(api, "design").mockResolvedValue({
      ...design,
      target_state: { dimensions: [], addressing_plan: { status: "candidate", subnets, note: "n/a" } },
    } as never);
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    render(<DesignBlueprintPanel snapId={1} />);
    await screen.findByText("Right-size to requirements (the WHY)");
    expect(screen.queryByText(/more row\(s\)/)).not.toBeInTheDocument();
  });

  it("renders an all-undetermined lifecycle BoM instead of hiding it as a healthy zero", async () => {
    vi.spyOn(api, "design").mockResolvedValue({
      ...design,
      target_state: {
        dimensions: [],
        replacement_bom: {
          replace_now: [],
          refresh_soon: [],
          undetermined: [["WS-C6509-E", 2], ["(lifecycle row missing)", 1]],
          n_replace: 0,
          n_refresh: 0,
          n_undetermined: 3,
          n_not_assessed: 1,
          note: "Undetermined models require authoritative lifecycle evidence before procurement.",
        },
      },
    } as never);
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    render(<DesignBlueprintPanel snapId={1} />);
    await screen.findByText("Right-size to requirements (the WHY)");

    expect(screen.getByText("Lifecycle disposition BoM · 0 replace / 0 refresh / 3 resolve")).toBeInTheDocument();
    expect(screen.getByText("WS-C6509-E")).toBeInTheDocument();
    expect(screen.getByText("(lifecycle row missing)")).toBeInTheDocument();
    expect(screen.getAllByText("Resolve before procurement")).toHaveLength(2);
    expect(screen.getByText(/authoritative lifecycle evidence before procurement/)).toBeInTheDocument();
  });

  it("keeps undetermined models visible beside costed replace and refresh rows", async () => {
    vi.spyOn(api, "design").mockResolvedValue({
      ...design,
      target_state: {
        dimensions: [],
        replacement_bom: {
          replace_now: [["PAST-LDOS", 1]],
          refresh_soon: [["PAST-EOS", 2]],
          undetermined: [["NO-AUTHORITY", 3]],
          n_replace: 1,
          n_refresh: 2,
          n_undetermined: 3,
          note: "Each lifecycle disposition remains separate.",
        },
      },
    } as never);
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverage as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    render(<DesignBlueprintPanel snapId={1} />);
    await screen.findByText("Right-size to requirements (the WHY)");

    expect(screen.getByText("Lifecycle disposition BoM · 1 replace / 2 refresh / 3 resolve")).toBeInTheDocument();
    expect(screen.getByText("PAST-LDOS")).toBeInTheDocument();
    expect(screen.getByText("PAST-EOS")).toBeInTheDocument();
    expect(screen.getByText("NO-AUTHORITY")).toBeInTheDocument();
    expect(screen.getByText("Replace")).toBeInTheDocument();
    expect(screen.getByText("Refresh")).toBeInTheDocument();
    expect(screen.getByText("Resolve before procurement")).toBeInTheDocument();
  });

  it("ArchitectureCoveragePanel resolves colors from real theme tokens, never the dead #888/#ccc fallbacks", async () => {
    vi.spyOn(api, "design").mockResolvedValue(design as never);
    vi.spyOn(api, "architectureCoverage").mockResolvedValue(archCoverageWithRow as never);
    vi.spyOn(api, "domainPacks").mockResolvedValue(domainPacks as never);
    const { container } = render(<DesignBlueprintPanel snapId={1} />);
    await screen.findByText("Right-size to requirements (the WHY)");
    // the not-observed status badge + the channel chip are what carried the dead fallbacks
    await screen.findByText("not-observed");

    const styled = Array.from(container.querySelectorAll("[style]"));
    expect(styled.length).toBeGreaterThan(0);
    for (const el of styled) expect(el.getAttribute("style")).not.toMatch(/#888|#ccc/);
    // positive check the real tokens took their place, so the fix isn't just a silent drop
    expect(styled.some((el) => (el.getAttribute("style") || "").includes("var(--text-faint)"))).toBe(true);
    expect(styled.some((el) => (el.getAttribute("style") || "").includes("var(--border)"))).toBe(true);
  });
});
