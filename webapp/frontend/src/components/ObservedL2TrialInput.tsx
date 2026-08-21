import { useRef, useState } from "react";
import type { L2FailureTrialInput, SnapshotMeta } from "../api";

const MAX_WITNESS_BYTES = 64 * 1024;

export interface ObservedL2TrialDraft {
  enabled: boolean;
  preFailureSnapshotId: number | "";
  postFailureSnapshotId: number | "";
  witnessJsonBase64: string;
  witnessFileName: string;
  witnessReadState: "empty" | "reading" | "ready" | "error";
}

export const EMPTY_OBSERVED_L2_TRIAL: ObservedL2TrialDraft = {
  enabled: false,
  preFailureSnapshotId: "",
  postFailureSnapshotId: "",
  witnessJsonBase64: "",
  witnessFileName: "",
  witnessReadState: "empty",
};

export function observedL2TrialIsReading(draft: ObservedL2TrialDraft): boolean {
  return draft.enabled && draft.witnessReadState === "reading";
}

export function observedL2TrialRequest(
  draft: ObservedL2TrialDraft,
  beforeSnapshotId: number | "",
  recoverySnapshotId: number | "",
): { input?: L2FailureTrialInput; error?: string } {
  if (!draft.enabled) return {};
  if (beforeSnapshotId === "" || recoverySnapshotId === "") {
    return { error: "Choose the comparison before and recovery snapshots first." };
  }
  if (draft.preFailureSnapshotId === "" || draft.postFailureSnapshotId === "") {
    return { error: "Choose both pre-failure and post-failure phase snapshots." };
  }
  if (draft.witnessReadState === "reading") {
    return { error: "Wait for the newly selected witness JSON file to finish loading." };
  }
  if (draft.witnessReadState !== "ready") {
    return { error: "Choose the exact observed-trial witness JSON file." };
  }
  if (!draft.witnessJsonBase64) {
    return { error: "Choose the exact observed-trial witness JSON file." };
  }
  const roles = [
    beforeSnapshotId,
    draft.preFailureSnapshotId,
    draft.postFailureSnapshotId,
    recoverySnapshotId,
  ];
  if (new Set(roles).size !== roles.length) {
    return {
      error: "Before, pre-failure, post-failure, and recovery must be four distinct snapshots.",
    };
  }
  return {
    input: {
      pre_failure_snapshot_id: draft.preFailureSnapshotId,
      post_failure_snapshot_id: draft.postFailureSnapshotId,
      witness_json_base64: draft.witnessJsonBase64,
    },
  };
}

async function exactFileBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

