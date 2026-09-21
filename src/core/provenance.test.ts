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
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
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

const meta = fabric.meta as {
  source: string;
  sourceBytes: number;
  sourceSha256: string;
};

const sandboxes: string[] = [];
afterAll(() => {
  for (const dir of sandboxes) rmSync(dir, { recursive: true, force: true });
});

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

  it("recomputes the displayed sha256 from the source bytes and gets the same answer", () => {
    const raw = readFileSync(SOURCE);
    expect(sha256(raw)).toBe(meta.sourceSha256);
  });

  it("recomputes the displayed byte length from the file on disk", () => {
    expect(statSync(SOURCE).size).toBe(meta.sourceBytes);
    expect(readFileSync(SOURCE).byteLength).toBe(meta.sourceBytes);
  });

  it("ships a model that is byte-identical to what the compiler produces from that source", () => {
    /* THE ASSERTION THAT MAKES THE DIGEST MEAN SOMETHING. Run in a sandbox with the same relative
       layout the compiler resolves against, so this test can never overwrite the shipped model —
       a check that rewrites its own subject would certify whatever it just wrote. */
    const root = mkdtempSync(join(tmpdir(), "atlas-provenance-"));
    sandboxes.push(root);
    mkdirSync(join(root, "atlas-scope", "tools"), { recursive: true });
    mkdirSync(join(root, "webapp", "sample_data"), { recursive: true });
    cpSync(COMPILER, join(root, "atlas-scope", "tools", "compile-snapshot.mjs"));
    cpSync(SOURCE, join(root, "webapp", "sample_data", "sample_fleet.snapshot.json"));

    execFileSync(process.execPath, [join(root, "atlas-scope", "tools", "compile-snapshot.mjs")], {
      stdio: "pipe",
    });

    const rebuilt = readFileSync(join(root, "atlas-scope", "src", "data", "fabric.json"));
    const shipped = readFileSync(MODEL);
    expect(
      sha256(rebuilt),
      "src/data/fabric.json is NOT what tools/compile-snapshot.mjs produces from the snapshot it\n" +
        "names. Either the model was edited by hand — in which case every sha256 the product\n" +
        "displays is now a claim about bytes this model did not come from — or the compiler\n" +
        `changed and the model was not regenerated. Shipped ${shipped.byteLength} bytes, rebuilt ` +
        `${rebuilt.byteLength} bytes.`,
    ).toBe(sha256(shipped));
  });

  it("detects a hand-edited model — the failure path, executed", () => {
    /* A gate whose red path never runs is not a gate. Mutate one byte of the shipped model in
       memory and confirm the comparison the test above performs would reject it. */
    const shipped = readFileSync(MODEL);
    const tampered = Buffer.from(shipped);
    const at = tampered.indexOf(Buffer.from('"devices"'));
    expect(at, "the model must contain a devices collection to tamper with").toBeGreaterThan(0);
    tampered[at + 2] = (tampered[at + 2] ?? 0) === 0x65 ? 0x66 : 0x65; // flip one character
    expect(sha256(tampered)).not.toBe(sha256(shipped));
  });

  it("is bound to bytes, not to a length: a same-size difference still fails", () => {
    // sourceBytes alone would accept any edit that preserved the length. The digest is the part
    // that does the work, and this states which of the two is load-bearing.
    const raw = readFileSync(SOURCE);
    const altered = Buffer.from(raw);
    const at = Math.floor(altered.byteLength / 2);
    altered[at] = ((altered[at] ?? 0) ^ 0x01) & 0xff;
    expect(altered.byteLength).toBe(meta.sourceBytes);
    expect(sha256(altered)).not.toBe(meta.sourceSha256);
  });
});
