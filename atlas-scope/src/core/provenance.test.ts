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
import fabric from "../data/fabric.json";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, "..", ".."); // atlas-scope/
const COMPILER = resolve(PKG, "tools", "compile-snapshot.mjs");
const MODEL = resolve(PKG, "src", "data", "fabric.json");

/* The same resolution the compiler performs, written independently: `resolve(HERE, "../../webapp/
   sample_data/sample_fleet.snapshot.json")` from `tools/`. Stated here so a change to either side
   shows up as a disagreement rather than as both moving together. */
const SOURCE = resolve(PKG, "..", "webapp", "sample_data", "sample_fleet.snapshot.json");

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

const meta = fabric.meta as {
  source: string;
  sourceBytes: number;
  sourceSha256: string;
  sourceDigestForm: string;
};

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

/** Run the real compiler in a sandbox against `sourceBytes` and return the model it writes. */
const compiled = new Map<string, Buffer>();
function compileInSandbox(sourceBytes: Buffer): Buffer {
  const key = sha256(sourceBytes);
  const hit = compiled.get(key);
  if (hit !== undefined) return hit;
  /* Same relative layout the compiler resolves against, so this can never overwrite the shipped
     model — a check that rewrites its own subject would certify whatever it just wrote. */
  const root = mkdtempSync(join(tmpdir(), "atlas-provenance-"));
  sandboxes.push(root);
  mkdirSync(join(root, "atlas-scope", "tools"), { recursive: true });
  mkdirSync(join(root, "webapp", "sample_data"), { recursive: true });
  cpSync(COMPILER, join(root, "atlas-scope", "tools", "compile-snapshot.mjs"));
  for (const helper of HELPERS) cpSync(join(TOOLS, helper), join(root, "atlas-scope", "tools", helper));
  writeFileSync(join(root, "webapp", "sample_data", "sample_fleet.snapshot.json"), sourceBytes);
  execFileSync(process.execPath, [join(root, "atlas-scope", "tools", "compile-snapshot.mjs")], { stdio: "pipe" });
  const out = readFileSync(join(root, "atlas-scope", "src", "data", "fabric.json"));
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
    // ...and the model names the same file, relatively.
    expect(meta.source).toBe("webapp/sample_data/sample_fleet.snapshot.json");
  });

  it("recomputes the displayed sha256 and byte length from the source bytes and gets the same answer", () => {
    const raw = readFileSync(SOURCE);
    expect(meta.sourceDigestForm, "meta must say which form of the bytes its digest binds").toBe(DIGEST_FORM);
    expect(sha256(lfNormalised(raw))).toBe(meta.sourceSha256);
    expect(lfNormalised(raw).byteLength).toBe(meta.sourceBytes);
    expect(statSync(SOURCE).size).toBeGreaterThanOrEqual(meta.sourceBytes); // CRLF on disk can only be longer
    expect(sourceMatchesMeta(raw, meta)).toBe(true);
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
    // And the COMPILER agrees: both checkouts compile to one byte-identical model.
    expect(sha256(compileInSandbox(crlf))).toBe(sha256(compileInSandbox(lf)));
    expect(sha256(compileInSandbox(lf))).toBe(sha256(readFileSync(MODEL)));
  });

  it("ships a model that is byte-identical to what the compiler produces from that source", () => {
    /* THE ASSERTION THAT MAKES THE DIGEST MEAN SOMETHING. */
    const shipped = readFileSync(MODEL);
    const verdict = modelIsCompilerOutput(shipped, readFileSync(SOURCE));
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
    expect(pins, "derive the tag from fabric.meta.sourceSha256 (or snapshotTag()) instead").toEqual([]);
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

function walk(dir: string, keep: (p: string) => boolean, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, keep, out);
    else if (keep(p)) out.push(p);
  }
  return out;
}

const posix = (p: string): string => p.split("\\").join("/");

/** Run ONE compiler in a fresh sandbox; return every file it wrote under src/, keyed by src-relative path. */
function runCompiler(name: string, sourceBytes: Buffer): Map<string, Buffer> {
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
  mkdirSync(join(root, "webapp", "sample_data"), { recursive: true });
  cpSync(join(TOOLS, name), join(pkg, "tools", name));
  // The shared modules a compiler may import (the source-binding rule lives in one), never the
  // OTHER compilers — each compiler's outputs are attributed to it alone.
  for (const helper of HELPERS) cpSync(join(TOOLS, helper), join(pkg, "tools", helper));
  writeFileSync(join(root, "webapp", "sample_data", "sample_fleet.snapshot.json"), sourceBytes);
  execFileSync(process.execPath, [join(pkg, "tools", name)], { stdio: "pipe" });
  const written = new Map<string, Buffer>();
  for (const f of walk(join(pkg, "src"), () => true)) written.set(posix(relative(join(pkg, "src"), f)), readFileSync(f));
  return written;
}

const COMPILERS = readdirSync(TOOLS).filter((f) => /^compile-.+\.mjs$/.test(f)).sort();
const HELPERS = readdirSync(TOOLS).filter((f) => f.endsWith(".mjs") && !COMPILERS.includes(f)).sort();

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
    const written = runCompiler(name, readFileSync(SOURCE));
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
  });

  it.each(COMPILERS)("%s takes its binding from tools/source-binding.mjs and hashes nothing itself", (name) => {
    /* One rule, not N copies of it: a compiler that hashes the source on its own can drift back to
       the raw working-tree bytes without any other test noticing until a CRLF host compiles it. */
    const text = readFileSync(join(TOOLS, name), "utf8");
    expect(HELPERS, "the shared binding module must exist beside the compilers").toContain("source-binding.mjs");
    expect(text, `tools/${name} must import the shared binding rule`).toMatch(/from\s+["']\.\/source-binding\.mjs["']/);
    expect(text, `tools/${name} must not hash anything itself`).not.toMatch(/["']node:crypto["']|\bcreateHash\s*\(/);
    expect(text, `tools/${name} must not read the snapshot itself`).not.toMatch(/sample_fleet\.snapshot\.json["']/);
  });

  it.each(COMPILERS)("%s writes the same bytes from a CRLF checkout as from an LF one (O15)", (name) => {
    const raw = readFileSync(SOURCE);
    const fromCrlf = runCompiler(name, crlfOf(raw));
    const fromLf = runCompiler(name, lfNormalised(raw));
    expect([...fromCrlf.keys()].sort()).toEqual([...fromLf.keys()].sort());
    for (const [rel, bytes] of fromLf) {
      expect(fileIsCompilerOutput(fromCrlf.get(rel)!, bytes), `tools/${name} writes a different src/${rel} from a CRLF checkout`).toBe(true);
    }
  });

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
