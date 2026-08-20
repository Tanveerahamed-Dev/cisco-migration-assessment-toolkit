import { promisify } from "node:util";
import { constants, crc32, deflateRaw, inflateRaw } from "node:zlib";

import { CANONICAL_GZIP_HEADER_BYTES } from "./gzip-contract.js";

const deflateRawAsync = promisify(deflateRaw);
const inflateRawAsync = promisify(inflateRaw);
const CANONICAL_HEADER = Buffer.from(CANONICAL_GZIP_HEADER_BYTES);

export const RECEIPT_BOUND_GZIP_ALGORITHM =
  "gzip:deflate-raw:level-9:memlevel-8:strategy-filtered:mtime-0:os-255";

export async function deterministicGzip(original) {
  if (!Buffer.isBuffer(original)) {
    throw new Error("deterministic gzip input must be bytes");
  }
  const input = Buffer.from(original);
  let deflated;
  try {
    deflated = await deflateRawAsync(input, {
      level: constants.Z_BEST_COMPRESSION,
      memLevel: 8,
      strategy: constants.Z_FILTERED,
    });
  } catch {
    throw new Error("deterministic gzip compression failed");
  }
  const trailer = Buffer.alloc(8);
  trailer.writeUInt32LE(crc32(input) >>> 0, 0);
  trailer.writeUInt32LE(input.byteLength >>> 0, 4);
  return Buffer.concat([CANONICAL_HEADER, deflated, trailer]);
}

async function expandReceiptBoundGzipUnsafe(
  representation,
  options,
) {
  if (
    !options ||
    typeof options !== "object" ||
    Object.getPrototypeOf(options) !== Object.prototype
  ) {
    throw new Error("invalid options");
  }
  const keys = Reflect.ownKeys(options);
  if (
    keys.length !== 3 ||
    !keys.every((key) => typeof key === "string") ||
    !["label", "maximumCompressedBytes", "maximumExpandedBytes"].every(
      (key) => keys.includes(key),
    )
  ) {
    throw new Error("invalid options");
  }
  const descriptors = Object.getOwnPropertyDescriptors(options);
  if (
    Object.values(descriptors).some(
      (descriptor) =>
        !("value" in descriptor) ||
        descriptor.get ||
        descriptor.set ||
        descriptor.enumerable !== true,
    )
  ) {
    throw new Error("invalid options");
  }
  const label = descriptors.label.value;
  const maximumCompressedBytes = descriptors.maximumCompressedBytes.value;
  const maximumExpandedBytes = descriptors.maximumExpandedBytes.value;
  if (
    !Buffer.isBuffer(representation) ||
    typeof label !== "string" ||
    !label ||
    !Number.isSafeInteger(maximumCompressedBytes) ||
    maximumCompressedBytes < CANONICAL_HEADER.byteLength + 8 ||
    !Number.isSafeInteger(maximumExpandedBytes) ||
    maximumExpandedBytes < 0
  ) {
    throw new Error("receipt-bound gzip verifier configuration is invalid");
  }
  if (representation.byteLength > maximumCompressedBytes) {
    throw new Error(`${label} exceeds the bounded gzip representation limit`);
  }
  if (
    representation.byteLength < CANONICAL_HEADER.byteLength + 8 ||
    !representation.subarray(0, CANONICAL_HEADER.byteLength).equals(CANONICAL_HEADER)
  ) {
    throw new Error(`${label} does not have the fixed gzip header`);
  }
  let result;
  try {
    result = await inflateRawAsync(
      representation.subarray(CANONICAL_HEADER.byteLength),
      { info: true, maxOutputLength: maximumExpandedBytes },
    );
  } catch {
    throw new Error(`${label} cannot be bounded-gunzipped`);
  }
  const expanded = result?.buffer;
  const deflateBytes = result?.engine?.bytesWritten;
  if (
    !Buffer.isBuffer(expanded) ||
    !Number.isSafeInteger(deflateBytes) ||
    deflateBytes < 1
  ) {
    throw new Error(`${label} cannot be bounded-gunzipped`);
  }
  if (expanded.byteLength > maximumExpandedBytes) {
    throw new Error(`${label} exceeds the bounded expanded-byte limit`);
  }
  const trailerOffset = CANONICAL_HEADER.byteLength + deflateBytes;
  if (trailerOffset + 8 !== representation.byteLength) {
    throw new Error(`${label} is not exactly one fixed-header gzip member`);
  }
  const trailer = representation.subarray(trailerOffset);
  if (
    trailer.readUInt32LE(0) !== (crc32(expanded) >>> 0) ||
    trailer.readUInt32LE(4) !== (expanded.byteLength >>> 0)
  ) {
    throw new Error(`${label} has an invalid gzip trailer`);
  }
  return expanded;
}

export async function expandReceiptBoundGzip(representation, options) {
  try {
    const representationSnapshot = Buffer.isBuffer(representation)
      ? Buffer.from(representation)
      : representation;
    return await expandReceiptBoundGzipUnsafe(representationSnapshot, options);
  } catch {
    throw new Error("receipt-bound gzip verification failed");
  }
}
