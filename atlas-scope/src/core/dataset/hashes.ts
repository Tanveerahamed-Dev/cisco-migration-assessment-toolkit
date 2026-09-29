/**
 * dataset/hashes.ts — the hash functions a runtime compile binds its source with.
 *
 * The one compiler hashes nothing itself (tools/lib/compile-model.mjs `bindSourceAsync` takes the
 * functions from its caller). In a SECURE CONTEXT (https, localhost, 127.0.0.1) the browser supplies
 * WebCrypto, and every digest is computed here over the bytes received. Outside one (AssessHub reached
 * over plain http by a host name) there is no `crypto.subtle` at all, and the owner's rule applies: the
 * page says "server-attested, not re-verified" rather than a verified mark. What the binding then records
 * as the sha256 IS the server's statement (X-Snapshot-Sha256), passed through, not a computation — which
 * is exactly what "attested" means. The Git blob id has no header to attest it, so it is computed with
 * the small SHA-1 below; it is an identifier the binding carries, not a verification of anything.
 */
import type { AsyncHashes } from "../../../tools/lib/compile-model.mjs";

const hex = (buf: ArrayBuffer): string => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

/** WebCrypto hashes (a secure context: window or worker). */
export function webCryptoHashes(subtle: SubtleCrypto): AsyncHashes {
  return {
    sha256Hex: async (b) => hex(await subtle.digest("SHA-256", b)),
    sha1Hex: async (b) => hex(await subtle.digest("SHA-1", b)),
  };
}

/**
 * Hashes for a page that cannot compute sha256: the sha256 of the (store-form) bytes is the server's
 * attested value, returned as stated. Only valid for an AssessHub stored blob, whose digested bytes and
 * exact bytes are the same bytes (compile-model.mjs `bindingPreimages`, form "assesshub-store-blob").
 */
export function attestedHashes(attestedSha256: string): AsyncHashes {
  return { sha256Hex: () => attestedSha256, sha1Hex: (b) => sha1Hex(b) };
}

/** SHA-1 (FIPS 180-4), hex. Used only for the Git blob id where WebCrypto does not exist. */
export function sha1Hex(bytes: Uint8Array): string {
  const len = bytes.length;
  const words = ((len + 8) >>> 6) + 1;
  const w = new Uint32Array(words * 16);
  for (let i = 0; i < len; i += 1) w[i >>> 2]! |= bytes[i]! << (24 - (i % 4) * 8);
  w[len >>> 2]! |= 0x80 << (24 - (len % 4) * 8);
  const bits = len * 8;
  w[words * 16 - 1] = bits >>> 0;
  w[words * 16 - 2] = Math.floor(bits / 0x100000000) >>> 0;
  let h0 = 0x67452301;
  let h1 = 0xefcdab89;
  let h2 = 0x98badcfe;
  let h3 = 0x10325476;
  let h4 = 0xc3d2e1f0;
  const m = new Uint32Array(80);
  const rotl = (x: number, n: number): number => (x << n) | (x >>> (32 - n));
  for (let blk = 0; blk < words * 16; blk += 16) {
    for (let t = 0; t < 16; t += 1) m[t] = w[blk + t]!;
    for (let t = 16; t < 80; t += 1) m[t] = rotl(m[t - 3]! ^ m[t - 8]! ^ m[t - 14]! ^ m[t - 16]!, 1);
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    for (let t = 0; t < 80; t += 1) {
      const f = t < 20 ? (b & c) | (~b & d) : t < 40 ? b ^ c ^ d : t < 60 ? (b & c) | (b & d) | (c & d) : b ^ c ^ d;
      const k = t < 20 ? 0x5a827999 : t < 40 ? 0x6ed9eba1 : t < 60 ? 0x8f1bbcdc : 0xca62c1d6;
      const tmp = (rotl(a, 5) + f + e + k + m[t]!) >>> 0;
      e = d;
      d = c;
      c = rotl(b, 30) >>> 0;
      b = a;
      a = tmp;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
  }
  return [h0, h1, h2, h3, h4].map((x) => x.toString(16).padStart(8, "0")).join("");
}
