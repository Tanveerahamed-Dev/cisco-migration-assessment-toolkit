/**
 * compile-model.mjs — the ONE compiler between the assessment engine's evidence snapshot and Atlas
 * Scope's model. Pure: it takes a parsed snapshot and its binding and returns the four compiled
 * documents. It reads no file, writes no file, hashes nothing and imports nothing outside this
 * directory, so the SAME code runs at build time in Node (tools/compile-*.mjs, through
 * tools/lib/compile-io.mjs) and at runtime in a browser. `src/core/compile-model.test.ts` proves the
 * import graph names no `node:` builtin, no package and no Node global.
 *
 * Doctrine (CLAUDE.md, SSOT + coverage-honesty), unchanged from the four compilers this replaces:
 *   - Every field emitted here is READ from the snapshot; nothing is invented, defaulted to a
 *     healthy value, or interpolated. Absence is emitted as `null` and rendered as "not observed".
 *   - Every record carries `cite`: a dotted path back into the snapshot so the Inspector can show
 *     the raw evidence a claim rests on. A claim with no `cite` is a bug.
 *   - Every compiled document carries the SOURCE BINDING in `meta` (see `bindSource` below): which
 *     bytes it was compiled from, in which form, under which name.
 *
 * WHY ONE MODULE (2026-09-26). The four compilers each read the snapshot on their own, and
 * `npm run compile:data` ran only one of them, so a routine recompile left three sidecars bound to
 * the previous snapshot, and a failed main compile still let the other three write. Their bodies now
 * live here, and `compileAll` produces the set together from one parsed value.
 *
 * FAILURES ARE CODED. Everything this module refuses is a `CompileError` with a stable `code`
 * (E_UNKNOWN_PRODUCER_FIELD, E_NON_PRIMITIVE, E_PRODUCER_FIELD_TYPE, E_EVIDENCE_CONTRACT,
 * E_EVIDENCE_REF_MALFORMED, E_EVIDENCE_REF_UNRESOLVED, E_PROTOCOL_STATE, E_EMPTY_FABRIC, E_SOURCE_LABEL,
 * E_ENGINE_CONTRACT) and the snapshot path it concerns, so a loader can say in plain language what is
 * wrong and where.
 *
 * ONE CONTRACT (cluster R3, refuter X6). The evidence vocabularies and rules this module enforces are not
 * written here: they are READ from atlas-scope/contracts/engine-contract.v1.json, which the engine
 * generates from its own constants (cisco_toolkit/analyze.py `engine_contract_projection`, guarded there by
 * tests/test_engine_contract_projection.py). The copy that used to live here was hand-kept, so an engine-side
 * change to a kind, a role or a rule could not reach it. The import is a JSON module (data, no code): it is
 * the one edge the purity test (src/core/compile-model.test.ts) allows outside this directory.
 */
import ENGINE_CONTRACT_JSON from "../../contracts/engine-contract.v1.json" with { type: "json" };

/* ── errors ─────────────────────────────────────────────────────────────────────────────────── */

/** A refusal with a stable machine-readable code and the snapshot path it concerns. */
export class CompileError extends Error {
  /**
   * @param {string} code  stable identifier, e.g. "E_NON_PRIMITIVE"
   * @param {string} message  plain-language explanation
   * @param {string | null} [path]  where in the snapshot (dotted cite grammar or a JSON Pointer)
   * @param {unknown[]} [issues]  every issue, when one refusal stands for several
   * @param {{ cause?: unknown }} [options]  the underlying error, kept (never discarded) when one is wrapped
   */
  constructor(code, message, path = null, issues = [], options = undefined) {
    super(`${code}: ${message}`, options);
    this.name = "CompileError";
    this.code = code;
    this.path = path;
    this.issues = issues;
  }
}

/* ── the engine contract ────────────────────────────────────────────────────────────────────── */

/** The `schema` tag of the engine contract this compiler reads. */
export const ENGINE_CONTRACT_SCHEMA = "atlas-engine-contract/1";
/** The row-level evidence rules the contract may state, each a boolean switch the compiler enforces. */
const EVIDENCE_RULE_KEYS = Object.freeze([
  "total_only_when_capped",
  "absence_forbids_record_kinds",
  "record_requires_record_kind",
  "row_requires_ref",
  "host_must_be_row_device_or_null",
]);

/**
 * Validate the engine contract's shape, once, and freeze it. Nothing is defaulted: a missing, malformed or
 * UNKNOWN piece is a refusal (E_ENGINE_CONTRACT) — an unknown rule key would be an engine rule this compiler
 * silently does not enforce, which is the drift the contract exists to prevent.
 * @param {unknown} c
 */
export function readEngineContract(c) {
  /** @param {string} why @returns {never} */
  const bad = (why) => {
    throw new CompileError(
      "E_ENGINE_CONTRACT",
      `the engine contract (atlas-scope/contracts/engine-contract.v1.json) ${why}. It is generated from the engine ` +
        `(cisco_toolkit/analyze.py engine_contract_projection); regenerate it rather than editing it.`,
    );
  };
  /** @param {unknown} v @returns {v is Record<string, unknown>} */
  const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  if (!isObj(c)) bad("is not a JSON object");
  const top = /** @type {Record<string, unknown>} */ (c);
  const topKeys = ["schema", "owner", "punch_evidence", "protocol_assessability_states", "severities", "health_bands", "node_kinds"];
  const extraTop = Object.keys(top).filter((k) => !topKeys.includes(k));
  if (extraTop.length > 0) bad(`carries key(s) this compiler does not know: ${extraTop.join(", ")}`);
  if (top.schema !== ENGINE_CONTRACT_SCHEMA) bad(`has schema ${JSON.stringify(top.schema)}, not ${ENGINE_CONTRACT_SCHEMA}`);
  if (typeof top.owner !== "string" || top.owner === "") bad("names no owner");
  if (!isObj(top.punch_evidence)) bad("has no punch_evidence object");
  const pe = /** @type {Record<string, unknown>} */ (top.punch_evidence);
  const peKeys = ["kinds", "record_kinds", "roles", "bases", "cap", ...EVIDENCE_RULE_KEYS];
  const extraPe = Object.keys(pe).filter((k) => !peKeys.includes(k));
  if (extraPe.length > 0) bad(`states punch_evidence rule(s) this compiler does not enforce: ${extraPe.join(", ")}`);
  /** @param {unknown} v @param {string} name @returns {readonly string[]} */
  const names = (v, name) => {
    if (!Array.isArray(v) || v.length === 0 || !v.every((s) => typeof s === "string" && s !== "") || new Set(v).size !== v.length) {
      bad(`${name} is not a non-empty list of distinct names`);
    }
    return Object.freeze([.../** @type {string[]} */ (v)]);
  };
  const kinds = names(pe.kinds, "punch_evidence.kinds");
  const recordKinds = names(pe.record_kinds, "punch_evidence.record_kinds");
  if (!recordKinds.every((k) => kinds.includes(k))) bad("punch_evidence.record_kinds names a kind that is not in punch_evidence.kinds");
  const roles = names(pe.roles, "punch_evidence.roles");
  const bases = names(pe.bases, "punch_evidence.bases");
  for (const b of ["record", "row", "absence"]) if (!bases.includes(b)) bad(`punch_evidence.bases lacks ${JSON.stringify(b)}, which its rules name`);
  if (typeof pe.cap !== "number" || !Number.isSafeInteger(pe.cap) || pe.cap < 1) bad(`punch_evidence.cap is ${JSON.stringify(pe.cap)}, not a positive whole number`);
  /** @type {Record<string, boolean>} */
  const rules = {};
  for (const k of EVIDENCE_RULE_KEYS) {
    if (typeof pe[k] !== "boolean") bad(`punch_evidence.${k} is ${JSON.stringify(pe[k])}, not true or false`);
    rules[k] = /** @type {boolean} */ (pe[k]);
  }
  const states = names(top.protocol_assessability_states, "protocol_assessability_states");
  /* The closed display vocabularies (severity, health band, node kind). This compiler carries such a term VERBATIM
     (`term`), so it does not use them — the app's recognisers do (src/core/vocab.ts reads the same file). They are
     still validated here, because an accepted-but-unchecked key is exactly what the unknown-key refusal above exists
     to prevent: a malformed vocabulary stops the build here as well as in the app. */
  names(top.severities, "severities");
  if (!isObj(top.health_bands)) bad("has no health_bands object");
  const hb = /** @type {Record<string, unknown>} */ (top.health_bands);
  const extraHb = Object.keys(hb).filter((k) => k !== "scored" && k !== "not_measured");
  if (extraHb.length > 0) bad(`states health_bands key(s) this compiler does not know: ${extraHb.join(", ")}`);
  const scored = names(hb.scored, "health_bands.scored");
  if (typeof hb.not_measured !== "string" || hb.not_measured === "") bad("health_bands.not_measured is not a name");
  if (scored.includes(/** @type {string} */ (hb.not_measured))) bad("health_bands.not_measured is also a scored band");
  if (!isObj(top.node_kinds)) bad("has no node_kinds object");
  const nk = /** @type {Record<string, unknown>} */ (top.node_kinds);
  const extraNk = Object.keys(nk).filter((k) => k !== "collected" && k !== "classified");
  if (extraNk.length > 0) bad(`states node_kinds key(s) this compiler does not know: ${extraNk.join(", ")}`);
  const classified = names(nk.classified, "node_kinds.classified");
  if (typeof nk.collected !== "string" || nk.collected === "") bad("node_kinds.collected is not a name");
  if (classified.includes(/** @type {string} */ (nk.collected))) bad("node_kinds.collected is also a classified kind");
  return Object.freeze({
    schema: ENGINE_CONTRACT_SCHEMA,
    owner: /** @type {string} */ (top.owner),
    punchEvidence: Object.freeze({ kinds, recordKinds, roles, bases, cap: /** @type {number} */ (pe.cap), rules: Object.freeze(rules) }),
    protocolAssessabilityStates: states,
  });
}

/** The engine contract, validated at load. Every vocabulary and rule below is read from it. */
export const ENGINE_CONTRACT = readEngineContract(ENGINE_CONTRACT_JSON);

/* ── the snapshot contract this compiler supports ───────────────────────────────────────────── */

/** Top-level `schema` tags this compiler reads. The engine has never bumped `/1` (cisco_toolkit/html.py). */
export const SUPPORTED_SCHEMAS = Object.freeze(["collect_parse_snapshot/1"]);
/** What a legacy (schema-less) snapshot is read as, when the caller explicitly allows it. */
export const LEGACY_SCHEMA_ASSUMED = "collect_parse_snapshot/1";

