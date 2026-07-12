import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

// A child that throws during render — the exact hazard WEBAP-01 added the boundary for: one panel
// crashing must NOT white-screen the whole route.
function Boom({ message }: { message: string }) {
  throw new Error(message);
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs caught render errors (and componentDidCatch logs too) — silence the expected noise
    // so a green run is actually clean, without hiding a real failure.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders its children unchanged when nothing throws", () => {
    render(
      <ErrorBoundary>
        <p>healthy panel</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("healthy panel")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("catches a render crash and shows the recoverable alert card instead of unmounting", () => {
    render(
      <ErrorBoundary>
        <Boom message="section parse failed" />
      </ErrorBoundary>,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent("Something went wrong rendering this view");
  });

  it("surfaces the thrown error's own message to the operator", () => {
    render(
      <ErrorBoundary>
        <Boom message="malformed upload: device CS01" />
      </ErrorBoundary>,
    );
    expect(screen.getByText("malformed upload: device CS01")).toBeInTheDocument();
  });

  it("offers both recovery affordances (Try again + Reload), not a dead end", () => {
    render(
      <ErrorBoundary>
        <Boom message="x" />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });
});
