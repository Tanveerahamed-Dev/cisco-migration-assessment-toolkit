import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SummaryRows, SummaryValue } from "./SummaryFacts";
import { published, withheld } from "../test/projectionFixtures";

describe("summary engine states", () => {
  it("keeps a published zero visible", () => {
    render(<SummaryValue fact={published(0) as never} />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });
  it("renders the supplied minimum mark and qualifications", () => {
    render(<SummaryValue fact={{ ...published(3), minimum: true, caveats: ["finding_facet_source_incomplete"] } as never} />);
    expect(screen.getByText("≥ 3")).toBeInTheDocument();
    expect(screen.getByText(/engine-published minimum/)).toBeInTheDocument();
    expect(screen.getByText("finding_facet_source_incomplete")).toBeInTheDocument();
  });
  it.each(["not_collected", "analysis_unavailable", "not_assessed", "unverified", "collected_but_empty"] as const)(
    "renders %s with the owner reason and no numeric zero", (state) => {
      const { container } = render(<SummaryValue fact={{ ...withheld(), state, reason: "Exact owner reason" } as never} />);
      expect(container.querySelector(`[data-summary-state="${state}"]`)).toBeInTheDocument();
      expect(screen.getByText(/Exact owner reason/)).toBeInTheDocument();
      expect(screen.queryByText("0")).toBeNull();
    });
  it("refuses an older cache without the envelope contract", () => {
    render(<SummaryRows />);
    expect(screen.getByText(/Not verified — summary contract unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
  });
  it("retains each bucket's independent state", () => {
    render(<SummaryRows rows={[{ k: "Critical", n: published(1) as never }, { k: "High", n: withheld() as never }]} />);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Not collected")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
  });
});
