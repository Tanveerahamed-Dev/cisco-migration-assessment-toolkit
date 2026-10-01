/**
 * provenance.test.ts — the source binding, checked instead of displayed.
 *
 * WHAT WAS WRONG. `fabric.meta.sourceSha256` is shown on six surfaces, and the Inspector tells the
 * reader "the sha256 is what binds what you are reading to those exact bytes". That digest was
 * READ OUT OF `fabric.json` — the very file it is supposed to bind — and nothing anywhere
 * recomputed or compared it. `grep -rn "createHash|subtle.digest" src/` returned zero; no test
 * hashed anything. Hand-edit one route, one ACL line or one finding in `src/data/fabric.json`
 * without re-running the compiler and every surface keeps displaying the same digest, the whole
 * suite stays green, and the rendered model no longer corresponds to any snapshot that exists.
 * A self-asserted digest is a decoration.
 *
 * WHAT THIS CHECKS, in the order the chain runs:
 *
 *   1. The named source file exists at the path the compiler reads, and `meta.source` names it.
 *   2. Its sha256 and byte length, recomputed here, equal what `meta` claims.
 *   3. The shipped `fabric.json` is BYTE-IDENTICAL to what the compiler produces from that file —
 *      run in a sandbox copy, so the check cannot damage the thing it is checking.
 *
 * Step 3 is what turns the digest into a binding rather than a label: it is the assertion that
 * fails if anyone edits the compiled model by hand.
 *
 * WHY AN ABSENT SOURCE IS A FAILURE, NOT A SKIP. The source resolves OUTSIDE this package
 * (`../../webapp/sample_data/…`), so a standalone copy of `atlas-scope` cannot reproduce its own
 * data. Where the file is missing the binding claim is unverifiable — and an unverifiable claim
 * that the product keeps displaying is exactly the false-health shape this codebase exists to
 * refuse. It fails, and it says why.
 *
 * WHAT IT DOES NOT CHECK. That the COMPILER is right — that its reading of the snapshot is a
 * faithful one. That is what the citation tests and the coverage tests are for. This file only
 * establishes that what ships is what that compiler produced from the bytes it names.
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { SOURCE_BINDING_BYTE_KEYS } from "./types";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, "..", ".."); // atlas-scope/
const COMPILER = resolve(PKG, "tools", "compile-snapshot.mjs");
const MODEL = resolve(PKG, "src", "data", "fabric.json");

/* WHICH snapshot the tracked model is compiled from. The TRACKED compiled files may only ever be the
   sample's: they are committed, and compiling anything else into them would put client data one
   `git add` from the history (tools/lib/compile-io.mjs refuses it). That scoping is asserted in the
   first test below, against this literal, written independently of `tools/source-binding.mjs
   SOURCE_REL` so a change to either side shows up as a disagreement rather than both moving together.
   Everything else in this file reads the dataset under test — the file `meta.source` names — rather
   than this path (R7). */
const SAMPLE_REL = "webapp/sample_data/sample_fleet.snapshot.json";
const REPO = resolve(PKG, "..");

const sha256 = (buf: Buffer): string => createHash("sha256").update(buf).digest("hex");

/* THE FORM THAT BINDS (acceptance F5 / open-issues O15). The digest used to be taken over the raw
   bytes on disk, which on a Windows checkout are the CRLF working-tree bytes (`9cc348bd…5dfd`), while
   the committed blob is LF (`9580aa09…3089`): the binding held on this host's disk and on no clone.
   It is now taken over the LF-normalised bytes — every CRLF pair read as LF, byte-level, nothing else
   touched — which is what Git stores for a text blob, so the recorded digest equals
   `git cat-file blob HEAD:<source> | sha256sum` and does not depend on the checkout's line endings.
   Written here INDEPENDENTLY of `tools/source-binding.mjs` (latin1 is a byte-preserving decode), so
   the compiler's rule and this oracle disagree rather than move together. */
const DIGEST_FORM = "lf-normalised";
const lfNormalised = (buf: Buffer): Buffer => Buffer.from(buf.toString("latin1").split("\r\n").join("\n"), "latin1");
const crlfOf = (buf: Buffer): Buffer => Buffer.from(lfNormalised(buf).toString("latin1").split("\n").join("\r\n"), "latin1");