/**
 * Every snapshot section this module reads. NOT a hand-kept list standing in for the class: the test
 * `src/core/compile-model.test.ts` derives the set of `snap.<key>` reads from this file's own text and
 * requires it to equal SECTIONS_READ ∪ META_KEYS_READ, and forbids bracketed (dynamic) access on the snapshot, so a
 * new read cannot escape the validator's section-schema gate (validate-snapshot.mjs).
 */
export const SECTIONS_READ = Object.freeze([
  "acl_line_reachability",
  "acls",
  "cable_map",
  "cross_layer",
  "devices",
  "endpoint_identity",
  "failure_impact",
  "health_scores",
  "interfaces",
  "l3_forwarding",
  "link_centrality",
  "object_groups",
  "overlay",
  "physical_health",
  "protocol_assessability",
  "protocol_health",
  "punchlist",
  "routes",
  "routing_neighbors",
]);
/** Top-level scalars read into `meta`, which are not sections. */
export const META_KEYS_READ = Object.freeze(["collected_at", "generated_at", "schema", "script_version"]);

/**
 * Section-level `schema` tags this compiler understands, for the sections it reads. A section the
 * compiler reads that carries a tag NOT listed here is refused (E_SECTION_SCHEMA): a new section
 * version means its semantics changed, and reading it under the old meaning is a silent misreading.
 */
export const KNOWN_SECTION_SCHEMAS = Object.freeze({
  protocol_assessability: Object.freeze(["protocol_assessability/1"]),
});

/* ── the source binding ─────────────────────────────────────────────────────────────────────── */

/** The byte forms a digest may be taken over. */
export const DIGEST_FORMS = Object.freeze(["lf-normalised", "assesshub-store-blob"]);
/** Where the bytes came from — this decides what "the exact bytes" are (see bindingPreimages). */
export const SOURCE_ORIGINS = Object.freeze(["repository-file", "external-file", "assesshub-store"]);
/** Every key a binding carries, in the order it is written. Mirrors `SOURCE_BINDING_KEYS` in src/core/types.ts. */
export const BINDING_KEYS = Object.freeze([
  "source",
  "sourceOrigin",
  "sourceDigestForm",
  "sourceSha256",
  "sourceBytes",
  "sourceExactSha256",
  "sourceGitBlob",
]);

const CR = 0x0d;
const LF = 0x0a;

/**
 * The LF-normalised form: every CR LF pair becomes LF; every other byte is copied unchanged (a lone CR
 * stays, no Unicode normalisation, no JSON re-serialisation). Exactly the conversion Git applies to a
 * text blob on commit, so a digest over it does not depend on the checkout's line endings (O15).
 * @param {Uint8Array} raw
 * @returns {Uint8Array}
 */
export function lfNormalise(raw) {
  const out = new Uint8Array(raw.length);
  let n = 0;
  for (let i = 0; i < raw.length; i += 1) {
    const b = /** @type {number} */ (raw[i]);
    if (b === CR && raw[i + 1] === LF) continue;
    out[n] = b;
    n += 1;
  }
  return out.subarray(0, n);
}

/**
 * Git's blob preimage: `"blob " + <length> + NUL + content`. Its SHA-1 is the blob id `git hash-object`
 * prints and `git rev-parse HEAD:<path>` resolves to.
 * @param {Uint8Array} content
 * @returns {Uint8Array}
 */
export function gitBlobPreimage(content) {
  const header = new TextEncoder().encode(`blob ${content.length}\u0000`);
  const out = new Uint8Array(header.length + content.length);
  out.set(header, 0);
  out.set(content, header.length);
  return out;
}

/**
 * A source label must NAME the source without disclosing where it sits on a disk: a home-directory
 * path carries the Windows username, which this repository treats as a client-privacy marker. A
 * repository file is named by its repository-relative POSIX path; an external file by its bare file
 * name; an AssessHub record by its store id (`assesshub:snapshot/<id>`).
 * @param {{ source: string; sourceOrigin: string; sourceDigestForm?: string }} label
 */
function checkLabel(label) {
  const { source, sourceOrigin } = label;
  const form = label.sourceDigestForm ?? "lf-normalised";
  const refuse = (/** @type {string} */ why) => {
    throw new CompileError("E_SOURCE_LABEL", `the source name ${JSON.stringify(source)} is refused: ${why}.`, null);
  };
  if (!SOURCE_ORIGINS.includes(sourceOrigin)) refuse(`the origin ${JSON.stringify(sourceOrigin)} is not one of ${SOURCE_ORIGINS.join(", ")}`);
  if (!DIGEST_FORMS.includes(form)) refuse(`the digest form ${JSON.stringify(form)} is not one of ${DIGEST_FORMS.join(", ")}`);
  /* The form is TIED to the origin (verifier S1-R2V-3): the store-blob form binds an AssessHub stored blob,
     and only an AssessHub record is one. A repository or external file in that form would take its digest
     over raw CRLF bytes; an AssessHub record in the LF form would show a digest that is not its store's. */
  if ((form === "assesshub-store-blob") !== (sourceOrigin === "assesshub-store")) {
    refuse(
      `the digest form ${JSON.stringify(form)} contradicts the origin ${JSON.stringify(sourceOrigin)}: "assesshub-store-blob" is the form of ` +
        `an "assesshub-store" record and of nothing else, and every other origin is bound in the "lf-normalised" form`,
    );
  }
  if (typeof source !== "string" || source.trim() === "" || source !== source.trim()) refuse("a source must have a non-empty name without surrounding spaces");
  if (/[\u0000-\u001f]/.test(source)) refuse("it contains a control character");
  if (source.includes("\\")) refuse("it contains a backslash (a Windows path)");
  if (/^[A-Za-z]:/.test(source) || source.startsWith("/")) refuse("it is an absolute path, which would publish where the file sits on this disk");
  if (sourceOrigin === "assesshub-store") {
    if (!/^assesshub:snapshot\/[A-Za-z0-9_-]+$/.test(source)) refuse("an AssessHub record is named assesshub:snapshot/<id>");
    return;
  }
  if (source.split("/").some((seg) => seg === ".." || seg === "." || seg === "")) refuse("it is not a normalised relative path");
  if (sourceOrigin === "external-file" && source.includes("/")) refuse("an external file is named by its file name alone, never by its directories");
}

/**
 * The byte strings each binding digest is taken over.
 *
 *   digested — `sourceSha256`/`sourceBytes`: the LF-normalised bytes (form "lf-normalised"), or the
 *              stored blob exactly (form "assesshub-store-blob", whose writer emits no CR).
 *   exact    — `sourceExactSha256`, in the ENGINE's form (`"sha256:" + sha256(<exact bytes>)`,
 *              cisco_toolkit/protocol_assurance.py `bind_snapshot_json_bytes`): the bytes AS READ, for
 *              every origin — exactly what the name says (owner decision, verifier S1-R2V-4; it used to
 *              be the LF form for a repository file, which on a CRLF checkout was the digest of no file
 *              on that disk and only restated sourceSha256). It is the one byte-dependent key
 *              (src/core/types.ts SOURCE_BINDING_BYTE_KEYS): a CRLF and an LF checkout of one file differ
 *              in it and agree on every other key, so a compile-identity check across checkouts compares
 *              the model with it excluded and checks it separately against the bytes each compile read.
 *   gitBlob  — `sourceGitBlob`: Git's blob preimage of the LF-normalised bytes.
 * @param {Uint8Array} bytes  the bytes as read
 * @param {{ sourceOrigin: string; sourceDigestForm?: string }} label
 */
export function bindingPreimages(bytes, label) {
  const form = label.sourceDigestForm ?? "lf-normalised";
  const normalised = lfNormalise(bytes);
  /* A private ArrayBuffer-backed copy of the input: what WebCrypto's digest() accepts, and immune to a
     caller mutating (or a Node Buffer pool reusing) the bytes while an async digest is in flight. */
  const asRead = new Uint8Array(bytes);
  const digested = form === "lf-normalised" ? normalised : asRead;
  return { digested, exact: asRead, gitBlob: gitBlobPreimage(normalised) };
}

/**
 * @typedef {{ source: string; sourceOrigin: string; sourceDigestForm: string; sourceSha256: string;
 *   sourceBytes: number; sourceExactSha256: string; sourceGitBlob: string }} Binding
 * @typedef {{ source: string; sourceOrigin: string; sourceDigestForm?: string }} SourceLabel
 * @typedef {{ sha256Hex: (b: Uint8Array) => string; sha1Hex: (b: Uint8Array) => string }} SyncHashes
 * @typedef {{ sha256Hex: (b: Uint8Array) => string | Promise<string>; sha1Hex: (b: Uint8Array) => string | Promise<string> }} AsyncHashes
 */

/**
 * @param {SourceLabel} label
 * @param {{ digested: Uint8Array }} pre
 * @param {string} digestedHex @param {string} exactHex @param {string} blobHex
 * @returns {Binding}
 */
function assemble(label, pre, digestedHex, exactHex, blobHex) {
  for (const [what, hex, len] of /** @type {const} */ ([["sha256", digestedHex, 64], ["sha256", exactHex, 64], ["sha1", blobHex, 40]])) {
    if (typeof hex !== "string" || hex.length !== len || !/^[0-9a-f]+$/.test(hex)) {
      throw new CompileError("E_HASH", `the ${what} function returned ${JSON.stringify(hex)}, not ${len} lowercase hex digits.`);
    }
  }
  return {
    source: label.source,
    sourceOrigin: label.sourceOrigin,
    sourceDigestForm: label.sourceDigestForm ?? "lf-normalised",
    sourceSha256: digestedHex,
    sourceBytes: pre.digested.length,
    sourceExactSha256: `sha256:${exactHex}`,
    sourceGitBlob: blobHex,
  };
}

/**
 * Bind `bytes` under `label`, with hash functions the CALLER supplies — this module hashes nothing
 * itself (tools/source-binding.mjs supplies node:crypto; a browser supplies WebCrypto).
 * @param {Uint8Array} bytes @param {SourceLabel} label @param {SyncHashes} hashes
 * @returns {Binding}
 */
export function bindSourceWith(bytes, label, hashes) {
  checkLabel(label);
  const pre = bindingPreimages(bytes, label);
  return assemble(label, pre, hashes.sha256Hex(pre.digested), hashes.sha256Hex(pre.exact), hashes.sha1Hex(pre.gitBlob));
}

/**
 * The same binding with asynchronous hash functions (WebCrypto's `crypto.subtle.digest`).
 * @param {Uint8Array} bytes @param {SourceLabel} label @param {AsyncHashes} hashes
 * @returns {Promise<Binding>}
 */
export async function bindSourceAsync(bytes, label, hashes) {
  checkLabel(label);
  const pre = bindingPreimages(bytes, label);
  const [d, e, g] = await Promise.all([hashes.sha256Hex(pre.digested), hashes.sha256Hex(pre.exact), hashes.sha1Hex(pre.gitBlob)]);
  return assemble(label, pre, d, e, g);
}

