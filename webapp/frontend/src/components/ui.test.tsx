import { render, renderHook, screen, act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  Bars, CountUp, SegBar, SevChip, Skeleton, SkelLines, SkelTable, useAsync, usePositionTween,
  useToast, useViewTransition, type Pt,
} from "./ui";

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

  it("surfaces a toast, plays its exit at the display timeout, then clears after the exit duration", () => {
    const { result } = renderHook(() => useToast());
    expect(result.current.node).toBeNull(); // nothing initially
    act(() => result.current.toast("saved"));
    expect(result.current.node).not.toBeNull(); // shown
    expect(result.current.node?.props.className).toBe("toast"); // no exit class yet
    act(() => vi.advanceTimersByTime(2600));
    expect(result.current.node).not.toBeNull(); // still mounted — playing its exit
    expect(result.current.node?.props.className).toBe("toast out");
    act(() => vi.advanceTimersByTime(260));
    expect(result.current.node).toBeNull(); // cleared once the exit duration has elapsed
  });

  it("resets cleanly when a new toast interrupts one that is mid-exit", () => {
    const { result } = renderHook(() => useToast());
    act(() => result.current.toast("first"));
    act(() => vi.advanceTimersByTime(2600)); // first toast begins its exit
    expect(result.current.node?.props.className).toBe("toast out");
    act(() => result.current.toast("second")); // interrupts mid-exit
    expect(result.current.node?.props.className).toBe("toast"); // fully shown again, no stale exit class
    expect(result.current.node?.props.children).toBe("second");
    act(() => vi.advanceTimersByTime(260)); // the interrupted exit's own clear timer must not fire early
    expect(result.current.node).not.toBeNull();
    act(() => vi.advanceTimersByTime(2600 - 260));
    expect(result.current.node?.props.className).toBe("toast out"); // "second" now plays its own exit
    act(() => vi.advanceTimersByTime(260));
    expect(result.current.node).toBeNull();
  });
});

// Animated primitives are asserted on their STABLE final state, never a mid-tween frame —
// the same convention the page tests use around CountUp/Gauge.