/* THE BYTE-DEPENDENT KEYS (owner decision R3, verifier S1-R2V-4). `sourceExactSha256` is sha256 of the bytes
   AS READ, so a compile of a CRLF checkout and one of an LF checkout differ in exactly that value and in
   nothing else. A compile-identity check across checkouts therefore compares the compiled bytes with the
   value of each key in SOURCE_BINDING_BYTE_KEYS replaced by a placeholder — every other byte is still
   compared exactly — and then checks each masked value separately against the bytes that compile read.
   The masking must hit exactly one occurrence per key, so it can never be vacuous. */
const MASK = "<byte-dependent>";
function maskByteKeys(compiledFile: Buffer): { masked: Buffer; values: Record<string, string> } {
  let text = compiledFile.toString("utf8");
  const values: Record<string, string> = {};
  for (const k of SOURCE_BINDING_BYTE_KEYS) {
    const re = new RegExp(`("${k}":\\s*)"([^"]*)"`, "g");
    const hits = [...text.matchAll(re)];
    expect(hits.length, `${k} occurs exactly once in the compiled file`).toBe(1);
    values[k] = hits[0]![2]!;
    text = text.replace(re, `$1"${MASK}"`);
  }
  return { masked: Buffer.from(text, "utf8"), values };
}
/** The compiled file's content is the same, and each byte-dependent key names the bytes its compile read. */
function sameContentAcrossCheckouts(a: { out: Buffer; read: Buffer }, b: { out: Buffer; read: Buffer }): boolean {
  const ma = maskByteKeys(a.out);
  const mb = maskByteKeys(b.out);
  expect(ma.values.sourceExactSha256, "the first compile's exact digest is of ITS bytes").toBe(`sha256:${sha256(a.read)}`);
  expect(mb.values.sourceExactSha256, "the second compile's exact digest is of ITS bytes").toBe(`sha256:${sha256(b.read)}`);
  return sha256(ma.masked) === sha256(mb.masked);
}

/* THE TRACKED MODEL, READ FROM DISK — never through the `../data/fabric.json` import. Every gate in this file
   compares the TRACKED files (MODEL, SRC_DIR) against a compile of the source their meta names. Under a phase
   leg's dataset override (vitest.config.ts, ATLAS_DATASET_DIR) that import resolves to ANOTHER dataset, and the
   file then compared the tracked bytes against a compile of the other dataset's source (the golden leg: 18 reds,
   the rename leg: an unlocatable external file name) — two datasets in one comparison. What this file certifies is
   a property of what the repository ships, so it holds, and runs, on every leg (phase 3.5 close, 2026-09-30). */
const fabric = JSON.parse(readFileSync(MODEL, "utf8")) as { meta: Record<string, unknown> };
const meta = fabric.meta as {
  source: string;
  sourceOrigin: string;
  sourceBytes: number;
  sourceSha256: string;
  sourceDigestForm: string;
};
/* The dataset under test: the file the shipped model names, resolved from the repository root. */
const SOURCE = resolve(REPO, meta.source);

const sandboxes: string[] = [];
afterAll(() => {
  for (const dir of sandboxes) rmSync(dir, { recursive: true, force: true });
});

/* ── The gate, as functions ─────────────────────────────────────────────────────────────────────
 *
 * The comparisons below used to live inline in the passing tests, and the "failure path" tests
 * then flipped a byte and asserted `sha256(copy) !== sha256(original)` — which tests SHA-256, not
 * this gate. A tampered input never went through the comparison the product relies on. So the
 * comparison is factored out ONCE, the passing test calls it on the shipped bytes, and the failure
 * tests call the very same function on tampered bytes and assert that it REJECTS. */

/**
 * Run the real compiler in a sandbox against `sourceBytes` and return the model it writes. `via` "tracked" is
 * the default run, which writes the tracked path; "out" compiles with --out to a directory outside src/. The
 * tracked path takes ONLY the committed (LF) form — a CRLF checkout is refused there (E_TRACKED_SOURCE_FORM,
 * verifier R3-V4: the byte-dependent key would otherwise put this checkout's line endings into committed
 * files) — so a compile of a CRLF checkout, for the O15 identity check, goes through --out.
 */