/** @param {Binding} b */
const bindingMeta = (b) => Object.fromEntries(BINDING_KEYS.map((k) => [k, b[/** @type {keyof Binding} */ (k)]]));

/* ── readers: every value from the snapshot enters as unknown and is narrowed here ───────────── */

/** Absence is absence. "", "-", "N/A" and the engine's explicit [NOT OBSERVED] marker all mean unobserved. */
const NOT_OBSERVED = /^\s*\[NOT OBSERVED\]/i;
/** @param {unknown} v */
const val = (v) => {
  if (v === undefined || v === null) return null;
  if (typeof v === "string") {
    const t = v.trim();
    if (t === "" || t === "-" || t === "N/A" || NOT_OBSERVED.test(t)) return null;
    return t;
  }
  if (typeof v === "number" && !Number.isFinite(v)) return null;
  return v;
};
/**
 * A value of a CLOSED vocabulary — a finding's severity, a device's health band, a node's kind — as the snapshot
 * wrote it. Absent or unobserved is null (as `val`). Text is kept VERBATIM, member or not: a value the vocabulary
 * does not name is carried as the producer wrote it and typed `Unrecognised` (src/core/types.ts, where each
 * vocabulary and its recogniser live), so it is never coerced to a member, never dropped, and never typed as one — a
 * surface cannot use it as a member without first asking the recogniser. A number or boolean is carried as its text
 * (no vocabulary names one, so it reads as unrecognised: `val` used to pass it through as a number, which every
 * string reader then threw on). Anything else is refused: stringifying it would emit "[object Object]".
 * @param {unknown} v @param {string} where
 * @returns {string | null}
 */
const term = (v, where) => {
  if (v !== null && typeof v === "object") {
    throw new CompileError(
      "E_NON_PRIMITIVE",
      `${where} is ${JSON.stringify(v).slice(0, 120)}, not a name. Stringifying it would emit "[object Object]"; this compiler ` +
        `does not know how to show it, so it refuses rather than guess.`,
      where,
    );
  }
  const t = val(v);
  return t === null ? null : String(t);
};
/**
 * Keep the engine's own unobserved prose when it carries a REASON worth showing.
 * @param {unknown} v
 */
const reason = (v) => (typeof v === "string" && NOT_OBSERVED.test(v.trim()) ? v.trim() : null);
/**
 * A number is a number the snapshot ACTUALLY carried, or nothing.
 *
 * An earlier implementation stripped every non-digit character before calling Number(), which turned
 * the snapshot's own absence markers into measurements (`num("N/A")` was 0, `num("Gi0/1")` was 1):
 * 92 of 122 port-health rows rendered a clean 0/0/0/0 error profile and 19 of 44 cables "Speed 0 Mbps"
 * (measured 2026-09-21). So: no character stripping, ever. A string is accepted only if the WHOLE of it
 * parses.
 * @param {unknown} v
 */
const num = (v) => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string") return null;
  const t = v.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};
/** @param {unknown} v @returns {any[]} */
const arr = (v) => (Array.isArray(v) ? v : []);
/**
 * String arrays, with a loud refusal instead of `[object Object]`. `arr(x).map(String)` over a list
 * of OBJECTS emits the literal "[object Object]" silently (measured 2026-09-21: all 44 links carried
 * `members: ["[object Object]"]`). This makes that shape a BUILD FAILURE rather than a shipped string.
 * @param {unknown} v
 * @param {string} where  the snapshot path, named in the build failure
 * @returns {string[]}
 */
const strs = (v, where) =>
  arr(v)
    .map((x) => {
      if (typeof x === "string") return x.trim();
      if (typeof x === "number" || typeof x === "boolean") return String(x);
      throw new CompileError(
        "E_NON_PRIMITIVE",
        `${where} contains a non-primitive member (${JSON.stringify(x).slice(0, 120)}). Stringifying it would ` +
          `emit "[object Object]"; this compiler does not know how to show it, so it refuses rather than guess.`,
        where,
      );
    })
    .filter((s) => s !== "");
/**
 * A JSON object, or an empty one. Its members stay `any` on purpose: they are snapshot values,
 * and each is narrowed by `val`/`num`/`strs`/`arr` at the point it is read.
 * @param {unknown} v
 * @returns {Record<string, any>}
 */
const obj = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : {});
/**
 * A snapshot object's member by an ENGINE-SUPPLIED name (a host, an ACL, a port), or undefined: only an OWN member
 * answers. `o[name]` answers a name the object does not hold from Object.prototype, so a cable-map node named
 * "constructor" read as inventoried, with the Object function as its inventory record.
 *
 * THE DICTIONARY RULE (CodeQL js/remote-property-injection). Every name a snapshot supplies is untrusted text, and
 * this module never assigns through one (`dict[name] = …`, `dict[name] ??= …`): a host named "__proto__" replaced
 * such a dictionary's prototype (so that host vanished from the model) or, through `??=`, handed back
 * Object.prototype itself. Dictionaries keyed by snapshot names are built with `Object.fromEntries` (which DEFINES
 * each member, so "__proto__" is an ordinary member) or accumulated in a Map, and read through `own`.
 * src/core/compile-reserved-names.test.ts compiles the sample with hosts renamed to such names.
 * @param {Record<string, any>} o @param {string} name
 */
const own = (o, name) => (Object.hasOwn(o, name) ? o[name] : undefined);
/**
 * A producer PROSE field (a disclosure the producer writes about its own finding): absent (or null) is
 * null — "not emitted" — and a string is kept VERBATIM, whatever it says. It deliberately does not go
 * through `val`: "N/A", "-", "" or an [NOT OBSERVED] sentence the producer DID write is a statement it
 * made, and reading it as null would render an emitted disclosure as one never emitted (verifier S1-V10).
 * Anything else is a coded refusal — never a stringified object.
 * @param {unknown} v @param {string} where
 * @returns {string | null}
 */
const text = (v, where) => {
  if (v === undefined || v === null) return null;
  if (typeof v === "string") return v;
  throw new CompileError("E_PRODUCER_FIELD_TYPE", `${where} should be text and is ${JSON.stringify(v).slice(0, 120)}.`, where);
};
/** Byte-stable ordering that does not depend on the runtime's default locale (Node and browsers differ). */
const byName = (/** @type {string} */ a, /** @type {string} */ b) => a.localeCompare(b, "en");

/* ── RFC 6901 JSON Pointers ─────────────────────────────────────────────────────────────────── */

/**
 * Parse an RFC 6901 pointer into its reference tokens, or null when it is not a well-formed pointer
 * that names a PART of a document. The whole-document pointer "" is refused: a citation of the
 * entire snapshot cites nothing in particular.
 * @param {unknown} pointer
 * @returns {string[] | null}
 */
export function parsePointer(pointer) {
  if (typeof pointer !== "string" || !pointer.startsWith("/")) return null;
  const tokens = pointer.slice(1).split("/");
  for (const t of tokens) if (/~(?![01])/.test(t)) return null;
  return tokens.map((t) => t.replace(/~1/g, "/").replace(/~0/g, "~"));
}

/**
 * Resolve a pointer against a parsed document. Only OWN members resolve, and an array index is
 * "0" or a decimal with no leading zero, below the length ("-", past the end, never resolves).
 * @param {unknown} doc @param {unknown} pointer
 * @returns {{ ok: true; value: unknown } | { ok: false; reason: string }}
 */
export function resolvePointer(doc, pointer) {
  const tokens = parsePointer(pointer);
  if (tokens === null) return { ok: false, reason: "not an RFC 6901 JSON Pointer to a part of the document" };
  /** @type {unknown} */
  let cur = doc;
  for (let i = 0; i < tokens.length; i += 1) {
    const t = /** @type {string} */ (tokens[i]);
    if (Array.isArray(cur)) {
      if (!/^(0|[1-9][0-9]*)$/.test(t) || Number(t) >= cur.length) return { ok: false, reason: `no element ${JSON.stringify(t)} in a list of ${cur.length}` };
      cur = cur[Number(t)];
    } else if (cur !== null && typeof cur === "object") {
      if (!Object.hasOwn(cur, t)) return { ok: false, reason: `no member ${JSON.stringify(t)}` };
      cur = /** @type {Record<string, unknown>} */ (cur)[t];
    } else {
      return { ok: false, reason: `the path passes through a ${cur === null ? "null" : typeof cur} at token ${i + 1}` };
    }
  }
  return { ok: true, value: cur };
}

/* ── the punch-list producer contract ───────────────────────────────────────────────────────── */

/**
 * Every key the producer may put on a punchlist row, and the compiled field that carries it.
 *
 * A row key NOT in this map is a BUILD FAILURE (E_UNKNOWN_PRODUCER_FIELD), not a silent drop: the
 * structural answer to a defect this compiler shipped three times (object groups, ACL evaluability,
 * `source_command`) — the producer adds a field, the compiler never learns of it, and the UI reports
 * a model gap as though the evidence did not exist.
 *
 * `severity_basis` and `evidence_confidence` (cisco_toolkit/analyze.py `compute_migration_punchlist`
 * `add()`, always written on Multicast/Media rows) are compiled since 2026-09-26: leaving them out
 * stopped the build for every real fleet with such a finding. `evidence_basis` / `evidence_refs` /
 * `evidence_refs_total` are the per-finding evidence contract (engine cluster E1), compiled and
 * RESOLVED below. Rendering all five is the UI's job (Finding in src/core/types.ts).
 */
export const PUNCHLIST_FIELDS = Object.freeze({
  severity: "severity",
  rank: "rank",
  priority: "priority",
  category: "category",
  devices: "devices",
  wave: "wave",
  title: "title",
  detail: "detail",
  remediation: "remediation",
  source_command: "sourceCommand",
  severity_basis: "severityBasis",
  evidence_confidence: "evidenceConfidence",
  evidence_basis: "evidenceBasis",
  evidence_refs: "evidenceRefs",
  evidence_refs_total: "evidenceRefsTotal",
});

/* The evidence vocabularies — READ from the engine contract, never restated (src/core/types.ts declares
   the same sets as TypeScript unions; src/core/compile-evidence.test.ts requires all three to agree). */
