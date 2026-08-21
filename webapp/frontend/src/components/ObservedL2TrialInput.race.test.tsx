import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { SnapshotMeta } from "../api";
import ObservedL2TrialInput, {
  EMPTY_OBSERVED_L2_TRIAL,
  observedL2TrialRequest,
} from "./ObservedL2TrialInput";
import type { ObservedL2TrialDraft } from "./ObservedL2TrialInput";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function fileWithRead(name: string, read: Promise<ArrayBuffer>): File {
  const file = new File([new Uint8Array([1])], name, { type: "application/json" });
  Object.defineProperty(file, "arrayBuffer", {
    configurable: true,
    value: vi.fn(() => read),
  });
  return file;
}

const snapshots = [1, 2, 3, 4].map((id) => ({
  id,
  campaign_id: 7,
  label: `snapshot-${id}`,
  uploaded_at: `2026-08-20T01:0${id}:00Z`,
  n_devices: 1,
  summary: {},
})) as SnapshotMeta[];

function Harness() {
  const [draft, setDraft] = useState<ObservedL2TrialDraft>({
    ...EMPTY_OBSERVED_L2_TRIAL,
    enabled: true,
    preFailureSnapshotId: 2,
    postFailureSnapshotId: 3,
  });
  const result = observedL2TrialRequest(draft, 1, 4);
  return (
    <>
      <ObservedL2TrialInput
        idPrefix="race"
        draft={draft}
        onChange={setDraft}
        snapshots={snapshots}
        beforeSnapshotId={1}
        recoverySnapshotId={4}
      />
      <div data-testid="request-result">
        {result.error || result.input?.witness_json_base64 || "omitted"}
      </div>
    </>
  );
}

describe("ObservedL2TrialInput exact-byte read authority", () => {
  it("clears A synchronously and refuses submission while selected B is pending", async () => {
    const a = deferred<ArrayBuffer>();
    const b = deferred<ArrayBuffer>();
    render(<Harness />);
    const input = screen.getByLabelText("race failure witness JSON");

    fireEvent.change(input, { target: { files: [fileWithRead("a.json", a.promise)] } });
    a.resolve(Uint8Array.from([65]).buffer);
    await waitFor(() => expect(screen.getByTestId("request-result")).toHaveTextContent("QQ=="));

    fireEvent.change(input, { target: { files: [fileWithRead("b.json", b.promise)] } });
    expect(screen.getByTestId("request-result")).toHaveTextContent(/finish loading/i);
    expect(screen.getByTestId("request-result")).not.toHaveTextContent("QQ==");

    b.resolve(Uint8Array.from([66]).buffer);
    await waitFor(() => expect(screen.getByTestId("request-result")).toHaveTextContent("Qg=="));
  });

  it("ignores a slow stale A read after a later B read becomes authoritative", async () => {
    const a = deferred<ArrayBuffer>();
    const b = deferred<ArrayBuffer>();
    render(<Harness />);
    const input = screen.getByLabelText("race failure witness JSON");

    fireEvent.change(input, { target: { files: [fileWithRead("a.json", a.promise)] } });
    fireEvent.change(input, { target: { files: [fileWithRead("b.json", b.promise)] } });
    b.resolve(Uint8Array.from([66]).buffer);
    await waitFor(() => expect(screen.getByTestId("request-result")).toHaveTextContent("Qg=="));

    a.resolve(Uint8Array.from([65]).buffer);
    await Promise.resolve();
    expect(screen.getByTestId("request-result")).toHaveTextContent("Qg==");
    expect(screen.getByTestId("race-observed-l2-witness-status")).toHaveTextContent(
      "Witness loaded: b.json",
    );
  });
});