const compiled = new Map<string, Buffer>();
function compileInSandbox(sourceBytes: Buffer, via: "tracked" | "out" = "tracked"): Buffer {
  const key = `${via}:${sha256(sourceBytes)}`;
  const hit = compiled.get(key);
  if (hit !== undefined) return hit;
  /* Same relative layout the compiler resolves against, so this can never overwrite the shipped
     model — a check that rewrites its own subject would certify whatever it just wrote. */
  const root = mkdtempSync(join(tmpdir(), "atlas-provenance-"));
  sandboxes.push(root);
  mkdirSync(join(root, "atlas-scope", "tools"), { recursive: true });
  mkdirSync(dirname(join(root, meta.source)), { recursive: true });
  cpSync(COMPILER, join(root, "atlas-scope", "tools", "compile-snapshot.mjs"));
  for (const helper of HELPERS) cpSync(join(TOOLS, helper), join(root, "atlas-scope", "tools", helper), { recursive: true });
  cpSync(CONTRACTS, join(root, "atlas-scope", "contracts"), { recursive: true }); // data the compiler imports
  writeFileSync(join(root, meta.source), sourceBytes);
  const outDir = join(root, "atlas-scope", "compiled-out");
  execFileSync(process.execPath, [join(root, "atlas-scope", "tools", "compile-snapshot.mjs"), ...(via === "out" ? ["--out", outDir] : [])], { stdio: "pipe" });
  const out = readFileSync(via === "out" ? join(outDir, "fabric.json") : join(root, "atlas-scope", "src", "data", "fabric.json"));
  compiled.set(key, out);
  return out;
}

/** Gate 1: the model on disk is exactly what the compiler produces from the named source. */
function modelIsCompilerOutput(model: Buffer, sourceBytes: Buffer): { ok: boolean; rebuiltBytes: number } {
  const rebuilt = compileInSandbox(sourceBytes);
  return { ok: sha256(rebuilt) === sha256(model), rebuiltBytes: rebuilt.byteLength };
}

/** Gate 2: the source bytes are the ones `meta` claims — the form, the digest and the length, all
    three of the LF-normalised bytes. */
function sourceMatchesMeta(sourceBytes: Buffer, m: typeof meta): boolean {
  const canonical = lfNormalised(sourceBytes);
  return m.sourceDigestForm === DIGEST_FORM && canonical.byteLength === m.sourceBytes && sha256(canonical) === m.sourceSha256;
}

/** Gate 3: one compiled file on disk is exactly the bytes its compiler just produced. The per-file
    comparison every sidecar check below uses — factored out so the tamper test goes through IT. */
function fileIsCompilerOutput(shipped: Buffer, rebuilt: Buffer): boolean {
  return shipped.byteLength === rebuilt.byteLength && sha256(shipped) === sha256(rebuilt);
}

