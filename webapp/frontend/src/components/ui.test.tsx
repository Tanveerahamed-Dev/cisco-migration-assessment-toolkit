import { render, renderHook, screen, act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Bars, SegBar, SevChip, useAsync, useToast } from "./ui";

// The shared UI primitives carry real, reusable logic (zero-filtering, empty states, a data-load
// state machine, an auto-dismissing toast) used across every page. These pin that logic on the
// jsdom-safe surface — no three.js / WebGL is touched.

describe("SegBar", () => {
  it("drops zero-valued buckets and renders the surviving ones in the legend", () => {
    render(<SegBar data={{ Critical: 3, High: 0, Low: 2 }} colorFor={(k) => `c-${k}`} />);
    // legend shows the two non-zero buckets with their counts...
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();
    // ...and the zero bucket is filtered out entirely
    expect(screen.queryByText("High")).not.toBeInTheDocument();
  });
});

describe("Bars", () => {
  it("filters zeros and sizes each bar against the max", () => {
    const { container } = render(<Bars data={{ A: 10, B: 5, C: 0 }} />);
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.queryByText("C")).not.toBeInTheDocument(); // zero dropped
    const fills = container.querySelectorAll(".fill");
    expect(fills).toHaveLength(2);
    expect((fills[0] as HTMLElement).style.width).toBe("100%"); // A is the max -> full width
    expect((fills[1] as HTMLElement).style.width).toBe("50%"); // B is half of A
  });

  it("shows the honest empty state when every bucket is zero/absent", () => {
    render(<Bars data={{ X: 0 }} />);
    expect(screen.getByText("None.")).toBeInTheDocument();
  });
});

describe("SevChip", () => {
  it("squashes the severity into the CSS token and falls back to the sev as its label", () => {
    const { container } = render(<SevChip sev="High Risk" />);
    expect(screen.getByText("High Risk")).toBeInTheDocument(); // label ?? sev
    // the whitespace-squashed token drives the chip colour var
    expect(container.querySelector(".chip.sev")?.getAttribute("style")).toContain("--sev-HighRisk");
  });

  it("prefers an explicit label over the raw sev", () => {
    render(<SevChip sev="High Risk" label="HR" />);
    expect(screen.getByText("HR")).toBeInTheDocument();
    expect(screen.queryByText("High Risk")).not.toBeInTheDocument();
  });
});

describe("useToast", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("surfaces a toast node then auto-dismisses it after the timeout", () => {
    const { result } = renderHook(() => useToast());
    expect(result.current.node).toBeNull(); // nothing initially
    act(() => result.current.toast("saved"));
    expect(result.current.node).not.toBeNull(); // shown
    act(() => vi.advanceTimersByTime(2600));
    expect(result.current.node).toBeNull(); // auto-cleared
  });
});

describe("useAsync", () => {
  it("goes loading -> data on success", async () => {
    const { result } = renderHook(() => useAsync(() => Promise.resolve({ ok: 1 })));
    expect(result.current.loading).toBe(true); // starts loading, no data yet
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ ok: 1 });
    expect(result.current.error).toBeNull();
  });

  it("goes loading -> error message on rejection (never throws)", async () => {
    const { result } = renderHook(() => useAsync(() => Promise.reject(new Error("collection failed"))));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("collection failed");
    expect(result.current.data).toBeNull();
  });
});
