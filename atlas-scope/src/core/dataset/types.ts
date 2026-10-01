/**
 * dataset/types.ts — the shapes the dataset door speaks in. Types only: this module has no runtime
 * code, so the entry chunk can name these types without carrying anything.
 */
import type { CompiledSet } from "../../../tools/lib/compile-model.mjs";

/** The four compiled documents, exactly as the one compiler (tools/lib/compile-model.mjs `compileAll`) emits them. */
export type CompiledDataset = CompiledSet;

/** A coded, plain-language finding about a dataset the app was asked to load. */
export interface DatasetIssue {
  /** Stable machine code: the validator's (E_BOM, E_NOT_JSON, …), the compiler's (E_EMPTY_FABRIC, …), or this door's (E_HUB_*, E_FILE_*, E_STORE_*, E_WORKER). */
  code: string;
  /** One plain-language sentence a reader can act on. */
  message: string;
  /** The JSON Pointer (or snapshot path) of the value concerned, when there is one. */
  path?: string;
}

/** Where the loaded dataset came from — what the banner names. */
export type DatasetOrigin =
  | { kind: "bundled-sample" }
  | {
      kind: "opened-file";
      /** The file's own name, never a path (a browser File carries no directory). */
      fileName: string;
      /** The file's size as read, in bytes. */
      fileBytes: number;
      /** Non-blocking validator warnings, kept so the banner can say what the file lacked. */
      warnings: DatasetIssue[];
    }
  | {
      kind: "assesshub";
      /** The AssessHub store id, as it appears in /scope/snapshots/{id}/. */
      snapshotId: string;
      /**
       * `verified-in-browser`: this page recomputed sha256 over the bytes it received and it equals the
       * server's X-Snapshot-Sha256 (possible only in a secure context, where WebCrypto exists).
       * `server-attested`: the page could not recompute it (not a secure context); the digest shown is
       * the server's statement, not re-verified here.
       */
      verification: "verified-in-browser" | "server-attested";
      /** X-Snapshot-Sha256 as the server sent it (bare lowercase hex). */
      attestedSha256: string;
      /** X-Snapshot-Bytes as the server sent it; the body length was checked against it either way. */
      attestedBytes: number;
      warnings: DatasetIssue[];
    };

/** A dataset the runtime installed in place of the bundled one. */
export interface InstalledDataset {
  set: CompiledDataset;
  origin: Exclude<DatasetOrigin, { kind: "bundled-sample" }>;
}

/**
 * Something the reader must be told about the dataset that is NOT the dataset itself — today only a
 * snapshot opened earlier that could not be restored, so the page is showing the sample instead.
 */
export interface DatasetNotice {
  code: string;
  message: string;
}