describe("the source binding the whole product displays", () => {
  it("finds the snapshot the compiler names, at the path it reads it from", () => {
    expect(
      existsSync(SOURCE),
      `the evidence snapshot this model claims to be compiled from is not at ${SOURCE}.\n` +
        `Until it is, \`meta.sourceSha256\` is a string this file asserts about itself and the\n` +
        `Inspector's "recompile from a file with that digest and you reproduce this model" is\n` +
        `unverifiable. That is a failure, not a skip.`,
    ).toBe(true);
    // ...and the TRACKED model names the sample, relatively, as a repository file — never client data.
    expect(meta.source).toBe(SAMPLE_REL);
    expect(meta.sourceOrigin).toBe("repository-file");
  });

  it("recomputes the displayed sha256 and byte length from the source bytes and gets the same answer", () => {
    const raw = readFileSync(SOURCE);
    expect(meta.sourceDigestForm, "meta must say which form of the bytes its digest binds").toBe(DIGEST_FORM);
    expect(sha256(lfNormalised(raw))).toBe(meta.sourceSha256);
    expect(lfNormalised(raw).byteLength).toBe(meta.sourceBytes);
    expect(statSync(SOURCE).size).toBeGreaterThanOrEqual(meta.sourceBytes); // CRLF on disk can only be longer
    expect(sourceMatchesMeta(raw, meta)).toBe(true);
    /* The TRACKED model is compiled from the committed bytes of the sample (the LF form Git stores), so
       its byte-dependent exact digest is theirs — whatever line endings this checkout renders. */
    expect((fabric.meta as { sourceExactSha256: string }).sourceExactSha256).toBe(`sha256:${sha256(lfNormalised(raw))}`);
  });

  it("binds the same digest whether the checkout has CRLF or LF line endings (O15)", () => {
    const raw = readFileSync(SOURCE);
    const lf = lfNormalised(raw);
    const crlf = crlfOf(raw);
    // Precondition: the two forms really differ on disk, so agreement below is not vacuous.
    expect(crlf.byteLength).toBeGreaterThan(lf.byteLength);
    expect(sha256(crlf)).not.toBe(sha256(lf));
    expect(sourceMatchesMeta(lf, meta), "an LF checkout (a Linux/macOS clone, or the committed blob)").toBe(true);
    expect(sourceMatchesMeta(crlf, meta), "a CRLF checkout (Windows autocrlf)").toBe(true);
    /* And the COMPILER agrees: both checkouts compile to one model, byte-identical apart from the
       byte-dependent binding keys, each of which names the bytes its own compile read (see maskByteKeys). */
    expect(sameContentAcrossCheckouts({ out: compileInSandbox(crlf, "out"), read: crlf }, { out: compileInSandbox(lf, "out"), read: lf })).toBe(true);
    // The tracked model IS the compile of the committed (LF) bytes, on every byte — its exact digest included —
    // and the --out compile of those bytes is the same file (the destination changes nothing in the content).
    expect(sha256(compileInSandbox(lf))).toBe(sha256(readFileSync(MODEL)));
    expect(sha256(compileInSandbox(lf, "out"))).toBe(sha256(readFileSync(MODEL)));
  });

  it("ships a model that is byte-identical to what the compiler produces from that source", () => {
    /* THE ASSERTION THAT MAKES THE DIGEST MEAN SOMETHING. */
    const shipped = readFileSync(MODEL);
    /* From the COMMITTED bytes (the LF form Git stores): that is what the tracked model is compiled from,
       and on an LF checkout (this one) it is the file on disk byte for byte. */
    const verdict = modelIsCompilerOutput(shipped, lfNormalised(readFileSync(SOURCE)));
    expect(
      verdict.ok,
      "src/data/fabric.json is NOT what tools/compile-snapshot.mjs produces from the snapshot it\n" +
        "names. Either the model was edited by hand — in which case every sha256 the product\n" +
        "displays is now a claim about bytes this model did not come from — or the compiler\n" +
        `changed and the model was not regenerated. Shipped ${shipped.byteLength} bytes, rebuilt ` +
        `${verdict.rebuiltBytes} bytes.`,
    ).toBe(true);
  });

  it("detects a hand-edited model — the failure path, executed through the same gate", () => {
    /* A gate whose red path never runs is not a gate. One same-length character edit inside the
       devices collection, then the SAME `modelIsCompilerOutput` the test above passes — which must
       now reject, against a real compiler run. */
    const shipped = readFileSync(MODEL);
    const tampered = Buffer.from(shipped);
    const at = tampered.indexOf(Buffer.from('"devices"'));
    expect(at, "the model must contain a devices collection to tamper with").toBeGreaterThan(0);
    tampered[at + 2] = (tampered[at + 2] ?? 0) === 0x65 ? 0x66 : 0x65; // flip one character
    expect(tampered.byteLength).toBe(shipped.byteLength);
    expect(modelIsCompilerOutput(tampered, readFileSync(SOURCE)).ok).toBe(false);
  });

  it("is bound to bytes, not to a length: a same-size source difference is rejected by the binding", () => {
    /* sourceBytes alone would accept any edit that preserved the length. The same-size edit goes
       through `sourceMatchesMeta` — the binding the passing test above uses — and must be refused. */
    const raw = readFileSync(SOURCE);
    const altered = Buffer.from(raw);
    let at = Math.floor(altered.byteLength / 2);
    // Flip a byte that is not part of a line ending, so the edit cannot change the normalised length.
    while (altered[at] === 0x0d || altered[at] === 0x0a || altered[at] === 0x0c || altered[at] === 0x0b) at += 1;
    altered[at] = ((altered[at] ?? 0) ^ 0x01) & 0xff;
    expect(altered.byteLength).toBe(raw.byteLength);
    expect(lfNormalised(altered).byteLength).toBe(meta.sourceBytes);
    expect(sourceMatchesMeta(altered, meta)).toBe(false);
  });
});

