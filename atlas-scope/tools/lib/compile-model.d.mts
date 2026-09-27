/**
 * Types for tools/lib/compile-model.mjs — the one compiler, which the phase-3 browser loader imports
 * under `tsc` strict. `src/core/compile-model.test.ts` requires this file to declare exactly the names
 * the module exports at runtime, and the model types are the app's own (src/core/types.ts), so a
 * compiled document and the UI that renders it are checked against one contract.
 */
import type {
  EvidenceBasis,
  EvidenceRefKind,
  EvidenceRefRole,
  Fabric,
  SourceBinding,
  SourceDigestForm,
  SourceOrigin,
} from "../../src/core/types";

/** A refusal with a stable machine-readable code and the snapshot path it concerns. */
export declare class CompileError extends Error {
  constructor(code: string, message: string, path?: string | null, issues?: unknown[], options?: { cause?: unknown });
  code: string;
  path: string | null;
  issues: unknown[];
}

export declare const SUPPORTED_SCHEMAS: readonly string[];
export declare const LEGACY_SCHEMA_ASSUMED: string;
export declare const SECTIONS_READ: readonly string[];
export declare const META_KEYS_READ: readonly string[];
export declare const KNOWN_SECTION_SCHEMAS: Readonly<Record<string, readonly string[]>>;
export declare const DIGEST_FORMS: readonly SourceDigestForm[];
export declare const SOURCE_ORIGINS: readonly SourceOrigin[];
export declare const BINDING_KEYS: readonly (keyof SourceBinding)[];
export declare const PUNCHLIST_FIELDS: Readonly<Record<string, string>>;
export declare const EVIDENCE_REF_KINDS: readonly EvidenceRefKind[];
export declare const EVIDENCE_REF_ROLES: readonly EvidenceRefRole[];
export declare const EVIDENCE_BASES: readonly EvidenceBasis[];

/** Names a source. Never an absolute path: `bindSourceWith` refuses one (E_SOURCE_LABEL). */
export interface SourceLabel {
  source: string;
  sourceOrigin: SourceOrigin;
  sourceDigestForm?: SourceDigestForm;
}
export interface SyncHashes {
  sha256Hex(bytes: Uint8Array): string;
  sha1Hex(bytes: Uint8Array): string;
}
/** WebCrypto-shaped: the bytes handed over are always ArrayBuffer-backed, as crypto.subtle.digest requires. */
export interface AsyncHashes {
  sha256Hex(bytes: Uint8Array<ArrayBuffer>): string | Promise<string>;
  sha1Hex(bytes: Uint8Array<ArrayBuffer>): string | Promise<string>;
}

export declare function lfNormalise(raw: Uint8Array): Uint8Array<ArrayBuffer>;
export declare function gitBlobPreimage(content: Uint8Array): Uint8Array<ArrayBuffer>;
export declare function bindingPreimages(
  bytes: Uint8Array,
  label: Pick<SourceLabel, "sourceOrigin" | "sourceDigestForm">,
): { digested: Uint8Array<ArrayBuffer>; exact: Uint8Array<ArrayBuffer>; gitBlob: Uint8Array<ArrayBuffer> };
export declare function bindSourceWith(bytes: Uint8Array, label: SourceLabel, hashes: SyncHashes): SourceBinding;
export declare function bindSourceAsync(bytes: Uint8Array, label: SourceLabel, hashes: AsyncHashes): Promise<SourceBinding>;

export declare function parsePointer(pointer: unknown): string[] | null;
export declare function resolvePointer(doc: unknown, pointer: unknown): { ok: true; value: unknown } | { ok: false; reason: string };

/** One port's ACL binding, as src/forwarding/bindings.ts reads it. */
export interface AclBindingRecord {
  port: string;
  vlan: string | null;
  switchportMode: string | null;
  aclIn: string | null;
  aclOut: string | null;
  gateCandidates: string[];
  gateUnmodeled: string[];
  runConfigObserved: boolean;
  cite: string;
}
export interface AclBindingsDocument {
  meta: SourceBinding;
  hosts: Record<string, AclBindingRecord[]>;
}
export interface RibEvidenceDocument {
  meta: SourceBinding & { routingProtocols: string[]; routingProtocolsFrom: string };
  hosts: Record<
    string,
    {
      protocols: { protocol: string; state: string | null; reason: string | null; cite: string }[];
      adjacencies: {
        protocol: string;
        neighbor: string | null;
        state: string | null;
        cite: string;
        address: string | null;
        interface: string | null;
      }[];
      overlay: { kind: string; neighbor: string | null; state: string | null; prefixes: number | null; cite: string }[];
    }
  >;
}
export interface ProducerEmissionDocument {
  meta: SourceBinding & { aclLineFields: Record<string, string>; deviceHealthFields: Record<string, string> };
  aclLineAbsent: Record<string, string[]>;
  deviceAbsent: Record<string, string[]>;
}
export interface CompiledSet {
  fabric: Fabric;
  aclBindings: AclBindingsDocument;
  ribEvidence: RibEvidenceDocument;
  producerEmission: ProducerEmissionDocument;
}
export type OutputKey = keyof CompiledSet;
export interface CompileOptions {
  schemaAssumed?: string | null;
}

export declare function compileFabric(snap: Record<string, unknown>, binding: SourceBinding, opts?: CompileOptions): Fabric;
export declare function compileAclBindings(snap: Record<string, unknown>, binding: SourceBinding): AclBindingsDocument;
export declare function compileRibEvidence(snap: Record<string, unknown>, binding: SourceBinding): RibEvidenceDocument;
export declare function compileProducerEmission(snap: Record<string, unknown>, binding: SourceBinding): ProducerEmissionDocument;
export declare function compileAll(snap: Record<string, unknown>, binding: SourceBinding, opts?: CompileOptions): CompiledSet;

export declare const OUTPUTS: readonly { readonly key: OutputKey; readonly file: string; readonly trackedPath: string }[];
export declare function serialiseCompiled(set: CompiledSet): Record<OutputKey, string>;
