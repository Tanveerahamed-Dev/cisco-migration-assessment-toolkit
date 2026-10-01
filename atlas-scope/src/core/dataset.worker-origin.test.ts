// @vitest-environment node
/**
 * dataset.worker-origin.test.ts — the compile worker compiles only what its owner sends, and ANSWERS everything else.
 *
 * c199e0f9 gave dataset/compile.worker.ts an origin guard (CodeQL js/missing-origin-check): a dedicated worker's
 * owner posts over the worker's own port, so its messages arrive with the empty origin (the worker's own origin is
 * accepted too); a message from any other origin is refused with an E_WORKER outcome — never compiled, and never
 * dropped silently, because a dropped message leaves the owner waiting forever. That guard had no test.
 *
 * The REAL worker module runs here, with no module replaced: `self` is swapped for a stand-in scope before the
 * worker is imported (it binds `self` when evaluated). The owner's message is the tracked sample's bytes, so
 * "accepted" means compiled. A foreign message carries bytes that are not JSON: had the worker compiled it, the
 * validator's refusal would be posted within microtasks — long before the owner's compile (which awaits WebCrypto
 * digests) answers — so "never compiled" is read from what was posted, not from a mock.
 */
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CompileOutcome, CompileRequest } from "./dataset/compile-request";
import { SAMPLE_SNAPSHOT } from "../test-support/dataset/testing";

const WORKER_ORIGIN = "http://localhost:4181";

interface Scope {
  isSecureContext: boolean;
  crypto: Crypto;
  location: { origin: string };
  onmessage: ((e: MessageEvent<CompileRequest>) => void) | null;
  postMessage: (message: unknown) => void;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

/** The real worker, bound to a stand-in scope, and every message it posts. */
async function startWorker(): Promise<{ scope: Scope; posted: CompileOutcome[] }> {
  const posted: CompileOutcome[] = [];
  const scope: Scope = {
    isSecureContext: true,
    crypto: globalThis.crypto,
    location: { origin: WORKER_ORIGIN },
    onmessage: null,
    postMessage: (m) => {
      posted.push(m as CompileOutcome);
    },
  };
  vi.resetModules();
  vi.stubGlobal("self", scope);
  await import("./dataset/compile.worker");
  expect(scope.onmessage, "the worker installed no message handler").toBeTypeOf("function");
  return { scope, posted };
}

const label = { source: "snapshot.json", sourceOrigin: "external-file" } as const;
const sampleRequest = (): CompileRequest => {
  const b = readFileSync(SAMPLE_SNAPSHOT);
  return { bytes: b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer, label, expect: null };
};
/** Bytes the validator refuses at once (not JSON) — what a compile of a foreign message would visibly post. */
const notJsonRequest = (): CompileRequest => ({ bytes: new TextEncoder().encode("{ not json").buffer as ArrayBuffer, label, expect: null });
const send = (scope: Scope, origin: string, data: CompileRequest): void => {
  scope.onmessage?.({ origin, data } as MessageEvent<CompileRequest>);
};
/** The next message the worker posts (the compile is asynchronous). */
async function nextPosted(posted: CompileOutcome[], after: number): Promise<CompileOutcome> {
  await vi.waitFor(() => expect(posted.length).toBeGreaterThan(after), { timeout: 30_000, interval: 20 });
  return posted[after]!;
}
const codes = (o: CompileOutcome | undefined): string[] => (o === undefined || o.ok ? [] : o.errors.map((e) => e.code));

describe("the compile worker's origin guard", () => {
  it('compiles a message from its owner (origin "")', async () => {
    const { scope, posted } = await startWorker();
    send(scope, "", sampleRequest());
    const outcome = await nextPosted(posted, 0);
    expect(outcome.ok, JSON.stringify(outcome).slice(0, 300)).toBe(true);
    if (outcome.ok) expect(outcome.set.fabric.devices.length).toBeGreaterThan(0);
    expect(posted).toHaveLength(1);
  }, 60_000);

  it("compiles a message stamped with the worker's own origin", async () => {
    const { scope, posted } = await startWorker();
    send(scope, WORKER_ORIGIN, sampleRequest());
    expect((await nextPosted(posted, 0)).ok).toBe(true);
  }, 60_000);

  it("control: a not-JSON message from the owner IS compiled, and its refusal is the validator's, not E_WORKER", async () => {
    const { scope, posted } = await startWorker();
    send(scope, "", notJsonRequest());
    const outcome = await nextPosted(posted, 0);
    expect(outcome.ok).toBe(false);
    expect(codes(outcome).length).toBeGreaterThan(0);
    expect(codes(outcome)).not.toContain("E_WORKER");
  }, 60_000);

  it.each([["https://attacker.example"], ["null"], ["http://localhost:4182"]])(
    "refuses a message from %s with E_WORKER — answered at once, never compiled, never dropped",
    async (origin) => {
      const { scope, posted } = await startWorker();
      send(scope, origin, notJsonRequest());
      /* Answered synchronously, before anything asynchronous could run: the refusal is not a late compile failure. */
      expect(posted).toHaveLength(1);
      const refusal = posted[0];
      expect(refusal?.ok).toBe(false);
      expect(codes(refusal)).toEqual(["E_WORKER"]);
      if (refusal !== undefined && !refusal.ok) {
        expect(refusal.errors[0]?.message).toContain(JSON.stringify(origin));
        expect(refusal.warnings).toEqual([]);
      }
      /* The worker still serves its owner afterwards — and by the time the owner's compile answers, a compile of the
         foreign bytes would have posted its validator refusal: nothing but the owner's outcome may follow. */
      send(scope, "", sampleRequest());
      expect((await nextPosted(posted, 1)).ok).toBe(true);
      expect(posted.map((o) => (o.ok ? "ok" : codes(o).join(",")))).toEqual(["E_WORKER", "ok"]);
    },
    60_000,
  );
});