export default function ObservedL2TrialInput({
  draft,
  onChange,
  snapshots,
  beforeSnapshotId,
  recoverySnapshotId,
  disabled = false,
  idPrefix,
}: {
  draft: ObservedL2TrialDraft;
  onChange: (value: ObservedL2TrialDraft) => void;
  snapshots: SnapshotMeta[];
  beforeSnapshotId: number | "";
  recoverySnapshotId: number | "";
  disabled?: boolean;
  idPrefix: string;
}) {
  const [fileError, setFileError] = useState<string | null>(null);
  const readGeneration = useRef(0);
  const latestDraft = useRef(draft);
  latestDraft.current = draft;
  const recovery = snapshots.find((snapshot) => snapshot.id === recoverySnapshotId);
  const eligible = snapshots.filter((snapshot) => (
    snapshot.id !== beforeSnapshotId && snapshot.id !== recoverySnapshotId
  ));

  const chooseWitness = async (file?: File) => {
    const generation = ++readGeneration.current;
    setFileError(null);
    if (!file) {
      onChange({
        ...latestDraft.current,
        witnessJsonBase64: "",
        witnessFileName: "",
        witnessReadState: "empty",
      });
      return;
    }
    if (file.size === 0 || file.size > MAX_WITNESS_BYTES) {
      setFileError("Witness JSON must contain 1 to 65,536 exact bytes.");
      onChange({
        ...latestDraft.current,
        witnessJsonBase64: "",
        witnessFileName: "",
        witnessReadState: "error",
      });
      return;
    }
    // Invalidate the old bytes before starting the asynchronous read. The visible file control now
    // names `file`, so retaining the prior payload for even one render would let an immediate submit
    // bind the old witness to the newly selected file name.
    onChange({
      ...latestDraft.current,
      witnessJsonBase64: "",
      witnessFileName: file.name,
      witnessReadState: "reading",
    });
    try {
      const witnessJsonBase64 = await exactFileBase64(file);
      if (generation !== readGeneration.current) return;
      onChange({
        ...latestDraft.current,
        witnessJsonBase64,
        witnessFileName: file.name,
        witnessReadState: "ready",
      });
    } catch {
      if (generation !== readGeneration.current) return;
      setFileError("The witness file could not be read as exact bytes.");
      onChange({
        ...latestDraft.current,
        witnessJsonBase64: "",
        witnessFileName: file.name,
        witnessReadState: "error",
      });
    }
  };

  return (
    <details data-testid={`${idPrefix}-observed-l2-trial`} style={{ marginTop: 9 }}>
      <summary className="faint" style={{ cursor: "pointer", fontSize: 11.5 }}>
        Observed local L2 failure trial (advanced)
      </summary>
      <label className="row-flex" style={{ gap: 7, marginTop: 8, fontSize: 11.5 }}>
        <input
          type="checkbox"
          aria-label={`${idPrefix} include observed local L2 trial`}
          checked={draft.enabled}
          disabled={disabled}
          onChange={(event) => {
            if (!event.target.checked) {
              readGeneration.current += 1;
              setFileError(null);
            }
            onChange(event.target.checked
              ? { ...draft, enabled: true }
              : { ...EMPTY_OBSERVED_L2_TRIAL });
          }}
        />
        Include one source-bound STP, EtherChannel, or multichassis local failure trial
      </label>
      <div className="faint" style={{ fontSize: 10.5, margin: "6px 0" }}>
        Recovery is the selected comparison after snapshot
        {recovery ? ` (${recovery.label} · snapshot ${recovery.id})` : " (not selected)"}.
        The server re-reads all phase bytes and chronology. Witness bytes are operator context only;
        phase snapshots must independently prove the transition. This can establish only local safety
        preservation—never service survival, traffic continuity, or convergence.
      </div>
      {draft.enabled && (
        <div className="grid" style={{ gap: 7 }}>
          <label className="field">
            <span>Pre-failure snapshot (post-implementation current state)</span>
            <select
              aria-label={`${idPrefix} pre-failure snapshot`}
              value={draft.preFailureSnapshotId}
              disabled={disabled}
              onChange={(event) => onChange({
                ...draft,
                preFailureSnapshotId: event.target.value === ""
                  ? "" : Number(event.target.value),
              })}
            >
              <option value="">choose pre-failure phase…</option>
              {eligible.filter((snapshot) => snapshot.id !== draft.postFailureSnapshotId)
                .map((snapshot) => (
                  <option key={snapshot.id} value={snapshot.id}>
                    {snapshot.label} · snapshot {snapshot.id}
                  </option>
                ))}
            </select>
          </label>
          <label className="field">
            <span>Post-failure snapshot (induced failure still present)</span>
            <select
              aria-label={`${idPrefix} post-failure snapshot`}
              value={draft.postFailureSnapshotId}
              disabled={disabled}
              onChange={(event) => onChange({
                ...draft,
                postFailureSnapshotId: event.target.value === ""
                  ? "" : Number(event.target.value),
              })}
            >
              <option value="">choose post-failure phase…</option>
              {eligible.filter((snapshot) => snapshot.id !== draft.preFailureSnapshotId)
                .map((snapshot) => (
                  <option key={snapshot.id} value={snapshot.id}>
                    {snapshot.label} · snapshot {snapshot.id}
                  </option>
                ))}
            </select>
          </label>
          <label className="field">
            <span>Failure witness JSON (exact bytes, maximum 64 KiB)</span>
            <input
              type="file"
              accept=".json,application/json"
              aria-label={`${idPrefix} failure witness JSON`}
              disabled={disabled}
              onChange={(event) => void chooseWitness(event.target.files?.[0])}
            />
          </label>
          <div className="faint" data-testid={`${idPrefix}-observed-l2-witness-status`}
            style={{ fontSize: 10.5 }}>
            {fileError || (draft.witnessReadState === "reading"
              ? `Reading exact bytes: ${draft.witnessFileName}`
              : draft.witnessReadState === "ready" && draft.witnessFileName
                ? `Witness loaded: ${draft.witnessFileName}`
              : "Witness not loaded; the trial will remain unsubmitted.")}
          </div>
        </div>
      )}
    </details>
  );
}
