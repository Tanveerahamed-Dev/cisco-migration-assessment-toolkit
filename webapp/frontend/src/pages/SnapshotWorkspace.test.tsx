import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import SnapshotWorkspace from "./SnapshotWorkspace";

// This boundary test stubs only the Core body. App.test exercises the actual Core source guard.
vi.mock("./CoreSnapshot", () => ({ default: ({ embedded }: { embedded?: boolean }) => {
  const location = useLocation();
  return <div data-testid="core-body" data-embedded={String(embedded)}>{location.search}</div>;
} }));

function Harness() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/snapshots/2")}>Change snapshot</button>
    <Routes><Route path="/snapshots/:id" element={<SnapshotWorkspace />} /></Routes></>;
}
function show(path = "/snapshots/1") {
  return render(<MemoryRouter initialEntries={[path]}><Harness /></MemoryRouter>);
}
const explorer = () => screen.getByTitle("Network Migration Explorer") as HTMLIFrameElement;

describe("Snapshot topology workspace", () => {
  afterEach(() => vi.restoreAllMocks());

  it("opens the existing Cable Map renderer in an opaque frame without a popup", () => {
    const popup = vi.spyOn(window, "open");
    show();
    expect(explorer()).toHaveAttribute("src", "/api/snapshots/1/explorer#mode=cablemap");
    expect(explorer()).toHaveAttribute("sandbox", "allow-scripts allow-downloads allow-modals");
    expect(explorer().sandbox?.contains("allow-same-origin") ?? false).toBe(false);
    expect(screen.getByRole("link", { name: "Network", exact: true })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByTestId("core-body")).not.toBeInTheDocument();
    expect(popup).not.toHaveBeenCalled();
  });

  it("retains the same frame across Core tabs, hiding it from interaction until Network returns", () => {
    show();
    const initial = explorer();
    fireEvent.click(screen.getByRole("link", { name: "Findings", exact: true }));
    expect(explorer()).toBe(initial);
    const network = screen.getByLabelText("Network workspace", { selector: "section" });
    expect(network).toHaveAttribute("hidden");
    expect(network).toHaveAttribute("inert");
    expect(screen.getByTestId("core-body")).toHaveAttribute("data-embedded", "true");
    expect(screen.getByTestId("core-body")).toHaveTextContent("?view=findings");
    fireEvent.click(screen.getByRole("link", { name: "Network", exact: true }));
    expect(explorer()).toBe(initial);
    expect(network).not.toHaveAttribute("hidden");
    expect(network).not.toHaveAttribute("inert");
    expect(screen.queryByTestId("core-body")).not.toBeInTheDocument();
  });

  it("does not load the Explorer for an explicit Core deep link and preserves its exact parameters", () => {
    const params = new URLSearchParams({ view: "inventory", inventory: "endpoints", ref: "/endpoints/4",
      row: "4", source: `sha256:${"b".repeat(64)}`, source_bytes: "123" });
    show(`/snapshots/1?${params}`);
    expect(screen.queryByTitle("Network Migration Explorer")).not.toBeInTheDocument();
    expect(screen.getByTestId("core-body").textContent).toBe(`?${params}`);
    expect(screen.getByRole("link", { name: "Inventory", exact: true })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("link", { name: "Network", exact: true }));
    expect(explorer()).toHaveAttribute("src", "/api/snapshots/1/explorer#mode=cablemap");
  });

  it("preserves exact device identity on a secondary deep link", () => {
    const params = new URLSearchParams({ view: "device", host: "edge/a~b" });
    show(`/snapshots/1?${params}`);
    expect(screen.getByTestId("core-body").textContent).toBe(`?${params}`);
    expect(screen.getByRole("link", { name: "Inventory", exact: true })).toHaveAttribute("aria-current", "page");
  });

  it("starts a new frame on snapshot change rather than carrying the previous investigation", () => {
    show();
    const previous = explorer();
    fireEvent.click(screen.getByRole("button", { name: "Change snapshot" }));
    expect(explorer()).not.toBe(previous);
    expect(previous).not.toBeInTheDocument();
    expect(explorer()).toHaveAttribute("src", "/api/snapshots/2/explorer#mode=cablemap");
    expect(screen.getByText("Snapshot 2")).toBeInTheDocument();
  });

  it("offers focus and a fresh frame after a frame loading error", () => {
    show();
    const original = explorer();
    const focus = vi.spyOn(original, "focus");
    fireEvent.click(screen.getByRole("button", { name: "Focus topology" }));
    expect(focus).toHaveBeenCalledOnce();
    fireEvent.error(original);
    expect(screen.getByRole("alert")).toHaveTextContent("The Explorer frame could not load");
    fireEvent.click(screen.getByRole("button", { name: "Reload topology" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(explorer()).not.toBe(original);
    expect(explorer()).toHaveAttribute("src", "/api/snapshots/1/explorer#mode=cablemap");
    fireEvent.error(original);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(["0", "-1", "not-a-snapshot", "9007199254740992", "1e3", "0x1", "01"])("withholds all snapshot readers for invalid id %s", (id) => {
    show(`/snapshots/${id}`);
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a valid snapshot from Campaigns");
    expect(screen.queryByTitle("Network Migration Explorer")).not.toBeInTheDocument();
    expect(screen.queryByTestId("core-body")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Focus topology" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload topology" })).toBeDisabled();
  });

  it("keeps tool scope available through Workspace info and retains secondary assessment access", () => {
    show();
    const navigation = within(screen.getByRole("navigation", { name: "Snapshot views" }));
    for (const title of ["Overview", "Trust", "Inventory", "Findings", "Topology & Paths"]) {
      expect(navigation.getByRole("link", { name: title, exact: true })).toHaveAttribute("href", expect.stringContaining("?view="));
    }
    expect(screen.getByRole("link", { name: "Tools and downloads" })).toHaveAttribute("href", "/snapshots/1/tools");
    const info = screen.getByText("Workspace info").closest("details")!;
    expect(info).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Workspace info"));
    expect(info).toHaveAttribute("open");
    expect(info).toHaveTextContent("Flow is not canonical Traffic Assurance");
    expect(info).toHaveTextContent("They do not test live traffic or establish application delivery");
  });
});