/* ── Nothing outside the compiled files pins the snapshot's digest ─────────────────────────────
 *
 * WHAT WAS WRONG. When the bound form changed (O15) the displayed tag changed with it, and three
 * places still carried the old one as a literal: `review/layout-guard.mjs` defaulted its URL
 * envelope to the old 12-character tag `snap=9cc348bd…` (every run would have opened a snapshot-mismatch page), and
 * `src/fabric3d/devHandle.ts`/`.test.ts` carried it in example URLs. A literal copy of a digest is a
 * cache that nothing invalidates. So the rule is structural: in every authored code file of the tree
 * — found with `git ls-files -co --exclude-standard`, not listed — no hex literal of 8 or more
 * characters may be a prefix of the bound digest, or of this checkout's working-tree digest (the
 * form that used to be bound). The compiled JSON files are where the digest lives; Markdown records
 * measurements. An abbreviated citation (`9cc348bd…5dfd`, hex followed by an ellipsis) is prose
 * that cannot be used as a value, and is allowed. */
describe("no authored code file pins the snapshot digest", () => {
  it("every snap tag and digest is derived from the compiled meta, never typed in", () => {
    const listed = execFileSync("git", ["ls-files", "-co", "--exclude-standard", "-z"], { cwd: PKG, encoding: "utf8" })
      .split("\0")
      .filter((p) => /\.(ts|tsx|mts|cts|js|mjs|cjs|html)$/.test(p))
      .filter((p) => existsSync(resolve(PKG, p)));
    expect(listed, "the scan must see this file itself (not vacuous)").toContain("src/core/provenance.test.ts");
    expect(listed).toContain("review/layout-guard.mjs");
    const raw = readFileSync(SOURCE);
    const digests = [meta.sourceSha256, sha256(raw)];
    const HEX = /(?<![0-9a-fA-F])([0-9a-f]{8,64})(?![0-9a-fA-F]|…)/g;
    const pins: string[] = [];
    for (const rel of listed) {
      const text = readFileSync(resolve(PKG, rel), "utf8");
      for (const m of text.matchAll(HEX)) {
        const lit = m[1]!;
        if (digests.some((d) => d.startsWith(lit))) {
          const line = text.slice(0, m.index).split("\n").length;
          pins.push(`${rel}:${line} ${lit}`);
        }
      }
    }
    /* THE ONE SANCTIONED PIN (2026-09-28, phase 3). src/test-support/golden-sample.ts declares GOLDEN_SHA, the
       digest the golden test tier was derived from. It is not "a cache that nothing invalidates": importing that
       module THROWS when the tracked sample's compiled digest differs from it, so a regenerated sample fails every
       golden test loudly instead of passing on stale expectations. It is allowed exactly there, exactly once, in
       its GOLDEN_SHA declaration, and only while that self-invalidation is present; every other file stays under
       the rule above. */
    const OWNER = "src/test-support/golden-sample.ts";
    const ownerPins = pins.filter((p) => p.startsWith(`${OWNER}:`));
    const ownerText = readFileSync(resolve(PKG, OWNER), "utf8");
    expect(ownerPins, "the golden tier's GOLDEN_SHA is the one sanctioned pin").toHaveLength(1);
    expect(ownerText).toMatch(/export const GOLDEN_SHA = "[0-9a-f]{64}";/);
    expect(ownerText, "the sanctioned pin must invalidate itself").toMatch(
      /fabric\.meta\.sourceSha256 !== GOLDEN_SHA\) \{\s*throw new Error/,
    );
    expect(
      pins.filter((p) => !p.startsWith(`${OWNER}:`)),
      "derive the tag from fabric.meta.sourceSha256 (or snapshotTag()) instead",
    ).toEqual([]);
  });
});

