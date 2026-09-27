/**
 * Types for tools/source-binding.mjs — the one Node module that hashes snapshot bytes.
 * `src/core/compile-model.test.ts` requires this file to declare exactly the runtime exports.
 */
import type { SourceBinding } from "../src/core/types";
import type { SourceLabel, SyncHashes } from "./lib/compile-model.mjs";

export declare const SOURCE_REL: string;
export declare const SOURCE_DIGEST_FORM: string;
export declare const NODE_HASHES: Readonly<SyncHashes>;
export declare function lfNormalise(raw: Uint8Array): Buffer;
export declare function bindSource(bytes: Uint8Array, label: SourceLabel): SourceBinding;
export declare function workingTreeDigest(raw: Uint8Array): { sha256: string; bytes: number };
