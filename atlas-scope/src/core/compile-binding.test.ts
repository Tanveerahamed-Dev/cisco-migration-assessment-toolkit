// @vitest-environment node
/**
 * compile-binding.test.ts — a compiled model is provably bound to the engine output it was read from.
 *
 * WHAT WAS MISSING (R3). The binding carried one digest, taken over the LF-normalised bytes. That is
 * the right form for "the same bytes on every checkout" (O15), and it is NOT the form the engine binds:
 * the engine's own receipt is `"sha256:" + sha256(<exact bytes>)` (cisco_toolkit/protocol_assurance.py,
 * `bind_snapshot_json_bytes`), so a compiled model could not be joined to an engine receipt by value.
 * Nor could it be joined to Git: nothing in `meta` named the blob the model came from, so "this model
 * was compiled from the tracked engine output at HEAD" was a claim no one could check mechanically.
 *
 * WHAT THIS PINS, against the SHIPPED files and against Git itself (not against a restatement):
 *   - every compiled file carries every binding key, and all four agree on every one of them;
 *   - `sourceGitBlob` equals `git hash-object` of the LF-normalised source and, when the source is
 *     unmodified, `git rev-parse HEAD:<source>` — Git's own answer, not this repository's;
 *   - `sourceExactSha256` is in the engine's form and equals sha256 of the bytes Git stores;
 *   - `sameSourceBinding` refuses a sidecar that differs in ANY binding key — iterated over the key
 *     list the type itself is checked against, so a new key cannot be left out of the comparison.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { bindSource } from "../../tools/source-binding.mjs";
import { bindSourceAsync, CompileError } from "../../tools/lib/compile-model.mjs";
import fabricJson from "../data/fabric.json";
import aclJson from "../forwarding/acl-bindings.json";
import ribJson from "../forwarding/rib-evidence.json";
import emissionJson from "../panels/producer-emission.json";
import { SOURCE_BINDING_BYTE_KEYS, SOURCE_BINDING_KEYS, sameSourceBinding, type SourceBinding } from "./types";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPO = resolve(PKG, "..");

const sha256 = (b: Uint8Array): string => createHash("sha256").update(b).digest("hex");
/* The LF-normalised form, restated independently of the tools (latin1 is a byte-preserving decode). */
const lf = (b: Buffer): Buffer => Buffer.from(b.toString("latin1").split("\r\n").join("\n"), "latin1");

const COMPILED: Record<string, { meta: Record<string, unknown> }> = {
  "src/data/fabric.json": fabricJson as unknown as { meta: Record<string, unknown> },
  "src/forwarding/acl-bindings.json": aclJson as unknown as { meta: Record<string, unknown> },
  "src/forwarding/rib-evidence.json": ribJson as unknown as { meta: Record<string, unknown> },
  "src/panels/producer-emission.json": emissionJson as unknown as { meta: Record<string, unknown> },
};
const fabricMeta = (fabricJson as unknown as { meta: SourceBinding }).meta;
/* The dataset under test is the one the shipped model names — not a path typed here. */
const SOURCE = resolve(REPO, fabricMeta.source);