/* ── Every compiled data file, not the one this file was first written for ──────────────────────
 *
 * WHAT WAS WRONG. The gate above names `fabric.json` and `compile-snapshot.mjs`. A second compiler
 * (`tools/compile-acl-bindings.mjs`) writes a second sourced file (`src/forwarding/acl-bindings.json`)
 * that the forwarding engine reads as evidence, and nothing recompiled it: a hand edit to one
 * `acl_in` would have changed a trace verdict with the suite green. A gate scoped to one named file
 * stands in for the class it means.
 *
 * So the class is derived, not listed. Every `tools/compile-*.mjs` is run in its own sandbox (src/
 * directory skeleton mirrored, snapshot placed where the compiler resolves it), every file it
 * writes under src/ must be byte-identical to the shipped one, and every JSON under src/ that
 * carries `meta.sourceSha256` must be written by SOME compiler — so a new compiled file with no
 * reproducing compiler fails here instead of being silently outside the gate. */

const TOOLS = resolve(PKG, "tools");
const SRC_DIR = resolve(PKG, "src");
/** The engine contract directory (atlas-scope/contracts/): generated by the engine, imported by the compiler. */
const CONTRACTS = resolve(PKG, "contracts");

function walk(dir: string, keep: (p: string) => boolean, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, keep, out);
    else if (keep(p)) out.push(p);
  }
  return out;
}

const posix = (p: string): string => p.split("\\").join("/");

/**
 * Run ONE compiler in a fresh sandbox; return every file it wrote under src/, keyed by src-relative path.
 * With `via` "out" it compiles with --out to a directory outside src/ instead (the only way a CRLF checkout
 * compiles: see compileInSandbox) and returns what it wrote there, keyed by file name.
 */
function runCompiler(name: string, sourceBytes: Buffer, via: "tracked" | "out" = "tracked"): Map<string, Buffer> {
  const root = mkdtempSync(join(tmpdir(), "atlas-provenance-all-"));
  sandboxes.push(root);
  const pkg = join(root, "atlas-scope");
  mkdirSync(join(pkg, "tools"), { recursive: true });
  // The directory skeleton only: a compiler may assume its output directory exists, but it must
  // not find the shipped outputs there (it would then be comparing a file with itself).
  const mirror = (from: string, to: string): void => {
    mkdirSync(to, { recursive: true });
    for (const n of readdirSync(from)) {
      const p = join(from, n);
      if (statSync(p).isDirectory()) mirror(p, join(to, n));
    }
  };
  mirror(SRC_DIR, join(pkg, "src"));
  mkdirSync(dirname(join(root, meta.source)), { recursive: true });
  cpSync(join(TOOLS, name), join(pkg, "tools", name));
  // The shared modules a compiler may import (the source-binding rule lives in one; the one compiler
  // and its I/O live under lib/), never the OTHER compilers — each compiler's outputs are attributed
  // to it alone.
  for (const helper of HELPERS) cpSync(join(TOOLS, helper), join(pkg, "tools", helper), { recursive: true });
  // The engine contract (R3): DATA the one compiler imports for its evidence vocabularies — not a compiler.
  cpSync(CONTRACTS, join(pkg, "contracts"), { recursive: true });
  writeFileSync(join(root, meta.source), sourceBytes);
  const outDir = join(pkg, "compiled-out");
  execFileSync(process.execPath, [join(pkg, "tools", name), ...(via === "out" ? ["--out", outDir] : [])], { stdio: "pipe" });
  const written = new Map<string, Buffer>();
  if (via === "out") {
    for (const f of walk(outDir, () => true)) written.set(posix(relative(outDir, f)), readFileSync(f));
    expect(walk(join(pkg, "src"), () => true), `${name} --out wrote under src/`).toEqual([]);
    return written;
  }
  for (const f of walk(join(pkg, "src"), () => true)) written.set(posix(relative(join(pkg, "src"), f)), readFileSync(f));
  return written;
}

const COMPILERS = readdirSync(TOOLS).filter((f) => /^compile-.+\.mjs$/.test(f)).sort();
/* Everything in tools/ that is not a compiler: the top-level shared modules and, since 2026-09-26,
   the lib/ directory that holds the one compiler (compile-model.mjs), its validator and its I/O.
   Found by listing, not named, so a new shared module is copied into every sandbox automatically. */
const HELPERS = readdirSync(TOOLS)
  .filter((f) => !COMPILERS.includes(f) && (f.endsWith(".mjs") || statSync(join(TOOLS, f)).isDirectory()))
  .sort();