describe("CountUp", () => {
  it("settles on the target value, and a retarget settles on the new target (no snap-back to 0)", async () => {
    const { rerender } = render(<CountUp value={100} duration={40} />);
    await waitFor(() => expect(screen.getByText("100")).toBeInTheDocument());
    // retarget: the tween must continue from the shown value and settle on the new target
    rerender(<CountUp value={50} duration={40} />);
    await waitFor(() => expect(screen.getByText("50")).toBeInTheDocument());
  });

  it("renders the honest dash for a non-finite value", () => {
    render(<CountUp value={NaN} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("useViewTransition", () => {
  it("applies the update synchronously where startViewTransition is unsupported (jsdom)", () => {
    const { result } = renderHook(() => useViewTransition());
    const update = vi.fn();
    act(() => result.current(update));
    expect(update).toHaveBeenCalledTimes(1); // fallback ran it inline, exactly once
  });
});

describe("usePositionTween", () => {
  const map = (o: Record<string, Pt>) => new Map(Object.entries(o));

  it("starts AT the targets (no fly-in) and a membership-only change adopts new ids at target", async () => {
    const a = map({ sw1: { x: 0, y: 0 } });
    const { result, rerender } = renderHook(({ m }) => usePositionTween(m, 40), { initialProps: { m: a } });
    expect(result.current.get("sw1")).toEqual({ x: 0, y: 0 }); // resting state = final state
    // add a node without moving the survivor: no tween, the new id appears at its target
    const b = map({ sw1: { x: 0, y: 0 }, sw2: { x: 9, y: 9 } });
    rerender({ m: b });
    await waitFor(() => expect(result.current.get("sw2")).toEqual({ x: 9, y: 9 }));
  });

  it("tweens a persisting id to its new target and drops vanished ids", async () => {
    const a = map({ sw1: { x: 0, y: 0 }, sw2: { x: 5, y: 5 } });
    const { result, rerender } = renderHook(({ m }) => usePositionTween(m, 40), { initialProps: { m: a } });
    const b = map({ sw1: { x: 100, y: 60 } }); // sw1 relocates, sw2 is filtered away
    rerender({ m: b });
    await waitFor(() => expect(result.current.get("sw1")).toEqual({ x: 100, y: 60 })); // settled
    expect(result.current.has("sw2")).toBe(false); // vanished id dropped, not tweened out
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

  // Out-of-order responses: the LAST-REQUESTED result must win, not the last-RESOLVED one. Two
  // requests are routinely in flight (NrfuPanel refires on `register`; reload() races a live fetch),
  // and an overlay POST that recomputes server-side is easily slower than the GET issued after it.
  // Ungenerationed, the superseded response wrote last and the panel showed data for requirements
  // the operator had already cleared — no error, no spinner.
  it("drops a SUPERSEDED response that resolves after the newer one", async () => {
    let releaseOld: (v: unknown) => void = () => {};
    const oldReq = new Promise((res) => { releaseOld = res; });
    const calls = [() => oldReq, () => Promise.resolve({ which: "new" })];
    let i = 0;
    const { result, rerender } = renderHook(({ dep }) => useAsync(() => calls[i++]() as Promise<any>, [dep]),
      { initialProps: { dep: 1 } });
    rerender({ dep: 2 });                                   // supersede the still-pending first request
    await waitFor(() => expect(result.current.data).toEqual({ which: "new" }));
    await act(async () => { releaseOld({ which: "old" }); await Promise.resolve(); });
    expect(result.current.data).toEqual({ which: "new" });  // the stale winner is refused
    expect(result.current.loading).toBe(false);
  });

  it("a SUPERSEDED rejection cannot blank the fresh data or clear its spinner", async () => {
    let failOld: (e: unknown) => void = () => {};
    const oldReq = new Promise((_res, rej) => { failOld = rej; });
    const calls = [() => oldReq, () => new Promise(() => {})];   // the new request stays in flight
    let i = 0;
    const { result, rerender } = renderHook(({ dep }) => useAsync(() => calls[i++]() as Promise<any>, [dep]),
      { initialProps: { dep: 1 } });
    rerender({ dep: 2 });
    await act(async () => { failOld(new Error("stale 500")); await Promise.resolve(); });
    expect(result.current.error).toBeNull();      // the dead request's failure is not the new one's
    expect(result.current.loading).toBe(true);    // ...and it must not end the live request's spinner
  });
});

// Structure-shaped loading placeholders (animation Unit 23). The sr-only "Loading…" announcement is
// the load-bearing contract — ArchReview.test.tsx and DesignBlueprint.test.tsx assert getByText(/Loading/i)
// against these presets with ZERO changes to those test files, so a single-match getByText must never
// throw on a duplicate announcer here. Assertions are on stable state only (counts, text), never a
// mid-shimmer frame.
describe("Skeleton", () => {
  it("announces the sr-only default text, and a custom label overrides it", () => {
    const { rerender } = render(<Skeleton />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    rerender(<Skeleton label="Building cable map…" />);
    expect(screen.getByText("Building cable map…")).toBeInTheDocument();
  });

  it("drops the sr-only child entirely when announce=false", () => {
    render(<Skeleton announce={false} />);
    expect(screen.queryByText(/Loading/i)).not.toBeInTheDocument();
  });

  it("always carries the skel + loading marker classes (Campaign.test.tsx's .spinner, .loading selector)", () => {
    const { container } = render(<Skeleton className="skel-h" />);
    expect(container.querySelector(".skel.loading.skel-h")).toBeTruthy();
  });
});

describe("SkelLines", () => {
  it("renders a heading bar + the default 4 body lines, announcing exactly once", () => {
    const { container } = render(<SkelLines />);
    expect(screen.getByText("Loading…")).toBeInTheDocument(); // single match: the body lines don't re-announce
    expect(container.querySelectorAll(".skel-line")).toHaveLength(4);
    expect(container.querySelectorAll(".skel-h")).toHaveLength(1);
  });

  it("honours an explicit n and forwards a custom label to its one announcer", () => {
    const { container } = render(<SkelLines n={7} label="Building topology…" />);
    expect(screen.getByText("Building topology…")).toBeInTheDocument();
    expect(container.querySelectorAll(".skel-line")).toHaveLength(7);
  });
});

describe("SkelTable", () => {
  it("renders a header row + rows x cols cell bars, announcing exactly once", () => {
    const { container } = render(<SkelTable rows={3} cols={4} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument(); // single match: only the first header cell announces
    expect(container.querySelectorAll(".skel-th")).toHaveLength(4);
    expect(container.querySelectorAll(".skel-td")).toHaveLength(12);
  });

  it("defaults to a 4x4 grid", () => {
    const { container } = render(<SkelTable />);
    expect(container.querySelectorAll(".skel-th")).toHaveLength(4);
    expect(container.querySelectorAll(".skel-td")).toHaveLength(16);
  });
});