/** What kind of record an evidence ref points at. */
export const EVIDENCE_REF_KINDS = ENGINE_CONTRACT.punchEvidence.kinds;
/** The kinds that are configuration/device RECORDS (what basis "record" rests on, and "absence" never carries). */
export const EVIDENCE_RECORD_KINDS = ENGINE_CONTRACT.punchEvidence.recordKinds;
/** How the pointed-at record relates to the finding. */
export const EVIDENCE_REF_ROLES = ENGINE_CONTRACT.punchEvidence.roles;
/** What a finding's evidence rests on. */
export const EVIDENCE_BASES = ENGINE_CONTRACT.punchEvidence.bases;
/** The most refs a row publishes; a longer list is capped and its uncapped count stated as evidence_refs_total. */
export const EVIDENCE_REFS_CAP = ENGINE_CONTRACT.punchEvidence.cap;
/** Every state a protocol_assessability row may carry. */
export const PROTOCOL_ASSESSABILITY_STATES = ENGINE_CONTRACT.protocolAssessabilityStates;
/** The keys an evidence ref carries — all required (a null host is STATED, never implied). */
const EVIDENCE_REF_FIELDS = Object.freeze(["kind", "host", "ref", "role", "cite"]);

/* ── the evidence-record projection ─────────────────────────────────────────────────────────── */

/**
 * The bounds every record an evidence pointer names is projected under, in characters of text (JavaScript
 * string length). A record is copied into the model ONLY because a finding's `evidence_refs` names it; these
 * caps keep that copy small on a large fleet (the engine caps a row at 64 refs, so a 300-device fleet can name
 * thousands of records). Stated in the model as `fabric.evidenceProjection`, beside what they cost.
 *   fieldTextChars  — one member's text (a string member, or a nested object or list written as compact
 *                     JSON), cut past this;
 *   scalarTextChars — a record that IS a string (a configuration line, a literal evidence line);
 *   recordFields    — members carried per record, in the engine's order;
 *   recordChars     — one projected record, serialised; members past it are not carried;
 *   totalChars      — the whole projection as written, withheld records' pointer-only stubs included; records
 *                     past it, in the engine's priority order, are carried WITHHELD (compileEvidenceRecords).
 * Measured on the regenerated sample (2026-09-28): 369 distinct pointers; the largest pointed value is 4 347
 * characters of JSON (/operational_drift/0), all of them together 191 106, and their projection about 230 000 —
 * so the total cap holds the sample whole with room to spare, and bounds a large fleet at about 0.5 M characters.
 */
export const EVIDENCE_PROJECTION_CAPS = Object.freeze({
  fieldTextChars: 240,
  scalarTextChars: 1024,
  recordFields: 32,
  recordChars: 4096,
  totalChars: 524288,
});

/** @param {unknown} v @returns {"string" | "number" | "boolean" | "null" | "object" | "array"} */
const jsonType = (v) => {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  const t = typeof v;
  if (t === "string" || t === "number" || t === "boolean") return t;
  return "object";
};
/** The first `cap` characters, never ending inside a surrogate pair. @param {string} s @param {number} cap */
const cutText = (s, cap) => {
  if (s.length <= cap) return s;
  const t = s.slice(0, cap);
  return /[\uD800-\uDBFF]$/.test(t) ? t.slice(0, -1) : t;
};
/** Code-unit order, which does not depend on a runtime's locale. @param {string} a @param {string} b */
const byCodeUnit = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
/**
 * The characters `"key":member` takes as a member of a written object: exactly `JSON.stringify({ [key]: member })`
 * less its two braces, computed from the key's and the member's own JSON text. No object is keyed by the name —
 * the name is an ENGINE-SUPPLIED string (a host, an ACL, a port), so it is only ever text here. A member JSON
 * writes nothing for (undefined) costs nothing, as it did in the object form.
 * @param {string} key @param {unknown} member
 */
const memberChars = (key, member) => {
  const m = JSON.stringify(member);
  return m === undefined ? 0 : JSON.stringify(key).length + 1 + m.length;
};

/**
 * Project every record the findings' evidence pointers name (see EVIDENCE_PROJECTION_CAPS). One record per
 * DISTINCT pointer, sorted by pointer; each carries `cite` = its pointer, so the Inspector's citation index
 * resolves the engine's pointer to it. Nothing is copied that no pointer names: a pointed record's members
 * are part of it, its siblings are not.
 *
 * THE FORM of a record is the engine's value itself, one level deep: an object or list keeps its members in
 * the engine's order with every scalar member as the engine wrote it; a member that is itself an object or
 * list is written as its compact JSON text and named in `nested`; any text longer than its cap is cut and
 * its WHOLE length stated in `cut` (a scalar record's own cut under the key ""). Members past the per-record
 * caps are not carried and are counted by `fieldsTotal`. So every cut is stated, and nothing is paraphrased.
 *
 * THE TOTAL bounds everything written — the array as the model writes it, brackets and separators and the
 * WITHHELD records included. A record past the budget is written as
 * a pointer-only stub (it is never dropped: a finding carries that pointer), and every stub's size is reserved
 * from the total before any record is carried; so the whole projection stays within `totalChars` whenever the
 * stubs alone fit. When they do not, every record is withheld and `writtenChars` > `totalChars` states the
 * overrun, which is then the pointers the findings carry and nothing more. The budget is spent in the
 * ENGINE's priority order — findings by `priority`, then punch-list order, each finding's pointers in the
 * engine's order — so a record the engine ranks lower never displaces one it ranks higher; the output stays
 * sorted by pointer. (Before 2026-09-28 stubs were outside every budget and records were admitted in pointer
 * sort order: verifier P3A1-V1-4.)
 * @param {readonly { priority?: number | null; evidenceRefs?: readonly { ref: string }[] | null }[]} findings  compiled findings (every ref already RESOLVED)
 * @param {unknown} snap
 * @param {typeof EVIDENCE_PROJECTION_CAPS} [caps]  the bounds (the stated constant; a test may pass others)
 */
export function compileEvidenceRecords(findings, snap, caps = EVIDENCE_PROJECTION_CAPS) {
  /* The engine's priority order: a pointer's place is its first naming there. */
  const byPriority = findings
    .map((f, i) => ({ f, i }))
    .sort((a, b) => (a.f.priority ?? Infinity) - (b.f.priority ?? Infinity) || a.i - b.i);
  /** @type {Map<string, number>} */
  const rank = new Map();
  for (const { f } of byPriority) for (const r of f.evidenceRefs ?? []) if (!rank.has(r.ref)) rank.set(r.ref, rank.size);
  const pointers = [...rank.keys()].sort(byCodeUnit);
  const built = pointers.map((pointer) => {
    const hit = resolvePointer(snap, pointer);
    /* compileEvidence refused every pointer that does not resolve, so this cannot fire from a snapshot; it
       would be a compiler defect, and is refused as one rather than projected as "nothing". */
    if (!hit.ok) throw new CompileError("E_EVIDENCE_REF_UNRESOLVED", `${pointer} did not resolve at projection time (${hit.reason}).`, pointer);
    const v = hit.value;
    const base = { pointer, cite: pointer, type: jsonType(v), jsonChars: JSON.stringify(v).length };
    /** @type {string[]} */
    const nested = [];
    /** @type {[string, number][]} */
    const cut = [];
    /** @type {unknown} */
    let value;
    let fieldsTotal = 0;
    let carried = 0;
    if (v !== null && typeof v === "object") {
      /** @type {[string, unknown][]} */
      const entries = Array.isArray(v) ? v.map((x, i) => [String(i), x]) : Object.entries(v);
      fieldsTotal = entries.length;
      /** @type {[string, unknown][]} */
      const kept = [];
      /* The record as it will be written with no member yet; then each member's cost as it would be written. */
      let size = JSON.stringify({ ...base, value: Array.isArray(v) ? [] : {}, nested, cut: {}, fieldsTotal, withheld: false }).length;
      for (const [key, x] of entries) {
        if (kept.length >= caps.recordFields) break;
        const isNested = x !== null && typeof x === "object";
        const whole = isNested ? JSON.stringify(x) : x;
        const member = typeof whole === "string" ? cutText(whole, caps.fieldTextChars) : whole;
        const wasCut = typeof whole === "string" && typeof member === "string" && member.length < whole.length;
        /* A cut member's `cut` entry is measured as `{"key":0}` (its braces included), as it always was. */
        const add =
          (Array.isArray(v) ? JSON.stringify(member).length : memberChars(key, member)) +
          (kept.length === 0 ? 0 : 1) +
          (isNested ? JSON.stringify(key).length + 1 : 0) +
          (wasCut ? memberChars(key, 0) + 2 : 0);
        if (size + add > caps.recordChars) break;
        kept.push([key, member]);
        if (isNested) nested.push(key);
        if (wasCut) cut.push([key, /** @type {string} */ (whole).length]);
        size += add;
      }
      /* Object.fromEntries defines each member as data, so an engine key such as "__proto__" stays a member. */
      const build = () => ({ ...base, value: Array.isArray(v) ? kept.map(([, x]) => x) : Object.fromEntries(kept), nested, cut: Object.fromEntries(cut), fieldsTotal, withheld: false });
      /* The running size above is an estimate; the cap is checked on the record as written, dropping trailing
         members until it holds. */
      while (kept.length > 0 && JSON.stringify(build()).length > caps.recordChars) {
        const [k] = /** @type {[string, unknown]} */ (kept.pop());
        if (nested[nested.length - 1] === k) nested.pop();
        if (cut.length > 0 && cut[cut.length - 1]?.[0] === k) cut.pop();
      }
      carried = kept.length;
      value = build().value;
    } else {
      const whole = v;
      value = typeof whole === "string" ? cutText(whole, caps.scalarTextChars) : whole;
      if (typeof whole === "string" && typeof value === "string" && value.length < whole.length) cut.push(["", whole.length]);
    }
    const rec = { ...base, value, nested, cut: Object.fromEntries(cut), fieldsTotal, withheld: false };
    const stub = { ...base, value: null, nested: [], cut: {}, fieldsTotal, withheld: true };
    return { pointer, rec, stub, recChars: JSON.stringify(rec).length, stubChars: JSON.stringify(stub).length, omitted: fieldsTotal - carried, cuts: cut.length };
  });
  /* Everything starts withheld (every stub reserved); records are then carried in priority order while the
     whole — carried records plus the remaining stubs, and the array's own "[", "]" and separating commas as the
     model writes it — stays within the total. (The frame was outside the budget until verifier P3A1-V2-4: a
     planted run wrote 524 881 characters against 524 288.) */
  const frameChars = built.length === 0 ? 2 : built.length + 1;
  let writtenChars = frameChars + built.reduce((a, b) => a + b.stubChars, 0);
  /** @type {Set<string>} */
  const carriedSet = new Set();
  for (const b of [...built].sort((x, y) => /** @type {number} */ (rank.get(x.pointer)) - /** @type {number} */ (rank.get(y.pointer)))) {
    const next = writtenChars - b.stubChars + b.recChars;
    if (next > caps.totalChars) continue;
    writtenChars = next;
    carriedSet.add(b.pointer);
  }
  let projectedChars = 0;
  let withheldChars = 0;
  let recordsWithheld = 0;
  let fieldsOmitted = 0;
  let textsCut = 0;
  const records = built.map((b) => {
    if (!carriedSet.has(b.pointer)) {
      recordsWithheld += 1;
      withheldChars += b.stubChars;
      return b.stub;
    }
    projectedChars += b.recChars;
    fieldsOmitted += b.omitted;
    textsCut += b.cuts;
    return b.rec;
  });
  return {
    records,
    projection: {
      ...caps,
      records: records.length,
      projectedChars,
      recordsWithheld,
      fieldsOmitted,
      textsCut,
      withheldChars,
      writtenChars: projectedChars + withheldChars + frameChars,
    },
  };
}

