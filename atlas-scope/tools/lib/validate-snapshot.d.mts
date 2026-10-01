/**
 * Types for tools/lib/validate-snapshot.mjs (pure; the phase-3 browser loader runs it on a file a user
 * opens). `src/core/compile-model.test.ts` requires this file to declare exactly the runtime exports.
 */

/** One coded finding about the input: an error (E_*) blocks, a warning (W_*) never does. */
export interface Issue {
  code: string;
  message: string;
  /** RFC 6901 JSON Pointer of the value concerned, when there is one. */
  path?: string;
  offset?: number;
  line?: number;
  column?: number;
  snippet?: string;
}
export interface ValidateOptions {
  allowLegacy?: boolean;
  maxBytes?: number;
}
export interface ValidationResult {
  ok: boolean;
  errors: Issue[];
  warnings: Issue[];
  snap: Record<string, unknown> | null;
  schemaAssumed: string | null;
}

export declare const DEFAULT_MAX_SNAPSHOT_BYTES: number;
export declare const CORE_SECTIONS: readonly string[];
export declare const CORE_SECTIONS_REQUIRED: number;
export declare function validateSnapshot(bytes: Uint8Array, opts?: ValidateOptions): ValidationResult;
export declare function assertValidSnapshot(
  bytes: Uint8Array,
  opts?: ValidateOptions,
): { snap: Record<string, unknown>; warnings: Issue[]; schemaAssumed: string | null };
