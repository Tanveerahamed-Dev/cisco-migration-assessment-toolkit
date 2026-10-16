import { useEffect, useState } from "react";
import { equalJson, loadProjection, sameIdentity, type ViewDocument } from "../projection";

export interface SnapshotTopologyRequest {
  snapshotId: number;
  valid: boolean;
  source: string | null;
  sourceBytes: string | null;
}

// Data custody and request lifecycle only. Navigation, selection and canvas layout
// stay with the workspace; changing a tab does not create another projection request.
export function useSnapshotTopology({ snapshotId, valid, source, sourceBytes }: SnapshotTopologyRequest): {
  key: string;
  document: ViewDocument<"topology"> | null;
  error: string | null;
  retry: () => void;
} {
  const key = JSON.stringify([snapshotId, source, sourceBytes]);
  const [result, setResult] = useState<{ key: string; document: ViewDocument<"topology"> } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setResult(null); setFailure(null);
    if (!valid) { setFailure({ key, message: "Choose a valid stored snapshot from Engagements." }); return () => controller.abort(); }
    const timeout = window.setTimeout(() => { controller.abort(); setFailure({ key, message: "The Network request timed out. Retry snapshot." }); }, 30_000);
    loadProjection(snapshotId, "topology", undefined, controller.signal).then((document) => {
      if ((source !== null || sourceBytes !== null) && (document.identity.sha256 !== source || String(document.identity.bytes) !== sourceBytes)) throw new Error("The referenced record belongs to a different stored snapshot. Select it again from Engagements.");
      if (!controller.signal.aborted) setResult({ key, document });
    }).catch((error: unknown) => { if (!controller.signal.aborted) setFailure({ key, message: error instanceof Error ? error.message : "Snapshot unavailable." }); }).finally(() => window.clearTimeout(timeout));
    return () => { controller.abort(); window.clearTimeout(timeout); };
  }, [snapshotId, key, valid, source, sourceBytes, retry]);
  return { key, document: result?.key === key ? result.document : null,
    error: failure?.key === key ? failure.message : null, retry: () => setRetry((value) => value + 1) };
}

// The trust response keeps its own limitation registry. Its complete stored identity
// and engine context must match the topology parent, including when returned to render.
export function useSnapshotTrust(parent: ViewDocument<"topology">): {
  document: ViewDocument<"trust"> | null;
  error: string;
  retry: () => void;
} {
  const [result, setResult] = useState<ViewDocument<"trust"> | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setResult(null); setError("");
    const timeout = window.setTimeout(() => { controller.abort(); setError("Coverage request timed out. Retry coverage."); }, 30_000);
    loadProjection(parent.identity.snapshot_id, "trust", undefined, controller.signal).then((next) => {
      if (!sameIdentity(parent.identity, next.identity) || !equalJson(parent.engine, next.engine)) throw new Error("Coverage belongs to a different snapshot context. Reload Network.");
      if (!controller.signal.aborted) setResult(next);
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Coverage unavailable."); }).finally(() => window.clearTimeout(timeout));
    return () => { controller.abort(); window.clearTimeout(timeout); };
  }, [parent, retry]);
  return { document: result && sameIdentity(parent.identity, result.identity) && equalJson(parent.engine, result.engine) ? result : null,
    error, retry: () => setRetry((value) => value + 1) };
}
