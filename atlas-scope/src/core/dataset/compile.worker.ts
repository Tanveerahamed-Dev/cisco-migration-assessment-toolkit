/**
 * dataset/compile.worker.ts — the compile runs OFF the main thread: validation and the one compiler take
 * a few hundred milliseconds on a reference-size snapshot, and the boot line (or the open-file dialog)
 * must stay responsive while they do. Everything it does is dataset/compile-request.ts.
 */
import { runCompileRequest, type CompileRequest } from "./compile-request";

const scope = self as unknown as {
  isSecureContext?: boolean;
  crypto?: Crypto;
  location?: { origin: string };
  onmessage: ((e: MessageEvent<CompileRequest>) => void) | null;
  postMessage(message: unknown): void;
};

/**
 * Whether a message can only have come from the page that started this worker. A DEDICATED worker has one
 * sender, its owner, whose messages arrive with the empty origin (they travel over the worker's own port);
 * this worker's own origin is accepted too, so an engine that stamps the owner's origin is not refused. Any
 * other origin is answered with a refusal, never compiled and never silently dropped (a dropped message
 * would leave the owner waiting forever).
 */
const fromOwner = (e: MessageEvent): boolean => e.origin === "" || e.origin === scope.location?.origin;

scope.onmessage = (e: MessageEvent<CompileRequest>): void => {
  if (!fromOwner(e)) {
    scope.postMessage({
      ok: false,
      errors: [{ code: "E_WORKER", message: `the compile worker refused a message from ${JSON.stringify(e.origin)}, which is not the page that started it` }],
      warnings: [],
    });
    return;
  }
  const subtle = scope.isSecureContext === true && scope.crypto?.subtle !== undefined ? scope.crypto.subtle : null;
  runCompileRequest(e.data, subtle).then(
    (outcome) => scope.postMessage(outcome),
    (err: unknown) =>
      scope.postMessage({
        ok: false,
        errors: [{ code: "E_WORKER", message: `the compile worker failed: ${err instanceof Error ? err.message : String(err)}` }],
        warnings: [],
      }),
  );
};