/**
 * Compile one row's evidence contract, resolving every pointer against the snapshot it came from.
 * A key that is absent compiles to null ("not emitted"); a key that is present must honour the
 * contract exactly, or the build stops with a code.
 * @param {Record<string, any>} p  the punchlist row
 * @param {number} i  its index
 * @param {unknown} snap  the whole snapshot (pointers resolve against it)
 */
function compileEvidence(p, i, snap) {
  const at = `punchlist[${i}]`;
  const contract = (/** @type {string} */ where, /** @type {string} */ why) => {
    throw new CompileError("E_EVIDENCE_CONTRACT", `${where} ${why}`, where);
  };

  /** @type {string | null} */
  let basis = null;
  if (Object.hasOwn(p, "evidence_basis")) {
    const b = p.evidence_basis;
    if (typeof b !== "string" || !EVIDENCE_BASES.includes(b)) {
      contract(`${at}.evidence_basis`, `is ${JSON.stringify(b)}; the contract allows ${EVIDENCE_BASES.join(", ")}.`);
    }
    basis = /** @type {string} */ (b);
  }

  /** @type {{ kind: string; host: string | null; ref: string; role: string; label: string }[] | null} */
  let refs = null;
  if (Object.hasOwn(p, "evidence_refs")) {
    if (!Array.isArray(p.evidence_refs)) contract(`${at}.evidence_refs`, `is not a list (${JSON.stringify(p.evidence_refs).slice(0, 80)}).`);
    refs = /** @type {any[]} */ (p.evidence_refs).map((r, k) => {
      const where = `${at}.evidence_refs[${k}]`;
      if (r === null || typeof r !== "object" || Array.isArray(r)) contract(where, `is not an object (${JSON.stringify(r).slice(0, 80)}).`);
      const extra = Object.keys(r).filter((key) => !EVIDENCE_REF_FIELDS.includes(key));
      if (extra.length > 0) {
        throw new CompileError(
          "E_UNKNOWN_PRODUCER_FIELD",
          `${where} carries key(s) the evidence contract does not define: ${extra.join(", ")}. Compile them rather than dropping them.`,
          where,
        );
      }
      const missing = EVIDENCE_REF_FIELDS.filter((key) => !Object.hasOwn(r, key));
      if (missing.length > 0) contract(where, `lacks ${missing.join(", ")}; every ref states all of ${EVIDENCE_REF_FIELDS.join(", ")}.`);
      if (typeof r.kind !== "string" || !EVIDENCE_REF_KINDS.includes(r.kind)) contract(where, `has kind ${JSON.stringify(r.kind)}; the contract allows ${EVIDENCE_REF_KINDS.join(", ")}.`);
      if (typeof r.role !== "string" || !EVIDENCE_REF_ROLES.includes(r.role)) contract(where, `has role ${JSON.stringify(r.role)}; the contract allows ${EVIDENCE_REF_ROLES.join(", ")}.`);
      if (r.host !== null && typeof r.host !== "string") contract(where, `has host ${JSON.stringify(r.host)}; a host is a name or null.`);
      if (typeof r.cite !== "string") contract(where, `has cite ${JSON.stringify(r.cite)}; a cite is text.`);
      if (parsePointer(r.ref) === null) {
        throw new CompileError(
          "E_EVIDENCE_REF_MALFORMED",
          `${where} points at ${JSON.stringify(r.ref)}, which is not an RFC 6901 JSON Pointer to a part of the snapshot ` +
            `(it must start with "/", escape "~" as "~0" and "/" as "~1", and not be the whole document "").`,
          where,
        );
      }
      const hit = resolvePointer(snap, r.ref);
      if (!hit.ok || hit.value === null) {
        /* A whole missing SECTION is named as such: a file the engine wrote carries every section its refs
           cite, so a missing one means sections were removed afterwards (the pipeline golden strips its
           date-relative sections, device_dossiers among them). A present key holding null is refused too:
           the engine's contract is that a ref resolves to a NON-NULL node, and null records that nothing
           was observed there — citing it would render absence as a record. */
        const section = /** @type {string[]} */ (parsePointer(r.ref))[0];
        const sectionMissing = !hit.ok && section !== undefined && snap !== null && typeof snap === "object" && !Object.hasOwn(snap, section);
        const why = hit.ok
          ? "it holds null there — nothing observed, so nothing to cite"
          : sectionMissing
            ? `this snapshot has no ${section} section at all, so the file was altered — sections removed after the engine wrote it — and cannot back its own citations`
            : hit.reason;
        throw new CompileError(
          "E_EVIDENCE_REF_UNRESOLVED",
          `${where} cites ${r.ref}, which this snapshot does not hold (${why}). The model will not cite a record ` +
            `that is not in its own source.`,
          where,
        );
      }
      /* The producer's `cite` is a human LABEL ("core1 Gi1/0/9 (L1 leg of the stacked SPOF)"), compiled as
         `label`: in this model `cite` is a snapshot path, and every object carrying one is indexed as that
         citation's bearer (src/panels/Inspector.tsx citeBearers) — a label there is a "citation" nothing can
         open. The path is `ref`. */
      return { kind: r.kind, host: r.host, ref: r.ref, role: r.role, label: r.cite };
    });
  }

  /** @type {number | null} */
  let total = null;
  if (Object.hasOwn(p, "evidence_refs_total")) {
    const t = p.evidence_refs_total;
    if (refs === null) contract(`${at}.evidence_refs_total`, "is stated but the row carries no evidence_refs to count.");
    if (typeof t !== "number" || !Number.isSafeInteger(t) || t < /** @type {any[]} */ (refs).length) {
      contract(`${at}.evidence_refs_total`, `is ${JSON.stringify(t)}; it must be a whole number no smaller than the ${/** @type {any[]} */ (refs).length} ref(s) carried.`);
    }
    total = /** @type {number} */ (t);
  }

  /* THE ROW-LEVEL RULES — every one the engine contract states, enforced here so a model can never make a
     claim its evidence does not support (verifier S1-R2V-6: a "record" basis no record ref backs, a ref about
     a device the finding does not name, a total that says a complete list was cut). */
  const { cap, recordKinds, rules } = ENGINE_CONTRACT.punchEvidence;
  // The contract is written whole or not at all: a basis with no refs, or refs with no basis, is half of it.
  if (basis === null && refs !== null) contract(`${at}.evidence_basis`, "is missing although the row carries evidence_refs; the contract states the basis with every ref list.");
  if (basis !== null && refs === null) contract(`${at}.evidence_refs`, `is missing although the row states evidence_basis ${JSON.stringify(basis)}; the contract publishes the ref list (possibly empty) with every basis.`);
  if (refs !== null) {
    if (refs.length > cap) contract(`${at}.evidence_refs`, `carries ${refs.length} refs; the contract caps a row at ${cap} (the rest are counted in evidence_refs_total).`);
    if (rules.total_only_when_capped && total !== null && !(refs.length === cap && total > refs.length)) {
      contract(
        `${at}.evidence_refs_total`,
        `is ${total} with ${refs.length} ref(s) carried; the contract writes a total only when the list was CAPPED (exactly ${cap} refs and a larger total) — ` +
          `a total on an uncapped list would say evidence was cut that was not.`,
      );
    }
    if (rules.host_must_be_row_device_or_null) {
      const devices = new Set(arr(p.devices).filter((d) => typeof d === "string"));
      refs.forEach((r, k) => {
        if (r.host !== null && !devices.has(r.host)) {
          contract(`${at}.evidence_refs[${k}]`, `is about host ${JSON.stringify(r.host)}, which this finding does not name (devices: ${[...devices].join(", ") || "none"}); a ref is null-hosted or about one of the finding's own devices.`);
        }
      });
    }
    const recordRefs = refs.filter((r) => recordKinds.includes(r.kind));
    if (rules.record_requires_record_kind && basis === "record" && recordRefs.length === 0) {
      contract(`${at}.evidence_basis`, `is "record" but no ref is a record (${recordKinds.join(", ")}); a record basis no record ref backs is a claim its evidence does not support.`);
    }
    if (rules.absence_forbids_record_kinds && basis === "absence" && recordRefs.length > 0) {
      contract(`${at}.evidence_basis`, `is "absence" but the row carries record ref(s) of kind ${[...new Set(recordRefs.map((r) => r.kind))].join(", ")}; a finding about something MISSING cites witnesses, never a record of the missing thing.`);
    }
    if (rules.row_requires_ref && basis === "row" && refs.length === 0) {
      contract(`${at}.evidence_refs`, 'is empty although the basis is "row"; a row-based finding names the row it was derived from.');
    }
  }
  return { basis, refs, total };
}

/* ── the fabric model ───────────────────────────────────────────────────────────────────────── */

/**
 * Compile the UI model (src/data/fabric.json).
 * @param {Record<string, any>} snap  a validated snapshot (tools/lib/validate-snapshot.mjs)
 * @param {Binding} binding
 * @param {{ schemaAssumed?: string | null }} [opts]
 */
