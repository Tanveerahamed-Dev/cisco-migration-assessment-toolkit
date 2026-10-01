/**
 * dataset/compile-request.ts — bytes in, a compiled dataset (or coded refusals) out, with the ONE
 * compiler. This is what the compile worker runs (dataset/compile.worker.ts is a thin message wrapper
 * around it), kept separate so a test can run exactly the same code without a Worker.
 *
 * Steps, each a refusal with a stable code when it fails:
 *   1. the byte count equals what the source stated (AssessHub's X-Snapshot-Bytes) — E_HUB_BYTES_MISMATCH;
 *   2. when the page can hash (WebCrypto) and the source stated a digest, sha256 over the bytes equals
 *      it — E_HUB_DIGEST_MISMATCH. When it cannot hash, the result says `server-attested`, never verified;
 *   3. tools/lib/validate-snapshot.mjs `validateSnapshot` — every E_* it returns, verbatim;
 *   4. tools/lib/compile-model.mjs `bindSourceAsync` + `compileAll` — a CompileError keeps its code.
 */
import { bindSourceAsync, CompileError, compileAll, type SourceLabel } from "../../../tools/lib/compile-model.mjs";
import { validateSnapshot } from "../../../tools/lib/validate-snapshot.mjs";
import { attestedHashes, webCryptoHashes } from "./hashes";
import type { CompiledDataset, DatasetIssue } from "./types";

export interface CompileRequest {
  bytes: ArrayBuffer;
  label: SourceLabel;
  /** What the source stated about the bytes (AssessHub's headers); null for a file the reader opened. */
  expect: { sha256: string; bytes: number } | null;
}

export type CompileOutcome =
  | { ok: true; set: CompiledDataset; warnings: DatasetIssue[]; verification: "computed" | "verified-in-browser" | "server-attested" }
  | { ok: false; errors: DatasetIssue[]; warnings: DatasetIssue[] };

const issue = (code: string, message: string, path?: string | null): DatasetIssue => (path ? { code, message, path } : { code, message });

/**
 * Run one compile. `subtle` is WebCrypto where the context has it (a secure context), null where it does
 * not — then only a stated digest can be carried, as the server's statement.
 */
export async function runCompileRequest(req: CompileRequest, subtle: SubtleCrypto | null): Promise<CompileOutcome> {
  const bytes = new Uint8Array(req.bytes);
  const fail = (...errors: DatasetIssue[]): CompileOutcome => ({ ok: false, errors, warnings: [] });

  let verification: "computed" | "verified-in-browser" | "server-attested" = "computed";
  if (req.expect !== null) {
    if (bytes.length !== req.expect.bytes) {
      return fail(
        issue(
          "E_HUB_BYTES_MISMATCH",
          `the snapshot arrived as ${bytes.length} bytes, but the server stated ${req.expect.bytes}. The transfer was cut short or altered, so nothing was shown. Reload the page.`,
        ),
      );
    }
    if (subtle !== null) {
      const got = [...new Uint8Array(await subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
      if (got !== req.expect.sha256) {
        return fail(
          issue(
            "E_HUB_DIGEST_MISMATCH",
            `the snapshot's sha256 computed in this browser (${got.slice(0, 12)}…) is not the one the server stated (${req.expect.sha256.slice(0, 12)}…). ` +
              "The bytes are not the stored snapshot, so nothing was shown.",
          ),
        );
      }
      verification = "verified-in-browser";
    } else {
      verification = "server-attested";
    }
  } else if (subtle === null) {
    return fail(
      issue(
        "E_NO_WEBCRYPTO",
        "this page is not a secure context (https or localhost), so the browser offers no way to compute the file's sha256, and a file with no computed digest cannot be bound. Open Atlas Scope from localhost or over https.",
      ),
    );
  }

  const v = validateSnapshot(bytes);
  const warnings: DatasetIssue[] = v.warnings.map((w) => issue(w.code, w.message, w.path));
  if (!v.ok || v.snap === null) return { ok: false, errors: v.errors.map((e) => issue(e.code, e.message, e.path)), warnings };

  try {
    const hashes = subtle !== null ? webCryptoHashes(subtle) : attestedHashes(req.expect!.sha256);
    const binding = await bindSourceAsync(bytes, req.label, hashes);
    const set = compileAll(v.snap, binding, { schemaAssumed: v.schemaAssumed });
    return { ok: true, set, warnings, verification };
  } catch (e) {
    if (e instanceof CompileError) return { ok: false, errors: [issue(e.code, e.message, e.path)], warnings };
    return { ok: false, errors: [issue("E_COMPILE", `the compiler failed on this snapshot: ${e instanceof Error ? e.message : String(e)}`)], warnings };
  }
}
