const MAX_INPUT_BYTES = 16 * 1024 * 1024;
const MAX_PREFIX_BYTES = 512;
const MAX_DIMENSION = 100_000;
const MAX_PIXELS = 100_000_000;
const PNG_SIGNATURE = Object.freeze([137, 80, 78, 71, 13, 10, 26, 10]);

function reject(reason) {
  throw new TypeError(`bounded image metadata rejected: ${reason}`);
}

function inputBytes(input) {
  if (!(input instanceof Uint8Array)) {
    reject("input must be a Uint8Array");
  }
  if (input.byteLength === 0 || input.byteLength > MAX_INPUT_BYTES) {
    reject("input length is outside the supported bound");
  }
  // Vinext supplies Buffers, but accepting a SharedArrayBuffer-backed view
  // would otherwise let another thread change header bytes between checks.
  // The parser needs at most the fixed SVG prefix (PNG needs only 33 bytes),
  // so take one bounded snapshot before inspecting any format field.
  return Uint8Array.from(input.subarray(0, Math.min(input.byteLength, MAX_PREFIX_BYTES)));
}

function matches(bytes, offset, expected) {
  if (offset < 0 || offset + expected.length > bytes.byteLength) return false;
  for (let index = 0; index < expected.length; index += 1) {
    if (bytes[offset + index] !== expected[index]) return false;
  }
  return true;
}

function uint32(bytes, offset) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(offset, false);
}

function crc32(bytes, start, end) {
  let crc = 0xffffffff;
  for (let index = start; index < end; index += 1) {
    crc ^= bytes[index];
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngDimensions(bytes) {
  if (bytes.byteLength < 33 || !matches(bytes, 0, PNG_SIGNATURE)) return null;
  if (uint32(bytes, 8) !== 13 || !matches(bytes, 12, [73, 72, 68, 82])) {
    reject("PNG must begin with one canonical IHDR chunk");
  }
  if (crc32(bytes, 12, 29) !== uint32(bytes, 29)) {
    reject("PNG IHDR checksum is invalid");
  }

  const width = uint32(bytes, 16);
  const height = uint32(bytes, 20);
  if (width === 0 || height === 0 || width > MAX_DIMENSION || height > MAX_DIMENSION) {
    reject("PNG dimensions are outside the supported bound");
  }
  if (width * height > MAX_PIXELS) {
    reject("PNG pixel area is outside the supported bound");
  }

  const bitDepth = bytes[24];
  const colorType = bytes[25];
  const validDepths = {
    0: [1, 2, 4, 8, 16],
    2: [8, 16],
    3: [1, 2, 4, 8],
    4: [8, 16],
    6: [8, 16],
  };
  if (!validDepths[colorType]?.includes(bitDepth)) {
    reject("PNG color type and bit depth are inconsistent");
  }
  if (bytes[26] !== 0 || bytes[27] !== 0 || ![0, 1].includes(bytes[28])) {
    reject("PNG IHDR method fields are unsupported");
  }
  return Object.freeze({ width, height, type: "png" });
}

function isAsciiWhitespace(value) {
  return value === 9 || value === 10 || value === 12 || value === 13 || value === 32;
}

function matchesAscii(bytes, offset, text) {
  if (offset < 0 || offset + text.length > bytes.byteLength) return false;
  for (let index = 0; index < text.length; index += 1) {
    if (bytes[offset + index] !== text.charCodeAt(index)) return false;
  }
  return true;
}

function hasCompleteStartTag(bytes, offset, limit) {
  let quote = 0;
  for (let cursor = offset; cursor < limit; cursor += 1) {
    const value = bytes[cursor];
    if (quote !== 0) {
      if (value === quote) quote = 0;
      continue;
    }
    if (value === 34 || value === 39) {
      quote = value;
    } else if (value === 62) {
      return true;
    }
  }
  return false;
}

function xmlDeclarationEnd(bytes, offset, limit) {
  let quote = 0;
  for (let cursor = offset; cursor + 1 < limit; cursor += 1) {
    const value = bytes[cursor];
    if (quote !== 0) {
      if (value === quote) quote = 0;
      continue;
    }
    if (value === 34 || value === 39) {
      quote = value;
    } else if (value === 63 && bytes[cursor + 1] === 62) {
      return cursor + 2;
    }
  }
  return -1;
}

function isSvg(bytes) {
  const limit = Math.min(bytes.byteLength, MAX_PREFIX_BYTES);
  let cursor = matches(bytes, 0, [0xef, 0xbb, 0xbf]) ? 3 : 0;
  while (cursor < limit && isAsciiWhitespace(bytes[cursor])) cursor += 1;

  if (matchesAscii(bytes, cursor, "<?xml") && isAsciiWhitespace(bytes[cursor + 5])) {
    cursor = xmlDeclarationEnd(bytes, cursor + 5, limit);
    if (cursor < 0) return false;
    while (cursor < limit && isAsciiWhitespace(bytes[cursor])) cursor += 1;
  }

  if (!matchesAscii(bytes, cursor, "<svg")) return false;
  const terminator = bytes[cursor + 4];
  if (!(terminator === 47 || terminator === 62 || isAsciiWhitespace(terminator))) return false;
  if (terminator === 47) return bytes[cursor + 5] === 62;
  return hasCompleteStartTag(bytes, cursor + 4, limit);
}

export function imageSize(input) {
  const bytes = inputBytes(input);
  const png = pngDimensions(bytes);
  if (png) return png;
  if (isSvg(bytes)) return Object.freeze({ type: "svg" });
  reject("format is not an allowed PNG or SVG");
}

export default imageSize;
