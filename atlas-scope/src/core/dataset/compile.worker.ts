/**
 * dataset/compile.worker.ts — the compile runs OFF the main thread: validation and the one compiler take
 * a few hundred milliseconds on a reference-size snapshot, and the boot line (or the open-file dialog)
 * must stay responsive while they do. Everything it does is dataset/compile-request.ts.
 */
import { runCompileRequest, type CompileRequest } from "./compile-request";

const scope = self as unknown as {
  isSecureContext?: boolean;
  crypto?: Crypto;
  onmessage: ((e: MessageEvent<CompileRequest>) => void) | null;
  postMessage(message: unknown): void;
};

scope.onmessage = (e: MessageEvent<CompileRequest>): void => {
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
