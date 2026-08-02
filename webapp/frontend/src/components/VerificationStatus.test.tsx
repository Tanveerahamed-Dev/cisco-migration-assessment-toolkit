import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SnapshotVerification } from "../api";
import { VerificationBadge, VerificationWarning } from "./VerificationStatus";

const verified: SnapshotVerification = {
  contract_version: 3,
  integrity_status: "verified",
  status: "verified",
  label: "Verified assessment",
  verified: true,
  coverage_honest: true,
  reasons: [],
  failed_phases: [],
  missing_authorities: [],
  non_authoritative_authorities: [],
  integrity_failed_authorities: [],
  integrity_unknown_authorities: [],
};

describe("snapshot verification status", () => {
  it("treats missing legacy status as unverified and warns against healthy-empty inference", () => {
    render(
      <>
        <VerificationBadge compact />
        <VerificationWarning />
      </>,
    );

    expect(screen.getByText("Unverified")).toBeInTheDocument();
    expect(
      screen.getByRole("alert", { name: "Assessment coverage is unverified" }),
    ).toHaveTextContent("Empty or absent results must not be read as healthy");
    expect(screen.getByRole("alert")).toHaveTextContent("legacy snapshot");
  });

  it("suppresses the warning only for a fully verified assessment", () => {
    render(
      <>
        <VerificationBadge value={verified} />
        <VerificationWarning value={verified} />
      </>,
    );

    expect(screen.getByText("Verified assessment")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows failed phases on a partial assessment", () => {
    const partial: SnapshotVerification = {
      ...verified,
      status: "partial",
      label: "Partial assessment",
      verified: false,
      reasons: ["Assessment phases failed: lifecycle, reachability."],
      failed_phases: ["lifecycle", "reachability"],
    };
    render(<VerificationWarning value={partial} />);

    expect(
      screen.getByRole("alert", { name: "Partial assessment coverage" }),
    ).toHaveTextContent("lifecycle, reachability");
  });

  it.each([
    ["stale contract", { ...verified, contract_version: 2 }],
    ["verified flag mismatch", { ...verified, verified: false }],
    ["coverage flag mismatch", { ...verified, coverage_honest: false }],
    ["unknown run integrity", {
      ...verified,
      status: "unverified" as const,
      verified: false,
      integrity_status: "unknown" as const,
      reasons: ["Producer run integrity is unknown."],
    }],
  ])("fails closed for %s", (_label, value) => {
    render(
      <>
        <VerificationBadge value={value} compact />
        <VerificationWarning value={value} />
      </>,
    );
    expect(screen.getByText("Unverified")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
