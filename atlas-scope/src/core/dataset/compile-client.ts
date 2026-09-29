/**
 * dataset/compile-client.ts — run one compile request in a dedicated module worker and resolve with its
 * outcome. A worker that cannot start, errors, or answers with something that is not an outcome is a
 * coded refusal (E_WORKER), never a hang: the caller's boot line or dialog must always resolve.
 */
import type { CompileOutcome, CompileRequest } from "./compile-request";

export type CompileFn = (req: CompileRequest) => Promise<CompileOutcome>;

const workerFailure = (why: string): CompileOutcome => ({
  ok: false,
  errors: [{ code: "E_WORKER", message: `the snapshot could not be compiled in this browser: ${why}. Reload the page; if it fails again, the build is incomplete.` }],
  warnings: [],
});

/** Compile in a worker. The request's bytes are transferred (not copied) to it. */
export const compileInWorker: CompileFn = (req) =>
  new Promise<CompileOutcome>((resolve) => {
    let worker: Worker;
    try {
      worker = new Worker(new URL("./compile.worker.ts", import.meta.url), { type: "module", name: "atlas-scope-compile" });
    } catch (e) {
      resolve(workerFailure(`the compile worker could not start (${e instanceof Error ? e.message : String(e)})`));
      return;
    }
    const done = (o: CompileOutcome): void => {
      worker.terminate();
      resolve(o);
    };
    worker.onmessage = (e: MessageEvent<unknown>): void => {
      const o = e.data as Partial<CompileOutcome> | null;
      if (o === null || typeof o !== "object" || typeof o.ok !== "boolean") done(workerFailure("the compile worker answered with something that is not a result"));
      else done(o as CompileOutcome);
    };
    worker.onerror = (e: ErrorEvent): void => {
      e.preventDefault();
      done(workerFailure(`the compile worker failed (${e.message || "no message"})`));
    };
    worker.onmessageerror = (): void => done(workerFailure("the compile worker's result could not be read"));
    worker.postMessage(req, [req.bytes]);
  });
