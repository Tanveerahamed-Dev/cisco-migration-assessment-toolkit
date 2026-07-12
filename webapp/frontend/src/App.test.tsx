import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

// App is the routing spine: the top bar (always present), the route table, and the theme toggle.
// These exercise the parts jsdom can reach without mocking every page's API — the catch-all route
// and the persisted-theme logic. (Real route→page navigation is covered by the Playwright E2E.)
function renderApp(path = "/nowhere") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App shell", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("renders the top bar (brand + nav) on any route", () => {
    renderApp();
    expect(screen.getByText("AssessHub")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Campaigns" })).toBeInTheDocument();
  });

  it("degrades an unknown route to a recoverable Not-Found card, not a white screen (WEBAP-01 spirit)", () => {
    renderApp("/definitely-not-a-real-route");
    expect(screen.getByText(/Not found/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Go home/i })).toBeInTheDocument();
    // the chrome survives — the boundary is below the top bar
    expect(screen.getByText("AssessHub")).toBeInTheDocument();
  });

  it("defaults to the dark theme and persists a toggle to light", () => {
    renderApp();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    fireEvent.click(screen.getByRole("button", { name: /toggle theme/i }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("assesshub-theme")).toBe("light");
  });

  it("restores the persisted theme from localStorage on load", () => {
    localStorage.setItem("assesshub-theme", "light");
    renderApp();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