const git = (args: string[], input?: Buffer): string =>
  execFileSync("git", args, { cwd: REPO, input, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();

describe("every compiled file carries the whole binding, and all four agree", () => {
  it("the binding key list is not empty and names the three digests", () => {
    expect(SOURCE_BINDING_KEYS).toEqual(
      expect.arrayContaining(["source", "sourceOrigin", "sourceDigestForm", "sourceSha256", "sourceBytes", "sourceExactSha256", "sourceGitBlob"]),
    );
  });

  it.each(Object.keys(COMPILED))("%s carries every binding key", (rel) => {
    const meta = COMPILED[rel]!.meta;
    const missing = SOURCE_BINDING_KEYS.filter((k) => !(k in meta));
    expect(missing, `${rel} meta lacks binding key(s)`).toEqual([]);
  });

  it("the four files bind the same bytes on every key", () => {
    for (const [rel, doc] of Object.entries(COMPILED)) {
      for (const k of SOURCE_BINDING_KEYS) expect(doc.meta[k], `${rel} ${k}`).toEqual(fabricMeta[k]);
    }
  });

  it("the tracked model is compiled from a repository file, named relatively (never an absolute path)", () => {
    expect(fabricMeta.sourceOrigin).toBe("repository-file");
    expect(fabricMeta.source).not.toMatch(/^([A-Za-z]:|[\\/])/);
    expect(fabricMeta.source).not.toContain("\\");
    expect(fabricMeta.source.split("/")).not.toContain("..");
  });
});

describe("the binding joins the model to Git and to the engine's receipt form", () => {
  const raw = readFileSync(SOURCE);
  const canonical = lf(raw);

  it("sourceGitBlob is git's blob id of the LF-normalised source (git hash-object, no filters)", () => {
    expect(fabricMeta.sourceGitBlob).toMatch(/^[0-9a-f]{40}$/);
    const byGit = git(["hash-object", "--no-filters", "--stdin"], canonical);
    expect(fabricMeta.sourceGitBlob).toBe(byGit);
  });

  it("…and, when the source is unmodified versus HEAD, the blob HEAD itself records", () => {
    const rel = fabricMeta.source;
    const dirty = spawnSync("git", ["diff", "--quiet", "HEAD", "--", rel], { cwd: REPO }).status !== 0;
    const atHead = git(["rev-parse", `HEAD:${rel}`]);
    if (dirty) {
      /* Another lane may be regenerating the sample in this working tree. The claim is then about the
         working tree, and HEAD's blob must DIFFER — anything else would mean git and the model disagree
         about what changed. Stated, not skipped. */
      expect(atHead).not.toBe(fabricMeta.sourceGitBlob);
    } else {
      expect(fabricMeta.sourceGitBlob).toBe(atHead);
    }
  });

  it("sourceExactSha256 is the engine's form (sha256: prefix) over the bytes the TRACKED model was compiled from — the committed ones", () => {
    expect(fabricMeta.sourceExactSha256).toMatch(/^sha256:[0-9a-f]{64}$/);
    /* sourceExactSha256 is sha256 of the bytes AS READ (S1-R2V-4). The tracked files are compiled from the
       committed bytes — the blob, the LF form — so for them it is the digest of the blob, on any checkout. */
    expect(fabricMeta.sourceExactSha256).toBe(`sha256:${sha256(canonical)}`);
    /* Read the stored blob back when the object database HAS it: a source regenerated and recompiled but
       not yet committed has a blob id Git computes (above: hash-object) yet does not hold, and
       `git cat-file` would fail there — the dirty-tree state the sibling test states rather than skips
       (verifier S1-V6). In that state the bytes whose blob id IS sourceGitBlob are `canonical` itself
       (proved by the hash-object test), so the claim is checked on them; either way it is checked. */
    const inObjectDb = spawnSync("git", ["cat-file", "-e", `${fabricMeta.sourceGitBlob}^{blob}`], { cwd: REPO }).status === 0;
    const stored = inObjectDb ? execFileSync("git", ["cat-file", "blob", fabricMeta.sourceGitBlob], { cwd: REPO, maxBuffer: 256 * 1024 * 1024 }) : canonical;
    expect(git(["hash-object", "--no-filters", "--stdin"], stored), "the bytes checked are the blob the model names").toBe(fabricMeta.sourceGitBlob);
    expect(`sha256:${sha256(stored)}`).toBe(fabricMeta.sourceExactSha256);
    const clean = spawnSync("git", ["diff", "--quiet", "HEAD", "--", fabricMeta.source], { cwd: REPO }).status === 0;
    if (clean) expect(inObjectDb, "an unmodified tracked source's blob is in the object database").toBe(true);
  });

  it("the LF-normalised digest and its label are unchanged (O15)", () => {
    expect(fabricMeta.sourceDigestForm).toBe("lf-normalised");
    expect(fabricMeta.sourceSha256).toBe(sha256(canonical));
    expect(fabricMeta.sourceBytes).toBe(canonical.byteLength);
  });
});

describe("the binding rule on bytes of each origin", () => {
  const golden = readFileSync(resolve(REPO, "tests", "golden", "snapshot.json"));
  const crlf = Buffer.from(lf(golden).toString("latin1").split("\n").join("\r\n"), "latin1");

  it("an external file is bound to its exact bytes, and its LF digest still matches an LF copy", () => {
    const b = bindSource(crlf, { source: "client.snapshot.json", sourceOrigin: "external-file" });
    expect(b.sourceExactSha256).toBe(`sha256:${sha256(crlf)}`);
    expect(b.sourceSha256).toBe(sha256(lf(golden)));
    expect(b.sourceGitBlob).toBe(git(["hash-object", "--no-filters", "--stdin"], lf(golden)));
  });

  it("a repository file binds the same CONTENT from a CRLF and an LF checkout; only the byte-dependent keys differ (O15)", () => {
    /* THE RULE (owner decision, R3 / verifier S1-R2V-4). sourceExactSha256 is exactly what its name says —
       sha256 of the bytes AS READ — so it is the one key that depends on the checkout's line endings; every
       other key (the LF digest, its length and form, the Git blob, the name) is the same from either
       checkout. The byte-dependent set is DERIVED here from two real bindings and must equal the declared
       SOURCE_BINDING_BYTE_KEYS, so neither can drift from the other. */
    const label = { source: "tests/golden/snapshot.json", sourceOrigin: "repository-file" } as const;
    const a = bindSource(crlf, label);
    const b = bindSource(lf(golden), label);
    const differing = SOURCE_BINDING_KEYS.filter((k) => a[k] !== b[k]);
    expect(differing).toEqual([...SOURCE_BINDING_BYTE_KEYS]);
    for (const k of SOURCE_BINDING_KEYS.filter((x) => !(SOURCE_BINDING_BYTE_KEYS as readonly string[]).includes(x))) expect(a[k], k).toEqual(b[k]);
    // …and each byte-dependent key names the bytes that were read, not the other checkout's.
    expect(a.sourceExactSha256).toBe(`sha256:${sha256(crlf)}`);
    expect(b.sourceExactSha256).toBe(`sha256:${sha256(lf(golden))}`);
  });

  it("sourceExactSha256 is sha256 of the bytes AS READ for every origin — a CRLF repository file included (S1-R2V-4)", () => {
    /* Before: a "repository-file" took its exact digest over the LF form, so on a CRLF checkout the value was
       not the sha256 of the file on disk and only restated sourceSha256. */
    for (const sourceOrigin of ["repository-file", "external-file"] as const) {
      const b = bindSource(crlf, { source: sourceOrigin === "repository-file" ? "tests/golden/snapshot.json" : "client.snapshot.json", sourceOrigin });
      expect(b.sourceExactSha256, sourceOrigin).toBe(`sha256:${sha256(crlf)}`);
      expect(b.sourceExactSha256, `${sourceOrigin}: exact is not a restatement of the LF digest`).not.toBe(`sha256:${b.sourceSha256}`);
    }
  });

  it("the AssessHub store-blob form binds the stored bytes exactly and says so", () => {
    const compact = Buffer.from(JSON.stringify(JSON.parse(golden.toString("utf8"))), "utf8");
    const b = bindSource(compact, { source: "assesshub:snapshot/7", sourceOrigin: "assesshub-store", sourceDigestForm: "assesshub-store-blob" });
    expect(b.sourceDigestForm).toBe("assesshub-store-blob");
    expect(b.sourceSha256).toBe(sha256(compact));
    expect(b.sourceExactSha256).toBe(`sha256:${sha256(compact)}`);
    expect(b.sourceBytes).toBe(compact.byteLength);
  });

  it("the browser path (WebCrypto) produces the identical binding to the Node path", async () => {
    const label = { source: "tests/golden/snapshot.json", sourceOrigin: "repository-file" } as const;
    const subtle = globalThis.crypto.subtle;
    const hex = (buf: ArrayBuffer): string => [...new Uint8Array(buf)].map((x) => x.toString(16).padStart(2, "0")).join("");
    const viaWeb = await bindSourceAsync(new Uint8Array(crlf), label, {
      sha256Hex: async (bytes) => hex(await subtle.digest("SHA-256", bytes)),
      sha1Hex: async (bytes) => hex(await subtle.digest("SHA-1", bytes)),
    });
    expect(viaWeb).toEqual(bindSource(crlf, label));
  });

  it.each([
    ["an absolute Windows path", "C:\\cases\\client.snapshot.json", "external-file"],
    ["an absolute POSIX path", "/home/someone/client.snapshot.json", "external-file"],
    ["a parent-relative path", "../client.snapshot.json", "repository-file"],
    ["a backslash path", "webapp\\sample_data\\x.json", "repository-file"],
    ["a directory in an external name", "cases/client.snapshot.json", "external-file"],
    ["an empty name", "", "external-file"],
  ] as const)("refuses %s as a source label (a path is a privacy marker)", (_why, source, sourceOrigin) => {
    let err: unknown;
    try {
      bindSource(Buffer.from("{}"), { source, sourceOrigin });
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(CompileError);
    expect((err as CompileError).code).toBe("E_SOURCE_LABEL");
  });

  it.each([
    ["a repository file in the store-blob form", "webapp/x.json", "repository-file", "assesshub-store-blob"],
    ["an external file in the store-blob form", "client.snapshot.json", "external-file", "assesshub-store-blob"],
    ["an AssessHub record in the LF-normalised form", "assesshub:snapshot/7", "assesshub-store", "lf-normalised"],
    ["an AssessHub record with no form (which defaults to LF-normalised)", "assesshub:snapshot/7", "assesshub-store", undefined],
  ] as const)("refuses %s — the digest form is tied to the origin (S1-R2V-3)", (_why, source, sourceOrigin, sourceDigestForm) => {
    /* Before: accepted. A repository file labelled "assesshub-store-blob" got sourceSha256 over the RAW CRLF
       bytes; an AssessHub record in "lf-normalised" form showed a digest that is not the store's binding. */
    let err: unknown;
    try {
      bindSource(Buffer.from('{\r\n "a": 1\r\n}\r\n'), sourceDigestForm === undefined ? { source, sourceOrigin } : { source, sourceOrigin, sourceDigestForm });
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(CompileError);
    expect((err as CompileError).code).toBe("E_SOURCE_LABEL");
  });

  it.each([
    ["repository-file", "webapp/x.json", "lf-normalised"],
    ["external-file", "client.snapshot.json", "lf-normalised"],
    ["assesshub-store", "assesshub:snapshot/7", "assesshub-store-blob"],
  ] as const)("accepts the consistent combination %s + %s (control)", (sourceOrigin, source, sourceDigestForm) => {
    expect(bindSource(Buffer.from("{}"), { source, sourceOrigin, sourceDigestForm }).sourceDigestForm).toBe(sourceDigestForm);
  });
});

describe("sameSourceBinding compares every binding key", () => {
  it.each(SOURCE_BINDING_KEYS.map((k) => [k]))("refuses a sidecar that differs only in %s", (key) => {
    expect(sameSourceBinding({ ...fabricMeta }, fabricMeta), "positive control").toBe(true);
    const bent = { ...fabricMeta, [key]: typeof fabricMeta[key] === "number" ? Number(fabricMeta[key]) + 1 : `${String(fabricMeta[key])}x` };
    expect(sameSourceBinding(bent, fabricMeta)).toBe(false);
    const dropped = Object.fromEntries(Object.entries(fabricMeta).filter(([k]) => k !== key));
    expect(sameSourceBinding(dropped, fabricMeta)).toBe(false);
  });
});
