import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { deviceFixture, published, topologyFixture } from "../../test/projectionFixtures";
import { DeviceDossier, requireDossierContext } from "./DeviceDossier";

const json = (value: unknown) => new Response(JSON.stringify(value));
const parent = () => topologyFixture() as never;
const child = (host = "synthetic-edge-a", model = "Synthetic model") => {
  const document = deviceFixture(1, host);
  document.payload.identity.model = published(model) as never;
  return document;
};

describe("Native selected device dossier", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
  it("waits for a topology selection without fetching a second frontend", () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    render(<DeviceDossier document={parent()} host={null} snapshotId={1} />);
    expect(screen.getByRole("complementary", { name: "Device dossier" })).toHaveTextContent("Select a device on the topology");
    expect(fetcher).not.toHaveBeenCalled();
    expect(document.querySelector("iframe")).toBeNull();
  });
  it("uses only the exact host device projection and preserves the owner's health band", async () => {
    const document = child("edge/a~b");
    document.payload.health.score = published(999) as never;
    document.payload.health.band = published("Synthetic owner band") as never;
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(json(document));
    render(<DeviceDossier document={parent()} host="edge/a~b" snapshotId={1} />);
    await screen.findByText("Synthetic model");
    const url = new URL(String(fetcher.mock.calls[0][0]), "http://localhost");
    expect(url.pathname).toBe("/api/snapshots/1/ui-projection/device");
    expect(url.searchParams.get("host")).toBe("edge/a~b");
    expect(url.searchParams.get("limit")).toBe("25");
    const health = screen.getByRole("region", { name: "Device health" });
    expect(health).toHaveTextContent("999"); expect(health).toHaveTextContent("Synthetic owner band");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("keeps child-only qualifications attached to their own fact", async () => {
    const document = child();
    document.limitations = [{ id: "device_only", text: "Synthetic device-only limitation", owner: "synthetic.device", applies_to: ["/identity/model"] }] as never;
    document.payload.identity.model = { ...published("Synthetic model"), caveats: ["device_only"] } as never;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(document));
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    await screen.findByText("Synthetic model");
    fireEvent.click(screen.getByRole("button", { name: /^(Info|Evidence) for model$/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Synthetic device-only limitation");
    expect(screen.getByRole("dialog")).not.toHaveTextContent("Limitation detail unavailable");
  });
  it("opens native list Info in the device's own evidence context", async () => {
    const document = child();
    document.limitations = [{ id: "device_list_only", text: "Synthetic device interface list caveat", owner: "synthetic.device.interfaces", applies_to: ["/interfaces/rows"] }] as never;
    document.payload.interfaces.rows = { ...document.payload.interfaces.rows, source_list: {
      state: "not_collected", reason: "Synthetic interface evidence was not captured", subject: "/devices/synthetic-edge-a/interfaces",
      refs: [{ pointer: "/collection_completeness/devices/0", role: "basis" }], basis: "synthetic.device.interfaces:source_selection", caveats: ["device_list_only"],
    } } as never;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(document));
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    await screen.findByText("Synthetic model");
    fireEvent.click(screen.getByText("Interfaces & routes", { exact: true }));
    const list = screen.getByRole("region", { name: "Device interfaces" });
    expect(list).toHaveTextContent("Not collected"); expect(list).toHaveTextContent("Synthetic interface evidence was not captured");
    fireEvent.click(within(list).getByRole("button", { name: "Info for Device interfaces" }));
    const drawer = screen.getByRole("dialog", { name: "Evidence: Device interfaces" });
    expect(drawer).toHaveTextContent("Synthetic device interface list caveat");
    expect(drawer).toHaveTextContent("synthetic.device.interfaces:source_selection");
    expect(drawer).toHaveTextContent("/devices/synthetic-edge-a/interfaces");
    expect(drawer).toHaveTextContent("/collection_completeness/devices/0");
    expect(drawer).toHaveTextContent(document.identity.sha256);
    expect(drawer).not.toHaveTextContent("Limitation detail unavailable");
  });
  it("makes the admitted device source, engine and limitation registry available in compact evidence details", async () => {
    const document = child();
    document.limitations = [{ id: "device_source_scope", text: "Synthetic device source limitation", owner: "synthetic.device", applies_to: ["/identity"] }] as never;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(document));
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    await screen.findByText("Synthetic model");
    const summary = screen.getByText("Evidence: source, engine & limitations", { exact: true });
    const details = summary.closest("details")!;
    expect(details).not.toHaveAttribute("open"); fireEvent.click(summary); expect(details).toHaveAttribute("open");
    expect(details).toHaveTextContent(`Stored snapshot ${document.identity.snapshot_id}`);
    expect(details).toHaveTextContent(`${document.identity.bytes} bytes`); expect(details).toHaveTextContent(document.identity.digest_form);
    expect(details).toHaveTextContent(document.identity.sha256); expect(details).toHaveTextContent("Synthetic device source limitation");
    expect(details).toHaveTextContent("synthetic.device"); expect(details).toHaveTextContent("/identity");
    fireEvent.click(within(details).getByRole("button", { name: "Info for script version" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(document.engine.script_version.basis);
  });
  it("renders withheld health and collection evidence with their reasons", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(child()));
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    await screen.findByText("Synthetic model");
    for (const label of ["Device health", "Device collection"]) {
      const region = screen.getByRole("region", { name: label });
      expect(region).toHaveTextContent("Not collected"); expect(region).toHaveTextContent("Synthetic input was not collected");
      expect(within(region).queryByText("0")).toBeNull();
    }
  });
  it.each(["identity", "engine"])("refuses a device result with different %s", async (kind) => {
    const document = child("synthetic-edge-a", "Wrong source answer");
    if (kind === "identity") document.identity.bytes += 1;
    else document.engine.generated_at = published("Changed engine context") as never;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(document));
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("identity or engine context changed");
    expect(screen.queryByText("Wrong source answer")).toBeNull();
  });
  it("refuses a response naming another device", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(child("synthetic-other", "Wrong device answer")));
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("different device");
    expect(screen.queryByText("Wrong device answer")).toBeNull();
  });
  it("does not request a device when the parent snapshot and selected snapshot differ", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={2} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("different snapshot context");
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("cancels on a host switch and rejects a late old answer even when fetch ignores abort", async () => {
    let resolveOld!: (value: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise((done) => { resolveOld = done; }))
      .mockResolvedValueOnce(json(child("synthetic-edge-b", "Current device model")));
    const document = parent();
    const rendered = render(<DeviceDossier document={document} host="synthetic-edge-a" snapshotId={1} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const signal = fetcher.mock.calls[0][1]?.signal;
    rendered.rerender(<DeviceDossier document={document} host="synthetic-edge-b" snapshotId={1} />);
    expect(signal?.aborted).toBe(true); await screen.findByText("Current device model");
    await act(async () => resolveOld(json(child("synthetic-edge-a", "Late old device model"))));
    expect(screen.queryByText("Late old device model")).toBeNull();
    expect(screen.getByRole("complementary")).toHaveTextContent("Current device model");
  });
  it("hides old facts and cancels the request when the parent source object changes", async () => {
    let resolveOld!: (value: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise((done) => { resolveOld = done; }))
      .mockResolvedValueOnce(json(child("synthetic-edge-a", "Replacement source model")));
    const rendered = render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const signal = fetcher.mock.calls[0][1]?.signal;
    rendered.rerender(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    expect(signal?.aborted).toBe(true); await screen.findByText("Replacement source model");
    await act(async () => resolveOld(json(child("synthetic-edge-a", "Previous source model"))));
    expect(screen.queryByText("Previous source model")).toBeNull();
  });
  it("aborts and clears facts on deselection and unmount", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    const document = parent();
    const rendered = render(<DeviceDossier document={document} host="synthetic-edge-a" snapshotId={1} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const firstSignal = fetcher.mock.calls[0][1]?.signal;
    rendered.rerender(<DeviceDossier document={document} host={null} snapshotId={1} />);
    expect(firstSignal?.aborted).toBe(true); expect(screen.queryByRole("status")).toBeNull();
    rendered.rerender(<DeviceDossier document={document} host="synthetic-edge-a" snapshotId={1} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    const secondSignal = fetcher.mock.calls[1][1]?.signal;
    rendered.unmount(); expect(secondSignal?.aborted).toBe(true);
  });
  it("offers retry after a failed request and renders only the successful owner response", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Synthetic unavailable"))
      .mockResolvedValueOnce(json(child()));
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Synthetic unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Retry device dossier" }));
    await screen.findByText("Synthetic model"); expect(fetcher).toHaveBeenCalledTimes(2); expect(screen.queryByRole("alert")).toBeNull();
  });
  it("times out and withholds a late answer", async () => {
    vi.useFakeTimers();
    let resolve!: (value: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise((done) => { resolve = done; }));
    render(<DeviceDossier document={parent()} host="synthetic-edge-a" snapshotId={1} />);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(screen.getByRole("alert")).toHaveTextContent("timed out");
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
    await act(async () => resolve(json(child("synthetic-edge-a", "Late timed-out model"))));
    expect(screen.queryByText("Late timed-out model")).toBeNull();
  });
  it("admits matching identity and engine even when the child's caveat registry differs", () => {
    expect(() => requireDossierContext(parent(), child() as never)).not.toThrow();
  });
});
