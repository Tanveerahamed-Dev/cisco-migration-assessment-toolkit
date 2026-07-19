import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AboutPage from "./About";
import { api } from "../api";
import type { Meta } from "../api";

// The About/version page (ADR-0004 P1). Everything it shows comes from /api/meta — the app
// identity is served from the brand SSOT (cisco_toolkit/brand_tokens.py), never hardcoded here.
const META: Meta = {
  engine_schema: "3.23.0",
  severity_order: [],
  bands: [],
  section_labels: [],
  deliverables: [
    { key: "runbook", label: "Runbook", ext: "docx", available: true },
    { key: "deck", label: "Executive deck", ext: "pptx", available: true },
  ],
  app: { name: "Atlas", byline: "by Tanveer Ahamed", title: "Atlas — by Tanveer Ahamed", release: "3.31.0 (checkout)" },
};

describe("AboutPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the served identity + versions + deliverable-family size", async () => {
    vi.spyOn(api, "meta").mockResolvedValue(META);
    render(
      <MemoryRouter>
        <AboutPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Atlas — by Tanveer Ahamed")).toBeInTheDocument();
    expect(screen.getByText(/3\.31\.0 \(checkout\)/)).toBeInTheDocument();
    expect(screen.getByText(/3\.23\.0/)).toBeInTheDocument(); // engine schema
    expect(screen.getByText(/2 documents/)).toBeInTheDocument(); // from meta.deliverables, not a literal
  });

  it("surfaces a load error instead of a blank page", async () => {
    vi.spyOn(api, "meta").mockRejectedValue(new Error("api down"));
    render(
      <MemoryRouter>
        <AboutPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("api down")).toBeInTheDocument();
  });
});
