import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { published, topologyFixture, trustFixture } from "../test/projectionFixtures";
import type { ViewDocument } from "../projection";
import { useSnapshotTopology, useSnapshotTrust, type SnapshotTopologyRequest } from "./useSnapshotProjection";

const json = (value: unknown) => new Response(JSON.stringify(value));
function pendingResponse() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}
const request: SnapshotTopologyRequest = { snapshotId: 1, valid: true, source: null, sourceBytes: null };
const topology = () => topologyFixture() as unknown as ViewDocument<"topology">;
function replacementParent(kind: "source" | "engine"): ViewDocument<"topology"> {
  const document = topology();
  return kind === "source" ? { ...document, identity: { ...document.identity, sha256: `sha256:${"b".repeat(64)}`, bytes: 43 },
    engine: { ...document.engine, snapshot_sha256: { ...published(`sha256:${"b".repeat(64)}`), subject: null } as never, snapshot_bytes: { ...published(43), subject: null } as never } }
    : { ...document, engine: { ...document.engine, code_schema_version: "synthetic-replacement-engine" } };
}
function trustFor(parent: ViewDocument<"topology">, text: string) {
  const document = trustFixture(parent.identity.snapshot_id);
  return { ...document, identity: parent.identity, engine: parent.engine,
    payload: { ...document.payload, coverage_matrix: { ...document.payload.coverage_matrix, note: published(text) } } };
}