export function compileFabric(snap, binding, opts = {}) {
  /* devices ---------------------------------------------------------------- */
  const cableNodes = arr(snap.cable_map?.nodes);
  const nodeByHost = new Map(cableNodes.map((n) => [n.host, n]));
  const healthByHost = new Map(arr(snap.health_scores).map((h) => [h.switch, h]));
  const impactByHost = new Map(arr(snap.failure_impact).map((f) => [f.host, f]));

  /* Hosts the fabric must render = cable-map nodes union inventoried devices. A cable-map-only node
     (an AP, a phone, an uncollected neighbour) is REAL topology; dropping it would silently shrink
     the blast radius. It is emitted with collected:false so the UI can never imply we assessed it. */
  const hosts = [...new Set([...cableNodes.map((n) => n.host), ...Object.keys(obj(snap.devices))])].sort();

  /* PER-FIELD PROVENANCE (acceptance B6). A device record is assembled from up to four source records,
     so one `cite` cannot say where each field came from. `fieldCites` names, for each compiled field,
     the source record it was READ from, and names one only where that record exists. */
  const INVENTORY_FIELDS = ["platform", "model", "serial", "swVersion", "uptime", "powerSupplies", "modules"];
  const NODE_FIELDS = ["tier", "order", "opStatus", "badges"];
  const HEALTH_FIELDS = ["score", "band", "criticality", "dataQuality", "deductions"];
  /**
   * @param {string} host
   * @param {Record<string, any> | undefined} d  inventory record
   * @param {Record<string, any> | undefined} n  cable-map node
   * @param {Record<string, any> | undefined} h  health score
   * @returns {Record<string, string>}
   */
  const deviceFieldCites = (host, d, n, h) => {
    /** @type {Record<string, string>} */
    const out = {};
    const inv = `devices.${host}`;
    const node = `cable_map.nodes[host=${host}]`;
    const health = `health_scores[switch=${host}]`;
    const own = d ? inv : node;
    out.id = own;
    out.host = own;
    if (d) out.collected = inv;
    else if (n && typeof n.collected === "boolean") out.collected = node;
    if (d) for (const f of INVENTORY_FIELDS) out[f] = inv;
    if (n) for (const f of NODE_FIELDS) out[f] = node;
    if (n && val(n.kind) !== null) out.kind = node;
    if (h && val(h.role) !== null) out.role = health;
    else if (n && val(n.role) !== null) out.role = node;
    else if (h) out.role = health;
    else if (n) out.role = node;
    if (h) for (const f of HEALTH_FIELDS) out[f] = health;
    return out;
  };

  const inventory = obj(snap.devices);
  const devices = hosts.map((host) => {
    const d = own(inventory, host);
    const n = nodeByHost.get(host);
    const h = healthByHost.get(host);
    const fi = impactByHost.get(host);
    return {
      id: host,
      host,
      collected: d ? true : Boolean(n?.collected),
      inventoried: Boolean(d),
      /* null = NOT STATED. The engine writes a kind only on a cable-map node (cisco_toolkit/analyze.py
         compute_cable_map: CABLE_MAP_COLLECTED_KIND for a collected host, a _KIND_RANK member for a classified
         neighbour) and documents no default for a host it did not map, so none is invented here: this used to be
         `?? (d ? "switch" : "unknown")`, an uncited kind no record supports (src/core/compile-kind-absence.test.ts). */
      kind: term(n?.kind, `cable_map.nodes[host=${host}].kind`),
      role: val(h?.role) ?? val(n?.role),
      tier: Number.isFinite(n?.tier) ? n.tier : null,
      order: Number.isFinite(n?.order) ? n.order : 0,
      opStatus: val(n?.op_status) ?? "unknown",
      badges: strs(n?.badges, `cable_map.nodes[host=${host}].badges`),
      platform: val(d?.platform),
      model: val(d?.model),
      serial: val(d?.serial_number) ?? val(d?.chassis_serial),
      swVersion: val(d?.sw_version),
      uptime: val(d?.uptime),
      powerSupplies: num(d?.num_power_supplies),
      modules: num(d?.num_modules),
      score: Number.isFinite(h?.score) ? h.score : null,
      band: term(h?.band, `health_scores[switch=${host}].band`),
      criticality: Number.isFinite(h?.criticality) ? h.criticality : null,
      dataQuality: Number.isFinite(h?.data_quality) ? h.data_quality : null,
      deductions: strs(h?.deductions, `health_scores[switch=${host}].deductions`),
      impact: fi
        ? {
            severity: val(fi.severity),
            vlans: num(fi.vlans_impacted),
            stranded: num(fi.stranded),
            hard: num(fi.hard),
            backup: num(fi.backup),
            fhrp: num(fi.fhrp),
            detail: val(fi.detail),
            cite: `failure_impact[host=${host}]`,
          }
        : null,
      fieldCites: deviceFieldCites(host, d, n, h),
      cite: d ? `devices.${host}` : `cable_map.nodes[host=${host}]`,
    };
  });

  /* The source records the device fields above were read from, compiled under the SAME path the
     citations name, so a citation into them resolves inside the model to the very record that carries
     the figure. Only the fields the compiler reads are carried; nothing is defaulted — absent is null. */
  const cableMapNodes = cableNodes.map((n) => ({
    host: n.host,
    kind: val(n.kind),
    role: val(n.role),
    tier: Number.isFinite(n.tier) ? n.tier : null,
    order: Number.isFinite(n.order) ? n.order : null,
    collected: typeof n.collected === "boolean" ? n.collected : null,
    opStatus: val(n.op_status),
    badges: strs(n.badges, `cable_map.nodes[host=${n.host}].badges`),
    cite: `cable_map.nodes[host=${n.host}]`,
  }));
  const healthScores = arr(snap.health_scores).map((h) => ({
    switch: h.switch,
    role: val(h.role),
    score: Number.isFinite(h.score) ? h.score : null,
    band: val(h.band),
    criticality: Number.isFinite(h.criticality) ? h.criticality : null,
    dataQuality: Number.isFinite(h.data_quality) ? h.data_quality : null,
    deductions: strs(h.deductions, `health_scores[switch=${h.switch}].deductions`),
    cite: `health_scores[switch=${h.switch}]`,
  }));

  /* links ------------------------------------------------------------------ */
  /** @param {unknown} a @param {unknown} ap @param {unknown} b @param {unknown} bp */
  const centralityKey = (a, ap, b, bp) => [`${a}|${ap}`, `${b}|${bp}`].sort().join("::");
  /* The engine's own link_centrality rows, compiled under their source path (acceptance B6). */
  const linkCentrality = arr(snap.link_centrality).map((c, k) => ({
    aHost: val(c.a_host),
    aPort: val(c.a_port),
    bHost: val(c.b_host),
    bPort: val(c.b_port),
    betweenness: Number.isFinite(c.betweenness) ? c.betweenness : null,
    isBridge: typeof c.is_bridge === "boolean" ? c.is_bridge : null,
    pairsCut: Number.isFinite(c.pairs_cut) ? c.pairs_cut : null,
    rank: Number.isFinite(c.rank) ? c.rank : null,
    cite: `link_centrality[${k}]`,
  }));
  /** @type {Map<string, { row: any, k: number }>} */
  const centrality = new Map();
  arr(snap.link_centrality).forEach((c, k) => {
    centrality.set(centralityKey(c.a_host, c.a_port, c.b_host, c.b_port), { row: c, k });
  });
  const links = arr(snap.cable_map?.cables).map((c, i) => {
    const hit = centrality.get(centralityKey(c.a, c.a_port, c.b, c.b_port));
    const cen = hit?.row;
    return {
      id: `L${i}`,
      a: c.a,
      aPort: val(c.a_port),
      b: c.b,
      bPort: val(c.b_port),
      isPortChannel: Boolean(c.is_pc),
      /* A member is a PAIR of ports, not a name ("Po1 ↔ Po1"); a member whose ports are BOTH
         unobserved contributes nothing, which keeps DevicePane's "members not observed" reachable. */
      members: arr(c.members)
        .map((m, mi) => {
          if (typeof m === "string" || typeof m === "number") return strs([m], `cable_map.cables[${i}].members[${mi}]`)[0] ?? null;
          const a = val(m?.a_port);
          const b = val(m?.b_port);
          if (a === null && b === null) return null;
          return `${a ?? "port not observed"} ↔ ${b ?? "port not observed"}`;
        })
        .filter((m) => m !== null),
      speedMbps: num(c.speed),
      opStatus: val(c.op_status) ?? "unknown",
      confirmation: val(c.confirmation),
      betweenness: cen && Number.isFinite(cen.betweenness) ? cen.betweenness : null,
      /* The one field on this object whose FALSE value is a safety claim ("a redundant path exists
         around this link"). `Boolean(undefined)` would publish that claim from a missing field, so
         it is read as a boolean or not at all — the same guard its numeric siblings already carry. */
      isBridge: cen && typeof cen.is_bridge === "boolean" ? cen.is_bridge : null,
      pairsCut: cen && Number.isFinite(cen.pairs_cut) ? cen.pairs_cut : null,
      centralityRank: cen && Number.isFinite(cen.rank) ? cen.rank : null,
      /* The link_centrality row the four figures above were read from, or null when the engine
         scored no such cable. */
      centralityCite: hit ? `link_centrality[${hit.k}]` : null,
      cite: `cable_map.cables[${i}]`,
    };
  });

  /* findings (punchlist) --------------------------------------------------- */
  arr(snap.punchlist).forEach((p, i) => {
    const unknownKeys = Object.keys(obj(p)).filter((k) => !Object.hasOwn(PUNCHLIST_FIELDS, k));
    if (unknownKeys.length > 0) {
      throw new CompileError(
        "E_UNKNOWN_PRODUCER_FIELD",
        `punchlist[${i}] carries producer field(s) this compiler does not compile: ${unknownKeys.join(", ")}. ` +
          `Compile them (and add them to PUNCHLIST_FIELDS) rather than dropping them.`,
        `punchlist[${i}]`,
      );
    }
  });
  const findings = arr(snap.punchlist).map((p, i) => {
    const ev = compileEvidence(obj(p), i, snap);
    return {
      id: `F${String(i + 1).padStart(3, "0")}`,
      /* null = the producer states NO severity (absent, "", "-", "N/A", [NOT OBSERVED]): NOT STATED, never a member.
         This read used to end `?? "Info"` — absence compiled to a low-risk grade (src/core/severity-absence.test.ts). */
      severity: term(p.severity, `punchlist[${i}].severity`),
      rank: num(p.rank),
      priority: num(p.priority),
      category: val(p.category),
      devices: strs(p.devices, `punchlist[${i}].devices`),
      wave: val(p.wave),
      title: val(p.title) ?? "(untitled finding)",
      detail: val(p.detail),
      remediation: val(p.remediation),
      /* The show-command the engine cites as this finding's evidence, or null when its category is a
         composite with no single backing command. A COMMAND NAME, not a record. */
      sourceCommand: val(p.source_command),
      /* Why the finding carries its severity, and how confident the evidence is — the producer's own
         words, or null where it published none. */
      severityBasis: text(p.severity_basis, `punchlist[${i}].severity_basis`),
      evidenceConfidence: text(p.evidence_confidence, `punchlist[${i}].evidence_confidence`),
      /* The evidence contract: every ref RESOLVED against this snapshot above; null = not emitted. */
      evidenceBasis: ev.basis,
      evidenceRefs: ev.refs,
      evidenceRefsTotal: ev.total,
      cite: `punchlist[${i}]`,
    };
  });

  const evidence = compileEvidenceRecords(findings, snap);

  const crossLayer = arr(snap.cross_layer).map((c, i) => ({
    id: val(c.id) ?? `CL-${i}`,
    severity: term(c.severity, `cross_layer[${i}].severity`), // null = not stated, never Info (as punchlist above)
    layers: val(c.layers),
    title: val(c.title) ?? "",
    detail: val(c.detail),
    recommendation: val(c.recommendation),
    hosts: strs(c.hosts, `cross_layer[${i}].hosts`),
    cite: `cross_layer[${i}]`,
  }));

  /* forwarding substrate: routes, ACLs, SVIs -------------------------------- */
  /* Keyed by snapshot names, so built by Object.fromEntries (see `own`, THE DICTIONARY RULE). */
  /** @type {Record<string, object[]>} */
  const routes = Object.fromEntries(
    Object.entries(obj(snap.routes)).map(([host, rs]) => [
      host,
      arr(rs)
        .map((r, i) => ({
          prefix: val(r.prefix),
          source: val(r.source),
          nextHop: val(r.next_hop),
          outIntf: val(r.out_intf),
          adminDistance: num(r.admin_distance),
          cite: `routes.${host}[${i}]`,
        }))
        .filter((r) => r.prefix),
    ]),
  );
  /* A match field may name an OBJECT-GROUP instead of an address/wildcard pair; dropping it made the
     application report a model gap as a collection gap. */
  /** @param {any} f  one `src`/`dst` match field from the snapshot, or nothing */
  const matchField = (f) => (f ? { ip: val(f.ip), wild: val(f.wild), group: val(f.group) } : null);

  /** @type {Record<string, Record<string, Array<{ unevaluable: boolean }>>>} */
  const acls = Object.fromEntries(
    Object.entries(obj(snap.acls)).map(([host, named]) => [
      host,
      Object.fromEntries(
        Object.entries(obj(named)).map(([name, lines]) => [
          name,
          arr(lines).map((l, i) => ({
            index: i,
            action: val(l.action),
            raw: val(l.raw),
            proto: val(l.proto),
            src: matchField(l.src),
            dst: matchField(l.dst),
            sport: l.sport ?? null,
            dport: l.dport ?? null,
            /* The producer's OWN verdict on whether it could model this line, plus the qualifiers that
               defeated it — ground truth, never re-derived from the raw text. */
            unevaluable: l.unevaluable === true,
            unmodeledQualifiers: strs(l.unmodeled_qualifiers, `acls.${host}.${name}[${i}].unmodeled_qualifiers`),
            /* established — stateful; icmpType — an unimplemented ICMP qualifier; timeRange — any verdict
               is conditional on a named window. */
            established: l.established === true,
            icmpType: val(l.icmp_type),
            timeRange: val(l.time_range),
            cite: `acls.${host}.${name}[${i}]`,
          })),
        ]),
      ),
    ]),
  );

  /** Object groups referenced by ACL match fields. */
  /** @type {Record<string, Record<string, object>>} */
  const objectGroups = Object.fromEntries(
    Object.entries(obj(snap.object_groups)).map(([host, groups]) => [
      host,
      Object.fromEntries(
        Object.entries(obj(groups)).map(([name, g]) => [
          name,
          {
            kind: val(g.kind),
            members: arr(g.members).map((m) => ({ ip: val(m.ip), wild: val(m.wild) })),
            cite: `object_groups.${host}.${name}`,
          },
        ]),
      ),
    ]),
  );
  const aclFindings = arr(snap.acl_line_reachability?.findings).map((f, i) => ({
    host: val(f.host),
    acl: val(f.acl),
    lineIndex: num(f.line_index),
    action: val(f.action),
    raw: val(f.raw),
    verdict: val(f.verdict),
    reason: val(f.reason),
    detail: val(f.detail),
    blockingLines: arr(f.blocking_lines),
    sourceCommand: val(f.source_command),
    cite: val(f.citation) ?? `acl_line_reachability.findings[${i}]`,
  }));

  const l3 = arr(snap.l3_forwarding).map((r, i) => ({
    host: val(r.switch),
    vlan: num(r.vlan),
    sviIp: val(r.svi_ip),
    fhrp: val(r.fhrp),
    fhrpRole: val(r.role),
    vip: val(r.vip),
    routingSource: val(r.routing_source),
    nextHop: val(r.next_hop),
    primarySubnet: val(r.primary_subnet),
    secondary: val(r.secondary),
    tracking: val(r.tracking),
    trackingUnobserved: reason(r.tracking),
    risk: val(r.risk),
    riskUnobserved: reason(r.risk),
    severity: val(r.severity),
    cite: `l3_forwarding[${i}]`,
  }));

  /* per-port and per-protocol evidence -------------------------------------- */
  /** @type {Record<string, object[]>} */
  const interfaces = Object.fromEntries(
    Object.entries(obj(snap.interfaces)).map(([host, ports]) => [
      host,
      Object.entries(obj(ports)).map(([port, p]) => ({
        port,
        status: val(p.status),
        duplex: val(p.duplex),
        speed: val(p.speed),
        portType: val(p.port_type),
        linkType: val(p.link_type),
        description: val(p.description),
        portChannel: val(p.port_channel),
        pcProtocol: val(p.port_channel_protocol),
        runConfigObserved: Boolean(p.run_config_observed),
        cite: `interfaces.${host}.${port}`,
      })),
    ]),
  );
  const physical = arr(snap.physical_health).map((p, i) => ({
    host: val(p.switch),
    port: val(p.port),
    status: val(p.status),
    speed: val(p.speed),
    duplex: val(p.duplex),
    media: val(p.media),
    inputErrors: num(p.input_errors),
    crcErrors: num(p.crc_errors),
    outputErrors: num(p.output_errors),
    lateCollisions: num(p.late_collisions),
    outputDrops: num(p.output_drops),
    poe: val(p.poe),
    risk: val(p.risk),
    /* The engine's own explanation for why this port has no counters, which `val()` nulls. */
    riskUnobserved: reason(p.risk),
    severity: val(p.severity),
    cite: `physical_health[${i}]`,
  }));
  const protocols = arr(snap.protocol_health).map((p, i) => ({
    host: val(p.switch),
    protocol: val(p.protocol),
    severity: val(p.severity),
    summary: val(p.summary),
    detail: val(p.detail),
    cite: `protocol_health[${i}]`,
  }));
  const endpoints = arr(snap.endpoint_identity).map((e, i) => ({
    host: val(e.host),
    port: val(e.port),
    vlan: val(e.vlan),
    ip: val(e.ip),
    mac: val(e.mac),
    macCount: num(e.mac_count),
    vendor: val(e.vendor),
    endpointClass: val(e.endpoint_class),
    confidence: val(e.confidence),
    evidence: val(e.evidence),
    cite: `endpoint_identity[${i}]`,
  }));

  /* coverage honesty: what the snapshot does NOT contain --------------------- */
  const coverage = {
    devicesInventoried: devices.filter((d) => d.inventoried).length,
    devicesOnTopologyOnly: devices.filter((d) => !d.inventoried).length,
    hostsWithRoutes: Object.keys(routes).length,
    hostsWithAcls: Object.keys(acls).length,
    hostsWithObjectGroups: Object.keys(objectGroups).length,
    /* Lines the PRODUCER could not model — the hot path for honesty. */
    aclLinesUnevaluable: Object.values(acls).flatMap((n) => Object.values(n).flat()).filter((l) => l.unevaluable).length,
    aclLinesTotal: Object.values(acls).flatMap((n) => Object.values(n).flat()).length,
    hostsWithInterfaces: Object.keys(interfaces).length,
    routableHosts: Object.keys(routes).sort(),
    aclHosts: Object.keys(acls).sort(),
    linksWithCentrality: links.filter((l) => l.betweenness !== null).length,
    aclSummary: obj(snap.acl_line_reachability?.summary),
    cite: "collection_completeness / coverage_matrix",
  };

  return {
    meta: {
      ...bindingMeta(binding),
      schema: val(snap.schema),
      /* Set only when a schema-less (legacy) snapshot was read under an explicit --allow-legacy: the
         schema this model ASSUMED, never one the snapshot stated. */
      schemaAssumed: opts.schemaAssumed ?? null,
      scriptVersion: val(snap.script_version),
      collectedAt: val(snap.collected_at),
      generatedAt: val(snap.generated_at),
    },
    tiers: arr(snap.cable_map?.tiers).map((t, i) => strs(t, `cable_map.tiers[${i}]`)),
    devices,
    links,
    findings,
    crossLayer,
    routes,
    acls,
    aclFindings,
    l3,
    objectGroups,
    interfaces,
    physical,
    protocols,
    endpoints,
    coverage,
    /* Source records the device and link figures were read from, under the paths their citations
       name (acceptance B6). Appended last so every earlier model path is unchanged. */
    cable_map: { nodes: cableMapNodes },
    health_scores: healthScores,
    link_centrality: linkCentrality,
    /* The records the findings' evidence pointers name, bounded (compileEvidenceRecords). Appended last so
       every earlier model path is unchanged. */
    evidenceRecords: evidence.records,
    evidenceProjection: evidence.projection,
  };
}

