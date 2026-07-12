import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Landing from "./Landing";
import { api } from "../api";

// A real PAGE integration test: the landing route wired through the router, with the api mocked. This
// is the actual user-facing surface (render + the seed-demo interaction + its error path), not a unit.
function renderLanding() {
  return render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>,
  );
}

describe("Landing page", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the hero call-to-action and all four feature cards", () => {
    renderLanding();
    expect(screen.getByRole("button", { name: /Open a sample fleet/ })).toBeInTheDocument();
    for (const title of ["Risk cockpit", "Keystone devices", "Campaign timeline", "Deep explorer"]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it("seeds the demo fleet on click and shows the loading state", async () => {
    const spy = vi
      .spyOn(api, "seedDemo")
      .mockResolvedValue({ campaign: { id: 1 }, snapshot: { id: 5 } } as never);
    renderLanding();
    fireEvent.click(screen.getByRole("button", { name: /Open a sample fleet/ }));
    expect(spy).toHaveBeenCalledTimes(1);
    // the button flips to "Loading…" the moment seeding starts
    expect(await screen.findByRole("button", { name: /Loading/ })).toBeInTheDocument();
  });

  it("surfaces an error toast when seeding fails — never throws at the user", async () => {
    vi.spyOn(api, "seedDemo").mockRejectedValue(new Error("engine offline"));
    renderLanding();
    fireEvent.click(screen.getByRole("button", { name: /Open a sample fleet/ }));
    expect(await screen.findByText("engine offline")).toBeInTheDocument();
    // and the button recovers (not stuck in Loading)
    expect(screen.getByRole("button", { name: /Open a sample fleet/ })).toBeInTheDocument();
  });
});
