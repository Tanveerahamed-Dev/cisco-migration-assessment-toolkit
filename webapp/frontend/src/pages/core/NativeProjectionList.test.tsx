import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { findingsFixture } from "../../test/projectionFixtures";
import { NativeProjectionList } from "./NativeProjectionList";
import type { Projection } from "../../projection";

const json = (value: unknown) => new Response(JSON.stringify(value));
function pagingFixture() {
  const first = findingsFixture(), second = findingsFixture(1, 1);
  return { document: first as unknown as Projection, initial: first.payload.rows,
    next: { ...second, payload: undefined, list: second.payload.rows } };
}

describe("Native evidence paging deadlines", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
  it("times out Next, retries the exact offset and ignores the late old result without cancelling the new deadline", async () => {
    vi.useFakeTimers();
    const fixture = pagingFixture();
    let resolveOld!: (value: Response) => void, resolveRetry!: (value: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => new Promise((done) => { resolveOld = done; }))
      .mockImplementationOnce(() => new Promise((done) => { resolveRetry = done; }));
    render(<NativeProjectionList title="Findings" document={fixture.document} initial={fixture.initial}
      renderRow={(row) => <p>{row.pointer}</p>} />);
    const region = screen.getByRole("region", { name: "Findings" });
    fireEvent.click(screen.getByRole("button", { name: "Next Findings page" }));
    expect(fetcher).toHaveBeenCalledTimes(1);
    const firstSignal = fetcher.mock.calls[0][1]?.signal;
    expect(region).toHaveAttribute("aria-busy", "true");
    await act(async () => { vi.advanceTimersByTime(29_999); });
    expect(firstSignal?.aborted).toBe(false); expect(screen.queryByRole("alert")).toBeNull();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(firstSignal?.aborted).toBe(true);
    expect(screen.getByRole("alert")).toHaveTextContent("The evidence page request timed out. Retry this page.");
    expect(region).toHaveAttribute("aria-busy", "false");
    expect(screen.getByText("/punchlist/7", { exact: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next Findings page" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry Findings page" }));
    expect(fetcher).toHaveBeenCalledTimes(2);
    const retrySignal = fetcher.mock.calls[1][1]?.signal;
    expect(fetcher.mock.calls.map(([url]) => new URL(String(url), "http://localhost").searchParams.get("offset"))).toEqual(["1", "1"]);
    expect(region).toHaveAttribute("aria-busy", "true"); expect(vi.getTimerCount()).toBe(1);
    const obsolete = { ...fixture.next, list: { ...fixture.next.list, page: { ...fixture.next.list.page,
      items: fixture.next.list.page.items.map((row) => ({ ...row, pointer: "/punchlist/late-old" })) } } };
    await act(async () => resolveOld(json(obsolete)));
    expect(screen.queryByText("/punchlist/late-old", { exact: true })).toBeNull();
    expect(screen.getByText("/punchlist/7", { exact: true })).toBeInTheDocument();
    expect(region).toHaveAttribute("aria-busy", "true"); expect(retrySignal?.aborted).toBe(false);
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => resolveRetry(json(fixture.next)));
    expect(screen.getByText("/punchlist/93", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("/punchlist/7", { exact: true })).toBeNull();
    expect(region).toHaveAttribute("aria-busy", "false"); expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Next Findings page" })).toBeDisabled();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("aborts the in-flight page and clears its deadline when unmounted", async () => {
    vi.useFakeTimers();
    const fixture = pagingFixture();
    let resolve!: (value: Response) => void;
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise((done) => { resolve = done; }));
    const rendered = render(<NativeProjectionList title="Findings" document={fixture.document} initial={fixture.initial}
      renderRow={(row) => <p>{row.pointer}</p>} />);
    fireEvent.click(screen.getByRole("button", { name: "Next Findings page" }));
    expect(fetcher).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(1);
    const signal = fetcher.mock.calls[0][1]?.signal;
    expect(signal?.aborted).toBe(false);
    rendered.unmount(); expect(signal?.aborted).toBe(true); expect(vi.getTimerCount()).toBe(0);
    await act(async () => { vi.advanceTimersByTime(30_000); resolve(json(fixture.next)); });
    expect(rendered.container).toBeEmptyDOMElement(); expect(vi.getTimerCount()).toBe(0);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
