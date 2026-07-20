import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ArchReviewPanel, { V_LABEL, V_COLOR, GRADE_COLOR } from "./ArchReview";
import { api } from "../api";

describe("ArchReview verdict maps", () => {
  it("labels every verdict band", () => {
    expect(V_LABEL.critical).toBe("CRITICAL DEVIATION");
    expect(V_LABEL.deviation).toBe("DEVIATION");
    expect(V_LABEL.advisory).toBe("ADVISORY");
    expect(V_LABEL.conforms).toBe("CONFORMS");
    expect(V_LABEL["not-assessable"]).toBe("NOT ASSESSABLE");
  });

  it("colours verdicts by severity — conforms green, critical red, not-assessable neutral (coverage-honest)", () => {
    expect(V_COLOR.conforms).toBe("var(--ok)");
    expect(V_COLOR.critical).toBe("var(--crit)");
    expect(V_COLOR.deviation).toBe("var(--risk)");
    expect(V_COLOR.advisory).toBe("var(--watch)");
    expect(V_COLOR["not-assessable"]).toBe("var(--text-faint)");
  });
});

describe("GRADE_COLOR", () => {
  it("greens A/B, ambers C, reds D/F, and stays neutral for anything unrecognised", () => {
    expect(GRADE_COLOR("A")).toBe("var(--ok)");
    expect(GRADE_COLOR("B")).toBe("var(--ok)");
    expect(GRADE_COLOR("C")).toBe("var(--watch)");
    expect(GRADE_COLOR("D")).toBe("var(--crit)");
    expect(GRADE_COLOR("F")).toBe("var(--crit)");
    expect(GRADE_COLOR("")).toBe("var(--text-faint)");
    expect(GRADE_COLOR("Z")).toBe("var(--text-faint)");
  });
});

// ── render smoke (mocked api; no router needed) ──────────────────────────────
const archreview = {
  checks: [],
  top_actions: [],
  domains: [],
  summary: {
    grade: "B",
    grade_label: "Largely conformant, few material gaps",
    statement: "The fabric broadly conforms; a few deviations to close before cutover.",
    score_pct: 82,
    n_conforms: 10, n_advisory: 3, n_deviation: 2, n_critical: 0, n_not_assessable: 1,
  },
};

// one real domain + its check, for the domain-row keyboard-selection test below.
const archreviewWithDomain = {
  ...archreview,
  domains: [{ key: "Resiliency", verdict: "advisory", score_pct: 75, checks: ["R-1"] }],
  checks: [{
    id: "R-1", domain: "Resiliency", title: "Dual-homed uplinks", verdict: "advisory",
    observed: "Single uplink observed on 3 switches.", implication: "No redundancy on failure.",
    recommendation: "Add a second uplink.", reference: "CCDE 4.2", evidence: ["sw1"],
  }],
};

describe("ArchReviewPanel (render)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the loading state while the review loads", () => {
    vi.spyOn(api, "archreview").mockReturnValue(new Promise(() => {}) as never);
    render(<ArchReviewPanel snapId={1} />);
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    vi.spyOn(api, "archreview").mockRejectedValue(new Error("archreview 1 failed"));
    render(<ArchReviewPanel snapId={1} />);
    expect(await screen.findByText("archreview 1 failed")).toBeInTheDocument();
  });

  it("renders the question board on success", async () => {
    vi.spyOn(api, "archreview").mockResolvedValue(archreview as never);
    render(<ArchReviewPanel snapId={1} />);
    expect(await screen.findByRole("tab", { name: "Where do we start?" })).toBeInTheDocument();
  });
});

describe("ArchReviewPanel accessible tabs + keyboard domain rows", () => {
  afterEach(() => vi.restoreAllMocks());

  it("flips aria-selected to the clicked question tab and back off the old one", async () => {
    vi.spyOn(api, "archreview").mockResolvedValue(archreview as never);
    render(<ArchReviewPanel snapId={1} />);
    const start = await screen.findByRole("tab", { name: "Where do we start?" });
    expect(start).toHaveAttribute("aria-selected", "true");
    const blockers = screen.getByRole("tab", { name: "What blocks the migration?" });
    expect(blockers).toHaveAttribute("aria-selected", "false");

    fireEvent.click(blockers);

    expect(blockers).toHaveAttribute("aria-selected", "true");
    expect(start).toHaveAttribute("aria-selected", "false");
    // the tabpanel's aria-labelledby follows the newly active tab
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", blockers.id);
  });

  it("selects a domain row from the keyboard — Enter toggles aria-pressed and reveals its checks", async () => {
    vi.spyOn(api, "archreview").mockResolvedValue(archreviewWithDomain as never);
    render(<ArchReviewPanel snapId={1} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Judge every design domain" }));

    const row = screen.getByRole("button", { name: /Resiliency/ });
    expect(row).toHaveAttribute("aria-pressed", "false");

    fireEvent.keyDown(row, { key: "Enter" });

    // the .tabfade wrapper remounts on domainSel change (key={q + domainSel}), so the old `row`
    // node is now detached — re-query rather than assert on the stale reference.
    expect(screen.getByRole("button", { name: /Resiliency/ })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("Dual-homed uplinks")).toBeInTheDocument();
  });
});