/* ── the forwarding sidecars ────────────────────────────────────────────────────────────────── */

/**
 * The interface ACL bindings (`ip access-group`) the snapshot carries, for the forwarding engine
 * (src/forwarding/acl-bindings.json). Every field is READ, never defaulted: a port whose running
 * configuration was not observed carries `runConfigObserved: false`, read by the engine as "binding
 * unknown", never as "no ACL here".
 * @param {Record<string, any>} snap @param {Binding} binding
 */
export function compileAclBindings(snap, binding) {
  /** @param {unknown} v @returns {string | null} */
  const sval = (v) => {
    if (v === undefined || v === null) return null;
    if (typeof v !== "string") return null;
    const t = v.trim();
    if (t === "" || t === "-" || t === "N/A" || NOT_OBSERVED.test(t)) return null;
    return t;
  };
  /** @param {unknown} v @returns {string[]} */
  const list = (v) => (sval(v) ?? "").split(",").map((s) => s.trim()).filter((s) => s !== "");
  /* Keyed by snapshot names, so built by Object.fromEntries (see `own`, THE DICTIONARY RULE). */
  /** @type {Record<string, Array<Record<string, unknown>>>} */
  const hosts = Object.fromEntries(
    Object.entries(obj(snap.interfaces))
      .sort(([a], [b]) => byName(a, b))
      .map(([host, ports]) => [
        host,
        Object.entries(obj(ports)).map(([port, p]) => ({
          port,
          vlan: sval(p.vlan),
          switchportMode: sval(p.switchport_mode),
          aclIn: sval(p.acl_in),
          aclOut: sval(p.acl_out),
          gateCandidates: list(p.forwarding_gate_candidates),
          gateUnmodeled: list(p.forwarding_gate_unmodeled),
          runConfigObserved: p.run_config_observed === true,
          cite: `interfaces.${host}.${port}`,
        })),
      ]),
  );
  return { meta: bindingMeta(binding), hosts };
}