/** Every .mjs under tools/, recursively, as tools-relative POSIX paths. */
const TOOL_MODULES = walk(TOOLS, (p) => p.endsWith(".mjs")).map((p) => posix(relative(TOOLS, p))).sort();

/** The relative-import closure of one tools module (static `import`/`export … from` specifiers). */
function importClosure(rel: string): Set<string> {
  const seen = new Set<string>();
  const queue = [rel];
  while (queue.length > 0) {
    const cur = queue.pop()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    const text = readFileSync(join(TOOLS, cur), "utf8");
    for (const m of text.matchAll(/(?:import|export)\s[^;]*?from\s+["'](\.{1,2}\/[^"']+)["']/g)) {
      queue.push(posix(relative(TOOLS, resolve(dirname(join(TOOLS, cur)), m[1]!))));
    }
  }
  return seen;
}

/** Every JSON under src/ that claims a source binding — the denominator, found by content. */
const SOURCED = walk(SRC_DIR, (p) => p.endsWith(".json"))
  .filter((p) => {
    try {
      const j = JSON.parse(readFileSync(p, "utf8")) as { meta?: { sourceSha256?: unknown } };
      return typeof j.meta?.sourceSha256 === "string";
    } catch {
      return false;
    }
  })
  .map((p) => posix(relative(SRC_DIR, p)))
  .sort();

