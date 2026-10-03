/**
 * validate-snapshot.mjs — decide whether a byte string is a snapshot this compiler supports, BEFORE
 * compiling it, and say in plain language what is wrong and where when it is not.
 *
 * Pure, like compile-model.mjs: no `node:` import, no Node global, so a browser runs the same checks
 * on a file a user opens. Everything it refuses carries a stable code:
 *
 *   E_TOO_LARGE          above the size cap (checked before anything is decoded)
 *   E_BOM                a UTF-8 or UTF-16 byte-order mark (the engine writes plain UTF-8)
 *   E_NOT_UTF8           bytes that are not UTF-8
 *   E_NOT_JSON           not JSON — with line, column, a snippet, and the JSON Pointer of the value
 *                        being read; NaN / Infinity named as the non-finite numbers they are
 *   E_DUPLICATE_KEY      a member name repeated in one object. JSON.parse keeps the LAST silently; the
 *                        engine refuses (cisco_toolkit/protocol_assurance.py reject_duplicate_json_keys)
 *   E_ROOT_NOT_OBJECT    a list or a scalar (a devices.json inventory is a list)
 *   E_NOT_A_SNAPSHOT     an object that is not an assessment snapshot
 *   E_SCHEMA_UNSUPPORTED a snapshot schema this compiler does not read; or no schema at all (a legacy
 *                        snapshot), unless the caller explicitly allows legacy input
 *   E_SECTION_SCHEMA     a section the compiler reads, at a section schema it does not know
 *
 * Warnings never block: W_COLLECTED_AT_MISSING, W_GENERATED_AT_MISSING, W_SCHEMA_ASSUMED,
 * W_SECTION_ABSENT (a section the model reads is absent, so the UI will show it as not observed) and
 * W_ROUTES_NOT_USABLE (a host's `routes` value is not a routing table, such as null, an empty list, a
 * marker string or prefix-less entries, so the model gives that host no RIB and a trace reaching it is
 * indeterminate; or the `routes` section itself is not an object, so no host has one).
 */
import { CompileError, KNOWN_SECTION_SCHEMAS, LEGACY_SCHEMA_ASSUMED, SECTIONS_READ, SUPPORTED_SCHEMAS, unusableRouteTable } from "./compile-model.mjs";

/** The largest snapshot accepted: 256 MiB, far above a real fleet's on-disk form and below what a browser tab can parse. */
export const DEFAULT_MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024;

/**
 * Top-level sections every assessment snapshot writes. A schema-less object holding fewer than
 * `CORE_SECTIONS_REQUIRED` of them is not a snapshot at all (an inventory, another document, `{}`).
 */
export const CORE_SECTIONS = Object.freeze(["devices", "interfaces", "cable_map", "punchlist", "health_scores"]);
export const CORE_SECTIONS_REQUIRED = 2;

/** Deeper nesting than this is refused rather than risking the call stack on hostile input. */
const MAX_DEPTH = 512;
/** Duplicate keys are all reported, up to this many. */
const MAX_DUPLICATES_REPORTED = 20;

/**
 * @typedef {{ code: string; message: string; path?: string; offset?: number; line?: number; column?: number; snippet?: string }} Issue
 */