/**
 * The evidence that says whether a collected routing table is COMPLETE (src/forwarding/rib-evidence.json).
 * Which protocol families populate a table is not a list written here: it is the set of protocol keys
 * the producer itself uses in `routing_neighbors` records. If there are none the set is empty, and the
 * engine reads that as "completeness unknown", not "complete".
 * @param {Record<string, any>} snap @param {Binding} binding
 */
export function compileRibEvidence(snap, binding) {
  /** @param {unknown} v @returns {string | null} */
  const str = (v) => (typeof v === "string" && v.trim() !== "" ? v.trim() : null);
  /** @param {unknown} v @returns {number | null} */
  const finite = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

  const neighbours = obj(snap.routing_neighbors);
  const routingProtocols = [
    ...new Set(Object.values(neighbours).flatMap((rec) => Object.keys(obj(rec)).map((k) => k.toLowerCase()))),
  ].sort();

  /**
   * @typedef {{ protocol: string; state: string | null; reason: string | null; cite: string }} ProtocolRow
   * @typedef {{ protocol: string; neighbor: string | null; state: string | null; cite: string; address: string | null; interface: string | null }} Adjacency
   * @typedef {{ kind: string; neighbor: string | null; state: string | null; prefixes: number | null; cite: string }} OverlayPeer
   * @typedef {{ protocols: ProtocolRow[]; adjacencies: Adjacency[]; overlay: OverlayPeer[] }} HostEvidence
   */
  /* Accumulated per snapshot host name, so in a Map (see `own`, THE DICTIONARY RULE): `hosts[h] ??= …` on a plain
     object handed back Object.prototype for a host named "__proto__" (and the Object function for "constructor"). */
  /** @type {Map<string, HostEvidence>} */
  const hosts = new Map();
  /** @param {string} h @returns {HostEvidence} */
  const at = (h) => {
    let e = hosts.get(h);
    if (e === undefined) {
      e = { protocols: [], adjacencies: [], overlay: [] };
      hosts.set(h, e);
    }
    return e;
  };

  /* Every protocol_assessability row's state is one the engine contract names (the engine grows this set —
     e.g. "not_running" — and a state this compiler has never heard of must not pass as a string it renders
     without knowing its meaning). Checked on EVERY row, not only the routing rows compiled below. Absent or
     null stays null: "not stated", never a state. */
  arr(obj(snap.protocol_assessability).rows).forEach((r, i) => {
    const s = obj(r).state;
    if (s !== undefined && s !== null && (typeof s !== "string" || !PROTOCOL_ASSESSABILITY_STATES.includes(s))) {
      throw new CompileError(
        "E_PROTOCOL_STATE",
        `protocol_assessability.rows[${i}].state is ${JSON.stringify(s)}, which the engine contract does not name ` +
          `(it names ${PROTOCOL_ASSESSABILITY_STATES.join(", ")}). Regenerate the contract from the engine, or fix the producer.`,
        `protocol_assessability.rows[${i}].state`,
      );
    }
  });
  arr(obj(snap.protocol_assessability).rows).forEach((r, i) => {
    const host = str(obj(r).switch);
    const protocol = str(obj(r).protocol);
    if (host === null || protocol === null) return;
    if (!routingProtocols.includes(protocol.toLowerCase())) return;
    at(host).protocols.push({ protocol, state: str(r.state), reason: str(r.reason), cite: `protocol_assessability.rows[${i}]` });
  });

  for (const [host, rec] of Object.entries(neighbours)) {
    for (const [protocol, list] of Object.entries(obj(rec))) {
      arr(list).forEach((n, i) => {
        at(host).adjacencies.push({
          protocol: protocol.toLowerCase(),
          neighbor: str(obj(n).neighbor),
          state: str(obj(n).state),
          cite: `routing_neighbors.${host}.${protocol}[${i}]`,
          address: str(obj(n).address),
          interface: str(obj(n).interface),
        });
      });
    }
  }

  for (const [host, rec] of Object.entries(obj(snap.overlay))) {
    arr(obj(rec).evpn_neighbors).forEach((n, i) => {
      at(host).overlay.push({
        kind: "evpn",
        neighbor: str(obj(n).neighbor),
        state: str(obj(n).state),
        prefixes: finite(obj(n).prefixes),
        cite: `overlay.${host}.evpn_neighbors[${i}]`,
      });
    });
  }

  const sorted = Object.fromEntries([...hosts].sort(([a], [b]) => byName(a, b)));
  return {
    meta: { ...bindingMeta(binding), routingProtocols, routingProtocolsFrom: "routing_neighbors" },
    hosts: sorted,
  };
}

/**
 * Which producer fields the collector ACTUALLY EMITTED, for the compiled fields `compileFabric` fills
 * in when the source key is absent (src/panels/producer-emission.json). It names the defaulting sites
 * found on 2026-09-22 (ACL lines: unevaluable, unmodeled_qualifiers, established; devices: the
 * health_scores record). A bounded list, not a proof that no other compiled field is defaulted:
 * `src/panels/producer-emission.test.ts` re-reads the source and checks each LISTED field on every record.
 * @param {Record<string, any>} snap @param {Binding} binding
 */
export function compileProducerEmission(snap, binding) {
  const ACL_LINE_FIELDS = { unevaluable: "unevaluable", unmodeledQualifiers: "unmodeled_qualifiers", established: "established" };
  const DEVICE_HEALTH_FIELDS = { deductions: "deductions" };

  /* Both tables are keyed by snapshot names, so accumulated in Maps (see `own`, THE DICTIONARY RULE). */
  /** @type {Map<string, string[]>} cite -> compiled fields whose source key was NOT emitted */
  const aclLineAbsent = new Map();
  for (const [host, lists] of Object.entries(obj(snap.acls))) {
    for (const [name, lines] of Object.entries(obj(lists))) {
      arr(lines).forEach((l, i) => {
        const rec = obj(l);
        const missing = Object.entries(ACL_LINE_FIELDS)
          .filter(([, key]) => !Object.prototype.hasOwnProperty.call(rec, key))
          .map(([field]) => field)
          .sort();
        if (missing.length > 0) aclLineAbsent.set(`acls.${host}.${name}[${i}]`, missing);
      });
    }
  }

  /** @type {Map<string, string[]>} host -> compiled device fields whose source was NOT emitted */
  const deviceAbsent = new Map();
  const health = new Map();
  for (const h of arr(snap.health_scores)) if (typeof obj(h).switch === "string") health.set(h.switch, obj(h));
  const hosts = new Set([
    ...Object.keys(obj(snap.devices)),
    ...arr(obj(snap.cable_map).nodes).map((n) => obj(n).host).filter((h) => typeof h === "string"),
  ]);
  for (const host of [...hosts].sort()) {
    const h = health.get(host);
    const missing = Object.entries(DEVICE_HEALTH_FIELDS)
      .filter(([, key]) => h === undefined || !Object.prototype.hasOwnProperty.call(h, key))
      .map(([field]) => field)
      .sort();
    if (missing.length > 0) deviceAbsent.set(host, missing);
  }

  /** @param {Map<string, string[]>} m */
  const sortObj = (m) => Object.fromEntries([...m].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
  return {
    meta: { ...bindingMeta(binding), aclLineFields: ACL_LINE_FIELDS, deviceHealthFields: DEVICE_HEALTH_FIELDS },
    aclLineAbsent: sortObj(aclLineAbsent),
    deviceAbsent: sortObj(deviceAbsent),
  };
}

/* ── the set ────────────────────────────────────────────────────────────────────────────────── */

/**
 * The four compiled documents: where each is tracked for the sample build, its file name in an
 * output directory, and its exact serialisation (unchanged from the four compilers this replaces,
 * which is what keeps the shipped files byte-identical).
 */
export const OUTPUTS = Object.freeze([
  Object.freeze({ key: "fabric", file: "fabric.json", trackedPath: "src/data/fabric.json" }),
  Object.freeze({ key: "aclBindings", file: "acl-bindings.json", trackedPath: "src/forwarding/acl-bindings.json" }),
  Object.freeze({ key: "ribEvidence", file: "rib-evidence.json", trackedPath: "src/forwarding/rib-evidence.json" }),
  Object.freeze({ key: "producerEmission", file: "producer-emission.json", trackedPath: "src/panels/producer-emission.json" }),
]);

/**
 * Compile the whole set from ONE parsed snapshot and ONE binding. Refuses an empty fabric
 * (E_EMPTY_FABRIC): a model with no device is not an empty network, it is not a network at all, and
 * the 3-D layout cannot place it ("layout: no tiers to lay out").
 * @param {Record<string, any>} snap  a validated snapshot (validate-snapshot.mjs `assertValidSnapshot`)
 * @param {Binding} binding
 * @param {{ schemaAssumed?: string | null }} [opts]
 */
export function compileAll(snap, binding, opts = {}) {
  try {
    const fabric = compileFabric(snap, binding, opts);
    if (fabric.devices.length === 0) {
      throw new CompileError(
        "E_EMPTY_FABRIC",
        "the snapshot names no device (no `devices` inventory and no `cable_map.nodes`). There is nothing to draw, " +
          "and an empty model would read as an empty network rather than as missing evidence.",
        "devices",
      );
    }
    return {
      fabric,
      aclBindings: compileAclBindings(snap, binding),
      ribEvidence: compileRibEvidence(snap, binding),
      producerEmission: compileProducerEmission(snap, binding),
    };
  } catch (e) {
    if (e instanceof CompileError) throw e;
    /* THE CLASS, not the instances: a record that is not the shape a reader expects (a null list
       element, a string where a record belongs) surfaces as a TypeError somewhere in the readers, and is
       refused with one code rather than escaping as a raw runtime error. ONLY a TypeError: any other
       failure (a ReferenceError, a RangeError …) is not evidence about the input and propagates as it is
       (verifier S1-V8). And a TypeError can itself be a compiler defect, so the refusal says so and keeps
       the original error as its cause. */
    if (!(e instanceof TypeError)) throw e;
    throw new CompileError(
      "E_SNAPSHOT_SHAPE",
      `this snapshot could not be read: a record is not the shape the engine writes, or the compiler has a defect ` +
        `(TypeError: ${e.message}).`,
      null,
      [],
      { cause: e },
    );
  }
}

/**
 * The exact text of each compiled document, keyed like OUTPUTS: fabric compact, the sidecars indented
 * by one space with a trailing newline — the forms the tracked files have always had.
 * @param {ReturnType<typeof compileAll>} set
 * @returns {{ fabric: string; aclBindings: string; ribEvidence: string; producerEmission: string }}
 */
export function serialiseCompiled(set) {
  return {
    fabric: JSON.stringify(set.fabric),
    aclBindings: JSON.stringify(set.aclBindings, null, 1) + "\n",
    ribEvidence: JSON.stringify(set.ribEvidence, null, 1) + "\n",
    producerEmission: JSON.stringify(set.producerEmission, null, 1) + "\n",
  };
}