describe("every compiled data file is reproduced by its compiler from the named bytes", () => {
  const outputs = new Map<string, string>(); // src-relative path -> compiler that wrote it
  const rebuilt = new Map<string, Buffer>();

  it("finds more than one compiler and more than one sourced file (the scan is not vacuous)", () => {
    expect(COMPILERS).toContain("compile-snapshot.mjs");
    expect(COMPILERS).toContain("compile-acl-bindings.mjs");
    expect(SOURCED).toContain("data/fabric.json");
    expect(SOURCED).toContain("forwarding/acl-bindings.json");
  });

  it.each(COMPILERS)("%s writes only files that are byte-identical to the shipped ones", (name) => {
    const written = runCompiler(name, lfNormalised(readFileSync(SOURCE))); // the committed bytes (see above)
    expect(written.size, `${name} wrote nothing under src/`).toBeGreaterThan(0);
    for (const [rel, bytes] of written) {
      outputs.set(rel, name);
      rebuilt.set(rel, bytes);
      const shipped = resolve(SRC_DIR, rel);
      expect(existsSync(shipped), `${name} writes src/${rel}, which is not shipped`).toBe(true);
      expect(
        fileIsCompilerOutput(readFileSync(shipped), bytes),
        `src/${rel} is NOT what tools/${name} produces from the snapshot it names — hand-edited, or the ` +
          `compiler changed and the file was not regenerated (run \`node tools/${name}\`).`,
      ).toBe(true);
    }
  }, 120_000); // two real compiler runs in fresh sandboxes: under host contention they exceed the 30 s hang detector

  it.each(COMPILERS)("%s takes its binding from tools/source-binding.mjs and hashes nothing itself", (name) => {
    /* One rule, not N copies of it: a compiler that hashes the source on its own can drift back to
       the raw working-tree bytes without any other test noticing until a CRLF host compiles it.
       AMENDED 2026-09-26 (deliberately, and made stricter, not looser): the compilers became thin
       wrappers over tools/lib/compile-io.mjs, which is what imports source-binding.mjs. So the rule is
       now stated over the IMPORT GRAPH — every compiler must REACH source-binding.mjs — and the
       no-hashing rule covers EVERY module under tools/ except source-binding.mjs itself (the test
       below), where it used to cover only the files named compile-*.mjs. */
    const text = readFileSync(join(TOOLS, name), "utf8");
    expect(HELPERS, "the shared binding module must exist beside the compilers").toContain("source-binding.mjs");
    expect([...importClosure(name)], `tools/${name} must reach the shared binding rule through its imports`).toContain("source-binding.mjs");
    expect(text, `tools/${name} must not hash anything itself`).not.toMatch(/["']node:crypto["']|\bcreateHash\s*\(/);
    expect(text, `tools/${name} must not read the snapshot itself`).not.toMatch(/sample_fleet\.snapshot\.json["']/);
  });

  it("no module under tools/ hashes anything except tools/source-binding.mjs", () => {
    expect(TOOL_MODULES, "the walk sees the one compiler and the binding module (not vacuous)").toEqual(
      expect.arrayContaining(["lib/compile-model.mjs", "lib/compile-io.mjs", "source-binding.mjs"]),
    );
    const hashing = TOOL_MODULES.filter((rel) => /["']node:crypto["']|\bcreateHash\s*\(/.test(readFileSync(join(TOOLS, rel), "utf8")));
    expect(hashing).toEqual(["source-binding.mjs"]);
  });

  it.each(COMPILERS)("%s writes the same content from a CRLF checkout as from an LF one, apart from the byte-dependent keys (O15)", (name) => {
    const raw = readFileSync(SOURCE);
    const crlf = crlfOf(raw);
    const lf = lfNormalised(raw);
    /* Both through --out: the tracked path refuses a CRLF checkout (R3-V4, pinned in compile-all.test.ts), and
       the LF run through --out is checked below to be the very file the tracked run writes. */
    const fromCrlf = runCompiler(name, crlf, "out");
    const fromLf = runCompiler(name, lf, "out");
    expect(fromLf.size, `${name} wrote nothing`).toBeGreaterThan(0);
    expect([...fromCrlf.keys()].sort()).toEqual([...fromLf.keys()].sort());
    const tracked = runCompiler(name, lf);
    for (const [file, bytes] of fromLf) {
      expect(
        sameContentAcrossCheckouts({ out: fromCrlf.get(file)!, read: crlf }, { out: bytes, read: lf }),
        `tools/${name} writes different content in ${file} from a CRLF checkout`,
      ).toBe(true);
      const trackedTwin = [...tracked].find(([rel]) => rel.split("/").pop() === file);
      expect(trackedTwin, `${name}: the tracked run writes ${file} too`).toBeDefined();
      expect(sha256(trackedTwin![1]), `${name}: --out and the tracked run write the same ${file}`).toBe(sha256(bytes));
    }
  }, 180_000); // two real compiler runs in fresh sandboxes: under host contention they exceed the 30 s hang detector

  it("leaves no sourced file outside every compiler", () => {
    // Runs after the per-compiler tests above (vitest runs a file's tests in order).
    const orphans = SOURCED.filter((rel) => !outputs.has(rel));
    expect(orphans, `sourced JSON that no tools/compile-*.mjs reproduces: ${orphans.join(", ")}`).toEqual([]);
  });

  it("every sourced file binds the same source bytes, and those bytes are the snapshot's", () => {
    const raw = readFileSync(SOURCE);
    for (const rel of SOURCED) {
      const m = (JSON.parse(readFileSync(resolve(SRC_DIR, rel), "utf8")) as { meta: typeof meta }).meta;
      expect(sourceMatchesMeta(raw, m), `src/${rel} meta does not bind the snapshot bytes`).toBe(true);
    }
  });

  it("detects a hand-edited acl-bindings.json — the failure path, through the same gate", () => {
    /* This used to assert `sha256(tampered) !== sha256(fresh)`, which tests SHA-256 and never
       called the gate: making the per-file comparison always accept left it green (measured
       2026-09-22). Now the tampered bytes go through `fileIsCompilerOutput` — the SAME function
       the it.each above passes the shipped bytes through — with a positive control first, so a
       rejection here cannot be explained by a gate that rejects everything. */
    const shipped = readFileSync(resolve(SRC_DIR, "forwarding/acl-bindings.json"));
    const fresh = rebuilt.get("forwarding/acl-bindings.json");
    expect(fresh, "compile-acl-bindings.mjs must have run above").toBeDefined();
    expect(fileIsCompilerOutput(shipped, fresh!), "positive control: the shipped sidecar passes the gate").toBe(true);
    const tampered = Buffer.from(shipped);
    const at = tampered.indexOf(Buffer.from('"aclIn": "'));
    expect(at, "the sidecar must hold at least one observed binding to tamper with").toBeGreaterThan(0);
    const c = at + '"aclIn": "'.length;
    tampered[c] = (tampered[c] ?? 0) === 0x58 ? 0x59 : 0x58; // one character of an ACL name
    expect(tampered.byteLength).toBe(shipped.byteLength);
    expect(fileIsCompilerOutput(tampered, fresh!), "the gate ACCEPTED a hand-edited acl-bindings.json").toBe(false);
  });
});
