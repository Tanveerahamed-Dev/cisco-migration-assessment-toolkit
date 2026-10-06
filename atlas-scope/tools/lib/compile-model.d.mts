/**
 * Types for tools/lib/compile-model.mjs — the one compiler, which the phase-3 browser loader imports
 * under `tsc` strict. `src/core/compile-model.test.ts` requires this file to declare exactly the names
 * the module exports at runtime, and the model types are the app's own (src/core/types.ts), so a
 * compiled document and the UI that renders it are checked against one contract.
 */
import type {
  EvidenceBasis,
  EvidenceProjection,
  EvidenceRecord,
  EvidenceRefKind,
  EvidenceRefRole,
  Fabric,
  NameKeyed,
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

/** The engine contract (atlas-scope/contracts/engine-contract.v1.json), validated and frozen at load. */
export interface EngineContract {
  readonly schema: "atlas-engine-contract/1";
  readonly owner: string;
  readonly punchEvidence: {
    readonly kinds: readonly EvidenceRefKind[];
    readonly recordKinds: readonly EvidenceRefKind[];
    readonly roles: readonly EvidenceRefRole[];
    readonly bases: readonly EvidenceBasis[];
    readonly cap: number;
    readonly rules: Readonly<Record<string, boolean>>;
  };
  readonly protocolAssessabilityStates: readonly string[];
}
export declare const ENGINE_CONTRACT_SCHEMA: "atlas-engine-contract/1";
/** Validate a parsed engine contract; a malformed, missing or unknown piece throws E_ENGINE_CONTRACT. */
export declare function readEngineContract(c: unknown): EngineContract;
export declare const ENGINE_CONTRACT: EngineContract;
export declare const EVIDENCE_RECORD_KINDS: readonly EvidenceRefKind[];
export declare const EVIDENCE_REFS_CAP: number;
export declare const PROTOCOL_ASSESSABILITY_STATES: readonly string[];

export declare const SUPPORTED_SCHEMAS: readonly string[];
export declare const LEGACY_SCHEMA_ASSUMED: string;
export declare const SECTIONS_READ: readonly string[];
/** A route entry's prefix as the engine will read it (the trimmed text), or null when src/forwarding/ip.ts `parsePrefix` cannot read it. */
export declare function usableRoutePrefix(v: unknown): string | null;
/** Why one host's `routes` value is not a collected routing table (a list with an entry whose prefix the engine reads), or null when it is. */
export declare function unusableRouteTable(rs: unknown): string | null;
/** Why one entry of a usable routing table is left out (no prefix the engine can read), or null when it is a route. */
export declare function unreadableRouteEntry(r: unknown): string | null;
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
/** The bounds evidence records are projected under (characters of text); stated in `Fabric.evidenceProjection`. */
export declare const EVIDENCE_PROJECTION_CAPS: Readonly<{
  fieldTextChars: number;
  scalarTextChars: number;
  recordFields: number;
  recordChars: number;
  totalChars: number;
}>;
/** Project every record the findings' (already resolved) evidence pointers name, once per distinct pointer. */
export declare function compileEvidenceRecords(
  findings: readonly { priority?: number | null; evidenceRefs?: readonly { ref: string }[] | null }[],
  snap: unknown,
  caps?: typeof EVIDENCE_PROJECTION_CAPS,
): { records: EvidenceRecord[]; projection: EvidenceProjection };
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
  hosts: NameKeyed<AclBindingRecord[]>;
}
export interface RibEvidenceDocument {
  meta: SourceBinding & { routingProtocols: string[]; routingProtocolsFrom: string };
  hosts: NameKeyed<
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
  meta: SourceBinding & { aclLineFields: NameKeyed<string>; deviceHealthFields: NameKeyed<string> };
  aclLineAbsent: NameKeyed<string[]>;
  deviceAbsent: NameKeyed<string[]>;
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
