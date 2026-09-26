/**
 * source-binding.mjs — the ONE rule for binding a compiled file to the snapshot it was read from.
 *
 * Every `tools/compile-*.mjs` imports this module; none of them hashes the source itself.
 * `src/core/provenance.test.ts` enforces both halves by globbing tools/ (not by listing): every
 * compiler must import `./source-binding.mjs` and must not import `node:crypto`, and every
 * compiler must write byte-identical output from a CRLF and from an LF copy of the source.
 *
 * WHAT WAS WRONG (acceptance F5 / open-issues O15). Each compiler hashed `readFileSync(SRC)` — the
 * RAW bytes on disk. On this Windows host Git checks the snapshot out with CRLF line endings, so
 * the recorded digest (`9cc348bd…5dfd`, 3,148,592 bytes) was a digest of THIS host's working tree,
 * while the committed blob is LF (`9580aa09…3089`, 3,072,771 bytes). The binding the product
 * displays held on one disk and on no clone: a Linux checkout, or `git cat-file blob`, could not
 * reproduce it, and the same snapshot compiled on two hosts gave two "different" snapshots.
 *
 * THE CANONICAL FORM. The digest is taken over the LF-normalised bytes: every CR LF pair is read as
 * LF, byte-level, and nothing else is touched (a lone CR stays, no Unicode normalisation, no JSON
 * re-serialisation). That is exactly the conversion Git applies to a text blob on commit, so the
 * recorded `sourceSha256` equals `git cat-file blob HEAD:<source> | sha256sum`, and `sourceBytes`
 * equals `git cat-file -s`. It is independent of the checkout's line endings by construction.
 * `meta.sourceDigestForm` states the form, so a reader never has to guess which bytes are bound.
 *
 * Why the working-tree digest is NOT also recorded: it would differ between a CRLF and an LF
 * checkout, which would make the compiled files themselves differ between hosts — the very
 * non-reproducibility this module exists to remove. It is printed by the compiler instead.
 *
 * JSON semantics are unaffected: a JSON string cannot contain a raw CR or LF, so a CR LF pair can
 * only occur as insignificant whitespace between tokens, and the parsed value is the same either way.
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/** The snapshot every compiler reads, relative to the repository root (the package's parent). */
export const SOURCE_REL = "webapp/sample_data/sample_fleet.snapshot.json";

/** The name of the byte form the digest is taken over. Recorded in every compiled `meta`. */
export const SOURCE_DIGEST_FORM = "lf-normalised";

const CR = 0x0d;
const LF = 0x0a;

/**
 * The LF-normalised form: every CR LF pair becomes LF. Every other byte is copied unchanged.
 * @param {Buffer} raw
 * @returns {Buffer}
 */
export function lfNormalise(raw) {
  const out = Buffer.allocUnsafe(raw.length);
  let n = 0;
  for (let i = 0; i < raw.length; i += 1) {
    const b = /** @type {number} */ (raw[i]);
    if (b === CR && raw[i + 1] === LF) continue;
    out[n] = b;
    n += 1;
  }
  return out.subarray(0, n);
}

/** @param {Buffer} buf @returns {string} */
const sha256Hex = (buf) => createHash("sha256").update(buf).digest("hex");

/**
 * Read the snapshot the compiler in `toolsDir` resolves, and return its parsed value, the bytes that
 * bind, and the `meta` fields every compiled file carries.
 * @param {string} toolsDir  the directory of the calling compiler (`tools/`)
 */
export function readSource(toolsDir) {
  const path = resolve(toolsDir, "..", "..", SOURCE_REL);
  const raw = readFileSync(path);
  const canonical = lfNormalise(raw);
  /** @type {any} */
  const snap = JSON.parse(canonical.toString("utf8"));
  const binding = {
    source: SOURCE_REL,
    sourceDigestForm: SOURCE_DIGEST_FORM,
    sourceSha256: sha256Hex(canonical),
    sourceBytes: canonical.length,
  };
  return {
    path,
    snap,
    binding,
    /** For the compiler's console line only — never written into a compiled file (see above). */
    workingTree: { sha256: sha256Hex(raw), bytes: raw.length },
  };
}