/** RFC 6901 escaping of one reference token. @param {string} t */
const escapeToken = (t) => t.replace(/~/g, "~0").replace(/\//g, "~1");
/** @param {(string | number)[]} tokens */
const pointerOf = (tokens) => tokens.map((t) => `/${escapeToken(String(t))}`).join("");

/** Line (1-based), column (1-based, UTF-16 units) and a one-line snippet around `offset`. @param {string} text @param {number} offset */
function locate(text, offset) {
  let line = 1;
  let lineStart = 0;
  for (let i = 0; i < offset && i < text.length; i += 1) {
    if (text.charCodeAt(i) === 0x0a) {
      line += 1;
      lineStart = i + 1;
    }
  }
  let lineEnd = text.indexOf("\n", lineStart);
  if (lineEnd === -1) lineEnd = text.length;
  const from = Math.max(lineStart, offset - 40);
  const to = Math.min(lineEnd, offset + 40);
  const snippet = text.slice(from, to).replace(/[\u0000-\u001f]/g, " ");
  return { line, column: offset - lineStart + 1, snippet };
}

/** Thrown inside the scanner, caught by `scan`. */
class SyntaxStop {
  /** @param {number} offset @param {string} message @param {(string | number)[]} path */
  constructor(offset, message, path) {
    this.offset = offset;
    this.message = message;
    this.path = path;
  }
}

/**
 * A JSON scanner that does what JSON.parse will not: it reports WHERE the text stops being JSON (with
 * the pointer of the value being read), names NaN/Infinity for what they are, and records every
 * duplicate member name. It builds no value — JSON.parse does that once the text is known to be clean,
 * and for clean text the two agree by construction (no duplicate means nothing was overwritten).
 * @param {string} text
 * @returns {{ error: SyntaxStop | null; duplicates: { path: string; offset: number; key: string }[] }}
 */
function scan(text) {
  const n = text.length;
  let i = 0;
  /** @type {{ path: string; offset: number; key: string }[]} */
  const duplicates = [];
  /** @type {(string | number)[]} */
  const path = [];

  const ws = () => {
    while (i < n) {
      const c = text.charCodeAt(i);
      if (c === 0x20 || c === 0x0a || c === 0x0d || c === 0x09) i += 1;
      else break;
    }
  };
  /** @param {string} message @returns {never} */
  const fail = (message) => {
    throw new SyntaxStop(i, message, [...path]);
  };
  const describeHere = () => (i >= n ? "the end of the file" : `${JSON.stringify(text.slice(i, i + 12))}`);

  /** Scan a string starting at the opening quote; return its decoded value only when `decode`. @param {boolean} decode */
  const string = (decode) => {
    const start = i;
    i += 1; // opening quote
    let escaped = false;
    while (true) {
      if (i >= n) fail("a text value is not closed (its closing quote is missing)");
      const c = text.charCodeAt(i);
      if (c === 0x22) break;
      if (c < 0x20) fail("a text value contains a raw control character (a line break inside quotes?)");
      if (c === 0x5c) {
        escaped = true;
        const e = text[i + 1];
        if (e === "u") {
          if (!/^[0-9a-fA-F]{4}$/.test(text.slice(i + 2, i + 6))) fail("a \\u escape is not followed by four hex digits");
          i += 6;
          continue;
        }
        if (e === undefined || !'"\\/bfnrt'.includes(e)) fail(`an unknown escape \\${e ?? ""} in a text value`);
        i += 2;
        continue;
      }
      i += 1;
    }
    i += 1; // closing quote
    if (!decode) return "";
    const raw = text.slice(start + 1, i - 1);
    return escaped ? /** @type {string} */ (JSON.parse(text.slice(start, i))) : raw;
  };

  const number = () => {
    const m = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/.exec(text.slice(i, i + 400));
    if (m === null || m[0] === "" || m[0] === "-") fail(`expected a value, found ${describeHere()}`);
    i += /** @type {RegExpExecArray} */ (m)[0].length;
  };

  /** @param {number} depth */
  const value = (depth) => {
    if (depth > MAX_DEPTH) fail(`the document nests deeper than ${MAX_DEPTH} levels`);
    ws();
    if (i >= n) fail("the file ends where a value was expected (is it truncated?)");
    const c = text[i];
    if (c === "{") {
      i += 1;
      /** @type {Set<string>} */
      const keys = new Set();
      ws();
      if (text[i] === "}") {
        i += 1;
        return;
      }
      while (true) {
        ws();
        if (text[i] !== '"') fail(`expected a quoted member name, found ${describeHere()}`);
        const keyAt = i;
        const key = string(true);
        if (keys.has(key)) {
          if (duplicates.length < MAX_DUPLICATES_REPORTED) duplicates.push({ path: pointerOf([...path, key]), offset: keyAt, key });
        } else keys.add(key);
        ws();
        if (text[i] !== ":") fail(`expected ":" after the member name ${JSON.stringify(key)}, found ${describeHere()}`);
        i += 1;
        path.push(key);
        value(depth + 1);
        path.pop();
        ws();
        if (text[i] === ",") {
          i += 1;
          continue;
        }
        if (text[i] === "}") {
          i += 1;
          return;
        }
        fail(`expected "," or "}" in an object, found ${describeHere()}`);
      }
    }
    if (c === "[") {
      i += 1;
      ws();
      if (text[i] === "]") {
        i += 1;
        return;
      }
      for (let k = 0; ; k += 1) {
        path.push(k);
        value(depth + 1);
        path.pop();
        ws();
        if (text[i] === ",") {
          i += 1;
          continue;
        }
        if (text[i] === "]") {
          i += 1;
          return;
        }
        fail(`expected "," or "]" in a list, found ${describeHere()}`);
      }
    }
    if (c === '"') {
      string(false);
      return;
    }
    for (const word of ["true", "false", "null"]) {
      if (text.startsWith(word, i)) {
        i += word.length;
        return;
      }
    }
    for (const word of ["NaN", "Infinity", "-Infinity"]) {
      if (text.startsWith(word, i)) {
        fail(
          `the engine wrote a non-finite number (${word}) here. JSON has no such number: Python's json.dump emits it by ` +
            `default, and the engine's own snapshot reader refuses it too (cisco_toolkit/protocol_assurance.py)`,
        );
      }
    }
    number();
  };

  try {
    value(0);
    ws();
    if (i < n) fail(`the document continues after its end, at ${describeHere()}`);
    return { error: null, duplicates };
  } catch (e) {
    if (e instanceof SyntaxStop) return { error: e, duplicates };
    throw e;
  }
}

/**
 * Validate `bytes` as a snapshot this compiler supports.
 * @param {Uint8Array} bytes
 * @param {{ allowLegacy?: boolean; maxBytes?: number }} [opts]
 * @returns {{ ok: boolean; errors: Issue[]; warnings: Issue[]; snap: Record<string, any> | null; schemaAssumed: string | null }}
 */
export function validateSnapshot(bytes, opts = {}) {
  const maxBytes = opts.maxBytes ?? DEFAULT_MAX_SNAPSHOT_BYTES;
  /** @type {Issue[]} */
  const errors = [];
  /** @type {Issue[]} */
  const warnings = [];
  /** @param {Issue} e */
  const refuse = (e) => ({ ok: false, errors: [...errors, e], warnings, snap: null, schemaAssumed: null });

  if (bytes.length > maxBytes) {
    return refuse({
      code: "E_TOO_LARGE",
      message: `the file is ${bytes.length.toLocaleString("en")} bytes, above the ${maxBytes.toLocaleString("en")}-byte limit this reader accepts.`,
    });
  }
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return refuse({
      code: "E_BOM",
      message:
        "the file starts with a UTF-8 byte-order mark (EF BB BF). The engine writes plain UTF-8 without one; an editor " +
        "probably re-saved it. Save it again as UTF-8 without BOM, or re-export it from the engine.",
      offset: 0,
    });
  }
  if ((bytes[0] === 0xff && bytes[1] === 0xfe) || (bytes[0] === 0xfe && bytes[1] === 0xff)) {
    return refuse({
      code: "E_BOM",
      message: "the file starts with a UTF-16 byte-order mark: it was saved as UTF-16, and a snapshot is UTF-8. Re-export it from the engine.",
      offset: 0,
    });
  }
  /** @type {string} */
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    return refuse({ code: "E_NOT_UTF8", message: "the file is not UTF-8 text, so it cannot be an engine snapshot (which is UTF-8 JSON)." });
  }

  const scanned = scan(text);
  if (scanned.error !== null) {
    const { line, column, snippet } = locate(text, scanned.error.offset);
    const where = pointerOf(scanned.error.path);
    return refuse({
      code: "E_NOT_JSON",
      message: `this is not valid JSON at line ${line}, column ${column}${where ? ` (reading ${where})` : ""}: ${scanned.error.message}.`,
      path: where,
      offset: scanned.error.offset,
      line,
      column,
      snippet,
    });
  }
  if (scanned.duplicates.length > 0) {
    for (const d of scanned.duplicates) {
      const { line, column, snippet } = locate(text, d.offset);
      errors.push({
        code: "E_DUPLICATE_KEY",
        message:
          `the member name ${JSON.stringify(d.key)} appears twice in one object (${d.path}, line ${line}). A reader would keep ` +
          `one silently and drop the other; the engine refuses such a file, and so does this one.`,
        path: d.path,
        offset: d.offset,
        line,
        column,
        snippet,
      });
    }
    return { ok: false, errors, warnings, snap: null, schemaAssumed: null };
  }

  /** @type {unknown} */
  const root = JSON.parse(text);
  if (root === null || typeof root !== "object" || Array.isArray(root)) {
    const what = Array.isArray(root) ? "a list" : root === null ? "null" : `a ${typeof root}`;
    return refuse({
      code: "E_ROOT_NOT_OBJECT",
      message:
        `the file holds ${what}, and a snapshot is one JSON object. ` +
        (Array.isArray(root) ? "A list is what a devices.json inventory looks like — that is the collector's input, not its output." : ""),
      path: "",
    });
  }
  const snap = /** @type {Record<string, any>} */ (root);

  /** @type {string | null} */
  let schemaAssumed = null;
  if (Object.hasOwn(snap, "schema")) {
    const schema = snap.schema;
    if (typeof schema !== "string" || !schema.startsWith("collect_parse_snapshot/")) {
      return refuse({
        code: "E_NOT_A_SNAPSHOT",
        message: `the file declares schema ${JSON.stringify(schema)}, which is not an assessment snapshot (collect_parse_snapshot/…).`,
        path: "/schema",
      });
    }
    if (!SUPPORTED_SCHEMAS.includes(schema)) {
      return refuse({
        code: "E_SCHEMA_UNSUPPORTED",
        message: `the snapshot's schema is ${schema}; this compiler reads ${SUPPORTED_SCHEMAS.join(", ")} and will not guess at another version's meaning.`,
        path: "/schema",
      });
    }
  } else {
    const present = CORE_SECTIONS.filter((s) => Object.hasOwn(snap, s));
    if (present.length < CORE_SECTIONS_REQUIRED) {
      return refuse({
        code: "E_NOT_A_SNAPSHOT",
        message:
          `the file has no schema tag and ${present.length === 0 ? "none" : `only ${present.join(", ")}`} of the sections every ` +
          `snapshot writes (${CORE_SECTIONS.join(", ")}), so it is not an assessment snapshot.`,
        path: "",
      });
    }
    if (opts.allowLegacy !== true) {
      return refuse({
        code: "E_SCHEMA_UNSUPPORTED",
        message:
          `the snapshot has no schema tag — an older (legacy) engine output. Its meaning is ASSUMED, not stated, so it is refused ` +
          `unless you pass --allow-legacy, which reads it as ${LEGACY_SCHEMA_ASSUMED} and records that assumption in the model.`,
        path: "/schema",
      });
    }
    schemaAssumed = LEGACY_SCHEMA_ASSUMED;
    warnings.push({
      code: "W_SCHEMA_ASSUMED",
      message: `no schema tag: read as ${LEGACY_SCHEMA_ASSUMED} because legacy input was allowed; the model records meta.schemaAssumed.`,
      path: "/schema",
    });
  }

  for (const section of SECTIONS_READ) {
    const v = snap[section];
    if (v === null || typeof v !== "object" || Array.isArray(v) || !Object.hasOwn(v, "schema")) continue;
    const known = /** @type {Record<string, readonly string[]>} */ (KNOWN_SECTION_SCHEMAS)[section] ?? [];
    if (!known.includes(v.schema)) {
      errors.push({
        code: "E_SECTION_SCHEMA",
        message:
          `the section ${section} is written at schema ${JSON.stringify(v.schema)}, which this compiler does not read ` +
          `(${known.length > 0 ? `it reads ${known.join(", ")}` : "it knows no tagged version of this section"}).`,
        path: `/${escapeToken(section)}/schema`,
      });
    }
  }
  if (errors.length > 0) return { ok: false, errors, warnings, snap: null, schemaAssumed: null };

  for (const [key, code] of /** @type {const} */ ([["collected_at", "W_COLLECTED_AT_MISSING"], ["generated_at", "W_GENERATED_AT_MISSING"]])) {
    const v = snap[key];
    if (typeof v !== "string" || v.trim() === "") {
      warnings.push({ code, message: `the snapshot does not say when it was ${key === "collected_at" ? "collected" : "generated"} (${key}); the model will show that date as not stated.`, path: `/${key}` });
    }
  }
  for (const section of SECTIONS_READ) {
    if (!Object.hasOwn(snap, section)) {
      warnings.push({ code: "W_SECTION_ABSENT", message: `the snapshot has no ${section} section; what it would show is rendered as not observed.`, path: `/${escapeToken(section)}` });
    }
  }
  /* A routing table the snapshot does not actually hold is the absence of one. The compiler gives such a
     host no RIB (compile-model.mjs `unusableRouteTable`, the one rule); this says so where it happens,
     rather than letting a null or a marker string pass unremarked into "no routing table collected". */
  if (Object.hasOwn(snap, "routes")) {
    const routes = snap.routes;
    if (routes === null || typeof routes !== "object" || Array.isArray(routes)) {
      warnings.push({
        code: "W_ROUTES_NOT_USABLE",
        message: `the routes section is ${Array.isArray(routes) ? "a list" : routes === null ? "null" : `a ${typeof routes}`}, not an object keyed by host, so no host has a collected routing table; every trace is indeterminate at its first routed hop.`,
        path: "/routes",
      });
    } else {
      for (const [host, rs] of Object.entries(routes)) {
        const why = unusableRouteTable(rs);
        if (why === null) continue;
        warnings.push({
          code: "W_ROUTES_NOT_USABLE",
          message: `routes.${host} is ${why}, so ${host} has no collected routing table in this model; a trace that reaches it is indeterminate there, never a decided drop.`,
          path: `/routes/${escapeToken(host)}`,
        });
      }
    }
  }
  return { ok: true, errors, warnings, snap, schemaAssumed };
}

/**
 * Validate, and throw a CompileError carrying every issue when the bytes are refused.
 * @param {Uint8Array} bytes
 * @param {{ allowLegacy?: boolean; maxBytes?: number }} [opts]
 * @returns {{ snap: Record<string, any>; warnings: Issue[]; schemaAssumed: string | null }}
 */
export function assertValidSnapshot(bytes, opts = {}) {
  const r = validateSnapshot(bytes, opts);
  if (!r.ok || r.snap === null) {
    const first = /** @type {Issue} */ (r.errors[0]);
    const more = r.errors.length > 1 ? ` (and ${r.errors.length - 1} more)` : "";
    throw new CompileError(first.code, `${first.message}${more}`, first.path ?? null, r.errors);
  }
  return { snap: r.snap, warnings: r.warnings, schemaAssumed: r.schemaAssumed };
}