describe("Stable native snapshot projection hooks", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
  it("times out topology at 30 seconds, retries and ignores an old result without clearing the retry deadline", async () => {
    vi.useFakeTimers();
    const old = pendingResponse(), next = pendingResponse(), admitted = topology();
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => old.promise).mockImplementationOnce(() => next.promise);
    const rendered = renderHook(() => useSnapshotTopology(request));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(String(fetcher.mock.calls[0][0])).toBe("/api/snapshots/1/ui-projection/topology?limit=25");
    const oldSignal = fetcher.mock.calls[0][1]?.signal;
    await act(async () => { vi.advanceTimersByTime(29_999); });
    expect(oldSignal?.aborted).toBe(false); expect(rendered.result.current.error).toBeNull();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(oldSignal?.aborted).toBe(true); expect(rendered.result.current.document).toBeNull();
    expect(rendered.result.current.error).toBe("The Network request timed out. Retry snapshot.");
    act(() => rendered.result.current.retry());
    expect(fetcher).toHaveBeenCalledTimes(2); expect(fetcher.mock.calls[1][0]).toBe(fetcher.mock.calls[0][0]);
    expect(rendered.result.current.error).toBeNull(); expect(vi.getTimerCount()).toBe(1);
    await act(async () => old.resolve(json(admitted)));
    expect(rendered.result.current.document).toBeNull(); expect(vi.getTimerCount()).toBe(1);
    expect(fetcher.mock.calls[1][1]?.signal?.aborted).toBe(false);
    await act(async () => next.resolve(json(admitted)));
    expect(rendered.result.current.document).toEqual(admitted); expect(rendered.result.current.error).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("aborts topology on source-parameter replacement, ignores the old answer and admits the replacement bytes", async () => {
    const old = pendingResponse(), next = pendingResponse(), initial = topology(), replacement = replacementParent("source");
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => old.promise).mockImplementationOnce(() => next.promise);
    const first = { ...request, source: initial.identity.sha256, sourceBytes: String(initial.identity.bytes) };
    const second = { ...request, source: replacement.identity.sha256, sourceBytes: String(replacement.identity.bytes) };
    const rendered = renderHook((props: SnapshotTopologyRequest) => useSnapshotTopology(props), { initialProps: first });
    const oldSignal = fetcher.mock.calls[0][1]?.signal;
    rendered.rerender(second);
    expect(oldSignal?.aborted).toBe(true); expect(fetcher).toHaveBeenCalledTimes(2);
    expect(rendered.result.current.key).toBe(JSON.stringify([1, second.source, second.sourceBytes]));
    await act(async () => old.resolve(json(initial)));
    expect(rendered.result.current.document).toBeNull(); expect(rendered.result.current.error).toBeNull();
    await act(async () => next.resolve(json(replacement)));
    expect(rendered.result.current.document).toEqual(replacement); expect(rendered.result.current.error).toBeNull();
  });
  it.each(["source", "sourceBytes"] as const)("rejects an incomplete custody pair containing only %s", async (field) => {
    const answer = pendingResponse(), document = topology();
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(() => answer.promise);
    const input = { ...request, [field]: field === "source" ? document.identity.sha256 : String(document.identity.bytes) };
    const rendered = renderHook(() => useSnapshotTopology(input));
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => answer.resolve(json(document)));
    expect(rendered.result.current.document).toBeNull();
    expect(rendered.result.current.error).toBe("The referenced record belongs to a different stored snapshot. Select it again from Engagements.");
  });
  it("keeps source byte matching exact instead of normalising a noncanonical reference", async () => {
    const answer = pendingResponse(), document = topology();
    vi.spyOn(globalThis, "fetch").mockImplementation(() => answer.promise);
    const rendered = renderHook(() => useSnapshotTopology({ ...request, source: document.identity.sha256, sourceBytes: `0${document.identity.bytes}` }));
    await act(async () => answer.resolve(json(document)));
    expect(rendered.result.current.document).toBeNull(); expect(rendered.result.current.error).toContain("different stored snapshot");
  });
  it("does not request an invalid snapshot", () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    const rendered = renderHook(() => useSnapshotTopology({ ...request, valid: false }));
    expect(fetcher).not.toHaveBeenCalled(); expect(rendered.result.current.document).toBeNull();
    expect(rendered.result.current.error).toBe("Choose a valid stored snapshot from Engagements.");
  });
  it("times out trust, retries without a legacy fallback, and retains the retry deadline after the old answer settles", async () => {
    vi.useFakeTimers();
    const parent = topology(), old = pendingResponse(), next = pendingResponse(), admitted = trustFor(parent, "Current coverage");
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => old.promise).mockImplementationOnce(() => next.promise);
    const rendered = renderHook(() => useSnapshotTrust(parent));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(String(fetcher.mock.calls[0][0])).toBe("/api/snapshots/1/ui-projection/trust?limit=25");
    const oldSignal = fetcher.mock.calls[0][1]?.signal;
    await act(async () => { vi.advanceTimersByTime(29_999); });
    expect(oldSignal?.aborted).toBe(false); expect(rendered.result.current.error).toBe("");
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(oldSignal?.aborted).toBe(true); expect(rendered.result.current.document).toBeNull();
    expect(rendered.result.current.error).toBe("Coverage request timed out. Retry coverage.");
    act(() => rendered.result.current.retry());
    expect(fetcher).toHaveBeenCalledTimes(2); expect(fetcher.mock.calls[1][0]).toBe(fetcher.mock.calls[0][0]);
    expect(rendered.result.current.error).toBe(""); expect(vi.getTimerCount()).toBe(1);
    await act(async () => old.resolve(json(trustFor(parent, "Late old coverage"))));
    expect(rendered.result.current.document).toBeNull(); expect(vi.getTimerCount()).toBe(1);
    expect(fetcher.mock.calls[1][1]?.signal?.aborted).toBe(false);
    await act(async () => next.resolve(json(admitted)));
    expect(rendered.result.current.document).toEqual(admitted); expect(rendered.result.current.error).toBe("");
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(["source", "engine"] as const)("rejects a late trust response after parent %s changes, then admits the current parent response", async (kind) => {
    const original = topology(), replacement = replacementParent(kind), old = pendingResponse(), next = pendingResponse();
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => old.promise).mockImplementationOnce(() => next.promise);
    const rendered = renderHook((parent: ViewDocument<"topology">) => useSnapshotTrust(parent), { initialProps: original });
    const oldSignal = fetcher.mock.calls[0][1]?.signal;
    rendered.rerender(replacement);
    expect(oldSignal?.aborted).toBe(true); expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => old.resolve(json(trustFor(original, "Late original coverage"))));
    expect(rendered.result.current.document).toBeNull(); expect(rendered.result.current.error).toBe("");
    const admitted = trustFor(replacement, "Admitted replacement coverage");
    await act(async () => next.resolve(json(admitted)));
    expect(rendered.result.current.document).toEqual(admitted); expect(rendered.result.current.error).toBe("");
  });
  it.each(["source", "engine"] as const)("withholds already-loaded trust on the first render under a changed parent %s", async (kind) => {
    const original = topology(), replacement = replacementParent(kind), first = pendingResponse(), next = pendingResponse();
    vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => first.promise).mockImplementationOnce(() => next.promise);
    const observations: { parent: ViewDocument<"topology">; document: ViewDocument<"trust"> | null }[] = [];
    const rendered = renderHook((parent: ViewDocument<"topology">) => {
      const result = useSnapshotTrust(parent); observations.push({ parent, document: result.document }); return result;
    }, { initialProps: original });
    const initial = trustFor(original, "Original loaded coverage");
    await act(async () => first.resolve(json(initial)));
    expect(rendered.result.current.document).toEqual(initial);
    rendered.rerender(replacement);
    expect(observations.find((entry) => entry.parent === replacement)?.document).toBeNull();
    // The new request also refuses the old authority even if the server returns it again.
    await act(async () => next.resolve(json(initial)));
    expect(rendered.result.current.document).toBeNull();
    expect(rendered.result.current.error).toBe("Coverage belongs to a different snapshot context. Reload Network.");
  });
  it("admits trust-only limitations without replacing them with topology's registry", async () => {
    const parent = topology(), answer = pendingResponse();
    const caveat = { id: "trust_only", owner: "synthetic.trust.owner", text: "Synthetic coverage-only qualification", applies_to: ["/coverage_matrix/note"] };
    const document = { ...trustFor(parent, "Qualified coverage"), limitations: [caveat] };
    document.payload.coverage_matrix.note = { ...published("Qualified coverage"), caveats: [caveat.id] } as never;
    vi.spyOn(globalThis, "fetch").mockImplementation(() => answer.promise);
    const rendered = renderHook(() => useSnapshotTrust(parent));
    await act(async () => answer.resolve(json(document)));
    expect(rendered.result.current.error).toBe(""); expect(rendered.result.current.document).toEqual(document);
    expect(rendered.result.current.document?.limitations).toEqual([caveat]);
    expect(rendered.result.current.document?.payload.coverage_matrix.note.caveats).toEqual([caveat.id]);
    expect(parent.limitations).toEqual([]);
  });
});
