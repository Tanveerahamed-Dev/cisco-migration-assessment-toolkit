/**
 * source-binding.mjs — the ONE place a Node tool hashes snapshot bytes, and the name of the sample
 * snapshot the tracked compiled files are built from.
 *
 * Every `tools/compile-*.mjs` reaches this module through `tools/lib/compile-io.mjs`; no other file
 * under tools/ imports `node:crypto` or calls createHash. `src/core/provenance.test.ts` enforces both
 * halves structurally (it walks each compiler's import graph and scans every tools module), and every
 * compiler must write the same model from a CRLF and from an LF copy of the source — identical apart from
 * the byte-dependent binding key sourceExactSha256, which names the bytes each compile read.
 *
 * WHAT A BINDING IS — the rule itself lives in tools/lib/compile-model.mjs (`bindSourceWith`), which is
 * pure so a browser applies the SAME rule with WebCrypto; this module only supplies node:crypto:
 *
 *   sourceSha256 / sourceBytes / sourceDigestForm — the digest over the LF-NORMALISED bytes (every CR LF
 *     read as LF, byte-level, nothing else touched). That is the conversion Git applies to a text blob
 *     on commit, so the digest equals `git cat-file blob HEAD:<source> | sha256sum` and does not depend
 *     on the checkout's line endings. (Before O15 each compiler hashed the RAW bytes on disk — on this
 *     Windows host the CRLF working tree, `9cc348bd…5dfd` — a binding that held on one disk and on no
 *     clone.) Form "assesshub-store-blob" instead binds an AssessHub stored blob exactly.
 *   sourceExactSha256 — the ENGINE's binding form, `"sha256:" + sha256(<exact bytes>)`
 *     (cisco_toolkit/protocol_assurance.py `bind_snapshot_json_bytes`), so a compiled model joins an
 *     engine receipt by value. The exact bytes are the bytes AS READ, for every origin (a CRLF checkout
 *     of a repository file gives the CRLF digest): it is the one byte-dependent binding key, and a
 *     CRLF/LF compile-identity check compares the model with it excluded and checks it separately — see
 *     compile-model.mjs `bindingPreimages` and src/core/types.ts SOURCE_BINDING_BYTE_KEYS.
 *   sourceGitBlob — the Git blob id of the LF-normalised bytes (`git hash-object`; for an unmodified
 *     tracked source, `git rev-parse HEAD:<source>`), so "compiled from the tracked engine output" is a
 *     claim Git itself can check.
 *   source / sourceOrigin — WHICH file: a repository-relative path, or a bare file name for a file
 *     outside the repository. Never an absolute path (the home directory's username is a privacy marker).
 *
 * JSON semantics are unaffected by LF normalisation: a JSON string cannot contain a raw CR or LF, so a
 * CR LF pair can only occur as insignificant whitespace between tokens.
 */
import { createHash } from "node:crypto";
import { bindSourceWith, lfNormalise as lfNormaliseBytes } from "./lib/compile-model.mjs";

/** The sample snapshot the TRACKED compiled files are built from, relative to the repository root. */
export const SOURCE_REL = "webapp/sample_data/sample_fleet.snapshot.json";

/** The default byte form the digest is taken over. Recorded in every compiled `meta`. */
export const SOURCE_DIGEST_FORM = "lf-normalised";

/**
 * The LF-normalised form of `raw`, as a Buffer.
 * @param {Uint8Array} raw
 * @returns {Buffer}
 */
export function lfNormalise(raw) {
  const out = lfNormaliseBytes(raw);
  return Buffer.from(out.buffer, out.byteOffset, out.byteLength);
}

/** The hash functions the binding rule is applied with. */
export const NODE_HASHES = Object.freeze({
  /** @param {Uint8Array} b */
  sha256Hex: (b) => createHash("sha256").update(b).digest("hex"),
  /** @param {Uint8Array} b */
  sha1Hex: (b) => createHash("sha1").update(b).digest("hex"),
});

/**
 * Bind `bytes` under `label` (see the header for every field).
 * @param {Uint8Array} bytes
 * @param {import("./lib/compile-model.mjs").SourceLabel} label
 */
export function bindSource(bytes, label) {
  return bindSourceWith(bytes, label, NODE_HASHES);
}

/**
 * The raw working-tree digest — for a compiler's console line ONLY, never written into a compiled file
 * (it differs between a CRLF and an LF checkout, which is exactly what the binding must not).
 * @param {Uint8Array} raw
 */
export function workingTreeDigest(raw) {
  return { sha256: NODE_HASHES.sha256Hex(raw), bytes: raw.length };
}
